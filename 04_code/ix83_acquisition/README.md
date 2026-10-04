# IX83 acquisition baseline

Small local package for camera/XYZ-stage devices and acquisition lifecycle, used before introducing a RedSun device bundle. Processing and GUI behavior remain owned by RTASPT and its frontend.

## Environment

From this directory:

```shell
uv sync --locked --extra ome --extra pycromanager
uv run --locked --extra pycromanager python scripts/demo_zmq_smoke.py
```

The project targets Python 3.12, matching RTASPT. The acquisition runtime stays small: NumPy is required and Pycro-Manager remains an optional extra. RTASPT handoff/controller-check extras mirror its relevant analysis dependencies and constraints. The package is locally installable and is not published on PyPI.

On 2026-10-04, the locked `.venv-integration` Python 3.12.13 environment passed the bounded mixed Ludl/PVCAM plus demo-Z hardware smoke check with Pycro-Manager 1.0.2, PyJavaZ 1.2.8 and NumPy 1.26.4. See the [run record](../../08_session_logs/2026-10-04-mixed-hardware-validation-py312.json); this is limited device-operation evidence, not full instrument acceptance.

## Ported components

- `Camera`, `XYZStage`, `Position`, `Channel` and `Frame`: typed device and image contracts. Frames carry request/target/timepoint context, sequence, stage position and host acquisition-call start/end timestamps.
- `MockXYZStage` and `MockCamera`: absolute XYZ positions with optional limits, and a seeded specimen fixed in XY coordinates. The baseline mock records Z but does not simulate optical defocus or stage timing.
- `PycroManagerCamera` and `PycroManagerXYZStage`: explicit, caller-owned Core adapters. No connection occurs on import. MMStudio Live must be stopped; adapters do not unload devices on close. Optional finite, ordered XYZ `limits_um` reject out-of-bounds targets before sending motion commands; these are software bounds, not calibrated mechanical limits.
- `AcquisitionController`: one worker for free run or finite requests, bounded/coalesced preview, complete finite-run callbacks, cancellation and completed/cancelled/failed run results. Callbacks run on the worker, so GUI consumers must route updates onto their own UI thread.
- `read_mda_settings` and `mda_timepoints`: caller-owned MMStudio settings snapshot and channel/timepoint requests. Timepoint delays apply once per timepoint, independently of channel count. GUI Z/position/custom-interval modes are rejected; explicit XYZ requests are supported separately.
- `RunRecorder` and `replay_frames`: incremental raw NPY recording, checksummed metadata and integrity-checked replay.
- `SequenceRequest` and `start_sequence`: fixed-position native camera sequences, with hardware frame numbers, source timestamps, overflow detection and cancellation that drains the captured prefix.
- `OMERecorder` and `replay_ome_frames`: bounded concurrent OME BigTIFF recording, pixel/ledger checksums and explicit requested, acquired and written counts.
- `rtaspt_handoff.rtaspt_planes`: optional replay as actual RTASPT `YXPlane` objects; imports RTASPT only when consumed.
- `RtasptBackend`: compatibility with RTASPT's injectable `acquire(event)`/`close()`/`update_config()` boundary, without importing RTASPT.

Behavioral references: RTASPT checkout `56a09dd487fc48e267f88605470fea74d54597dd`, inspected 2026-10-04, especially `src/rtaspt/acquisition_contracts.py`, `acquisition.py`, `pycromanager_backend.py` and `live.py`. The local implementation separates acquisition concerns from their original project configuration, analysis and GUI dependencies. Uncommitted frontend hooks in that checkout allow the bundle launcher to supply this package's backend; default RTASPT behavior is retained.

## Fixed-position sequence recording

From this directory, the standalone program defaults to 50 ms exposure and 100 frames. For the measured PVCAM configuration this targets 20 fps:

```shell
uv run --locked --extra ome --extra pycromanager ix83-acquire --devices mock
uv run --locked --extra ome --extra pycromanager ix83-acquire --devices mixed --allow-real --frames 600 --exposure-ms 50
```

`python -m ix83_acquisition` provides the same entry point. Mixed mode requires the operator-loaded Ludl/PVCAM/demo-Z configuration, MMStudio Live stopped, an empty Core image queue and no shutter binding. It reads the current stage position and records there. Exposure is restored after cleanup. Ctrl+C stops production, drains queued frames and finalizes a cancelled prefix.

The API is `controller.start_sequence(SequenceRequest(frames=600, exposure_ms=50), on_frame=writer)`, where `writer` is an `OMERecorder`. After `controller.wait()`, use the result returned by `writer.finish(result)` as the final status: storage failure can change capture success to failure. Close both objects in cleanup.

The storage worker performs hashing and TIFF writes independently of capture and lossy preview. A full writer queue, overflow, missing hardware frame number or short sequence fails the run explicitly. OME recording requires fixed shape, dtype, position, channel and target, with contiguous timepoints. Use the existing request/NPY path for general position/channel plans. Native source timestamps have their own clock domain; host transfer timestamps do not measure exposure timing. Final files and manifests are flushed and synced; crash recovery is not transactional.

The real 50 ms test recorded 600/600 full-resolution frames at 19.99 fps over approximately 30 seconds, with no overflow or frame-number gaps. All saved pixel hashes matched, and RTASPT consumed all 600 TYX planes. The writer queue peaked at one frame. A separate cancellation saved and verified 21 frames of a 200-frame request and left the camera stopped with no unread frames. See the [measurement record](../../02_docs_offline/camera_throughput_validation.md). The RTASPT GUI still uses its existing snap/controller path; sequence-aware GUI integration remains planned.

## Snapshot finite acquisition

```python
from ix83_acquisition import (
    AcquisitionController,
    CaptureRequest,
    MockCamera,
    MockXYZStage,
    Position,
)

controller = AcquisitionController(MockCamera(), MockXYZStage(), preview_capacity=4)
try:
    controller.start_finite(
        [
            CaptureRequest(position=Position(0, 0, 0), target_id="first"),
            CaptureRequest(position=Position(20, 0, 2), target_id="second"),
        ],
        on_frame=lambda frame: print(frame.request_id, frame.pixels.shape),
    )
    result = controller.wait(timeout=5)
    print(result)
finally:
    controller.close()
```

`start_free_run(CaptureRequest(), interval_s=0.1)` runs until `stop()` is called. Wait for stop completion before starting another run. Preview may discard old frames; persistence belongs in the finite run's `on_frame` callback. A callback error fails the run. Use `request_stop()` inside a callback to cancel without attempting to join the worker itself.

Stop is cooperative between device calls and during waits. A driver call that blocks past a timeout remains active; the controller retains ownership and rejects new runs until cleanup can finish. Run failure/cancellation does not automatically restore stage position or undo physical actions. Acquisition timestamps describe host call boundaries; stage metadata is supplied position context, not exposure-synchronized telemetry.

The local acquisition-only controller uses fixed MDA snapshots. When hosted through RTASPT, its existing controller refreshes settings between timepoints; the single-detector exposure refresh path has been checked with this backend. The compatibility backend returns pixels unchanged; split/dual detector parity remains unverified. Calibration/registration/SPT logic remains in RTASPT.

## RTASPT frontend integration

The bundle launcher [rtaspt_app.py](scripts/rtaspt_app.py) uses RTASPT's public `cli.main(..., backend_factory=...)` hook. The same factory reaches free-run, calibration snaps and the finite MDA runner. Device construction occurs on the acquisition worker for GUI runs. RTASPT retains processing, Qt event delivery and its higher-level controller; this does not replace that controller with `AcquisitionController`.

From this package directory, create the separate Python 3.12 integration environment in PowerShell:

```powershell
$env:UV_PROJECT_ENVIRONMENT = '.venv-integration'
uv sync --locked --python 3.12 --extra rtaspt-controller-check
.venv-integration/Scripts/python.exe scripts/rtaspt_app.py acquire --config configs/rtaspt_mock.yaml
.venv-integration/Scripts/python.exe scripts/rtaspt_controller_check.py
Remove-Item Env:UV_PROJECT_ENVIRONMENT
```

The default launcher selects local mock camera/XYZ devices and requires `detector_config.type: single`. `--devices demo` explicitly selects Core adapters and rejects any loaded non-Core device outside DemoCamera; it never loads a configuration or permits the mixed real-device profile. Demo mode also needs the `pycromanager` extra in the Python 3.12 environment. Core channel presets must match the YAML or active MMStudio MDA settings.

To use `--gui`, run in an environment containing RTASPT's complete napari/live dependencies and set `acquisition.freerun: true` in the YAML. The existing GUI reads MDA settings from MMStudio even when its camera/stage backend uses local mocks. The check environment above does not install napari, and rendered GUI acceptance remains pending.

On 2026-10-04, the actual RTASPT controller passed free-run/stop followed by three-frame MDA, runtime exposure refresh (10, 20, 20 ms), exact raw pixel comparison and backend cleanup. Targeted RTASPT acquisition/CLI/live/factory tests passed 95 tests with 10 skips under offscreen Qt. RTASPT source Ruff and mypy passed; mypy retains that project's existing configuration and does not check every untyped function body.

## Package checks

The [camera throughput validation](../../02_docs_offline/camera_throughput_validation.md) documents the initial 10 ms buffer-overflow stress tests and the implemented concurrent 50 ms/20 fps recording baseline. The 600-frame native run and cancellation passed with exact OME replay. Longer runs and simultaneous GUI/processing load remain unqualified.

The separately authorized [mixed hardware check](scripts/mixed_hardware_smoke.py) passed on 2026-10-04 with [Ludl/PVCAM plus demo Z](../02_mmcfg/ix83_mixed_ludl_pvcam_mmconfig.cfg). The guard accepts only that inventory/roles, MMStudio Live off and no automatic shutter binding. It uses a 1 mm-wide XY envelope about the starting readback, tests 25/100 um offsets, retains demo Z, and returns to the recorded origin. Out-of-bounds commands are rejected before device calls. A failed/uncertain move is not automatically retried; reconcile its recorded readback before selecting a recovery origin.

PVCAM produced 2048 x 2048 uint16 images, three finite frames replayed pixel-for-pixel, and free-run cancellation completed. Ludl errors were at most 0.3 um with a 0.5 um acceptance tolerance; return error was at most 0.2 um. Exposure was restored and binning/illumination were unchanged. Timing includes Python/ZMQ/device calls, not hardware trigger timing. Full optical calibration, fluorescent specimen performance and interlock acceptance remain pending. Logs are local under `08_session_logs/`; the smoke test requires explicit operator authorization and `--allow-real`.

```shell
uv run --locked --extra ome --extra pycromanager pytest
uv run --locked --extra pycromanager ruff check .
uv run --locked --extra pycromanager mypy
```

Forty-four hardware-free tests pass, Ruff passes and strict mypy passes over all package source. Tests cover stage-aware images and limits, pre-command Core motion-bound rejection, bounded preview with complete callbacks, ownership, cancellation during waits, blocked-driver cleanup, callback failure, multichannel timepoint timing, MDA settings validation, the RTASPT compatibility boundary, dataset collisions, partial/failed recordings and checksum corruption.

For demo ZMQ testing, load [ix83_demo_mmconfig.cfg](../02_mmcfg/ix83_demo_mmconfig.cfg) in Micro-Manager, enable its server and stop Live. The check rejects loaded devices outside the DemoCamera library, tests XYZ readback and image capture, then exercises finite recording/replay and free-run cancellation through the worker. Starting position, exposure and binning are restored. The current client passes without a protocol mismatch warning: three direct 512 x 512 uint8 frames, XYZ error within 0.01 um, a three-frame finite run with pixel-identical replay and a cancelled free run. No physical-device acceptance is implied.

Earlier Python 3.8.10 / Pycro-Manager 0.24.1 results are historical; that client expected protocol 4.2.0 and is superseded for this project by the isolated environment above. The instrument setup and future workflow gates are recorded in the [setup plan](../../02_docs_offline/device_bundle_setup_plan.md).

## Raw recording and replay

Pass a `RunRecorder` to the finite run's `on_frame` callback and call `finish(result)` after the worker exits. Reused dataset names allocate a suffixed directory. Local `recordings/` output is ignored by Git.

```python
from pathlib import Path
from ix83_acquisition import RunRecorder, replay_frames

writer = RunRecorder(Path("recordings"), "demo", context={"specimen_id": "mock"})
try:
    controller.start_finite(requests, on_frame=writer)
    writer.finish(controller.wait(timeout=5))
finally:
    writer.close()

for frame in replay_frames(writer.dataset_dir):
    print(frame.request_id, frame.stage_position, frame.pixels.shape)
```

The ledger preserves channel, target, request, stage, timepoint and host acquisition timestamps. Put calibration/experiment IDs in `context`. Failed and cancelled runs retain saved frames and explicit final status; captured and written counts can differ after a sink failure. Each frame and the ledger have SHA-256 checksums. Replay rejects unfinished recordings and checksum mismatches. A crash may leave an unreferenced raw file; this baseline does not promise transactional recovery or replay of hardware actions.

The interchange axis is `QYX`: Q indexes arrivals, independently of T, channel and target metadata. Keep the ledger as context when handing planes to RTASPT. Generic handoff does not automatically adapt TIFF-specific reconstruction consumers or establish a published storage format.

## Actual RTASPT interface check

The `rtaspt-check` extra contains only the dependencies needed to inspect RTASPT's acquisition/data modules. It does not install its full GUI/analysis distribution. Use a separate Python 3.12 environment as required by the RTASPT checkout:

```powershell
$env:UV_PROJECT_ENVIRONMENT = "$PWD/.venv-integration"
uv sync --locked --python 3.12.13 --extra rtaspt-check --no-default-groups
uv run --locked --python 3.12.13 --extra rtaspt-check --no-default-groups python scripts/rtaspt_handoff_check.py
Remove-Item Env:UV_PROJECT_ENVIRONMENT
```

On 2026-10-04, this passed with Python 3.12.13 and NumPy 1.26.4 against RTASPT commit `56a09dd487fc48e267f88605470fea74d54597dd`. Three recorded frames became actual `YXPlane` objects consumed by `IterablePlaneInput`; the original `run_acquisition` used the new backend and wrote three raw TIFF frames matching captured pixels and metadata. These are targeted single-detector acquisition/data checks, not full GUI or analysis validation. External RTASPT source and pins were preserved.
