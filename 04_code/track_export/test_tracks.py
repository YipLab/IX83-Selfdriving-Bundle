"""Hardware-free tests for the track coverage export (Q08).

Every fixture is synthetic: a stationary control, a drifting track, a track with
dropped frames, a censored track, an edge-touching track and the malformed cases.
No RTASPT fitting is exercised here; the export only counts coverage.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import tracks
from tracks import TrackWindow, export_document, export_track

WINDOW = TrackWindow(
    start_s=0.0,
    end_s=1.0,
    roi_x_px=(0.0, 100.0),
    roi_y_px=(0.0, 100.0),
    edge_margin_px=2.0,
)


def _point(frame: int, x_px: float = 50.0, y_px: float = 50.0) -> dict[str, Any]:
    return {"frame": frame, "x_px": x_px, "y_px": y_px}


def _document(tracks_doc: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema": tracks.SCHEMA,
        "specimen_id": "fixture-specimen",
        "field_id": "fixture-field",
        "frame_period_s": 0.1,
        "window": {
            "start_s": 0.0,
            "end_s": 1.0,
            "roi_px": {"x": [0.0, 100.0], "y": [0.0, 100.0]},
            "edge_margin_px": 2.0,
        },
        "tracks": tracks_doc,
    }


def test_a_stationary_track_reports_duration_and_full_lag_support() -> None:
    export, issues = export_track(
        "t-stationary",
        [_point(frame) for frame in range(2, 7)],
        window=WINDOW,
        frame_period_s=0.1,
    )

    assert issues == []
    assert export.frames == (2, 3, 4, 5, 6)
    assert export.duration_s == pytest.approx(0.4)
    assert export.censoring == "none"
    assert export.gaps == 0
    assert export.lag_pairs == {1: 4, 2: 3, 3: 2}
    assert export.support_runs == ((2, 6),)
    assert export.edge_at_start is False
    assert export.edge_at_end is False


def test_a_drifting_track_keeps_the_same_lag_counts() -> None:
    stationary, _ = export_track(
        "t-stationary",
        [_point(frame) for frame in range(2, 7)],
        window=WINDOW,
        frame_period_s=0.1,
    )
    drifting, _ = export_track(
        "t-drifting",
        [_point(frame, 20.0 + 5.0 * frame, 30.0 + 2.0 * frame) for frame in range(2, 7)],
        window=WINDOW,
        frame_period_s=0.1,
    )

    assert drifting.lag_pairs == stationary.lag_pairs
    assert drifting.duration_s == stationary.duration_s
    assert drifting.censoring == stationary.censoring


def test_dropped_frames_reduce_the_lag_pairs_and_are_reported() -> None:
    export, issues = export_track(
        "t-gapped",
        [_point(frame) for frame in (2, 3, 5, 6)],
        window=WINDOW,
        frame_period_s=0.1,
    )

    assert export.gaps == 1
    assert export.lag_pairs == {1: 2, 2: 1, 3: 2}
    assert export.support_runs == ((2, 3), (5, 6))
    assert [issue.code for issue in issues] == ["track_frames_missing"]
    assert issues[0].severity == tracks.INFO


def test_a_track_spanning_the_window_is_censored_at_both_ends() -> None:
    export, _ = export_track(
        "t-censored",
        [_point(frame) for frame in range(0, 11)],
        window=WINDOW,
        frame_period_s=0.1,
    )

    assert export.censoring == "both"
    assert export.duration_s == pytest.approx(1.0)


def test_edge_contact_is_classified_separately_from_censoring() -> None:
    export, _ = export_track(
        "t-edge",
        [
            _point(2, 1.0, 50.0),
            _point(3, 5.0, 50.0),
            _point(4, 10.0, 50.0),
        ],
        window=WINDOW,
        frame_period_s=0.1,
    )

    assert export.edge_at_start is True
    assert export.edge_at_end is False
    assert export.censoring == "none"


def test_the_document_export_summarizes_the_field() -> None:
    report = export_document(
        _document(
            [
                {"track_id": "t1", "points": [_point(frame) for frame in range(2, 7)]},
                {
                    "track_id": "t2",
                    "points": [_point(frame, 1.0, 50.0) for frame in (0, 1, 2)],
                },
            ]
        )
    )

    assert report["accepted"] is True
    assert report["schema"] == tracks.EXPORT_SCHEMA
    assert report["specimen_id"] == "fixture-specimen"
    assert report["window"]["duration_s"] == pytest.approx(1.0)
    assert [track["track_id"] for track in report["tracks"]] == ["t1", "t2"]
    assert report["summary"] == {
        "tracks": 2,
        "frames": 8,
        "pairs_at_lag_1": 4 + 2,
        "censored_tracks": 1,
        "edge_ended_tracks": 1,
        "gap_events": 0,
    }
    assert report["issues"] == []


def test_the_export_refuses_a_missing_schema_and_window() -> None:
    report = export_document({"tracks": []})

    codes = {issue["code"] for issue in report["issues"]}
    assert report["accepted"] is False
    assert {"schema_missing", "window_missing"} <= codes


def test_the_export_refuses_duplicate_ids_and_bad_points() -> None:
    report = export_document(
        _document(
            [
                {"track_id": "t1", "points": [_point(2)]},
                {"track_id": "t1", "points": [_point(3)]},
                {"track_id": "t2", "points": [_point(4), _point(4)]},
                {"track_id": "t3", "points": []},
                {"track_id": "", "points": [_point(5)]},
            ]
        )
    )

    codes = [issue["code"] for issue in report["issues"]]
    assert report["accepted"] is False
    assert "track_id_duplicate" in codes
    assert "frames_not_increasing" in codes
    assert "track_without_points" in codes
    assert "track_id_missing" in codes


def test_the_export_retains_a_track_longer_than_its_window() -> None:
    report = export_document(
        _document(
            [{"track_id": "t-long", "points": [_point(frame) for frame in range(0, 15)]}]
        )
    )

    codes = {issue["code"] for issue in report["issues"]}
    assert report["accepted"] is True
    assert "track_exceeds_window" in codes


def test_the_window_and_track_inputs_are_validated() -> None:
    with pytest.raises(ValueError, match="after its start"):
        TrackWindow(start_s=1.0, end_s=0.5, roi_x_px=(0, 1), roi_y_px=(0, 1))
    with pytest.raises(ValueError, match="roi_x_px"):
        TrackWindow(start_s=0.0, end_s=1.0, roi_x_px=(5, 5), roi_y_px=(0, 1))
    with pytest.raises(ValueError, match="track_id"):
        export_track("", [_point(0)], window=WINDOW, frame_period_s=0.1)
    with pytest.raises(ValueError, match="frame_period_s"):
        export_track("t", [_point(0)], window=WINDOW, frame_period_s=0.0)


def test_the_command_line_writes_the_report(tmp_path: Path) -> None:
    table = tmp_path / "tracks.json"
    table.write_text(
        json.dumps(
            _document(
                [{"track_id": "t1", "points": [_point(frame) for frame in range(2, 5)]}]
            )
        ),
        encoding="utf-8",
    )
    output = tmp_path / "export.json"

    exit_code = tracks.main([str(table), "--output", str(output)])

    assert exit_code == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["accepted"] is True
    assert report["summary"]["tracks"] == 1


def test_the_command_line_returns_one_for_a_refused_table(tmp_path: Path) -> None:
    table = tmp_path / "tracks.json"
    table.write_text(json.dumps({"tracks": []}), encoding="utf-8")

    assert tracks.main([str(table), "--output", str(tmp_path / "out.json")]) == 1

