# IX83-Automation

Device bundle and instrument integration record for the modular IX83 microscope. The current checkout name is IX83-Selfdriving-Bundle.

Start with the [setup plan](02_docs_offline/device_bundle_setup_plan.md), [architecture flowchart](02_docs_offline/architecture_flowchart.md) and [contributor conventions](AGENTS.md). The overall architecture follows RTASPT's [sample-search workflow research](03_external/Realtime-Anisotropy-SPT-Analysis/docs/sample-search-workflow-research.md): reusable workflows, reusable processing and one runtime-owned execution policy. The [local acquisition package](04_code/ix83_acquisition/README.md) now provides camera/XYZ-stage interfaces, stage-aware mocks, free run, finite acquisition and cancellation. Its locked Pycro-Manager client matches server protocol 5.1.0; mock and demo ZMQ checks pass. The sample-search library publishes reusable descriptors, calculations and records, while the bundle host owns runner transitions and device execution; seeded and mock validation passed. The first IX83 recipe is specified around operator-confirmed well corners, relative body focus-lock, temporal-median per-channel maps, Otsu intensity scoring and paired-channel detail suggestions; those recipe-specific integrations remain planned. A prospective RedSun composition would give its RunEngine the sole execution authority and import the same framework-neutral workflow/processing contracts; package/process placement is still a design question, and calibrated specimen acceptance remains pending.

The numbered directories contain public/offline documentation, external software, instrument code, local simulations, module descriptions and experiment notebooks. The local package records/replays raw frames and supplies an optional backend to RTASPT CLI/GUI/MDA, with actual mock controller and exposure-refresh checks passing on Python 3.12. Reusable processing remains in [Realtime-Anisotropy-SPT-Analysis](03_external/Realtime-Anisotropy-SPT-Analysis/docs/architecture.md); its package extraction is planned. The operator-loaded [mixed Ludl/PVCAM configuration](04_code/02_mmcfg/ix83_mixed_ludl_pvcam_mmconfig.cfg) passed a limited camera/control smoke test with demo Z and 25/100 um XY moves; calibrated optical and broader hardware acceptance remain pending.

The [camera throughput validation](02_docs_offline/camera_throughput_validation.md) now verifies native acquisition with concurrent OME BigTIFF recording at 50 ms exposure: all 600 frames were saved at 19.99 fps with exact pixel replay, no overflow and no hardware-ID gaps. The local acquisition CLI defaults to 50 ms; cancellation preserves the captured prefix. Longer recording and simultaneous processing/GUI load remain to be measured.

The [sample-search library](03_external/sample_search/README.md) provides recipe descriptors, pure calculations, review metadata and hardware-free records; the IX83 runner and device execution belong to the host under `04_code/sample_search/ix83_search_host/`. Its [validation record](02_docs_offline/sample_search_validation.md) separates seeded/AutoScanJ image checks from real mechanical scanning. The checkpoint [review CLI](04_code/sample_search/review_cli.py) opens the saved survey coverage/image page without hardware access. Split-detector calibration, channel-group MDA orchestration and the recipe-specific survey-map GUI remain planned. The local prototype reuses the acquisition environment and has no distribution or repository packaging yet.

## Existing optical system record

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
60x | Olympus PlanApo 60x/1.4 Oil
100x | Olympus UApoN 100x/1.49 Oil

### Filter Cube
Quad band | Chroma ([TRF89901-EMv2-OL3](https://www.chroma.com/products/sets/trf89901-emv2-et-405-488-561-640nm-laser-quad-band-set-for-tirf-applications))

### Camera
CAM | Photometrics Prime BSI sCMOS

### Software
The legacy module record lists Micro-Manager 2.0.3 Current deployment compatibility with RTASPT's optional live workflow requires validation.

