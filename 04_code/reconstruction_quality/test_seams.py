"""Hardware-free tests for seam measurement and its geometry precondition.

Synthetic mosaics carry known tile edges and coverage, so a recovered tile size
and a measured step can be checked exactly. The recorded 5x5 case is exercised
only when its local archive is present; it is expected to be refused.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
import pytest

import seams

RECORDED = (
    Path(__file__).resolve().parents[2]
    / "08_session_logs"
    / "20261023T_grid_5x5_regression_01"
    / "calibrated"
)


def _coverage(shape: tuple[int, int], origins: list[tuple[int, int]], tile: int) -> np.ndarray:
    return seams.predict_coverage(origins, shape, tile)


def _two_tile_mosaic() -> tuple[np.ndarray, np.ndarray, list[tuple[float, float]]]:
    shape = (40, 40)
    origins = [(0.0, 0.0), (20.0, 0.0)]
    mosaic = np.zeros(shape, dtype=float)
    mosaic[:, :20] = 1.0
    mosaic[:, 20:] = 2.0
    coverage = _coverage(shape, [(0, 0), (20, 0)], 20)
    return mosaic, coverage, origins


def test_a_known_two_tile_geometry_is_recovered() -> None:
    mosaic, coverage, origins = _two_tile_mosaic()

    fit = seams.fit_tile_geometry(origins, coverage, minimum_tile_px=8, maximum_tile_px=30)

    assert fit.accepted is True
    assert fit.tile_px == 20
    assert fit.mismatch_fraction == pytest.approx(0.0)


def test_the_edge_step_separates_tiles_from_within_tile_noise() -> None:
    mosaic, coverage, origins = _two_tile_mosaic()
    fit = seams.fit_tile_geometry(origins, coverage)

    report = seams.measure_seams(mosaic, coverage, origins, fit, axes=("x",))

    assert report.refused_reason is None
    assert len(report.measurements) == 1
    seam = report.measurements[0]
    assert seam.position_px == 20
    assert seam.step == pytest.approx(1.0)
    assert seam.control == pytest.approx(0.0)
    document = report.to_document()
    assert document["accepted"] is True
    assert document["seams_measured"] == 1
    assert document["step_median"] == pytest.approx(1.0)


def test_a_blended_overlap_edge_shows_a_half_step() -> None:
    shape = (40, 30)
    origins = [(0.0, 0.0), (10.0, 0.0)]
    mosaic = np.zeros(shape, dtype=float)
    mosaic[:, :10] = 1.0
    mosaic[:, 10:] = 1.5
    coverage = _coverage(shape, [(0, 0), (10, 0)], 20)
    fit = seams.fit_tile_geometry(origins, coverage)

    report = seams.measure_seams(mosaic, coverage, origins, fit, axes=("x",))

    assert fit.tile_px == 20
    assert len(report.measurements) == 1
    assert report.measurements[0].step == pytest.approx(0.5)
    assert report.measurements[0].control == pytest.approx(0.0)


def test_a_vertical_edge_is_measured_on_the_y_axis() -> None:
    shape = (40, 40)
    origins = [(0.0, 0.0), (0.0, 20.0)]
    mosaic = np.zeros(shape, dtype=float)
    mosaic[:20, :] = 3.0
    mosaic[20:, :] = 1.0
    coverage = _coverage(shape, [(0, 0), (0, 20)], 20)
    fit = seams.fit_tile_geometry(origins, coverage)

    report = seams.measure_seams(mosaic, coverage, origins, fit, axes=("y",))

    assert report.refused_reason is None
    assert report.measurements[0].axis == "y"
    assert report.measurements[0].position_px == 20
    assert report.measurements[0].step == pytest.approx(2.0)


def test_geometry_that_no_tile_model_reproduces_is_refused() -> None:
    shape = (40, 40)
    origins = [(0.0, 0.0), (20.0, 0.0)]
    mosaic = np.zeros(shape, dtype=float)
    coverage = np.full(shape, 5, dtype=np.int64)

    fit = seams.fit_tile_geometry(origins, coverage)
    report = seams.measure_seams(mosaic, coverage, origins, fit, axes=("x",))

    assert fit.accepted is False
    assert fit.mismatch_fraction > 0.5
    assert report.refused_reason == "geometry_unverified"
    assert report.to_document()["seams_measured"] == 0


def test_a_single_tile_covering_the_canvas_has_no_seam() -> None:
    shape = (20, 20)
    origins = [(0.0, 0.0)]
    mosaic = np.ones(shape, dtype=float)
    coverage = _coverage(shape, [(0, 0)], 20)
    fit = seams.fit_tile_geometry(origins, coverage)

    report = seams.measure_seams(mosaic, coverage, origins, fit, axes=("x", "y"))

    assert fit.accepted is True
    assert report.refused_reason == "no_measurable_seams"


def test_the_inputs_are_validated() -> None:
    with pytest.raises(ValueError, match="tile_px"):
        seams.predict_coverage([(0.0, 0.0)], (5, 5), 0)
    with pytest.raises(ValueError, match="rounding"):
        seams.predict_coverage([(0.0, 0.0)], (5, 5), 2, rounding="ceil")
    with pytest.raises(ValueError, match="2D"):
        seams.fit_tile_geometry([(0.0, 0.0)], np.zeros(3))
    with pytest.raises(ValueError, match="origin"):
        seams.fit_tile_geometry([], np.zeros((4, 4)))
    with pytest.raises(ValueError, match="minimum_tile_px"):
        seams.fit_tile_geometry(
            [(0.0, 0.0)], np.zeros((4, 4)), minimum_tile_px=10, maximum_tile_px=5
        )
    fit = seams.fit_tile_geometry([(0.0, 0.0)], np.zeros((16, 16)), minimum_tile_px=1)
    with pytest.raises(ValueError, match="axis"):
        seams.measure_seams(
            np.zeros((4, 4)), np.zeros((4, 4)), [(0.0, 0.0)], fit, axes=("z",)
        )


@pytest.mark.skipif(
    not (RECORDED / "registered_snap_mosaic.tif").is_file(),
    reason="the recorded 5x5 mosaic archive is not present",
)
def test_the_recorded_mosaic_is_refused_because_its_geometry_is_unknown() -> None:
    import tifffile

    mosaic = tifffile.imread(RECORDED / "registered_snap_mosaic.tif")
    coverage = tifffile.imread(RECORDED / "registered_snap_coverage.tif")
    with (RECORDED / "registered_snap_frame_placements.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        rows = list(csv.DictReader(handle))
    origins = [
        (
            float(row["registration_origin_x_px"]),
            float(row["registration_origin_y_px"]),
        )
        for row in rows
    ]

    fit = seams.fit_tile_geometry(origins, np.asarray(coverage))
    report = seams.measure_seams(mosaic, coverage, origins, fit, axes=("x", "y"))

    assert fit.accepted is False
    assert report.refused_reason == "geometry_unverified"
    document = report.to_document()
    assert document["accepted"] is False
    assert document["seams_measured"] == 0


def test_the_command_line_returns_zero_for_a_measurable_mosaic(tmp_path: Path) -> None:
    import tifffile

    mosaic, coverage, _origins = _two_tile_mosaic()
    mosaic_path = tmp_path / "mosaic.tif"
    coverage_path = tmp_path / "coverage.tif"
    placements_path = tmp_path / "placements.csv"
    tifffile.imwrite(mosaic_path, mosaic.astype(np.float32))
    tifffile.imwrite(coverage_path, coverage.astype(np.uint16))
    with placements_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["registration_origin_x_px", "registration_origin_y_px"])
        writer.writerow([0.0, 0.0])
        writer.writerow([20.0, 0.0])
    output = tmp_path / "seams.json"

    exit_code = seams.main(
        [str(mosaic_path), str(coverage_path), str(placements_path), "--output", str(output)]
    )

    assert exit_code == 0
    document = json.loads(output.read_text(encoding="utf-8"))
    assert document["accepted"] is True
    assert document["seams_measured"] == 1


