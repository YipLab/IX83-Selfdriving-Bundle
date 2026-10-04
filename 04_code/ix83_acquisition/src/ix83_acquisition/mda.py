"""Small MMStudio settings boundary, independent of RTASPT configuration.

This baseline handles channel/timepoint MDA. Unsupported GUI Z/position/custom
interval modes are rejected rather than silently converted to a different scan.
Explicit XYZ requests remain supported by the acquisition controller.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from math import isfinite
from typing import Any

from .controller import CaptureRequest
from .interfaces import Channel


@dataclass(frozen=True)
class ChannelExposure:
    channel: Channel
    exposure_ms: float


@dataclass(frozen=True)
class MDASettings:
    channels: tuple[ChannelExposure, ...]
    frames: int = 1
    interval_s: float = 0.0
    output_dir: str = ""
    dataset_name: str = ""
    save_enabled: bool = False

    def validate(self) -> None:
        if self.frames < 1 or not self.channels:
            raise ValueError("MDA requires positive frames and enabled channels")
        if not isfinite(self.interval_s) or self.interval_s < 0:
            raise ValueError("MDA interval must be finite and nonnegative")
        for channel in self.channels:
            if not channel.channel.group or not channel.channel.preset:
                raise ValueError("MDA channels require group and preset names")
            CaptureRequest(exposure_ms=channel.exposure_ms).validate()


def _value(obj: Any, name: str, default: Any = None) -> Any:
    value = getattr(obj, name, default)
    return value() if callable(value) else value


def _items(collection: Any) -> Iterator[Any]:
    if callable(getattr(collection, "size", None)) and callable(getattr(collection, "get", None)):
        for index in range(int(collection.size())):
            yield collection.get(index)
    else:
        yield from collection


def read_mda_settings(studio: Any) -> MDASettings:
    """Read a caller-owned Studio proxy; this function never connects itself."""
    settings = studio.acquisitions().get_acquisition_settings()
    if not _value(settings, "use_channels", True):
        raise ValueError("MDA channel selection is disabled; enable channels for this baseline")
    for name in ("use_slices", "use_position_list", "use_custom_intervals"):
        if _value(settings, name, False):
            raise ValueError(f"MDA setting {name} is unsupported by this baseline")
    group = str(_value(settings, "channel_group", "") or "").strip()
    channels = tuple(
        ChannelExposure(
            Channel(group, str(_value(item, "config", "") or "").strip()),
            float(_value(item, "exposure")),
        )
        for item in _items(_value(settings, "channels", ()))
        if _value(item, "use_channel", True)
    )
    result = MDASettings(
        channels=channels,
        frames=int(_value(settings, "num_frames", 1))
        if _value(settings, "use_frames", False)
        else 1,
        interval_s=float(_value(settings, "interval_ms", 0)) / 1000.0,
        output_dir=str(_value(settings, "root", "") or ""),
        dataset_name=str(_value(settings, "prefix", "") or ""),
        save_enabled=bool(_value(settings, "save", False)),
    )
    result.validate()
    return result


def mda_timepoints(settings: MDASettings) -> Iterator[CaptureRequest]:
    """Yield time/channel requests with offsets per timepoint, not per channel.

    Pass these to start_finite with its default zero inter-request interval.
    """
    settings.validate()
    for timepoint in range(settings.frames):
        for channel in settings.channels:
            yield CaptureRequest(
                exposure_ms=channel.exposure_ms,
                channel=channel.channel,
                timepoint=timepoint,
                start_after_s=timepoint * settings.interval_s,
            )
