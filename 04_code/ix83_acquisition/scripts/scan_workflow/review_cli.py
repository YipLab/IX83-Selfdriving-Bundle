"""Create and open the hardware-free review GUI for a saved survey checkpoint."""

# Source-tree bootstrapping is intentional while upstream package extraction is in progress.
from __future__ import annotations

import argparse
import webbrowser
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from source_bootstrap import enable_source_tree

enable_source_tree()

from planner import RunStatus, SearchObservation, load_review_run
from planner.contracts import Phase
from planner.review import ReviewContext, render_review_html

from ix83_acquisition import replay_frames
from ix83_acquisition.scan_host import local_dataset_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkpoint", type=Path, help="saved review-pending checkpoint.json")
    parser.add_argument("--output", type=Path, help="HTML output (default: sibling .review.html)")
    parser.add_argument(
        "--no-open", action="store_true", help="write HTML without opening a browser"
    )
    args = parser.parse_args(argv)

    run, _recipe, calibration, region, _full_calibration = load_review_run(args.checkpoint)
    if run.status is not RunStatus.REVIEW_PENDING:
        parser.error(f"checkpoint status must be review_pending, got {run.status.value}")
    observations = tuple(obs for obs in run.observations if obs.phase is Phase.SURVEY)
    if not observations:
        parser.error("checkpoint contains no saved survey observations")

    def load_median_image(observation: SearchObservation) -> NDArray[np.generic]:
        if observation.data_reference is None:
            raise ValueError(f"survey image has no data reference: {observation.request_id}")
        frames = [
            frame.pixels for frame in replay_frames(local_dataset_path(observation.data_reference))
        ]
        if not frames:
            raise ValueError(f"survey image is missing: {observation.data_reference}")
        return frames[0] if len(frames) == 1 else np.median(np.stack(frames), axis=0)

    output = args.output or args.checkpoint.with_suffix(".review.html")
    context = ReviewContext(
        run.run_id, run.specimen_id, calibration.coordinate_frame, calibration.calibration_id
    )
    manifest = render_review_html(
        output, context, run.targets, observations, load_median_image, calibration, region
    )
    if not args.no_open and not webbrowser.open(output.resolve().as_uri()):
        raise RuntimeError(f"could not open the review page: {output}")
    print(f"Review page: {output.resolve()} (manifest {manifest.sha256})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
