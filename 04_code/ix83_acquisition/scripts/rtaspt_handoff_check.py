"""Exercise actual RTASPT source contracts without napari or physical devices.

Requires Python 3.12 and the rtaspt-check extra. Full RTASPT GUI/analysis runtime
validation remains separate. Only this checkout's public acquisition/data APIs
are imported; no modules or device backends are replaced for this check.
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

package_root = Path(__file__).resolve().parents[1]
bundle_root = package_root.parents[1]
sys.path.insert(0, str(package_root / "src"))
sys.path.insert(0, str(bundle_root / "03_external/Realtime-Anisotropy-SPT-Analysis/src"))


def main() -> None:
    # Validates the interpreter this check was launched with, which need not be
    # the project environment that enforces requires-python.
    if sys.version_info < (3, 12):  # noqa: UP036
        raise RuntimeError("Run this check on Python 3.12, as required by the RTASPT checkout")
    from rtaspt.acquisition import run_acquisition
    from rtaspt.config import load_config
    from rtaspt.data_inputs import IterablePlaneInput, YXPlane
    from rtaspt.io import read_tiff

    from ix83_acquisition import (
        AcquisitionController,
        CaptureRequest,
        MockCamera,
        MockXYZStage,
        RunRecorder,
    )
    from ix83_acquisition.rtaspt_backend import RtasptBackend
    from ix83_acquisition.rtaspt_handoff import rtaspt_planes

    with TemporaryDirectory(prefix="ix83-rtaspt-") as temporary:
        root = Path(temporary)
        # Recorded raw planes -> real RTASPT input adapter, with no reacquisition.
        writer = RunRecorder(
            root, "local", context={"specimen_id": "mock", "calibration_id": "test"}
        )
        controller = AcquisitionController(MockCamera(shape_yx=(16, 16)), MockXYZStage())
        try:
            controller.start_finite(
                [CaptureRequest(timepoint=i) for i in range(3)], on_frame=writer
            )
            result = controller.wait(5)
            if result.state != "completed":
                raise RuntimeError(result.error)
            writer.finish(result)
        finally:
            writer.close()
            controller.close()
        source = IterablePlaneInput(planes=rtaspt_planes(writer.dataset_dir), axes="QYX")
        planes = list(source)
        if len(planes) != 3 or not all(isinstance(plane, YXPlane) for plane in planes):
            raise RuntimeError("RTASPT plane handoff failed")
        if [plane.coordinates["Q"] for plane in planes] != [0, 1, 2]:
            raise RuntimeError("Plane coordinate mapping was lost")

        # Real RTASPT acquisition runner -> new device backend -> its OME output.
        original = load_config(
            bundle_root / "03_external/Realtime-Anisotropy-SPT-Analysis/configs/mock.yaml"
        )
        config = replace(
            original,
            acquisition=replace(
                original.acquisition, output_dir=str(root), dataset_name="rtaspt", frames=3
            ),
            detector_config=replace(original.detector_config, type="single"),
        )
        backend = RtasptBackend(
            MockCamera(shape_yx=(16, 16)),
            MockXYZStage(),
            channel_group=config.acquisition.channel_group,
        )
        expected = []
        acquired = run_acquisition(
            config,
            backend=backend,
            show_progress=False,
            frame_callback=lambda event, pixels: expected.append(pixels.copy()),
        )
        raw, axes = read_tiff(acquired.raw_path)
        np.testing.assert_array_equal(raw, np.stack(expected))
        metadata = json.loads(acquired.metadata_path.read_text())
        if acquired.frames_acquired != len(expected) or len(metadata["events"]) != len(expected):
            raise RuntimeError("RTASPT raw output/event count mismatch")
        print(
            json.dumps(
                {
                    "result": "PASS",
                    "python": sys.version.split()[0],
                    "numpy": version("numpy"),
                    "replayed_planes": len(planes),
                    "rtaspt_raw_frames": acquired.frames_acquired,
                    "rtaspt_raw_axes": axes,
                    "raw_pixels_equal": True,
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
