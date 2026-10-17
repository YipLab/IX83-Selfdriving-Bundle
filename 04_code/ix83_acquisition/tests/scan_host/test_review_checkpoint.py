import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from planner import (
    AcquisitionSettings,
    Calibration,
    DetectedObject,
    ManualTarget,
    Phase,
    Region,
    RunStatus,
    WorkflowRecipe,
    load_review_run,
    save_run,
)
from planner.review import ReviewContext, create_manifest, make_decision

from ix83_acquisition.scan_host import (
    AcquisitionResult,
    DataReference,
    MoveResult,
    SampleSearchRunner,
)


class MockBackend:
    capabilities = frozenset({"stage.xy", "camera.snap", "storage.raw"})
    resources = frozenset({"stage", "camera", "storage"})
    setting_capabilities = frozenset({"exposure_ms"})

    def __init__(self):
        self.events = []

    def move_to(self, request):
        self.events.append(("move", request.position_xyz_um))
        return MoveResult(request.request_id, request.position_xyz_um)

    def acquire(self, request):
        self.events.append(("acquire", request.phase, request.tile_id))
        now = datetime.now(UTC)
        position = self.events[-2][1]
        dataset = DataReference(
            f"memory://{request.tile_id}",
            "npy-frames",
            "QYX",
            (request.settings.frames, 10, 10),
            "uint8",
            request.settings.frames,
            "completed",
            "0" * 64,
        )
        return AcquisitionResult(
            request.request_id,
            request.run_id,
            request.specimen_id,
            request.phase,
            request.coordinate_frame,
            request.calibration_id,
            request.tile_id,
            request.tile_id,
            position[:2],
            now,
            dataset,
        )


def setup(backend=None, *, clock=None, age=300):
    backend = backend or MockBackend()
    cal = Calibration("cal", "stage-xy", ((1, 0), (0, 1)), (5, 5), (0, 0))
    settings = AcquisitionSettings(image_shape_yx=(10, 10))
    recipe = WorkflowRecipe(
        "search",
        "1",
        "sample",
        "stage-xy",
        "cal",
        settings,
        settings,
        (10, 10),
        overlap=0.2,
        deduplication_um=1,
        max_targets=3,
    )

    def detector(image, obs):
        if image == "tile-r00-c00":
            return [DetectedObject(2, 2, 9), DetectedObject(8, 8, 8)]
        return []

    runner = SampleSearchRunner(
        backend, detector, recipe, cal, Region(0, 0, 10, 10), clock=clock, max_observation_age_s=age
    )
    return runner


def decision_for(run, runner):
    context = ReviewContext(
        run.run_id,
        runner.recipe.specimen_id,
        runner.calibration.coordinate_frame,
        runner.calibration.calibration_id,
    )
    return make_decision(
        create_manifest(context, run.targets),
        accepted_target_ids=(run.targets[0].target_id,) if run.targets else (),
        additions=(ManualTarget("manual-a", 8, 8, "visible by operator"),),
    )


def test_checkpoint_load_resume_runs_only_revisits_and_keeps_review_record(tmp_path):
    original_backend = MockBackend()
    runner = setup(original_backend)
    checkpoint = runner.run(review_only=True)
    assert checkpoint.status is RunStatus.REVIEW_PENDING
    assert [e[1] for e in original_backend.events if e[0] == "acquire"]
    assert not any(e[1] is Phase.REVISIT for e in original_backend.events if e[0] == "acquire")
    path = tmp_path / "checkpoint.json"
    save_run(path, checkpoint, runner.recipe, runner.calibration, runner.region)
    loaded, recipe, calibration, region, full = load_review_run(path)
    assert loaded.execution_bindings == checkpoint.execution_bindings
    resumed_backend = MockBackend()
    resumed_runner = SampleSearchRunner(
        resumed_backend, runner.detector, recipe, calibration, region, full_calibration=full
    )
    result = resumed_runner.resume_review(loaded, decision_for(loaded, resumed_runner))
    assert result.status is RunStatus.COMPLETED
    assert len([e for e in resumed_backend.events if e[0] == "acquire"]) == 2
    assert not any(e[1] is Phase.SURVEY for e in resumed_backend.events if e[0] == "acquire")
    assert result.review_decision["additions"][0]["target_id"] == "manual-a"
    assert result.manual_provenance[0]["reason"] == "visible by operator"
    assert len([o for o in result.observations if o.phase is Phase.REVISIT]) == 2
    with pytest.raises(ValueError, match="unused"):
        resumed_runner.resume_review(result, decision_for(result, resumed_runner))


def test_legacy_checkpoint_is_verified_then_normalized_to_named_axes(tmp_path):
    runner = setup()
    checkpoint = runner.run(review_only=True)
    path = tmp_path / "legacy.json"
    save_run(path, checkpoint, runner.recipe, runner.calibration, runner.region)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.pop("payload_sha256")
    payload["schema"] = "samplescout-run-v1"
    for observation in payload["observations"]:
        observation["axes"] = [axis.lower() for axis in observation["axes"]]
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    import hashlib

    payload["payload_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    path.write_text(json.dumps(payload), encoding="utf-8")
    loaded, *_ = load_review_run(path)
    assert loaded.status is RunStatus.REVIEW_PENDING
    assert all(o.axes == ("Y", "X") for o in loaded.observations)


def test_blank_survey_still_pauses_and_missing_survey_fails():
    runner = setup()
    runner.detector = lambda image, obs: []
    pending = runner.run(review_only=True)
    assert pending.status is RunStatus.REVIEW_PENDING and pending.targets == []
    missing = setup()

    class Missing(MockBackend):
        def acquire(self, request):
            result = super().acquire(request)
            return replace(result, image=None, dataset=None)

    missing.backend = Missing()
    assert missing.run(review_only=True).status is RunStatus.FAILED


def test_bad_binding_decision_age_and_checksum_rejected_before_actions(tmp_path):
    runner = setup()
    pending = runner.run(review_only=True)
    decision = decision_for(pending, runner)
    other_backend = MockBackend()
    changed = replace(runner.calibration, calibration_id="changed")
    altered = SampleSearchRunner(
        other_backend,
        runner.detector,
        replace(runner.recipe, calibration_id="changed"),
        changed,
        runner.region,
    )
    with pytest.raises(ValueError, match="binding"):
        altered.resume_review(pending, decision)
    assert other_backend.events == []

    event_count = len(runner.backend.events)
    with pytest.raises(ValueError):
        runner.resume_review(pending, replace(decision, run_id="other"))
    assert len(runner.backend.events) == event_count

    badfile = tmp_path / "tampered.json"
    save_run(badfile, pending, runner.recipe, runner.calibration, runner.region)
    data = json.loads(badfile.read_text())
    data["run"]["specimen_id"] = "forged"
    badfile.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="checksum"):
        load_review_run(badfile)


def test_resume_rejects_stale_survey_before_any_action():
    runner = setup(clock=lambda: datetime.now(UTC), age=1)
    pending = runner.run(review_only=True)
    later = setup(clock=lambda: datetime.now(UTC) + timedelta(seconds=3), age=1)
    with pytest.raises(ValueError, match="stale"):
        later.resume_review(pending, decision_for(pending, later))
    assert later.backend.events == []


@pytest.mark.parametrize("context", ["run", "observation"])
def test_resume_rejects_corrupted_in_memory_context_before_commands(context):
    runner = setup()
    pending = runner.run(review_only=True)
    decision = decision_for(pending, runner)
    if context == "run":
        pending.specimen_id = "different-specimen"
    else:
        pending.observations[0] = replace(
            pending.observations[0], coordinate_frame="different-frame"
        )
    event_count = len(runner.backend.events)
    with pytest.raises(ValueError, match="identity|context"):
        runner.resume_review(pending, decision)
    assert len(runner.backend.events) == event_count


def test_rejecting_every_target_finishes_empty_without_commands():
    runner = setup()
    pending = runner.run(review_only=True)
    context = ReviewContext(
        pending.run_id,
        pending.specimen_id,
        runner.calibration.coordinate_frame,
        runner.calibration.calibration_id,
    )
    decision = make_decision(
        create_manifest(context, pending.targets),
        rejected_target_ids=tuple(t.target_id for t in pending.targets),
    )
    event_count = len(runner.backend.events)
    result = runner.resume_review(pending, decision)
    assert result.status is RunStatus.EMPTY and result.targets == []
    assert result.review_decision is not None
    assert len(runner.backend.events) == event_count


def test_new_decision_cannot_rebind_mutated_survey_candidates():
    runner = setup()
    pending = runner.run(review_only=True)
    pending.targets[0] = replace(pending.targets[0], x_um=4)
    decision = decision_for(pending, runner)
    event_count = len(runner.backend.events)
    with pytest.raises(ValueError, match="candidate manifest"):
        runner.resume_review(pending, decision)
    assert len(runner.backend.events) == event_count
