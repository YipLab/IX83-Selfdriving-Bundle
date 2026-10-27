# Operating matrix

A versioned speed × exposure × detector-width matrix in which every point is
either feasible or refused with a typed reason, and in which the metrics the
matrix cannot compute are named rather than omitted. This is Q05 of the
[2026-10-27 implementation increment](../../02_docs_offline/redsun_rtaspt_integration_next_steps.md#manuscript-driven-implementation-increment-2026-10-27):
"compose a versioned speed × exposure × detector/readout-width matrix from
installed planner calculations, measured device capabilities and app execution
bounds ... record infeasible settings with reasons."

The model is not reimplemented here. Each row builds a
`planner.acquisition_space.AcquisitionPoint` and calls `assess_measurement`, so
motion blur, interframe shift, residence, observations, duty, gamma and
area-throughput come from the installed planner. The matrix adds the binding
checks the planner cannot know: stage speed ceiling, sensor field, illumination
footprint, ROI pixel alignment and exposure against the frame period.

## Specification

| Field | Meaning |
| --- | --- |
| `camera.sensor_width_px`, `camera.sensor_height_px`, `camera.pixel_size_um`, `camera.binning` | delivered camera mode; the field extent is derived, not typed |
| `optics.resolution_um`, `optics.resolution_basis` | the resolution used for `blur_ratio`; `sampling_pitch_not_psf` is recorded as a proxy and raises `psf_unmeasured` |
| `frame_period_s`, `strip_length_um` | frame interval (distinct from exposure) and the route length used for retained-frame prediction |
| `illumination_footprint_um` | optional bound on usable width; `null` is recorded as undeclared |
| `speeds_um_s`, `exposures_ms` | axes, kept separate in every row |
| `virtual_slit_widths_um` | reconstruction-slit widths, any value up to the field |
| `hardware_roi_widths_px` | camera ROI widths in sensor pixels; the micrometre width is derived |
| `limits` | `max_stage_speed_um_s`, `min_frame_period_s`, the planner's blur/gamma/observation/duty bounds, a `provisional` flag and per-limit `sources` |

`limits.provisional` never changes a verdict; it adds a finding so a design matrix
cannot be read as measurement acceptance.

## Refusal codes

| Code | Raised when |
| --- | --- |
| `exposure_not_below_frame_period` | exposure ≥ frame period; no metrics are computed |
| `speed_exceeds_declared_max` | speed above the declared stage ceiling |
| `width_exceeds_sensor_field` | width beyond the derived field width |
| `width_exceeds_illumination_footprint` | width beyond a declared footprint |
| `roi_width_not_pixel_multiple` | hardware ROI width not divisible by the binning |
| `hardware_roi_exceeds_sensor` | hardware ROI wider than the sensor |
| `blur_ratio_exceeds_declared_max`, `interframe_gap_exceeds_declared_max`, `observations_below_declared_min`, `duty_outside_declared_range` | the planner's own verdict, mapped to the matrix vocabulary |

Each row also carries `warnings` (`psf_blur_is_a_proxy`,
`frame_period_below_declared_camera_floor`) that qualify the numbers without
refusing the point.

## Output

```text
{schema, matrix_id, created_utc, instrument, limits, rows[], summary, not_computed[], findings[], accepted:false}
```

`summary` reports totals, feasible/infeasible per detector mode, and a histogram
of refusal reasons. `not_computed` names `valid_area`, `local_support_duration`,
`psf_blur` (when the resolution is a proxy) and `acquisition_overhead`, each with
the dependency that would supply it: registered support, a recorded run, a
measured PSF, or per-frame timing from Q02/Q04.

## Observed comparison

`compare_observed(matrix, run_dir, commanded_speed_um_s, exposure_ms, width_um)`
takes a matrix report and a recorded run, finds the declared row the run claims
to have executed (exact on mode, speed and exposure; within a micrometre on
width), and refuses a near miss instead of interpolating. It then compares only
what the recording contains: captured frames, the recorded frame interval, the
implied step along the strip and the residual span after the measured intervals.
Valid area, local support and PSF blur are listed in `not_comparable`.

The comparison carries a guard: the recorded route commands speed in the stage
service's own unit, so a step or frame ratio measures agreement inside that
convention and does not establish physical speed. On `ix71-snake-06` the declared
100 um/s / 10 ms / full-field row predicts 157 frames per 781 um strip; the run
recorded 93, an 8.489 um step, a 47 ms median interval and a step ratio of 1.6978
— consistent with the documented ~1.7x unit-scaling behaviour, stated as a guard
rather than a measurement.

```powershell
& $py "$root\04_code\operating_matrix\matrix.py" `
    --spec "$root\04_code\operating_matrix\spec.ix71-design-v1.json" `
    --out "$root\04_code\operating_matrix\ix71-design-v1.matrix.json" `
    --run "$root\08_session_logs\20261024T_long_strip_broom_01\run_snake_06" `
    --commanded-speed-um-s 100 --exposure-ms 10 --width-um 219.384
# writes ix71-design-v1.observed.json beside the matrix
```

## Design matrix, 2026-10-27

`spec.ix71-design-v1.json` composes the camera mode and sampling from the
accepted crop900 record and the MR095 reticle (0.18282 um/px, 1200 × 1200,
binning 1), a 50 ms frame period from the measured 19.81 frames/s cadence, the
stage ceiling of 200 um/s from the recorded 0.2 mm/s route, exposures of 5/10/20
ms from the measured ladder, and widths of 20/50/100/219.384/250 um plus
hardware ROIs of 120/400/1200 px. The 400 um/s speed and the 250 um width are
deliberate boundary probes: they must appear as refusals, not disappear.

Result with the provisional limits (`max_blur_ratio` 2.0, `max_gamma` 0.5,
`min_observations` 3, `max_duty` 0.5): **120 rows, 61 feasible, 59 refused** —
blur 48, speed ceiling 24, observations 15, field 15, interframe gap 6 (a point
can carry several reasons). Examples:

| Point | Verdict | Retained frames per 781 um | blur ratio | observations | duty |
| --- | --- | --- | --- | --- | --- |
| virtual slit 20 um, 25 um/s, 5 ms | feasible | 625 | 1.019 | 16.0 | 0.10 |
| virtual slit 219.384 um, 200 um/s, 5 ms | feasible | 79 | 1.869 | 21.94 | 0.10 |
| virtual slit 20 um, 400 um/s, 20 ms | refused | — | — | — | — |

The 625-to-79 frame spread across the speed axis is the predicted retained-frame
range for one 781 um strip; it is a prediction from declared values, not a
measurement.

## Usage

```powershell
$root = 'C:\Users\yipgroup\Documents\IX83-Selfdriving-Bundle'
$py = "$root\03_external\redsun-searching-is-imaging\.venv\Scripts\python.exe"
$env:PYMM_LOG_FILE = "$root\.pva-tmp\pymmcore-plus.log"; $env:PYTHONUTF8 = '1'
& $py "$root\04_code\operating_matrix\matrix.py" `
    --spec "$root\04_code\operating_matrix\spec.ix71-design-v1.json" `
    --out "$root\04_code\operating_matrix\ix71-design-v1.matrix.json" --examples 3
```

Exit codes: `0` when at least one row is feasible, `1` when none is, `2` for a
refused specification.

## What this does not establish

- **Not acceptance.** The limits are provisional design placeholders and the
  document says so; no point here is a qualified operating setting.
- **No valid area, local support or overhead.** Those need a recorded run and
  registered support; `not_computed` names them instead of guessing.
- **No measured PSF.** `blur_ratio` compares motion blur with a declared
  resolution proxy, so it ranks rows but is not an optical resolution result.
- **No continuous-motion capability claim.** The speed axis is a declared
  request; whether a binding can execute it is Q04's qualification.
- **No observation of the specimen.** The matrix is a plan, not data.

## Verification

Twenty-five hardware-free tests cover every refusal code, the planner equality
of a row's metrics, the axis coverage, retained-frame arithmetic, the declared
gaps, the findings, spec validation and the CLI exit codes; six more cover the
observed comparison (exact matching, the near-miss refusal, the delta
arithmetic, a missing interval, a missing strip record and one recorded run). On
2026-10-27 the suite passed **31 tests** and `ruff format --check` / `ruff check
--select E,F,I` were clean. The full record is [2026-10-27 operating
matrix](../../08_session_logs/20261027T_operating_matrix_q05/README.md).
