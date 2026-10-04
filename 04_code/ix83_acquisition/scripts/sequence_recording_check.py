"""Authorized 50 ms/20 fps real-camera sequence/OME/RTASPT handoff check.

Fixed position, no illumination commands. Full images are temporary; measurement
JSON stays in local session logs. Requires Python 3.12 with RTASPT-check deps.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory

package_root = Path(__file__).resolve().parents[1]
bundle_root = package_root.parents[1]
sys.path.insert(0, str(package_root / "src"))
sys.path.insert(0, str(bundle_root / "03_external/Realtime-Anisotropy-SPT-Analysis/src"))


def main() -> None:
    from rtaspt.data_inputs import IterablePlaneInput

    from ix83_acquisition.__main__ import main as acquire
    from ix83_acquisition.rtaspt_handoff import rtaspt_planes

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-real", action="store_true", required=True)
    parser.add_argument("--frames", type=int, default=600)
    args = parser.parse_args()
    if not args.allow_real:
        raise RuntimeError("Real camera authorization required")
    recordings = package_root / "recordings"
    recordings.mkdir(exist_ok=True)
    with TemporaryDirectory(prefix="ix83-20fps-", dir=recordings) as temporary:
        root = Path(temporary)
        started = time.monotonic()
        status = acquire(["--devices", "mixed", "--allow-real", "--frames", str(args.frames),
                          "--exposure-ms", "50", "--output", str(root), "--name", "sequence"])
        elapsed = time.monotonic() - started
        if status != 0:
            raise RuntimeError("Sequence did not complete; inspect the acquisition result above")
        dataset = root / "sequence"
        manifest = json.loads((dataset / "run_metadata.json").read_text())
        lines = (dataset / "frames.jsonl").read_text().splitlines()
        records = [json.loads(line) for line in lines[1:]]
        assert len(records) == manifest["frames_written"] == args.frames
        assert [record["core_image_number"] for record in records] == list(range(args.frames))
        camera_numbers = [record["camera_frame_number"] for record in records]
        assert camera_numbers == list(range(camera_numbers[0], camera_numbers[0]+args.frames))
        timestamps = [record["source_timestamp_ms"] for record in records]
        source_fps = (args.frames - 1) * 1000 / (timestamps[-1]-timestamps[0])
        assert 19 <= source_fps <= 21, source_fps
        # Checks all TIFF page hashes while handing actual YXPlane objects to
        # RTASPT. No second whole-stack allocation or inference from preview.
        source = IterablePlaneInput(planes=rtaspt_planes(dataset), axes="TYX")
        count = 0
        shape = None
        verify_started = time.monotonic()
        for plane in source:
            assert plane.coordinates["T"] == count
            shape = list(plane.pixels.shape)
            count += 1
        assert count == args.frames
        report = {"result": "PASS", "requested": args.frames, "written": count,
                  "exposure_ms": 50, "source_fps": source_fps, "elapsed_capture_and_finalize_s": elapsed,
                  "max_writer_queue_depth": manifest["max_queue_depth"], "shape_yx": shape,
                  "all_pixel_hashes_verified": True, "hardware_ids_contiguous": True,
                  "rtaspt_axes": "TYX", "rtaspt_planes": count,
                  "verification_s": time.monotonic()-verify_started,
                  "raw_bytes": (dataset / "raw.ome.tif").stat().st_size}
        path = bundle_root / f"08_session_logs/sequence-20fps-{time.time_ns()}.json"
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        print(f"Report: {path}")


if __name__ == "__main__":
    main()
