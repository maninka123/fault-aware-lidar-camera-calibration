# V3 research gaps and falsifiable decisions

Date: **6 November 2026**. This document specifies research questions and failure conditions; it reports no new detection/classification result. Existing V2 recordings, including its former held-out recordings, are development data for V3.

## What already exists

| Function | Existing implementation | Consequence |
|---|---|---|
| Projection, local rotation update, calibration serialization | `geometry.py` | Verify analytical sensitivities against this exact model and perturbation convention. Do not substitute a pinhole approximation. |
| Frozen associations and scalar image-normal residuals | `residuals.py` | Each normal observes one displacement component. A full 2D signature gives an optimistic upper bound if only a normal residual is measured. |
| Scaled conditional information, rival/nuisance profiling, principal angles and stable subspaces | `observability.py` | These operations are already present and are established mathematics. Reuse them. |
| Recorded-capture selection with random/count/D/E/contrast strategies | `evidence_selection.py` | New selection must outperform these at matched budgets and use the same available information. |
| Selective fitting and production decision | `selective_optimizer.py`, `decision_policy.py`, `calibration_pipeline.py` | Diagnosis is not permission to write a calibration. Preserve existing production behavior. |
| Descriptive uncertainty | `uncertainty.py` | A Hessian/bootstrap summary is not a calibrated fault probability. |
| V2 cue scoring, held-out replication, ambiguity, CUSUM/conformal diagnostics | `fault_diagnostics/` | Improve the evidence input before proposing another temporal detector. |

## Priority 1: which physical explanations can this scene distinguish?

**Question:** Does the proposed fault's projected displacement remain distinguishable after a rival calibration model and declared nuisance are allowed to explain the *same observations*?

The missing quantity is not another singular-value threshold. It is the expected residual mismatch at a physically meaningful fault magnitude, connected to depth, bearing, image location, measured normal and uncertainty.

**Required tests:** optical-axis limits; fisheye distortion derivatives; nonzero baseline rotation/translation; translation scale at fixed bearing; narrow versus wide angular coverage; shallow versus varied depth; co-oriented versus varied image normals; rank loss; a true joint effect; nested models; nuisance aliases; coordinate/unit consistency. Independent finite differences must verify the derivative convention actually used in fitting.

**Failure criterion:** an alleged unique fault label changes merely because units change, a subspace is reparameterized, duplicated correlated points are added, or a rival model has extra columns. In that case the inference formulation is wrong or its assumptions are unreported.

**Boundary:** local distinguishability is conditional on associations, noise scale, fault magnitude and camera model. It is not a global identifiability theorem or proof of a physical mounting change.

## Priority 2: correspondence quality before more cues

| V2 finding | Competing explanation | Experiment that separates explanations |
|---|---|---|
| Rotation/principal-point alias | Narrow FoV, one-sided image support, edge-normal loss, local linearization, or an actual camera-model gauge | Sweep bearing coverage and normal direction at fixed depth/noise, then repeat with the repository fisheye model and fixed 3D geometry. Compare scalar measured residuals and full 2D oracle measurements separately. |
| Weak translation | Distant scene, limited inverse-depth variation, missing depth range or poor normal directions | Match feature count/angular coverage and vary range/depth distribution. A near/far stratification alone cannot recover an unobserved displacement direction. |
| Dense-image false improvement | Nearest unrelated edge and reassociation, not true alignment | Hold evaluation support fixed; compare orientation-aware matching, lift and displaced controls under added texture. Audit visibility losses. |
| Intensity agreement loses detections | Low cue sensitivity, correlated scene artifacts or modality mismatch | Compare edges alone, mandatory agreement and an informativeness-gated auxiliary cue. Do not add correlated cue scores as independent likelihoods. |
| Decoys do not beat oriented share | Helpful quality reference but redundant decision statistic | Keep raw oriented share as a mandatory comparator. Retain decoys centrally only if a declared outcome improves; otherwise use them as an audit/ablation. |
| Quality filtering helps | True rejection of bad correspondences or preferential removal of difficult drift cases | Report retained data/coverage by fault class as well as accuracy. Freeze quality criteria before final evaluation; do not choose support using final test gains. |
| Selection lacks clear advantage | Current geometry already redundant, score targets the wrong direction, or cost is dominated by preprocessing | Compare selection curves at equal capture/feature/fitting budgets and include preprocessing time. Report no advantage when all-data/simple selection wins. |

Depth jumps, surface creases, occlusion boundaries and intensity texture have different measurement mechanisms. A physically reliable LiDAR edge can still have no visible camera counterpart. Visibility masks, association alternatives and edge-normal diversity need explicit evidence fields; a feature count is insufficient.

## Priority 3: ask for information that could resolve the ambiguity

The selection question is conditional: given the current plausible effects, which *recorded* capture would make the common rival fit fail by the largest useful amount per acquisition/processing cost?

**Traps to avoid:**

- Minimizing separation over two models that both allow zero change gives zero. Specify a nonzero effect, lower effect bound, or a current fitted candidate; disclose the choice.
- Nested models share predictions. R cannot be separated globally from RT, since T can be zero. Test the incremental effect and retain compatible supersets instead of inventing positive separation.
- Refit shared physical parameters across stacked captures. Independently refitting the rival in every capture measures a different, more permissive model.
- Profile shared nuisance after stacking and whitening. Giving every capture an arbitrary 2D image offset exactly absorbs principal-point change; that diagnosis then cannot be recovered by more point count.
- Small principal angle is geometric overlap, not a decision error probability. Magnitude and covariance determine whether the remaining signal is usable.
- A longer accumulation window is not an independent view. Without motion/visibility/timing labels its utility remains conditional.

T-optimal model discrimination and active fault-diagnosis design already cover the broad selection principle; see [the review](LITERATURE_REVIEW.md). A useful V3 adaptation must establish a concrete sensor/scene advantage.

## Priority 4: monitoring and safe acceptance

Reuse V2 temporal code. Compare its old contrast stream with any proposed quality-conditioned diagnostic stream under nominal, abrupt/gradual drift, isolated corruption, lighting change, correspondence failure, scene transition and timing error. With unavailable motion/timestamp information, timing and calibration may remain observationally equivalent. Do not label timing as ruled out.

A reference period is nominal only by an external assumption or independent calibration evidence. “No detector alarm” cannot prove that assumption. Persistent scene bias can remain persistent after robust aggregation. Report per-recording false alarms/delay and the number of independent sessions; do not turn repeated points/captures into independent trials.

Drift detection, group attribution, estimable directions, candidate optimization and independent acceptance are separate outputs. An ambiguous explanation does not justify silently updating all groups. Unsupported probabilistic acceptance claims must wait for independent development, risk-calibration and final-test sessions.

## Data and publication gaps

There are no independently measured physical faults in the current V2 evaluation. Parameter perturbations of a recorded dataset are software/geometric verification relative to an uncertain anchor, not new physical sensor observations. They cannot validate occlusion changes, mechanical timing effects, lens changes or operational false-alarm rates.

The most valuable next collection uses measured mount rotations and translations, independent intrinsic checks before/after changes, scene geometry with controlled angular/depth diversity, timestamped nuisance-only sequences and multiple rigs/sessions. Reserve complete independent sessions before tuning. The simulator interface should preserve camera model, poses, visibility, depth, timing, edge identity and sensor profile; its known truth must not enter the algorithm input.

A strong publication still needs a narrow novelty statement surviving robust-FDI/model-design prior art, a demonstrated improvement beyond V2 and simpler ablations, independently justified labels, and evidence across scenes/rigs. If V3 adds only abstention with lower coverage, report that tradeoff rather than calling it solved fault identification.
