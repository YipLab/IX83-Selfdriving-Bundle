# Figure-input builder

Q12 asks for rebuildable CSV/SVG/PNG figure outputs linked to their run products,
analysis configuration, exclusions and uncertainty. This tool builds the first
half of a figure: a measured per-pair table, a deterministic SVG and a
provenance sidecar, all from a saved registration record.

It does not register, re-stitch, re-fit or choose a manuscript slot. The numbers
are the record's own reported placement residuals, and the sidecar says the slot
assignment is pending the author.

## What it writes

| Artifact | Content |
| --- | --- |
| `placement_residuals.csv` | one row per passing pair: pair index, reference/moving frame, residual x/y and magnitude in px |
| `placement_residuals.svg` | deterministic histogram of the magnitudes, with the x axis in px and `n` annotated |
| `provenance.json` | record path and digest, registration and calibration ids, pairs total versus plotted, magnitude median and maximum, table and SVG digests, bins, and an explicit `slot: null` with `pending author assignment` |

A failed pair is excluded because it has no placement to plot; the sidecar keeps
`pairs_total` so the exclusion is visible rather than silent. A record with no
passing pair, no `pairs` list, or a non-numeric or non-finite residual is
refused.

## Determinism

The SVG is assembled directly from strings — no plotting library, no fonts and no
timestamps — so rebuilding the same record produces the same bytes. That is what
makes the table and the SVG digestable in a manifest.

## Usage

```powershell
python figure.py <registration-record.json> `
  --table placement_residuals.csv `
  --svg placement_residuals.svg `
  --sidecar provenance.json `
  --title "Recorded 5x5 placement residual magnitudes" --bins 24
```

## Verification

```powershell
$env:PYTHONPATH = "$root\tmp\track-export-20261027\shim"   # DSH mkdir(0o777) shim
$env:TEMP = "$root\tmp\track-export-20261027\temp"; $env:TMP = $env:TEMP
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
python -m pytest -q -p no:cacheprovider --basetemp "$root\tmp\track-export-20261027\figure-basetemp" test_figure.py
# 7 passed
```

Seven tests cover failed-pair exclusion, histogram accounting, SVG determinism
and labels, every refusal, the three written artifacts with their digests, the
command line, and the recorded 5×5 record (300 plotted pairs, median magnitude
0.148 px, maximum below 1 px) when that local archive is present.
