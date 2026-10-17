from __future__ import annotations

import json
import sys
from pathlib import Path

import demo_scan_workflow
import pytest
from planner.bounded_scanning import (
    ConfirmedBoundary,
    CornerObservation,
    plan_broom_scan,
    plan_snap_scan,
)

from ix83_acquisition import MockCamera, MockXYZStage, Position, replay_frames
from ix83_acquisition.scan_host import (
    StageScanRunner,
    dataset_reference_from_record,
    local_dataset_path,
)
from ix83_acquisition.scan_host.demo_scanning import (
    CommandedStepDemoEmulator,
    DemoOnlyPreflight,
    TrajectoryMock,
    run_broom_plan,
    run_snap_plan,
)
from ix83_acquisition.scan_host.executor import IX83SearchExecutor


def boundary():
    return ConfirmedBoundary.from_opposite_corners(
        CornerObservation((0, 0), True, "op-a", (0, 0)),
        CornerObservation((160, 160), True, "op-b", (160, 160)),
        coordinate_frame="stage-xy",
        boundary_id="demo-bounds",
    )


def test_cli_final_confirmation_gate_issues_no_actions(tmp_path: Path, monkeypatch):
    corners = tmp_path / "corners.json"
    corners.write_text(
        json.dumps(
            {
                "boundary_id": "gate",
                "corners": [
                    {
                        "corner_xy_um": [0, 0],
                        "confirmed": True,
                        "confirmation_id": "a",
                        "readback_xy_um": [0, 0],
                    },
                    {
                        "corner_xy_um": [160, 160],
                        "confirmed": True,
                        "confirmation_id": "b",
                        "readback_xy_um": [160, 160],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "not-started"
    monkeypatch.setattr(
        sys,
        "argv",
        ["demo_scan_workflow.py", "--corners", str(corners), "--output", str(output)],
    )
    monkeypatch.setattr("builtins.input", lambda _prompt="": "no")
    demo_scan_workflow.main()
    assert not output.exists()


class FakeCore:
    def __init__(self, libraries=None, live=False):
        self.devices = {
            "DHub": "DemoCamera",
            "Camera": "DemoCamera",
            "XYStage": "DemoCamera",
            "ZStage": "DemoCamera",
        }
        self.devices.update(libraries or {})
        self.live = live

    def is_sequence_running(self):
        return self.live

    def get_remaining_image_count(self):
        return 0

    def get_loaded_devices(self):
        return list(self.devices)

    def get_device_library(self, label):
        return self.devices[label]

    def get_device_name(self, label):
        return "Demo" + label

    def get_camera_device(self):
        return "Camera"

    def get_xy_stage_device(self):
        return "XYStage"

    def get_focus_device(self):
        return "ZStage"

    def get_auto_shutter(self):
        return False

    def get_shutter_device(self):
        return ""


def test_demo_preflight_accepts_only_demo_devices_and_requires_live_off():
    DemoOnlyPreflight(FakeCore())()
    with pytest.raises(RuntimeError, match="every loaded device"):
        DemoOnlyPreflight(FakeCore({"RealCamera": "PVCAM"}))()
    with pytest.raises(RuntimeError, match="stop MMStudio Live"):
        DemoOnlyPreflight(FakeCore(live=True))()


def test_snap_runner_records_bounded_snake_and_raw_frames(tmp_path: Path, monkeypatch):
    original_replace = Path.replace
    scan_journal_replace_attempts = 0

    def replace_after_temporary_sharing_error(path: Path, target: Path):
        nonlocal scan_journal_replace_attempts
        if path.name == "scan.json.tmp":
            scan_journal_replace_attempts += 1
            if scan_journal_replace_attempts == 1:
                raise PermissionError("temporary Windows sharing violation")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", replace_after_temporary_sharing_error)
    plan = plan_snap_scan(boundary(), (80, 80), 0.1)
    stage = MockXYZStage(Position(80, 80, 0))
    camera = MockCamera(shape_yx=(32, 32), pixel_size_um=2.5)
    output = tmp_path / "datasets"
    executor = IX83SearchExecutor(
        camera, stage, output, limits_xy_um=((0, 160), (0, 160)), fixed_z_um=0
    )
    runner = StageScanRunner(
        executor,
        limits_xy_um=((0, 160), (0, 160)),
        fixed_z_um=0,
        origin_xy_um=(80, 80),
        journal=tmp_path / "scan.json",
    )
    run = run_snap_plan(runner, plan, specimen_id="fake", exposure_ms=1)
    assert run.status.value == "completed"
    assert scan_journal_replace_attempts > 1
    assert len(run.positions) == len(plan.positions)
    journal = json.loads((tmp_path / "scan.json").read_text())
    assert journal["actions"]
    assert all(action["request_id"] for action in journal["actions"])
    reference = dataset_reference_from_record(run.positions[0]["data_reference"])
    assert sum(1 for _ in replay_frames(local_dataset_path(reference))) == 1
    executor.close()


def test_broom_mock_persists_trajectory_datasets_and_rejects_other_backend(
    tmp_path: Path,
):
    plan = plan_broom_scan(boundary(), (80, 80), 0.1)
    camera = MockCamera(shape_yx=(24, 24), pixel_size_um=3)
    backend = TrajectoryMock(
        camera,
        z_um=0,
        dataset_root=tmp_path / "datasets",
        samples_per_strip=3,
        exposure_ms=1,
    )
    with pytest.raises(RuntimeError, match="lacks declared capture/emulation"):
        run_broom_plan(plan, backend=object(), journal=tmp_path / "rejected.json")
    run = run_broom_plan(plan, backend=backend, journal=tmp_path / "broom.json")
    assert run["status"] == "completed"
    assert run["capture_mode"] == "trajectory-mock-emulation"
    assert len(run["datasets"]) == len(plan.strips)
    first = Path(run["datasets"][0]["dataset"])
    assert len(list(replay_frames(first))) == 3
    assert json.loads((tmp_path / "broom.json").read_text())["actions"][0]["status"] == "completed"


def test_cancelled_broom_keeps_replayable_prefix_and_action_outcome(tmp_path: Path):
    plan = plan_broom_scan(boundary(), (80, 80), 0.1)
    backend = TrajectoryMock(
        MockCamera(shape_yx=(24, 24), pixel_size_um=3),
        z_um=0,
        dataset_root=tmp_path / "datasets",
        samples_per_strip=4,
        exposure_ms=1,
    )
    checks = iter((False, False, False, True))
    run = run_broom_plan(
        plan,
        backend=backend,
        journal=tmp_path / "cancelled.json",
        cancelled=lambda: next(checks, True),
    )
    assert run["status"] == "cancelled"
    first_action = run["actions"][0]
    assert first_action["status"] == "cancelled"
    dataset = Path(first_action["readback"]["dataset"])
    assert len(list(replay_frames(dataset))) == 2
    assert (
        json.loads((tmp_path / "cancelled.json").read_text())["actions"][0]["events"][-1]["status"]
        == "cancelled"
    )


def test_broom_timeout_is_durable_as_unknown_without_retry(tmp_path: Path):
    plan = plan_broom_scan(boundary(), (80, 80), 0.1)

    class TimeoutBackend:
        trajectory_capture = True
        capture_mode = "timeout-test"
        continuous_capture = False

        def capture_trajectory(self, *args, **kwargs):
            raise TimeoutError("capture acknowledgement lost")

    run = run_broom_plan(plan, backend=TimeoutBackend(), journal=tmp_path / "unknown.json")
    assert run["status"] == "outcome_unknown"
    assert run["actions"][0]["status"] == "outcome_unknown"
    assert len(run["actions"]) == 1


def test_demo_broom_emulation_records_each_commanded_readback_separately(
    tmp_path: Path,
):
    plan = plan_broom_scan(boundary(), (80, 80), 0.1)
    stage = MockXYZStage(Position(80, 80, 0))
    camera = MockCamera(shape_yx=(24, 24), pixel_size_um=3)
    backend = CommandedStepDemoEmulator(
        camera,
        stage,
        dataset_root=tmp_path / "datasets",
        limits_xy_um=((0, 160), (0, 160)),
        samples_per_strip=3,
        exposure_ms=1,
    )
    run = run_broom_plan(plan, backend=backend, journal=tmp_path / "demo-broom.json")
    assert run["status"] == "completed"
    assert run["capture_mode"] == "demo-commanded-step-emulation"
    assert run["capabilities"] == {"continuous_capture": False, "broom_emulation": True}
    first_action = run["actions"][0]
    assert len(first_action["readback"]["samples"]) == 3
    assert first_action["readback"]["samples"][0]["readback_xyz_um"][:2] == list(
        first_action["start_xy_um"]
    )


def test_broom_plan_keeps_all_strip_endpoints_in_footprint_safe_polygon():
    plan = plan_broom_scan(boundary(), (80, 80), 0.1)
    assert plan.whole_footprint_inside
    assert len(plan.travel_xy_um) == 2 * len(plan.strips)
    assert "edge fill is not claimed" in plan.coverage_claim
