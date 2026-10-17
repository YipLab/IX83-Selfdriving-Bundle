"""Optional low-level Pycro-Manager Core adapters.

This module imports Pycro-Manager lazily and never starts Micro-Manager or
connects to hardware by being imported. Construct adapters only in an explicitly
configured application after the operator has selected the intended devices.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from math import isfinite
from typing import Any

import numpy as np

from .interfaces import Channel, Frame, Position


@dataclass(frozen=True)
class SequenceStatus:
    requested: int
    received: int
    overflowed: bool
    unread_at_cleanup: int
    cancelled: bool


class PycroManagerCamera:
    """Snap images through a caller-owned Pycro-Manager Core."""

    def __init__(
        self, core: Any, channel_group: str | None = None, channel: str | None = None
    ) -> None:
        self.core = core
        self.channel_group = channel_group
        self.channel = channel
        self.sequence = 0
        self._closed = False
        self.last_sequence_status: SequenceStatus | None = None

    def snap(
        self,
        *,
        stage_position: Position,
        exposure_ms: float,
        channel: Channel | None = None,
        configure_exposure: bool = True,
    ) -> Frame:
        if self._closed:
            raise RuntimeError("camera is closed")
        if not isfinite(exposure_ms) or exposure_ms <= 0:
            raise ValueError("exposure must be positive and finite")
        if self.core.is_sequence_running():
            raise RuntimeError("Stop MMStudio Live before acquiring from this camera")
        selected = channel
        if selected is None and self.channel_group and self.channel:
            selected = Channel(self.channel_group, self.channel)
        if selected is not None:
            self.core.set_config(selected.group, selected.preset)
            self.core.wait_for_config(selected.group, selected.preset)
        if configure_exposure:
            self.core.set_exposure(exposure_ms)
            actual_exposure_ms = float(exposure_ms)
        else:
            actual_exposure_ms = float(self.core.get_exposure())
            if not isfinite(actual_exposure_ms) or abs(actual_exposure_ms - exposure_ms) > 1e-6:
                raise RuntimeError(
                    f"current exposure is {actual_exposure_ms:g} ms; "
                    f"requested read-only exposure is {exposure_ms:g} ms"
                )
        started_ns = time.time_ns()
        self.core.snap_image()
        tagged = self.core.get_tagged_image()
        height, width = int(tagged.tags["Height"]), int(tagged.tags["Width"])
        pixels = np.asarray(tagged.pix).reshape(height, width).copy()
        frame = Frame(
            pixels,
            stage_position,
            self.sequence,
            actual_exposure_ms,
            started_ns,
            time.time_ns(),
            selected,
        )
        self.sequence += 1
        return frame

    def close(self) -> None:
        # The host owns Core and Micro-Manager owns the physical device lifecycle.
        self._closed = True

    def stream_sequence(
        self,
        *,
        frames: int,
        exposure_ms: float,
        stage_position: Position,
        stop_requested: Callable[[], bool],
        channel: Channel | None = None,
        timeout_s: float = 10,
    ) -> Iterator[Frame]:
        """Drain a native fixed-channel sequence, stopping on overflow.

        The interval argument to Core is unused. Exposure is explicitly selected;
        the caller must characterize actual camera cadence rather than infer it.
        Native IDs must be contiguous. Camera production stops on cancellation,
        followed by draining the captured prefix. Callback failure closes this
        generator; unread Core frames are reported and cleared after stopping.
        """
        if self._closed:
            raise RuntimeError("camera is closed")
        if frames < 1 or not isfinite(exposure_ms) or exposure_ms <= 0:
            raise ValueError("invalid sequence frame count or exposure")
        if not isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError("invalid sequence timeout")
        if stop_requested():
            return
        if self.core.is_sequence_running() or self.core.get_remaining_image_count():
            raise RuntimeError("camera or Core buffer is already owned by another acquisition")
        selected = channel
        if selected is None and self.channel_group and self.channel:
            selected = Channel(self.channel_group, self.channel)
        if selected is not None:
            self.core.set_config(selected.group, selected.preset)
            self.core.wait_for_config(selected.group, selected.preset)
        self.core.set_exposure(exposure_ms)
        self.core.initialize_circular_buffer()
        received = 0
        previous_core: int | None = None
        previous_camera: int | None = None
        overflowed = False
        cancelled = False
        last_progress = time.monotonic()
        try:
            # Include start in cleanup scope: an RPC timeout does not establish
            # that the camera failed to start.
            self.core.start_sequence_acquisition(frames, 0.0, True)
            while True:
                if stop_requested() and not cancelled:
                    self.core.stop_sequence_acquisition()
                    cancelled = True
                remaining = self.core.get_remaining_image_count()
                running = self.core.is_sequence_running()
                if remaining:
                    started = time.time_ns()
                    tagged = self.core.pop_next_tagged_image()
                    core_number = int(tagged.tags["ImageNumber"])
                    camera_number = (
                        int(tagged.tags["PVCAM-FrameNr"])
                        if "PVCAM-FrameNr" in tagged.tags
                        else None
                    )
                    if previous_core is None and core_number != 0:
                        raise RuntimeError(
                            f"sequence starts with missing Core frames: {core_number}"
                        )
                    if received == 0 and camera_number is not None and camera_number != 1:
                        raise RuntimeError(
                            f"sequence starts with missing PVCAM frames: {camera_number}"
                        )
                    if previous_core is not None and core_number != previous_core + 1:
                        raise RuntimeError(
                            f"Core frame gap or duplicate: {previous_core} -> {core_number}"
                        )
                    if previous_camera is not None and camera_number != previous_camera + 1:
                        raise RuntimeError(
                            f"camera frame gap or duplicate: {previous_camera} -> {camera_number}"
                        )
                    if received >= frames:
                        raise RuntimeError("camera returned more frames than requested")
                    previous_core, previous_camera = core_number, camera_number
                    pixels = (
                        np.asarray(tagged.pix)
                        .reshape(int(tagged.tags["Height"]), int(tagged.tags["Width"]))
                        .copy()
                    )
                    timestamp = (
                        float(tagged.tags["TimeStampMsec"])
                        if "TimeStampMsec" in tagged.tags
                        else None
                    )
                    frame = Frame(
                        pixels,
                        stage_position,
                        received,
                        exposure_ms,
                        started,
                        time.time_ns(),
                        selected,
                        core_image_number=core_number,
                        camera_frame_number=camera_number,
                        source_timestamp_ms=timestamp,
                    )
                    received += 1
                    last_progress = time.monotonic()
                    yield frame
                elif not running and self.core.get_remaining_image_count() == 0:
                    break
                else:
                    time.sleep(0.001)
                if time.monotonic() - last_progress > timeout_s:
                    raise TimeoutError("camera sequence stalled")
            overflowed = bool(self.core.is_buffer_overflowed())
            if overflowed:
                raise RuntimeError(f"Core buffer overflow: {received}/{frames} received")
            if not cancelled and received != frames:
                raise RuntimeError(f"incomplete camera sequence: {received}/{frames}")
        finally:
            self.core.stop_sequence_acquisition()
            unread = int(self.core.get_remaining_image_count())
            overflowed = overflowed or bool(self.core.is_buffer_overflowed())
            self.last_sequence_status = SequenceStatus(
                frames, received, overflowed, unread, cancelled
            )
            if unread:
                self.core.clear_circular_buffer()


class PycroManagerXYZStage:
    """Absolute XYZ motion through a caller-owned Core and explicit stage labels."""

    def __init__(
        self,
        core: Any,
        *,
        xy_stage: str,
        z_stage: str,
        limits_um: tuple[tuple[float, float], tuple[float, float], tuple[float, float]]
        | None = None,
    ) -> None:
        if limits_um is not None:
            for low, high in limits_um:
                if not (isfinite(low) and isfinite(high) and low <= high):
                    raise ValueError("stage limits must be finite and ordered")
        self.core = core
        self.xy_stage = xy_stage
        self.z_stage = z_stage
        self.limits_um = limits_um
        self._closed = False

    @property
    def position(self) -> Position:
        configured_xy = self.core.get_xy_stage_device()
        if configured_xy != self.xy_stage:
            raise RuntimeError(f"Core XY stage is {configured_xy!r}, expected {self.xy_stage!r}")
        # Java Core returns a Point2D from get_xy_stage_position, not a tuple.
        # Scalar readbacks also work with the Pycro-Manager Java bridge.
        x_um = self.core.get_x_position(self.xy_stage)
        y_um = self.core.get_y_position(self.xy_stage)
        z_um = self.core.get_position(self.z_stage)
        return Position(float(x_um), float(y_um), float(z_um))

    def move_to(self, position: Position) -> Position:
        if self._closed:
            raise RuntimeError("stage is closed")
        if not all(isfinite(value) for value in (position.x_um, position.y_um, position.z_um)):
            raise ValueError("stage positions must be finite")
        if self.limits_um is not None:
            for axis, value, bounds in zip(
                "xyz", (position.x_um, position.y_um, position.z_um), self.limits_um, strict=True
            ):
                if not bounds[0] <= value <= bounds[1]:
                    raise ValueError(f"{axis} target {value} um outside stage limits {bounds}")
        configured_xy = self.core.get_xy_stage_device()
        if configured_xy != self.xy_stage:
            raise RuntimeError(f"Core XY stage is {configured_xy!r}, expected {self.xy_stage!r}")
        self.core.set_xy_position(position.x_um, position.y_um)
        self.core.set_position(self.z_stage, position.z_um)
        self.core.wait_for_device(self.xy_stage)
        self.core.wait_for_device(self.z_stage)
        return self.position

    def close(self) -> None:
        # The host owns Core and Micro-Manager owns the physical device lifecycle.
        self._closed = True


def connect_core(**kwargs: Any) -> Any:
    """Explicitly connect to a running Micro-Manager instance on request."""
    try:
        from pycromanager import Core
    except ImportError as exc:
        raise RuntimeError("Install the optional pycromanager dependency to connect") from exc
    return Core(**kwargs)
