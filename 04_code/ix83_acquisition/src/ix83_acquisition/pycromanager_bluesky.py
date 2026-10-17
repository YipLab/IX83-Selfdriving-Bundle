"""Hardware-disconnected Ophyd bindings for planner snap plans.

The caller constructs these devices around an already-owned Core. Importing
this module does not connect to Micro-Manager. XY moves and snaps use blocking
Core calls; this adapter is for bounded step-and-snap workflows only, not
continuous capture, live speed updates, or hard real-time synchronization.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from math import isfinite
from typing import Any

import numpy as np
from planner import plans as planner_plans
from planner.bounded_scanning import SnapScanPlan
from planner.scanning import StageScanRecipe

from .interfaces import Position
from .pycromanager import PycroManagerCamera


class PycroManagerXYPositioner:
    """Bluesky movable exposing one atomic Core XY command and scalar readbacks."""

    def __init__(
        self,
        core: Any,
        *,
        xy_stage: str,
        limits_xy_um: tuple[tuple[float, float], tuple[float, float]],
        readback_tolerance_um: float,
        preflight: Callable[[], None] | None = None,
        name: str = "ix83_xy",
    ) -> None:
        if not xy_stage or not name:
            raise ValueError("stage label and Bluesky device name are required")
        if not isfinite(readback_tolerance_um) or readback_tolerance_um < 0:
            raise ValueError("readback tolerance must be finite and nonnegative")
        if len(limits_xy_um) != 2 or any(
            not isfinite(low) or not isfinite(high) or low > high for low, high in limits_xy_um
        ):
            raise ValueError("XY limits must contain two finite ordered ranges")
        self.core = core
        self.xy_stage = xy_stage
        self.limits_xy_um = limits_xy_um
        self.readback_tolerance_um = readback_tolerance_um
        self.preflight = preflight or (lambda: None)
        self.name = name
        self.parent = None
        self._closed = False
        self._motion_unresolved = False

    @property
    def motion_unresolved(self) -> bool:
        """Whether a failed Core call may have left the stage in motion."""
        return self._motion_unresolved

    def _read_xy(self) -> tuple[float, float]:
        configured = self.core.get_xy_stage_device()
        if configured != self.xy_stage:
            raise RuntimeError(f"Core XY stage is {configured!r}, expected {self.xy_stage!r}")
        position = (
            float(self.core.get_x_position(self.xy_stage)),
            float(self.core.get_y_position(self.xy_stage)),
        )
        if not all(isfinite(value) for value in position):
            raise RuntimeError("Core returned nonfinite XY readback")
        return position

    def set(self, value: tuple[float, float]) -> Any:
        """Set both axes with one Core command; completion follows readback validation."""
        from ophyd.status import DeviceStatus

        status = DeviceStatus(self, call_stop_on_failure=False)
        command_may_have_started = False
        try:
            if self._closed:
                raise RuntimeError("XY positioner is closed")
            if self._motion_unresolved:
                raise RuntimeError("reconcile the previous XY command before moving again")
            if len(value) != 2:
                raise ValueError("XY target must contain exactly two coordinates")
            x_um, y_um = float(value[0]), float(value[1])
            if not isfinite(x_um) or not isfinite(y_um):
                raise ValueError("XY target must be finite")
            for axis, target, bounds in zip(
                ("x", "y"), (x_um, y_um), self.limits_xy_um, strict=True
            ):
                if not bounds[0] <= target <= bounds[1]:
                    raise ValueError(f"{axis} target {target} µm outside limits {bounds}")
            self.preflight()
            if self.core.is_sequence_running() or self.core.get_remaining_image_count():
                raise RuntimeError("camera/Core acquisition is active or retains unread images")
            if self.core.device_busy(self.xy_stage):
                raise RuntimeError("XY stage is already busy before the requested move")
            self._read_xy()
            command_may_have_started = True
            self.core.set_xy_position(x_um, y_um)
            self.core.wait_for_device(self.xy_stage)
            if self.core.device_busy(self.xy_stage):
                raise RuntimeError("XY stage remains busy after Core wait_for_device")
            actual_x_um, actual_y_um = self._read_xy()
            if (
                abs(actual_x_um - x_um) > self.readback_tolerance_um
                or abs(actual_y_um - y_um) > self.readback_tolerance_um
            ):
                raise RuntimeError(
                    "XY readback exceeds tolerance after move; reconcile before retrying"
                )
            status.set_finished()
        except Exception as exc:
            if command_may_have_started:
                self._motion_unresolved = True
            status.set_exception(exc)
        return status

    def reconcile(self, *, timeout_s: float = 5.0) -> tuple[float, float]:
        """Observe a stable idle XY position without retrying or moving the stage.

        A successful reconciliation only establishes the current stable
        readback. It does not assert that the prior requested target was
        reached; the caller must decide whether the run can continue.
        """
        if not self._motion_unresolved:
            raise RuntimeError("there is no unresolved XY command to reconcile")
        if not isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError("reconciliation timeout must be finite and positive")
        deadline = time.monotonic() + timeout_s
        anchor: tuple[float, float] | None = None
        stable_since: float | None = None
        while time.monotonic() < deadline:
            if self.core.device_busy(self.xy_stage):
                anchor = None
                stable_since = None
            else:
                position = self._read_xy()
                if not all(
                    bounds[0] <= value <= bounds[1]
                    for value, bounds in zip(position, self.limits_xy_um, strict=True)
                ):
                    raise RuntimeError(
                        f"XY readback {position} is outside configured limits; "
                        "motion remains unresolved"
                    )
                now = time.monotonic()
                if anchor is None:
                    anchor = position
                    stable_since = now
                elif max(abs(position[i] - anchor[i]) for i in range(2)) > (
                    self.readback_tolerance_um / 4
                ):
                    anchor = position
                    stable_since = now
                elif stable_since is not None and now - stable_since >= 0.3:
                    self._motion_unresolved = False
                    return position
            time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
        raise TimeoutError(
            "XY stage did not reach a stable idle readback; motion remains unresolved"
        )

    def read(self) -> dict[str, dict[str, float]]:
        x_um, y_um = self._read_xy()
        timestamp = time.time()
        return {
            "stage_x_um": {"value": x_um, "timestamp": timestamp},
            "stage_y_um": {"value": y_um, "timestamp": timestamp},
        }

    def describe(self) -> dict[str, dict[str, Any]]:
        return {
            "stage_x_um": {
                "source": f"Micro-Manager Core XY stage {self.xy_stage}; host readback",
                "dtype": "number",
                "shape": [],
                "units": "µm",
            },
            "stage_y_um": {
                "source": f"Micro-Manager Core XY stage {self.xy_stage}; host readback",
                "dtype": "number",
                "shape": [],
                "units": "µm",
            },
        }

    def stop(self, *, success: bool = False) -> None:
        """No asynchronous stage call is outstanding after ``set`` returns."""

    def close(self) -> None:
        self._closed = True


class PycroManagerSnapDetector:
    """Triggerable/readable detector that records each snap with host-clock context."""

    def __init__(
        self,
        core: Any,
        stage: PycroManagerXYPositioner,
        *,
        z_stage: str,
        exposure_ms: float,
        shape_yx: tuple[int, int],
        dtype: str,
        configure_exposure: bool = True,
        preflight: Callable[[], None] | None = None,
        name: str = "ix83_camera",
    ) -> None:
        if not z_stage:
            raise ValueError("focus-stage label is required")
        if not isfinite(exposure_ms) or exposure_ms <= 0:
            raise ValueError("exposure must be finite and positive")
        if len(shape_yx) != 2 or min(shape_yx) < 1:
            raise ValueError("camera shape must be positive YX dimensions")
        try:
            self.dtype = np.dtype(dtype)
        except TypeError as exc:
            raise ValueError("camera dtype must be a valid NumPy dtype") from exc
        self.core = core
        self.xy_positioner = stage
        self.z_stage = z_stage
        self.exposure_ms = float(exposure_ms)
        self.configure_exposure = bool(configure_exposure)
        self.shape_yx = tuple(int(dim) for dim in shape_yx)
        self.preflight = preflight or (lambda: None)
        self.name = name
        self.parent = None
        self._camera = PycroManagerCamera(core)
        self._frame: Any | None = None
        self._stage_readback_intervals_ns: tuple[tuple[int, int], ...] | None = None
        self._closed = False

    def stage(self) -> list[PycroManagerSnapDetector]:
        if self._closed:
            raise RuntimeError("camera is closed")
        return [self]

    def unstage(self) -> list[PycroManagerSnapDetector]:
        return [self]

    def trigger(self) -> Any:
        from ophyd.status import DeviceStatus

        status = DeviceStatus(self, call_stop_on_failure=False)
        try:
            if self._closed:
                raise RuntimeError("camera is closed")
            if self.xy_positioner.motion_unresolved:
                raise RuntimeError("reconcile unresolved XY motion before acquiring frames")
            self.preflight()
            if self.core.get_remaining_image_count():
                raise RuntimeError("camera/Core retains unread images")
            if self.core.device_busy(self.xy_positioner.xy_stage):
                raise RuntimeError("XY stage is busy; refusing an unsynchronized snap")
            configured = self.core.get_xy_stage_device()
            if configured != self.xy_positioner.xy_stage:
                raise RuntimeError(
                    f"Core XY stage is {configured!r}, expected {self.xy_positioner.xy_stage!r}"
                )
            stage_x_start_ns = time.time_ns()
            x_um = float(self.core.get_x_position(self.xy_positioner.xy_stage))
            stage_x_end_ns = time.time_ns()
            stage_y_start_ns = time.time_ns()
            y_um = float(self.core.get_y_position(self.xy_positioner.xy_stage))
            stage_y_end_ns = time.time_ns()
            stage_z_start_ns = time.time_ns()
            z_um = float(self.core.get_position(self.z_stage))
            stage_z_end_ns = time.time_ns()
            if not all(isfinite(value) for value in (x_um, y_um, z_um)):
                raise RuntimeError("Core returned a nonfinite pre-snap stage readback")
            stage_position = Position(x_um, y_um, z_um)
            frame = self._camera.snap(
                stage_position=stage_position,
                exposure_ms=self.exposure_ms,
                configure_exposure=self.configure_exposure,
            )
            if frame.pixels.shape != self.shape_yx:
                raise ValueError(
                    f"camera returned shape {frame.pixels.shape}; expected {self.shape_yx}"
                )
            if frame.pixels.dtype != self.dtype:
                raise ValueError(
                    f"camera returned dtype {frame.pixels.dtype}; expected {self.dtype}"
                )
            self._frame = frame
            self._stage_readback_intervals_ns = (
                (stage_x_start_ns, stage_x_end_ns),
                (stage_y_start_ns, stage_y_end_ns),
                (stage_z_start_ns, stage_z_end_ns),
            )
            status.set_finished()
        except Exception as exc:
            status.set_exception(exc)
        return status

    def read(self) -> dict[str, dict[str, Any]]:
        if self._frame is None:
            raise RuntimeError("camera must be triggered before it is read")
        if self._stage_readback_intervals_ns is None:
            raise RuntimeError("stage readback timestamps are missing")
        frame = self._frame
        end_time = frame.acquisition_end_ns / 1e9
        x_interval, y_interval, z_interval = self._stage_readback_intervals_ns
        x_time = sum(x_interval) // 2
        y_time = sum(y_interval) // 2
        z_time = sum(z_interval) // 2
        return {
            "image": {"value": frame.pixels, "timestamp": end_time},
            "frame_id": {"value": int(frame.sequence), "timestamp": end_time},
            "exposure_ms": {"value": frame.exposure_ms, "timestamp": end_time},
            "snap_request_start_host_ns": {
                "value": int(frame.acquisition_start_ns),
                "timestamp": end_time,
            },
            "snap_result_received_host_ns": {
                "value": int(frame.acquisition_end_ns),
                "timestamp": end_time,
            },
            "stage_x_pre_snap_um": {"value": frame.stage_position.x_um, "timestamp": x_time / 1e9},
            "stage_y_pre_snap_um": {"value": frame.stage_position.y_um, "timestamp": y_time / 1e9},
            "stage_z_pre_snap_um": {"value": frame.stage_position.z_um, "timestamp": z_time / 1e9},
            "stage_x_readback_call_start_host_ns": {
                "value": x_interval[0],
                "timestamp": x_interval[0] / 1e9,
            },
            "stage_x_readback_call_end_host_ns": {
                "value": x_interval[1],
                "timestamp": x_interval[1] / 1e9,
            },
            "stage_y_readback_call_start_host_ns": {
                "value": y_interval[0],
                "timestamp": y_interval[0] / 1e9,
            },
            "stage_y_readback_call_end_host_ns": {
                "value": y_interval[1],
                "timestamp": y_interval[1] / 1e9,
            },
            "stage_z_readback_call_start_host_ns": {
                "value": z_interval[0],
                "timestamp": z_interval[0] / 1e9,
            },
            "stage_z_readback_call_end_host_ns": {
                "value": z_interval[1],
                "timestamp": z_interval[1] / 1e9,
            },
        }

    def describe(self) -> dict[str, dict[str, Any]]:
        image_description: dict[str, Any] = {
            "source": "Micro-Manager Core snap_image",
            "dtype": "array",
            "shape": list(self.shape_yx),
            "dtype_numpy": self.dtype.str,
        }
        number_fields = {
            "exposure_ms": "ms",
            "stage_x_pre_snap_um": "µm",
            "stage_y_pre_snap_um": "µm",
            "stage_z_pre_snap_um": "µm",
        }
        description = {"image": image_description}
        for key, units in number_fields.items():
            description[key] = {
                "source": "Pycro-Manager snap record",
                "dtype": "number",
                "shape": [],
                "units": units,
            }
        description["frame_id"] = {
            "source": "Pycro-Manager adapter sequence",
            "dtype": "integer",
            "shape": [],
        }
        for key in (
            "snap_request_start_host_ns",
            "snap_result_received_host_ns",
            "stage_x_readback_call_start_host_ns",
            "stage_x_readback_call_end_host_ns",
            "stage_y_readback_call_start_host_ns",
            "stage_y_readback_call_end_host_ns",
            "stage_z_readback_call_start_host_ns",
            "stage_z_readback_call_end_host_ns",
        ):
            description[key] = {
                "source": "host clock around Core.snap_image/get_tagged_image",
                "dtype": "integer",
                "shape": [],
                "units": "ns",
            }
        return description

    def stop(self, *, success: bool = False) -> None:
        """Core snap is blocking; cancellation can be handled only between exposures."""

    def close(self) -> None:
        self._closed = True
        self._camera.close()


def validate_snap_bindings(
    recipe: StageScanRecipe | SnapScanPlan,
    *,
    stage: PycroManagerXYPositioner,
    camera: PycroManagerSnapDetector,
) -> None:
    """Reject unsupported settings, resources or bounds before a plan is submitted."""
    if stage.core is not camera.core:
        raise ValueError("stage and camera must share the same caller-owned Core")
    if camera.xy_positioner is not stage:
        raise ValueError("camera and scan plan must share the same XY positioner")
    stage.preflight()
    camera.preflight()
    if stage.motion_unresolved:
        raise RuntimeError("reconcile unresolved XY motion before validating the scan")
    stage._read_xy()
    if stage.core.device_busy(stage.xy_stage):
        raise RuntimeError("XY stage must be idle before validating the scan")
    if stage.core.is_sequence_running() or stage.core.get_remaining_image_count():
        raise RuntimeError("stop Live and clear/finish camera acquisition before plan execution")
    if isinstance(recipe, StageScanRecipe):
        settings = recipe.settings
        if settings.exposure_ms != camera.exposure_ms:
            raise ValueError("recipe exposure differs from the camera binding")
        if settings.frames < 1:
            raise ValueError("recipe frame count must be positive")
        if settings.channel_id is not None:
            raise ValueError("channel selection is not configured in this snap adapter")
        if settings.roi_origin is not None or settings.binning is not None:
            raise ValueError("ROI/binning selection is not configured in this snap adapter")
        if settings.image_shape_yx is not None and settings.image_shape_yx != camera.shape_yx:
            raise ValueError("recipe image shape differs from the camera binding")
    elif not isinstance(recipe, SnapScanPlan):
        raise TypeError("recipe must be a StageScanRecipe or bounded SnapScanPlan")
    for position in recipe.positions:
        for axis, target, bounds in zip(
            ("x", "y"),
            (position.x_um, position.y_um),
            stage.limits_xy_um,
            strict=True,
        ):
            if not bounds[0] <= target <= bounds[1]:
                raise ValueError(f"recipe {axis} target {target} µm outside loaded limits {bounds}")


def validate_hand_eye_bindings(
    *,
    anchor_xy_um: tuple[float, float],
    stage: PycroManagerXYPositioner,
    camera: PycroManagerSnapDetector,
    x_probe_um: float,
    y_probe_um: float,
    mode_context: dict[str, str],
) -> None:
    """Read-only preflight for the bounded startup calibration composition."""
    if stage.core is not camera.core:
        raise ValueError("stage and camera must share the same caller-owned Core")
    if camera.xy_positioner is not stage:
        raise ValueError("camera and calibration plan must share the same XY positioner")
    if len(anchor_xy_um) != 2 or any(
        isinstance(v, bool) or not isinstance(v, (int, float)) or not isfinite(v)
        for v in anchor_xy_um
    ):
        raise ValueError("anchor must be a finite XY pair in micrometres")
    if any(
        isinstance(v, bool) or not isinstance(v, (int, float)) or not isfinite(v) or v <= 0
        for v in (x_probe_um, y_probe_um)
    ):
        raise ValueError("probe offsets must be finite and positive")
    if not mode_context or any(
        not isinstance(key, str) or not key or not isinstance(value, str) or not value
        for key, value in mode_context.items()
    ):
        raise ValueError("a nonempty loaded-profile/camera mode identity is required")
    required_mode_fields = {"profile_revision", "camera", "objective", "binning", "roi"}
    missing_mode_fields = required_mode_fields - set(mode_context)
    if missing_mode_fields:
        raise ValueError(
            "mode identity is missing required fields: " + ", ".join(sorted(missing_mode_fields))
        )
    stage.preflight()
    camera.preflight()
    if not camera.configure_exposure:
        current_exposure_ms = float(stage.core.get_exposure())
        if (
            not isfinite(current_exposure_ms)
            or abs(current_exposure_ms - camera.exposure_ms) > 1e-6
        ):
            raise ValueError(
                f"loaded exposure is {current_exposure_ms:g} ms; "
                f"read-only calibration expects {camera.exposure_ms:g} ms"
            )
    if stage.motion_unresolved:
        raise RuntimeError("reconcile unresolved XY motion before calibration")
    if stage.core.device_busy(stage.xy_stage):
        raise RuntimeError("XY stage must be idle before calibration")
    if stage.core.is_sequence_running() or stage.core.get_remaining_image_count():
        raise RuntimeError("stop Live and clear/finish camera acquisition before calibration")
    current = stage._read_xy()
    if max(abs(current[i] - anchor_xy_um[i]) for i in range(2)) > stage.readback_tolerance_um:
        raise ValueError("anchor must match the current stable stage readback")
    for axis, value, limits in zip(("x", "y"), anchor_xy_um, stage.limits_xy_um, strict=True):
        if not limits[0] <= value <= limits[1]:
            raise ValueError(f"{axis} anchor {value} µm outside loaded limits {limits}")
    if max(x_probe_um, y_probe_um) > 2_000:
        raise ValueError("probe offsets exceed the authorized ±2 mm anchor envelope")
    targets = (
        (anchor_xy_um[0] + x_probe_um, anchor_xy_um[1]),
        (anchor_xy_um[0] - x_probe_um, anchor_xy_um[1]),
        (anchor_xy_um[0], anchor_xy_um[1] + y_probe_um),
        (anchor_xy_um[0], anchor_xy_um[1] - y_probe_um),
    )
    for target in targets:
        if any(abs(target[i] - anchor_xy_um[i]) > 2_000 for i in range(2)):
            raise ValueError("probe target exceeds the authorized ±2 mm anchor envelope")
        for axis, value, limits in zip(("x", "y"), target, stage.limits_xy_um, strict=True):
            if not limits[0] <= value <= limits[1]:
                raise ValueError(f"{axis} probe target {value} µm outside loaded limits {limits}")


def pycromanager_hand_eye_calibration_plan(
    *,
    anchor_xy_um: tuple[float, float],
    stage: PycroManagerXYPositioner,
    camera: PycroManagerSnapDetector,
    coordinate_frame: str,
    mode_context: dict[str, str],
    x_probe_um: float = 10.0,
    y_probe_um: float = 10.0,
    registration_roi_yxhw_px: tuple[int, int, int, int] | None = None,
    registration_preprocessing: str = "none",
    md: dict[str, Any] | None = None,
) -> Iterable[Any]:
    """Compose planner calibration with the bounded Pycro-Manager bindings.

    Construction performs read-only identity, idle, anchor and limit checks.
    Actual movement occurs only if the returned Bluesky plan is submitted to a
    RunEngine. The host requires every requested offset to stay within ±2 mm
    of the current readback and the loaded absolute stage limits.
    """
    validate_hand_eye_bindings(
        anchor_xy_um=anchor_xy_um,
        stage=stage,
        camera=camera,
        x_probe_um=x_probe_um,
        y_probe_um=y_probe_um,
        mode_context=mode_context,
    )
    return planner_plans.hand_eye_calibration_plan(
        anchor_xy_um=anchor_xy_um,
        stage_xy=stage,
        camera=camera,
        x_probe_um=x_probe_um,
        y_probe_um=y_probe_um,
        coordinate_frame=coordinate_frame,
        mode_context=mode_context,
        registration_roi_yxhw_px=registration_roi_yxhw_px,
        registration_preprocessing=registration_preprocessing,
        readables=(stage,),
        md=md,
    )
