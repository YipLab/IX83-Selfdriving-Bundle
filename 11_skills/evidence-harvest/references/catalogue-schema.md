# Catalogue row schema

Reference for the [evidence-harvest skill](../SKILL.md) and the
[harvesting procedure](../../../02_docs_offline/evidence_harvesting.md). This is the shape of a
harvest row, not a claim about any particular record.

Rows that pass verification land in the maintained
[canonical values and reference images](../../../02_docs_offline/canonical_values.md) page, or in the
[artifact register](../../../02_docs_offline/artifacts.md) for reusable images and data products; the
session run record keeps the scope, method and machine inventories. The schema below is what those
pages' tables and any intermediate harvest table use.

## Markdown table

A harvest table is readable by a person and auditable by a script. One row per artifact or value.

| Column | Required | Content |
| --- | --- | --- |
| `row_id` | yes | stable short id, e.g. `H03`; unique within the harvest |
| `owner` | yes | relative link to the **entry README** that measured it (not the index, not a summary) |
| `artifact` | yes | relative link to the file, or `—` for a value that exists only in the entry's prose (state which section) |
| `kind` | yes | `image` · `table` · `array` · `value` · `refusal` · `reproducer` · `identity` |
| `what` | yes | quantity + unit, or one line on what the image/table shows |
| `conditions` | yes | camera mode, binning, exposure, crop, scale, step, profile, calibration id, specimen, date — only what applies |
| `ran` | yes | `physical` · `recorded-replay` · `mock` · `synthetic` · `not-run` |
| `verdict` | yes | `measured` · `partial` · `refused` · `not_applied` · `unknown` · `superseded` |
| `reuse` | yes | `as-is` · `with-conditions` · `do-not-reuse` |
| `producer` | for images and tables | link to the script/plan that made it, or the plan name |
| `identity` | when declared | sha256 (or `none declared`), frame/target counts, gate verdict |
| `non_claim` | yes | the sentence this row may **not** be used to support |
| `supersedes` | when true | link to the row/entry it replaces, and the reason |

Units are explicit in the column, never implied by a field name: `µm/px`, `px`, `DN`, `µm`,
`mW`, `s`, `%`. Uncertainty is `±` with its basis (standard error, RMS, range) or `none stated`.

## JSON record

The same row as machine-readable data, for a harvest that feeds a tool:

```json
{
  "schema": "ix83.evidence-harvest-row/v1",
  "harvested_utc": "2026-10-31T00:00:00Z",
  "harvest_scope": "one sentence naming the quantity and the campaigns in scope",
  "row_id": "H03",
  "owner": {"path": "07_experiment_notebook/2026-10-23_ix71_optical_scale/README.md", "section": "Result"},
  "artifact": {"path": "07_experiment_notebook/2026-10-23_ix71_optical_scale/scale_summary.json", "kind": "json", "sha256": null},
  "what": {"quantity": "sampling", "value": 0.18333, "unit": "um/px", "uncertainty": "reticle 0.1823-0.1829"},
  "conditions": {"objective": "60x", "sensor_pixel_um": 11.0, "camera": "PVCAM Camera-1", "binning": 1},
  "ran": "recorded-replay",
  "verdict": "measured",
  "reuse": "with-conditions",
  "producer": "07_experiment_notebook/2026-10-23_ix71_optical_scale/analyse_scale.py",
  "non_claim": "does not establish physical accuracy without the reticle authority",
  "supersedes": null
}
```

The JSON form is a convenience. The Markdown table remains the record; a harvesting run that
writes JSON also writes the table, or the JSON is data with no readable owner.

## Status vocabulary, and the tools that share it

| Axis | Values | Matches existing vocabulary |
| --- | --- | --- |
| `ran` | `physical`, `recorded-replay`, `mock`, `synthetic`, `not-run` | "physical", "recorded-data", "software/mock" in session READMEs |
| `verdict` | `measured`, `partial`, `refused`, `not_applied`, `unknown`, `superseded` | export manifest `measured`/`recorded`/`synthetic`/`placeholder`/`not-applied`; rehearsal `completed`/`unknown`/`not_applied`/`failed` |
| `reuse` | `as-is`, `with-conditions`, `do-not-reuse` | no existing equivalent; this axis is the harvest's own contribution |

Do not translate a tool's status into a verdict silently. A rehearsal stage in `completed` may be
`verdict: partial` if only its artifact presence was verified, and a plan in `exit_status:
success` may carry `verdict: refused` for the calibration it reports.

## Worked examples

Each example is filled from the record it links, at the date shown; it is an example of *shape*,
not a re-verified measurement.

### A — canonical value with a conversion trap

| field | value |
| --- | --- |
| row_id | `H01` |
| owner | [ix71 optical scale](../../../07_experiment_notebook/2026-10-23_ix71_optical_scale/README.md#result) |
| artifact | [`scale_summary.json`](../../../07_experiment_notebook/2026-10-23_ix71_optical_scale/scale_summary.json), [`scale.png`](../../../07_experiment_notebook/2026-10-23_ix71_optical_scale/scale.png) |
| kind | `value` |
| what | sampling **0.18333 µm/px** (5.455 px/µm) |
| conditions | 60×, 11 µm camera pixels, PVCAM `Camera-1`, 1200×1200, 12-bit, unbinned, 10 ms |
| ran | `recorded-replay` |
| verdict | `measured` |
| reuse | `with-conditions` — the MR095 reticle (0.1823–0.1829 µm/px) is the authority |
| producer | [`analyse_scale.py`](../../../07_experiment_notebook/2026-10-23_ix71_optical_scale/analyse_scale.py) |
| identity | inputs declared by sha256 in the JSON; fit slopes 10.08 / 10.53 px per **reported** µm |
| non_claim | the stored `result.um_per_px_mean` ≈ 0.0971 is the reported-travel value at the doubled conversion; it is **not** the sampling, and quoting it is the known trap |

### B — image result reused outside its entry

| field | value |
| --- | --- |
| row_id | `H02` |
| owner | [physical bead capture](../../../08_session_logs/20261020T_physical_redsun_bead_capture_01/README.md) |
| artifact | [`bead_snap_contact_sheet.png`](../../../08_session_logs/20261020T_physical_redsun_bead_capture_01/bead_snap_contact_sheet.png) |
| kind | `image` |
| what | contact sheet of acquired bead frames; cropped for Figure 3a in the [figure source catalogue](../../../09_reporting/figures/source_catalogue.md) |
| conditions | physical capture on the bead field recorded in that entry |
| ran | `physical` |
| verdict | `measured` |
| reuse | `with-conditions` — reuse the crop, not the whole sheet, and carry the acquisition identity |
| producer | the session's capture plan/record (see the entry) |
| non_claim | a contact sheet is a view of frames, not a registration or scale result |

### C — session result with a stated limit

| field | value |
| --- | --- |
| row_id | `H03` |
| owner | [T2 on the live sample](../../../08_session_logs/20261030T_t2_live_01/README.md#result) |
| artifact | the entry's `run2` results (revisit landing written beside the frames) |
| kind | `value` |
| what | **12/12** revisit landings within 2 µm, median 0.695 µm, max 1.088 µm (stage-space) |
| conditions | live specimen, one session, `ix71-asi-sapphire`, 6 × 6 at 60 µm, 20 ms, 1×1, 1200 × 1200, `laser488` 1.0 mW, `2HB` 16 µm on the survey leg (restored to 1.4), `single_session: true` |
| ran | `physical` |
| verdict | `measured` |
| reuse | `with-conditions` — stage-space landing only; a different mount, step or calibration is a different measurement |
| producer | `run_workflow_retest.py --step chain` (headless, one session; see the entry's "What was commanded") |
| non_claim | the optical landing is **14.97 µm** (outside 2 µm) and is the record's own limitation; this row is not optical-accuracy evidence |

### D — refusal kept as evidence

| field | value |
| --- | --- |
| row_id | `H04` |
| owner | [T2 on the live sample](../../../08_session_logs/20261030T_t2_live_01/README.md#run1-isolated-the-only-blocker-the-detection-floor) |
| artifact | `run1/review.html` and the refused decision |
| kind | `refusal` |
| what | the review decision refused: "the checkpoint has no candidate targets, so there is nothing to decide" |
| conditions | inherited fixed-sample floor `minimum_adu: 800`; live field corrected mosaic p99 52, max 509 |
| ran | `physical` |
| verdict | `refused` |
| reuse | `with-conditions` — reusable as a documented precondition (the floor must be field-matched) |
| producer | `prepare_snap_review_checkpoint` / `prepare_snap_review_decision` on the run's own store |
| non_claim | a refusal is not a failed acquisition: the survey and registration in the same run passed |

## Row granularity

- One row per quantity, not per sentence. A table of ten targets is one row with a count, not ten
  rows.
- One row per condition set. Two camera modes are two rows even when the value is "the same".
- A superseded value keeps its row and gains `supersedes`/`superseded-by` links; it is never
  overwritten by the newer number.
- A figure is a row only when something downstream needs the figure itself; otherwise the row
  points at the data product the figure was drawn from.
