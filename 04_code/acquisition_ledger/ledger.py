"""Typed frame/pose/clock/action ledger and its pre-physical refusal checks.

Q02 of the 2026-10-27 increment asks the acquisition/storage boundary to retain
the camera sequence, exposure timing when available, service arrival,
publication, processing, decision, command and observed response on identified
clocks, with the seven action states, request ids, readbacks, frame refusals and
acquisition gaps. It also asks for mismatch, dropped-frame, stale-observation,
reversal and delayed-response fixtures *before* physical qualification.

This module owns the contract and the checks; the application owns emission. A
host assembles a :class:`Ledger` (or writes the same document shape) and calls
:func:`validate_document`. The validator never raises on a malformed row: it
reports a typed issue, because a refusal must survive the record that caused it.

Three rules from the backlog are enforced rather than described:

* a receipt-time pose is labelled as such and is never promoted to an
  exposure-associated pose without an exposure window;
* a timeout is ``outcome_unknown`` and never proof that an action did not
  occur, so marking a timed-out action ``failed`` or ``cancelled`` is refused;
* every clock a row's timestamps use is declared, and unknown uncertainty is
  reported instead of being assumed zero.

The module imports no device, host or image library.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Literal

LEDGER_SCHEMA = "ix71.acquisition-ledger.v1"

ActionState = Literal[
    "proposed",
    "accepted",
    "started",
    "completed",
    "failed",
    "cancelled",
    "outcome_unknown",
]

PoseSource = Literal["camera_receipt", "exposure_bracket", "unavailable"]

ACTION_STATES = (
    "proposed",
    "accepted",
    "started",
    "completed",
    "failed",
    "cancelled",
    "outcome_unknown",
)

#: Legal forward progress for one action; a completed action cannot restart.
ACTION_ORDER = {
    "proposed": 0,
    "accepted": 1,
    "started": 2,
    "completed": 3,
    "failed": 3,
    "cancelled": 3,
    "outcome_unknown": 3,
}

POSE_SOURCES = ("camera_receipt", "exposure_bracket", "unavailable")

Severity = Literal["blocking", "warning", "info"]

BLOCKING = "blocking"
WARNING = "warning"
INFO = "info"


@dataclass(frozen=True)
class LedgerLimits:
    """Bounds a host declares before a run, never after seeing its outcome.

    ``max_pose_offset_ns`` is how far a receipt pose may sit from the frame
    arrival it is attached to. ``max_response_latency_ns`` is how long an
    accepted command may take before its first observed response.
    """

    max_pose_offset_ns: int = 200_000_000
    max_response_latency_ns: int = 1_000_000_000
    expected_frames: int | None = None

    def __post_init__(self) -> None:
        """Reject non-positive bounds and a negative frame count."""
        for name in ("max_pose_offset_ns", "max_response_latency_ns"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if self.expected_frames is not None and (
            isinstance(self.expected_frames, bool)
            or not isinstance(self.expected_frames, int)
            or self.expected_frames < 0
        ):
            raise ValueError("expected_frames must be a nonnegative integer")


@dataclass(frozen=True)
class ClockMapping:
    """One source clock, the host clock it maps to, and the mapping's uncertainty."""

    clock: str
    host_clock: str
    offset_ns: int = 0
    uncertainty_ns: int | None = None

    def to_document(self) -> dict[str, Any]:
        """Return the JSON-safe clock declaration."""
        return {
            "clock": self.clock,
            "host_clock": self.host_clock,
            "offset_ns": self.offset_ns,
            "uncertainty_ns": self.uncertainty_ns,
        }


@dataclass(frozen=True)
class FrameLedgerRow:
    """One delivered or refused frame, its timing evidence and its pose.

    ``store`` names the image store the frame belongs to. Frame ids and array
    indices are store-scoped, so two stores may both contain frame 1; ordering is
    checked within a store, not across unrelated stores.
    """

    frame_id: int
    sequence_index: int
    pose_source: PoseSource = "camera_receipt"
    store: str | None = None
    source_frame_id: int | None = None
    arrival_ns: int | None = None
    pose_ns: int | None = None
    pose_xy_um: tuple[float, float] | None = None
    exposure_start_ns: int | None = None
    exposure_end_ns: int | None = None
    rejected_reason: str | None = None
    dropped: bool = False

    def to_document(self) -> dict[str, Any]:
        """Return the JSON-safe row."""
        return {
            "kind": "frame",
            "store": self.store,
            "frame_id": self.frame_id,
            "sequence_index": self.sequence_index,
            "pose_source": self.pose_source,
            "source_frame_id": self.source_frame_id,
            "arrival_ns": self.arrival_ns,
            "pose_ns": self.pose_ns,
            "pose_xy_um": (None if self.pose_xy_um is None else list(self.pose_xy_um)),
            "exposure_start_ns": self.exposure_start_ns,
            "exposure_end_ns": self.exposure_end_ns,
            "rejected_reason": self.rejected_reason,
            "dropped": self.dropped,
        }


@dataclass(frozen=True)
class ActionLedgerRow:
    """One proposed/started/finished action with its request id and readback.

    ``timed_out`` records that the host stopped waiting. A timed-out action is
    ``outcome_unknown``: the command may still have executed, so the validator
    refuses any other terminal state for it.
    """

    request_id: str
    action: str
    state: ActionState
    proposed_ns: int | None = None
    accepted_ns: int | None = None
    started_ns: int | None = None
    completed_ns: int | None = None
    observed_ns: int | None = None
    readback: dict[str, Any] | None = None
    error: str | None = None
    timed_out: bool = False

    def to_document(self) -> dict[str, Any]:
        """Return the JSON-safe row."""
        return {
            "kind": "action",
            "request_id": self.request_id,
            "action": self.action,
            "state": self.state,
            "proposed_ns": self.proposed_ns,
            "accepted_ns": self.accepted_ns,
            "started_ns": self.started_ns,
            "completed_ns": self.completed_ns,
            "observed_ns": self.observed_ns,
            "readback": self.readback,
            "error": self.error,
            "timed_out": self.timed_out,
        }


@dataclass(frozen=True)
class Ledger:
    """One run's frame and action ledger with its declared clocks."""

    run_id: str
    clocks: tuple[ClockMapping, ...]
    frames: tuple[FrameLedgerRow, ...] = ()
    actions: tuple[ActionLedgerRow, ...] = ()
    pose_semantics: str = "camera_receipt"
    exposure_association: str = "none"
    notes: dict[str, Any] | None = None

    def to_document(self) -> dict[str, Any]:
        """Return the JSON-safe ledger document a host writes beside its run."""
        if not self.run_id:
            raise ValueError("run_id is required")
        return {
            "schema": LEDGER_SCHEMA,
            "run_id": self.run_id,
            "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "clocks": [clock.to_document() for clock in self.clocks],
            "declared": {
                "pose_semantics": self.pose_semantics,
                "exposure_association": self.exposure_association,
            },
            "rows": [
                *(row.to_document() for row in self.frames),
                *(row.to_document() for row in self.actions),
            ],
            "notes": dict(self.notes or {}),
        }


@dataclass(frozen=True)
class Issue:
    """One typed refusal or retained limitation found in a ledger."""

    code: str
    severity: Severity
    detail: str
    row_index: int | None = None

    def to_document(self) -> dict[str, Any]:
        """Return the JSON-safe issue."""
        return {
            "code": self.code,
            "severity": self.severity,
            "detail": self.detail,
            "row_index": self.row_index,
        }


@dataclass(frozen=True)
class LedgerReport:
    """Issues plus the measured counts a run record quotes."""

    issues: tuple[Issue, ...]
    summary: dict[str, Any]

    @property
    def blocking(self) -> list[str]:
        """Return the distinct blocking codes, in first-seen order."""
        return list(
            dict.fromkeys(
                issue.code for issue in self.issues if issue.severity == BLOCKING
            )
        )

    @property
    def accepted(self) -> bool:
        """Return whether the ledger has no blocking issue."""
        return not self.blocking

    def to_document(self) -> dict[str, Any]:
        """Return the JSON-safe report."""
        return {
            "schema": f"{LEDGER_SCHEMA}.report",
            "accepted": self.accepted,
            "blocking": self.blocking,
            "issues": [issue.to_document() for issue in self.issues],
            "summary": self.summary,
        }


def _int_or_none(value: Any, name: str) -> int | None:
    """Return a nonnegative integer or None, refusing bools and floats."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer or null")
    return value


def validate_document(
    document: Any, limits: LedgerLimits | None = None
) -> LedgerReport:
    """Check one ledger document and return typed issues plus measured counts.

    The validator is deliberately tolerant of row content: a malformed row
    produces an issue rather than an exception, so a refused ledger can still be
    archived and inspected. Only a document that is not a mapping at all raises.
    """
    limits = LedgerLimits() if limits is None else limits
    if not isinstance(limits, LedgerLimits):
        raise TypeError("limits must be a LedgerLimits")
    if not isinstance(document, dict):
        raise ValueError("a ledger document must be a JSON object")

    issues: list[Issue] = []
    if document.get("schema") != LEDGER_SCHEMA:
        issues.append(
            Issue(
                "schema_missing",
                BLOCKING,
                f"expected schema {LEDGER_SCHEMA!r}, found {document.get('schema')!r}",
            )
        )
    run_id = document.get("run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        issues.append(Issue("run_id_missing", BLOCKING, "run_id is required"))

    clocks = document.get("clocks")
    clock_docs = clocks if isinstance(clocks, list) else []
    if not clock_docs:
        issues.append(
            Issue(
                "clock_mapping_missing",
                BLOCKING,
                "no clock mapping is declared; timestamps cannot be interpreted",
            )
        )
    for index, clock in enumerate(clock_docs):
        if not isinstance(clock, dict):
            issues.append(
                Issue(
                    "clock_mapping_invalid", BLOCKING, "clock is not an object", index
                )
            )
            continue
        name = clock.get("clock")
        host = clock.get("host_clock")
        if (
            not isinstance(name, str)
            or not name.strip()
            or not isinstance(host, str)
            or not host.strip()
        ):
            issues.append(
                Issue(
                    "clock_mapping_invalid",
                    BLOCKING,
                    "clock and host_clock are required",
                    index,
                )
            )
            continue
        uncertainty = clock.get("uncertainty_ns")
        if uncertainty is None:
            issues.append(
                Issue(
                    "clock_uncertainty_missing",
                    WARNING,
                    f"clock {name!r} declares no mapping uncertainty",
                    index,
                )
            )

    declared = (
        document.get("declared") if isinstance(document.get("declared"), dict) else {}
    )
    pose_semantics = declared.get("pose_semantics")
    exposure_association = declared.get("exposure_association")
    rows = document.get("rows")
    row_docs = rows if isinstance(rows, list) else []
    if not isinstance(rows, list):
        issues.append(Issue("rows_missing", BLOCKING, "rows must be a list"))
    frame_rows = [
        row for row in row_docs if isinstance(row, dict) and row.get("kind") == "frame"
    ]
    action_rows = [
        row for row in row_docs if isinstance(row, dict) and row.get("kind") == "action"
    ]
    unknown_kind = [
        index
        for index, row in enumerate(row_docs)
        if not isinstance(row, dict) or row.get("kind") not in {"frame", "action"}
    ]
    for index in unknown_kind:
        issues.append(
            Issue(
                "row_kind_invalid", BLOCKING, "row kind must be frame or action", index
            )
        )

    frame_ids: list[int] = []
    sequence_indices: list[int] = []
    frames_by_store: dict[str, list[tuple[int, int, int]]] = {}
    pose_offsets: list[int] = []
    for index, row in enumerate(row_docs):
        if not isinstance(row, dict) or row.get("kind") != "frame":
            continue
        frame_id = row.get("frame_id")
        sequence = row.get("sequence_index")
        if isinstance(frame_id, bool) or not isinstance(frame_id, int) or frame_id < 1:
            issues.append(
                Issue(
                    "frame_id_invalid",
                    BLOCKING,
                    "frame_id must be a positive integer",
                    index,
                )
            )
            continue
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
            issues.append(
                Issue(
                    "sequence_index_invalid",
                    BLOCKING,
                    "sequence_index must be a nonnegative integer",
                    index,
                )
            )
            continue
        frame_ids.append(frame_id)
        sequence_indices.append(sequence)
        frames_by_store.setdefault(str(row.get("store") or ""), []).append(
            (index, frame_id, sequence)
        )
        source = row.get("pose_source")
        if source not in POSE_SOURCES:
            issues.append(
                Issue(
                    "pose_source_invalid",
                    BLOCKING,
                    f"unknown pose_source {source!r}",
                    index,
                )
            )
            continue
        arrival = _optional_int(row.get("arrival_ns"), "arrival_ns", issues, index)
        pose_ns = _optional_int(row.get("pose_ns"), "pose_ns", issues, index)
        dropped = bool(row.get("dropped"))
        rejected = row.get("rejected_reason")
        has_pose = row.get("pose_xy_um") is not None
        if not dropped and not has_pose and not rejected:
            issues.append(
                Issue(
                    "pose_missing",
                    BLOCKING,
                    "frame has no pose, no refusal reason and is not marked dropped",
                    index,
                )
            )
        if rejected is not None and not isinstance(rejected, str):
            issues.append(
                Issue(
                    "rejected_reason_invalid",
                    WARNING,
                    "rejected_reason must be text",
                    index,
                )
            )
        if rejected is not None and not rejected.strip():
            issues.append(
                Issue(
                    "rejected_frame_without_reason",
                    WARNING,
                    "empty refusal reason",
                    index,
                )
            )
        if source == "exposure_bracket":
            start = _optional_int(
                row.get("exposure_start_ns"), "exposure_start_ns", issues, index
            )
            end = _optional_int(
                row.get("exposure_end_ns"), "exposure_end_ns", issues, index
            )
            if start is None or end is None or end < start:
                issues.append(
                    Issue(
                        "exposure_window_missing",
                        BLOCKING,
                        "an exposure-associated pose needs a valid exposure window",
                        index,
                    )
                )
            if exposure_association != "bracket":
                issues.append(
                    Issue(
                        "exposure_association_undeclared",
                        BLOCKING,
                        "a bracket pose is recorded but the ledger declares no bracket "
                        "association",
                        index,
                    )
                )
        if source == "camera_receipt" and pose_semantics == "exposure_bracket":
            issues.append(
                Issue(
                    "receipt_pose_declared_as_exposure",
                    BLOCKING,
                    "the ledger declares bracket poses while this row is a "
                    "receipt pose",
                    index,
                )
            )
        if source != "unavailable" and arrival is not None and pose_ns is not None:
            offset = pose_ns - arrival
            pose_offsets.append(offset)
            if abs(offset) > limits.max_pose_offset_ns:
                issues.append(
                    Issue(
                        "pose_offset_exceeds_limit",
                        WARNING,
                        f"pose sits {offset / 1e6:.1f} ms from its frame arrival "
                        f"(limit {limits.max_pose_offset_ns / 1e6:.1f} ms)",
                        index,
                    )
                )

    for store, values in frames_by_store.items():
        label_store = f" in store {store!r}" if store else ""
        for label, series in (
            ("frame_id", [item[1] for item in values]),
            ("sequence_index", [item[2] for item in values]),
        ):
            duplicates = sorted({value for value in series if series.count(value) > 1})
            if duplicates:
                issues.append(
                    Issue(
                        f"{label}_duplicate",
                        BLOCKING,
                        f"repeated {label}{label_store}: {duplicates}",
                    )
                )
            if any(right <= left for left, right in zip(series, series[1:])):
                issues.append(
                    Issue(
                        f"{label}_not_monotonic",
                        BLOCKING,
                        f"{label} must strictly increase{label_store}",
                    )
                )
            gaps = [
                (left, right)
                for left, right in zip(series, series[1:])
                if right - left > 1
            ]
            if gaps:
                issues.append(
                    Issue(
                        f"{label}_gap",
                        WARNING,
                        f"{len(gaps)} {label} gap(s){label_store}: {gaps[:5]}",
                    )
                )
    if limits.expected_frames is not None and len(frame_rows) != limits.expected_frames:
        issues.append(
            Issue(
                "frame_count_mismatch",
                BLOCKING,
                f"{len(frame_rows)} frame rows against "
                f"{limits.expected_frames} expected",
            )
        )

    request_ids: list[str] = []
    for index, row in enumerate(row_docs):
        if not isinstance(row, dict) or row.get("kind") != "action":
            continue
        request_id = row.get("request_id")
        if not isinstance(request_id, str) or not request_id.strip():
            issues.append(
                Issue("request_id_missing", BLOCKING, "action has no request_id", index)
            )
        else:
            request_ids.append(request_id)
        state = row.get("state")
        if state not in ACTION_STATES:
            issues.append(
                Issue(
                    "action_state_invalid", BLOCKING, f"unknown state {state!r}", index
                )
            )
            continue
        times = {}
        for name in (
            "proposed_ns",
            "accepted_ns",
            "started_ns",
            "completed_ns",
            "observed_ns",
        ):
            times[name] = _optional_int(row.get(name), name, issues, index)
        for earlier, later in (
            ("proposed_ns", "accepted_ns"),
            ("accepted_ns", "started_ns"),
            ("started_ns", "completed_ns"),
            ("accepted_ns", "observed_ns"),
        ):
            first = times[earlier]
            second = times[later]
            if first is not None and second is not None and second < first:
                issues.append(
                    Issue(
                        "action_time_out_of_order",
                        BLOCKING,
                        f"{later} precedes {earlier}",
                        index,
                    )
                )
        if (
            state in {"accepted", "started", "completed"}
            and times["proposed_ns"] is None
        ):
            issues.append(
                Issue(
                    "proposed_time_missing",
                    WARNING,
                    f"{state} action retains no proposal time",
                    index,
                )
            )
        if state == "completed" and times["started_ns"] is None:
            issues.append(
                Issue(
                    "started_time_missing",
                    WARNING,
                    "a completed action retains no start time",
                    index,
                )
            )
        if state == "completed" and times["observed_ns"] is None:
            issues.append(
                Issue(
                    "completed_without_observation",
                    WARNING,
                    "a completed action records no observed response; "
                    "completion is a claim",
                    index,
                )
            )
        timed_out = bool(row.get("timed_out"))
        if timed_out and state != "outcome_unknown":
            issues.append(
                Issue(
                    "timeout_not_outcome_unknown",
                    BLOCKING,
                    "a timeout is outcome_unknown, not proof that the action "
                    "did not occur",
                    index,
                )
            )
        if state == "outcome_unknown" and not timed_out and not row.get("error"):
            issues.append(
                Issue(
                    "outcome_unknown_without_evidence",
                    WARNING,
                    "outcome_unknown needs the timeout or error that left it unknown",
                    index,
                )
            )
        accepted = times["accepted_ns"]
        observed = times["observed_ns"]
        if accepted is not None and observed is not None:
            latency = observed - accepted
            if latency > limits.max_response_latency_ns:
                issues.append(
                    Issue(
                        "response_latency_exceeds_limit",
                        WARNING,
                        f"first response arrived {latency / 1e6:.1f} ms after "
                        f"(limit {limits.max_response_latency_ns / 1e6:.1f} ms)",
                        index,
                    )
                )
    duplicate_requests = sorted(
        {value for value in request_ids if request_ids.count(value) > 1}
    )
    if duplicate_requests:
        issues.append(
            Issue(
                "duplicate_request_id",
                BLOCKING,
                f"repeated request ids: {duplicate_requests}",
            )
        )
    if not action_rows:
        issues.append(
            Issue(
                "no_action_records",
                INFO,
                "the ledger carries no action rows; command/response "
                "evidence is absent",
            )
        )

    summary = {
        "frames_total": len(frame_ids),
        "action_rows": len(action_rows),
        "stores": {
            store: {
                "frames": len(values),
                "frame_id_first": values[0][1] if values else None,
                "frame_id_last": values[-1][1] if values else None,
            }
            for store, values in frames_by_store.items()
        },
        "pose_offsets_measured": len(pose_offsets),
        "pose_offset_median_ns": int(median(pose_offsets)) if pose_offsets else None,
        "pose_offset_max_abs_ns": max(
            (abs(value) for value in pose_offsets), default=None
        ),
        "declared_pose_semantics": pose_semantics,
        "declared_exposure_association": exposure_association,
    }
    return LedgerReport(tuple(issues), summary)


def _optional_int(value: Any, name: str, issues: list[Issue], index: int) -> int | None:
    """Return an optional nonnegative integer, reporting a malformed value."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        issues.append(
            Issue(
                f"{name}_invalid",
                WARNING,
                f"{name} must be a nonnegative integer",
                index,
            )
        )
        return None
    return value


def adapt_recorded_run(run_dir: Path) -> dict[str, Any]:
    """Build a ledger document from a recorded run's position and timing sidecars.

    The recorder that produced the 2026-10-24/26 runs writes receipt-time poses
    and a timing sidecar whose clock is the host monotonic clock. This adapter
    states exactly that and no more: it does not invent an exposure window, a
    clock uncertainty or action rows the recorder never wrote. It also reports,
    without interpreting, the rows that cannot be joined across the two files
    and the frames the strip record counts but the position sidecars omit.
    """
    run_dir = Path(run_dir)
    reports = sorted(run_dir.glob("*-report.json"))
    if len(reports) != 1:
        raise ValueError(
            f"expected one *-report.json under {run_dir}, found {len(reports)}"
        )
    report = json.loads(reports[0].read_text(encoding="utf-8"))
    run_id = str(report.get("confirmation_id") or "")
    positions = sorted(run_dir.rglob("*.positions.json"))
    timing = sorted(run_dir.rglob("*.timing.json"))
    if not positions:
        raise ValueError(f"no *.positions.json under {run_dir}")

    clock_name: str | None = None
    timing_by_store: dict[str, dict[int, dict[str, int]]] = {}
    for path in timing:
        document = json.loads(path.read_text(encoding="utf-8"))
        clock_name = clock_name or document.get("clock")
        store = _store_key(path)
        timing_by_store[store] = {
            int(row["written_index"]): {
                "arrival_ns": int(row["service_monotonic_ns"]),
                "frame_id": int(row.get("frame_id", 0)),
            }
            for row in document.get("records") or []
            if isinstance(row, dict)
            and isinstance(row.get("written_index"), int)
            and isinstance(row.get("service_monotonic_ns"), int)
        }
    strip_by_row = _strip_rows(run_dir, run_id)

    frames: list[dict[str, Any]] = []
    pose_without_timing = 0
    timing_without_pose = 0
    absent: list[dict[str, Any]] = []
    for path in positions:
        document = json.loads(path.read_text(encoding="utf-8"))
        store = _store_key(path)
        arrivals = timing_by_store.get(store, {})
        used_arrivals: set[int] = set()
        row_number = _store_row_number(store)
        positioned = 0
        for frame in document.get("frames") or []:
            frame_id = int(frame["frame_id"])
            sequence = int(frame.get("array_index", positioned))
            arrival = arrivals.get(sequence)
            if arrival is not None:
                used_arrivals.add(sequence)
                arrival_ns: int | None = arrival["arrival_ns"]
                source_frame_id: int | None = arrival["frame_id"]
            else:
                pose_without_timing += 1
                arrival_ns = None
                source_frame_id = None
            time_s = frame.get("time")
            pose_ns = None if time_s is None else int(round(float(time_s) * 1e9))
            positioned += 1
            frames.append(
                {
                    "kind": "frame",
                    "store": store,
                    "frame_id": frame_id,
                    "sequence_index": sequence,
                    "pose_source": "camera_receipt",
                    "source_frame_id": source_frame_id,
                    "arrival_ns": arrival_ns,
                    "pose_ns": pose_ns,
                    "pose_xy_um": list(frame.get("stage_xy_um") or []) or None,
                    "exposure_start_ns": None,
                    "exposure_end_ns": None,
                    "rejected_reason": None,
                    "dropped": False,
                }
            )
        timing_without_pose += len(set(arrivals) - used_arrivals)
        strip = strip_by_row.get(row_number) if row_number is not None else None
        if strip is not None and strip.get("captured_count") is not None:
            captured = int(strip["captured_count"])
            if captured != positioned:
                absent.append(
                    {
                        "row": row_number,
                        "captured_count": captured,
                        "positioned_count": positioned,
                        "difference": captured - positioned,
                    }
                )

    clocks = (
        [
            {
                "clock": clock_name,
                "host_clock": "python.time.monotonic_ns",
                "offset_ns": 0,
                "uncertainty_ns": None,
            }
        ]
        if clock_name
        else []
    )
    rejections = [
        {"row": row, "pose_index": index, "status": frame["status"]}
        for row, strip in strip_by_row.items()
        for index, frame in enumerate(strip.get("frame_poses") or [])
        if isinstance(frame, dict)
        and isinstance(frame.get("status"), str)
        and frame["status"] != "associated_receipt"
    ]
    label_mismatches = sum(
        1
        for row in frames
        if row["source_frame_id"] is not None
        and row["source_frame_id"] != row["frame_id"]
    )
    return {
        "schema": LEDGER_SCHEMA,
        "run_id": run_id,
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "clocks": clocks,
        "declared": {
            "pose_semantics": "camera_receipt",
            "exposure_association": "none",
            "adapted_from": "positions and timing sidecars",
            "join_key": (
                "store + sequence_index (timing written_index / position array_index); "
                "frame_id is source-local and differs between the two files"
            ),
            "source_label_mismatches": label_mismatches,
            "timing_rows_without_pose": timing_without_pose,
            "pose_rows_without_timing": pose_without_timing,
            "frames_absent_from_positions": absent,
            "rejected_poses": rejections,
        },
        "rows": frames,
        "notes": {
            "source": "adapt_recorded_run",
            "action_records": "the recorder emitted none",
        },
    }


def _store_key(path: Path) -> str:
    """Return the store stem a sidecar belongs to."""
    name = path.name
    for suffix in (".positions.json", ".timing.json"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return path.stem


def _store_row_number(store: str) -> int | None:
    """Return the zero-based row a recorder store name implies, when it has one."""
    tail = store.rsplit("_", 1)[-1]
    if tail.isdigit():
        return int(tail) - 1
    return None


def _strip_rows(run_dir: Path, run_id: str) -> dict[int, dict[str, Any]]:
    """Return the strip record's per-row entries, keyed by zero-based row."""
    if not run_id:
        return {}
    candidates = sorted(run_dir.glob(f"strips/*-{run_id}-strips.json"))
    if len(candidates) != 1:
        return {}
    document = json.loads(candidates[0].read_text(encoding="utf-8"))
    rows = {}
    for strip in document.get("strips") or []:
        row = strip.get("row")
        if isinstance(row, int):
            rows[row] = strip
    return rows


def main(argv: list[str] | None = None) -> int:
    """Validate a recorded run or a saved ledger document, printing the report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, help="recorded run directory to adapt")
    parser.add_argument("--ledger", type=Path, help="saved ledger JSON to validate")
    parser.add_argument("--out", type=Path, help="write the ledger document here")
    parser.add_argument("--report", type=Path, help="write the validation report here")
    args = parser.parse_args(argv)
    if args.ledger:
        document = json.loads(args.ledger.read_text(encoding="utf-8"))
    elif args.run:
        document = adapt_recorded_run(args.run)
    else:
        parser.error("provide --run or --ledger")
        return 2
    report = validate_document(document)
    print(
        f"{document.get('run_id')}: {report.summary['frames_total']} frames, "
        f"{report.summary['action_rows']} actions, "
        f"pose offset median {report.summary['pose_offset_median_ns']}, "
        f"{len(report.blocking)} blocking"
    )
    for issue in report.issues:
        print(f"  {issue.severity:<8} {issue.code}: {issue.detail}")
    if args.out:
        args.out.write_text(json.dumps(document, indent=1) + "\n", encoding="utf-8")
    if args.report:
        args.report.write_text(
            json.dumps(report.to_document(), indent=1) + "\n", encoding="utf-8"
        )
    return 0 if report.accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
