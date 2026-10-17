"""Bundle host adapters for resolving typed dataset references."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from urllib.request import url2pathname

from planner import DatasetReference


def dataset_reference_from_record(value: Mapping[str, Any]) -> DatasetReference:
    """Rebuild a validated reference from a host journal record."""
    return DatasetReference(
        uri=str(value["uri"]),
        format=str(value["format"]),
        axes=str(value["axes"]),
        shape=tuple(int(size) for size in value["shape"]),
        dtype=str(value["dtype"]),
        frames_written=int(value["frames_written"]),
        terminal_status=str(value["terminal_status"]),
        manifest_sha256=str(value["manifest_sha256"]),
    )


def verify_local_dataset_reference(reference: DatasetReference, path: Path | None = None) -> Path:
    """Verify the reference digest and core metadata against a local dataset manifest."""
    dataset_path = path or _file_uri_path(reference)
    manifest_path = dataset_path / "run_metadata.json"
    manifest_bytes = manifest_path.read_bytes()
    if hashlib.sha256(manifest_bytes).hexdigest() != reference.manifest_sha256:
        raise ValueError("dataset manifest checksum does not match typed reference")
    metadata = json.loads(manifest_bytes)
    expected_format = "ome-tiff" if metadata.get("format") == "ome-tiff" else "npy-frames"
    expected_axes = "TYX" if expected_format == "ome-tiff" else "QYX"
    if reference.format != expected_format or reference.axes != expected_axes:
        raise ValueError("dataset format or axes do not match typed reference")
    if (
        metadata.get("axes") != expected_axes
        or metadata.get("frames_written") != reference.frames_written
    ):
        raise ValueError("dataset manifest shape/count metadata does not match typed reference")
    terminal = metadata.get("result", {}).get("state")
    if terminal != reference.terminal_status:
        raise ValueError("dataset terminal status does not match typed reference")
    return dataset_path


def local_dataset_path(reference: DatasetReference | str) -> Path:
    """Resolve and verify local references; remote schemes need another adapter."""
    # String references are accepted only for v1/v2 persisted records, where
    # the field was an untyped local path. New records must use typed references.
    if isinstance(reference, str):
        scheme = urlsplit(reference).scheme
        is_windows_drive_path = len(scheme) == 1 and reference[1:3] in {":\\", ":/"}
        if scheme and not is_windows_drive_path:
            raise ValueError("legacy string dataset references must be local paths")
        return Path(reference)
    return verify_local_dataset_reference(reference)


def _file_uri_path(reference: DatasetReference) -> Path:
    parsed = urlsplit(reference.uri)
    if parsed.scheme != "file":
        raise ValueError(f"dataset URI {parsed.scheme!r} is not available through local storage")
    path = url2pathname(parsed.path)
    if parsed.netloc:
        path = f"//{parsed.netloc}{path}"
    return Path(path)
