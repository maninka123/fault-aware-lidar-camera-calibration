# V3 novelty comparison and claim boundaries

Assessment date: **6 November 2026**. **No publication-level novelty or readiness is established by this review.** This is a comparison of the proposed research mechanism, not a claim that all V3 modules/experiments have already passed. Actual implementation and numerical results belong in `IMPLEMENTATION_LOG.md` and `EXPERIMENTAL_RESULTS.md`.

## Prior-art difference table

| Proposed element | Already covered by | What could still be a useful V3 difference | Required evidence |
|---|---|---|---|
| Correct fisheye sensitivities | Differentiable camera models and standard calibration Jacobians | A verified derivative implementation matching this repository's rotation, translation, distortion and beam conventions | Independent finite differences, nonzero-baseline/axis/invalid-domain tests; not novelty by itself |
| Rotation/translation/intrinsic signatures | Calibration sensitivity analysis; existing joint calibration | Explicit scene-conditioned explanation of which finite physical effects are distinguishable through *measured* edge normals | Controlled depth/bearing/normal sweeps; contrast with full-2D oracle observations |
| Whitened nuisance/rival projection | Scharf–Friedlander matched subspaces; statistical FDI/parity methods | Consistent integration with association uncertainty and camera geometry | Covariance/nuisance assumptions, rank-deficient tests and failures of misspecified nuisance models |
| Principal angles and conditional singular values | Established subspace geometry; existing V2 `observability.py` | Interpretable weak effect combinations and where their evidence occurs | Effect-size/noise-aware discrimination beyond an angle/threshold plot |
| Estimate only identifiable directions | OA-LICalib TSVD; existing selective optimizer | Link diagnosable physical explanations to permissible update directions | Demonstrate preservation of unsupported directions and independent update validation |
| Joint intrinsic/extrinsic fitting | JointCalib, Shen et al., Bultmann et al.; existing RTI fit | A fault explanation contract that refuses unsupported attribution | Matched truth-labelled comparisons; joint fit alone earns no claim |
| Scene quality / oriented edges | OCaMo frame preselection, EdgeCalib, Scott et al.; V2 quality gating | Geometry-specific reliability tied to actual discrimination loss | Coverage-aware ablations versus simpler oriented share/quality rules |
| Uncertain correspondences | Yuan et al. propagated noise; UniCalib probabilistic matching; V2 association variants | Conservative stress testing of explanation stability without pretending variants are a probability law | Alternative-association experiments and unknown-correspondence failures |
| Choose captures that distinguish rivals | Classical T-optimality, multi-model design, active FDI; V2 contrast selection | A finite-effect camera-specific utility exposing the scene information needed next | Accuracy/delay/capture budget and total cost versus random/count/D/E/V2/all |
| Sequential persistence | OCaMo, MiCaDe, CUSUM/conformal literature; V2 monitor | A better diagnostic signal supplied to the existing detector | Matched nuisance/drift streams and per-recording delay/false alarms |
| Reference confirmation, abstention and safe updates | Existing V2; monitoring/estimation separation in prior work | Coherent preservation of physically equivalent explanations through acceptance | Truth containment, selective accuracy/coverage and false update rate |
| Risk-controlled acceptance | Conformal/risk-calibration methods under explicit assumptions | Future independently calibrated update acceptance | Separate labelled development/calibration/test sessions; unavailable now |

The [literature review](LITERATURE_REVIEW.md) records primary links, access levels, inspected software commits and license boundaries. “Not found among reviewed papers” never means “never published.”

## Candidate contribution, stated narrowly

The defensible research hypothesis is a **camera-geometry-conditioned explanation and data-request procedure**: a fixed physical fault effect is tested against nuisance and rival explanations using the actual fisheye residual model; the system preserves the explanations that the available measurements cannot separate and identifies recorded observations expected to expose their difference.

The potential contribution would be a new, validated characterization or empirical result about this camera–LiDAR ambiguity and its resolution. Standard projection derivatives, whitening, Schur complements, SVD, principal angles, robust aggregation, maximin selection and abstention remain established tools. Giving their combination a new package or acronym does not establish novelty.

## Why the illustrative direction needs revision

“Geometry-Conditioned Fault Signature Analysis” alone can collapse to the conditional Jacobian analysis already implemented in V2. A stronger research formulation must specify a nonzero fault magnitude, noise/reliability model, observable residual components, nuisance-sharing structure and rival parameter fitting rule. Otherwise it measures rank while leaving the actual fault decision undefined.

For candidate mean displacement `m_i` and rival design `A_j`, the descriptive mismatch

`min_b ||P_nuisance_perp (m_i - A_j b)||^2`

is a matched-subspace/model-discrimination quantity. Under a correctly specified common Gaussian covariance it relates to a noncentrality/separation measure, but arbitrary robust weights and uncertain associations do not make it a likelihood ratio. Its experimental usefulness must be measured rather than inferred from the formula. Designs based on this discrepancy belong to the T-optimal family, not a newly discovered class.

Nested hypotheses cannot all be mutually separated: a true pure-R effect belongs to RT, RI and RTI whenever their additional components are zero. Parsimony is a model-selection convention, not proof that the extra physical faults are absent. The report should distinguish a minimal supported explanation, compatible supersets and alternatives that are actually rejected. If the scientific question requires exact nonzero group support, declare effect floors and test sensitivity to them.

## Claims that are currently rejected

- “First joint intrinsic/extrinsic LiDAR–camera calibration,” “first observability-aware selective update,” and “first active capture selection for fault isolation.”
- “Full fault identification” based only on a lower fitting loss, a full-rank Jacobian or a unique minimum selected by a complexity penalty.
- “Controlled false alarm,” “fault probability,” “confidence of physical diagnosis,” or “safe update probability” without the required distributional/independent calibration evidence.
- “Independent V3 held-out validation” using V2's already inspected recordings.
- “Physical calibration accuracy” inferred from nearest-edge distances, reference-anchor perturbations or simulated visibility that is absent from real recorded observations.
- “More informative captures” merely because they contain more points; repeated/correlated points can increase an uncorrected score without adding independent information.

## What would strengthen or contradict the contribution

| Finding | Scientific implication |
|---|---|
| Wider measured angular support separates R/principal-point effects at matched noise/count, with verified fisheye signatures predicting the transition | Supports a concrete geometry-conditioned ambiguity characterization; compare against existing sensitivity analysis before claiming novelty |
| Depth diversity improves translation identification after controlling bearing and normal directions | Supports a useful acquisition rule; inverse-range parallax itself is established |
| V3 ambiguity sets contain true effects more often while exact attribution/coverage improve at matched budgets | Supports an inference improvement; report all three outcomes, not only fewer wrong labels |
| Active selection resolves ambiguity earlier than random/count/D/E/V2 across independent sessions | Supports the application-specific utility; does not create a new experimental-design principle |
| Apparent gains vanish with true correspondences, matched support, session-level evaluation or equal compute | Contradicts the claimed mechanism and points to evaluation/front-end artifacts |
| More abstention is the only gain, or a simpler oriented-edge quality rule matches performance | Narrow the claim or simplify V3; do not bury the ablation |
| No reliable discrimination even with diverse geometry and independent truth | Investigate camera-model error, correspondence bias and unmodelled timing; the parameter-group hypothesis may be inadequate |

## Remaining review limits

The full OCaMo manuscript was recovered and inspected in this round. Shen et al.'s full method, UniCalib's full PDF and the active-FDI sensor-selection paper's full derivation were not accessed. Fouladirad–Nikiforov's linked full PDF timed out; only publisher introduction/abstract were reviewed. The review is sufficient to reject broad novelty claims, not sufficient to certify the absence of a closer formulation. Independent physical validation and evidence across sensor families remain essential.
