"""Authorized fixed-position PVCAM capture/OME integrity benchmark.

Measures serial snaps, the actual RTASPT acquisition runner/OME writer, and a
finite Core sequence with stop-on-overflow. No stage/illumination commands.
Temporary full-resolution datasets are checked page by page, then removed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from dataclasses import asdict, replace
from pathlib import Path
from tempfile import TemporaryDirectory
from xml.etree import ElementTree

import numpy as np

package_root = Path(__file__).resolve().parents[1]
bundle_root = package_root.parents[1]
sys.path.insert(0, str(package_root / "src"))
sys.path.insert(0, str(bundle_root / "03_external/Realtime-Anisotropy-SPT-Analysis/src"))


def main() -> None:
    import tifffile
    from rtaspt.acquisition import run_acquisition
    from rtaspt.config import load_config
    from rtaspt.io import write_ome_stack

    from ix83_acquisition.pycromanager import (
        PycroManagerCamera,
        PycroManagerXYZStage,
        connect_core,
    )

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-real", action="store_true", required=True)
    parser.add_argument("--frames", type=int, default=64)
    parser.add_argument("--sequence-only", action="store_true")
    parser.add_argument(
        "--defer-hashing",
        action="store_true",
        help="Verify sequence hashes after draining to isolate transfer throughput",
    )
    parser.add_argument(
        "--buffer-mb",
        type=int,
        choices=(250, 512, 1024),
        help="Temporary Core buffer size; original size is restored",
    )
    args = parser.parse_args()
    if not args.allow_real or not 16 <= args.frames <= 256:
        raise ValueError("Authorize real camera access and select 16..256 frames")
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError("Actual RTASPT writer check requires Python 3.12")
    core = connect_core(timeout=5000)
    if core.get_camera_device() != "Camera-1" or core.get_device_library("Camera-1") != "PVCAM":
        raise RuntimeError("Expected the operator-loaded PVCAM Camera-1")
    if core.is_sequence_running() or core.get_remaining_image_count():
        raise RuntimeError("Stop MMStudio Live and finish its queued acquisition first")
    if core.get_auto_shutter() or core.get_shutter_device():
        raise RuntimeError("Unexpected shutter binding; leave illumination untouched")
    stage = PycroManagerXYZStage(core, xy_stage="XYStage", z_stage="ZStage")
    initial = stage.position
    exposure = core.get_exposure()
    binning = core.get_property("Camera-1", "Binning")
    readout = core.get_property("Camera-1", "ReadoutRate")
    initial_buffer_mb = core.get_circular_buffer_memory_footprint()
    output = bundle_root / f"08_session_logs/camera-throughput-{time.time_ns()}.json"
    report = {
        "state": "running",
        "frames_per_trial": args.frames,
        "exposure_ms": 10,
        "binning": binning,
        "readout": readout,
        "initial_position_um": asdict(initial),
        "stage_commands": 0,
        "initial_buffer_mb": initial_buffer_mb,
        "trials": [],
    }
    sequence_owned = False

    def journal():
        output.write_text(json.dumps(report, indent=2), encoding="utf-8")

    def digest(pixels):
        return hashlib.sha256(memoryview(np.ascontiguousarray(pixels)).cast("B")).hexdigest()

    def tagged_pixels(tagged):
        return (
            np.asarray(tagged.pix)
            .reshape(int(tagged.tags["Height"]), int(tagged.tags["Width"]))
            .copy()
        )

    def simple_tags(tagged):
        return {
            str(key): value
            for key, value in tagged.tags.items()
            if any(
                word in str(key).lower()
                for word in ("frame", "image", "time", "camera", "width", "height")
            )
            and isinstance(value, (str, int, float, bool, type(None)))
        }

    def verify(path, expected):
        started = time.monotonic()
        with tifffile.TiffFile(path) as tiff:
            hashes = [digest(page.asarray()) for page in tiff.pages]
            ome = ElementTree.fromstring(tiff.ome_metadata)
            pixels = ome.find("{*}Image/{*}Pixels")
            result = {
                "pages": len(tiff.pages),
                "series_axes": tiff.series[0].axes,
                "series_shape": list(tiff.series[0].shape),
                "ome_dimensions": {key: pixels.attrib[key] for key in ("SizeT", "SizeC", "SizeZ")},
                "pixels_and_order_equal": hashes == expected,
                "file_bytes": path.stat().st_size,
            }
        result["verification_s"] = time.monotonic() - started
        if hashes != expected:
            raise RuntimeError(f"OME frame count/order/pixel mismatch: {result}")
        return result

    def save_stack(name, frames, hashes, trial, directory):
        stack_started = time.monotonic()
        stack = np.stack(frames)
        trial["stack_copy_s"] = time.monotonic() - stack_started
        path = directory / f"{name}.ome.tif"
        started = time.monotonic()
        write_ome_stack(path, stack, "QYX")
        trial["write_s"] = time.monotonic() - started
        trial["write_mib_s"] = stack.nbytes / 2**20 / trial["write_s"]
        del stack
        trial["ome"] = verify(path, hashes)

    journal()
    try:
        core.set_exposure(10)
        if args.buffer_mb is not None:
            core.set_circular_buffer_memory_footprint(args.buffer_mb)
        report["buffer_mb"] = core.get_circular_buffer_memory_footprint()
        with TemporaryDirectory(
            prefix="ix83-throughput-", dir=package_root / "recordings"
        ) as temporary:
            directory = Path(temporary)
            if not args.sequence_only:
                # Same snap/getTaggedImage/copy path as the existing RTASPT adapter.
                trial = {"name": "serial_core_snap", "requested": args.frames, "timings_s": []}
                report["trials"].append(trial)
                print(f"Starting serial capture: {args.frames} full frames", flush=True)
                frames, hashes, metadata = [], [], []
                started = time.monotonic()
                for _ in range(args.frames):
                    before = time.monotonic()
                    core.snap_image()
                    triggered = time.monotonic()
                    tagged = core.get_tagged_image()
                    transferred = time.monotonic()
                    pixels = tagged_pixels(tagged)
                    copied = time.monotonic()
                    frames.append(pixels)
                    hashes.append(digest(pixels))
                    metadata.append(simple_tags(tagged))
                    trial["timings_s"].append(
                        {
                            "snap": triggered - before,
                            "get_tagged": transferred - triggered,
                            "copy": copied - transferred,
                        }
                    )
                trial.update(
                    capture_s=time.monotonic() - started, captured=len(frames), tags=metadata
                )
                trial["capture_fps"] = len(frames) / trial["capture_s"]
                trial["shape_yx"] = list(frames[0].shape)
                save_stack("serial", frames, hashes, trial, directory)
                del frames, hashes
                journal()
                print(f"Serial: {trial['capture_fps']:.2f} fps; OME verified", flush=True)

                # Real RTASPT event loop, event table and original OME writer.
                # The mixed cfg has no channel presets. Keep its single camera fixed
                # rather than creating/changing hardware config groups for this test.
                trial = {
                    "name": "rtaspt_runner_fixed_camera",
                    "requested": args.frames,
                    "channel_presets": "not switched; mixed cfg has none",
                }
                report["trials"].append(trial)
                camera = PycroManagerCamera(core)
                hashes, times = [], []

                class FixedCameraBackend:
                    def acquire(self, event):
                        before = time.monotonic()
                        pixels = camera.snap(
                            stage_position=initial, exposure_ms=event.exposure_ms
                        ).pixels
                        times.append(time.monotonic() - before)
                        return pixels

                    def close(self):
                        camera.close()

                def on_frame(event, pixels):
                    hashes.append(digest(pixels))

                config = load_config(package_root / "configs/rtaspt_mock.yaml")
                config = replace(
                    config,
                    acquisition=replace(
                        config.acquisition,
                        output_dir=str(directory),
                        dataset_name="rtaspt",
                        frames=args.frames,
                        interval_s=0,
                    ),
                )
                print(f"Starting RTASPT runner: {args.frames} frames", flush=True)
                started = time.monotonic()
                result = run_acquisition(
                    config,
                    backend=FixedCameraBackend(),
                    show_progress=False,
                    frame_callback=on_frame,
                )
                trial.update(
                    total_run_s=time.monotonic() - started,
                    captured=result.frames_acquired,
                    capture_call_s=sum(times),
                    frame_call_s=times,
                )
                trial["capture_call_fps"] = len(times) / sum(times)
                trial["end_to_end_fps"] = result.frames_acquired / trial["total_run_s"]
                trial["ome"] = verify(result.raw_path, hashes)
                events = json.loads(result.metadata_path.read_text())["events"]
                trial["events"] = len(events)
                if len(events) != args.frames or [event["frame"] for event in events] != list(
                    range(args.frames)
                ):
                    raise RuntimeError("RTASPT event sequence/count mismatch")
                journal()
                print(
                    f"RTASPT: {trial['end_to_end_fps']:.2f} fps; {trial['ome']['pages']} OME pages verified",
                    flush=True,
                )

            # Sequence producer can outrun Python/ZMQ transfer. Preserve the
            # configured Core buffer and stop explicitly on overflow, never allow
            # overwriting frames. Drain all queued frames even after camera stops.
            trial = {
                "name": "core_sequence_to_python",
                "requested": args.frames,
                "stop_on_overflow": True,
                "timings_s": [],
                "hashing_during_drain": not args.defer_hashing,
            }
            report["trials"].append(trial)
            core.initialize_circular_buffer()
            trial["buffer_capacity_frames"] = core.get_buffer_total_capacity()
            frames, hashes, metadata = [], [], []
            print(
                f"Starting finite camera sequence; buffer capacity {trial['buffer_capacity_frames']} frames",
                flush=True,
            )
            started = time.monotonic()
            sequence_owned = True
            core.start_sequence_acquisition(args.frames, 0.0, True)
            deadline = time.monotonic() + max(60, args.frames)
            stopped_after_s = None
            while True:
                remaining = core.get_remaining_image_count()
                running = core.is_sequence_running()
                if not running and stopped_after_s is None:
                    stopped_after_s = time.monotonic() - started
                if remaining:
                    before = time.monotonic()
                    tagged = core.pop_next_tagged_image()
                    pixels = tagged_pixels(tagged)
                    trial["timings_s"].append(time.monotonic() - before)
                    frames.append(pixels)
                    if not args.defer_hashing:
                        hashes.append(digest(pixels))
                    metadata.append(simple_tags(tagged))
                elif not running:
                    # Recheck the queue after the camera's final state read, so a
                    # frame inserted between the two reads cannot be left behind.
                    if core.get_remaining_image_count() == 0:
                        break
                else:
                    time.sleep(0.001)
                if time.monotonic() > deadline:
                    raise TimeoutError("Finite camera sequence did not finish")
            elapsed = time.monotonic() - started
            trial.update(
                captured=len(frames),
                received_fps=len(frames) / elapsed,
                capture_and_drain_s=elapsed,
                camera_stopped_observed_s=stopped_after_s,
                buffer_overflowed=core.is_buffer_overflowed(),
                tags=metadata,
            )
            indices = [int(tags["ImageNumber"]) for tags in metadata if "ImageNumber" in tags]
            camera_indices = [
                int(tags["PVCAM-FrameNr"]) for tags in metadata if "PVCAM-FrameNr" in tags
            ]
            trial["core_image_numbers_contiguous"] = bool(indices) and indices == list(
                range(indices[0], indices[0] + len(frames))
            )
            trial["camera_frame_numbers_contiguous"] = bool(
                camera_indices
            ) and camera_indices == list(range(camera_indices[0], camera_indices[0] + len(frames)))
            if len(metadata) > 1 and all("TimeStampMsec" in tags for tags in metadata):
                span_ms = float(metadata[-1]["TimeStampMsec"]) - float(metadata[0]["TimeStampMsec"])
                trial["producer_fps_from_timestamps"] = (len(metadata) - 1) * 1000 / span_ms
            core.stop_sequence_acquisition()
            sequence_owned = False
            if args.defer_hashing:
                hashing_started = time.monotonic()
                hashes = [digest(frame) for frame in frames]
                trial["hash_validation_s_after_drain"] = time.monotonic() - hashing_started
            if frames:
                save_stack("sequence", frames, hashes, trial, directory)
            trial["requested_count_met"] = len(frames) == args.frames
            journal()
            print(
                f"Sequence: {len(frames)}/{args.frames} received; overflow={trial['buffer_overflowed']}; saved pages verified",
                flush=True,
            )
        report["state"] = "completed"
    except Exception as exc:
        report.update(state="failed", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        try:
            if sequence_owned:
                core.stop_sequence_acquisition()
            if args.buffer_mb is not None:
                report["queued_frames_before_buffer_restore"] = core.get_remaining_image_count()
                core.set_circular_buffer_memory_footprint(initial_buffer_mb)
                core.initialize_circular_buffer()
            report["buffer_size_restored"] = (
                core.get_circular_buffer_memory_footprint() == initial_buffer_mb
            )
            core.set_exposure(exposure)
            report.update(
                final_position_um=asdict(stage.position),
                exposure_restored=core.get_exposure() == exposure,
                binning_unchanged=core.get_property("Camera-1", "Binning") == binning,
                sequence_running_at_end=core.is_sequence_running(),
            )
        finally:
            report["finished_ns"] = time.time_ns()
            journal()
    print(f"Report: {output}", flush=True)
    print(
        json.dumps(
            [
                {
                    key: value
                    for key, value in trial.items()
                    if key not in ("tags", "timings_s", "frame_call_s")
                }
                for trial in report["trials"]
            ],
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
