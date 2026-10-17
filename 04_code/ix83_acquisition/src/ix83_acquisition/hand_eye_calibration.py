"""Pycro-Manager persistence adapter for planner hand-eye calibration runs."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from .recording import _json_line, _sha256


def _jsonable(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        raise TypeError("raw arrays must be persisted as separate binary frame files")
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    raise TypeError(f"unsupported run-document value: {type(value).__name__}")


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    with path.open("x", encoding="utf-8") as stream:
        stream.write(_json_line(_jsonable(value)))
        stream.flush()
        os.fsync(stream.fileno())


class HandEyeCalibrationRecorder:
    """Persist raw calibration images and Bluesky docs, then analyze on stop.

    Subscribe this instance to the RunEngine. Each image is written once as a
    checksummed NPY file and its event fields are retained in a JSONL ledger.
    A terminal manifest is written only after the stop document arrives.
    """

    def __init__(self, root: Path, name: str) -> None:
        if not name or name in (".", "..") or Path(name).name != name or ":" in name:
            raise ValueError("record name must be a single directory name")
        root.mkdir(parents=True, exist_ok=True)
        suffix = 0
        while True:
            self.directory = root / (name if suffix == 0 else f"{name}_{suffix}")
            try:
                self.directory.mkdir()
                break
            except FileExistsError:
                suffix += 1
        self.images_dir = self.directory / "images"
        self.images_dir.mkdir()
        self._events = (self.directory / "events.jsonl").open("x", encoding="utf-8")
        self._start_doc: dict[str, Any] | None = None
        self._stop_doc: dict[str, Any] | None = None
        self._event_docs: list[dict[str, Any]] = []
        self._images: list[NDArray[np.generic]] = []
        self._closed = False

    def __call__(self, name: str, doc: Mapping[str, Any]) -> None:
        if self._closed:
            raise RuntimeError("calibration recorder is closed")
        if name == "start":
            if self._start_doc is not None:
                raise ValueError("recorder cannot accept more than one run")
            self._start_doc = dict(doc)
            _write_json(self.directory / "start.json", self._start_doc)
        elif name == "event":
            self._record_event(doc)
        elif name == "event_page":
            for event in self._expand_event_page(doc):
                self._record_event(event)
        elif name == "stop":
            self._finish(doc)

    def _record_event(self, doc: Mapping[str, Any]) -> None:
        if self._start_doc is None or self._stop_doc is not None:
            raise RuntimeError("calibration event arrived outside an active run")
        sequence = len(self._event_docs) + 1
        if int(doc.get("seq_num", -1)) != sequence:
            raise ValueError("calibration event sequence is not contiguous")
        data = dict(doc.get("data", {}))
        if "image" not in data:
            raise ValueError("calibration event is missing raw camera image")
        pixels = np.asarray(data.pop("image"))
        if pixels.ndim != 2 or pixels.dtype.kind not in "uif":
            raise ValueError("calibration image must be a numeric YX plane")
        filename = f"image_{sequence - 1:03d}.npy"
        image_path = self.images_dir / filename
        with image_path.open("xb") as stream:
            np.save(stream, pixels, allow_pickle=False)
            stream.flush()
            os.fsync(stream.fileno())
        record = {
            "seq_num": sequence,
            "time": _jsonable(doc["time"]),
            "descriptor": str(doc.get("descriptor", "")),
            "data": _jsonable(data),
            "timestamps": _jsonable(doc.get("timestamps", {})),
            "image_file": f"images/{filename}",
            "image_shape": list(pixels.shape),
            "image_dtype": str(pixels.dtype),
            "image_sha256": _sha256(image_path),
        }
        self._events.write(_json_line(record))
        self._events.flush()
        os.fsync(self._events.fileno())
        self._event_docs.append(record)
        self._images.append(pixels)

    @staticmethod
    def _expand_event_page(doc: Mapping[str, Any]) -> list[dict[str, Any]]:
        sequences = list(doc["seq_num"])
        times = list(doc["time"])
        count = len(sequences)
        data = doc["data"]
        timestamps = doc["timestamps"]
        if (
            len(times) != count
            or any(len(values) != count for values in data.values())
            or any(len(values) != count for values in timestamps.values())
        ):
            raise ValueError("event_page columns have inconsistent lengths")
        return [
            {
                "seq_num": sequences[index],
                "time": times[index],
                "descriptor": doc.get("descriptor", ""),
                "data": {key: values[index] for key, values in data.items()},
                "timestamps": {key: values[index] for key, values in timestamps.items()},
            }
            for index in range(count)
        ]

    def _finish(self, doc: Mapping[str, Any]) -> None:
        if self._start_doc is None or self._stop_doc is not None:
            raise RuntimeError("stop document arrived outside an active run")
        self._stop_doc = dict(doc)
        self._events.flush()
        os.fsync(self._events.fileno())
        self._events.close()
        _write_json(self.directory / "stop.json", self._stop_doc)
        analysis: dict[str, Any]
        try:
            # Imported here because the analysis pulls in OpenCV for image
            # registration; a missing extra is recorded as a failed analysis
            # instead of breaking recorder construction or import.
            from .hand_eye_analysis import analyze_hand_eye_run

            analysis_events = []
            for event in self._event_docs:
                normalized = dict(event)
                data = dict(event["data"])
                data["stage_position_xy"] = [
                    float(data["stage_x_pre_snap_um"]),
                    float(data["stage_y_pre_snap_um"]),
                ]
                normalized["data"] = data
                analysis_events.append(normalized)
            analysis = analyze_hand_eye_run(
                self._start_doc, analysis_events, self._stop_doc, self._images
            )
        except Exception as exc:
            analysis = {
                "schema_version": 1,
                "analysis_type": "stage-camera-hand-eye-calibration",
                "status": "analysis_failed",
                "accepted_for_scan_preflight": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
        _write_json(self.directory / "analysis.json", analysis)
        files = {}
        for path in sorted(item for item in self.directory.rglob("*") if item.is_file()):
            files[path.relative_to(self.directory).as_posix()] = _sha256(path)
        metadata = {
            "schema_version": 1,
            "record_type": "ix83-hand-eye-calibration-run",
            "event_count": len(self._event_docs),
            "stop_status": self._stop_doc.get("exit_status"),
            "analysis_status": analysis.get("status"),
            "files_sha256": files,
        }
        _write_json(self.directory / "run_metadata.json", metadata)
        self._closed = True

    def close(self) -> None:
        """Close an incomplete recorder without inventing a terminal manifest."""
        if not self._closed:
            self._events.close()
            self._closed = True
