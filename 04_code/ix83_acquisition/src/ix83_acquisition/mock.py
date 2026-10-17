"""Deterministic, hardware-free XYZ stage and stage-aware camera."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from math import isfinite

import numpy as np

from .interfaces import Channel, Frame, Position


class MockXYZStage:
    """In-memory XYZ stage with configurable travel limits and move history."""

    def __init__(
        self,
        position: Position | None = None,
        limits_um: tuple[tuple[float, float], tuple[float, float], tuple[float, float]]
        | None = None,
    ) -> None:
        self._position = position or Position(0.0, 0.0, 0.0)
        self.limits_um = limits_um
        self.history = [self._position]
        self._closed = False

    @property
    def position(self) -> Position:
        return self._position

    def move_to(self, position: Position) -> Position:
        if self._closed:
            raise RuntimeError("stage is closed")
        if not all(isfinite(value) for value in (position.x_um, position.y_um, position.z_um)):
            raise ValueError("stage positions must be finite")
        if self.limits_um is not None:
            for axis, value, limits in zip(
                "xyz", (position.x_um, position.y_um, position.z_um), self.limits_um, strict=True
            ):
                if not limits[0] <= value <= limits[1]:
                    raise ValueError(f"{axis} position {value} um outside mock limits {limits}")
        self._position = position
        self.history.append(position)
        return position

    def close(self) -> None:
        self._closed = True


class MockCamera:
    """Render seeded fluorescent spots fixed in specimen coordinates.

    Spot locations and stage coordinates use micrometres. The configured pixel
    size and image shape define a centered field of view, so moving the mock
    stage moves specimen features predictably across the image.
    """

    def __init__(
        self,
        *,
        shape_yx: tuple[int, int] = (256, 256),
        pixel_size_um: float = 0.25,
        specimen_spots_um: tuple[tuple[float, float], ...] = (
            (0.0, 0.0),
            (20.0, 15.0),
            (-30.0, 25.0),
        ),
        seed: int = 0,
        read_noise: float = 2.0,
    ) -> None:
        if min(shape_yx) < 1 or pixel_size_um <= 0 or read_noise < 0:
            raise ValueError(
                "image dimensions and pixel size must be positive; noise must be nonnegative"
            )
        self.shape_yx = shape_yx
        self.pixel_size_um = pixel_size_um
        self.specimen_spots_um = specimen_spots_um
        self.rng = np.random.default_rng(seed)
        self.read_noise = read_noise
        self.sequence = 0
        self._closed = False

    def snap(
        self, *, stage_position: Position, exposure_ms: float, channel: Channel | None = None
    ) -> Frame:
        if self._closed:
            raise RuntimeError("camera is closed")
        if not isfinite(exposure_ms) or exposure_ms <= 0:
            raise ValueError("exposure must be positive")
        started_ns = time.time_ns()
        height, width = self.shape_yx
        yy, xx = np.mgrid[:height, :width]
        pixels = self.rng.normal(20.0, self.read_noise, self.shape_yx)
        center_x, center_y = (width - 1) / 2, (height - 1) / 2
        scale = exposure_ms / 10.0
        for spot_x, spot_y in self.specimen_spots_um:
            x = center_x + (spot_x - stage_position.x_um) / self.pixel_size_um
            y = center_y + (spot_y - stage_position.y_um) / self.pixel_size_um
            pixels += 1500.0 * scale * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / 4.5)
        image = np.clip(pixels, 0, np.iinfo(np.uint16).max).astype(np.uint16)
        frame = Frame(
            image, stage_position, self.sequence, exposure_ms, started_ns, time.time_ns(), channel
        )
        self.sequence += 1
        return frame

    def close(self) -> None:
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
        """Exposure-paced mock sequence with deterministic native frame IDs."""
        from dataclasses import replace

        started = time.monotonic()
        for index in range(frames):
            deadline = started + index * exposure_ms / 1000
            while time.monotonic() < deadline:
                if stop_requested():
                    return
                time.sleep(min(0.001, max(0, deadline - time.monotonic())))
            if stop_requested():
                return
            yield replace(
                self.snap(stage_position=stage_position, exposure_ms=exposure_ms, channel=channel),
                core_image_number=index,
                camera_frame_number=index + 1,
                source_timestamp_ms=index * exposure_ms,
            )
