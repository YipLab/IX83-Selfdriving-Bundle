# IX83 sample-search execution host

This bundle-owned source tree imports the pure [scan library](../../03_external/sample_search/README.md).
`ix83_search_host` owns typed execution requests/results, serial runner transitions,
deadlines, cancellation and action journaling. `IX83SearchExecutor` owns camera/stage
calls, declared binding capabilities, resource ownership, limits and NPY/OME recording.
Both sample-search and scan runners preflight their exclusive stage, camera and storage
requirements, supported settings and operations before issuing commands. They persist
the same typed `ActionRecord` events for proposal, acceptance, start and outcome.
Run snapshots also record the adapter provider and declared capabilities, resources
and settings.
Local launchers share one temporary source-tree bootstrap in `source_bootstrap.py`;
replace it with editable package dependencies when package ownership and metadata settle.
Real executor-backed search runs require a durable JSONL action journal. Importing
either module opens no hardware connection.

The library publishes `WorkflowRecipe` and `StageScanRecipe` descriptors and pure
geometry/detection/review calculations; it imports no IX83, RedSun or RTASPT host.
Survey images declare uppercase `YX` axes. Recorded datasets use typed references
with storage format, named axes, shape, dtype, verified count, terminal state and
manifest checksum. Survey/revisit and explicit scans use the same host-side dataset
validator; version 1 checkpoints are verified before legacy-axis conversion.
The file-storage adapter verifies the typed reference's manifest digest before replay;
the NPY/OME readers then validate the frame ledger and raw pixel checksums.
The host resolves the current instrument origin, imports `build_grid_recipe`, and
interprets the resulting recipe under its own limits and cleanup policy.

```python
from samplescout import AcquisitionSettings, build_grid_recipe
from ix83_search_host import StageScanRunner

recipe = build_grid_recipe(origin_xy_um, specimen_id="specimen-1", rows=2,
                          columns=3, step_xy_um=(25, 25),
                          settings=AcquisitionSettings(exposure_ms=50, frames=3))
host = StageScanRunner(executor, limits_xy_um=limits_xy_um,
                      fixed_z_um=fixed_z_um, origin_xy_um=origin_xy_um,
                      journal="scan.json")
result = host.run_recipe(recipe)
```

Use the existing acquisition integration environment. No scan-library distribution
metadata or new environment is required for this local prototype:

```powershell
$env:PYTHONPATH = '03_external/sample_search;04_code/sample_search'
04_code/ix83_acquisition/.venv-integration/Scripts/python.exe `
  -m pytest 03_external/sample_search/tests 04_code/sample_search/tests `
  04_code/ix83_acquisition/tests -q
04_code/ix83_acquisition/.venv-integration/Scripts/python.exe `
  04_code/sample_search/scan.py --frames 3
Remove-Item Env:PYTHONPATH
```

See [scan usage](../../03_external/sample_search/docs/scanning_usage.md) for real
device selection and target lists. This CLI is an acquisition-host launcher.
The library does not orchestrate the flow. Typed host requests and results now define
the bundle execution seam; a future RedSun host can bind those recipe/data contracts
through its own adapter while keeping one command authority.
PV/IOC publishing and RTASPT live-view attachment remain future integrations.
