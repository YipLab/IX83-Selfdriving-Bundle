# Run evidence records

One record per recorded acquisition run, in which every field names the source it came from and
whether that source actually states it. This is the bundle half of **Q01** ("build a run manifest
linking source hashes, source software revisions, camera/ROI/binning, objective, illumination mode,
stage conversion, coordinate convention, calibration IDs, specimen/field IDs and output products")
from the [2026-10-27 implementation increment](../../02_docs_offline/redsun_rtaspt_integration_next_steps.md#manuscript-driven-implementation-increment-2026-10-27).

The bundle already had two manifests with different jobs: the Track D
[digest manifest](../../08_session_logs/20261024T_long_strip_broom_01/rehearsal/run_manifest.json)
owns artifact digests for the rehearsal, and
[the release manifest](../release_evidence/build_release_candidate.py) owns release gates. Neither records the run's
scientific/technical identity, and neither re-checks the sources it names. This tool does both for a
single run and writes a third, narrower document.

## What it reads

| Source | Fields |
| --- | --- |
| the run's `*-report.json` | attempt id, session outcome, error, setpoint, field, overlap, strip span, anchor, store shapes |
| the strip record `strips/*-<attempt>-strips.json` | route rows, footprint, anchor return, per-frame pose status and pose sources, completion flags |
| each `*.positions.json` | coordinate basis, readback keys, camera name, exposure, binning, sensor and binned ROI, pose phases, frame ids |
| each `*.timing.json` | pose clock, timestamp semantics, frame-metadata semantics |
| the recorder's `run_manifest_*.json` | attempt UUID, creation time, completion |
| the instrument profile YAML | camera adapter/device, stage conversion, speed, ramp, backlash, take-up, motion envelope |
| optional accepted calibration records | calibration id, camera mode, image extent, and whether the mode matches the run |
| `git` | bundle, application, planner and RTASPT revisions with dirty state |
| the files above | SHA-256 digests; Zarr stores are named by shape and explicitly **not** digested |

## What it emits

Every value is a cell of `{value, source, status}` with one of four statuses:

| Status | Meaning |
| --- | --- |
| `declared` | a named source states the value |
| `derived` | the value is computed from named sources (digest, count, match, revision) |
| `unresolved` | no source supplies it; the cell carries a reason and the paths that were checked |
| `mismatch` | two sources disagree or a source is malformed; the cell is also a finding |

`unresolved` and `mismatch` cells are listed under `unresolved`; `findings` carries a code, a
severity and the offending source. The record is always `accepted: false`: it is evidence about a
run, not an acceptance decision.

## Findings

| Code | Severity | Raised when |
| --- | --- | --- |
| `run_outcome_failed` | blocking | the plan reported anything other than `success` |
| `frame_count_mismatch` | blocking | a sidecar's `frames_written` differs from the store's first shape element, or no sidecar matches a store |
| `frame_id_not_monotonic` | blocking | frame ids do not strictly increase within a sidecar |
| `missing_run_manifest` | blocking | the recorder wrote no `run_manifest_*.json` beside the stores |
| `array_index_gap` | warning | a store holds frames with no pose record (`array_index` is not contiguous) |
| `pose_association_incomplete` | warning | any frame's pose status is not `associated_receipt`, with the reason counts |
| `route_encoding_inconsistent` | warning | a report route row is not a numeric xy pair; the strip record is used instead |
| `complete_but_failed` | info | the recorder finished every strip while the plan reported a failed session |
| `profile_unreadable` | blocking | the profile is absent or is not a YAML mapping |

## Usage

```powershell
$root = 'C:\Users\yipgroup\Documents\IX83-Selfdriving-Bundle'
$py = "$root\03_external\redsun-searching-is-imaging\.venv\Scripts\python.exe"
$env:PYMM_LOG_FILE = "$root\.pva-tmp\pymmcore-plus.log"; $env:PYTHONUTF8 = '1'

& $py "$root\04_code\run_evidence\build_run_evidence.py" `
    --run "$root\08_session_logs\20261024T_long_strip_broom_01\run_snake_06" `
    --profile "$root\03_external\redsun-searching-is-imaging\src\redsun_searching_is_imaging\configurations\ix71_asi_pvcam_sapphire.yaml" `
    --out "$root\04_code\run_evidence\records\ix71-snake-06.run-evidence.json"
```

Add `--calibration <accepted.json>` for each candidate record; the id is only claimed when exactly
one record's camera mode matches the run's exposure and binning. The exit code is `0` when the
record has no blocking finding, `1` when it does, and `2` when a required source is missing or
unreadable.

## Records in this directory

| Record | Run | Result |
| --- | --- | --- |
| [`records/ix71-snake-06.run-evidence.json`](records/ix71-snake-06.run-evidence.json) | successful three-strip snake, 10 ms, 1.0 mW | no blocking finding; 279/279 frames `associated_receipt`; frame counts reconcile; camera 10 ms / binning 1x1 / 1200x1200; `counts-per-um` 5.0; pose basis `stage-xy-reported-um` on the `python.time.monotonic_ns` clock with arrival semantics |
| [`records/ix71-snake-05.run-evidence.json`](records/ix71-snake-05.run-evidence.json) | failed snake (two rows rejected for telemetry bracket) | **2 blocking**: session failed and two stores hold one more frame than their sidecars (94 posed versus 95 stored); the two rejected frames carry `X telemetry bracket 0.289s exceeds 0.2s limit` |

Both records leave the same six fields unresolved on purpose: `illumination.mode`,
`illumination.objective`, `calibration.id`, `calibration.mode_match`, `specimen.specimen_id` and
`specimen.field_id`. No recorded source in these runs supplies them, so the record says so instead of
copying a neighbouring session's values.

## What this does not establish

- **No acceptance.** A clean record means the sources agree and the identity fields are present; it
  does not establish physical calibration, placement accuracy or that the run answers a manuscript
  endpoint.
- **No endpoint classification.** Mapping a run to D/M slots is still Q01's second half and needs the
  author's canonical-artifact decision.
- **No transferred-data inventory.** Records reported on the other computer are not evaluated here;
  their absence is the transfer checklist's business, not this tool's.
- **No directory digestion.** A Zarr store is recorded by shape and marked `not_digested`.
- **No re-computation.** It never re-registers, re-stitches or re-derives a pose; it reads what the
  recorder wrote and reports agreement or disagreement.
- **No device or session.** It imports no acquisition host and contacts nothing.

## Verification

Sixteen hardware-free pytest cases build synthetic run trees and cover the complete record, every
finding code, the refusals, determinism and the source rule. On 2026-10-27:

```powershell
$env:PYTHONPATH = "$root\tmp\dsh-sitecustomize"      # DSH mkdir(0o700) shim
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'; $env:PYTHONUTF8 = '1'
& $py -m pytest 04_code\run_evidence\test_build_run_evidence.py -q `
    -p no:cacheprovider --basetemp 04_code\run_evidence\.pytest-tmp
# 16 passed in 6.25s
```

`ruff format --check` and `ruff check --select E,F,I` are clean on both files. The full record is
[2026-10-27 run evidence](../../08_session_logs/20261027T_run_evidence_q01/README.md).
