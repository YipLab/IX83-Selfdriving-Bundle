"""Hardware-free tests for the figure-input builder (Q12)."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

import figure

RECORDED = (
    Path(__file__).resolve().parents[2]
    / "08_session_logs"
    / "20261023T_grid_5x5_regression_01"
    / "calibrated_record.json"
)


def _record(pairs: list[dict[str, Any]], **overrides: Any) -> dict[str, Any]:
    document = {
        "registration_id": "reg-fixture",
        "calibration_id": "cal-fixture",
        "pairs": pairs,
    }
    document.update(overrides)
    return document


def _pair(
    reference: int,
    moving: int,
    residual: tuple[float, float],
    *,
    status: str = "passed",
) -> dict[str, Any]:
    return {
        "reference_frame_index": reference,
        "moving_frame_index": moving,
        "fit_status": status,
        "placement_graph_residual_xy_px": list(residual),
    }


def test_only_passing_pairs_become_rows() -> None:
    rows = figure.read_pairs(
        _record(
            [
                _pair(0, 1, (1.0, 0.0)),
                _pair(0, 2, (0.0, 2.0), status="failed"),
                _pair(0, 3, (3.0, 4.0)),
            ]
        )
    )

    assert [row["frame_a"] for row in rows] == [0, 0]
    assert [row["frame_b"] for row in rows] == [1, 3]
    assert [row["magnitude_px"] for row in rows] == [pytest.approx(1.0), pytest.approx(5.0)]
    assert [row["pair_index"] for row in rows] == [0, 2]


def test_the_histogram_counts_every_value() -> None:
    bins = figure.histogram_bins([0.0, 0.5, 1.0, 1.5, 2.0], bins=4)

    assert len(bins) == 4
    assert sum(count for _low, _high, count in bins) == 5
    assert bins[0][0] == pytest.approx(0.0)
    assert bins[-1][1] == pytest.approx(2.0)


def test_the_svg_is_deterministic_and_labelled() -> None:
    values = [1.0, 2.0, 2.0, 3.0]
    first = figure.render_histogram_svg(values, title="Residuals", x_label="px", bins=6)
    second = figure.render_histogram_svg(values, title="Residuals", x_label="px", bins=6)

    assert first == second
    assert first.count("<rect ") == 6 + 1  # plot background plus one bar per bin
    assert "Residuals" in first
    assert "n = 4" in first
    assert first.startswith("<svg")


def test_bad_records_are_refused() -> None:
    with pytest.raises(ValueError, match="pairs list"):
        figure.read_pairs({})
    with pytest.raises(ValueError, match="no passing pairs"):
        figure.read_pairs(_record([_pair(0, 1, (0.0, 0.0), status="failed")]))
    with pytest.raises(ValueError, match="numbers"):
        figure.read_pairs(_record([_pair(0, 1, ("x", 0.0))]))
    with pytest.raises(ValueError, match="finite"):
        figure.read_pairs(_record([_pair(0, 1, (float("nan"), 0.0))]))
    with pytest.raises(ValueError, match="two-value"):
        figure.read_pairs(_record([{"fit_status": "passed", "placement_graph_residual_xy_px": [1.0]}]))
    with pytest.raises(ValueError, match="bins"):
        figure.histogram_bins([1.0], bins=0)
    with pytest.raises(ValueError, match="empty"):
        figure.render_histogram_svg([], title="x", x_label="y")
    with pytest.raises(ValueError, match="at least 200"):
        figure.render_histogram_svg([1.0], title="x", x_label="y", width=100)


def test_build_writes_table_svg_and_provenance(tmp_path: Path) -> None:
    record_path = tmp_path / "record.json"
    record_path.write_text(
        json.dumps(_record([_pair(0, 1, (1.0, 0.0)), _pair(0, 2, (0.0, 2.0))])),
        encoding="utf-8",
    )
    table_path = tmp_path / "table.csv"
    svg_path = tmp_path / "figure.svg"
    sidecar_path = tmp_path / "provenance.json"

    sidecar = figure.build(
        record_path,
        table_path=table_path,
        svg_path=svg_path,
        sidecar_path=sidecar_path,
        title="Fixture residuals",
    )

    with table_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert list(rows[0]) == list(figure.TABLE_COLUMNS)
    assert [row["magnitude_px"] for row in rows] == ["1.0", "2.0"]
    assert sidecar["schema"] == figure.SIDECAR_SCHEMA
    assert sidecar["registration_id"] == "reg-fixture"
    assert sidecar["pairs_total"] == 2
    assert sidecar["pairs_plotted"] == 2
    assert sidecar["slot"] is None
    assert sidecar["slot_assignment"] == "pending author assignment"
    assert sidecar["record"]["sha256"] == hashlib.sha256(record_path.read_bytes()).hexdigest()
    assert sidecar["table"]["sha256"] == hashlib.sha256(table_path.read_bytes()).hexdigest()
    assert sidecar["svg"]["sha256"] == hashlib.sha256(svg_path.read_bytes()).hexdigest()
    assert json.loads(sidecar_path.read_text(encoding="utf-8")) == sidecar
    assert "Fixture residuals" in svg_path.read_text(encoding="utf-8")


def test_the_command_line_writes_all_three_files(tmp_path: Path) -> None:
    record_path = tmp_path / "record.json"
    record_path.write_text(json.dumps(_record([_pair(0, 1, (1.0, 1.0))])), encoding="utf-8")

    exit_code = figure.main(
        [
            str(record_path),
            "--table",
            str(tmp_path / "table.csv"),
            "--svg",
            str(tmp_path / "figure.svg"),
            "--sidecar",
            str(tmp_path / "provenance.json"),
            "--bins",
            "8",
        ]
    )

    assert exit_code == 0
    assert (tmp_path / "table.csv").is_file()
    assert (tmp_path / "figure.svg").is_file()
    sidecar = json.loads((tmp_path / "provenance.json").read_text(encoding="utf-8"))
    assert sidecar["bins"] == 8


@pytest.mark.skipif(not RECORDED.is_file(), reason="the recorded 5x5 registration is not present")
def test_the_recorded_registration_becomes_three_hundred_rows(tmp_path: Path) -> None:
    sidecar = figure.build(
        RECORDED,
        table_path=tmp_path / "table.csv",
        svg_path=tmp_path / "figure.svg",
        sidecar_path=tmp_path / "provenance.json",
        title="Recorded 5x5 placement residuals",
    )

    assert sidecar["pairs_total"] == 300
    assert sidecar["pairs_plotted"] == 300
    assert sidecar["registration_id"].startswith("7f5b75e2")
    assert sidecar["magnitude_px"]["median"] == pytest.approx(0.148, abs=0.01)
    assert sidecar["magnitude_px"]["max"] < 1.0
