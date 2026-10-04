import json
from dataclasses import replace

import numpy as np
import pytest

from ix83_acquisition import (
    AcquisitionController,
    CaptureRequest,
    MockCamera,
    MockXYZStage,
    Position,
    RunRecorder,
    replay_frames,
)


def record(root, name="run", *, cancel=False):
    recorder = RunRecorder(root, name, context={"calibration_id": "test", "specimen_id": "mock"})
    controller = AcquisitionController(
        MockCamera(shape_yx=(8, 8)), MockXYZStage(), preview_capacity=1
    )

    def sink(frame):
        recorder(frame)
        if cancel:
            controller.request_stop()

    try:
        controller.start_finite(
            [
                CaptureRequest(position=Position(i, 0, 0), timepoint=i, target_id=f"target-{i}")
                for i in range(3)
            ],
            on_frame=sink,
        )
        result = controller.wait(2)
        recorder.finish(result)
        return recorder.dataset_dir, result
    finally:
        controller.close()
        recorder.close()


def test_recorded_frames_survive_preview_eviction_and_replay_exactly(tmp_path):
    path, result = record(tmp_path)
    frames = list(replay_frames(path))
    assert result.state == "completed" and len(frames) == 3
    assert [frame.stage_position.x_um for frame in frames] == [0, 1, 2]
    assert frames[2].target_id == "target-2" and frames[2].timepoint == 2
    for frame in frames:
        np.testing.assert_array_equal(
            frame.pixels, np.load(path / f"frame_{frame.sequence:06d}.npy")
        )


def test_cancelled_recording_replays_the_committed_prefix(tmp_path):
    path, result = record(tmp_path, cancel=True)
    assert result.state == "cancelled" and len(list(replay_frames(path))) == 1


def test_dataset_collision_preserves_previous_run(tmp_path):
    first, _ = record(tmp_path)
    second, _ = record(tmp_path)
    assert first.name == "run" and second.name == "run_1"
    assert len(list(replay_frames(first))) == len(list(replay_frames(second))) == 3


def test_corrupted_pixels_and_ledger_are_rejected(tmp_path):
    path, _ = record(tmp_path)
    (path / "frame_000000.npy").write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="raw frame checksum"):
        list(replay_frames(path))
    with (path / "frames.jsonl").open("a") as stream:
        stream.write("{}\n")
    with pytest.raises(ValueError, match="ledger checksum"):
        list(replay_frames(path))


def test_incomplete_recording_does_not_look_completed(tmp_path):
    writer = RunRecorder(tmp_path, "unfinished")
    writer.close()
    with pytest.raises(FileNotFoundError):
        list(replay_frames(writer.dataset_dir))


def test_failed_write_is_reported_without_claiming_full_capture(tmp_path):
    writer = RunRecorder(tmp_path, "failed")
    controller = AcquisitionController(MockCamera(shape_yx=(8, 8)), MockXYZStage())

    def sink(frame):
        writer(frame if frame.sequence == 0 else replace(frame, sequence=10))

    try:
        controller.start_finite([CaptureRequest(), CaptureRequest()], on_frame=sink)
        result = controller.wait(2)
        writer.finish(result)
        metadata = json.loads((writer.dataset_dir / "run_metadata.json").read_text())
        assert result.state == "failed" and result.frames_acquired == 2
        assert metadata["frames_written"] == 1
        assert len(list(replay_frames(writer.dataset_dir))) == 1
    finally:
        controller.close()
        writer.close()


@pytest.mark.parametrize("name", ["..", "../escape", "a/b", "C:escape"])
def test_dataset_names_cannot_escape_the_root(tmp_path, name):
    with pytest.raises(ValueError):
        RunRecorder(tmp_path, name)
