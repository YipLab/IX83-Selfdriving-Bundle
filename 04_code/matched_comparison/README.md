# Matched-strategy comparison manifest and reducer

Q07 of the [2026-10-27
increment](../../02_docs_offline/redsun_rtaspt_integration_next_steps.md#manuscript-driven-implementation-increment-2026-10-27):
a bundle-owned experiment manifest that invokes the supported survey/revisit,
uniform broom and adaptive broom plans over one common specimen footprint,
target criterion, observation requirement and quality rule, with a
mean-step-matched and a residence-requirement-matched fixed control; plus an
offline reducer for union valid area per time, accepted target windows per
minute, the successful fraction and paired field/specimen effects.

The manifest is a declaration and the reducer consumes an event table. Neither
acquires data, and neither treats frames, tracks or overlapping units as
independent specimens.

## Manifest

| Field | Meaning |
| --- | --- |
| `footprint` | the one specimen footprint (`width_um`, `height_um`, `overlap`) shared by every arm |
| `detector_width_um`, `frame_period_s` | the detector window along travel and the frame interval; residence and step are derived from these |
| `target_criterion` | detection threshold, area band and dedup distance, shared by every arm |
| `observation_requirement` | minimum accepted windows per target and the window length |
| `quality_rule` | maximum blur ratio and edge RMS; a unit that misses it is a rejected observation, not a retry |
| `illumination` | mode, setpoint and exposure; exposure must be below the frame period |
| `time_endpoints` | must include `focus`, `travel`, `review`, `acquisition`, `segmentation`, `processing` |
| `field_blocks` | each block names its fields and the order in which the three primary arms run |
| `strategies` | exactly `survey_revisit`, `uniform_broom`, `adaptive_broom`, `mean_step_matched`, `residence_matched`, each with its plan name |
| `controls` | the mean-step tolerance fraction, the required residence and its tolerance |

An arm may not restate a common unit. Two nominally matched arms with different
footprints or criteria are refused rather than compared, because their areas and
window counts would not be commensurable.

### Control arithmetic

The validator derives and checks the controls from declared values:

- `uniform_broom`, `mean_step_matched` and `residence_matched` steps are
  `speed x frame_period`; the adaptive arm declares its mean step and mean rate.
- `mean_step_matched.step` must equal the adaptive mean step within
  `mean_step_tolerance_fraction`.
- `residence_matched` is `detector_width / speed` and must equal
  `residence_requirement_s` within `residence_tolerance_s`.
- the adaptive arm's mean residence (`detector_width / mean_speed`) must meet or
  exceed the declared requirement.

In the shipped design example the uniform arm runs at 200 um/s (10 um step,
1.10 s residence), the adaptive mean is 100 um/s (5 um step, 2.19 s residence),
the mean-step control runs at 100 um/s (5 um step, delta 0.0 um) and the
residence control at 109.692 um/s (2.00 s residence, delta 0.0 s).

## Reducer

The event table lists **field units**: one row per field and strategy, with the
unit's valid area, elapsed time (including every declared endpoint when
available), detected and accepted targets, accepted windows and the per-endpoint
seconds. The reducer:

- refuses a unit that names a `frame_id` or `track_id`, or declares any
  granularity other than `field`;
- refuses overlapping units, because their areas cannot form a union;
- refuses an event table whose `experiment_id` differs from the manifest's;
- sums only disjoint field areas, so overlapping frames never inflate the union;
- reports a strategy absent from the event table as absent, never as zero;
- pairs each primary arm and each control against `uniform_broom` within a
  field, and lists a field as unpaired when an arm is missing;
- reports which declared time endpoints have no recorded seconds.

Example fixture figures (illustrative numbers, not measurements): survey
0.350 mm²/min and 27.0 windows/min; uniform broom 0.525 and 52.5; adaptive broom
0.540 and 59.4; mean-step control 0.524 and 52.4; residence control 0.400 and
40.0. Success fractions are 0.773 / 0.909 / 0.909 / 0.864 / 0.818 over 22
detected targets, and all eight field-by-arm pairs are present.

## Usage

```powershell
$root = 'C:\Users\yipgroup\Documents\IX83-Selfdriving-Bundle'
$py = "$root\03_external\redsun-searching-is-imaging\.venv\Scripts\python.exe"
& $py "$root\04_code\matched_comparison\comparison.py" `
    --manifest "$root\04_code\matched_comparison\spec.ix71-matched-v1.json" `
    --events "$root\04_code\matched_comparison\events.example.json" `
    --out "$root\04_code\matched_comparison\comparison_report.example.json"
```

Exit codes: `0` for a valid manifest (with or without a report), `2` for a
refused manifest or event table.

## What this does not establish

- **No measurement.** The shipped manifest and events are a design and an
  arithmetic fixture; the figures above are not specimen results.
- **No physical comparability.** The manifest declares one footprint and
  criterion, but whether the instrument executes each arm over the same
  registered support is what Q04/Q05/Q06/Q10 must show.
- **No independence by assertion.** Field units are the comparison unit; the
  reducer refuses frames and tracks, but it cannot detect a field that was
  physically re-used under two unit ids — that is a recording-integrity check for
  Q02.
- **No statistical model.** Paired deltas are reported per field; choosing
  replication and a test belongs to the study design.
- **No annotation.** "Accepted" targets come from the recorded decision; the
  reducer does not re-detect or annotate.

## Verification

Thirty hardware-free tests cover the shipped manifest, every refusal (schema,
identity, footprint, area band, endpoints, block order, common-unit override,
mean-step mismatch, residence mismatch, adaptive-residence shortfall), the
reducer's metrics on the example, pairing, unpaired fields, frame/track and
overlap refusals, experiment mismatch, duplicate ids, accepted-exceeds-detected,
unmeasured endpoints and the CLI exit codes. On 2026-10-27 the suite passed and
`ruff format --check` / `ruff check --select E,F,I` were clean. The full record is
[2026-10-27 matched comparison](../../08_session_logs/20261027T_matched_comparison_q07/README.md).
