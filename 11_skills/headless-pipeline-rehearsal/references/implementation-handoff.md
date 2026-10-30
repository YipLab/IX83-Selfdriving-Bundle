# Manuscript-driven implementation routing

Planning update: 2026-10-27. This reference routes work; it does not own priority or repeat the backlog. Read the [canonical Q01–Q12 increment](../../../02_docs_offline/redsun_rtaspt_integration_next_steps.md#manuscript-driven-implementation-increment-2026-10-27) and the relevant [technical work package](../../../02_docs_offline/Stage_Scanning_TIRF_Implementation_Work_Packages.md#manuscript-to-implementation-update-2026-10-27). Track D remains the leading instrument gate. The [slot registry](../../../09_reporting/manuscript_slots.md) names expected outputs; [reporting next steps](../../../09_reporting/next_steps.md) names evidence needs, not another execution order.

## Route the requested work

| Work | Owner and existing starting point | Required distinction |
| --- | --- | --- |
| Q01/Q12 provenance and exports | Bundle run manifests, saved-data handoff/verifier, reporting CSV/config and figure builds | Transfer/review before repeating measurements; real/synthetic status and source identity remain explicit |
| Q02 timing and action records | Redsun acquisition/storage boundary and bundle calibration/clock records | Exposure, arrival, decision, command and observed response have identified clocks and uncertainty; a timeout is not proof of non-execution |
| Q03 policy and Q05 calculations | Installed `planner` package, acquisition-space and speed/adaptive-broom modules | Pure policy/calculation code proposes; it neither calls devices nor implements reconstruction |
| Q04 acquisition integration | Redsun Presenter/RunEngine, ASI service, finite camera capture and storage | Port the onset session prototype with stepped parity first; capability/response qualification precedes continuous-speed claims |
| Q06 reconstruction and Q10 revisit validation | RTASPT processing, acquisition-host registration/stitching, bundle references and accepted mode-specific survey/revisit records | Image-derived consistency is distinct from independent spatial accuracy; do not reopen implemented calibration/refusal code without evidence |
| Q07 matched comparison | Bundle experiment manifest invoking existing app plans and offline reducers | Same footprint, target/quality requirement, complete time endpoint and independent field/specimen unit; plots do not define measured performance |
| Q08 SPT and Q11 readouts | RTASPT tracking/diffusion/drift/precision, polarization and astigmatic processing, with bundle optical/control records | Existing algorithms need workflow/control qualification; track counts and heuristic classes do not establish biological replication or calibrated transport |
| Q09 sustained processing | Acquisition-host publication/consumer lifecycle, RTASPT processing kernels or recorded-file entry points | Identical-input agreement, frame completeness and physical throughput/latency are separate outcomes |

## Reuse before adding a new path

The app's adaptive raster uses bounded point moves and service-arrival metadata; its live-buffer route is not the capture-ring route. The leading/trailing onset demonstration remains a separate session prototype until integrated. RTASPT already provides calibrated MSD/fits, drift controls and localization-precision analysis; the reporting SPT plotting adapter is a consumer, not a new scientific fitting engine. The pure planner remains independent of the Redsun runtime.

Retain one Redsun session as command authority and managed services as device I/O. RTASPT does not regain camera/stage acquisition. Pycro-Manager remains the temporary compatibility path. New service/process placement requires measured timing, memory and lifecycle need. No change to a package lock, source pin, release state or remote is implied by picking a backlog item.

The existing rehearsal report, low-contrast refusal and scoped brightfield/fluorescence hand-eye/survey/revisit records supersede older instructions to create them from scratch. Search-scan, anisotropy and tracking use separate supported entry points; unsupported top-level request keys must remain refused. Record each stage outcome separately, including justified not-applied outcomes, while leaving quantitative modality acceptance open.

For closure, synchronize the owning technical document and canonical row with the actual source revision, input/calibration identity, checks and evidence record. Update reporting slots/panel statuses only when the corresponding scientific evidence is accepted; do not silently fill manuscript promises with incompatible pilots or placeholder data.
