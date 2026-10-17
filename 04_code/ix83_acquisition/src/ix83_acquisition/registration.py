"""Translation registration and stitching for overlapping, fixed-camera images.

The returned transform maps moving-image pixel coordinates into the reference
image's pixel coordinates. This is image registration only; it does not infer
micrometres or a stage-to-camera calibration without known stage readbacks.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise

import cv2
import numpy as np
from numpy.typing import NDArray
from planner.geometry import Calibration

# Identifier for the stage-registration CLI metadata document.
STAGE_REGISTRATION_SCHEMA = "planner-stage-registration-v1"


@dataclass(frozen=True)
class TranslationFit:
    """Translation placing the moving image in reference-image coordinates."""

    dx_px: float
    dy_px: float
    correlation: float
    overlap_fraction: float


@dataclass(frozen=True)
class FeatureTranslationFit:
    """Feature-RANSAC motion at image center, with fit quality diagnostics."""

    content_motion_xy_px: tuple[float, float]
    placement_xy_px: tuple[float, float]
    candidate_match_count: int
    inlier_count: int
    inlier_fraction: float
    median_reprojection_residual_px: float


@dataclass(frozen=True)
class StitchResult:
    """A blended mosaic and the pixel origin of each source image."""

    image: NDArray[np.float32]
    origins_xy_px: tuple[tuple[float, float], ...]
    pairwise_fits: tuple[TranslationFit, ...]


def estimate_feature_translation(
    reference: NDArray[np.generic],
    moving: NDArray[np.generic],
    *,
    max_features: int = 2500,
    ratio_threshold: float = 0.75,
    ransac_reprojection_threshold_px: float = 3.0,
) -> FeatureTranslationFit:
    """Estimate translation by SIFT descriptor matches and affine RANSAC.

    The returned content-motion vector is the displacement of specimen
    features from the reference image to the moving image, evaluated at the
    image center. ``placement_xy_px`` maps the moving image back to the
    reference and therefore has the opposite sign for pure translation.
    Inlier and reprojection metrics are returned for planner quality gates.
    """
    ref = np.asarray(reference)
    mov = np.asarray(moving)
    if ref.ndim != 2 or mov.ndim != 2 or ref.shape != mov.shape:
        raise ValueError("feature registration images must be same-shaped 2D arrays")
    if min(ref.shape) < 32 or not np.isfinite(ref).all() or not np.isfinite(mov).all():
        raise ValueError("feature images must be finite and at least 32x32")
    if max_features < 3 or not 0 < ratio_threshold < 1:
        raise ValueError("invalid SIFT feature or ratio threshold")
    if not np.isfinite(ransac_reprojection_threshold_px) or ransac_reprojection_threshold_px <= 0:
        raise ValueError("RANSAC reprojection threshold must be finite and positive")
    if not hasattr(cv2, "SIFT_create"):
        raise RuntimeError(
            "OpenCV build does not include SIFT; install the planner registration extra"
        )

    def to_uint8(image: NDArray[np.generic]) -> NDArray[np.uint8]:
        values = image.astype(np.float32, copy=False)
        low, high = np.percentile(values, (1.0, 99.8))
        if not np.isfinite(low) or not np.isfinite(high) or high <= low:
            raise ValueError("feature image has insufficient intensity variation")
        scaled = np.clip((values - low) * (255.0 / (high - low)), 0, 255)
        return np.asarray(scaled, dtype=np.uint8)

    detector = cv2.SIFT_create(nfeatures=max_features, contrastThreshold=0.015)
    ref_points, ref_desc = detector.detectAndCompute(to_uint8(ref), None)
    mov_points, mov_desc = detector.detectAndCompute(to_uint8(mov), None)
    if ref_desc is None or mov_desc is None:
        raise ValueError("SIFT found no descriptors in one or both images")
    matches = cv2.BFMatcher(cv2.NORM_L2).knnMatch(mov_desc, ref_desc, k=2)
    good = [
        pair[0]
        for pair in matches
        if len(pair) == 2 and pair[0].distance < ratio_threshold * pair[1].distance
    ]
    if len(good) < 3:
        raise ValueError(f"only {len(good)} SIFT matches; at least three are required")
    source = np.float32([mov_points[match.queryIdx].pt for match in good])
    destination = np.float32([ref_points[match.trainIdx].pt for match in good])
    affine, inlier_mask = cv2.estimateAffinePartial2D(
        source,
        destination,
        method=cv2.RANSAC,
        ransacReprojThreshold=float(ransac_reprojection_threshold_px),
        maxIters=2000,
        confidence=0.995,
        refineIters=10,
    )
    if affine is None or inlier_mask is None:
        raise ValueError("SIFT/RANSAC could not estimate an image transform")
    inliers = inlier_mask.reshape(-1).astype(bool)
    if np.count_nonzero(inliers) < 3:
        raise ValueError("SIFT/RANSAC retained fewer than three inliers")
    affine = np.asarray(affine, dtype=np.float64)
    center = np.asarray([(ref.shape[1] - 1) / 2, (ref.shape[0] - 1) / 2], dtype=np.float64)
    center_h = np.asarray([center[0], center[1], 1.0])
    placement = affine @ center_h - center
    inverse = cv2.invertAffineTransform(affine)
    content = inverse @ center_h - center
    projected = source[inliers] @ affine[:, :2].T + affine[:, 2]
    errors = np.linalg.norm(projected - destination[inliers], axis=1)
    inlier_count = int(np.count_nonzero(inliers))
    return FeatureTranslationFit(
        content_motion_xy_px=(float(content[0]), float(content[1])),
        placement_xy_px=(float(placement[0]), float(placement[1])),
        candidate_match_count=len(good),
        inlier_count=inlier_count,
        inlier_fraction=float(inlier_count / len(good)),
        median_reprojection_residual_px=float(np.median(errors)),
    )


def stage_translation_to_pixel(
    stage_delta_xy_um: tuple[float, float], calibration: Calibration
) -> tuple[float, float]:
    """Convert a stage readback delta to a moving-tile origin estimate in pixels.

    The calibration maps delivered image-pixel offsets to stage micrometres.
    A positive stage move shifts a stationary specimen feature in the opposite
    direction within the moving image, so the mosaic origin uses the inverse
    calibration applied to the positive stage delta.
    """
    delta = np.asarray(stage_delta_xy_um, dtype=np.float64)
    if delta.shape != (2,) or not np.isfinite(delta).all():
        raise ValueError("stage delta must contain two finite micrometre values")
    pixel_to_stage = np.asarray(calibration.pixel_to_stage, dtype=np.float64)
    pixel_to_stage = pixel_to_stage @ np.diag(calibration.binning)
    shift = np.linalg.solve(pixel_to_stage, delta)
    return float(shift[0]), float(shift[1])


def estimate_translation(
    reference: NDArray[np.generic],
    moving: NDArray[np.generic],
    *,
    downsample: int = 2,
    min_correlation: float = 0.2,
    min_overlap_fraction: float = 0.1,
    initial_shift_xy_px: tuple[float, float] | None = None,
    max_prior_deviation_px: float | None = None,
) -> TranslationFit:
    """Estimate a moving-to-reference translation using OpenCV ECC.

    Images must be same-sized 2D grayscale arrays from the same camera mode.
    Fits with inadequate correlation or geometric overlap are rejected. When
    supplied, ``initial_shift_xy_px`` is the stage-derived moving-tile origin;
    ECC refines it instead of estimating a free-running phase-correlation seed.
    Physical acquisition callers should supply this stage prior.
    """
    ref = np.asarray(reference)
    mov = np.asarray(moving)
    if ref.ndim != 2 or mov.ndim != 2 or ref.shape != mov.shape:
        raise ValueError("registration images must be same-shaped 2D arrays")
    if min(ref.shape) < 16 or not np.isfinite(ref).all() or not np.isfinite(mov).all():
        raise ValueError("registration images must be finite and at least 16x16")
    if downsample < 1:
        raise ValueError("downsample must be >= 1")
    if not 0 <= min_overlap_fraction <= 1:
        raise ValueError("min_overlap_fraction must be in [0, 1]")
    if not -1 <= min_correlation <= 1:
        raise ValueError("min_correlation must be in [-1, 1]")
    if initial_shift_xy_px is not None and (
        len(initial_shift_xy_px) != 2 or not np.isfinite(initial_shift_xy_px).all()
    ):
        raise ValueError("initial shift must contain two finite pixel values")
    if max_prior_deviation_px is not None and (
        not np.isfinite(max_prior_deviation_px) or max_prior_deviation_px < 0
    ):
        raise ValueError("maximum prior deviation must be finite and nonnegative")
    if max_prior_deviation_px is not None and initial_shift_xy_px is None:
        raise ValueError("maximum prior deviation requires an initial shift")

    ref_fit = np.asarray(ref, dtype=np.float32)
    mov_fit = np.asarray(mov, dtype=np.float32)
    scale_x = scale_y = 1.0
    if downsample > 1:
        fit_size = (
            max(16, ref.shape[1] // downsample),
            max(16, ref.shape[0] // downsample),
        )
        scale_x, scale_y = ref.shape[1] / fit_size[0], ref.shape[0] / fit_size[1]
        ref_fit = np.asarray(
            cv2.resize(ref_fit, fit_size, interpolation=cv2.INTER_AREA),
            dtype=np.float32,
        )
        mov_fit = np.asarray(
            cv2.resize(mov_fit, fit_size, interpolation=cv2.INTER_AREA),
            dtype=np.float32,
        )

    if initial_shift_xy_px is None:
        # Image-only callers use phase correlation. Acquisition data should pass
        # the stage-derived estimate so low-overlap pairs do not start at zero.
        window = cv2.createHanningWindow((ref_fit.shape[1], ref_fit.shape[0]), cv2.CV_32F)
        (phase_dx, phase_dy), response = cv2.phaseCorrelate(ref_fit, mov_fit, window)
        if not np.isfinite(response) or response < 0.1:
            raise ValueError("phase-correlation response is too weak to seed registration")
        warp = np.asarray([[1, 0, phase_dx], [0, 1, phase_dy]], dtype=np.float32)
    else:
        # ECC takes the inverse sampling map. The stage-derived moving-image
        # origin is therefore negated for its initial warp.
        prior_x, prior_y = initial_shift_xy_px
        warp = np.asarray(
            [[1, 0, -prior_x / scale_x], [0, 1, -prior_y / scale_y]],
            dtype=np.float32,
        )
    criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 2000, 1e-7)
    try:
        _score, fitted_warp = cv2.findTransformECC(
            ref_fit, mov_fit, warp, cv2.MOTION_TRANSLATION, criteria
        )
    except cv2.error as exc:
        raise ValueError(f"ECC registration did not converge: {exc}") from exc

    # OpenCV's ECC warp is the inverse sampling map used by WARP_INVERSE_MAP.
    # Negating its translation gives the moving tile's forward image origin.
    warp = np.asarray(fitted_warp, dtype=np.float32)
    dx, dy = -float(warp[0, 2]) * scale_x, -float(warp[1, 2]) * scale_y
    if initial_shift_xy_px is not None and max_prior_deviation_px is not None:
        deviation = float(np.hypot(dx - initial_shift_xy_px[0], dy - initial_shift_xy_px[1]))
        if deviation > max_prior_deviation_px:
            raise ValueError(
                f"image refinement moved {deviation:.2f}px from the stage prior, "
                f"above the {max_prior_deviation_px:.2f}px limit"
            )
    h, w = ref.shape
    overlap = max(0.0, w - abs(dx)) * max(0.0, h - abs(dy)) / (w * h)
    forward = np.asarray([[1, 0, dx], [0, 1, dy]], dtype=np.float32)
    aligned = cv2.warpAffine(
        mov.astype(np.float32),
        forward,
        (w, h),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
    )
    valid = cv2.warpAffine(
        np.ones((h, w), dtype=np.uint8),
        forward,
        (w, h),
        flags=cv2.INTER_NEAREST,
        borderMode=cv2.BORDER_CONSTANT,
    ).astype(bool)
    reference_values = ref[valid].astype(np.float64)
    moving_values = aligned[valid].astype(np.float64)
    reference_values -= reference_values.mean()
    moving_values -= moving_values.mean()
    denominator = np.linalg.norm(reference_values) * np.linalg.norm(moving_values)
    aligned_correlation = (
        float(np.dot(reference_values, moving_values) / denominator) if denominator > 0 else -1.0
    )
    fit = TranslationFit(dx, dy, aligned_correlation, overlap)
    if fit.correlation < min_correlation:
        raise ValueError(f"ECC correlation {fit.correlation:.4f} is below threshold")
    if fit.overlap_fraction < min_overlap_fraction:
        raise ValueError(f"estimated overlap {fit.overlap_fraction:.3f} is too small")
    return fit


def stitch_sequence(
    images: tuple[NDArray[np.generic], ...] | list[NDArray[np.generic]],
    *,
    downsample: int = 2,
    min_correlation: float = 0.2,
    min_overlap_fraction: float = 0.1,
    stage_positions_xy_um: tuple[tuple[float, float], ...]
    | list[tuple[float, float]]
    | None = None,
    calibration: Calibration | None = None,
    max_prior_deviation_px: float | None = None,
) -> StitchResult:
    """Register each image to its predecessor and blend the resulting mosaic.

    The sequence must be ordered along a path where every adjacent pair overlaps.
    If stage positions are supplied, each delta is converted through the same-tile
    calibration and used as ECC's initial estimate. This utility does not guess
    grid topology or stage units.
    """
    if len(images) < 2:
        raise ValueError("at least two images are required")
    if (stage_positions_xy_um is None) != (calibration is None):
        raise ValueError("stage positions and hand-eye calibration must be supplied together")
    if stage_positions_xy_um is not None and len(stage_positions_xy_um) != len(images):
        raise ValueError("one stage position is required for every image")
    arrays = [np.asarray(image) for image in images]
    shape = arrays[0].shape
    if len(shape) != 2 or any(image.shape != shape for image in arrays):
        raise ValueError("all stitch images must have the same 2D shape")

    fits: list[TranslationFit] = []
    origins: list[tuple[float, float]] = [(0.0, 0.0)]
    for reference, moving in pairwise(arrays):
        pair_index = len(fits)
        initial_shift = None
        if stage_positions_xy_um is not None and calibration is not None:
            first = np.asarray(stage_positions_xy_um[pair_index], dtype=np.float64)
            second = np.asarray(stage_positions_xy_um[pair_index + 1], dtype=np.float64)
            if (
                first.shape != (2,)
                or second.shape != (2,)
                or not (np.isfinite(first).all() and np.isfinite(second).all())
            ):
                raise ValueError("stage positions must contain finite XY micrometre pairs")
            initial_shift = stage_translation_to_pixel(
                (float(second[0] - first[0]), float(second[1] - first[1])), calibration
            )
        fit = estimate_translation(
            reference,
            moving,
            downsample=downsample,
            min_correlation=min_correlation,
            min_overlap_fraction=min_overlap_fraction,
            initial_shift_xy_px=initial_shift,
            max_prior_deviation_px=max_prior_deviation_px,
        )
        fits.append(fit)
        prior_x, prior_y = origins[-1]
        origins.append((prior_x + fit.dx_px, prior_y + fit.dy_px))

    h, w = shape
    min_x = int(np.floor(min(x for x, _ in origins)))
    min_y = int(np.floor(min(y for _, y in origins)))
    max_x = int(np.ceil(max(x + w for x, _ in origins)))
    max_y = int(np.ceil(max(y + h for _, y in origins)))
    canvas_shape = (max_y - min_y, max_x - min_x)
    accumulator = np.zeros(canvas_shape, dtype=np.float64)
    weights = np.zeros(canvas_shape, dtype=np.float32)
    for image, (x, y) in zip(arrays, origins, strict=True):
        transform = np.asarray([[1, 0, x - min_x], [0, 1, y - min_y]], dtype=np.float32)
        warped = cv2.warpAffine(
            np.asarray(image, dtype=np.float32),
            transform,
            (canvas_shape[1], canvas_shape[0]),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
        )
        mask = cv2.warpAffine(
            np.ones(shape, dtype=np.float32),
            transform,
            (canvas_shape[1], canvas_shape[0]),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
        )
        accumulator += warped * mask
        weights += mask
    mosaic = np.divide(accumulator, weights, out=np.zeros_like(accumulator), where=weights > 0)
    shifted_origins = tuple((x - min_x, y - min_y) for x, y in origins)
    return StitchResult(mosaic.astype(np.float32), shifted_origins, tuple(fits))
