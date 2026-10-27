"""Hardware-free tests for the matched-comparison manifest and reducer."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import comparison
import pytest
from comparison import ComparisonError

HERE = Path(__file__).resolve().parent
MANIFEST = json.loads((HERE / "spec.ix71-matched-v1.json").read_text(encoding="utf-8"))
EVENTS = json.loads((HERE / "events.example.json").read_text(encoding="utf-8"))


def _manifest(**overrides: Any) -> dict[str, Any]:
    spec = copy.deepcopy(MANIFEST)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(spec.get(key), dict):
            spec[key].update(value)
        else:
            spec[key] = value
    return spec


def _events(**overrides: Any) -> dict[str, Any]:
    document = copy.deepcopy(EVENTS)
    document.update(overrides)
    return document


def test_the_shipped_manifest_validates_and_derives_its_controls() -> None:
    spec = comparison.validate_manifest(_manifest())
    assert spec["experiment_id"] == "ix71-matched-design-v1"
    assert spec["strategies"]["uniform_broom"]["step_um"] == pytest.approx(10.0)
    assert spec["strategies"]["mean_step_matched"]["step_um"] == pytest.approx(5.0)
    assert spec["strategies"]["residence_matched"]["residence_s"] == pytest.approx(2.0)
    assert spec["strategies"]["adaptive_broom"]["mean_residence_s"] == pytest.approx(
        2.19384
    )
    assert spec["controls"]["mean_step_delta_um"] == pytest.approx(0.0)
    assert spec["controls"]["residence_delta_s"] == pytest.approx(0.0, abs=1e-9)
    assert spec["reference_strategy"] == "uniform_broom"
    assert len(spec["field_blocks"]) == 1
    assert spec["field_blocks"][0]["order"] == [
        "survey_revisit",
        "uniform_broom",
        "adaptive_broom",
    ]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"schema": "other"}, "schema"),
        ({"experiment_id": ""}, "experiment_id"),
        ({"specimen_id": " "}, "specimen_id"),
        ({"footprint": {"overlap": 1.2}}, "overlap"),
        ({"target_criterion": {"min_area_px": 90000}}, "min_area_px"),
        ({"time_endpoints": ["focus", "travel"]}, "missing"),
        ({"field_blocks": []}, "field_blocks"),
        ({"frame_period_s": 0.0}, "frame_period_s"),
        ({"detector_width_um": -1}, "detector_width_um"),
        ({"illumination": {"exposure_ms": 60.0}}, "exposure_ms"),
    ],
)
def test_invalid_manifests_are_refused(change: dict[str, Any], message: str) -> None:
    with pytest.raises(ComparisonError, match=message):
        comparison.validate_manifest(_manifest(**change))


def test_a_field_block_must_order_each_primary_strategy_once() -> None:
    with pytest.raises(ComparisonError, match="order must list"):
        comparison.validate_manifest(
            _manifest(
                field_blocks=[
                    {
                        "block": 1,
                        "fields": ["field-a"],
                        "order": ["uniform_broom", "adaptive_broom"],
                    }
                ]
            )
        )


def test_an_arm_may_not_restate_a_common_unit() -> None:
    spec = _manifest()
    spec["strategies"]["adaptive_broom"]["footprint"] = {"width_um": 10.0}
    with pytest.raises(ComparisonError, match="restates common units"):
        comparison.validate_manifest(spec)


def test_the_mean_step_control_must_match_the_adaptive_mean() -> None:
    spec = _manifest()
    spec["strategies"]["mean_step_matched"]["speed_um_s"] = 150.0
    with pytest.raises(ComparisonError, match="mean_step_matched is not matched"):
        comparison.validate_manifest(spec)


def test_the_residence_control_must_match_the_declared_requirement() -> None:
    spec = _manifest()
    spec["strategies"]["residence_matched"]["speed_um_s"] = 200.0
    with pytest.raises(ComparisonError, match="residence_matched is not matched"):
        comparison.validate_manifest(spec)


def test_the_adaptive_arm_must_meet_the_residence_requirement() -> None:
    spec = _manifest()
    spec["strategies"]["adaptive_broom"]["mean_speed_um_s"] = 150.0
    with pytest.raises(ComparisonError, match="below the declared requirement"):
        comparison.validate_manifest(spec)


def test_the_adaptive_arm_must_declare_its_mean_rate_and_step() -> None:
    spec = _manifest()
    del spec["strategies"]["adaptive_broom"]["mean_step_um"]
    with pytest.raises(ComparisonError, match="mean_step_um"):
        comparison.validate_manifest(spec)


def test_the_reducer_computes_the_example_figures() -> None:
    spec = comparison.validate_manifest(_manifest())
    report = comparison.reduce_events(spec, _events())

    assert report["units"] == 10
    assert report["by_strategy"]["survey_revisit"]["area_mm2_per_min"] == pytest.approx(
        0.35
    )
    assert report["by_strategy"]["uniform_broom"]["area_mm2_per_min"] == pytest.approx(
        0.525
    )
    assert report["by_strategy"]["adaptive_broom"]["area_mm2_per_min"] == pytest.approx(
        0.54
    )
    assert report["by_strategy"]["adaptive_broom"][
        "accepted_windows_per_min"
    ] == pytest.approx(59.4)
    assert report["by_strategy"]["uniform_broom"]["success_fraction"] == pytest.approx(
        0.9091
    )
    assert report["by_strategy"]["residence_matched"][
        "success_fraction"
    ] == pytest.approx(0.8182)
    assert report["unpaired"] == []
    assert report["time_endpoints_not_measured"] == []
    assert report["accepted"] is False


def test_pairing_subtracts_the_reference_arm_per_field() -> None:
    spec = comparison.validate_manifest(_manifest())
    report = comparison.reduce_events(spec, _events())
    entry = next(
        item
        for item in report["paired"]
        if item["field_id"] == "field-a" and item["strategy"] == "adaptive_broom"
    )
    assert entry["area_mm2_per_min_delta"] == pytest.approx(0.0)
    assert entry["accepted_windows_per_min_delta"] == pytest.approx(6.0)
    assert len(report["paired"]) == 8


def test_a_missing_arm_is_reported_as_unpaired() -> None:
    spec = comparison.validate_manifest(_manifest())
    events = _events()
    events["units"] = [
        unit
        for unit in events["units"]
        if not (unit["field_id"] == "field-b" and unit["strategy"] == "adaptive_broom")
    ]
    report = comparison.reduce_events(spec, events)
    assert {"field_id": "field-b", "reason": "adaptive_broom arm missing"} in report[
        "unpaired"
    ]
    assert not any(
        item["field_id"] == "field-b" and item["strategy"] == "adaptive_broom"
        for item in report["paired"]
    )


@pytest.mark.parametrize("key", ["frame_id", "track_id"])
def test_a_frame_or_track_unit_is_refused(key: str) -> None:
    spec = comparison.validate_manifest(_manifest())
    events = _events()
    events["units"][0][key] = 1
    with pytest.raises(ComparisonError, match="comparison unit is a field"):
        comparison.reduce_events(spec, events)


def test_a_non_field_granularity_is_refused() -> None:
    spec = comparison.validate_manifest(_manifest())
    events = _events()
    events["units"][0]["granularity"] = "track"
    with pytest.raises(ComparisonError, match="only field units are independent"):
        comparison.reduce_events(spec, events)


def test_overlapping_units_cannot_be_summed_as_a_union() -> None:
    spec = comparison.validate_manifest(_manifest())
    events = _events()
    events["units"][0]["overlap_with"] = ["f1-adaptive"]
    with pytest.raises(ComparisonError, match="overlaps another unit"):
        comparison.reduce_events(spec, events)


def test_events_and_manifest_must_name_one_experiment() -> None:
    spec = comparison.validate_manifest(_manifest())
    events = _events(experiment_id="other")
    with pytest.raises(ComparisonError, match="different experiments"):
        comparison.reduce_events(spec, events)


def test_empty_events_are_refused() -> None:
    spec = comparison.validate_manifest(_manifest())
    with pytest.raises(ComparisonError, match="units"):
        comparison.reduce_events(spec, _events(units=[]))


def test_accepted_targets_cannot_exceed_detected_targets() -> None:
    spec = comparison.validate_manifest(_manifest())
    events = _events()
    events["units"][0]["targets_accepted"] = 13
    with pytest.raises(ComparisonError, match="accepts"):
        comparison.reduce_events(spec, events)


def test_duplicate_unit_ids_are_refused() -> None:
    spec = comparison.validate_manifest(_manifest())
    events = _events()
    events["units"][1]["unit_id"] = events["units"][0]["unit_id"]
    with pytest.raises(ComparisonError, match="repeated unit ids"):
        comparison.reduce_events(spec, events)


def test_endpoints_without_any_recorded_seconds_are_listed() -> None:
    spec = comparison.validate_manifest(_manifest())
    events = _events()
    for unit in events["units"]:
        unit.pop("time", None)
    report = comparison.reduce_events(spec, events)
    assert report["time_endpoints_not_measured"] == [
        "focus",
        "travel",
        "review",
        "acquisition",
        "segmentation",
        "processing",
    ]


def test_cli_validates_the_manifest_and_writes_the_report(tmp_path: Path) -> None:
    out = tmp_path / "report.json"
    assert (
        comparison.main(
            [
                "--manifest",
                str(HERE / "spec.ix71-matched-v1.json"),
                "--events",
                str(HERE / "events.example.json"),
                "--out",
                str(out),
            ]
        )
        == 0
    )
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["units"] == 10

    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema": "other"}), encoding="utf-8")
    assert comparison.main(["--manifest", str(bad)]) == 2

    assert comparison.main(["--manifest", str(HERE / "spec.ix71-matched-v1.json")]) == 0
