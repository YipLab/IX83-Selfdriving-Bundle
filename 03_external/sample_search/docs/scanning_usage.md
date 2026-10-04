# Explicit stage scanning through Pycro-Manager

The [scan command](../../../04_code/sample_search/scan.py) is a bundle-owned host
launcher for a primary stage grid and a secondary scan of explicit target positions, using the original
[Beanshell behavior](beanshell_scan_reference.md) as a reference.
It calls the existing IX83 executor and Pycro-Manager/MMCore adapters; it does not
execute the MM1.4 scripts or create another microscope control server.

The current stage position is the grid origin. Rows advance along grid Y and
columns along grid X, with positive micrometre spacing and optional signs/XY
exchange. Default traversal is column-major, as in the original tiled macro;
`--serpentine` reverses the row traversal in alternate columns.
Every position is checked before the first move against a 1 mm-wide envelope
centered on the starting position (at most 500 um offset per axis).
These are explicit commanded stage distances. Without an optical transform,
the procedure makes no assertion of contiguous image coverage or target centering.

Run from the bundle root using the existing acquisition integration environment
with both the library and host on `PYTHONPATH`:

```powershell
# Hardware-free: six positions, three 50 ms frames per position.
$env:PYTHONPATH = "03_external/sample_search;04_code/sample_search"
04_code/ix83_acquisition/.venv-integration/Scripts/python.exe `
  04_code/sample_search/scan.py --rows 2 --columns 3 `
  --step-x-um 25 --step-y-um 25 --frames 3 --settle-ms 10

# Real Ludl/PVCAM, already-loaded tested mixed configuration; MMStudio Live off.
04_code/ix83_acquisition/.venv-integration/Scripts/python.exe `
  04_code/sample_search/scan.py --backend pycromanager --allow-real `
  --rows 2 --columns 3 --step-x-um 25 --step-y-um 25 --settle-ms 10
```

The real binding verifies the device inventory, COM22 controller, Core roles,
idle camera queue and absent automatic shutter binding before commands.
Movement waits and readbacks come from the stage adapter; optional extra settling
is specified in milliseconds. Z is held fixed, using the loaded demo focus role.
No illumination, objective, channel, ROI or binning switching is implemented.
The prior exposure is restored after camera cleanup.

For a secondary pass, supply a JSON list in absolute stage micrometres:

```json
[
  {"position_id": "target-1", "x_um": 10.0, "y_um": 15.0},
  {"position_id": "target-2", "x_um": 20.0, "y_um": 25.0}
]
```

```powershell
04_code/ix83_acquisition/.venv-integration/Scripts/python.exe `
  04_code/sample_search/scan.py --targets targets.json --frames 20
```

This example defaults to mocks. Add the real binding flags only when the listed
positions are intended for the physical stage. Calibrated image detections should
use the existing sample-search/review runner to produce physical targets;
the stage scanner does not interpret legacy CAM commands or image pixel offsets.

Each run gets a new output folder. `scan.json` records the resolved plan/settings,
request IDs, intent before commands, readbacks, raw dataset references, outcomes
and any recorded prefix. One-frame captures use checksummed NPY recording;
movies use the existing bounded concurrent OME recorder. The command verifies
all saved frame checksums and counts. `cleanup.json` records cleanup/readback and
camera setting restoration in the current command implementation.

Ctrl+C requests cancellation between commands and during extra settling.
An already active finite acquisition must finish or reach its deadline before
ownership can be released. Successful/cancelled scans return to the recorded
origin when outcomes are known. Failed/uncertain scans retain their position and
never automatically retry or return; consult the journal and reconcile hardware.
Journals do not implement automatic restart or exactly-once physical recovery.

Validation on 2026-10-04: six mock positions saved all 18 requested movie frames;
the real column-major 50 x 25 um scan saved and checksum-verified six camera frames
and returned within the 0.5 um readback tolerance. The real journal is local
`04_code/sample_search/recordings/scan-1791141072216763100/scan.json`.
The combined library/host/acquisition suite passes 114 tests after the import-boundary refactor. This is
mechanical procedure evidence; calibrated specimen recall remains pending.
