# ruff: noqa: E402
"""Hardware-free end-to-end offline review checkpoint validation."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "03_external/sample_search"), str(ROOT / "04_code/sample_search")]

from ix83_search_host import AcquisitionResult, SampleSearchRunner
from samplescout import (
    AcquisitionSettings,
    Calibration,
    DetectedObject,
    Phase,
    Region,
    RunStatus,
    WorkflowRecipe,
    load_review_run,
    save_run,
)
from samplescout.review import (
    ManualTarget,
    ReviewContext,
    create_manifest,
    make_decision,
)


class MockBackend:
    capabilities = frozenset()
    resources = frozenset({"stage", "camera"})

    def __init__(self) -> None:
        self.events: list[tuple] = []

    def move_to(self, request_id, position_xyz_um, *, deadline=None):
        self.events.append(("move", position_xyz_um))
        return position_xyz_um

    def acquire(self, request_id, settings, *, phase, specimen_id, coordinate_frame,
                calibration_id, run_id, tile_id, target_id, deadline=None):
        self.events.append(("acquire", phase, tile_id))
        moved = self.events[-2][1]
        return AcquisitionResult(tile_id, tuple(moved[:2]), datetime.now(timezone.utc),
                                 f"movie://{phase.value}/{tile_id}")


def main() -> None:
    calibration = Calibration("cal-1", "stage-xy", ((1, 0), (0, 1)), (5, 5), (0, 0))
    settings = AcquisitionSettings(image_shape_yx=(10, 10))
    recipe = WorkflowRecipe("review-check", "1", "seeded", "stage-xy", "cal-1",
                            settings, settings, (10, 10), max_targets=3)
    def detector(image, _observation):
        return [DetectedObject(2, 2, 9), DetectedObject(8, 8, 8)] if image == "tile-r00-c00" else []
    region = Region(0, 0, 10, 10)
    survey_backend = MockBackend()
    runner = SampleSearchRunner(survey_backend, detector, recipe, calibration, region)
    pending = runner.run(review_only=True)
    if pending.status is not RunStatus.REVIEW_PENDING or len(pending.targets) != 2:
        raise RuntimeError("survey did not produce the expected review checkpoint")

    context = ReviewContext(pending.run_id, recipe.specimen_id,
                            calibration.coordinate_frame, calibration.calibration_id)
    decision = make_decision(create_manifest(context, pending.targets),
        accepted_target_ids=(pending.targets[0].target_id,),
        additions=(ManualTarget("manual-1", 8, 8, "operator-marked feature"),))
    with TemporaryDirectory() as directory:
        path = Path(directory) / "checkpoint.json"
        save_run(path, pending, recipe, calibration, region)
        loaded, loaded_recipe, loaded_calibration, loaded_region, full_calibration = load_review_run(path)
        revisit_backend = MockBackend()
        resumed = SampleSearchRunner(revisit_backend, detector, loaded_recipe, loaded_calibration,
                                     loaded_region, full_calibration=full_calibration)
        result = resumed.resume_review(loaded, decision)
        acquisitions = [event for event in revisit_backend.events if event[0] == "acquire"]
        if result.status is not RunStatus.COMPLETED or len(acquisitions) != 2:
            raise RuntimeError("review resume did not execute exactly the selected and manual targets")
        if any(event[1] is Phase.SURVEY for event in acquisitions):
            raise RuntimeError("resume unexpectedly repeated the survey")
        if not result.manual_provenance or result.manual_provenance[0]["reason"] != "operator-marked feature":
            raise RuntimeError("manual provenance was not retained")
        print(f"checkpoint={pending.run_id}; selected={len(result.targets)}; revisits={len(acquisitions)}; survey_repeated=false")


if __name__ == "__main__":
    main()
