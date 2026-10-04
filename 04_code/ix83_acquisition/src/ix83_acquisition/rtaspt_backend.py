"""Compatibility adapter for RTASPT's injectable acquisition backend boundary.

No import of RTASPT is required. This adapter preserves its ndarray-returning
acquire(event) contract while the device work lives in this local package.
"""

from __future__ import annotations

from typing import Protocol

from .interfaces import Camera, Channel, Image, XYZStage


class LegacyEvent(Protocol):
    @property
    def color(self) -> str: ...

    @property
    def exposure_ms(self) -> float: ...


class AcquisitionSettings(Protocol):
    @property
    def channel_group(self) -> str: ...


class ProjectSettings(Protocol):
    @property
    def acquisition(self) -> AcquisitionSettings: ...


class RtasptBackend:
    """Inject into RTASPT run_acquisition or its controller backend_factory.

    Pixel layout is returned unchanged. Polarization selection and channel
    reconstruction remain the host's responsibility, as in its Core adapter.
    """

    def __init__(self, camera: Camera, stage: XYZStage, *, channel_group: str) -> None:
        self.camera = camera
        self.stage = stage
        self.channel_group = channel_group

    def acquire(self, event: LegacyEvent) -> Image:
        return self.camera.snap(
            stage_position=self.stage.position,
            exposure_ms=event.exposure_ms,
            channel=Channel(self.channel_group, event.color),
        ).pixels

    def update_config(self, config: ProjectSettings) -> None:
        self.channel_group = config.acquisition.channel_group

    def close(self) -> None:
        try:
            self.camera.close()
        finally:
            self.stage.close()
