"""Register grayscale TIFFs using stage positions and a hand-eye calibration."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import tifffile
from planner.geometry import Calibration

from ix83_acquisition.registration import STAGE_REGISTRATION_SCHEMA, stitch_sequence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("images", nargs="+", type=Path, help="ordered, overlapping grayscale TIFFs")
    parser.add_argument("--output", required=True, type=Path, help="output mosaic TIFF path")
    parser.add_argument(
        "--metadata",
        required=True,
        type=Path,
        help="JSON with calibration and ordered stage_positions_xy_um",
    )
    parser.add_argument("--min-correlation", type=float, default=0.2)
    parser.add_argument("--min-overlap", type=float, default=0.1)
    parser.add_argument("--downsample", type=int, default=2)
    parser.add_argument("--max-prior-deviation-px", type=float)
    args = parser.parse_args()

    metadata = json.loads(args.metadata.read_text(encoding="utf-8"))
    if metadata.get("schema") != STAGE_REGISTRATION_SCHEMA:
        parser.error(f"metadata schema must be {STAGE_REGISTRATION_SCHEMA}")
    calibration_data = metadata["calibration"]
    calibration = Calibration(
        calibration_id=calibration_data["calibration_id"],
        coordinate_frame=calibration_data["coordinate_frame"],
        pixel_to_stage=tuple(tuple(row) for row in calibration_data["pixel_to_stage"]),
        reference_pixel=tuple(calibration_data["reference_pixel"]),
        camera_stage_xy_um=tuple(calibration_data["camera_stage_xy_um"]),
        roi_origin=tuple(calibration_data.get("roi_origin", (0, 0))),
        binning=tuple(calibration_data.get("binning", (1, 1))),
    )
    stage_positions = tuple(tuple(position) for position in metadata["stage_positions_xy_um"])
    images = [tifffile.imread(path) for path in args.images]
    result = stitch_sequence(
        images,
        downsample=args.downsample,
        min_correlation=args.min_correlation,
        min_overlap_fraction=args.min_overlap,
        stage_positions_xy_um=stage_positions,
        calibration=calibration,
        max_prior_deviation_px=args.max_prior_deviation_px,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    tifffile.imwrite(args.output, result.image)
    details = {
        "inputs": [str(path.resolve()) for path in args.images],
        "output": str(args.output.resolve()),
        "coordinate_system": "mosaic pixels; transforms composed from the first input",
        "calibration_id": calibration.calibration_id,
        "stage_positions_xy_um": stage_positions,
        "origins_xy_px": result.origins_xy_px,
        "pairwise_fits": [fit.__dict__ for fit in result.pairwise_fits],
        "warning": "stage positions seed registration; transforms remain image-pixel coordinates",
    }
    args.output.with_suffix(args.output.suffix + ".registration.json").write_text(
        json.dumps(details, indent=2) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
