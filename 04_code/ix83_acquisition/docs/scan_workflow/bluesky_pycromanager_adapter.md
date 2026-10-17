# Bounded snap-plan Pycro-Manager binding

`ix83_acquisition.pycromanager_bluesky` is an optional, hardware-disconnected
binding from `planner.snap_scan_plan` to a caller-owned Pycro-Manager Core. It
does not start Micro-Manager, load a configuration, or connect on import.
Construct it only after the operator has loaded the intended profile and
stopped Live. Keep one RunEngine as the sole command authority for the run.

The snap adapter exposes one combined XY movable. Each plan target results in
one absolute `Core.set_xy_position(x_um, y_um)` call, followed by
`wait_for_device` and a checked readback. XY targets are checked against the
caller-supplied absolute bounds both before the plan and at each move. Z is
read for the associated frame but never moved by this binding. The adapter does
not set motor speed or acceleration and does not issue repeated jog commands;
those remain properties of the loaded stage/controller profile. Calls are
blocking. RunEngine cancellation cannot interrupt a Core call already in
progress, so long hardware timeouts and motion timing need separate measured
handling. If a move command or wait fails after the command may have reached
the controller, the positioner latches motion as unresolved and rejects new
moves and snaps. `reconcile()` only observes busy state and a stable in-bounds
readback; it never retries or moves the stage. Its result reports the current
position, not success at the previous target, so the run owner must decide
whether to continue.

The detector wraps `PycroManagerCamera.snap`. For each event it records the
image, adapter frame sequence, selected exposure, stage X/Y/Z readbacks made
before the snap request, host-clock intervals around each Core readback call,
and host-clock times surrounding the Core snap call and result retrieval. The
Bluesky timestamp attached to each stage value is the midpoint of that host
call interval; the raw interval remains in separate event fields. These times
are not camera hardware exposure timestamps, and the pre-snap position is not
encoder-synchronized exposure telemetry. Do not use them to claim continuous
push-broom registration accuracy.

```python
from ix83_acquisition.pycromanager_bluesky import (
    PycroManagerSnapDetector,
    PycroManagerXYPositioner,
    validate_snap_bindings,
)
from planner.plans import snap_scan_plan

stage = PycroManagerXYPositioner(
    core,
    xy_stage="XYStage",
    limits_xy_um=absolute_xy_limits_um,
    readback_tolerance_um=measured_readback_tolerance_um,
    preflight=verify_loaded_profile_and_idle_core,
)
camera = PycroManagerSnapDetector(
    core,
    stage,
    z_stage="ZStage",
    exposure_ms=10,
    shape_yx=(height, width),
    dtype="uint16",
    preflight=verify_loaded_profile_and_idle_core,
)
validate_snap_bindings(recipe, stage=stage, camera=camera)
run_engine(snap_scan_plan(recipe, stage_xy=stage, camera=camera, readables=(stage,)))
```

The acquisition `pycromanager` extra installs Ophyd. The RunEngine integration
test uses a fake Core and verifies bounds, atomic XY target order, frame data,
per-event readbacks and host-call intervals. It does not verify a loaded DemoCamera/Ludl profile or
physical motion. The binding rejects recipes that request unconfigured
channel, ROI or binning changes. Continuous capture, a Core flyer, adaptive
speed changes, exposure-synchronized stage telemetry and perfusion are outside
this snap-only binding.

```mermaid
%%{init: {"theme": "base", "themeCSS": ".nodeLabel, .cluster-label { font-size: 22px !important; } .edgeLabel { font-size: 17px !important; }"}}%%
flowchart LR
  recipe["Planner bounded snap recipe"] -->|"validated targets and settings"| preflight["IX83 binding preflight"]
  preflight -->|"one absolute XY command per target"| core["Caller-owned Pycro-Manager Core"]
  core -->|"readback, snap image, host-call times"| detector["Ophyd readable event fields"]
  detector -->|"sequence-numbered RunEngine events"| record["Notebook run record"]
```
