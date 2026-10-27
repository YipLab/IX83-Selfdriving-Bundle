# Track coverage export

Q08 of the [2026-10-27
increment](../../02_docs_offline/redsun_rtaspt_integration_next_steps.md#manuscript-driven-implementation-increment-2026-10-27)
asks for calibrated track/window/control exports built on RTASPT's analysis, with
duration and censoring retained, support masks kept, edge exits classified
separately from particle disappearance, and gap/censoring behaviour tested
before dynamic-data acceptance.

This tool is the export half only. RTASPT owns tracking, fitting, diffusion,
drift control and localization precision; nothing here estimates motion or
fits a model. It consumes a declared track table and reports what a figure or a
downstream fit needs to know about **coverage**.

## What it computes

| Field | Meaning |
| --- | --- |
| `frames`, `duration_s` | observed frames and their span at the declared frame period |
| `gaps` | breaks in frame continuity, reported as information |
| `censoring` | `none`, `start`, `end` or `both`, from whether the track touches the window bounds |
| `lag_pairs` | observed frame pairs at lags 1..N — what a fit *could* use, not a displacement estimate |
| `support_runs` | the contiguous frame runs the track was seen in |
| `edge_at_start`, `edge_at_end` | whether the first/last detection sits within the declared ROI margin |
| `summary` | per-field totals: tracks, frames, lag-1 pairs, censored tracks, edge-ended tracks, gap events |

Refusals are typed rather than raised, so a refused table can still be archived:
a missing schema or window, an invalid frame period, a duplicate or empty track
id, a track without points, and non-increasing frames are blocking; a track that
spans more than its window is a warning; frame gaps are information.

## Adapter from a recorded export

`adapter.py` reads a delimited track export with the columns `track_id`, `frame`,
`x_px`, `y_px` and produces the declared table, with the identity, frame period,
window and ROI the caller states. It refuses a missing column by name, a blank
`track_id`, a non-integer or negative frame, a non-numeric coordinate and a
duplicate `(track, frame)` pair, naming the line. It does not rename or reorder
columns, and it does not infer the frame period, window, ROI or identity from the
file. The produced table records the source path and its SHA-256 so a downstream
figure can point at the exact input.

```powershell
python adapter.py tracks.csv --specimen spec-1 --field field-1 `
  --frame-period 0.05 --window 0 2 --roi-x 0 64 --roi-y 0 64 --output table.json
```
## What this does not establish

- **No motion model.** A lag-pair count is not a diffusion coefficient, an
  anomalous exponent or a localization precision.
- **No disappearance mechanism.** An edge flag says the track's end is near the
  ROI boundary. A track that ends without edge contact is a different event and
  is not classified here.
- **No identity beyond the declared table.** Specimen, field and window come from
  the table; the tool checks their consistency, not their provenance.
- **No RTASPT import.** The export is standard-library only, so it can run beside
  any RTASPT environment without pinning that environment's stack.

## Usage

```powershell
python tracks.py tracks.json --output export.json
```

The command returns 0 for an accepted table and 1 for a refused one, writing the
report either way.

## Verification

```powershell
$env:PYTHONPATH = "$root\tmp\track-export-20261027\shim"   # DSH mkdir(0o777) shim
$env:TEMP = "$root\tmp\track-export-20261027\temp"; $env:TMP = $env:TEMP
python -m pytest -q -p no:cacheprovider --basetemp "$root\tmp\track-export-20261027\basetemp" test_tracks.py test_adapter.py
# 19 passed
```

The tests cover a stationary control, a drifting track with identical lag
support, dropped frames (including the lag pairs that survive a gap), a track
censored at both ends, edge contact classified apart from censoring, the
document-level summary, every refusal code, a track longer than its window, input
validation and both command-line exit codes. The adapter tests cover a convert
round trip through the export, a missing column, an empty file, four row errors,
a duplicate point, missing identity and the adapter CLI.

