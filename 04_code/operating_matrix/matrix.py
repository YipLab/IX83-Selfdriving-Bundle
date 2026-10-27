"""Executable operating matrix: speed x exposure x detector width, with refusals.

Q05 of the 2026-10-27 increment asks for a versioned operating matrix composed
from the installed planner calculations, measured device capabilities and
application bounds, with infeasible settings recorded rather than dropped, and
with hardware ROI, virtual reconstruction slit, illumination footprint, exposure
and frame interval kept distinct.

The module adapts `planner.acquisition_space` instead of re-deriving its model:
each row builds an ``AcquisitionPoint`` and calls ``assess_measurement``, then
adds the binding checks the planner cannot know (stage speed ceiling, sensor
field, illumination footprint, ROI pixel alignment, exposure against the frame
period). Every refusal carries a typed reason, and the document lists the
metrics it could not compute so an incomplete matrix cannot look finished.

    python matrix.py --spec spec.ix71-design-v1.json --out operating_matrix.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PLANNER = ROOT / "03_external" / "sample_search" / "src"
if str(PLANNER) not in sys.path:
    sys.path.insert(0, str(PLANNER))

from planner.acquisition_space import (  # noqa: E402
    AcquisitionPoint,
    FeasibilityReason,
    MeasurementLimits,
    assess_measurement,
)

MATRIX_SCHEMA = "ix71.operating-matrix.1"
REPORT_SCHEMA = "ix71.operating-matrix-report.1"

#: Planner reasons mapped to the matrix vocabulary.
PLANNER_REASON = {
    FeasibilityReason.BLUR: "blur_ratio_exceeds_declared_max",
    FeasibilityReason.GAP: "interframe_gap_exceeds_declared_max",
    FeasibilityReason.TOO_FEW_OBSERVATIONS: "observations_below_declared_min",
    FeasibilityReason.DUTY: "duty_outside_declared_range",
}

#: Metrics this matrix cannot compute yet, and why. Kept in the document so a
#: consumer cannot read the predicted rows as a full predicted-versus-observed set.
NOT_COMPUTED = (
    {
        "metric": "valid_area",
        "reason": "needs registered support from an acquired run, not a declared point",
    },
    {
        "metric": "local_support_duration",
        "reason": (
            "needs a recorded run; the row records residence_s for the declared "
            "width only"
        ),
    },
    {
        "metric": "psf_blur",
        "reason": (
            "no measured point-spread function; optics.resolution_um is declared "
            "as a proxy"
        ),
    },
    {
        "metric": "acquisition_overhead",
        "reason": "needs a recorded run with per-frame timing (Q02/Q04)",
    },
)


class MatrixSpecError(ValueError):
    """The operating-matrix specification is missing or inconsistent."""


def _number(value: Any, name: str, *, positive: bool) -> float:
    """Return a finite number, rejecting bools and out-of-range values."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MatrixSpecError(f"{name} must be a number")
    number = float(value)
    if not number == number or number in (float("inf"), float("-inf")):
        raise MatrixSpecError(f"{name} must be finite")
    if positive and number <= 0:
        raise MatrixSpecError(f"{name} must be positive")
    if not positive and number < 0:
        raise MatrixSpecError(f"{name} must be nonnegative")
    return number


def _integer(value: Any, name: str, *, minimum: int) -> int:
    """Return an integer at or above a minimum, rejecting bools and floats."""
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise MatrixSpecError(f"{name} must be an integer >= {minimum}")
    return value


def _mapping(value: Any, name: str) -> dict[str, Any]:
    """Return a required mapping."""
    if not isinstance(value, dict):
        raise MatrixSpecError(f"{name} must be an object")
    return value


def _positive_list(value: Any, name: str) -> tuple[float, ...]:
    """Return a nonempty tuple of positive numbers, rejecting duplicates."""
    if not isinstance(value, list) or not value:
        raise MatrixSpecError(f"{name} must be a nonempty list")
    numbers = tuple(
        _number(item, f"{name}[{index}]", positive=True)
        for index, item in enumerate(value)
    )
    if len(set(numbers)) != len(numbers):
        raise MatrixSpecError(f"{name} must not repeat a value")
    return numbers


def validate_spec(document: Any) -> dict[str, Any]:
    """Validate one matrix specification and return it with parsed axes.

    The specification is data, so it stays a plain mapping; parsing here keeps
    every bound and axis finite before a row is computed.
    """
    spec = _mapping(document, "specification")
    if spec.get("schema") != MATRIX_SCHEMA:
        raise MatrixSpecError(f"schema must be {MATRIX_SCHEMA!r}")
    matrix_id = spec.get("matrix_id")
    if not isinstance(matrix_id, str) or not matrix_id.strip():
        raise MatrixSpecError("matrix_id is required")
    camera = _mapping(spec.get("camera"), "camera")
    optics = _mapping(spec.get("optics"), "optics")
    limits = _mapping(spec.get("limits"), "limits")
    parsed: dict[str, Any] = {
        "schema": MATRIX_SCHEMA,
        "matrix_id": matrix_id,
        "description": spec.get("description"),
        "camera": {
            "sensor_width_px": _integer(
                camera.get("sensor_width_px"), "camera.sensor_width_px", minimum=1
            ),
            "sensor_height_px": _integer(
                camera.get("sensor_height_px"), "camera.sensor_height_px", minimum=1
            ),
            "pixel_size_um": _number(
                camera.get("pixel_size_um"), "camera.pixel_size_um", positive=True
            ),
            "binning": _integer(camera.get("binning", 1), "camera.binning", minimum=1),
            "source": camera.get("source"),
        },
        "optics": {
            "resolution_um": _number(
                optics.get("resolution_um"), "optics.resolution_um", positive=True
            ),
            "resolution_basis": optics.get("resolution_basis") or "unspecified",
            "source": optics.get("source"),
        },
        "frame_period_s": _number(
            spec.get("frame_period_s"), "frame_period_s", positive=True
        ),
        "strip_length_um": _number(
            spec.get("strip_length_um"), "strip_length_um", positive=True
        ),
        "illumination_footprint_um": (
            None
            if spec.get("illumination_footprint_um") is None
            else _number(
                spec.get("illumination_footprint_um"),
                "illumination_footprint_um",
                positive=True,
            )
        ),
        "speeds_um_s": _positive_list(spec.get("speeds_um_s"), "speeds_um_s"),
        "exposures_ms": _positive_list(spec.get("exposures_ms"), "exposures_ms"),
        "virtual_slit_widths_um": _positive_list(
            spec.get("virtual_slit_widths_um"), "virtual_slit_widths_um"
        ),
        "hardware_roi_widths_px": tuple(
            _integer(item, f"hardware_roi_widths_px[{index}]", minimum=1)
            for index, item in enumerate(spec.get("hardware_roi_widths_px") or [])
        ),
        "limits": {
            "max_stage_speed_um_s": _number(
                limits.get("max_stage_speed_um_s"),
                "limits.max_stage_speed_um_s",
                positive=True,
            ),
            "min_frame_period_s": (
                None
                if limits.get("min_frame_period_s") is None
                else _number(
                    limits.get("min_frame_period_s"),
                    "limits.min_frame_period_s",
                    positive=True,
                )
            ),
            "max_blur_ratio": _number(
                limits.get("max_blur_ratio"), "limits.max_blur_ratio", positive=True
            ),
            "max_gamma": _number(
                limits.get("max_gamma"), "limits.max_gamma", positive=True
            ),
            "min_observations": (
                None
                if limits.get("min_observations") is None
                else _number(
                    limits.get("min_observations"),
                    "limits.min_observations",
                    positive=True,
                )
            ),
            "max_duty": (
                None
                if limits.get("max_duty") is None
                else _number(limits.get("max_duty"), "limits.max_duty", positive=False)
            ),
            "provisional": bool(limits.get("provisional", False)),
            "sources": limits.get("sources")
            if isinstance(limits.get("sources"), dict)
            else {},
        },
    }
    if not parsed["hardware_roi_widths_px"] and not parsed["virtual_slit_widths_um"]:
        raise MatrixSpecError("at least one detector width is required")
    if parsed["limits"]["max_duty"] is not None and parsed["limits"]["max_duty"] > 1:
        raise MatrixSpecError("limits.max_duty must be in [0, 1]")
    return parsed


def load_spec(path: Path) -> dict[str, Any]:
    """Read and validate one specification file."""
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise MatrixSpecError(f"specification not found: {path}") from error
    except json.JSONDecodeError as error:
        raise MatrixSpecError(f"specification is not JSON: {error}") from error
    return validate_spec(document)


def _field_extent_um(spec: dict[str, Any]) -> tuple[float, float]:
    """Return the delivered field width and height in specimen micrometres."""
    camera = spec["camera"]
    pixel = camera["pixel_size_um"] * camera["binning"]
    return camera["sensor_width_px"] * pixel, camera["sensor_height_px"] * pixel


def _binding_reasons(
    spec: dict[str, Any],
    *,
    mode: str,
    speed_um_s: float,
    exposure_s: float,
    width_um: float,
    width_px: int | None,
) -> list[str]:
    """Return refusals that depend on the binding, not on the planner metrics."""
    reasons: list[str] = []
    limits = spec["limits"]
    field_width, _ = _field_extent_um(spec)
    if exposure_s >= spec["frame_period_s"]:
        reasons.append("exposure_not_below_frame_period")
    if speed_um_s > limits["max_stage_speed_um_s"]:
        reasons.append("speed_exceeds_declared_max")
    if width_um > field_width + 1e-9:
        reasons.append("width_exceeds_sensor_field")
    footprint = spec["illumination_footprint_um"]
    if footprint is not None and width_um > footprint + 1e-9:
        reasons.append("width_exceeds_illumination_footprint")
    if mode == "hardware_roi":
        if width_px is None:
            reasons.append("roi_width_missing")
        else:
            binning = spec["camera"]["binning"]
            if width_px % binning != 0:
                reasons.append("roi_width_not_pixel_multiple")
            if width_px > spec["camera"]["sensor_width_px"]:
                reasons.append("hardware_roi_exceeds_sensor")
    return reasons


def _row(
    spec: dict[str, Any],
    *,
    mode: str,
    speed_um_s: float,
    exposure_ms: float,
    width_um: float,
    width_px: int | None,
) -> dict[str, Any]:
    """Compute one operating point and record every refusal with its reason."""
    exposure_s = exposure_ms / 1000.0
    reasons = _binding_reasons(
        spec,
        mode=mode,
        speed_um_s=speed_um_s,
        exposure_s=exposure_s,
        width_um=width_um,
        width_px=width_px,
    )
    field_width, field_height = _field_extent_um(spec)
    limits = MeasurementLimits(
        max_blur_ratio=spec["limits"]["max_blur_ratio"],
        max_gamma=spec["limits"]["max_gamma"],
        min_observations=spec["limits"]["min_observations"],
        max_duty=spec["limits"]["max_duty"],
    )
    metrics = None
    planner_reasons: list[str] = []
    if "exposure_not_below_frame_period" not in reasons:
        point = AcquisitionPoint(
            velocity_um_s=speed_um_s,
            exposure_s=exposure_s,
            width_um=width_um,
            frame_period_s=spec["frame_period_s"],
            pixel_size_um=spec["camera"]["pixel_size_um"] * spec["camera"]["binning"],
            resolution_um=spec["optics"]["resolution_um"],
            height_um=field_height,
        )
        verdict = assess_measurement(point, limits)
        metrics = verdict.metrics.to_dict()
        planner_reasons = [PLANNER_REASON[reason] for reason in verdict.reasons]
        reasons.extend(planner_reasons)
    step_um = speed_um_s * spec["frame_period_s"]
    retained_frames = (
        int(spec["strip_length_um"] // step_um) + 1 if step_um > 0 else None
    )
    warnings: list[str] = []
    if spec["optics"]["resolution_basis"] != "measured_psf":
        warnings.append("psf_blur_is_a_proxy")
    if spec["frame_period_s"] < (spec["limits"]["min_frame_period_s"] or 0):
        warnings.append("frame_period_below_declared_camera_floor")
    return {
        "detector_mode": mode,
        "speed_um_s": speed_um_s,
        "exposure_ms": exposure_ms,
        "exposure_s": exposure_s,
        "frame_period_s": spec["frame_period_s"],
        "width_um": width_um,
        "width_px": width_px,
        "width_fraction_of_field": width_um / field_width,
        "step_um": step_um,
        "retained_frames_per_strip": retained_frames,
        "metrics": metrics,
        "feasible": not reasons,
        "reasons": sorted(set(reasons)),
        "warnings": warnings,
    }


def build_matrix(spec: dict[str, Any]) -> dict[str, Any]:
    """Build the full matrix document from a validated specification."""
    rows: list[dict[str, Any]] = []
    for mode, widths in (
        ("virtual_slit", [(width, None) for width in spec["virtual_slit_widths_um"]]),
        (
            "hardware_roi",
            [
                (
                    px * spec["camera"]["pixel_size_um"] * spec["camera"]["binning"],
                    px,
                )
                for px in spec["hardware_roi_widths_px"]
            ],
        ),
    ):
        for speed in spec["speeds_um_s"]:
            for exposure_ms in spec["exposures_ms"]:
                for width_um, width_px in widths:
                    rows.append(
                        _row(
                            spec,
                            mode=mode,
                            speed_um_s=speed,
                            exposure_ms=exposure_ms,
                            width_um=width_um,
                            width_px=width_px,
                        )
                    )
    reason_counts: dict[str, int] = {}
    for row in rows:
        for reason in row["reasons"]:
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
    findings: list[dict[str, Any]] = []
    if spec["limits"]["provisional"]:
        findings.append(
            {
                "code": "limits_provisional",
                "detail": (
                    "the feasibility limits are design placeholders; the matrix does "
                    "not establish measurement acceptance"
                ),
            }
        )
    if spec["optics"]["resolution_basis"] != "measured_psf":
        findings.append(
            {
                "code": "psf_unmeasured",
                "detail": (
                    "optics.resolution_um is a declared proxy, so blur_ratio compares "
                    "motion blur with that proxy, not with a measured PSF"
                ),
            }
        )
    if spec["illumination_footprint_um"] is None:
        findings.append(
            {
                "code": "illumination_footprint_undeclared",
                "detail": (
                    "no illumination footprint is declared, so width is bounded only "
                    "by the sensor field"
                ),
            }
        )
    if not spec["limits"]["sources"]:
        findings.append(
            {
                "code": "limit_sources_missing",
                "detail": "no limit names the record or profile it came from",
            }
        )
    by_mode: dict[str, dict[str, int]] = {}
    for row in rows:
        entry = by_mode.setdefault(row["detector_mode"], {"rows": 0, "feasible": 0})
        entry["rows"] += 1
        entry["feasible"] += int(row["feasible"])
    return {
        "schema": REPORT_SCHEMA,
        "matrix_id": spec["matrix_id"],
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "specification_schema": MATRIX_SCHEMA,
        "instrument": {
            "camera": dict(spec["camera"]),
            "optics": dict(spec["optics"]),
            "frame_period_s": spec["frame_period_s"],
            "illumination_footprint_um": spec["illumination_footprint_um"],
            "field_extent_um": list(_field_extent_um(spec)),
        },
        "limits": dict(spec["limits"]),
        "rows": rows,
        "summary": {
            "rows_total": len(rows),
            "feasible": sum(1 for row in rows if row["feasible"]),
            "infeasible": sum(1 for row in rows if not row["feasible"]),
            "by_mode": by_mode,
            "reason_counts": dict(sorted(reason_counts.items())),
        },
        "not_computed": [
            item
            for item in NOT_COMPUTED
            if not (
                item["metric"] == "psf_blur"
                and spec["optics"]["resolution_basis"] == "measured_psf"
            )
        ],
        "findings": findings,
        "accepted": False,
    }


OBSERVED_SCHEMA = "ix71.operating-matrix-observed.1"

#: Predictions the recorded runs used here cannot check, with the reason.
NOT_COMPARABLE = (
    {
        "metric": "valid_area",
        "reason": "no registered support exists for this run",
    },
    {
        "metric": "local_support_duration",
        "reason": "no per-location observation map exists for this run",
    },
    {
        "metric": "psf_blur",
        "reason": "no measured point-spread function exists",
    },
)

#: The recorded runs command speed in the stage service's own unit. The matrix
#: speed axis is a request in the same unit, so a ratio below measures agreement
#: inside that convention, not a physical speed.
SPEED_CONVENTION_GUARD = (
    "the recorded route commands speed in the stage service's own unit; the "
    "matrix speed axis is a request in the same unit. A frame-count or step ratio "
    "measures agreement inside that convention and does not establish physical "
    "speed, which remains the open unit-scaling item on this instrument"
)


def _matching_row(
    document: dict[str, Any],
    *,
    commanded_speed_um_s: float,
    exposure_ms: float,
    width_um: float,
) -> dict[str, Any]:
    """Return the declared row a recorded run claims to have executed.

    Matching is exact on mode, speed and exposure and within a micrometre on
    width. A near miss is refused rather than interpolated, because a comparison
    against an invented point would not describe the run.
    """
    for row in document.get("rows") or []:
        if row.get("detector_mode") != "virtual_slit":
            continue
        if abs(float(row["speed_um_s"]) - commanded_speed_um_s) > 1e-9:
            continue
        if abs(float(row["exposure_ms"]) - exposure_ms) > 1e-9:
            continue
        if abs(float(row["width_um"]) - width_um) > 1e-6:
            continue
        return row
    raise MatrixSpecError(
        "no declared row matches "
        f"virtual_slit {commanded_speed_um_s} um/s, {exposure_ms} ms, {width_um} um"
    )


def compare_observed(
    document: dict[str, Any],
    run_dir: Path,
    *,
    commanded_speed_um_s: float,
    exposure_ms: float,
    width_um: float,
) -> dict[str, Any]:
    """Compare one declared row with a recorded run's frame accounting.

    Only quantities the recording actually contains are compared: captured frame
    count, frame interval, the implied step along the strip and the residual span
    after the measured intervals. Valid area, local support and PSF blur are
    listed as not comparable instead of being approximated.
    """
    row = _matching_row(
        document,
        commanded_speed_um_s=commanded_speed_um_s,
        exposure_ms=exposure_ms,
        width_um=width_um,
    )
    run_dir = Path(run_dir)
    reports = sorted(run_dir.glob("*-report.json"))
    if len(reports) != 1:
        raise MatrixSpecError(
            f"expected one *-report.json under {run_dir}, found {len(reports)}"
        )
    report = json.loads(reports[0].read_text(encoding="utf-8"))
    confirmation_id = str(report.get("confirmation_id") or "")
    strips = sorted(run_dir.glob(f"strips/*-{confirmation_id}-strips.json"))
    if len(strips) != 1:
        raise MatrixSpecError(
            f"expected one strip record for {confirmation_id!r} under {run_dir}"
        )
    strip_document = json.loads(strips[0].read_text(encoding="utf-8"))

    comparisons = []
    for strip in strip_document.get("strips") or []:
        captured = strip.get("captured_count")
        span = strip.get("frame_span_s")
        interval = strip.get("frame_interval_s")
        median_interval = (
            interval.get("median") if isinstance(interval, dict) else interval
        )
        length = strip.get("strip_length_um")
        implied = strip.get("implied_traverse_speed_um_s")
        predicted_frames = row["retained_frames_per_strip"]
        observed_step = (
            float(length) / (int(captured) - 1)
            if length is not None and captured and int(captured) > 1
            else None
        )
        predicted_step = row["step_um"]
        overhead = (
            float(span) - (int(captured) - 1) * float(median_interval)
            if span is not None and captured and median_interval is not None
            else None
        )
        comparisons.append(
            {
                "row": strip.get("row"),
                "captured_count": captured,
                "frame_span_s": span,
                "median_frame_interval_s": median_interval,
                "strip_length_um": length,
                "record_implied_speed_um_s": implied,
                "predicted_frames": predicted_frames,
                "frame_delta": (
                    None
                    if captured is None or predicted_frames is None
                    else int(captured) - int(predicted_frames)
                ),
                "predicted_step_um": predicted_step,
                "observed_step_um": (
                    None if observed_step is None else round(observed_step, 4)
                ),
                "step_ratio": (
                    None
                    if observed_step is None or not predicted_step
                    else round(observed_step / predicted_step, 4)
                ),
                "interval_delta_s": (
                    None
                    if median_interval is None
                    else round(float(median_interval) - row["frame_period_s"], 6)
                ),
                "observed_overhead_s": None if overhead is None else round(overhead, 4),
            }
        )
    if not comparisons:
        raise MatrixSpecError(f"the strip record for {confirmation_id!r} has no strips")

    ratios = [
        item["step_ratio"] for item in comparisons if item["step_ratio"] is not None
    ]
    deltas = [
        item["interval_delta_s"]
        for item in comparisons
        if item["interval_delta_s"] is not None
    ]
    return {
        "schema": OBSERVED_SCHEMA,
        "matrix_id": document.get("matrix_id"),
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "run": {
            "run_dir": str(run_dir),
            "confirmation_id": confirmation_id,
            "report": str(reports[0]),
            "strip_record": str(strips[0]),
            "setpoint_mw": report.get("setpoint_mw"),
            "declared_maximum_frame_period_s": report.get("maximum_frame_period_s"),
        },
        "declared_point": {
            "detector_mode": row["detector_mode"],
            "speed_um_s": row["speed_um_s"],
            "exposure_ms": row["exposure_ms"],
            "width_um": row["width_um"],
            "frame_period_s": row["frame_period_s"],
            "step_um": row["step_um"],
            "retained_frames_per_strip": row["retained_frames_per_strip"],
        },
        "strips": comparisons,
        "summary": {
            "strips": len(comparisons),
            "predicted_frames_per_strip": row["retained_frames_per_strip"],
            "observed_frames": [item["captured_count"] for item in comparisons],
            "step_ratio_median": round(median(ratios), 4) if ratios else None,
            "interval_delta_median_s": round(median(deltas), 6) if deltas else None,
        },
        "not_comparable": list(NOT_COMPARABLE),
        "guard": SPEED_CONVENTION_GUARD,
        "accepted": False,
    }


def main(argv: list[str] | None = None) -> int:
    """Build a matrix from a specification file and write the report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--spec", type=Path, required=True, help="matrix specification JSON"
    )
    parser.add_argument("--out", type=Path, required=True, help="output report JSON")
    parser.add_argument(
        "--examples", type=int, default=0, help="print this many feasible rows"
    )
    parser.add_argument(
        "--run", type=Path, help="recorded run directory to compare against"
    )
    parser.add_argument(
        "--commanded-speed-um-s",
        type=float,
        help="speed the run's route requested, in the service's own unit",
    )
    parser.add_argument("--exposure-ms", type=float, help="the run's exposure")
    parser.add_argument("--width-um", type=float, help="the run's detector width")
    parser.add_argument(
        "--observed-out", type=Path, help="write the observed comparison here"
    )
    args = parser.parse_args(argv)
    try:
        spec = load_spec(args.spec)
    except MatrixSpecError as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2
    document = build_matrix(spec)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(document, indent=1) + "\n", encoding="utf-8")
    summary = document["summary"]
    print(
        f"{document['matrix_id']}: {summary['rows_total']} rows, "
        f"{summary['feasible']} feasible, {summary['infeasible']} infeasible"
    )
    for reason, count in summary["reason_counts"].items():
        print(f"  {count:>3}  {reason}")
    if args.examples:
        shown = 0
        for row in document["rows"]:
            if row["feasible"] and shown < args.examples:
                print(
                    f"  example: {row['detector_mode']} {row['speed_um_s']} um/s, "
                    f"{row['exposure_ms']} ms, {row['width_um']:.2f} um, "
                    f"{row['retained_frames_per_strip']} frames"
                )
                shown += 1
    if args.run is not None:
        if (
            args.commanded_speed_um_s is None
            or args.exposure_ms is None
            or args.width_um is None
        ):
            parser.error(
                "--run needs --commanded-speed-um-s, --exposure-ms and --width-um"
            )
            return 2
        try:
            observed = compare_observed(
                document,
                args.run,
                commanded_speed_um_s=args.commanded_speed_um_s,
                exposure_ms=args.exposure_ms,
                width_um=args.width_um,
            )
        except MatrixSpecError as error:
            print(f"refused: {error}", file=sys.stderr)
            return 2
        observed_out = args.observed_out or args.out.with_suffix(".observed.json")
        observed_out.write_text(json.dumps(observed, indent=1) + "\n", encoding="utf-8")
        print(
            f"observed {observed['run']['confirmation_id']}: "
            f"{observed['summary']['observed_frames']} frames against "
            f"{observed['summary']['predicted_frames_per_strip']} predicted; "
            f"step ratio {observed['summary']['step_ratio_median']}; "
            f"interval delta {observed['summary']['interval_delta_median_s']} s"
        )
    return 0 if summary["feasible"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
