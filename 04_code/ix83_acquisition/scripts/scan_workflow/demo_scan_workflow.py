"""DEMO-only operator-bounded IX83 scan prototype; mock is the default backend."""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict
from pathlib import Path

from source_bootstrap import enable_source_tree

BUNDLE = enable_source_tree()

from planner.bounded_scanning import (
    ConfirmedBoundary,
    CornerObservation,
    plan_broom_scan,
    plan_snap_scan,
)

from ix83_acquisition import MockCamera, MockXYZStage, Position
from ix83_acquisition.pycromanager import (
    PycroManagerCamera,
    PycroManagerXYZStage,
    connect_core,
)
from ix83_acquisition.scan_host import StageScanRunner
from ix83_acquisition.scan_host.demo_scanning import (
    CommandedStepDemoEmulator,
    DemoOnlyPreflight,
    TrajectoryMock,
    run_broom_plan,
    run_snap_plan,
)
from ix83_acquisition.scan_host.executor import IX83SearchExecutor


def _boundary(path: Path, frame: str) -> ConfirmedBoundary:
    value = json.loads(path.read_text(encoding="utf-8"))
    observations = tuple(
        CornerObservation(
            tuple(item["corner_xy_um"]),
            item["confirmed"],
            item["confirmation_id"],
            tuple(item["readback_xy_um"]),
        )
        for item in value["corners"]
    )
    boundary_id = str(value.get("boundary_id", f"operator-{time.time_ns()}"))
    if len(observations) == 2:
        return ConfirmedBoundary.from_opposite_corners(
            *observations, coordinate_frame=frame, boundary_id=boundary_id
        )
    return ConfirmedBoundary.from_polygon(
        observations, coordinate_frame=frame, boundary_id=boundary_id
    )


def _capture_boundary(stage, count: int, frame: str) -> ConfirmedBoundary:
    observations = []
    for index in range(count):
        input(
            f"Manually place DEMO stage at boundary corner {index + 1}/{count}, then press Enter: "
        )
        position = stage.position
        xy = (position.x_um, position.y_um)
        confirmation_id = input(f"Confirm readback {xy} um? Type CONFIRM CORNER: ").strip()
        if confirmation_id != "CONFIRM CORNER":
            raise SystemExit("Corner was not confirmed; no scan actions issued.")
        observations.append(CornerObservation(xy, True, f"operator-{time.time_ns()}", xy))
    boundary_id = f"operator-boundary-{time.time_ns()}"
    if count == 2:
        return ConfirmedBoundary.from_opposite_corners(
            *observations, coordinate_frame=frame, boundary_id=boundary_id
        )
    return ConfirmedBoundary.from_polygon(
        tuple(observations), coordinate_frame=frame, boundary_id=boundary_id
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corners",
        type=Path,
        help="JSON operator confirmations with corner and stage-readback XY pairs",
    )
    parser.add_argument(
        "--capture-corners",
        type=int,
        choices=(2, 4),
        help="read current DEMO stage position after manually placing each corner",
    )
    parser.add_argument("--mode", choices=("snap", "broom"), default="snap")
    parser.add_argument("--backend", choices=("mock", "devices"), default="mock")
    parser.add_argument(
        "--port",
        type=int,
        default=4827,
        help="Pycro-Manager Core bridge port for an explicitly selected Demo server",
    )
    parser.add_argument(
        "--footprint-um",
        nargs=2,
        type=float,
        default=(80, 60),
        metavar=("WIDTH", "HEIGHT"),
    )
    parser.add_argument("--overlap", type=float, default=0.1)
    parser.add_argument(
        "--unidirectional",
        action="store_true",
        help="make every broom strip travel in the same direction with bounded flyback",
    )
    parser.add_argument("--exposure-ms", type=float, default=20)
    parser.add_argument("--specimen-id", default="demo-specimen")
    parser.add_argument("--coordinate-frame", default="stage-xy-demo")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = (
        args.output
        or BUNDLE
        / "04_code/ix83_acquisition/recordings/scan_workflow"
        / f"demo-scan-{time.time_ns()}"
    )
    if output.exists():
        parser.error("output must be a new directory")
    if bool(args.corners) == bool(args.capture_corners):
        parser.error("provide exactly one of --corners or --capture-corners")
    if args.capture_corners and args.backend != "devices":
        parser.error("--capture-corners reads a loaded DemoCamera Core; use --backend devices")
    boundary = None if args.capture_corners else _boundary(args.corners, args.coordinate_frame)
    core = None

    def preflight() -> None:
        """Mock backend runs no device preflight; the devices path rebinds this."""

    if args.backend == "mock":
        vertices = boundary.vertices_xy_um
        center = Position(sum(p[0] for p in vertices) / 4, sum(p[1] for p in vertices) / 4, 0.0)
        width_px = 80
        height_px = max(1, round(args.footprint_um[1] / args.footprint_um[0] * width_px))
        stage, camera = (
            MockXYZStage(position=center),
            MockCamera(
                shape_yx=(height_px, width_px),
                pixel_size_um=args.footprint_um[0] / width_px,
            ),
        )
        origin = stage.position
    else:
        core = connect_core(port=args.port, timeout=5000)
        preflight = DemoOnlyPreflight(core)
        preflight()
        stage = PycroManagerXYZStage(core, xy_stage="XYStage", z_stage="ZStage")
        camera = PycroManagerCamera(core)
        origin = stage.position
    prior_exposure = float(core.get_exposure()) if core is not None else None
    if boundary is None:
        try:
            boundary = _capture_boundary(stage, args.capture_corners, args.coordinate_frame)
        except Exception:
            camera.close()
            stage.close()
            raise
    try:
        plan = (
            plan_snap_scan(boundary, tuple(args.footprint_um), args.overlap)
            if args.mode == "snap"
            else plan_broom_scan(
                boundary,
                tuple(args.footprint_um),
                args.overlap,
                serpentine=not args.unidirectional,
            )
        )
    except Exception:
        camera.close()
        stage.close()
        raise
    vertices = boundary.vertices_xy_um
    limits = (
        (min(p[0] for p in vertices), max(p[0] for p in vertices)),
        (min(p[1] for p in vertices), max(p[1] for p in vertices)),
    )
    if any(high - low > 1000 for low, high in limits):
        camera.close()
        stage.close()
        parser.error("DEMO scan envelope must be no wider than 1 mm per XY axis")
    print(
        json.dumps(
            {
                "boundary_id": boundary.boundary_id,
                "boundary_xy_um": vertices,
                "mode": args.mode,
                "backend": args.backend,
                "planned_positions": len(plan.positions)
                if args.mode == "snap"
                else len(plan.strips),
                "whole_footprint_inside": plan.whole_footprint_inside,
                "coverage_claim": plan.coverage_claim,
                "output": str(output),
            },
            indent=2,
        )
    )
    if input("Type EXECUTE DEMO to start this bounded scan: ").strip() != "EXECUTE DEMO":
        camera.close()
        stage.close()
        print("No scan actions issued.")
        return
    confirmation_path = output / "corner_confirmations.json"
    confirmation_path.parent.mkdir(parents=True, exist_ok=False)
    confirmation_path.write_text(
        json.dumps(
            {
                "boundary_id": boundary.boundary_id,
                "coordinate_frame": boundary.coordinate_frame,
                "kind": boundary.kind,
                "corners": [asdict(corner) for corner in boundary.corners],
                "vertices_xy_um": boundary.vertices_xy_um,
            },
            indent=2,
            allow_nan=False,
        ),
        encoding="utf-8",
    )
    if args.mode == "snap":
        executor = IX83SearchExecutor(
            camera,
            stage,
            output / "datasets",
            limits_xy_um=limits,
            fixed_z_um=origin.z_um,
            preflight=preflight,
        )
        try:
            runner = StageScanRunner(
                executor,
                limits_xy_um=limits,
                fixed_z_um=origin.z_um,
                origin_xy_um=(origin.x_um, origin.y_um),
                journal=output / "scan.json",
            )
            run = run_snap_plan(
                runner, plan, specimen_id=args.specimen_id, exposure_ms=args.exposure_ms
            )
            print(
                json.dumps(
                    {
                        "status": run.status.value,
                        "positions": len(run.positions),
                        "journal": str(output / "scan.json"),
                        "errors": run.errors,
                    },
                    indent=2,
                )
            )
        finally:
            executor.close()
            action_unknown = locals().get("run") is not None and any(
                action.status.value == "outcome_unknown" for action in run.actions
            )
            if (
                core is not None
                and locals().get("run") is not None
                and run.status.value != "outcome_unknown"
                and not action_unknown
            ):
                preflight()
                core.set_exposure(prior_exposure)
                if float(core.get_exposure()) != prior_exposure:
                    raise RuntimeError("DemoCamera exposure restoration failed")
        if run.status.value != "completed":
            raise SystemExit(1)
    else:
        backend = (
            TrajectoryMock(
                camera,
                z_um=origin.z_um,
                dataset_root=output / "datasets",
                exposure_ms=args.exposure_ms,
            )
            if args.backend == "mock"
            else CommandedStepDemoEmulator(
                camera,
                stage,
                dataset_root=output / "datasets",
                limits_xy_um=limits,
                exposure_ms=args.exposure_ms,
                preflight=preflight,
            )
        )
        try:
            run = run_broom_plan(
                plan,
                backend=backend,
                journal=output / "scan.json",
                specimen_id=args.specimen_id,
            )
        finally:
            camera.close()
            stage.close()
            if core is not None:
                final_status = locals().get("run", {}).get("status")
                if final_status != "outcome_unknown":
                    preflight()
                    core.set_exposure(prior_exposure)
                    if float(core.get_exposure()) != prior_exposure:
                        raise RuntimeError("DemoCamera exposure restoration failed")
        print(
            json.dumps(
                {
                    "status": run["status"],
                    "capture_mode": run["capture_mode"],
                    "journal": str(output / "scan.json"),
                    "datasets": len(run["datasets"]),
                },
                indent=2,
            )
        )
        if run["status"] != "completed":
            raise SystemExit(1)


if __name__ == "__main__":
    main()
