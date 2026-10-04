"""Register and stitch an ordered sequence of overlapping grayscale TIFFs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import tifffile
from samplescout.registration import stitch_sequence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("images", nargs="+", type=Path, help="ordered, overlapping grayscale TIFFs")
    parser.add_argument("--output", required=True, type=Path, help="output mosaic TIFF path")
    parser.add_argument("--min-correlation", type=float, default=0.2)
    parser.add_argument("--min-overlap", type=float, default=0.1)
    parser.add_argument("--downsample", type=int, default=2)
    args = parser.parse_args()

    images = [tifffile.imread(path) for path in args.images]
    result = stitch_sequence(images, downsample=args.downsample,
                             min_correlation=args.min_correlation,
                             min_overlap_fraction=args.min_overlap)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    tifffile.imwrite(args.output, result.image)
    details = {
        "inputs": [str(path.resolve()) for path in args.images],
        "output": str(args.output.resolve()),
        "coordinate_system": "mosaic pixels; transforms composed from the first input",
        "origins_xy_px": result.origins_xy_px,
        "pairwise_fits": [fit.__dict__ for fit in result.pairwise_fits],
        "warning": "image registration only; no stage units or stage-camera calibration inferred",
    }
    args.output.with_suffix(args.output.suffix + ".registration.json").write_text(
        json.dumps(details, indent=2) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
