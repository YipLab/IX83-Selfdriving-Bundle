# Operator brief (verbatim)

Source: direct operator instruction, 2026-10-26. The quote is preserved verbatim as historical intent and authorization for that task. It does not authorize a new run merely because another agent loads the skill. Current-session scope and authorization govern execution; the [canonical implementation increment](../../../02_docs_offline/redsun_rtaspt_integration_next_steps.md#manuscript-driven-implementation-increment-2026-10-27) governs priorities.

> Continue with the description in any of the global/submodule next step document headlessly with this fixed sample. Remember the need is to validate on exsiting stationary sample the runnability of the full software pipeline before switching to live cell sample in 1 day. You are authorized to use the stage, the camera, and the laser to move inside the physicial boundaries demarcated by the plans. You may spawn any number of subagents to perform code implementation or reconstruction/stitching/processing work (for stitiching, try methods such as cropping out dark borders introduced in the optic path, PCC-seeded-ECC, etc, compute image collage as artifact/evidence for my inspection); howerver, only the main agent is allowed to use the instrument. Delegation needed to share compute/dual-GPU/Disk resources (anything can be accelerated should run on the GPU Path). You have unlimited inference tokens, and your context budget is bigger than you think.

## Meaning in the original rehearsal task

| Statement | Operative meaning in the skill |
| --- | --- |
| "any of the global/submodule next step document" | Discovery step across [02_docs_offline](../../../02_docs_offline) and submodule `docs/`; follow the page that names itself canonical for ranking. |
| "headlessly" | No napari/Qt window from an agent session; offscreen widget construction only for contract checks. |
| "this fixed sample" | No specimen, objective or mount change between stages. |
| "before switching to live cell sample in 1 day" | The live-cell switch is the gate this work serves, and the deadline is a cut-selection constraint — not a reason to relabel unverified work. |
| "authorized to use the stage, the camera, and the laser ... inside the physicial boundaries demarcated by the plans" | Authorization in that task for bounded plan execution only: plan-declared envelopes, exposure and laser setpoint. Not limits, firmware, profile changes, motion beyond the plans or blanket permission for a later task. |
| "spawn any number of subagents ... code implementation or reconstruction/stitching/processing" | Delegation covers files and compute only. |
| "only the main agent is allowed to use the instrument" | Sole command authority: sessions, devices, PVA services, serial ports. Subagents never hold a device handle. |
| "share compute/dual-GPU/Disk resources" | Independent stages run concurrently, pinned to separate GPUs, with separate run directories and recorded assignment. |
| "anything can be accelerated should run on the GPU Path" | Registration, PCC/ECC, compositing, reconstruction, anisotropy, tracking run on GPU with a recorded CPU-equivalence check. |
| "unlimited inference tokens ... context budget is bigger than you think" | Do not trade verification for token economy; do keep the conversation surface small (no giant pasted logs or inline image walls) and run heavy numeric work in the run directory. |

## Scope notes

- The brief authorized instrument use for the original validation objective. A later task must have applicable session authorization; a different sample, objective or live-cell run is not covered by this archived quote.
- Anything that changes physical safety state — interlocks, E-stop, firmware, limit configuration — is outside the brief regardless of how convenient it would be for a stage.
- The one-day figure is the operator's planning constraint as stated. Record the actual elapsed time and what slipped; do not restate the deadline as an achievement.
