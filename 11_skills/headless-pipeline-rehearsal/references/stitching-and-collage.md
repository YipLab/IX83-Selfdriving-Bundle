# Stitching, residuals, and the collage artifact

Companion detail for the stitching-mosaic stage of the rehearsal. The goal is a mosaic and a collage the operator can inspect, plus numbers that say how much of the result is measured rather than assumed.

## 1. Crop or mask the dark borders first

Tiles acquired through the optic path typically carry black bands at the edges: camera ROI that extends past the illuminated/scan area, vignetting, or the field stop. Registering on those bands biases the estimate toward the border geometry, because a constant black region correlates with nothing and drags ECC toward a translation that aligns darkness.

Two acceptable treatments, both recorded:

- **Common rectangle.** Compute one axis-aligned validity rectangle for the batch from row/column intensity profiles (or a low-percentile threshold plus morphological opening) and apply the same rectangle in the same frame to every tile. Consistent geometry, but it discards real overlap if the band varies across the scan.
- **Per-tile mask.** Build a mask per tile, pass it to the ECC estimator and the compositor, and keep the fully uncropped tile for the 1:1 collage. Preserves overlap, but the mosaic must be composited mask-aware.

Never crop each tile to a different size and then treat the results as if they share a pixel grid.

Two different crops are in play and they must not be conflated. The **declared tile-processing crop**
is fixed per camera mode for every tile consumer — `(150, 150, 900, 900)` for a 1200 × 1200 readout —
and belongs in the recorded geometry. The **border mask above** is an additional, per-run treatment of
unilluminated edges inside that crop. Changing either one is a new analysis: record it and compare
like-for-like, and convert crop-relative pixels back through the crop origin before applying a
full-frame calibration.

Record for each tile: threshold or percentile used, rectangle or mask digest, and the fraction of area discarded. A crop that removes more than a small fraction of the planned overlap is a finding about the acquisition, not a stitching parameter to tune.

## 2. Registration: stage seed, PCC seed, ECC refine

The stage readbacks give an approximate relative placement. Use them, but do not stop there.

1. **Seed.** Acquisition data must pass the stage-derived estimate as `initial_shift_xy_px`, so
   low-overlap pairs do not start at zero. Image-only callers get phase correlation instead
   (`cv2.phaseCorrelate` on a Hann-windowed, Gaussian-pre-smoothed pair), and that path **refuses a
   response below 0.1** with "phase-correlation response is too weak to seed registration". Record
   which seed source produced each accepted transform. A flat tile seeded by stage pose is honest; a
   flat tile "registered" by PCC on noise is not.
2. **Refine with ECC.** The shipped path is `cv2.findTransformECC` with **`MOTION_TRANSLATION`**,
   termination 2000 iterations or 1e-7, on optionally downsampled and blurred inputs — it is a
   translation fit, not a similarity or affine one. Do not describe it as Euclidean. If a pair cannot
   be explained by translation (rotation or shear over the overlap), that is a **different model** and
   a new analysis: record the escalation per pair, and do not silently widen the model for the whole
   grid. `MOTION_EUCLIDEAN` or `MOTION_AFFINE` may be tried on such a pair only with enough overlap
   to constrain the extra parameters.
3. **Convention after the refine.** OpenCV's ECC warp is the inverse sampling map used with
   `WARP_INVERSE_MAP`; the moving tile's forward image origin is the negated translation. This is
   exactly where a placement-versus-content mix-up enters, so state which one the stored matrix is
   (see section 3).
4. **Intensity normalisation.** Per-tile exposure, bleaching and illumination gradients differ. Normalise robustly (median/MAD or percentile scaling) before correlation. Do not normalise with min/max, which a single hot pixel destroys.

## 3. State the coordinate convention

Every transform in the record must say what it maps:

- **placement convention** — where a tile's pixels sit on the mosaic plane; or
- **feature-displacement convention** — how far a scene feature moved between tiles.

These differ by an inverse. Pick one, write it once at the top of the report, and label each matrix with it. A transpose that is not stated is indistinguishable from a sign bug; converting between conventions is a documented coordinate conversion, not a correction for an old script's defect.

## 4. Gate on the residual, not on the picture

A mosaic that looks convincing can be globally wrong. Enforce the gate the review path enforces, and
get the **basis** right — the two modes do not share a threshold:

| mode | gate | recording |
| --- | --- | --- |
| fluorescence | edge RMS ≤ **2 % of the processed field width**, i.e. `0.02 * crop_width` — **18 px** for the 900 px tile crop | `gate_px=18.0`, `gate_basis="relative_field"` |
| brightfield | edge RMS ≤ **0.5 px**, absolute | `gate_px=0.5`, `gate_basis="absolute_px"` |

The presenter selects it from the camera mode rather than the caller: `redsun_searching_is_imaging/presenter/planner.py`
sets `gate_basis = "relative_field" if settings["image_mode"] == "fluorescence" else "absolute_px"`
and `gate = 0.02 * crop[2]` in the first case, `0.5` in the second. Applying the brightfield number to
fluorescence rejects good pairs; applying the relative number to brightfield accepts bad ones. Record
`gate_px` and `gate_basis` with every verdict, and never state a bare "passed" without them.

The gate is a gross-misregistration screen, not physical accuracy. Passing it does not certify the
mosaic: scale and hand-eye acceptance are separate, and a gate pass does not detect a double image.

Report the rest as stated criteria rather than as passes:

- Per-pair residual table: pair ids, seed source, model, correlation coefficient, edge RMS measured over the overlap band (not the whole tile), overlap area, and accept/reject.
- Acceptance fraction over planned neighbour pairs.
- Connected graph over accepted pairs, with the connected components named if it fragments.
- Coverage against the planned footprint, with the measured fraction, misses and overscan regions. Report the measured fraction and do not assert "≥ 99 %": the mosaics recorded on this instrument have come in below 1.0, so a claimed criterion of 99 % would be a number nobody met.
- Image-side scale compared with the value the plans use; a deviation beyond the declared tolerance is a scale finding, not an ECC parameter to nudge.
- Double-image quantification via the app's `mosaic_ghost_metrics` (`acquisition/snap_mosaic.py`): strongest secondary autocorrelation peak of the high-pass gradient, returning `max_ratio`, `p95_ratio`, `worst_offset_yx`, `worst_patch_xy`, `patch_count` and the search/stride settings used. It is an advisory visual-quality measurement, not a registration gate, so it cannot replace the edge-RMS gate or the operator's look.

Rejected pairs are chain breaks. Close them by fixing acquisition or geometry, not by relaxing the gate inside the stitching call.

## 5. Compute the collage as evidence

The operator inspects the collage. Produce it from the same transforms that produced the mosaic, under `<run>/artifacts/stitching/`. Reuse the contact-sheet drivers that already exist rather than inventing a third figure format — [make_collage.py](../../../08_session_logs/20261024T_snap_plan_retest_01/make_collage.py) renders a contrast-stretched sheet of a saved stack, and [brightfield_survey_collage.py](../../../08_session_logs/20261024T_snap_plan_retest_01/brightfield_survey_collage.py) does the nine-tile survey sheet. Keep this set in the run directory so the figure and the numbers cannot drift apart:

- `mosaic.png` — the composited result, blend mode recorded (feather, mean, max).
- `mosaic_unblended.png` — the same layout without blending, so seams and residual misalignment stay visible.
- `collage_overview.png` — downscaled mosaic with tile ids, planned grid and coverage boundary drawn on top.
- `seams_1to1.png` — full-resolution strips through the worst-residual seams, not only the best ones.
- `coverage_overlay.png` — accepted footprints, rejected pairs, misses and overscan on the sample plane.
- `residuals.csv` and `transforms.json` — the numbers behind the pictures.

State the downscale factor and the blend mode on each figure. A collage rendered from a different transform set than the mosaic is a decoration, not evidence.

## 6. GPU path and equivalence

Use the existing qualified GPU PCC/ECC backend for heavy grids when requested or supported by measured need. Device availability alone does not establish estimator parity.

The shipped path is a presenter-plan parameter set, not an inference: `registration_backend="rtaspt"`,
`rtaspt_backend="gpu"`, `rtaspt_seed="pcc"` on the survey/review chain. Record what the run **resolved**,
not what it requested — a `flat_backend: "auto"` field is not a resolved backend, and an absent
`gpu_backends_verified` key means the run carries no GPU evidence even on a host with two GPUs.

- Keep one device per concurrent job, and record the device assignment and wall time per stage.
- Compare the existing GPU backend with the accepted CPU estimator on a representative subset: per-pair transform delta and max mosaic pixel difference. Record the comparison before accepting the GPU result; creating a new estimator is a separate implementation decision.
- FFT-based phase correlation is deterministic modulo float ordering; keep the same window and filter settings on both paths or the comparison is meaningless.
- If the runtime refuses the default compiled-kernel cache, point the cache at the run directory (`CUPY_CACHE_DIR`, `CUDA_CACHE_PATH`) instead of elevating or rebuilding the environment.

## 7. Verification independent of the estimator

Two cheap independent checks catch the errors ECC cannot see:

- **Placement-only mosaic.** Composite using stage readbacks alone and compare with the registered mosaic. A systematic shear or scale difference points at calibration or sampling, not at registration tuning.
- **Round-trip residual.** Warp every accepted tile into mosaic space, sample the overlap band, and re-measure RMS from the saved mosaic rather than from the estimator's internal metric.

Both belong in the report with their numbers, even when they agree.

Three ways this comparison has gone wrong, so check them before believing a disagreement:

- **The canvases did not match.** A stage-seeded mosaic built on its own origin and extent cannot be compared with the recorded mosaic by phase correlation: the correlation locks onto the framing, not the content. A recorded attempt returned a shift of about (-199, -201) mosaic px at a response of 0.163, which was the canvas difference rather than a registration error. Build both images in **one** coordinate system — same origin, same shape, same scale — and only then correlate.
- **The compositor's origin was misread.** The compositor places a **cropped** tile's pixel zero at `registration_origin - crop_origin`, so the registration origin is not the cropped tile's origin. Treating it as one, then adding a crop origin when converting to a full-frame pixel, misses exactly the crop origin on each axis — 150 source px for the 900 px crop. That error is easy to mistake for a missing centre term or a rotation. A calibration-only round trip cannot expose it, because the calibration does not know where the compositor put the tile.
- **The comparison was judged by eye.** A stored-versus-transposed replay of all 36 crop translations reproduced the saved TIFF at NCC 1.0 and maximum absolute pixel difference 0.0 in the stored orientation, against NCC 0.588 transposed. When a whole-image reconstruction can be reproduced to zero pixels, that is the answer; a few labelled patches chosen by eye are not.

One related caveat about stage coordinates: a corrected remap can move every target's stage coordinate by tens of micrometres without any physical improvement. **A coordinate change is not a landing improvement** — only a recorded revisit measures that.
