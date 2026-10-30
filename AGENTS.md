# IX83-Automation agent and contributor conventions

This is the single source of working conventions for this device bundle: documentation, configuration, firmware and integration work. Keep durable rules here; any future CLAUDE.md should point here.

IX83-Automation is the project identity; IX83-Selfdriving-Bundle is the current checkout name. This repository is the instrument and integration record, not a copy of an independently released application or processing library.

## Mandatory test gate

Before composing or running Windows tests, read [Windows test execution](02_docs_offline/windows_test_execution.md) and the owning repository's test instructions. For the primary Redsun app, use the [app test runner](03_external/redsun-searching-is-imaging/scripts/run_full_test_suite.ps1) for a host-side full-suite run. The exact existing bundle `.pva-tmp` path is `TEMP`/`TMP`; never nest run-specific folders beneath it. The `_ctypes` DLL restriction and fallback are specific to the Codex Windows sandbox; other coding agents have not shown this issue so far. Do not apply that workaround to other agents unless their own environment demonstrates the same failure, and do not regenerate or resync a venv to work around a Codex DLL restriction.

## Read first

0. [Windows test execution](02_docs_offline/windows_test_execution.md) before any Windows test command.
1. [README](README.md) for the repository map and setup entry point.
2. [ix71 system setup plan](02_docs_offline/ix71_system_bundle_setup_plan.md) for the current `ix71-system` hardware, disabled IX83 services and open gates, and [IX83 device bundle setup plan](02_docs_offline/device_bundle_setup_plan.md) for the historical IX83 ownership and reusable application decisions.
3. [Python environment inventory](02_docs_offline/python_environment_inventory.md) for the dated environment map and recovery evidence; each project's own lockfile remains authoritative.
4. The primary acquisition [README](03_external/redsun-searching-is-imaging/README.md), [conventions](03_external/redsun-searching-is-imaging/AGENTS.md) and [upstream baseline/parity matrix](03_external/redsun-searching-is-imaging/docs/upstream_baseline.md), then the bundle's [sample search workflow research](02_docs_offline/sample_search_workflow_research.md) for supporting reusable workflows, processing, and bundle-owned execution policy. Its section 0 assesses current implementation status; the numbered sections below it remain a research/design record, not implemented software.
5. RTASPT's [architecture](03_external/Realtime-Anisotropy-SPT-Analysis/docs/architecture.md) and [input contracts](03_external/Realtime-Anisotropy-SPT-Analysis/docs/data-input-contracts.md) for current software boundaries; its [live acquisition](03_external/Realtime-Anisotropy-SPT-Analysis/docs/live-acquisition.md) page is now the record of the acquisition path removed on 2026-10-17.
6. [Architecture flowchart](02_docs_offline/architecture_flowchart.md), relevant module descriptions in 06_module_description/ and instrument artifacts in 04_code/.
7. [Hardware availability](02_docs_offline/hardware_devices_available_to_agents.md) is a developer-maintained offline snapshot. Agents must not edit it or interpret it as authorization to contact devices.
8. [Remote update monitor](02_docs_offline/redsun_external_update_monitor.md) records incoming upstream changes. Read it before planning software integration; distinguish discovery from adopted, tested or released behavior.
9. [Agent skills](11_skills/) — the [headless pipeline rehearsal skill](11_skills/headless-pipeline-rehearsal/SKILL.md) is the entry point for instrument sessions and implementation rounds; it owns the headless default, the fixed-sample boundary and the single command-authority rule.

Correct lower-priority summaries when they conflict with the owning plan. External software documentation owns claims about that software's implemented contracts.

## Skills

Reusable agent procedures live in [11_skills/](11_skills/). Start with the
[headless pipeline rehearsal skill](11_skills/headless-pipeline-rehearsal/SKILL.md) for
any instrument session or backlog continuation: it defines the headless (no-Qt) default,
the fixed-sample boundary, the one-command-authority rule and the close-out evidence.
Loading the skill is not a substitute for the owning plans' contracts or for the
authorization the current request provides.

## Project boundaries

- The bundle owns instrument profiles, wiring, firmware, calibration references, integration/front-end coordination, execution policy and acceptance evidence. The primary Redsun acquisition application is `03_external/redsun-searching-is-imaging/`, derived from upstream redsun-mimir main and its recorded release baseline. Existing camera/XYZ acquisition and scan-host code under `04_code/ix83_acquisition/` are the temporary Pycro-Manager compatibility and qualification path; migration into the primary application remains planned.
- Begin the acquisition baseline with stage-aware camera and bounded XYZ-stage mocks. The local Pycro-Manager adapter must remain optional and hardware-disconnected until explicitly constructed.
- Reusable sample-search logic lives under `03_external/sample_search/src/planner/` as the local `redsun-planner` distribution; `planner` is the only importable name, since the former `samplescout` shim was removed. Acquisition declares the built planner wheel as a non-editable local path dependency, locked with Bluesky and build/runtime dependencies; the development group includes Ophyd for simulated RunEngine verification. The bundle source gitlink pins the planner; an independent package release, portable consumer dependency reference and final hardware-adapter contract are still pending. The primary app declares `redsun-planner` as an installed non-editable sibling path dependency and uses its plans through the Presenter plan-map and Redsun session policy. Keep recipe descriptors, geometry/calculation helpers, review metadata, plan generators and hardware-free records separate from device calls. The current IX83/Pycro-Manager compatibility stack and parity evidence live under `04_code/ix83_acquisition/`; the mid-term target is to port its full functional stack into `03_external/redsun-searching-is-imaging/` using the existing session, per-device service, Ophyd-async, Bluesky RunEngine, Presenter, callback and storage infrastructure. Migrate in tested module-sized slices, preserve the bundle package as parity reference until acceptance, and retain Pycro-Manager only as a temporary device adapter where needed. Import installed planner distributions from consumers; add source directories to `sys.path` only for intentional local development runs. The planner generates plans and pure calculations only: image registration, hand-eye run analysis and stitching are host-owned. The compatibility implementations live in `04_code/ix83_acquisition/`; the primary Redsun app also owns ported registration and pass-end stitching plus a hand-eye acquisition binding. OpenCV belongs to these hosts, not the planner.
- RTASPT owns reusable reconstruction, anisotropy, tracking and analysis. Its live acquisition path was removed on 2026-10-17 (camera, MDA, Pycro-Manager backend, napari acquisition dock and the `acquire` command), so RTASPT consumes recorded data only; a source-independent live processor is no longer planned there. Its current distribution metadata has a processing profile without GUI/plot dependencies and a separate `gui` extra; packaging search-scan and identity as a separately named minimal distribution remains planned.
- A listener reports typed observations or proposes actions. The bundle executor owns device calls, resource arbitration and hardware limits. Processing callbacks, scripts, GUIs and agents must use the same execution policy.
- Keep recipe (versioned executable workflow), skill (discovery/guidance metadata) and run (resolved execution record) distinct. Agent prose must not replace executable configuration.
- Start with a serial state machine and declared resources. First validate same-objective, two-pass tiled sample search; use baseline/perfusion/anisotropy as a later generalization case.
- Redsun/Bluesky is the default plan composition for the future `redsun-planner` package; Pycro-Manager is a temporary IX83 execution adapter, not the reusable package's primary API. Keep device bindings and camera/stage operations at the composition edge, with one physical command authority per run. Reusable RTASPT processing remains separately owned.
- Standardize package imports and inter-package boundaries around installed/editable packages and typed public interfaces. Do not add launcher-specific `sys.path` mutation as a lasting integration mechanism; isolate any local prototype bootstrap and migrate it when package metadata is available.
- Keep one runtime as the sole physical command authority. Sample search is an imported recipe/calculation library by default, not an independent device-command IOC. Place latency-sensitive RTASPT work in process only where measured needs support it; heavy block processing may use an optional service boundary with typed inputs/results. Retain the inherited managed per-device service topology as the baseline; additional processing/planner services and changes to process placement require timing, throughput and lifecycle evidence. One session/RunEngine owns policy while its services perform device I/O.
- `redsun-searching-is-imaging` adopts redsun-mimir as its architecture root and mainline implementation, based on main `293e8ba0f2f5229eb5ca202e372647dd9338f216` and official release `v0.5.1` at `66a4b3b656649156d6aab6c4111bdd724c1fe765` (audit 2026-10-15; official main and latest release verified). Preserve applicable feature/engineering parity across sessions, typed discovery/wiring, built-in controls, presenter plan maps/actions, callbacks, managed FastCS/PVAccess services, ophyd-async clients, napari, storage and validation tooling. Record intentional divergences; Mimir-specific board deployment and iSCAT intentions are excluded. Preserve unused source as clearly marked references where useful. Keep the official `C:/Users/YipGroup/Documents/GitHub/redsun-mimir` checkout for pulling/reviewing fresh upstream versions; the derived repository has its own identity and no upstream remote.
- The primary Redsun Presenter now exposes a two-stage bounded snap survey → operator review → selected-target revisit workflow and a bounded multi-strip native-Ludl broom workflow, composed from installed `redsun-planner` plans and host-bound devices. Survey coverage and revisit envelope are checked before motion; scan calibration must match the live camera mode and XY service signal sources. Device names remain binding provenance, not hardware-unique identities. The current physical hand-eye fit remains provisional, and physical calibration acceptance, sustained camera cadence, exposure-associated stage poses and full GUI acceptance remain open. Keep planner importable without a hard Redsun runtime dependency; other-framework adapters remain supporting examples or skills. See the [current next steps](02_docs_offline/redsun_rtaspt_integration_next_steps.md), [snap workflow](03_external/redsun-searching-is-imaging/docs/snap_review_checkpoint.md) and [broom workflow](03_external/redsun-searching-is-imaging/docs/broom_scan_workflow.md).
- One application may acquire from a camera at a time; MMStudio Live and napari acquisition must take turns.
- Preserve typed axes, coordinates, sequence/timestamp semantics, missing-frame policy, target boundaries and calibration context. Generic plane adapters do not mean every current RTASPT consumer supports arbitrary streaming inputs.
- Do not inherit robotic holotomography, articulated motion or external reconstruction services from copied reference documentation.

## Documentation conventions

- Explicitly distinguish implemented, planned, deferred and non-goal behavior. Files and prototypes do not establish operational readiness or hardware acceptance.
- **Registration sign convention:** The known sign-flip issue belongs to the old ECC registration script, which is marked stale across the repository. Do not attribute that issue to current registration workflows or comparisons unless they explicitly used that stale script. When comparing engines, state each result's coordinate convention (for example, image placement versus feature content displacement) and describe any sign conversion as a coordinate-convention conversion, not as a correction for the stale script's bug.
- Record exact software commits/tags, protocol/configuration revisions, calibration IDs and audit dates for external-code claims.
- Prefer relative Markdown links and valid anchors. Use UTF-8, balanced fences, no trailing whitespace and no conflict markers.
- Keep README concise; detailed contracts belong in the owning plan. Update that plan before synchronized indexes and diagrams in the same task.
- Preserve publication names, device terminology and external package identities; rename only this project's identity.
- Write the application name as **Redsun** in prose and `redsun` in packages, modules, paths and identifiers. Never capitalise the second word. That camel-case spelling spread through copied prose once and had to be corrected repo-wide, so fix it on sight instead of reproducing it in new text, code comments and diagrams.
- Keep session/commit logs in 08_session_logs/ and 09_commit_logs/ as local archives; do not commit them. The top-level [session log index](08_session_logs/README.md) tracks evidence and the [experiment notebook index](07_experiment_notebook/README.md) tracks reusable analysis. Whenever creating an entry in either directory, add or refresh its index row in the same change. Give every entry a README that states scope, source/revision, method, result, artifacts, evidence status, limitations and next gate; cross-link paired session/notebook records. Preserve historical evidence and mark superseded or pre-fix outputs explicitly. Update the owning setup plan before both indexes if acceptance status changes.
- Markdown records in `07_experiment_notebook/` and `08_session_logs/` may embed or link to local PNG and SVG evidence alongside fenced Mermaid diagrams. Store figures with the record that owns them, use relative paths and descriptive alt text/captions, and preserve the generating inputs or script when needed to reproduce a figure. Experiment notebooks may use Obsidian-inspired backlinking: add a concise `Related notes` or `Backlinks` section connecting paired experiment, session, method, and follow-up records, and make reciprocal links when the relationship matters. Prefer standard relative Markdown links so navigation remains portable outside Obsidian; use Obsidian wikilinks only when a notebook-vault workflow specifically needs them.

## Mermaid conventions

- [Architecture source](02_docs_offline/architecture_flowchart.md) is authoritative; static exports are secondary.
- For new Mermaid diagrams, place the source in a Markdown document inside a fenced `mermaid` code block so the diagram renders inline in Markdown viewers. Existing standalone `.mmd` sources do not need to be converted unless explicitly requested.
- Update the authoritative architecture diagram in the same change after any tangible architectural change to component boundaries, ownership, dependency direction or execution flow.
- Set node and cluster labels to 22px and edge labels to 17px through themeCSS.
- Use compact layouts, short multiline labels and quoted labels containing punctuation or spaces.
- Distinguish planned composition from current code; check fences and node/edge references and render when tooling is available.

## Software and execution baseline

- For agent command execution on Windows, prefer WSL Linux when a usable distribution is available, then Git Bash, then PowerShell (`pwsh` when installed; otherwise `powershell.exe`). Check that the selected shell can run commands in the repository before relying on it. Codex's shell executable is controlled by its runtime/user configuration, so this project guidance sets the preference for agent behavior rather than forcing a shell executable.
- The `_ctypes` DLL initialization and protected-path failures described here are specific to the Codex Windows sandbox; other coding agents have not shown the same issue so far. The Redsun app `.venv` may fail importing `_ctypes` inside this sandbox even when it works in the user's PowerShell. A no-escalation import/test fallback is the existing base Python 3.12 interpreter with the intended project's `.venv\Lib\site-packages` on `PYTHONPATH`. Napari's `user_cache_dir` may also need an in-process override because Windows known-folder lookup can bypass the sandbox's writable workspace. Keep these workarounds out of project runtime behavior and do not transfer them to other coding agents unless they reproduce the failure.
- **Codex Matplotlib/Pillow DLL restriction (2026-10-17):** importing Matplotlib through the app `site-packages` with base Python 3.12 failed at Pillow's `_imaging` DLL with `Access is denied`. Treat this as a Codex Windows sandbox native-DLL restriction; do not rebuild or resync the environment. Other coding agents have not shown this issue so far. Prefer Markdown Mermaid or existing plot evidence in this sandbox; if a Matplotlib artifact is required, preserve the inputs and command and use a normal host shell.
- **Codex CuPy kernel-cache restriction (2026-10-19):** the first live GPU median warmup tried to create CuPy's compiled-kernel cache under its default protected cache directory. Python then spun in `tempfile.NamedTemporaryFile(dir=cache_dir)` without producing test output. Before CUDA tests in this sandbox, create `CUPY_CACHE_DIR` and `CUDA_CACHE_PATH` folders under a workspace-owned evidence/run directory and set both variables before Python starts. Create the folders as the normal workspace user before a host-side elevated run; leave the venv and lock unchanged. This has not been observed with other coding agents so far; don't transfer the workaround unless they reproduce it. See [GPU median integration evidence](08_session_logs/20261019T_gpu_broom_fakecore_cuda_diagnostic/README.md).
- **CuPy kernel-cache spin also hits session launches (2026-10-29, DSH):** the same protected-cache spin appeared outside pytest, inside a headless Redsun session: the first GPU kernel compile of the route flat (`pooled_gated_median_flat` via `prepare_flatfield_corrected_stack`) sat at ~100 % of one core with 0 % GPU and no log line for 14 minutes, and a `faulthandler` stack showed `tempfile.NamedTemporaryFile` under `cupy/cuda/_compiler_cache.py`. Any session launch that will run GPU processing must export `CUPY_CACHE_DIR` and `CUDA_CACHE_PATH` into a workspace directory before Python starts, alongside `PYMM_LOG_FILE`; with them the same 12-lane route completed. Do not diagnose that hang as a pipeline defect. See [hardware smoke record](08_session_logs/20261029T_hw_smoke_route_01/README.md).
- **Redsun PVA test incident (2026-10-17):** in the Codex sandbox, P4P 4.3.0 could fail `event_base_new()` when Windows temp-file setup used an inaccessible/default or too-long path. A successful host-side run used base Python 3.12 with both the app `src` tree and `.venv\Lib\site-packages` on `PYTHONPATH`, loopback PVA, `TEMP`/`TMP` set to the short bundle-root `.pva-tmp`, and a separate `--basetemp` under the evidence directory. A long temp path reproduced libevent's `Temp file name is too long` and `event_base_new()` failure; the previous `08_session_logs\redsun_sim_temp` root also inherited an ACL that blocked pytest temp creation. The one-frame PVCAM camera-only test passed (`1 passed in 10.79 s`) and the 50 µm Ludl/DemoCamera stage test passed (`1 passed in 16.77 s`); see the [ordered physical rehearsal evidence](08_session_logs/20261017T_physical_redsun_rehearsal/README.md). A separate headless managed-Demo Redsun Session also passed outside the sandbox: real loopback PVA, Ophyd-async signals, a Presenter plan and three Zarr-backed snake strips completed with 72 frames; see [headless managed-Demo PVA evidence](08_session_logs/20261017T152410Z_managed_demo_broom_pva_headless/README.md). The same service still fails PVI readiness inside the sandbox. Create exact temporary roots as the normal workspace user before any authorized host-side run; clean only those exact roots and new libevent `*.tmp` files in the same command. Never leave elevated-owned temp directories. Hardware/PVA runs still require explicit user authorization. The earlier full app suite passed outside the sandbox (`131 passed, 23 skipped, 18 warnings in 83.66 s`) with DemoCamera/DemoXY fixtures. Avoid pytest temp fixtures in the sandbox when ACL cleanup has not been verified. See the [PVA and DemoCamera evidence](08_session_logs/20261017T0219Z_democamera_zarr_tiff_export/README.md#democamera-service-attempt).
- **Codex sandbox PVA fixture stall (2026-10-26):** the hardware-free ASI fake-serial/DemoCamera PVA test remained alive for over three minutes without a pytest result or a visible PVA child-service result, despite a successful app-venv `_ctypes` probe and the prescribed temp paths; it was interrupted. The same test passed on the host in 7.44 s. This comparison does not identify the sandbox stall's cause or establish that PVA itself failed. Do not treat a stalled run as a test failure or repeatedly restart it; retain its evidence, and if diagnosis is needed capture a bounded stack trace and service startup evidence. For user-authorized PVA verification, the existing host-side runner remains the supported comparison. See the [sandbox record](08_session_logs/20261026T155955_full_test_run/README.md) and [host record](08_session_logs/20261026T160346_full_test_run/README.md). The separate host-side laser-service discovery failure was resolved by setting the documented client loopback address; it is not evidence of a sandbox fault.
- **Offline PVA port is a launch cue, not a blocker:** when the expected Redsun PVA/UI listener (currently 4827) is offline, that means no session is occupying it. Start the requested new Redsun session when the task calls for one; do not repeatedly report the port as a reason to stop. Check for conflicts only if another active session/process is present or the launch reports a bind error.
- **RTASPT test incident (2026-10-16):** a fresh `.venv` lock sync installed 130 packages; the user requested renaming it from `.venv-codex-20261016`. Its launcher still fails at `_ctypes` initialization (`0xC0000142`). With the managed Python 3.12.13 base interpreter and this venv's `site-packages` on `PYTHONPATH`, isolated `tests/test_streaming.py` and `tests/test_tubular.py` each passed 17 tests. Full-suite attempts crashed with Windows status `0xC0000409` during sandboxed Vispy/Qt execution; excluding GUI tests still crashed later and produced one unresolved failure marker. Napari's cache path must be redirected in-process to a workspace-owned temporary directory, then removed after testing. Ruff exits without output in the sandbox; the user reports Ruff and formatting checks pass outside it. These fallback runs are partial evidence and do not qualify `.venv` for regular GUI or hardware use. See the [diagnostic record](08_session_logs/20261016T_python_venv_dll_diagnostics/README.md#fresh-rtaspt-environment-and-test-attempt-2026-10-16) before reattempting.
- **Sandbox DLL start-up failures are shell faults, not environment damage (2026-10-17):** the acquisition `_ctypes`/`0xC0000142` start-up failures came from the Codex sandbox DLL path; every affected interpreter launched and imported `ctypes` under a normal shell. Never respond by creating a new, renamed or dated venv: probe the intended interpreter, report the sandbox path, and stop. Tighter and more specific test rules reduce that path but rely on agent adherence, so keep the probe as the gate before a run. The acquisition project has exactly one environment, `04_code/ix83_acquisition/.venv`; do not add a second one and do not set `UV_PROJECT_ENVIRONMENT` for it.
- Use each project's named Python environment and lock; never rely on bare `python`/`pip` resolving to the machine interpreter. Python 3.8 is prohibited; use the existing Python 3.12 runtime for IX83 bundle execution. Keep environments separate across the acquisition host, Redsun application, RTASPT and planner source; use the [environment inventory](02_docs_offline/python_environment_inventory.md) as a dated status snapshot, not as a replacement for owning project metadata.

- Change reusable software in its owning repository, following its contributor instructions. The explicitly adopted acquisition repository preserves upstream source and applicable engineering configuration; record its origin and parity decisions there. Do not copy unrelated donor source or quality exclusions into instrument code.
- Require project-owned dependency locks, CI/release metadata, appropriate linting/typing and meaningful hardware-free mock/replay fixtures in independently released software.
- Recipe manifests should declare typed parameters/units, capabilities, preconditions, resources, physical effects, completion/failure conditions, identity/version and validation evidence.
- Preserve specimen, target, phase, coordinate-frame and calibration context. Keep acquisition time separate from publication time; reject stale or mismatched observations.
- Log proposed, accepted, started, completed, failed, cancelled and outcome-unknown actions with request IDs and readbacks where available.
- Recovery is action-specific. A timeout does not prove an action did not occur; never assume safe automatic retries or universal physical rollback.
- Tight trigger timing belongs in acquisition backends; reject unsupported timing/capability bindings rather than claiming hard real-time Python execution.

## Survey image-processing policy (2026-10-28)

- The integrated survey/review/revisit workflow uses RTASPT GPU gated flat-field
  correction and GPU PCC-seeded ECC. Require and record the resolved GPU backend;
  refuse unavailable GPU support or insufficient device budget instead of falling
  back to CPU. Stage priors remain geometric gates, not a replacement for the PCC
  seed. Pure planning and record validation remain device-free. Explicit historical
  CPU comparison paths do not qualify this workflow's processing result.

## DSH Windows sandbox (2026-10-18)

DSH is the DeepSeek Harness Web GUI agent. Its file policy here is
`workspace-write` with an ask approval policy. It is not the Codex sandbox: the
Redsun app `.venv` starts and imports `_ctypes` normally, and managed PVA child
services do start and resolve over loopback. Keep the Codex `_ctypes` and
no-elevation fallbacks out of DSH runs.

The remaining limitations, all observed on 2026-10-18 while running the native
Ludl scan tests:

- **Writes outside the workspace are denied, including during import.**
  `pymmcore_plus` opens `%LOCALAPPDATA%\pymmcore-plus\logs\pymmcore-plus.log`
  when imported, so even `find_micromanager()` raises `PermissionError`. Set
  `PYMM_LOG_FILE` to a workspace path before starting any Python process that
  imports it; child services inherit the variable. No escalation is needed.
- **Qt/Napari startup reads the protected user cache.** Constructing
  `QApplication` loads Napari theme SVGs from `%LOCALAPPDATA%\napari\Cache` and
  fails with `PermissionError`. Patch
  `napari.utils._platformdirs.user_cache_dir` in the pytest launcher process to
  a workspace directory (the same patch `scripts/run_full_test_suite.ps1` uses)
  and point `NAPARI_TEST_CACHE` there. Do not redirect
  `platformdirs.user_data_dir` globally: MMCore service children need the real
  path to find the Device Interface 75 adapter bundle.
- **`mkdir(mode=0o700)` creates an unreadable directory on this host.** A
  restrictive POSIX mode becomes a DACL the sandbox token can neither read nor
  delete. pytest 9 creates `--basetemp` that way, so a run ends with
  `PermissionError: [WinError 5]` in `cleanup_dead_symlinks`, no test summary
  and exit 1 even when every test passed. `mode=0o777` (the default) is fine.
  Use a run-scoped `sitecustomize.py` on `PYTHONPATH`:

  ```python
  import os, sys
  if sys.platform == "win32":
      _mkdir = os.mkdir
      def mkdir(path, mode=0o777, *, dir_fd=None):
          _mkdir(path, 0o777, dir_fd=dir_fd)
      os.mkdir = mkdir
  ```

  Such directories cannot be deleted afterwards inside the sandbox; leave them
  in the gitignored `tmp/` or remove them outside it. Do not rebuild an
  environment over this.
- **Recurring `pytest-of-<user>` ACL:** once created, pytest's default `tmp_path`
  base is unreadable and every later run errors at fixture setup with
  `PermissionError: [WinError 5] ...\pytest-of-...`. Always pass a fresh
  `--basetemp <workspace>\tmp\pytest-<run>`; do not reuse the default root or try
  to delete it from the sandbox. Many fixture-setup `PermissionError`s are this
  artifact, not test failures. See
  [Windows test execution](02_docs_offline/windows_test_execution.md#dsh-pytest-tmp-base-acl-recurring).
- **Plugin autoload collides with the explicit asyncio plugin.** With
  `PYTEST_DISABLE_PLUGIN_AUTOLOAD` unset, passing `-p pytest_asyncio.plugin`
  raises `Plugin already registered under a different name: asyncio`. Disable
  autoload and pass the plugin explicitly; `addopts` already adds
  `-p redsun.testing`.
- **Working pytest environment for Redsun:**

  ```powershell
  $env:TEMP = "$root\.pva-tmp"; $env:TMP = $env:TEMP
  $env:PYMM_LOG_FILE = "$root\.pva-tmp\pymmcore-plus.log"
  $env:NAPARI_TEST_CACHE = "$root\.pva-tmp\napari-cache"
  $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"; $env:PYTHONUTF8 = "1"
  $env:EPICS_PVAS_INTF_ADDR_LIST = "127.0.0.1"
  $env:EPICS_PVAS_AUTO_BEACON_ADDR_LIST = "NO"
  # launcher patches the Napari cache, then calls pytest.main with
  # -p pytest_asyncio.plugin --basetemp <run evidence folder>
  ```

  Use the app `.venv\Scripts\python.exe` directly; the base-Python fallback is
  not needed in DSH. `scripts/run_full_test_suite.ps1` already patches the
  Napari cache but not the `mkdir` mode, so in DSH put the shim directory first
  on `PYTHONPATH` before invoking it.
- **Managed PVA works, with one known child flake.**
  `Micro-Manager_2.0.3_20260420` DemoCamera starts, connects, captures and
  writes Zarr through loopback PVA, and the native Ludl fake-serial service
  reaches readiness. The pre-existing
  `test_legacy_ascii_stage_runs_as_pva_child_with_fake_serial_peer` still
  misses its 15 s ready line after printing `Starting FastCS`; it fails alone
  too, so it is not test ordering. The binary fake-serial child and the
  managed DemoCamera tests pass.
- **Search noise from ACL-damaged leftovers.** `glob`/`grep` built on `rg`
  report `Access is denied` for old roots such as `_pytest-tmp`,
  `.pva-tmp\pytest-of-*`, `.pytest_cache` and
  `03_external/redsun-searching-is-imaging/tmp/codex-mock-scans-*`. Scope the
  search to the directory you need rather than reading those roots.
- **Do not start a napari/Qt GUI from the agent sandbox (2026-10-24).** Attempting a full
  GUI session in-process - `QApplication` on the default platform plus `napari.Viewer`, with
  the documented cache patch and `NAPARI_CONFIG` redirected into the workspace, while managed
  PVA child services were alive - **crashed DSH and a Codex process together**; the run log
  stayed empty, so nothing was captured. Offscreen widget construction
  (`create_plan_spec` + `create_plan_widget`) is safe and sufficient for contract checks.
  Operator click-through belongs to a normal host session and is recorded there as evidence.
  Do not retry the GUI path from here, and do not add cache/platformdirs patches to make it
  start.
- **DSH renderer OOM under heavy sessions (2026-10-24).** Three restarts in fifteen minutes were
  caused by the DSH desktop renderer being killed for out-of-memory, not by Python or Codex:
  `%APPDATA%\@deepseek-ai\dsh-desktop\logs\crash-*.log` records `Desktop renderer exited: oom` twice
  and a host exit `3758096392` (`0xE0000008`). `dwm.exe`, `codex.exe` and the Codex MSIX app died in
  the same window as bystanders; a 1 MB OpenCV allocation also failed, which was memory pressure, not
  a numeric-code defect. Keep the renderer surface small (links and short tables instead of many
  embedded images; never paste full JSON/log listings), start a fresh session after repeated app
  restarts, and run heavy numeric/vision work in a separate host terminal rather than inside the
  agent conversation. Collect the crash logs before restarting if it recurs. See
  [crash record](08_session_logs/20261024T_harness_crashes_01/README.md).

- **Escalation.** `danger-full-access` is available with approval, but use it
  only for the specific command that needs it. Never create an elevated temp
  root or resync an environment to work around these findings.

The first full native scan run and its exact commands are in the
[native scan record](08_session_logs/20261018T_native_ludl_scan_01/README.md).

## Safety and hardware work

- Documentation/setup tasks do not authorize connecting, moving, illuminating, flashing firmware or changing physical safety state.
- Before separately authorized hardware enablement, verify identity, limits, shutter-off state, applicable MCU watchdog, E-stop/interlock provisions and failure cleanup against the actual revision. Do not imply these protections already exist.
- **ASI MS2000/LX4000 minimum run speed:** 0.1 mm/s on this installation. A lower `2HSPEED`/profile command can be ignored or leave the stage on its previous profile, producing unintended motion; reject run speeds below 0.1 in plans/profiles. A lower value requires a separately qualified controller/route and owner approval, not a software ceiling change.
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
