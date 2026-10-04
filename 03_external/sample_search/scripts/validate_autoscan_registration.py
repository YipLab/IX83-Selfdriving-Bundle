"""Mock-test stitching on overlapping crops derived from AutoScanJ's supplied montage."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import tifffile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from samplescout.registration import stitch_sequence

DEFAULT_AUTOSCAN = Path(
    "C:/Users/YipGroup/Documents/GitHub/AutoScanJ/TestData/FixedSample_Tiling_HeLa_Metaphase"
)


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_AUTOSCAN
    montage_path = root / "Montagescan--2011_03_28_09_41_52.tif"
    montage = np.asarray(tifffile.imread(montage_path))
    if montage.ndim != 2 or min(montage.shape) < 1024:
        raise ValueError(f"expected a 2D montage at least 1024 px per axis, got {montage.shape}")

    tile_paths = list((root / "scan--2011_03_28_09_41_52").glob("*.ome.tif"))
    tile_shapes = {tuple(tifffile.TiffFile(path).series[0].shape[-2:]) for path in tile_paths}
    # These patches have exactly known 50%-overlap offsets, using actual AutoScanJ
    # montage pixels. The source tile files do not provide recorded stage positions.
    tile_size = 600
    starts = (0, 200, 400)
    crops = [montage[:tile_size, x:x + tile_size] for x in starts]
    result = stitch_sequence(crops, downsample=1, min_correlation=0.2,
                             min_overlap_fraction=0.2)
    expected = np.asarray(starts, dtype=float)
    estimated = np.asarray([x for x, _ in result.origins_xy_px])
    error = np.abs(estimated - expected)
    if float(error.max()) > 3.0:
        raise AssertionError(f"AutoScanJ-derived crop offset error too large: {error.tolist()}")

    report = {
        "source": str(montage_path),
        "montage_shape_yx": montage.shape,
        "individual_tile_count": len(tile_paths),
        "individual_tile_shapes_yx": sorted(tile_shapes),
        "actual_tile_stage_positions_available": False,
        "mock_method": "three 600x600 overlapping crops of the supplied montage, 200px apart",
        "expected_origins_x_px": starts,
        "estimated_origins_xy_px": result.origins_xy_px,
        "pairwise_correlation": [fit.correlation for fit in result.pairwise_fits],
        "max_x_offset_error_px": float(error.max()),
        "interpretation": "registration tested on source-derived overlapping crops; source tiles themselves lack documented overlap/positions",
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
