# IX83-Automation architecture flowchart

This planned composition follows the [setup plan](device_bundle_setup_plan.md) and RTASPT's [sample-search workflow research](../03_external/Realtime-Anisotropy-SPT-Analysis/docs/sample-search-workflow-research.md). Workflow packaging, executor implementation and RTASPT extraction are not claimed complete.

```mermaid
%%{init: {"theme": "base", "themeVariables": {"fontSize": "22px"}, "themeCSS": ".nodeLabel { font-size: 22px; } .cluster-label .nodeLabel { font-size: 22px; } .edgeLabel { font-size: 17px; }"}}%%
flowchart TB
    subgraph WORKFLOW["Reusable workflow layer ? planned"]
        observations["Typed observations<br/>target, phase, time, quality"]
        recipe["Recipe state and decision policy<br/>serial runner, deadlines"]
        proposals["Action proposals<br/>capabilities and resources"]
        observations --> recipe --> proposals
    end
    callers["Script, GUI or future agent"] --> recipe
    subgraph BUNDLE["IX83-Automation ? device integration"]
        profiles["Profiles, firmware and calibration<br/>existing artifacts, acceptance planned"]
        executor["Executor ? planned<br/>safety, limits, resource arbitration"]
        backend["Acquisition backend binding<br/>first adapter selection pending"]
        ledger["Run and action ledger ? planned<br/>outcomes, readbacks, provenance"]
        profiles -. binding references .-> executor
        executor --> backend
        executor --> ledger
    end
    proposals --> executor
    hardware["IX83 devices<br/>separately authorized access"]
    backend -->|authorized commands| hardware
    hardware -->|images and telemetry| backend
    inputs["Acquisition context and inputs<br/>axes, coordinates, calibration IDs"]
    backend --> inputs
    replay["Stage-aware simulation and replay<br/>planned first verification"] --> inputs
    processing["RTASPT processing<br/>reconstruction, anisotropy, tracking"]
    inputs -->|consumer-supported data contracts| processing
    processing --> observations
    backend -->|execution observations| observations
    storage["Data and result references<br/>persistence selection pending"]
    inputs --> storage
    processing --> storage
    ledger --> storage
```

First planned verification: same-objective survey, calibrated detection, physical-coordinate deduplication and selection, then full acquisition of selected targets and RTASPT processing. Baseline/perfusion/anisotropy is the second proposed reference recipe.

Processing reports observations; the bundle executor owns physical commands. The existing RTASPT live workflow uses Micro-Manager/Pycro-Manager and napari with exclusive camera ownership. Generic input adapters exist, but ndarray/TIFF consumers and the current live controller retain their documented limitations.
