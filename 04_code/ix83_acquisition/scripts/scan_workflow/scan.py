"""MM2/Pycro-Manager stage-grid or explicit-target acquisition procedure."""

from __future__ import annotations

import argparse
import json
import signal
import time
from pathlib import Path

from source_bootstrap import enable_source_tree

BUNDLE = enable_source_tree()

from planner import AcquisitionSettings, Phase, RunStatus
from planner.scanning import (
    ScanPosition,
    StageScanRecipe,
    build_grid_recipe,
    grid_positions,
)

from ix83_acquisition import MockCamera, MockXYZStage, replay_frames, replay_ome_frames
from ix83_acquisition.pycromanager import (
    PycroManagerCamera,
    PycroManagerXYZStage,
    connect_core,
)
from ix83_acquisition.scan_host import (
    StageScanRunner,
    dataset_reference_from_record,
    local_dataset_path,
)
from ix83_acquisition.scan_host.executor import IX83SearchExecutor


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("mock", "pycromanager"), default="mock")
    parser.add_argument("--allow-real", action="store_true")
    parser.add_argument("--rows", type=int, default=2)
    parser.add_argument("--columns", type=int, default=3)
    parser.add_argument("--step-x-um", type=float, default=25)
    parser.add_argument("--step-y-um", type=float, default=25)
    parser.add_argument("--x-sign", type=int, choices=(-1, 1), default=1)
    parser.add_argument("--y-sign", type=int, choices=(-1, 1), default=1)
    parser.add_argument("--swap-xy", action="store_true")
    parser.add_argument("--serpentine", action="store_true")
    parser.add_argument(
        "--targets",
        type=Path,
        help="JSON list of position_id/x_um/y_um in absolute stage coordinates",
    )
    parser.add_argument("--frames", type=int, default=1)
    parser.add_argument("--exposure-ms", type=float, default=50)
    parser.add_argument("--settle-ms", type=float, default=0)
    parser.add_argument("--timeout-s", type=float, default=120)
    parser.add_argument("--specimen-id", default="operator-current-field")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.backend == "pycromanager" and not args.allow_real:
        parser.error("real device selection requires --allow-real")
    # Validate grid sizes and steps before connecting to devices.
    grid_positions(
        (0, 0), rows=args.rows, columns=args.columns, step_xy_um=(args.step_x_um, args.step_y_um)
    )
    settings = AcquisitionSettings(exposure_ms=args.exposure_ms, frames=args.frames)
    output = (
        args.output
        or BUNDLE / "04_code/ix83_acquisition/recordings/scan_workflow" / f"scan-{time.time_ns()}"
    )
    if output.exists():
        parser.error("output must be a new directory")
    core = None
    prior_exposure = None
    prior_binning = None
    if args.backend == "mock":
        stage, camera = MockXYZStage(), MockCamera(shape_yx=(80, 80))

        def preflight():
            pass
    else:
        core = connect_core(timeout=5000)
        expected = {
            "COM22": ("SerialManager", "COM22"),
            "Camera-1": ("PVCAM", "Camera-1"),
            "LudlController": ("Ludl", "LudlController"),
            "XYStage": ("Ludl", "XYStage"),
            "DHub": ("DemoCamera", "DHub"),
            "ZStage": ("DemoCamera", "DStage"),
        }

        def preflight():
            devices = core.get_loaded_devices()
            labels = (
                [str(devices.get(i)) for i in range(devices.size())]
                if hasattr(devices, "size")
                else list(devices)
            )
            actual = {
                label: (core.get_device_library(label), core.get_device_name(label))
                for label in labels
                if label != "Core"
            }
            if actual != expected or core.get_property("LudlController", "Port") != "COM22":
                raise RuntimeError(
                    "loaded devices do not match the tested mixed Ludl/PVCAM profile"
                )
            if (core.get_camera_device(), core.get_xy_stage_device(), core.get_focus_device()) != (
                "Camera-1",
                "XYStage",
                "ZStage",
            ):
                raise RuntimeError("unexpected Core device roles")
            if core.is_sequence_running() or core.get_remaining_image_count():
                raise RuntimeError("stop MMStudio Live and other acquisition clients first")
            if core.get_auto_shutter() or core.get_shutter_device():
                raise RuntimeError("unexpected automatic shutter binding")

        preflight()
        stage = PycroManagerXYZStage(core, xy_stage="XYStage", z_stage="ZStage")
        camera = PycroManagerCamera(core)
        prior_exposure = float(core.get_exposure())
        prior_binning = str(core.get_property("Camera-1", "Binning"))
    origin = stage.position
    limits = ((origin.x_um - 500, origin.x_um + 500), (origin.y_um - 500, origin.y_um + 500))
    if args.targets:
        entries = json.loads(args.targets.read_text(encoding="utf-8"))
        if not isinstance(entries, list):
            raise ValueError("targets must be a JSON list")
        positions = tuple(ScanPosition(**entry) for entry in entries)
        recipe = StageScanRecipe(
            "target-scan", args.specimen_id, positions, settings, phase=Phase.REVISIT
        )
    else:
        recipe = build_grid_recipe(
            (origin.x_um, origin.y_um),
            specimen_id=args.specimen_id,
            settings=settings,
            rows=args.rows,
            columns=args.columns,
            step_xy_um=(args.step_x_um, args.step_y_um),
            x_sign=args.x_sign,
            y_sign=args.y_sign,
            swap_xy=args.swap_xy,
            serpentine=args.serpentine,
        )
        positions = recipe.positions
    device = IX83SearchExecutor(
        camera,
        stage,
        output / "datasets",
        limits_xy_um=limits,
        fixed_z_um=origin.z_um,
        preflight=preflight,
    )
    cancelled = False

    def cancel(_signal, _frame):
        nonlocal cancelled
        cancelled = True

    previous_handler = signal.signal(signal.SIGINT, cancel)
    try:
        runner = StageScanRunner(
            device,
            limits_xy_um=limits,
            fixed_z_um=origin.z_um,
            origin_xy_um=(origin.x_um, origin.y_um),
            journal=output / "scan.json",
            cancelled=lambda: cancelled,
        )
        run = runner.run_recipe(recipe, settle_ms=args.settle_ms, timeout_s=args.timeout_s)
        frames = 0
        for recorded in run.positions:
            dataset = dataset_reference_from_record(recorded["data_reference"])
            reference = local_dataset_path(dataset)
            frames += sum(
                1
                for _ in (
                    replay_frames(reference) if args.frames == 1 else replay_ome_frames(reference)
                )
            )
        if run.status is RunStatus.COMPLETED and frames != len(positions) * args.frames:
            raise RuntimeError("saved frame count does not match planned acquisition")
        print(
            json.dumps(
                {
                    "status": run.status.value,
                    "planned_positions": len(positions),
                    "recorded_positions": len(run.positions),
                    "verified_frames": frames,
                    "journal": str(output / "scan.json"),
                    "errors": run.errors,
                },
                indent=2,
            )
        )
        if run.status is not RunStatus.COMPLETED:
            raise SystemExit(1)
    finally:
        signal.signal(signal.SIGINT, previous_handler)
        device.close(timeout=15)
        final_position = stage.position
        cleanup = {
            "backend": args.backend,
            "final_xyz_um": [final_position.x_um, final_position.y_um, final_position.z_um],
            "resources_closed": True,
        }
        if core is not None:
            preflight()
            core.set_exposure(prior_exposure)
            if (
                float(core.get_exposure()) != prior_exposure
                or str(core.get_property("Camera-1", "Binning")) != prior_binning
            ):
                raise RuntimeError("camera settings restoration failed")
            cleanup.update(
                exposure_before_ms=prior_exposure,
                exposure_restored_ms=float(core.get_exposure()),
                binning_before=prior_binning,
                binning_after=str(core.get_property("Camera-1", "Binning")),
            )
        if output.exists():
            (output / "cleanup.json").write_text(json.dumps(cleanup, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
