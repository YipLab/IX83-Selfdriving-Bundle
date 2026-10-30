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

## Generating the report (T7)

`assemble_report.py` writes the record this audit verifies. It takes **one run root**
and derives each of the ten stage statuses from the artifacts that exist under it:

```powershell
& $py "$root\04_code\rehearsal_audit\assemble_report.py" `
    --run-root "$root\08_session_logs\20261029T_t2_chain_01\run08" `
    --output <run>/rehearsal_report.json `
    --specimen-id ix71-fixed-sample-20261015 --calibration <record>.json `
    --profile ix71_asi_pvcam_sapphire.yaml --profile-revision 2026-10-28 `
    --authorization "<who, when, which envelope>" --attempt t2chain08
```

It emits `ix83.rehearsal-report/v3`: the Close-out names per stage (`status`,
`artifact`, `measured`, `criterion`, `verdict`, `notes`) plus the `state` /
`artifact_check` mirror this audit's `rehearsal-report-v2` collector reads, so the
loop assemble → audit is closed. Statuses are `completed` (artifact inside the root
and a figure read from it), `unknown` (present but unreadable, partial, or outside the
root), `not_applied` (absent, with the reason) and `failed` (the artifact's own record
says the step failed).

**It refuses the one-session claim** when the root carries more than one session log
with a plan completion marker, naming each session; a preflight session that launched
no plan is reported as idle and does not count. `--check <report>` re-hashes every
declared artifact.

Exit codes: `0` claim stands, `1` claim refused, `2` run root unusable. Its tests are
in `test_assemble_report.py`.

## Declared-digest audit across records

`declared_digests.py` audits the digests that Markdown records declare for their
artifacts. It reads `| file link | `sha256` |` rows, including rows that annotate the link (for example `(new)`), resolves each target
against the record, recomputes the digest and reports `verified`, `missing`,
`digest_mismatch` or `unreadable`. External links are skipped, and a row without
a digest is ignored.

A table under a heading that mentions a commit, history or a snapshot is treated
as a point-in-time claim: a mismatch there is reported as
`historical_mismatch` and does not block, so an old commit record stays honest
without pretending it describes today's file.

```powershell
python declared_digests.py --root <bundle> --output <run>/declared-digests.json
```

On the bundle as of 2026-10-27 it reads **87 declared digests** across 17
records: 84 verified and 3 classified historical (two planner files recorded at commit `08248b1`, and the
work-packages source-snapshot row). Its first run found eight mismatches — five
stale current claims and three misclassified point-in-time ones — and each was
fixed rather than suppressed: two planner rows moved under a "Files at planner
commit 08248b1" heading, the work-packages heading became an explicit snapshot,
two application-file digests in the ring-consumer record and the ledger test
digest in the Q02 record were refreshed with a note, and the S2 handoff record's
table was corrected after it had printed one digest for three different files.
## Findings

| Code | Severity | Raised when |
| --- | --- | --- |
| `artifact_missing` | blocking | a declared path no longer exists |
| `stage_claim_broken` | blocking | a stage in a verified state has a missing declared artifact |
| `artifact_digest_mismatch` | blocking | the file exists but its digest differs from the record |
| `artifact_byte_mismatch` | warning | the size differs and no digest was declared |

The record is never edited. A missing file does not prove the acquisition never
happened; it means the evidence can no longer be re-verified from this checkout.

`declared_digests.py` audits the digests that Markdown records declare for their
artifacts. It reads `| file link | `sha256` |` rows, including rows that annotate the link (for example `(new)`), resolves each target
against the record, recomputes the digest and reports `verified`, `missing`,
`digest_mismatch` or `unreadable`. External links are skipped, and a row without
a digest is ignored.

A table under a heading that mentions a commit, history or a snapshot is treated
as a point-in-time claim: a mismatch there is reported as
`historical_mismatch` and does not block, so an old commit record stays honest
without pretending it describes today's file.

```powershell
python declared_digests.py --root <bundle> --output <run>/declared-digests.json
```

On the bundle as of 2026-10-27 it reads **87 declared digests** across 17
records: 84 verified and 3 classified historical (two planner files recorded at commit `08248b1`, and the
work-packages source-snapshot row). Its first run found eight mismatches — five
stale current claims and three misclassified point-in-time ones — and each was
fixed rather than suppressed: two planner rows moved under a "Files at planner
commit 08248b1" heading, the work-packages heading became an explicit snapshot,
two application-file digests in the ring-consumer record and the ledger test
digest in the Q02 record were refreshed with a note, and the S2 handoff record's
table was corrected after it had printed one digest for three different files.
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

`declared_digests.py` audits the digests that Markdown records declare for their
artifacts. It reads `| file link | `sha256` |` rows, including rows that annotate the link (for example `(new)`), resolves each target
against the record, recomputes the digest and reports `verified`, `missing`,
`digest_mismatch` or `unreadable`. External links are skipped, and a row without
a digest is ignored.

A table under a heading that mentions a commit, history or a snapshot is treated
as a point-in-time claim: a mismatch there is reported as
`historical_mismatch` and does not block, so an old commit record stays honest
without pretending it describes today's file.

```powershell
python declared_digests.py --root <bundle> --output <run>/declared-digests.json
```

On the bundle as of 2026-10-27 it reads **87 declared digests** across 17
records: 84 verified and 3 classified historical (two planner files recorded at commit `08248b1`, and the
work-packages source-snapshot row). Its first run found eight mismatches — five
stale current claims and three misclassified point-in-time ones — and each was
fixed rather than suppressed: two planner rows moved under a "Files at planner
commit 08248b1" heading, the work-packages heading became an explicit snapshot,
two application-file digests in the ring-consumer record and the ledger test
digest in the Q02 record were refreshed with a note, and the S2 handoff record's
table was corrected after it had printed one digest for three different files.
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

`declared_digests.py` audits the digests that Markdown records declare for their
artifacts. It reads `| file link | `sha256` |` rows, including rows that annotate the link (for example `(new)`), resolves each target
against the record, recomputes the digest and reports `verified`, `missing`,
`digest_mismatch` or `unreadable`. External links are skipped, and a row without
a digest is ignored.

A table under a heading that mentions a commit, history or a snapshot is treated
as a point-in-time claim: a mismatch there is reported as
`historical_mismatch` and does not block, so an old commit record stays honest
without pretending it describes today's file.

```powershell
python declared_digests.py --root <bundle> --output <run>/declared-digests.json
```

On the bundle as of 2026-10-27 it reads **87 declared digests** across 17
records: 84 verified and 3 classified historical (two planner files recorded at commit `08248b1`, and the
work-packages source-snapshot row). Its first run found eight mismatches — five
stale current claims and three misclassified point-in-time ones — and each was
fixed rather than suppressed: two planner rows moved under a "Files at planner
commit 08248b1" heading, the work-packages heading became an explicit snapshot,
two application-file digests in the ring-consumer record and the ledger test
digest in the Q02 record were refreshed with a note, and the S2 handoff record's
table was corrected after it had printed one digest for three different files.
## What this does not establish

- **Not a re-run.** The artifacts are read, not regenerated; a figure or table is
  not re-derived.
- **Not content verification.** A present file with a matching digest is the file
  the record described; it is not proof the record was right.
- **No discovery of undeclared evidence.** A file nobody declared is invisible
  here.
- **No physical state.** Nothing contacts a device.

`declared_digests.py` audits the digests that Markdown records declare for their
artifacts. It reads `| file link | `sha256` |` rows, including rows that annotate the link (for example `(new)`), resolves each target
against the record, recomputes the digest and reports `verified`, `missing`,
`digest_mismatch` or `unreadable`. External links are skipped, and a row without
a digest is ignored.

A table under a heading that mentions a commit, history or a snapshot is treated
as a point-in-time claim: a mismatch there is reported as
`historical_mismatch` and does not block, so an old commit record stays honest
without pretending it describes today's file.

```powershell
python declared_digests.py --root <bundle> --output <run>/declared-digests.json
```

On the bundle as of 2026-10-27 it reads **87 declared digests** across 17
records: 84 verified and 3 classified historical (two planner files recorded at commit `08248b1`, and the
work-packages source-snapshot row). Its first run found eight mismatches — five
stale current claims and three misclassified point-in-time ones — and each was
fixed rather than suppressed: two planner rows moved under a "Files at planner
commit 08248b1" heading, the work-packages heading became an explicit snapshot,
two application-file digests in the ring-consumer record and the ledger test
digest in the Q02 record were refreshed with a note, and the S2 handoff record's
table was corrected after it had printed one digest for three different files.
## Verification

Nine hardware-free tests cover the three record shapes, clean and broken
verification, digest and byte drift, prose notes, missing sources and the CLI.
On 2026-10-27 the suite passed and `ruff format --check` / `ruff check --select
E,F,I` were clean.



