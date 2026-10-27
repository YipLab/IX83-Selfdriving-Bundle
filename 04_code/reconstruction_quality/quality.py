"""Replay a recorded snap registration for reconstruction-quality figures (Q06).

Q06 asks for replayable analysis over recorded inputs: registration residuals,
closure/reversal repeatability, seams, valid support and uncertainty, while
keeping image-derived placement distinct from independent stage or reticle truth.
Bead PSF widths need bead data that this instrument has not recorded.

This tool reads a saved pairwise registration record and its mosaic report and
recomputes the consistency figures from the recorded pairs and the coverage
array. It does not re-register, re-stitch or read the mosaic image, and it lists
the endpoints it cannot measure instead of approximating them.

    python quality.py --record <calibrated_record.json> \\
        --mosaic-report <registered_snap_mosaic_report.json> --out quality.json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

SCHEMA = "ix71.reconstruction-quality.1"
RECORD_SCHEMA = "redsun-searching-imaging.snap-pairwise-registration-v1"

NOT_MEASURED = (
    {
        "metric": "bead_psf_width",
        "reason": "no bead or point-source recording exists for this camera mode",
    },
    {
        "metric": "independent_placement_error",
        "reason": (
            "no stage-referenced truth or reticle sample is paired with these frames"
        ),
    },
    {
        "metric": "seam_intensity_step",
        "reason": (
            "not computed here; the seam is a blending property of the mosaic image"
        ),
    },
)


class QualityError(ValueError):
    """The record cannot support the analysis it was asked for."""


def _percentile(values: list[float], fraction: float) -> float | None:
    """Return a nearest-rank percentile of a nonempty list."""
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(fraction * (len(ordered) - 1)))))
    return round(ordered[index], 6)


def _magnitudes(vectors: list[Any]) -> list[float]:
    """Return the Euclidean magnitude of each finite pair."""
    values = []
    for vector in vectors:
        if (
            isinstance(vector, (list, tuple))
            and len(vector) == 2
            and all(
                isinstance(item, (int, float)) and math.isfinite(item)
                for item in vector
            )
        ):
            values.append(math.hypot(float(vector[0]), float(vector[1])))
    return values


def _stats(values: list[float]) -> dict[str, float | None]:
    """Return count, median, p95 and maximum for a list of magnitudes."""
    if not values:
        return {"count": 0, "median": None, "p95": None, "max": None}
    return {
        "count": len(values),
        "median": round(median(values), 6),
        "p95": _percentile(values, 0.95),
        "max": round(max(values), 6),
        "rms": round(
            math.sqrt(sum(value * value for value in values) / len(values)), 6
        ),
    }


def _coverage(
    mosaic_report: dict[str, Any], report_path: Path
) -> dict[str, Any] | None:
    """Read the coverage array named by the mosaic report, if it exists."""
    name = mosaic_report.get("coverage_file")
    if not isinstance(name, str) or not name:
        return None
    path = report_path.parent / Path(name).name
    if not path.is_file():
        path = Path(name)
    if not path.is_file():
        return None
    try:
        import numpy as np
        import tifffile
    except ImportError:  # pragma: no cover - the app venv has both
        return None
    array = np.asarray(tifffile.imread(path))
    if array.size == 0:
        return None
    total = float(array.size)
    return {
        "file": path.name,
        "pixels": int(array.size),
        "max_tiles_per_pixel": int(array.max()),
        "fraction_at_least_1": round(float((array >= 1).sum()) / total, 6),
        "fraction_at_least_2": round(float((array >= 2).sum()) / total, 6),
        "fraction_at_least_3": round(float((array >= 3).sum()) / total, 6),
    }


def analyze(
    record_path: Path,
    *,
    mosaic_report_path: Path | None = None,
    max_edge_rms_px: float = 0.5,
) -> dict[str, Any]:
    """Recompute the recorded registration's consistency figures."""
    record_path = Path(record_path)
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise QualityError(f"record not found: {record_path}") from error
    except json.JSONDecodeError as error:
        raise QualityError(f"record is not JSON: {error}") from error
    if not isinstance(record, dict):
        raise QualityError("record must be an object")
    if record.get("schema") != RECORD_SCHEMA:
        raise QualityError(f"record schema must be {RECORD_SCHEMA!r}")
    pairs = record.get("pairs")
    if not isinstance(pairs, list) or not pairs:
        raise QualityError("record has no pairs")

    findings: list[dict[str, Any]] = []
    if record.get("registration_performed") is not True:
        findings.append(
            {
                "code": "registration_not_performed",
                "severity": "blocking",
                "detail": (
                    "registration_performed is "
                    f"{record.get('registration_performed')!r}"
                ),
            }
        )
    passed = [pair for pair in pairs if pair.get("fit_status") == "passed"]
    failed = [pair for pair in pairs if pair.get("fit_status") != "passed"]
    residuals = _magnitudes(
        [pair.get("placement_graph_residual_xy_px") for pair in passed]
    )
    prior_gaps = _magnitudes(
        [pair.get("registration_minus_stage_prior_xy_px") for pair in passed]
    )
    correlations = [
        float(pair["correlation"])
        for pair in passed
        if isinstance(pair.get("correlation"), (int, float))
        and math.isfinite(pair["correlation"])
    ]
    overlaps = [
        float(pair["image_overlap_fraction"])
        for pair in passed
        if isinstance(pair.get("image_overlap_fraction"), (int, float))
        and math.isfinite(pair["image_overlap_fraction"])
    ]
    residual_stats = _stats(residuals)
    if failed:
        findings.append(
            {
                "code": "pair_failures",
                "severity": "warning",
                "detail": f"{len(failed)} of {len(pairs)} pairs failed their gate",
            }
        )
    if residual_stats["rms"] is not None and residual_stats["rms"] > max_edge_rms_px:
        findings.append(
            {
                "code": "edge_rms_over_gate",
                "severity": "blocking",
                "detail": (
                    f"recomputed edge RMS {residual_stats['rms']} px over the "
                    f"{max_edge_rms_px} px gate"
                ),
            }
        )

    placements = record.get("frame_placements") or []
    components = {
        placement.get("graph_component")
        for placement in placements
        if isinstance(placement, dict)
    }
    components.discard(None)
    if record.get("connected_registration_graph") is not True or len(components) > 1:
        findings.append(
            {
                "code": "disconnected_graph",
                "severity": "blocking",
                "detail": (
                    f"connected_registration_graph is "
                    f"{record.get('connected_registration_graph')!r} with "
                    f"{len(components)} component(s)"
                ),
            }
        )

    mosaic: dict[str, Any] | None = None
    coverage: dict[str, Any] | None = None
    if mosaic_report_path is not None:
        report_path = Path(mosaic_report_path)
        try:
            mosaic = json.loads(report_path.read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            raise QualityError(f"mosaic report not found: {report_path}") from error
        if not isinstance(mosaic, dict):
            raise QualityError("mosaic report must be an object")
        summary = mosaic.get("edge_residual_summary_px") or {}
        reported = summary.get("rms")
        if isinstance(reported, (int, float)) and residual_stats["rms"] is not None:
            if abs(float(reported) - residual_stats["rms"]) > 1e-6:
                findings.append(
                    {
                        "code": "edge_rms_disagrees",
                        "severity": "warning",
                        "detail": (
                            f"mosaic report says {reported} px, recomputed "
                            f"{residual_stats['rms']} px"
                        ),
                    }
                )
        coverage = _coverage(mosaic, report_path)
        if coverage is None:
            findings.append(
                {
                    "code": "coverage_missing",
                    "severity": "warning",
                    "detail": (
                        "the coverage array named by the mosaic report is unavailable"
                    ),
                }
            )
        else:
            expected = mosaic.get("coverage_max_tiles_per_pixel")
            if (
                expected is not None
                and int(expected) != coverage["max_tiles_per_pixel"]
            ):
                findings.append(
                    {
                        "code": "coverage_disagrees",
                        "severity": "warning",
                        "detail": (
                            f"report says {expected} tiles per pixel, array says "
                            f"{coverage['max_tiles_per_pixel']}"
                        ),
                    }
                )

    findings.append(
        {
            "code": "psf_not_measurable",
            "severity": "info",
            "detail": (
                "no bead recording; widths and independent truth are not computed"
            ),
        }
    )
    blocking = [
        finding["code"] for finding in findings if finding["severity"] == "blocking"
    ]
    return {
        "schema": SCHEMA,
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": {
            "record": str(record_path),
            "registration_id": record.get("registration_id"),
            "mosaic_report": None
            if mosaic_report_path is None
            else str(mosaic_report_path),
            "calibration_id": record.get("calibration_id"),
            "frames": len(placements) or record.get("source_frame_count"),
        },
        "pairs": {
            "total": len(pairs),
            "passed": len(passed),
            "failed": len(failed),
            "pass_fraction": round(len(passed) / len(pairs), 6),
            "placement_residual_px": residual_stats,
            "registration_minus_stage_prior_px": _stats(prior_gaps),
            "correlation": {
                "count": len(correlations),
                "median": _percentile(correlations, 0.5),
                "min": round(min(correlations), 6) if correlations else None,
            },
            "overlap_fraction": {
                "count": len(overlaps),
                "median": _percentile(overlaps, 0.5),
                "min": round(min(overlaps), 6) if overlaps else None,
            },
        },
        "graph": {
            "connected": record.get("connected_registration_graph"),
            "components": len(components),
            "frames_placed": len(placements),
        },
        "coverage": coverage,
        "mosaic": (
            None
            if mosaic is None
            else {
                "shape_yx": mosaic.get("mosaic_shape_yx"),
                "canvas_pixel_count": mosaic.get("canvas_pixel_count"),
                "edge_residual_summary_px": mosaic.get("edge_residual_summary_px"),
            }
        ),
        "gate": {"max_edge_rms_px": max_edge_rms_px},
        "not_measured": list(NOT_MEASURED),
        "findings": findings,
        "blocking": blocking,
        "accepted": False,
        "notes": [
            "residuals are image-derived pairwise placement consistency, not "
            "independent stage or reticle accuracy",
            "coverage is the fraction of the mosaic canvas with at least one, two "
            "or three contributing tiles",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    """Analyze one recorded registration and write the quality report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", type=Path, required=True)
    parser.add_argument("--mosaic-report", type=Path)
    parser.add_argument("--max-edge-rms-px", type=float, default=0.5)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = analyze(
            args.record,
            mosaic_report_path=args.mosaic_report,
            max_edge_rms_px=args.max_edge_rms_px,
        )
    except QualityError as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    pairs = report["pairs"]
    residuals = pairs["placement_residual_px"]
    prior = pairs["registration_minus_stage_prior_px"]
    coverage = report["coverage"]
    print(
        f"{report['source']['registration_id'][:12]}: "
        f"{pairs['passed']}/{pairs['total']} pairs, "
        f"edge RMS {residuals['rms']} px, "
        f"prior gap median {prior['median']} px, "
        f"coverage>=1 {None if coverage is None else coverage['fraction_at_least_1']}"
    )
    for finding in report["findings"]:
        print(f"  {finding['severity']:<8} {finding['code']}: {finding['detail']}")
    return 0 if not report["blocking"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
