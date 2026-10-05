"""Explicit stage-coordinate scans inspired by the AutoScanJ procedure.

This is an original implementation. Grid spacing is commanded micrometres,
not an inferred optical calibration or claim of contiguous specimen coverage.
"""
from __future__ import annotations

import json
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path
from uuid import uuid4

from samplescout.contracts import (
    AcquisitionSettings,
    ActionRecord,
    ActionStatus,
    ExecutionBindingSnapshot,
    Phase,
    ResourceRequirement,
    RunStatus,
)
from samplescout.records import to_record_value
from samplescout.scanning import ScanPosition, StageScanRecipe

from .binding import required_settings, validate_binding
from .contracts import (
    AcquireRequest,
    AcquisitionResult,
    ExecutionControl,
    MoveRequest,
    MoveResult,
    SearchBackend,
)
from .dataset import validate_dataset_reference
from .runner import SearchCancelled


@dataclass
class ScanRun:
    run_id: str = field(default_factory=lambda: str(uuid4()))
    status: RunStatus = RunStatus.RUNNING
    execution_bindings: tuple[ExecutionBindingSnapshot, ...] = ()
    positions: list[dict[str, object]] = field(default_factory=list)
    actions: list[ActionRecord] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    resolved: dict[str, object] = field(default_factory=dict)


class ScanCancelled(Exception):
    pass


class StageScanRunner:
    """Move/wait/settle/acquire with a persisted journal and known-outcome cleanup.

    Device waits and exclusive ownership belong to the backend. The runner
    validates every target before commanding anything, and never retries an
    uncertain physical action. A journal is evidence, not automatic recovery.
    """

    def __init__(self, backend: SearchBackend, *, limits_xy_um: tuple[tuple[float, float], tuple[float, float]],
                 fixed_z_um: float, origin_xy_um: tuple[float, float], journal: str | Path,
                 cancelled: Callable[[], bool] = lambda: False,
                 monotonic: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.backend, self.limits = backend, limits_xy_um
        self.fixed_z, self.origin, self.journal = fixed_z_um, origin_xy_um, Path(journal)
        self.cancelled, self.monotonic, self.sleep = cancelled, monotonic, sleep
        if not isfinite(fixed_z_um) or len(limits_xy_um) != 2:
            raise ValueError("finite fixed Z and XY limits required")
        for low, high in limits_xy_um:
            if not all(isfinite(v) for v in (low, high)) or not 0 <= high - low <= 1000:
                raise ValueError("each XY envelope must be ordered and at most 1 mm wide")
        self._validate_xy(*origin_xy_um)

    def _validate_xy(self, x: float, y: float) -> None:
        if not all(isfinite(v) and low <= v <= high for v, (low, high) in zip((x, y), self.limits, strict=True)):
            raise ValueError("scan position exceeds finite bundle XY envelope")

    def _save(self, run: ScanRun) -> None:
        self.journal.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.journal.with_suffix(self.journal.suffix + ".tmp")
        temporary.write_text(json.dumps(to_record_value(asdict(run)), indent=2, allow_nan=False), encoding="utf-8")
        temporary.replace(self.journal)

    def _append_action(self, run: ScanRun, request_id: str, action: str, status: ActionStatus,
                       phase: Phase, started_at: datetime, parameters: dict[str, object], *,
                       finished_at: datetime | None = None, readback: object = None,
                       error: str | None = None) -> None:
        run.actions.append(ActionRecord(request_id, action, status, phase, started_at,
                                        finished_at, parameters, readback, error))
        self._save(run)

    def _check(self, deadline: float) -> None:
        if self.cancelled():
            raise ScanCancelled()
        if self.monotonic() >= deadline:
            raise RuntimeError("scan deadline expired before next command")

    def _action(self, run: ScanRun, name: str, parameters: dict[str, object],
                call: Callable[[str], object], phase: Phase) -> tuple[str, object]:
        request_id = str(uuid4())
        started_at = datetime.now(timezone.utc)
        for status in (ActionStatus.PROPOSED, ActionStatus.ACCEPTED, ActionStatus.STARTED):
            self._append_action(run, request_id, name, status, phase, started_at, parameters)
        try:
            result = call(request_id)
        except SearchCancelled as exc:
            cancellation_readback = None
            if exc.dataset is not None:
                cancellation_readback = {"dataset": to_record_value(exc.dataset)}
            self._append_action(run, request_id, name, ActionStatus.CANCELLED, phase,
                                started_at, parameters, finished_at=datetime.now(timezone.utc),
                                readback=cancellation_readback)
            raise
        except Exception as exc:
            status = (ActionStatus.OUTCOME_UNKNOWN if isinstance(exc, TimeoutError) or getattr(
                self.backend, "outcome_uncertain", False) else ActionStatus.FAILED)
            self._append_action(run, request_id, name, status, phase, started_at, parameters,
                                finished_at=datetime.now(timezone.utc),
                                error=f"{type(exc).__name__}: {exc}")
            raise
        readback: object = to_record_value(result)
        if isinstance(result, AcquisitionResult):
            readback = {"stage_xy_um": result.stage_xy_um,
                        "acquired_at": result.acquired_at.isoformat(),
                        "data_reference": to_record_value(result.dataset),
                        "axes": result.image_axes,
                        "image_shape": getattr(result.image, "shape", None)}
        self._append_action(run, request_id, name, ActionStatus.COMPLETED, phase, started_at,
                            parameters, finished_at=datetime.now(timezone.utc), readback=readback)
        return request_id, result

    def _move(self, run: ScanRun, request_id: str, xy: tuple[float, float], deadline: float) -> object:
        resolved = run.resolved
        request = MoveRequest(request_id, run.run_id, str(resolved["procedure"]),
            str(resolved["version"]), str(resolved["specimen_id"]), Phase(str(resolved["phase"])),
            str(resolved["coordinate_frame"]), str(resolved["calibration_id"]),
            (*xy, self.fixed_z), "scan-move", control=ExecutionControl(
                cancelled=self.cancelled, deadline_monotonic=deadline))
        result = self.backend.move_to(request)
        if not isinstance(result, MoveResult) or result.request_id != request_id:
            raise TypeError("backend.move_to must return a matching MoveResult")
        actual = result.stage_xyz_um
        if not isinstance(actual, (tuple, list)) or len(actual) != 3 or not all(
            isinstance(v, (float, int)) and isfinite(v) and abs(v - expected) <= 0.5 + 1e-9
            for v, expected in zip(actual, (*xy, self.fixed_z), strict=True)
        ):
            raise TimeoutError("stage move has no verified XYZ readback within 0.5 um")
        return actual

    def run(self, positions: Sequence[ScanPosition], settings: AcquisitionSettings, *,
            specimen_id: str, coordinate_frame: str = "stage-xy",
            calibration_id: str = "uncalibrated-stage-scan", phase: Phase = Phase.SURVEY,
            settle_ms: float = 0, timeout_s: float = 120, return_to_origin: bool = True,
            recipe_id: str = "stage-scan", recipe_version: str = "0.1-local",
            resources: Sequence[ResourceRequirement] = (
                ResourceRequirement("stage"), ResourceRequirement("camera"),
                ResourceRequirement("storage"),
            )) -> ScanRun:
        if self.journal.exists():
            raise FileExistsError("refusing to overwrite an existing scan journal")
        if not positions or len(positions) > 10000 or len({p.position_id for p in positions}) != len(positions):
            raise ValueError("1–10000 uniquely identified positions required")
        if not specimen_id or not coordinate_frame or not calibration_id:
            raise ValueError("specimen and coordinate context required")
        if not isfinite(settle_ms) or settle_ms < 0 or not isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError("nonnegative settling and positive deadline required")
        if settings.channel_id is not None or settings.roi_origin is not None or settings.binning is not None:
            raise ValueError("scanner preserves the loaded channel, ROI and binning")
        for position in positions:
            self._validate_xy(position.x_um, position.y_um)
        required = {"stage.xy", "camera.snap", "storage.raw"}
        if settings.frames > 1:
            required.add("camera.sequence")
        binding = validate_binding(self.backend, capabilities=required, resources=resources,
                                   settings=(settings,))
        run = ScanRun(resolved={"procedure": recipe_id, "version": recipe_version,
            "specimen_id": specimen_id, "coordinate_frame": coordinate_frame,
            "calibration_id": calibration_id, "phase": phase.value, "settings": asdict(settings),
            "requirements": {"capabilities": sorted(required),
                             "resources": [asdict(requirement) for requirement in resources],
                             "settings": sorted(required_settings((settings,)))},
            "origin_xy_um": self.origin, "fixed_z_um": self.fixed_z, "limits_xy_um": self.limits,
            "settle_ms": settle_ms, "timeout_s": timeout_s, "return_to_origin": return_to_origin,
            "planned_positions": [asdict(p) for p in positions]},
            execution_bindings=(binding,))
        self._save(run)
        deadline = self.monotonic() + timeout_s
        try:
            for position in positions:
                self._check(deadline)
                def move(request_id: str, position: ScanPosition = position) -> object:
                    return self._move(run, request_id, (position.x_um, position.y_um), deadline)
                self._action(run, "move_to", asdict(position), move, phase)
                settled = self.monotonic() + settle_ms / 1000
                while self.monotonic() < settled:
                    self._check(deadline)
                    self.sleep(max(0, min(0.05, settled - self.monotonic())))
                self._check(deadline)
                def acquire(request_id: str, position: ScanPosition = position) -> AcquisitionResult:
                    return self.backend.acquire(AcquireRequest(request_id, run.run_id,
                        recipe_id, recipe_version, specimen_id, phase, coordinate_frame,
                        calibration_id, position.position_id, settings,
                        position.position_id if phase is Phase.REVISIT else None,
                        ExecutionControl(cancelled=self.cancelled,
                                         deadline_monotonic=deadline)))
                acquire_id, result = self._action(
                    run, "acquire", {"position_id": position.position_id}, acquire, phase
                )
                if not isinstance(result, AcquisitionResult) or result.image is None:
                    raise RuntimeError("scan acquisition has no recorded image")
                if (result.run_id, result.request_id, result.tile_id, result.phase) != (
                    run.run_id, acquire_id, position.position_id, phase
                ):
                    raise ValueError("scan acquisition result context does not match request")
                if (result.specimen_id, result.coordinate_frame, result.calibration_id) != (
                    specimen_id, coordinate_frame, calibration_id
                ):
                    raise ValueError("scan acquisition context does not match recipe")
                if result.image_axes != ("Y", "X"):
                    raise ValueError("scan image axes must be YX")
                if result.acquired_at.tzinfo is None:
                    raise ValueError("scan acquisition timestamp must be timezone-aware")
                actual_shape = tuple(int(size) for size in result.image.shape[:2])
                if len(actual_shape) != 2:
                    raise ValueError("scan acquisition image must have YX dimensions")
                if settings.image_shape_yx is not None and actual_shape != settings.image_shape_yx:
                    raise ValueError("scan image shape does not match acquisition settings")
                dataset_reference = validate_dataset_reference(result.dataset, settings, actual_shape)
                self._validate_xy(*result.stage_xy_um)
                if any(abs(a - b) > 0.5 + 1e-9 for a, b in zip(
                    result.stage_xy_um, (position.x_um, position.y_um), strict=True
                )):
                    raise TimeoutError("exposure-associated stage readback disagrees with commanded position")
                run.positions.append({**asdict(position), "stage_xy_um": result.stage_xy_um,
                    "acquired_at": result.acquired_at.isoformat(), "axes": dataset_reference.axes,
                    "data_reference": asdict(dataset_reference)})
                self._save(run)
            run.status = RunStatus.COMPLETED
        except (ScanCancelled, SearchCancelled):
            run.status = RunStatus.CANCELLED
        except Exception as exc:  # noqa: BLE001 -- Persist every host action failure before returning.
            run.status = RunStatus.OUTCOME_UNKNOWN if isinstance(exc, TimeoutError) or getattr(
                self.backend, "outcome_uncertain", False) else RunStatus.FAILED
            run.errors.append(f"{type(exc).__name__}: {exc}")
        # Failure/unknown runs retain their position for operator reconciliation.
        if return_to_origin and run.status in (RunStatus.COMPLETED, RunStatus.CANCELLED):
            try:
                self._action(run, "return_to_origin", {"origin_xy_um": self.origin},
                    lambda request_id: self._move(run, request_id, self.origin, self.monotonic() + 10), phase)
            except Exception as exc:  # noqa: BLE001 -- Preserve failed origin-return outcome.
                run.status = RunStatus.OUTCOME_UNKNOWN
                run.errors.append(f"return failed: {type(exc).__name__}: {exc}")
        self._save(run)
        return run

    def run_recipe(self, recipe: StageScanRecipe, *, settle_ms: float = 0,
                   timeout_s: float = 120, return_to_origin: bool = True) -> ScanRun:
        """Interpret a library recipe under this host's device and execution policy."""
        return self.run(recipe.positions, recipe.settings, specimen_id=recipe.specimen_id,
                        coordinate_frame=recipe.coordinate_frame, calibration_id=recipe.calibration_id,
                        phase=recipe.phase, settle_ms=settle_ms, timeout_s=timeout_s,
                        return_to_origin=return_to_origin, recipe_id=recipe.recipe_id,
                        recipe_version=recipe.version, resources=recipe.resources)
