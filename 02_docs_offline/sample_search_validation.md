# Sample-search prototype and validation

The owning architecture is the [device bundle setup plan](device_bundle_setup_plan.md), based on RTASPT's [sample-search workflow research](../03_external/Realtime-Anisotropy-SPT-Analysis/docs/sample-search-workflow-research.md), inspected at commit `56a09dd487fc48e267f88605470fea74d54597dd` on 2026-10-04.
The [local library](../03_external/sample_search/README.md) publishes recipe descriptors, pure calculations and hardware-free records/serialization under the provisional `samplescout` import. The bundle runner, runtime scanning and device execution live in `04_code/sample_search/ix83_search_host/`.
Commands use the existing acquisition integration environment with `03_external/sample_search` and `04_code/sample_search` on `PYTHONPATH`. The operator requested no repository/distribution packaging yet.

## Implementation boundary

The library owns recipe descriptors, calibrated geometry and pure calculations, typed observations/results, target deduplication/review metadata, and hardware-free record/checkpoint replay/serialization. The [IX83 host](../04_code/sample_search/ix83_search_host/) owns runner transitions and cancellation; its executor owns stage/camera commands, software limits, fixed Z, readback validation, resource ownership and storage coordination.
Processing remains in RTASPT; its existing `YXPlane` handoff accepts the generated target movies.
Run contexts link specimen, target, phase, request, calibration and coordinate frame to their separate datasets.

The baseline detector is independent threshold segmentation and connected components.
AutoScanJ's manuals, fixed/live tiling/block workflows and supplied TIFFs are references; its MM1.4 Beanshell scripts are not an acquisition backend for this MM2 installation.
No donor macros are translated into the new core.

## Hardware-free gates

The seeded 4 x 3 overlap survey checks physical coverage, seam duplicates, nearby distinct objects, a dim object, blank tiles and exclusion of an outside-region object.
Affine tests cover rotation/reflection, axis exchange, ROI/binning and full-image centring.
Half-open component bounds are mapped from pixel edges, including reflection and rotation.
Synthetic revisit error measured against independent seeded object positions is at most 0.376 um, within the declared 2 um tolerance; commanded stage readback error is recorded separately.
Decision replay uses saved detections rather than a new camera acquisition.
The [seeded validation artifact](../03_external/sample_search/docs/seeded_search_validation.json) and [plot](../03_external/sample_search/docs/seeded_search_validation.png) record the executable synthetic case.

The [bundle mock check](../04_code/sample_search/validate_seeded_search.py) passed 12 survey tiles, five selected targets and 15 recorded movie frames at 50 ms exposure.
Every stored frame passed checksum replay; actual RTASPT input accepted all 15 movie planes.
Replayed observations reproduced the same target IDs.
Motion-envelope rejection, fixed Z, external-motion detection, unacknowledged moves, blocked-camera ownership and unsupported ROI binding have hardware-free tests.

The [review/resume check](../04_code/sample_search/validate_review_checkpoint.py) passed with 12 saved survey tiles and five candidates, a persisted/reloaded review checkpoint, two accepted targets and one manual replacement with a reason.
No survey was repeated; all nine 50 ms movie frames passed checksum replay and actual RTASPT input.
The [offline review page](../03_external/sample_search/docs/review_demo.html) displays this synthetic survey with calibrated footprints and candidate overlays; it performs no device calls.
Review decisions bind run, specimen, coordinate frame, calibration and candidate manifest; resume additionally verifies recipe/calibration/region/fixed-Z binding and observation freshness before commands.
The default freshness limit is 300 seconds. A longer review requires an explicitly chosen specimen-appropriate limit or a fresh survey.
Checksummed checkpoints detect accidental edits, but cannot establish exactly-once physical recovery from an older file after motion or acquisition has begun. Operators must reconcile the action ledger and recording evidence before restarting.
The page's JavaScript controls were exercised with a Qt DOM stub; full browser interaction was not automatically tested.

On 2026-10-04 the Python detector processed all 100 supplied AutoScanJ HeLa fixed-tiling TIFFs (256 x 256 uint8), producing 2,541 components with the configured Otsu/12–100-pixel area baseline.
Independent SciPy component counts matched all 100 planes; weighted-centroid checks measured zero difference in the supplied-data report.
The first three images also passed a separately run count/centroid comparison at 1e-10-pixel tolerance.
The [AutoScanJ reference record](../03_external/sample_search/docs/autoscan_reference.md) gives exact commit, source/manual provenance, settings and limitations.
Installed ImageJ 1.54p independently matched every plane's component count and sorted foreground areas: 2,541 total, using the same explicit threshold masks and area filter.
The [headless validator](../03_external/sample_search/scripts/validate_imagej_components.py) records the jar/input hashes and per-plane results without running AutoScanJ acquisition macros.
This is segmentation consistency evidence; complete AutoScanJ detector parity and annotation-based recall were not measured.
The [source/manual audit](../03_external/sample_search/docs/manual_workflow_audit.md) also found no stage positions or explicit physical-size units in those supplied tiles, so they do not establish a verified physical-coordinate montage or overlap test.

The combined runtime suite passes 127 tests across the pure library, IX83 execution host and acquisition baseline. An isolated import check rejects acquisition-host/framework imports while compiling a library recipe. New offline review and image registration checks do not extend hardware acceptance.
Ruff passes across the new source, scripts and tests; strict mypy passes across all twelve library/host/adapter source files.
Typed local dataset resolution verifies the referenced manifest digest and summary metadata; NPY/OME replay verifies the frame ledger and stored pixels. Legacy untyped local paths remain readable without typed-manifest verification.
Synthetic success is not biological sensitivity, specimen recall or optical calibration evidence.

## Real-hardware operating envelope

The operator authorized independent real scanning after mock and supplied-data validation, retaining the previous maximum 1 mm displacement per XY axis.
The [mechanical check](../04_code/sample_search/validate_hardware_scan.py) uses only a 50 x 25 um serpentine excursion about the recorded origin, a 1 mm-wide software envelope, six 50 ms survey snaps and one five-frame 50 ms control movie.
It preserves binning/illumination and physical Z, records every target/readback and returns only when device outcome and ownership are known.
Exposure is restored after camera cleanup.

The 2026-10-04 mechanical check passed with six 2048 x 2048 uint16 survey frames and all five requested control-movie frames saved and checksum-verified.
RTASPT's actual `IterablePlaneInput` consumed all five real movie planes as TYX.
The largest per-axis move/readback error was 0.2 um.
Initial XYZ was (0.7, 3.4, 0) um; final readback was (0.6, 3.2, 0) um, within the declared 0.5 um tolerance.
Exposure restoration and unchanged binning were verified; no illumination or physical-Z command occurred.
The loaded mixed profile SHA-256 was `58bd8537292fe5892509842156174406c9dc2880ca224544798a6036303167dc`, with Pycro-Manager 1.0.2/PyJavaZ 1.2.8 and Java bridge protocol 5.1.0.
The detailed journal is local `08_session_logs/sample-search-hardware-1791106795431591200.json`; raw acceptance data remain ignored under `04_code/sample_search/recordings/`.

This mechanical check makes no image-to-stage calibration claim and does not select real biological objects.
The subsequent [explicit scanning procedure](../03_external/sample_search/docs/scanning_usage.md), modeled on the original Beanshell column-major loop, also passed a six-position 50 x 25 um Pycro-Manager scan with all six frames checksum-verified and a bounded return to origin.
It supports requested stage spacing independently of optical calibration; the source procedure remains fixed Z and preserves the loaded channel/ROI/binning.
The current objective, calibrated camera transform and stable fluorescent specimen are not established by the loaded MM configuration.
Calibrated specimen search remains a separate acceptance gate.

## Image registration mock

The local [`samplescout.registration`](../03_external/sample_search/samplescout/registration.py) utility estimates adjacent-image translations with phase-correlation-seeded OpenCV ECC, composes an ordered image sequence and blends an output mosaic. Its coordinates are pixels; it does not calculate stage displacement, physical scale or an optical calibration.

Four unit tests cover translation recovery, accumulated sequence offsets/blending, low-quality inputs and invalid shapes. The AutoScanJ validation script used three 600 x 600 crops from its supplied 2560 x 2560 HeLa montage, offset by 200 px; estimated horizontal origins were 0, 199.978 and 399.871 px (maximum error 0.129 px). Those are source-derived mock overlaps created by cropping the montage. The supplied 100 individual 256 x 256 TIFFs have no documented stage positions or overlap, so this check does not claim to stitch the original acquisitions or calibrate stage-to-camera geometry.

## Remaining work

Measure real-specimen detection recall against annotations, target revisit error, coverage and data volume using a calibrated same-objective profile.
Then validate the offline review interface with the operator and add bounded focus policy and further processing integration as required by that specimen case.
Before the first IX83 recipe can be accepted, implement operator-confirmed well corners, the relative body focus-lock binding, temporal-median per-channel maps, per-channel Otsu metrics and paired-channel suggestions, split-detector-aware transforms, and the survey-map review UI. The new review CLI currently opens the saved coverage/tile-image page only. Z focus maps, distributed graphs, continuous motion, fluidics and agent authorship remain deferred.
