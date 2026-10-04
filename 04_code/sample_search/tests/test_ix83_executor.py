from __future__ import annotations

import threading
import time
from pathlib import Path

import numpy as np
import pytest
from ix83_acquisition import (
    MockCamera,
    MockXYZStage,
    Position,
    replay_frames,
    replay_ome_frames,
)
from ix83_search_adapter import IX83SearchExecutor
from samplescout import AcquisitionSettings, Phase


def executor(tmp_path, stage=None):
    return IX83SearchExecutor(
        MockCamera(shape_yx=(32, 32)), stage or MockXYZStage(), tmp_path,
        limits_xy_um=((-50, 50), (-50, 50)), fixed_z_um=0,
    )


def capture(device, *, frames=1, **kwargs):
    return device.acquire("capture", AcquisitionSettings(exposure_ms=50, frames=frames),
        phase=Phase.SURVEY if frames == 1 else Phase.REVISIT,
        specimen_id="seeded", coordinate_frame="stage", calibration_id="calibration",
        run_id="test-run", tile_id="tile", target_id="target" if frames > 1 else None,
        **kwargs)


def test_limits_reject_before_move_and_fixed_z(tmp_path):
    stage = MockXYZStage()
    device = executor(tmp_path, stage)
    try:
        with pytest.raises(ValueError, match="envelope"):
            device.move_to("outside", (51, 0, 0))
        with pytest.raises(ValueError, match="fixed Z"):
            device.move_to("z", (0, 0, 1))
        assert stage.history == [Position(0, 0, 0)]
    finally:
        device.close()


def test_snap_and_movie_save_exact_raw_pixels(tmp_path):
    device = executor(tmp_path)
    try:
        assert device.move_to("move", (10, 5, 0)) == (10, 5, 0)
        survey = capture(device)
        movie = capture(device, frames=3)
        saved = list(replay_frames(Path(survey.data_reference)))
        frames = list(replay_ome_frames(Path(movie.data_reference)))
        np.testing.assert_array_equal(saved[0].pixels, survey.image)
        np.testing.assert_array_equal(frames[0].pixels, movie.image)
        assert len(frames) == 3
        assert all(frame.stage_position == Position(10, 5, 0) for frame in frames)
    finally:
        device.close()


def test_external_motion_and_deadline_prevent_commands(tmp_path):
    stage = MockXYZStage()
    device = executor(tmp_path, stage)
    try:
        with pytest.raises(TimeoutError):
            device.move_to("expired", (10, 0, 0), deadline=time.monotonic() - 1)
        assert len(stage.history) == 1
        stage.move_to(Position(2, 0, 0))
        with pytest.raises(RuntimeError, match="external stage movement"):
            capture(device)
        assert device.outcome_uncertain
        with pytest.raises(RuntimeError, match="reconciliation"):
            device.move_to("return", (0, 0, 0))
        assert len(stage.history) == 2
    finally:
        device.close()


def test_unacknowledged_move_has_no_retry_or_rollback(tmp_path):
    class UnacknowledgedStage(MockXYZStage):
        def move_to(self, target):
            super().move_to(target)
            raise TimeoutError("acknowledgement lost")

    stage = UnacknowledgedStage()
    device = executor(tmp_path, stage)
    try:
        with pytest.raises(TimeoutError):
            device.move_to("move", (10, 0, 0))
        assert stage.position.x_um == 10
        assert device.outcome_uncertain
        with pytest.raises(RuntimeError, match="reconciliation"):
            capture(device)
    finally:
        device.close()
    assert len(stage.history) == 2


def test_blocked_camera_retains_writer_and_device_ownership(tmp_path):
    entered, release = threading.Event(), threading.Event()

    class BlockedCamera(MockCamera):
        def snap(self, **kwargs):
            entered.set()
            release.wait(5)
            return super().snap(**kwargs)

    device = IX83SearchExecutor(BlockedCamera(shape_yx=(32, 32)), MockXYZStage(), tmp_path,
        limits_xy_um=((-50, 50), (-50, 50)), fixed_z_um=0)
    try:
        with pytest.raises(TimeoutError):
            capture(device, deadline=time.monotonic() + 0.05)
        assert entered.is_set()
        assert device.outcome_uncertain
        with pytest.raises(RuntimeError, match="reconciliation"):
            device.move_to("competing-move", (1, 1, 0))
        with pytest.raises(TimeoutError):
            device.close(timeout=0.01)
        assert not (device.datasets[0] / "manifest.json").exists()
    finally:
        release.set()
        device.close(timeout=5)
    assert len(list(replay_frames(device.datasets[0]))) == 1


def test_unsupported_roi_binding_is_rejected_before_capture(tmp_path):
    device = executor(tmp_path)
    try:
        with pytest.raises(ValueError, match="ROI/binning"):
            device.acquire("roi", AcquisitionSettings(roi_origin=(10, 0)),
                phase=Phase.SURVEY, specimen_id="s", coordinate_frame="stage",
                calibration_id="c", run_id="r", tile_id="t")
        assert not device.datasets
        assert device.camera.sequence == 0
    finally:
        device.close()
