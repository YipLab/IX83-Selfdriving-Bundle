"""Execution-host acquisition interfaces, independent of concrete devices."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from samplescout.contracts import AcquisitionSettings, DatasetReference, Phase

DataReference = DatasetReference


@dataclass(frozen=True)
class ExecutionControl:
    cancelled: Callable[[], bool] = lambda: False
    deadline_monotonic: float | None = None


@dataclass(frozen=True)
class MoveRequest:
    request_id: str
    run_id: str
    recipe_id: str
    recipe_version: str
    specimen_id: str
    phase: Phase
    coordinate_frame: str
    calibration_id: str
    position_xyz_um: tuple[float, float, float]
    tile_id: str
    target_id: str | None = None
    control: ExecutionControl = ExecutionControl()


@dataclass(frozen=True)
class AcquireRequest:
    request_id: str
    run_id: str
    recipe_id: str
    recipe_version: str
    specimen_id: str
    phase: Phase
    coordinate_frame: str
    calibration_id: str
    tile_id: str
    settings: AcquisitionSettings
    target_id: str | None = None
    control: ExecutionControl = ExecutionControl()


@dataclass(frozen=True)
class MoveResult:
    request_id: str
    stage_xyz_um: tuple[float, float, float]


@dataclass(frozen=True)
class AcquisitionResult:
    request_id: str
    run_id: str
    specimen_id: str
    phase: Phase
    coordinate_frame: str
    calibration_id: str
    tile_id: str
    image: Any
    stage_xy_um: tuple[float, float]
    acquired_at: datetime
    dataset: DataReference | None = None
    image_axes: tuple[str, ...] = ("Y", "X")


class SearchBackend(Protocol):
    """Small device boundary; backend owns execution policy and device calls."""
    capabilities: frozenset[str]
    resources: frozenset[str]
    setting_capabilities: frozenset[str]

    def move_to(self, request: MoveRequest) -> MoveResult: ...
    def acquire(self, request: AcquireRequest) -> AcquisitionResult: ...


