import json
import threading
from dataclasses import replace

import numpy as np
import pytest
import tifffile

from ix83_acquisition import (
    AcquisitionController,
    Frame,
    MockCamera,
    MockXYZStage,
    Position,
    RunResult,
    SequenceRequest,
)
from ix83_acquisition.ome_recording import OMERecorder, replay_ome_frames


def frame(index):
    return Frame(np.full((8, 8), index, dtype=np.uint16), Position(1, 2, 3), index, 50,
                 timepoint=index,
                 core_image_number=index, camera_frame_number=index+1, source_timestamp_ms=index*50)


def test_concurrent_controller_recording_retains_every_frame(tmp_path):
    writer = OMERecorder(tmp_path, "mock", queue_capacity=8)
    controller = AcquisitionController(MockCamera(shape_yx=(8, 8)), MockXYZStage(), preview_capacity=1)
    controller.start_sequence(SequenceRequest(4, exposure_ms=1), on_frame=writer)
    result = writer.finish(controller.wait(2))
    assert result.state == "completed" and writer.frames_written == 4
    assert len(controller.preview()) == 1
    replayed = list(replay_ome_frames(writer.dataset_dir))
    assert [value.core_image_number for value in replayed] == list(range(4))
    with tifffile.TiffFile(writer.raw_path) as tiff:
        assert tiff.is_ome and tiff.is_bigtiff
        assert len(tiff.pages) == 4 and tiff.series[0].axes == "TYX"
    controller.close()


def test_cancelled_recording_has_real_prefix_count(tmp_path):
    writer = OMERecorder(tmp_path, "cancelled", queue_capacity=4)
    writer(frame(0))
    writer(frame(1))
    result = writer.finish(RunResult("run", "cancelled", 2, frames_requested=10))
    assert result.state == "cancelled"
    assert len(list(replay_ome_frames(writer.dataset_dir))) == 2


def test_complete_short_run_cannot_be_finalized_as_success(tmp_path):
    writer = OMERecorder(tmp_path, "short", queue_capacity=4)
    writer(frame(0))
    result = writer.finish(RunResult("run", "completed", 1, frames_requested=3))
    assert result.state == "failed" and "requested/written" in result.error
    assert len(list(replay_ome_frames(writer.dataset_dir))) == 1


def test_bounded_queue_raises_instead_of_dropping_frames(tmp_path, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original = tifffile.TiffWriter.write

    def slow_write(self, *args, **kwargs):
        entered.set()
        assert release.wait(2)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(tifffile.TiffWriter, "write", slow_write)
    writer = OMERecorder(tmp_path, "bounded", queue_capacity=1)
    try:
        writer(frame(0))
        assert entered.wait(1)
        writer(frame(1))
        with pytest.raises(RuntimeError, match="queue full"):
            writer(frame(2))
        assert writer.frames_submitted == 2
    finally:
        release.set()
    result = writer.finish(RunResult("run", "failed", 3, "queue full", frames_requested=3))
    assert result.state == "failed" and len(list(replay_ome_frames(writer.dataset_dir))) == 2


def test_writer_error_propagates_and_replay_rejects_unverified_file(tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("disk failure")

    monkeypatch.setattr(tifffile.TiffWriter, "write", fail)
    writer = OMERecorder(tmp_path, "disk")
    writer(frame(0))
    result = writer.finish(RunResult("run", "completed", 1, frames_requested=1))
    assert result.state == "failed" and "disk failure" in result.error
    with pytest.raises(ValueError, match="failed OME"):
        list(replay_ome_frames(writer.dataset_dir))


def test_pixel_corruption_is_detected(tmp_path):
    writer = OMERecorder(tmp_path, "corrupt")
    writer(frame(0))
    writer.finish(RunResult("run", "completed", 1))
    with tifffile.TiffFile(writer.raw_path) as tiff:
        offset = tiff.pages[0].dataoffsets[0]
    with writer.raw_path.open("r+b") as stream:
        stream.seek(offset)
        stream.write(b"\xff\xff")
    with pytest.raises(ValueError, match="checksum"):
        list(replay_ome_frames(writer.dataset_dir))


def test_layout_change_failed_and_close_without_finish_remains_incomplete(tmp_path):
    writer = OMERecorder(tmp_path, "layout", queue_capacity=4)
    writer(frame(0))
    writer(replace(frame(1), pixels=np.zeros((4, 4), dtype=np.uint16)))
    result = writer.finish(RunResult("run", "completed", 2))
    assert result.state == "failed" and "fixed shape" in result.error
    incomplete = OMERecorder(tmp_path, "incomplete")
    incomplete(frame(0))
    incomplete.close()
    assert not (incomplete.dataset_dir / "run_metadata.json").exists()
    with pytest.raises(FileNotFoundError):
        list(replay_ome_frames(incomplete.dataset_dir))
    manifest = json.loads((writer.dataset_dir / "run_metadata.json").read_text())
    assert manifest["frames_written"] == 1


def test_blocked_writer_cannot_finalize_before_explicit_completion(tmp_path, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original = tifffile.TiffWriter.write

    def slow_write(self, *args, **kwargs):
        entered.set()
        assert release.wait(2)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(tifffile.TiffWriter, "write", slow_write)
    writer = OMERecorder(tmp_path, "blocked")
    writer(frame(0))
    assert entered.wait(1)
    monkeypatch.setattr(writer._thread, "is_alive", lambda: False)
    try:
        with pytest.raises(TimeoutError):
            writer.finish(RunResult("run", "completed", 1), timeout=0.01)
        assert not (writer.dataset_dir / "run_metadata.json").exists()
    finally:
        release.set()
    assert writer.finish(RunResult("run", "completed", 1)).state == "completed"


def test_ome_rejects_ambiguous_timepoints_and_changing_target_binding(tmp_path):
    writer = OMERecorder(tmp_path, "binding")
    writer(frame(0))
    with pytest.raises(ValueError, match="timepoint"):
        writer(replace(frame(1), timepoint=0))
    with pytest.raises(ValueError, match="fixed position"):
        writer(replace(frame(1), target_id="another-target"))
    writer.finish(RunResult("run", "cancelled", 1))
