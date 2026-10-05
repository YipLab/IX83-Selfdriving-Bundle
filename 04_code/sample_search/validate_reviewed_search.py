"""Saved survey, offline review, and resumed movies through the bundle executor."""
# Source-tree bootstrapping is intentional before packaging.
from __future__ import annotations

import json
import time

import numpy as np
from source_bootstrap import enable_source_tree

BUNDLE = enable_source_tree(include_processing_source=True)

from ix83_acquisition import MockCamera, MockXYZStage, replay_frames, replay_ome_frames
from ix83_acquisition.rtaspt_handoff import rtaspt_planes
from ix83_search_adapter import IX83SearchExecutor
from ix83_search_host import SampleSearchRunner, local_dataset_path
from samplescout import (
    AcquisitionSettings,
    Calibration,
    Phase,
    Region,
    RunStatus,
    WorkflowRecipe,
    load_review_run,
    save_run,
)
from samplescout.detection import DetectionConfig, detect_bright_objects
from samplescout.review import (
    ManualTarget,
    ReviewContext,
    decision_from_json,
    make_decision,
    render_review_html,
)


def main():
    output = BUNDLE / "04_code/sample_search/recordings" / f"reviewed-{time.time_ns()}"
    spots = ((0, 0), (16, 10), (20, 10), (64, 32), (96, 64))

    def camera():
        return MockCamera(shape_yx=(80, 80), pixel_size_um=0.5, read_noise=0,
                          specimen_spots_um=spots)

    def executor(stage, destination):
        return IX83SearchExecutor(camera(), stage, destination,
                                  limits_xy_um=((-500, 500), (-500, 500)), fixed_z_um=0)

    calibration = Calibration("mock-0.5um", "stage", ((0.5, 0), (0, 0.5)), (39.5, 39.5), (0, 0))
    region = Region(-20, -20, 116, 84)
    recipe = WorkflowRecipe("reviewed-search", "0.1-local", "seeded", "stage", "mock-0.5um",
        AcquisitionSettings(exposure_ms=50, frames=1, image_shape_yx=(80, 80)),
        AcquisitionSettings(exposure_ms=50, frames=3, image_shape_yx=(80, 80)), (80, 80),
        deduplication_um=1, max_targets=5,
        required_capabilities=frozenset({"stage.xy", "camera.snap", "camera.sequence", "storage.raw"}))

    def detector(image, _observation):
        return detect_bright_objects(image, DetectionConfig(threshold=1000, min_area_px=3))

    stage = MockXYZStage()
    survey_executor = executor(stage, output / "survey")
    try:
        pending = SampleSearchRunner(survey_executor, detector, recipe, calibration,
                                    region, timeout_s=30,
                                    action_journal=output / "survey-actions.jsonl").run(review_only=True)
        assert pending.status is RunStatus.REVIEW_PENDING, pending.errors
        survey = [obs for obs in pending.observations if obs.phase is Phase.SURVEY]
        assert len(survey) == 12 and len(pending.targets) == 5
        assert not any(obs.phase is Phase.REVISIT for obs in pending.observations)
        save_run(output / "checkpoint.json", pending, recipe, calibration, region)
        context = ReviewContext(pending.run_id, pending.specimen_id,
                                calibration.coordinate_frame, calibration.calibration_id)
        manifest = render_review_html(output / "review.html", context, pending.targets, survey,
            image_loader=lambda obs: next(replay_frames(local_dataset_path(obs.data_reference))).pixels,
            calibration=calibration, region=region)
        replacement = pending.targets[-1]
        decision = make_decision(manifest,
            accepted_target_ids=tuple(target.target_id for target in pending.targets[:2]),
            rejected_target_ids=tuple(target.target_id for target in pending.targets[2:]),
            additions=(ManualTarget("manual-replacement", replacement.x_um, replacement.y_um,
                                    "Synthetic operator replacement checked against saved survey"),))
        decision_path = output / "review-decision.json"
        decision_path.write_text(json.dumps(decision.to_dict(), indent=2), encoding="utf-8")
    finally:
        survey_executor.close()

    loaded, loaded_recipe, loaded_calibration, loaded_region, full_calibration = load_review_run(
        output / "checkpoint.json")
    resumed_executor = executor(MockXYZStage(position=stage.position), output / "revisits")
    try:
        resumed = SampleSearchRunner(resumed_executor, detector, loaded_recipe,
            loaded_calibration, loaded_region, full_calibration=full_calibration,
            z_um=loaded.review_fixed_z_um, timeout_s=30,
            action_journal=output / "revisit-actions.jsonl")
        run = resumed.resume_review(loaded, decision_from_json(decision_path))
        assert run.status is RunStatus.COMPLETED, run.errors
        revisits = [obs for obs in run.observations if obs.phase is Phase.REVISIT]
        assert len(revisits) == len(run.targets) == 3
        assert len([obs for obs in run.observations if obs.phase is Phase.SURVEY]) == 12
        assert len(run.manual_provenance) == 1 and run.review_decision is not None
        survey_frames = sum(len(list(replay_frames(local_dataset_path(obs.data_reference)))) for obs in survey)
        movie_frames = sum(len(list(replay_ome_frames(local_dataset_path(obs.data_reference)))) for obs in revisits)
        assert survey_frames == 12 and movie_frames == 9
        for target, observed in zip(run.targets, revisits, strict=True):
            assert np.linalg.norm(np.array(observed.stage_xy_um) - (target.x_um, target.y_um)) < 1e-9
            image = next(replay_ome_frames(local_dataset_path(observed.data_reference))).pixels
            assert image[38:42, 38:42].max() > 5000
        plane_count = sum(len(list(rtaspt_planes(local_dataset_path(obs.data_reference)))) for obs in revisits)
        assert plane_count == movie_frames
        save_run(output / "workflow_run.json", run, recipe, calibration, region)
        report = {"status": "passed", "survey_tiles": 12, "candidate_targets": 5,
                  "reviewed_targets": 3, "manual_targets": 1, "full_movie_frames": movie_frames,
                  "rtaspt_planes": plane_count, "survey_repeated": False, "exposure_ms": 50,
                  "checksums_verified": True, "run_directory": str(output),
                  "no_hardware_access": True}
        (output / "validation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
    finally:
        resumed_executor.close()


if __name__ == "__main__":
    main()
