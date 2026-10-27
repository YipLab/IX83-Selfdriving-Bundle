# Figure export manifest

Q12 of the [2026-10-27
increment](../../02_docs_offline/redsun_rtaspt_integration_next_steps.md#manuscript-driven-implementation-increment-2026-10-27):
"link run products, analysis versions/configurations, exclusions, uncertainty and
CSV/SVG/PNG figure outputs in one rebuildable manifest ... Reject incompatible
units/modes, missing source IDs and placeholder/recorded status mismatches."

One document per figure. A declaration lists the figure's inputs (path, kind,
quantity, unit, status), the manuscript slots it fills, the analysis name,
version and configuration, and the exclusions. The builder resolves each input,
hashes it, records the four software revisions and derives the manifest; the
verifier re-hashes a saved manifest and reports every changed or missing input.

The tool does not plot, re-process or invent a value, and it does not edit the
reporting pages. It reads the same saved products the handoff verifier reads, so
the bundle keeps one transport rather than two.

## Declaration

| Field | Meaning |
| --- | --- |
| `figure_id`, `title` | the figure identity |
| `status` | `measured`, `recorded`, `synthetic`, `placeholder` or `not-applied` |
| `reason` | required when `status` is `not-applied` |
| `slots` | `{slot, claim, reason?}`, with `slot` matching `Dnn` or `Mnn` and `claim` `filled` or `not-applied` |
| `inputs` | `{path, kind, status, quantity, unit, produced_by?}`, with `kind` one of `csv`, `png`, `svg`, `json`, `tif`, `zarr` |
| `unit_registry` | quantity to expected unit, checked against every input |
| `analysis` | `{name, version, config}`; the configuration file is hashed |
| `exclusions` | nonempty statements of what the figure leaves out |

## Status rules

The manifest's status is a claim about the figure, and the rules are deliberately
narrow:

| Figure status | Allowed input statuses |
| --- | --- |
| `measured` | every input `measured`; any synthetic or placeholder input is refused |
| `recorded` | `recorded` and `measured`; synthetic and placeholder refused |
| `synthetic` | `synthetic`; placeholder refused |
| `placeholder` | `placeholder` |
| `not-applied` | no inputs, with a reason |

A delivered figure may not carry a `not-applied` slot: that slot is delivered
separately or the figure is marked `not-applied` with its reason.

## Refusals

- unknown schema, status, kind or slot format;
- a repeated slot, or a slot that is `not-applied` without a reason;
- a declared input that is missing, is a directory, or lacks a status, kind,
  quantity or unit;
- a unit that disagrees with the declaration's registry;
- a status combination the table above forbids;
- a missing analysis configuration at build time;
- a saved manifest whose input digest or analysis-config digest has changed;
- a manifest written under another schema.

`accepted` is always `false`: the manifest supports a claim, it does not make one.

## Example

`records/figure-2.sources.json` declares a placeholder figure filling D03 and D06
with one placeholder CSV input and an analysis configuration. Building it writes
`records/figure-2.manifest.json`, which the verifier accepts unchanged. The
example is deliberately **placeholder**, because no measured revisit/registration
figure exists yet; the tests exercise the measured and recorded paths with
synthetic trees.

```powershell
$root = 'C:\Users\yipgroup\Documents\IX83-Selfdriving-Bundle'
$py = "$root\03_external\redsun-searching-is-imaging\.venv\Scripts\python.exe"
& $py "$root\04_code\export_manifest\export.py" `
    --sources "$root\04_code\export_manifest\records\figure-2.sources.json" `
    --out "$root\04_code\export_manifest\records\figure-2.manifest.json"
& $py "$root\04_code\export_manifest\export.py" `
    --verify "$root\04_code\export_manifest\records\figure-2.manifest.json"
```

Exit codes: `0` for a built or verified manifest, `1` when verification finds a
changed or missing input, `2` for a refused declaration or manifest.

## What this does not establish

- **Not a measurement.** A manifest records what a figure was built from; it
  cannot tell whether the underlying number is right.
- **Not truth enforcement.** The status is a declaration. The builder refuses
  incoherent combinations, but a wrong `measured` label on a fabricated CSV
  would pass; provenance review remains the author's job.
- **No slot authority.** The manifest records the slots a figure claims; it does
  not decide which slot a result belongs to, and it does not edit the slot
  registry.
- **No plotting or analysis.** It never produces the figure, the statistic or the
  table.
- **Zarr inputs are not digested** — a directory is refused rather than hashed
  file-by-file; export the product to a file first.

## Verification

Twenty-eight hardware-free tests cover the coherent declaration, every refusal
above, digest building, software identity, changed/missing input and config
verification, and the CLI exit codes. On 2026-10-27 the suite passed and
`ruff format --check` / `ruff check --select E,F,I` were clean. The full record is
[2026-10-27 figure export](../../08_session_logs/20261027T_figure_export_q12/README.md).
