# Throughput accounting

Q09 of the [2026-10-27
increment](../../02_docs_offline/redsun_rtaspt_integration_next_steps.md#manuscript-driven-implementation-increment-2026-10-27):
"report attempted/captured/published/refused/processed/released/persisted/missing
IDs, queue occupancy, memory, segmentation/restart overhead and exposure-to-output
latency with clock uncertainty. Compare online and batch on identical retained
inputs, then report completeness separately."

The harness has two modes and one rule: **a category the source does not contain
is `not_recorded`, never zero.**

| Mode | Input | Measured |
| --- | --- | --- |
| `--run <dir>` | a finished acquisition: stores, position sidecars, timing sidecars, strip record | captured, persisted, missing; camera mode |
| `--consumer-log <file>` | a publication/consumer log (the replay fixture) | attempted, published, refused, processed, released, missing; queue occupancy, restarts, latency |

In a run account, attempted, published, refused, processed and released are
`not_recorded` because the recorder writes no such record; in a consumer account,
captured and persisted are `not_recorded` because the log starts after capture.
That asymmetry is the point: a reader can see which links were actually observed.

## Categories

| Category | Run | Consumer log |
| --- | --- | --- |
| `attempted` | not recorded | rows with any timestamp |
| `captured` | store length | not recorded |
| `published` | not recorded | rows with a publication time |
| `refused` | not recorded | rows marked dropped |
| `processed` | not recorded | rows with a processing time |
| `released` | not recorded | rows with a release time |
| `persisted` | store length (reported separately from capture) | not recorded |
| `missing` | captured minus posed | non-dropped rows without a publication |

`queue` is the peak of published minus released, ordered by frame id, against the
declared capacity. `latency` is publish-to-process and process-to-release with
median/p95/max and the declared clock uncertainty. `memory` is always
`not_recorded`; no run or log here carries a measured peak.

## Findings

| Code | Severity | Raised when |
| --- | --- | --- |
| `captured_without_pose` | blocking | store length differs from posed frames (a frame exists with no placement) |
| `captured_without_timing` | warning | store length differs from timing rows |
| `run_incomplete` | warning | the plan reported anything other than success, with its error |
| `frame_budget_exceeded` | warning | a strip captured more frames than its declared budget |
| `frames_dropped` | warning | consumer rows marked dropped |
| `missing_publications` | blocking | a non-dropped row has no publication time |
| `unreleased_at_close` | warning | published frames were not released |
| `sequence_gap` | warning | frame ids are not contiguous |
| `queue_overflow` | blocking | peak occupancy exceeds the declared capacity |
| `latency_over_budget` | warning | p95 publish-to-process latency exceeds the declared budget |

## Results

Recorded run `ix71-snake-06`: captured and persisted **279**, missing **0**, no
findings, camera 10 ms / 1×1 / 1200×1200; every consumer category `not_recorded`.

Recorded run `ix71-snake-05`: captured **284**, posed **282**, missing **2** —
`captured_without_pose` blocking and `run_incomplete` warning carrying the plan's
own reason (two rows rejected on a 0.289 s telemetry bracket against the 0.2 s
limit).

Consumer fixture: attempted **7**, published **6**, refused **1**, processed
**6**, released **6**, missing **0**; queue peak **1 of 2**; publish-to-process
median **80 ms**, p95 **260 ms** (over the 150 ms budget), max 260 ms;
process-to-release median **20 ms**; **1** restart. Findings: `frames_dropped`
and `latency_over_budget`.

## Usage

```powershell
$root = 'C:\Users\yipgroup\Documents\IX83-Selfdriving-Bundle'
$py = "$root\03_external\redsun-searching-is-imaging\.venv\Scripts\python.exe"
& $py "$root\04_code\throughput_accounting\account.py" `
    --run "$root\08_session_logs\20261024T_long_strip_broom_01\run_snake_06" `
    --out "$root\04_code\throughput_accounting\ix71-snake-06.accounting.json"
& $py "$root\04_code\throughput_accounting\account.py" `
    --consumer-log "$root\04_code\throughput_accounting\consumer.example.json" `
    --out "$root\04_code\throughput_accounting\consumer.example.accounting.json"
```

Exit codes: `0` for a written account, `2` for a refused source.

## What this does not establish

- **No capacity measurement.** The consumer numbers are fixture arithmetic; a
  real endurance run at the intended mode and load is still required.
- **No memory or segmentation overhead.** Neither source carries them.
- **No causality claim.** Queue occupancy is derived from publication and release
  timestamps, not a queue readback; latency is timestamp arithmetic with the
  declared clock uncertainty, not a hardware measurement.
- **No online-versus-batch comparison.** That needs one retained input processed
  both ways, which does not exist yet.
- **No completeness inference.** A missing counter is reported as missing, not
  estimated from other counters.

## Verification

Fifteen hardware-free tests cover the clean and failed recorded runs, the consumer
fixture, missing publications, unreleased frames, sequence gaps, queue overflow,
latency budget and clock uncertainty, absent capacity, duplicate or malformed
rows, invalid schemas and the CLI. On 2026-10-27 the suite passed and
`ruff format --check` / `ruff check --select E,F,I` were clean. The full record is
[2026-10-27 throughput accounting](../../08_session_logs/20261027T_throughput_accounting_q09/README.md).
