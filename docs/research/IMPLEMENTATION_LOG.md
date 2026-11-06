# Implementation log

Project date: **5 November 2026**. Work is isolated under `Fault-aware calibration/`; the original maintenance project and recordings are read-only inputs. No push, merge, production credential change or hardware calibration write was performed.

## 1. Baseline and input audit

- Cloned the published repository at `d0931889bf2f2a5ecb2cca9dd3c8a77c9fa8c763`, branch `research/fault-aware-calibration`.
- Executed 28 baseline tests in the clone and inspected the separate development tree, whose baseline had 56 tests.
- Distinguished published documentation/screenshots from the older committed application source.
- Audited edge extraction, equidistant projection, optimization priors, update comparison, movement, uncertainty and result writing. Recorded higher-distortion-term loss, invisible-zero residuals, dependent sensitivity checks and validation-range leakage concerns.
- Created the path/hash manifest for the two primary recorded caches, plus inventories of additional caches. No simulated-drift outputs were used as physical-fault evidence.
- Deliverable: [CURRENT_SYSTEM_AUDIT.md](CURRENT_SYSTEM_AUDIT.md).

## 2. Paper-to-algorithm gate before implementation

- Prepared [PAPER_TO_ALGORITHM.md](PAPER_TO_ALGORITHM.md) and an exploratory mathematical draft before writing the numerical engine.
- Compared all twelve mandatory works, with central mathematical contributions, assumptions, limits and adopted/rejected/deferred concepts. Marked A4 abstract-only and B1 supplement/code access explicitly.
- Investigated fault-subspace diagnosis and robust model-discrimination design beyond calibration papers. Rejected broad novelty claims for joint estimation, monitoring, Hessians, SVD, informative selection and abstention.
- Chose a narrower falsifiable adaptation: distinguish estimability from group attribution and stress the actual proposed change across training correspondence variants.
- Inspected six external reference repositories, recording commits and license/release limits; no external code was transplanted.
- Later read extracted C3 Sections III-B/IV and strengthened its comparison with the actual NID profile descriptor/ranking equations. Added primary-source search context; originality remains open.
- Deliverables: [PRIOR_ART_REVIEW.md](PRIOR_ART_REVIEW.md), [NOVELTY_ASSESSMENT.md](NOVELTY_ASSESSMENT.md).

## 3. Backend implementation

- Added parameter hypotheses and physical scales, SO(3) retraction, validated projection retaining k3/k4, central fixed-association Jacobians, thin nuisance projection and conditional/group information.
- Implemented stable right-parameter subspaces with both mean-projector proposals and every-variant support/sensitivity checks. Variant counts do not multiply independent evidence.
- Added bounded reduced optimization, exact frozen-group behavior, finite penalties for lost training projections and fixed-support capped held-out nearest-edge loss.
- Reused the cloned capture readers and edge extractors. Replaced all-data fitted image-circle preprocessing with a declared image-size mask, avoiding held-out appearance in training preprocessing.
- Added training-only greedy contrast selection plus random/feature/D/E/all alternatives. Shared nuisance is eliminated after stacking captures.
- Added nested/non-nested model ambiguity handling, explicit failed-fold refusal, untouched outer validation and conservative capture-cluster uncertainty.
- Added JSON/Markdown reports, accepted versus proposed deltas, stale-reference-metadata separation and exact reference retention on rejection.
- Final candidate support is recomputed after optimization. Attribution checks the actual update's supported energy, rather than declaring an entire group identifiable merely because one axis is supported.
- Corrected covariance inversion to use the rank-checked Jacobian SVD, avoiding a second, inconsistent truncation of its squared information spectrum.
- Final equations: [MATHEMATICAL_METHOD.md](MATHEMATICAL_METHOD.md). The draft remains an explicitly superseded design record.

## 4. Integration and resource controls

- Public Python API: `assess`, `calibrate_from_scratch`. CLI: `python -B -m research_calibration`.
- Added selectable research/joint/no-observability/no-selection/single-variant/legacy-refine/strict-legacy modes.
- Preserved inherited targetless initialization through an adapter. Subsequently executed the full three-capture initializer under a low-priority watchdog. Final report scoping was replayed from the saved estimate without repeating the coarse search.
- Added a small **Research check…** button in the cloned app's manual setup page, enabled for stacked captures. It launches the same CLI in a child process, shows logs and links reports, with no accept/device-write control. It refuses concurrent normal checks.
- User reported a previous Windows blue screen and requested care. Thereafter all evaluations remained sequential with one numerical thread, no GPU work, and soft memory checks at work boundaries. No Windows/driver/service settings were changed. These controls do not diagnose or guarantee prevention of kernel faults.
- Added sequential verification, recorded benchmark and additional-ablation scripts. No simulator or broad UI redesign was added.

## 5. Problems found and resolved

| Finding | Resolution / remaining scope |
|---|---|
| A solver test expected tighter accuracy than its function-cost termination tolerance | Verified the 2.3e-6 difference; used a justified 1e-5 numeric tolerance while retaining exact forbidden-coordinate checks. |
| Final uncertainty initially used the pre-update linearization | Recompute final associations/Jacobians/support before attribution and covariance. |
| A nonzero unique rank could incorrectly bless an aliased update direction | Require actual directional support in final stable unique and hypothesis subspaces. Add final-support rejection regression. |
| Rejected result could expose candidate deltas as accepted updates | Accepted deltas are zero on rejection; candidate deltas remain explicitly separate. |
| Candidate export could retain stale reference quality/uncertainty | Move historical evidence under reference_metadata; preserve unchanged parameter groups. |
| Initial legacy comparator KEEP used wide gates that temporarily released no coordinates | Corrected the wrapper to the original nuisance-only `[4,3,2,2]` schedule. This was a comparator invocation bug, not evidence against the legacy algorithm. |
| One ten-capture legacy RTI fold violates research camera/domain bounds | Preserve the failure and unavailable aggregate; no fold was dropped. Strict original workflow is separately tested. |
| Mean projector could hide a failing correspondence variant | Verify retained joint basis under every variant; report support, sensitivity and variant ranks. |
| Historical OpenCV distribution version differed from imported cv2 | Record imported 4.8.1 and overlapping existing distribution metadata separately; no global dependency changes. |
| Initializer hit an exactly 260-character Windows image path | Added local extended-path handling and a real long-filename regression; no OS policy or original numerical code changed. Retry completed. |
| Later KEEP support could be confused with initial-estimator properties | Save conditional assessment separately; initial output reports unvalidated initialization, no historical delta and no inferred scalar support/nullspace. Replayed finalization on the actual saved estimate. |
| A calibration in an output directory could be overwritten before an assessment marker existed | Require a new empty assessment directory; verify existing calibration bytes remain untouched. |

## 6. Executed checks and experiments

Final commands and evidence are in [VERIFICATION_RESULTS.md](VERIFICATION_RESULTS.md).

- `python -B verify_research.py --output research_artifacts/verified_37`: **28 baseline + 37 research tests, all pass**.
- Five methods on `creep_three`: complete reports; all retain reference for insufficient evidence.
- Five methods on `enclosure_off_ten`: completed in 27.15 seconds including shared extraction; no accepted update. Fault-aware best CV squared-loss gain 0.6243%, below 1% threshold. One invalid legacy joint fold remains visible.
- Single-association support and random/feature/D/E selection ablations: all keep current. No performance advantage of the added ensemble/selection mechanism established.
- `python -B verify_desktop_bridge.py`: actual offscreen desktop-child-process run on creep recordings, exit code 0, structured report generated.
- Strict legacy `assess --strategy legacy` on creep: completed; BORDERLINE, 1.4085 px movement, 0.1856 px spread, 4/7 regions improved. Outputs landed only in the cloned project.
- Full initializer: completed in 188.75 seconds under a 600-second/1.5-GiB child-process watchdog. Maximum sampled child memory 285.72 MiB; minimum sampled available physical memory 25,929.54 MiB. The initial candidate requires independent review despite its inherited heuristic label.
- Built a figure and inspectable JSON summary from computed results and visually checked the plot.

## 7. Completion boundaries

Core backend, numerical verification, real recorded maintenance comparisons, ablation tooling, legacy execution, a minimal desktop bridge and research documentation are delivered. No code or data has been published.

Unsupported: independently measured initialization accuracy, other camera families/sensors, moving timing effects, nominal false-alarm tests, physical fault-label accuracy, calibrated interval/risk claims and independent multi-session generalization. Missing full-paper access and unresolved robust-FDI overlap prevent novelty certification. This is a prototype with a critical research assessment, not an automatically positive conference-readiness conclusion.

## 8. Fault diagnostics v2 (6 November 2026, branch `research/fault-diagnostics-v2`)

Method: [FAULT_DIAGNOSTICS_V2.md](FAULT_DIAGNOSTICS_V2.md). Review: [PRIOR_ART_REVIEW_V2.md](PRIOR_ART_REVIEW_V2.md).
Protocol: [PREREGISTRATION_V2.md](PREREGISTRATION_V2.md).

### Production code touched (behaviour unchanged except one crash fix)

- `calibration_pipeline.assess(..., fold_observer=None)`. A read-only callback receives copies of each fold's
  fitted parameters and of the final candidate. The default `None` leaves every result unchanged; a parity test
  compares results with and without it.
- `legacy_adapter.load_capture_bundle(..., intensity_points=0)`. When the value is above zero, it also keeps a
  reflectivity sample and the capture time, using a separate random generator. The default leaves the bundle
  unchanged.
- `observability.hypothesis_basis` and `uncertainty.cluster_uncertainty`. An empty supported basis used to make
  `scipy.linalg.null_space` fail inside LAPACK. Now every direction is reported unobservable. This path only
  occurred when a capture had no depth edges, which happened in the synthetic tests; the recorded data have
  depth edges.
- `__main__`: a new `diagnose` command.

### New modules: `research_calibration/fault_diagnostics/`

| Module | Purpose |
|---|---|
| `config` | `DiagnosticsConfig`, the frozen constants |
| `cues` | Decoy-referenced edge and intensity contrasts |
| `evidence` | Per-fold counterfactual table, including the chance-predicted production gain |
| `policy` | Experimental verdicts and ablation switches |
| `sequential` | Clipped CUSUM, conformal test martingale and the persistent/transient label |
| `perturbations` | Known calibration changes and nuisances (verification only) |
| `runner` | Production assessment plus `fault_diagnostics.json` |

### Development history (development recordings only)

1. **Measured the loss bias** (`tools/probe_loss_bias.py`).
2. **Round 1** (`october_device_one`, one replicate). With a 0.005 edge margin and an intensity *veto*, the
   method alarmed on the nominal anchor, on global blur and on one desynchronised capture. Fold refits from a
   converged anchor gain up to 0.7 contrast points.
   - Changes: margin set to 0.01; intensity *agreement* required; single-capture corruptions directed at
     comparison (non-outer) captures.
3. **Round 2** (partial). Ambiguity sets listed every superset.
   - Change: a parsimony rule, keeping only the minimal tied explanations.
4. **Round 3** (`october_device_one` and `enclosure_off_ten`, three replicates). The doubled edges-only margin
   cost 7 of 15 detections on `enclosure_off_ten`.
   - Change: removed, so the single-cue margin equals the base margin.
5. **Sequential, development.** A single extreme capture raised CUSUM alarms, and the spread of a 4-capture
   window was too small.
   - Changes: Huber clip at 2 (below the threshold of 4); spread floor of 0.25·|median|; cues already at chance
     are reported as uninformative.

The held-out recordings (`enclosure_on_twelve`, `october_device_four`) were not opened by any v2 code before the
preregistration commit.
