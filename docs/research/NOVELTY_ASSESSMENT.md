# Novelty assessment

**Verdict: useful research prototype; scientific distinctness remains unverified. A* submission readiness is not established.**

The [paper-to-algorithm gate](PAPER_TO_ALGORITHM.md) and [review](PRIOR_ART_REVIEW.md) reject novelty based on joint calibration, a monitoring framework, information matrices, parameter scaling, Schur complements, SVD, selective updates, principal angles, greedy selection or abstention alone. All have close prior art.

## Specific hypothesis being tested

The narrow candidate is a camera–LiDAR maintenance decision procedure that separates:

1. Estimating a constrained update when other calibration groups are held fixed.
2. Attributing that update to a group after allowing rival groups and beam nuisance to explain the measurements.
3. Requiring the actual proposed parameter-change direction to retain unique support across multiple training association gates.
4. Selecting recorded fitting captures by a worst-variant group-discrimination proxy, then independently checking a candidate on reserved captures.

Association variants are finite stress tests, not independent measurements or a probabilistic association model. The procedure is an adaptation of robust subspace reasoning and experimental design. We have not established that the complete formulation is absent from robust fault-diagnosis literature. The review cannot certify this without resolving inaccessible papers and a deeper robust-FDI comparison.

## Falsifiable advantage

Against single-association conditional TSVD and unconditional joint fitting, stable conditional support should reduce incorrect group attribution under ambiguous cross-modal associations, without excessive rejection of useful updates. A real benefit must survive equal input/test support, capture budgets, initialization, compute accounting and independent fault labels. A reduction in training error is insufficient.

## What the current implementation and recordings establish

Small numerical fixtures verify alias rejection, nuisance profiling, every-variant support, constrained optimization and preservation after rejected outer validation. Recorded runs exercise the backend and expose negative outcomes. They do **not** establish fault-classification accuracy, known-correspondence reprojection accuracy, calibrated confidence or superiority of the added mechanism.

Three captures are below the declared comparison threshold. The ten-capture run's best fault-aware candidate does not meet the 1% practical loss-gain threshold. The original optimizer comparator has invalid folds under the new model/domain checks. This is not evidence that our method is more accurate than legacy calibration. Feature budgets, declared angular mask and local initialization also differ from historical app runs, so their numerical errors cannot be compared directly.

## Before a publication claim

- Resolve A4 full text, B1 journal methods and the closest robust-subspace/active-diagnosis formulations; maintain an explicit difference table.
- Obtain independently measured rotation, translation and intrinsic changes, plus genuinely nominal sessions and nuisance-only changes. Do not use filenames or optimizer outputs as labels.
- Evaluate multiple rigs/camera models, scenes, distances, independent sessions and controlled correspondence ambiguity. This phase does not implement a simulator.
- Separate threshold development, uncertainty calibration, model selection and final held-out testing. Current descriptive bootstrap quantities supply no risk guarantee.
- Compare single-variant conditional support, variant-stable support, generic TSVD, frozen legacy refine, joint fits, and random/feature/D/E/contrast selection at matched budgets and reported runtime.
- Quantify false attribution, acceptance errors, missed useful updates and abstention jointly. If the extra mechanism only adds rejection, simplify it or abandon the claim.

A stronger direction would derive a sensor-geometry-specific diagnosability result or a finite-sample, independently calibrated acceptance-risk result under explicit association contamination. That is future research, not a theorem provided by this code.

## Fault diagnostics v2 (6 November 2026)

Method: [FAULT_DIAGNOSTICS_V2.md](FAULT_DIAGNOSTICS_V2.md). Review: [PRIOR_ART_REVIEW_V2.md](PRIOR_ART_REVIEW_V2.md).

### What is *not* new

| Component | Closest prior art |
|---|---|
| Matched-to-chance edge share | Our own maintenance `lift`; the chance-normalisation idea is old |
| NID between reflectivity and intensity | Pandey et al.; Koide et al. |
| Scene-conditioned evidence | Scott et al. (cost-profile ranking); EdO-LCEC (density-driven view count) |
| Local-optimality certificate of a reference | OCaMo/LTO |
| Sequential change detection | MiCaDe (Lepage CPM); Page's CUSUM; robust (clipped) CUSUM; conformal test martingales (Vovk et al.) |
| Nuisance-residualised isolability and ambiguity classes | Robust fault-detection and isolation; matched-subspace detection |
| Parsimony among tied explanations | Standard model-selection practice |

### Candidate contribution

The candidate is narrow: *a negative-control (decoy) reference inside each held-out capture, used as the common
currency for drift detection, attribution, acceptance and persistence monitoring.*

1. Every candidate's held-out gain is split into a chance-predicted part, which the decoys produce, and a
   chance-referenced part. Only the second counts as evidence for a calibration change. The first is reported
   as the explicit nuisance counterfactual: NUISANCE_SUSPECTED.
2. The same decoy contrast decides two things: whether a capture can carry evidence at all (scene-conditioned
   quality, without a learned density model), and whether the *current* calibration is confirmed. This splits
   the old KEEP into KEEP_CONFIRMED, REFERENCE_NOT_CONFIRMED and INSUFFICIENT_EVIDENCE.
3. Two physically different cues, each referenced to its own decoys, must agree before a change is declared.
4. Sequential monitoring of the decoy contrast needs no nominal density model fitted from labelled data.
   MiCaDe needs a GMM fitted on calibrated sequences; LTO needs Beta densities fitted on calibrated and
   decalibrated sequences.

We found no reviewed calibration-monitoring paper that references its alignment statistic to displaced copies of
the same capture. Absence from the reviewed set does not prove novelty. Permutation and shift controls are
common in image registration and in statistics generally, so the novelty is at most an application and
integration claim. One reviewer could reasonably call it an engineering control.

### What the evidence shows and does not show

See [VERIFICATION_RESULTS.md](VERIFICATION_RESULTS.md#fault-diagnostics-v2) for the numbers.

- **Shown on recorded data, without labels.** The production held-out loss has a scene-dependent gradient of
  5–15 % over 4 px. This is 5–15× the acceptance threshold, and 75–105 % of it is predicted by the decoys. The
  decoy contrasts do not show it. This is a measured property of the current backend, and the main empirical
  finding of this round.
- **Shown semi-synthetically, held out and preregistered, relative to an anchor.** On two held-out recordings,
  the experimental layer, compared with production:

  | Measure | Proposed | Production |
  |---|---:|---:|
  | False alarms on no-change trials | 0/54 | 12/54 |
  | Detected injected changes | 29/48 | 16/48 |
  | Wrong attributions | 3 | 24 |

  The persistence monitor separated persistent changes (17/24 alarmed) from single-capture corruption
  (0/18). All five preregistered expectations were met.
- **Withdrawn or not demonstrated by the held-out ablations.**
  - *Candidate contribution 3* (two-cue agreement) is withdrawn. Requiring intensity agreement cost 13 of
    48 detections and prevented no false alarm.
  - *Decoy subtraction inside the decision rule* is not demonstrated. The raw oriented matched share
    performed equivalently on held-out data. So candidate contribution 1 holds as a *measurement and
    diagnosis* of the production loss's bias, and as the basis of reference confirmation and quality gating
    (contribution 2). It does not yet hold as a decision statistic that beats the raw oriented share.
  - The held-out gain over production is explained mostly by three changes: oriented edge agreement in place
    of nearest-edge distance, replication on informative captures, and quality gating.
- **Not shown.**
  - Correct *attribution*: proposed 1/48, production 4/48. R, I and often T remain one ambiguity class.
  - Physical-fault accuracy and operational false-alarm rates.
  - Generalisation beyond two held-out recordings of one hardware family.

**Verdict.** A defensible methodological improvement with a measured failure mode behind it. The strongest
results are the bias measurement (chance explains 75–105 % of the production loss gradient) and a held-out
reduction of false alarms and wrong attributions. Novelty is modest. The decoy-referenced decision statistic has
not shown an advantage over a simpler oriented-share statistic. The intensity agreement rule should be removed
or redesigned, for example by weighting it by its own informativeness. Attribution is the main open problem.
