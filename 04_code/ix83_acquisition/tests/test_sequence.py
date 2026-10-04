import threading
from collections import deque
from types import SimpleNamespace

import numpy as np
import pytest

from ix83_acquisition import (
    AcquisitionController,
    MockCamera,
    MockXYZStage,
    Position,
    SequenceRequest,
)
from ix83_acquisition.pycromanager import PycroManagerCamera


class SequenceCore:
    def __init__(self, numbers=(0, 1, 2), *, overflow=False, stalled=False):
        self.images = deque(SimpleNamespace(pix=np.full(16, number, dtype=np.uint16),
            tags={"ImageNumber": number, "PVCAM-FrameNr": number+1, "Height": 4, "Width": 4,
                  "TimeStampMsec": str(number*50)}) for number in numbers)
        self.running = False
        self.overflow = overflow
        self.stalled = stalled
        self.stops = 0

    def is_sequence_running(self):
        return self.running and (bool(self.images) or self.stalled)

    def get_remaining_image_count(self):
        return len(self.images) if self.running or self.stops else 0

    def set_exposure(self, exposure):
        self.exposure = exposure

    def initialize_circular_buffer(self):
        pass

    def start_sequence_acquisition(self, frames, interval, stop_on_overflow):
        assert interval == 0 and stop_on_overflow
        self.running = True

    def pop_next_tagged_image(self):
        return self.images.popleft()

    def stop_sequence_acquisition(self):
        self.running = False
        self.stops += 1

    def is_buffer_overflowed(self):
        return self.overflow

    def clear_circular_buffer(self):
        self.images.clear()


def test_native_sequence_preserves_hardware_ids_and_stops_camera():
    core = SequenceCore()
    camera = PycroManagerCamera(core)
    frames = list(camera.stream_sequence(frames=3, exposure_ms=50, stage_position=Position(1, 2, 3),
                                       stop_requested=lambda: False))
    assert [frame.core_image_number for frame in frames] == [0, 1, 2]
    assert [frame.camera_frame_number for frame in frames] == [1, 2, 3]
    assert [frame.source_timestamp_ms for frame in frames] == [0, 50, 100]
    assert core.stops and not core.running
    assert camera.last_sequence_status.received == 3


@pytest.mark.parametrize("numbers,overflow,match", [
    ((0, 2, 3), False, "gap"), ((0, 1), False, "incomplete"),
    ((0, 1), True, "overflow"), ((1, 2, 3), False, "missing Core"),
])
def test_native_gaps_short_runs_and_overflow_fail(numbers, overflow, match):
    core = SequenceCore(numbers, overflow=overflow)
    camera = PycroManagerCamera(core)
    with pytest.raises(RuntimeError, match=match):
        list(camera.stream_sequence(frames=3, exposure_ms=50, stage_position=Position(0, 0, 0),
                                    stop_requested=lambda: False))
    assert not core.running and not core.images


def test_cancel_stops_production_and_drains_already_queued_frames():
    core = SequenceCore()
    camera = PycroManagerCamera(core)
    stream = camera.stream_sequence(frames=10, exposure_ms=50, stage_position=Position(0, 0, 0),
                                    stop_requested=lambda: core.stops == 0 and len(core.images) < 3)
    assert len(list(stream)) == 3
    assert camera.last_sequence_status.cancelled


def test_callback_failure_closes_generator_and_reports_unread_core_frames():
    core = SequenceCore()
    camera = PycroManagerCamera(core)
    controller = AcquisitionController(camera, MockXYZStage())

    def fail(frame):
        raise RuntimeError("sink failed")

    controller.start_sequence(SequenceRequest(3), on_frame=fail)
    result = controller.wait(1)
    assert result.state == "failed" and "sink failed" in result.error
    assert camera.last_sequence_status.unread_at_cleanup == 2
    assert not core.images and not core.running
    controller.close()


def test_stalled_sequence_times_out_and_stops_camera():
    core = SequenceCore((), stalled=True)
    with pytest.raises(TimeoutError):
        list(PycroManagerCamera(core).stream_sequence(frames=3, exposure_ms=50,
            stage_position=Position(0, 0, 0), stop_requested=lambda: False, timeout_s=0.01))
    assert not core.running


def test_missing_camera_prefix_fails_even_if_core_renumbers_from_zero():
    core = SequenceCore()
    core.images[0].tags["PVCAM-FrameNr"] = 7
    with pytest.raises(RuntimeError, match="missing PVCAM"):
        list(PycroManagerCamera(core).stream_sequence(frames=3, exposure_ms=50,
            stage_position=Position(0, 0, 0), stop_requested=lambda: False))
    assert not core.running and not core.images


def test_mock_sequence_ownership_preview_and_cancelled_prefix():
    controller = AcquisitionController(MockCamera(shape_yx=(4, 4)), MockXYZStage(), preview_capacity=1)
    accepted = []

    def record(frame):
        accepted.append(frame)
        if len(accepted) == 3:
            controller.request_stop()

    controller.start_sequence(SequenceRequest(10, exposure_ms=1), on_frame=record)
    result = controller.wait(1)
    assert result.state == "cancelled" and result.frames_acquired == 3 and result.frames_requested == 10
    assert len(controller.preview()) == 1
    assert len({frame.request_id for frame in accepted}) == 3
    controller.start_sequence(SequenceRequest(3, exposure_ms=1))
    assert controller.wait(1).state == "completed"
    controller.close()


def test_worker_completion_keeps_ownership_even_if_thread_liveness_is_wrong(monkeypatch):
    entered, release = threading.Event(), threading.Event()

    class BlockedCamera(MockCamera):
        def snap(self, **kwargs):
            entered.set()
            assert release.wait(2)
            return super().snap(**kwargs)

    controller = AcquisitionController(BlockedCamera(shape_yx=(4, 4)), MockXYZStage())
    controller.start_sequence(SequenceRequest(3, exposure_ms=1))
    assert entered.wait(1)
    monkeypatch.setattr(controller._thread, "is_alive", lambda: False)
    try:
        with pytest.raises(RuntimeError, match="already owned"):
            controller.start_sequence(SequenceRequest(1))
        with pytest.raises(TimeoutError):
            controller.wait(0.01)
    finally:
        release.set()
        controller.close()
