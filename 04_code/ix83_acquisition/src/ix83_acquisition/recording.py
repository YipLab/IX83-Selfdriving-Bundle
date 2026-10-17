"""Incremental raw-plane recording with a checksummed acquisition ledger.

This local interchange format keeps storage independent of RTASPT and GUI code.
It is not a released microscopy file-format contract or a hardware event journal.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Iterator, Mapping
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np

from .controller import RunResult
from .interfaces import Channel, Frame, Position


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_line(record: Mapping[str, object]) -> str:
    return json.dumps(record, allow_nan=False, separators=(",", ":")) + "\n"


class RunRecorder:
    """Finite-run frame callback; writes every frame independently of preview.

    Call finish only after the worker exits. A failed or interrupted write can
    leave an unreferenced raw file; replay uses the ledger and never guesses which
    files were accepted. Close without finish preserves an incomplete recording.
    """

    def __init__(
        self, root: Path, name: str, *, context: Mapping[str, object] | None = None
    ) -> None:
        if not name or name in (".", "..") or Path(name).name != name or ":" in name:
            raise ValueError("dataset name must be a single directory name")
        header = _json_line(
            {"type": "dataset", "schema_version": 1, "context": dict(context or {})}
        )
        root.mkdir(parents=True, exist_ok=True)
        index = 0
        while True:
            self.dataset_dir = root / (name if index == 0 else f"{name}_{index}")
            try:
                self.dataset_dir.mkdir()
                break
            except FileExistsError:
                index += 1
        self._ledger = (self.dataset_dir / "frames.jsonl").open("x", encoding="utf-8")
        self._ledger.write(header)
        self._flush()
        self.frames_written = 0
        self._finished = False

    def _flush(self) -> None:
        self._ledger.flush()
        os.fsync(self._ledger.fileno())

    def __call__(self, frame: Frame) -> None:
        if self._finished or self._ledger.closed:
            raise RuntimeError("recording is closed")
        if frame.sequence != self.frames_written:
            raise ValueError("recording requires contiguous zero-based frame sequences")
        if frame.pixels.ndim != 2 or frame.pixels.dtype.kind not in "uif":
            raise ValueError("recording requires a numeric YX camera plane")
        filename = f"frame_{frame.sequence:06d}.npy"
        path = self.dataset_dir / filename
        # Validate metadata before writing raw pixels. No ndarray in the ledger.
        record: dict[str, object] = {
            "type": "frame",
            "sequence": frame.sequence,
            "file": filename,
            "shape": list(frame.pixels.shape),
            "dtype": str(frame.pixels.dtype),
            "stage_position": asdict(frame.stage_position),
            "exposure_ms": frame.exposure_ms,
            "acquisition_start_ns": frame.acquisition_start_ns,
            "acquisition_end_ns": frame.acquisition_end_ns,
            "channel": asdict(frame.channel) if frame.channel else None,
            "request_id": frame.request_id,
            "target_id": frame.target_id,
            "timepoint": frame.timepoint,
            "core_image_number": frame.core_image_number,
            "camera_frame_number": frame.camera_frame_number,
            "source_timestamp_ms": frame.source_timestamp_ms,
        }
        _json_line(record)
        with path.open("xb") as raw:
            np.save(raw, frame.pixels, allow_pickle=False)
            raw.flush()
            os.fsync(raw.fileno())
        record["sha256"] = _sha256(path)
        self._ledger.write(_json_line(record))
        self._flush()
        self.frames_written += 1

    def finish(self, result: RunResult) -> Path:
        if self._finished or self._ledger.closed:
            raise RuntimeError("recording is closed")
        if result.frames_requested is not None and (
            isinstance(result.frames_requested, bool)
            or not isinstance(result.frames_requested, int)
            or result.frames_requested < 0
        ):
            raise ValueError("frames_requested must be a nonnegative integer")
        if result.frames_acquired < self.frames_written or (
            result.state == "completed" and result.frames_acquired != self.frames_written
        ):
            raise ValueError("run result disagrees with the number of recorded frames")
        if (
            result.state == "completed"
            and result.frames_requested is not None
            and result.frames_acquired != result.frames_requested
        ):
            raise ValueError("completed run does not contain every requested frame")
        metadata = self.dataset_dir / "run_metadata.json"
        with metadata.open("x", encoding="utf-8") as stream:
            stream.write(
                _json_line(
                    {
                        "schema_version": 1,
                        "axes": "QYX",
                        "frames_written": self.frames_written,
                        "ledger_sha256": _sha256(self.dataset_dir / "frames.jsonl"),
                        "result": asdict(result),
                    }
                )
            )
            stream.flush()
            os.fsync(stream.fileno())
        self._finished = True
        self.close()
        return metadata

    def close(self) -> None:
        self._ledger.close()


def replay_frames(dataset_dir: Path) -> Iterator[Frame]:
    """Read completed/cancelled/failed recordings, validating before each yield.

    Incomplete recordings have no final manifest and are rejected. Failure and
    cancellation do not imply zero recorded frames. Processing must retain the
    accompanying manifest/context rather than infer identity from filenames.
    """
    metadata: Any = json.loads((dataset_dir / "run_metadata.json").read_text(encoding="utf-8"))
    ledger = dataset_dir / "frames.jsonl"
    if metadata["schema_version"] != 1 or metadata["axes"] != "QYX":
        raise ValueError("unsupported recording schema")
    if _sha256(ledger) != metadata["ledger_sha256"]:
        raise ValueError("acquisition ledger checksum mismatch")
    count = 0
    with ledger.open(encoding="utf-8") as stream:
        header = json.loads(next(stream))
        if header["type"] != "dataset" or header["schema_version"] != 1:
            raise ValueError("invalid acquisition ledger header")
        for line in stream:
            record = json.loads(line)
            filename = str(record["file"])
            if record["type"] != "frame" or record["sequence"] != count:
                raise ValueError("invalid frame sequence in acquisition ledger")
            if not re.fullmatch(r"frame_[0-9]+\.npy", filename):
                raise ValueError("invalid raw frame filename")
            path = dataset_dir / filename
            if _sha256(path) != record["sha256"]:
                raise ValueError(f"raw frame checksum mismatch: {filename}")
            pixels = np.load(path, allow_pickle=False)
            if list(pixels.shape) != record["shape"] or str(pixels.dtype) != record["dtype"]:
                raise ValueError(f"raw frame layout mismatch: {filename}")
            count += 1
            yield Frame(
                pixels=pixels,
                stage_position=Position(**record["stage_position"]),
                sequence=record["sequence"],
                exposure_ms=record["exposure_ms"],
                acquisition_start_ns=record["acquisition_start_ns"],
                acquisition_end_ns=record["acquisition_end_ns"],
                channel=Channel(**record["channel"]) if record["channel"] else None,
                request_id=record["request_id"],
                target_id=record["target_id"],
                timepoint=record["timepoint"],
                core_image_number=record.get("core_image_number"),
                camera_frame_number=record.get("camera_frame_number"),
                source_timestamp_ms=record.get("source_timestamp_ms"),
            )
    if count != metadata["frames_written"]:
        raise ValueError("manifest frame count disagrees with acquisition ledger")
