"""Backend-independent device contracts."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import numpy as np

Image = np.ndarray[Any, np.dtype[Any]]


@dataclass(frozen=True)
class DeviceCapabilities:
    """Capabilities reported by the selected device binding, not a recipe."""

    operations: frozenset[str]
    resources: frozenset[str]
    settings: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not self.operations or not self.resources:
            raise ValueError("device binding must declare operations and owned resources")
        if any(not value for value in (*self.operations, *self.resources, *self.settings)):
            raise ValueError("capability names must be nonempty")


@dataclass(frozen=True)
class Channel:
    """An optional Micro-Manager-compatible group/preset selection."""

    group: str
    preset: str


@dataclass(frozen=True)
class Position:
    """Stage coordinates in micrometres."""

    x_um: float
    y_um: float
    z_um: float


@dataclass(frozen=True)
class Frame:
    """One camera image and the stage position associated with its request."""

    pixels: Image
    stage_position: Position
    sequence: int
    exposure_ms: float
    acquisition_start_ns: int = 0
    acquisition_end_ns: int = 0
    channel: Channel | None = None
    request_id: str = ""
    target_id: str | None = None
    timepoint: int = 0
    core_image_number: int | None = None
    camera_frame_number: int | None = None
    source_timestamp_ms: float | None = None


class XYZStage(Protocol):
    """Three-axis stage supporting absolute positions in micrometres."""

    @property
    def position(self) -> Position: ...

    def move_to(self, position: Position) -> Position: ...

    def close(self) -> None: ...


class Camera(Protocol):
    """Camera that returns a frame associated with the supplied stage position."""

    def snap(
        self, *, stage_position: Position, exposure_ms: float, channel: Channel | None = None
    ) -> Frame: ...

    def close(self) -> None: ...


@runtime_checkable
class SequenceCamera(Camera, Protocol):
    """Finite, fixed-position sequence; incomplete acquisition must raise.

    Stop requests halt production and drain its queued prefix. Source timestamps
    retain their own clock domain and must not be treated as wall-clock time.
    """

    def stream_sequence(
        self, *, frames: int, exposure_ms: float, stage_position: Position,
        stop_requested: Callable[[], bool], channel: Channel | None = None,
        timeout_s: float = 10,
    ) -> Iterator[Frame]: ...
