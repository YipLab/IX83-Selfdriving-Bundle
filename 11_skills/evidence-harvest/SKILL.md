---
name: evidence-harvest
description: Find, extract, verify and catalogue reusable images, data products and canonical numbers from 07_experiment_notebook and 08_session_logs for internal reuse, keeping run status separate from acceptance.
---

# Evidence harvest

Use this skill when a task needs evidence that already exists in this bundle rather than new data:
building a table of starting values, reusing a saved mosaic or registration report in the next
analysis, answering "what did we actually measure for X", assembling a handover or a status
summary, or deciding whether a number quoted in prose is still current.

Do not use it to assemble manuscript text (the [reporting workspace](../../09_reporting/README.md)
owns publication selection), to re-run an analysis, or as authorization to touch hardware.

The owning procedure is
[Harvesting reusable evidence from the notebook and session logs](../../02_docs_offline/evidence_harvesting.md).
This file is the agent-facing workflow; that page owns the rules, the traps and the tool list.

## Read first

1. [AGENTS.md](../../AGENTS.md) — evidence, index and gitignore rules.
2. [Evidence harvesting](../../02_docs_offline/evidence_harvesting.md) — the procedure this skill runs.
3. [Experiment notebook index](../../07_experiment_notebook/README.md) and
   [session log index](../../08_session_logs/README.md) — the curated maps, and their entry contracts.
4. [Catalogue row schema](references/catalogue-schema.md) — the row/record shape and worked examples.
5. [Canonical values and reference images](../../02_docs_offline/canonical_values.md) — the page this
   skill updates; check whether the value already has a row before adding one.
6. When the harvest touches instrument numbers, the
   [rehearsal skill's starting-values table](../headless-pipeline-rehearsal/SKILL.md) — the current
   maintained table, with its owner records.

If a newer page supersedes one of these, follow the newer page and say so in the output.

## Boundaries that do not move

- **Read-only by default.** A harvest reads files. It does not re-run a plan, refit a calibration,
  rebuild a mosaic or open a session. If the existing evidence cannot answer the question, the
  result is "cannot answer with existing evidence", not a fresh acquisition.
- **No device contact.** Camera, stage, laser, shutter, PVA service and session calls are outside
  this skill; that needs the authorization its own record names.
- **The entry owns the number.** Index rows, summaries and tables are pointers. When they disagree
  with an entry, the entry wins and the discrepancy is recorded once.
- **One quantity, one row, one owner.** No averaging across datasets, crops, steps, exposures or
  camera modes. A mean of unlike measurements is a new analysis and needs its own record.
- **Run status is not acceptance.** `exit_status: success`, "passed" and "completed" describe the
  run. A refused calibration carried by a successful run is still refused.
- **Local archive.** `07_experiment_notebook/`, `08_session_logs/` and `09_reporting/` are ignored
  by the public repository. Do not commit them, do not copy raw data or Zarr stores into a record,
  and do not rewrite an original to make a link work.

## Phase 1 — scope

1. Write one sentence: the quantity or artifact wanted, and the campaigns/dataset/camera mode in
   scope. "Everything important" is not a scope.
2. Decide the output shape up front: a single canonical-value row, a multi-row catalogue, an
   image set for a handover, or a refusal ("no usable evidence exists").
3. Name what you are **not** harvesting, and why, before reading anything.

## Phase 2 — discover

1. Search the two curated indexes first; they already mark supersession, acceptance and refusal:
   `Select-String` on `canonical|superseded|acceptance|refus|not_applied` over both index files.
2. Follow to the entry README and read it in its contract order (session: scope → commanded →
   result → artifacts → evidence status → next gate; notebook: scope → source/revision → method →
   result → artifacts → evidence status/limits → next gate).
3. Census the artifacts **scoped to that entry**:

   ```powershell
   $entry = "<entry path>"
   Get-ChildItem $entry -File |
     Where-Object { $_.Extension -in '.png','.svg','.json','.csv','.npy','.html','.tif' } |
     Sort-Object Length -Descending | Select-Object Name, Length
   Get-ChildItem $entry -Directory | Select-Object Name
   ```

   Never begin with a recursive pass over the whole archive: it is slow (over two minutes on
   2026-10-31), and old sandbox temp roots under the tree deny access and add noise.

4. Skip an entry whose `README.md` is absent. Roughly a third of session directories have none
   (245 of 692 on 2026-10-31); they are test-run and scratch roots, not evidence. The archive grows
   during a working day, so re-count rather than trusting a remembered figure.

5. Exclude cache and runtime roots before counting anything: `napari-cache/` (7 900 of the
   archive's 7 906 `.svg` files are napari theme icons) and `*.cubin` (CuPy kernels) are not
   evidence.

## Phase 3 — extract

Fill one row per artifact or value using
[the catalogue schema](references/catalogue-schema.md):

- owner entry link and artifact path;
- quantity and unit, or a one-line description of what an image shows;
- the three status axes — **ran**, **verdict**, **reuse**;
- conditions (camera mode, exposure, crop, scale, step, profile, calibration id, specimen, date);
- producing script or plan;
- the explicit non-claim (what this row does not establish).

An image row is incomplete without the script/plan that drew it and the input identity. An image
with neither is an illustration, not a measurement.

**Where the row lands.** Canonical values and known-good TIFFs go into the maintained
[canonical values and reference images](../../02_docs_offline/canonical_values.md) page; reusable
images and data products go into the [artifact register](../../02_docs_offline/artifacts.md), with
their current paths. Neither lives in a session log. The run record keeps the scope, method and
machine inventories and links both pages. A row enters a page only after Phase 4; a value that cannot
be verified stays in the run's open list, not in the catalogue.

## Phase 4 — verify identity

- Declared digests:
  `04_code/rehearsal_audit/declared_digests.py --root <bundle> --output <run>/declared-digests.json`.
  `verified` means the file is the one the record described; it does not mean the record was right.
  A row under a commit/snapshot/history heading is a point-in-time claim; a mismatch there is
  `historical_mismatch`, not a defect.
- Figure reuse: register or verify through
  [export manifest](../../04_code/export_manifest/README.md); it refuses a missing input, an
  undeclared unit and an incoherent status combination.
- Run artifacts: [rehearsal audit](../../04_code/rehearsal_audit/README.md) re-reads a saved
  `run_manifest.json` / `rehearsal_report.json` for missing files, digest drift and broken stage
  claims.
- A missing file is "unverifiable from this checkout", not "never happened". Write that sentence.

## Phase 5 — write and close out

1. Update [canonical values and reference images](../../02_docs_offline/canonical_values.md) and the
   [artifact register](../../02_docs_offline/artifacts.md) in place: add or supersede rows, add
   known-good TIFFs when their record says the product passed, keep artifact paths current, and date
   the change in the page's change log. Do not keep a second copy in the run record.
2. A harvest that answers a question and produces artifacts gets its own dated entry under
   `08_session_logs/` with a full README (scope, method, inventories, checks, open list); add a
   notebook entry too when it establishes a reusable method, and cross-link the pair.
3. A harvest that only refreshes the catalogue needs no new directory — just the dated change-log
   row and the refreshed index entries.
4. Add or refresh the index row in the notebook or session index **in the same change**.
5. Never write into another record's folder; write your own and link the original.
6. Report the harvest as documentation work, separately from runtime tests and physical acceptance.

## Refuse, and say which condition failed, when

- the scope is "everything" or the question has no quantity or artifact attached;
- the only source is an index row, a prose summary or a filename;
- two records disagree and neither is identified as superseding the other — report both, do not
  choose;
- answering would require a re-run, a refit or a device;
- the artifact is missing, a Zarr directory, or a preview whose downsample factor is unstated;
- the number would have to be averaged across datasets to be useful.

## Close-out

State: the scope sentence; rows added and where; every digest check run with its result; the
entries read but not promoted and why; which non-claims each row carries; the index rows
refreshed; and that nothing was re-run or contacted. Keep a dated "harvested / skipped / open"
list rather than claiming the archive has been exhausted.
