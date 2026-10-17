# IX83 DEMO bounded scan prototype

**Implemented for hardware-free mock runs.** An optional Pycro-Manager backend
connects to an already-running Micro-Manager instance only after explicit
`--backend devices` selection. It does not load or change a device configuration.
This prototype is not hardware acceptance evidence.

The operator supplies two opposite rectangle corners or four ordered convex
corners as confirmed XY stage readbacks. Supply them with `--corners`, or use
`--backend devices --capture-corners 2|4` to manually place the loaded Demo
stage at each corner, read its current position, and confirm each readback.
The capture option issues no stage move. `planner.bounded_scanning` plans
snake snap centers or parallel broom strips while keeping the full camera
footprint inside the polygon. It does not claim to fill polygon edges. Before
any scan command, the CLI prints the plan and requires the exact confirmation
`EXECUTE DEMO`.

## Corner input

Move the Demo stage to each selected corner using the operator's normal
procedure, record the stage readback, and confirm the observation. For a
rectangle, provide opposite corners. For a skewed boundary, provide four
corners in perimeter order (clockwise or counterclockwise):

```json
{
  "boundary_id": "demo-field-01",
  "corners": [
    {"corner_xy_um": [0, 0], "confirmed": true, "confirmation_id": "operator-2026-10-14-a", "readback_xy_um": [0, 0]},
    {"corner_xy_um": [200, 10], "confirmed": true, "confirmation_id": "operator-2026-10-14-b", "readback_xy_um": [200, 10]},
    {"corner_xy_um": [180, 160], "confirmed": true, "confirmation_id": "operator-2026-10-14-c", "readback_xy_um": [180, 160]},
    {"corner_xy_um": [-20, 140], "confirmed": true, "confirmation_id": "operator-2026-10-14-d", "readback_xy_um": [-20, 140]}
  ]
}
```

The confirmation file is operator input; the program does not move to corners
to capture readbacks in this mode. It records the supplied confirmations beside the run.
The 2-corner rectangle factory and 4-corner convex polygon factory reject
unconfirmed, non-convex, degenerate, or incomplete geometry.

## Run

Use the acquisition project's Python 3.12 environment, `.venv`:

```powershell
$env:PYTHONPATH = '04_code/ix83_acquisition/scripts/scan_workflow'
04_code/ix83_acquisition/.venv/Scripts/python.exe `
  04_code/ix83_acquisition/scripts/scan_workflow/demo_scan_workflow.py --corners corner-confirmations.json
```

Mock is the default. The DemoCamera device backend requires stopping MMStudio
Live first and using a loaded configuration where **every** device library is
`DemoCamera`, with `Camera`, `XYStage`, and `ZStage` assigned to the Core roles.
The program checks those conditions, including Live/sequence inactivity, and
never loads a config or changes shutter/illumination state:

```powershell
04_code/ix83_acquisition/.venv/Scripts/python.exe `
  04_code/ix83_acquisition/scripts/scan_workflow/demo_scan_workflow.py --corners corner-confirmations.json `
  --backend devices --mode snap --footprint-um 80 60 --overlap 0.1
```

The snap path uses the existing bundle executor and runner. It validates the
full plan against the boundary envelope before movement, keeps Z fixed, uses
exclusive camera/stage/storage resources, journals proposed/accepted/started
and terminal action records with readbacks, and stores raw frames separately
from any preview. This CLI currently has no preview stream. `scan.json` records
planned and executed positions, timestamps and typed dataset references;
`corner_confirmations.json` records the boundary evidence. Raw datasets retain
their acquisition ledger and pixel checksums.

### Broom limitation

The broom path has two emulated modes. Mock uses frames sampled along a virtual
linear path and labels output `trajectory-mock-emulation`. Demo devices use
separately commanded stage move/readback/snap samples and label output
`demo-commanded-step-emulation`. Neither mode provides continuous acquisition.
They verify bounded geometry, orchestration and raw storage, but do not verify
acceleration, velocity, trigger jitter, exposure during motion, or continuous
camera synchronization. Broom sample readbacks are checked against the
confirmed XY envelope.

Each bundle demo capture result reports `frames`, `frames_requested`, and
`capture_status`. The host rejects an explicit frame-count mismatch or
non-completed result and retains any returned readback in the action journal;
reported `cancelled` and `outcome_unknown` statuses retain those terminal
meanings. Completed `RunRecorder` manifests also require the requested and
recorded frame counts to agree. Legacy backends that omit `frames_requested`
remain unverifiable for completeness and must adopt the count field before
being treated as fully checked. Hardware-free examples are recorded in the
[failure-injection matrix](../../../../07_experiment_notebook/2026-10-14_scanning_workflow_evidence/demo_runs/failure_injection_matrix_20261015/README.md).

**Runtime correction:** a previous isolated probe used the wrong legacy
Micro-Manager installation and configuration. Its reported DemoCamera DLL/API
mismatch is superseded and is not a current blocker. The supported method is to
have the operator create and load the configuration in the intended
Micro-Manager installation, stop Live, enable the Pycro-Manager server, and
then let the workflow inspect the running Core. The verified runtime identity
and superseded probe context are recorded in the [scanning evidence notebook](../../../../07_experiment_notebook/2026-10-14_scanning_workflow_evidence/README.md).

For the **real Ludl XY + DemoCamera** profile, use the dedicated
[mixed-profile snake workflow](../../scripts/scan_workflow/mixed_ludl_demo_scan_workflow.py). It connects
only to the already-running operator-loaded Core, prompts before motion,
requires the operator to verify E-stop and travel limits, fixes Z, disables
illumination commands, and bounds every XY target to ±2000 µm from the live
starting readback. The bounded 2026-10-15 run is archived under
`08_session_logs/20261015T072614Z_mixed_ludl_demo_snake/`. Its snap path is a
real-stage benchmark with DemoCamera images; broom is commanded-step emulation,
not continuous capture. See that session's README and checksummed frame
ledgers for the exact results.

The same workflow accepts `--four-corner` to move to four ordered points inside
the bounded area, use their live readbacks as a convex polygon, and execute the
snap and broom paths over its footprint-eroded interior. The 2026-10-15 run
completed 13 snap positions and four broom-emulation strips (24 step-and-snap
frames); all XY remained within about 101 µm of the run origin, and every frame
and ledger hash passed. This verifies four-corner positioning and path execution
with DemoCamera, not optical coverage or continuous capture. Evidence is in
`08_session_logs/20261015T074025Z_mixed_ludl_demo_snake/`.

Run focused verification with:

```powershell
04_code/ix83_acquisition/.venv/Scripts/python.exe `
  -m pytest 04_code/ix83_acquisition/tests/scan_host/test_demo_scanning.py
```


