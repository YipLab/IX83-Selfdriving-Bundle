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


@dataclass(frozen=True)
class TranslationFit:
    """Translation placing the moving image in reference-image coordinates."""

    dx_px: float
    dy_px: float
    correlation: float
    overlap_fraction: float


@dataclass(frozen=True)
class StitchResult:
    """A blended mosaic and the pixel origin of each source image."""

    image: NDArray[np.float32]
    origins_xy_px: tuple[tuple[float, float], ...]
    pairwise_fits: tuple[TranslationFit, ...]


def estimate_translation(
    reference: NDArray[np.generic],
    moving: NDArray[np.generic],
    *,
    downsample: int = 2,
    min_correlation: float = 0.2,
    min_overlap_fraction: float = 0.1,
) -> TranslationFit:
    """Estimate a moving-to-reference translation using OpenCV ECC.

    Images must be same-sized 2D grayscale arrays from the same camera mode.
    Fits with inadequate correlation or geometric overlap are rejected.
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

    ref_fit = np.asarray(ref, dtype=np.float32)
    mov_fit = np.asarray(mov, dtype=np.float32)
    scale_x = scale_y = 1.0
    if downsample > 1:
        fit_size = (max(16, ref.shape[1] // downsample), max(16, ref.shape[0] // downsample))
        scale_x, scale_y = ref.shape[1] / fit_size[0], ref.shape[0] / fit_size[1]
        ref_fit = np.asarray(cv2.resize(ref_fit, fit_size, interpolation=cv2.INTER_AREA), dtype=np.float32)
        mov_fit = np.asarray(cv2.resize(mov_fit, fit_size, interpolation=cv2.INTER_AREA), dtype=np.float32)

    # Phase correlation gives ECC a useful translation seed. Starting at the
    # identity is unreliable when the initial displacement is a large fraction
    # of the tile width (the common case for a stitched mosaic).
    window = cv2.createHanningWindow((ref_fit.shape[1], ref_fit.shape[0]), cv2.CV_32F)
    (phase_dx, phase_dy), response = cv2.phaseCorrelate(ref_fit, mov_fit, window)
    if not np.isfinite(response) or response < 0.1:
        raise ValueError("phase-correlation response is too weak to seed registration")
    warp = np.asarray([[1, 0, phase_dx], [0, 1, phase_dy]], dtype=np.float32)
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
    h, w = ref.shape
    overlap = max(0.0, w - abs(dx)) * max(0.0, h - abs(dy)) / (w * h)
    forward = np.asarray([[1, 0, dx], [0, 1, dy]], dtype=np.float32)
    aligned = cv2.warpAffine(mov.astype(np.float32), forward, (w, h),
                             flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
    valid = cv2.warpAffine(np.ones((h, w), dtype=np.uint8), forward, (w, h),
                           flags=cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT).astype(bool)
    reference_values = ref[valid].astype(np.float64)
    moving_values = aligned[valid].astype(np.float64)
    reference_values -= reference_values.mean()
    moving_values -= moving_values.mean()
    denominator = np.linalg.norm(reference_values) * np.linalg.norm(moving_values)
    aligned_correlation = (float(np.dot(reference_values, moving_values) / denominator)
                           if denominator > 0 else -1.0)
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
) -> StitchResult:
    """Register each image to its predecessor and blend the resulting mosaic.

    The sequence must be ordered along a path where every adjacent pair overlaps.
    This intentionally small utility does not guess grid topology or stage units.
    """
    if len(images) < 2:
        raise ValueError("at least two images are required")
    arrays = [np.asarray(image) for image in images]
    shape = arrays[0].shape
    if len(shape) != 2 or any(image.shape != shape for image in arrays):
        raise ValueError("all stitch images must have the same 2D shape")

    fits: list[TranslationFit] = []
    origins: list[tuple[float, float]] = [(0.0, 0.0)]
    for reference, moving in pairwise(arrays):
        fit = estimate_translation(
            reference, moving, downsample=downsample,
            min_correlation=min_correlation,
            min_overlap_fraction=min_overlap_fraction,
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
    for image, (x, y) in zip(arrays, origins):
        transform = np.asarray([[1, 0, x - min_x], [0, 1, y - min_y]], dtype=np.float32)
        warped = cv2.warpAffine(np.asarray(image, dtype=np.float32), transform,
                                (canvas_shape[1], canvas_shape[0]),
                                flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
        mask = cv2.warpAffine(np.ones(shape, dtype=np.float32), transform,
                              (canvas_shape[1], canvas_shape[0]),
                              flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
        accumulator += warped * mask
        weights += mask
    mosaic = np.divide(accumulator, weights, out=np.zeros_like(accumulator), where=weights > 0)
    shifted_origins = tuple((x - min_x, y - min_y) for x, y in origins)
    return StitchResult(mosaic.astype(np.float32), shifted_origins, tuple(fits))
