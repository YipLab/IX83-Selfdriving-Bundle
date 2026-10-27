# Reconstruction-quality replay

Q06 of the [2026-10-27
increment](../../02_docs_offline/redsun_rtaspt_integration_next_steps.md#manuscript-driven-implementation-increment-2026-10-27)
asks for replayable analysis over recorded inputs — registration residuals,
closure/repeatability, seams, valid support and uncertainty — while keeping
image-derived placement distinct from independent stage or reticle truth.

This tool replays a saved pairwise registration record and its mosaic report and
recomputes the consistency figures from the recorded pairs and the coverage
array. It does not re-register, re-stitch or read the mosaic image.

## What it recomputes

| Figure | Source |
| --- | --- |
| pair accounting (total, passed, failed, pass fraction) | the record's `pairs[].fit_status` |
| placement residual (median, p95, max, RMS) | `pairs[].placement_graph_residual_xy_px` magnitudes |
| registration-versus-stage-prior gap | `pairs[].registration_minus_stage_prior_xy_px` magnitudes |
| correlation and overlap | `pairs[].correlation`, `pairs[].image_overlap_fraction` |
| graph connectivity and components | `connected_registration_graph`, `frame_placements[].graph_component` |
| coverage fractions | the mosaic report's `coverage_file`, read as a count-per-pixel array |
| agreement with the mosaic report | its `edge_residual_summary_px` and `coverage_max_tiles_per_pixel` |

An RMS that disagrees with the mosaic report, a coverage maximum that disagrees,
or a missing coverage array is reported as a warning. A disconnected graph or a
recomputed RMS above the declared gate is blocking. `psf_not_measurable` is
always reported as information, because no bead recording exists.

## Result, recorded 5×5 grid (2026-10-23)

`08_session_logs/20261023T_grid_5x5_regression_01/calibrated_record.json`
(registration `7f5b75e26c7d`, calibration `hand-eye-…`):

| Figure | Value |
| --- | --- |
| pairs | **300 / 300 passed** (fraction 1.0) |
| placement residual | median **0.148 px**, p95 **0.301 px**, max **0.452 px**, RMS **0.177966 px** |
| mosaic report RMS | 0.1779655 px — **agrees** with the recomputation |
| registration minus stage prior | median **7.386 px**, p95 **15.965 px**, max **18.047 px**, RMS 9.281 px |
| correlation | median 0.901, min 0.795 |
| overlap fraction | median 0.807, min 0.545 |
| graph | connected, 1 component, 25 frames placed |
| coverage | **99.41 %** ≥ 1 tile, 97.97 % ≥ 2, 95.44 % ≥ 3; max 25 tiles/pixel |

The report is
[`records/ix71-5x5-quality.json`](records/ix71-5x5-quality.json). The
registration-versus-prior figure is the useful separation: the image-derived
placement differs from the stage prior by 7.4 px at the median, so a placement
that trusted the prior alone would sit several pixels away from where the content
actually registers. That is consistency between frames, not accuracy against an
independent reference.

## Seam measurement and its geometry precondition

`seams.py` adds the seam half. A seam metric needs to know which canvas position
each tile's edge falls on, and a saved mosaic does not always carry that: the
declared source shape and downsample can disagree with the canvas once the
builder also crops. Rather than trust a declared scale, the module derives an
integer tile size from the record's own coverage array — searching candidate
sizes and both origin roundings — and reports the best fraction of pixels that
disagree. A geometry that reproduces at most 1 % of pixels wrongly is accepted;
otherwise seam measurement is refused with `geometry_unverified`, because a
measured step on a guessed geometry would be a fabricated number.

For an accepted geometry it reports, per tile edge, the mean absolute intensity
step across that edge and a control step from three interior positions of the
same tile. The report gives medians and p95 values for both. The comparison is
what makes it interpretable: a step is reported relative to that tile's own
within-tile variation, not as an absolute quality verdict. Because a mosaic
averages overlapping tiles, a boundary step is the residual mismatch after
averaging, not the raw tile disagreement.

On the recorded 5×5 mosaic the geometry search is refused (the best equal-tile
model still misses about 99 % of pixels, and the coverage array's counts cluster
at multiples of five), so the tool records `geometry_unverified` instead of
measuring seams on it. Synthetic fixtures with known geometry are measured
exactly — a two-tile step of 1.0 against a control of 0.0, a blended overlap
edge of 0.5, and a vertical edge of 2.0 — which is what the module's own tests
assert.
## Usage

```powershell
$root = 'C:\Users\yipgroup\Documents\IX83-Selfdriving-Bundle'
$py = "$root\03_external\redsun-searching-is-imaging\.venv\Scripts\python.exe"
& $py "$root\04_code\reconstruction_quality\quality.py" `
    --record "$root\08_session_logs\20261023T_grid_5x5_regression_01\calibrated_record.json" `
    --mosaic-report "$root\08_session_logs\20261023T_grid_5x5_regression_01\calibrated\registered_snap_mosaic_report.json" `
    --out "$root\04_code\reconstruction_quality\records\ix71-5x5-quality.json"
```

Exit codes: `0` with no blocking finding, `1` with one, `2` for an unreadable or
unrecognised record.

## What this does not establish

- **Not independent accuracy.** Every residual compares frames with frames; no
  stage-referenced truth or reticle sample is paired, and the report says so.
- **No bead PSF width.** No bead recording exists for this camera mode, so the
  along/across width endpoint is `not_measured`.
- **No seam intensity step.** That is a property of the blended mosaic image and
  is not computed here.
- **No re-registration.** The record is read, not regenerated; a bad recorded
  placement is reported by its own residuals, not corrected.
- **Coverage is canvas coverage**, not coverage of the specimen's valid support.

## Verification

Eleven hardware-free tests cover the statistics, the gate, failed pairs,
disconnected graphs, coverage fractions, coverage and RMS disagreement, a missing
array, unregistered/unreadable records and the CLI. On 2026-10-27 the suite
passed and `ruff format --check` / `ruff check --select E,F,I` were clean. The
full record is
[2026-10-27 reconstruction quality](../../08_session_logs/20261027T_reconstruction_quality_q06/README.md).

