"""Bundle-owned sample-search executor; importing this module connects no devices.

Run from source with samplescout and ix83_acquisition on PYTHONPATH. Limits and
actual instrument preflight are supplied by the hosting application, not a recipe.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path
from typing import Any

from ix83_acquisition import (
    AcquisitionController,
    CaptureRequest,
    DeviceCapabilities,
    Frame,
    OMERecorder,
    Position,
    RunRecorder,
    SequenceRequest,
)
from ix83_acquisition.interfaces import Camera, SequenceCamera, XYZStage
from ix83_search_host import (
    AcquireRequest,
    AcquisitionResult,
    DataReference,
    MoveRequest,
    MoveResult,
    SearchCancelled,
)


class IX83SearchExecutor:
    """Serial bounded XY executor with fixed Z and complete per-target storage.

    The host must stop MMStudio Live and prevent other device clients. This lock
    protects callers sharing this executor, not independent MMStudio processes.
    An uncertain command forbids subsequent actions and automatic return moves.
    """

    durable_journal_required = True


    def __init__(
        self, camera: Camera, stage: XYZStage, output: Path, *,
        limits_xy_um: tuple[tuple[float, float], tuple[float, float]],
        fixed_z_um: float, tolerance_um: float = 0.5,
        preflight: Callable[[], None] = lambda: None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if not isfinite(tolerance_um) or tolerance_um <= 0 or not isfinite(fixed_z_um):
            raise ValueError("finite fixed Z and positive readback tolerance required")
        if len(limits_xy_um) != 2 or any(
            not (isfinite(low) and isfinite(high) and low <= high)
            for low, high in limits_xy_um
        ):
            raise ValueError("finite ordered XY limits required")
        self.camera, self.stage, self.output = camera, stage, output
        operations = {"stage.xy", "camera.snap", "storage.raw"}
        if isinstance(camera, SequenceCamera):
            operations.add("camera.sequence")
        self.device_capabilities = DeviceCapabilities(
            frozenset(operations), frozenset({"stage", "camera", "storage"}),
            frozenset({"exposure_ms"}))
        self.capabilities = self.device_capabilities.operations
        self.resources = self.device_capabilities.resources
        self.setting_capabilities = self.device_capabilities.settings
        self.limits_xy_um, self.fixed_z_um = limits_xy_um, fixed_z_um
        self.tolerance_um, self.preflight, self.monotonic = tolerance_um, preflight, monotonic
        self.controller = AcquisitionController(camera, stage, preview_capacity=1)
        self._lock = threading.Lock()
        self._uncertain = False
        self._closed = False
        self._expected_position = stage.position
        self._pending_writer: RunRecorder | OMERecorder | None = None
        self.datasets: list[Path] = []

    @property
    def outcome_uncertain(self) -> bool:
        return self._uncertain

    def _close_to(self, actual: Position, expected: Position) -> bool:
        return all(abs(a-b) <= self.tolerance_um + 1e-9 for a, b in zip(
            (actual.x_um, actual.y_um, actual.z_um),
            (expected.x_um, expected.y_um, expected.z_um), strict=True,
        ))

    def _guard(self, deadline: float | None) -> None:
        if self._closed or self._uncertain:
            raise RuntimeError("executor closed or previous hardware outcome requires reconciliation")
        if deadline is not None and self.monotonic() >= deadline:
            raise TimeoutError("action deadline elapsed")
        if self.controller.state != "idle":
            raise RuntimeError("acquisition worker retains device ownership")
        self.preflight()
        if not self._close_to(self.stage.position, self._expected_position):
            self._uncertain = True
            raise RuntimeError("external stage movement detected; reconcile readback before continuing")

    def move_to(
        self, request: MoveRequest,
    ) -> MoveResult:
        position_xyz_um = request.position_xyz_um
        target = Position(*position_xyz_um)
        if not all(isfinite(v) for v in position_xyz_um):
            raise ValueError("nonfinite target")
        if target.z_um != self.fixed_z_um:
            raise ValueError("this search executor permits fixed Z only")
        for value, (low, high) in zip(position_xyz_um[:2], self.limits_xy_um, strict=True):
            if not low <= value <= high:
                raise ValueError("target exceeds bundle XY envelope")
        if not self._lock.acquire(blocking=False):
            raise RuntimeError("executor resources are already owned")
        try:
            if request.control.cancelled():
                raise SearchCancelled("cancelled before stage command")
            self._guard(request.control.deadline_monotonic)
            self._uncertain = True
            actual = self.stage.move_to(target)
            if not self._close_to(actual, target):
                raise RuntimeError("stage readback exceeds centring tolerance")
            self._expected_position = actual
            if request.control.deadline_monotonic is not None and self.monotonic() > request.control.deadline_monotonic:
                raise TimeoutError("move returned after deadline; no automatic retry")
            self._uncertain = False
            return MoveResult(request.request_id, (actual.x_um, actual.y_um, actual.z_um))
        finally:
            self._lock.release()

    def acquire(
        self, request: AcquireRequest,
    ) -> AcquisitionResult:
        settings = request.settings
        if settings.channel_id is not None:
            raise ValueError("channel switching is unsupported by the loaded mixed profile")
        if settings.roi_origin is not None or settings.binning is not None:
            raise ValueError("ROI/binning changes require a separately implemented camera binding")
        if settings.frames > 1 and not isinstance(self.camera, SequenceCamera):
            raise ValueError("camera binding cannot execute native movies")
        if not self._lock.acquire(blocking=False):
            raise RuntimeError("executor resources are already owned")
        writer: RunRecorder | OMERecorder | None = None
        result: Any = None
        try:
            if request.control.cancelled():
                raise SearchCancelled("cancelled before acquisition")
            self._guard(request.control.deadline_monotonic)
            context = {"workflow_run_id": request.run_id, "recipe_id": request.recipe_id,
                       "recipe_version": request.recipe_version, "specimen_id": request.specimen_id,
                       "coordinate_frame": request.coordinate_frame, "calibration_id": request.calibration_id,
                       "phase": request.phase.value, "tile_id": request.tile_id,
                       "target_id": request.target_id, "request_id": request.request_id,
                       "settings": dict(settings.metadata)}
            writer = (OMERecorder(self.output, request.request_id, context=context)
                      if settings.frames > 1 else RunRecorder(self.output, request.request_id, context=context))
            self._pending_writer = writer
            self.datasets.append(writer.dataset_dir)
            first: list[Frame] = []

            def record(frame: Frame) -> None:
                if settings.image_shape_yx is not None and frame.pixels.shape != settings.image_shape_yx:
                    raise ValueError("camera output shape differs from recipe binding")
                if request.control.cancelled():
                    self.controller.request_stop()
                writer(frame)
                if not first:
                    first.append(frame)

            if settings.frames > 1:
                self.controller.start_sequence(SequenceRequest(
                    settings.frames, settings.exposure_ms, target_id=request.target_id,
                    request_id=request.request_id,
                ), on_frame=record)
            else:
                self.controller.start_finite([CaptureRequest(
                    exposure_ms=settings.exposure_ms, target_id=request.target_id,
                    request_id=request.request_id,
                )], on_frame=record)
            while True:
                if request.control.cancelled():
                    self.controller.request_stop()
                    result = self.controller.wait()
                    break
                deadline = request.control.deadline_monotonic
                if deadline is not None and self.monotonic() >= deadline:
                    self.controller.request_stop()
                    self._uncertain = True
                    raise TimeoutError("acquisition deadline elapsed; stop requested, outcome requires reconciliation")
                try:
                    result = self.controller.wait(0.05)
                    break
                except TimeoutError:
                    continue
            self._uncertain = result.state != "completed"
            if isinstance(writer, OMERecorder):
                final = writer.finish(result)
            else:
                writer.finish(result)
                final = result
            dataset = self._dataset_reference(writer, final.state)
            if final.state == "cancelled":
                self._uncertain = False
                raise SearchCancelled("acquisition cancelled after retaining its captured prefix",
                                       dataset=dataset)
            if final.state != "completed":
                raise RuntimeError(final.error or "acquisition did not complete")
            self._uncertain = False
            if final.state != "completed" or final.frames_acquired != settings.frames or not first:
                raise RuntimeError(f"incomplete acquisition: {final}")
            if request.control.deadline_monotonic is not None and self.monotonic() > request.control.deadline_monotonic:
                raise TimeoutError("acquisition/storage completed after deadline")
            frame = first[0]
            return AcquisitionResult(
                request_id=request.request_id, run_id=request.run_id,
                specimen_id=request.specimen_id, phase=request.phase,
                coordinate_frame=request.coordinate_frame, calibration_id=request.calibration_id,
                tile_id=request.tile_id,
                image=frame.pixels,
                stage_xy_um=(frame.stage_position.x_um, frame.stage_position.y_um),
                acquired_at=datetime.fromtimestamp(frame.acquisition_end_ns / 1e9, timezone.utc),
                dataset=dataset,
            )
        finally:
            if writer is not None and result is not None:
                writer.close()
                self._pending_writer = None
            self._lock.release()

    @staticmethod
    def _dataset_reference(writer: RunRecorder | OMERecorder, terminal: str) -> DataReference:
        metadata_path = writer.dataset_dir / "run_metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        ledger = writer.dataset_dir / "frames.jsonl"
        with ledger.open(encoding="utf-8") as stream:
            next(stream)
            first = json.loads(next(stream)) if metadata["frames_written"] else None
        is_ome = metadata.get("format") == "ome-tiff"
        shape = tuple(first["shape"]) if first else (0, 0)
        if is_ome:
            axes = "TYX"
            shape = (metadata["frames_written"], *shape)
            dtype = first["dtype"] if first else "unknown"
        else:
            axes = "QYX"
            shape = (metadata["frames_written"], *shape)
            dtype = first["dtype"] if first else "unknown"
        return DataReference(writer.dataset_dir.resolve().as_uri(),
            "ome-tiff" if is_ome else "npy-frames", axes, shape, dtype,
            int(metadata["frames_written"]), terminal,
            hashlib.sha256(metadata_path.read_bytes()).hexdigest())

    def close(self, timeout: float = 15) -> None:
        """Stop/wait before closing a writer; never automatically move hardware."""
        if not self._lock.acquire(blocking=False):
            raise RuntimeError("executor action is still active")
        try:
            self.controller.close(timeout)
            if self._pending_writer is not None:
                result = self.controller.wait(timeout)
                self._pending_writer.finish(result)
                self._pending_writer.close()
                self._pending_writer = None
            self._closed = True
        finally:
            self._lock.release()
