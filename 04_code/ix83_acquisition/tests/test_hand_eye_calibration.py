from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from bluesky import RunEngine

from ix83_acquisition.hand_eye_calibration import HandEyeCalibrationRecorder
from ix83_acquisition.pycromanager_bluesky import (
    PycroManagerSnapDetector,
    PycroManagerXYPositioner,
    pycromanager_hand_eye_calibration_plan,
)


class SyntheticCore:
    def __init__(self, image: np.ndarray) -> None:
        self.x_um = 0.0
        self.y_um = 0.0
        self.z_um = 0.0
        self.image = image
        self.moves: list[tuple[float, float]] = []
        self.frame_number = 0
        self.exposure_ms = 10.0
        self.exposure_writes = 0
        self.tagged = None
        self.matrix = np.asarray([[0.1, 1.0], [1.0, 0.1]], dtype=np.float64)

    def get_xy_stage_device(self):
        return "XYStage"

    def get_x_position(self, label):
        assert label == "XYStage"
        return self.x_um

    def get_y_position(self, label):
        assert label == "XYStage"
        return self.y_um

    def get_position(self, label):
        assert label == "ZStage"
        return self.z_um

    def set_xy_position(self, x_um, y_um):
        self.x_um, self.y_um = float(x_um), float(y_um)
        self.moves.append((self.x_um, self.y_um))

    def wait_for_device(self, label):
        assert label == "XYStage"

    def device_busy(self, label):
        assert label == "XYStage"
        return False

    def is_sequence_running(self):
        return False

    def get_remaining_image_count(self):
        return 0

    def set_exposure(self, exposure_ms):
        self.exposure_ms = float(exposure_ms)
        self.exposure_writes += 1

    def get_exposure(self):
        return self.exposure_ms

    def snap_image(self):
        cv2 = pytest.importorskip("cv2")
        self.frame_number += 1
        dx, dy = self.matrix @ np.asarray([self.x_um, self.y_um])
        transform = np.asarray([[1, 0, dx], [0, 1, dy]], dtype=np.float32)
        pixels = cv2.warpAffine(
            self.image,
            transform,
            (self.image.shape[1], self.image.shape[0]),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REFLECT,
        )
        self.tagged = SimpleNamespace(
            pix=np.asarray(np.clip(pixels, 0, 65535), dtype=np.uint16),
            tags={"Height": pixels.shape[0], "Width": pixels.shape[1]},
        )

    def get_tagged_image(self):
        return self.tagged


def _textured_image() -> np.ndarray:
    cv2 = pytest.importorskip("cv2")
    rng = np.random.default_rng(20261016)
    image = rng.normal(15000, 3500, size=(256, 256)).astype(np.float32)
    image = cv2.GaussianBlur(image, (0, 0), 1.0)
    for _ in range(100):
        x, y = rng.integers(12, 244, size=2)
        radius = int(rng.integers(2, 8))
        intensity = float(rng.integers(4000, 60000))
        cv2.circle(image, (int(x), int(y)), radius, intensity, -1)
    return np.asarray(np.clip(image, 0, 65535), dtype=np.uint16)


def test_runengine_hand_eye_calibration_persists_and_analyzes_raw_frames(tmp_path: Path):
    core = SyntheticCore(_textured_image())
    stage = PycroManagerXYPositioner(
        core,
        xy_stage="XYStage",
        limits_xy_um=((-2000, 2000), (-2000, 2000)),
        readback_tolerance_um=0.01,
    )
    camera = PycroManagerSnapDetector(
        core,
        stage,
        z_stage="ZStage",
        exposure_ms=10,
        shape_yx=(256, 256),
        dtype="uint16",
        configure_exposure=False,
    )
    plan = pycromanager_hand_eye_calibration_plan(
        anchor_xy_um=(0, 0),
        stage=stage,
        camera=camera,
        coordinate_frame="synthetic-ix83-stage-xy",
        mode_context={
            "profile_revision": "synthetic-profile-v1",
            "camera": "SyntheticCamera",
            "objective": "synthetic-20x",
            "binning": "2x2",
            "roi": "full",
        },
        registration_roi_yxhw_px=(32, 32, 192, 192),
        registration_preprocessing="percentile_clahe",
    )
    recorder = HandEyeCalibrationRecorder(tmp_path, "hand-eye")
    engine = RunEngine({})
    engine.subscribe(recorder)
    engine(plan)

    manifest = json.loads((recorder.directory / "run_metadata.json").read_text())
    analysis = json.loads((recorder.directory / "analysis.json").read_text())
    assert manifest["event_count"] == 10
    assert core.exposure_writes == 0
    assert manifest["stop_status"] == "success"
    assert manifest["analysis_status"] == "passed"
    assert analysis["accepted_for_scan_preflight"] is True
    assert analysis["registration"] == {
        "roi_yxhw_px": [32, 32, 192, 192],
        "preprocessing": "percentile_clahe",
        "percentile_limits": [1.0, 99.7],
        "clahe_clip_limit": 2.0,
        "clahe_tile_grid_yx": [8, 8],
    }
    fitted = np.asarray(analysis["fit"]["content_motion_px_per_stage_unit"])
    np.testing.assert_allclose(fitted, core.matrix, atol=0.4)
    assert len(list((recorder.directory / "images").glob("image_*.npy"))) == 10
    for relative, expected_hash in manifest["files_sha256"].items():
        path = recorder.directory / relative
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected_hash
    ledger = [
        json.loads(line) for line in (recorder.directory / "events.jsonl").read_text().splitlines()
    ]
    assert [record["data"]["stage_x_pre_snap_um"] for record in ledger] == [
        0.0,
        0.0,
        10.0,
        0.0,
        -10.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
    ]


def test_incomplete_calibration_recorder_has_no_terminal_manifest(tmp_path: Path):
    recorder = HandEyeCalibrationRecorder(tmp_path, "interrupted")
    recorder("start", {"uid": "incomplete"})
    recorder.close()
    assert not (recorder.directory / "run_metadata.json").exists()
