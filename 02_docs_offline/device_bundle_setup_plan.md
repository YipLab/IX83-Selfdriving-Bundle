# IX83-Automation device bundle setup plan

## Authority and status

IX83-Automation is the instrument integration project; IX83-Selfdriving-Bundle is the current checkout name. The primary architecture reference is RTASPT's [sample-search workflow research](../03_external/Realtime-Anisotropy-SPT-Analysis/docs/sample-search-workflow-research.md), especially sections 7-15. It proposes an architecture and verification cases, not completed implementations.

External documentation audit: 2026-10-04, RTASPT checkout commit `56a09dd487fc48e267f88605470fea74d54597dd`. This records the inspected checkout, not a tested release or a changed submodule pin. Supporting references are its [architecture](../03_external/Realtime-Anisotropy-SPT-Analysis/docs/architecture.md), [input contracts](../03_external/Realtime-Anisotropy-SPT-Analysis/docs/data-input-contracts.md) and [live workflow](../03_external/Realtime-Anisotropy-SPT-Analysis/docs/live-acquisition.md).

**Existing artifacts:** numbered directories, module descriptions, optical schematic, Micro-Manager profiles, shutter firmware and auxiliary scripts. Their presence does not establish current-PC hardware acceptance.

**Planned:** backend-independent workflow integration, bundle-owned execution, versioned profiles/calibration, mock/replay verification and supervised hardware acceptance. RTASPT's package extraction and source-independent live processing remain future work.

**Deferred:** arbitrary concurrent graphs, distributed scheduling, continuous stage scanning, periodic event search, deep-model/optimizer dependencies and LLM integration until a verification case requires them.

**Non-goals for this setup:** driver installation, hardware access, firmware flashing, external-code or pin changes, and adoption of the reference project's robotic holotomography architecture.

## Repository map

| Directory | Responsibility |
| --- | --- |
| 01_docs_public/ | Shareable instrument and user documentation |
| 02_docs_offline/ | Internal plans and developer-maintained offline hardware snapshot |
| 03_external/ | Independently owned software checkouts/submodules |
| 04_code/ | Instrument-specific profiles, firmware and auxiliary scripts |
| 05_simulations/ | Local simulation/replay work; currently ignored by Git |
| 06_module_description/ | Optical modules, drawings and calibration procedures |
| 07_experiment_notebook/ | Experiment records; exclude secrets and large raw datasets |
| 08_session_logs/, 09_commit_logs/ | Local archives, created as needed and ignored by Git |

## Three-layer architecture

1. **Reusable workflow layer (planned):** recipe state, typed observations, decisions and action proposals. Core logic does not require RTASPT, Redsun, Pycro-Manager or a UI. Begin with a serial state machine, declared resources, bounded conditions/deadlines and cancel/finalize behavior. Naming and repository location remain open.
2. **Reusable processing (RTASPT):** reconstruction, calibration, anisotropy, tracking and structural analysis. Processing reports observations, not device commands. Current acquisition/controller code remains in RTASPT during migration; do not describe extraction as complete.
3. **IX83 device integration (planned composition):** backend bindings, profiles, frontend coordination, execution policy, resource arbitration, physical limits, hardware calls and acceptance records. Scripts, GUIs and future agents use the same executor.

Redsun is the research note's leading integration candidate; Pycro-Manager remains an intended deployment path and is used by RTASPT's existing optional live workflow. The first real adapter, supported versions and persistence format require inspection and tests before selection. Bluesky Adaptive is optional, not the workflow core's type authority.

Keep recipes, skills and runs distinct. A recipe manifest declares typed parameters and units, capabilities, preconditions, resources, physical effects, outputs, completion/failure conditions and versioned validation evidence. Skills expose guidance; runs record resolved parameters, bindings, decisions and outcomes.

## Data, timing and recovery contracts

Use YXPlane/IterablePlaneInput for sequential data and ArrayBlockInput for random access where supported. Current RTASPT reconstruction still includes ndarray and TIFF-page consumers, and its live controller has not been converted to generic plane-source ingestion.

Carry experiment/dataset/target IDs, phase, channel/polarization, Z position/index, axes, timestamps and calibration. Preserve sequence versus time-coordinate semantics, explicit missing-frame behavior and polarization pairing. Reset tracking at declared target boundaries; link survey/full datasets separately when shapes or dtypes differ.

Preserve acquisition and processing/publication times separately. Conditions need freshness/validity, sufficient support, persistence windows, timeout and missing-data behavior; delayed measurements must not affect unrelated targets or later phases. Simulation uses an injectable clock.

Record proposed, accepted, started, completed, failed, cancelled and outcome-unknown actions with request IDs, policy/recipe versions, decision reasons, data references and available readbacks. Recovery depends on action semantics: a timeout after delivery may require reconciliation rather than a second dose. Do not promise exactly-once physical execution or universal rollback. Backend timing and capability gaps must be explicit.

## First recipe and acceptance gate

**Planned first recipe:** same-objective two-pass sample search, using settled step-and-snap acquisition and fixed Z initially. Complete a rectangular, overlapping, deterministic serpentine survey; detect candidates; map image positions through calibrated scale/rotation/reflection/axis exchange/binning/ROI offsets; deduplicate in physical space; bounds-check and limit targets; optionally review; revisit with the full recipe; pass full datasets to RTASPT.

Verify on a seeded, stage-aware specimen with a 4 x 3 overlapping grid. Survey and full images must come from the same physical specimen, including overlap duplicates, a seam object, a dim object, a blank tile and an out-of-region object. A generic camera demo alone is insufficient.

Acceptance requires coverage without unintended gaps, correct transformed coordinates, duplicates merged without collapsing nearby distinct objects, revisits within a declared centring tolerance, correct settings order, distinct empty/failure/missing/cancelled outcomes and replay reproducing decisions without acquiring again. Record chosen overlap, detector assumptions and tolerances before testing. Simulation success is not specimen validation.

**Planned second recipe:** baseline acquisition, validated baseline, configured perfusion request/outcome, explicit arrival/mixing criterion, anisotropy monitoring and sustained-response/timeout transition. Pump completion is not reagent arrival; chamber-wide resource and specimen state must be explicit. Hardware and response criteria remain undecided.

## Setup phases

1. **Documentation baseline (this task):** project identity, ownership, setup plan and synchronized diagram. Gate: documentation validation and preserved hardware/external source.
2. **Offline environment (planned):** inventory external Git registration, exact pins/worktree status and dependencies; document reproducible setup in the owning software repository. Gate: hardware-free processing and mock execution. The current outer Git status reports 03_external/ as untracked; this task does not repair registration or stage it.
3. **Workflow verification (planned):** implement contracts/runner in the chosen owning repository and exercise the first recipe's simulation/replay acceptance case. Gate: recorded evidence for a specific version and operating envelope.
4. **Profile and supervised device acceptance (planned):** review existing profiles/firmware against the developer's [hardware snapshot](hardware_devices_available_to_agents.md), then obtain separate hardware authorization. Verify identity, limits, shutter-off state, applicable watchdog/interlocks and cleanup before testing one device alongside mocks and a stable fluorescent specimen. Measure recall, revisit error, duration and data volume.
5. **Release record (planned):** record exact tested software commits, firmware checksums, profile revisions, hardware configuration and calibration IDs. Pin changes and publication require their own authorization.

See the [architecture flowchart](architecture_flowchart.md). This plan does not authorize connecting to hardware or modifying the developer-maintained snapshot.
