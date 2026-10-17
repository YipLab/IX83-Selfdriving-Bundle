"""Check a running demo-only Micro-Manager configuration over ZMQ.

Run from the package root: python scripts/demo_zmq_smoke.py
The GUI must have loaded ix83_demo_mmconfig.cfg and stopped Live.
"""

from __future__ import annotations

import json
import sys
import time
import warnings
from dataclasses import asdict
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ix83_acquisition import (
    AcquisitionController,
    CaptureRequest,
    Channel,
    Position,
    RunRecorder,
    replay_frames,
)
from ix83_acquisition.pycromanager import (
    PycroManagerCamera,
    PycroManagerXYZStage,
    connect_core,
)


def check(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> None:
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        core = connect_core(timeout=3000)
    for warning in captured:
        check("mistmatch" not in str(warning.message), str(warning.message))
    loaded = core.get_loaded_devices()
    # Java returns StrVector; some newer clients convert it to a Python list.
    labels = (
        [loaded.get(i) for i in range(loaded.size())] if hasattr(loaded, "size") else list(loaded)
    )
    for label in labels:
        if label != "Core":
            check(
                core.get_device_library(label) == "DemoCamera", f"Non-demo device loaded: {label}"
            )
    for label, name in {"Camera": "DCam", "XYStage": "DXYStage", "ZStage": "DStage"}.items():
        check(core.get_device_name(label) == name, f"Unexpected device: {label}")
    check(core.get_camera_device() == "Camera", "Unexpected camera role")
    check(core.get_xy_stage_device() == "XYStage", "Unexpected XY-stage role")
    check(core.get_focus_device() == "ZStage", "Unexpected focus role")
    check(not core.is_sequence_running(), "Stop MM Live before running this check")

    stage = PycroManagerXYZStage(core, xy_stage="XYStage", z_stage="ZStage")
    camera = PycroManagerCamera(core, channel_group="Channel", channel="Demo")
    initial = stage.position
    exposure = core.get_exposure()
    binning = core.get_property("Camera", "Binning")
    report = {
        "python": sys.version,
        "pycromanager": version("pycromanager"),
        "pyjavaz": version("pyjavaz"),
        "numpy": version("numpy"),
        "frames": [],
    }
    controller = None
    try:
        target = Position(initial.x_um + 10.0, initial.y_um + 5.0, initial.z_um + 2.0)
        actual = stage.move_to(target)
        check(
            np.allclose(
                (actual.x_um, actual.y_um, actual.z_um),
                (target.x_um, target.y_um, target.z_um),
                atol=0.01,
                rtol=0,
            ),
            "Demo XYZ readback exceeds 0.01 um tolerance",
        )
        report["requested_um"] = vars(target)
        report["readback_um"] = vars(actual)
        for sequence in range(3):
            frame = camera.snap(stage_position=stage.position, exposure_ms=10.0)
            check(frame.sequence == sequence, "Unexpected frame sequence")
            check(frame.pixels.ndim == 2 and frame.pixels.size > 0, "Invalid YX frame")
            check(frame.stage_position == actual, "Unexpected frame position context")
            check(np.isfinite(frame.pixels).all(), "Non-finite image values")
            report["frames"].append(
                {
                    "sequence": sequence,
                    "shape": list(frame.pixels.shape),
                    "dtype": str(frame.pixels.dtype),
                }
            )
        controller = AcquisitionController(camera, stage, preview_capacity=2)
        with TemporaryDirectory(prefix="ix83-demo-recording-") as temporary:
            writer = RunRecorder(
                Path(temporary), "demo", context={"device_profile": "ix83_demo_mmconfig.cfg"}
            )
            expected = []

            def record(frame):
                writer(frame)
                expected.append(frame.pixels.copy())

            try:
                controller.start_finite(
                    [
                        CaptureRequest(channel=Channel("Channel", "Demo"), timepoint=t)
                        for t in range(3)
                    ],
                    on_frame=record,
                )
                finite = controller.wait(10)
                check(finite.state == "completed" and finite.frames_acquired == 3, str(finite))
                check(len(controller.preview()) == 2, "Preview did not respect its capacity")
                writer.finish(finite)
                replayed = list(replay_frames(writer.dataset_dir))
                check(len(replayed) == 3, "Recording lost finite-run frames")
                for saved, pixels in zip(replayed, expected, strict=True):
                    np.testing.assert_array_equal(saved.pixels, pixels)
                report["recorded_frames"] = len(replayed)
                report["replay_pixels_equal"] = True
                report["finite_run"] = asdict(finite)
            finally:
                controller.request_stop()
                controller.wait(10)
                writer.close()
        controller.start_free_run(
            CaptureRequest(channel=Channel("Channel", "Demo")), interval_s=0.05
        )
        deadline = time.monotonic() + 5
        while not controller.preview() and time.monotonic() < deadline:
            time.sleep(0.01)
        check(bool(controller.preview()), "Free run did not produce an image")
        free = controller.stop(5)
        check(free.state == "cancelled" and free.frames_acquired > 0, str(free))
        report["free_run"] = asdict(free)
    finally:
        if controller is not None:
            controller.request_stop()
            # Do not restore through the same devices while a driver is blocked.
            controller.wait(10)
        # Try every cleanup even if an earlier restoration fails.
        try:
            stage.move_to(initial)
        finally:
            try:
                core.set_exposure(exposure)
            finally:
                core.set_property("Camera", "Binning", binning)
                if controller is not None:
                    controller.close()
                else:
                    camera.close()
                    stage.close()
    check(stage.position == initial, "Starting XYZ position was not restored")
    check(core.get_exposure() == exposure, "Exposure was not restored")
    check(core.get_property("Camera", "Binning") == binning, "Binning was not restored")
    report["result"] = "PASS"
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
