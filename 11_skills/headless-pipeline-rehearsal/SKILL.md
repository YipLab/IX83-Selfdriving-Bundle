---
name: headless-pipeline-rehearsal
description: Continue the IX83-Automation implementation backlog and headless Redsun/RTASPT rehearsal, translating manuscript outputs into owned code work and evidence gates before live-cell validation.
---

# Headless stationary-sample pipeline rehearsal

Use this skill for the bundle's implementation next steps and headless pipeline rehearsal. Choose the mode the user requested: roadmap maintenance, software/recorded-data implementation, or separately authorized instrument rehearsal. Updating a plan or implementing an offline component does not require acquiring new data.

The canonical backlog owns priority; the manuscript specifies intended outputs, not implementation status. Earlier one-day rehearsal deadlines are historical context, not a new deadline or an acceptance result.

## Mission

For instrument rehearsal, run the chain on one stationary specimen in one headless session and show that each stage's artifact reaches the next:

`acquisition -> pose-registration -> review-decision -> revisit/survey -> stitching-mosaic -> handoff-storage -> reconstruction -> anisotropy -> SPT-tracking`

Success is not "the scripts exit 0". Link every required stage artifact into one run directory and a `rehearsal_report.json` with the actual outcome, measurement, attempt and source identity. Retain partial, refused, not-applied and unknown outcomes instead of forcing a pass/fail claim; a justified not-applied modality outcome does not establish that modality's scientific endpoint. Reuse the existing report where applicable. A live-cell switch remains gated by the stationary-sample chain.

## Read first, in this order

1. [AGENTS.md](../../AGENTS.md) — execution policy, test gate, evidence and git rules.
2. [Next actions: Redsun and RTASPT](../../02_docs_offline/redsun_rtaspt_integration_next_steps.md) — read [Track D](../../02_docs_offline/redsun_rtaspt_integration_next_steps.md#track-d--stationary-sample-full-pipeline-rehearsal-leading-track), the [Q01–Q12 increment and reconciliation](../../02_docs_offline/redsun_rtaspt_integration_next_steps.md#manuscript-driven-implementation-increment-2026-10-27), the [standing instruction](../../02_docs_offline/redsun_rtaspt_integration_next_steps.md#standing-instruction-for-an-agent-picking-this-up) and the [execution lanes](../../02_docs_offline/redsun_rtaspt_integration_next_steps.md#parallel-execution--what-two-agents-can-run-side-by-side). The dated reconciliation overrides stale next-action wording in earlier tables.
3. [RTASPT searching-scanning next steps](../../02_docs_offline/rtaspt_searching_scanning_next_steps.md) — the technical detail and contracts behind those rows.
4. [Windows test execution](../../02_docs_offline/windows_test_execution.md) before composing any test command.
5. [Live-cell readiness checklist](../../02_docs_offline/live_cell_readiness_checklist.md) — the gate this work serves.
6. The owning submodule's `docs/` next-step or workflow pages for the stage being touched, and its own contributor instructions.

If a newer next-step page supersedes these, follow the newer page and say so in the run record.

For manuscript-driven implementation, read [references/implementation-handoff.md](references/implementation-handoff.md) for routing and existing-code distinctions, then only the relevant owning work package. Do not copy the ranking into this skill.

## Boundaries that do not move

- **Fixed sample.** No specimen change, no objective change, no re-mount between stages. A blank, dim or structureless field is a finding to record, not a licence to leave the demarcated plan.
- **Bounded motion and illumination.** Check authorization from the current session for the actual specimen, devices, plan, limits, exposure and illumination. Preserve applicable authorization already given without asking again. The archived [operator brief](references/operator-brief.md) records an earlier task; loading this skill or that quote does not itself authorize a new run. Limits, firmware and undeclared profile/safety changes remain outside bounded plan execution. Physical illumination-off confirmation remains a rehearsal gate.
- **One command authority.** Only the main agent constructs a session and talks to devices: camera, stage, laser, shutter, PVA child services. Subagents never do, even for "just a readback".
- **Headless.** No napari or Qt window from an agent session; that path crashed the harness on 2026-10-24 and must not be retried. Offscreen widget construction for contract checks is fine.
- **No relabelling.** Keep software/mock/replay evidence separate from physical acceptance. A recorded-data analysis can verify that analysis on its identified input without qualifying current hardware. Follow the canonical state vocabulary and state exactly what ran.
- **Urgency is not evidence.** A deadline changes priorities, never what a result establishes.

## Phase 1 — intake and selection

1. Locate the current next-step documents: global pages under [02_docs_offline](../../02_docs_offline) and the owning submodule's `docs/`. Prefer the page that names itself canonical for ranking.
2. Re-rank only as the standing instruction allows, and record the re-ranking with dates. Do not invent a second ordering.
3. Select by lane. Rows in the instrument lane need the main agent and the authorization above. Rows in the code/processing lane are delegation candidates.
4. State explicitly which rows you are **not** doing and why, before starting the first stage.

For a planning request, finish by synchronizing the canonical backlog, technical work packages and affected indexes, with checked links and explicit remaining inputs. For code work, implement in the owning repository and use its required checks; avoid unrelated full-suite reruns for documentation-only changes. For instrument work, continue through the preflight below only within the applicable authorization.

Recover transferred records first: scanning-speed and related evidence on another computer is awaiting review, not presumed unmeasured. Start the relevant Q01/Q02 manifest/ledger slice, then Q03 pure onset policy and Q04 stepped parity before continuous response qualification, following the canonical dependencies. Recorded-data Q06/Q08/Q10 and export Q12 work can proceed while physical gates remain open.

## Phase 2 — headless preflight

- Probe the environment before running anything: correct project `.venv`, interpreter, `PYMM_LOG_FILE` and cache/temp variables pointed at workspace-owned paths when the runtime denies the defaults.
- Run the chain-state check (`workflow_doctor.py` in the [snap retest driver set](../../08_session_logs/20261024T_snap_plan_retest_01/), taking `--calibration` and `--review-config`) and record its verdict: devices, accepted calibration, valid review configuration, next command. The stage drivers live beside their own records; reuse them instead of rewriting the chain.
- Run the suite that guards the chain headless and record the **actual count** from that run, not a remembered figure. The modules that guard it, in the app's `tests/`: `test_saved_snap_chain_plan.py`, `test_snap_stack_review.py`, `test_hand_eye_analysis.py`, `test_asi_calibration_identifier.py`, `test_plan_catalog.py`, `test_streaming_plan_exposure.py`, `test_plan_device_controls.py`. On a host use the app's own runner rather than an ad-hoc pytest line.
- Confirm the authorization record: who authorized which envelope, when, and which plan constants bound it. Write that into the run directory.
- Refuse in order, and say which precondition failed, rather than improvising a route around it.

Treat the existing adaptive app's point increments, the leading/trailing-band session prototype and a future continuous-speed binding as distinct paths. Receipt-time metadata is not exposure-associated pose. Search-scan rejects unsupported anisotropy/tracking request sections: invoke their supported workflows separately and link their outcomes.

## Phase 3 — authorized execution

Execute stage by stage into one run directory, in the artifact order of the pass-criteria table. After each stage:

- Persist the artifact and its digest, plus the readbacks that bound it (position, exposure, setpoint, calibration id, camera mode).
- Check the stage's criterion against the measured number. A miss is recorded as a miss; a later retry is a new attempt id.
- Keep the anchor-return and stop behaviour honest: an unknown or failed stage outcome blocks the next move rather than being retried blind.

Advance only when the previous artifact is readable and identified. Never stitch from frames whose positions are missing, and never reconstruct from tiles whose coverage identity is unconfirmed.

**The review stage's acceptance artifact is the operator's page, not a number.** Three checks, in this
order, because they fail independently:

1. **One target catalogue.** The page must annotate the same targets it displays. A page can carry a
   checkpoint with 12 targets and a mosaic catalogue with 9 of different detection provenance — that
   is not a deduplication, it is two different runs presented as one, and every marker is then a
   claim about a target the page is not showing. Compare counts *and* ids between the checkpoint, the
   mosaic catalogue and the detection map before rendering.
2. **Markers on content.** The drawn markers must sit on the detected objects. If they do not, do not
   tune the geometry to make the picture look right: establish which coordinate chain the page used,
   and whether the mosaic compositor's origin convention was respected (`registration_origin -
   crop_origin`, not the registration origin).
3. **The operator's glance is the gate.** A rehearsal is not accepted because the numbers are right;
   it is accepted when the person who knows the sample says the page shows the right things. Record
   who looked, when, and what they said. An agent asserting its own page is correct is not evidence.

A landing error and a page can disagree without either being wrong: a 1.4 um landing with offset
markers is a display bug, and the measurement stands while the page is fixed.

## Phase 3 checklist — closing a rehearsal on this instrument (2026-10-28)

Purpose of this section: get from "start a session" to "a recorded landing error" with the
fewest decisions, using the values already established on this instrument.

Scope, stated honestly: this section closes the **acquisition leg** — acquisition, registration,
review decision and revisit. It is not the whole mission. The downstream legs in the artifact
order at the top (stitching, handoff-storage, reconstruction, anisotropy, SPT tracking) keep
their own acceptance from the evidence defaults below, and a rehearsal report that stops at a
good landing error is a partial rehearsal, marked `not_applied` for the rest with reasons.

Within this leg, done means: a revisit landed on a detected target and the error is written
down. It does not mean the plan list looked complete.

### Starting values, not acceptance

These are the numbers a rehearsal starts from, each owned by a record that measured it. They
are pointers so the next session does not re-derive them, not targets and not acceptance: if a
run disagrees with one, the run's own measurement wins and the record is corrected.

| quantity | value | source |
| --- | --- | --- |
| camera sampling | **0.18281535648994515 um/px**, i.e. 5.47 px/um | measured step ratio, 35 steps, std 6.29 px |
| delivered scale for any placement matrix | **5.47** px/um (the stored fit says 5.1567; rescale as a similarity, factor 1.0608) | 2026-10-27 survey, mosaic export placements |
| laser 488 | **1.0 mW minimum**; 0.5 mW does not lase on this head | emission threshold |
| stage run speed | **0.1 mm/s**, both ceiling and floor; lower values are ignored or leave the previous profile | ASI MS2000 contract |
| survey geometry | 6x6, 60 um pitch, crop `[150,150,900,900]`, mosaic scale 0.25, mosaic origin `[-1776,-1784]` | recorded survey |
| saturation gate | `maximum_score = 4095` for this 12-bit camera | clipped blob has a biased centroid |
| jog behaviour | one bounded relative move, no software take-up; the controller's anti-backlash setting is the only compensation | one-compensation policy, 2026-10-28 |

### Before launching anything

1. **The spec contains the arm you need.** Check for recorded revisit frames. A comparison
   spec named "survey and revisit" held three arms and no revisit; the four-arm revisit broom
   is an inert prototype that cannot issue commands. If there are no revisit frames, there is
   no landing result to produce.
2. **The thresholds are the ones you intend.** `minimum_score` alone cannot reject a clipped
   blob; `maximum_score` must be set.
3. **The GPU path is recorded, not merely available.** Require a resolved backend in the run's
   start document (`gpu_backends_verified` or equivalent); `flat_backend: "auto"` is not
   evidence.
4. **One command authority.** No other session, GUI, MMStudio or stray interpreter holding the
   camera or the ASI serial line. If one is live, ask the operator to close it - do not kill it.
5. **A driver that takes an output root**, so the new run cannot overwrite the run it is
   compared against.

### The three runs that actually close the goal

| run | what it answers | acceptance |
| --- | --- | --- |
| **backlash, per axis and direction** | the mechanical play | **done 2026-10-29**: the reversal-step sweep gives a shortfall of 21.74 um at `2HB` 0, 19.47 at the shipped 1.4, 13.96 at 4, 5.67 at 8, **-0.50 at 16** and -0.47 at 32, so the knee is 16 um. It is a **survey** value, not a navigation default - 16 um is unusable for small jogs - and the survey plan now sets it for its own scope and restores what it replaced (`anti_backlash_um`, verified by readback and recorded as `planner_stage_anti_backlash`) |
| **jog landing, four directions** | whether a jog lands where it was asked | landing error at or below the measured lash. A 0.52 um residual survives three identical absolute commands on this stage - it is a **fixed setpoint/readback offset**, not converging play, so any return-to-anchor check has to close the loop on the measurement (`command anchor - measured residual`), which the revisit plan now does |
| **survey -> review -> revisit on the fixed sample** | whether a revisit lands on the detected target | **passed 2026-10-29 in one session** (`t2-chain-06`, `t2-chain-09`): 6x6 at 60 um registered 126-130 of 239-242 pairs in **one component**, the automatic decision wrote 4-5 targets, and the revisit landed **5/5 within 2 um (median 0.906, max 1.139)**. The revisit plan now writes its own landing JSON, contact sheet, stage-space record figure and HTML beside the frames, so a revisit cannot be recorded as "reviewed" without a landing figure |

The first two are minutes each and they change the third's interpretation, so do them in that
order. All three are cheap compared with the deliverables they unblock.

### The chain that closes T2 and T7 (verified 2026-10-29)

One session, one run root, no broom - the broom is its own gate and is not chained:

```powershell
# from 08_session_logs/20261024T_snap_plan_retest_01
python run_workflow_retest.py --step chain `
  --calibration <accepted hand-eye record> --review-config <record>\review_config.json `
  --checkpoint <run>\checkpoint.json --review-html <run>\review.html `
  --decision <run>\decision.json --result <run>\result.json --run-root <run> `
  --rows 6 --columns 6 --step-um 60 --revisit-envelope-um 2000 --anti-backlash-um 16 `
  --exposure-ms 20 --setpoint-mw 1.0 --shutter-gate acquisition `
  --confirmation-id <id> --confirmation ix71-workflow-chain-<id>
```

Then, on that same root, `04_code/rehearsal_audit/assemble_report.py --run-root <run>` writes
`rehearsal_report.json` and `audit.py --source <run>/rehearsal_report.json` re-verifies its digests.
Five things decide whether this works, and each one cost a run to learn:

- **`src` must precede site-packages.** The app exists twice in this checkout; without
  `PYTHONPATH=<shim>;<app>/src` the session, and the suite, load the stale installed copy.
- **A 3x3 survey is too thin to stay connected** at 60 um (15 of 34 pairs accepted, still two
  components). 6x6 gives the redundancy that one bad row or column edge needs.
- **The survey must set its own `2HB`.** At the profile's 1.4 um the same field registered 2 of 34
  pairs; the priors are ~100 px wrong because the reversal delivers ~40 um of a commanded 60.
- **The revisit's anchor return needs the corrected-command loop** (see the table above).
- **The session log must be INFO.** T7's one-session claim is read from the log and the marker it
  looks for (`'<plan>' ended`) is an INFO line; at WARNING the report refuses the claim for a run
  that really was one session.


### First reproduce a known-good chain on the current tree (2026-10-28)

Before blaming a new dataset for a broken product, run the *same* plan on a recorded input that
already has a known-good result and diff the numbers. `08_session_logs/20261028T_fixed_sample_strip_01/`
holds five three-lane runs with their mosaic shapes, coverage, seam ratios and gains in
`slitfix_summary.json`; re-running `prepare_broom_mosaic_from_recorded_run` on one of those inputs
(remember to pass `band_width_factor=1.0` explicitly, because the plan now defaults to 3.0) separates
three very different situations:

- the numbers reproduce - the code is fine and the new data is the problem;
- they differ in one named way - you are looking at your own recent change, not a defect;
- they differ in an unnamed way - a genuine regression, and now you have a specific one to chase.

A new product that looks wrong is not evidence that the code is wrong, and a chain that "worked a few
hours ago" is not evidence that it still does: the worktree is shared and changes under you. This
check costs one offline run and it is the only cheap way to tell a data problem from a code problem.

### Hand-eye capture and its analysis

Measured 2026-10-28 over three brightfield captures on the fixed sample. Each point below cost a run.

- **A capture must persist its own record.** The analyser reads a saved `hand_eye_capture.json`
  plus one `.npy` per frame. A capture plan that only streams its frames into the run leaves
  nothing to analyse, and it will report success while doing so - observed: 26 probe captures, zero
  artifacts. Save with the plan, in the analyser's own schema, and label the frames from
  `planner.plans.hand_eye_capture_labels` because the plan puts every capture in one stream: the
  per-capture identity is positional, not in the documents.
- **Probe size is bounded by content overlap, not by the plan's 100 um limit.** At a 60 um probe,
  four of twelve pairs failed ECC outright ("images may be uncorrelated or non-overlapped"), and
  the sparse-spot fallback found zero compact components on a brightfield texture. At 20 um the same
  field gave twelve clean registrations. Choose the probe for the field, not for the envelope.
- **Measure the estimator's repeatability floor before believing a closure.** The reference-repeat
  pair - two frames with no stage motion between them - moved 1.95 px, against a 3 px closure gate.
  A closure of 3.9 px is then 2 px of real error on top of a 2 px floor, which is what the record
  should say; it is not a 3.9 px physical error.
- **Do not assume frame averaging fixes a closure failure - it was measured and it did not.** Three
  exposures per capture on the same field and probe tripled the run duration and made every closure
  worse: the four returns went from 1.90 / 2.26 / 3.92 / 1.41 px to 3.42 / 5.11 / 5.64 / 3.12 px,
  while the reference-repeat floor moved only 1.95 to 2.17 px. So the closure error is not per-frame
  noise; it accumulates **over the run**. A capture that must close to a few pixels has to be fast,
  and the anchor has to be re-measured close to each probe rather than once at the start. The same
  run did reproduce the delivered scale - median **5.4677 px/um**, against 5.2817 for the
  single-frame run and the 5.47 declared for this instrument - so a slower, better-settled capture
  measures scale well while it drifts in position.
- **A stage prior is a seed, never an answer.** The capture records the stage delta, which converts
  to an ECC seed through the placement matrix. Use it when a large step defeats a feature seed, and
  still let ECC refine it and the residual and agreement gates decide. On the 60 um capture the seed
  could not rescue the pairs, because the failure was non-overlap rather than a bad start - which is
  itself the finding.
- **Slit reconstruction is the mode for broom data - registered is never a substitute.** Operator
  instruction 2026-10-28: a slit compose that fails, or that is awkward or slow, is a defect to
  record and fix, not a reason to switch to `mode="registered"`. The only legitimate registered run
  is one where slit cannot apply at all (no slit geometry for that camera mode), and that run says
  why.
- **Refusals are the result.** The analyser declines to accept a calibration when its gates fail,
  and that is the correct outcome to record. Do not lower a gate to obtain an acceptance: the
  2026-10-28 captures remain unaccepted, with the numbers recorded beside them.


### Commands that exist (verified 2026-10-28)

Do not invent a driver. These entry points exist in the app and cover the rehearsal:

```powershell
$app = "C:\Users\yipgroup\Documents\IX83-Selfdriving-Bundle\03_external\redsun-searching-is-imaging"

# 1. Launch a session on a named profile. The first argument is the command, the rest is passed
#    through. No argument means the managed demo broom session, which declares a simulated broom
#    only: no camera, no laser, no stage. That is not a rehearsal session.
.\scripts\run_session.ps1 ix71-asi --session-config src\redsun_searching_is_imaging\configurations\ix71_asi_pvcam.yaml
.\scripts\run_session.ps1 ix71-asi-sapphire    # real camera + 488 Sapphire

# 2. Run one plan headlessly with a JSON parameter file (offline/recorded-data plans).
.\scripts\run_plan_offline.ps1 -Plan <plan_name> -ParamsJson <file.json> -WorkDirectory <dir> -SkipBackendCheck

# 3. Run an acquisition plan through a session with a timeout.
.\scripts\run_session.ps1 acquire-plan --plan <plan_name> --session-config <profile.yaml> --param-json <file.json> --timeout 2400

# 4. Guard the plan/annotation catalog after any presenter edit. The catalog embeds planner
#    source line numbers, so a docstring that shifts lines invalidates it until regenerated.
& "$app\.venv\Scripts\python.exe" scripts\plan_catalog.py --check
& "$app\.venv\Scripts\python.exe" scripts\plan_catalog.py --write

# 5. The full app suite on the host (preferred over an ad-hoc pytest line).
.\scripts\run_full_test_suite.ps1
```

A plan name that appears in a plan map but not in the chooser is not broken: the presenter drops
any plan whose device annotation the session cannot satisfy, and logs "Leaving out <plan>". Read
that line before concluding a plan is missing from the code.
### When something disagrees

- **Markers offset but the landing is right** - the page and the coordinate chain are separate
  questions. Measure the landing first; a 1.4 um landing with wrong markers is a display bug,
  not a calibration bug.
- **Landing drifts with distance from the mosaic centre** - suspect a scale error in the
  hand-eye fit (5 to 6 percent here) before suspecting a convention.
- **Landing drifts only after a direction reversal** - that is backlash, and the answer is a
  measurement, not a larger compensation.
- **A number looks plausible and nobody measured it** - say so in the record and schedule the
  measurement. The 16 um backlash and the 449.5 px crop-centre term were both that.
- **A control is missing from the GUI** - it is built from what the running session declares, so
  check the profile before the code. The managed demo session declares a simulated broom only: no
  camera, no laser, no stage, so nothing that needs one can be shown. Since 2026-10-28 a device
  parameter whose role has no session device renders an empty control naming the role instead of
  vanishing; if it is still absent, the plan is not listed for that session at all.
- **A service refuses all writes after one failure** - read the message before restarting. A
  channel that reports a fault and asks for a restart is a latch: since 2026-10-28 the optics
  service records the failed request and re-initialises the transport on the next one, so one
  unreadable reply no longer costs the session. If a write still fails, the device is genuinely
  not answering and the failure is real, not stale.
- **A parameter or a smoothing step is documented and the symptom it prevents is still there** -
  check that the code actually reads it. This has now happened twice in one module: `band_width_factor`
  was recorded as `n_obs` and never applied (so "widen the slit" changed nothing), and
  `along_smoothed` is computed in `build_broom_strip_panoramas` with a comment describing exactly the
  staircase it prevents, and is **referenced nowhere**. A comment is a claim, not evidence: grep the
  variable, and prefer a report field or a test that would fail if the value stopped reaching the
  geometry. When a defect's fix is already written but not wired in, the fix is one line and the
  "investigation" was the reading.

### Evidence to write down, every run

Resolved GPU backend, the exact config values used, the arm timings, and the per-target landing
error (dx, dy, norm) with median, RMS and max, listing every excluded target and why. A run
whose recursion into the record stops at "completed" has not produced evidence.

## Fluorescence and evidence defaults

These are rules for any fluorescence run, not a claim that every current consumer already implements them. Where a path does not do what a rule requires, record that gap in the run record; do not describe the run as if it did.

**Flat-field and dark calibration are defaults, derived per run.**

- Derive the gated flat from **that run's own frames** with RTASPT `pooled_gated_median_flat` ([gated reconstruction](../../03_external/Realtime-Anisotropy-SPT-Analysis/src/rtaspt/gated_reconstruction.py)) — a pooled, intensity-gated temporal median over every sequence of the run.
- Derive the offset and read-noise of a **matching dark exposure** (same exposure, binning, gain and temperature) with RTASPT [camera calibration](../../03_external/Realtime-Anisotropy-SPT-Analysis/src/rtaspt/camera_calibration.py) (`estimate_camera_calibration`, `apply_camera_calibration`).
- Never reuse a flat or noise artifact from another dataset, exposure, power, binning or sample. An earlier published flat at another exposure is not a substitute — a 10 ms flat does not describe a 20 ms survey. The specimen's own bulk is part of what the map measures ([checklist](../../02_docs_offline/live_cell_readiness_checklist.md), A8).
- Apply flat, dark offset and noise normalization **before** the Otsu/threshold detection and to the image the review page renders. A review page built on raw frames is a recorded non-compliance, not a presentation choice.
- Record the gate accounting (candidates, accepted, gate bounds, flat statistics) and state that the flat is an **empirical illumination estimate, not calibrated radiometry**; do not promote it into a radiometric claim.

**One global tile-processing crop per camera mode — tiles only, not slit processing.**

- Applies only to bounded tile work: snap survey/revisit grids and hand-eye (tile) registration. Slit processing is not cropped by this rule: pre-slit **strip-level registration** may use the tile crop as a registration aid, but the **slits themselves** (slit images, slit mosaic, slit intensity/profile) keep their full slit geometry.
- Acquisition keeps the full frame; every tile-processing consumer — hand-eye, flat/dark/noise estimation, registration, detection, review and mosaic — uses the same declared crop. The reference for a 1200×1200 readout is `(x, y, width, height) = (150, 150, 900, 900)`; a different readout or binning gets its own recorded crop.
- The review region is a sub-rectangle of that crop, and downsampling is a rendering choice, not a second crop. Record the crop origin with every result and add it back when converting crop-relative pixels through a full-frame calibration.
- Do not re-crop per stage or per experiment. A changed crop is a new analysis: record it and compare like-for-like.

**Registration gate is mode-specific.**

- `0.5 px` accepted-edge RMS is a **brightfield** gate, not a universal one. Fluorescence uses a relative gate: edge RMS ≤ **2 % of the processed field width** (18 px for the 900×900 tile crop), with a connected graph and accepted-edge coverage. Record `gate_px` and `gate_basis="relative_field"`; do not apply the brightfield gate to fluorescence.
- The gate is a gross-misregistration screen, not physical accuracy. Passing it does not certify the fluorescence mosaic; physical registration/scale acceptance is separate.
- Double images are quantified with the app's `mosaic_ghost_metrics` (strongest secondary autocorrelation peak of the high-pass gradient, with the ghost offset). Record `max_ratio`, `p95_ratio` and `worst_offset_yx`; a gate pass does not detect a double image, so visual review remains mandatory.

**GPU is the default where available.**

- RTASPT's gated estimator defaults to `backend="auto"`: the device when the accepted-frame buffer fits the device budget, host fallback with a warning when it does not. `backend="cpu"` forces the host.
- Report the **resolved** backend and device bytes from `to_dict()["compute"]` (`backend`, `device_buffer_bytes`). Never write "GPU" because GPU was requested.
- Redsun's environment default is `uv sync --locked --extra all` (all extras; CuPy 14.2 is in `cuda12`/`all`) — see its [install section](../../03_external/redsun-searching-is-imaging/README.md#install).
- The app's `stitch_saved_snap_rows` is an OpenCV **CPU** action. GPU stitching and reconstruction belong to RTASPT's gated path; a mosaic produced by the app stitch must not be described as a GPU result.

**Mosaic export is a default output.**

- Every fluorescence run exports a mosaic PNG **and** TIFF with a coverage/report file, beside the review artifacts.
- The export is an evidence product, not acceptance: record the enforced gate verdict — `within_gate`, edge RMS and accepted edge count — and describe a failed gate as failed.
- The app stitch writes the PNG by default. A GPU mosaic must go through RTASPT, not the app's CPU action. Crop, registration and collage detail stays in [stitching and collage](references/stitching-and-collage.md).

**Detection and target policy.**

- Default to an Otsu/histogram-derived threshold (`threshold: null`). An absolute threshold is an explicit override that must be justified in the config, and the existing >50 %-signal guard applies **only** to such absolute thresholds.
- Enforce a minimum target radius/area and a minimum separation, and merge same-tile overlapping detections. The planner's `deduplicate_targets` ([geometry](../../03_external/sample_search/src/planner/geometry.py)) skips pairs with the same `tile_id`, so `deduplication_um` alone cannot merge two components in one frame; that needs a structural merge in the consumer.
- Candidate or component counts are not distinct interests. Report both and label which is which.
- Declare and record the review region. Tiles and components outside it are not reviewed, even when they were acquired.
- Record minimum area/radius, separation, threshold policy and any score filter with the checkpoint, so the interest set can be reproduced.

**A revisit is only evidence if it persists.**

- Launch `execute_asi_reviewed_snap_revisit_from_decision` through `acq_ctrl.launch` (the plan-map path). A bare `engine(presenter...)` call can move and expose but writes no Zarr store or positions sidecar.
- Verify `frames_written`, `exit_status` and the landing error from the persisted sidecar/readbacks, not from console output.
- Budget about 2.88 MB per revisit frame at 1200 x 1200 uint16. The Zarr size follows the target count; the review page's size is embedded tile images, not target records.

**No one-off scripts for experiment visualizations.**

- Use the app's own plan/review/stitch/PNG actions, or add the missing capability to the app in its owning repository. A thin session driver that calls those actions is acceptable; an ad-hoc visualization or analysis script is not.
- A stack the app refuses (for example a sidecar reporting `fail`) stays refused; characterize it only in an explicitly labelled diagnostic, never by wrapping it in a new pipeline.

**Dated critical and unattempted list.**

- Keep a dated "critical and unattempted task list" in the run record at every round: per item the status, the evidence, what was **not** attempted, and the next action. Update it when a gate changes, and link the records instead of copying session-specific numbers into this skill as acceptance.

The evidence behind these defaults is in the [large survey record](../../08_session_logs/20261027T_large_survey_speed_01/README.md) (flat/noise derivation, GPU resolution, same-tile overlap, bare-engine revisit, CPU stitch gate) and the [imaging resume record](../../08_session_logs/20261027T_imaging_resume_01/README.md) (built-in stitch, PNG-by-default, gate verdicts). Those are historical measurements on one field, not targets or acceptance for a new run.

## Delegation

When delegation is authorized, use subagents for separable code, recorded-data processing, artifact generation or documentation. Preserve the main agent's sole instrument authority; independent workers receive files, not device handles. Respect available compute resources and the user's requested model/settings.

Every delegation must carry:

- **Inputs**: absolute paths to the exported frames, position sidecars, Zarr/TIFF copies or tables — never a live device handle.
- **Expected output**: absolute artifact paths plus the check that decides success.
- **Forbidden**: any camera, stage, laser, shutter, serial, PVA or session call; any specimen or focus change; edits outside the files the subagent owns.
- **Return**: artifacts produced, checks run with numbers, and what it did **not** verify.

Run independent stages concurrently and write the parallelism into the report. When a subagent's result feeds the chain, the main agent re-checks the artifact against the stage criterion before accepting it; a subagent's summary is a claim until the file and figure confirm it.

Use existing GPU paths for suitable heavy work when requested or supported by measured need and backend qualification. Record device assignment, parameters and CPU-equivalence evidence; an unqualified GPU localizer is not a substitute for the accepted tracking baseline. On a multi-GPU host, separate authorized concurrent jobs by available device and record the assignment. Do not implement another GPU estimator solely because an archived task requested acceleration.

## Stitching and collage evidence

Stitching is the stage most likely to look finished while being wrong. Follow [references/stitching-and-collage.md](references/stitching-and-collage.md) for the border-crop step, PCC-seeded ECC registration, residual gates and the collage/coverage artifacts the operator inspects. The short version:

- Crop or mask the dark borders introduced in the optic path **before** estimating transforms, and record the rectangle or mask you used.
- Seed with phase correlation, refine with ECC, and state the coordinate convention (image placement versus feature-content displacement) next to every transform.
- Enforce the edge-RMS gate the review path enforces; do not accept a mosaic that bypassed it.
- Produce an image collage plus a coverage overlay as the artifact the operator actually looks at, and keep the unblended mosaic beside it.

### Check the lane pitch, not just the seam ratios (2026-10-28)

A feathered mosaic can report 0.97 coverage and seam ratios inside ±11 % while every lane is in the
wrong place, because those metrics measure support and level, not whether neighbouring lanes landed
at the spacing the route declares. Two arithmetic checks catch it before a compose is believed:

- **Across pitch must equal the calibration scale times the route lane step**, uniformly, for every
  lane including the reversed ones. Measured on the recorded 12-lane route, a coordinate-index bug
  wrote the *along* anchor into the *across* slot, so the pitch alternated **428.6 / 658.5 px around
  the true 542.86** — overlaps swung between 541 and 771 px and some joins had almost nothing to
  match on, which is what "the strip overlaps are all wrong" looks like numerically.
- **Compute the overlap each placed pair actually has and read the list**, rather than trusting the
  route. A pair with a few hundred px of overlap cannot be measured or feathered meaningfully.

The general rule behind both: when a plan derives an offset tuple, the axis *name* is not the axis
*index*. `offset_xy_px` is `(x, y)` whatever `along_image_axis` says, and `route_origin_px` returns
`[across, along]`. Deriving the slot from the name silently swaps them.

### Slit mode: record the slit height, and remember n_obs = 1 is the banded case (2026-10-28)

"Slit mode" alone does not say what was composed. The same mode produced a continuous panorama at
`band_width_factor = 3.0` (slit **136.9 px = 25.0 µm**, `n_obs = 3`, the only configuration the app
records as `mode_validated: true`) and a banded one at `1.0` (**44.5 px = 8.1 µm**, `n_obs = 1`,
disjoint, no redundancy). The 2026-10-24 record measured the same effect from the other direction:
span 0.5 (disjoint) leaves a black dashed line at a known seam row and 1.5× removes it, at a measured
**7 % product-sharpness cost**.

Consequences to apply:

- State the **slit height in px and µm and `n_obs`** in every slit result; "slit" without them is not
  evidence of what was reconstructed.
- `n_obs = 1` is the known-banded geometry. A banded panorama at `n_obs = 1` is an expected artifact,
  not a new defect — check the parameter before diagnosing the pipeline.
- Widening is a real trade, not a free fix. The band and the sharpness cost are both measured, so pick
  deliberately and record which was paid.

## Close-out

- For a rehearsal, one run directory links every stage artifact with a digest, calibration and attempt ids, collage and `rehearsal_report.json` naming actual outcomes, measured versus target figures, scope and elapsed time, plus the dated critical/unattempted list from the defaults above. Do not invent a new one-day target from the archived brief.

  `rehearsal_report.json` carries, per stage, at least: `stage`, `attempt_id`, `status`
  (`completed` / `refused` / `not_applied` / `unknown` / `failed`), `artifact` (path plus digest),
  `measured` (the number the criterion is judged on), `criterion`, `verdict`, and `notes` whenever
  the outcome is partial or unknown. At the top level: `specimen_id`, `calibration_id`, `profile`
  and its revision, `resolved_backends` (flat and registration, as the run resolved them),
  `authorization` (who, when, which envelope), `started_at`, `finished_at`, and `software` (commit,
  and whether the worktree was clean). A stage whose artifact is missing is `unknown`, never
  `completed`; a stage deliberately skipped is `not_applied` with the reason. Writing the schema
  once here stops the next session inventing a different one.
- A session log entry under [08_session_logs](../../08_session_logs) with its README (scope, source/revision, method, result, artifacts, evidence status, limitations, next gate) and its index row in the same change.
- Update the canonical backlog rows with dated links to the record, and move urgency only because the gate moved.
- Report documentation checks, runtime tests and physical acceptance **separately**; never let a green suite stand in for a hardware result, or a figure labelled *target* pass as a measurement.
- If a stage's code turns out to be broken during an authorized run, record the failure with its
  evidence and stop that leg. Do not patch source mid-run, and do not re-run the leg in the same
  session to see whether it passes now: a result produced by a tree that changed under it has no
  provenance.

## Stop rules

Stop and report, rather than continuing, when:

- The run would exceed the authorized envelope: motion outside the plan-demarcated bounds, an exposure or setpoint outside the declared values, or a stage the standing authorization does not cover.
- A stage outcome is unknown (timeout, lost readback, unacknowledged stop) — no automatic retry, no optimistic next stage.
- The field is unusable and the only fix would leave the demarcated plan or change the specimen.
- A service or calibration state contradicts the profile, and the fix would require a limit, firmware or configuration change nobody authorized.

Say plainly what was attempted, what the artifact shows, and which gate is now blocked.
