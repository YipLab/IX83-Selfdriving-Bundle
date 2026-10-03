# ARH documentation agent and contributor conventions

This is the single source of working conventions for agents and contributors editing `*_docs_*/`. `CLAUDE.md` points here; keep durable rules in this file instead of duplicating them by client.

The ARH repository is the **instrument and integration record**, not the published acquisition application. Documentation, drawings, specifications, firmware, system profiles and acceptance evidence belong here. The future AHT and robotic ARH applications are independent repositories pinned under `03_external/`.

## Read first

Use the planning documents in this order when statements overlap:

1. `README.md` for the handoff index, frozen decisions and new-PC bootstrap checklist.
2. `ARH_restructuring_plan.md` for authoritative architecture, contracts, migration phases and gates.
3. `multi_system_repository_strategy.md` for package ownership, dependency direction and submodule policy.
4. Domain plans for processing, firmware, SLAR and post-processing.
5. `mimir_to_arh_implementation_matrix.md` and `arh_architecture_flowcharts.md` as synchronized summaries.
6. `hardware_devices_available_to_agents.md` gives a list of real hardware mapping on the acquisition platform *at a given time point*. This will be *modifed by the developer only* and *strictly for offline use* to inform physical hardware currently connected to the testing PC per agent run.

When a lower-priority document conflicts with a higher-priority one, correct the summary or historical interpretation. Do not silently weaken the authoritative decision.

## Frozen project boundaries

- Build `redsun-adaptive-holotomography` first, with import package `redsun_aht` and command `aht`.
- Build `redsun-adaptive-robotic-holotomography` later, with import package `redsun_arh` and command `arh`.
- The robotic package depends on a tested AHT public API. AHT never imports the robotic package.
- Do not create a third shared-core repository until measured release or dependency pressure justifies it.
- AHT contains all common acquisition, calibration, storage, local/offline processing, MCU-host and UI behavior, but installs, configures and contacts neither `arh_sim` nor SLAR.
- Robotic ARH owns 6+1DoF authorization, `arh_sim`, SLAR, articulated composition and robotic-only MCU capabilities.
- The instrument application is the only physical command authority. `arh_sim` and SLAR are advisory/external services and never bypass ARH safety policy.
- SLAR stays outside Bluesky/ophyd/EPICS initially. Its implemented H5/HTTP-MsgPack path precedes any future ZMQ scene stream.
- Firmware, panel profiles, wiring and hardwired E-stop evidence remain in the instrument repository. The AHT package owns the typed host protocol and conformance interface.

## Source and compatibility authority

- Target a pinned, tested RedSun 0.11-or-later public API in new software repositories.
- `03_external/redsun-pyhololab` is an archival behavioral donor, not an application base. Its final WIP merge is `e989f77`, with parents `be72139` and `be76edb`.
- The archive passes 106 tests with 7 skipped, but retains 15 Ruff findings and 55 mypy errors in RedSun 0.10-era donor code. Never copy those exclusions or call the archive production-ready.
- Depend on or upstream current typed providers, canonical event streams, `BaseStorage`, upstream MMCore camera/stage foundations and the document-routed median presenter.
- Rewrite or upstream legacy serial, shutter, state/filter-wheel, Hamamatsu and ASI adapters against current ophyd-async contracts. Do not restore removed `DataWriter`/`SourceInfo`, storage-presenter or old `mm_property_signal(..., datatype=..., readonly=...)` APIs.
- Use `03_external/pyhololab/src/simple_acquisition` and `src/core` as behavioral/solver donors with provenance and characterization tests, not as the target architecture.
- Use `03_external/SLAR` branch `feat/psf_splatting_impl` as the canonical reconstruction reference described in `SLAR_live_integration_plan.md`. Do not modify SLAR from this repository unless a future task explicitly changes that policy.

## Documentation conventions

- Separate **implemented**, **planned**, **deferred** and **non-goal** behavior explicitly. Do not describe a stub, donor file or proposed API as operational.
- Record exact repository commit/tag, protocol version, configuration revision and audit date for claims tied to external code.
- Prefer relative Markdown links between files in `docs/`; keep anchors valid when renaming headings.
- Use UTF-8, one sentence per line only when it improves diffs, no trailing whitespace and no unresolved conflict markers.
- Keep the planning index concise. Put detailed contracts and rationale in the owning plan, then link rather than duplicate.
- If a decision changes, update the authoritative plan first, then the index, matrix, diagrams and affected domain plan in the same task.
- Preserve instrument-specific terminology and publication names. Internal shorthand such as “cartesian” must not become a public repository identity.
- Write session logs and commit logs in `08_session_logs` and `09_commit_logs`. These are for local archival purpose for which you can reference from, and will not be committed.

## Mermaid conventions

- Mermaid source in `arh_architecture_flowcharts.md` is authoritative; static PNG files are secondary exports.
- Set node and cluster-label text to `22px` and edge labels to `17px` through `themeCSS`.
- Prefer compact layouts, short multiline labels and balanced axes. Avoid long one-direction chains.
- Quote node and subgraph labels containing spaces, punctuation or parentheses.
- Keep the current donor and proposed ARH diagrams structurally comparable without implying feature parity.
- After edits, check fence balance, node/edge references and a rendered result when a Mermaid renderer is available.

## New software repository baseline

When work moves to the new instrument PC, scaffold rather than copy the donor:

- independent Git repository with `src/redsun_aht` layout;
- project-owned `pyproject.toml`, `uv.lock`, CI and release metadata;
- pytest async/Qt conventions and comprehensive real/mock/replay fixtures;
- pre-commit, Ruff and strict mypy over both `src` and `tests` from the first commit;
- typed provider keys, canonical stream names, manifest-integrity tests and inspectable `build_*` factories;
- partial staging per device and hardware-free GUI/headless processing profiles;
- no donor-wide lint/type exclusions and no imports from `redsun_mimir` internals.

## Safety and hardware work

- See `hardware_devices_available_to_agents.md`.
- Documentation tasks do not authorize connecting, moving, illuminating, flashing firmware or changing physical safety state.
- Before hardware enablement, verify device identity, limits, shutter-off state, MCU watchdog, E-stop latch/reset and failure cleanup against the applicable hardware revision.
- Start with simulation, then one real device alongside mocks. Characterize software timing before MCU-master or camera-master triggering.
- Never place credentials, machine-local secrets or large raw datasets in Git. Commit redacted/example profiles and durable checksummed references.

## Validation checklist

For documentation-only changes:

1. Check all relative Markdown files and heading anchors.
2. Check code-fence and Mermaid-block balance.
3. Check Mermaid structure or render it when tooling is available.
4. Search for stale commit IDs, obsolete storage/median APIs and contradictory AHT/ARH/SLAR boundaries.
5. Check UTF-8 text, trailing whitespace and conflict markers.

When reporting repository validation, distinguish passing runtime tests from failing archival quality checks. Do not alter archived donor code merely to make a documentation claim cleaner.

## Git and submodule policy

- Preserve unrelated user changes and do not commit, push, tag or change submodule pins unless explicitly requested.
- Always obtain explicit manual approval immediately before every remote push, including branch creation, branch deletion, force pushes and tag pushes. Earlier authorization to work on or prepare a branch does not count as approval to push it.
- Never merge, fast-forward, squash, rebase or otherwise integrate a branch into `main` without explicit manual approval for that specific integration.
- Make software changes in the owning software repository first. Update the instrument repository's submodule pointer separately after testing.
- Pin exact tested commits; never rely on an implicitly tracked branch or an uncommitted submodule worktree.
- Record software commit/tag, firmware checksum, panel-profile revision, hardware configuration and calibration IDs in released system manifests.

## Updating this guide

Persist new cross-client documentation conventions here. Keep `CLAUDE.md` as a pointer unless Claude requires a narrowly client-specific instruction that cannot be expressed here.
