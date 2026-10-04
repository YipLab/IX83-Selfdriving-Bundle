from dataclasses import replace
from datetime import datetime, timezone

from ix83_search_host import AcquisitionResult, SampleSearchRunner
from samplescout import (
    AcquisitionSettings,
    ActionStatus,
    Calibration,
    DetectedObject,
    Phase,
    Region,
    RunStatus,
    WorkflowRecipe,
    load_replay,
    replay_targets,
    save_replay,
    save_run,
)


class MockBackend:
    def __init__(self, *, missing=False, fail_after=None):
        self.events = []
        self.missing = missing
        self.fail_after = fail_after

    def move_to(self, request_id, position_xyz_um, *, deadline=None):
        self.events.append(("move", position_xyz_um))
        return position_xyz_um

    def acquire(self, request_id, settings, *, phase, specimen_id, coordinate_frame,
                calibration_id, run_id, tile_id, target_id, deadline=None):
        self.events.append(("acquire", phase, tile_id))
        if self.fail_after is not None and len(self.events) >= self.fail_after:
            raise RuntimeError("camera failure")
        now = datetime.now(timezone.utc)
        image = None if self.missing is True else ("blank" if self.missing == "blank" else tile_id)
        return AcquisitionResult(image, (self.events[-2][1][0], self.events[-2][1][1]), now,
                                data_reference=f"data://{tile_id}" if image is not None else None)


def setup(backend, *, cancelled=lambda: False, review=None):
    cal = Calibration("cal", "stage-xy", ((1, 0), (0, 1)), (5, 5), (0, 0))
    settings = AcquisitionSettings()
    recipe = WorkflowRecipe("search", "0.1", "sample-1", "stage-xy", "cal", settings, settings,
                            (10, 10), overlap=0.2, deduplication_um=2, max_targets=3)

    def detector(image, observation):
        # A seeded world-space object at (2, 2), visible in the field around tile (5, 5).
        if image == "blank":
            return []
        px = 2 - observation.stage_xy_um[0] + 5
        py = 2 - observation.stage_xy_um[1] + 5
        return [DetectedObject(px, py, 5)] if 0 <= px < 10 and 0 <= py < 10 else []

    return SampleSearchRunner(backend, detector, recipe, cal, Region(0, 0, 20, 20),
                              cancelled=cancelled, review=review)


def test_runner_finishes_survey_before_detection_then_revisits_targets():
    backend = MockBackend()
    runner = setup(backend)
    run = runner.run()
    assert run.status is RunStatus.COMPLETED
    phases = [e[1] for e in backend.events if e[0] == "acquire"]
    first_revisit = phases.index(Phase.REVISIT)
    assert all(p is Phase.SURVEY for p in phases[:first_revisit])
    assert run.targets
    terminal = {}
    for action in run.actions:
        if action.action == "acquire":
            terminal[action.request_id] = action.status
    assert all(status is ActionStatus.COMPLETED for status in terminal.values())
    assert all(o.run_id == run.run_id for o in run.observations)


def test_missing_data_is_failed_but_a_valid_blank_survey_is_empty():
    missing = setup(MockBackend(missing=True)).run()
    assert missing.status is RunStatus.FAILED
    assert any("without image data" in e for e in missing.errors)
    assert missing.observations and missing.observations[0].missing

    blank = setup(MockBackend(missing="blank")).run()
    assert blank.status is RunStatus.EMPTY

    failed = setup(MockBackend(fail_after=2)).run()
    assert failed.status is RunStatus.FAILED
    assert failed.errors
    assert any(a.status is ActionStatus.FAILED for a in failed.actions)


def test_failed_second_revisit_retains_first_completed_dataset_observation():
    class FailingSecondRevisit(MockBackend):
        revisits = 0

        def acquire(self, request_id, settings, **kwargs):
            if kwargs["phase"] is Phase.REVISIT:
                self.revisits += 1
                if self.revisits == 2:
                    raise RuntimeError("second movie failed")
            return super().acquire(request_id, settings, **kwargs)

    runner = setup(FailingSecondRevisit())
    runner.region = Region(0, 0, 10, 10)
    runner.detector = lambda _image, _obs: [DetectedObject(3, 3), DetectedObject(7, 7)]
    run = runner.run()
    assert run.status is RunStatus.FAILED
    assert len(run.targets) == 2
    revisits = [obs for obs in run.observations if obs.phase is Phase.REVISIT]
    assert len(revisits) == 1
    assert revisits[0].data_reference is not None
    assert all(a.finished_at is not None for a in run.actions if a.status is ActionStatus.COMPLETED)


def test_saved_detection_replay_reproduces_selected_targets(tmp_path):
    runner = setup(MockBackend())
    run = runner.run()
    detections = [o for o in run.observations if o.phase is Phase.DETECTION]
    path = tmp_path / "replay.json"
    save_replay(path, detections)
    loaded = load_replay(path)
    targets = replay_targets(loaded, runner.calibration, runner.region,
                             distance_um=runner.recipe.deduplication_um,
                             max_targets=runner.recipe.max_targets)
    assert [(t.target_id, t.x_um, t.y_um) for t in targets] == [
        (t.target_id, t.x_um, t.y_um) for t in run.targets
    ]
    snapshot = tmp_path / "run.json"
    save_run(snapshot, run, runner.recipe, runner.calibration, runner.region)
    payload = __import__("json").loads(snapshot.read_text(encoding="utf-8"))
    assert payload["schema"] == "samplescout-run-v1"
    assert payload["run"]["run_id"] == run.run_id
    assert payload["observations"]
    assert all("image" not in action.get("readback", {}) for action in payload["actions"]
               if isinstance(action.get("readback"), dict))


def test_cancellation_is_distinct_and_deadline_is_passed_to_backend():
    cancelled = setup(MockBackend(), cancelled=lambda: True).run()
    assert cancelled.status is RunStatus.CANCELLED


def test_backend_timeout_is_outcome_unknown_and_is_not_retried():
    class TimeoutBackend(MockBackend):
        attempts = 0

        def acquire(self, *args, **kwargs):
            self.attempts += 1
            raise TimeoutError("camera acknowledgement timed out")

    backend = TimeoutBackend()
    run = setup(backend).run()
    assert run.status is RunStatus.OUTCOME_UNKNOWN
    assert backend.attempts == 1
    acquire_records = [action for action in run.actions if action.action == "acquire"]
    assert acquire_records[-1].status is ActionStatus.OUTCOME_UNKNOWN
    assert acquire_records[-1].request_id == acquire_records[0].request_id


def test_capability_and_explicit_resource_preflight_happens_before_motion():
    backend = MockBackend()
    runner = setup(backend)
    runner.recipe = replace(runner.recipe, required_capabilities=frozenset({"camera.sequence"}))
    result = runner.run()
    assert result.status is RunStatus.FAILED
    assert "does not declare capabilities" in result.errors[0]
    assert backend.events == []

    backend = MockBackend()
    runner = setup(backend)
    runner.recipe = replace(runner.recipe, resources=runner.recipe.resources + (replace(runner.recipe.resources[0], name="fluidics"),))
    result = runner.run()
    assert result.status is RunStatus.FAILED
    assert "does not declare explicitly requested resources" in result.errors[0]
    assert backend.events == []


def test_backend_capabilities_and_resources_are_checked_before_actions():
    backend = MockBackend()
    backend.capabilities = frozenset({"stage.xy", "camera.snap"})
    backend.resources = frozenset({"stage", "camera"})
    runner = setup(backend)
    runner.recipe = replace(runner.recipe, required_capabilities=frozenset({"stage.xy", "camera.sequence"}))
    result = runner.run()
    assert result.status is RunStatus.FAILED
    assert "camera.sequence" in result.errors[0]
    assert backend.events == []


def test_review_can_select_targets_but_cannot_change_their_physical_coordinates():
    runner = setup(MockBackend(), review=lambda targets: [replace(targets[0], x_um=999.0)])
    result = runner.run()
    assert result.status is RunStatus.COMPLETED
    assert result.targets[0].x_um != 999.0
    revisit = next(obs for obs in result.observations if obs.phase is Phase.REVISIT)
    assert abs(revisit.stage_xy_um[0] - result.targets[0].x_um) < 1.0
    assert all(abs(event[1][0] - 999.0) > 1.0 for event in runner.backend.events if event[0] == "move")


def test_acquisition_settings_reject_invalid_typed_values():
    import pytest

    for kwargs in (
        {"exposure_ms": float("nan")}, {"exposure_ms": True}, {"frames": True},
        {"frames": 1.5}, {"image_shape_yx": (10,)}, {"image_shape_yx": (10, False)},
        {"roi_origin": (0,)}, {"binning": (True, 1)},
    ):
        with pytest.raises(ValueError):
            AcquisitionSettings(**kwargs)


def test_full_roi_or_binning_requires_matching_full_calibration():
    import pytest

    runner = setup(MockBackend())
    full = replace(runner.recipe.full_settings, roi_origin=(4.0, 0.0), binning=(1.0, 1.0))
    runner.recipe = replace(runner.recipe, full_settings=full)
    with pytest.raises(ValueError, match="provide full_calibration"):
        SampleSearchRunner(runner.backend, runner.detector, runner.recipe, runner.calibration, runner.region)

    wrong = replace(runner.calibration, roi_origin=(8.0, 0.0))
    with pytest.raises(ValueError, match="full settings ROI"):
        SampleSearchRunner(runner.backend, runner.detector, runner.recipe, runner.calibration,
                           runner.region, full_calibration=wrong)


def test_sequence_setting_requires_declared_camera_sequence_capability():
    backend = MockBackend()
    runner = setup(backend)
    runner.recipe = replace(runner.recipe, survey_settings=replace(runner.recipe.survey_settings, frames=3))
    result = runner.run()
    assert result.status is RunStatus.FAILED
    assert "camera.sequence" in result.errors[0]
    assert backend.events == []


def test_settings_calibration_metadata_must_match_calibration():
    import pytest

    runner = setup(MockBackend())
    survey = replace(runner.recipe.survey_settings, metadata={"calibration_id": "wrong"})
    with pytest.raises(ValueError, match="survey settings calibration_id"):
        SampleSearchRunner(runner.backend, runner.detector, replace(runner.recipe, survey_settings=survey),
                           runner.calibration, runner.region)
    full = replace(runner.recipe.full_settings, metadata={"calibration_id": "wrong"})
    with pytest.raises(ValueError, match="full settings calibration_id"):
        SampleSearchRunner(runner.backend, runner.detector, replace(runner.recipe, full_settings=full),
                           runner.calibration, runner.region)
