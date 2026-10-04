"""Execution-host acquisition interfaces, independent of concrete devices."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from samplescout.contracts import AcquisitionSettings, Phase


@dataclass(frozen=True)
class AcquisitionResult:
    image: Any
    stage_xy_um: tuple[float, float]
    acquired_at: datetime
    data_reference: str | None = None
    axes: tuple[str, ...] = ("y", "x")


class SearchBackend(Protocol):
    """Small device boundary; backend owns execution policy and device calls."""
    capabilities: frozenset[str]
    resources: frozenset[str]

    def move_to(self, request_id: str, position_xyz_um: tuple[float, float, float], *, deadline: float | None = None) -> Any: ...
    def acquire(self, request_id: str, settings: AcquisitionSettings, *, phase: Phase,
                specimen_id: str, coordinate_frame: str, calibration_id: str,
                run_id: str, tile_id: str, target_id: str | None,
                deadline: float | None = None) -> AcquisitionResult: ...


