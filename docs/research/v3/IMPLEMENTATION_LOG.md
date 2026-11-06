# V3 implementation log

Work date: 6 November 2026. This log records development decisions, including negative findings. It is not an independently timestamped preregistration.

1. Read the master research prompt, existing pipeline, geometry, observability, residuals, hypothesis definitions, selection, optimizer, decision, uncertainty and complete V2 package; reviewed V2 mathematical/results/prior-art documents. GitHub branch discovery and fetch confirmed V2 tip `51e1c50dcb0008dcfbc8df432ced6ca8584cc6af`. Created local `research/fault-diagnostics-v3`; no assistant commit, push or merge. Preserved the existing GUI modification. An external concurrent commit advanced HEAD to `c09361c0e38fb307fc15d15bc3fd12e07b8c7a07` and incorporated that GUI work. Protocols record actual source hashes.

2. Reproduced cached V2 outcomes exactly and ran baseline verification before V3 algorithm changes: 56 maintenance passes, 213/214 research passes, one pre-existing responsive matrix-layout assertion. All baseline algorithm tests passed. [Baseline audit](BASELINE_AUDIT.md) gives the exception and denominator reconciliation. Saved [V3 protocol](PREREGISTRATION_V3.md) before V3 execution. Every old recording is V3 development data.

3. Reviewed full accessible primary papers and reference implementations, recovering the previously unavailable OCaMo author manuscript. Established that conditional information, nuisance projection, principal angles, matched-subspace tests and T-optimal model discrimination are prior art. Rejected broad novelty claims. See [literature](LITERATURE_REVIEW.md), [research gaps](RESEARCH_GAPS.md) and [novelty comparison](NOVELTY_COMPARISON.md).

4. Added an experimental package beside V2, reusing its calibration loader, projection conventions, physical scales, nuisance projection, oriented associations, hypothesis groups, selective optimizer and sequential monitor. Analytic derivatives cover all 13 existing parameters, including beam nuisance and fixed higher-order fisheye terms. Independent finite-difference tests passed at nonzero rotations, nonzero translation, beam offsets, optical axis and wide angles with different intrinsics.

5. Derived and verified a specific ambiguity: undistorted equidistant projection on a horizontal great circle makes yaw and horizontal principal point exactly aliased, even at broad horizontal angles and varied depth. Two-dimensional off-plane bearings can separate them. Inverse-range translation sensitivity holds at fixed camera bearing; a nonzero mounting offset requires the correct rotation convention. These are mathematical/model results, not physical sensor fault validation or a novelty theorem.

6. Implemented known-correspondence signed-signal inference separately from recorded matching. It supports declared diagonal/full positive-definite covariance, consistent whitening, shared nuisance elimination, rival refitting, minimal explanations and explicit ambiguity. A full covariance is partitioned before CV whitening. Covariance/sampling assumptions remain descriptive. No calibrated probability, risk bound or guarantee is produced.

7. Initial recorded development combined raw oriented share, existing quality gating, no mandatory intensity gain, and an actual-effect geometric alias check. The first source-frozen round is preserved under `research_artifacts/v3_matched_development_20261106`; it was stopped for correctness review and must not be presented as a final full-protocol run. Independent review plus deterministic failing regressions exposed two implementation defects: parsimony could promote an unsupported subset alias to a unique diagnosis, and coordinatewise medians could invent a vector outside every fold's fitted subspace. These findings justified a code correction rather than threshold tuning.

8. The same initial development also exposed a raw-share nuisance alarm. The final development round must compare the already available decoy-referenced/no-intensity evidence with its raw-share ablation, so removing the harmful intensity requirement is not confused with a geometric contribution. This is an explicitly outcome-informed development revision, not a fresh blind test. Detection and separation tolerances stay unchanged.

9. Implemented and ran frozen oracle-correspondence geometry and active-selection experiments. The initial geometry experiment contains 200 cases: 160 drift and 40 nominal/beam-nuisance cases. Wide two-dimensional views permit accurate identification in this camera/noise fixture, while narrow/great-circle views retain ambiguity. Results are mathematical verification under correct correspondences. The selector experiment contains 171 method/budget cases; its finite-effect utility did not outperform D/E/V2 contrast. The selector remains experimental, with no claimed default superiority. [Selection results](ACTIVE_SELECTION_RESULTS.md) state capture/feature budget limits.

10. Added a hash-checked, role-checked exact-correspondence simulator adapter and documented the paired image/PCD end-to-end interface. No simulator, renderer, new sensor model or hardware access is added. Independent simulated/physical fault validation is still missing.

Final corrections, verification counts and measured comparisons are recorded in [experimental results](EXPERIMENTAL_RESULTS.md), [V2/V3 comparison](V2_V3_COMPARISON.md) and [readiness assessment](RESEARCH_READINESS.md). Negative outcomes are retained; code volume and oracle accuracy do not establish a stronger real-sensor calibration method.


## Improved V3 (correspondence study), 6 November 2026

11. **Audit.** Pulled `research/fault-diagnostics-v3` at `edb1727`: V3 package, tests, tools and documents all present but the experimental-results document referenced by the README was missing and nothing was
    committed on the branch beyond the overlay fix. Verified 250 research and 56 maintenance tests, then wrote that document from the saved artifacts and committed the V3 work.
12. **Root-cause experiments** (`tools/analyze_attribution_root_cause_v3.py`, development recordings only). Isolated the pairing front end by feeding the unchanged V3 inference with (a) the anchor's own pairs as a control and (b) each
    front end's pairs. Result: 15/28 exact with control pairs against 4 to 5/28 with 15 to 19 wrong labels for nearest and oriented pairing. Pair identity measured (57 to 62 %, falling with the diagnosed error), optimizer recovery
    measured (it does not recover the truth even for the right group; its best fit beats the anchor in 10/14), signature angles measured. See [ROOT_CAUSE_ANALYSIS.md](ROOT_CAUSE_ANALYSIS.md).
13. **`correspondence.py`**: mixture responsibility over distinct edge lines, z-buffer visibility, cell/range balancing, optional unique-within-radius rule, identity accuracy and signed rows. Deterministic tests exposed two defects in the
    first version (edge samples competing for responsibility; points of the chosen edge counted as rivals). Both were fixed before any final number was recorded; the numbers from the defective version were discarded.
14. **`joint_estimation.py`**: annealed alternating pairing/calibration estimation with a truncated-SVD identifiable-direction step. A ridge step diverged on a correct calibration (1.2 degrees, 5.5 cm, 5.6 px); the truncated step is stable
    (0.33 degree, 7.2 cm, 1.0 px) but pairs chosen at the estimate are circular and caused false alarms. Negative result, kept with its stability test.
15. **Radius sweep and ablations** on the development pair chose nothing: the unique-pair rule did not help; the default pairing is the responsibility + visibility + balancing configuration with the constants declared in
    `CorrespondenceConfig`, chosen before any evaluation recording was run. Design constants were not tuned on the evaluation recordings.
16. **Frozen protocol** ([PROTOCOL_CORRESPONDENCE.md](PROTOCOL_CORRESPONDENCE.md)) committed at `e8beb0e` with manifest roles (`pairing_role`), then the evaluation was run once; the original recorded V3 pipeline was run on the same trials.
    Outcome and the predeclared expectations are in EXPERIMENTAL_RESULTS.md sections 10 to 12.
17. **CI.** The workflow now runs the research suite on Windows (gating, one process per module) and on Linux (non-gating until observed green); the single-process `unittest discover` is kept as an informational step. In a clean checkout (no saved
    checks) the single-process run crashed natively (Windows heap corruption 0xc0000374) while constructing the desktop window in a later test. Bisect: the earlier commits (214 and 250 tests) pass in clean checkouts, adding the new numerical test
    file triggers it, a control with equally heavy existing tests does not, process-heap validation after every new numerical call is clean, and repeated window creation alone is clean. The cause is **not resolved**; it looks like a latent
    fault in desktop-window test setup/teardown that is exposed by allocation layout. The isolated runner (`tools/run_research_tests.py`) passes all 264 tests in a clean checkout (51 skipped: they need saved local checks). Temporary clean
    worktrees `C:\fa_ci_check`, `C:\fa_ci_a`, `C:\fa_ci_b` were created for this and were not removed (the cleanup command was refused by a safety check); delete them with `git worktree remove --force`.
18. **Not done, and why.** (Part C) physically constrained rival alternatives: no justified bound on a fault exists in the data or the reference calibrations (their standard deviations describe the reference estimate, not drift); the unbounded
    result and its limitation are retained. (Part D) active selection: the earlier benchmark offers one dominant candidate that every information selector picks first, so it cannot separate the finite-effect objective from D/E; no new objective was
    developed, and the established D/E/contrast selectors are the recommended simple choice. No experiment with a pool designed to separate them was run. (Temporal) the V2 monitor is reused unchanged; no new temporal evidence was produced. (Gate 5)
    independent simulated or physical validation: no new data exists.
