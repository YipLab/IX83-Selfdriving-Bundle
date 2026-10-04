import json
import os
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import tifffile


def test_stitch_cli_writes_mosaic_and_transform_record(tmp_path):
    rng = np.random.default_rng(23)
    canvas = np.zeros((120, 260), dtype=np.uint8)
    for _ in range(55):
        x, y = int(rng.integers(0, 260)), int(rng.integers(0, 120))
        cv2.circle(canvas, (x, y), int(rng.integers(2, 7)),
                   int(rng.integers(80, 255)), -1)
    canvas = cv2.GaussianBlur(canvas, (0, 0), 1)
    inputs = []
    for index, x in enumerate((0, 50, 100)):
        path = tmp_path / f"tile-{index}.tif"
        tifffile.imwrite(path, canvas[:, x:x + 160])
        inputs.append(path)

    output = tmp_path / "mosaic.tif"
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join((
        str(Path(__file__).resolve().parents[3] / "03_external" / "sample_search"),
        str(Path(__file__).resolve().parents[1]),
    ))
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parents[1] / "stitch_images.py"),
         "--output", str(output), *map(str, inputs)],
        env=env, capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert abs(tifffile.imread(output).shape[1] - 260) < 3
    metadata = json.loads(output.with_suffix(".tif.registration.json").read_text(encoding="utf-8"))
    assert len(metadata["pairwise_fits"]) == 2
    assert "no stage units" in metadata["warning"]
