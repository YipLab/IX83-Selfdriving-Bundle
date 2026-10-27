"""Hardware-free tests for the acquisition ledger contract and its refusals.

Each case builds a small ledger document and checks one finding. The recorded-run
cases at the end only run when the 2026-10-24 session files are present.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import ledger
import pytest
from ledger import (
    ActionLedgerRow,
    ClockMapping,
    FrameLedgerRow,
    Ledger,
    LedgerLimits,
)

SESSION = (
    Path(__file__).resolve().parents[2]
    / "08_session_logs"
    / "20261024T_long_strip_broom_01"
)


def _frame(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "kind": "frame",
        "store": "store-1",
        "frame_id": 1,
        "sequence_index": 0,
        "pose_source": "camera_receipt",
        "source_frame_id": 1,
        "arrival_ns": 1_000_000_000,
        "pose_ns": 1_010_000_000,
        "pose_xy_um": [0.0, 0.0],
        "exposure_start_ns": None,
        "exposure_end_ns": None,
        "rejected_reason": None,
        "dropped": False,
    }
    row.update(overrides)
    return row


def _action(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "kind": "action",
        "request_id": "req-1",
        "action": "move_relative",
        "state": "completed",
        "proposed_ns": 1,
        "accepted_ns": 2,
        "started_ns": 3,
        "completed_ns": 5,
        "observed_ns": 4,
        "readback": {"x": 1.0},
        "error": None,
        "timed_out": False,
    }
    row.update(overrides)
    return row


def _document(
    *,
    rows: list[dict[str, Any]] | None = None,
    clocks: list[dict[str, Any]] | None = None,
    declared: dict[str, Any] | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    document: dict[str, Any] = {
        "schema": ledger.LEDGER_SCHEMA,
        "run_id": "run-test",
        "clocks": clocks
        if clocks is not None
        else [
            {
                "clock": "service",
                "host_clock": "monotonic",
                "offset_ns": 0,
                "uncertainty_ns": 1000,
            }
        ],
        "declared": declared
        if declared is not None
        else {"pose_semantics": "camera_receipt", "exposure_association": "none"},
        "rows": rows if rows is not None else [_frame(), _action()],
    }
    document.update(overrides)
    return document


def _codes(report: ledger.LedgerReport) -> dict[str, str]:
    return {issue.code: issue.severity for issue in report.issues}


def test_clean_ledger_is_accepted_and_reports_its_measurements() -> None:
    report = ledger.validate_document(_document())
    assert report.accepted is True
    assert report.blocking == []
    assert report.summary["frames_total"] == 1
    assert report.summary["pose_offsets_measured"] == 1
    assert report.summary["pose_offset_median_ns"] == 10_000_000
    assert report.summary["declared_pose_semantics"] == "camera_receipt"


def test_schema_and_run_id_are_required() -> None:
    assert "schema_missing" in _codes(
        ledger.validate_document(_document(schema="other"))
    )
    assert "run_id_missing" in _codes(ledger.validate_document(_document(run_id=" ")))


def test_missing_clock_mapping_is_blocking_and_unknown_uncertainty_is_retained() -> (
    None
):
    assert "clock_mapping_missing" in _codes(
        ledger.validate_document(_document(clocks=[]))
    )
    report = ledger.validate_document(
        _document(
            clocks=[
                {
                    "clock": "c",
                    "host_clock": "h",
                    "offset_ns": 0,
                    "uncertainty_ns": None,
                }
            ]
        )
    )
    assert _codes(report)["clock_uncertainty_missing"] == "warning"
    assert report.accepted is True


def test_a_timeout_is_outcome_unknown_not_failure() -> None:
    failed = ledger.validate_document(
        _document(
            rows=[_frame(), _action(state="failed", timed_out=True, error="timeout")]
        )
    )
    assert "timeout_not_outcome_unknown" in failed.blocking

    unknown = ledger.validate_document(
        _document(
            rows=[
                _frame(),
                _action(
                    state="outcome_unknown",
                    timed_out=True,
                    completed_ns=None,
                    observed_ns=None,
                    error="no response within 1 s",
                ),
            ]
        )
    )
    assert unknown.accepted is True


def test_outcome_unknown_needs_the_evidence_that_left_it_unknown() -> None:
    report = ledger.validate_document(
        _document(
            rows=[_action(state="outcome_unknown", completed_ns=None, observed_ns=None)]
        )
    )
    assert _codes(report)["outcome_unknown_without_evidence"] == "warning"


def test_completed_action_without_an_observed_response_is_retained() -> None:
    report = ledger.validate_document(_document(rows=[_action(observed_ns=None)]))
    assert _codes(report)["completed_without_observation"] == "warning"


def test_receipt_pose_cannot_be_promoted_to_exposure_associated() -> None:
    report = ledger.validate_document(
        _document(
            declared={
                "pose_semantics": "exposure_bracket",
                "exposure_association": "bracket",
            }
        )
    )
    assert "receipt_pose_declared_as_exposure" in report.blocking


def test_bracket_pose_requires_a_window_and_a_declaration() -> None:
    without_window = ledger.validate_document(
        _document(
            rows=[_frame(pose_source="exposure_bracket")],
            declared={
                "pose_semantics": "exposure_bracket",
                "exposure_association": "bracket",
            },
        )
    )
    assert "exposure_window_missing" in without_window.blocking

    undeclared = ledger.validate_document(
        _document(
            rows=[
                _frame(
                    pose_source="exposure_bracket",
                    exposure_start_ns=900,
                    exposure_end_ns=1_100,
                )
            ],
            declared={
                "pose_semantics": "exposure_bracket",
                "exposure_association": "none",
            },
        )
    )
    assert "exposure_association_undeclared" in undeclared.blocking

    complete = ledger.validate_document(
        _document(
            rows=[
                _frame(
                    pose_source="exposure_bracket",
                    exposure_start_ns=900,
                    exposure_end_ns=1_100,
                )
            ],
            declared={
                "pose_semantics": "exposure_bracket",
                "exposure_association": "bracket",
            },
        )
    )
    assert complete.accepted is True


def test_a_frame_gap_is_retained_rather_than_hidden() -> None:
    rows = [
        _frame(frame_id=1, sequence_index=0),
        _frame(frame_id=2, sequence_index=1),
        _frame(frame_id=4, sequence_index=3),
    ]
    report = ledger.validate_document(_document(rows=rows))
    assert _codes(report)["frame_id_gap"] == "warning"
    assert _codes(report)["sequence_index_gap"] == "warning"
    assert report.accepted is True


def test_repeated_frame_ids_within_a_store_are_blocking() -> None:
    rows = [_frame(frame_id=1, sequence_index=0), _frame(frame_id=1, sequence_index=1)]
    report = ledger.validate_document(_document(rows=rows))
    assert "frame_id_duplicate" in report.blocking


def test_the_same_frame_id_in_two_stores_is_allowed() -> None:
    rows = [
        _frame(store="store-1", frame_id=1, sequence_index=0),
        _frame(store="store-2", frame_id=1, sequence_index=0),
    ]
    report = ledger.validate_document(_document(rows=rows))
    assert report.accepted is True
    assert set(report.summary["stores"]) == {"store-1", "store-2"}


def test_pose_offset_beyond_the_declared_bound_is_a_warning() -> None:
    report = ledger.validate_document(
        _document(rows=[_frame(arrival_ns=0, pose_ns=300_000_000)]),
        LedgerLimits(max_pose_offset_ns=200_000_000),
    )
    assert _codes(report)["pose_offset_exceeds_limit"] == "warning"


def test_missing_pose_needs_a_reason_or_a_drop_mark() -> None:
    bare = ledger.validate_document(_document(rows=[_frame(pose_xy_um=None)]))
    assert "pose_missing" in bare.blocking

    retained = ledger.validate_document(
        _document(rows=[_frame(pose_xy_um=None, rejected_reason="bracket overrun")])
    )
    assert retained.accepted is True


def test_action_state_and_time_rules() -> None:
    assert (
        "action_state_invalid"
        in ledger.validate_document(_document(rows=[_action(state="running")])).blocking
    )
    assert (
        "action_time_out_of_order"
        in ledger.validate_document(
            _document(rows=[_action(accepted_ns=10, started_ns=5)])
        ).blocking
    )
    assert (
        "request_id_missing"
        in ledger.validate_document(_document(rows=[_action(request_id="")])).blocking
    )
    duplicate = ledger.validate_document(
        _document(rows=[_action(), _action(action="other")])
    )
    assert "duplicate_request_id" in duplicate.blocking


def test_response_latency_beyond_the_declared_bound_is_a_warning() -> None:
    report = ledger.validate_document(
        _document(rows=[_action(accepted_ns=0, observed_ns=2_000_000_000)]),
        LedgerLimits(max_response_latency_ns=1_000_000_000),
    )
    assert _codes(report)["response_latency_exceeds_limit"] == "warning"


def test_no_action_rows_is_information_not_an_acceptance() -> None:
    report = ledger.validate_document(_document(rows=[_frame()]))
    assert _codes(report)["no_action_records"] == "info"
    assert report.accepted is True
    assert report.summary["action_rows"] == 0


def test_malformed_rows_are_reported_not_raised() -> None:
    report = ledger.validate_document(_document(rows=["not a row", {"kind": "other"}]))
    assert "row_kind_invalid" in report.blocking


def test_a_non_mapping_document_is_refused() -> None:
    with pytest.raises(ValueError, match="JSON object"):
        ledger.validate_document([])


def test_dataclasses_round_trip_to_a_valid_document() -> None:
    built = Ledger(
        run_id="run-1",
        clocks=(ClockMapping("service", "monotonic", uncertainty_ns=1000),),
        frames=(
            FrameLedgerRow(
                frame_id=1,
                sequence_index=0,
                store="store-1",
                arrival_ns=1_000,
                pose_ns=1_001,
                pose_xy_um=(1.0, 2.0),
            ),
        ),
        actions=(
            ActionLedgerRow(
                request_id="req-1",
                action="move",
                state="completed",
                proposed_ns=1,
                accepted_ns=2,
                started_ns=3,
                completed_ns=5,
                observed_ns=4,
            ),
        ),
    )
    document = built.to_document()
    json.dumps(document)
    report = ledger.validate_document(document)
    assert report.accepted is True
    assert report.summary["stores"]["store-1"]["frames"] == 1


@pytest.mark.skipif(
    not (SESSION / "run_snake_06").is_dir(), reason="recorded run is not present"
)
def test_recording_adapter_joins_on_sequence_not_frame_id() -> None:
    document = ledger.adapt_recorded_run(SESSION / "run_snake_06")
    declared = document["declared"]
    assert declared["timing_rows_without_pose"] == 0
    assert declared["pose_rows_without_timing"] == 0
    assert declared["source_label_mismatches"] == 279
    assert declared["frames_absent_from_positions"] == []

    report = ledger.validate_document(document)
    assert report.accepted is True
    assert report.summary["frames_total"] == 279
    offset = report.summary["pose_offset_median_ns"]
    assert offset is not None and 0 < offset < 100_000_000
    assert report.summary["declared_pose_semantics"] == "camera_receipt"


@pytest.mark.skipif(
    not (SESSION / "run_snake_05").is_dir(), reason="recorded run is not present"
)
def test_recording_adapter_retains_the_two_unposed_frames() -> None:
    document = ledger.adapt_recorded_run(SESSION / "run_snake_05")
    declared = document["declared"]
    absent = {entry["row"]: entry for entry in declared["frames_absent_from_positions"]}
    assert set(absent) == {1, 2}
    assert absent[1]["captured_count"] == 95
    assert absent[1]["positioned_count"] == 94
    assert declared["timing_rows_without_pose"] == 2
    reasons = {entry["status"] for entry in declared["rejected_poses"]}
    assert reasons == {"X telemetry bracket 0.289s exceeds 0.2s limit"}

    report = ledger.validate_document(document)
    assert report.summary["frames_total"] == 282
