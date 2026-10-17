import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

# ix83_acquisition.registration imports cv2 at module scope, so the skip runs
# before it: a base install collects this module as skipped, not failed.
cv2 = pytest.importorskip("cv2", reason="the hand-eye extra installs opencv-python-headless")
tifffile = pytest.importorskip("tifffile", reason="the stitching CLI reads TIFF tiles")

from ix83_acquisition.registration import (  # noqa: E402
    STAGE_REGISTRATION_SCHEMA,
)


def test_stitch_cli_writes_mosaic_and_transform_record(tmp_path):
    rng = np.random.default_rng(23)
    canvas = np.zeros((120, 260), dtype=np.uint8)
    for _ in range(55):
        x, y = int(rng.integers(0, 260)), int(rng.integers(0, 120))
        cv2.circle(canvas, (x, y), int(rng.integers(2, 7)), int(rng.integers(80, 255)), -1)
    canvas = cv2.GaussianBlur(canvas, (0, 0), 1)
    inputs = []
    for index, x in enumerate((0, 50, 100)):
        path = tmp_path / f"tile-{index}.tif"
        tifffile.imwrite(path, canvas[:, x : x + 160])
        inputs.append(path)

    output = tmp_path / "mosaic.tif"
    registration_input = tmp_path / "registration-input.json"
    registration_input.write_text(
        json.dumps(
            {
                "schema": STAGE_REGISTRATION_SCHEMA,
                "calibration": {
                    "calibration_id": "test",
                    "coordinate_frame": "stage_xy_um",
                    "pixel_to_stage": [[1, 0], [0, 1]],
                    "reference_pixel": [0, 0],
                    "camera_stage_xy_um": [0, 0],
                },
                "stage_positions_xy_um": [[0, 0], [50, 0], [100, 0]],
            }
        ),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        (
            str(Path(__file__).resolve().parents[3] / "03_external" / "sample_search" / "src"),
            str(Path(__file__).resolve().parents[1] / "scripts"),
        )
    )
    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve().parents[1] / "scripts" / "stitch_images.py"),
            "--output",
            str(output),
            "--metadata",
            str(registration_input),
            *map(str, inputs),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert abs(tifffile.imread(output).shape[1] - 260) < 3
    metadata = json.loads(output.with_suffix(".tif.registration.json").read_text(encoding="utf-8"))
    assert len(metadata["pairwise_fits"]) == 2
    assert "stage positions seed registration" in metadata["warning"]
