# IX83-Automation agent and contributor conventions

This is the single source of working conventions for this device bundle: documentation, configuration, firmware and integration work. Keep durable rules here; any future CLAUDE.md should point here.

IX83-Automation is the project identity; IX83-Selfdriving-Bundle is the current checkout name. This repository is the instrument and integration record, not a copy of an independently released application or processing library.

## Read first

1. [README](README.md) for the repository map and setup entry point.
2. [Device bundle setup plan](02_docs_offline/device_bundle_setup_plan.md) for authoritative instrument ownership, phases and gates.
3. RTASPT's [sample-search workflow research](03_external/Realtime-Anisotropy-SPT-Analysis/docs/sample-search-workflow-research.md) for the overall architecture: reusable workflows, processing, and bundle-owned execution. It is a research/design record, not implemented software.
4. RTASPT's [architecture](03_external/Realtime-Anisotropy-SPT-Analysis/docs/architecture.md), [input contracts](03_external/Realtime-Anisotropy-SPT-Analysis/docs/data-input-contracts.md) and [live acquisition](03_external/Realtime-Anisotropy-SPT-Analysis/docs/live-acquisition.md) for current software boundaries.
5. [Architecture flowchart](02_docs_offline/architecture_flowchart.md), relevant module descriptions in 06_module_description/ and instrument artifacts in 04_code/.
6. [Hardware availability](02_docs_offline/hardware_devices_available_to_agents.md) is a developer-maintained offline snapshot. Agents must not edit it or interpret it as authorization to contact devices.

Correct lower-priority summaries when they conflict with the owning plan. External software documentation owns claims about that software's implemented contracts.

## Project boundaries

- The bundle owns instrument profiles, wiring, firmware, calibration references, integration/front-end coordination, execution policy and acceptance evidence. Camera/XYZ acquisition belongs under `04_code/ix83_acquisition/`; the sample-search host and its device-facing runner belong under `04_code/sample_search/ix83_search_host/`.
- Begin the acquisition baseline with stage-aware camera and bounded XYZ-stage mocks. The local Pycro-Manager adapter must remain optional and hardware-disconnected until explicitly constructed.
- Reusable sample-search logic is backend independent. The source under `03_external/sample_search/` publishes recipe descriptors, geometry/calculation helpers, review metadata and hardware-free run/checkpoint records through the provisional `samplescout` import. It does not own orchestration transitions or device calls. The bundle host under `04_code/sample_search/ix83_search_host/` owns runner transitions, action execution, resource arbitration, device bindings, recording/storage coordination and cancellation. Packaging remains deferred.
- RTASPT owns reusable reconstruction, anisotropy, tracking and analysis. Its processing-package extraction and source-independent live processor remain planned.
- A listener reports typed observations or proposes actions. The bundle executor owns device calls, resource arbitration and hardware limits. Processing callbacks, scripts, GUIs and agents must use the same execution policy.
- Keep recipe (versioned executable workflow), skill (discovery/guidance metadata) and run (resolved execution record) distinct. Agent prose must not replace executable configuration.
- Start with a serial state machine and declared resources. First validate same-objective, two-pass tiled sample search; use baseline/perfusion/anisotropy as a later generalization case.
- Acquisition frameworks remain outer composition adapters. The current Pycro-Manager host and a prospective RedSun RunEngine host must bind the same framework-neutral recipe, data and processing contracts; `samplescout` and reusable RTASPT processing must not acquire a RedSun dependency.
- Standardize package imports and inter-package boundaries around installed/editable packages and typed public interfaces. Do not add launcher-specific `sys.path` mutation as a lasting integration mechanism; isolate any local prototype bootstrap and migrate it when package metadata is available.
- Keep one runtime as the sole physical command authority. Sample search is an imported recipe/calculation library by default, not an independent device-command IOC. Place latency-sensitive RTASPT work in process only where measured needs support it; heavy block processing may use an optional service boundary with typed inputs/results. Process placement and IOC topology remain open pending timing, throughput and lifecycle evidence.
- RedSun may be selected as the future run host, not merely as a parallel device adapter. The local `redsun-mimir` example (audited 2026-10-04 at commit `2cd53d66a9fd7a5838e2038cf9f5e9630feb4dd3`) uses a plugin manifest, typed protocols and component wiring around a RedSun-owned RunEngine; treat it as a composition reference, not as an adopted dependency or a mandate to make all components IOCs.
- One application may acquire from a camera at a time; MMStudio Live and napari acquisition must take turns.
- Preserve typed axes, coordinates, sequence/timestamp semantics, missing-frame policy, target boundaries and calibration context. Generic plane adapters do not mean every current RTASPT consumer supports arbitrary streaming inputs.
- Do not inherit robotic holotomography, articulated motion or external reconstruction services from copied reference documentation.

## Documentation conventions

- Explicitly distinguish implemented, planned, deferred and non-goal behavior. Files and prototypes do not establish operational readiness or hardware acceptance.
- Record exact software commits/tags, protocol/configuration revisions, calibration IDs and audit dates for external-code claims.
- Prefer relative Markdown links and valid anchors. Use UTF-8, balanced fences, no trailing whitespace and no conflict markers.
- Keep README concise; detailed contracts belong in the owning plan. Update that plan before synchronized indexes and diagrams in the same task.
- Preserve publication names, device terminology and external package identities; rename only this project's identity.
- Keep session/commit logs in 08_session_logs/ and 09_commit_logs/ as local archives; do not commit them.

## Mermaid conventions

- [Architecture source](02_docs_offline/architecture_flowchart.md) is authoritative; static exports are secondary.
- Update the authoritative architecture diagram in the same change after any tangible architectural change to component boundaries, ownership, dependency direction or execution flow.
- Set node and cluster labels to 22px and edge labels to 17px through themeCSS.
- Use compact layouts, short multiline labels and quoted labels containing punctuation or spaces.
- Distinguish planned composition from current code; check fences and node/edge references and render when tooling is available.

## Software and execution baseline

- Change reusable software in its owning repository, following its contributor instructions. Do not copy donor source or quality exclusions into the bundle.
- Require project-owned dependency locks, CI/release metadata, appropriate linting/typing and meaningful hardware-free mock/replay fixtures in independently released software.
- Recipe manifests should declare typed parameters/units, capabilities, preconditions, resources, physical effects, completion/failure conditions, identity/version and validation evidence.
- Preserve specimen, target, phase, coordinate-frame and calibration context. Keep acquisition time separate from publication time; reject stale or mismatched observations.
- Log proposed, accepted, started, completed, failed, cancelled and outcome-unknown actions with request IDs and readbacks where available.
- Recovery is action-specific. A timeout does not prove an action did not occur; never assume safe automatic retries or universal physical rollback.
- Tight trigger timing belongs in acquisition backends; reject unsupported timing/capability bindings rather than claiming hard real-time Python execution.

## Safety and hardware work

- Documentation/setup tasks do not authorize connecting, moving, illuminating, flashing firmware or changing physical safety state.
- Before separately authorized hardware enablement, verify identity, limits, shutter-off state, applicable MCU watchdog, E-stop/interlock provisions and failure cleanup against the actual revision. Do not imply these protections already exist.
- Start with simulation/replay, then one authorized real device alongside mocks. Characterize timing before hardware-master triggering.
- Never commit credentials, machine-local secrets or large raw datasets. Use redacted profiles and checksummed references.

## Validation checklist

For documentation changes, check relative files/anchors, code-fence and Mermaid balance, node/edge references (render when available), stale identities and contradictory ownership/status claims, UTF-8, trailing whitespace and conflict markers.

Report documentation checks separately from runtime tests and physical acceptance. Do not modify external donor code to improve a documentation claim.

## Git and submodule policy

- Preserve unrelated user changes; do not commit, push, tag or change submodule pins unless explicitly requested.
- Obtain explicit manual approval immediately before every remote push, including branch/tag creation, deletion and force pushes. Earlier authorization to prepare work is insufficient.
- Never merge, fast-forward, squash, rebase or otherwise integrate into main without explicit manual approval for that specific integration.
- Make and test software changes in the owning repository first; update the bundle pointer separately when authorized.
- Pin exact tested commits, not implicit branches or uncommitted worktrees.
- Release manifests must record software commits/tags, firmware checksums, profile revisions, hardware configuration and calibration IDs.
