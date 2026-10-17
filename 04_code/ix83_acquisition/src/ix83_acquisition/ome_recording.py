"""Bounded concurrent OME recording; complete recording is separate from preview."""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import threading
from collections.abc import Iterator, Mapping
from dataclasses import asdict, fields, replace
from pathlib import Path
from queue import Full, Queue
from typing import Any

import numpy as np

from .controller import RunResult
from .interfaces import Channel, Frame, Position
from .recording import _json_line, _sha256


def pixel_hash(pixels: np.ndarray[Any, np.dtype[Any]]) -> str:
    return hashlib.sha256(np.ascontiguousarray(pixels).data).hexdigest()


class OMERecorder:
    """One writer worker and a bounded queue; overflow raises, never drops.

    Frames transfer to recording ownership on submit; pixels must not be mutated.
    Call finish after acquisition stops and use its final RunResult, which also
    accounts for writer errors. Until finish returns, recording is incomplete.
    Flush/fsync at finalization, not per frame. No crash-atomicity guarantee.
    """

    def __init__(
        self,
        root: Path,
        name: str,
        *,
        queue_capacity: int = 32,
        context: Mapping[str, object] | None = None,
    ) -> None:
        if queue_capacity < 1:
            raise ValueError("writer queue capacity must be positive")
        if not name or name in (".", "..") or Path(name).name != name or ":" in name:
            raise ValueError("dataset name must be a single directory name")
        self._tifffile = importlib.import_module("tifffile")
        header = _json_line(
            {"type": "dataset", "schema_version": 1, "context": dict(context or {})}
        )
        root.mkdir(parents=True, exist_ok=True)
        suffix = 0
        while True:
            self.dataset_dir = root / (name if suffix == 0 else f"{name}_{suffix}")
            try:
                self.dataset_dir.mkdir()
                break
            except FileExistsError:
                suffix += 1
        self.raw_path = self.dataset_dir / "raw.ome.tif"
        self._ledger = (self.dataset_dir / "frames.jsonl").open("x", encoding="utf-8")
        self._ledger.write(header)
        self._ledger.flush()
        self._queue: Queue[Frame | None] = Queue(queue_capacity)
        self._lock = threading.Lock()
        self._accepting = True
        self._sentinel_sent = False
        self._finished = False
        self._binding: tuple[Position, Channel | None, str | None] | None = None
        self._done = threading.Event()
        self._error: str | None = None
        self.frames_submitted = 0
        self.frames_written = 0
        self.max_queue_depth = 0
        self.result: RunResult | None = None
        self._thread = threading.Thread(target=self._write, daemon=True)
        self._thread.start()

    def __call__(self, frame: Frame) -> None:
        with self._lock:
            if not self._accepting:
                raise RuntimeError("recording is closed")
            if self._error is not None:
                raise RuntimeError(f"OME writer failed: {self._error}")
            if frame.sequence != self.frames_submitted:
                raise ValueError("recording requires contiguous zero-based frame sequences")
            if frame.timepoint != frame.sequence:
                raise ValueError("OME recording requires one plane per sequential timepoint")
            binding = (frame.stage_position, frame.channel, frame.target_id)
            if self._binding is not None and binding != self._binding:
                raise ValueError("OME recording requires one fixed position, channel and target")
            if frame.pixels.ndim != 2 or frame.pixels.dtype.kind not in "uif":
                raise ValueError("recording requires numeric YX planes")
            frame.pixels.flags.writeable = False
            try:
                self._queue.put_nowait(frame)
            except Full as exc:
                raise RuntimeError("OME writer queue full; acquisition must stop") from exc
            self.frames_submitted += 1
            self._binding = binding
            self.max_queue_depth = max(self.max_queue_depth, self._queue.qsize())

    def _write(self) -> None:
        writer: Any = None
        layout: tuple[tuple[int, ...], str] | None = None
        try:
            while True:
                frame = self._queue.get()
                if frame is None:
                    break
                frame_layout = (frame.pixels.shape, str(frame.pixels.dtype))
                if layout is not None and layout != frame_layout:
                    raise ValueError("OME recording requires a fixed shape and dtype")
                layout = frame_layout
                record = {
                    field.name: getattr(frame, field.name)
                    for field in fields(frame)
                    if field.name != "pixels"
                }
                record["stage_position"] = asdict(frame.stage_position)
                record["channel"] = asdict(frame.channel) if frame.channel else None
                record.update(
                    type="frame",
                    page=frame.sequence,
                    shape=list(frame.pixels.shape),
                    dtype=str(frame.pixels.dtype),
                    sha256=pixel_hash(frame.pixels),
                )
                line = _json_line(record)
                if writer is None:
                    writer = self._tifffile.TiffWriter(self.raw_path, bigtiff=True, ome=False)
                writer.write(
                    frame.pixels,
                    contiguous=True,
                    photometric="minisblack",
                    metadata=None,
                    description="Incomplete acquisition" if not self.frames_written else None,
                )
                self._ledger.write(line)
                self.frames_written += 1
            if writer is not None and layout is not None:
                shape, dtype = layout
                ome = self._tifffile.OmeXml()
                ome.addimage(
                    dtype,
                    (self.frames_written, *shape),
                    (self.frames_written, 1, 1, shape[0], shape[1], 1),
                    axes="TYX",
                )
                writer.overwrite_description(ome.tostring())
        except Exception as exc:
            with self._lock:
                self._error = f"{type(exc).__name__}: {exc}"
        finally:
            try:
                if writer is not None:
                    writer.close()
            except Exception as exc:
                with self._lock:
                    self._error = self._error or f"{type(exc).__name__}: {exc}"
            try:
                self._ledger.flush()
                os.fsync(self._ledger.fileno())
            except Exception as exc:
                with self._lock:
                    self._error = self._error or f"{type(exc).__name__}: {exc}"
            finally:
                try:
                    self._ledger.close()
                except Exception as exc:
                    with self._lock:
                        self._error = self._error or f"{type(exc).__name__}: {exc}"
                finally:
                    self._done.set()

    def _join(self, timeout: float) -> None:
        with self._lock:
            self._accepting = False
        if not self._done.is_set() and not self._sentinel_sent:
            try:
                self._queue.put(None, timeout=timeout)
                self._sentinel_sent = True
            except Full as exc:
                raise TimeoutError("OME writer is still busy") from exc
        if not self._done.wait(timeout):
            raise TimeoutError("OME writer is still busy")

    def finish(
        self,
        result: RunResult,
        *,
        timeout: float = 30,
        device_status: Mapping[str, object] | None = None,
    ) -> RunResult:
        if self._finished:
            raise RuntimeError("recording already finished")
        self._join(timeout)
        error = self._error
        if result.frames_acquired != self.frames_submitted and result.state == "completed":
            error = error or "captured/submitted frame count mismatch"
        if self.frames_written != self.frames_submitted:
            error = error or "submitted/written frame count mismatch"
        if (
            result.state == "completed"
            and result.frames_requested is not None
            and self.frames_written != result.frames_requested
        ):
            error = error or "requested/written frame count mismatch"
        final_error = f"{result.error}; OME writer: {error}" if error and result.error else error
        final = replace(result, state="failed", error=final_error) if error else result
        if self.raw_path.exists() and not self._error:
            with self.raw_path.open("r+b") as raw:
                os.fsync(raw.fileno())
        manifest = {
            "schema_version": 1,
            "format": "ome-tiff",
            "axes": "TYX",
            "raw_file": "raw.ome.tif",
            "frames_written": self.frames_written,
            "frames_submitted": self.frames_submitted,
            "max_queue_depth": self.max_queue_depth,
            "ledger_sha256": _sha256(self.dataset_dir / "frames.jsonl"),
            "raw_integrity": "unverified_after_writer_error" if self._error else "ledger_hashes",
            "result": asdict(final),
            "device_status": dict(device_status or {}),
        }
        with (self.dataset_dir / "run_metadata.json").open("x", encoding="utf-8") as stream:
            stream.write(_json_line(manifest))
            stream.flush()
            os.fsync(stream.fileno())
        self.result = final
        self._finished = True
        return final

    def close(self, timeout: float = 30) -> None:
        """Drain/close without inventing completion; no manifest without finish."""
        self._join(timeout)


def replay_ome_frames(dataset_dir: Path) -> Iterator[Frame]:
    """Verify count, page order and pixels before yielding each recorded frame."""
    tifffile = importlib.import_module("tifffile")
    manifest = json.loads((dataset_dir / "run_metadata.json").read_text(encoding="utf-8"))
    ledger = dataset_dir / "frames.jsonl"
    if (
        manifest["schema_version"] != 1
        or manifest["format"] != "ome-tiff"
        or manifest["raw_integrity"] != "ledger_hashes"
        or manifest["axes"] != "TYX"
        or manifest["raw_file"] != "raw.ome.tif"
    ):
        raise ValueError("unsupported or failed OME recording")
    if _sha256(ledger) != manifest["ledger_sha256"]:
        raise ValueError("frame ledger checksum mismatch")
    with ledger.open(encoding="utf-8") as stream:
        header = json.loads(next(stream))
        if header["type"] != "dataset":
            raise ValueError("invalid ledger header")
        records = [json.loads(line) for line in stream]
    if len(records) != manifest["frames_written"]:
        raise ValueError("manifest/ledger count mismatch")
    if not records:
        return
    with tifffile.TiffFile(dataset_dir / "raw.ome.tif") as tiff:
        if len(tiff.pages) != len(records) or not tiff.is_ome:
            raise ValueError("OME page count/metadata mismatch")
        for index, record in enumerate(records):
            if record["page"] != index or record["sequence"] != index:
                raise ValueError("invalid frame/page sequence")
            pixels = tiff.pages[index].asarray()
            if (
                list(pixels.shape) != record["shape"]
                or str(pixels.dtype) != record["dtype"]
                or pixel_hash(pixels) != record["sha256"]
            ):
                raise ValueError("OME frame checksum/layout mismatch")
            yield Frame(
                pixels,
                Position(**record["stage_position"]),
                index,
                record["exposure_ms"],
                record["acquisition_start_ns"],
                record["acquisition_end_ns"],
                Channel(**record["channel"]) if record["channel"] else None,
                record["request_id"],
                record["target_id"],
                record["timepoint"],
                record["core_image_number"],
                record["camera_frame_number"],
                record["source_timestamp_ms"],
            )
