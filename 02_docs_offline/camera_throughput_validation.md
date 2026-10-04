# PVCAM capture throughput and OME-TIFF integrity

Audit: 2026-10-04. Operator authorized real-camera validation after loading `ix83_mixed_ludl_pvcam_mmconfig.cfg` (SHA256 `58bd8537292fe5892509842156174406c9dc2880ca224544798a6036303167dc`). Pycro-Manager 1.0.2 / PyJavaZ 1.2.8, Python 3.12.13, NumPy 1.26.4, tifffile 2025.1.10. RTASPT base commit `56a09dd487fc48e267f88605470fea74d54597dd`, with the current uncommitted backend-injection hooks. These are local measurements, not a released-system qualification.

## Configuration and method

Photometrics camera via PVCAM Camera-1, 2048 x 2048 YX, uint16, 1x1 binning, 10 ms exposure, 100MHz 16bit readout, 1-HDR gain, internal trigger. Each frame is 8 MiB. Camera timestamps indicate approximately 43.6 fps during sequences, or 349 MiB/s of raw pixels. Readout/exposure overlap means 10 ms exposure does not establish 100 fps.

The [benchmark script](../04_code/ix83_acquisition/scripts/camera_throughput_check.py) measures serial Core snaps, actual RTASPT `run_acquisition` with a fixed-camera backend, and finite Core sequences. The loaded mixed profile has no channel presets; the RTASPT trial intentionally retains the current single camera without switching channel groups. No tracking, anisotropy, Qt preview or multichannel switching is included. Serial/RTASPT trials include an audit checksum callback, so their end-to-end rates include validation overhead.

Every saved TIFF page is compared with the corresponding captured frame by SHA256, in order. OME dimensions, physical page count and event count are checked separately. For sequences, `ImageNumber` and `PVCAM-FrameNr` establish continuity of received frames; requested versus received counts identify early termination. `stopOnOverflow=True` is used: Core overflow terminates acquisition instead of permitting frame skipping, as specified by the [MMCore API](https://micro-manager.org/apidoc/MMCore/latest/class_c_m_m_core.html). All queued images are drained after the camera stops, including a final queue recheck.

XY and demo Z are read only throughout the throughput tests. No stage commands or illumination changes occurred. Exposure and the original 250 MB Core buffer size were restored; binning remained unchanged. Full TIFFs were temporary and removed after verification; timestamped JSON measurement records remain in local `08_session_logs/`.

## Initial 10 ms stress results

| Trial | Core buffer | Requested / received / TIFF pages | Measured rate | Overflow | TIFF integrity |
| --- | --- | --- | --- | --- | --- |
| Serial Core snaps, inline hashes | 250 MB | 64 / 64 / 64 | 5.12 fps capture | Not a sequence | Exact pixels/order |
| RTASPT runner + audit callback | 250 MB | 64 / 64 / 64 | 4.51 fps end to end; 6.29 fps inside camera calls | Not a sequence | Exact pixels/order; 64 events |
| Sequence, inline hashes | 250 MB / 31 frames | 64 / 53 / 53 | 16.47 fps capture and drain | Yes | Exact received pixels/order |
| Sequence, inline hashes | 512 MB / 64 frames | 64 / 64 / 64 | 17.14 fps capture and drain | No | Exact pixels/order |
| Sequence, hashes after drain | 512 MB / 64 frames | 128 / 128 / 128 | 31.50 fps capture and drain | No | Exact pixels/order; contiguous hardware IDs |
| Sequence, hashes after drain | 250 MB / 31 frames | 128 / 128 / 128 | 34.28 fps capture and drain | No | Exact pixels/order; contiguous hardware IDs |
| Sequence, hashes after drain | 250 MB / 31 frames | 256 / 160 / 160 | 34.13 fps capture and drain | Yes | Exact received pixels/order; contiguous hardware IDs |
| Sequence, hashes after drain | 512 MB / 64 frames | 256 / 256 / 256 | 35.08 fps capture and drain | No | Exact pixels/order; contiguous hardware IDs |

The 256-frame success produced a 2.00 GiB OME-TIFF with SizeT=256, SizeC=1, SizeZ=1. Its write call took 9.67 s, approximately 212 MiB/s. Smaller writes measured approximately 275–334 MiB/s. These are buffered filesystem write-call rates; no power-loss durability, cache-flushed sustained disk benchmark or simultaneous capture/write guarantee is established. Deferred checksum verification itself cost 5.11 s for 256 frames and was excluded from capture/drain timing.

## Interpretation and next gate

No frames were lost by the tested OME writer: every file contained exactly the received frames, in order and pixel-identical. The earlier reported RTASPT writer issue was not reproduced in the current serial runner. An acquisition-side shortfall was reproduced through Core buffer overflow, including a longer sequence with checksums deferred. At 250 MB, the 256-frame sequence stopped after 160 frames; it must be treated as incomplete, even though its 160-page TIFF is valid.

Increasing the buffer to 512 MB allowed this 256-frame burst to complete. It did not establish sustained 43.6 fps operation: measured Python draining remained slower than production, and batch writes followed capture rather than overlapping it. Moving per-frame hashing out of the drain loop improved measured transfer throughput substantially. Calibration, tracking, processing and GUI work would consume additional resources unless isolated from the complete recording path.

The implemented native sequence baseline now uses the operator's revised 50 ms exposure/20 fps target and the concurrent writer described below. Preserve declared producer/consumer rates, buffer bounds and an explicit overflow policy. Hardware frame numbers/timestamps, requested/received/written counts and the completion reason must remain inspectable. A short acquisition reports failure or cancellation. Complete recording stays independent of lossy preview and expensive processing. Increasing RAM alone cannot establish a stable queue when the average consumer is slower than the producer; camera-rate 43.6 fps storage remains unqualified.

For another operator-authorized, fixed-position sequence measurement from the package directory, using its separate Python 3.12 environment with both `rtaspt-controller-check` and `pycromanager` extras:

```powershell
.venv-integration/Scripts/python.exe scripts/camera_throughput_check.py --allow-real --frames 256 --sequence-only --buffer-mb 512 --defer-hashing
```

The buffer change in that stress benchmark is temporary.

## Implemented 50 ms / 20 fps recording

`PycroManagerCamera.stream_sequence`, `SequenceRequest`/`AcquisitionController.start_sequence` and `OMERecorder` now provide a separate fixed-position, fixed-channel native sequence recording path. Camera transfer and disk/checksum work run on separate workers with a bounded queue; complete storage does not depend on the preview ring. Core overflow, missing/duplicate hardware IDs, incomplete counts, camera stalls, writer queue exhaustion and disk errors fail explicitly. Finalization checks submitted/written/requested counts, writes OME metadata for the actual prefix and flushes/fsyncs files. Failed writer output is marked unverified; interrupted finalization has no completed manifest. BigTIFF is selected explicitly to support files above 4 GiB.

Actual real-camera recording, 2026-10-04:

| Measurement | Result |
| --- | --- |
| Exposure / measured frame cadence | 50 ms / 19.99 fps |
| Requested / received / written / replayed | 600 / 600 / 600 / 600 |
| Capture and drain | 30.56 s, 19.63 fps including startup/transfer |
| Capture plus final file flush | 34.50 s |
| Observed maximum writer queue depth | 1 frame, capacity 32 |
| Core overflow / unread frames after stop | None / 0 |
| Core and PVCAM frame IDs | Contiguous |
| File size and axes | 4.69 GiB OME BigTIFF, TYX |
| Pixel integrity / actual RTASPT handoff | Every page hash verified / 600 YXPlane inputs accepted |
| Native cancellation | 21/200 frames saved and verified; cancelled state, camera stopped, no unread frames |

Exposure was restored to its prior value and the original 250 MB Core buffer was retained. No stage or illumination commands occurred. Test TIFFs were temporary and removed after verification; local reports are `sequence-20fps-1791103754234654100.json` and the timestamped cancellation report in `08_session_logs/`.

Forty-four hardware-free package tests cover native counts/gaps/overflow/stalls/cancellation, writer bounds/errors/corruption, partial recordings and explicit worker completion before releasing ownership. Source Ruff and strict mypy pass. This verifies a 30 s, 20 fps recording with concurrent writes. Longer duration, simultaneous processing/GUI load and higher camera rates require their own measurements. Existing RTASPT GUI acquisition still uses the snap path; native-sequence GUI composition remains planned.
