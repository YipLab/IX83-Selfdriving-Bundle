# Rehearsal record audit

Track D's evidence lives in a rehearsal report and a digest manifest, and both
were written before they were last read. This tool re-reads a saved record and
answers one question: **do the files it declares still exist, with the size and
digest it claims?**

It knows the three record shapes in use:

| Shape | Where the artifacts are declared |
| --- | --- |
| `run-manifest` | `stages[].artifacts[]` with `path`, `bytes`, `sha256` |
| `rehearsal-report-v2` | `stages[].artifact_check.found[]` with `path`/`bytes`, plus `stages[].record` when it is a path |
| `rehearsal-report-v1` | `artifact_manifest` file (`artifacts[]` with `original_path`/`consolidated_path`/`sha256`), or `stages{}.artifact_source_paths[]` |

A prose `record` (for example the anisotropy stage's "no analyser in this light
path…") is kept as a note, not counted as a missing file.

## Findings

| Code | Severity | Raised when |
| --- | --- | --- |
| `artifact_missing` | blocking | a declared path no longer exists |
| `stage_claim_broken` | blocking | a stage in a verified state has a missing declared artifact |
| `artifact_digest_mismatch` | blocking | the file exists but its digest differs from the record |
| `artifact_byte_mismatch` | warning | the size differs and no digest was declared |

The record is never edited. A missing file does not prove the acquisition never
happened; it means the evidence can no longer be re-verified from this checkout.

## Result, 2026-10-27

| Record | Declared | Verified | Missing | Byte drift |
| --- | --- | --- | --- | --- |
| long-strip `run_manifest.json` | 28 | 25 | 2 | 1 |
| long-strip `rehearsal_report.json` | 37 (1 note) | 34 | 2 | 1 |
| `20261025T0830Z` report | 28 | 28 | 0 | 0 |

The two missing files are the `ix71-snake-01` and `ix71-snake-02` stage-7 attempt
reports; no report anywhere in the session carries either confirmation id, so
this is not a rename. Both records mark stage 7 verified, so the audit reports
`stage_claim_broken` for it. `review_config.template.json` has drifted in size in
both records without a declared digest, so the change cannot be attributed. The
full record is
[2026-10-27 rehearsal audit](../../08_session_logs/20261027T_rehearsal_audit/README.md).

## Usage

```powershell
$root = 'C:\Users\yipgroup\Documents\IX83-Selfdriving-Bundle'
$py = "$root\03_external\redsun-searching-is-imaging\.venv\Scripts\python.exe"
& $py "$root\04_code\rehearsal_audit\audit.py" `
    --source "$root\08_session_logs/20261024T_long_strip_broom_01/rehearsal/run_manifest.json" `
    --source "$root\08_session_logs/20261024T_long_strip_broom_01/rehearsal/rehearsal_report.json" `
    --source "$root\05_simulations/rehearsal/20261025T0830Z/rehearsal_report.json" `
    --out "$root\04_code\rehearsal_audit\records\rehearsal-audit.json"
```

Exit codes: `0` when no blocking finding, `1` when one exists, `2` for an
unreadable or unrecognised record.

## What this does not establish

- **Not a re-run.** The artifacts are read, not regenerated; a figure or table is
  not re-derived.
- **Not content verification.** A present file with a matching digest is the file
  the record described; it is not proof the record was right.
- **No discovery of undeclared evidence.** A file nobody declared is invisible
  here.
- **No physical state.** Nothing contacts a device.

## Verification

Nine hardware-free tests cover the three record shapes, clean and broken
verification, digest and byte drift, prose notes, missing sources and the CLI.
On 2026-10-27 the suite passed and `ruff format --check` / `ruff check --select
E,F,I` were clean.
