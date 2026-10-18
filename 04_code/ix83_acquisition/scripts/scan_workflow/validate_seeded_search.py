"""Run and visualize the deterministic, hardware-free seeded search scenario.

Run with the acquisition project's `.venv` from the bundle root:
  04_code/ix83_acquisition/.venv/Scripts/python.exe `
    04_code/ix83_acquisition/scripts/scan_workflow/validate_seeded_search.py

The script adds the acquisition source tree and its scan_host test-support
directory to the import path itself; `planner` comes from the installed
`redsun-planner` distribution. Matplotlib is supplied by the
`rtaspt-controller-check` extra. Recall is measured only against this
simulator's supplied object coordinates.
It is not a biological sensitivity or hardware acceptance result.
"""

from __future__ import annotations

import json
import tempfile
from math import hypot
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from source_bootstrap import enable_source_tree

ROOT = enable_source_tree(include_test_support=True)
PACKAGE_ROOT = ROOT / "03_external" / "sample_search"

from planner import (
    Phase,
    RunStatus,
    load_replay,
    replay_targets,
    save_replay,
)
from test_acceptance import CAL, OBJECTS, REGION, run_seeded_search


def main() -> int:
    run, backend, _recipe = run_seeded_search()
    surveys = [
        event for event in backend.events if event[0] == "acquire" and event[1] is Phase.SURVEY
    ]
    revisits = [o for o in run.observations if o.phase is Phase.REVISIT]
    inside = OBJECTS[:-1]
    recalled = {
        f"({x:g},{y:g})": min(
            (hypot(t.x_um - x, t.y_um - y) for t in run.targets), default=float("inf")
        )
        <= 2.0
        for x, y, _r, _i in inside
    }
    outside = OBJECTS[-1]
    outside_near = [
        t for t in run.targets if hypot(t.x_um - outside[0], t.y_um - outside[1]) <= outside[2]
    ]
    detections = [o for o in run.observations if o.phase is Phase.DETECTION]
    empty_tiles = [o.tile_id for o in detections if not o.value]
    seam_tiles = []
    for obs in detections:
        if any(
            hypot(
                *(
                    CAL.image_to_stage(d.x_pixel, d.y_pixel, obs.stage_xy_um)[i] - OBJECTS[0][i]
                    for i in (0, 1)
                )
            )
            <= 8.0
            for d in obs.value
        ):
            seam_tiles.append(obs.tile_id)
    ordered = bool(
        surveys
        and revisits
        and max(
            i for i, e in enumerate(backend.events) if e[0] == "acquire" and e[1] is Phase.SURVEY
        )
        < min(
            i for i, e in enumerate(backend.events) if e[0] == "acquire" and e[1] is Phase.REVISIT
        )
    )
    revisit_error = {
        target.target_id: hypot(
            next(o for o in revisits if o.target_id == target.target_id).stage_xy_um[0]
            - target.x_um,
            next(o for o in revisits if o.target_id == target.target_id).stage_xy_um[1]
            - target.y_um,
        )
        for target in run.targets
    }
    truth_centering_error = {}
    for target in run.targets:
        truth = min(inside, key=lambda obj: hypot(target.x_um - obj[0], target.y_um - obj[1]))
        observed = next(o for o in revisits if o.target_id == target.target_id)
        truth_centering_error[target.target_id] = hypot(
            observed.stage_xy_um[0] - truth[0], observed.stage_xy_um[1] - truth[1]
        )
    with tempfile.TemporaryDirectory() as scratch:
        replay_path = Path(scratch) / "observations.json"
        save_replay(replay_path, detections)
        replayed = replay_targets(load_replay(replay_path), CAL, REGION, distance_um=4.0)
    replay_equal = sorted((t.x_um, t.y_um) for t in replayed) == sorted(
        (t.x_um, t.y_um) for t in run.targets
    )
    report = {
        "status": run.status.value,
        "scope": "seeded synthetic simulation only; no biological sensitivity or hardware acceptance",
        "survey_tile_count": len(surveys),
        "survey_tile_ids": [event[3] for event in surveys],
        "empty_survey_tile_ids": empty_tiles,
        "survey_precedes_full_revisits": ordered,
        "target_count": len(run.targets),
        "recalled_inside_truth_objects_within_2um": recalled,
        "distinct_nearby_objects_retained": len(
            [t for t in run.targets if hypot(t.x_um + 3.0, t.y_um - 1.0) <= 2.0]
        )
        == 1
        and len([t for t in run.targets if hypot(t.x_um - 8.0, t.y_um - 1.0) <= 2.0]) == 1,
        "outside_truth_object_rejected": not outside_near,
        "outside_truth_object_false_targets": [
            {"target_id": t.target_id, "x_um": t.x_um, "y_um": t.y_um} for t in outside_near
        ],
        "commanded_target_readback_error_um": revisit_error,
        "revisit_truth_centering_error_um": truth_centering_error,
        "truth_centering_tolerance_um": 2.0,
        "saved_detection_replay_matches_targets": replay_equal,
        "targets_um": [
            {"target_id": t.target_id, "x_um": t.x_um, "y_um": t.y_um} for t in run.targets
        ],
        "seam_object_detected_tiles": seam_tiles,
        "run_errors": run.errors,
    }
    report["acceptance_checks_pass"] = bool(
        run.status is RunStatus.COMPLETED
        and len(surveys) == 12
        and ordered
        and all(recalled.values())
        and report["distinct_nearby_objects_retained"]
        and report["outside_truth_object_rejected"]
        and replay_equal
        and all(error <= 1e-9 for error in revisit_error.values())
        and all(error <= 2 for error in truth_centering_error.values())
        and bool(empty_tiles)
        and len(seam_tiles) >= 2
    )
    docs = ROOT / "02_docs_offline"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "sample_search_seeded_search_validation.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )

    fig, ax = plt.subplots(figsize=(10, 7), constrained_layout=True)
    ax.add_patch(
        Rectangle(
            (REGION.x_min_um, REGION.y_min_um),
            REGION.x_max_um - REGION.x_min_um,
            REGION.y_max_um - REGION.y_min_um,
            fill=False,
            lw=2,
            ec="black",
            label="permitted region",
        )
    )
    for _name, _phase, _settings, _tile, _target, (cx, cy) in surveys:
        ax.add_patch(
            Rectangle((cx - 60, cy - 60), 120, 120, fill=False, lw=0.7, ec="#7aa6c2", alpha=0.55)
        )
    for x, y, radius, _intensity in inside:
        ax.scatter(
            [x],
            [y],
            marker="o",
            s=35,
            c="#25803d",
            label="in-region truth object" if (x, y) == (inside[0][0], inside[0][1]) else None,
        )
        ax.add_patch(plt.Circle((x, y), radius, fill=False, ec="#25803d", alpha=0.5))
    ax.scatter([outside[0]], [outside[1]], marker="x", s=90, c="red", label="outside truth object")
    if run.targets:
        ax.scatter(
            [t.x_um for t in run.targets],
            [t.y_um for t in run.targets],
            marker="+",
            s=90,
            c="#6d3fa0",
            label="selected target",
        )
    for t in run.targets:
        obs = next((o for o in revisits if o.target_id == t.target_id), None)
        if obs is not None:
            ax.plot(
                [t.x_um, obs.stage_xy_um[0]], [t.y_um, obs.stage_xy_um[1]], color="#6d3fa0", lw=1
            )
    ax.set(
        xlim=(-185, 190),
        ylim=(-140, 145),
        xlabel="stage X (µm)",
        ylabel="stage Y (µm)",
        title="Seeded stage-aware sample search (simulation only)",
    )
    ax.set_aspect("equal")
    ax.grid(alpha=0.2)
    ax.legend(loc="upper left", fontsize=8)
    fig.savefig(docs / "sample_search_seeded_search_validation.png", dpi=140)
    plt.close(fig)
    print(json.dumps(report, indent=2))
    # This artifact is a diagnostic; retain output even when an acceptance
    # condition fails so a reviewer can inspect the observed behavior.
    return 0 if report["acceptance_checks_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
