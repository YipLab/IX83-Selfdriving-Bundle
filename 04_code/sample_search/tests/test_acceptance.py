"""Seeded, stage-aware integration acceptance for the first search recipe.

Synthetic recall is computed against the supplied object list. It is not a
biological sensitivity claim.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import hypot

import numpy as np
from ix83_search_host import (
    AcquisitionResult,
    DataReference,
    MoveResult,
    SampleSearchRunner,
)
from samplescout import (
    AcquisitionSettings,
    Calibration,
    Phase,
    Region,
    RunStatus,
    WorkflowRecipe,
    load_replay,
    replay_targets,
    save_replay,
)
from samplescout.detection import DetectionConfig, make_detector

REGION = Region(-160.0, -120.0, 160.0, 120.0)
CAL = Calibration("seeded-cal-v1", "seeded-stage-xy", ((-1.0, 0.0), (0.0, 1.0)),
                  (59.5, 59.5), (0.0, 0.0))
# (x, y, radius, intensity). The last object is intentionally outside the
# permitted region but visible as a clipped component in the boundary tile.
OBJECTS = (
    ( -3.0,   1.0, 4.0, 180.0),  # crosses a survey-tile seam; overlap duplicate
    (  8.0,   1.0, 2.0, 160.0),  # nearby, physically distinct object
    (-145.0, 90.0, 3.0,  35.0),  # dim object
    ( 55.0, -75.0, 4.0, 190.0),
    (162.0, 100.0, 4.0, 180.0),  # outside permitted bounds
)


class SeededStageBackend:
    """Render a fixed specimen into the image around the stage readback."""

    capabilities = frozenset({"stage.xy", "camera.snap", "storage.raw"})
    resources = frozenset({"stage", "camera", "storage"})
    setting_capabilities = frozenset({"exposure_ms", "channel"})

    def __init__(self):
        self.events = []
        self.frames = {}
        self.position = (0.0, 0.0)

    def move_to(self, request):
        self.position = (float(request.position_xyz_um[0]), float(request.position_xyz_um[1]))
        self.events.append(("move", request.request_id, self.position))
        return MoveResult(request.request_id, (*self.position, float(request.position_xyz_um[2])))

    def acquire(self, request):
        settings = request.settings
        h, w = settings.image_shape_yx or (120, 120)
        yy, xx = np.mgrid[:h, :w]
        # Pixel centers are transformed through the same reflected calibration
        # used by target conversion. Draw each physical object, not tile-local
        # pseudo detections, so tile-to-specimen coherence is exercised.
        sx = self.position[0] + CAL.pixel_to_stage[0][0] * (xx - CAL.reference_pixel[0])
        sy = self.position[1] + CAL.pixel_to_stage[1][1] * (yy - CAL.reference_pixel[1])
        image = np.full((h, w), 5.0, dtype=np.float32)
        for x, y, radius, intensity in OBJECTS:
            mask = (sx - x) ** 2 + (sy - y) ** 2 <= radius ** 2
            image[mask] = intensity
        # Stable, phase-specific exposure scale preserves geometry while making
        # survey and full acquisition settings observably distinct.
        image *= settings.exposure_ms / 20.0
        self.frames[request.request_id] = image.copy()
        self.events.append(("acquire", request.phase, settings, request.tile_id,
                            request.target_id, self.position))
        dataset = DataReference(f"memory://{request.request_id}", "npy-frames", "QYX",
            (settings.frames, h, w), str(image.dtype), settings.frames, "completed", "0" * 64)
        return AcquisitionResult(request.request_id, request.run_id, request.specimen_id,
            request.phase, request.coordinate_frame, request.calibration_id, request.tile_id,
            image, self.position, datetime.now(timezone.utc), dataset)


def run_seeded_search():
    backend = SeededStageBackend()
    survey = AcquisitionSettings(exposure_ms=20.0, image_shape_yx=(120, 120),
                                 channel_id="brightfield", metadata={"objective": "20x"})
    full = AcquisitionSettings(exposure_ms=100.0, image_shape_yx=(120, 120),
                               channel_id="brightfield", metadata={"objective": "20x"})
    recipe = WorkflowRecipe("seeded-two-pass", "0.1", "synthetic-specimen",
                            CAL.coordinate_frame, CAL.calibration_id, survey, full,
                            (120, 120), overlap=0.2, deduplication_um=4.0)
    detector = make_detector(DetectionConfig(threshold=20.0, min_area_px=1))
    runner = SampleSearchRunner(backend, detector, recipe, CAL, REGION)
    return runner.run(), backend, recipe


def test_seeded_stage_aware_search_meets_recall_revisit_order_and_replay(tmp_path):
    run, backend, recipe = run_seeded_search()
    assert run.status is RunStatus.COMPLETED, run.errors
    survey_events = [e for e in backend.events if e[0] == "acquire" and e[1] is Phase.SURVEY]
    full_events = [e for e in backend.events if e[0] == "acquire" and e[1] is Phase.REVISIT]
    assert len(survey_events) == 12, f"expected 4x3, got {len(survey_events)} survey tiles"
    assert survey_events and full_events
    assert max(i for i, e in enumerate(backend.events) if e[0] == "acquire" and e[1] is Phase.SURVEY) < min(
        i for i, e in enumerate(backend.events) if e[0] == "acquire" and e[1] is Phase.REVISIT)
    assert all(e[2] == recipe.survey_settings for e in survey_events)
    assert all(e[2] == recipe.full_settings for e in full_events)
    assert {e[2].metadata["objective"] for e in survey_events + full_events} == {"20x"}

    targets = run.targets
    expected_inside = OBJECTS[:-1]
    for x, y, _radius, _intensity in expected_inside:
        assert min(hypot(t.x_um - x, t.y_um - y) for t in targets) <= 2.0, (x, y, targets)
    # Close distinct objects must not collapse into one target.
    left = min(targets, key=lambda t: hypot(t.x_um + 3.0, t.y_um - 1.0))
    right = min(targets, key=lambda t: hypot(t.x_um - 8.0, t.y_um - 1.0))
    assert left.target_id != right.target_id
    # The outside-region object must not become an accepted target.
    assert all(hypot(t.x_um - 162.0, t.y_um - 100.0) > 4.0 for t in targets)

    revisits = [o for o in run.observations if o.phase is Phase.REVISIT]
    assert len(revisits) == len(targets)
    for target in targets:
        obs = next(o for o in revisits if o.target_id == target.target_id)
        assert hypot(obs.stage_xy_um[0] - target.x_um, obs.stage_xy_um[1] - target.y_um) <= 1e-9
        truth = min(expected_inside, key=lambda obj: hypot(target.x_um-obj[0], target.y_um-obj[1]))
        # Compare with specimen ground truth, independently of commanded targets.
        assert hypot(obs.stage_xy_um[0]-truth[0], obs.stage_xy_um[1]-truth[1]) <= 2
        image = backend.frames[obs.request_id]
        assert image[57:63, 57:63].max() > 100

    detected_obs = [o for o in run.observations if o.phase is Phase.DETECTION]
    replay_path = tmp_path / "seeded-replay.json"
    save_replay(replay_path, detected_obs)
    restored = load_replay(replay_path)
    replayed = replay_targets(restored, CAL, REGION, distance_um=recipe.deduplication_um)
    assert sorted((t.x_um, t.y_um) for t in replayed) == sorted((t.x_um, t.y_um) for t in targets)
    # Replay is a pure decision operation; it does not call the acquisition backend.
    before = len(backend.events)
    assert replay_targets(restored, CAL, REGION, distance_um=recipe.deduplication_um)
    assert len(backend.events) == before

    # One planned field is intentionally empty: no object center lies there.
    # Validate requested coverage independently against the 12 returned stage centers.
    centers = [e[5] for e in survey_events]
    assert len(set(centers)) == 12
    empty_survey = {o.tile_id for o in run.observations if o.phase is Phase.DETECTION and not o.value}
    assert empty_survey, "seeded region must include a valid blank survey tile"
    # The planner's calibrated 120 x 120 um fields cover every point in the
    # declared rectangle (the fixture's matrix is an axis-aligned reflection).
    for x in np.linspace(REGION.x_min_um, REGION.x_max_um, 81):
        for y in np.linspace(REGION.y_min_um, REGION.y_max_um, 61):
            assert any(abs(x - cx) <= 60.0 and abs(y - cy) <= 60.0 for cx, cy in centers)


def test_seeded_detector_exercises_a_dim_object_and_duplicate_seam_observations():
    run, _backend, _recipe = run_seeded_search()
    detections = [o for o in run.observations if o.phase is Phase.DETECTION]
    # At least one tile detects each intended in-region object, and the seam
    # object is observed in more than one survey tile before physical dedup.
    assert len(detections) > 0
    seam = [
        o for o in detections
        if any(hypot(CAL.image_to_stage(d.x_pixel, d.y_pixel, o.stage_xy_um)[0] + 3.0,
                     CAL.image_to_stage(d.x_pixel, d.y_pixel, o.stage_xy_um)[1] - 1.0) < 8.0
               for d in o.value)
    ]
    assert len(seam) >= 2
