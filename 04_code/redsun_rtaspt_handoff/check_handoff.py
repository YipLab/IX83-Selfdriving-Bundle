"""Check a Redsun→RTASPT handoff bundle against its own contract.

`redsun_to_rtaspt.py` writes the handoff and records seven writer-side checks;
`verify_product.py` checks the RTASPT *product* against that handoff. This tool
checks the bundle itself, reader-side, from the files on disk: the declared
outputs and their digests, the frame table, the request's pinned order and key
set, the movie's `TYX` shape against `tile_shape`, and the provenance record.

The writer's `checks` are recorded but not re-verified: a check is a claim until
the file it describes is read.

    python check_handoff.py --handoff <handoff.json> [--out report.json]
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HANDOFF_SCHEMA = "redsun-rtaspt-handoff-v1"
REPORT_SCHEMA = "redsun-rtaspt-handoff-check/v1"

REQUIRED_OUTPUTS = ("movie", "frames", "request")
FRAME_TABLE_HEADER = ["frame", "x_um", "y_um", "time_s"]

#: Top-level keys `rtaspt-search-product-v1` accepts in the composed request.
ALLOWED_REQUEST_KEYS = frozenset(
    {
        "kind",
        "frames",
        "searchscan",
        "transform",
        "tile_shape",
        "order",
        "lattice_spacing_um",
        "snap_to_lattice",
        "images",
        "detection",
        "duplicates",
        "notes",
    }
)

WRITER_CHECK_IDS = (
    "C1-sidecar-schema",
    "C2-frame-count",
    "C3-acquisition-order",
    "C4-order-pinned",
    "C5-no-dropped-sections",
    "C6-tiff-carrier",
    "C7-tile-shape",
)


class HandoffError(RuntimeError):
    """The bundle cannot be read at all."""


def _sha256(path: Path) -> str:
    """Return the SHA-256 of one file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _load(path: Path) -> Any:
    """Read one JSON file, refusing by name when unreadable."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise HandoffError(f"missing file: {path}") from error
    except json.JSONDecodeError as error:
        raise HandoffError(f"unreadable JSON in {path}: {error}") from error


def check_handoff(handoff_path: Path) -> dict[str, Any]:
    """Read one handoff bundle and recompute every file-level claim."""
    handoff_path = Path(handoff_path)
    handoff = _load(handoff_path)
    if not isinstance(handoff, dict):
        raise HandoffError("handoff.json must be an object")
    base = handoff_path.parent
    checks: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []

    def record(
        identifier: str,
        ok: bool,
        detail: str,
        *,
        severity: str = "blocking",
        code: str | None = None,
    ) -> None:
        checks.append({"id": identifier, "ok": bool(ok), "detail": detail})
        if not ok:
            findings.append(
                {"code": code or identifier, "severity": severity, "detail": detail}
            )

    record(
        "schema",
        handoff.get("schema") == HANDOFF_SCHEMA,
        f"schema {handoff.get('schema')!r}",
        code="schema_mismatch",
    )
    required = (
        "frame_count",
        "order",
        "tile_shape",
        "request",
        "outputs",
        "provenance",
    )
    missing = [key for key in required if key not in handoff]
    record(
        "required-keys",
        not missing,
        f"missing {missing}" if missing else "all required keys present",
        code="required_key_missing",
    )

    frame_count = handoff.get("frame_count")
    if (
        isinstance(frame_count, bool)
        or not isinstance(frame_count, int)
        or frame_count < 1
    ):
        record(
            "frame-count",
            False,
            f"frame_count {frame_count!r}",
            code="frame_count_invalid",
        )
        frame_count = None
    else:
        record("frame-count", True, f"{frame_count} frames")

    tile_shape = handoff.get("tile_shape")
    if (
        not isinstance(tile_shape, list)
        or len(tile_shape) != 2
        or any(
            isinstance(v, bool) or not isinstance(v, int) or v < 1 for v in tile_shape
        )
    ):
        record(
            "tile-shape", False, f"tile_shape {tile_shape!r}", code="tile_shape_invalid"
        )
        tile_shape = None
    else:
        record("tile-shape", True, f"{tile_shape[0]}x{tile_shape[1]}")

    outputs = handoff.get("outputs") if isinstance(handoff.get("outputs"), dict) else {}
    record(
        "outputs-present",
        all(name in outputs for name in REQUIRED_OUTPUTS),
        f"declared outputs {sorted(outputs)}",
        code="output_missing",
    )
    digests: dict[str, str] = {}
    for name in REQUIRED_OUTPUTS:
        entry = outputs.get(name)
        if (
            not isinstance(entry, dict)
            or not entry.get("path")
            or not entry.get("sha256")
        ):
            record(
                f"output-{name}",
                False,
                "output entry lacks path or sha256",
                code="output_invalid",
            )
            continue
        path = base / str(entry["path"])
        if not path.is_file():
            record(
                f"output-{name}",
                False,
                f"missing {entry['path']}",
                code="output_missing",
            )
            continue
        digest = _sha256(path)
        digests[name] = digest
        record(
            f"output-{name}",
            digest == entry["sha256"],
            f"{entry['path']} digest "
            f"{'matches' if digest == entry['sha256'] else 'differs'}",
            code="output_digest_mismatch",
        )

    frames_entry = (
        outputs.get("frames") if isinstance(outputs.get("frames"), dict) else {}
    )
    frames_path = base / str(frames_entry.get("path") or "")
    frame_ids: list[int] = []
    times: list[float] = []
    if frames_path.is_file() and frame_count is not None:
        with frames_path.open(newline="", encoding="utf-8") as handle:
            reader = csv.reader(handle)
            header = next(reader, [])
            rows = list(reader)
        record(
            "frame-table-header",
            header == FRAME_TABLE_HEADER,
            f"header {header}",
            code="frame_table_header_mismatch",
        )
        record(
            "frame-table-count",
            len(rows) == frame_count,
            f"{len(rows)} rows against {frame_count} frames",
            code="frame_table_count_mismatch",
        )
        malformed = False
        for row in rows:
            if len(row) != 4:
                malformed = True
                continue
            try:
                frame_ids.append(int(row[0]))
                x = float(row[1])
                y = float(row[2])
                t = float(row[3])
            except ValueError:
                malformed = True
                continue
            if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(t)):
                malformed = True
            times.append(t)
        record(
            "frame-table-values",
            not malformed and frame_ids == list(range(len(rows))),
            "frame ids 0..N-1 with finite coordinates"
            if not malformed
            else "malformed row or non-sequential id",
            code="frame_table_values_invalid",
        )
        record(
            "frame-table-order",
            all(right >= left for left, right in zip(times, times[1:])),
            "time_s non-decreasing in emitted order",
            code="frame_table_time_order",
        )

    request_entry = (
        outputs.get("request") if isinstance(outputs.get("request"), dict) else {}
    )
    request_path = base / str(request_entry.get("path") or "")
    if request_path.is_file():
        try:
            import yaml
        except ImportError as error:  # pragma: no cover - the app venv has pyyaml
            raise HandoffError("pyyaml is required to read request.yaml") from error
        try:
            request = yaml.safe_load(request_path.read_text(encoding="utf-8"))
        except yaml.YAMLError as error:
            raise HandoffError(f"request.yaml is not YAML: {error}") from error
        if not isinstance(request, dict):
            record(
                "request-yaml",
                False,
                "request.yaml is not a mapping",
                code="request_not_mapping",
            )
        else:
            record(
                "request-order-pinned",
                request.get("order") == "as_given",
                f"order {request.get('order')!r}",
                code="request_order_not_pinned",
            )
            unknown = sorted(set(request) - ALLOWED_REQUEST_KEYS)
            record(
                "request-keys",
                not unknown,
                f"unknown top-level keys {unknown}" if unknown else "only schema keys",
                code="request_key_unknown",
            )
            record(
                "request-kind",
                isinstance(request.get("kind"), str) and bool(request.get("kind")),
                f"kind {request.get('kind')!r}",
                code="request_kind_missing",
            )
        if request_entry.get("sha256") and digests.get("request"):
            record(
                "request-digest-consistency",
                request_entry["sha256"] == digests["request"],
                "request digest agrees with the file on disk",
                code="request_digest_mismatch",
            )

    movie_entry = outputs.get("movie") if isinstance(outputs.get("movie"), dict) else {}
    movie_path = base / str(movie_entry.get("path") or "")
    if movie_path.is_file() and frame_count is not None and tile_shape is not None:
        try:
            import tifffile
        except ImportError as error:  # pragma: no cover - the app venv has tifffile
            raise HandoffError("tifffile is required to read the movie") from error
        with tifffile.TiffFile(movie_path) as tif:
            series = tif.series[0]
            axes = series.axes
            shape = series.shape
        record(
            "movie-axes",
            axes.startswith("T"),
            f"axes {axes!r}",
            code="movie_axes_not_t",
        )
        record(
            "movie-shape",
            len(shape) == 3
            and shape[0] == frame_count
            and [shape[1], shape[2]] == list(tile_shape),
            f"shape {shape} against {frame_count} x {tile_shape}",
            code="movie_shape_mismatch",
        )

    provenance_path = base / "provenance.json"
    if provenance_path.is_file():
        provenance = _load(provenance_path)
        record(
            "provenance-schema",
            isinstance(provenance, dict) and bool(provenance.get("schema")),
            "provenance.json carries a schema",
            code="provenance_invalid",
        )
        declared = provenance.get("outputs") if isinstance(provenance, dict) else {}
        if isinstance(declared, dict):
            mismatched = [
                name
                for name in REQUIRED_OUTPUTS
                if name in digests
                and isinstance(declared.get(name), dict)
                and declared[name].get("sha256")
                and declared[name]["sha256"] != digests[name]
            ]
            record(
                "provenance-outputs",
                not mismatched,
                f"provenance digests differ for {mismatched}"
                if mismatched
                else "provenance digests agree",
                code="provenance_digest_mismatch",
                severity="warning",
            )
    else:
        record(
            "provenance-present",
            False,
            "provenance.json is missing",
            code="provenance_missing",
        )

    declared_checks = handoff.get("checks")
    declared_ids = (
        [item.get("id") for item in declared_checks if isinstance(item, dict)]
        if isinstance(declared_checks, list)
        else []
    )
    record(
        "writer-checks-declared",
        all(identifier in declared_ids for identifier in WRITER_CHECK_IDS),
        f"declared {len(declared_ids)} writer checks",
        code="writer_check_missing",
        severity="warning",
    )

    accepted = not [item for item in findings if item["severity"] == "blocking"]
    return {
        "schema": REPORT_SCHEMA,
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "handoff": str(handoff_path),
        "handoff_schema": handoff.get("schema"),
        "frame_count": frame_count,
        "checks": checks,
        "declared_checks": [
            {"id": item.get("id"), "detail": item.get("detail")}
            for item in (declared_checks or [])
            if isinstance(item, dict)
        ],
        "findings": findings,
        "accepted": accepted,
        "notes": [
            "writer checks are recorded, not re-verified; the file-level checks "
            "above are recomputed",
            "this checks the handoff bundle, not the RTASPT product: use "
            "verify_product.py for the product",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    """Check one handoff bundle and print or write the report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--handoff", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    try:
        report = check_handoff(args.handoff)
    except HandoffError as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    failed = [check for check in report["checks"] if not check["ok"]]
    print(
        f"{Path(args.handoff).parent.name}: {len(report['checks'])} checks, "
        f"{len(failed)} failed, {len(report['findings'])} findings"
    )
    for check in failed:
        print(f"  {check['id']}: {check['detail']}")
    return 0 if report["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
