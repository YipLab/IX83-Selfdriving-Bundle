"""Hardware-free tests for the frozen-limits check (Q05)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import limits


def _limits(**bounds: dict[str, float]) -> dict[str, Any]:
    document = {
        "schema": limits.LIMITS_SCHEMA,
        "author": "fixture-author",
        "date": "2026-10-27",
        "status": "author-declared",
        "rationale": "fixture bounds",
        "bounds": bounds or {"speed_um_s": {"max": 100.0}},
    }
    return document


def _row(**overrides: Any) -> dict[str, Any]:
    row = {
        "detector_mode": "virtual_slit",
        "speed_um_s": 50.0,
        "exposure_ms": 5.0,
        "frame_period_s": 0.05,
        "width_um": 20.0,
        "step_um": 1.0,
        "retained_frames_per_strip": 100,
        "feasible": True,
        "reasons": [],
    }
    row.update(overrides)
    return row


def _matrix(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"schema": limits.MATRIX_SCHEMA, "spec": {"name": "fixture"}, "rows": rows}


def test_rows_within_the_declared_bounds_are_marked_within() -> None:
    report = limits.check_matrix(
        _matrix([_row(), _row(speed_um_s=10.0)]), _limits(speed_um_s={"max": 100.0})
    )

    assert report["accepted"] is True
    assert report["summary"] == {
        "rows": 2,
        "within_limits": 2,
        "outside_limits": 0,
        "outside_and_matrix_feasible": 0,
    }
    assert report["issues"] == []


def test_a_row_outside_a_bound_carries_a_typed_violation() -> None:
    report = limits.check_matrix(
        _matrix([_row(speed_um_s=200.0), _row(exposure_ms=1.0)]),
        _limits(speed_um_s={"max": 100.0}, exposure_ms={"min": 2.0}),
    )

    assert report["accepted"] is True
    assert report["summary"]["outside_limits"] == 2
    assert report["summary"]["outside_and_matrix_feasible"] == 2
    codes = [row["violations"] for row in report["rows"]]
    assert codes == [["speed_um_s_above_max"], ["exposure_ms_below_min"]]


def test_a_row_that_was_already_infeasible_keeps_its_own_reasons() -> None:
    report = limits.check_matrix(
        _matrix([_row(speed_um_s=200.0, feasible=False, reasons=[{"code": "binding"}])]),
        _limits(speed_um_s={"max": 100.0}),
    )

    assert report["rows"][0]["matrix_feasible"] is False
    assert report["rows"][0]["within_limits"] is False
    assert report["summary"]["outside_and_matrix_feasible"] == 0


def test_a_missing_identity_or_rationale_is_refused() -> None:
    for key in ("author", "date", "rationale"):
        document = _limits(speed_um_s={"max": 1.0})
        document[key] = " "
        with pytest.raises(limits.LimitsError, match=key):
            limits.validate_limits(document)


def test_an_unknown_or_missing_quantity_is_refused() -> None:
    with pytest.raises(limits.LimitsError, match="unknown bound quantity"):
        limits.validate_limits(_limits(laser_power_mw={"max": 1.0}))
    with pytest.raises(limits.LimitsError, match="no matching row quantity"):
        limits.check_matrix(
            {"schema": limits.MATRIX_SCHEMA, "rows": [{"speed_um_s": 1.0}]},
            _limits(width_um={"max": 50.0}),
        )


def test_a_row_missing_a_bounded_field_is_reported() -> None:
    row = _row()
    del row["width_um"]
    report = limits.check_matrix(_matrix([_row(), row]), _limits(width_um={"max": 50.0}))

    assert report["rows"][0]["within_limits"] is True
    assert report["rows"][1]["violations"] == ["width_um_missing_in_row"]


def test_bad_bounds_and_statuses_are_refused() -> None:
    with pytest.raises(limits.LimitsError, match="status"):
        limits.validate_limits(_limits() | {"status": "final"})
    with pytest.raises(limits.LimitsError, match="finite"):
        limits.validate_limits(_limits(speed_um_s={"max": float("inf")}))
    with pytest.raises(limits.LimitsError, match="min exceeds max"):
        limits.validate_limits(_limits(speed_um_s={"min": 5.0, "max": 1.0}))
    with pytest.raises(limits.LimitsError, match="unknown key"):
        limits.validate_limits(_limits(speed_um_s={"typical": 1.0}))
    with pytest.raises(limits.LimitsError, match="matrix schema"):
        limits.check_matrix({"schema": "other", "rows": [_row()]}, _limits())
    with pytest.raises(limits.LimitsError, match="no rows"):
        limits.check_matrix({"schema": limits.MATRIX_SCHEMA, "rows": []}, _limits())


def test_a_provisional_declaration_is_retained_as_information() -> None:
    document = _limits(speed_um_s={"max": 10.0})
    document["status"] = "provisional"

    report = limits.check_matrix(_matrix([_row(speed_um_s=50.0)]), document)

    assert report["accepted"] is True
    assert report["limits"]["status"] == "provisional"
    assert report["issues"] == [
        {
            "code": "limits_provisional",
            "severity": "info",
            "detail": "the declaration is provisional, not the instrument's frozen decision",
        }
    ]


def test_the_command_line_checks_a_matrix(tmp_path: Path) -> None:
    matrix_path = tmp_path / "matrix.json"
    limits_path = tmp_path / "limits.json"
    output = tmp_path / "checked.json"
    matrix_path.write_text(json.dumps(_matrix([_row(speed_um_s=50.0)])), encoding="utf-8")
    limits_path.write_text(json.dumps(_limits(speed_um_s={"max": 100.0})), encoding="utf-8")

    assert limits.main([str(matrix_path), "--limits", str(limits_path), "--output", str(output)]) == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["schema"] == limits.REPORT_SCHEMA
    assert report["summary"]["within_limits"] == 1

