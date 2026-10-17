"""Operator-authorized Ludl/PVCAM smoke check with a bounded XY envelope.

Does not load configurations, home/reset stages, change illumination, change
binning or move physical Z. Run only after permission to use these real devices.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from dataclasses import asdict
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

package_root = Path(__file__).resolve().parents[1]
bundle_root = package_root.parents[1]
sys.path.insert(0, str(package_root / "src"))


def check(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def labels(vector):
    return (
        [vector.get(i) for i in range(vector.size())] if hasattr(vector, "size") else list(vector)
    )


def main() -> None:
    from ix83_acquisition import (
        AcquisitionController,
        CaptureRequest,
        Position,
        RunRecorder,
        replay_frames,
    )
    from ix83_acquisition.pycromanager import (
        PycroManagerCamera,
        PycroManagerXYZStage,
        connect_core,
    )

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-real", action="store_true", required=True)
    parser.add_argument(
        "--origin-um",
        type=float,
        nargs=3,
        metavar=("X", "Y", "Z"),
        help="Previously recorded origin, after reconciling an interrupted test",
    )
    args = parser.parse_args()
    check(args.allow_real, "Explicit real-device selection required")
    profile = bundle_root / "04_code/02_mmcfg/ix83_mixed_ludl_pvcam_mmconfig.cfg"
    report_path = bundle_root / "08_session_logs/2026-10-04-mixed-hardware-validation.json"
    report_path.parent.mkdir(exist_ok=True)
    report = {
        "state": "preflight",
        "profile": profile.name,
        "profile_sha256": hashlib.sha256(profile.read_bytes()).hexdigest(),
        "started_ns": time.time_ns(),
        "pycromanager": version("pycromanager"),
        "pyjavaz": version("pyjavaz"),
        "moves": [],
        "frames": [],
        "illumination_changed": False,
        "physical_z_moved": False,
        "tolerance_um": 0.5,
        "max_xy_span_um": 1000,
    }

    def journal():
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    journal()
    core = connect_core(timeout=5000)
    expected = {
        "COM22": ("SerialManager", "COM22"),
        "Camera-1": ("PVCAM", "Camera-1"),
        "LudlController": ("Ludl", "LudlController"),
        "XYStage": ("Ludl", "XYStage"),
        "DHub": ("DemoCamera", "DHub"),
        "ZStage": ("DemoCamera", "DStage"),
    }
    actual = {
        label: (core.get_device_library(label), core.get_device_name(label))
        for label in labels(core.get_loaded_devices())
        if label != "Core"
    }
    check(actual == expected, f"Unexpected device inventory: {actual}")
    check(core.get_property("LudlController", "Port") == "COM22", "Wrong Ludl port")
    check(
        (core.get_camera_device(), core.get_xy_stage_device(), core.get_focus_device())
        == ("Camera-1", "XYStage", "ZStage"),
        "Unexpected Core roles",
    )
    check(not core.is_sequence_running(), "Stop MMStudio Live first")
    check(
        not core.get_auto_shutter() and not core.get_shutter_device(), "Unexpected shutter binding"
    )
    report["devices"] = actual
    unbounded = PycroManagerXYZStage(core, xy_stage="XYStage", z_stage="ZStage")
    connected_position = unbounded.position
    initial = Position(*args.origin_um) if args.origin_um is not None else connected_position
    check(all(np.isfinite((initial.x_um, initial.y_um, initial.z_um))), "Nonfinite stage readback")
    limits = (
        (initial.x_um - 500, initial.x_um + 500),
        (initial.y_um - 500, initial.y_um + 500),
        (initial.z_um, initial.z_um),
    )
    check(
        all(
            low <= value <= high
            for value, (low, high) in zip(
                (connected_position.x_um, connected_position.y_um, connected_position.z_um),
                limits,
                strict=True,
            )
        ),
        "Current position is outside the original envelope",
    )
    stage = PycroManagerXYZStage(core, xy_stage="XYStage", z_stage="ZStage", limits_um=limits)
    camera = PycroManagerCamera(core)
    exposure = core.get_exposure()
    binning = core.get_property("Camera-1", "Binning")
    report.update(
        initial_um=asdict(initial),
        connected_position_um=asdict(connected_position),
        limits_um=limits,
        initial_exposure_ms=exposure,
        initial_binning=binning,
    )
    journal()
    controller = None
    expected_position = connected_position
    motion_in_flight = False

    def close_to(a, b):
        return np.allclose(
            (a.x_um, a.y_um, a.z_um), (b.x_um, b.y_um, b.z_um), atol=0.5 + 1e-9, rtol=0
        )

    def snap():
        started = time.monotonic()
        frame = camera.snap(stage_position=stage.position, exposure_ms=10)
        check(frame.pixels.ndim == 2 and frame.pixels.size > 0, "Invalid camera YX frame")
        check(frame.pixels.dtype == np.uint16, "Unexpected PVCAM pixel type")
        report["frames"].append(
            {
                "sequence": frame.sequence,
                "shape": list(frame.pixels.shape),
                "dtype": str(frame.pixels.dtype),
                "min": int(frame.pixels.min()),
                "max": int(frame.pixels.max()),
                "mean": float(frame.pixels.mean()),
                "elapsed_s": time.monotonic() - started,
            }
        )
        journal()

    def move(target):
        nonlocal expected_position, motion_in_flight
        check(close_to(stage.position, expected_position), "Unexpected external stage movement")
        check(not core.is_sequence_running(), "MMStudio Live became active")
        entry = {"target_um": asdict(target), "state": "started"}
        report["moves"].append(entry)
        journal()
        started = time.monotonic()
        motion_in_flight = True
        actual_position = stage.move_to(target)
        motion_in_flight = False
        entry.update(readback_um=asdict(actual_position), elapsed_s=time.monotonic() - started)
        if not close_to(actual_position, target):
            entry["state"] = "readback_outside_tolerance"
        check(close_to(actual_position, target), "XY readback exceeds 0.5 um tolerance")
        expected_position = actual_position
        entry["state"] = "completed"
        journal()

    try:
        report["state"] = "camera_check"
        snap()
        report["state"] = "xy_check"
        if not close_to(connected_position, initial):
            move(initial)
        for dx, dy in ((25, 0), (25, 25), (100, 25), (100, 100)):
            move(Position(initial.x_um + dx, initial.y_um + dy, initial.z_um))
            snap()
        move(initial)
        report["state"] = "controller_check"
        controller = AcquisitionController(camera, stage, preview_capacity=2)
        with TemporaryDirectory(prefix="ix83-real-smoke-") as temporary:
            writer = RunRecorder(
                Path(temporary), "pvcam", context={"profile_sha256": report["profile_sha256"]}
            )
            pixels = []

            def record(frame):
                writer(frame)
                pixels.append(frame.pixels.copy())

            try:
                controller.start_finite(
                    [CaptureRequest(timepoint=i) for i in range(3)], on_frame=record
                )
                result = controller.wait(15)
                check(result.state == "completed" and result.frames_acquired == 3, str(result))
                writer.finish(result)
                replayed = list(replay_frames(writer.dataset_dir))
                check(len(replayed) == 3, "Replay frame count mismatch")
                for frame, expected_pixels in zip(replayed, pixels, strict=True):
                    np.testing.assert_array_equal(frame.pixels, expected_pixels)
                report.update(finite_run=asdict(result), replay_pixels_equal=True)
            finally:
                controller.request_stop()
                controller.wait(15)
                writer.close()
        controller.start_free_run(CaptureRequest(), interval_s=0.2)
        deadline = time.monotonic() + 10
        while not controller.preview() and time.monotonic() < deadline:
            time.sleep(0.02)
        check(bool(controller.preview()), "No free-run preview")
        result = controller.stop(15)
        check(result.state == "cancelled" and result.frames_acquired > 0, str(result))
        report["free_run"] = asdict(result)
        report["state"] = "passed"
    except Exception as exc:
        report.update(state="failed", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        try:
            if controller is not None:
                controller.request_stop()
                controller.wait(15)
            # A timed-out move can still be executing. Do not issue an automatic
            # retry or return move when completion/position is uncertain.
            if motion_in_flight:
                report["return_to_start"] = "not_attempted_motion_outcome_unknown"
            elif not close_to(stage.position, expected_position):
                report["return_to_start"] = "not_attempted_unexpected_position"
            else:
                if not close_to(stage.position, initial):
                    move(initial)
                report["final_um"] = asdict(stage.position)
                check(close_to(stage.position, initial), "Starting XY position not restored")
                report["return_to_start"] = "verified"
            core.set_exposure(exposure)
            report["exposure_restored"] = core.get_exposure() == exposure
            report["binning_unchanged"] = core.get_property("Camera-1", "Binning") == binning
            check(
                report["exposure_restored"] and report["binning_unchanged"],
                "Camera settings mismatch",
            )
            if controller is not None:
                controller.close()
            else:
                camera.close()
                stage.close()
        except Exception as exc:
            report.update(state="failed", cleanup_error=f"{type(exc).__name__}: {exc}")
            raise
        finally:
            report["finished_ns"] = time.time_ns()
            journal()
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
