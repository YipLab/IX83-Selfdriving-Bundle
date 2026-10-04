import threading
from dataclasses import replace

import pytest

from ix83_acquisition import (
    AcquisitionController,
    CaptureRequest,
    Channel,
    MockCamera,
    MockXYZStage,
    Position,
    PreviewReady,
)
from ix83_acquisition.mda import ChannelExposure, MDASettings, mda_timepoints


def test_stage_aware_image_and_bounded_preview_keep_finite_callback_complete():
    camera = MockCamera(shape_yx=(32, 32), read_noise=0, specimen_spots_um=((0, 0),))
    stage = MockXYZStage()
    controller = AcquisitionController(camera, stage, preview_capacity=1)
    frames = []
    requests = [
        CaptureRequest(position=Position(0, 0, 0), target_id="first"),
        CaptureRequest(position=Position(20, 0, 2), target_id="second"),
    ]
    controller.start_finite(requests, on_frame=frames.append)
    result = controller.wait(2)
    assert result.state == "completed" and result.frames_acquired == 2
    assert len(frames) == 2 and len(controller.preview()) == 1
    assert frames[0].pixels.max() > frames[1].pixels.max()
    assert frames[1].stage_position == Position(20, 0, 2)
    assert frames[1].request_id == requests[1].request_id
    assert frames[1].target_id == "second"
    assert frames[0].acquisition_end_ns >= frames[0].acquisition_start_ns > 0
    assert sum(isinstance(event, PreviewReady) for event in controller.drain_events()) == 1
    controller.close()


def test_free_run_cancels_during_wait_and_finite_run_can_follow():
    controller = AcquisitionController(MockCamera(shape_yx=(8, 8)), MockXYZStage())
    controller.start_free_run(CaptureRequest(), interval_s=60)
    # Wait on a capture notification, avoiding arbitrary sleep for test ordering.
    event = controller._events.get(timeout=2)
    assert isinstance(event, PreviewReady)
    with pytest.raises(RuntimeError, match="already owned"):
        controller.start_finite([CaptureRequest()])
    result = controller.stop(timeout=1)
    assert result.state == "cancelled" and controller.state == "idle"
    controller.start_finite([CaptureRequest()])
    assert controller.wait(2).state == "completed"
    controller.close()


def test_callback_failure_is_reported_and_camera_ownership_released():
    controller = AcquisitionController(MockCamera(shape_yx=(8, 8)), MockXYZStage())

    def fail(frame):
        raise OSError("sink full")

    controller.start_finite([CaptureRequest(), CaptureRequest()], on_frame=fail)
    result = controller.wait(2)
    assert result.state == "failed" and result.frames_acquired == 1
    assert "sink full" in result.error
    controller.start_finite([CaptureRequest()])
    assert controller.wait(2).state == "completed"
    controller.close()


def test_blocked_driver_timeout_keeps_device_owned_until_finished():
    entered, release = threading.Event(), threading.Event()

    class BlockingCamera(MockCamera):
        def snap(self, **kwargs):
            entered.set()
            release.wait(2)
            return super().snap(**kwargs)

    controller = AcquisitionController(BlockingCamera(shape_yx=(8, 8)), MockXYZStage())
    controller.start_finite([CaptureRequest()])
    assert entered.wait(2)
    try:
        with pytest.raises(TimeoutError):
            controller.close(timeout=0.001)
        with pytest.raises(RuntimeError, match="closed"):
            controller.start_finite([CaptureRequest()])
    finally:
        release.set()
        controller.close(timeout=2)
    assert controller.state == "closed"


def test_stage_limits_fail_before_camera_capture():
    camera = MockCamera(shape_yx=(8, 8))
    stage = MockXYZStage(limits_um=((-1, 1), (-1, 1), (-1, 1)))
    controller = AcquisitionController(camera, stage)
    controller.start_finite([CaptureRequest(position=Position(2, 0, 0))])
    result = controller.wait(2)
    assert result.state == "failed" and result.frames_acquired == 0
    assert camera.sequence == 0 and stage.position == Position(0, 0, 0)
    controller.close()


def test_cancel_from_callback_is_cooperative():
    controller = AcquisitionController(MockCamera(shape_yx=(8, 8)), MockXYZStage())
    controller.start_finite(
        [CaptureRequest(), CaptureRequest()], on_frame=lambda frame: controller.request_stop()
    )
    result = controller.wait(2)
    assert result.state == "cancelled" and result.frames_acquired == 1
    controller.close()


def test_multichannel_mda_offsets_are_per_timepoint():
    settings = MDASettings(
        channels=(
            ChannelExposure(Channel("Channel", "A"), 10),
            ChannelExposure(Channel("Channel", "B"), 20),
        ),
        frames=2,
        interval_s=0.05,
    )
    requests = list(mda_timepoints(settings))
    assert [request.start_after_s for request in requests] == [0, 0, 0.05, 0.05]
    assert [request.timepoint for request in requests] == [0, 0, 1, 1]
    controller = AcquisitionController(MockCamera(shape_yx=(8, 8)), MockXYZStage())
    frames = []
    controller.start_finite(requests, on_frame=frames.append)
    assert controller.wait(2).frames_acquired == 4
    assert frames[2].acquisition_start_ns - frames[0].acquisition_start_ns >= 40_000_000
    controller.close()


def test_invalid_request_is_a_failed_run():
    controller = AcquisitionController(MockCamera(shape_yx=(8, 8)), MockXYZStage())
    controller.start_finite([replace(CaptureRequest(), exposure_ms=float("nan"))])
    assert controller.wait(2).state == "failed"
    controller.close()
