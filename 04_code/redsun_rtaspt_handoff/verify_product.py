#!/usr/bin/env python3
"""Check one RTASPT search-scan product against the handoff that requested it.

This is the offline counterpart of the product run. It reads the handoff record
``redsun_to_rtaspt.py`` wrote and the product directory RTASPT wrote, then checks
the three things a handoff must never get wrong:

1. ``request_used.json`` kept ``order: as_given`` (the schema defaults to
   ``serpentine``, and a silent default is the corruption trap);
2. the product's tile count equals the recorded frame count;
3. tile *i* carries frame *i*'s stage coordinates. This is the check that would
   have caught the silent renumbering: with ``raster``/``serpentine``,
   ``build_tiles`` renumbers ``tile_index`` by traversal while the frame table
   keeps the acquisition order, so ``tiles.csv`` and ``detections.csv`` describe
   different tiles and every detection lands on another tile's offset.

Usage::

    python verify_product.py --handoff <handoff.json> --product <searchscan dir>

Exit 0 when every check passes, 1 when any check fails. No hardware, no RTASPT
import: the product's own JSON and CSV files are the evidence.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

TOOL_NAME = "verify_product.py"
TOOL_VERSION = "1.1.0"
ORDER = "as_given"


class CheckFailed(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> Any:
    if not path.is_file():
        raise CheckFailed(f"missing file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise CheckFailed(f"missing table: {path}")
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _close(left: float, right: float, tolerance: float = 1e-6) -> bool:
    return math.isfinite(left) and math.isfinite(right) and abs(left - right) <= tolerance


def verify(
    handoff_path: Path, product_dir: Path, *, require_input_provenance: bool = False
) -> dict[str, Any]:
    handoff = _load_json(handoff_path)
    product = product_dir if product_dir.is_dir() else product_dir.parent
    checks: list[dict[str, Any]] = []

    def record(name: str, passed: bool, detail: str) -> None:
        checks.append({"check": name, "status": "pass" if passed else "fail", "detail": detail})

    frames_requested = int(handoff.get("frame_count", -1))
    handoff_dir = handoff_path.parent
    frame_count_rows = _read_csv(handoff_dir / handoff["outputs"]["frames"]["path"])
    request_rows_path = product / "request_used.json"
    recorded = _load_json(request_rows_path)

    # 1. The product kept the pinned order.
    order = recorded.get("order")
    record(
        "request_used_order_as_given",
        order == ORDER,
        f"request_used.json order={order!r} (expected {ORDER!r})",
    )

    # 2. The image source is the movie this handoff wrote.
    images = recorded.get("images") or {}
    movie_written = (handoff_dir / handoff["outputs"]["movie"]["path"]).resolve()
    movie_used = Path(str(images.get("path") or "")).resolve() if images.get("path") else None
    record(
        "request_used_movie_path",
        movie_used == movie_written,
        f"request_used.json images.path={movie_used} (handoff wrote {movie_written})",
    )

    # A path match alone cannot detect changed bytes at that path. Verify each
    # handoff file against the digest captured when the adapter wrote it.
    for name in ("movie", "frames", "request"):
        output_info = handoff["outputs"].get(name) or {}
        output_path = handoff_dir / str(output_info.get("path") or "")
        expected_sha = output_info.get("sha256")
        matches = (
            isinstance(expected_sha, str)
            and len(expected_sha) == 64
            and output_path.is_file()
            and _sha256(output_path) == expected_sha
        )
        record(
            f"handoff_{name}_sha256",
            matches,
            f"{name} matches its recorded handoff digest: {matches}",
        )

    # 3. The frame table is the same file, unchanged.
    frames_declared = Path(str(recorded.get("frames") or "")).resolve()
    frames_written = (handoff_dir / handoff["outputs"]["frames"]["path"]).resolve()
    same_bytes = (
        frames_declared.is_file()
        and frames_written.is_file()
        and _sha256(frames_declared) == _sha256(frames_written)
    )
    record(
        "request_used_frame_table",
        frames_declared == frames_written and same_bytes,
        f"request_used.json frames={frames_declared}; same sha256 as the handoff table: {same_bytes}",
    )

    # 4. Tile geometry and the declared transform survived.
    tile_shape = recorded.get("tile_shape")
    record(
        "request_used_tile_shape",
        list(tile_shape or []) == list(handoff.get("tile_shape") or []),
        f"request_used.json tile_shape={tile_shape} (handoff {handoff.get('tile_shape')})",
    )
    used_matrix = (recorded.get("transform") or {}).get("matrix")
    declared_matrix = (handoff.get("transform") or {}).get("matrix")
    matrix_ok = (
        isinstance(used_matrix, (list, tuple))
        and isinstance(declared_matrix, (list, tuple))
        and len(used_matrix) == len(declared_matrix) == 2
        and all(isinstance(row, (list, tuple)) and len(row) == 3 for row in used_matrix)
        and all(isinstance(row, (list, tuple)) and len(row) == 3 for row in declared_matrix)
        and all(
            _close(float(a), float(b), 1e-9)
            for row_used, row_declared in zip(used_matrix, declared_matrix)
            for a, b in zip(row_used, row_declared)
        )
    )
    record(
        "request_used_transform",
        matrix_ok,
        f"request_used.json transform.matrix={used_matrix}",
    )

    # 5. No section survived that the schema would have dropped.
    dropped = sorted(
        key for key in ("anisotropy", "tracking") if key in recorded
    )
    record(
        "request_used_no_unsupported_stage_sections",
        not dropped,
        f"anisotropy/tracking keys present: {dropped or 'none'}",
    )

    # 6. Tile count equals the recorded frame count.
    tiles = _read_csv(product / "tiles.csv")
    record(
        "handoff_frame_table_count",
        frames_requested >= 0 and len(frame_count_rows) == frames_requested,
        f"frames.csv rows={len(frame_count_rows)} (handoff frames={frames_requested})",
    )
    record(
        "handoff_frame_indices_are_rows",
        [int(row["frame"]) for row in frame_count_rows] == list(range(len(frame_count_rows))),
        "frame indices must be contiguous and in row order",
    )
    record(
        "tile_count_tiles_csv",
        len(tiles) == frames_requested,
        f"tiles.csv rows={len(tiles)} (sidecar frames={frames_requested})",
    )
    record_file = _load_json(product / "search_scan.json")
    counts = record_file.get("counts") or {}
    provenance_path = product / "input_provenance.json"
    source_identity = "unverified: product has no input provenance"
    if not provenance_path.is_file():
        if require_input_provenance:
            record("processing_input_provenance", False, source_identity)
        else:
            checks.append({
                "check": "processing_input_provenance",
                "status": "not-verified",
                "detail": source_identity,
            })
    else:
        provenance = _load_json(provenance_path)
        before = provenance.get("inputs_before")
        after = provenance.get("inputs_after")
        entries_valid = isinstance(before, list) and all(isinstance(item, dict) for item in before)
        expected = {
            "frame_table": (frames_written, handoff["outputs"]["frames"].get("sha256")),
            "image": (movie_written, handoff["outputs"]["movie"].get("sha256")),
        }
        identities_match = entries_valid and len(before) == 2
        if identities_match:
            for role, (path, digest) in expected.items():
                matches = [item for item in before if item.get("role") == role]
                if len(matches) != 1 or (
                    Path(str(matches[0].get("path") or "")).resolve() != path
                    or matches[0].get("sha256") != digest
                ):
                    identities_match = False
        provenance_ok = (
            provenance.get("schema") == "rtaspt-search-input-provenance-v1"
            and provenance.get("status") == "complete"
            and provenance.get("image_source_kind") == "movie"
            and provenance.get("unchanged_at_boundaries") is True
            and before == after
            and identities_match
            and (record_file.get("products") or {}).get("input_provenance.json")
            == "input_provenance.json"
        )
        source_identity = (
            "matching input digests observed at processing boundaries"
            if provenance_ok else "input provenance does not match the handoff"
        )
        record("processing_input_provenance", bool(provenance_ok), source_identity)
    record(
        "tile_count_search_scan",
        int(counts.get("tiles", -1)) == frames_requested,
        f"search_scan.json counts.tiles={counts.get('tiles')} (sidecar frames={frames_requested})",
    )

    # 7. tile_index is the table row, in order: the renumbering check.
    indices = [int(row["tile_index"]) for row in tiles]
    record(
        "tile_index_is_row",
        indices == list(range(len(tiles))),
        f"tile_index sequence starts {indices[:5]}... and is {len(indices)} long",
    )

    # 8. Tile i carries frame i's stage coordinates.
    mismatches: list[str] = []
    for row, frame_row in zip(tiles, frame_count_rows):
        index = int(row["tile_index"])
        expected_x = float(frame_row["x_um"])
        expected_y = float(frame_row["y_um"])
        actual_x = float(row["stage_x_um"])
        actual_y = float(row["stage_y_um"])
        if not (_close(actual_x, expected_x) and _close(actual_y, expected_y)):
            mismatches.append(
                f"tile {index}: tile ({actual_x:.4f},{actual_y:.4f}) vs "
                f"frame ({expected_x:.4f},{expected_y:.4f})"
            )
    record(
        "tile_stage_coordinates_match_frame_rows",
        len(tiles) == len(frame_count_rows) == frames_requested and not mismatches,
        (
            "every tiles.csv row carries its frame table row's stage coordinates"
            if len(tiles) == len(frame_count_rows) == frames_requested and not mismatches
            else f"frame rows={len(frame_count_rows)}, tiles={len(tiles)}, expected={frames_requested}; "
            + "; ".join(mismatches[:5])
            + (f" (+{len(mismatches) - 5} more)" if len(mismatches) > 5 else "")
        ),
    )

    # 9. Detections were joined on the same tile indices.
    detections_path = product / "detections.csv"
    record("detections_table_present", detections_path.is_file(), "detections.csv is required")
    if detections_path.is_file():
        detections = _read_csv(detections_path)
        record(
            "detection_count_matches_record",
            counts.get("detections") == len(detections),
            f"detections.csv rows={len(detections)}; record={counts.get('detections')}",
        )
        bad = sorted(
            {
                int(row["tile_index"])
                for row in detections
                if not 0 <= int(row["tile_index"]) < frames_requested
            }
        )
        record(
            "detections_tile_index_in_range",
            not bad,
            f"{len(detections)} detections over tile_index 0..{frames_requested - 1}; "
            f"out of range: {bad or 'none'}",
        )
    objects_path = product / "objects.csv"
    record("objects_table_present", objects_path.is_file(), "objects.csv is required")
    if objects_path.is_file():
        objects = _read_csv(objects_path)
        record(
            "object_count_matches_record",
            counts.get("objects") == len(objects),
            f"objects.csv rows={len(objects)}; record={counts.get('objects')}",
        )
        with objects_path.open("r", encoding="utf-8", newline="") as handle:
            object_columns = csv.DictReader(handle).fieldnames or []
        tile_values = sorted({int(row["tile_index"]) for row in objects if "tile_index" in row})
        record(
            "objects_have_tile_provenance",
            "tile_index" in object_columns
            and all(0 <= value < frames_requested for value in tile_values),
            f"{len(objects)} objects; tile_index values {tile_values[:8]}"
            f"{'...' if len(tile_values) > 8 else ''}",
        )

    failed = [check for check in checks if check["status"] == "fail"]
    return {
        "tool": {"name": TOOL_NAME, "version": TOOL_VERSION},
        "handoff": str(handoff_path),
        "product": str(product),
        "checks": checks,
        "passed": not failed,
        "failed": [check["check"] for check in failed],
        "source_identity": source_identity,
        "limitations": [
            (
                "Checks current files against the handoff record; they do not prove which bytes "
                "an earlier RTASPT process consumed."
            ),
            "Does not verify coverage identity, physical calibration, or scientific acceptance.",
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog=TOOL_NAME,
        description="Check an RTASPT search-scan product against its Redsun handoff.",
    )
    parser.add_argument("--handoff", required=True, help="handoff.json written by redsun_to_rtaspt.py")
    parser.add_argument("--product", required=True, help="the searchscan output directory")
    parser.add_argument("--json", action="store_true", help="print the full JSON report")
    parser.add_argument(
        "--require-input-provenance", action="store_true",
        help="fail when the product has no processing-time input provenance",
    )
    parser.add_argument("--version", action="version", version=f"{TOOL_NAME} {TOOL_VERSION}")
    args = parser.parse_args(argv)
    try:
        report = verify(
            Path(args.handoff).resolve(), Path(args.product).resolve(),
            require_input_provenance=args.require_input_provenance,
        )
    except CheckFailed as failure:
        print(f"FAILED {failure}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=False))
    else:
        for check in report["checks"]:
            print(f"[{check['status']}] {check['check']}: {check['detail']}")
        print(f"passed: {report['passed']}")
        print(f"source identity: {report['source_identity']}")
        if report["failed"]:
            print("failed: " + ", ".join(report["failed"]), file=sys.stderr)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
