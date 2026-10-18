"""Authorized mechanical XY scan acceptance; no optical calibration is inferred.

Run after the mock and AutoScanJ replay gates with the full MM config already
loaded. Uses only PVCAM capture and Ludl XY motion. No IX83 component, shutter,
focus/Z axis, illumination, homing or driver setting is commanded.
"""

# Source-tree bootstrapping is intentional until distribution packaging is added.
from __future__ import annotations

import argparse
import hashlib
import json
import time
from dataclasses import asdict

import numpy as np
from source_bootstrap import enable_source_tree

BUNDLE = enable_source_tree()

from planner import AcquisitionSettings, Phase

from ix83_acquisition import replay_frames, replay_ome_frames
from ix83_acquisition.interfaces import Position
from ix83_acquisition.pycromanager import (
    PycroManagerCamera,
    connect_core,
)
from ix83_acquisition.scan_host import (
    AcquireRequest,
    ExecutionControl,
    MoveRequest,
    local_dataset_path,
)
from ix83_acquisition.scan_host.executor import IX83SearchExecutor

PROFILE = BUNDLE / "04_code/02_mmcfg/ix83_full_mmconfig.cfg"


class XYOnlyStage:
    """Expose XY motion to the search executor without touching IX83 focus/Z."""

    def __init__(self, core, *, xy_stage: str, fixed_z_um: float, limits_xy_um):
        self.core = core
        self.xy_stage = xy_stage
        self.fixed_z_um = fixed_z_um
        self.limits_xy_um = limits_xy_um
        self._closed = False

    @property
    def position(self):
        if self.core.get_xy_stage_device() != self.xy_stage:
            raise RuntimeError("unexpected Core XY stage")
        return Position(
            float(self.core.get_x_position(self.xy_stage)),
            float(self.core.get_y_position(self.xy_stage)),
            self.fixed_z_um,
        )

    def move_to(self, position):
        if self._closed:
            raise RuntimeError("stage is closed")
        if position.z_um != self.fixed_z_um:
            raise RuntimeError("XY-only scan cannot change Z")
        x_limits, y_limits = self.limits_xy_um
        if not (
            x_limits[0] <= position.x_um <= x_limits[1]
            and y_limits[0] <= position.y_um <= y_limits[1]
        ):
            raise ValueError("XY target outside scan limits")
        if self.core.get_xy_stage_device() != self.xy_stage:
            raise RuntimeError("unexpected Core XY stage")
        self.core.set_xy_position(position.x_um, position.y_um)
        self.core.wait_for_device(self.xy_stage)
        return self.position

    def close(self):
        self._closed = True


def labels(vector):
    return (
        [str(vector.get(i)) for i in range(vector.size())]
        if hasattr(vector, "size")
        else list(vector)
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-real", action="store_true", required=True)
    args = parser.parse_args()
    if not args.allow_real:
        parser.error("operator authorization required")
    core = connect_core(timeout=5000)
    expected = {}
    for line in PROFILE.read_text(encoding="utf-8").splitlines():
        fields = [field.strip() for field in line.split(",")]
        if len(fields) == 4 and fields[0] == "Device":
            expected[fields[1]] = (fields[2], fields[3])

    def preflight():
        actual = {
            label: (core.get_device_library(label), core.get_device_name(label))
            for label in labels(core.get_loaded_devices())
            if label != "Core"
        }
        if actual != expected or core.get_property("LudlController", "Port") != "COM22":
            raise RuntimeError("unexpected loaded hardware")
        if (core.get_camera_device(), core.get_xy_stage_device()) != ("Camera-1", "XYStage"):
            raise RuntimeError("unexpected Core roles")
        if core.is_sequence_running() or core.get_remaining_image_count():
            raise RuntimeError("stop MMStudio Live and finish queued acquisitions")
        if core.get_auto_shutter():
            raise RuntimeError("automatic shutter must remain disabled")

    preflight()
    # Z is a bookkeeping sentinel required by the framework-neutral XYZ contract;
    # this check deliberately never reads the focus device or writes any Z value.
    xy_origin = XYOnlyStage(
        core,
        xy_stage="XYStage",
        fixed_z_um=0.0,
        limits_xy_um=((-float("inf"), float("inf")), (-float("inf"), float("inf"))),
    ).position
    origin = Position(xy_origin.x_um, xy_origin.y_um, 0.0)
    limits = ((origin.x_um - 500, origin.x_um + 500), (origin.y_um - 500, origin.y_um + 500))
    stage = XYOnlyStage(core, xy_stage="XYStage", fixed_z_um=origin.z_um, limits_xy_um=limits)
    exposure = float(core.get_exposure())
    binning = str(core.get_property("Camera-1", "Binning"))
    report_path = BUNDLE / f"08_session_logs/sample-search-hardware-{time.time_ns()}.json"
    report = {
        "status": "started",
        "origin_um": asdict(origin),
        "xy_limits_um": limits,
        "exposure_ms": 50,
        "moves": [],
        "datasets": [],
        "optical_calibration": "unavailable; mechanical scanning only",
        "illumination_changed": False,
        "binning_changed": False,
        "physical_z_moved": False,
        "profile": PROFILE.name,
        "profile_sha256": hashlib.sha256(PROFILE.read_bytes()).hexdigest(),
        "ix83_hardware_commanded": False,
        "z_read_or_moved": False,
    }

    def journal():
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    device = IX83SearchExecutor(
        PycroManagerCamera(core),
        stage,
        BUNDLE / "04_code/ix83_acquisition/recordings/scan_workflow" / report_path.stem,
        limits_xy_um=limits,
        fixed_z_um=origin.z_um,
        preflight=preflight,
    )
    journal()
    try:
        for index, (dx, dy) in enumerate(((0, 0), (25, 0), (50, 0), (50, 25), (25, 25), (0, 25))):
            entry = {
                "target_um": [origin.x_um + dx, origin.y_um + dy, origin.z_um],
                "state": "started",
            }
            report["moves"].append(entry)
            journal()
            deadline = time.monotonic() + 15
            readback = device.move_to(
                MoveRequest(
                    f"scan-move-{index}",
                    report_path.stem,
                    "mechanical-scan",
                    "1",
                    "operator-current-field",
                    Phase.SURVEY,
                    "ludl-stage",
                    "uncalibrated-motion-test",
                    tuple(entry["target_um"]),
                    f"tile-{index}",
                    control=ExecutionControl(deadline_monotonic=deadline),
                )
            )
            entry.update(state="completed", readback_um=readback.stage_xyz_um)
            observed = device.acquire(
                AcquireRequest(
                    f"scan-tile-{index}",
                    report_path.stem,
                    "mechanical-scan",
                    "1",
                    "operator-current-field",
                    Phase.SURVEY,
                    "ludl-stage",
                    "uncalibrated-motion-test",
                    f"tile-{index}",
                    AcquisitionSettings(exposure_ms=50, image_shape_yx=(2048, 2048)),
                    control=ExecutionControl(deadline_monotonic=deadline),
                )
            )
            frames = list(replay_frames(local_dataset_path(observed.dataset)))
            np.testing.assert_array_equal(frames[0].pixels, observed.image)
            report["datasets"].append(
                {
                    "path": observed.dataset.uri,
                    "frames": len(frames),
                    "stage_xy_um": observed.stage_xy_um,
                    "pixels_verified": True,
                    "image_min": int(observed.image.min()),
                    "image_max": int(observed.image.max()),
                    "image_mean": float(observed.image.mean()),
                }
            )
            journal()
        deadline = time.monotonic() + 15
        movie = device.acquire(
            AcquireRequest(
                "control-movie",
                report_path.stem,
                "mechanical-scan",
                "1",
                "operator-current-field",
                Phase.REVISIT,
                "ludl-stage",
                "uncalibrated-motion-test",
                "control",
                AcquisitionSettings(exposure_ms=50, frames=5, image_shape_yx=(2048, 2048)),
                "mechanical-control",
                ExecutionControl(deadline_monotonic=deadline),
            )
        )
        frames = list(replay_ome_frames(local_dataset_path(movie.dataset)))
        np.testing.assert_array_equal(frames[0].pixels, movie.image)
        if len(frames) != 5:
            raise RuntimeError("control movie incomplete")
        report["datasets"].append({"path": movie.dataset.uri, "frames": 5, "pixels_verified": True})
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
                actual = device.move_to(
                    MoveRequest(
                        "return-to-origin",
                        report_path.stem,
                        "mechanical-scan",
                        "1",
                        "operator-current-field",
                        Phase.REVISIT,
                        "ludl-stage",
                        "uncalibrated-motion-test",
                        (origin.x_um, origin.y_um, origin.z_um),
                        "origin",
                        control=ExecutionControl(deadline_monotonic=time.monotonic() + 15),
                    )
                )
                report["final_um"] = actual.stage_xyz_um
                report["return_to_origin"] = "verified_within_0.5_um"
            device.close(timeout=15)
            preflight()
            core.set_exposure(exposure)
            if (
                float(core.get_exposure()) != exposure
                or str(core.get_property("Camera-1", "Binning")) != binning
            ):
                raise RuntimeError("camera settings restoration failed")
            report["exposure_restored"] = True
            report["binning_unchanged"] = True
        except Exception as exc:
            report.update(status="failed", cleanup_error=f"{type(exc).__name__}: {exc}")
            raise
        finally:
            journal()
    print(
        json.dumps(
            {
                "status": report["status"],
                "report": str(report_path),
                "survey_frames": 6,
                "control_movie_frames": 5,
                "scan_span_xy_um": [50, 25],
                "return_to_origin": report["return_to_origin"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
