# Ludl motion diagnostic host

`ix83_acquisition.scan_host.ludl_motion.LudlMotionHost` is a local, bounded diagnostic for an already constructed Pycro-Manager Core. Importing the module does not connect to Micro-Manager. The caller owns Core construction and must choose the operator-loaded `ix83_ludl_democam_mmconfig.cfg` profile.

The host accepts only the expected COM22/Ludl XY and DemoCamera inventory, XY and focus roles, disabled automatic shutter, and an idle camera. It captures an immutable XY anchor and fixes Z at its initial readback. Supply `expected_origin_xy_um=(x, y)` to require the separately recorded task anchor. By default, initial XY must match that anchor within tolerance. A supervised continuation can set `allow_displaced_start=True`; this requires an expected origin and keeps the ±2000 µm envelope centered on that origin while allowing the current readback anywhere inside it. Every target must be finite and inside that immutable envelope. Before each new move or pre-move property change, the host rechecks profile and fixed Z, then requires an idle, stable XY readback. It never commands Z, homes, jogs, retries, returns to origin, changes serial timeouts, or owns Core lifecycle.

## Minimal use

```python
host = LudlMotionHost(
    caller_owned_core,
    output_dir / "actions.jsonl",
    run_context={"run_id": run_id, "profile_revision": profile_hash},
    expected_origin_xy_um=(57901.0, -16256.9),
)
handle = host.start_move(target_x_um, target_y_um, timeout_s=20)
result = host.wait(handle, cancelled=lambda: cancel_requested)
```

`start_move` validates bounds before issuing `core.set_xy_position(x, y)` and returns after command acknowledgement; it does not call a device wait. `wait` polls `device_busy("XYStage")` and actual X/Y readbacks. Each successful motion poll now appends a typed `stage_position_sample` line to the same JSONL journal, with a request/sequence event ID, XY values in µm, source `controller_readback`, host UTC, monotonic X and Y call intervals, their encompassing sample bracket, Busy call interval, and reported Busy state. The default sample cadence is 50 ms. X and Y are read sequentially; `host_monotonic_midpoint_estimate_ns` is a host estimate inside the recorded bracket, not a simultaneous read or hardware timestamp. Busy is queried afterward and has its own interval. Samples are not associated with camera exposures and do not provide a shared camera/stage clock. They can support coarse offline motion analysis; do not treat them as exposure-synchronous positions or compute stage acceleration without accounting for polling, serial latency, quantization and settling. If writing a position record fails during motion, the host attempts `Core.stop("XYStage")`, marks the result outcome unknown, and blocks further actions until read-only `reconcile()` establishes stable idle state.

Since the Ludl driver may report Busy false after serial status errors, false-busy observations remain pending while position changes. Completion requires Busy false, target tolerance, and at least 0.3 s of stable position. A stable false-busy position outside target tolerance becomes `outcome_unknown` and blocks new moves. Reconciliation requires valid positions that stay stable for at least 0.3 s with Busy false; a reconciliation timeout raises and preserves the lock. The deadline begins before command submission, including acknowledgement time. Results include command acknowledgement latency and UTC/monotonic start, acknowledgement, and finish timestamps.

On cancellation or deadline, the host calls `core.stop("XYStage")` once, then polls busy state and position for bounded stable reconciliation. Stop lifecycle is journaled separately. A result whose physical outcome remains uncertain blocks subsequent motion until `reconcile()` obtains a stable idle readback. `reconcile()` never sends commands; the caller decides whether the observed position permits continuing.

## Motion properties

The host records initial XYStage `Speed`, `StartSpeed`, and `Acceleration`. At a pre-move gate, `set_motion_properties(speed=..., start_speed=..., accel=...)` validates positive speed values and integer acceleration 1–255, consults device limits only when the driver reports them, writes the driver properties, and checks the readbacks. `motion_property_relative_tolerance` defaults to exact matching and accepts values from 0 through 0.05; it applies only to Speed and StartSpeed. Acceleration remains exact. The journal records requested values, actual readbacks, and the configured tolerance. If property limits are unavailable, the host does not invent a numeric speed cap. These are driver property values; this interface does not assign physical units to them. An explicit `allow_in_motion_speed_update=True` host capability is required for `set_motion_properties(speed=..., gate="in_motion")`; an in-motion update can write Speed only. Property updates are journaled.

The append-only JSONL journal starts with run context, profile identity, origin, fixed Z and envelope. Action records carry request IDs, lifecycle state, timestamps, parameters, errors and available readbacks. A journal is not automatic recovery evidence and an uncertain move must be reconciled by an operator-run procedure.

This module does not initialize devices, select a profile, start acquisition, open a shutter or establish calibrated specimen safety. Hardware operation remains a separate explicitly authorized and supervised activity.

