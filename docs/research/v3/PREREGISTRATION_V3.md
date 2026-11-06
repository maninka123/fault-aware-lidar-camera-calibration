# V3 experimental protocol

Protocol recorded on 6 November 2026 before executing the V3 evaluation. This is a development protocol, not a claim that the old recordings are new blind tests. Changes after results must be described in the implementation log and evaluated as a new development round.

## Correctness amendment before the final development round

The initial implementation run was intentionally stopped after 56 of 68 planned trials when independent regression tests demonstrated unsafe alias promotion and a coordinate-median effect bug. Completed rows, the initial protocol and hash-verified source archive remain in `research_artifacts/v3_matched_development_20261106/`, explicitly marked `interrupted_for_correctness_review`. Those preliminary outcomes are not the final V3 evaluation.

The second round repeats the same four recordings, conditions, seeds, fitting budgets and declared numerical tolerances after the correctness fixes. No threshold is chosen to improve the preliminary results. Its output directory and frozen source/configuration distinguish it from the defective first round. A separate frozen-maintenance-optimizer comparison uses the same recorded-data machinery at the common fitting budget, with two recordings, nominal and all seven drift conditions, one replicate. This is an optimizer comparator, not a claim to have rerun the entire strict legacy maintenance application under identical hypotheses.

An explicitly outcome-informed development revision restores decoy correction in the default V3 edge policy after the raw-edge first round produced a nuisance alarm. The raw-edge version remains a declared `v3_raw_edges` ablation. This is a model-component revision informed by development outcomes, not an untouched-test claim or a numerical threshold change. Final comparisons include V2 without intensity so removing its harmful agreement gate cannot be mistaken for a new geometric contribution.

The matched diagnostic evaluation does not execute V3's final candidate refit/outer-acceptance pathway. Its zero V3 update count therefore does not establish accepted-update accuracy or safety. Separate numerical decision-contract and full API tests verify software gates only; independent physical update accuracy remains unavailable.

## Data roles and truth

Every recording in the V2 manifest, including `enclosure_on_twelve` and `october_device_four`, is **V3 development data**. The V2 labels `held_out_v2` describe historical V2 status only. Cached V2 summaries may be reproduced without changing their original verdicts. The 104-row V2 evaluation contains 102 scored perturbation trials and two unlabelled board-reference runs; report these denominators separately.

Recorded perturbations are known changes to the supplied calibration relative to an estimated anchor. They are not physical sensor motion, independently correct extrinsics, or ground-truth image correspondences. Pixel displacement from the anchor is a perturbation-recovery proxy. Nearest-edge distance is an alignment proxy. Neither is ground-truth physical calibration error.

Synthetic numerical fixtures may use exact poses, intrinsics, correspondences and faults. Their results establish numerical/model correctness under stated assumptions. They cannot establish real-sensor diagnosis accuracy. Newly supplied simulation and physical datasets must have recording-level development, calibration and untouched test IDs and hashes declared before their labels or outcomes are inspected. No suitable independent test dataset is currently declared.

## Matched recorded-data experiment

Use the same V2 anchor construction, perturbation directions, retained capture IDs, seed, hypotheses, association variants, fitting iterations and optimizer budget for V2 and V3. Evaluate nominal, R, T, principal-point, focal-length, joint RT, and V2 nuisance conditions. Never drop failed trials silently. Report full failures and attempted/scored denominators.

Run the production backend once per trial and share its read-only fold records between production, V2 and V3 diagnostic policies. Any additional V3 geometric computation, fitting or validation is timed and counted. Where a comparator requires different optimization, report it as a separately timed fit with the same declared fitting budget. A cached-policy rescore is not a fresh end-to-end run.

Freeze numerical configuration and ablation definitions in the output `protocol.json` before the first trial. Save the Git HEAD, working-tree diff/hash or dirty status, software versions, input manifest hashes and protocol hash. A local uncommitted protocol establishes execution order only; it is not an independently timestamped preregistration.

Required comparisons are production, unchanged V2, V3, V3 without geometric signatures and V3 without quality evidence. Additional original optimizer, active-selection and temporal comparisons must be reported as missing if not executed, rather than inferred from unit tests. Reusing V2 without intensity is an established ablation, not evidence for a new geometric contribution.

## Fault attribution and abstention

An alarm is `DRIFT_SUPPORTED`, `DRIFT_AMBIGUOUS` or `UPDATE_CANDIDATE_VALIDATED`. Exact attribution requires a unique supported hypothesis whose group set equals the injected fault set. A unique wrong set is a wrong attribution. Ambiguity coverage means the ambiguity set contains a hypothesis with exactly the true group set; a generic joint superset does not count as exact coverage. Also report the ambiguity-set size to prevent trivial all-hypothesis coverage being presented as success.

Report detection/miss rates, no-change false alarms, exact attribution by fault type, incorrect attribution, ambiguity, truth inclusion conditional on ambiguity, selective attribution accuracy and unique-attribution coverage. Report update candidates and false updates separately. Diagnosis never authorizes a hardware write. Unavailable independent accuracy metrics remain null with reasons.

No expected positive accuracy or superiority threshold is assumed. The geometric contribution is supported only if matched results improve reliable exact attribution or informative ambiguity over its ablation without raising incorrect attribution, or if controlled fixtures demonstrate a capability V2 lacks while real-data limitations remain explicit. Negative and mixed outcomes are retained.

## Observation-selection and temporal experiments

Selection sees only the training pool and training-derived surviving hypotheses. Compare at equal capture budgets against seeded random, feature count, D proxy, E proxy, V2 contrast and all captures. Reserve validation captures before selection. Score hypothesis separation, decision quality, capture count and complete computation time. An analytical utility demonstration alone does not establish better capture efficiency in recorded data.

Reuse the V2 sequential monitor. If V3 produces a new signal, declare its normalization, historical reference assumptions and nuisance handling before evaluation. Separate nominal, persistent, gradual and transient streams. Report delay only for detected changes, with undetected changes counted separately. Captures within one static scene and repeated perturbations of that scene are dependent; do not claim independent binomial confidence, calibrated false-alarm probability or operating average run length.

## Independent validation gate

Physical validation remains incomplete until independently measured mount rotations, translations and intrinsic changes plus nuisance-only sessions are available. Prioritize depth-rich/wide-angle and depth-poor/narrow-angle scenes, changed viewpoints, low light, timing offsets, window reflections and dropout. Ground-truth simulator data must include projection family, distortion, units, pose convention, timestamps, visibility and provenance. Any unsupported dataset or projection must fail explicitly.
