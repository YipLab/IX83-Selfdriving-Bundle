from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
from bluesky import RunEngine
from planner import AcquisitionSettings, build_grid_recipe
from planner.bounded_scanning import (
    ConfirmedBoundary,
    CornerObservation,
    plan_snap_scan,
)
from planner.plans import snap_scan_plan

from ix83_acquisition.pycromanager_bluesky import (
    PycroManagerSnapDetector,
    PycroManagerXYPositioner,
    pycromanager_hand_eye_calibration_plan,
    validate_snap_bindings,
)


class FakeCore:
    def __init__(self) -> None:
        self.x_um = 0.0
        self.y_um = 0.0
        self.z_um = 3.0
        self.moves: list[tuple[float, float]] = []
        self.exposure_ms = 10.0
        self.frame_number = 0
        self.tagged = None

    def get_xy_stage_device(self):
        return "XYStage"

    def get_x_position(self, label):
        assert label == "XYStage"
        return self.x_um

    def get_y_position(self, label):
        assert label == "XYStage"
        return self.y_um

    def get_position(self, label):
        assert label == "ZStage"
        return self.z_um

    def set_xy_position(self, x_um, y_um):
        self.x_um, self.y_um = float(x_um), float(y_um)
        self.moves.append((self.x_um, self.y_um))

    def wait_for_device(self, label):
        assert label == "XYStage"

    def device_busy(self, label):
        assert label == "XYStage"
        return False

    def is_sequence_running(self):
        return False

    def get_remaining_image_count(self):
        return 0

    def set_exposure(self, exposure_ms):
        self.exposure_ms = exposure_ms

    def get_exposure(self):
        return self.exposure_ms

    def snap_image(self):
        self.frame_number += 1
        self.tagged = SimpleNamespace(
            pix=np.full((8, 8), self.frame_number, dtype=np.uint16),
            tags={"Height": 8, "Width": 8},
        )

    def get_tagged_image(self):
        return self.tagged


def test_runengine_snap_plan_records_bounded_atomic_xy_and_frame_context():
    core = FakeCore()
    preflight_calls = []

    def preflight():
        preflight_calls.append(True)

    stage = PycroManagerXYPositioner(
        core,
        xy_stage="XYStage",
        limits_xy_um=((-10, 40), (-10, 40)),
        readback_tolerance_um=0.01,
        preflight=preflight,
    )
    camera = PycroManagerSnapDetector(
        core,
        stage,
        z_stage="ZStage",
        exposure_ms=10,
        shape_yx=(8, 8),
        dtype="uint16",
        preflight=preflight,
    )
    recipe = build_grid_recipe(
        (0, 0),
        specimen_id="bounded-fake-core",
        rows=1,
        columns=2,
        step_xy_um=(25, 25),
        settings=AcquisitionSettings(exposure_ms=10, frames=1),
    )
    validate_snap_bindings(recipe, stage=stage, camera=camera)
    documents = []
    engine = RunEngine({})
    engine.subscribe(lambda name, doc: documents.append((name, doc)))

    engine(
        snap_scan_plan(
            recipe,
            stage_xy=stage,
            camera=camera,
            readables=(stage,),
        )
    )

    events = [doc for name, doc in documents if name == "event"]
    stop = next(doc for name, doc in documents if name == "stop")
    assert stop["exit_status"] == "success"
    assert core.moves == [(0.0, 0.0), (25.0, 0.0)]
    assert len(preflight_calls) >= 4
    assert [event["data"]["stage_x_um"] for event in events] == [0.0, 25.0]
    assert [event["data"]["stage_y_um"] for event in events] == [0.0, 0.0]
    assert [event["data"]["stage_x_pre_snap_um"] for event in events] == [0.0, 25.0]
    assert [event["data"]["frame_id"] for event in events] == [0, 1]
    assert all(
        event["data"]["snap_result_received_host_ns"] >= event["data"]["snap_request_start_host_ns"]
        for event in events
    )
    for event in events:
        start_ns = event["data"]["stage_x_readback_call_start_host_ns"]
        end_ns = event["data"]["stage_x_readback_call_end_host_ns"]
        assert end_ns >= start_ns
        assert event["data"]["snap_request_start_host_ns"] >= end_ns
        assert event["timestamps"]["stage_x_pre_snap_um"] == (start_ns + end_ns) // 2 / 1e9
    assert all(event["data"]["image"].shape == (8, 8) for event in events)


def test_runengine_hand_eye_plan_uses_atomic_xy_and_records_probe_readbacks():
    core = FakeCore()
    stage = PycroManagerXYPositioner(
        core,
        xy_stage="XYStage",
        limits_xy_um=((-2_000, 2_000), (-2_000, 2_000)),
        readback_tolerance_um=0.01,
    )
    camera = PycroManagerSnapDetector(
        core,
        stage,
        z_stage="ZStage",
        exposure_ms=10,
        shape_yx=(8, 8),
        dtype="uint16",
    )
    plan = pycromanager_hand_eye_calibration_plan(
        anchor_xy_um=(0, 0),
        stage=stage,
        camera=camera,
        coordinate_frame="ix83-stage-xy",
        mode_context={
            "profile_revision": "operator-loaded-demo",
            "camera": "DemoCamera",
            "objective": "10x",
            "binning": "2x2",
            "roi": "full",
        },
    )
    assert core.moves == []  # Binding/preflight is read-only until RE submission.
    documents = []
    engine = RunEngine({})
    engine.subscribe(lambda name, doc: documents.append((name, doc)))
    engine(plan)

    events = [doc for name, doc in documents if name == "event"]
    start = next(doc for name, doc in documents if name == "start")
    assert len(events) == 10
    assert len(core.moves) == 10
    assert max(abs(x) for x, _y in core.moves) <= 10
    assert max(abs(y) for _x, y in core.moves) <= 10
    assert events[0]["data"]["stage_x_um"] == 0
    assert events[2]["data"]["stage_x_um"] == 10
    assert events[6]["data"]["stage_y_um"] == 10
    assert start["planner_calibration_mode_context"] == {
        "binning": "2x2",
        "camera": "DemoCamera",
        "objective": "10x",
        "profile_revision": "operator-loaded-demo",
        "roi": "full",
        "registration_preprocessing": "none",
        "registration_roi_yxhw_px": "full-frame",
    }
    assert core.exposure_ms == 10


def test_hand_eye_binding_rejects_probe_outside_two_mm_envelope_before_motion():
    core = FakeCore()
    stage = PycroManagerXYPositioner(
        core,
        xy_stage="XYStage",
        limits_xy_um=((-2_500, 2_500), (-2_500, 2_500)),
        readback_tolerance_um=0.01,
    )
    camera = PycroManagerSnapDetector(
        core,
        stage,
        z_stage="ZStage",
        exposure_ms=10,
        shape_yx=(8, 8),
        dtype="uint16",
        configure_exposure=False,
    )
    with pytest.raises(ValueError, match="authorized ±2 mm"):
        pycromanager_hand_eye_calibration_plan(
            anchor_xy_um=(0, 0),
            stage=stage,
            camera=camera,
            coordinate_frame="ix83-stage-xy",
            mode_context={
                "profile_revision": "test",
                "camera": "DemoCamera",
                "objective": "10x",
                "binning": "2x2",
                "roi": "full",
            },
            x_probe_um=2_000.1,
        )
    assert core.moves == []


def test_hand_eye_read_only_exposure_mismatch_blocks_before_motion():
    core = FakeCore()
    stage = PycroManagerXYPositioner(
        core,
        xy_stage="XYStage",
        limits_xy_um=((-2_000, 2_000), (-2_000, 2_000)),
        readback_tolerance_um=0.01,
    )
    camera = PycroManagerSnapDetector(
        core,
        stage,
        z_stage="ZStage",
        exposure_ms=20,
        shape_yx=(8, 8),
        dtype="uint16",
        configure_exposure=False,
    )
    with pytest.raises(ValueError, match="read-only calibration expects 20 ms"):
        pycromanager_hand_eye_calibration_plan(
            anchor_xy_um=(0, 0),
            stage=stage,
            camera=camera,
            coordinate_frame="ix83-stage-xy",
            mode_context={
                "profile_revision": "test",
                "camera": "DemoCamera",
                "objective": "10x",
                "binning": "2x2",
                "roi": "full",
            },
        )
    assert core.moves == []


def test_recipe_bounds_are_checked_before_runengine_or_core_motion():
    core = FakeCore()
    stage = PycroManagerXYPositioner(
        core,
        xy_stage="XYStage",
        limits_xy_um=((-10, 40), (-10, 40)),
        readback_tolerance_um=0.01,
    )
    camera = PycroManagerSnapDetector(
        core,
        stage,
        z_stage="ZStage",
        exposure_ms=10,
        shape_yx=(8, 8),
        dtype="uint16",
    )
    recipe = build_grid_recipe(
        (0, 0),
        specimen_id="out-of-bounds",
        rows=1,
        columns=3,
        step_xy_um=(25, 25),
        settings=AcquisitionSettings(exposure_ms=10, frames=1),
    )
    with pytest.raises(ValueError, match="outside loaded limits"):
        validate_snap_bindings(recipe, stage=stage, camera=camera)
    assert core.moves == []


def test_four_corner_snake_plan_runs_through_bounded_pycromanager_binding():
    core = FakeCore()
    corners = tuple(
        CornerObservation(point, True, f"corner-{index}", point)
        for index, point in enumerate(((0, 0), (30, 0), (30, 20), (0, 20)))
    )
    boundary = ConfirmedBoundary.from_polygon(
        corners, coordinate_frame="stage-xy", boundary_id="four-corner-demo"
    )
    recipe = plan_snap_scan(boundary, (10, 10), 0.5)
    stage = PycroManagerXYPositioner(
        core,
        xy_stage="XYStage",
        limits_xy_um=((-2_000, 2_000), (-2_000, 2_000)),
        readback_tolerance_um=0.01,
    )
    camera = PycroManagerSnapDetector(
        core,
        stage,
        z_stage="ZStage",
        exposure_ms=10,
        shape_yx=(8, 8),
        dtype="uint16",
    )
    validate_snap_bindings(recipe, stage=stage, camera=camera)
    documents = []
    engine = RunEngine({})
    engine.subscribe(lambda name, doc: documents.append((name, doc)))
    engine(
        snap_scan_plan(
            recipe,
            stage_xy=stage,
            camera=camera,
            readables=(stage,),
        )
    )
    events = [doc for name, doc in documents if name == "event"]
    start = next(doc for name, doc in documents if name == "start")
    assert len(events) == len(recipe.positions)
    assert len(core.moves) == len(recipe.positions)
    assert [start["planner_event_position_ids"][event["seq_num"] - 1] for event in events] == [
        position.position_id for position in recipe.positions
    ]


def test_xy_adapter_rejects_out_of_bounds_before_core_command():
    core = FakeCore()
    stage = PycroManagerXYPositioner(
        core,
        xy_stage="XYStage",
        limits_xy_um=((-2_000, 2_000), (-2_000, 2_000)),
        readback_tolerance_um=0.01,
    )
    status = stage.set((2_000.1, 0.0))
    with pytest.raises(ValueError, match="outside limits"):
        status.wait(timeout=1)
    assert core.moves == []


def test_ambiguous_core_move_requires_stable_reconciliation_before_retry():
    class AmbiguousCore(FakeCore):
        def set_xy_position(self, x_um, y_um):
            super().set_xy_position(x_um, y_um)
            raise TimeoutError("Core response timed out after move may have started")

    core = AmbiguousCore()
    stage = PycroManagerXYPositioner(
        core,
        xy_stage="XYStage",
        limits_xy_um=((-100, 100), (-100, 100)),
        readback_tolerance_um=0.01,
    )
    with pytest.raises(TimeoutError, match="may have started"):
        stage.set((20, 30)).wait(timeout=1)
    assert stage.motion_unresolved
    assert core.moves == [(20.0, 30.0)]

    with pytest.raises(RuntimeError, match="reconcile"):
        stage.set((40, 50)).wait(timeout=1)
    assert core.moves == [(20.0, 30.0)]

    actual = stage.reconcile(timeout_s=1)
    assert actual == (20.0, 30.0)
    assert not stage.motion_unresolved
    assert core.moves == [(20.0, 30.0)]
