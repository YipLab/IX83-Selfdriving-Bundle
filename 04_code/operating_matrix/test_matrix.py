"""Hardware-free tests for the operating-matrix builder.

Each case starts from a small specification and changes one axis or bound, so the
refusal it checks is the only new failure.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import matrix
import pytest
from matrix import MatrixSpecError

BASE: dict[str, Any] = {
    "schema": "ix71.operating-matrix.1",
    "matrix_id": "test-matrix",
    "description": "test",
    "camera": {
        "sensor_width_px": 100,
        "sensor_height_px": 100,
        "pixel_size_um": 1.0,
        "binning": 1,
        "source": "test",
    },
    "optics": {
        "resolution_um": 1.0,
        "resolution_basis": "measured_psf",
        "source": "test",
    },
    "frame_period_s": 0.1,
    "strip_length_um": 100.0,
    "illumination_footprint_um": 100.0,
    "speeds_um_s": [10.0, 50.0],
    "exposures_ms": [10.0],
    "virtual_slit_widths_um": [20.0, 40.0],
    "hardware_roi_widths_px": [20, 40],
    "limits": {
        "max_stage_speed_um_s": 50.0,
        "min_frame_period_s": 0.05,
        "max_blur_ratio": 2.0,
        "max_gamma": 1.0,
        "min_observations": 1.0,
        "max_duty": 1.0,
        "provisional": False,
        "sources": {"max_stage_speed_um_s": "test"},
    },
}


def _spec(**overrides: Any) -> dict[str, Any]:
    spec = copy.deepcopy(BASE)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(spec.get(key), dict):
            spec[key].update(value)
        else:
            spec[key] = value
    return spec


def _rows(document: dict[str, Any]) -> list[dict[str, Any]]:
    return document["rows"]


def _codes(row: dict[str, Any]) -> set[str]:
    return set(row["reasons"])


def test_the_matrix_covers_every_axis_combination() -> None:
    document = matrix.build_matrix(matrix.validate_spec(_spec()))
    # 2 modes x 2 speeds x 1 exposure x 2 widths
    assert len(_rows(document)) == 8
    assert document["summary"]["rows_total"] == 8
    assert {row["detector_mode"] for row in _rows(document)} == {
        "virtual_slit",
        "hardware_roi",
    }
    assert document["summary"]["by_mode"]["virtual_slit"] == {"rows": 4, "feasible": 4}
    assert document["summary"]["by_mode"]["hardware_roi"] == {"rows": 4, "feasible": 4}


def test_a_row_reproduces_the_planner_metrics() -> None:
    from planner.acquisition_space import AcquisitionPoint, assess_measurement

    spec = matrix.validate_spec(_spec())
    row = next(row for row in _rows(matrix.build_matrix(spec)) if row["feasible"])
    point = AcquisitionPoint(
        velocity_um_s=row["speed_um_s"],
        exposure_s=row["exposure_s"],
        width_um=row["width_um"],
        frame_period_s=row["frame_period_s"],
        pixel_size_um=1.0,
        resolution_um=1.0,
        height_um=100.0,
    )
    verdict = assess_measurement(
        point,
        matrix.MeasurementLimits(
            max_blur_ratio=2.0, max_gamma=1.0, min_observations=1.0, max_duty=1.0
        ),
    )
    assert row["metrics"] == verdict.metrics.to_dict()


def test_speed_above_the_declared_ceiling_is_refused() -> None:
    spec = matrix.validate_spec(_spec(speeds_um_s=[10.0, 80.0]))
    rows = [
        row for row in _rows(matrix.build_matrix(spec)) if row["speed_um_s"] == 80.0
    ]
    assert rows and all("speed_exceeds_declared_max" in _codes(row) for row in rows)
    assert all(not row["feasible"] for row in rows)


def test_exposure_at_or_above_the_frame_period_is_refused_without_metrics() -> None:
    spec = matrix.validate_spec(_spec(exposures_ms=[100.0]))
    rows = _rows(matrix.build_matrix(spec))
    assert rows
    assert all("exposure_not_below_frame_period" in _codes(row) for row in rows)
    assert all(row["metrics"] is None for row in rows)


def test_width_above_the_sensor_field_is_refused() -> None:
    spec = matrix.validate_spec(_spec(virtual_slit_widths_um=[20.0, 140.0]))
    rows = [row for row in _rows(matrix.build_matrix(spec)) if row["width_um"] == 140.0]
    assert rows and all("width_exceeds_sensor_field" in _codes(row) for row in rows)


def test_width_above_the_illumination_footprint_is_refused() -> None:
    spec = matrix.validate_spec(_spec(illumination_footprint_um=30.0))
    rows = [row for row in _rows(matrix.build_matrix(spec)) if row["width_um"] == 40.0]
    assert rows and all(
        "width_exceeds_illumination_footprint" in _codes(row) for row in rows
    )
    # Without a footprint the same width is only bounded by the sensor.
    open_spec = matrix.validate_spec(_spec(illumination_footprint_um=None))
    open_rows = [
        row for row in _rows(matrix.build_matrix(open_spec)) if row["width_um"] == 40.0
    ]
    assert all(
        "width_exceeds_illumination_footprint" not in _codes(row) for row in open_rows
    )


def test_a_roi_width_that_does_not_divide_by_binning_is_refused() -> None:
    spec = matrix.validate_spec(
        _spec(camera={"binning": 2}, hardware_roi_widths_px=[21, 40])
    )
    rows = {
        row["width_px"]: row
        for row in _rows(matrix.build_matrix(spec))
        if row["detector_mode"] == "hardware_roi" and row["speed_um_s"] == 10.0
    }
    assert "roi_width_not_pixel_multiple" in _codes(rows[21])
    assert "roi_width_not_pixel_multiple" not in _codes(rows[40])


def test_a_roi_wider_than_the_sensor_is_refused() -> None:
    spec = matrix.validate_spec(_spec(hardware_roi_widths_px=[20, 200]))
    rows = [row for row in _rows(matrix.build_matrix(spec)) if row["width_px"] == 200]
    assert rows and all("hardware_roi_exceeds_sensor" in _codes(row) for row in rows)


def test_planner_limits_map_to_matrix_reasons() -> None:
    spec = matrix.validate_spec(_spec(limits={"max_duty": 0.05}))
    rows = _rows(matrix.build_matrix(spec))
    assert all("duty_outside_declared_range" in _codes(row) for row in rows)

    spec = matrix.validate_spec(_spec(limits={"min_observations": 100.0}))
    rows = _rows(matrix.build_matrix(spec))
    assert all("observations_below_declared_min" in _codes(row) for row in rows)

    spec = matrix.validate_spec(_spec(limits={"max_blur_ratio": 0.01}))
    rows = _rows(matrix.build_matrix(spec))
    assert all("blur_ratio_exceeds_declared_max" in _codes(row) for row in rows)


def test_retained_frames_follow_the_step_not_the_width() -> None:
    document = matrix.build_matrix(matrix.validate_spec(_spec()))
    narrow = next(
        row
        for row in _rows(document)
        if row["detector_mode"] == "virtual_slit"
        and row["speed_um_s"] == 10.0
        and row["width_um"] == 20.0
    )
    wide = next(
        row
        for row in _rows(document)
        if row["detector_mode"] == "virtual_slit"
        and row["speed_um_s"] == 10.0
        and row["width_um"] == 40.0
    )
    assert narrow["step_um"] == pytest.approx(1.0)
    assert (
        narrow["retained_frames_per_strip"] == wide["retained_frames_per_strip"] == 101
    )


def test_declared_gaps_are_stated_in_the_document() -> None:
    document = matrix.build_matrix(matrix.validate_spec(_spec()))
    assert document["accepted"] is False
    assert {item["metric"] for item in document["not_computed"]} == {
        "valid_area",
        "local_support_duration",
        "acquisition_overhead",
    }
    assert document["summary"]["reason_counts"] == {}

    proxy = matrix.build_matrix(
        matrix.validate_spec(
            _spec(optics={"resolution_basis": "sampling_pitch_not_psf"})
        )
    )
    assert "psf_blur" in {item["metric"] for item in proxy["not_computed"]}


def test_a_frame_period_below_the_declared_camera_floor_is_a_warning() -> None:
    document = matrix.build_matrix(
        matrix.validate_spec(
            _spec(frame_period_s=0.04, limits={"min_frame_period_s": 0.05})
        )
    )
    assert all(
        "frame_period_below_declared_camera_floor" in row["warnings"]
        for row in _rows(document)
    )
    assert all(row["feasible"] for row in _rows(document))


def test_findings_name_provisional_limits_and_proxy_optics() -> None:
    document = matrix.build_matrix(
        matrix.validate_spec(
            _spec(
                optics={"resolution_basis": "sampling_pitch_not_psf"},
                illumination_footprint_um=None,
                limits={"provisional": True},
            )
        )
    )
    codes = {finding["code"] for finding in document["findings"]}
    assert {
        "limits_provisional",
        "psf_unmeasured",
        "illumination_footprint_undeclared",
    } <= codes

    clean = matrix.build_matrix(matrix.validate_spec(_spec()))
    assert {finding["code"] for finding in clean["findings"]} == set()


def test_missing_limit_sources_are_reported() -> None:
    document = matrix.build_matrix(matrix.validate_spec(_spec(limits={"sources": {}})))
    assert "limit_sources_missing" in {
        finding["code"] for finding in document["findings"]
    }


def test_the_same_specification_builds_the_same_rows() -> None:
    spec = matrix.validate_spec(_spec())
    first = matrix.build_matrix(spec)
    second = matrix.build_matrix(spec)
    assert first["rows"] == second["rows"]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"schema": "other"}, "schema"),
        ({"matrix_id": ""}, "matrix_id"),
        ({"speeds_um_s": []}, "speeds_um_s"),
        ({"speeds_um_s": [10.0, 10.0]}, "repeat"),
        ({"exposures_ms": [-1.0]}, "exposures_ms"),
        ({"frame_period_s": 0.0}, "frame_period_s"),
        ({"limits": {"max_duty": 1.5}}, "max_duty"),
        ({"camera": {"binning": 0}}, "binning"),
        ({"camera": {"sensor_width_px": 0}}, "sensor_width_px"),
    ],
)
def test_invalid_specifications_are_refused(
    change: dict[str, Any], message: str
) -> None:
    with pytest.raises(MatrixSpecError, match=message):
        matrix.validate_spec(_spec(**change))


def test_cli_refuses_a_bad_specification_and_reports_no_feasible_rows(
    tmp_path: Path,
) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema": "other"}), encoding="utf-8")
    assert matrix.main(["--spec", str(bad), "--out", str(tmp_path / "out.json")]) == 2

    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(_spec(limits={"max_duty": 0.01})), encoding="utf-8")
    out = tmp_path / "out.json"
    assert matrix.main(["--spec", str(spec_path), "--out", str(out)]) == 1
    document = json.loads(out.read_text(encoding="utf-8"))
    assert document["summary"]["feasible"] == 0
    assert document["summary"]["infeasible"] == 8


def _recorded_run(
    tmp_path: Path,
    *,
    captured: int = 93,
    span: float = 4.344,
    interval: float | None = 0.047,
    length: float = 781.0,
    implied: float = 164.9,
    strips: int = 1,
) -> Path:
    run = tmp_path / "run"
    (run / "strips").mkdir(parents=True)
    (run / "ix71-test-01-report.json").write_text(
        json.dumps(
            {
                "schema": "ix71.asi-broom-snake.v1",
                "confirmation_id": "ix71-test-01",
                "setpoint_mw": 1.0,
                "maximum_frame_period_s": 0.1,
                "stores": {},
            }
        ),
        encoding="utf-8",
    )
    (run / "strips" / "asi-broom-ix71-test-01-strips.json").write_text(
        json.dumps(
            {
                "schema": "ix71.asi-broom-strips.v1",
                "confirmation_id": "ix71-test-01",
                "strips": [
                    {
                        "row": row,
                        "captured_count": captured,
                        "frame_span_s": span,
                        "frame_interval_s": (
                            None
                            if interval is None
                            else {"min": 0.031, "median": interval, "max": 0.063}
                        ),
                        "strip_length_um": length,
                        "implied_traverse_speed_um_s": implied,
                    }
                    for row in range(strips)
                ],
            }
        ),
        encoding="utf-8",
    )
    return run


def test_observed_comparison_reports_frames_step_interval_and_overhead(
    tmp_path: Path,
) -> None:
    document = matrix.build_matrix(matrix.validate_spec(_spec()))
    run = _recorded_run(tmp_path)
    observed = matrix.compare_observed(
        document, run, commanded_speed_um_s=10.0, exposure_ms=10.0, width_um=20.0
    )

    strip = observed["strips"][0]
    assert observed["declared_point"]["retained_frames_per_strip"] == 101
    assert strip["predicted_frames"] == 101
    assert strip["captured_count"] == 93
    assert strip["frame_delta"] == -8
    assert strip["predicted_step_um"] == pytest.approx(1.0)
    assert strip["observed_step_um"] == pytest.approx(round(781 / 92, 4))
    assert strip["step_ratio"] == pytest.approx(round((781 / 92) / 1.0, 4))
    assert strip["interval_delta_s"] == pytest.approx(0.047 - 0.1)
    assert strip["observed_overhead_s"] == pytest.approx(round(4.344 - 92 * 0.047, 4))
    assert observed["accepted"] is False


def test_observed_comparison_refuses_a_point_the_matrix_does_not_declare(
    tmp_path: Path,
) -> None:
    document = matrix.build_matrix(matrix.validate_spec(_spec()))
    run = _recorded_run(tmp_path)
    with pytest.raises(MatrixSpecError, match="no declared row matches"):
        matrix.compare_observed(
            document, run, commanded_speed_um_s=33.0, exposure_ms=10.0, width_um=20.0
        )
    with pytest.raises(MatrixSpecError, match="no declared row matches"):
        matrix.compare_observed(
            document, run, commanded_speed_um_s=10.0, exposure_ms=10.0, width_um=20.5
        )


def test_observed_comparison_states_what_it_cannot_compare(tmp_path: Path) -> None:
    document = matrix.build_matrix(matrix.validate_spec(_spec()))
    observed = matrix.compare_observed(
        document,
        _recorded_run(tmp_path),
        commanded_speed_um_s=10.0,
        exposure_ms=10.0,
        width_um=20.0,
    )
    assert {item["metric"] for item in observed["not_comparable"]} == {
        "valid_area",
        "local_support_duration",
        "psf_blur",
    }
    assert "service's own unit" in observed["guard"]
    assert "physical speed" in observed["guard"]


def test_observed_comparison_tolerates_a_missing_interval(tmp_path: Path) -> None:
    document = matrix.build_matrix(matrix.validate_spec(_spec()))
    observed = matrix.compare_observed(
        document,
        _recorded_run(tmp_path, interval=None),
        commanded_speed_um_s=10.0,
        exposure_ms=10.0,
        width_um=20.0,
    )
    strip = observed["strips"][0]
    assert strip["interval_delta_s"] is None
    assert strip["observed_overhead_s"] is None
    assert observed["summary"]["interval_delta_median_s"] is None


def test_observed_comparison_needs_one_strip_record(tmp_path: Path) -> None:
    document = matrix.build_matrix(matrix.validate_spec(_spec()))
    run = _recorded_run(tmp_path)
    (run / "strips" / "asi-broom-ix71-test-01-strips.json").unlink()
    with pytest.raises(MatrixSpecError, match="strip record"):
        matrix.compare_observed(
            document, run, commanded_speed_um_s=10.0, exposure_ms=10.0, width_um=20.0
        )


DESIGN_SPEC = Path(__file__).resolve().parent / "spec.ix71-design-v1.json"
REAL_RUN = (
    Path(__file__).resolve().parents[2]
    / "08_session_logs"
    / "20261024T_long_strip_broom_01"
    / "run_snake_06"
)


@pytest.mark.skipif(not REAL_RUN.is_dir(), reason="recorded run is not present")
def test_observed_comparison_on_a_recorded_run_reproduces_its_step() -> None:
    document = matrix.build_matrix(matrix.load_spec(DESIGN_SPEC))
    observed = matrix.compare_observed(
        document,
        REAL_RUN,
        commanded_speed_um_s=100.0,
        exposure_ms=10.0,
        width_um=219.384,
    )
    assert observed["summary"]["predicted_frames_per_strip"] == 157
    assert observed["summary"]["observed_frames"] == [93, 93, 93]
    # 781 um over 92 intervals is ~8.49 um/frame against a declared 5 um step.
    assert observed["summary"]["step_ratio_median"] == pytest.approx(1.6971, abs=0.001)
    assert observed["summary"]["interval_delta_median_s"] == pytest.approx(
        0.047 - 0.05, abs=1e-9
    )
