"""Minimal fixed-position sequence acquisition CLI with complete OME recording."""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .controller import AcquisitionController, SequenceRequest
from .interfaces import Camera, XYZStage
from .mock import MockCamera, MockXYZStage
from .ome_recording import OMERecorder


def _labels(vector: Any) -> list[str]:
    return [str(vector.get(i)) for i in range(vector.size())] if hasattr(vector, "size") else list(vector)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--devices", choices=("mock", "demo", "mixed"), default="mock")
    parser.add_argument("--allow-real", action="store_true")
    parser.add_argument("--frames", type=int, default=100)
    parser.add_argument("--exposure-ms", type=float, default=50)
    parser.add_argument("--output", type=Path, default=Path("recordings"))
    parser.add_argument("--name", default="sequence")
    parser.add_argument("--writer-queue", type=int, default=32)
    args = parser.parse_args(argv)
    request = SequenceRequest(args.frames, exposure_ms=args.exposure_ms)
    request.validate()
    core: Any = None
    camera: Camera
    stage: XYZStage
    initial_exposure: float | None = None
    if args.devices == "mock":
        camera, stage = MockCamera(), MockXYZStage()
    else:
        if args.devices == "mixed" and not args.allow_real:
            parser.error("mixed devices require operator authorization and --allow-real")
        from .pycromanager import PycroManagerCamera, PycroManagerXYZStage, connect_core

        core = connect_core(timeout=5000)
        expected = {"DHub": ("DemoCamera", "DHub"), "ZStage": ("DemoCamera", "DStage")}
        camera_label = "Camera"
        if args.devices == "demo":
            expected.update(Camera=("DemoCamera", "DCam"), XYStage=("DemoCamera", "DXYStage"))
        else:
            camera_label = "Camera-1"
            expected.update({"Camera-1": ("PVCAM", "Camera-1"), "XYStage": ("Ludl", "XYStage"),
                             "LudlController": ("Ludl", "LudlController"), "COM22": ("SerialManager", "COM22")})
            if core.get_property("LudlController", "Port") != "COM22":
                raise RuntimeError("unexpected Ludl serial port")
        actual = {label: (core.get_device_library(label), core.get_device_name(label))
                  for label in _labels(core.get_loaded_devices()) if label != "Core"}
        if actual != expected:
            raise RuntimeError(f"loaded profile does not match selected devices: {actual}")
        if (core.get_camera_device(), core.get_xy_stage_device(), core.get_focus_device()) != (
                camera_label, "XYStage", "ZStage"):
            raise RuntimeError("unexpected Core roles")
        if core.is_sequence_running() or core.get_remaining_image_count():
            raise RuntimeError("Stop MMStudio Live and finish its queued acquisition")
        if core.get_auto_shutter() or core.get_shutter_device():
            raise RuntimeError("unexpected automatic shutter or shutter binding")
        camera = PycroManagerCamera(core)
        stage = PycroManagerXYZStage(core, xy_stage="XYStage", z_stage="ZStage")
        initial_exposure = float(core.get_exposure())
    controller = AcquisitionController(camera, stage, preview_capacity=2)
    writer: OMERecorder | None = None
    try:
        position = stage.position
        writer = OMERecorder(args.output, args.name, queue_capacity=args.writer_queue,
                             context={"devices": args.devices, "exposure_ms": args.exposure_ms,
                                      "fixed_position_um": asdict(position)})
        started = time.monotonic()
        controller.start_sequence(request, on_frame=writer)
        try:
            result = controller.wait()
        except KeyboardInterrupt:
            result = controller.stop(timeout=15)
        capture_s = time.monotonic() - started
        sequence_status = getattr(camera, "last_sequence_status", None)
        final = writer.finish(result, device_status=asdict(sequence_status) if sequence_status is not None else None)
        print(json.dumps({"result": asdict(final), "frames_written": writer.frames_written,
            "capture_s": capture_s, "end_to_end_s": time.monotonic()-started,
            "capture_and_drain_fps": result.frames_acquired/capture_s,
            "max_writer_queue_depth": writer.max_queue_depth,
            "sequence_status": asdict(sequence_status) if sequence_status is not None else None,
            "dataset_dir": str(writer.dataset_dir)}, indent=2))
        return 0 if final.state == "completed" else 1
    finally:
        # If a native call is blocked, wait/close raises and no competing device
        # restoration is attempted. Retain ownership until the worker ends.
        controller.close(timeout=15)
        try:
            if writer is not None:
                writer.close()
        finally:
            if core is not None and initial_exposure is not None:
                if core.is_sequence_running():
                    raise RuntimeError("Native camera remains active; exposure restoration not attempted")
                core.set_exposure(initial_exposure)


if __name__ == "__main__":
    raise SystemExit(main())
