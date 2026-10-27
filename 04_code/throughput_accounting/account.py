"""Capture, publication and consumer accounting with explicit gaps (Q09).

Q09 asks for attempted / captured / published / refused / processed / released /
persisted / missing frame accounting, queue occupancy, restart overhead and
exposure-to-output latency, with completeness reported separately from latency.
The hard part is not the arithmetic; it is refusing to let an unmeasured link
look like a zero.

This module has two modes:

``--run <dir>``
    Accounts a finished acquisition from its stores, position sidecars, timing
    sidecars and strip record. Captured, posed, timed and persisted frames are
    measured; attempted, published, refused, processed, released and consumed are
    reported ``not_recorded`` because the recorder wrote no such record.

``--consumer-log <file>``
    Accounts a publication/consumer log (the replay fixture). Attempted,
    published, processed, released, queue occupancy, restarts and latency are
    measured; the run-side categories are reported ``not_recorded``.

Every category carries a value and a status, and the document lists what it
could not measure. Nothing is inferred: a missing record is never a zero.

    python account.py --run <run-dir> --out run_accounting.json
    python account.py --consumer-log consumer.example.json --out consumer.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = "ix71.throughput-accounting.1"
CONSUMER_SCHEMA = "ix71.consumer-log.1"

CATEGORIES = (
    "attempted",
    "captured",
    "published",
    "refused",
    "processed",
    "released",
    "persisted",
    "missing",
)


class AccountingError(ValueError):
    """The source cannot support the accounting it was asked for."""


def _cell(value: Any, status: str, source: str | None = None) -> dict[str, Any]:
    """Return one value/status/source cell."""
    return {"value": value, "status": status, "source": source}


def _not_recorded(reason: str) -> dict[str, Any]:
    """Return a category the source does not contain."""
    return {"value": None, "status": "not_recorded", "reason": reason}


def _percentile(values: list[float], fraction: float) -> float | None:
    """Return a nearest-rank percentile of a nonempty list."""
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(fraction * (len(ordered) - 1)))))
    return round(ordered[index], 4)


def _read_json(path: Path) -> Any:
    """Read one JSON source, refusing an unreadable file by name."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise AccountingError(f"missing source: {path}") from error
    except json.JSONDecodeError as error:
        raise AccountingError(f"unreadable JSON in {path}: {error}") from error


def _sidecar_summary(paths: list[Path]) -> dict[str, Any]:
    """Return the camera mode and per-sidecar frame counts."""
    documents = [_read_json(path) for path in paths]
    first = documents[0]
    stores = []
    for path, document in zip(paths, documents):
        stores.append(
            {
                "sidecar": path.name,
                "frames_written": document.get("frames_written"),
                "frames": len(document.get("frames") or []),
                "exit_status": document.get("exit_status"),
            }
        )
    return {
        "camera_exposure_ms": first.get("camera_exposure_ms"),
        "camera_binning_xy": first.get("camera_binning_xy"),
        "camera_roi_sensor_pixels": first.get("camera_roi_sensor_pixels"),
        "stores": stores,
    }


def account_run(run_dir: Path) -> dict[str, Any]:
    """Account a recorded run's capture, pose, timing and persistence links."""
    run_dir = Path(run_dir)
    reports = sorted(run_dir.glob("*-report.json"))
    if len(reports) != 1:
        raise AccountingError(
            f"expected one *-report.json under {run_dir}, found {len(reports)}"
        )
    report = _read_json(reports[0])
    confirmation_id = str(report.get("confirmation_id") or "")
    positions = sorted(run_dir.rglob("*.positions.json"))
    timing = sorted(run_dir.rglob("*.timing.json"))
    if not positions:
        raise AccountingError(f"no *.positions.json under {run_dir}")
    sidecars = _sidecar_summary(positions)
    stores = report.get("stores") or {}
    captured = sum(int(shape[0]) for shape in stores.values() if shape)
    posed = sum(
        int(item["frames_written"])
        for item in sidecars["stores"]
        if item["frames_written"] is not None
    )
    timed = 0
    timing_rows = []
    for path in timing:
        document = _read_json(path)
        written = document.get("written_count")
        timed += (
            int(written) if written is not None else len(document.get("records") or [])
        )
        timing_rows.append({"timing": path.name, "written_count": written})
    persisted = captured

    strips = sorted(run_dir.glob(f"strips/*-{confirmation_id}-strips.json"))
    strip_rows = []
    if len(strips) == 1:
        strip_document = _read_json(strips[0])
        for strip in strip_document.get("strips") or []:
            strip_rows.append(
                {
                    "row": strip.get("row"),
                    "captured_count": strip.get("captured_count"),
                    "frame_budget": strip.get("frame_budget"),
                    "terminal_state": strip.get("terminal_state"),
                }
            )

    findings: list[dict[str, Any]] = []
    if captured != posed:
        findings.append(
            {
                "code": "captured_without_pose",
                "severity": "blocking",
                "detail": f"{captured} captured against {posed} posed",
            }
        )
    if captured != timed:
        findings.append(
            {
                "code": "captured_without_timing",
                "severity": "warning",
                "detail": f"{captured} captured against {timed} timing rows",
            }
        )
    if report.get("session_outcome") != "success":
        findings.append(
            {
                "code": "run_incomplete",
                "severity": "warning",
                "detail": report.get("error") or report.get("session_outcome"),
            }
        )
    over_budget = [
        row
        for row in strip_rows
        if row["frame_budget"] is not None
        and row["captured_count"] is not None
        and int(row["captured_count"]) > int(row["frame_budget"])
    ]
    if over_budget:
        findings.append(
            {
                "code": "frame_budget_exceeded",
                "severity": "warning",
                "detail": over_budget,
            }
        )

    return {
        "schema": SCHEMA,
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": {
            "mode": "recorded_run",
            "run_dir": str(run_dir),
            "confirmation_id": confirmation_id,
            "store_count": len(stores),
        },
        "camera_mode": {
            "exposure_ms": sidecars["camera_exposure_ms"],
            "binning_xy": sidecars["camera_binning_xy"],
            "roi_sensor_pixels": sidecars["camera_roi_sensor_pixels"],
        },
        "categories": {
            "attempted": _not_recorded("the recorder wrote no attempt log"),
            "captured": _cell(captured, "measured", "report stores"),
            "published": _not_recorded("no publication record exists for this run"),
            "refused": _not_recorded("no refusal record exists for this run"),
            "processed": _not_recorded("no consumer processed this run"),
            "released": _not_recorded("no consumer released this run"),
            "persisted": _cell(persisted, "measured", "report stores"),
            "missing": _cell(
                max(0, captured - posed), "derived", "captured minus posed"
            ),
        },
        "queue": _not_recorded("no queue record exists for this run"),
        "latency": _not_recorded("no exposure-to-output timestamps exist for this run"),
        "restarts": _not_recorded("the recorder wrote no session boundaries"),
        "memory": _not_recorded("peak memory was not recorded"),
        "stores": {
            "captured": stores,
            "sidecars": sidecars["stores"],
            "timing": timing_rows,
            "strips": strip_rows,
        },
        "findings": findings,
        "notes": [
            "captured and persisted are the same store length here; they are kept "
            "separate because a consumer run may persist fewer frames than were "
            "captured",
            "a category the recorder did not write is not zero",
        ],
        "accepted": False,
    }


def account_consumer(log: Any, *, source: str | None = None) -> dict[str, Any]:
    """Account a publication/consumer log, including queue occupancy and latency."""
    if not isinstance(log, dict):
        raise AccountingError("consumer log must be an object")
    if log.get("schema") != CONSUMER_SCHEMA:
        raise AccountingError(f"consumer log schema must be {CONSUMER_SCHEMA!r}")
    rows = log.get("rows")
    if not isinstance(rows, list) or not rows:
        raise AccountingError("consumer log rows must be a nonempty list")
    budget = log.get("budget") or {}
    capacity = budget.get("queue_capacity")
    latency_budget_ms = budget.get("max_latency_ms")

    parsed = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise AccountingError(f"rows[{index}] is not an object")
        frame_id = row.get("frame_id")
        if isinstance(frame_id, bool) or not isinstance(frame_id, int) or frame_id < 0:
            raise AccountingError(
                f"rows[{index}].frame_id must be a nonnegative integer"
            )
        parsed.append(
            {
                "frame_id": frame_id,
                "attempted_ns": row.get("attempted_ns"),
                "published_ns": row.get("published_ns"),
                "processed_ns": row.get("processed_ns"),
                "released_ns": row.get("released_ns"),
                "dropped": bool(row.get("dropped")),
            }
        )
    frame_ids = [row["frame_id"] for row in parsed]
    duplicates = sorted({value for value in frame_ids if frame_ids.count(value) > 1})
    if duplicates:
        raise AccountingError(f"repeated frame ids: {duplicates}")

    attempted = [
        _has_any(row, "attempted_ns", "published_ns", "processed_ns", "released_ns")
        for row in parsed
    ]
    published = [row for row in parsed if row["published_ns"] is not None]
    processed = [row for row in parsed if row["processed_ns"] is not None]
    released = [row for row in parsed if row["released_ns"] is not None]
    dropped = [row for row in parsed if row["dropped"]]
    missing = [
        row for row in parsed if not row["dropped"] and row["published_ns"] is None
    ]

    latency_ms = [
        (row["processed_ns"] - row["published_ns"]) / 1e6
        for row in processed
        if row["published_ns"] is not None
    ]
    release_latency_ms = [
        (row["released_ns"] - row["processed_ns"]) / 1e6
        for row in released
        if row["processed_ns"] is not None
    ]
    ordered = sorted(parsed, key=lambda row: row["frame_id"])
    outstanding = 0
    max_outstanding = 0
    for row in ordered:
        if row["published_ns"] is not None:
            outstanding += 1
            max_outstanding = max(max_outstanding, outstanding)
        if row["released_ns"] is not None and outstanding > 0:
            outstanding -= 1
    sessions = log.get("sessions")
    restarts = None if not isinstance(sessions, list) else max(0, len(sessions) - 1)

    findings: list[dict[str, Any]] = []
    if dropped:
        findings.append(
            {
                "code": "frames_dropped",
                "severity": "warning",
                "detail": f"{len(dropped)} rows are marked dropped",
            }
        )
    if missing:
        findings.append(
            {
                "code": "missing_publications",
                "severity": "blocking",
                "detail": [row["frame_id"] for row in missing],
            }
        )
    unconsumed = len(published) - len(released)
    if unconsumed:
        findings.append(
            {
                "code": "unreleased_at_close",
                "severity": "warning",
                "detail": f"{unconsumed} published frames were not released",
            }
        )
    gaps = [
        (left, right)
        for left, right in zip(sorted(frame_ids), sorted(frame_ids)[1:])
        if right - left > 1
    ]
    if gaps:
        findings.append(
            {
                "code": "sequence_gap",
                "severity": "warning",
                "detail": gaps[:5],
            }
        )
    if capacity is not None and max_outstanding > int(capacity):
        findings.append(
            {
                "code": "queue_overflow",
                "severity": "blocking",
                "detail": f"peak occupancy {max_outstanding} over capacity {capacity}",
            }
        )
    p95 = _percentile(latency_ms, 0.95)
    if (
        latency_budget_ms is not None
        and p95 is not None
        and p95 > float(latency_budget_ms)
    ):
        findings.append(
            {
                "code": "latency_over_budget",
                "severity": "warning",
                "detail": f"p95 {p95} ms over budget {latency_budget_ms} ms",
            }
        )

    total = len(parsed)
    return {
        "schema": SCHEMA,
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": {
            "mode": "consumer_log",
            "log": source,
            "stream_id": log.get("stream_id"),
            "rows": total,
        },
        "camera_mode": log.get("camera_mode")
        if isinstance(log.get("camera_mode"), dict)
        else None,
        "categories": {
            "attempted": _cell(sum(attempted), "measured", "consumer log"),
            "captured": _not_recorded("the consumer log starts after capture"),
            "published": _cell(len(published), "measured", "consumer log"),
            "refused": _cell(len(dropped), "measured", "consumer log dropped flag"),
            "processed": _cell(len(processed), "measured", "consumer log"),
            "released": _cell(len(released), "measured", "consumer log"),
            "persisted": _not_recorded("no persistence record exists in this log"),
            "missing": _cell(
                len(missing), "derived", "non-dropped rows without a publication"
            ),
        },
        "queue": (
            _not_recorded("the log declares no capacity")
            if capacity is None
            else _cell(
                {"peak_occupancy": max_outstanding, "capacity": int(capacity)},
                "derived",
                "published minus released, ordered by frame id",
            )
        ),
        "latency": (
            _not_recorded("no row carries both a publication and a processing time")
            if not latency_ms
            else _cell(
                {
                    "publish_to_process_ms": {
                        "count": len(latency_ms),
                        "median": _percentile(latency_ms, 0.5),
                        "p95": p95,
                        "max": round(max(latency_ms), 4),
                    },
                    "process_to_release_ms": (
                        None
                        if not release_latency_ms
                        else {
                            "count": len(release_latency_ms),
                            "median": _percentile(release_latency_ms, 0.5),
                            "p95": _percentile(release_latency_ms, 0.95),
                        }
                    ),
                    "clock_uncertainty_ms": budget.get("clock_uncertainty_ms"),
                },
                "derived",
                "consumer log timestamps",
            )
        ),
        "restarts": (
            _not_recorded("the log declares no sessions")
            if restarts is None
            else _cell(restarts, "derived", "session list length minus one")
        ),
        "memory": _not_recorded("peak memory was not recorded"),
        "findings": findings,
        "notes": [
            "capture, persistence and attempt counts are absent from a consumer log",
            "queue occupancy is published minus released, not a device readback",
        ],
        "accepted": False,
    }


def _has_any(row: dict[str, Any], *keys: str) -> bool:
    """Return whether any named timestamp is present."""
    return any(row.get(key) is not None for key in keys)


def main(argv: list[str] | None = None) -> int:
    """Account a recorded run or a consumer log and write the document."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path)
    parser.add_argument("--consumer-log", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.run is not None:
            document = account_run(args.run)
        elif args.consumer_log is not None:
            document = account_consumer(
                _read_json(args.consumer_log), source=str(args.consumer_log)
            )
        else:
            parser.error("provide --run or --consumer-log")
            return 2
    except AccountingError as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(document, indent=1) + "\n", encoding="utf-8")
    measured = {
        name: cell["value"]
        for name, cell in document["categories"].items()
        if cell["status"] == "measured"
    }
    source = document["source"]
    label = source.get("confirmation_id") or source.get("log")
    print(f"{label}: {source.get('mode')}, measured {measured}")
    for finding in document["findings"]:
        print(f"  {finding['severity']:<8} {finding['code']}: {finding['detail']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
