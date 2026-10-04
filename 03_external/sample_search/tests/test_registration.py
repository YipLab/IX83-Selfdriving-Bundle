import cv2
import numpy as np
import pytest
from samplescout.registration import estimate_translation, stitch_sequence


def textured_canvas(seed=3):
    rng = np.random.default_rng(seed)
    canvas = rng.normal(100, 25, size=(240, 480)).astype(np.float32)
    canvas = cv2.GaussianBlur(canvas, (0, 0), 1.2)
    for _ in range(35):
        x, y = rng.integers(0, 480), rng.integers(0, 240)
        cv2.circle(canvas, (int(x), int(y)), int(rng.integers(2, 8)),
                   float(rng.integers(40, 220)), -1)
    return canvas


def test_estimate_translation_recovers_moving_image_origin():
    canvas = textured_canvas()
    reference = canvas[:, :240]
    moving = canvas[:, 80:320]
    fit = estimate_translation(reference, moving, downsample=1,
                                min_correlation=0.4, min_overlap_fraction=0.5)
    assert fit.dx_px == pytest.approx(80, abs=1.0)
    assert fit.dy_px == pytest.approx(0, abs=1.0)
    assert fit.correlation >= 0.4


def test_stitch_sequence_accumulates_offsets_and_blends_overlap():
    canvas = textured_canvas()
    tiles = [canvas[:, start:start + 240] for start in (0, 80, 160)]
    result = stitch_sequence(tiles, downsample=1, min_correlation=0.4,
                             min_overlap_fraction=0.5)
    xs = [origin[0] for origin in result.origins_xy_px]
    assert xs == pytest.approx([0, 80, 160], abs=1.5)
    assert 240 <= result.image.shape[0] <= 242
    assert 400 <= result.image.shape[1] <= 403
    h = min(result.image.shape[0], canvas.shape[0])
    w = min(result.image.shape[1], canvas.shape[1])
    assert float(np.mean(np.abs(result.image[:h, :w] - canvas[:h, :w]))) < 2.0


def test_registration_rejects_dissimilar_or_untextured_inputs():
    a = textured_canvas()[:, :240]
    b = textured_canvas(seed=81)[:, 240:]
    with pytest.raises(ValueError, match="phase-correlation|correlation|overlap|converge"):
        estimate_translation(a, b, downsample=1, min_correlation=0.8)
    with pytest.raises(ValueError):
        estimate_translation(np.zeros((64, 64)), np.zeros((64, 64)))


def test_registration_rejects_invalid_shapes_and_single_image_stitch():
    with pytest.raises(ValueError, match="same-shaped 2D"):
        estimate_translation(np.zeros((32, 32)), np.zeros((32, 31)))
    with pytest.raises(ValueError, match="at least two"):
        stitch_sequence([np.zeros((32, 32))])
