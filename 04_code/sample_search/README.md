# IX83 sample-search execution host

This bundle-owned source tree imports the pure [scan library](../../03_external/sample_search/README.md).
`ix83_search_host` owns the serial search/scan runners, phase transitions, deadlines,
cancellation and action journaling. `IX83SearchExecutor` owns actual camera/stage
calls, resource ownership, limits and NPY/OME recording. The selected real binding
uses Pycro-Manager/MMCore. Importing either module opens no hardware connection.

The library publishes `WorkflowRecipe` and `StageScanRecipe` descriptors and pure
geometry/detection/review calculations; it imports no IX83, RedSun or RTASPT host.
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
The library does not orchestrate the flow; a future parallel RedSun host may
import the same recipe/calculation contracts through its own execution adapter.
PV/IOC publishing and RTASPT live-view attachment remain future integrations.
