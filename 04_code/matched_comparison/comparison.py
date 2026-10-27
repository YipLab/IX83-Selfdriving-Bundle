"""Matched-strategy comparison manifest and offline reducer (Q07).

Q07 asks for a bundle-owned experiment manifest that invokes the supported
survey/revisit, uniform broom and adaptive broom plans with one common specimen
footprint, target criterion, observation requirement and quality rule, including
a mean-step-matched and a residence-requirement-matched fixed control. An offline
reducer then reports union valid area per time, accepted target windows per
minute, the successful fraction and paired field/specimen effects.

Nothing here acquires data. The manifest is a versioned declaration; the reducer
consumes an event table from recorded or replayed units and refuses to treat
frames, tracks or overlapping units as independent specimens.

    python comparison.py --manifest spec.ix71-matched-v1.json \\
        --events events.example.json --out comparison_report.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MANIFEST_SCHEMA = "ix71.matched-comparison.1"
EVENTS_SCHEMA = "ix71.matched-comparison-events.1"
REPORT_SCHEMA = "ix71.matched-comparison-report.1"

PRIMARY_STRATEGIES = ("survey_revisit", "uniform_broom", "adaptive_broom")
CONTROL_STRATEGIES = ("mean_step_matched", "residence_matched")
ALL_STRATEGIES = PRIMARY_STRATEGIES + CONTROL_STRATEGIES
REQUIRED_TIME_ENDPOINTS = (
    "focus",
    "travel",
    "review",
    "acquisition",
    "segmentation",
    "processing",
)
REFERENCE_STRATEGY = "uniform_broom"


class ComparisonError(ValueError):
    """A manifest or event table is missing, inconsistent or not comparable."""


def _number(value: Any, name: str, *, positive: bool = True) -> float:
    """Return a finite number, rejecting bools and out-of-range values."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ComparisonError(f"{name} must be a number")
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        raise ComparisonError(f"{name} must be finite")
    if positive and number <= 0:
        raise ComparisonError(f"{name} must be positive")
    if not positive and number < 0:
        raise ComparisonError(f"{name} must be nonnegative")
    return number


def _integer(value: Any, name: str, *, minimum: int = 1) -> int:
    """Return an integer at or above a minimum."""
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ComparisonError(f"{name} must be an integer >= {minimum}")
    return value


def _text(value: Any, name: str) -> str:
    """Return a nonempty string."""
    if not isinstance(value, str) or not value.strip():
        raise ComparisonError(f"{name} is required")
    return value.strip()


def _mapping(value: Any, name: str) -> dict[str, Any]:
    """Return a required mapping."""
    if not isinstance(value, dict):
        raise ComparisonError(f"{name} must be an object")
    return value


def _broom_arm(arm: dict[str, Any], name: str) -> tuple[float, float]:
    """Return a broom arm's speed and its declared frame-period step."""
    speed = _number(arm.get("speed_um_s"), f"strategies.{name}.speed_um_s")
    return speed, speed


def validate_manifest(document: Any) -> dict[str, Any]:
    """Validate a matched-comparison manifest and derive the control arithmetic.

    The three strategies share one footprint, target criterion, observation
    requirement and quality rule; an arm that restates any of them is refused,
    because two nominally matched arms with different units are not comparable.
    """
    spec = _mapping(document, "manifest")
    if spec.get("schema") != MANIFEST_SCHEMA:
        raise ComparisonError(f"schema must be {MANIFEST_SCHEMA!r}")
    experiment_id = _text(spec.get("experiment_id"), "experiment_id")
    specimen_id = _text(spec.get("specimen_id"), "specimen_id")
    footprint = _mapping(spec.get("footprint"), "footprint")
    width = _number(footprint.get("width_um"), "footprint.width_um")
    height = _number(footprint.get("height_um"), "footprint.height_um")
    overlap = _number(footprint.get("overlap"), "footprint.overlap", positive=False)
    if overlap >= 1:
        raise ComparisonError("footprint.overlap must be below 1")
    criterion = _mapping(spec.get("target_criterion"), "target_criterion")
    min_area = _integer(criterion.get("min_area_px"), "target_criterion.min_area_px")
    max_area = _integer(criterion.get("max_area_px"), "target_criterion.max_area_px")
    if min_area >= max_area:
        raise ComparisonError("target_criterion.min_area_px must be below max_area_px")
    detection = _number(
        criterion.get("detection_threshold"), "target_criterion.detection_threshold"
    )
    dedup = _number(
        criterion.get("dedup_um"), "target_criterion.dedup_um", positive=False
    )
    observation = _mapping(
        spec.get("observation_requirement"), "observation_requirement"
    )
    min_windows = _integer(
        observation.get("min_windows_per_target"),
        "observation_requirement.min_windows_per_target",
    )
    window_s = _number(observation.get("window_s"), "observation_requirement.window_s")
    quality = _mapping(spec.get("quality_rule"), "quality_rule")
    max_blur = _number(quality.get("max_blur_ratio"), "quality_rule.max_blur_ratio")
    max_edge = _number(quality.get("max_edge_rms_px"), "quality_rule.max_edge_rms_px")
    illumination = _mapping(spec.get("illumination"), "illumination")
    mode = _text(illumination.get("mode"), "illumination.mode")
    setpoint = _number(illumination.get("setpoint_mw"), "illumination.setpoint_mw")
    exposure = _number(illumination.get("exposure_ms"), "illumination.exposure_ms")
    frame_period = _number(spec.get("frame_period_s"), "frame_period_s")
    detector_width = _number(spec.get("detector_width_um"), "detector_width_um")
    if exposure >= frame_period * 1000:
        raise ComparisonError("illumination.exposure_ms must be below the frame period")

    endpoints = spec.get("time_endpoints")
    if not isinstance(endpoints, list) or not endpoints:
        raise ComparisonError("time_endpoints must be a nonempty list")
    missing = [item for item in REQUIRED_TIME_ENDPOINTS if item not in endpoints]
    if missing:
        raise ComparisonError(f"time_endpoints is missing {missing}")

    blocks = spec.get("field_blocks")
    if not isinstance(blocks, list) or not blocks:
        raise ComparisonError("field_blocks must be a nonempty list")
    parsed_blocks = []
    for index, block in enumerate(blocks):
        entry = _mapping(block, f"field_blocks[{index}]")
        block_id = _integer(entry.get("block"), f"field_blocks[{index}].block")
        fields = entry.get("fields")
        if (
            not isinstance(fields, list)
            or not fields
            or any(not isinstance(field, str) or not field.strip() for field in fields)
        ):
            raise ComparisonError(
                f"field_blocks[{index}].fields must be nonempty names"
            )
        order = entry.get("order")
        if not isinstance(order, list) or sorted(order) != sorted(PRIMARY_STRATEGIES):
            raise ComparisonError(
                f"field_blocks[{index}].order must list "
                f"{list(PRIMARY_STRATEGIES)} once each"
            )
        parsed_blocks.append(
            {"block": block_id, "fields": list(fields), "order": list(order)}
        )

    strategies_doc = _mapping(spec.get("strategies"), "strategies")
    if set(strategies_doc) != set(ALL_STRATEGIES):
        raise ComparisonError(f"strategies must declare exactly {list(ALL_STRATEGIES)}")
    common_units = {
        "footprint",
        "target_criterion",
        "observation_requirement",
        "quality_rule",
    }
    strategies: dict[str, dict[str, Any]] = {}
    for name in ALL_STRATEGIES:
        arm = _mapping(strategies_doc[name], f"strategies.{name}")
        overrides = common_units.intersection(arm)
        if overrides:
            raise ComparisonError(
                f"strategies.{name} restates common units {sorted(overrides)}; "
                "the comparison requires one shared declaration"
            )
        plan = _text(arm.get("plan"), f"strategies.{name}.plan")
        strategies[name] = {"plan": plan}
        if name == "survey_revisit":
            strategies[name]["step_um"] = _number(
                arm.get("step_um"), f"strategies.{name}.step_um"
            )
            continue
        if name == "adaptive_broom":
            # The adaptive arm declares a mean rate and step, not one fixed speed.
            continue
        speed, _ = _broom_arm(arm, name)
        strategies[name]["speed_um_s"] = speed
        strategies[name]["step_um"] = speed * frame_period
        strategies[name]["residence_s"] = detector_width / speed
    adaptive = strategies["adaptive_broom"]
    adaptive_doc = strategies_doc["adaptive_broom"]
    adaptive["mean_speed_um_s"] = _number(
        adaptive_doc.get("mean_speed_um_s"), "strategies.adaptive_broom.mean_speed_um_s"
    )
    adaptive["mean_step_um"] = _number(
        adaptive_doc.get("mean_step_um"), "strategies.adaptive_broom.mean_step_um"
    )
    adaptive["mean_residence_s"] = detector_width / adaptive["mean_speed_um_s"]
    adaptive["speed_um_s"] = adaptive["mean_speed_um_s"]
    adaptive["step_um"] = adaptive["mean_step_um"]
    adaptive["residence_s"] = adaptive["mean_residence_s"]

    controls = _mapping(spec.get("controls"), "controls")
    step_tolerance = _number(
        controls.get("mean_step_tolerance_fraction"),
        "controls.mean_step_tolerance_fraction",
        positive=False,
    )
    residence_requirement = _number(
        controls.get("residence_requirement_s"), "controls.residence_requirement_s"
    )
    residence_tolerance = _number(
        controls.get("residence_tolerance_s"),
        "controls.residence_tolerance_s",
        positive=False,
    )
    matched_step = strategies["mean_step_matched"]["step_um"]
    step_delta = matched_step - adaptive["mean_step_um"]
    step_limit = step_tolerance * adaptive["mean_step_um"]
    if abs(step_delta) > step_limit + 1e-9:
        raise ComparisonError(
            "mean_step_matched is not matched: "
            f"step {matched_step:.4f} um against adaptive mean "
            f"{adaptive['mean_step_um']:.4f} um "
            f"(tolerance {step_limit:.4f})"
        )
    matched_residence = strategies["residence_matched"]["residence_s"]
    residence_delta = matched_residence - residence_requirement
    if abs(residence_delta) > residence_tolerance + 1e-9:
        raise ComparisonError(
            "residence_matched is not matched: "
            f"residence {matched_residence:.4f} s against requirement "
            f"{residence_requirement:.4f} s (tolerance {residence_tolerance})"
        )
    if adaptive["mean_residence_s"] < residence_requirement - 1e-9:
        raise ComparisonError(
            "adaptive_broom mean residence "
            f"{adaptive['mean_residence_s']:.4f} s is below the declared requirement "
            f"{residence_requirement:.4f} s"
        )

    return {
        "schema": MANIFEST_SCHEMA,
        "experiment_id": experiment_id,
        "specimen_id": specimen_id,
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "footprint": {"width_um": width, "height_um": height, "overlap": overlap},
        "detector_width_um": detector_width,
        "frame_period_s": frame_period,
        "target_criterion": {
            "detection_threshold": detection,
            "min_area_px": min_area,
            "max_area_px": max_area,
            "dedup_um": dedup,
        },
        "observation_requirement": {
            "min_windows_per_target": min_windows,
            "window_s": window_s,
        },
        "quality_rule": {
            "max_blur_ratio": max_blur,
            "max_edge_rms_px": max_edge,
        },
        "illumination": {
            "mode": mode,
            "setpoint_mw": setpoint,
            "exposure_ms": exposure,
        },
        "time_endpoints": list(endpoints),
        "field_blocks": parsed_blocks,
        "strategies": strategies,
        "controls": {
            "mean_step_tolerance_fraction": step_tolerance,
            "residence_requirement_s": residence_requirement,
            "residence_tolerance_s": residence_tolerance,
            "mean_step_delta_um": round(step_delta, 6),
            "residence_delta_s": round(residence_delta, 6),
        },
        "reference_strategy": REFERENCE_STRATEGY,
    }


def load_manifest(path: Path) -> dict[str, Any]:
    """Read and validate one manifest file."""
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ComparisonError(f"manifest not found: {path}") from error
    except json.JSONDecodeError as error:
        raise ComparisonError(f"manifest is not JSON: {error}") from error
    return validate_manifest(document)


def reduce_events(manifest: dict[str, Any], events: Any) -> dict[str, Any]:
    """Reduce per-field event units into the Q07 comparison figures.

    Units are fields. A unit that names a frame or a track, or that overlaps
    another unit's area, is refused: overlapping frames and tracks are not
    independent specimens and their areas cannot be summed as a union.
    """
    document = _mapping(events, "events")
    if document.get("schema") != EVENTS_SCHEMA:
        raise ComparisonError(f"events schema must be {EVENTS_SCHEMA!r}")
    if document.get("experiment_id") != manifest["experiment_id"]:
        raise ComparisonError(
            "event table and manifest name different experiments: "
            f"{document.get('experiment_id')!r} against {manifest['experiment_id']!r}"
        )
    units = document.get("units")
    if not isinstance(units, list) or not units:
        raise ComparisonError("events.units must be a nonempty list")
    parsed = []
    for index, unit in enumerate(units):
        entry = _mapping(unit, f"units[{index}]")
        for forbidden in ("frame_id", "track_id"):
            if forbidden in entry:
                raise ComparisonError(
                    f"units[{index}] is a {forbidden}; the comparison unit is a field"
                )
        if entry.get("granularity", "field") != "field":
            raise ComparisonError(
                f"units[{index}] declares granularity {entry.get('granularity')!r}; "
                "only field units are independent"
            )
        unit_id = _text(entry.get("unit_id"), f"units[{index}].unit_id")
        field_id = _text(entry.get("field_id"), f"units[{index}].field_id")
        specimen = _text(entry.get("specimen_id"), f"units[{index}].specimen_id")
        strategy = entry.get("strategy")
        if strategy not in manifest["strategies"]:
            raise ComparisonError(
                f"units[{index}] names strategy {strategy!r}, which the manifest "
                "does not declare"
            )
        if entry.get("overlap_with"):
            raise ComparisonError(
                f"units[{index}] overlaps another unit; union area would double-count"
            )
        parsed.append(
            {
                "unit_id": unit_id,
                "field_id": field_id,
                "specimen_id": specimen,
                "field_block": entry.get("field_block"),
                "strategy": strategy,
                "valid_area_um2": _number(
                    entry.get("valid_area_um2"),
                    f"units[{index}].valid_area_um2",
                    positive=False,
                ),
                "elapsed_s": _number(
                    entry.get("elapsed_s"), f"units[{index}].elapsed_s"
                ),
                "targets_detected": _integer(
                    entry.get("targets_detected"),
                    f"units[{index}].targets_detected",
                    minimum=0,
                ),
                "targets_accepted": _integer(
                    entry.get("targets_accepted"),
                    f"units[{index}].targets_accepted",
                    minimum=0,
                ),
                "accepted_windows": _integer(
                    entry.get("accepted_windows"),
                    f"units[{index}].accepted_windows",
                    minimum=0,
                ),
                "time": entry.get("time")
                if isinstance(entry.get("time"), dict)
                else {},
            }
        )
    unit_ids = [unit["unit_id"] for unit in parsed]
    duplicates = sorted({value for value in unit_ids if unit_ids.count(value) > 1})
    if duplicates:
        raise ComparisonError(f"repeated unit ids: {duplicates}")
    for unit in parsed:
        if unit["targets_accepted"] > unit["targets_detected"]:
            raise ComparisonError(
                f"{unit['unit_id']} accepts {unit['targets_accepted']} of "
                f"{unit['targets_detected']} detected targets"
            )

    by_strategy: dict[str, dict[str, Any]] = {}
    for name in manifest["strategies"]:
        selected = [unit for unit in parsed if unit["strategy"] == name]
        if not selected:
            continue
        elapsed = sum(unit["elapsed_s"] for unit in selected)
        area = sum(unit["valid_area_um2"] for unit in selected)
        detected = sum(unit["targets_detected"] for unit in selected)
        accepted = sum(unit["targets_accepted"] for unit in selected)
        windows = sum(unit["accepted_windows"] for unit in selected)
        by_strategy[name] = {
            "units": len(selected),
            "valid_area_mm2": round(area / 1e6, 6),
            "elapsed_s": round(elapsed, 3),
            "area_mm2_per_min": round(area / 1e6 / (elapsed / 60.0), 6)
            if elapsed
            else None,
            "accepted_windows": windows,
            "accepted_windows_per_min": round(windows / (elapsed / 60.0), 4)
            if elapsed
            else None,
            "targets_detected": detected,
            "targets_accepted": accepted,
            "success_fraction": round(accepted / detected, 4) if detected else None,
        }

    reference = manifest["reference_strategy"]
    paired = []
    unpaired = []
    fields = sorted({unit["field_id"] for unit in parsed})
    for field in fields:
        field_units = {
            unit["strategy"]: unit for unit in parsed if unit["field_id"] == field
        }
        if reference not in field_units:
            unpaired.append({"field_id": field, "reason": "reference arm missing"})
            continue
        base = field_units[reference]
        for name in manifest["strategies"]:
            if name == reference:
                continue
            if name not in field_units:
                unpaired.append({"field_id": field, "reason": f"{name} arm missing"})
                continue
            arm = field_units[name]
            if base["elapsed_s"] <= 0:
                unpaired.append(
                    {"field_id": field, "reason": "reference elapsed time is zero"}
                )
                continue
            paired.append(
                {
                    "field_id": field,
                    "strategy": name,
                    "area_mm2_per_min_delta": round(
                        arm["valid_area_um2"] / 1e6 / (arm["elapsed_s"] / 60.0)
                        - base["valid_area_um2"] / 1e6 / (base["elapsed_s"] / 60.0),
                        6,
                    ),
                    "accepted_windows_per_min_delta": round(
                        arm["accepted_windows"] / (arm["elapsed_s"] / 60.0)
                        - base["accepted_windows"] / (base["elapsed_s"] / 60.0),
                        4,
                    ),
                }
            )

    measured_endpoints = set()
    for unit in parsed:
        measured_endpoints.update(unit["time"])
    not_measured = [
        endpoint
        for endpoint in REQUIRED_TIME_ENDPOINTS
        if endpoint not in measured_endpoints
    ]
    return {
        "schema": REPORT_SCHEMA,
        "experiment_id": manifest["experiment_id"],
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "units": len(parsed),
        "by_strategy": by_strategy,
        "paired": paired,
        "unpaired": unpaired,
        "time_endpoints_not_measured": not_measured,
        "declared_controls": manifest["controls"],
        "notes": [
            "units are fields, not frames or tracks",
            "union area is summed over disjoint field units only",
            "a strategy absent from the event table is absent from "
            "by_strategy, not zero",
        ],
        "accepted": False,
    }


def main(argv: list[str] | None = None) -> int:
    """Validate a manifest, reduce an event table, and write the report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--events", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    try:
        manifest = load_manifest(args.manifest)
    except ComparisonError as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2
    print(
        f"{manifest['experiment_id']}: 5 strategies over "
        f"{len(manifest['field_blocks'])} field block(s); "
        f"mean-step delta {manifest['controls']['mean_step_delta_um']} um, "
        f"residence delta {manifest['controls']['residence_delta_s']} s"
    )
    if args.events is None:
        return 0
    try:
        events = json.loads(args.events.read_text(encoding="utf-8"))
        report = reduce_events(manifest, events)
    except FileNotFoundError:
        print(f"refused: events not found: {args.events}", file=sys.stderr)
        return 2
    except ComparisonError as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    for name, figures in report["by_strategy"].items():
        print(
            f"  {name:<18} {figures['units']} field(s), "
            f"{figures['area_mm2_per_min']} mm2/min, "
            f"{figures['accepted_windows_per_min']} windows/min, "
            f"success {figures['success_fraction']}"
        )
    print(
        f"  paired {len(report['paired'])}, unpaired {len(report['unpaired'])}, "
        f"endpoints not measured {report['time_endpoints_not_measured']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
