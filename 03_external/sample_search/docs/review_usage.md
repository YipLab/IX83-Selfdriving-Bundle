# Offline target review

`samplescout.review` provides a local review manifest, a self-contained HTML
viewer, and validation for a separately saved decision. It performs no device
calls. Pass saved survey observations and an `image_loader` that reads the
recorded image reference; supply the exact calibration used by the run so target
markers are drawn in delivered-image pixel coordinates.

```python
from samplescout.review import ReviewContext, render_review_html

context = ReviewContext(run.run_id, run.specimen_id, calibration.coordinate_frame,
                        calibration.calibration_id)
manifest = render_review_html("review.html", context, run.targets, survey_observations,
                              image_loader=load_saved_image, calibration=calibration,
                              region=region)
```

Open `review.html` locally. Choose target IDs, optionally add targets with
physical X/Y in micrometres and a reason, then export `review-decision.json`.
The exported decision contains the manifest SHA-256 and run/specimen/frame/
calibration binding. Apply it to the same unchanged candidates:

```python
from samplescout.review import apply_review, decision_from_json

decision = decision_from_json("review-decision.json")
reviewed = apply_review(decision, run.targets, context=context, region=region,
                        max_targets=10)  # choose the run's declared finite target cap
```

`reviewed.targets` is the ordered accepted target tuple followed by manual
additions. `reviewed.manual_provenance` records each manual ID, coordinates and
reason for the execution ledger. A stale manifest, context mismatch, invalid
coordinate, out-of-region addition, duplicate ID, or target-limit violation
raises `ValueError`. Existing candidate records remain unchanged.

For a survey that pauses before any target acquisition, use the runner's checkpoint flow:

```python
from ix83_search_host import SampleSearchRunner
from samplescout.records import load_review_run, save_run

run = runner.run(review_only=True)
save_run("checkpoint.json", run, recipe, calibration, region)
# Launch the bundle's offline survey-review GUI from the checkpoint:
# python 04_code/sample_search/review_cli.py checkpoint.json
# Export the operator's decision from that page.
saved, recipe, calibration, region, full = load_review_run("checkpoint.json")
resumer = SampleSearchRunner(backend, detector, recipe, calibration, region,
                            full_calibration=full, z_um=saved.review_fixed_z_um)
result = resumer.resume_review(saved, decision_from_json("review-decision.json"))
save_run("reviewed-run.json", result, recipe, calibration, region,
         full_calibration=full)
```

The checkpoint retains recipe settings, both calibrations, permitted region,
fixed Z, observations, candidates and actions. Resume verifies their bindings
and survey freshness before commands and records the decision and manual provenance.
The default freshness limit is 300 seconds; choose a different limit only when
appropriate to the specimen. A stale survey must not be treated as a current observation.
Rejecting all candidates without additions produces an empty run.

The checkpoint is consumed in memory when revisits begin. Loading an older
saved pending file cannot prove whether a previous physical action occurred;
exactly-once recovery across process restarts is not implemented. Reconcile the
action ledger and recordings before restarting after any motion or movie has begun.

The [bundle validation script](../../../04_code/sample_search/validate_review_checkpoint.py)
exercises recording, checkpoint reload, JSON decision validation and resumed
movies with mocks. The [synthetic page](review_demo.html) contains saved example
images; its coordinates are not an IX83 calibration.

The bundle [review CLI](../../../04_code/sample_search/review_cli.py) validates a
saved review-pending checkpoint, renders its coverage overview and survey images,
then opens the self-contained HTML in the default browser. It reads recorded data
only and never connects to hardware. This is a prototype review GUI; median-map,
channel-metric and well-corner capture panels for the first IX83 recipe remain
planned.

The page includes a physical X/Y coverage overview, calibrated tile footprints,
candidate centers, and (when supplied) the permitted region, plus saved image
thumbnails with target overlays. The coordinate form adds a new target. To
replace a candidate position, reject its ID and add a replacement with a reason;
the decision never edits the original candidate record.

From the bundle root, validate this prototype with the acquisition integration
environment:

```powershell
$env:PYTHONPATH = "03_external/sample_search;04_code/sample_search"
& "04_code/ix83_acquisition/.venv-integration/Scripts/python.exe" -m pytest `
  04_code/sample_search/tests/test_review_checkpoint.py -q
```
