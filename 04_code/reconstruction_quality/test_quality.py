"""Hardware-free tests for the reconstruction-quality replay."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import quality
import tifffile
from quality import QualityError


def _pair(
    *,
    index: int = 0,
    status: str = "passed",
    residual: tuple[float, float] = (0.3, 0.4),
    prior: tuple[float, float] = (6.0, 8.0),
    correlation: float = 0.9,
    overlap: float = 0.8,
) -> dict[str, Any]:
    return {
        "reference_frame_index": index,
        "moving_frame_index": index + 1,
        "fit_status": status,
        "placement_graph_residual_xy_px": list(residual),
        "registration_minus_stage_prior_xy_px": list(prior),
        "correlation": correlation,
        "image_overlap_fraction": overlap,
    }


def _record(tmp_path: Path, **overrides: Any) -> Path:
    document: dict[str, Any] = {
        "schema": quality.RECORD_SCHEMA,
        "registration_id": "reg-test",
        "registration_performed": True,
        "connected_registration_graph": True,
        "calibration_id": "cal-test",
        "pairs": [
            _pair(
                index=0,
                residual=(0.3, 0.4),
                prior=(6.0, 8.0),
                correlation=0.9,
                overlap=0.8,
            ),
            _pair(
                index=1,
                residual=(0.0, 0.5),
                prior=(3.0, 4.0),
                correlation=0.8,
                overlap=0.6,
            ),
            _pair(
                index=2,
                residual=(0.0, 0.0),
                prior=(0.0, 0.0),
                correlation=0.95,
                overlap=0.9,
            ),
        ],
        "frame_placements": [
            {"frame_index": index, "graph_component": 0} for index in range(4)
        ],
    }
    document.update(overrides)
    path = tmp_path / "record.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _mosaic_report(
    tmp_path: Path,
    *,
    coverage: np.ndarray | None = None,
    rms: float | None = 0.359166,
    max_tiles: int | None = 3,
) -> Path:
    if coverage is not None:
        tifffile.imwrite(tmp_path / "coverage.tif", coverage)
    document = {
        "schema": "redsun-searching-imaging.snap-registration-mosaic-v1",
        "coverage_file": "coverage.tif" if coverage is not None else "absent.tif",
        "coverage_max_tiles_per_pixel": max_tiles,
        "mosaic_shape_yx": [2, 2],
        "canvas_pixel_count": 4,
        "edge_residual_summary_px": {
            "accepted_edge_count": 3,
            "rms": rms,
            "maximum": 0.5,
        },
    }
    path = tmp_path / "mosaic_report.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _codes(report: dict[str, Any]) -> set[str]:
    return {finding["code"] for finding in report["findings"]}


def test_the_replay_recomputes_pair_and_prior_statistics(tmp_path: Path) -> None:
    report = quality.analyze(_record(tmp_path))
    pairs = report["pairs"]
    assert pairs["total"] == 3
    assert pairs["passed"] == 3
    assert pairs["pass_fraction"] == 1.0
    residual = pairs["placement_residual_px"]
    assert residual["median"] == pytest.approx(0.5)
    assert residual["max"] == pytest.approx(0.5)
    assert residual["rms"] == pytest.approx(
        round((0.25 + 0.25 + 0.0) / 3, 6) ** 0.5, abs=1e-6
    )
    prior = pairs["registration_minus_stage_prior_px"]
    assert prior["median"] == pytest.approx(5.0)
    assert prior["max"] == pytest.approx(10.0)
    assert pairs["correlation"]["median"] == pytest.approx(0.9)
    assert pairs["overlap_fraction"]["min"] == pytest.approx(0.6)
    assert report["graph"] == {"connected": True, "components": 1, "frames_placed": 4}
    assert report["blocking"] == []
    assert report["accepted"] is False


def test_the_edge_rms_gate_is_enforced(tmp_path: Path) -> None:
    report = quality.analyze(_record(tmp_path), max_edge_rms_px=0.3)
    assert "edge_rms_over_gate" in _codes(report)
    assert report["blocking"]


def test_failed_pairs_are_retained_as_a_warning(tmp_path: Path) -> None:
    document = json.loads(_record(tmp_path).read_text(encoding="utf-8"))
    document["pairs"].append(_pair(index=3, status="failed", residual=(9.0, 9.0)))
    path = tmp_path / "record.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    report = quality.analyze(path)
    assert report["pairs"]["failed"] == 1
    findings = {finding["code"]: finding["severity"] for finding in report["findings"]}
    assert findings["pair_failures"] == "warning"
    assert report["blocking"] == []


def test_a_disconnected_graph_is_blocking(tmp_path: Path) -> None:
    report = quality.analyze(_record(tmp_path, connected_registration_graph=False))
    assert "disconnected_graph" in report["blocking"]


def test_two_components_break_the_claim_even_when_the_flag_is_true(
    tmp_path: Path,
) -> None:
    placements = [
        {"frame_index": 0, "graph_component": 0},
        {"frame_index": 1, "graph_component": 0},
        {"frame_index": 2, "graph_component": 1},
    ]
    report = quality.analyze(_record(tmp_path, frame_placements=placements))
    assert report["graph"]["components"] == 2
    assert "disconnected_graph" in report["blocking"]


def test_coverage_fractions_come_from_the_array(tmp_path: Path) -> None:
    coverage = np.array([[0, 1], [2, 3]], dtype=np.uint16)
    report = quality.analyze(
        _record(tmp_path),
        mosaic_report_path=_mosaic_report(tmp_path, coverage=coverage),
    )
    values = report["coverage"]
    assert values["max_tiles_per_pixel"] == 3
    assert values["fraction_at_least_1"] == pytest.approx(0.75)
    assert values["fraction_at_least_2"] == pytest.approx(0.5)
    assert values["fraction_at_least_3"] == pytest.approx(0.25)
    assert "coverage_disagrees" not in _codes(report)


def test_a_coverage_maximum_that_disagrees_is_a_warning(tmp_path: Path) -> None:
    coverage = np.array([[0, 1], [2, 3]], dtype=np.uint16)
    report = quality.analyze(
        _record(tmp_path),
        mosaic_report_path=_mosaic_report(tmp_path, coverage=coverage, max_tiles=9),
    )
    findings = {finding["code"]: finding["severity"] for finding in report["findings"]}
    assert findings["coverage_disagrees"] == "warning"


def test_a_missing_coverage_array_is_a_warning(tmp_path: Path) -> None:
    report = quality.analyze(
        _record(tmp_path), mosaic_report_path=_mosaic_report(tmp_path, coverage=None)
    )
    findings = {finding["code"]: finding["severity"] for finding in report["findings"]}
    assert findings["coverage_missing"] == "warning"
    assert report["coverage"] is None


def test_a_reported_rms_that_disagrees_is_a_warning(tmp_path: Path) -> None:
    report = quality.analyze(
        _record(tmp_path),
        mosaic_report_path=_mosaic_report(tmp_path, coverage=None, rms=0.9),
    )
    findings = {finding["code"]: finding["severity"] for finding in report["findings"]}
    assert findings["edge_rms_disagrees"] == "warning"


def test_an_unregistered_or_unreadable_record_is_refused(tmp_path: Path) -> None:
    report = quality.analyze(_record(tmp_path, registration_performed=False))
    assert "registration_not_performed" in report["blocking"]

    with pytest.raises(QualityError, match="record not found"):
        quality.analyze(tmp_path / "absent.json")
    bad_schema = tmp_path / "bad.json"
    bad_schema.write_text(json.dumps({"schema": "other"}), encoding="utf-8")
    with pytest.raises(QualityError, match="schema"):
        quality.analyze(bad_schema)


def test_cli_writes_the_report_and_reports_blocking(tmp_path: Path) -> None:
    record = _record(tmp_path)
    out = tmp_path / "quality.json"
    assert quality.main(["--record", str(record), "--out", str(out)]) == 0
    document = json.loads(out.read_text(encoding="utf-8"))
    assert document["pairs"]["passed"] == 3

    assert (
        quality.main(
            ["--record", str(record), "--out", str(out), "--max-edge-rms-px", "0.1"]
        )
        == 1
    )
    assert (
        quality.main(["--record", str(tmp_path / "absent.json"), "--out", str(out)])
        == 2
    )
