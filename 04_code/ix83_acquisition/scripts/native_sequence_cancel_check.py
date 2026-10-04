"""Operator-authorized 50 ms native cancellation/partial-recording check."""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory

package_root = Path(__file__).resolve().parents[1]
bundle_root = package_root.parents[1]
sys.path.insert(0, str(package_root / "src"))


def main() -> None:
    from ix83_acquisition import (
        AcquisitionController,
        OMERecorder,
        SequenceRequest,
        replay_ome_frames,
    )
    from ix83_acquisition.__main__ import _labels
    from ix83_acquisition.pycromanager import PycroManagerCamera, PycroManagerXYZStage, connect_core

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-real", required=True, action="store_true")
    args = parser.parse_args()
    assert args.allow_real
    core = connect_core(timeout=5000)
    expected = {"COM22": ("SerialManager", "COM22"), "Camera-1": ("PVCAM", "Camera-1"),
                "LudlController": ("Ludl", "LudlController"), "XYStage": ("Ludl", "XYStage"),
                "DHub": ("DemoCamera", "DHub"), "ZStage": ("DemoCamera", "DStage")}
    assert {label: (core.get_device_library(label), core.get_device_name(label))
            for label in _labels(core.get_loaded_devices()) if label != "Core"} == expected
    assert (core.get_camera_device(), core.get_xy_stage_device(), core.get_focus_device()) == (
        "Camera-1", "XYStage", "ZStage")
    assert not core.is_sequence_running() and not core.get_remaining_image_count()
    assert not core.get_auto_shutter() and not core.get_shutter_device()
    exposure = core.get_exposure()
    camera = PycroManagerCamera(core)
    stage = PycroManagerXYZStage(core, xy_stage="XYStage", z_stage="ZStage")
    controller = AcquisitionController(camera, stage, preview_capacity=2)
    with TemporaryDirectory(prefix="ix83-cancel-", dir=package_root / "recordings") as temporary:
        writer = OMERecorder(Path(temporary), "cancelled")

        def record(frame):
            writer(frame)
            if frame.sequence == 19:
                controller.request_stop()

        try:
            controller.start_sequence(SequenceRequest(200, exposure_ms=50), on_frame=record)
            result = writer.finish(controller.wait(15), device_status=asdict(camera.last_sequence_status))
            assert result.state == "cancelled" and 20 <= writer.frames_written < 200
            replayed = 0
            for frame in replay_ome_frames(writer.dataset_dir):
                assert frame.core_image_number == replayed
                replayed += 1
            assert replayed == writer.frames_written == result.frames_acquired
            assert camera.last_sequence_status.cancelled
            assert not camera.last_sequence_status.overflowed
            assert camera.last_sequence_status.unread_at_cleanup == 0
            assert not core.is_sequence_running()
            report = {"result": "PASS", "run": asdict(result), "verified_pages": replayed,
                      "sequence_status": asdict(camera.last_sequence_status)}
            print(json.dumps(report, indent=2))
            path = bundle_root / f"08_session_logs/sequence-cancel-{time.time_ns()}.json"
            path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        finally:
            controller.close(timeout=15)
            writer.close()
            if core.is_sequence_running():
                raise RuntimeError("Native sequence remains active")
            core.set_exposure(exposure)


if __name__ == "__main__":
    main()
