"""Two-pass sample-search through the bundle executor and real storage contracts."""
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
)
from samplescout.detection import DetectionConfig, detect_bright_objects
from samplescout.records import load_replay, replay_targets, save_replay, save_run


def main():
    output = BUNDLE / "04_code/sample_search/recordings" / f"mock-{time.time_ns()}"
    camera = MockCamera(shape_yx=(80, 80), pixel_size_um=0.5, read_noise=0,
        specimen_spots_um=((0, 0), (16, 10), (20, 10), (64, 32), (96, 64)))
    stage = MockXYZStage()
    executor = IX83SearchExecutor(camera, stage, output,
        limits_xy_um=((-500, 500), (-500, 500)), fixed_z_um=0)
    calibration = Calibration("mock-0.5um", "stage", ((0.5, 0), (0, 0.5)), (39.5, 39.5), (0, 0))
    region = Region(-20, -20, 116, 84)
    recipe = WorkflowRecipe("two-pass-search", "0.1-local", "seeded", "stage", "mock-0.5um",
        AcquisitionSettings(exposure_ms=50, frames=1, image_shape_yx=(80, 80)),
        AcquisitionSettings(exposure_ms=50, frames=3, image_shape_yx=(80, 80)), (80, 80),
        deduplication_um=1, required_capabilities=frozenset({"stage.xy", "camera.snap", "camera.sequence", "storage.raw"}))
    try:
        run = SampleSearchRunner(executor,
            lambda image, _obs: detect_bright_objects(image, DetectionConfig(threshold=1000, min_area_px=3)),
            recipe, calibration, region, timeout_s=30,
            action_journal=output / "actions.jsonl").run()
        if run.status != RunStatus.COMPLETED:
            raise RuntimeError(f"mock workflow failed: {run.errors}")
        survey = [obs for obs in run.observations if obs.phase == Phase.SURVEY]
        revisits = [obs for obs in run.observations if obs.phase == Phase.REVISIT]
        assert len(survey) == 12
        assert len(run.targets) == len(revisits) == 5
        assert all(obs.exposure_ms == 50 for obs in survey + revisits)
        assert sum(len(list(replay_frames(local_dataset_path(obs.data_reference)))) for obs in survey) == 12
        movie_frames = sum(len(list(replay_ome_frames(local_dataset_path(obs.data_reference)))) for obs in revisits)
        assert movie_frames == 15
        for target, observed in zip(run.targets, revisits, strict=True):
            assert np.linalg.norm(np.array(observed.stage_xy_um) - (target.x_um, target.y_um)) < 1e-9
            image = next(replay_ome_frames(local_dataset_path(observed.data_reference))).pixels
            # Actual saved pixels contain a bright target at the reference pixel.
            assert image[38:42, 38:42].max() > 5000
        replay_path = output / "observations.json"
        save_replay(replay_path, run.observations)
        save_run(output / "workflow_run.json", run, recipe, calibration, region)
        targets = replay_targets(load_replay(replay_path), calibration, region, distance_um=1)
        assert {target.target_id for target in targets} == {target.target_id for target in run.targets}
        plane_count = sum(len(list(rtaspt_planes(local_dataset_path(obs.data_reference)))) for obs in revisits)
        assert plane_count == movie_frames
        report = {"status": "passed", "survey_tiles": 12, "targets": 5,
                  "full_movie_frames": movie_frames, "rtaspt_planes": plane_count,
                  "replay_target_ids_match": True, "run_directory": str(output),
                  "exposure_ms": 50, "no_hardware_access": True}
        (output / "validation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
    finally:
        executor.close()


if __name__ == "__main__":
    main()
