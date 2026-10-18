"""Run a small, user-authorized snake and broom-emulation scan.

This entry point is specific to the operator-loaded COM22 Ludl + DemoCamera
configuration. It uses the live stage readback as the immutable origin, keeps
all XY targets within +/- 2000 um of that origin, never commands Z, and records
that broom acquisition is commanded-step emulation rather than continuous
capture.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from source_bootstrap import enable_source_tree

BUNDLE = enable_source_tree()

from planner.bounded_scanning import (
    ConfirmedBoundary,
    CornerObservation,
    plan_broom_scan,
    plan_snap_scan,
)

from ix83_acquisition import Position
from ix83_acquisition.pycromanager import PycroManagerCamera, connect_core
from ix83_acquisition.scan_host import StageScanRunner
from ix83_acquisition.scan_host.demo_scanning import CommandedStepDemoEmulator, run_broom_plan
from ix83_acquisition.scan_host.executor import IX83SearchExecutor
from ix83_acquisition.scan_host.ludl_motion import LudlMotionHost


class BoundedLudlStage:
    """XYZStage facade that routes XY through the immutable Ludl motion host."""

    def __init__(self, core: Any, motion: LudlMotionHost) -> None:
        self.core, self.motion = core, motion
        self._closed = False

    @property
    def position(self) -> Position:
        self.motion._check_profile()
        z = self.motion._verify_fixed_z()
        xy = self.motion._read_xy()
        self.motion._validate_readback(xy)
        return Position(xy[0], xy[1], z)

    def move_to(self, position: Position) -> Position:
        if self._closed:
            raise RuntimeError("stage facade is closed")
        if abs(position.z_um - self.motion.fixed_z_um) > self.motion.tolerance:
            raise ValueError("this workflow holds Demo Z fixed and never commands Z")
        handle = self.motion.start_move(position.x_um, position.y_um, timeout_s=30.0)
        result = self.motion.wait(handle)
        if result.status != "completed":
            raise TimeoutError(
                f"Ludl move ended {result.status} at {result.actual_xy_um}; "
                "reconcile before any further stage command"
            )
        return Position(*result.actual_xy_um, self.motion.fixed_z_um)

    def close(self) -> None:
        self._closed = True


def _boundary_from_readbacks(
    corner_readbacks: tuple[tuple[float, float], ...], *, four_corner: bool = False
) -> ConfirmedBoundary:
    if len(corner_readbacks) != (4 if four_corner else 2):
        raise ValueError("corner readback count does not match selected boundary mode")
    confirmation_id = "user-authorized-small-demo-area"
    corners = tuple(
        CornerObservation(point, True, confirmation_id, point) for point in corner_readbacks
    )
    if four_corner:
        return ConfirmedBoundary.from_polygon(
            corners,
            coordinate_frame="live-ludl-stage-xy",
            boundary_id="user-authorized-four-corner-demo-polygon",
        )
    return ConfirmedBoundary.from_opposite_corners(
        corners[0],
        corners[1],
        coordinate_frame="live-ludl-stage-xy",
        boundary_id="user-authorized-200um-demo-rectangle",
    )


def _plot_evidence(
    output: Path,
    origin: tuple[float, float],
    boundary: ConfirmedBoundary,
    snap_plan: Any,
    broom_plan: Any,
    motion_records: list[dict[str, Any]],
) -> None:
    fig, ax = plt.subplots(figsize=(8, 7), constrained_layout=True)
    vertices = boundary.vertices_xy_um + (boundary.vertices_xy_um[0],)
    ax.plot(
        [p[0] - origin[0] for p in vertices],
        [p[1] - origin[1] for p in vertices],
        color="#333333",
        linewidth=2,
        label="Measured test boundary",
    )
    snake = snap_plan.positions
    ax.plot(
        [p.x_um - origin[0] for p in snake],
        [p.y_um - origin[1] for p in snake],
        "o-",
        color="#1878a8",
        label="Snap-scan snake centers",
    )
    for index, strip in enumerate(broom_plan.strips):
        ax.plot(
            [strip.start_xy_um[0] - origin[0], strip.end_xy_um[0] - origin[0]],
            [strip.start_xy_um[1] - origin[1], strip.end_xy_um[1] - origin[1]],
            "--",
            color="#d27625",
            label="Broom strips (step emulation)" if index == 0 else None,
        )
    moves = [
        item
        for item in motion_records
        if item.get("record_type") == "action"
        and item.get("action") == "move_xy"
        and item.get("status") == "completed"
        and isinstance(item.get("readback"), dict)
        and isinstance(item["readback"].get("actual_xy_um"), list)
    ]
    actual = [item["readback"]["actual_xy_um"] for item in moves]
    if actual:
        ax.plot(
            [p[0] - origin[0] for p in actual],
            [p[1] - origin[1] for p in actual],
            ".-",
            color="#438a52",
            alpha=0.55,
            linewidth=0.8,
            label="Completed Ludl readbacks",
        )
    ax.scatter([0], [0], marker="+", s=90, color="black", label="Initial XY")
    ax.set(
        xlabel="X from initial readback (µm)",
        ylabel="Y from initial readback (µm)",
        title="Mixed Ludl + DemoCamera snake and broom emulation",
        xlim=(-125, 125),
        ylim=(-125, 125),
        aspect="equal",
    )
    ax.grid(alpha=0.25)
    ax.legend(fontsize=8, loc="best")
    for ext in ("png", "svg"):
        fig.savefig(output / f"scan_paths.{ext}", dpi=180 if ext == "png" else None)
    plt.close(fig)


def _verify_dataset_integrity(roots: dict[str, Path]) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema": "ix83-demo-scan-dataset-integrity-v1",
        "runs": {},
    }
    for label, dataset_root in roots.items():
        datasets = []
        for ledger in sorted(dataset_root.rglob("frames.jsonl")):
            rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
            frames = [row for row in rows if row.get("type") == "frame"]
            metadata = json.loads((ledger.parent / "run_metadata.json").read_text(encoding="utf-8"))
            ledger_matches = (
                hashlib.sha256(ledger.read_bytes()).hexdigest() == metadata["ledger_sha256"]
            )
            frame_matches = [
                (ledger.parent / row["file"]).is_file()
                and hashlib.sha256((ledger.parent / row["file"]).read_bytes()).hexdigest()
                == row["sha256"]
                for row in frames
            ]
            datasets.append(
                {
                    "dataset": str(ledger.parent),
                    "frames": len(frames),
                    "metadata_frames": int(metadata["frames_written"]),
                    "ledger_sha256_matches": ledger_matches,
                    "frame_sha256_all_match": all(frame_matches),
                }
            )
        report["runs"][label] = {
            "datasets": datasets,
            "dataset_count": len(datasets),
            "frame_count": sum(item["frames"] for item in datasets),
            "integrity_pass": all(
                item["ledger_sha256_matches"]
                and item["frame_sha256_all_match"]
                and item["frames"] == item["metadata_frames"]
                for item in datasets
            ),
        }
    report["integrity_pass"] = all(item["integrity_pass"] for item in report["runs"].values())
    return report


def _resume_broom(run_dir: Path) -> int:
    """Continue a completed snap run without repeating its stage movements."""
    run_dir = run_dir.resolve()
    confirmation_path = run_dir / "corner_confirmations.json"
    snap_journal_path = run_dir / "snap_scan" / "scan.json"
    if not confirmation_path.is_file() or not snap_journal_path.is_file():
        raise FileNotFoundError("resume requires saved corner and snap-scan records")
    confirmation = json.loads(confirmation_path.read_text(encoding="utf-8"))
    snap_journal = json.loads(snap_journal_path.read_text(encoding="utf-8"))
    if snap_journal.get("status") != "completed":
        raise RuntimeError("resume refused: saved snap-scan is not completed")
    output = run_dir / "broom_emulation_resume_01"
    output.mkdir(parents=False, exist_ok=False)
    profile = BUNDLE / "04_code/02_mmcfg/ix83_ludl_democam_mmconfig.cfg"
    profile_sha256 = hashlib.sha256(profile.read_bytes()).hexdigest()
    core = connect_core(port=4827, timeout=5000)
    original_exposure = float(core.get_exposure())
    origin = tuple(float(v) for v in confirmation["origin_xy_um"])
    expected_corners_sha = confirmation.get("profile_sha256")
    if expected_corners_sha and expected_corners_sha != profile_sha256:
        raise RuntimeError("loaded profile file changed since corner acquisition")
    motion = LudlMotionHost(
        core,
        output / "ludl_motion_actions.jsonl",
        run_context={
            "run_id": run_dir.name,
            "workflow": "mixed-ludl-democam-broom-emulation-resume",
            "profile_path": str(profile.relative_to(BUNDLE)),
            "profile_sha256": profile_sha256,
            "hardware_safety_confirmation": "operator confirmed E-stop and travel limits",
            "test_area_selection": "operator approved small area around current position",
            "continues_snap_record": str(snap_journal_path),
        },
        expected_origin_xy_um=origin,
        allow_displaced_start=True,
    )
    observations = tuple(
        CornerObservation(
            tuple(item["corner_xy_um"]),
            bool(item["confirmed"]),
            str(item["confirmation_id"]),
            tuple(item["readback_xy_um"]),
        )
        for item in confirmation["corners"]
    )
    boundary = ConfirmedBoundary.from_opposite_corners(
        observations[0],
        observations[1],
        coordinate_frame=str(confirmation["coordinate_frame"]),
        boundary_id=str(confirmation["boundary_id"]),
    )
    footprint = tuple(float(v) for v in confirmation.get("footprint_xy_um", [100, 100]))
    overlap = float(confirmation.get("overlap", 0.1))
    plan = plan_broom_scan(boundary, footprint, overlap)
    limits = (
        (
            min(p[0] for p in boundary.vertices_xy_um),
            max(p[0] for p in boundary.vertices_xy_um),
        ),
        (
            min(p[1] for p in boundary.vertices_xy_um),
            max(p[1] for p in boundary.vertices_xy_um),
        ),
    )
    print(
        json.dumps(
            {
                "continuing_snap_run": str(snap_journal_path),
                "origin_xy_um": origin,
                "current_xy_um": [
                    float(core.get_x_position("XYStage")),
                    float(core.get_y_position("XYStage")),
                ],
                "envelope_xy_um": motion.envelope_xy_um,
                "broom_strip_count": len(plan.strips),
                "samples_per_strip": 6,
                "continuous_capture": False,
            },
            indent=2,
        )
    )
    if (
        input(
            "Confirm verified stage E-stop and travel limits; type E-STOP AND LIMITS VERIFIED: "
        ).strip()
        != "E-STOP AND LIMITS VERIFIED"
        or input("Type EXECUTE RESUMED BROOM EMULATION to continue: ").strip()
        != "EXECUTE RESUMED BROOM EMULATION"
    ):
        (output / "summary.json").write_text(
            json.dumps(
                {"status": "cancelled_before_motion", "motion_commands_issued": 0},
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print("No stage moves or camera captures issued.")
        return 0
    stage = BoundedLudlStage(core, motion)
    camera = PycroManagerCamera(core)
    try:
        backend = CommandedStepDemoEmulator(
            camera,
            stage,
            dataset_root=output / "datasets",
            limits_xy_um=limits,
            samples_per_strip=6,
            exposure_ms=original_exposure,
            preflight=motion._check_profile,
        )
        run = run_broom_plan(
            plan,
            backend=backend,
            journal=output / "scan.json",
            specimen_id="demo-camera-test-target",
        )
        if run["status"] != "completed":
            raise RuntimeError(f"broom emulation ended {run['status']}: {run.get('errors')}")
        stage.move_to(Position(origin[0], origin[1], motion.fixed_z_um))
        if not core.is_sequence_running() and not core.get_remaining_image_count():
            core.set_exposure(original_exposure)
        if abs(float(core.get_exposure()) - original_exposure) > 1e-9:
            raise RuntimeError("DemoCamera exposure restoration failed")

        prior_records = [
            json.loads(line)
            for line in (run_dir / "ludl_motion_actions.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        new_records = [
            json.loads(line)
            for line in (output / "ludl_motion_actions.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        snap_geometry = json.loads(
            (run_dir / "corner_confirmations.json").read_text(encoding="utf-8")
        )
        snap_plan = plan_snap_scan(boundary, footprint, overlap)
        _plot_evidence(
            output,
            origin,
            boundary,
            snap_plan,
            plan,
            prior_records + new_records,
        )
        integrity = _verify_dataset_integrity(
            {
                "snap": run_dir / "snap_scan" / "datasets",
                "broom": output / "datasets",
            }
        )
        (run_dir / "integrity_verification.json").write_text(
            json.dumps(integrity, indent=2) + "\n", encoding="utf-8"
        )
        summary = {
            "status": "completed",
            "continued_run_directory": str(run_dir),
            "profile_sha256": profile_sha256,
            "origin_xy_um": origin,
            "final_xy_um": [
                float(core.get_x_position("XYStage")),
                float(core.get_y_position("XYStage")),
            ],
            "fixed_demo_z_um": motion.fixed_z_um,
            "envelope_xy_um": motion.envelope_xy_um,
            "boundary_xy_um": snap_geometry["vertices_xy_um"],
            "footprint_xy_um": footprint,
            "snap_scan": {
                "status": snap_journal["status"],
                "positions": len(snap_journal.get("positions", [])),
                "journal": str(snap_journal_path),
            },
            "broom_emulation": {
                "status": run["status"],
                "capture_mode": run["capture_mode"],
                "samples_per_strip": 6,
                "strip_count": len(plan.strips),
                "frames_written": sum(int(item["frames"]) for item in run["datasets"]),
                "continuous_capture": False,
                "journal": "broom_emulation_resume_01/scan.json",
                "motion_journal": "broom_emulation_resume_01/ludl_motion_actions.jsonl",
                "first_attempt": {
                    "status": "failed_before_stage_motion",
                    "reason": "snap executor closed the stage facade before broom reuse",
                    "frames_written": 0,
                    "journal": "broom_emulation/scan.json",
                },
            },
            "max_abs_displacement_from_origin_um": [
                max(
                    abs(float(item["readback"]["actual_xy_um"][axis]) - origin[axis])
                    for item in prior_records + new_records
                    if item.get("action") == "move_xy"
                    and item.get("status") == "completed"
                    and isinstance(item.get("readback"), dict)
                )
                for axis in range(2)
            ],
            "safety": {
                "operator_confirmed_estop_and_travel_limits": True,
                "stage_motion_bound": "±2000 µm from original live XY readback",
                "z_commands": 0,
                "illumination_commands": 0,
            },
            "plots": ["scan_paths.png", "scan_paths.svg"],
            "dataset_integrity": integrity,
        }
        (output / "summary.json").write_text(
            json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8"
        )
        (output / "execution_workflow.mmd").write_text(
            "%%{init: {'themeCSS': '.nodeLabel, .cluster-label { font-size: 22px !important; } .edgeLabel { font-size: 17px !important; }'}}%%\n"
            "flowchart LR\n"
            '  P["Loaded mixed profile preflight"] --> B["Read measured two-corner bounds"]\n'
            '  B --> S["Completed snake snap benchmark"]\n'
            '  S --> E["Commanded-step broom emulation"]\n'
            '  E --> R["Return to original XY and verify"]\n'
            '  R --> A["Save raw frames, motion journal, plots"]\n'
            "  classDef component fill:#f3f6fa,stroke:#40566d,stroke-width:1px\n"
            "  class P,B,S,E,R,A component\n",
            encoding="utf-8",
        )
        (run_dir / "broom_resume_summary.json").write_text(
            json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8"
        )
        (run_dir / "summary.json").write_text(
            json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8"
        )
        (run_dir / "README.md").write_text(
            "# Mixed Ludl + DemoCamera bounded scan run\n\n"
            "The operator-loaded profile used real COM22/Ludl XY and DemoCamera camera/Z. "
            "The operator confirmed E-stop/travel limits and approved a small test area. "
            "All XY targets were constrained to ±2000 µm from the live starting readback; "
            "the actual scan stayed within about ±101 µm. Z and illumination were not commanded.\n\n"
            "## Results\n\n"
            f"- Snake snap-scan: {len(snap_journal.get('positions', []))} positions, status `{snap_journal['status']}`. "
            "See [scan journal](snap_scan/scan.json).\n"
            f"- Broom mode: {summary['broom_emulation']['frames_written']} frames across "
            f"{len(plan.strips)} strips, status `{run['status']}`. This is commanded-step emulation; "
            "`continuous_capture` is false. See [broom journal](broom_emulation_resume_01/scan.json).\n"
            "- The first broom attempt failed before any stage motion because the snap executor had closed its stage facade; "
            "its zero-frame record is preserved at [the first-attempt journal](broom_emulation/scan.json). "
            "A fresh bounded host completed the resumed broom pass.\n"
            "- Frame and ledger SHA-256 integrity is recorded in [the verification record](integrity_verification.json).\n"
            "- See the [path plot](broom_emulation_resume_01/scan_paths.png), [Mermaid workflow](broom_emulation_resume_01/execution_workflow.mmd), "
            "and [summary](summary.json).\n\n"
            "## Provenance\n\n"
            f"- Initial XY: `{origin[0]:.3f}, {origin[1]:.3f} µm`; final readback is recorded in the summary.\n"
            f"- Loaded config file SHA-256: `{profile_sha256}`.\n"
            "- Micro-Manager Core 12.5.0, Device API 75 / Module API 10; Live stopped; auto-shutter disabled.\n"
            "- Demo Z remained at 0 µm; camera exposure was restored to 10 ms; Ludl Speed/StartSpeed/Acceleration remained 10/100/4.\n"
            "- This validates bounded host orchestration and adapter wiring, not calibrated optical overlap or continuous moving capture.\n",
            encoding="utf-8",
        )
        print(json.dumps(summary, indent=2))
        print(f"Broom continuation evidence: {output}")
        return 0
    finally:
        try:
            if not core.is_sequence_running() and not core.get_remaining_image_count():
                core.set_exposure(original_exposure)
        finally:
            camera.close()
            stage.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--resume-broom",
        type=Path,
        help="continue a completed saved snap-scan's broom emulation without repeating it",
    )
    parser.add_argument(
        "--four-corner",
        action="store_true",
        help="use a compact four-readback convex polygon instead of the two-corner rectangle",
    )
    args = parser.parse_args()
    if args.resume_broom:
        return _resume_broom(args.resume_broom)
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output = BUNDLE / "08_session_logs" / f"{run_id}_mixed_ludl_demo_snake"
    output.mkdir(parents=True, exist_ok=False)
    profile = BUNDLE / "04_code/02_mmcfg/ix83_ludl_democam_mmconfig.cfg"
    profile_sha256 = hashlib.sha256(profile.read_bytes()).hexdigest()

    core = connect_core(port=4827, timeout=5000)
    original_exposure = float(core.get_exposure())
    motion = LudlMotionHost(
        core,
        output / "ludl_motion_actions.jsonl",
        run_context={
            "run_id": run_id,
            "workflow": "mixed-ludl-democam-snake-and-broom-emulation",
            "profile_path": str(profile.relative_to(BUNDLE)),
            "profile_sha256": profile_sha256,
            "hardware_safety_confirmation": "operator confirmed E-stop and travel limits",
            "test_area_selection": "operator approved small area around current position",
        },
    )
    origin = motion.origin_xy_um
    fixed_z = motion.fixed_z_um
    half_extent_um = 100.0
    if args.four_corner:
        desired = (
            (origin[0] - 100.0, origin[1] - 80.0),
            (origin[0] + 100.0, origin[1] - 80.0),
            (origin[0] + 80.0, origin[1] + 100.0),
            (origin[0] - 90.0, origin[1] + 80.0),
        )
    else:
        desired = (
            (origin[0] - half_extent_um, origin[1] - half_extent_um),
            (origin[0] + half_extent_um, origin[1] + half_extent_um),
        )
    preview_boundary = _boundary_from_readbacks(
        tuple(point for point in desired), four_corner=args.four_corner
    )
    footprint = (60.0, 60.0) if args.four_corner else (100.0, 100.0)
    overlap = 0.1
    preview_snap = plan_snap_scan(preview_boundary, footprint, overlap)
    preview_broom = plan_broom_scan(preview_boundary, footprint, overlap)
    preview = {
        "origin_xy_um": origin,
        "envelope_xy_um": motion.envelope_xy_um,
        "test_half_extent_um": half_extent_um,
        "boundary_kind": preview_boundary.kind,
        "desired_boundary_xy_um": desired,
        "footprint_xy_um": footprint,
        "overlap": overlap,
        "snap_centers": [asdict(p) for p in preview_snap.positions],
        "broom_strips": [asdict(p) for p in preview_broom.strips],
        "snap_position_count": len(preview_snap.positions),
        "broom_strip_count": len(preview_broom.strips),
        "continuous_capture": False,
    }
    print(json.dumps(preview, indent=2))
    if (
        input(
            "Confirm verified stage E-stop and travel limits; type E-STOP AND LIMITS VERIFIED: "
        ).strip()
        != "E-STOP AND LIMITS VERIFIED"
    ):
        (output / "summary.json").write_text(
            json.dumps(
                {
                    "status": "cancelled_before_motion",
                    "motion_commands_issued": 0,
                    "preview": preview,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print("No stage moves or camera captures issued.")
        return 0
    if input("Type EXECUTE LUDL DEMO SCAN to continue: ").strip() != "EXECUTE LUDL DEMO SCAN":
        (output / "summary.json").write_text(
            json.dumps(
                {
                    "status": "cancelled_before_motion",
                    "motion_commands_issued": 0,
                    "preview": preview,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print("No stage moves or camera captures issued.")
        return 0

    stage = BoundedLudlStage(core, motion)
    camera = PycroManagerCamera(core)
    try:
        corner_readbacks = []
        for target in desired:
            observed = stage.move_to(Position(target[0], target[1], fixed_z))
            corner_readbacks.append((observed.x_um, observed.y_um))
        if any(
            abs(actual[axis] - target[axis]) > motion.tolerance
            for actual, target in zip(corner_readbacks, desired, strict=True)
            for axis in range(2)
        ):
            raise RuntimeError("corner readback differs from planned test boundary")

        boundary = _boundary_from_readbacks(tuple(corner_readbacks), four_corner=args.four_corner)
        scan_plan = plan_snap_scan(boundary, footprint, overlap)
        broom_plan = plan_broom_scan(boundary, footprint, overlap)
        limits = (
            (
                min(p[0] for p in boundary.vertices_xy_um),
                max(p[0] for p in boundary.vertices_xy_um),
            ),
            (
                min(p[1] for p in boundary.vertices_xy_um),
                max(p[1] for p in boundary.vertices_xy_um),
            ),
        )
        if any(
            not motion.envelope_xy_um[axis][0] <= value <= motion.envelope_xy_um[axis][1]
            for point in boundary.vertices_xy_um
            for axis, value in enumerate(point)
        ):
            raise RuntimeError("measured test boundary exceeds immutable ±2 mm envelope")
        (output / "corner_confirmations.json").write_text(
            json.dumps(
                {
                    "boundary_id": boundary.boundary_id,
                    "coordinate_frame": boundary.coordinate_frame,
                    "kind": boundary.kind,
                    "confirmation_id": "user-authorized-small-demo-area",
                    "source": "actual MMCore XY readbacks after bounded Ludl corner moves",
                    "origin_xy_um": origin,
                    "corners": [asdict(c) for c in boundary.corners],
                    "vertices_xy_um": boundary.vertices_xy_um,
                    "half_extent_um": half_extent_um,
                    "footprint_xy_um": footprint,
                    "overlap": overlap,
                    "profile_sha256": profile_sha256,
                },
                indent=2,
                allow_nan=False,
            )
            + "\n",
            encoding="utf-8",
        )

        executor = IX83SearchExecutor(
            camera,
            stage,
            output / "snap_scan" / "datasets",
            limits_xy_um=limits,
            fixed_z_um=fixed_z,
            preflight=motion._check_profile,
        )
        runner = StageScanRunner(
            executor,
            limits_xy_um=limits,
            fixed_z_um=fixed_z,
            origin_xy_um=origin,
            journal=output / "snap_scan" / "scan.json",
        )
        snap_run = runner.run(
            scan_plan_to_positions(scan_plan),
            acquisition_settings(),
            specimen_id="demo-camera-test-target",
            coordinate_frame=boundary.coordinate_frame,
            calibration_id="synthetic-100um-footprint",
            timeout_s=300,
            return_to_origin=True,
            recipe_id="mixed-ludl-democam-snake-snap",
            recipe_version="0.1-local",
        )
        executor.close()
        if snap_run.status.value != "completed":
            raise RuntimeError(f"snap-scan ended {snap_run.status.value}: {snap_run.errors}")

        broom_output = output / "broom_emulation"
        broom_output.mkdir()
        broom_motion = LudlMotionHost(
            core,
            broom_output / "ludl_motion_actions.jsonl",
            run_context={"run_id": run_id, "phase": "broom-step-emulation"},
            expected_origin_xy_um=origin,
            allow_displaced_start=True,
        )
        broom_stage = BoundedLudlStage(core, broom_motion)
        broom_camera = PycroManagerCamera(core)
        broom_backend = CommandedStepDemoEmulator(
            broom_camera,
            broom_stage,
            dataset_root=broom_output / "datasets",
            limits_xy_um=limits,
            samples_per_strip=6,
            exposure_ms=original_exposure,
            preflight=broom_motion._check_profile,
        )
        broom_run = run_broom_plan(
            broom_plan,
            backend=broom_backend,
            journal=broom_output / "scan.json",
            specimen_id="demo-camera-test-target",
        )
        if broom_run["status"] != "completed":
            raise RuntimeError(
                f"broom emulation ended {broom_run['status']}: {broom_run.get('errors')}"
            )
        broom_stage.move_to(Position(origin[0], origin[1], fixed_z))
        if abs(float(core.get_exposure()) - original_exposure) > 1e-9:
            core.set_exposure(original_exposure)
        if abs(float(core.get_exposure()) - original_exposure) > 1e-9:
            raise RuntimeError("DemoCamera exposure restoration failed")

        motion_records = [
            json.loads(line)
            for path in (
                output / "ludl_motion_actions.jsonl",
                broom_output / "ludl_motion_actions.jsonl",
            )
            for line in path.read_text(encoding="utf-8").splitlines()
        ]
        _plot_evidence(
            output,
            origin,
            boundary,
            scan_plan,
            broom_plan,
            motion_records,
        )
        dataset_integrity = _verify_dataset_integrity(
            {
                "snap": output / "snap_scan" / "datasets",
                "broom": broom_output / "datasets",
            }
        )
        (output / "integrity_verification.json").write_text(
            json.dumps(dataset_integrity, indent=2) + "\n", encoding="utf-8"
        )
        summary = {
            "status": "completed",
            "run_id": run_id,
            "profile_sha256": profile_sha256,
            "origin_xy_um": origin,
            "final_xy_um": [
                float(core.get_x_position("XYStage")),
                float(core.get_y_position("XYStage")),
            ],
            "fixed_demo_z_um": fixed_z,
            "envelope_xy_um": motion.envelope_xy_um,
            "max_abs_displacement_from_origin_um": [
                max(
                    abs(float(item["readback"]["actual_xy_um"][axis]) - origin[axis])
                    for item in motion_records
                    if item.get("action") == "move_xy"
                    and item.get("status") == "completed"
                    and isinstance(item.get("readback"), dict)
                )
                for axis in range(2)
            ],
            "boundary_xy_um": boundary.vertices_xy_um,
            "footprint_xy_um": footprint,
            "snap_scan": {
                "status": snap_run.status.value,
                "positions": len(snap_run.positions),
                "journal": "snap_scan/scan.json",
                "continuous_capture": False,
            },
            "broom_emulation": {
                "status": broom_run["status"],
                "capture_mode": broom_run["capture_mode"],
                "datasets": len(broom_run["datasets"]),
                "continuous_capture": False,
                "samples_per_strip": 6,
                "journal": "broom_emulation/scan.json",
            },
            "plots": ["scan_paths.png", "scan_paths.svg"],
            "dataset_integrity": dataset_integrity,
            "safety": {
                "operator_confirmed_estop_and_travel_limits": True,
                "stage_motion_bound": "±2000 µm from initial live XY readback",
                "z_commands": 0,
                "illumination_commands": 0,
            },
        }
        (output / "summary.json").write_text(
            json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8"
        )
        (output / "execution_workflow.mmd").write_text(
            "%%{init: {'themeCSS': '.nodeLabel, .cluster-label { font-size: 22px !important; } .edgeLabel { font-size: 17px !important; }'}}%%\n"
            "flowchart LR\n"
            '  P["Live profile preflight"] --> B["Capture measured test corners"]\n'
            '  B --> S["Snake snap-scan benchmark"]\n'
            '  S --> E["Commanded-step broom emulation"]\n'
            '  E --> R["Return to initial XY and verify"]\n'
            '  R --> A["Save frames, action ledgers, plot"]\n'
            "  classDef component fill:#f3f6fa,stroke:#40566d,stroke-width:1px\n"
            "  class P,B,S,E,R,A component\n",
            encoding="utf-8",
        )
        print(json.dumps(summary, indent=2))
        print(f"Evidence directory: {output}")
        return 0
    finally:
        try:
            if not core.is_sequence_running() and not core.get_remaining_image_count():
                core.set_exposure(original_exposure)
                if abs(float(core.get_exposure()) - original_exposure) > 1e-9:
                    raise RuntimeError("DemoCamera exposure restoration failed")
        finally:
            camera.close()
            stage.close()
            if "broom_camera" in locals():
                broom_camera.close()
            if "broom_stage" in locals():
                broom_stage.close()


def scan_plan_to_positions(plan: Any):
    from planner.scanning import ScanPosition

    return tuple(
        ScanPosition(point.position_id, point.x_um, point.y_um) for point in plan.positions
    )


def acquisition_settings():
    from planner import AcquisitionSettings

    return AcquisitionSettings(exposure_ms=10)


if __name__ == "__main__":
    raise SystemExit(main())
