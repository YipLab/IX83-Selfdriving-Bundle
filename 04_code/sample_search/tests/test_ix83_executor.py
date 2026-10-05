from __future__ import annotations

import threading
import time
from dataclasses import replace

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
from ix83_search_host import (
    AcquireRequest,
    ExecutionControl,
    MoveRequest,
    SearchCancelled,
    local_dataset_path,
)
from samplescout import AcquisitionSettings, Phase


def executor(tmp_path, stage=None):
    return IX83SearchExecutor(
        MockCamera(shape_yx=(32, 32)), stage or MockXYZStage(), tmp_path,
        limits_xy_um=((-50, 50), (-50, 50)), fixed_z_um=0,
    )


def capture(device, *, frames=1, **kwargs):
    control = ExecutionControl(cancelled=kwargs.get("cancelled", lambda: False),
        deadline_monotonic=kwargs.get("deadline"))
    return device.acquire(AcquireRequest("capture", "test-run", "search", "1", "seeded",
        Phase.SURVEY if frames == 1 else Phase.REVISIT, "stage", "calibration", "tile",
        AcquisitionSettings(exposure_ms=50, frames=frames), "target" if frames > 1 else None,
        control))


def move(device, position, *, deadline=None, request_id="move"):
    return device.move_to(MoveRequest(request_id, "test-run", "search", "1", "seeded",
        Phase.SURVEY, "stage", "calibration", tuple(position), "tile",
        control=ExecutionControl(deadline_monotonic=deadline)))


def test_limits_reject_before_move_and_fixed_z(tmp_path):
    stage = MockXYZStage()
    device = executor(tmp_path, stage)
    try:
        with pytest.raises(ValueError, match="envelope"):
            move(device, (51, 0, 0))
        with pytest.raises(ValueError, match="fixed Z"):
            move(device, (0, 0, 1))
        assert stage.history == [Position(0, 0, 0)]
    finally:
        device.close()


def test_snap_and_movie_save_exact_raw_pixels(tmp_path):
    device = executor(tmp_path)
    try:
        assert move(device, (10, 5, 0)).stage_xyz_um == (10, 5, 0)
        survey = capture(device)
        movie = capture(device, frames=3)
        with pytest.raises(ValueError, match="manifest checksum"):
            local_dataset_path(replace(survey.dataset, manifest_sha256="f" * 64))
        saved = list(replay_frames(local_dataset_path(survey.dataset)))
        frames = list(replay_ome_frames(local_dataset_path(movie.dataset)))
        np.testing.assert_array_equal(saved[0].pixels, survey.image)
        np.testing.assert_array_equal(frames[0].pixels, movie.image)
        assert len(frames) == 3
        assert all(frame.stage_position == Position(10, 5, 0) for frame in frames)
    finally:
        device.close()


def test_mid_movie_cancellation_returns_the_recorded_prefix_reference(tmp_path):
    device = executor(tmp_path)
    try:
        with pytest.raises(SearchCancelled, match="captured prefix") as caught:
            capture(device, frames=20, cancelled=lambda: device.camera.sequence >= 1)
        reference = caught.value.dataset
        assert reference.terminal_status == "cancelled"
        assert reference.axes == "TYX" and reference.frames_written == 1
        assert len(list(replay_ome_frames(local_dataset_path(reference)))) == 1
    finally:
        device.close()


def test_legacy_windows_path_string_remains_readable():
    from pathlib import Path

    assert local_dataset_path(r"C:\recordings\dataset") == Path(r"C:\recordings\dataset")


def test_external_motion_and_deadline_prevent_commands(tmp_path):
    stage = MockXYZStage()
    device = executor(tmp_path, stage)
    try:
        with pytest.raises(TimeoutError):
            move(device, (10, 0, 0), deadline=time.monotonic() - 1)
        assert len(stage.history) == 1
        stage.move_to(Position(2, 0, 0))
        with pytest.raises(RuntimeError, match="external stage movement"):
            capture(device)
        assert device.outcome_uncertain
        with pytest.raises(RuntimeError, match="reconciliation"):
            move(device, (0, 0, 0))
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
            move(device, (10, 0, 0))
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
            move(device, (1, 1, 0), request_id="competing-move")
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
            device.acquire(AcquireRequest("roi", "r", "search", "1", "s", Phase.SURVEY,
                "stage", "c", "t", AcquisitionSettings(roi_origin=(10, 0))))
        assert not device.datasets
        assert device.camera.sequence == 0
    finally:
        device.close()
