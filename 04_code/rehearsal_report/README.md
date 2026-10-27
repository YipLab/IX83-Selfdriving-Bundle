# Rehearsal report builder

The rehearsal skill's close-out asks for one report that names every stage's
actual outcome with its artifacts and digests, keeping partial and not-applied
stages visible. `build_report.py` assembles that report from a declaration:

```json
{
  "schema": "ix71.rehearsal-declaration.v1",
  "run_id": "…",
  "scope": "software-recorded-data; …",
  "attempts": {"acquisition": "…"},
  "calibration_id": "…",
  "stages": [
    {"stage": "pose-registration", "status": "verified",
     "artifacts": [{"path": "…/calibrated_record.json", "sha256": "…"}]},
    {"stage": "anisotropy", "status": "not-applied",
     "reason": "no RTASPT analysis was run for this attempt"}
  ]
}
```

## Rules

- A stage is `verified` only when every declared artifact exists and matches its
  declared digest. A missing or changed artifact makes the stage `partial` and
  lands in the report's `blocking` list.
- A directory artifact (a Zarr store) cannot be digested as one file. It is
  recorded as `present-not-digested` with its file count and never counts as
  verified — the stage reports `partial` even when everything else matches.
- A `not-applied` stage must carry a reason and may not declare artifacts. The
  report counts those stages and lists them by name, so a modality that never ran
  cannot read as a pass.
- Known stages, unique stage ids, the declaration schema and 64-hex digests are
  validated; the tool never executes a stage and never judges whether a stage's
  method was right.

## Usage

```powershell
python build_report.py declaration.json --root <bundle> --output rehearsal_report.json
```

The command exits 0 when the report has no blocking artifact and 1 otherwise.

## Verification

```powershell
$env:PYTHONPATH = "<run>\shim"; $env:TEMP = "<run>\temp"; $env:TMP = $env:TEMP
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
python -m pytest -q -p no:cacheprovider --basetemp "<run>\report-basetemp" test_build_report.py
# 7 passed
```

Seven tests cover a fully verified chain, a missing artifact, a changed artifact,
a directory artifact, a not-applied stage with its reason, the declaration
refusals, and the command line.
