"""Authorized mechanical XY scan acceptance; no optical calibration is inferred.

Run after the mock and AutoScanJ replay gates. Uses six positions over 50 x 25 um,
50 ms camera exposure and one five-frame control movie. No illumination, gain,
binning, physical Z, homing or driver settings are changed.
"""
# Source-tree bootstrapping is intentional until distribution packaging is added.
# ruff: noqa: E402
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np

BUNDLE = Path(__file__).resolve().parents[1].parent
sys.path[:0] = [str(BUNDLE / "03_external/sample_search"),
                str(BUNDLE / "04_code/sample_search"),
                str(BUNDLE / "04_code/ix83_acquisition/src")]

from ix83_acquisition import replay_frames, replay_ome_frames
from ix83_acquisition.pycromanager import (
    PycroManagerCamera,
    PycroManagerXYZStage,
    connect_core,
)
from ix83_search_adapter import IX83SearchExecutor
from samplescout import AcquisitionSettings, Phase


def labels(vector):
    return [str(vector.get(i)) for i in range(vector.size())] if hasattr(vector, "size") else list(vector)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-real", action="store_true", required=True)
    args = parser.parse_args()
    if not args.allow_real:
        parser.error("operator authorization required")
    core = connect_core(timeout=5000)
    expected = {"COM22": ("SerialManager", "COM22"), "Camera-1": ("PVCAM", "Camera-1"),
                "LudlController": ("Ludl", "LudlController"), "XYStage": ("Ludl", "XYStage"),
                "DHub": ("DemoCamera", "DHub"), "ZStage": ("DemoCamera", "DStage")}

    def preflight():
        actual = {label: (core.get_device_library(label), core.get_device_name(label))
                  for label in labels(core.get_loaded_devices()) if label != "Core"}
        if actual != expected or core.get_property("LudlController", "Port") != "COM22":
            raise RuntimeError("unexpected loaded hardware")
        if (core.get_camera_device(), core.get_xy_stage_device(), core.get_focus_device()) != (
            "Camera-1", "XYStage", "ZStage"):
            raise RuntimeError("unexpected Core roles")
        if core.is_sequence_running() or core.get_remaining_image_count():
            raise RuntimeError("stop MMStudio Live and finish queued acquisitions")
        if core.get_auto_shutter() or core.get_shutter_device():
            raise RuntimeError("unexpected automatic shutter binding")

    preflight()
    stage = PycroManagerXYZStage(core, xy_stage="XYStage", z_stage="ZStage")
    origin = stage.position
    limits = ((origin.x_um - 500, origin.x_um + 500),
              (origin.y_um - 500, origin.y_um + 500))
    stage = PycroManagerXYZStage(core, xy_stage="XYStage", z_stage="ZStage",
        limits_um=(*limits, (origin.z_um, origin.z_um)))
    exposure = float(core.get_exposure())
    binning = str(core.get_property("Camera-1", "Binning"))
    report_path = BUNDLE / f"08_session_logs/sample-search-hardware-{time.time_ns()}.json"
    report = {"status": "started", "origin_um": asdict(origin), "xy_limits_um": limits,
              "exposure_ms": 50, "moves": [], "datasets": [],
              "optical_calibration": "unavailable; mechanical scanning only",
              "illumination_changed": False, "binning_changed": False,
              "physical_z_moved": False,
              "profile_sha256": hashlib.sha256((BUNDLE / "04_code/02_mmcfg/ix83_mixed_ludl_pvcam_mmconfig.cfg").read_bytes()).hexdigest()}

    def journal():
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    device = IX83SearchExecutor(PycroManagerCamera(core), stage,
        BUNDLE / "04_code/sample_search/recordings" / report_path.stem,
        limits_xy_um=limits, fixed_z_um=origin.z_um, preflight=preflight)
    journal()
    try:
        for index, (dx, dy) in enumerate(((0, 0), (25, 0), (50, 0), (50, 25), (25, 25), (0, 25))):
            entry = {"target_um": [origin.x_um + dx, origin.y_um + dy, origin.z_um], "state": "started"}
            report["moves"].append(entry)
            journal()
            readback = device.move_to(f"scan-move-{index}", tuple(entry["target_um"]), deadline=time.monotonic() + 15)
            entry.update(state="completed", readback_um=readback)
            observed = device.acquire(f"scan-tile-{index}",
                AcquisitionSettings(exposure_ms=50, image_shape_yx=(2048, 2048)),
                phase=Phase.SURVEY, specimen_id="operator-current-field", coordinate_frame="ludl-stage",
                calibration_id="uncalibrated-motion-test", run_id=report_path.stem, tile_id=f"tile-{index}",
                deadline=time.monotonic() + 15)
            frames = list(replay_frames(Path(observed.data_reference)))
            np.testing.assert_array_equal(frames[0].pixels, observed.image)
            report["datasets"].append({"path": observed.data_reference, "frames": len(frames),
                "stage_xy_um": observed.stage_xy_um, "pixels_verified": True,
                "image_min": int(observed.image.min()), "image_max": int(observed.image.max()),
                "image_mean": float(observed.image.mean())})
            journal()
        movie = device.acquire("control-movie", AcquisitionSettings(exposure_ms=50, frames=5,
                image_shape_yx=(2048, 2048)), phase=Phase.REVISIT,
                specimen_id="operator-current-field", coordinate_frame="ludl-stage",
                calibration_id="uncalibrated-motion-test", run_id=report_path.stem,
                tile_id="control", target_id="mechanical-control", deadline=time.monotonic() + 15)
        frames = list(replay_ome_frames(Path(movie.data_reference)))
        np.testing.assert_array_equal(frames[0].pixels, movie.image)
        if len(frames) != 5:
            raise RuntimeError("control movie incomplete")
        report["datasets"].append({"path": movie.data_reference, "frames": 5, "pixels_verified": True})
        report["status"] = "passed"
    except Exception as exc:
        report.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        try:
            if device.outcome_uncertain:
                report["return_to_origin"] = "not_attempted_outcome_unknown"
            else:
                report["final_before_return_um"] = asdict(stage.position)
                actual = device.move_to("return-to-origin", (origin.x_um, origin.y_um, origin.z_um),
                                        deadline=time.monotonic() + 15)
                report["final_um"] = actual
                report["return_to_origin"] = "verified_within_0.5_um"
            device.close(timeout=15)
            preflight()
            core.set_exposure(exposure)
            if float(core.get_exposure()) != exposure or str(core.get_property("Camera-1", "Binning")) != binning:
                raise RuntimeError("camera settings restoration failed")
            report["exposure_restored"] = True
            report["binning_unchanged"] = True
        except Exception as exc:
            report.update(status="failed", cleanup_error=f"{type(exc).__name__}: {exc}")
            raise
        finally:
            journal()
    print(json.dumps({"status": report["status"], "report": str(report_path),
                      "survey_frames": 6, "control_movie_frames": 5,
                      "scan_span_xy_um": [50, 25], "return_to_origin": report["return_to_origin"]}, indent=2))


if __name__ == "__main__":
    main()
