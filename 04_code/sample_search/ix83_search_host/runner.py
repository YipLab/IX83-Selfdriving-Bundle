"""Serial survey, detect, select, and revisit workflow runner."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from math import isfinite
from time import monotonic
from typing import Any

from samplescout.contracts import (
    AcquisitionSettings,
    ActionRecord,
    ActionStatus,
    DetectedObject,
    Phase,
    RunStatus,
    SearchObservation,
    Target,
    WorkflowRecipe,
    WorkflowRun,
    new_request_id,
)
from samplescout.geometry import (
    Calibration,
    Region,
    Tile,
    deduplicate_targets,
    plan_tiles,
)
from samplescout.records import to_record_value
from samplescout.review import ReviewDecision

from .contracts import AcquisitionResult, SearchBackend

Detector = Callable[[Any, SearchObservation], Sequence[Any]]
Review = Callable[[Sequence[Target]], Sequence[Target]]
Clock = Callable[[], datetime]
CancelCheck = Callable[[], bool]


class SearchCancelled(Exception):
    pass


class WorkflowDeadlineExceeded(Exception):
    pass


class MissingAcquisitionData(RuntimeError):
    pass


class SampleSearchRunner:
    def __init__(self, backend: SearchBackend, detector: Detector, recipe: WorkflowRecipe,
                 calibration: Calibration, region: Region, *,
                 z_um: float = 0.0, timeout_s: float | None = None,
                 clock: Clock | None = None, deadline_clock: Callable[[], float] | None = None,
                 cancelled: CancelCheck | None = None, review: Review | None = None,
                 max_observation_age_s: float | None = 300.0,
                 full_calibration: Calibration | None = None):
        self.backend = backend
        self.detector = detector
        self.recipe = recipe
        self.calibration = calibration
        self.full_calibration = full_calibration or calibration
        self.region = region
        self.z_um = z_um
        self.timeout_s = timeout_s
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.deadline_clock = deadline_clock or monotonic
        self.cancelled = cancelled or (lambda: False)
        self.review = review
        self.max_observation_age_s = max_observation_age_s
        if timeout_s is not None and timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        if recipe.specimen_id == "" or recipe.coordinate_frame != calibration.coordinate_frame or recipe.calibration_id != calibration.calibration_id:
            raise ValueError("recipe and calibration specimen/frame/identity must be configured consistently")
        if self.full_calibration.coordinate_frame != recipe.coordinate_frame:
            raise ValueError("full calibration coordinate frame must match recipe")
        survey = recipe.survey_settings
        if survey.roi_origin is not None and survey.roi_origin != calibration.roi_origin:
            raise ValueError("survey settings ROI does not match survey calibration")
        if survey.binning is not None and survey.binning != calibration.binning:
            raise ValueError("survey settings binning does not match survey calibration")
        survey_calibration_id = survey.metadata.get("calibration_id")
        if survey_calibration_id is not None and survey_calibration_id != calibration.calibration_id:
            raise ValueError("survey settings calibration_id does not match survey calibration")
        full = recipe.full_settings
        geometry_mismatch = ((full.roi_origin is not None and full.roi_origin != calibration.roi_origin) or
                             (full.binning is not None and full.binning != calibration.binning))
        if geometry_mismatch and full_calibration is None:
            raise ValueError("provide full_calibration when full-acquisition ROI/binning differs")
        if full_calibration is not None:
            if full.roi_origin is not None and full.roi_origin != full_calibration.roi_origin:
                raise ValueError("full settings ROI does not match full calibration")
            if full.binning is not None and full.binning != full_calibration.binning:
                raise ValueError("full settings binning does not match full calibration")
            full_calibration_id = full.metadata.get("calibration_id")
            if full_calibration_id is not None and full_calibration_id != full_calibration.calibration_id:
                raise ValueError("full settings calibration_id does not match full calibration")
        elif full.metadata.get("calibration_id") not in (None, self.full_calibration.calibration_id):
            raise ValueError("full settings calibration_id does not match full calibration")

    def run(self, *, review_only: bool = False) -> WorkflowRun:
        run = WorkflowRun(recipe_id=self.recipe.recipe_id, recipe_version=self.recipe.version,
                          specimen_id=self.recipe.specimen_id, started_at=self.clock())
        deadline = self.deadline_clock() + self.timeout_s if self.timeout_s is not None else None
        try:
            self._check(deadline)
            self._preflight()
            survey_shape = self.recipe.survey_settings.image_shape_yx or self.recipe.image_shape_yx
            fw, fh = self.calibration.image_extent_um(survey_shape)
            tiles = plan_tiles(self.region, (fw, fh), self.recipe.overlap)
            # Survey is a complete pass. Detection is deferred until every tile has been acquired.
            survey: list[tuple[SearchObservation, Any]] = []
            for tile in tiles:
                self._check(deadline)
                run.phase = Phase.SURVEY
                obs, image = self._acquire(run, tile, Phase.SURVEY, self.recipe.survey_settings,
                                           self.calibration, survey_shape, deadline)
                run.observations.append(obs)
                if not obs.missing and image is not None:
                    survey.append((obs, image))
            if not survey:
                run.status = RunStatus.EMPTY
                return run

            run.phase = Phase.DETECTION
            detected_observations: list[SearchObservation] = []
            for obs, image in survey:
                self._check(deadline)
                detections = tuple(self.detector(image, obs))
                converted = tuple(DetectedObject(float(d.x_pixel), float(d.y_pixel),
                    getattr(d, "score", getattr(d, "mean_intensity", getattr(d, "max_intensity", None))),
                    getattr(d, "bounds_xyxy_pixel", None), bool(getattr(d, "touches_edge", False)))
                    for d in detections)
                detected_observations.append(SearchObservation(
                    specimen_id=obs.specimen_id, phase=Phase.DETECTION,
                    coordinate_frame=obs.coordinate_frame, calibration_id=obs.calibration_id,
                    acquired_at=obs.acquired_at, published_at=self.clock(), stage_xy_um=obs.stage_xy_um,
                    tile_id=obs.tile_id, request_id=obs.request_id, run_id=run.run_id,
                    value=converted, axes=obs.axes, data_reference=obs.data_reference,
                    channel_id=obs.channel_id, exposure_ms=obs.exposure_ms,
                    image_shape_yx=obs.image_shape_yx))
            run.observations.extend(detected_observations)
            run.phase = Phase.SELECTION
            targets = list(deduplicate_targets(detected_observations, self.calibration,
                                               distance_um=self.recipe.deduplication_um,
                                               region=self.region))
            if self.recipe.max_targets is not None:
                if self.recipe.max_targets < 0:
                    raise ValueError("max_targets must be nonnegative")
                targets = sorted(targets, key=lambda t: (-(t.score if t.score is not None else float("-inf")), t.y_um, t.x_um))[:self.recipe.max_targets]
            run.review_binding_sha256 = self._review_binding()
            run.review_fixed_z_um = self.z_um
            if self.review is not None:
                eligible = {target.target_id: target for target in targets}
                reviewed = list(self.review(tuple(targets)))
                reviewed_ids = [target.target_id for target in reviewed]
                if any(target_id not in eligible for target_id in reviewed_ids):
                    raise ValueError("review may only accept or reject proposed targets")
                if len(reviewed_ids) != len(set(reviewed_ids)):
                    raise ValueError("review may not return duplicate targets")
                targets = [eligible[target_id] for target_id in reviewed_ids]
            run.targets = targets
            if review_only:
                from samplescout.review import ReviewContext, create_manifest
                context = ReviewContext(run.run_id, self.recipe.specimen_id,
                                        self.calibration.coordinate_frame, self.calibration.calibration_id)
                run.review_manifest_sha256 = create_manifest(context, targets).sha256
                run.status = RunStatus.REVIEW_PENDING
                return run
            if not targets:
                run.status = RunStatus.EMPTY
                return run

            run.phase = Phase.REVISIT
            for index, target in enumerate(targets):
                self._check(deadline)
                tile = Tile(f"target-{target.target_id}", 0, index, target.x_um, target.y_um)
                full_shape = self.recipe.full_settings.image_shape_yx or self.recipe.image_shape_yx
                obs, _image = self._acquire(run, tile, Phase.REVISIT, self.recipe.full_settings,
                                            self.full_calibration, full_shape, deadline,
                                            target_id=target.target_id)
                run.observations.append(obs)
            run.status = RunStatus.COMPLETED
        except SearchCancelled:
            run.status = RunStatus.CANCELLED
        except WorkflowDeadlineExceeded as exc:
            run.status = RunStatus.FAILED
            run.errors.append(str(exc))
        except TimeoutError as exc:
            run.status = RunStatus.OUTCOME_UNKNOWN
            run.errors.append(str(exc) or "operation deadline exceeded")
        except Exception as exc:  # noqa: BLE001 -- Record all workflow failures in the run ledger.
            run.status = RunStatus.FAILED
            run.errors.append(f"{type(exc).__name__}: {exc}")
        finally:
            run.finished_at = self.clock()
        return run

    def _review_binding(self) -> str:
        context = {"recipe": to_record_value(self.recipe), "survey_calibration": to_record_value(self.calibration),
                   "full_calibration": to_record_value(self.full_calibration), "region": to_record_value(self.region),
                   "fixed_z_um": self.z_um}
        return hashlib.sha256(json.dumps(context, sort_keys=True, separators=(",", ":"),
                                         allow_nan=False).encode("utf-8")).hexdigest()

    def resume_review(self, run: WorkflowRun, decision: ReviewDecision) -> WorkflowRun:
        """Apply a saved manual decision and execute only the revisit pass.

        A pending review is a single-use checkpoint. Physical recovery after an
        unknown action remains operator directed; this method never auto-retries it.
        """
        from samplescout.review import ReviewContext, apply_review, create_manifest
        if not isinstance(run, WorkflowRun) or run.status is not RunStatus.REVIEW_PENDING:
            raise ValueError("run is not an unused review-pending checkpoint")
        if (run.recipe_id, run.recipe_version, run.specimen_id, run.phase) != (
            self.recipe.recipe_id, self.recipe.version, self.recipe.specimen_id, Phase.SELECTION
        ):
            raise ValueError("checkpoint run identity or phase does not match current workflow")
        if run.review_binding_sha256 != self._review_binding():
            raise ValueError("checkpoint recipe, calibration, region, or fixed Z binding is stale")
        if run.review_fixed_z_um != self.z_um:
            raise ValueError("checkpoint fixed Z does not match current workflow")
        if any((o.run_id, o.specimen_id, o.coordinate_frame, o.calibration_id) !=
               (run.run_id, self.recipe.specimen_id, self.calibration.coordinate_frame,
                self.calibration.calibration_id) for o in run.observations
               if o.phase in (Phase.SURVEY, Phase.DETECTION)):
            raise ValueError("checkpoint observation context does not match workflow")
        if not isinstance(decision, ReviewDecision):
            raise TypeError("decision must be a validated ReviewDecision")
        context = ReviewContext(run.run_id, self.recipe.specimen_id,
                                self.calibration.coordinate_frame, self.calibration.calibration_id)
        if create_manifest(context, run.targets).sha256 != run.review_manifest_sha256:
            raise ValueError("checkpoint candidate manifest changed after survey")
        result = apply_review(decision, tuple(run.targets), context=context, region=self.region,
                              max_targets=self.recipe.max_targets if self.recipe.max_targets is not None else 2**31 - 1)
        # Validate saved observations and age before any command is issued.
        now = self.clock()
        survey = [o for o in run.observations if o.phase is Phase.SURVEY and not o.missing]
        if not survey:
            raise ValueError("checkpoint has no complete survey observations")
        if self.max_observation_age_s is not None and any(
            (now - o.acquired_at).total_seconds() < 0 or
            (now - o.acquired_at).total_seconds() > self.max_observation_age_s for o in survey
        ):
            raise ValueError("survey observation is stale for revisit")
        self._preflight()
        run.targets = list(result.targets)
        run.review_decision = decision.to_dict()
        run.manual_provenance = tuple({"target_id": p.target_id, "reason": p.reason,
                                       "x_um": p.x_um, "y_um": p.y_um}
                                      for p in result.manual_provenance)
        run.phase = Phase.SELECTION if not run.targets else Phase.REVISIT
        run.review_resumed_at = self.clock()
        deadline = self.deadline_clock() + self.timeout_s if self.timeout_s is not None else None
        run.status = RunStatus.EMPTY if not run.targets else RunStatus.COMPLETED
        try:
            for index, target in enumerate(run.targets):
                self._check(deadline)
                tile = Tile(f"target-{target.target_id}", 0, index, target.x_um, target.y_um)
                full_shape = self.recipe.full_settings.image_shape_yx or self.recipe.image_shape_yx
                obs, _image = self._acquire(run, tile, Phase.REVISIT, self.recipe.full_settings,
                                            self.full_calibration, full_shape, deadline,
                                            target_id=target.target_id)
                run.observations.append(obs)
        except SearchCancelled:
            run.status = RunStatus.CANCELLED
        except WorkflowDeadlineExceeded as exc:
            run.status = RunStatus.FAILED
            run.errors.append(str(exc))
        except TimeoutError as exc:
            run.status = RunStatus.OUTCOME_UNKNOWN
            run.errors.append(str(exc) or "operation deadline exceeded")
        except Exception as exc:  # noqa: BLE001 - preserve partial ledger on failure
            run.status = RunStatus.FAILED
            run.errors.append(f"{type(exc).__name__}: {exc}")
        finally:
            run.finished_at = self.clock()
        return run

    def _check(self, deadline: float | None) -> None:
        if self.cancelled():
            raise SearchCancelled()
        if deadline is not None and self.deadline_clock() >= deadline:
            raise WorkflowDeadlineExceeded("workflow deadline exceeded before the next action")

    def _preflight(self) -> None:
        required_capabilities = set(self.recipe.required_capabilities)
        if self.recipe.survey_settings.frames > 1 or self.recipe.full_settings.frames > 1:
            required_capabilities.add("camera.sequence")
        available_capabilities = getattr(self.backend, "capabilities", None)
        if required_capabilities:
            if available_capabilities is None:
                raise RuntimeError(
                    "backend does not declare capabilities required by the recipe: "
                    + ", ".join(sorted(required_capabilities)))
            missing = required_capabilities - set(available_capabilities)
            if missing:
                raise RuntimeError(f"backend lacks required capabilities: {', '.join(sorted(missing))}")

        required_resources = {requirement.name for requirement in self.recipe.resources}
        available_resources = getattr(self.backend, "resources", None)
        default_resources = {"stage", "camera"}
        if available_resources is None:
            if required_resources != default_resources:
                raise RuntimeError("backend does not declare explicitly requested resources")
            return
        missing_resources = required_resources - set(available_resources)
        if missing_resources:
            raise RuntimeError(f"backend lacks required resources: {', '.join(sorted(missing_resources))}")

    def _record(self, run: WorkflowRun, action: str, phase: Phase, call: Callable[[], Any], deadline: float | None,
                request_id: str | None = None, parameters: Mapping[str, Any] | None = None) -> Any:
        self._check(deadline)
        request_id = request_id or new_request_id()
        started = self.clock()
        params = dict(parameters or {})
        run.actions.append(ActionRecord(request_id, action, ActionStatus.PROPOSED, phase, started, parameters=params))
        run.actions.append(ActionRecord(request_id, action, ActionStatus.ACCEPTED, phase, started, parameters=params))
        run.actions.append(ActionRecord(request_id, action, ActionStatus.STARTED, phase, started, parameters=params))
        try:
            result = call()
        except TimeoutError as exc:
            run.actions.append(ActionRecord(request_id, action, ActionStatus.OUTCOME_UNKNOWN, phase, started, self.clock(), parameters=params, error=str(exc)))
            raise
        except SearchCancelled:
            run.actions.append(ActionRecord(request_id, action, ActionStatus.CANCELLED, phase, started, self.clock(), parameters=params))
            raise
        except Exception as exc:
            run.actions.append(ActionRecord(request_id, action, ActionStatus.FAILED, phase, started, self.clock(), parameters=params, error=f"{type(exc).__name__}: {exc}"))
            raise
        readback = result
        if isinstance(result, AcquisitionResult):
            readback = {"stage_xy_um": result.stage_xy_um, "acquired_at": result.acquired_at.isoformat(),
                        "data_reference": result.data_reference, "axes": result.axes,
                        "image_shape": getattr(result.image, "shape", None), "image_present": result.image is not None}
        run.actions.append(ActionRecord(request_id, action, ActionStatus.COMPLETED, phase, started,
                                        self.clock(), parameters=params, readback=readback))
        return request_id, result

    def _acquire(self, run: WorkflowRun, tile: Tile, phase: Phase,
                 settings: AcquisitionSettings, calibration: Calibration,
                 shape_yx: tuple[int, int], deadline: float | None,
                 target_id: str | None = None) -> tuple[SearchObservation, Any]:
        h, w = shape_yx
        center_offset = calibration.image_to_stage((w - 1) / 2, (h - 1) / 2, (0.0, 0.0))
        requested_stage_xy = tile.x_um - center_offset[0], tile.y_um - center_offset[1]
        request_id = new_request_id()
        _, readback = self._record(run, "move_to", phase,
            lambda: self.backend.move_to(request_id, (*requested_stage_xy, self.z_um), deadline=deadline),
            deadline, request_id, {"position_xyz_um": (*requested_stage_xy, self.z_um),
                                   "tile_id": tile.tile_id, "target_id": target_id})
        actual_xy = requested_stage_xy
        if isinstance(readback, (tuple, list)) and len(readback) >= 2:
            actual_xy = float(readback[0]), float(readback[1])
        acquire_id = new_request_id()
        actual_id, result = self._record(run, "acquire", phase,
            lambda: self.backend.acquire(acquire_id, settings, phase=phase,
                specimen_id=self.recipe.specimen_id, coordinate_frame=calibration.coordinate_frame,
                calibration_id=calibration.calibration_id, run_id=run.run_id,
                tile_id=tile.tile_id, target_id=target_id, deadline=deadline), deadline, acquire_id,
            {"exposure_ms": settings.exposure_ms, "frames": settings.frames,
             "channel_id": settings.channel_id, "image_shape_yx": shape_yx,
             "roi_origin": settings.roi_origin or calibration.roi_origin,
             "binning": settings.binning or calibration.binning,
             "specimen_id": self.recipe.specimen_id, "coordinate_frame": calibration.coordinate_frame,
             "calibration_id": calibration.calibration_id, "run_id": run.run_id,
             "tile_id": tile.tile_id, "target_id": target_id})
        if actual_id != acquire_id:
            raise RuntimeError("internal request ID mismatch")
        if not isinstance(result, AcquisitionResult):
            raise TypeError("backend.acquire must return AcquisitionResult")
        if len(result.stage_xy_um) != 2 or not all(isfinite(v) for v in result.stage_xy_um):
            raise ValueError("acquisition stage readback must contain finite x/y micrometres")
        if result.axes.count("x") != 1 or result.axes.count("y") != 1 or len(set(result.axes)) != len(result.axes):
            raise ValueError("acquisition axes must include unique x and y axes")
        if result.acquired_at.tzinfo is None:
            raise ValueError("acquired_at must be timezone-aware UTC")
        published_at = self.clock()
        if result.acquired_at > published_at:
            raise ValueError("acquisition timestamp is in the future")
        if self.max_observation_age_s is not None and (published_at - result.acquired_at).total_seconds() > self.max_observation_age_s:
            raise ValueError("acquisition result is stale")
        image_shape = getattr(result.image, "shape", None)
        if image_shape is not None and len(image_shape) != len(result.axes):
            raise ValueError("image shape does not match declared axes")
        if image_shape is not None and settings.image_shape_yx is not None:
            y_size, x_size = image_shape[result.axes.index("y")], image_shape[result.axes.index("x")]
            if (y_size, x_size) != settings.image_shape_yx:
                raise ValueError("image y/x dimensions do not match acquisition settings")
        if result.stage_xy_um != actual_xy:
            actual_xy = result.stage_xy_um
        actual_xy = result.stage_xy_um
        actual_shape = None
        if image_shape is not None:
            actual_shape = (int(image_shape[result.axes.index("y")]), int(image_shape[result.axes.index("x")]))
        elif settings.image_shape_yx is not None:
            actual_shape = settings.image_shape_yx
        else:
            actual_shape = shape_yx
        obs = SearchObservation(self.recipe.specimen_id, phase, calibration.coordinate_frame,
            calibration.calibration_id, result.acquired_at, published_at, actual_xy,
            tile.tile_id, acquire_id, run_id=run.run_id, value=None, axes=result.axes, missing=result.image is None,
            target_id=target_id, data_reference=result.data_reference,
            channel_id=settings.channel_id, exposure_ms=settings.exposure_ms, image_shape_yx=actual_shape)
        if result.image is None:
            run.observations.append(obs)
            raise MissingAcquisitionData(f"acquisition {acquire_id} completed without image data")
        return obs, result.image



