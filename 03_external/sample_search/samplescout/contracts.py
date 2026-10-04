"""Backend-independent contracts for serial sample-search workflows."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from math import isfinite
from typing import Any
from uuid import uuid4


class Phase(str, Enum):
    SURVEY = "survey"
    DETECTION = "detection"
    SELECTION = "selection"
    REVISIT = "revisit"


class RunStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    EMPTY = "empty"
    CANCELLED = "cancelled"
    FAILED = "failed"
    OUTCOME_UNKNOWN = "outcome_unknown"
    REVIEW_PENDING = "review_pending"


class ActionStatus(str, Enum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    OUTCOME_UNKNOWN = "outcome_unknown"


@dataclass(frozen=True)
class ResourceRequirement:
    name: str
    mode: str = "exclusive"


@dataclass(frozen=True)
class AcquisitionSettings:
    exposure_ms: float = 50.0
    frames: int = 1
    channel_id: str | None = None
    image_shape_yx: tuple[int, int] | None = None
    roi_origin: tuple[float, float] | None = None
    binning: tuple[float, float] | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.exposure_ms, bool) or not isinstance(self.exposure_ms, (int, float)) or not isfinite(self.exposure_ms) or self.exposure_ms <= 0:
            raise ValueError("exposure_ms must be finite and positive")
        if isinstance(self.frames, bool) or not isinstance(self.frames, int) or self.frames < 1:
            raise ValueError("exposure_ms and frames must be positive")
        if self.image_shape_yx is not None and (len(self.image_shape_yx) != 2 or any(isinstance(v, bool) or not isinstance(v, int) or v <= 0 for v in self.image_shape_yx)):
            raise ValueError("image_shape_yx must be a pair of positive integers")
        if self.roi_origin is not None and (len(self.roi_origin) != 2 or any(isinstance(x, bool) or not isinstance(x, (int, float)) or not isfinite(x) for x in self.roi_origin)):
            raise ValueError("ROI origin must be finite")
        if self.binning is not None and (len(self.binning) != 2 or min(self.binning) <= 0 or any(isinstance(x, bool) or not isinstance(x, (int, float)) or not isfinite(x) for x in self.binning)):
            raise ValueError("binning must be finite and positive")


@dataclass(frozen=True)
class WorkflowRecipe:
    recipe_id: str
    version: str
    specimen_id: str
    coordinate_frame: str
    calibration_id: str
    survey_settings: AcquisitionSettings
    full_settings: AcquisitionSettings
    image_shape_yx: tuple[int, int]
    overlap: float = 0.2
    deduplication_um: float = 3.0
    max_targets: int | None = None
    required_capabilities: frozenset[str] = frozenset()
    resources: tuple[ResourceRequirement, ...] = (ResourceRequirement("stage"), ResourceRequirement("camera"))
    preconditions: tuple[str, ...] = ()
    physical_effects: tuple[str, ...] = ("stage_motion", "image_acquisition")
    completion_condition: str = "all selected revisit acquisitions complete"
    failure_condition: str = "any failed or outcome-unknown device action"
    parameters: Mapping[str, Any] = field(default_factory=dict)
    validation_evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.survey_settings, AcquisitionSettings) or not isinstance(self.full_settings, AcquisitionSettings):
            raise TypeError("survey_settings and full_settings must be AcquisitionSettings")
        if len(self.image_shape_yx) != 2 or any(isinstance(v, bool) or not isinstance(v, int) or v <= 0 for v in self.image_shape_yx):
            raise ValueError("image_shape_yx must be a pair of positive integers")
        if not isfinite(self.overlap) or not 0 <= self.overlap < 1:
            raise ValueError("overlap must be finite and in [0, 1)")
        if not isfinite(self.deduplication_um) or self.deduplication_um < 0:
            raise ValueError("deduplication_um must be finite and nonnegative")
        if self.max_targets is not None and (isinstance(self.max_targets, bool) or not isinstance(self.max_targets, int) or self.max_targets < 0):
            raise ValueError("max_targets must be a nonnegative integer")


@dataclass(frozen=True)
class SearchObservation:
    specimen_id: str
    phase: Phase
    coordinate_frame: str
    calibration_id: str
    acquired_at: datetime
    published_at: datetime
    stage_xy_um: tuple[float, float]
    tile_id: str
    request_id: str
    run_id: str = ""
    value: Any = None
    axes: tuple[str, ...] = ("y", "x")
    missing: bool = False
    target_id: str | None = None
    data_reference: str | None = None
    channel_id: str | None = None
    exposure_ms: float | None = None
    image_shape_yx: tuple[int, int] | None = None


@dataclass(frozen=True)
class Target:
    target_id: str
    specimen_id: str
    coordinate_frame: str
    calibration_id: str
    x_um: float
    y_um: float
    observations: tuple[SearchObservation, ...] = ()
    score: float | None = None
    bounds_xyxy_um: tuple[float, float, float, float] | None = None


@dataclass(frozen=True)
class DetectedObject:
    x_pixel: float
    y_pixel: float
    score: float | None = None
    bounds_xyxy_pixel: tuple[float, float, float, float] | None = None
    touches_edge: bool = False


@dataclass(frozen=True)
class ActionRecord:
    request_id: str
    action: str
    status: ActionStatus
    phase: Phase
    started_at: datetime
    finished_at: datetime | None = None
    parameters: Mapping[str, Any] = field(default_factory=dict)
    readback: Any = None
    error: str | None = None


@dataclass
class WorkflowRun:
    run_id: str = field(default_factory=lambda: str(uuid4()))
    recipe_id: str = ""
    recipe_version: str = ""
    specimen_id: str = ""
    status: RunStatus = RunStatus.FAILED
    phase: Phase = Phase.SURVEY
    started_at: datetime | None = None
    finished_at: datetime | None = None
    actions: list[ActionRecord] = field(default_factory=list)
    observations: list[SearchObservation] = field(default_factory=list)
    targets: list[Target] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    review_binding_sha256: str | None = None
    review_manifest_sha256: str | None = None
    review_fixed_z_um: float | None = None
    review_decision: Mapping[str, Any] | None = None
    manual_provenance: tuple[Mapping[str, Any], ...] = ()
    review_resumed_at: datetime | None = None


def new_request_id() -> str:
    return str(uuid4())
