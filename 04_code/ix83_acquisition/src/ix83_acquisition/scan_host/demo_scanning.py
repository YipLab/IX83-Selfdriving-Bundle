"""DEMO-only execution of operator-confirmed bounded scans.

This prototype supports snap scans and two explicitly emulated broom modes.
DemoCamera broom emulation uses commanded move/readback/snap steps; no backend
claims synchronized continuous capture semantics.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Mapping
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, cast
from uuid import uuid4

from planner.bounded_scanning import BroomScanPlan, SnapScanPlan

from ix83_acquisition import MockCamera, Position, RunRecorder
from ix83_acquisition.controller import RunResult

from .scanning import ScanRun, StageScanRunner

_BROOM_RUN_LOCK = threading.Lock()


class CaptureResultError(RuntimeError):
    """A backend returned a dataset that cannot be marked completed."""

    def __init__(self, message: str, readback: Mapping[str, object]) -> None:
        super().__init__(message)
        self.readback = dict(readback)


class _ReadbackCarrier(Protocol):
    """Structural view of an error that carries the saved partial dataset."""

    readback: dict[str, object]


def _attach_readback(exc: BaseException, readback: Mapping[str, object]) -> None:
    """Attach the saved partial-capture dataset for the caller's journal.

    The runtime attribute is deliberate: the broom runner recovers a readback
    from whatever error type the device path raised.
    """
    cast(_ReadbackCarrier, exc).readback = dict(readback)


def _validate_capture_result(captured: Any) -> dict[str, object]:
    if not isinstance(captured, Mapping):
        raise TypeError("trajectory backend must return a capture-result mapping")
    result = dict(captured)
    frames = result.get("frames")
    requested = result.get("frames_requested")
    status = result.get("capture_status")
    if isinstance(frames, bool) or not isinstance(frames, int) or frames < 0:
        raise CaptureResultError("trajectory result has an invalid frame count", result)
    if requested is not None and (
        isinstance(requested, bool) or not isinstance(requested, int) or requested < 0
    ):
        raise CaptureResultError("trajectory result has an invalid requested-frame count", result)
    if requested is not None and frames != requested:
        raise CaptureResultError(
            f"trajectory returned {frames} of {requested} requested frames", result
        )
    if status == "cancelled":
        cancelled_exc = InterruptedError("trajectory backend reports cancelled capture")
        _attach_readback(cancelled_exc, result)
        raise cancelled_exc
    if status == "outcome_unknown":
        unknown_exc = TimeoutError("trajectory backend reports unknown capture outcome")
        _attach_readback(unknown_exc, result)
        raise unknown_exc
    if status is not None and status != "completed":
        raise CaptureResultError(
            f"trajectory dataset status is {status!r}, not 'completed'", result
        )
    return result


class DemoOnlyPreflight:
    """Validate an already-running MM instance without changing its state."""

    def __init__(self, core: Any) -> None:
        self.core = core

    def __call__(self) -> None:
        core = self.core
        if core.is_sequence_running() or core.get_remaining_image_count():
            raise RuntimeError("stop MMStudio Live and other acquisition clients first")
        devices = core.get_loaded_devices()
        labels = (
            [str(devices.get(i)) for i in range(devices.size())]
            if hasattr(devices, "size")
            else list(devices)
        )
        actual = {
            label: (
                str(core.get_device_library(label)),
                str(core.get_device_name(label)),
            )
            for label in labels
            if label != "Core"
        }
        if not actual or any(library != "DemoCamera" for library, _ in actual.values()):
            raise RuntimeError(
                "DEMO workflow requires every loaded device to use the DemoCamera library"
            )
        if not {"Camera", "XYStage", "ZStage"}.issubset(actual):
            raise RuntimeError("DEMO workflow requires Camera, XYStage, and ZStage device labels")
        if (
            core.get_camera_device(),
            core.get_xy_stage_device(),
            core.get_focus_device(),
        ) != ("Camera", "XYStage", "ZStage"):
            raise RuntimeError("unexpected Core camera or stage role")
        if core.get_auto_shutter() or core.get_shutter_device():
            raise RuntimeError(
                "unexpected shutter binding; DEMO workflow never changes illumination"
            )


def run_snap_plan(
    runner: StageScanRunner,
    plan: SnapScanPlan,
    *,
    specimen_id: str,
    exposure_ms: float,
    timeout_s: float = 120,
) -> ScanRun:
    """Run planned snake-grid centers through the standard durable scan runner."""
    from planner import AcquisitionSettings
    from planner.scanning import ScanPosition

    positions = tuple(
        ScanPosition(point.position_id, point.x_um, point.y_um) for point in plan.positions
    )
    run = runner.run(
        positions,
        AcquisitionSettings(exposure_ms=exposure_ms),
        specimen_id=specimen_id,
        coordinate_frame=plan.coordinate_frame,
        calibration_id="operator-confirmed-demo-boundary",
        timeout_s=timeout_s,
        return_to_origin=True,
        recipe_id="ix83-demo-bounded-snap",
        recipe_version="0.1",
    )
    run.resolved.update(
        {
            "mode": "snap",
            "footprint_xy_um": plan.footprint_xy_um,
            "overlap": plan.overlap,
            "boundary_id": plan.boundary_id,
            "coverage_claim": plan.coverage_claim,
        }
    )
    runner._save(run)
    return run


class TrajectoryMock:
    """Render time-ordered frames at positions along a virtual linear path."""

    trajectory_capture = True
    capture_mode = "trajectory-mock-emulation"
    continuous_capture = False
    resources = frozenset({"stage", "camera", "storage"})

    def __init__(
        self,
        camera: MockCamera,
        *,
        z_um: float,
        dataset_root: str | Path,
        samples_per_strip: int = 20,
        exposure_ms: float = 10,
    ) -> None:
        if samples_per_strip < 2:
            raise ValueError("trajectory needs at least two samples per strip")
        self.camera, self.z_um = camera, z_um
        self.dataset_root = Path(dataset_root)
        self.samples_per_strip, self.exposure_ms = samples_per_strip, exposure_ms

    def capture_trajectory(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
        *,
        cancelled: Callable[[], bool] = lambda: False,
        request_id: str = "broom",
    ) -> dict[str, object]:
        from dataclasses import replace

        writer = RunRecorder(
            self.dataset_root,
            request_id,
            context={"capture_mode": "trajectory-mock-emulation"},
        )
        first = None
        try:
            for index in range(self.samples_per_strip):
                if cancelled():
                    raise InterruptedError("trajectory mock cancelled")
                fraction = index / (self.samples_per_strip - 1)
                xy = (
                    start[0] + fraction * (end[0] - start[0]),
                    start[1] + fraction * (end[1] - start[1]),
                )
                frame = self.camera.snap(
                    stage_position=Position(*xy, self.z_um),
                    exposure_ms=self.exposure_ms,
                )
                frame = replace(frame, sequence=index, request_id=f"{request_id}-{index}")
                writer(frame)
                first = frame if first is None else first
            metadata = writer.finish(
                RunResult(
                    request_id,
                    "completed",
                    self.samples_per_strip,
                    frames_requested=self.samples_per_strip,
                )
            )
        except Exception as exc:
            metadata = writer.finish(
                RunResult(
                    request_id,
                    "cancelled" if isinstance(exc, InterruptedError) else "failed",
                    writer.frames_written,
                    f"{type(exc).__name__}: {exc}",
                    self.samples_per_strip,
                )
            )
            _attach_readback(
                exc,
                {
                    "dataset": str(writer.dataset_dir.resolve()),
                    "manifest": str(metadata.resolve()),
                    "frames": writer.frames_written,
                    "frames_requested": self.samples_per_strip,
                    "capture_status": "cancelled"
                    if isinstance(exc, InterruptedError)
                    else "failed",
                    "axes": "QYX",
                },
            )
            raise
        return {
            "dataset": str(writer.dataset_dir.resolve()),
            "manifest": str(metadata.resolve()),
            "frames": self.samples_per_strip,
            "frames_requested": self.samples_per_strip,
            "capture_status": "completed",
            "axes": "QYX",
            "first_stage_xy_um": [first.stage_position.x_um, first.stage_position.y_um]
            if first
            else None,
        }


class CommandedStepDemoEmulator(TrajectoryMock):
    """DemoCamera strip emulation using explicit move/readback/snap steps."""

    capture_mode = "demo-commanded-step-emulation"

    def __init__(
        self,
        camera: Any,
        stage: Any,
        *,
        dataset_root: str | Path,
        limits_xy_um: tuple[tuple[float, float], tuple[float, float]],
        samples_per_strip: int = 20,
        exposure_ms: float = 10,
        preflight: Callable[[], None] = lambda: None,
    ) -> None:
        super().__init__(
            camera,
            z_um=stage.position.z_um,
            dataset_root=dataset_root,
            samples_per_strip=samples_per_strip,
            exposure_ms=exposure_ms,
        )
        self.stage = stage
        self.limits_xy_um = limits_xy_um
        self.preflight = preflight

    def capture_trajectory(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
        *,
        cancelled: Callable[[], bool] = lambda: False,
        request_id: str = "broom",
    ) -> dict[str, object]:
        from dataclasses import replace

        from ix83_acquisition import RunRecorder
        from ix83_acquisition.controller import RunResult

        writer = RunRecorder(
            self.dataset_root,
            request_id,
            context={
                "capture_mode": self.capture_mode,
                "continuous_capture": False,
                "motion": "commanded step and snap",
            },
        )
        samples: list[dict[str, object]] = []
        try:
            for index in range(self.samples_per_strip):
                if cancelled():
                    raise InterruptedError("DEMO broom emulation cancelled between commanded steps")
                fraction = index / (self.samples_per_strip - 1)
                xy = (
                    start[0] + fraction * (end[0] - start[0]),
                    start[1] + fraction * (end[1] - start[1]),
                )
                if any(
                    not low <= coordinate <= high
                    for coordinate, (low, high) in zip(xy, self.limits_xy_um, strict=True)
                ):
                    raise ValueError("DEMO broom target exceeds confirmed boundary envelope")
                self.preflight()
                actual = self.stage.move_to(Position(*xy, self.z_um))
                if any(
                    abs(measured - expected) > 0.5 + 1e-9
                    for measured, expected in zip(
                        (actual.x_um, actual.y_um, actual.z_um),
                        (*xy, self.z_um),
                        strict=True,
                    )
                ):
                    raise TimeoutError(
                        "DEMO broom move readback differs from command by over 0.5 um"
                    )
                self.preflight()
                frame = self.camera.snap(stage_position=actual, exposure_ms=self.exposure_ms)
                frame = replace(frame, sequence=index, request_id=f"{request_id}-{index}")
                writer(frame)
                samples.append(
                    {
                        "commanded_xy_um": xy,
                        "readback_xyz_um": [actual.x_um, actual.y_um, actual.z_um],
                        "acquisition_start_ns": frame.acquisition_start_ns,
                        "acquisition_end_ns": frame.acquisition_end_ns,
                    }
                )
            metadata = writer.finish(
                RunResult(
                    request_id,
                    "completed",
                    len(samples),
                    frames_requested=self.samples_per_strip,
                )
            )
        except Exception as exc:
            metadata = writer.finish(
                RunResult(
                    request_id,
                    "cancelled" if isinstance(exc, InterruptedError) else "failed",
                    writer.frames_written,
                    f"{type(exc).__name__}: {exc}",
                    self.samples_per_strip,
                )
            )
            _attach_readback(
                exc,
                {
                    "dataset": str(writer.dataset_dir.resolve()),
                    "manifest": str(metadata.resolve()),
                    "frames": writer.frames_written,
                    "frames_requested": self.samples_per_strip,
                    "capture_status": "cancelled"
                    if isinstance(exc, InterruptedError)
                    else "failed",
                    "axes": "QYX",
                    "samples": samples,
                },
            )
            raise
        return {
            "dataset": str(writer.dataset_dir.resolve()),
            "manifest": str(metadata.resolve()),
            "frames": len(samples),
            "frames_requested": self.samples_per_strip,
            "capture_status": "completed",
            "axes": "QYX",
            "samples": samples,
        }


def _run_broom_plan_owned(
    plan: BroomScanPlan,
    *,
    backend: Any,
    journal: str | Path,
    cancelled: Callable[[], bool] = lambda: False,
    specimen_id: str = "demo-specimen",
) -> dict[str, object]:
    """Execute emulated broom strips; reject backends without explicit capture support."""
    if not getattr(backend, "trajectory_capture", False):
        raise RuntimeError(
            "broom capture unsupported: backend lacks declared capture/emulation capability"
        )
    if Path(journal).exists():
        raise FileExistsError("refusing to overwrite an existing broom journal")
    mode = str(getattr(backend, "capture_mode", "unknown"))
    run: dict[str, Any] = {
        "workflow": "ix83-demo-broom",
        "status": "running",
        "specimen_id": specimen_id,
        "geometry": asdict(plan),
        "capture_mode": mode,
        "capabilities": {
            "continuous_capture": bool(getattr(backend, "continuous_capture", False)),
            "broom_emulation": True,
        },
        "resources": sorted(getattr(backend, "resources", {"stage", "camera", "storage"})),
        "actions": [],
        "datasets": [],
    }

    def save() -> None:
        path = Path(journal)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(json.dumps(run, indent=2, allow_nan=False, default=str), encoding="utf-8")
        temp.replace(path)

    save()
    try:
        if any(
            high - low > 1000
            for low, high in (
                (
                    min(p[0] for p in plan.center_boundary_xy_um),
                    max(p[0] for p in plan.center_boundary_xy_um),
                ),
                (
                    min(p[1] for p in plan.center_boundary_xy_um),
                    max(p[1] for p in plan.center_boundary_xy_um),
                ),
            )
        ):
            raise ValueError("broom envelope must be no wider than 1 mm per XY axis")
        if any(
            high - low + plan.footprint_xy_um[axis] > 1000 + 1e-9
            for axis, (low, high) in enumerate(
                (
                    (
                        min(p[0] for p in plan.center_boundary_xy_um),
                        max(p[0] for p in plan.center_boundary_xy_um),
                    ),
                    (
                        min(p[1] for p in plan.center_boundary_xy_um),
                        max(p[1] for p in plan.center_boundary_xy_um),
                    ),
                )
            )
        ):
            raise ValueError("broom confirmed scan envelope must be no wider than 1 mm per XY axis")
        for _index, strip in enumerate(plan.strips):
            if cancelled():
                run["status"] = "cancelled"
                save()
                return run
            request_id = str(uuid4())
            action: dict[str, Any] = {
                "request_id": request_id,
                "action": "capture_trajectory",
                "status": "proposed",
                "start_xy_um": strip.start_xy_um,
                "end_xy_um": strip.end_xy_um,
                "events": [{"status": "proposed", "at": datetime.now(UTC).isoformat()}],
            }
            run["actions"].append(action)
            save()
            for action_status in ("accepted", "started"):
                action["status"] = action_status
                action["events"].append(
                    {
                        "status": action_status,
                        "at": datetime.now(UTC).isoformat(),
                    }
                )
                save()
            # The mock evaluates positions on the declared continuous path and
            # renders trajectory-timestamped frames; no physical motion occurs.
            captured = _validate_capture_result(
                backend.capture_trajectory(
                    strip.start_xy_um,
                    strip.end_xy_um,
                    cancelled=cancelled,
                    request_id=request_id,
                )
            )
            run["datasets"].append(captured)
            action["readback"] = {**captured, "trajectory": mode}
            action["status"] = "completed"
            action["events"].append(
                {
                    "status": "completed",
                    "at": datetime.now(UTC).isoformat(),
                    "readback": action["readback"],
                }
            )
            save()
        run["status"] = "completed"
    except (TimeoutError, InterruptedError) as exc:
        if run["actions"] and run["actions"][-1]["status"] == "started":
            readback = getattr(exc, "readback", None)
            if readback is not None:
                run["actions"][-1]["readback"] = readback
                run["datasets"].append(readback)
            run["actions"][-1]["status"] = (
                "outcome_unknown" if isinstance(exc, TimeoutError) else "cancelled"
            )
            run["actions"][-1]["error"] = f"{type(exc).__name__}: {exc}"
            run["actions"][-1]["events"].append(
                {
                    "status": run["actions"][-1]["status"],
                    "at": datetime.now(UTC).isoformat(),
                    "error": run["actions"][-1]["error"],
                }
            )
        run["status"] = "outcome_unknown" if isinstance(exc, TimeoutError) else "cancelled"
        run["errors"] = [str(exc)]
    except Exception as exc:  # noqa: BLE001 -- persist every partial raw-data outcome
        if run["actions"] and run["actions"][-1]["status"] == "started":
            readback = getattr(exc, "readback", None)
            if readback is not None:
                run["actions"][-1]["readback"] = readback
                run["datasets"].append(readback)
            run["actions"][-1]["status"] = "failed"
            run["actions"][-1]["error"] = f"{type(exc).__name__}: {exc}"
            run["actions"][-1]["events"].append(
                {
                    "status": "failed",
                    "at": datetime.now(UTC).isoformat(),
                    "error": run["actions"][-1]["error"],
                }
            )
        run["status"] = "failed"
        run["errors"] = [f"{type(exc).__name__}: {exc}"]
    save()
    return run


def run_broom_plan(
    plan: BroomScanPlan,
    *,
    backend: Any,
    journal: str | Path,
    cancelled: Callable[[], bool] = lambda: False,
    specimen_id: str = "demo-specimen",
) -> dict[str, object]:
    """Execute one broom plan under exclusive bundle-owned camera/stage/storage resources."""
    if not _BROOM_RUN_LOCK.acquire(blocking=False):
        raise RuntimeError("DEMO broom stage/camera/storage resources are already owned")
    try:
        return _run_broom_plan_owned(
            plan,
            backend=backend,
            journal=journal,
            cancelled=cancelled,
            specimen_id=specimen_id,
        )
    finally:
        _BROOM_RUN_LOCK.release()
