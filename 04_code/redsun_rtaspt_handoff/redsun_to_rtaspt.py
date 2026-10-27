#!/usr/bin/env python3
"""Adapt one saved Redsun snap store into a validated RTASPT search-scan handoff.

RTASPT has no Zarr image source. Pointing ``images.path`` at a saved store fails
verbatim with ``FileNotFoundError: image stack not found: ...stitched_stack.zarr``
(rehearsal 20261025T0830Z finding F5). This tool is the missing adapter. It reads
the store plus its ``redsun-planner.snap-position-association-v4`` sidecar and
writes, into one output directory:

* ``<store>_tiles.ome.tif`` - OME-TIFF, axes ``TYX``, one page per recorded frame,
  uncompressed so RTASPT's memmapped plane reader can serve it;
* ``frames.csv`` - ``frame,x_um,y_um,time_s`` in acquisition order, the table
  shape ``rtaspt-search-product-v1`` expects;
* ``request.yaml`` - a request whose ``order`` is **pinned** to ``as_given`` and
  which contains no section the schema would silently drop;
* ``provenance.json`` - source paths, digests, frame count, order mode, crop and
  the Redsun preprocessing id;
* ``handoff.json`` - the machine-readable record of the handoff.

Two measured traps drive the design, both from that rehearsal:

1. **``order`` silently corrupts placement** (finding F6). With ``serpentine`` or
   ``raster``, ``build_tiles`` numbers tiles by traversal while the detector keeps
   the frame-table row index; both are ``{0..N}``, so ``merge_duplicate_detections``
   accepts the join and places every detection on another tile's offset, with no
   error. A Redsun store is written in acquisition order, so the request always
   says ``as_given`` and the movie page ``i`` is table row ``i``. ``--order`` here
   reorders the *emitted* movie and table together (a reading-order convenience);
   it never changes the request's ``order`` field.
2. **The request schema silently drops what it cannot do** (finding F5). A request
   carrying ``anisotropy:`` or ``tracking:`` sections validates (exit 0) and the
   keys vanish from ``request_used.json``. This tool writes only keys that
   ``rtaspt.search_product.request_from_mapping`` actually reads, and refuses to
   write any other top-level key.

Reader choice: a single OME-TIFF with a leading ``T`` axis. ``TiffSeriesReader``
takes ``series[0].axes`` and needs a leading axis in ``{T, I}`` to treat the
leading dimension as frames; a page-at-a-time writer yields one one-page series
per call and the run fails with "only 1 physical TIFF pages are present"
(finding F5 / gap G2). One shaped write with ``axes='TYX'`` is also exactly what
RTASPT's own ``io.write_ome_stack`` produces.

No instrument, camera, stage, laser or GUI is touched: this reads recorded files.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import sys
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

TOOL_NAME = "redsun_to_rtaspt.py"
TOOL_VERSION = "1.1.0"
HANDOFF_SCHEMA = "redsun-rtaspt-handoff-v1"
PROVENANCE_SCHEMA = "redsun-rtaspt-provenance-v1"
SIDECAR_SCHEMA = "redsun-planner.snap-position-association-v4"
RTASPT_REQUEST_SCHEMA = "rtaspt-search-product-v1"

#: Top-level keys ``rtaspt.search_product.request_from_mapping`` reads.
#: Anything outside this set is dropped without an error (finding F5), so the
#: writer refuses to emit it. Mirrors ``src/rtaspt/search_product.py`` as of the
#: 2026-10-25 rehearsal; ``searchscan-validate`` prints the same normalized set.
RTASPT_REQUEST_KEYS = frozenset(
    {
        "kind",
        "frames",
        "searchscan",
        "spec",
        "transform",
        "tile_shape",
        "images",
        "window",
        "detection",
        "order",
        "lattice_spacing_um",
        "snap_to_lattice",
        "duplicates",
        "linking",
        "identity",
        "output",
        "coverage_arrays",
        "max_canvas_pixels",
        "notes",
    }
)

#: Dtypes a TIFF sample format can carry. Anything else is refused rather than
#: silently cast, which would change the recorded intensities.
TIFF_DTYPES = frozenset(
    {"uint8", "uint16", "uint32", "int8", "int16", "int32", "float32", "float64"}
)

DEFAULT_DATA_KEY = "mmcamera-buffer"
DEFAULT_POSITION_TOLERANCE_UM = 1.0
DEFAULT_DUPLICATE_GATE_PX = 6.0
DEFAULT_DETECTION_BACKEND = "trackpy"
DEFAULT_DETECTION_DIAMETER = 7
DEFAULT_DETECTION_MIN_MASS = 500.0
DEFAULT_DETECTION_MIN_AREA_PX = 1
BIGTIFF_THRESHOLD_BYTES = 3_000_000_000


class Refusal(RuntimeError):
    """A handoff that must not be written, with a stable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _log(message: str) -> None:
    print(f"[{TOOL_NAME}] {message}", file=sys.stderr, flush=True)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_tree(path: Path) -> str:
    """Digest a store by relative name and content of every file beneath it."""
    if path.is_file():
        return sha256_file(path)
    digest = hashlib.sha256()
    files = sorted(item for item in path.rglob("*") if item.is_file())
    for item in files:
        relative = item.relative_to(path).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        with item.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _float_text(value: float) -> str:
    """Render a float as a YAML scalar that loads back as a float.

    ``repr`` may emit ``1e-07``, which PyYAML's YAML-1.1 float resolver does not
    match, so the value would silently load as a string. Keep decimal notation.
    """
    text = np.format_float_positional(float(value), unique=True, trim="-")
    if "." not in text:
        text += ".0"
    return text


def _yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"refusing to write a non-finite float: {value!r}")
        return _float_text(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    raise TypeError(f"unsupported YAML scalar: {type(value).__name__}")


def _yaml_lines(value: Any, indent: int = 0) -> list[str]:
    pad = " " * indent
    if isinstance(value, Mapping):
        lines: list[str] = []
        for key, item in value.items():
            if isinstance(item, Mapping):
                lines.append(f"{pad}{key}:")
                lines.extend(_yaml_lines(item, indent + 2))
            elif isinstance(item, (list, tuple)):
                if _is_flow_list(item):
                    lines.append(f"{pad}{key}: [{', '.join(_yaml_scalar(v) for v in item)}]")
                else:
                    lines.append(f"{pad}{key}:")
                    lines.extend(_yaml_lines(item, indent + 2))
            else:
                lines.append(f"{pad}{key}: {_yaml_scalar(item)}")
        return lines
    if isinstance(value, (list, tuple)):
        lines = []
        for item in value:
            if isinstance(item, (list, tuple)):
                lines.append(f"{pad}- [{', '.join(_yaml_scalar(v) for v in item)}]")
            elif isinstance(item, Mapping):
                nested = _yaml_lines(item, indent + 2)
                lines.append(f"{pad}- {nested[0].strip()}")
                lines.extend(nested[1:])
            else:
                lines.append(f"{pad}- {_yaml_scalar(item)}")
        return lines
    return [f"{pad}{_yaml_scalar(value)}"]


def _is_flow_list(value: Sequence[Any]) -> bool:
    if not value:
        return True
    if any(isinstance(item, (Mapping, list, tuple)) for item in value):
        return False
    rendered = ", ".join(_yaml_scalar(item) for item in value)
    return len(rendered) <= 88


def dump_yaml(mapping: Mapping[str, Any], header: Iterable[str] = ()) -> str:
    lines = [f"# {line}".rstrip() for line in header]
    if lines:
        lines.append("")
    lines.extend(_yaml_lines(mapping))
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Store and sidecar
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StoreInfo:
    path: Path
    array_key: str
    shape: tuple[int, ...]
    dtype: str
    chunks: Any
    array: Any

    @property
    def frames(self) -> int:
        return int(self.shape[0])

    @property
    def plane_shape(self) -> tuple[int, int]:
        return int(self.shape[-2]), int(self.shape[-1])


def resolve_store(store: Path, data_key: str | None, sidecar_key: str | None) -> StoreInfo:
    """Open the Zarr store and resolve the one image array it carries."""
    import zarr

    if not store.exists():
        raise Refusal("E-STORE-MISSING", f"saved store not found: {store}")
    try:
        node = zarr.open(str(store), mode="r")
    except Exception as exc:  # noqa: BLE001 - surface any zarr open failure
        raise Refusal(
            "E-STORE-NODE",
            f"{store} is not a readable Zarr array or group: {type(exc).__name__}: {exc}",
        ) from exc

    if isinstance(node, zarr.Array):
        array = node
        raw = str(getattr(node, "path", "") or "").strip("/")
        if raw in {"", "."}:
            name = store.name
            key = name[: -len(".zarr")] if name.lower().endswith(".zarr") else name
        else:
            key = Path(raw).name
        if data_key is not None and data_key != key:
            raise Refusal(
                "E-DATA-KEY",
                f"--data-key {data_key!r} but {store} is itself the array {key!r}; "
                "pass the store group to select a member by key",
            )
        if sidecar_key is not None and sidecar_key != key:
            raise Refusal(
                "E-DATA-KEY",
                f"sidecar data_key {sidecar_key!r} does not match the array {key!r} at {store}",
            )
        return StoreInfo(store, key, tuple(array.shape), str(array.dtype), array.chunks, array)

    if not isinstance(node, zarr.Group):
        raise Refusal("E-STORE-NODE", f"{store} resolved to {type(node).__name__}, not an array")

    keys = sorted(str(name) for name in node.array_keys())
    if not keys:
        raise Refusal("E-STORE-NODE", f"{store} is a Zarr group with no image array")
    wanted = data_key or sidecar_key
    if wanted is None:
        if len(keys) != 1:
            raise Refusal(
                "E-DATA-KEY",
                f"{store} holds {len(keys)} arrays ({', '.join(keys)}); pass --data-key",
            )
        wanted = keys[0]
    if wanted not in keys:
        raise Refusal(
            "E-DATA-KEY",
            f"data key {wanted!r} is not in {store}; available: {', '.join(keys)}",
        )
    if data_key is not None and sidecar_key is not None and data_key != sidecar_key:
        raise Refusal(
            "E-DATA-KEY",
            f"--data-key {data_key!r} contradicts the sidecar data_key {sidecar_key!r}",
        )
    array = node[wanted]
    if not isinstance(array, zarr.Array):
        raise Refusal("E-STORE-NODE", f"{store}:{wanted} is a group, not an image array")
    return StoreInfo(
        store, wanted, tuple(array.shape), str(array.dtype), array.chunks, array
    )


def check_dtype_and_shape(info: StoreInfo) -> None:
    """Refuse a store whose dtype or shape a TIFF cannot carry."""
    if info.dtype not in TIFF_DTYPES:
        raise Refusal(
            "E-DTYPE",
            f"store dtype {info.dtype!r} has no TIFF sample format that keeps the "
            f"recorded values; supported: {', '.join(sorted(TIFF_DTYPES))}",
        )
    if len(info.shape) != 3:
        raise Refusal(
            "E-SHAPE",
            f"store shape {info.shape} is not (frames, height, width); a TIFF movie "
            "page per frame needs exactly three axes",
        )
    frames, height, width = info.shape
    if frames < 1 or height < 1 or width < 1:
        raise Refusal("E-SHAPE", f"store shape {info.shape} has an empty axis")


@dataclass(frozen=True)
class SidecarFrame:
    array_index: int
    time_s: float
    x_um: float
    y_um: float


@dataclass(frozen=True)
class Sidecar:
    path: Path
    sha256: str
    schema: str
    data_key: str | None
    run_uid: str | None
    exit_status: str | None
    frames_written: int | None
    stage_coordinate_basis: str | None
    stage_readback_keys: Mapping[str, Any]
    camera: Mapping[str, Any]
    frames: tuple[SidecarFrame, ...]


def load_sidecar(path: Path) -> Sidecar:
    if not path.is_file():
        raise Refusal("E-SIDECAR-MISSING", f"positions sidecar not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise Refusal(
            "E-SIDECAR-MISSING", f"{path} is not valid JSON: {exc}"
        ) from exc
    if not isinstance(payload, Mapping):
        raise Refusal("E-SIDECAR-SCHEMA", f"{path} does not contain a JSON object")
    schema = str(payload.get("schema", ""))
    if schema != SIDECAR_SCHEMA:
        raise Refusal(
            "E-SIDECAR-SCHEMA",
            f"{path} declares schema {schema!r}; this adapter reads {SIDECAR_SCHEMA!r} "
            "(its stage_xy_um / array_index / time fields). Re-export the run or "
            "extend the reader before handing it off.",
        )
    raw_frames = payload.get("frames")
    if not isinstance(raw_frames, list) or not raw_frames:
        raise Refusal("E-SIDECAR-SCHEMA", f"{path} has no non-empty 'frames' list")
    frames: list[SidecarFrame] = []
    for position, row in enumerate(raw_frames):
        if not isinstance(row, Mapping):
            raise Refusal("E-SIDECAR-SCHEMA", f"{path}: frames[{position}] is not an object")
        try:
            index = int(row["array_index"])
            time_s = float(row["time"])
        except (KeyError, TypeError, ValueError) as exc:
            raise Refusal(
                "E-SIDECAR-SCHEMA",
                f"{path}: frames[{position}] needs numeric 'array_index' and 'time' ({exc})",
            ) from exc
        xy = row.get("stage_xy_um")
        if isinstance(xy, Mapping):
            xy = (xy.get("x"), xy.get("y"))
        if not isinstance(xy, (list, tuple)) or len(xy) != 2:
            raise Refusal(
                "E-SIDECAR-SCHEMA",
                f"{path}: frames[{position}].stage_xy_um is not a two-value [x, y]",
            )
        try:
            x_um, y_um = float(xy[0]), float(xy[1])
        except (TypeError, ValueError) as exc:
            raise Refusal(
                "E-SIDECAR-SCHEMA",
                f"{path}: frames[{position}].stage_xy_um is not numeric ({exc})",
            ) from exc
        if not (math.isfinite(x_um) and math.isfinite(y_um) and math.isfinite(time_s)):
            raise Refusal(
                "E-POSITION-NONFINITE",
                f"{path}: frames[{position}] has a non-finite stage coordinate or time",
            )
        frames.append(SidecarFrame(index, time_s, x_um, y_um))

    camera = {
        "name": payload.get("camera_name"),
        "binning_xy": payload.get("camera_binning_xy"),
        "exposure_ms": payload.get("camera_exposure_ms"),
        "roi_binned_pixels": payload.get("camera_roi_binned_pixels"),
        "roi_sensor_pixels": payload.get("camera_roi_sensor_pixels"),
    }
    written = payload.get("frames_written")
    return Sidecar(
        path=path,
        sha256=sha256_file(path),
        schema=schema,
        data_key=None if payload.get("data_key") is None else str(payload["data_key"]),
        run_uid=None if payload.get("run_uid") is None else str(payload["run_uid"]),
        exit_status=None if payload.get("exit_status") is None else str(payload["exit_status"]),
        frames_written=None if written is None else int(written),
        stage_coordinate_basis=(
            None
            if payload.get("stage_coordinate_basis") is None
            else str(payload["stage_coordinate_basis"])
        ),
        stage_readback_keys=dict(payload.get("stage_readback_keys") or {}),
        camera=camera,
        frames=tuple(frames),
    )


def check_sidecar_against_store(
    sidecar: Sidecar, info: StoreInfo
) -> tuple[tuple[SidecarFrame, ...], list[str]]:
    """Cross-check frame counts, frame identity, ordering and camera geometry."""
    warnings: list[str] = []
    if sidecar.exit_status is not None and sidecar.exit_status != "success":
        raise Refusal(
            "E-SIDECAR-STATUS",
            f"{sidecar.path} records run exit_status {sidecar.exit_status!r}; an "
            "interrupted snap run does not describe the frames that were written",
        )
    if sidecar.frames_written is not None and sidecar.frames_written != info.frames:
        raise Refusal(
            "E-FRAME-COUNT",
            f"store holds {info.frames} frames but the sidecar records "
            f"frames_written={sidecar.frames_written}",
        )
    if len(sidecar.frames) != info.frames:
        raise Refusal(
            "E-FRAME-COUNT",
            f"store holds {info.frames} frames but {sidecar.path} lists "
            f"{len(sidecar.frames)} position records",
        )
    indices = [frame.array_index for frame in sidecar.frames]
    if sorted(indices) != list(range(info.frames)):
        duplicates = sorted({value for value in indices if indices.count(value) > 1})
        detail = f"duplicated array_index {duplicates}" if duplicates else "not 0..N-1"
        raise Refusal(
            "E-FRAME-INDEX",
            f"{sidecar.path} array_index values are {detail}; the frame table must "
            "pair page i with step i of the acquisition",
        )
    frames = tuple(sorted(sidecar.frames, key=lambda frame: frame.array_index))

    diffs = np.diff(np.array([frame.time_s for frame in frames], dtype=float))
    if diffs.size:
        if np.all(diffs > 0):
            pass
        elif np.all(diffs == 0):
            warnings.append(
                "the sidecar records one identical time for every frame, so page "
                "order rests on the stage path only"
            )
        elif np.all(diffs < 0):
            raise Refusal(
                "E-TIME-ORDER",
                f"{sidecar.path} time stamps decrease with array_index; the store is "
                "not in acquisition order, so page i is not table row i",
            )
        else:
            raise Refusal(
                "E-TIME-ORDER",
                f"{sidecar.path} time stamps are not monotonic with array_index "
                f"({diffs.min():.3f}..{diffs.max():.3f} s steps); the recorded order "
                "cannot be trusted as acquisition order",
            )

    roi = sidecar.camera.get("roi_binned_pixels")
    if isinstance(roi, Mapping) and roi.get("height") and roi.get("width"):
        height, width = info.plane_shape
        if int(roi["height"]) != height or int(roi["width"]) != width:
            raise Refusal(
                "E-ROI",
                f"store plane is {height}x{width} but the sidecar camera ROI is "
                f"{int(roi['height'])}x{int(roi['width'])} binned pixels; the store "
                "and the sidecar describe different camera modes",
            )
    return frames, warnings


# ---------------------------------------------------------------------------
# Lattice and acquisition-order validation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Layout:
    """The stage lattice and the traversal that produced the recorded order."""

    n_slow: int
    n_fast: int
    fast_axis: str
    slow_idx: np.ndarray
    fast_idx: np.ndarray
    traversal: str
    x_centres: np.ndarray
    y_centres: np.ndarray
    x_spacing: float
    y_spacing: float
    spread_um: float

    def grid(self) -> str:
        if self.fast_axis == "y":
            return f"{self.n_slow} x {self.n_fast} (x by y, y fastest)"
        return f"{self.n_slow} x {self.n_fast} (y by x, x fastest)"

    def stage_coordinates(self) -> tuple[np.ndarray, np.ndarray]:
        return self.x_centres, self.y_centres


def _cluster_axis(values: np.ndarray, tolerance: float) -> tuple[np.ndarray, np.ndarray, float]:
    order = np.argsort(values, kind="stable")
    ordered = values[order]
    labels = np.zeros(ordered.size, dtype=int)
    for position in range(1, ordered.size):
        step = ordered[position] - ordered[position - 1]
        labels[position] = labels[position - 1] + (1 if step > tolerance else 0)
    centres = np.array(
        [float(ordered[labels == node].mean()) for node in range(int(labels[-1]) + 1)]
    )
    out = np.empty(values.size, dtype=int)
    out[order] = labels
    spread = max(
        (float(np.max(np.abs(values[out == node] - centres[node]))) for node in range(centres.size)),
        default=0.0,
    )
    return out, centres, spread


def _traversal(
    fast_axis: str, fast_idx: np.ndarray, n_fast: int, slow_idx: np.ndarray, n_slow: int
) -> tuple[str, int, int] | None:
    """Return (traversal, n_slow, n_fast) when the order is a real grid walk."""
    count = fast_idx.size
    if n_fast < 1 or count % n_fast:
        return None
    n_blocks = count // n_fast
    if n_blocks != n_slow:
        return None
    fast = fast_idx.reshape(n_blocks, n_fast)
    slow = slow_idx.reshape(n_blocks, n_fast)
    if not np.all(slow == slow[:, :1]):
        return None
    slow_sequence = slow[:, 0]
    if np.unique(slow_sequence).size != n_slow:
        return None
    if n_blocks > 1 and not np.all(np.abs(np.diff(slow_sequence)) == 1):
        return None
    directions: list[int] = []
    for block in range(n_blocks):
        row = fast[block]
        if np.unique(row).size != n_fast:
            return None
        steps = np.diff(row)
        if steps.size and not np.all(np.abs(steps) == 1):
            return None
        directions.append(1 if (steps.size == 0 or steps[0] > 0) else -1)
    same = all(value == directions[0] for value in directions)
    alternating = all(
        value == directions[0] * (-1) ** index for index, value in enumerate(directions)
    )
    if same:
        return "raster", n_slow, n_fast
    if alternating:
        return "serpentine", n_slow, n_fast
    return None


def analyse_lattice(points: np.ndarray, tolerance: float) -> Layout:
    """Prove the recorded positions are one complete grid walked in order."""
    count = points.shape[0]
    x_idx, x_centres, x_spread = _cluster_axis(points[:, 0], tolerance)
    y_idx, y_centres, y_spread = _cluster_axis(points[:, 1], tolerance)
    n_x, n_y = int(x_centres.size), int(y_centres.size)
    if n_x * n_y != count:
        nodes = len({(int(a), int(b)) for a, b in zip(x_idx.tolist(), y_idx.tolist())})
        if nodes < count:
            raise Refusal(
                "E-POSITION-DUPLICATE",
                f"{count} frames map onto only {nodes} lattice nodes at a "
                f"{tolerance:g} um tolerance ({n_x} x {n_y}); two or more frames "
                "share a stage position, so tile placement is ambiguous",
            )
        raise Refusal(
            "E-LATTICE",
            f"{count} frames do not fill a rectangle: {n_x} distinct x values x "
            f"{n_y} distinct y values = {n_x * n_y} nodes",
        )
    nodes = {(int(a), int(b)) for a, b in zip(x_idx.tolist(), y_idx.tolist())}
    if len(nodes) != count:
        raise Refusal(
            "E-POSITION-DUPLICATE",
            f"{count} frames occupy only {len(nodes)} distinct lattice nodes; a "
            "grid frame must not repeat a stage position",
        )

    chosen: tuple[str, int, int] | None = None
    fast_axis = "y"
    for candidate_axis, fast_idx, n_fast, slow_idx, n_slow in (
        ("y", y_idx, n_y, x_idx, n_x),
        ("x", x_idx, n_x, y_idx, n_y),
    ):
        found = _traversal(candidate_axis, fast_idx, n_fast, slow_idx, n_slow)
        if found is not None:
            chosen = found
            fast_axis = candidate_axis
            break
    if chosen is None:
        raise Refusal(
            "E-POSITION-TRAVERSAL",
            f"the {count} recorded stage positions fill a {n_x} x {n_y} grid but do "
            "not walk it in a raster or serpentine order: consecutive frames are not "
            "adjacent lattice nodes with a constant or alternating fast-axis "
            "direction. A store whose array order is not its acquisition order "
            "cannot be handed off with order: as_given.",
        )
    traversal, n_slow, n_fast = chosen
    x_spacing = (
        float((x_centres[-1] - x_centres[0]) / (n_x - 1)) if n_x > 1 else 0.0
    )
    y_spacing = (
        float((y_centres[-1] - y_centres[0]) / (n_y - 1)) if n_y > 1 else 0.0
    )
    return Layout(
        n_slow=n_slow,
        n_fast=n_fast,
        fast_axis=fast_axis,
        slow_idx=x_idx if fast_axis == "y" else y_idx,
        fast_idx=y_idx if fast_axis == "y" else x_idx,
        traversal=traversal,
        x_centres=x_centres,
        y_centres=y_centres,
        x_spacing=x_spacing,
        y_spacing=y_spacing,
        spread_um=max(x_spread, y_spread),
    )


def emission_order(layout: Layout, mode: str) -> list[int]:
    """Frame indices in the requested reading order (page i pairs with row i)."""
    count = int(layout.fast_idx.size)
    if mode == "as_given":
        return list(range(count))
    lookup = {
        (int(layout.slow_idx[frame]), int(layout.fast_idx[frame])): frame
        for frame in range(count)
    }
    order: list[int] = []
    for slow in range(layout.n_slow):
        descend = mode == "serpentine" and slow % 2 == 1
        fast_values = range(layout.n_fast)
        if descend:
            fast_values = range(layout.n_fast - 1, -1, -1)
        for fast in fast_values:
            order.append(lookup[(slow, int(fast))])
    return order


# ---------------------------------------------------------------------------
# Transform declaration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TransformChoice:
    matrix: tuple[tuple[float, float, float], tuple[float, float, float]]
    source: str
    calibration_id: str
    detail: Mapping[str, Any]
    warnings: tuple[str, ...] = ()


def parse_matrix(text: str) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    try:
        rows = [row.strip() for row in text.replace("|", ";").split(";") if row.strip()]
        if len(rows) != 2:
            raise ValueError("expected two rows")
        values = [[float(item) for item in row.replace(",", " ").split()] for row in rows]
    except ValueError as exc:
        raise Refusal(
            "E-TRANSFORM-MATRIX",
            f"--transform-matrix {text!r} is not two rows of three numbers ({exc})",
        ) from exc
    return _checked_matrix(values)


def _checked_matrix(
    values: Sequence[Sequence[float]],
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    if len(values) != 2 or any(len(row) != 3 for row in values):
        raise Refusal(
            "E-TRANSFORM-MATRIX", "the stage-to-pixel matrix must be two rows of three values"
        )
    rows = [[float(item) for item in row] for row in values]
    if not all(math.isfinite(item) for row in rows for item in row):
        raise Refusal("E-TRANSFORM-MATRIX", "the matrix has a non-finite value")
    (a, b, _), (d, e, _) = rows
    if abs(a * e - b * d) <= 1e-12:
        raise Refusal(
            "E-TRANSFORM-MATRIX",
            "the matrix linear part is singular: it cannot place tiles",
        )
    return (rows[0][0], rows[0][1], rows[0][2]), (rows[1][0], rows[1][1], rows[1][2])


def transform_from_scale(
    scale_text: str, rotation_deg: float, flip_x: bool, flip_y: bool, offset_px: Sequence[float]
) -> TransformChoice:
    try:
        parts = [float(item) for item in scale_text.replace("x", ",").split(",")]
    except ValueError as exc:
        raise Refusal(
            "E-TRANSFORM-MATRIX", f"--scale-px-per-um {scale_text!r} is not numeric ({exc})"
        ) from exc
    if len(parts) == 1:
        scale_x = scale_y = parts[0]
    elif len(parts) == 2:
        scale_x, scale_y = parts
    else:
        raise Refusal(
            "E-TRANSFORM-MATRIX", "--scale-px-per-um takes one value or two comma-separated values"
        )
    if not (math.isfinite(scale_x) and math.isfinite(scale_y)) or scale_x <= 0 or scale_y <= 0:
        raise Refusal("E-TRANSFORM-MATRIX", "a pixel scale must be finite and positive")
    sign_x = -1.0 if flip_x else 1.0
    sign_y = -1.0 if flip_y else 1.0
    angle = math.radians(float(rotation_deg))
    cos, sin = math.cos(angle), math.sin(angle)
    matrix = _checked_matrix(
        [
            [sign_x * scale_x * cos, -sign_y * scale_y * sin, float(offset_px[0])],
            [sign_x * scale_x * sin, sign_y * scale_y * cos, float(offset_px[1])],
        ]
    )
    digest = hashlib.sha256(
        json.dumps([[list(row) for row in matrix]], sort_keys=True).encode("utf-8")
    ).hexdigest()[:12]
    return TransformChoice(
        matrix=matrix,
        source="declared-scale",
        calibration_id=f"declared-scale-{scale_x:g}x{scale_y:g}px-per-um-{digest}",
        detail={
            "scale_px_per_um": [scale_x, scale_y],
            "rotation_deg": float(rotation_deg),
            "flip_x": bool(flip_x),
            "flip_y": bool(flip_y),
            "offset_px": [float(offset_px[0]), float(offset_px[1])],
        },
    )


def transform_from_calibration(record_path: Path, info: StoreInfo) -> TransformChoice:
    """Use a Redsun hand-eye calibration record's placement matrix, with mode checks."""
    if not record_path.is_file():
        raise Refusal("E-TRANSFORM-MISSING", f"calibration record not found: {record_path}")
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise Refusal(
            "E-TRANSFORM-MISSING", f"{record_path} is not valid JSON: {exc}"
        ) from exc
    warnings: list[str] = []
    fit = record.get("fit") if isinstance(record, Mapping) else None
    coordinate_frame = None
    if isinstance(record, Mapping):
        coordinate_frame = record.get("coordinate_frame")
    if coordinate_frame is None and isinstance(fit, Mapping):
        coordinate_frame = fit.get("coordinate_frame")
    matrix_values = None
    if isinstance(fit, Mapping):
        matrix_values = fit.get("mosaic_placement_px_per_stage_unit")
    if matrix_values is None and isinstance(record, Mapping):
        matrix_values = record.get("mosaic_placement_px_per_stage_unit")
    if not isinstance(matrix_values, Sequence) or len(matrix_values) != 2:
        raise Refusal(
            "E-TRANSFORM-MISSING",
            f"{record_path} has no fit.mosaic_placement_px_per_stage_unit 2x2 matrix; "
            "a content-motion fit is the inverse placement, so it cannot be used "
            "without flipping it",
        )
    linear = [[float(value) for value in row] for row in matrix_values]
    if any(len(row) != 2 for row in linear):
        raise Refusal("E-TRANSFORM-MATRIX", f"{record_path} placement matrix is not 2x2")
    matrix = _checked_matrix([[linear[0][0], linear[0][1], 0.0], [linear[1][0], linear[1][1], 0.0]])

    frame = coordinate_frame
    mode = record.get("mode_context") if isinstance(record, Mapping) else None
    if isinstance(mode, Mapping):
        camera = mode.get("camera")
        if camera and camera != info.array_key.split("-")[0]:
            warnings.append(
                f"calibration camera {camera!r} differs from the store data key "
                f"{info.array_key!r}"
            )
        roi = str(mode.get("camera_roi") or "")
        height, width = info.plane_shape
        if roi:
            parts = [item.strip() for item in roi.split(",")]
            if len(parts) == 4:
                try:
                    roi_w, roi_h = int(parts[2]), int(parts[3])
                except ValueError:
                    roi_w = roi_h = -1
                if (roi_w, roi_h) != (width, height):
                    warnings.append(
                        f"calibration camera_roi {roi!r} differs from the store plane "
                        f"{width}x{height}"
                    )
        if mode.get("camera_exposure_ms") in {None, "unknown"}:
            warnings.append(
                "the calibration record does not state camera_exposure_ms, so the "
                "transform is not matched to this exposure"
            )
    calibration_id = (
        fit.get("calibration_id") if isinstance(fit, Mapping) else None
    ) or f"hand-eye-{sha256_file(record_path)[:12]}"
    return TransformChoice(
        matrix=matrix,
        source=f"calibration-record:{record_path.name}",
        calibration_id=str(calibration_id),
        detail={
            "record": str(record_path),
            "record_sha256": sha256_file(record_path),
            "calibration_id": str(calibration_id),
            "coordinate_frame": frame,
            "basis": "fit.mosaic_placement_px_per_stage_unit (placement, not content motion)",
        },
        warnings=tuple(warnings),
    )


def discover_registration(sidecar: Sidecar, search_root: Path) -> Mapping[str, Any] | None:
    """Find a mosaic report beside the store that names *this* sidecar.

    The match is the report's own ``source_positions_path`` (and its
    ``source_sidecar_sha256`` when present), not a filename convention, so a
    report for another stack in the same tree cannot be picked up. A match whose
    recorded sidecar digest differs is returned with ``stale_sidecar`` set: it
    must not be used for a transform fit.
    """
    candidates: list[Path] = []
    seen: set[Path] = set()
    root = search_root.resolve()
    for depth in range(5):
        level = root
        for _ in range(depth):
            if level.parent == level:
                break
            level = level.parent
        if level in seen:
            continue
        seen.add(level)
        if (level / ".git").exists():
            # A run's artifacts live inside its own tree, never at a repository
            # root; stop rather than scanning every sibling checkout.
            break
        for pattern in ("*.json", "*/*.json", "*/mosaic/*.json", "*/calibrated/*.json"):
            for candidate in sorted(level.glob(pattern)):
                if candidate.is_file() and candidate not in candidates:
                    candidates.append(candidate)
    matches: list[dict[str, Any]] = []
    for candidate in candidates[:400]:
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, Mapping):
            continue
        source = payload.get("source_positions_path")
        if not isinstance(source, str) or not source:
            continue
        if "frame_placements_file" not in payload and "registration_id" not in payload:
            continue
        try:
            same = Path(source).resolve() == sidecar.path.resolve()
        except OSError:
            same = False
        if not same:
            continue
        recorded_sha = payload.get("source_sidecar_sha256")
        matches.append(
            {
                "report_path": candidate,
                "report": payload,
                "stale_sidecar": bool(recorded_sha) and recorded_sha != sidecar.sha256,
                "recorded_sidecar_sha256": recorded_sha,
            }
        )
    if not matches:
        return None
    # A mosaic report carries the placement table the fit needs; a registration
    # record names the same sidecar but only holds its own pair graph.
    matches.sort(
        key=lambda match: (
            0 if match["report"].get("frame_placements_file") else 1,
            1 if match["stale_sidecar"] else 0,
        )
    )
    return matches[0]


def fit_transform_from_placements(
    registration: Mapping[str, Any],
    frames: Sequence[SidecarFrame],
    tolerance_um: float,
) -> TransformChoice:
    """Least-squares stage->pixel affine from the saved registration origins."""
    if registration.get("stale_sidecar"):
        raise Refusal(
            "E-REGISTRATION-STALE",
            f"{Path(registration['report_path'])} registers a sidecar at this path "
            f"but with sha256 {registration.get('recorded_sidecar_sha256')}; the "
            "sidecar on disk is different. Re-run registration rather than fitting "
            "a stale placement.",
        )
    report_path = Path(registration["report_path"])
    report = registration["report"]
    placements_name = report.get("frame_placements_file")
    if not isinstance(placements_name, str) or not placements_name:
        raise Refusal(
            "E-REGISTRATION-STALE",
            f"{report_path} names no frame_placements_file, so the registration "
            "origins needed for a transform fit are not available",
        )
    placements_path = report_path.with_name(placements_name)
    if not placements_path.is_file():
        raise Refusal(
            "E-REGISTRATION-STALE", f"placement table not found: {placements_path}"
        )
    origins: dict[int, tuple[float, float]] = {}
    with placements_path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                index = int(row["frame_index"])
                origin = (
                    float(row["registration_origin_x_px"]),
                    float(row["registration_origin_y_px"]),
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise Refusal(
                    "E-REGISTRATION-STALE",
                    f"{placements_path} needs frame_index and registration_origin_*_px ({exc})",
                ) from exc
            if index in origins:
                raise Refusal(
                    "E-REGISTRATION-STALE", f"{placements_path} repeats frame {index}"
                )
            origins[index] = origin
    expected = list(range(len(frames)))
    if sorted(origins) != expected:
        raise Refusal(
            "E-REGISTRATION-STALE",
            f"{placements_path} covers {len(origins)} frames {sorted(origins)[:3]}..."
            f"{sorted(origins)[-3:]} but the store has {len(frames)} frames 0..N-1; "
            "the placement belongs to another stack",
        )

    anchor_x, anchor_y = frames[0].x_um, frames[0].y_um
    dx = np.array([frame.x_um - anchor_x for frame in frames], dtype=float)
    dy = np.array([frame.y_um - anchor_y for frame in frames], dtype=float)
    target_x = np.array([origins[index][0] for index in expected], dtype=float)
    target_y = np.array([origins[index][1] for index in expected], dtype=float)
    design = np.column_stack((dx, dy, np.ones_like(dx)))
    coefficients, *_ = np.linalg.lstsq(design, np.column_stack((target_x, target_y)), rcond=None)
    matrix = _checked_matrix(
        [
            [coefficients[0, 0], coefficients[1, 0], coefficients[2, 0]],
            [coefficients[0, 1], coefficients[1, 1], coefficients[2, 1]],
        ]
    )
    residual_x = design @ coefficients[:, 0] - target_x
    residual_y = design @ coefficients[:, 1] - target_y
    norm = np.hypot(residual_x, residual_y)
    linear = np.array(
        [[matrix[0][0], matrix[0][1]], [matrix[1][0], matrix[1][1]]], dtype=float
    )
    singular = np.linalg.svd(linear, compute_uv=False)
    registration_id = report.get("registration_id")
    label = (
        f"mosaic-affine-fit-from-registration-{str(registration_id)[:12]}"
        if registration_id
        else f"mosaic-affine-fit-from-{report_path.stem}-{sha256_file(placements_path)[:12]}"
    )
    edge = report.get("edge_residual_summary_px")
    warnings: list[str] = []
    if tolerance_um > 0 and float(norm.max()) > 3.0:
        warnings.append(
            f"the fitted transform leaves a {float(norm.max()):.2f} px worst-case "
            "placement residual; check the registration before trusting placement"
        )
    graph = report.get("placement_graph")
    if isinstance(graph, Mapping) and int(graph.get("component_count", 1)) > 1:
        warnings.append(
            f"the registration graph has {graph.get('component_count')} components; "
            "tiles in other components are not placed relative to the first"
        )
    return TransformChoice(
        matrix=matrix,
        source=f"registration-fit:{report_path.name}",
        calibration_id=label,
        detail={
            "report": str(report_path),
            "report_sha256": sha256_file(report_path),
            "placements": str(placements_path),
            "placements_sha256": sha256_file(placements_path),
            "registration_id": registration_id,
            "edge_residual_rms_px": (
                edge.get("rms") if isinstance(edge, Mapping) else None
            ),
            "fit_residual_rms_px": [
                float(np.sqrt(np.mean(residual_x**2))),
                float(np.sqrt(np.mean(residual_y**2))),
            ],
            "fit_residual_max_px": float(norm.max()),
            "fit_singular_values_px_per_um": [float(value) for value in singular],
            "anchor_stage_um": [anchor_x, anchor_y],
            "method": "ordinary least squares on registration origins vs stage deltas",
        },
        warnings=tuple(warnings),
    )


# ---------------------------------------------------------------------------
# Redsun preprocessing id
# ---------------------------------------------------------------------------


def resolve_preprocessing_id(
    sidecar: Sidecar, explicit: str | None, registration: Mapping[str, Any] | None
) -> tuple[str | None, str, list[str]]:
    """Resolve the Redsun preprocessing id this store's frames were saved with.

    The ``snap-position-association-v4`` sidecar records no preprocessing claim,
    so the only honest sources are an operator declaration or the registration
    record that consumed this exact sidecar.
    """
    if explicit:
        return explicit, "cli", []
    if registration is not None:
        report_path = Path(registration["report_path"])
        record_path = registration["report"].get("registration_record_path")
        candidates: list[Path] = []
        if isinstance(record_path, str) and record_path:
            candidates.append(Path(record_path))
        candidates.append(report_path.with_name(f"{registration['report'].get('registration_id', '')}.json"))
        for candidate in candidates:
            if not candidate.is_file():
                continue
            try:
                payload = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            fit = payload.get("fit_parameters") if isinstance(payload, Mapping) else None
            value = None
            if isinstance(fit, Mapping):
                value = fit.get("preprocessing_id")
            if value is None and isinstance(payload, Mapping):
                value = payload.get("preprocessing_id")
            if value:
                return str(value), f"registration-record:{candidate}", []
        return (
            None,
            f"unrecorded:{report_path.name} names no registration record",
            [
                "the mosaic report beside the store does not resolve to a registration "
                "record, so no Redsun preprocessing id can be stated"
            ],
        )
    return (
        None,
        "unrecorded:no registration record and no --preprocessing-id",
        [
            "no registration record sits beside the store and no --preprocessing-id "
            "was given, so the handoff states no Redsun preprocessing id rather than "
            "assuming one"
        ],
    )


# ---------------------------------------------------------------------------
# Request, provenance and handoff documents
# ---------------------------------------------------------------------------


def detection_declaration(options: argparse.Namespace) -> dict[str, Any]:
    """The ``detection`` block: backend plus the options that backend reads.

    ``threshold``/``min_area_px``/``max_area_px`` belong to RTASPT's ``region``
    backend (explicit threshold or Otsu, 8-connected components, area band). They
    are recorded for every backend because the product record and this request
    are the reproducibility evidence, and an unused-but-declared parameter is
    clearer than one that appears only in some requests. The three flags are
    validated here so an impossible area band is refused before anything is
    written, rather than by RTASPT after the movie has been emitted.
    """
    backend = str(options.detection_backend)
    if backend not in {"trackpy", "gaussian", "region"}:
        raise Refusal(
            "E-DETECTION",
            f"--detection-backend {backend!r} is not one of trackpy, gaussian, region",
        )
    threshold = options.detection_threshold
    min_area = int(options.detection_min_area_px)
    max_area = (
        None
        if options.detection_max_area_px is None
        else int(options.detection_max_area_px)
    )
    if threshold is not None and not math.isfinite(float(threshold)):
        raise Refusal("E-DETECTION", "--detection-threshold must be a finite number")
    if min_area < 1:
        raise Refusal("E-DETECTION", "--detection-min-area-px must be a positive integer")
    if max_area is not None and max_area < min_area:
        raise Refusal(
            "E-DETECTION",
            f"--detection-max-area-px {max_area} is below --detection-min-area-px "
            f"{min_area}, so no component could ever be kept",
        )
    return {
        "backend": backend,
        "diameter": int(options.detection_diameter),
        "min_mass": float(options.detection_min_mass),
        "processes": int(options.detection_processes),
        "temporal_median_window": None,
        "threshold": None if threshold is None else float(threshold),
        "min_area_px": min_area,
        "max_area_px": max_area,
    }


def build_request(
    *,
    info: StoreInfo,
    sidecar: Sidecar,
    layout: Layout,
    transform: TransformChoice,
    movie_name: str,
    frames_name: str,
    tile_shape: tuple[int, int],
    crop: tuple[tuple[int, int], tuple[int, int]] | None,
    detection: Mapping[str, Any],
    duplicate_gate_px: float,
    registration_residual_px: float | None,
    pose_uncertainty_um: float | None,
    pixel_scale_um: float | None,
    extra_notes: Sequence[str],
    run_id: str | None,
    trial_prefix: str,
) -> dict[str, Any]:
    x_spacing = layout.x_spacing
    y_spacing = layout.y_spacing
    spacing: list[float] | None
    if x_spacing > 0 and y_spacing > 0:
        spacing = [y_spacing, x_spacing]
    else:
        spacing = None

    duplicates: dict[str, Any] = {"gate_px": float(duplicate_gate_px)}
    if registration_residual_px is not None:
        # RTASPT derives its cross-tile merge radius from this number (max(6, 3*sigma)), so declaring a
        # residual is not bookkeeping: it silently widens the radius that decides which detections are
        # the same object. Measured 2026-10-25 on one 4x4 stack, same 16 frames: a 1.34 px residual
        # stayed at the 6 px floor and produced 4617 objects, while a stale 25.62 px placement widened
        # the radius to 76.85 px and star-linked 364 of 6102 detections into a single object. A residual
        # outside the duplicate gate means the placement cannot place tiles within that gate, so refuse
        # rather than hand RTASPT a number that distorts the merge.
        if float(registration_residual_px) > float(duplicate_gate_px):
            raise Refusal(
                "E-REGISTRATION-RESIDUAL",
                f"the registration record declares a {float(registration_residual_px):.2f}px residual, "
                f"above the {float(duplicate_gate_px):.2f}px duplicate gate; RTASPT would widen its "
                "cross-tile merge radius to "
                f"{max(float(duplicate_gate_px), 3.0 * float(registration_residual_px)):.2f}px and "
                "merge distinct objects. Re-register, or drop the record to use the exact origins",
            )
        duplicates["registration_residual_px"] = float(registration_residual_px)

    spec: dict[str, Any] = {
        "run_id": run_id or trial_prefix,
        "channel_id": sidecar.camera.get("name") or None,
        "calibration_id": transform.calibration_id,
        "coordinate_frame": "mosaic",
        "pose_source": "host_interpolated",
    }
    if pose_uncertainty_um is not None:
        spec["pose_uncertainty_um"] = float(pose_uncertainty_um)
    if pixel_scale_um is not None:
        spec["pixel_scale_um"] = float(pixel_scale_um)
    spec = {key: value for key, value in spec.items() if value is not None}

    notes: list[str] = [
        (
            "order is pinned to as_given: movie page i and frame-table row i are the "
            "same recorded frame. With raster or serpentine, build_tiles renumbers "
            "tile_index by traversal while detections keep the table-row index, and "
            "merge_duplicate_detections then places every detection on another tile's "
            "offset without an error."
        ),
        (
            f"frame table is the {layout.traversal} acquisition order of a "
            f"{layout.grid()} grid; the store arrays are in that same order and "
            f"page order was verified against it."
        ),
        (
            f"stage coordinates are the sidecar's "
            f"{sidecar.stage_coordinate_basis or 'unspecified'} readbacks "
            f"({', '.join(sorted(str(v) for v in sidecar.stage_readback_keys.values())) or 'no readback keys recorded'}), "
            "paired to frames by array_index, not to an exposure-start time."
        ),
        (
            f"stage-to-pixel transform comes from {transform.source}; "
            f"calibration_id {transform.calibration_id} names that derivation."
        ),
    ]
    if crop is not None:
        notes.append(
            f"images are cropped to y=[{crop[0][0]},{crop[0][1]}) "
            f"x=[{crop[1][0]},{crop[1][1]}) of the recorded {info.plane_shape[0]}x"
            f"{info.plane_shape[1]} plane."
        )
    else:
        notes.append("images are the full recorded plane, not cropped.")
    notes.extend(
        [
            (
                "no anisotropy or tracking section appears here on purpose: "
                "rtaspt-search-product-v1 has neither and silently drops unknown "
                "keys, so those stages are separate `rtaspt process` and "
                "`rtaspt track` commands."
            ),
            (
                f"detection backend is {detection.get('backend')!r} and its whole "
                "declaration (threshold/min_area_px/max_area_px included) sits inside "
                "the request sha256 recorded in provenance.json and handoff.json."
            ),
            (
                f"written by {TOOL_NAME} {TOOL_VERSION} from {info.path.name} "
                f"(sidecar sha256 {sidecar.sha256[:16]})."
            ),
        ]
    )
    notes.extend(str(note) for note in extra_notes)

    return {
        "kind": "settled",
        "frames": frames_name,
        "searchscan": spec,
        "transform": {"matrix": [list(row) for row in transform.matrix]},
        "tile_shape": [int(tile_shape[0]), int(tile_shape[1])],
        "order": "as_given",
        "lattice_spacing_um": spacing,
        "snap_to_lattice": False,
        "images": {"kind": "movie", "path": movie_name},
        "detection": dict(detection),
        "duplicates": duplicates,
        "notes": notes,
    }


def assert_request_keys(request: Mapping[str, Any]) -> None:
    extra = sorted(set(request) - RTASPT_REQUEST_KEYS)
    if extra:
        raise Refusal(
            "E-REQUEST-KEY",
            "refusing to write request section(s) "
            + ", ".join(extra)
            + " that rtaspt-search-product-v1 would drop silently",
        )
    missing = [key for key in ("kind", "frames", "tile_shape", "transform") if key not in request]
    if missing:
        raise Refusal("E-REQUEST-KEY", "request is missing " + ", ".join(missing))


REQUEST_HEADER = (
    "RTASPT search-scan request written by redsun_to_rtaspt.py.",
    "",
    "Schema: rtaspt-search-product-v1 (src/rtaspt/search_product.py); paths are",
    "relative to this file, which RTASPT resolves against the request's directory.",
    "",
    "order is pinned to as_given and must stay that way. The movie's page i and",
    "frames.csv row i are the same recorded frame. With serpentine or raster,",
    "build_tiles numbers tile_index by traversal while detections keep the",
    "table-row index; both are {0..N}, so merge_duplicate_detections accepts the",
    "join and places every detection on another tile's offset, with no error.",
    "",
    "No anisotropy or tracking section is written here: rtaspt-search-product-v1",
    "has neither and drops unknown keys without a warning. Those stages are",
    "separate commands (`rtaspt process`, `rtaspt track`).",
)


# ---------------------------------------------------------------------------
# Crop parsing
# ---------------------------------------------------------------------------


def parse_crop(
    text: str | None, plane_shape: tuple[int, int]
) -> tuple[tuple[int, int], tuple[int, int]] | None:
    if not text:
        return None
    cleaned = text.replace(" ", "")
    try:
        parts = [part for part in cleaned.split(",") if part]
        if len(parts) != 2:
            raise ValueError("expected 'y0:y1,x0:x1'")
        y_part, x_part = parts
        y0_text, y1_text = y_part.split(":")
        x0_text, x1_text = x_part.split(":")
        y0, y1, x0, x1 = int(y0_text), int(y1_text), int(x0_text), int(x1_text)
    except ValueError as exc:
        raise Refusal(
            "E-CROP", f"--crop {text!r} is not a 'y0:y1,x0:x1' pixel window ({exc})"
        ) from exc
    height, width = plane_shape
    if not (0 <= y0 < y1 <= height and 0 <= x0 < x1 <= width):
        raise Refusal(
            "E-CROP",
            f"--crop {text!r} must satisfy 0 <= y0 < y1 <= {height} and "
            f"0 <= x0 < x1 <= {width}",
        )
    return (y0, y1), (x0, x1)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


def _store_stem(store: Path) -> str:
    """The run's store name, whether the .zarr group or its buffer dir was passed."""
    resolved = store.resolve()
    name = resolved.name
    if name.lower().endswith(".zarr"):
        return name[: -len(".zarr")]
    if resolved.parent.name.lower().endswith(".zarr"):
        return resolved.parent.name[: -len(".zarr")]
    return name


def _write_movie(
    info: StoreInfo,
    order: Sequence[int],
    crop: tuple[tuple[int, int], tuple[int, int]] | None,
    target: Path,
) -> dict[str, Any]:
    import tifffile

    frames = len(order)
    height, width = info.plane_shape
    y_slice = slice(None) if crop is None else slice(crop[0][0], crop[0][1])
    x_slice = slice(None) if crop is None else slice(crop[1][0], crop[1][1])
    out_h = (crop[0][1] - crop[0][0]) if crop else height
    out_w = (crop[1][1] - crop[1][0]) if crop else width
    dtype = np.dtype(info.dtype)

    # One shaped write with a leading T axis: a page-at-a-time writer produces one
    # one-page series per call and TiffSeriesReader reads series[0] only.
    staging_stack = target.with_name("stack.raw")
    stack = np.memmap(staging_stack, dtype=dtype, mode="w+", shape=(frames, out_h, out_w))
    for page, source_index in enumerate(order):
        plane = np.asarray(info.array[source_index])
        if plane.shape != (height, width):
            raise Refusal(
                "E-SHAPE",
                f"store frame {source_index} read as {plane.shape}, expected {(height, width)}",
            )
        stack[page] = plane[y_slice, x_slice]
    stack.flush()
    bigtiff = frames * out_h * out_w * dtype.itemsize > BIGTIFF_THRESHOLD_BYTES
    tifffile.imwrite(
        target,
        stack,
        ome=True,
        photometric="minisblack",
        bigtiff=bigtiff,
        metadata={"axes": "TYX"},
    )
    del stack
    staging_stack.unlink(missing_ok=True)
    return {
        "axes": "TYX",
        "shape": [frames, out_h, out_w],
        "dtype": str(dtype),
        "bigtiff": bool(bigtiff),
        "compression": "none (RTASPT memmaps contiguous planes)",
    }


def _write_frames_csv(
    frames: Sequence[SidecarFrame], order: Sequence[int], target: Path
) -> dict[str, Any]:
    ordered = [frames[index] for index in order]
    t0 = ordered[0].time_s
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["frame", "x_um", "y_um", "time_s"])
        for page, frame in enumerate(ordered):
            writer.writerow(
                [
                    page,
                    f"{frame.x_um:.6f}",
                    f"{frame.y_um:.6f}",
                    f"{frame.time_s - t0:.6f}",
                ]
            )
    return {
        "columns": ["frame", "x_um", "y_um", "time_s"],
        "rows": len(ordered),
        "t_origin_s": t0,
        "elapsed_s": ordered[-1].time_s - t0 if len(ordered) > 1 else 0.0,
    }


def _output_dir_status(out: Path) -> list[str]:
    if not out.exists():
        return []
    names = [
        "request.yaml",
        "frames.csv",
        "provenance.json",
        "handoff.json",
    ]
    present = [name for name in names if (out / name).exists()]
    present.extend(item.name for item in out.glob("*_tiles.ome.tif"))
    return sorted(set(present))


def convert(options: argparse.Namespace) -> dict[str, Any]:
    store_path = Path(options.store).resolve()
    sidecar_path = Path(options.sidecar).resolve()
    out = Path(options.out).resolve()

    # 1. Sidecar first so its data_key can select the store array.
    if not sidecar_path.is_file():
        raise Refusal("E-SIDECAR-MISSING", f"positions sidecar not found: {sidecar_path}")
    sidecar = load_sidecar(sidecar_path)
    info = resolve_store(store_path, options.data_key, sidecar.data_key)
    check_dtype_and_shape(info)
    frames, warnings = check_sidecar_against_store(sidecar, info)
    if not sidecar_path.name.endswith(".positions.json") or _store_stem(store_path) not in sidecar_path.name:
        warnings.append(
            f"{sidecar_path.name} does not follow the Redsun "
            f"<{_store_stem(store_path)}>.positions.json naming convention; pairing "
            "was checked by content instead"
        )

    # 2. Acquisition order.
    points = np.array([[frame.x_um, frame.y_um] for frame in frames], dtype=float)
    layout = analyse_lattice(points, float(options.position_tolerance_um))
    if layout.spread_um > float(options.position_tolerance_um):
        warnings.append(
            f"one lattice node spans {layout.spread_um:.2f} um, above the "
            f"{options.position_tolerance_um:g} um clustering tolerance; check the "
            "stage readbacks"
        )
    order = emission_order(layout, options.order)
    if options.order != "as_given" and order == list(range(len(frames))):
        warnings.append(
            f"--order {options.order} is the recorded order for this grid, so the "
            "emitted movie is unchanged"
        )

    # 3. Transform (and the registration record that may declare it).
    crop = parse_crop(options.crop, info.plane_shape)
    registration = None
    if options.registration_record:
        record_path = Path(options.registration_record).resolve()
        if not record_path.is_file():
            raise Refusal(
                "E-REGISTRATION-STALE", f"registration record not found: {record_path}"
            )
        payload = json.loads(record_path.read_text(encoding="utf-8"))
        # An explicitly named record used to be trusted as-is. Verify the digest it declares against the
        # sidecar actually being handed over: a record written for another capture carries that
        # capture's placement, so fitting a transform from it would place these tiles by the wrong
        # geometry while every count still agreed. The discovery path already refused this.
        recorded_sha = payload.get("source_sidecar_sha256")
        if isinstance(recorded_sha, str) and recorded_sha != sidecar.sha256:
            raise Refusal(
                "E-REGISTRATION-STALE",
                f"{record_path} was written for a sidecar with sha256 {recorded_sha[:12]}... but "
                f"this sidecar is {sidecar.sha256[:12]}...; the placement describes another capture",
            )
        registration = {"report_path": record_path, "report": payload, "stale_sidecar": False}
    else:
        # Search from the sidecar's own directory so the tree walk does not depend
        # on whether the caller passed the .zarr group or the buffer array dir.
        registration = discover_registration(sidecar, sidecar_path.parent)
        if registration is not None and registration.get("stale_sidecar"):
            # Only fatal when the transform is about to be fitted from it.
            if not (options.transform_matrix or options.scale_px_per_um or options.calibration):
                raise Refusal(
                    "E-REGISTRATION-STALE",
                    f"{registration['report_path']} registers a sidecar at this path "
                    f"but with sha256 {registration.get('recorded_sidecar_sha256')}; the "
                    "sidecar on disk differs. Re-run registration rather than fitting "
                    "a stale placement.",
                )
            warnings.append(
                f"{registration['report_path']} registers a stale sidecar digest; it "
                "was not used for the transform"
            )
            registration = None

    if options.transform_matrix:
        matrix = parse_matrix(options.transform_matrix)
        digest = hashlib.sha256(
            json.dumps([[list(row) for row in matrix]]).encode("utf-8")
        ).hexdigest()[:12]
        transform = TransformChoice(
            matrix=matrix,
            source="cli-matrix",
            calibration_id=f"declared-matrix-{digest}",
            detail={"raw": options.transform_matrix},
        )
    elif options.scale_px_per_um:
        transform = transform_from_scale(
            options.scale_px_per_um,
            float(options.rotation_deg),
            bool(options.flip_x),
            bool(options.flip_y),
            (0.0, 0.0),
        )
    elif options.calibration:
        transform = transform_from_calibration(Path(options.calibration).resolve(), info)
    elif registration is not None:
        transform = fit_transform_from_placements(
            registration, frames, float(options.position_tolerance_um)
        )
    else:
        raise Refusal(
            "E-TRANSFORM-MISSING",
            "no stage-to-pixel declaration is available: no --transform-matrix, "
            "--scale-px-per-um or --calibration was given, and no mosaic report "
            "beside the store names this sidecar. Redsun'\''s hand-eye record is "
            "expressed in the doubled reported-um frame and is not a safe default, "
            "so the handoff states a transform explicitly instead of inventing one.",
        )
    warnings.extend(transform.warnings)

    # 4. Redsun preprocessing id.
    preprocessing_id, preprocessing_source, preprocessing_notes = resolve_preprocessing_id(
        sidecar, options.preprocessing_id, registration
    )
    warnings.extend(preprocessing_notes)

    # 5. Output guard.
    existing = _output_dir_status(out)
    if existing and not options.force:
        raise Refusal(
            "E-OUTPUT-EXISTS",
            f"{out} already holds {', '.join(existing)}; pass --force to overwrite",
        )

    # 6. Compose documents.
    stem = _store_stem(store_path)
    movie_name = f"{stem}_tiles.ome.tif"
    frames_name = "frames.csv"
    tile_shape = (
        (crop[0][1] - crop[0][0], crop[1][1] - crop[1][0])
        if crop
        else info.plane_shape
    )
    detection = detection_declaration(options)
    registration_residual = options.registration_residual_px
    if registration_residual is None:
        edge = (registration or {}).get("report", {}).get("edge_residual_summary_px")
        if isinstance(edge, Mapping) and edge.get("rms") is not None:
            registration_residual = float(edge["rms"])

    request = build_request(
        info=info,
        sidecar=sidecar,
        layout=layout,
        transform=transform,
        movie_name=movie_name,
        frames_name=frames_name,
        tile_shape=tile_shape,
        crop=crop,
        detection=detection,
        duplicate_gate_px=float(options.duplicate_gate_px),
        registration_residual_px=registration_residual,
        pose_uncertainty_um=options.pose_uncertainty_um,
        pixel_scale_um=options.pixel_scale_um,
        extra_notes=options.note or (),
        run_id=options.run_id,
        trial_prefix=stem,
    )
    assert_request_keys(request)
    _log(
        f"{len(frames)} frames, {layout.grid()} {layout.traversal} order, "
        f"transform from {transform.source}"
    )

    # 7. Write into a staging directory, then move into place.
    out.mkdir(parents=True, exist_ok=True)
    staging = out / ".redsun_to_rtaspt.staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    produced: list[Path] = []
    try:
        movie_path = staging / movie_name
        movie = _write_movie(info, order, crop, movie_path)
        produced.append(movie_path)
        _log(f"wrote {movie_name} {movie['shape']} {movie['dtype']}")

        frames_path = staging / frames_name
        frames_meta = _write_frames_csv(frames, order, frames_path)
        produced.append(frames_path)

        request_path = staging / "request.yaml"
        request_path.write_text(
            dump_yaml(request, header=REQUEST_HEADER), encoding="utf-8"
        )
        produced.append(request_path)

        for path in produced:
            os.replace(path, out / path.name)

        movie_sha = sha256_file(out / movie_name)
        request_sha = sha256_file(out / "request.yaml")
        frames_sha = sha256_file(out / frames_name)
        store_sha = sha256_tree(info.path)

        provenance = {
            "schema": PROVENANCE_SCHEMA,
            "generated_utc": _utc_now(),
            "tool": {"name": TOOL_NAME, "version": TOOL_VERSION},
            "source": {
                "store_path": str(info.path),
                "store_data_key": info.array_key,
                "store_sha256": store_sha,
                "store_shape_tyx": [int(value) for value in info.shape],
                "store_dtype": info.dtype,
                "store_chunks": _jsonable(info.chunks),
                "sidecar_path": str(sidecar.path),
                "sidecar_sha256": sidecar.sha256,
                "sidecar_schema": sidecar.schema,
                "sidecar_run_uid": sidecar.run_uid,
                "sidecar_exit_status": sidecar.exit_status,
                "sidecar_frames_written": sidecar.frames_written,
                "frame_count": len(frames),
                "stage_coordinate_basis": sidecar.stage_coordinate_basis,
                "stage_readback_keys": dict(sidecar.stage_readback_keys),
                "camera": dict(sidecar.camera),
                "registration": (
                    None
                    if registration is None
                    else {
                        "report_path": str(registration["report_path"]),
                        "report_sha256": sha256_file(Path(registration["report_path"])),
                        "registration_id": registration["report"].get("registration_id"),
                    }
                ),
            },
            "order": {
                "mode": options.order,
                "request_order": "as_given",
                "traversal": layout.traversal,
                "grid": {
                    "slow": layout.n_slow,
                    "fast": layout.n_fast,
                    "fast_axis": layout.fast_axis,
                },
                "emitted_frame_order": [int(value) for value in order],
            },
            "crop": (
                None
                if crop is None
                else {
                    "y": [crop[0][0], crop[0][1]],
                    "x": [crop[1][0], crop[1][1]],
                    "source_plane": [int(info.plane_shape[0]), int(info.plane_shape[1])],
                }
            ),
            "redsun_preprocessing_id": preprocessing_id,
            "redsun_preprocessing_id_source": preprocessing_source,
            "transform": {
                "source": transform.source,
                "calibration_id": transform.calibration_id,
                "matrix": [list(row) for row in transform.matrix],
                "detail": _jsonable(transform.detail),
            },
            "detection": dict(detection),
            "outputs": {
                "movie": {
                    "path": movie_name,
                    "sha256": movie_sha,
                    **movie,
                },
                "frames": {
                    "path": frames_name,
                    "sha256": frames_sha,
                    **frames_meta,
                },
                "request": {"path": "request.yaml", "sha256": request_sha},
            },
            "warnings": warnings,
            "hardware_commands_issued": False,
            "pixels_synthesised": False,
        }
        provenance_path = staging / "provenance.json"
        provenance_path.write_text(
            json.dumps(provenance, indent=2, sort_keys=False) + "\n", encoding="utf-8"
        )
        os.replace(provenance_path, out / "provenance.json")

        provenance_sha = sha256_file(out / "provenance.json")
        handoff = {
            "schema": HANDOFF_SCHEMA,
            "generated_utc": provenance["generated_utc"],
            "tool": provenance["tool"],
            "source": {
                "store": str(info.path),
                "store_sha256": store_sha,
                "sidecar": str(sidecar.path),
                "sidecar_sha256": sidecar.sha256,
                "run_uid": sidecar.run_uid,
                "frame_count": len(frames),
                "stage_coordinate_basis": sidecar.stage_coordinate_basis,
                "camera_name": sidecar.camera.get("name"),
                "camera_exposure_ms": sidecar.camera.get("exposure_ms"),
            },
            "frame_count": len(frames),
            "order": provenance["order"],
            "crop": provenance["crop"],
            "tile_shape": [int(tile_shape[0]), int(tile_shape[1])],
            "redsun_preprocessing_id": preprocessing_id,
            "redsun_preprocessing_id_source": preprocessing_source,
            "transform": provenance["transform"],
            "request_schema": RTASPT_REQUEST_SCHEMA,
            "request": {
                "path": "request.yaml",
                "sha256": request_sha,
                "order": request["order"],
                "kind": request["kind"],
                "images": request["images"],
                "frames": request["frames"],
                "calibration_id": transform.calibration_id,
                "notes_count": len(request["notes"]),
                "detection": request["detection"],
            },
            "outputs": provenance["outputs"],
            "provenance": {"path": "provenance.json", "sha256": provenance_sha},
            "checks": [
                {
                    "id": "C1-sidecar-schema",
                    "detail": f"sidecar declares {SIDECAR_SCHEMA}",
                },
                {
                    "id": "C2-frame-count",
                    "detail": f"store {info.frames}, sidecar {len(sidecar.frames)}, "
                    f"frames_written {sidecar.frames_written}",
                },
                {
                    "id": "C3-acquisition-order",
                    "detail": f"stage path is a complete {layout.grid()} "
                    f"{layout.traversal} walk; times monotonic with array_index",
                },
                {
                    "id": "C4-order-pinned",
                    "detail": "request order is as_given and movie page i is frame "
                    f"table row i for all {len(frames)} frames",
                },
                {
                    "id": "C5-no-dropped-sections",
                    "detail": "request carries only rtaspt-search-product-v1 keys",
                },
                {
                    "id": "C6-tiff-carrier",
                    "detail": f"{movie['axes']} {movie['shape']} {movie['dtype']} "
                    "single OME series, one page per frame",
                },
                {
                    "id": "C7-tile-shape",
                    "detail": f"{tile_shape[0]}x{tile_shape[1]} matches the emitted plane",
                },
            ],
            "warnings": warnings,
            "product_command": (
                f"rtaspt searchscan {(out / 'request.yaml')} "
                f"--output {out / 'searchscan'} --coverage-arrays"
            ),
            "product_check": (
                f"python verify_product.py --handoff {out / 'handoff.json'} "
                f"--product {out / 'searchscan'}"
            ),
            "limits": [
                "no anisotropy section: rtaspt-search-product-v1 has none and drops "
                "unknown keys silently; run `rtaspt process` separately",
                "no tracking section: same reason; run `rtaspt track` separately",
                "no stage-to-pixel measurement is made here; the transform is a "
                "declaration whose source is recorded",
                "no hardware command, no camera, no stage, no GUI",
            ],
        }
        handoff_path = staging / "handoff.json"
        handoff_path.write_text(
            json.dumps(handoff, indent=2, sort_keys=False) + "\n", encoding="utf-8"
        )
        os.replace(handoff_path, out / "handoff.json")
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    return {
        "out": str(out),
        "movie": str(out / movie_name),
        "frames": str(out / frames_name),
        "request": str(out / "request.yaml"),
        "handoff": str(out / "handoff.json"),
        "provenance": str(out / "provenance.json"),
        "frame_count": len(frames),
        "order_mode": options.order,
        "request_order": "as_given",
        "tile_shape": [int(tile_shape[0]), int(tile_shape[1])],
        "transform_source": transform.source,
        "calibration_id": transform.calibration_id,
        "detection": detection,
        "redsun_preprocessing_id": preprocessing_id,
        "warnings": warnings,
    }


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, Path):
        return str(value)
    return value


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=TOOL_NAME,
        description=(
            "Adapt a saved Redsun snap store plus its snap-position-association-v4 "
            "sidecar into a validated RTASPT search-scan handoff."
        ),
        epilog=(
            "The written request always pins order: as_given; --order only reorders "
            "the emitted movie and frame table together."
        ),
    )
    parser.add_argument("store", help="saved store: the .zarr group or the buffer array directory")
    parser.add_argument("sidecar", help="the run's <store>.positions.json sidecar")
    parser.add_argument("out", help="output directory for the handoff")
    parser.add_argument(
        "--data-key",
        default=None,
        help=f"store array to read (default: the sidecar's data_key, else --; {DEFAULT_DATA_KEY!r})",
    )
    parser.add_argument(
        "--order",
        choices=("as_given", "raster", "serpentine"),
        default="as_given",
        help=(
            "order of the emitted movie and frame table (default as_given, the "
            "recorded acquisition order). The request stays order: as_given because "
            "the movie is permuted with the table."
        ),
    )
    parser.add_argument(
        "--crop",
        default=None,
        help="half-open pixel window 'y0:y1,x0:x1' applied to every frame and to tile_shape",
    )
    parser.add_argument(
        "--position-tolerance-um",
        type=float,
        default=DEFAULT_POSITION_TOLERANCE_UM,
        help=f"stage-coordinate clustering tolerance in um (default {DEFAULT_POSITION_TOLERANCE_UM})",
    )
    parser.add_argument(
        "--transform-matrix",
        default=None,
        help="declared stage->pixel affine as 'a,b,c;d,e,f' (dx,dy,1 -> x_px,y_px)",
    )
    parser.add_argument(
        "--scale-px-per-um",
        default=None,
        help="declared pixel scale as S or SX,SY, with --rotation-deg/--flip-x/--flip-y",
    )
    parser.add_argument("--rotation-deg", type=float, default=0.0, help="with --scale-px-per-um")
    parser.add_argument("--flip-x", action="store_true", help="with --scale-px-per-um")
    parser.add_argument("--flip-y", action="store_true", help="with --scale-px-per-um")
    parser.add_argument(
        "--calibration",
        default=None,
        help="Redsun hand-eye calibration record whose mosaic_placement matrix is declared",
    )
    parser.add_argument(
        "--registration-record",
        default=None,
        help="explicit mosaic report to fit the transform from (skips auto-discovery)",
    )
    parser.add_argument(
        "--preprocessing-id",
        default=None,
        help="Redsun preprocessing id to record (default: from the registration record, else null)",
    )
    parser.add_argument(
        "--registration-residual-px",
        type=float,
        default=None,
        help="declared duplicate-gate registration residual (default: the mosaic report's edge RMS)",
    )
    parser.add_argument(
        "--duplicate-gate-px",
        type=float,
        default=DEFAULT_DUPLICATE_GATE_PX,
        help=f"RTASPT duplicate merge gate in mosaic pixels (default {DEFAULT_DUPLICATE_GATE_PX})",
    )
    parser.add_argument("--detection-diameter", type=int, default=DEFAULT_DETECTION_DIAMETER)
    parser.add_argument("--detection-min-mass", type=float, default=DEFAULT_DETECTION_MIN_MASS)
    parser.add_argument("--detection-processes", type=int, default=1)
    parser.add_argument(
        "--detection-backend",
        choices=("trackpy", "gaussian", "region"),
        default=DEFAULT_DETECTION_BACKEND,
        help=(
            "RTASPT detection backend (default trackpy). 'region' is a threshold + "
            "8-connected component detector for transmitted light: it finds object "
            "interiors, not band-pass rims"
        ),
    )
    parser.add_argument(
        "--detection-threshold",
        type=float,
        default=None,
        help="region backend: intensity threshold (default null = Otsu per frame)",
    )
    parser.add_argument(
        "--detection-min-area-px",
        type=int,
        default=DEFAULT_DETECTION_MIN_AREA_PX,
        help=f"region backend: smallest kept component in pixels (default {DEFAULT_DETECTION_MIN_AREA_PX})",
    )
    parser.add_argument(
        "--detection-max-area-px",
        type=int,
        default=None,
        help="region backend: largest kept component in pixels (default null = no upper bound)",
    )
    parser.add_argument("--pose-uncertainty-um", type=float, default=None)
    parser.add_argument("--pixel-scale-um", type=float, default=None)
    parser.add_argument("--run-id", default=None, help="RTASPT run identity (default: the store stem)")
    parser.add_argument("--note", action="append", help="extra request note (repeatable)")
    parser.add_argument("--force", action="store_true", help="overwrite existing handoff files")
    parser.add_argument("--json", action="store_true", help="print only the JSON summary")
    parser.add_argument("--version", action="version", version=f"{TOOL_NAME} {TOOL_VERSION}")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    options = parser.parse_args(argv)
    if options.position_tolerance_um <= 0:
        parser.error("--position-tolerance-um must be positive")
    try:
        summary = convert(options)
    except Refusal as refusal:
        print(f"REFUSED {refusal}", file=sys.stderr)
        return 2
    if options.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        for key in ("out", "movie", "frames", "request", "provenance", "handoff"):
            print(f"{key}: {summary[key]}")
        print(f"frames: {summary['frame_count']}")
        print(f"order: {summary['order_mode']} (request order {summary['request_order']})")
        print(f"tile_shape: {summary['tile_shape']}")
        print(f"transform: {summary['transform_source']} ({summary['calibration_id']})")
        detection = summary["detection"]
        print(f"detection: {detection['backend']} (threshold {detection['threshold']}, "
              f"area {detection['min_area_px']}..{detection['max_area_px']} px)")
        print(f"redsun_preprocessing_id: {summary['redsun_preprocessing_id']}")
        for warning in summary["warnings"]:
            print(f"warning: {warning}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
