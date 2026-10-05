# Local sample-search prototype

Backend-independent library for same-objective, two-pass tiled survey and targeted acquisition, following the [workflow research](../Realtime-Anisotropy-SPT-Analysis/docs/sample-search-workflow-research.md). It publishes recipe descriptors, pure grid/geometry calculations, review metadata, and hardware-free run/checkpoint records and serialization. Version 3 run/replay records preserve named uppercase axes and typed dataset references; the bundle host owns typed execution requests/results, orchestration transitions, device calls, cancellation, and recording/storage coordination. Version 1/2 records remain readable.
`samplescout` is a provisional import name. This is a local source tree: no build metadata, distribution, new Git repository or submodule pin has been created.
Use the existing IX83 acquisition environment for this run; dependencies will be formalized later.

## Run from the bundle root

```powershell
$env:PYTHONPATH = "$PWD/03_external/sample_search;$PWD/04_code/sample_search"
04_code/ix83_acquisition/.venv-integration/Scripts/python.exe -m pytest 03_external/sample_search/tests 04_code/sample_search/tests 04_code/ix83_acquisition/tests -q
04_code/ix83_acquisition/.venv-integration/Scripts/python.exe 04_code/sample_search/validate_seeded_search.py
04_code/ix83_acquisition/.venv-integration/Scripts/python.exe 04_code/sample_search/validate_mock_search.py
04_code/ix83_acquisition/.venv-integration/Scripts/python.exe 04_code/sample_search/validate_reviewed_search.py
04_code/ix83_acquisition/.venv-integration/Scripts/python.exe 04_code/sample_search/validate_review_checkpoint.py
Remove-Item Env:PYTHONPATH
```

The core uses ordinary Python and NumPy images; the detector uses NumPy. TIFF validation uses tifffile, and the acceptance plot uses matplotlib from the existing integration environment.
The optional [registration utility](samplescout/registration.py) uses OpenCV phase correlation plus ECC for ordered, overlapping 2D grayscale images. It returns pixel translations and a blended mosaic; it does not infer physical units or stage-to-camera calibration. The local `stitch_images.py` command writes the mosaic and a JSON transform record, and requires OpenCV from the existing integration environment.

Run it from the bundle root with the existing environment and ordered images whose consecutive pairs overlap:

```powershell
$env:PYTHONPATH = '03_external/sample_search;04_code/sample_search'
04_code/ix83_acquisition/.venv-integration/Scripts/python.exe `
  04_code/sample_search/stitch_images.py --output mosaic.tif tile-01.tif tile-02.tif tile-03.tif
Remove-Item Env:PYTHONPATH
```
The reusable modules import neither Pycro-Manager, RTASPT nor a GUI. The [IX83 search host](../../04_code/sample_search/ix83_search_host/) owns runner transitions and device execution. The library records and replay/checkpoint serializers remain hardware independent.
An [explicit scan command](docs/scanning_usage.md) provides Beanshell-style primary grids and secondary absolute target lists through the same mock or Pycro-Manager executor.

## Implemented workflow

`WorkflowRecipe` describes identity/version, specimen and coordinate context, separate survey/full acquisition settings, overlap, deduplication distance, target limit, capabilities and resources.
The current serial host treats stage, camera and storage requirements as exclusive and rejects resource modes it cannot arbitrate.
`build_grid_recipe` publishes a `StageScanRecipe` with resolved stage positions and required capabilities; the IX83 host calls `run_recipe` to execute it under instrument policy.
The host `SampleSearchRunner` executes serial survey, detection, physical target selection and full revisits; it is imported from `ix83_search_host`. `samplescout` exports recipe/configuration types and pure planning/calculation helpers, not the runner.
It finishes the survey before targeted acquisition. Survey images and target movies remain separate datasets.
`run(review_only=True)` pauses at a checksummed review checkpoint. The [offline review interface](docs/review_usage.md) displays saved images and a stage-space coverage overview, accepts/rejects candidates and adds manual targets with reasons. Launch the checkpoint review from the bundle root with `04_code/ix83_acquisition/.venv-integration/Scripts/python.exe 04_code/sample_search/review_cli.py path/to/checkpoint.json`; this is read-only with respect to hardware. `resume_review` validates the saved context and decision before executing only revisits. A [synthetic review page](docs/review_demo.html) is available for inspection.

`Calibration` maps delivered image pixel centers through native sensor ROI/binning and an invertible affine matrix to physical coordinates using each tile's actual stage readback.
Tile planning uses a conservative inscribed footprint under rotation/reflection and serpentine order. Off-centre image footprints and full-acquisition ROI centring are explicit.
The implemented prototype uses fixed Z and does not invoke microscope-body autofocus. The first IX83 example recipe specifies relative focus-lock through the IX83 body; its host capability binding is planned. Z focus maps and continuous scanning are deferred.

`detect_bright_objects` supplies an independent threshold/connected-component baseline with centroids, scores, bounds and edge flags.
It is replaceable through a callable and is not the proposed first IX83 recipe's intensity-map selector. That recipe will make temporal-median survey maps and apply separate Otsu intensity metrics per channel, without requiring user masks or cell segmentation. Detail suggestions require high-intensity evidence in both configured channels.
Deduplication uses physical distances and retains observation provenance; same-tile distinct detections stay separate.
Incomplete objects at the permitted-region boundary are conservatively excluded. Detection thresholds, object sizes and overlap require specimen-specific validation.

Run and action statuses distinguish completed, empty, review-pending, cancelled, failed and outcome-unknown results.
Missing acquisition data fails the run; an image containing no detected objects produces an empty result.
Deadlines are bounded and cancellation is cooperative. Synchronous calls cannot interrupt a blocked driver; the executor retains ownership and forbids competing commands or blind retries after uncertain motion.
Saved typed observations support deterministic target decision replay without acquiring again. Replay does not predict the outcome of an unperformed physical action.

## Bundle integration and evidence

The IX83 adapter enforces configured XY bounds, fixed Z, readback tolerance and exclusive access among callers sharing the executor.
It stores survey snaps as checksummed NPY datasets and full movies through the tested concurrent OME recorder, at 50 ms by default.
The initial adapter rejects channel/ROI/binning changes and does not orchestrate channel-group MDA. The future calibration/processing path must keep split-detector parallel/perpendicular views separate, calibrate each view's crop geometry, and score each channel independently before applying the paired-channel rule. Other device clients must remain stopped; an in-process lock cannot arbitrate independent MMStudio clients.

The [bundle validation record](../../02_docs_offline/sample_search_validation.md) distinguishes seeded simulation, supplied AutoScanJ images, acquisition/storage handoff and real mechanical scanning.
Run `03_external/sample_search/scripts/validate_autoscan_registration.py` to mock-test known-overlap crops taken from the supplied AutoScanJ montage. The 100 individual AutoScanJ TIFF tiles have no stage positions; their overlap cannot be reconstructed from the files alone.
The combined library/host/acquisition suite passes 127 tests, including isolated recipe compilation without acquisition-host or hardware-framework imports. Source lint and strict typing pass.
The stored survey/review/resume check verified three target movies with all nine frames and actual RTASPT input, without a repeated survey.
The authorized mechanical scan saved six survey frames and a five-frame movie over a 50 x 25 um excursion, then returned within 0.5 um of origin.
The [seeded specimen plot](docs/seeded_search_validation.png) provides a reviewable overview; it establishes synthetic geometry/decision behavior rather than biological sensitivity.
AutoScanJ remains a read-only feature/manual/data reference. See [reference findings](docs/autoscan_reference.md) for provenance and test limits.

Planned first-recipe work includes operator-confirmed 2/4-point well localization, IX83 body relative focus-lock binding, temporal-median channel maps, Otsu intensity scoring per channel, paired-channel detail proposals, split-detector-aware spatial calibration, channel-group MDA, and the minimal CLI-launched survey-map/review flow. The checkpoint review command and page renderer are implemented, but the recipe-specific map GUI and operator acceptance are pending. Calibrated real-specimen search/recall, longer movies under processing load and future host adapters also remain planned. RedSun may be a parallel future host and is not a library dependency.
There is no general workflow graph, fluidics implementation, deep-model dependency or agent-controlled physical executor in this prototype.
