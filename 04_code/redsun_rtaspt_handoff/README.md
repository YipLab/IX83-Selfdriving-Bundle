# Redsun → RTASPT handoff adapter

A small, tested, re-runnable tool that turns one saved Redsun snap store into a
validated RTASPT search-scan request. It reads recorded files only: no camera,
stage, laser, GUI, napari or GPU. Nothing under `03_external/` is modified.

Why it exists, measured on 2026-10-25: a rehearsal had to hand-write two TIFFs
because RTASPT has no Zarr image source. Pointing `images.path` at the saved store
fails verbatim with `FileNotFoundError: image stack not found: ...stitched_stack.zarr`
([rehearsal report](../05_simulations/rehearsal/20261025T0830Z/rehearsal_report.json),
findings F5 and F6; worked example
[`m3-rtaspt`](../05_simulations/rehearsal/20261025T0830Z/m3-rtaspt/README.md)).
Two traps in that gap are silent, so the adapter removes both by construction:

| trap | what happens | what this tool does |
| --- | --- | --- |
| `order: raster` / `serpentine` (RTASPT's default) | `build_tiles` numbers tiles by traversal while the detector keeps the table-row index; both sets are `{0..N}`, so the merge accepts the join and every detection lands on another tile's offset, with no error | the request always says `order: as_given`, and the movie's page *i* is table row *i* |
| a request carrying `anisotropy:` / `tracking:` | validates (exit 0) and the keys vanish from `request_used.json`, contradicting `docs/architecture.md` | only keys `request_from_mapping` actually reads are written; any other top-level key is refused |

The second row describes the 2026-10-25 observation. On 2026-10-26 RTASPT's
request loader was changed to reject those unsupported top-level sections;
anisotropy and tracking remain separate workflows.

## Contents

| file | role |
| --- | --- |
| [`redsun_to_rtaspt.py`](redsun_to_rtaspt.py) | the adapter CLI |
| [`verify_product.py`](verify_product.py) | checks an RTASPT product against the handoff that requested it |
| [`check_handoff.py`](check_handoff.py) | checks a handoff bundle by itself, before any product exists |
| [`test_redsun_to_rtaspt.py`](test_redsun_to_rtaspt.py) | hardware-free pytest for the refusals, the order pinning and the product check |
| [`test_check_handoff.py`](test_check_handoff.py) | hardware-free pytest for the bundle checker |
| [`verification/`](verification/) | the two recorded conversions, the one product run and its evidence |
| `.pytest-shim/sitecustomize.py` | launcher-only workaround for the DSH sandbox `mkdir(0o700)` ACL issue, never imported by the tools |

As of 2026-10-26, `verify_product.py` also checks the movie, frame table and
request against their recorded handoff SHA-256 digests, checks frame-row counts
and indices, requires the settled detections and objects tables, and compares
their row counts with the product record. An empty objects table is valid when
its provenance column exists and its recorded count is zero. It checks current
files; it does not establish which bytes an earlier RTASPT process consumed,
verify coverage identity or establish physical calibration or acceptance. The
[recorded-data check](../../08_session_logs/20261026T_handoff_integrity/README.md)
and synthetic regression are software evidence only.

## Usage

```powershell
$py = "03_external\redsun-searching-is-imaging\.venv\Scripts\python.exe"   # owns zarr

& $py 04_code\redsun_rtaspt_handoff\redsun_to_rtaspt.py `
    <store>.zarr <store>.positions.json <out-dir> [options]
```

Requires `zarr`, `tifffile` and `numpy`; it does **not** import `rtaspt`, PyYAML or
any Redsun package, so it can run from any environment that can read both formats.
The request is written as YAML by hand, and the file carries a header comment
stating why `order` is pinned.

Arguments: the store path (the `.zarr` group or its buffer array directory), the
`snap-position-association-v4` sidecar, the output directory.

| option | meaning |
| --- | --- |
| `--data-key KEY` | store array to read; default is the sidecar's `data_key`, else the only array |
| `--crop y0:y1,x0:x1` | half-open pixel window applied to every frame and to `tile_shape` |
| `--order as_given\|raster\|serpentine` | order of the **emitted** movie and frame table; see below |
| `--transform-matrix "a,b,c;d,e,f"` | declared stage→pixel affine |
| `--scale-px-per-um S[,SY]` (+`--rotation-deg`, `--flip-x`, `--flip-y`) | declared scale |
| `--calibration RECORD` | Redsun hand-eye record: uses its `fit.mosaic_placement_px_per_stage_unit` |
| `--registration-record REPORT` | explicit mosaic report to fit the transform from |
| `--preprocessing-id ID` | Redsun preprocessing id to record |
| `--position-tolerance-um` | stage-coordinate clustering tolerance (default 1 µm) |
| `--duplicate-gate-px`, `--registration-residual-px` | duplicate merge declaration |
| `--detection-diameter`, `--detection-min-mass`, `--detection-processes` | detection declaration for the `trackpy`/`gaussian` backends |
| `--detection-backend {trackpy,gaussian,region}` | RTASPT backend (default `trackpy`); `region` is the threshold + connected-component detector for transmitted light |
| `--detection-threshold`, `--detection-min-area-px`, `--detection-max-area-px` | `region` parameters (default: Otsu, 1, no upper bound); recorded for every backend and covered by the request digest |
| `--pose-uncertainty-um`, `--pixel-scale-um`, `--run-id`, `--note` | spec fields and extra notes |
| `--force` | overwrite an existing handoff |

### Detection declaration

`request.yaml` always carries a `detection` block. The three region parameters are
written even when another backend runs, because the request and the product record
are the reproducibility evidence: a declared-but-unused parameter is clearer than
one that appears only in some requests. The block sits inside `request.yaml`, so its
values are inside the request `sha256` recorded in `provenance.json` and
`handoff.json`; changing one detection flag changes that digest.

`--detection-backend region` is the crude detector for brightfield: an explicit
threshold (or per-frame Otsu), 8-connected components, and an area band, with
centroid/area/mean intensity per object and no sub-pixel refinement, deblending or
machine learning. `--detection-diameter`/`--detection-min-mass` do not participate
in region detection; the area band is its size filter.

### `--order` never reaches the request

The request's `order` is a constant, `as_given`. `--order raster|serpentine`
re-sorts the emitted movie **and** frame table together into that reading order,
so page *i* is still table row *i* and `as_given` stays true. A request that says
`raster` is not offered at all, because it cannot be correct for a store written
in acquisition order.

## What it writes

For a store `<stem>.zarr` into `<out>/`:

* `<stem>_tiles.ome.tif` — OME-TIFF, `axes: TYX`, one page per frame, uncompressed;
* `frames.csv` — `frame,x_um,y_um,time_s` in emitted order, `time_s` relative to the first frame;
* `request.yaml` — `kind: settled`, `order: as_given`, `tile_shape`, measured `lattice_spacing_um`, the transform, detection and duplicate declarations, and notes that carry the provenance;
* `provenance.json` — source paths, store tree digest, sidecar digest, frame count, order mode, crop, Redsun preprocessing id, transform derivation;
* `handoff.json` — the machine-readable record: outputs with digests and shapes, the request summary, seven named checks, warnings, the exact `rtaspt searchscan` and `verify_product.py` commands, and the stated limits.

All five are staged in `<out>/.redsun_to_rtaspt.staging` and moved into place, so a
refusal leaves the output directory untouched and does not even create it.

### Reader format: one shaped OME series with a leading `T`

`TiffSeriesReader` takes `series[0].axes` and only treats the leading dimension as
frames when that axis is `T` or `I` (`src/rtaspt/io.py`). A page-at-a-time writer
creates one one-page series per `write` call, and the run then fails with
`frame table indexes page 24 but only 1 physical TIFF pages are present`.
Therefore:

* one single `tifffile.imwrite` of the whole stack with `axes: "TYX"` — the same
  shape RTASPT's own `io.write_ome_stack` produces, so `track`/`process` can read
  the same file later;
* uncompressed, so RTASPT's memmapped plane reader serves planes without decoding;
* the stack is assembled in a temporary `np.memmap`, so a store larger than RAM
  still streams and the write stays a single shaped call;
* `bigtiff=True` above 3 GB, which the TIFF carrier needs and the reader accepts.

Two reader edges the tool avoids by construction: `resolve_tiff_series` globs
sibling files matching `<stem>.ome.tif` / `<stem>_<n>.ome.tif` in the same
directory, so the output directory must not contain a stray numbered sibling of
the movie; and non-`T`/`I` leading axes fall back to a flat-page count that happens
to work but is not the documented contract.

## Refusals

Exit code `2`, a `REFUSED [E-CODE] message` line on stderr, and no output written.
Every condition below was measured or constructed in
[`test_redsun_to_rtaspt.py`](test_redsun_to_rtaspt.py).

| code | refused when |
| --- | --- |
| `E-STORE-MISSING` | the store path does not exist |
| `E-STORE-NODE` | the path is not a readable Zarr array/group, has no image array, or the member is a group |
| `E-DATA-KEY` | `--data-key` is absent from the group, contradicts the sidecar's `data_key`, or the group holds several arrays and none was named |
| `E-SIDECAR-MISSING` | the sidecar is absent, unreadable or not JSON |
| `E-SIDECAR-SCHEMA` | the schema is not `redsun-planner.snap-position-association-v4`, or `frames` is empty/malformed |
| `E-SIDECAR-STATUS` | the run's `exit_status` is not `success` (an interrupted snap run does not describe what was written) |
| `E-FRAME-COUNT` | store frames ≠ `frames_written`, or ≠ the number of sidecar frame records |
| `E-FRAME-INDEX` | `array_index` is not exactly `0..N-1` once each |
| `E-POSITION-NONFINITE` | a stage coordinate or time is NaN/inf |
| `E-TIME-ORDER` | time stamps are not monotonic with `array_index` (decreasing, or mixed directions) |
| `E-POSITION-DUPLICATE` | two frames share one lattice node, so tile placement is ambiguous |
| `E-LATTICE` | the positions do not fill a rectangle (N ≠ unique-x × unique-y) |
| `E-POSITION-TRAVERSAL` | the positions fill the grid but do not walk it in raster or serpentine order — the store order cannot be trusted as acquisition order |
| `E-DTYPE` | the dtype has no TIFF sample format that keeps the recorded values (`float16`, 64-bit ints, complex …) |
| `E-SHAPE` | the store is not `(frames, height, width)` or an axis is empty |
| `E-ROI` | the sidecar's `camera_roi_binned_pixels` disagrees with the store plane (different camera modes) |
| `E-CROP` | the crop is outside the plane or empty |
| `E-TRANSFORM-MISSING` | no declaration is available: no matrix, scale, calibration and no mosaic report beside the store that names this sidecar |
| `E-TRANSFORM-MATRIX` | the matrix is not 2×3 finite, or its linear part is singular; a scale is not positive |
| `E-REGISTRATION-STALE` | the mosaic report's `source_sidecar_sha256` differs from the sidecar, its placement table does not cover exactly `0..N-1`, or a named record is missing. A record named explicitly with `--registration-record` is also digest-checked against the sidecar being handed over: naming it skips discovery, not verification |
| `E-REGISTRATION-RESIDUAL` | a declared edge residual exceeds the duplicate gate, so the placement cannot put tiles within the gate. RTASPT derives its cross-tile merge radius from that residual (`max(6, 3σ)`), so passing it on would widen the merge and fuse distinct objects |
| `E-DETECTION` | a detection declaration cannot be true: the backend is not `trackpy`/`gaussian`/`region`, the threshold is non-finite, `--detection-min-area-px` is not positive, or `--detection-max-area-px` is below it (no component could be kept) |
| `E-OUTPUT-EXISTS` | the output directory already holds handoff files and `--force` was not given |
| `E-REQUEST-KEY` | the composed request carries a top-level key `rtaspt-search-product-v1` would drop |

The traversal refusal is the one worth reading twice: a complete rectangle whose
walk is not raster/serpentine means the array order is not an acquisition order, so
`as_given` would be a false claim. The tool refuses instead of writing a request
that looks complete and places tiles wrongly.

## Transform: declared, never invented

RTASPT treats the stage→pixel transform as a *declaration* and asks the caller to
record the calibration identity it belongs to. Nothing in either repository
produces one for a Redsun store on its own, so a default scale would be a
fabricated measurement. Two properties of this instrument's records matter here:
the stage reports micrometres at `counts-per-um: 5.0` (0.2 µm per count), which is
correct — an earlier "doubled reported-µm frame" reading came from a
divided-by-two unit error in a runner and is retracted — and the optical mount is a
*reflection*, with stage x appearing along image y and stage y along image x, so a
transposed axis pairing is expected rather than a defect. Resolution order:

1. `--transform-matrix` (an explicit 2×3, source `cli-matrix`);
2. `--scale-px-per-um` with rotation/flips (`declared-scale`);
3. `--calibration RECORD` → its `mosaic_placement_px_per_stage_unit` (`calibration-record`, with camera/ROI/exposure cross-checks recorded as warnings);
4. a mosaic report beside the store whose `source_positions_path` **and** `source_sidecar_sha256` name this exact sidecar → ordinary least squares of `registration_origin_{x,y}_px` on the stage deltas (`registration-fit`; residuals and singular values are recorded);
5. otherwise: `E-TRANSFORM-MISSING`.

The `calibration_id` written into `request.yaml` names which of those produced the
matrix. The fit in step 4 reproduces the rehearsal's independent transform to four
decimals on the 5x5 control stack (see below), which is why it is preferred when a
saved registration exists.

The Redsun preprocessing id is resolved the same way: `--preprocessing-id`, else
`fit_parameters.preprocessing_id` from the registration record the mosaic report
names, else recorded as `null` with the reason. The sidecar v4 carries no
preprocessing claim, and the tool does not borrow the app's current constant for a
stack it cannot see.

## Deliberately not done

* **No anisotropy and no tracking request section.** `rtaspt-search-product-v1`
  has neither and drops unknown keys silently; the notes say so in every request.
  Those stages stay separate `rtaspt process` / `rtaspt track` commands.
* **No stage→pixel measurement.** The transform is a declaration with a recorded
  source; if no source exists the tool refuses rather than estimates.
* **No pixel synthesis, resampling, background or flat-field correction.** The
  emitted intensities are the recorded ones (cropping is the only pixel operation).
* **No per-frame files source.** `images.kind: files` exists in the schema, but a
  single movie is what this handoff needs and what the reader serves best.
* **No re-registration, no mosaic, no stitching.** If the saved registration is
  missing or stale, the tool says so instead of re-running ECC or guessing.
* **No hardware, no GUI, no napari, no RTASPT import.** It cannot run the product,
  only prepare and check it.

## Verification (offline, 2026-10-25)

Environment: Redsun application venv, Python 3.12.13, `zarr` 3.4.1, `tifffile`
2026.9.20, `numpy` 2.4.6. Hardware ID `IX83` was not contacted: no camera, stage,
laser or GUI command was issued.

### 1. Tests — 41 passed

```powershell
$env:TEMP = "$root\.pva-tmp"; $env:TMP = $env:TEMP
$env:PYTHONPATH = "$root\04_code\redsun_rtaspt_handoff\.pytest-shim"   # DSH mkdir(0o700) shim
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"; $env:PYTHONUTF8 = "1"
& $py -m pytest 04_code\redsun_rtaspt_handoff\test_redsun_to_rtaspt.py -q `
    -p no:cacheprovider --basetemp 04_code\redsun_rtaspt_handoff\.pytest-tmp
# 41 passed in 8.70s
```

Covered: the happy path (pinned request, single `TYX` OME series, frame table,
provenance digests), the schema-key guard, `lattice_spacing_um` being row-then-column,
`--order raster` permuting movie and table together while the request stays
`as_given`, crop, registration-derived transform (including from the buffer-directory
store form), every refusal in the table above, and the detection declaration: the
`trackpy` default is unchanged, the `gaussian` backend is selectable, the three
`region` flags reach `request.yaml` and the request digest, and an impossible area
band or a non-finite threshold is refused. `verify_product.py` is exercised
against a consistent product and against three broken ones (renumbered tiles,
dropped order pin, short tile table). The five detection tests were added on
2026-10-25; the earlier 36 were unchanged.

### 2. Conversions

| stack | frames | grid | transform source | preprocessing id |
| --- | --- | --- | --- | --- |
| 5x5 control | 25 | 5 × 5 serpentine | saved registration fit (`7f5b75e2…`) | `raw-saved-camera-frames-v1` |
| 4x4 ix71 | 16 | 4 × 4 serpentine | hand-eye record `hand-eye-5e1dca83b8d45040` | `null` (unrecorded) |

```powershell
$b5 = "08_session_logs\20261023T_grid_5x5_regression_01\run\specimen-grid-5x5\2026-10-24\mmcamera-buffer"
& $py 04_code\redsun_rtaspt_handoff\redsun_to_rtaspt.py `
    "$b5\execute_bounded_snap_grid_00000.zarr" "$b5\execute_bounded_snap_grid_00000.positions.json" `
    04_code\redsun_rtaspt_handoff\verification\5x5-control
# exit 0: 25 frames, 5 x 5 (x by y, y fastest) serpentine, TYX [25, 1200, 1200] uint16

$b4 = "03_external\redsun-searching-is-imaging\.redsun_data\searching-imaging-ix71-asi-pvcam-sapphire\2026-10-25\mmcamera-buffer"
& $py 04_code\redsun_rtaspt_handoff\redsun_to_rtaspt.py `
    "$b4\execute_bounded_snap_grid_00000.zarr" "$b4\execute_bounded_snap_grid_00000.positions.json" `
    04_code\redsun_rtaspt_handoff\verification\4x4-ix71 `
    --calibration 08_session_logs\20261023T_specimen_handeye_bundle_01\hand-eye-calibration.json
# exit 0: 16 frames, 4 x 4 (x by y, y fastest) serpentine, TYX [16, 1200, 1200] uint16
```

On the 5x5 the fitted matrix is
`[[0.062382, -5.554683, 1.601635], [-4.978807, -0.068133, 1.761262]]` with fit
residual RMS 0.989 px (x) / 1.255 px (y), maximum 2.913 px and singular values
5.5551 / 4.9792 px per reported µm — the same figures the rehearsal derived by
hand, so the per-axis 9.5 % difference is a property of the stack's registration,
not of this fit. The 4x4 declares the hand-eye record's placement matrix
`[[0.1087, -5.1354], [-5.0917, -0.1393]]` and records the caveat that the record
states no exposure. Its axes are transposed, which is the mount's reflection rather
than an error; the earlier "doubled reported-µm frame" caveat attached to this
record is retracted, because the doubling came from a divided-by-two unit error in a
runner and `counts-per-um: 5.0` is the correct conversion.

The 4x4 sidecar has no registration beside it, which is why it uses `--calibration`;
without a transform source the adapter refuses rather than defaulting.

### 2b. Region-backend brightfield handoffs (2026-10-25)

The adapter also declares RTASPT's `region` detector, which is what makes a
brightfield survey produce object interiors instead of cell-wall rims:

```powershell
$opts = "--detection-backend","region","--detection-threshold","550",
        "--detection-min-area-px","2000","--detection-max-area-px","80000"
& $py 04_code\redsun_rtaspt_handoff\redsun_to_rtaspt.py `
    "$b\...review_00002.zarr" "$b\...review_00002.positions.json" <out> `
    --calibration $cal @opts
```

Both the 170 µm 3×3 survey (`...00002`) and the 40 µm 3×3 survey (`...00003`)
were handed off with the same detection declaration; the only difference between
the two runs is the stage step, so their products differ by overlap rather than by
detector. Both products passed `verify_product.py` 12/12: 170 µm → 381 detections,
2 merged, 379 objects; 40 µm → 371 detections, **116 merged**, 255 objects. Full
numbers, interior fractions and placement residuals are in
`08_session_logs/20261024T_snap_plan_retest_01/rtaspt_region/`.

### 3. One RTASPT product run — exit 0, 25 tiles

```powershell
& "03_external\Realtime-Anisotropy-SPT-Analysis\.venv\Scripts\rtaspt.exe" `
    searchscan 04_code\redsun_rtaspt_handoff\verification\5x5-control\request.yaml `
    --output 04_code\redsun_rtaspt_handoff\verification\5x5-control\searchscan --coverage-arrays
# exit 0, 5.1 s
```

`searchscan-validate` was run once first (exit 0, no processing); it echoed
`order: "as_given"` and the seven notes, which is how the request was checked
before spending the one product run.

Measured product (`searchscan/search_scan.json`, log in
[`searchscan_run.log`](verification/5x5-control/searchscan_run.log)):

* `counts.tiles = 25` = the sidecar's frame count, and
  `counts.source_contiguous_pages_available = 25` — the reader saw all 25 written pages;
* `counts.detections = 1462`, `merged_detections = 842`, `objects = 620`;
* coverage canvas 1401 × 1425, `max_observation_count = 25`, `support_fraction = 0.9989`,
  `t_bar_available = true` with `t_bar_s.max = 34.119 s` = the recorded elapsed time.

`request_used.json` retains `order: as_given`, the 2×3 matrix, `tile_shape [1200, 1200]`,
the absolute path of the same `frames.csv` (identical sha256) and all seven notes;
it contains no `anisotropy`/`tracking` key.

`verify_product.py` then re-reads the product and passes 12/12 checks, including the
one that would have caught the renumbering: every `tiles.csv` row carries its own
frame-table row's `stage_x_um`/`stage_y_um`.

### 4. The trap, measured on this handoff

[`verification/order_trap_demo.py`](verification/order_trap_demo.py) calls RTASPT's
own `build_tiles` twice on the same frame table, with `as_given` and with `raster`:

```
22/25 tiles would take another frame's offset under order: raster; maximum shift 294.4 px
```

294 px is 22 % of a 1200 px frame — one lattice row's worth of misplacement per
tile, with no error, no warning and a complete-looking product. `as_given` matches
the frame rows exactly; `raster` matches none. Record:
[`order_trap_demo.json`](verification/5x5-control/order_trap_demo.json).

## The one place RTASPT's interface made this awkward

The stage→pixel transform is the awkward one. `StageToPixelTransform` is a
*declaration* — "pass an explicit matrix derived from a registration result and
record the calibration identity it belongs to" — but the request cannot be built
without it, RTASPT offers no way to obtain it from the data it is about to read,
and no component emits a consumable per-axis affine for a Redsun snap store on its
own. Records now exist that can be declared: the accepted brightfield calibration
`hand-eye-37d835078ce75216` carries a placement matrix and a camera/ROI/exposure
context, and the adapter cross-checks that context as warnings. What must not happen
is an *unqualified* reuse of an older record: the earlier reading that the bundle's
only hand-eye record sat in a doubled reported-µm frame, transposed, is retracted —
the doubling was a divided-by-two unit error in a runner and `counts-per-um: 5.0` is
correct, while the transposed pairing is the mount's reflection and is expected.
That is why the adapter keeps a discovery step (a mosaic report that names this
sidecar by path *and* digest) and a least-squares fit, plus a refusal when neither
exists: a request without a transform source is not honest, and a default would be
an invented measurement.

The reader adds a smaller awkwardness that the output layout has to respect:
`TiffSeriesReader` reads `series[0]` only, so the movie must be one shaped write; and
`resolve_tiff_series` globs `<stem>_<n>.ome.tif` siblings, so nothing numbered may sit
beside the movie.

## Re-running the verification

```powershell
& $py 04_code\redsun_rtaspt_handoff\verify_product.py `
    --handoff 04_code\redsun_rtaspt_handoff\verification\5x5-control\handoff.json `
    --product 04_code\redsun_rtaspt_handoff\verification\5x5-control\searchscan
# 12 checks pass
```

The generated artifacts (two OME-TIFFs, the product tables and coverage arrays) are
local evidence, about 120 MB; `.gitignore` here excludes them and the test scratch
directories so a future commit carries the tools and the JSON records only. One
empty directory, `tmp/tmpd78k0u9e`, survives from an early `tempfile.mkdtemp` call:
the DSH sandbox cannot delete a directory it created with `mkdir(mode=0o700)`, which
is the documented ACL behaviour, not a defect in this tool.
