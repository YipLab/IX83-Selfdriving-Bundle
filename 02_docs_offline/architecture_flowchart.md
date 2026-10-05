# IX83-Automation architecture flowchart

This composition follows the [setup plan](device_bundle_setup_plan.md) and RTASPT's [sample-search workflow research](../03_external/Realtime-Anisotropy-SPT-Analysis/docs/sample-search-workflow-research.md). The mock-first camera/XYZ-stage package exists at `04_code/ix83_acquisition/`; capture, XYZ movement, finite acquisition and free-run cancellation passed over demo ZMQ on 2026-10-04. RTASPT CLI/GUI/MDA backend-injection hooks now exist, with actual single-detector controller checks passing. See the plan for tested versions and compatibility limits. The `samplescout` library publishes recipe descriptors, calculations and hardware-free records; the bundle CLI/host imports those recipes and owns orchestration transitions and device execution. Seeded and recording/replay checks pass. A six-position 50 x 25 um mechanical scan passed on Pycro-Manager with checksum-verified frames and bounded return to origin; optical calibration and real-specimen targeting remain unverified. The saved-checkpoint review CLI and survey coverage GUI are implemented. The first IX83 recipe now specifies operator-confirmed well corners, IX83 body focus-lock, median channel maps and paired-channel intensity suggestions; corner capture, relative-focus binding, Otsu proposal generation, split-detector calibration and channel-group MDA remain planned. Distribution packaging and broader execution acceptance remain planned.

The planned RedSun direction is a composition alternative, not a second command authority: RedSun's RunEngine would own runs and device policy, importing the same recipe/data/processing contracts. `samplescout` remains a library; a heavy block-processing service is optional and measurement-driven. The single-channel search and stage-scan host now exchange typed execution requests/results, dataset references, declared binding capabilities and cancellation control. RedSun composition and source-path packaging cleanup remain future work.

```mermaid
%%{init: {"theme": "base", "themeVariables": {"fontSize": "22px"}, "themeCSS": ".nodeLabel { font-size: 22px; } .cluster-label .nodeLabel { font-size: 22px; } .edgeLabel { font-size: 17px; }"}}%%
flowchart TB
    subgraph WORKFLOW["Reusable workflow library (local prototype)"]
        observations["Typed observations<br/>target, phase, time, quality"]
        recipe["First IX83 recipe<br/>well localization, body focus-lock, survey, detail"]
        records["Typed run/checkpoint records<br/>serialization and replay"]
        observations --> recipe
        recipe --> records
        review["Saved survey review checkpoint<br/>HTML selection and manual additions"]
        records --> review --> records
        stitcher["Ordered image registration + mosaic<br/>phase-correlation seeded OpenCV ECC"]
        stitcher --> mosaic["Mosaic and pairwise pixel transforms<br/>split-view/stage calibration still pending"]
        medmap["Per-channel temporal median maps<br/>planned"]
        otsu["Per-channel Otsu intensity scores<br/>paired-channel suggestions planned"]
        medmap --> otsu
    end
    callers["Script, GUI or future agent"] --> cli
    frontend["RTASPT CLI and GUI controller<br/>bundle backend injection implemented"] --> backend
    subgraph BUNDLE["IX83-Automation device integration"]
        profiles["Profiles, firmware and calibration<br/>existing artifacts, acceptance planned"]
        cli["Bundle scan CLI<br/>selects mock or Pycro-Manager"]
        host["IX83 search host<br/>runner transitions, cancellation, storage"]
        seams["Typed requests, results, dataset references<br/>capabilities and execution control"]
        corners["Operator confirms 2/4 well corners<br/>wizard and start gate planned"]
        focuslock["IX83 body relative focus-lock<br/>adapter capability planned; Z-map deferred"]
        reviewcli["Bundle review CLI<br/>launches saved-checkpoint survey GUI"]
        executor["Bundle executor + acquisition controller<br/>device calls, bounded XY, fixed Z"]
        backend["Camera + XYZ interfaces<br/>mock baseline implemented"]
        pycro["Optional Pycro-Manager Core adapter<br/>client/server protocol 5.1.0 matched"]
        ledger["Run results and action ledger<br/>outcomes, readbacks, provenance"]
        profiles -. binding references .-> executor
        cli --> host --> seams --> executor
        corners -. confirmed well boundary .-> host
        host -. relative focus-lock capability .-> focuslock
        host -. after survey checkpoint .-> reviewcli
        executor --> backend
        backend -. optional live adapter .-> pycro
        executor --> ledger
    end
    subgraph FUTURE["Prospective RedSun composition (not implemented)"]
        engine["RedSun RunEngine<br/>sole run and command authority"]
        redsunadapter["RedSun host adapter<br/>maps typed execution and data contracts"]
        realtime["Imported recipe + bounded live processing<br/>framework-neutral contracts"]
        blocksvc["Optional block-processing worker / IOC<br/>typed data references and results"]
        engine -->|run plans and proposals| realtime
        engine --> redsunadapter
        engine -. measured need only .-> blocksvc
    end
    host -. imports recipe descriptors and pure calculations .-> recipe
    engine -. imports same workflow contracts .-> recipe
    redsunadapter -. binds host adapters at composition edge .-> backend
    processing -. candidate block-service boundary .-> blocksvc
    hardware["IX83 devices<br/>separately authorized access"]
    acceptance["Ludl/PVCAM smoke, 20 fps recording and<br/>six-position mechanical scan passed<br/>optical calibration pending"] -. evidence .-> hardware
    backend -->|authorized commands| hardware
    hardware -->|images and telemetry| backend
    inputs["Acquisition context and inputs<br/>axes, coordinates, calibration IDs"]
    backend --> inputs
    inputs -. future channel survey stack .-> medmap
    replay["Stage-aware simulation and replay<br/>first verification passed"] --> inputs
    processing["RTASPT processing<br/>reconstruction, anisotropy, tracking"]
    inputs -->|recorded YXPlane handoff checked| processing
    processing --> observations
    otsu -. channel intensity observations .-> observations
    inputs -. optional overlapping image sequence .-> stitcher
    backend -->|execution observations| observations
    storage["Raw NPY or OME BigTIFF + ledger<br/>checksum-validated replay implemented"]
    writequeue["Bounded OME writer queue<br/>concurrent hashing and writes"]
    executor --> writequeue --> storage
    preview["Coalesced preview<br/>old frames may be discarded"]
    executor --> preview
    inputs --> storage
    processing --> storage
    ledger --> storage
```

Implemented first verification: a seeded same-objective survey, calibrated detection, physical-coordinate deduplication and selection, then recorded target movies with RTASPT input handoff. The local library only describes recipes and provides pure calculations; the bundle CLI invokes a bundle-owned runner which interprets them under device limits and owns every physical operation. A saved-checkpoint CLI can open the existing offline map/review page, whose survey overview is coverage polygons plus tile previews. The refined first example recipe adds confirmed well corners, body focus-lock, temporal-median per-channel survey maps, Otsu metrics and split-aware paired-channel suggestions; those recipe-specific stages remain planned. The recent image-stitch utility handles ordered overlapping images in pixel coordinates and is not stage calibration. The six-position hardware scan establishes mechanical scan execution and data capture, not optical calibration or real-specimen targeting. Baseline/perfusion/anisotropy is the second proposed reference recipe.

Processing reports observations; the bundle executor owns physical commands. The existing RTASPT live workflow uses Micro-Manager/Pycro-Manager and napari with exclusive camera ownership. Generic input adapters exist, but ndarray/TIFF consumers and the current live controller retain their documented limitations.
