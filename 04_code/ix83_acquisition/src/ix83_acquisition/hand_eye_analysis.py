"""Backend-independent analysis of recorded stage-to-camera calibration runs.

The planner consumes Bluesky-shaped documents and ordered image planes. It
does not persist files, subscribe to a RunEngine, or bind hardware devices.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict
from typing import Any

import numpy as np
from numpy.typing import NDArray
from planner.hand_eye import (
    CAPTURE_LABELS,
    HandEyeClosure,
    HandEyePair,
    evaluate_hand_eye_quality,
    fit_hand_eye,
)

from .registration import estimate_feature_translation, estimate_translation


def _jsonable(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        raise TypeError("raw arrays must be persisted as separate binary frame files")
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    raise TypeError(f"unsupported run-document value: {type(value).__name__}")


def _position(event: Mapping[str, Any]) -> tuple[float, float]:
    data = event["data"]
    try:
        position = data["stage_position_xy"]
        if len(position) != 2:
            raise ValueError("position is not an XY pair")
        return float(position[0]), float(position[1])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("calibration event lacks pre-snap XY readbacks") from exc


def _registration_planes(
    start_doc: Mapping[str, Any],
    planes: Sequence[NDArray[np.generic]],
) -> tuple[list[NDArray[np.float32]], dict[str, Any]]:
    """Apply the recorded crop and optional deterministic ECC preprocessing."""
    config = start_doc.get("planner_hand_eye_registration", {})
    if not isinstance(config, Mapping):
        raise ValueError("planner_hand_eye_registration must be a mapping")
    roi = config.get("roi_yxhw_px")
    preprocessing = config.get("preprocessing", "none")
    if roi is not None:
        if (
            not isinstance(roi, (tuple, list))
            or len(roi) != 4
            or any(isinstance(v, bool) or not isinstance(v, int) for v in roi)
            or roi[0] < 0
            or roi[1] < 0
            or roi[2] < 16
            or roi[3] < 16
        ):
            raise ValueError("registration ROI must be nonnegative YXHW with H,W >= 16")
        y, x, height, width = roi
    else:
        y = x = 0
        height = width = None
    if preprocessing not in {"none", "percentile_clahe"}:
        raise ValueError("unsupported hand-eye registration preprocessing")
    cv2 = None
    if preprocessing == "percentile_clahe":
        try:
            import cv2 as cv2_module
        except ImportError as exc:
            raise RuntimeError("percentile_clahe preprocessing requires OpenCV") from exc
        cv2 = cv2_module
    processed: list[NDArray[np.float32]] = []
    for index, source in enumerate(planes):
        image = np.asarray(source)
        if roi is not None:
            if y + height > image.shape[0] or x + width > image.shape[1]:
                raise ValueError(
                    f"registration ROI {tuple(roi)} is outside frame {index} shape {image.shape}"
                )
            image = image[y : y + height, x : x + width]
        if preprocessing == "percentile_clahe":
            low, high = np.percentile(image, [1.0, 99.7])
            if not np.isfinite(low) or not np.isfinite(high) or high <= low:
                raise ValueError(f"frame {index} has no usable range for CLAHE preprocessing")
            scaled = np.clip((image.astype(np.float32) - low) * (255.0 / (high - low)), 0, 255)
            image = cv2.createCLAHE(
                clipLimit=2.0,
                tileGridSize=(8, 8),
            ).apply(scaled.astype(np.uint8))
        processed.append(np.asarray(image, dtype=np.float32))
    return processed, {
        "roi_yxhw_px": list(roi) if roi is not None else None,
        "preprocessing": preprocessing,
        "percentile_limits": [1.0, 99.7] if preprocessing == "percentile_clahe" else None,
        "clahe_clip_limit": 2.0 if preprocessing == "percentile_clahe" else None,
        "clahe_tile_grid_yx": [8, 8] if preprocessing == "percentile_clahe" else None,
    }


def analyze_hand_eye_run(
    start_doc: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
    stop_doc: Mapping[str, Any],
    images: Sequence[NDArray[np.generic]],
) -> dict[str, Any]:
    """Validate and fit one successful startup-calibration run.

    Event order must match :data:`CAPTURE_LABELS`; each event's
    ``data.stage_position_xy`` is the measured pre-capture position in
    micrometres. Hosts normalize their backend-specific readback fields to
    this input contract. The result is a
    JSON-compatible evidence report, not an authorization to use the fit.
    The acquisition host applies its own acceptance and persistence policy.
    """
    if start_doc.get("planner_workflow") != "stage-camera-hand-eye-calibration-v1":
        raise ValueError("start document is not a planner hand-eye calibration run")
    if stop_doc.get("exit_status") != "success":
        raise ValueError("only successfully stopped calibration runs can be analyzed")
    labels = tuple(start_doc.get("planner_calibration_capture_labels", ()))
    if labels != CAPTURE_LABELS or len(events) != len(CAPTURE_LABELS) or len(images) != len(events):
        raise ValueError("calibration run is missing or reorders required capture events")
    ordered = list(events)
    if [int(event["seq_num"]) for event in ordered] != list(range(1, len(labels) + 1)):
        raise ValueError("calibration event sequence numbers must be contiguous and one-based")
    planes = [np.asarray(image) for image in images]
    if any(image.ndim != 2 or image.dtype.kind not in "uif" for image in planes):
        raise ValueError("calibration requires numeric 2D camera frames")
    if any(image.shape != planes[0].shape for image in planes):
        raise ValueError("calibration camera frame shapes changed within the run")
    mode_context = start_doc.get("planner_calibration_mode_context")
    if not isinstance(mode_context, Mapping) or not mode_context:
        raise ValueError("start document lacks calibration mode identity")
    coordinate_frame = start_doc.get("planner_coordinate_frame")
    if not isinstance(coordinate_frame, str) or not coordinate_frame:
        raise ValueError("start document lacks coordinate frame")

    planes, registration_config = _registration_planes(start_doc, planes)
    frames = {label: (ordered[index], planes[index]) for index, label in enumerate(labels)}
    anchor_doc, anchor_image = frames["reference"]
    _repeat_doc, repeat_image = frames["reference_repeat"]
    anchor_position = _position(anchor_doc)
    reference = (anchor_image.astype(np.float32) + repeat_image.astype(np.float32)) / 2.0
    pairs: list[HandEyePair] = []
    closures: list[HandEyeClosure] = []
    pair_metrics: list[dict[str, Any]] = []
    closure_metrics: list[dict[str, Any]] = []

    for label in (
        "probe_x_positive",
        "probe_x_negative",
        "probe_y_positive",
        "probe_y_negative",
    ):
        event, image = frames[label]
        x_um, y_um = _position(event)
        stage_delta = (x_um - anchor_position[0], y_um - anchor_position[1])
        ecc = estimate_translation(
            reference,
            image,
            downsample=2,
            min_correlation=0.4,
            min_overlap_fraction=0.8,
        )
        feature = estimate_feature_translation(reference, image)
        pair = HandEyePair(
            pair_id=label,
            stage_delta_xy_um=stage_delta,
            content_motion_xy_px=(-ecc.dx_px, -ecc.dy_px),
            registration_score=ecc.correlation,
            feature_motion_xy_px=feature.content_motion_xy_px,
            ransac_inlier_count=feature.inlier_count,
            ransac_inlier_fraction=feature.inlier_fraction,
            ransac_median_residual_px=feature.median_reprojection_residual_px,
        )
        pairs.append(pair)
        pair_metrics.append(
            {
                **asdict(pair),
                "ecc_placement_xy_px": [ecc.dx_px, ecc.dy_px],
                "feature_candidate_match_count": feature.candidate_match_count,
                "feature_placement_xy_px": feature.placement_xy_px,
            }
        )

    closure_labels = (
        "reference_repeat",
        "return_x_positive",
        "return_x_negative",
        "return_y_positive",
        "return_y_negative",
    )
    for label in closure_labels:
        event, image = frames[label]
        position = _position(event)
        ecc = estimate_translation(
            reference,
            image,
            downsample=2,
            min_correlation=0.4,
            min_overlap_fraction=0.8,
        )
        closure_label = "return_reference_repeat" if label == "reference_repeat" else label
        closure = HandEyeClosure(
            label=closure_label,
            stage_error_xy_um=(
                position[0] - anchor_position[0],
                position[1] - anchor_position[1],
            ),
            image_displacement_xy_px=(-ecc.dx_px, -ecc.dy_px),
        )
        closures.append(closure)
        closure_metrics.append({**asdict(closure), "ecc_score": ecc.correlation})

    quality = evaluate_hand_eye_quality(pairs, closures)
    fit = fit_hand_eye(
        pairs,
        coordinate_frame=coordinate_frame,
        mode_context={str(key): str(value) for key, value in mode_context.items()},
    )
    return {
        "schema_version": 1,
        "analysis_type": "stage-camera-hand-eye-calibration",
        "run_uid": start_doc.get("uid"),
        "status": "passed" if quality.passed else "failed",
        "accepted_for_scan_preflight": quality.passed,
        "mode_context": _jsonable(mode_context),
        "registration": registration_config,
        "coordinate_frame": coordinate_frame,
        "source_frame_ids": {
            label: int(event["data"].get("frame_id", event["seq_num"] - 1))
            for label, (event, _image) in frames.items()
        },
        "fit": asdict(fit),
        "quality": asdict(quality),
        "pairs": pair_metrics,
        "closures": closure_metrics,
    }
