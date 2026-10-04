"""Optional replay handoff to RTASPT's existing named-axis plane contract."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from importlib import import_module
from pathlib import Path
from typing import Protocol, cast

from .interfaces import Image
from .ome_recording import replay_ome_frames
from .recording import replay_frames


class YXRecord(Protocol):
    @property
    def pixels(self) -> Image: ...

    @property
    def coordinates(self) -> Mapping[str, int]: ...

    @property
    def sequence(self) -> int | None: ...

    @property
    def timestamp(self) -> float | None: ...


def rtaspt_planes(dataset_dir: Path) -> Iterator[YXRecord]:
    """Yield actual RTASPT YXPlane objects; import RTASPT only when consumed.

    NPY uses Q for arrivals; fixed-position OME sequences use T for timepoints.
    Channel, target, stage and calibration context
    remain in the recording ledger and manifest, not implicitly encoded as Q/T.
    Host acquisition completion time is supplied as optional source timestamp.
    """
    try:
        data_inputs = import_module("rtaspt.data_inputs")
    except ModuleNotFoundError as exc:
        raise RuntimeError("Install RTASPT or expose its src directory for this handoff") from exc
    manifest = json.loads((dataset_dir / "run_metadata.json").read_text(encoding="utf-8"))
    is_ome = manifest.get("format") == "ome-tiff"
    frames = replay_ome_frames(dataset_dir) if is_ome else replay_frames(dataset_dir)
    for frame in frames:
        yield cast(
            YXRecord,
            data_inputs.YXPlane(
                pixels=frame.pixels,
                coordinates={"T": frame.timepoint} if is_ome else {"Q": frame.sequence},
                sequence=frame.sequence,
                timestamp=frame.acquisition_end_ns / 1_000_000_000,
            ),
        )
