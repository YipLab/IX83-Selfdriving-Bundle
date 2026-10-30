# IX83-Automation

Device bundle and instrument integration record for the modular IX83 microscope. The current checkout name is IX83-Selfdriving-Bundle.

The current hardware set is tracked as **`ix71-system`**, a temporary identifier for this host and its different devices. The [ix71 system setup plan](02_docs_offline/ix71_system_bundle_setup_plan.md) records the hardware cross-check, the disabled IX83 services, the new serial ASI XY stage and the open acceptance gates. The [IX83 setup plan](02_docs_offline/device_bundle_setup_plan.md) remains the historical record and the owner of reusable application decisions. The developer-maintained [hardware snapshot](02_docs_offline/hardware_devices_available_to_agents.md) remains authoritative for available and unavailable devices.

Browse the [session evidence index](08_session_logs/README.md) for run and validation records and the [experiment notebook index](07_experiment_notebook/README.md) for reusable analyses and methods.

The [implementation backlog](02_docs_offline/redsun_rtaspt_integration_next_steps.md#manuscript-driven-implementation-increment-2026-10-27) now maps the manuscript's expected outputs to evidence recovery, causal timing/pose records, onset-policy integration, calibrated reconstruction/tracking and matched acquisition comparisons. The [work packages](02_docs_offline/Stage_Scanning_TIRF_Implementation_Work_Packages.md#manuscript-to-implementation-update-2026-10-27) specify owners and deliverables; the stationary-sample rehearsal remains the leading instrument gate.

The [AOTF calibration module](04_code/aotf_calibration/README.md) prepares isolated
zero-order frequency/power sweeps using MDSnC and PM100USB/S120C. The current
hardware trial is 488 nm with externally controlled illumination; synthetic
and optional MMCore engine support covers additional lines. It has a
[Redsun transfer contract](04_code/aotf_calibration/REDSUN_TRANSFER.md).
Simulation and optional adapters are implemented; physical
calibration and transport acceptance remain pending.

Start with the [setup plan](02_docs_offline/device_bundle_setup_plan.md), [Python environment inventory](02_docs_offline/python_environment_inventory.md), [architecture flowchart](02_docs_offline/architecture_flowchart.md) and [contributor conventions](AGENTS.md). The primary acquisition foundation is [`redsun-searching-is-imaging`](03_external/redsun-searching-is-imaging/README.md), derived from redsun-mimir's recorded main/release baseline and retaining applicable architecture and feature parity. Bounded IX83 snap/broom composition and stage/camera bindings are implemented; generalized recipe preflight and calibrated acceptance remain planned; serial optics control is prepared but not physically accepted. `ix83_acquisition` is the temporary compatibility and qualification path. The bundle-owned [sample search workflow research](02_docs_offline/sample_search_workflow_research.md) remains supporting research for reusable workflows, reusable processing and one runtime-owned execution policy. The app imports its locked local `redsun-planner` dependency through snap/broom adapters and Presenter plan-map entries; generalized recipe preflight and calibrated physical acceptance remain planned. The Redsun app now contains a hardware-free MAC6000 binary codec, position/status and raw-count move clients, explicit calibration transforms, a bounded ±2 mm startup-relative XY facade, and an opt-in registered FastCS/PVAccess service over OxiSerial. Idle event handling and fake-peer spawned-PVA scan integration are implemented; physical scale, binary module/axis mapping, timed-report behavior and native hardware acceptance remain pending. A standalone checkout also needs the sibling planner source until an independent distribution is released. The [local acquisition package](04_code/ix83_acquisition/README.md) provides camera/XYZ-stage interfaces, stage-aware mocks, free run, finite acquisition and cancellation. Its locked Pycro-Manager client matches server protocol 5.1.0; mock and demo ZMQ checks pass. Reusable sample-search source is packaged as `redsun-planner`; `ix83_acquisition` builds and imports its local wheel through the project lock. Snap and flyer-based push-broom Bluesky plans pass simulated RunEngine tests. Redsun remains the first-class run-host target; the bundle owns a temporary Pycro-Manager adapter and IX83 execution code. Seeded search and saved-review validation pass. The first IX83 recipe is specified around operator-confirmed well corners, relative body focus-lock, temporal-median per-channel maps, Otsu intensity scoring and paired-channel detail suggestions; those recipe-specific integrations remain planned. Calibrated specimen acceptance remains pending.

The Redsun bundle now includes direct-serial laser controls adapted from the original BeanShell UI and the Arduino shutter firmware/service. The current operator-supplied laser map is 405→COM12, 488→COM6, 561→COM10 and fourth channel `670`→COM9; COM5 is the shutter Arduino. The 561 command dialect and operator-observed shutter travel have limited evidence; other heads, installed shutter firmware/wiring, interlocks and Redsun-managed optical acceptance remain pending. See the [migration record](02_docs_offline/ix83_laser_shutter_migration.md).

The 2026-10-17 supervised Redsun sequence passed a PVCAM-only one-frame snap and a separate 50 µm 2×2 physical Ludl snake using DemoCamera. The camera frame, intensity plot, readbacks, stage path plot and position ledger are recorded under [physical Redsun rehearsal](08_session_logs/20261017T_physical_redsun_rehearsal/README.md). A later combined PVCAM/Ludl 15x15 scan saved 225 frames, with 214 registered tiles; calibrated specimen acceptance and Redsun-managed laser/shutter operation remain pending; operator-supplied laser ports are recorded, while command dialects, head identity, shutter firmware/wiring and stop/interlock checks remain unverified.

The numbered directories contain public/offline documentation, external software, instrument code, local simulations, module descriptions and experiment notebooks. The local package records/replays raw frames and supplies recorded planes to RTASPT. Its former CLI/GUI/MDA backend-factory integration and mock exposure-refresh checks are historical: RTASPT removed that acquisition frontend on 2026-10-17. Reusable processing remains in [Realtime-Anisotropy-SPT-Analysis](03_external/Realtime-Anisotropy-SPT-Analysis/docs/architecture.md); its package extraction is planned. The operator-loaded [mixed Ludl/PVCAM configuration](04_code/02_mmcfg/ix83_mixed_ludl_pvcam_mmconfig.cfg) passed a limited camera/control smoke test with demo Z and 25/100 um XY moves; calibrated optical and broader hardware acceptance remain pending.

The [camera throughput validation](02_docs_offline/camera_throughput_validation.md) now verifies native acquisition with concurrent OME BigTIFF recording at 50 ms exposure: all 600 frames were saved at 19.99 fps with exact pixel replay, no overflow and no hardware-ID gaps. The local acquisition CLI defaults to 50 ms; cancellation preserves the captured prefix. Longer recording and simultaneous processing/GUI load remain to be measured.

The [scanning development evidence](07_experiment_notebook/2026-10-14_scanning_workflow_evidence/README.md) includes biological replay/virtual integration, intensity-based speed curves, confirmed two/four-corner geometry and DemoCamera snake/broom workflows. The [two-corner mixed Ludl/DemoCamera run](08_session_logs/20261015T072614Z_mixed_ludl_demo_snake/README.md) completed a bounded 9-position snake snap-scan and 3-strip broom step emulation. A later [four-corner polygon run](08_session_logs/20261015T074025Z_mixed_ludl_demo_snake/README.md) completed 13 snap positions and 24 broom-emulation frames with frame/ledger hashes and path plots. Broom remains emulated; calibrated continuous motion and live speed control remain planned. Snap-scan is the benchmark, denser 2×-binned bead calibration is next, and perfusion is deferred.

The reusable [`redsun-planner` library](03_external/sample_search/README.md) provides recipe descriptors, plans, calculations, review metadata and hardware-free records. IX83/Pycro-Manager execution belongs under `04_code/ix83_acquisition/`; its scan host imports the built planner distribution and keeps replay/mock checks separate from real mechanical scanning. The checkpoint [review CLI](04_code/ix83_acquisition/scripts/scan_workflow/review_cli.py) opens the saved survey coverage/image page without hardware access. Split-detector calibration, channel-group MDA orchestration and the recipe-specific survey-map GUI remain planned.

## Existing optical system record

This section is the retained IX83 optical-system record. The current `ix71-system` hardware differences, disabled services and open acceptance gates are in the [ix71 setup plan](02_docs_offline/ix71_system_bundle_setup_plan.md); the 60× objective line below records the current system magnification.

Modules enable different microscopy techniques to be applied on the same optical system. Modules are inserted into designated modular spaces the IX83 system. Detailed description of the modules can be found in their respective folders.


![System Schematic](images/schematic.png)


The system has 4 free spaced lasers that are aligned using a laser combiner. The beam profile can be manipulated in to modular exciation areas(Mod_Ex). The beam is then expanded and focused to the back focal plane of the objective.

There are two modular emission areas(Mod_Em), this permits image manipulation before it is acquired by the camera. Mod_Em1 is the second deck in a dual deck IX83 microscope body. The second is space between the microscope body and the camera.

## Components

### Lasers
405 Laser | Coherent Cube 405 nm 25 mW
488 Laser | Coherent Sapphire 488 nm 200 mW
561 Laser | Laser Quantum GEM 561 nm 200 mW
647 Laser | Coherent OBIS 637 nm 160 mW

### Optics
L1 | Achromatic Doublet f = 30 mm ([AC254-030-A-ML](https://www.thorlabs.com/thorproduct.cfm?partnumber=AC254-030-A-ML))
L2 | Achromatic Doublet f = 250 mm ([AC254-250-A-ML](https://www.thorlabs.com/thorproduct.cfm?partnumber=AC254-250-A-ML))
L3 | Achromatic Doublet f = 300 mm ([AC254-300-A-ML](https://www.thorlabs.com/thorproduct.cfm?partnumber=AC254-300-A-ML))
IX83 | Olympus IX83 Dual Deck

### Objectives
5x | Olympus LMPlanFLN 5x/0.13
10x | Olympus UPlanFl 10x/0.30
20x | Olympus LCPlanFl 20x/0.40
40x | Olympus LCPlanFl 40x/0.60
60x | Olympus PlanApo 60x/1.4 Oil — current ix71 objective. Sampling is 0.18333 µm/px (11 µm camera pixel at 60×, 5.455 px/µm); the AmScope MR095 reticle measured 0.1823–0.1829 µm/px directly, so reticle and optics agree and there is no magnification deviation
<!-- Prior IX83 canonical objective: Olympus UAPO N 100×/1.49 Oil — system magnification 1.0 -->

### Magnification
Sampling | 0.18333 µm/px (5.455 px/µm) — 11 µm camera pixels at 60×. The MR095 reticle measured 0.1823–0.1829 µm/px directly and is the authority. Readings near 0.092 µm/px were computed against stage travel that a doubled conversion reported at twice the physical move; the conversion is 5.0 (a 1 µm step series reports 7.76 µm against a reticle-true 8.30 µm, ratio 1.07). The fit is in the [ix71 optical scale notebook](07_experiment_notebook/2026-10-23_ix71_optical_scale/README.md).

### Filter Cube
Quad band | Chroma ([TRF89901-EMv2-OL3](https://www.chroma.com/products/sets/trf89901-emv2-et-405-488-561-640nm-laser-quad-band-set-for-tirf-applications))

### Camera
CAM | Photometrics Prime BSI sCMOS (IX83 record)
ix71 | PVCAM Camera-1, GS144BSI, 1200 × 1200, 11 µm pixels, 12-bit — online 2026-10-23 at 10 ms; stationary and 2×2 captures succeeded. Sampling is 0.18333 µm/px (11 µm at 60×), confirmed by the MR095 reticle at 0.1823–0.1829 µm/px; no magnification deviation.

### Software
The legacy module record lists Micro-Manager 2.0.3. The canonical MMCore adapter bundle on the ix71 host is `Micro-Manager_2.0.3_20260821` (Device Interface 75). Current Redsun adapter selection and compatibility evidence are recorded in the [environment inventory](02_docs_offline/python_environment_inventory.md) and the [ix71 setup plan](02_docs_offline/ix71_system_bundle_setup_plan.md); RTASPT owns processing and offline review, with its former camera workflow removed.

The ix71 stage is a native serial ASI MS2000/LX4000 XY device on COM5 at 115200 8N1. The IX83 Ludl stage and IX83 optics/Arduino-shutter services are retained in code but are not declared by the ix71 profile. The first authorized ±100 µm ASI run and a four-frame DemoCamera 2×2 snap are recorded in the [ix71 ASI motion session](08_session_logs/20261022T_ix71_asi_motion_01/README.md). The 2026-10-23 anti-backlash work then measured a ~4.5 µm reversal dead band, excluded sample drift with 0 px stationary controls, and selected **`2HB` 0.016 mm**: full step travel on both axes (98–99 %), 1–2 µm moves still proportional, and a 5 × 5 snake grid at 102 % per move including row-end reversals. The ASI service applies and keeps that value and both ix71 profiles set it ([trial](08_session_logs/20261023T_ix71_backlash_trial_02/README.md), [acceptance](08_session_logs/20261023T_asi_service_acceptance_01/README.md)). A headless full application session (spawned PVCAM and ASI services over PVA, planner snap-grid plan, Zarr storage) then completed a 5 × 5 scan at 25/25 frames twice, returning to the anchor and keeping the backlash ([first run](08_session_logs/20261023T_ix71_full_session_5x5/README.md), [repeat and content check](08_session_logs/20261023T_ix71_full_session_repeat_01/README.md)). Absolute stage scale against an independent reference, the registration-density decision on those stacks, and a bounded free-run camera cadence with exposure-start timing remain open.
