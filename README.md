# IX83-Automation

Device bundle and instrument integration record for the modular IX83 microscope. The current checkout name is IX83-Selfdriving-Bundle.

Start with the [setup plan](02_docs_offline/device_bundle_setup_plan.md), [architecture flowchart](02_docs_offline/architecture_flowchart.md) and [contributor conventions](AGENTS.md). The overall architecture follows RTASPT's [sample-search workflow research](03_external/Realtime-Anisotropy-SPT-Analysis/docs/sample-search-workflow-research.md): reusable workflows, reusable processing and bundle-owned execution. Two-pass sample search is the first planned validation recipe; implementation and hardware acceptance remain future work.

The numbered directories contain public/offline documentation, external software, instrument code, local simulations, module descriptions and experiment notebooks. Reusable processing remains in [Realtime-Anisotropy-SPT-Analysis](03_external/Realtime-Anisotropy-SPT-Analysis/docs/architecture.md); its package extraction is planned.

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

