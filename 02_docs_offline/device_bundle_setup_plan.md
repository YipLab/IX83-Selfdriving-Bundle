# IX83-Automation device bundle setup plan

## Primary acquisition foundation (2026-10-15)

**AOTF calibration preparation (2026-10-23):** the parent bundle now contains
an isolated [AOTF zero-order calibration module](../04_code/aotf_calibration/README.md)
for MDSnC and PM100USB/S120C. It sweeps one isolated laser at a time, selected
manually or through optional MMCore OBIS 405/640 and Sapphire 488/561 bindings,
records zero-order minima and RF-power curves, and keeps device construction
opt-in. It is a standalone instrument calibration executor, used only while
other owners of those resources are stopped; future Redsun integration remains
planned. Physical control and calibration acceptance are pending; the current
hardware context and open gates belong to the
[ix71 setup plan](ix71_system_bundle_setup_plan.md#aotf-calibration-preparation-2026-10-23).
The [Redsun transfer contract](../04_code/aotf_calibration/REDSUN_TRANSFER.md)
maps the prepared laser/AOTF/meter engine to application-owned service clients,
Presenter plans and callbacks without adding another RunEngine or adopting the
legacy IX83 laser command dialects for these newly identified heads.

The copied `03_external/redsun-mimir/` repository is established as
[`03_external/redsun-searching-is-imaging/`](../03_external/redsun-searching-is-imaging/README.md).
It is the new primary acquisition module, with distribution/CLI/plugin name
`redsun-searching-is-imaging` and import `redsun_searching_is_imaging`.
The architecture root is upstream redsun-mimir's mainline implementation,
including applicable features and engineering decisions, rather than only its
presenter example. No generic Redsun hardware-bundle template was available for
this establishment; the repository was copied instead of using a GitHub fork.

**Exact source:** copied main `293e8ba0f2f5229eb5ca202e372647dd9338f216`;
latest official release `v0.5.1` at
`66a4b3b656649156d6aab6c4111bdd724c1fe765`. Main includes post-release changes.
Official GitHub main refs and the latest-release API were verified on 2026-10-15 after retrying with network access.
The [baseline and parity matrix](../03_external/redsun-searching-is-imaging/docs/upstream_baseline.md)
records retained/adapted/excluded decisions and the update procedure.

**Implemented establishment:** upstream Git history, tags, authorship and license
are preserved; the copied remote is removed. Package/import/plugin/CLI/session
identities are renamed, versioning starts at `0.1.0.dev0`, automatic publication
is removed and release preparation automation is archived. The inherited
DemoCamera remains the simulation launch path. The IX83 camera commissioning
profile uses PVCAM / Camera-1 with simulated stages and lights; actual camera
startup/readback smoke now succeeds through a Redsun-managed PVCAM service
(2026-10-17; see the [camera check record](../08_session_logs/20261017T_physical_redsun_rehearsal/README.md));
full imaging and scan acceptance remains pending. Origin-specific board drivers, sessions and copied
deployment documents are removed; original versions remain in inherited history.

**Upstream tracking location:** `C:/Users/YipGroup/Documents/GitHub/redsun-mimir`
continues to be the official implementation checkout for pulling fresh versions.
It is separate from the new repository and must retain its official remote.
Record exact main and release revisions when reviewing updates; port applicable
features/fixes with parity evidence. Do not overwrite the derived repository or
silently integrate upstream branches into its main branch.

**Ownership:** the new repository owns Redsun sessions, presenters/views,
managed device services, device clients and application acquisition composition.
Preserve upstream typed discovery/wiring, built-in controls, plan maps/actions,
callback selection, run nesting, ROI/exposure behavior, locks, napari hooks,
service-side Zarr assets, lifecycle and engineering checks where applicable.
The instrument bundle continues to own physical profiles, firmware, wiring,
calibration, execution policy and acceptance evidence. Its existing
`04_code/ix83_acquisition/` implementation is a temporary Pycro-Manager
compatibility and qualification path. Planner remains an installed reusable
Bluesky library. This repository uses its bundle-local `../sample_search` source;
the planner is a registered bundle submodule with origin
`https://github.com/deanziyangyu/redsun-planner.git`. On 2026-10-18 the bundle index and local planner HEAD both recorded
`95e35aaf16c9bdcaa463344fa2c2cef24bf4422a`; remote CI and the wheel refresh
reported then apply to that source. The 2026-10-21 documentation audit finds
planner HEAD `2c863cb3b18b9aa82e53dc4a6ec583300e856153` with staged source
edits, while the bundle index still records `95e35aa`. The app HEAD is now
`9792619566cbc46452bac006c302c18e9d81201b`, versus index `8365ac4`.
Neither checkout identity establishes the currently installed planner wheel. This source pin
does not make the consumers' non-editable sibling-path dependencies portable or
identify their installed wheel contents when the planner worktree is modified.
The planner now owns a committed `uv.lock` for its development checks. Standalone
consumer installation/CI and an immutable distribution reference still need
validation. RTASPT retains reusable processing ownership.

**Establishment checks:** the renamed project lock resolves with unchanged registry versions; source/wheel builds, CLI/plugin packaging, Ruff, strict PyQt6/PySide6 typing and 101 hardware-free tests pass. Twenty-two demo-adapter/OpenGL tests are skipped. Documentation checks pass; Mermaid was checked structurally but not rendered. This is software establishment evidence, separate from IX83 runtime, graphical session and physical acceptance.

**Port started:** installed `redsun-planner` recipes now flow through
`acquisition.bind_snap_scan()` into Bluesky messages bound to a supplied stage and
camera; metadata preserves planner boundary identity. The Ludl `OxiSerialSession`
transport is ported into `device/ludl/`, with host-call timing, bounded raw reads,
serialized exchanges and explicit close semantics. Fake-device/port checks are added.
**Implemented in Redsun presenter:** `PlannerPresenter.plan_map()` registers a
geometry-only snake-snap preview in the AcquisitionView. It records proposed
positions and coverage metadata and issues no device commands. The bounded
2×2 Presenter snap qualification also runs against managed mock XY and
DemoCamera services over loopback PVA: four stage readbacks and four fresh
image-buffer arrays are emitted in position-associated Bluesky events. The
Presenter document callback now persists inline snap events to a Zarr image
stack and writes a matching position/ROI sidecar; a mock acquisition has
round-tripped that stack through saved-stack review. Combined physical
PVCAM/Ludl acquisition subsequently produced a 225-frame 15x15 scan in the
[physical rehearsal record](../08_session_logs/20261017T_physical_redsun_rehearsal/README.md).
Registration quality, physical scale and specimen FoV acceptance remain pending.
The Presenter also now has an opt-in in-process Demo broom path through
`LiveRun` into RTASPT's live slit processor. A five-strip run produced 153
frames/observations, per-strip TIFF products, and a passed run-integrity check;
the requested four-frame TDI depth was limited to two by the simulated slit
residence. This validates the software data path only. See the [run
record](../08_session_logs/20261019T_redsun_demo_broom_rtaspt_live_01/README.md).
For completed MMCore broom data, the app now has an offline helper that joins
the recorded geometry/context export to RTASPT Zarr replay; its physical speed
input remains a declared scenario value and pose timing is not yet calibrated.
The helper completed on a copied 20-frame managed Demo strip, producing
20 operating-point observations and 14 four-frame TDI planes; physical timing
and pose qualification remain pending (see the [bridge validation record](../08_session_logs/20261019T_redsun_broom_rtaspt_bridge_validation_01/README.md)).
The Redsun application composes a typed bounded Ludl XY device through MMCore
and starts it in its managed service; small physical qualification of standard
Ophyd moves passed on 2026-10-17 (see the [bundle Ludl qualification
record](ix83_ludl_stage_qualification.md)). The limited saved-snap review flow now exports a standalone checkpoint page, validates an exported decision, and composes a bounded selected-target revisit plan against the exact source files. A separate Presenter action fits stage-prior overlapping tile pairs, solves a weighted placement graph, and records registration-versus-hand-eye positions. Another offline action exports a downsampled mosaic, coverage map and labeled placement map. The checkpoint can optionally consume the verified registration record: it checks exact run, sidecar, calibration, camera-mode and frame-hash lineage, applies registration residuals before target deduplication within multi-tile graph components, and leaves singleton components at their stage-prior positions. This refines candidate placement; biological review and physical qualification remain outstanding. A shared structured preflight now records structural capabilities and host-supplied checks. Snap/broom geometry previews emit scoped geometry reports; reviewed-target and snap-grid execution share a pure relative-XY envelope check, which the native broom plan also records. Bounded snap and native broom plans accept direct absolute XY limits or an optional limits-profile path; profile mode matches camera and stage against Redsun session device names, checks camera mode and stage calibration before using its bounds; the camera name is not hardware-unique. The profile checksum and live identity context are recorded. Profile evidence resolution, freshness and safety margins remain caller-owned. These reports do not establish device readiness. **Still planned:** general recipe binding, broader Presenter review/acceptance and comprehensive capability/physical-limit/resource preflight; biological RTASPT qualification with exposure- and pose-linked data; qualifying cancellation, resource policy and scan-level hardware limits; and calibrated physical acceptance. The registered-support coverage review now has a dedicated dock and
hash-checked preview path. The saved-snap checkpoint HTML also opens in the
Plan review dock when Qt WebEngine is available, with a system-browser fallback
when unavailable or when the embedded page fails to load;
full GUI acceptance remains pending. Its data and geometry are covered by the focused
headless regression, but its Qt dock has not been instantiated in a normal GUI;
the offscreen smoke cannot load Qt bindings in the Codex Windows sandbox. See
the [coverage-preview evidence](../08_session_logs/20261017T172857_focused_headless_test_run/README.md).
The separate native
serial path is an experimental protocol slice: `OxiSerialSession` now supports
length-framed MAC6000 messages, the codec reads position counts and
`REPORT_STATUS_POS`, exposes read-only current module ID/version/type registers,
and has an explicit read-only probe CLI; all are hardware-free tested. The CLI
opens serial only when invoked and never sends motion/configuration commands. A
calibrated XY facade now requires explicit module IDs and per-axis
calibration, captures a startup position and enforces a ±2 mm software envelope;
paired changed-axis targets use a masked global start command. A separate opt-in FastCS/PVAccess native-stage
service is registered. A hardware-free integration test now drives its FastCS
axis I/O through the real calibration, MAC6000 codec, and OxiSerial framing
against a fake serial peer; it confirms count targets, µm readbacks, hard-stop
  frames, and session close. A spawned child fixture now exercises startup reads
  and shutdown cleanup. The two managed PVA tests failed before readiness in the
  Codex sandbox, but passed in the focused normal-host run: **16 passed**,
  including startup/shutdown, timed-report register setup/readback/restoration,
  host-bracketed telemetry through PVA into the Ophyd stage port, and bounded
  endpoint motion against a fake serial peer. The native PVA gate is therefore
  passed for hardware-free service integration; see the [timed-report PVA evidence](../08_session_logs/20261017T210303_full_test_run/README.md).
  An opt-in idle event reader now supports timed-report telemetry and paired-move
  status demultiplexing. Axis mapping, the controller's
  selected wire mode, measured count-to-distance calibration
  and physical qualification remain pending. A user-authorized read-only COM22
  probe on 2026-10-17 queried candidate module IDs 1 and 2 successfully; both
  returned firmware raw value 87 and position counts -256240 / -47029. This
  confirms query-path communication only, not axis identity or calibration.
  A later user-authorized read-only ASCII check on COM22 at 9600 baud received
  the `WHERE X Y` reply `:A -270056 -23554 ` without sending a mode selector.
  Its first parser rejected the trailing space and stopped after that single
  query; the parser was corrected and now has an offline regression. No other
  ASCII command or any motion/profile/stop/mode write was sent. The newer raw
  counts are not calibrated or directly comparable to the earlier binary
  counts until units, mode and position semantics are established. See the
  [read-only ASCII probe record](../08_session_logs/20261018T013222Z_ludl_ascii_readonly_probe/README.md).
  After that parser fix passed the offline regression suite, the same
  read-only query set succeeded without a selector: both axes reported not
  busy, `SPEED=100/100`, `STSPEED=1000/1000`, and `ACCEL=4/4`. These agree with
  the source-derived MMCore values for the captured profile. This establishes
  command and readback parity at current settings, not motion or ramp parity;
  no setting or motion was changed. Raw bytes showed that replies end in LF;
  changing the expected host terminator reduced `WHERE` round-trip from 516 ms
  to 16 ms and profile reads from about 500 ms to 31-32 ms. A subsequent
  100-sample read-only 50 ms polling run measured 47 ms median start interval,
  63 ms p95/max, and 15.5 ms median query time; status remained idle and final
  raw XY matched the starting point with a one-count transient in Y. See the
  [cadence evidence and plot](../08_session_logs/20261018T014333Z_ludl_ascii_poll_cadence/README.md).
  This short capture is not a hard real-time guarantee. The 9600 baud result above is a historical 2026-10-17 observation. On 2026-10-19 a read-only COM22 `BAUD 1` query at host 115200 8N2 returned `:A  115200`; checked-in COM22 profiles and active Redsun defaults now use 115200. Link configuration and read-only ASCII polling are verified; matched-rate physical motion timing remains unmeasured. See the [polling comparison](../08_session_logs/20261019T_ludl_baud115200_performance_01/README.md). See the [read-only verification record](../08_session_logs/20261019T_ludl_baud115200_readonly_verify/README.md). The next hardware parity gate is a
  separately authorized, small bounded move with before/during/after XY and
  timing measured against MMCore at the same configured profile. The current
  headless/offline regression passed 203 tests, skipped one, and deselected
  three; log: `../08_session_logs/20261017T215300_focused_headless_test_run/pytest-focused-headless.log`.
  See the [native Ludl
adapter assessment](ludl_serial_adapter_design.md)
for implementation and test details. The native serial adapter is integrated
into the adopted Redsun application as a separate stage backend. The signed
legacy-ASCII MMCore/serial comparison closed the stage parity gate on
2026-10-19; use the serial `ludl_stage` path by default for new physical scans
and calibration. MMCore Ludl is an explicit comparison/reference path. Native
binary MAC6000 operation remains a separate qualification gate. Inherited
per-device FastCS/PVAccess processes remain the
baseline topology.
One session/RunEngine owns command policy; device services perform delegated I/O.
Additional planner/processing services require measured need. This adoption does
not transfer donor runtime or physical acceptance to IX83.

## Authority and status

IX83-Automation is the instrument integration project; IX83-Selfdriving-Bundle is the current checkout name. The primary acquisition architecture and mainline implementation are [redsun-searching-is-imaging](../03_external/redsun-searching-is-imaging/README.md), derived from upstream redsun-mimir main. The bundle-owned [sample search workflow research](sample_search_workflow_research.md), especially sections 7-15 and its section 0 status assessment, remains supporting reusable-workflow/processing research and proposes verification cases. It does not supersede the inherited acquisition application architecture.

Historical external documentation audit: 2026-10-04, RTASPT checkout commit `56a09dd487fc48e267f88605470fea74d54597dd`. This records the inspected checkout, not a tested release or a changed submodule pin. Supporting references are its [architecture](../03_external/Realtime-Anisotropy-SPT-Analysis/docs/architecture.md), [input contracts](../03_external/Realtime-Anisotropy-SPT-Analysis/docs/data-input-contracts.md) and [removed live-workflow record](../03_external/Realtime-Anisotropy-SPT-Analysis/docs/live-acquisition.md). Current source audit (2026-10-18): RTASPT HEAD is `61d2dfbb339174629e1362b67ceb3800d5ece0a7`; its CLI accepts only `argv`, and the acquisition modules/factory hook are absent.

**Existing artifacts:** numbered directories, module descriptions, optical schematic, Micro-Manager profiles, shutter firmware and auxiliary scripts. Their presence does not establish current-PC hardware acceptance.

**Python environment ownership:** each independently managed project has its own interpreter environment and lock. The dated machine-local inventory is in [Python environment inventory](python_environment_inventory.md); this covers the primary Redsun app, reusable planner source, temporary IX83 acquisition host, RTASPT, and the upstream source-review checkout. Use Python 3.12 for IX83 bundle operation; Python 3.8 is prohibited. Environment status snapshots do not replace the project lockfiles or establish future runtime health.

**Implemented in this setup:** [ix83_acquisition](../04_code/ix83_acquisition/README.md) is a small local Python package with camera/XYZ-stage protocols, stage-aware mocks, optional Pycro-Manager Core adapters, free-run/finite acquisition lifecycle, bounded preview, cooperative cancellation, capture metadata, channel/timepoint MDA settings and an injectable RTASPT backend adapter. Dependencies are locked locally; no PyPI publication is required. Basic demo ZMQ and hardware-free lifecycle checks pass; physical IX83 acceptance remains unverified.

**Implemented recording/handoff:** `RunRecorder` writes raw NPY planes incrementally with a checksummed JSONL frame ledger and final run manifest. Cancelled/failed runs retain their recorded prefix; captured and recorded counts remain distinct. Replay supplies actual `YXPlane` objects to RTASPT's `IterablePlaneInput`. RTASPT's original acquisition runner and TIFF writer also passed a check using the local backend, with pixel-identical raw output and matching event counts. This is a local interchange baseline, not a frozen published microscopy format.

**Historical frontend hooks (2026-10-04; removed from RTASPT on 2026-10-17):** RTASPT's former CLI, napari launcher and finite MDA runner accepted a caller-owned backend factory. The bundle launcher supplies local mock devices or explicitly selected demo-only Core adapters. The actual RTASPT controller passed free-run/stop and three-frame MDA with runtime exposure refresh and pixel-identical raw output. These checks described then-uncommitted changes against the historical RTASPT commit above; neither that frontend nor its default backend remains available in current RTASPT. The local mock launcher requires a single detector and does not simulate dual/split polarization optics.

**Implemented sample-search prototype:** [03_external/sample_search](../03_external/sample_search/README.md) provides reusable `redsun-planner` recipes, calibrated geometry/calculation helpers, modular Bluesky plan generators, review metadata and hardware-free run/checkpoint records. The canonical import is `planner` in a `src/` layout; the former `samplescout` shim was removed, so `planner` is the only importable name. `redsun-planner` is a reusable library of building blocks that wrap Bluesky plan stubs or provide customized subplans. Its Bluesky plan interface can support non-Redsun hosts through compatible adapters, maintained as supporting examples or skills. The package requires Bluesky but no Redsun runtime. Interoperability with Blop and `bluesky-adaptive` is a design target whose current API contracts remain to be validated. The planner creates no RunEngine and owns no instrument devices. The bundle-owned host in [04_code/ix83_acquisition/src/ix83_acquisition/scan_host](../04_code/ix83_acquisition/src/ix83_acquisition/scan_host/) owns orchestration transitions, action execution, device calls, resource arbitration, recording/storage coordination and cancellation. A local wheel is built and installed in the Python 3.12 acquisition integration environment. A checksummed review checkpoint pauses after survey/detection; a local HTML page displays saved images and accepts target selection and manual additions with reasons. Context, bounds and freshness checks precede resumed revisits. Seeded specimen acceptance, a 12-tile mock integration with 15 recorded movie planes, and a saved-checkpoint review/resume check with nine movie planes pass. **Implemented in the adopted Redsun application:** the AcquisitionView registers geometry-only snake-snap and observed-coverage previews; the latter verifies the support TIFF dimensions and SHA-256 before displaying registered support, proposed footprints, misses and overscan. Bounded snap execution persists Zarr images with a frame/position/ROI sidecar. Broom recipe, coordinator, native-stage/MMCore-camera binding, Presenter entry and managed-Demo path are also present. The focused Codex headless regression records 81 passed and one optional Micro-Manager adapter skip; software tests do not qualify camera-to-stage timing or physical scan behavior. **Still planned:** independent upstream release, Presenter plan-block metadata consumption and host acceptance, complete capability/limit/resource preflight, broader Redsun runtime acceptance, Blop/`bluesky-adaptive` interop, supporting non-Redsun adapter examples/skills, and portable consumer dependency references. The IX83 bundle temporarily adapts supported plan messages to Pycro-Manager.

**Plan-block metadata update (2026-10-20):** the planner catalog now describes all public Bluesky plan generators in `planner.plans`, `planner.search_imaging` and `planner.operating_schedule`. This is runtime metadata only; it does not implement Presenter widgets, device preflight, resource locking or host acceptance. See the [descriptor contract](../03_external/sample_search/docs/plan_blocks.md).

**Planned:** rendered napari acceptance, detector-specific processing parity, wider instrument execution policy, versioned real calibration and calibrated real-specimen sample-search acceptance. RTASPT has removed its acquisition controller; the compatibility host acquisition lifecycle remains independent of RTASPT, napari and Qt.

**Implemented explicit scanning procedure:** stage-grid and target scanning uses the original Beanshell scan behavior as a reference and the bundle host launcher/executor as its backend. Pure recipe/grid-position calculations are in `planner`; execution, readbacks, storage, action journal and bounded cleanup are host-owned. Column-major traversal, optional serpentine/orientation and settling are implemented at fixed Z. The 50 x 25 um real grid saved all six frames and returned to origin within tolerance. Explicit stage spacing needs no inferred optical transform; image coverage and calibrated targeting still require one. This historical mechanical validation remains valid; the import-boundary refactor adds no new hardware acceptance.

**Scanning development increment (2026-10-14):** the [next-action plan](redsun_rtaspt_integration_next_steps.md) prioritizes biological replay with intensity-based fast-search/slow-imaging speed proposals and registered virtual integration/digital TDI. Settled snap-scan and fixed-speed continuous policies remain comparison controls; perfusion is deferred. Pure [bounded scan geometry](../03_external/sample_search/src/planner/bounded_scanning.py) now accepts confirmed two-corner rectangles or ordered convex four-corner bounds, plans snake snapshots and alternating/same-direction broom strips, and constrains complete detector footprints to the confirmed region. Polygon edge coverage is explicitly limited. The [demo workflow](../04_code/ix83_acquisition/docs/scan_workflow/demo_scan_workflow.md) adds CLI corner readback/confirmation and a final execution gate. Four running-Java-Core DemoCamera checks completed: two/four-corner snake scans saved 12 frames each; two/four-corner broom emulations saved 16 frames each. All frames passed checksummed replay, with origin and exposure restored. Broom uses commanded step/readback/snap emulation and declares `continuous_capture: false`; synchronized moving capture and live speed-policy binding remain planned. The [biological replay](../07_experiment_notebook/tools/scanning_replay/README.md) aligns recorded observations into a fixed image atlas, generates synthetic moving exposures over the same domain, and compares latest-frame and weighted integration with modeled snap/slow/fast/adaptive paths. Source and virtual clocks, valid support, score thresholds and inherited blur are explicit. Simulated timing and image-derived geometry do not establish physical motion/blur acceptance. See the [evidence record](../07_experiment_notebook/2026-10-14_scanning_workflow_evidence/README.md) for verification status and exported figures.

**Pose/identity and ROI-gating assessments (2026-10-17):** two offline assessments now bound how observations are placed and how a scan may adapt. The [identity pose estimation assessment](identity_pose_estimation_assessment.md) concludes that identity handoff to RTASPT does not need a full SLAM setup: use a stage-prior pose graph that keeps stage priors and image registration as separate covariance-bearing constraints, with explicit per-strip scale and drift states. The operator-confirmed 0.5 physical-per-reported Ludl correction reconciles the measured 3.8 px/reported-µm image fit with the 7.69 px/µm implied by the accepted 0.13 µm/pixel calibration; physical geometry estimates apply it once. Independent verification of the controller/drive setting remains pending. The MMCore Ludl path still has about 4.7 Hz reporting and an interpolation error (5.6 px median, 16.3 px p90) larger than the 8 px per-frame advance it would need to predict, so exposure-associated pose remains unavailable. The native MAC6000 serial path documents pulse/s² acceleration, timed status reports and typed stop semantics, but it is unqualified. COM22 now uses 115200 8N2; a 300-sample read-only `WHERE` comparison found 16 ms median / 31 ms p95 host-call latency and no material gain over historical 9600-baud polling. Neither path supplies exposure-synchronized pose. See the [baud performance record](../08_session_logs/20261019T_ludl_baud115200_performance_01/README.md). The [in-FOV motion gating assessment](in_fov_motion_gating_assessment.md) covers the control side: under the instrument-owner premise that a specimen is either static or dynamic with a stable level, a rolling-buffer-bounded detector is assessed as a regime classifier whose decision is applied at a boundary. Recorded evidence confines sensitivity during motion to bulk change (compensation residual about 5.6 px median, 16.3 px p90), and every recorded scan is static, so detection performance is unmeasured. The motion-gate assessment now includes partial E1 evidence from the 2026-10-20 static leave-one-strip-out probe: global residual medians were 0.54–0.66 px, while local-block residual medians were 3.40–5.13 px. The same-scan fitted prior is not an accepted calibration or a detector sensitivity floor. First define E0 sensitivity and labeled controls, then complete E1 prior/uncertainty qualification before E2 false-alarm and E3 injected-motion evaluation. No motion classifier or adaptive acquisition is accepted; see the [E1 analysis](../08_session_logs/20261020T_in_fov_motion_gate_E1/README.md).

**Real-time processing and storage assessment (2026-10-17):** six parallel investigations plus a bundle sweep are consolidated in the [real-time processing and storage assessment](realtime_processing_and_storage_assessment.md). It finds that measurement and geometry can keep up with a live scan but actuation and display cannot: a content metric over eight candidate widths costs 1.42 ms, but a camera ROI write stops the sequence and the store shape is frozen at the first frame; per-pair ECC at downsample 4 costs 9.3-10 ms against a 20.03 ms frame, while the recorded native-resolution pipeline runs at 1.9x real time and falls behind; Trackpy localization at 1024² with 573 features costs 218 ms/frame, so only a reduced ROI or a GPU backend fits; the viewer receives one queued texture upload per frame with no drop policy; and the camera store is plain Zarr with the time axis unbounded, so a live reader needs a commit sidecar rather than the metadata shape. It recommends a per-strip worker plus a coalesced preview, keeps stitching out of the acquisition plan, and treats the Redsun `tiled`/`ome-tiled` path as a publishing layer rather than a live reader; a per-strip OME-Zarr store preallocated through `ome-writers`, with a commit cursor and `ome-tiled` serving, is the adopted serving path in the 2026-10-17 update below. That assessment predates the current app worktree: bounded live capture, injected processing and local Tiled serving now exist under `acquisition/live/`. Hardware/runtime qualification remains separate; use the current [implementation order and gates](redsun_rtaspt_integration_next_steps.md#immediate-order), not the historical absence claim.

**Real-time compute with a working GPU path (2026-10-17 update):** CuPy is now installed in the RTASPT environment as `cupy-cuda12x` 13.6.0 with NumPy held at the locked 1.26.4, and measured costs replace the earlier CPU-only estimates. The live median is a gated, geometry-bounded product rather than a per-frame obligation: a flatfield is either a loaded reference (0.33 ms divide) or a median fitted only on intensity-gated accepted frames, amortized to about 4 ms per accepted frame, and the SPT window is the slit's own parallelepiped (`N_obs = w_s/(v T_f)`), where a (16, 128, 1024) volume gives a 0.81 ms GPU median, 0.22-0.33 ms en-face projections and 0.87 ms shear accumulation, against 33.6 ms for a full 1024² window. Digital TDI is 0.38 ms per four-frame sum, and 1-D line deconvolution along the motion axis is 1.07-2.73 ms per GPU iteration, so deconvolution is no longer compute-limited; it now lacks evidence, and a new exposure sweep is required before any brightness or blur claim. The plain-Zarr per-frame archive remains the crash-tolerant capture store. The resident bounded ring buffer and the per-frame composition now exist as RTASPT library code (`resident.py`, `liveproc.py`), and the [slit processor placement assessment](slit_processor_placement_assessment.md) keeps them there: pixels stay in RTASPT, while a scalar metrics record crosses to the planner's policy and the framework's coordinate model. The separate [plan-generation placement assessment](optimization_plan_generation_placement_assessment.md) puts the lowering from an operating-point request to Bluesky messages in `redsun-planner`, with the framework owning the cube model and the host executing. Every GPU claim remains a benchmark on this host, not an acquisition or physical acceptance.

**Runtime identity for the 2026-10-14 Pycro-Manager demo verification:** Pycro-Manager 1.0.2/PyJavaZ 1.2.8 connected to the operator-created and loaded MMStudio Java Core 12.5.0 configuration, Device API 75, with the adapter search path identifying `Micro-Manager_2.0.3_20260225` under the local `pymmcore-plus` installation. This is historical evidence for that MMStudio/Pycro-Manager run, not the current Redsun runtime selection. The Python lock pins `pymmcore==12.5.0.75.0`; it does not lock external Micro-Manager adapter DLLs.

**Historical IX83 Redsun MMCore runtime note (2026-10-17; superseded for current ix71):** the IX83-era check recorded the `C:/Users/YipGroup/AppData/Local/pymmcore-plus/pymmcore-plus/mm/Micro-Manager_2.0.3_20260420` adapter bundle (Device Interface 75), selected by `pymmcore_plus.find_micromanager()` for locked `pymmcore==12.5.0.75.0`. This is historical evidence for that setup; it is not the current ix71 runtime. The current ix71 plan and the user-authorized 2026-10-24 Redsun host-side check identify `C:/Users/yipgroup/AppData/Local/pymmcore-plus/pymmcore-plus/mm/Micro-Manager_2.0.3_20260821` as the selected adapter bundle. Use the ix71 record for current laser work and do not transfer the IX83 path to ix71. The `C:/Program Files/Micro-Manager-2.0` installation reports Device Interface 70 and is incompatible with Redsun's locked MMCore; do not select it. The user clarified that the 20260828 nightly was installed by overwriting executables in the directory still named `C:/Users/YipGroup/AppData/Local/pymmcore-plus/pymmcore-plus/mm/Micro-Manager_2.0.3_20260225`; its observed MMCore/adapter DLL timestamps of 2026-08-29 are consistent with that. Retain this overwritten bundle for separate MMStudio validation, not for ix71 runtime discovery. Redsun starts and owns its own MMCore instance through its managed device service; MMStudio is not required for Redsun. Only concurrent ownership of COM22 prevents both from controlling the Ludl at once. See the [environment inventory](python_environment_inventory.md) for the historical paths and discovery evidence.

**Authorized Ludl diagnostics (2026-10-14):** the operator loaded the [real Ludl with DemoCamera profile](../04_code/02_mmcfg/ix83_ludl_democam_mmconfig.cfg) and limited XY motion to ±2000 µm about the initial readback. The bundle-owned [finite-motion host](../04_code/ix83_acquisition/docs/scan_workflow/ludl_motion.md) validates that profile, retains the original envelope across resumed runs, separates command acknowledgement from completion, and checks stable idle plus target readback before accepting completion. Unknown outcomes block further actions until reconciliation. The [investigation notebook](../07_experiment_notebook/2026-10-14_ludl_timeout_investigation/README.md) preserves the complete pre-motion Ludl/COM property snapshot associated by the operator with the biological movies, adapter DLL hashes, timer/source audit and physical traces. The 50 µm X/Y checks passed after a settling-related first failure was preserved and reconciled. Long-move waiting and in-motion speed updates are separate diagnostics; coordinated moving-camera capture and intensity-driven hardware execution remain planned. This uses demo Z and issues no physical Z or illumination commands.

**Ludl diagnostic outcome:** a 5 s Core completion wait timed out while the bounded move continued and reached its target; the same wait with 60 s succeeded, with serial AnswerTimeout=50 s throughout. A 3000 µm traverse between −1500/+1500 µm endpoints completed in 29.594 s. Valid-range mid-MOVE Speed changes 200→100 and 100→200 changed controller property readbacks without the requested velocity transitions in the sampled position traces. Smooth live blending is not accepted for this tested adapter/controller combination; use pre-move settings with explicit segment overhead until another controller capability is characterized. Final stable XY was within 0.1 µm of the original anchor, and Speed=10, StartSpeed=100, Acceleration=4 and Core timeout=60 s were restored. This remains limited mechanical evidence, with no optical or synchronized moving-camera acceptance.

**Redsun native Ludl integration (updated 2026-10-18):** the native OxiSerial MAC6000 binary and legacy ASCII adapters, managed FastCS/PVA services, and `PlannerPresenter` plans are already implemented in `03_external/redsun-searching-is-imaging/`; the application is the shipping target. Do not duplicate the bundle transport module into the app. The native `LudlSerialStage` now satisfies the shared snap-plan XY contract, and its plan-spec regression exposes both MMCore `XY` and native `ludl_stage` as snap-stage choices. The coordinated broom plan remains paired with the MMCore camera backend. The app was also rerun as a headless managed Demo session through the Redsun RunEngine: a three-strip serpentine completed with 20/26/25 simulated frames and Zarr readback. This validates session, Presenter plan execution and storage only; the Demo session has no physical Ludl or camera and does not establish native motion acceptance. Two further hardware-free managed runs now exercise the native stage itself against the fake MAC6000 serial peer plus the DemoCamera service over loopback PVA: the 2x2 snap qualification (four 512x512 Zarr frames at the expected snake positions, position sidecar, return to anchor) and the three-strip coordinated broom (14 frames per strip, geometry and telemetry sidecars, return to anchor). Those runs exposed and fixed an MMCore-camera broom ordering gap: the camera stream descriptor was available only after a per-strip prepare, while Bluesky declares the stream first. The focused Codex-safe headless suite passed 223 tests, skipped one optional adapter test and deselected three managed PVA child tests. A separate operator-authorized physical probe used a direct OxiSerial legacy-ASCII client with the Redsun PVCAM service to capture five frames around separate +100-count X/Y moves and measured-count returns. It measured a provisional image-content matrix of `[[0.0144, -0.7648], [-0.7888, -0.0092]] px/raw count` and 90.35° axis angle; both requested moves settled at +102 counts, X returned to anchor and Y had a −2-count residual. This establishes ASCII stage-to-camera image-space mapping for that run, not the native MAC6000 binary service path or physical µm/count: objective and binning were not read. Evidence: [Demo scan](../08_session_logs/20261018T0550Z_redsun_managed_demo_scan_02/README.md), [native fake-peer scan](../08_session_logs/20261018T_native_ludl_scan_01/README.md), [physical ASCII calibration](../08_session_logs/20261018T0522Z_native_ludl_count_image_calibration/README.md), [latest read-only port check](../08_session_logs/20261018T_native_ludl_continuation_01/README.md), [focused suite](../08_session_logs/20261018T015509_focused_headless_test_run/README.md), [full-suite result](../08_session_logs/20261018T030549_full_test_run/README.md), and [native adapter design](ludl_serial_adapter_design.md). The bounded +100-count authorization is consumed. The larger survey or native-binary physical scan remains gated on objective/binning readbacks and physical scale/reference, verified binary module-to-axis mapping and `INVALID_PARAM` interpretation, profile preflight, a bounded area inside ±2 mm, and fresh run-specific authorization. Keep MMCore as the behavioral reference until that native binary comparison is complete.

**Paired MMCore/legacy-ASCII comparison (completed 2026-10-19):** the authorized sequential test used the standard MMCore `SerialManager`/Ludl composition and Redsun's OxiSerial legacy-ASCII client against the same physical controller, preserving baud, motion profile and camera/IX83 settings. Three repetitions of signed ±100-count-equivalent X/Y legs and measured returns were completed per backend, followed by nominal 5 µm comparisons. Directional movement means agreed within 0.67 count; each individual return residual was at most 2 counts. The 5 µm probe exposed the key unit distinction: MMCore's software-default `StepSize-X/Y = 0.1 µm/count` yields about 50 counts, while the native provisional 50 nm/count model requests 100 counts and observed about 102. This is evidence of a factor-of-two adapter/model mismatch, not independent physical calibration. ECC image registration produced similar local mappings (0.94 px MMCore and 0.63 px native fit RMS). Final readback showed a small residual; no extra recenter was authorized or sent. COM22 was released and stage idle at final read-only preflight. Camera initialization state before this run was unknown because a fresh PVCAM device was created without loading a profile; no explicit camera-property writes occurred. The complete result and limitations are in the [paired comparison evidence](../08_session_logs/20261019T_ludl_signed_backend_comparison/README.md), with design implications in the [native Ludl adapter design](ludl_serial_adapter_design.md). This closes the signed legacy-ASCII parity gate and its manifest-to-run gap. It does not qualify the native binary service, physical µm/count, speed/acceleration parity or large-area scanning.

**Remaining Ludl qualification:** use serial legacy ASCII as the default stage path for new physical work; retain MMCore for explicit comparison/reference. The initial full-frame ECC fit was weak (median correlation about 0.44) and underestimated shifts; reprocessing both the 2026-10-18 positive-only frames and the 2026-10-19 paired frames with the same centered crop ECC gives matching row norms of roughly 0.75–0.79 px/count. The canonical setup is an Olympus UAPO N 100×/1.49 TIRF objective with system magnification fixed at 1.0. The paired run camera readback was 1×1; applying the accepted 0.13 µm/px calibration at 2× binning and scaling for the binning gives 0.065 µm/px, yielding an image-derived estimate of 48.6–50.9 nm/count, within 2.8% of the provisional 50 nm/count claim. Ludl's BioPrecision2 inverted-stage LE2 sheet lists 50 nm minimum resolution and 0.20 µm repeatability, but no LE2 accuracy value; this is consistent with the resolution claim, not an accuracy qualification. The objective was not read back during the paired run, and no independent length standard was used, so retain the optical conversion as image-calibration-derived rather than an independent stage measurement. The stage label suffix remains uncertain. The next scale gate is an independent physical length reference; camera binning must be read from the active setup for each qualification run. A later legacy-ASCII/MMCore profile sweep is recorded in the [current next-action plan](redsun_rtaspt_integration_next_steps.md#immediate-order); it provides finite-move and host-polled count-rate evidence, not independently calibrated physical rates. Next establish an independent length reference and the configured controller-rate ceiling before qualifying scan-speed limits. The original matrix remains in [the speed/ramp qualification plan](../07_experiment_notebook/2026-10-14_ludl_timeout_investigation/native_motion_followup.md#speed-and-acceleration-calibration-plan-priority-update-2026-10-18). Keep speed/acceleration writes separate from active moves; compare measured trajectories, not property readbacks. Qualify the native binary service after its status/axis mapping gate. Any additional physical move or profile write needs fresh run-specific authorization.

**Native session-profile gap (2026-10-18):** the app's `ix83-native-ludl`
command still requires `--session-config <path>`, and the app contains no
packaged `ix83_native_ludl.yaml`. This is a Redsun session profile, not a
Micro-Manager Studio `.cfg`; the camera service declares its adapter/device and
the native stage uses no MMCore adapter. If “compose the configuration during
the run” means no operator-supplied Redsun YAML either, that requirement is
still open. Do not invent a packaged calibration: module mapping, camera
binning and per-axis physical scale/reference remain unverified. The canonical
optical setup is the Olympus UAPO N 100×/1.49 objective with system
magnification 1.0; record this declared configuration in the profile and read
actual camera binning from the active session.
Resolve this with a measured, versioned instrument profile and a runtime
composer before physical native-stage use; see the [adapter design record](ludl_serial_adapter_design.md).

**MMCore protocol comparison update (2026-10-19):** official `Ludl/XYStage`
source shows the standard MMCore reference uses legacy ASCII `MOVE`, `WHERE`,
`STATUS`, `SPEED`, `STSPEED` and `ACCEL` calls. The checked local profiles
select this standard `Ludl` adapter on COM22. The separate `LudlLow` adapter is
documented as incomplete and untested; its current source disables XY-stage
registration/construction, uses legacy MAC2000/5000 low-level bytes for
peripheral devices, and retains ASCII commands in its unregistered XY class.
It is not evidence that selecting `LudlLow` improves stage polling.

The bundled [90M061 MAC6142 manual](09_ludl_manuals/90M061-mac6142manualb.pdf)
distinguishes high-level ASCII, legacy MAC2000/2002/5000 low-level commands,
and direct MAC6000 binary commands. It
says old high/low mode-switch sequences are ignored by MAC6142 and valid
commands from all three formats are accepted; direct MAC6000 binary messaging
avoids interface translation and is described as fastest. This exact behavior
is conditional on the installed interface actually being MAC6142; the saved
snapshot only establishes a MAC6000 Interface, USB/ETH, firmware 13.500, so
confirm the module identity before applying the manual as the installed wire
contract. Use a read-only `VER *` during the next exclusive COM22 session to
capture the full interface/module version report; the saved `VER` property
does not identify an exact interface model. Do not conflate the `LudlLow`
legacy packets with MAC6000 binary
frames. The signed MMCore-versus-Redsun legacy-ASCII comparison is now complete;
see the paired comparison result above. The better future timing candidate is
qualified direct MAC6000 position/event messaging, after its interface/module
identity and terminal-report behavior are established.

MMCore `Speed`/`StartSpeed` are µm/s properties converted through
`StepSize-X/Y`; `Acceleration` is a 1–255 legacy control, unlike the native
profile's pulse/s² registers. These controls are not mapped by matching names.
With the recorded 0.1 step size, source arithmetic maps the saved Speed 10 and
StartSpeed 100 settings to legacy target rates of 100 and 1000 controller
steps/s; that is not a physical-speed measurement. No source-based conversion
from Acceleration 4 to native pulse/s² is established. The upstream source
review, manual distinction and completed comparison are recorded in the
[native adapter assessment](ludl_serial_adapter_design.md) and [paired adapter
review](../08_session_logs/20261018T_ludl_adapter_source_review/README.md).
Keep direct binary control opt-in and MMCore as the reference until the
installed interface/adaptor revision, protocol, scales, bounded endpoint
behavior and motion profiles have matched evidence.

**IX83 laser/shutter serial adaptation (updated 2026-10-17):** `LaserUI.bsh` now has a direct Oxiserial service path in `redsun-searching-is-imaging`, surfaced through its Redsun light device. The physical 561 channel on COM10 identified as SMD12/6H firmware 3.1.0 (`VERSION?`); ON returned controller status ENABLED, and the operator confirmed emission while the shutter blocked the beam. `POWER?` returned −0.2 mW, so that readback is not reliable evidence of optical output here. The COM5 MMConfig 20/21 probe was physically confirmed to move the 561 shutter; response text was not read, so installed firmware and reply behavior remain unknown. These observations verified the 561 command dialect and shutter travel, not calibrated power or interlocks. The Redsun commissioning session now declares only 561; its laser and manual shutter controls remain separate. Its opt-in per-laser auto-shutter checkbox now links to bounded snap scans: checked runs enable emission behind a closed shutter and cycle the shutter around each completed snap, closing before stage motion; normal completion restores the original emission command state, while stop, abort or error requests shutter-close and laser-off. Eleven isolated hardware-free checks cover checkbox selection, readable and streamable snap ordering, dark cleanup and a whole-broom shutter interval through stream drain. The broom binder can hold the shutter open for the whole acquisition, but no physical broom Presenter plan exposes it; the synthetic replay remains hardware-free. The Codex sandbox cannot import the installed PyQt6 QtWidgets DLL (access denied), so actual QWidget signal delivery remains unverified. The already-running physical session predates this change and needs reload plus 561-only UI verification. The service supports explicit legacy no-acknowledgement mode for this command-verified channel, reporting command state only. Other heads, fourth-channel 640/670 identity, and Redsun-managed physical service operation remain unqualified. COM22 remains Ludl. See the [Redsun laser/shutter migration record](ix83_laser_shutter_migration.md) and [physical rehearsal log](../08_session_logs/20261017T_physical_redsun_rehearsal/README.md).

**Mixed Ludl/DemoCamera snake execution (2026-10-15):** the operator created and loaded the mixed configuration in the intended Micro-Manager installation. A fresh read-only Core preflight confirmed MMCore 12.5.0 / Device API 75, Ludl XY on COM22, DemoCamera camera and Z, stopped Live, disabled auto-shutter, and the current Ludl property readbacks. After the operator confirmed E-stop/travel limits and approved a small centered test region, the [bounded workflow](../04_code/ix83_acquisition/scripts/scan_workflow/mixed_ludl_demo_scan_workflow.py) ran a 9-position snake snap-scan and a 3-strip / 18-frame commanded-step broom emulation. The immutable XY envelope was ±2000 µm from the live origin (57829.8, 557.1 µm); maximum observed displacement was approximately 100.2/100.1 µm X/Y. It issued no Z or illumination commands, restored exposure to 10 ms, retained Speed/StartSpeed/Acceleration = 10/100/4, and finished idle within 0.3 µm of origin. All saved-frame and dataset-ledger hashes passed. See the [session log and plots](../08_session_logs/20261015T072614Z_mixed_ludl_demo_snake/README.md). Broom remains emulated: no continuous capture, calibrated optical overlap or biological comparison is established. An initial zero-frame broom attempt exposed an executor-lifecycle issue; the failed record is preserved and the completed continuation is separately journaled.

**Redsun Ludl adapter and managed-service qualification (2026-10-17):** using the designated MMCore 2.0.3_20260420 / Device Interface 75 runtime, the Redsun managed session started the MMCore/PVAccess stage, DemoCamera and demo-Z services, read XY at (−25623.6, −4702.8) µm, and completed standard high-level Ophyd X/Y +50 µm moves and returns. A subsequent bounded 2×2 snake snap plan moved the physical Ludl within a 50 × 50 µm square, produced four DemoCamera event documents at requested XY positions within 0.3 µm, held the 100 ms exposure readback, and returned to within 0.2 µm per axis of its captured anchor. The RunEngine span was 6.347 s (0.63 events/s). No image files were found in the configured stream directory; this measures stage/trigger timing only, not specimen FoV throughput or image quality. No IX83 properties, Z, illumination, speed, acceleration or origin property was changed. The test process exited non-zero during cleanup/finalization after writing its evidence; the exact exception was not retained, and a second movement was not attempted. Next: resolve cleanup and verify DemoCamera stream persistence before using the actual camera path for FoV coverage qualification. See the [bounded scan record](../08_session_logs/20261017T0146Z_ludl_bounded_snap_qualification/README.md) and [per-move smoke record](../08_session_logs/20261017T005611Z_redsun_ludl_hardware_smoke/README.md).

**Historical verification (2026-10-04):** the project-owned acquisition environment used Python 3.12.13, Pycro-Manager 1.0.2, PyJavaZ 1.2.8 and NumPy 1.26.4 from the package's Python 3.12 `uv.lock`. PyJavaZ expected protocol 5.1.0, matching the running Java server. Earlier source-only checks used Python 3.8.10 / Pycro-Manager 0.24.1 and remain historical evidence only.

With the operator-loaded `ix83_demo_mmconfig.cfg`, that environment passed direct capture, XYZ move/readback, worker-based finite capture, bounded preview and free-run cancellation. Direct capture produced three 512 x 512 uint8 frames; stage readback for a +10/+5/+2 um move was within 0.01 um. Three recorded demo frames replayed pixel-for-pixel. Starting XYZ position, camera exposure and binning were restored. Twenty-two hardware-free tests passed, Ruff passed, and strict mypy passed over the package source. A separate Python 3.12.13 environment with the then-locked `rtaspt-check` extra verified RTASPT acquisition and data APIs using NumPy 1.26.4. That extra is retired with the obsolete frontend; these are historical checks, not current RTASPT acquisition support or a released instrument manifest.

**Deferred:** arbitrary concurrent graphs, distributed scheduling, continuous stage scanning, periodic event search, deep-model/optimizer dependencies and LLM integration until a verification case requires them.

**Historical RTASPT frontend verification (superseded):** the 2026-10-04 controller/CLI check passed with 95 tests and 10 skips under offscreen Qt, and confirmed refreshed exposures of 10, 20, 20 ms plus cleanup of both constructed backends. RTASPT removed that frontend on 2026-10-17; its launcher, controller-check script and local compatibility shim are now retired. These results describe only the historical revision. Current RTASPT integration is a recorded-data handoff through the current plane-input interface, temporarily using the RTASPT source checkout because its NumPy requirement conflicts with the IX83 acquisition lock. The [mixed Ludl/PVCAM profile](../04_code/02_mmcfg/ix83_mixed_ludl_pvcam_mmconfig.cfg) uses the existing COM22 serial settings and PVCAM Camera-1, retaining demo Z. Static checks preceded the separately authorized hardware measurements below.

**Limited hardware validation (2026-10-04):** the operator loaded the mixed profile and explicitly authorized real-device validation with a maximum 1 mm displacement on each XY axis. The check enforced a 1 mm-wide envelope centred on the original readback and tested positive 25/100 um offsets, retaining demo Z. Ludl target/readback errors were at most 0.3 um; final XY was within 0.2 um of the starting readback. PVCAM returned 2048 x 2048 uint16 images, completed three-frame recording with pixel-identical replay, and stopped free run cleanly. Exposure was restored; binning and illumination were unchanged. A first attempt stopped at the floating-point boundary of a 0.2 um tolerance; its record was preserved and positions reconciled before returning to the original origin and completing the check at 0.5 um tolerance. This verifies limited software/device operation, not calibrated optical accuracy, shutter/interlock acceptance or fluorescent specimen performance. Details remain in local session records. The package now passes 24 hardware-free tests, including pre-command motion-bound rejection.

**Non-goals for this setup:** physical driver installation, firmware flashing, pin changes, and adoption of the reference project's robotic holotomography architecture. The port includes narrowly scoped backend-injection hooks in RTASPT's owning checkout. Physical access requires separately scoped operator authorization; the limited check above does not authorize broader motion or illumination changes.

**Initial 10 ms throughput stress test (camera-rate storage unqualified):** [full validation](camera_throughput_validation.md) distinguishes requested, received and saved frames. At full 2048 x 2048 uint16, 1x1, 10 ms exposure, camera sequences produced approximately 43.6 fps, while Python drained approximately 31–35 fps with checksums deferred. The existing RTASPT serial runner saved all 64 requested frames without pixel/order loss, at 4.51 fps including audit overhead. A longer sequence overflowed the default 250 MB buffer and received 160/256 frames; all 160 were written correctly. A temporary 512 MB buffer completed 256/256 with exact OME pixels, order and hardware-ID continuity. Buffer size was restored to 250 MB. This is finite-burst evidence, not a sustained camera-rate guarantee or proof of the cause of the earlier reported RTASPT issue. The sequence backend requirements established by this test are to separate complete recording from processing/preview, preserve frame IDs and counts, reject incomplete runs as success, and demonstrate stable buffering and concurrent write throughput at its declared target rate.

**Implemented 20 fps sequence baseline:** the operator selected 50 ms exposure and a 20 fps target. `SequenceRequest` and `AcquisitionController.start_sequence` now own finite fixed-position camera sequences; optional Pycro-Manager streaming retains hardware IDs/source timestamps and fails on gaps, overflow, early termination or stalls. Cancellation stops production and drains its queued prefix. `OMERecorder` writes BigTIFF/OME on a separate bounded worker; queue exhaustion and write errors fail the run, and final requested/received/submitted/written counts cannot silently declare a short run successful. Preview remains bounded and may discard old images independently. The headless CLI defaults to 50 ms, requires explicit real-device selection, checks the loaded profile, never moves stages, and restores the prior exposure after stopping.

**Sequence acceptance (2026-10-04):** the actual camera produced 600/600 frames at 19.99 fps over approximately 30 s, with no Core overflow or hardware-ID gaps. All 600 pages in the 4.69 GiB OME BigTIFF passed pixel-hash replay and actual RTASPT TYX input handoff; observed writer queue depth peaked at one frame. A separately tested native cancellation retained and verified 21/200 frames as a cancelled prefix, stopped the camera and left no unread Core frames. Forty-four hardware-free tests, Ruff and strict source mypy pass. This validates the fixed-position, fixed-channel 20 fps recording baseline; longer stress runs, sequence-aware GUI composition, multichannel/position sequences and processing parity remain pending. The RTASPT GUI acquisition hooks were subsequently removed on 2026-10-17; the native recording path remains exposed through the compatibility host CLI/API.

## Documentation and acceptance recheck (2026-10-21)

The current RTASPT checkout is feature-branch commit
`7a09c4aedfb3974bb52c432289367d486e16ba2b`. Its background processing,
PCC/ECC strip registration and motion-shear library code are present locally;
the [remote monitor](redsun_external_update_monitor.md#audit-2026-10-21-0802-americanew_york)
records incoming branch discovery, not a released or accepted bundle dependency.
Redsun retains host ownership of acquisition, placement and physical commands.
Planner's adaptive-speed/search observations remain calculations and plan messages,
not qualified feedback control.

The [second delayed-shutter bead rescan](../08_session_logs/20261021T0357Z_autoshutter_bead_rescan_02/README.md)
saved nine event-buffer frames and yielded a connected 12/12-edge image-only graph
after noise-reference subtraction (0.125 px cycle RMS on the primary crop).
This is limited capture/registration evidence; it does not accept a hand-eye fit,
the physical count scale, shutter edge timing or measured optical power. The
[headless broom attempt](../08_session_logs/20261021T0516Z_headless_broom_bead_test_01/README.md)
saved 543 frames but the enclosing plan failed during anchor return. Its sampled
registration remained partial (22/35 frames in the largest component), and all
543 events lacked finite exposure-start times. Do not report this as a successful
full scan or exposure-associated pose acceptance. These dated records supersede
the older statement that the running session predates shutter integration; broad
optical/interlock and GUI acceptance remain open.

Prioritize: resolve terminal-state/anchor-return failure without blind retry;
review shutter stream timing and complete connected, repeated matched-footprint
hand-eye comparisons; then qualify exposure/pose clocks and common valid support
before speed/quality claims. Record exact source, wheel and lock identities before
consumer acceptance. None of these next gates authorizes hardware operation.

Private RTASPT benchmark, notebook and sandbox details have been detached from
package guidance into the [documentation review archive](../08_session_logs/20261021T_daily_documentation_review/README.md).
Historical distribution artifacts can still contain earlier private documents;
publication requires a fresh artifact audit after rebuilding from a reviewed tree.

**Superseded 2026-10-25.** The priorities above are replaced by the single
[canonical backlog](redsun_rtaspt_integration_next_steps.md#the-ranked-backlog); this section stays as
the 2026-10-21 record. Where its items landed, stated so a reader can follow the move:

- "Resolve terminal-state/anchor-return failure without blind retry" — on the ix71 the anchor now
  returns 0.000 um across repeated plans and an opt-in pose gate refuses unposed placement captures.
  What remains is that a stopped run still reports `success`, which is the presenter/RunEngine
  stop-result plumbing in [H7](redsun_rtaspt_integration_next_steps.md#h7---operational-robustness).
- "Review shutter stream timing" — the IX83 561 shutter path is not the current instrument; the ix71
  uses the Sapphire 488 laser as the illumination gate on COM4, and the optical edge is unmeasured on
  both (`A9`-`A11`).
- "Complete connected, repeated matched-footprint hand-eye comparisons" — open: no accepted ASI
  hand-eye record exists (`R1`), and the low-contrast field is a project decision (`R2`).
- "Qualify exposure/pose clocks and common valid support" — partial: a camera-side `TimeStampMsec`
  exists at ~47 ms cadence and ~33 ms before service arrival, but no exposure interval does (`A6`,
  `A7`).
- "Record exact source, wheel and lock identities before consumer acceptance" — the RTASPT source is
  committed at `c30d508` and a wheel consumer test passes; the consumer pin and the opt-in extra are
  open (`S5`).

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

1. **Reusable planner package (local distribution; independent upstream release planned):** recipe descriptors, pure grid/geometry calculations, typed observation/result records, review metadata, plan generators and hardware-free replay/checkpoint serialization live under `03_external/sample_search/`. The `redsun-planner` distribution imports as `planner`; acquisition declares it as a non-editable local path dependency, so its wheel and Bluesky dependencies are built/installed from the pinned `uv.lock`. Redsun/Bluesky plan generation and examples are the default user path. Planner owns reusable calculations, proposals, plan generators and framework-compatible run records; it does not own IX83 device calls or the temporary bundle's MM execution policy. The bundle runner remains under `04_code/ix83_acquisition/src/ix83_acquisition/scan_host/`; a bounded combined-XY Pycro-Manager/Ophyd snap binding is now implemented and fake-Core tested, while continuous flyer adaptation remains planned. An independent package release, finalized plan contract and portable consumer dependency reference remain future work; the bundle already pins the planner source gitlink.
2. **Reusable processing (RTASPT):** reconstruction, calibration, anisotropy, tracking and structural analysis. Processing reports observations, not device commands. Camera acquisition, the live controller and the `acquire` CLI were removed on 2026-10-17. Processing-only slit/resident-window APIs now exist; the independently installable processing-package extraction remains planned.
3. **IX83 device integration:** `04_code/ix83_acquisition/` defines minimal camera/XYZ-stage contracts and mock devices; its optional Pycro-Manager adapter and acquisition-only controller have passed basic demo ZMQ and mock lifecycle checks. Its RTASPT backend-factory launcher targets the removed historical frontend, not the current RTASPT CLI. Recorded-plane handoff remains the integration boundary. Consolidating the higher-level lifecycle, execution policy, resource arbitration, physical limits and acceptance records remains planned. Scripts, GUIs and future agents should use the same executor.

### Application ownership and Redsun-compatible seams

**Adopted application foundation; IX83 integration planned:** scanning procedures are authored as Bluesky-compatible plans and the Redsun plugin bundle is the first-class composition target. One active acquisition runtime owns physical commands, execution policy, resource arbitration and cancellation. The temporary IX83 bundle has a bounded combined-XY Pycro-Manager/Ophyd binding for planner snap plans; it is fake-Core tested, not accepted on the live microscope. The mid-term goal is to port the full functional `ix83_acquisition` stack into `redsun-searching-is-imaging`, using its existing session, per-device services, Ophyd-async clients, RunEngine, Presenter plan-map, document callbacks and storage. Keep the bundle implementation as the parity reference while migrating module by module; Pycro-Manager remains a temporary device adapter where needed. Do not create competing command authorities between Redsun, a search IOC, an RTASPT IOC and the acquisition host.

Build `redsun-planner` with import package `planner` around Redsun/Bluesky plan generation and composition as the default. It publishes reusable plan functions, proposals and typed results; the selected run owner decides when device actions execute. Keep Pycro-Manager integration in the temporary IX83 adapter rather than making MM the planner's primary API. RTASPT remains a separately owned reusable processing package: bounded, latency-sensitive operations may be called in-process when timing supports that choice, while the heavier tubular/block pipeline is a candidate for a worker or IOC only if throughput, memory isolation or lifecycle measurements justify a process boundary. Such a service consumes typed block/data references and returns run/target/channel/calibration-linked results; it does not command devices. An independently deployed planner IOC remains an option only if deployment, scaling or lifecycle requirements later establish a need.

The first pass standardizes the current single-channel execution and recorded-data seam. Remaining work includes split-detector/channel geometry and block-processing job/result contracts when their use cases are established. While the bundle stack remains the parity reference, its Pycro-Manager and Redsun/ophyd-async integrations stay in host adapters. As the stack migrates, the acquisition application owns the Redsun/ophyd-async types and session composition; reusable planner and processing packages continue to avoid host-specific device classes in their public APIs. Local sample-search launchers use one isolated `source_bootstrap.py` during migration from the source tree to an installed upstream package. The obsolete `rtaspt_app.py` launcher and backend-factory checks have been removed; a recorded-data-only handoff validator now consumes completed IX83 recordings through RTASPT's plane-input interface. The temporary source overlay is explicit because IX83 pins NumPy 1.26.4 while RTASPT requires NumPy 2.4+; resolve this at the planned processing-package extraction rather than mutate `sys.path` or install incompatible dependency sets together.

The `MedianPresenter.plan_map()` source audit at upstream main commit
`293e8ba0f2f5229eb5ca202e372647dd9338f216` remains historical evidence
([audit record](../07_experiment_notebook/2026-10-15_redsun_planwidget_audit/README.md)).
The whole acquisition application is now adopted as the architecture root and
mainline source in `redsun-searching-is-imaging`. Its presenters retain the
callable/callback and `@continuous`/`PlanAction` composition, alongside upstream
session, service, storage and UI decisions. Bind installed planner blocks there;
assess bluesky-adaptive at that composition layer. Planner retains no hard Redsun
dependency. The audit alone is not runtime compatibility or IX83 acceptance.

Bluesky plan compatibility is the default plan surface. bluesky-adaptive remains optional; planner's recipe and result records remain its own contracts.

#### First contract pass

**Implemented first contract pass (2026-10-04; adapter extension 2026-10-15):** standardize the existing single-channel survey/revisit and stage-scan paths before Redsun composition. The local `planner` source owns reusable recipe, observation, proposal and run records; the acquisition package owns camera/stage contracts and immutable binding capabilities; the bundle host owns typed execution requests, device results, policy, cancellation and storage coordination. The local `redsun-planner` package provides the Bluesky-compatible plan surface; the temporary IX83 host now binds snap plans to a combined-XY Pycro-Manager/Ophyd adapter. Extend its supported contract to continuous flyer capture and matched event/storage records. The host translates recorded datasets to RTASPT's existing YX-plane or block interfaces, which remain owned by RTASPT.

At the host boundary, carry run/recipe/request, specimen, phase, tile/target, coordinate-frame and calibration identity with every device operation and result. Dataset references identify storage format, named axes, shape/dtype, verified frame count, terminal status and manifest integrity. Plane axes are uppercase and named; arrival sequence is distinct from a T coordinate. Capability declarations describe the selected binding, and unsupported recipe requirements fail before physical commands.

For stage-aware scans, seed image alignment from the recorded stage translation and a mode-matched hand-eye calibration. Image correspondences determine pair registration; a rough stage displacement only initializes the search/placement estimate. The hand-eye fit separately relates image-derived translations to measured stage deltas. A provisional or assumed count-to-distance scale can affect the search window or physical-unit conversion, but it does not determine the image-only registration. Missing stage observations block a calibrated stage-to-camera fit and physically interpreted scan, not a clearly labeled image-only registration.

Make this a fixed scan-session startup action using the [stage-to-camera calibration workflow](stage_to_camera_startup_calibration.md): acquire a centered anchor and mode metadata, then run a configurable dense grid with paired images, measured raw stage deltas and return frames. The current Presenter/Planner binding already accepts independent odd column/row counts and X/Y spacing; it makes one snake pass. First compare matched-coverage 3×3 at 50 µm spacing with 5×5 at 25 µm spacing; keep crop, camera mode, specimen, illumination and motion profile fixed. Fit image-derived content translation against measured stage deltas, retain separate image-content and mosaic-placement transforms, report repeatability/covariance and loop closure, and persist a versioned calibration ID. Add repeated/reversed grid traversals only if the first comparison requires more directional redundancy. Only after selecting grid geometry should separate runs vary speed and then acceleration one factor at a time. The reusable plan belongs in `redsun-planner` as a Bluesky plan stub/result; the active Redsun session owns execution policy, while the host supplies its device binding. Current biological evidence shows nearly transposed camera/stage axes and a 3.8 px/reported-µm image fit. Apply the operator-confirmed 0.5 physical-per-reported factor once, yielding about 7.6 px per estimated physical µm consistent with the accepted optical scale. Persist raw fit, corrected estimate, factor provenance and residuals; independently confirm the stage/controller scaling mechanism in a later hardware audit.

Both survey/revisit and explicit scan execution now validate recorded dataset completion, frame count, axes and image shape through one host contract. Recipes declare exclusive stage, camera and storage resources; the serial prototype rejects unsupported sharing modes and checks required operations, resources and acquisition settings before its first command.

The search and scan hosts also emit the same typed `ActionRecord` status events for proposed, accepted, started and terminal outcomes. Their outer journal containers remain workflow-specific, but request IDs, statuses, timestamps, parameters, readbacks and errors now share one action contract.

Each run snapshot now carries a framework-neutral `ExecutionBindingSnapshot` containing the provider type and declared capabilities, resources and settings, plus an optional adapter-supplied configuration reference. This is adapter provenance, not proof of physical device identity or profile revision; those remain release-manifest and instrument-acceptance evidence.

Cancellation is cooperative during an active operation. The host requests device stop, drains the captured prefix and finishes recording before releasing resources. Timeouts or failures with unverified physical outcomes remain outcome-unknown and prohibit blind retries or automatic return moves. Persist action intent before dispatch, then record the terminal result and available readbacks. This contract pass does not add split-detector geometry or a processing-service interface; those seams follow when their current data and timing needs are established.

Version 3 run/replay records are written by the current implementation. Their dataset reference is a framework-neutral typed value carrying a URI, format, named axes, shape, dtype, verified frame count, terminal status and manifest SHA-256. The library preserves typed references through replay and review checkpoints; the bundle storage adapter alone resolves local `file:` URIs and checks the reference digest against the stored manifest, while older v1/v2 string paths remain readable. The version 1 review-checkpoint reader verifies the original checksum and review bindings before normalizing old lowercase axes to named uppercase axes. Prototype Python APIs changed with the new typed boundary. Hardware-free mock/replay tests cover search, scan, cancellation-prefix recording, and legacy checkpoint conversion. This work adds no Redsun runtime, shared distribution, packaging migration or hardware authorization.

Keep recipes, skills and runs distinct. A recipe manifest declares typed parameters and units, capabilities, preconditions, resources, physical effects, outputs, completion/failure conditions and versioned validation evidence. Skills expose guidance; runs record resolved parameters, bindings, decisions and outcomes.

## Data, timing and recovery contracts

Use YXPlane/IterablePlaneInput for sequential data and ArrayBlockInput for random access where supported. Current RTASPT reconstruction still includes ndarray and TIFF-page consumers; generic input types do not make all processing stages source-independent. RTASPT no longer owns an acquisition controller.

Carry experiment/dataset/target IDs, phase, channel/polarization, Z position/index, axes, timestamps and calibration. Preserve sequence versus time-coordinate semantics, explicit missing-frame behavior and polarization pairing. Reset tracking at declared target boundaries; link survey/full datasets separately when shapes or dtypes differ.

Preserve acquisition and processing/publication times separately. Conditions need freshness/validity, sufficient support, persistence windows, timeout and missing-data behavior; delayed measurements must not affect unrelated targets or later phases. Simulation uses an injectable clock.

Record proposed, accepted, started, completed, failed, cancelled and outcome-unknown actions with request IDs, policy/recipe versions, decision reasons, data references and available readbacks. Recovery depends on action semantics: a timeout after delivery may require reconciliation rather than a second dose. Do not promise exactly-once physical execution or universal rollback. Backend timing and capability gaps must be explicit.

## First recipe and acceptance gate

**Implemented generic prototype:** a same-objective, two-pass step-and-snap search supports calibrated image-to-stage coordinates, overlapping tiles, candidate detection/deduplication, optional saved-review checkpoint, targeted revisit, and RTASPT handoff. Seeded mock execution passes. It currently uses a connected-component detector, fixed-Z host binding, single-channel scan settings and the saved offline review page; those are not the final first IX83 recipe below.

**First IX83 example recipe, specification refined; new recipe behavior planned:**

1. **Operator well localization:** before arming a run, guide the operator to either two opposite well corners or four ordered well corners. Each point requires an explicit operator confirmation and a recorded XY readback. Show the proposed boundary and require a final start confirmation after all points are accepted. Two-point localization means an axis-aligned rectangle; four-point localization records the well boundary. Until polygon coverage is implemented, reject unsupported skewed/nonrectangular boundaries instead of silently scanning their bounding box.
2. **Focus:** use the IX83 body focus-lock/autofocus drive to hold relative focus. A Z focus map and per-tile absolute-Z surface are not part of this recipe. The host must declare and validate the body focus-lock capability; a software adapter/mock for its relative focus operation remains to be implemented and tested. Do not treat the current Demo Z binding as microscope autofocus.
3. **Survey:** execute a bounded, settled step-scan at the survey settings. At each location, acquire a short frame group and form a per-pixel temporal median. Use recorded positions and the applicable image-to-stage transform to place the median tiles into a channel-specific survey map. No user-drawn tissue mask or specimen-specific segmentation model is required.
4. **Intensity-based detail suggestions:** compute an Otsu threshold and intensity/area metrics independently for each channel map. Suggest detail imaging only where the configured per-channel evidence is high in both channels; retain each channel's score, threshold and contributing tiles in the proposal record. This is an intensity-selection rule, not a claim of cell/object segmentation. Exact score, area, threshold and no-hit policies require seeded/replay tuning before real-specimen acceptance.
5. **Minimal operator GUI:** launch a local survey-map/review window from the bundle CLI after survey processing. Show well boundary, tile coverage, the channel maps, Otsu/intensity overlays and paired-channel detail suggestions, and let the operator accept/reject suggestions before the detail MDA. The existing saved HTML review can review detector candidates but does not yet display median channel maps or implement this recipe's well-corner wizard and acceptance gate.
6. **Detector and channel geometry:** support single-camera, split-detector and multi-channel acquisition explicitly. For split-detector data, reconstruct and register parallel/perpendicular views per channel using RTASPT's [detector reconstruction geometry](../03_external/Realtime-Anisotropy-SPT-Analysis/src/rtaspt/channel_reconstruction.py); keep a separate pixel-to-stage transform for each cropped detector view. For channel-group MDA, acquire and score each channel independently, preserve channel/exposure/timing metadata, and cross-register channel maps before applying the “high in both channels” rule. A split detector may be present within each channel; do not collapse polarization views or channels before their transforms and intensity metrics are applied. The acquisition baseline can parse basic channel/timepoint MDA settings, but the search host does not yet orchestrate per-tile channel-group MDA.

The first survey-map renderer, saved-checkpoint launch command and image-pixel registration helper now exist. They do not implement steps 1-4 or 6 end to end: the production well-corner GUI, body focus-lock binding, temporal-median channel maps, Otsu proposal policy, split-view spatial calibration and channel-group MDA orchestration remain planned. The separate demo CLI now supports corner readback capture and final confirmation; that does not establish this full biological recipe. The current acquisition/search adapter intentionally rejects channel/ROI/binning changes.

The next hardware-free acceptance case should use a stage-aware multi-channel specimen mock with a 4 x 3 scan, two- and four-corner inputs, temporal intensity variation, hot areas present in both channels, hot areas in only one channel, blank areas, overlap and split-detector crops. Verify no motion occurs before boundary confirmation; median maps and independent Otsu metrics are reproducible; only paired-channel hits are proposed; each detector/channel transform is respected; cancellation/missing channel planes are explicit; and the GUI round-trips operator decisions. Follow with supplied-image/replay testing, then separately authorized calibrated specimen acceptance. Simulation success is not specimen validation.

**Planned second recipe:** baseline acquisition, validated baseline, configured perfusion request/outcome, explicit arrival/mixing criterion, anisotropy monitoring and sustained-response/timeout transition. Pump completion is not reagent arrival; chamber-wide resource and specimen state must be explicit. Hardware and response criteria remain undecided.

## Setup phases

1. **Minimal acquisition baseline (basic gate passed):** local camera/XYZ interfaces, stage-aware mocks, snapshot/native-sequence lifecycle, bounded preview, cooperative cancellation, raw/OME recording and checksummed replay are implemented. The locked supported environment, 44 tests, demo ZMQ, authorized Ludl/PVCAM smoke checks and the 600-frame 20 fps recording/cancellation checks pass. Longer stress runs, hardware-trigger timing and wider device-specific acceptance remain outside this gate.
2. **RTASPT boundary cleanup (acquisition removal implemented; extraction planned):** the compatibility host retains acquisition lifecycle, MDA reader/planner, raw recording/replay and recorded-plane handoff. The 2026-10-04 backend-factory/controller checks are historical; current RTASPT has no acquisition controller or factory hook. Next validate recorded-data detector/processing parity and explicit acquisition context against the current input contracts, then qualify the offline GUI separately. Do not restore the removed live frontend to satisfy old launchers.
3. **Sample-search workflow (local prototype gate passed):** the library supplies reusable descriptors/calculations and hardware-free records; the IX83 host owns serial orchestration and device execution. Stage-aware 4 x 3 replay/simulation acceptance passes for coordinate transforms, coverage, deduplication, revisit tolerance, failure/cancel outcomes and per-target movie handoff. Supplied-data and mechanical scanning evidence belongs in the domain validation record; calibrated real-specimen recall remains pending.
4. **Primary Redsun acquisition integration (bounded survey/review and multi-strip broom plans implemented; physical acceptance open):** `PlannerPresenter.plan_map()` registers `preview_snap_scan_geometry` in the AcquisitionView. This geometry-only entry takes two operator-confirmed corner readbacks, footprint, overlap and provenance IDs, then emits planner-generated snake positions and coverage metadata without device arguments or device commands. `execute_snap_coverage_survey_and_prepare_review` now combines a bounded snake survey (10×10 with 200 reported µm steps, about 100 µm physical per step under the 0.5 model, with configurable dimensions and spacing) with a pre-motion check that the camera footprints cover the complete review-config region, then creation/opening of its review checkpoint from that run's exact positions sidecar. Human candidate review remains an explicit boundary; `execute_reviewed_snap_revisit_from_decision` validates or writes the selected-target result, then invokes the existing live calibration, camera-mode, fresh-anchor and envelope checks before revisiting. The integrated snap plans require the native ludl_stage parent so they can check stage busy and terminal outcome; anchor return is skipped for unknown or failed stage state. The integrated sequence is not physically qualified. The standalone review, decision and revisit actions remain available for recovery and inspection. `PlannerPresenter.run_ludl_mmcore_coordinated_broom` is the selectable full bounded multi-strip native-Ludl broom plan, composing two-corner rectangle or four-corner convex-polygon geometry, camera/stage binding, frame persistence and stage telemetry. It rejects routes whose estimated total exceeds 20,000 frames across all strips and records that bound. Its finalizer returns to the captured anchor only after a completed traverse confirms its endpoint and idle state, or an acknowledged stop confirms idle; unknown or failed-stopped outcomes block another move even if busy=false. The camera is prepared/drained per strip; route-level capture continuity remains a parity gap. Stable focus, exposure-associated stage pose, physical FoV and scan-quality acceptance remain open. The opt-in snap qualification captured a real PVCAM frame, and the physical Ludl stage completed a separate 50×50 µm 2×2 DemoCamera path on 2026-10-17. A subsequent combined PVCAM/Ludl 15×15 run completed 225/225 frames and produced a connected flatfield-corrected image graph for 214 tiles (evidence in `08_session_logs/20261017T_physical_redsun_rehearsal/`). Use the operator-confirmed 0.5 physical-per-reported scale correction once for physical geometry estimates; do not change stage commands or optical calibration. The mosaic still needs operator review of seams and valid specimen support, and the saved illumination commands do not establish calibrated dose. The earlier 6×6 recipe's 1 mm span is only a nominal adapter-reported coordinate span. Keep `planner` returning Bluesky plans and requiring Bluesky but no Redsun runtime; do not add `PlanEntry`, `PlanAction` or presenter callbacks to its public API. The `preview_observed_coverage_snap_grid` plan now loads the referenced support TIFF after verifying its dimensions and SHA-256 and renders the registered support, proposed tile footprints, missed support and overscan in a separate Coverage Preview dock; its axes are explicitly the registered-mosaic pixel frame. Before physical acquisition, preflight current camera mode, native-stage module and scaling, limits, storage, illumination and timing. Camera service-arrival records do not provide exposure-synchronized pose, so keep that result unavailable until clock and exposure mapping are validated. Assess `bluesky-adaptive` at this Presenter composition layer. Keep non-Redsun adapters as supporting examples or skills, and standardize their data/capability contracts with the temporary Pycro-Manager host. Measure before placing block processing in a worker/IOC or introducing a sample-search service.
   **Broom geometry contract (2026-10-20):** the Presenter now prefers a loaded,
   scan-preflight-accepted, mode-matched hand-eye calibration to derive a
   conservative camera field in reported-stage coordinates. It verifies camera,
   ROI, binning, XY service identity and its recorded basis, plus coordinate frame before use, so
   camera rotation is handled by the calibration. The current physical fit is provisional and does not
   meet this gate. Without an accepted calibration, the operator supplies
   manually calibrated physical stage-axis field extents; this fallback does
   not establish calibration acceptance by itself. The default
   0.5 physical-per-reported factor converts those extents into reported-stage
   units for strip geometry. Corners, readbacks and motion commands remain in
   reported-stage coordinates; the run records field source, calibration
   provenance when used, both footprint values and the factor. Calibration
   records lacking the XY service identity or naming another signal endpoint fail
   preflight. Physical coverage still requires comparison with registered valid
   specimen support.

   **New mock evidence (2026-10-17):** the expanded base-Python headless suite
   passed 164 tests with one optional skip because matching Micro-Manager
   adapters were unavailable. It includes the delayed native-Ludl terminal
   readback regression, camera configuration defaults, auto-shutter routing,
   per-snap versus whole-broom shutter cadence, and offline protocol/replay
   cases. The full application suite then passed 318 tests, skipped 25 and
   emitted 18 warnings through the existing runner with escalation outside the
   Codex sandbox. These are software checks; they do not qualify GUI behavior,
   physical shutter timing or illuminated specimen coverage. See the
   [focused evidence](../08_session_logs/20261017T180917_focused_headless_test_run/README.md)
   and [full-suite evidence](../08_session_logs/20261017T180942_full_test_run/README.md).
   **Native Ludl scan integration evidence (2026-10-18):** the Redsun app now
   has hardware-free integration coverage for both scan recipes using its native
   serial stage service, a fake MAC6000 serial peer and DemoCamera over loopback
   PVA. The bounded 2×2 snap snake persisted four 512×512 frames and a four-point
   position sidecar, then returned to its anchor. The three-strip broom run
   persisted 42 frames, geometry and stage telemetry sidecars, then returned to
   its anchor. These checks also found and fixed broom stream descriptor ordering
   before capture. A post-run audit caught incorrect physical-execution flags in
   the original fake-peer broom documents; they remain preserved as produced and
   are explicitly marked pre-fix. The native PVA snap/broom tests were rerun
   after the correction through the app runner: **2 passed in 27.68 s**. Their
   new reports and sidecars show `simulation_only=true`,
   `hardware_commands_issued=false`, and `execution_authorized=false`. A separate
   host-side full-suite run passed 359 tests, skipped 26 and failed one known
   legacy-ASCII fake-service startup test (`not ready after 15 s`). These runs
   validate software plan/service/storage composition only; physical calibration,
   module/axis mapping, motion, timing and image quality remain unqualified. The
   next gate is a verified physical profile and newly authorized bounded scan.
   See the [native scan evidence](../08_session_logs/20261018T_native_ludl_scan_01/README.md),
   [post-fix PVA test record](../08_session_logs/20261018T031030_full_test_run/README.md),
   [full-suite record](../08_session_logs/20261018T030549_full_test_run/README.md),
   and [adapter design record](ludl_serial_adapter_design.md).
   **RTASPT broom context handoff (2026-10-19):** resource-backed broom events
   now carry the stream-resource UID resolved from their `stream_datum` index
   interval. At RunStop, the Presenter verifies each matching TYX Zarr store
   and optional camera timing sidecar, writes `frame_contexts.jsonl` plus its
   coverage report beside the store, and records each export result in the
   geometry JSON. This removes the manual join for new captures. A headless
   managed-Demo three-strip snake completed, all three resource sidecars
   matched their Zarr frame counts, and the existing RTASPT CPU replay
   processed strip 0 (10 frames; 10 observations; background, en-face and TDI
   outputs). The Redsun Presenter replay action also processed the corrected
   three-strip context sidecars on CPU, wrote integrity-verified replay runs
   and slit/background/en-face/TDI products for all 30 frames. A fresh managed
   Demo run after the context-export change verified that RunStop automatically
   writes the nominal linear-route speed and provenance to all three sidecars.
   The first run exposed and the follow-up fixed a stale Demo camera
   clock origin: the corrected three-strip run had 30/30 frames with associated
   poses and monotonically advancing strip start times. RTASPT CPU replay
   completed on all 30 frames using the known Demo linear-route speed, with
   velocity provenance marked as simulation-derived and gated by accepted
   same-clock poses. The Presenter now converts its offline ROI speed curve
   into a quantized, minimum-duration epoch schedule and executes a second
   source-frame pass with a fresh RTASPT processor/TDI volume per epoch. It
   writes separate products and records source frame ranges and scenario
   velocities. This does not replay stage motion; it tests the processing
   consequence of a modeled search-to-detail curve. The 34-frame biological
   replay covered source indices 36–69 in three contiguous epochs, verified
   per-epoch processor speeds/resets and `TYX` product stacks, and emitted 22
   modeled TDI planes versus 31 from the fixed 200 µm/s baseline. Effective
   TDI durations varied from 22.87 to 91.48 ms as depth changed from one to
   four frames. This is an integration-window model, not a throughput or image
   quality benchmark. At matched source indices, fixed-to-variable TDI median
   signal ratios were 4.07 at one temporal-sum frame and 1.96 at two. Frame
   69's fixed and slow outputs were pixel-identical because both summed the same
   four raw slit images; this does not indicate a stationary image or stage.
   RTASPT's current `tdi` product is an unshifted temporal sum. Redsun now adds
   an opt-in motion-sheared `virtual_tdi` using RTASPT's geometric accumulation
   helper and an explicit image-motion direction. It quantizes modeled offsets
   to whole pixels and remains unqualified until the scan axis/sign are checked
   against accepted pose or registration data. The bright-slit replay emitted
   30 virtual planes, but the fastest epoch's legal depth was one frame, so it
   did not perform multi-frame integration. Supplied advances of 175.73, 106.33
   and 21.00 pixels/frame are scenario calculations, not source motion
   measurements. Fractional shifts and coverage normalization remain open.
   See the [motion-sheared TDI evidence](../08_session_logs/20261019T_roi_speed_epoch_biological_replay_01/README.md#redsun-motion-sheared-rtaspt-product).
   A further Presenter/RTASPT slice groups contiguous source frames into
   unnormalized virtual exposure sums during the variable-speed pass. It keeps
   the original individual-frame ROI intensity trace, starts a new grouping
   window at each speed epoch, and carries each exact source span into the
   saved plane map. In the bright 34-frame interval, group size four produced
   10 virtual exposures (3.4-fold realized data-rate reduction due to epoch
   boundaries), with each sum and RTASPT product exported. This exposes an
   integrated-blur/data-rate corner for sample-search simulation; it does not
   establish a physical fourfold stage speed because source poses and exposure
   clocks are not recorded. See the
   [grouped virtual-exposure replay](../08_session_logs/20261019T_roi_speed_epoch_biological_replay_01/README.md#four-frame-virtual-exposure-and-rtaspt-replay).
   The source records a focus
   change and lacks per-frame pose/exposure context, so neither image quality
   nor physical motion can be concluded. Next, acquire a focus-stable
   moving region with exposure-synchronized stage pose, then compare against an
   accepted sharp reference over matched support before treating the speed
   curve as an acquisition recipe. See the
   [automatic broom-to-RTASPT evidence](../08_session_logs/20261019T_rtaspt_auto_broom_context_01/README.md),
   [speed-epoch implementation record](../08_session_logs/20261019T_rtaspt_speed_epoch_schedule_01/README.md),
   [biological variable-speed replay and validation](../08_session_logs/20261019T_roi_speed_epoch_biological_replay_01/README.md),
   and the [RTASPT handoff contract](redsun_upstreaming_evidence_20261020.md#replay-stored-strips-through-rtaspt).
5. **Profile and supervised device acceptance (started):** a Redsun PVCAM-only
   session starts the real Camera-1 adapter and exposes a 2048 × 2048 `uint16`
   frame; a later camera-only RunEngine snap saved one fresh PVCAM frame and a
   pixel-intensity plot without starting a stage or illumination service. A
   separate physical Ludl qualification then completed a 50×50 µm 2×2 snake
   through the Redsun RunEngine and MMCore `SerialManager`/`LudlController`/
   `XYStage` path on COM22 with DemoCamera frames, returning to within
   0.2 µm X / 0.1 µm Y of its captured anchor. On 2026-10-20 a second 50×50 µm
   2×2 DemoCamera qualification completed through the Redsun RunEngine with
   native legacy-ASCII serial on COM22 at 115200 baud; the post-run raw readback
   was within 4 X counts / 2 Y counts of its fresh anchor. The first attempt
   exposed stale PVA motion-state telemetry at cleanup; a bounded three-second
   terminal-state wait resolved it on retry. Both stage paths now have small
   physical DemoCamera snap evidence, while the 15×15 PVCAM/Ludl survey remains
   the larger-area integrated acquisition baseline. Neither DemoCamera test
   establishes specimen coverage or independent physical scale. Calibrated
   optical and laser/shutter integration acceptance remain pending. The original
   `Technique=storm` group in `ix83_full_mmconfig.cfg` cannot yet be applied as
   Redsun defaults: its Gain `3-Sensitivity` is unsupported by Redsun's
   designated 20260420 PVCAM adapter (which reports `1-HDR` and `2-CMS`), and
   the separate MMStudio-validation PVCAM DLL has a different hash. The
   2026-10-16 biological snap record shows `3-Sensitivity` before and after the
   operator-loaded MMStudio run with no settings written, so the saved preset
   was effective in that runtime. The binary difference makes runtime-specific
   behavior the leading explanation, but a matched-profile comparison is still
   needed to establish causation. Before setting any mapped defaults, compare
   the same camera/profile with the MMStudio-validation runtime after Redsun
   releases camera ownership; verify the complete property set and readbacks.
    The hardware-free optics protocol tests also pass (13 tests); they exercise
    command ordering, failure cleanup, firmware acknowledgement rejection,
    channel limits, and Redsun light-presenter integration using fake ports.
    The operator confirmed the shutter Arduino is on COM5. The full and mixed
    MMCore profiles plus the captured 2026-10-16 live property snapshot all
    assign the four laser shutter devices to COM5; COM19 is the separate
    Arduino LED/shutter controller in the GS2/DPC profile. Windows identifies
    both as Arduino Uno class boards. The operator supplied the current
    `LaserUI.bsh` map as 405→COM12, 488→COM6, 561→COM10, and fourth channel
    `670`→COM9. Windows enumerated COM6–COM13 during the session, so each
    mapped port was present; enumeration does not identify laser heads or
    verify safe operation. The historical live MMCore `561`→COM10 entry
    agrees with this map. COM22 remains the qualified Ludl stage port and is
    no longer part of the laser map. Laser command dialects remain unverified;
    the fourth-channel label `670` differs from the bundle optical record's
    647/637 nm entry. A single PVCAM snap with the operator-
    reported 561 source enabled but no shutter/laser commands showed no clear
    signal increase versus the earlier camera-only frame (mean 175.61 vs
    175.80 ADU; SD 12.91 vs 12.87); the Redsun snap did not use or read the
    shutter. Historical MMCore broom records explicitly required 561 shutter
    state 1 and `get_shutter_open=True` during the live sequence, while the
    post-adjustment run recorded idle state 0. This documents the MMCore
    commanded/readback sequence, not physical shutter position or current
    firmware. The bounded 2026-10-17 COM5 probe sent MMConfig 561 shutter
    close/open/close commands at 9600 8N1; transport writes returned without
    error, no response was received (MMConfig ignores responses), and the
    final command was close. The operator confirmed physical shutter travel and
    that the 561 source emits while the shutter blocks the beam. A direct COM10
    controller probe sent ON, POWER?, and STATUS? at 9600 8N1: STATUS? returned
    ENABLED and POWER? returned -000.2mW. No setpoint or shutter command was sent
    during that probe; the controller remains enabled and the shutter closed.
    The optical observation conflicts with the near-zero power readback, so
    POWER? is not a reliable emission proxy here. This verifies command/readback
    transport and operator-observed emission/shutter travel, not calibrated
    optical power, exact firmware identity, interlock behavior, or Redsun
    integration. See
    [physical rehearsal evidence](../08_session_logs/20261017T_physical_redsun_rehearsal/README.md).
    COM22 was opened separately by the MMCore Ludl stage service. Before
    physical Redsun laser/shutter acceptance, verify installed COM5 firmware and wiring/polarity
    plus laser stop/interlock behavior.
    Broader acceptance remains planned:
   review profiles/firmware against the developer's
   [hardware snapshot](hardware_devices_available_to_agents.md), verify
   applicable shutter/watchdog/interlock provisions, and obtain authorization
   for a stable fluorescent specimen. Measure calibrated motion, recall,
   revisit error, duration and data volume.
6. **Release record (planned):** record exact tested software commits, firmware checksums, profile revisions, hardware configuration and calibration IDs. Pin changes and publication require their own authorization.

**Repository-state audit (2026-10-19):** the acquisition app and planner are registered submodules in `.gitmodules` and the bundle index. The app index pin is `7a510fc6f3506624ce048784e6b2710449b4a60e`, while its checkout HEAD is `8365ac46ec9e550dc20b3baeebdacc61885d1245` with additional local changes. Planner index/HEAD is `95e35aaf16c9bdcaa463344fa2c2cef24bf4422a`; the bundle HEAD still pins `dce582bf8347c92b560d10d9c545d0ecbdbe8aa0`, so that index advance is staged, not committed. RTASPT HEAD is `2f38d1e9a0a0eec801f13dbd6ecdfc953f86195a` with local changes; `.gitmodules` declares it, but the current index contains no RTASPT gitlink. These are source identities, not exact tested release manifests or installed-wheel identities. Reconcile intended pins only after owning-repository validation and separate authorization; this review changes none. Publication requires approval immediately before each push. Remote discovery remains in the [update monitor](redsun_external_update_monitor.md).

See the [architecture flowchart](architecture_flowchart.md). This plan does not authorize connecting to hardware or modifying the developer-maintained snapshot.

**Native Ludl read-only port recheck (2026-10-18 07:18 UTC):** two separate
base-Python processes opened COM22, read both idle modules and exited with code
0; the second process reacquired the port successfully. Current raw positions
were X=349/Y=36, differing from the earlier X=352/Y=37 snapshot. Do not treat
either as a calibrated anchor or move from them without fresh bounded
authorization. No physical stage action was issued. See the [reopen evidence](../08_session_logs/20261018T_native_ludl_continuation_01/README.md).

**Hardware continuation (2026-10-18 23:56 UTC):** a fresh ASCII COM22
preflight found X=354/Y=33 counts, idle, at 9600 baud. The first 100 µm-bounded
2×2 PVCAM snap scan acquired three frames. On its Y return, the requested count
was 34 and the idle readback was 19, an overshoot of 15 counts (about 0.77 µm
on the provisional scale); the adapter correctly returned an outcome-unknown
error. Plan cleanup returned near the captured anchor. No laser/shutter or
camera/IX83 property writes were issued. See the [physical scan and
frame-pipeline evidence](../08_session_logs/20261018T_live_frame_path_physical_scan_01/README.md).

**Retained-frame consumer qualification (2026-10-19 00:05 UTC):** the existing
Redsun venv was synchronized from its lock with `--extra tiled --extra cuda12`
(not rebuilt). The four retained real PVCAM frames were replayed through
RTASPT's injected slit processor in NumPy/CPU and CuPy CUDA/device-resident
modes. Each path wrote four `LiveRun` frames and four `rtaspt-operating-point-v3`
records; TDI/background/en-face products were ready on the final synthetic
four-frame volume. Both outputs opened and were served through OME-Tiled/Tiled
with `t,y,x` axes and exact pixel equality to the captured frames. The focused
OME-Tiled tests passed 4/4. RTASPT remained a separate source import over
`PYTHONPATH`; it is not an app dependency. The velocity, period, pixel size and
slit geometry were nominal software parameters only: the camera frames were
captured stationary and had no calibrated stage positions, so this does not
qualify a physical TDI scan or position-associated processing. The Y-axis
settlement issue remains under bounded qualification. See the [hardware and
consumer evidence](../08_session_logs/20261018T_live_frame_path_physical_scan_01/README.md).

**Managed ASCII snap retry (2026-10-19 00:15 UTC):** after an isolated
50 µm Y excursion and return landed within 0.15 µm of its captured anchor, a
fresh idle/profile check preceded an identical 50 µm 2×2 scan through the
Redsun RunEngine, managed ASCII service and PVCAM. It completed all four
frames in 5.01 s, recorded all four expected waypoints, and returned within
0.12 µm Euclidean distance of its scan anchor (0.10 µm maximum per-axis error).
The subsequent read-only COM22 check found X=351,
Y=32 counts, idle, with the same 9600 baud, 18,000 steps/s, 5,000 start speed
and acceleration value 4. The earlier 15-count Y overshoot did not recur in
these two bounded checks; this does not establish general motion accuracy or
accept the provisional scale. Camera binning, exposure and ROI were read-only;
no laser/shutter commands were issued. The stage scan is no longer blocked
from the next **bounded** qualification, but larger-area motion still needs
repeatable return evidence and a calibration-backed stage-to-image fit. Offline
SIFT-seeded ECC stitched the four images into a coherent 2×2 mosaic, with
61.2–62.8% pairwise overlap and 756–785 px main-axis offsets. These agree
closely with the earlier image/count-derived scale, but are not independent
absolute-stage calibration because the native count-to-µm mapping uses that
same prior fit. Phase-correlation-only initialization failed on the repeated
cell pattern; feature-seeded ECC converged. The mosaic still shows illumination
seams; no flatfield or photometric homogenization was applied. See
the [managed retry record](../08_session_logs/20261018T_live_frame_path_physical_scan_01/managed_scan_retry_01/README.md).
