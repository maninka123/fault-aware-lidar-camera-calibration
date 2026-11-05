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
