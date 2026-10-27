# Acquisition ledger and its refusals

Q02's pre-physical half: a typed frame/pose/clock/action ledger, the checks that refuse a ledger whose
timestamps, poses or actions cannot be trusted, and an adapter that builds one from the files the
2026-10-24/26 recorder already writes. The application owns emission; this directory owns the contract
and the refusals, so the same checks exist before a session is instrumented.

The requirement is [Q02 of the 2026-10-27
increment](../../02_docs_offline/redsun_rtaspt_integration_next_steps.md#manuscript-driven-implementation-increment-2026-10-27):
retain the camera sequence, exposure timing when available, service arrival, publication, processing,
decision, command and observed response on identified clocks, with the seven action states, request
ids, readbacks, frame refusals and acquisition gaps.

## Document shape

```text
{
  "schema": "ix71.acquisition-ledger.v1",
  "run_id": "<confirmation id>",
  "clocks":   [{"clock", "host_clock", "offset_ns", "uncertainty_ns"}],
  "declared": {"pose_semantics", "exposure_association", ...},
  "rows": [ frame rows..., action rows... ],
  "notes": {...}
}
```

A **frame row** carries `store`, `frame_id`, `sequence_index`, `pose_source`
(`camera_receipt` | `exposure_bracket` | `unavailable`), `source_frame_id` (the source clock's own
label when it differs), `arrival_ns`, `pose_ns`, `pose_xy_um`, the exposure window, `rejected_reason`
and `dropped`. `store` and `sequence_index` are the identity: frame ids are source-local, and two
stores may each contain frame 1.

An **action row** carries `request_id`, `action`, `state` (one of `proposed`, `accepted`, `started`,
`completed`, `failed`, `cancelled`, `outcome_unknown`), the five lifecycle timestamps, `readback`,
`error` and `timed_out`.

## Refusals

| Code | Severity | Raised when |
| --- | --- | --- |
| `schema_missing`, `run_id_missing` | blocking | the document does not identify itself or its run |
| `clock_mapping_missing` | blocking | timestamps exist but no source clock is declared |
| `clock_uncertainty_missing` | warning | a declared clock states no mapping uncertainty |
| `frame_id_duplicate`, `frame_id_not_monotonic` | blocking | repeated or out-of-order ids **within one store** |
| `sequence_index_duplicate`, `sequence_index_not_monotonic` | blocking | the same for the join key |
| `frame_id_gap`, `sequence_index_gap` | warning | a dropped frame is retained as a gap, not hidden |
| `pose_missing` | blocking | a frame has no pose, no refusal reason and is not marked dropped |
| `rejected_frame_without_reason` | warning | a refusal is recorded with empty text |
| `pose_offset_exceeds_limit` | warning | the pose sits further from its frame arrival than the declared bound |
| `receipt_pose_declared_as_exposure` | blocking | the ledger claims bracket poses while a row is a receipt pose |
| `exposure_window_missing` | blocking | a bracket pose has no valid exposure window |
| `exposure_association_undeclared` | blocking | a bracket pose is recorded but the ledger declares no bracket association |
| `request_id_missing`, `duplicate_request_id` | blocking | actions cannot be traced to one request |
| `action_state_invalid` | blocking | an unknown lifecycle state |
| `action_time_out_of_order` | blocking | `accepted < proposed`, `started < accepted`, `completed < started` or `observed < accepted` |
| `timeout_not_outcome_unknown` | blocking | a timed-out action is marked failed, completed or cancelled |
| `outcome_unknown_without_evidence` | warning | `outcome_unknown` retains neither the timeout nor an error |
| `completed_without_observation` | warning | completion is claimed with no observed response |
| `response_latency_exceeds_limit` | warning | the first response arrives later than the declared bound |
| `no_action_records` | informational | no command/response evidence is present at all |

Three rules are enforced rather than described:

1. **A receipt-time pose stays a receipt-time pose.** Promoting it to an exposure-associated pose
   needs a bracketed window *and* a declaration; either alone is refused.
2. **A timeout is not proof of non-execution.** A timed-out action must be `outcome_unknown`; the
   validator refuses any other terminal state for it.
3. **Uncertainty is reported, not assumed.** A clock with no declared mapping uncertainty is flagged
   even when every timestamp is present.

The validator tolerates malformed rows and reports them; only a document that is not a JSON object
raises. A refused ledger can therefore be archived and inspected.

## Adapter over the recorded runs

`adapt_recorded_run(run_dir)` builds the document from a run's `*.positions.json`, `*.timing.json`
and strip record, and states what it does not know. On the two 2026-10-24 snake runs:

| Figure | `ix71-snake-06` (success) | `ix71-snake-05` (failed) |
| --- | --- | --- |
| ledger rows | 279 across 3 stores, 93 each | 282 across 3 stores, 94 each |
| timing-to-pose join | complete (0 unjoined either way) | complete for the posed frames; **2 timing rows have no pose row** |
| pose offset from frame arrival | median **27.23 ms**, max **35.38 ms** | median **27.73 ms**, max **35.13 ms** |
| source-label mismatches | 279 | 282 |
| frames the strip record counts but no sidecar poses | none | **rows 1 and 2: 95 captured, 94 positioned** |
| recorded refusals | none | `X telemetry bracket 0.289s exceeds 0.2s limit` at pose index 0 of rows 1 and 2 |
| blocking findings | none | none (no action rows, so no action violation exists to find) |

Two facts come out of the adapter that a prose record cannot state as checkable numbers:

- **`frame_id` is not a cross-source identifier.** The timing sidecar's `frame_id` is the run-global
  camera counter (2..94, 115..207, 225..317) while the positions sidecar's is store-local (1..93).
  The join that works is `store + sequence_index`, using the timing `written_index` and the position
  `array_index`; joining on `frame_id` silently drops 187 of 279 frames. The document records the join
  key and the mismatch count.
- **The receipt pose follows the frame arrival by 27-35 ms.** The pose is sampled after the frame
  arrives, so it cannot bracket the exposure; the adapter labels the semantics `camera_receipt` and the
  validator keeps it there. In the failed run the two frames that arrived but were never posed are
  retained as timing rows without a pose, next to the strip record's refusal reason.

## What a host must emit

A recording host supplies, per frame: the store name, a store-local sequence index, the source frame
labels it joined, the arrival time on a declared clock, the pose time and value, and whether the pose
is a receipt or a bracketed exposure pose; and per action: the request id, action name, state
transitions, timestamps, readback and, for a timeout, `timed_out: true` with `outcome_unknown`. A host
that cannot supply a field must say so with a refusal reason or a drop mark rather than omitting the
row.

## Example emitted by an application

[`examples/stepped-onset-ledger.example.json`](examples/stepped-onset-ledger.example.json) is not a
fixture written here: the Redsun stepped-onset binding produced it in a hardware-free RunEngine run,
with one frame row per captured frame (camera arrival, host pose-read time, their measured offset),
one `move_to_point` and one `capture_frame` action row per frame, and one traverse-level row.
`test_the_stepped_onset_emitter_document_is_accepted` validates it, so the producer is checked against
this contract without importing the application. It is accepted with the single retained issue
`clock_uncertainty_missing`: the camera frame clock is a service arrival, its mapping uncertainty is
unknown, and the ledger says so rather than assuming zero.

[`examples/stepped-onset-interrupted-ledger.example.json`](examples/stepped-onset-interrupted-ledger.example.json)
comes from the same binding when a capture fails part-way. It is accepted with two retained issues —
`clock_uncertainty_missing` and `completed_without_observation` — and shows the failed capture and the
traverse as `outcome_unknown` with an error and no completion time, while the move that succeeded keeps
a `completed` row whose pose read never happened. That second warning is the contract doing its job:
a completed move with no observed response is a claim, and it stays visible instead of disappearing
into a green summary.

## What this does not establish

- **Not physical acceptance.** No ledger here came from an instrument with this contract in place; the
  adapter reads what an older recorder wrote and states the gaps.
- **No device-level action timing.** The 2026-10-24 recorder wrote no per-action rows. The stepped
  example now carries per-frame move and capture rows, but their times are host issue and
  status-completion times, so per-move device timing and any exposure association remain
  unestablished. That is why `no_action_records` stays informational rather than a pass.
- **No clock mapping beyond the declared one.** The recorder declares the host monotonic clock and no
  uncertainty; the validator reports the missing uncertainty instead of assuming zero.
- **No real-time claim.** Timestamps bound latency; they do not make Python control hard real-time.

## Verification

```powershell
$root = 'C:\Users\yipgroup\Documents\IX83-Selfdriving-Bundle'
$env:PYTHONPATH = "$root\tmp\dsh-sitecustomize"      # DSH mkdir(0o700) shim
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'; $env:PYTHONUTF8 = '1'
& "$root\03_external\redsun-searching-is-imaging\.venv\Scripts\python.exe" `
    -m pytest 04_code\acquisition_ledger\test_ledger.py -q `
    -p no:cacheprovider --basetemp 04_code\acquisition_ledger\.pytest-tmp
# 23 passed
```

`ruff format --check` is clean on both modules. `ruff check --select E,F,I` reports one pre-existing
import-order finding in `test_ledger.py` (the local `ledger` import grouped with third-party imports);
it is left as is rather than silently reformatted in an unrelated change. The full record is
[2026-10-27 acquisition ledger](../../08_session_logs/20261027T_acquisition_ledger_q02/README.md), and the
emitter that produced the example is recorded in
[2026-10-27 stepped-onset binding](../../08_session_logs/20261027T_stepped_onset_binding_q04/README.md).
