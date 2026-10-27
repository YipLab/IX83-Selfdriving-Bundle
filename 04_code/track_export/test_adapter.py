"""Hardware-free tests for the track-export adapter (Q08)."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

import adapter
import tracks


def _write(path: Path, rows: list[dict[str, Any]], *, columns: tuple[str, ...] = adapter.COLUMNS) -> Path:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns))
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in columns})
    return path


def _build(rows: list[dict[str, Any]], source: Path | None = None) -> dict[str, Any]:
    return adapter.build_table(
        rows,
        specimen_id="fixture-specimen",
        field_id="fixture-field",
        frame_period_s=0.1,
        start_s=0.0,
        end_s=1.0,
        roi_x_px=(0.0, 100.0),
        roi_y_px=(0.0, 100.0),
        source=source,
    )


def test_a_csv_export_becomes_a_declared_table(tmp_path: Path) -> None:
    source = _write(
        tmp_path / "tracks.csv",
        [
            {"track_id": "t2", "frame": 3, "x_px": 30.0, "y_px": 40.0},
            {"track_id": "t1", "frame": 5, "x_px": 50.0, "y_px": 60.0},
            {"track_id": "t1", "frame": 4, "x_px": 40.0, "y_px": 50.0},
        ],
    )

    rows = adapter.read_rows(source)
    document = _build(rows, source=source)

    assert document["schema"] == tracks.SCHEMA
    assert [track["track_id"] for track in document["tracks"]] == ["t1", "t2"]
    assert [point["frame"] for point in document["tracks"][0]["points"]] == [4, 5]
    assert document["source"]["columns"] == list(adapter.COLUMNS)
    assert document["source"]["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    report = tracks.export_document(document)
    assert report["accepted"] is True
    assert report["summary"]["tracks"] == 2
    assert report["summary"]["frames"] == 3


def test_a_missing_column_is_refused_by_name(tmp_path: Path) -> None:
    source = _write(
        tmp_path / "tracks.csv",
        [{"track_id": "t1", "frame": 0, "x_px": 1.0}],
        columns=("track_id", "frame", "x_px"),
    )

    with pytest.raises(ValueError, match="y_px"):
        adapter.read_rows(source)


def test_a_header_only_export_is_refused(tmp_path: Path) -> None:
    source = tmp_path / "tracks.csv"
    source.write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="header"):
        adapter.read_rows(source)


def test_row_errors_name_the_line(tmp_path: Path) -> None:
    cases = [
        ({"track_id": "", "frame": 0, "x_px": 1.0, "y_px": 1.0}, "track_id"),
        ({"track_id": "t1", "frame": "x", "x_px": 1.0, "y_px": 1.0}, "integer"),
        ({"track_id": "t1", "frame": -1, "x_px": 1.0, "y_px": 1.0}, "nonnegative"),
        ({"track_id": "t1", "frame": 0, "x_px": "a", "y_px": 1.0}, "numeric"),
    ]
    for row, message in cases:
        source = _write(tmp_path / "tracks.csv", [row])
        with pytest.raises(ValueError, match=message):
            adapter.read_rows(source)


def test_a_duplicate_point_is_refused(tmp_path: Path) -> None:
    source = _write(
        tmp_path / "tracks.csv",
        [
            {"track_id": "t1", "frame": 2, "x_px": 1.0, "y_px": 1.0},
            {"track_id": "t1", "frame": 2, "x_px": 2.0, "y_px": 2.0},
        ],
    )

    with pytest.raises(ValueError, match="duplicate"):
        adapter.read_rows(source)


def test_the_table_requires_identity() -> None:
    with pytest.raises(ValueError, match="specimen_id"):
        adapter.build_table(
            [],
            specimen_id=" ",
            field_id="field",
            frame_period_s=0.1,
            start_s=0.0,
            end_s=1.0,
            roi_x_px=(0.0, 1.0),
            roi_y_px=(0.0, 1.0),
        )


def test_the_command_line_writes_the_table(tmp_path: Path) -> None:
    source = _write(
        tmp_path / "tracks.csv",
        [{"track_id": "t1", "frame": 1, "x_px": 5.0, "y_px": 6.0}],
    )
    output = tmp_path / "table.json"

    exit_code = adapter.main(
        [
            str(source),
            "--specimen",
            "spec-1",
            "--field",
            "field-1",
            "--frame-period",
            "0.05",
            "--window",
            "0",
            "2",
            "--roi-x",
            "0",
            "64",
            "--roi-y",
            "0",
            "64",
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0
    document = json.loads(output.read_text(encoding="utf-8"))
    assert document["specimen_id"] == "spec-1"
    assert document["frame_period_s"] == pytest.approx(0.05)
    assert document["window"]["roi_px"] == {"x": [0.0, 64.0], "y": [0.0, 64.0]}
    assert tracks.export_document(document)["accepted"] is True
