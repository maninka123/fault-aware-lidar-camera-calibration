# V3 experimental results

Collected 6 November 2026 from the executed experiments and saved result files listed in [results/README.md](results/README.md). Nothing here is a fresh blind test. Every recording is **V3 development data** (see [PREREGISTRATION_V3.md](PREREGISTRATION_V3.md)), and all perturbations are known changes relative to an estimated anchor calibration, not physical sensor motion. Counts come from dependent trials on a few static scenes. They carry no calibrated confidence, false-alarm probability or acceptance-risk guarantee.

## 1. Software verification

`python -B tools/verify_research.py` on the final working tree: **250 research tests and 56 maintenance tests pass, 0 failures**.

The baseline run before any V3 change had one failure: a layout test that assumed 1100 px was wide enough for the matrix view under this machine's font and DPI. The test now sizes the wide case from the widget's measured minimum width. No production widget code changed. The failure and its cause are kept in [BASELINE_AUDIT.md](BASELINE_AUDIT.md).

The V3 tests cover:

- finite-difference checks of all 13 parameter derivatives;
- rotation conventions;
- inverse-range translation sensitivity;
- exact aliases;
- rank loss;
- correlated covariance;
- shared nuisance;
- conservative abstention;
- training-only selection;
- the update contract;
- the simulator adapter.

These tests show that the numerical code is correct. They are not evidence about real sensors.

## 2. V2 baseline reproduction

The cached V2 results reproduce exactly (no policy recomputation): production 12/54 no-change alarms, 16/48 detections and 4/48 exact attributions. V2 has 0/54 alarms, 29/48 detections, 1/48 exact attributions and 3/102 wrong attributions. These are 102 scored trials plus two unlabelled board-reference runs. V2's sequential monitor: 17/24 persistent alarms, 0/18 temporary-corruption alarms, 0/6 nominal alarms.

## 3. Geometry with exact correspondences (mathematical verification)

Tool: `tools/evaluate_signature_geometry_v3.py`. The experiment uses 200 generated cases, 160 drift and 40 nominal or beam-nuisance, with 0.15 px Gaussian noise. Observations are generated through the nonlinear projection model, not by multiplying the tested Jacobian. The camera is equidistant with focal length 240 px.

| View geometry | Drift detected | Exact attribution | Ambiguity contains truth | Wrong | No-change false alarms |
|---|---:|---:|---:|---:|---:|
| Horizontal great circle | 40/40 | 10/40 | 20/40 | 0 | 0/10 |
| Narrow angular, depth-rich | 40/40 | 10/40 | 20/40 | 0 | 0/10 |
| Wide angular, depth-poor | 40/40 | 40/40 | 0/40 | 0 | 0/10 |
| Wide angular, depth-rich | 40/40 | 40/40 | 0/40 | 0 | 0/10 |

**Result.** On a horizontal great circle, a yaw change and a horizontal principal-point change produce the same image displacement, whatever the depth variation. The method reports them as one ambiguity class instead of guessing. Views spread over two image dimensions resolve them.

**Limit.** This holds under correct correspondences and the equidistant model. It does not show that the recorded edge-matching front end behaves the same way.

## 4. Recorded data: matched V2/V3 comparison

Four recordings, one replicate, 68 scored trials (36 no-change, 32 changed). V2 and V3 ablations all score the same production fits and partitions.

| Method | No-change alarms | Detections | Exact attribution | Wrong attribution | Ambiguous (truth included) |
|---|---:|---:|---:|---:|---:|
| Production | 4/36 | 9/32 | 1/32 | 12/68 | – |
| V2 | 0/36 | 22/32 | 0/32 | 4/68 | 18 (12) |
| V2 without intensity / V3 without geometry | 0/36 | 27/32 | 1/32 | 3/68 | 23 (16) |
| V3 finite-effect proposal | 0/36 | 27/32 | 0/32 | 2/68 | 25 (18) |
| **V3 conservative default** (policy replay) | 0/36 | 27/32 | 0/32 | **1/68** | 26 (18) |
| V3 without quality evidence (replay) | 0/36 | 25/32 | 0/32 | 1/68 | 24 (17) |
| V3 raw edges (replay) | 1/36 | 28/32 | 0/32 | 0/68 | 28 (17) |

The conservative default reaches 0/1 exact selective accuracy (1/68 unique coverage). Its remaining unique attribution is wrong.

**Where the gain comes from.** Detection rose from V2's 22/32 to 27/32 because the harmful intensity-agreement rule was removed. The same 27/32 appears without any geometric signature, so the gain is not a geometric contribution.

**What geometry does.** It only vetoes an attribution. It cannot upgrade an ambiguous decision, because the permissive version failed (§6).

**Frozen maintenance optimizer** (separate run: 16 trials, two recordings, nominal plus seven drifts). The maintenance optimizer policy gets 5/14 detections and 5/16 wrong attributions. V2 and V3 both detect 12/14. V3 conservative makes 0/16 wrong attributions by abstaining on every detected drift. It has 0/14 exact attributions.

**Cost.** Shared production plus V2 time is a median of 6.98 s per trial. The finite-effect V3 sidecar adds a mean of 0.019 s per trial (95th percentile 0.073 s). The 26 trials where geometry was evaluated have a median of 0.047 s.

## 5. Observation selection (exact correspondences)

Tool: `tools/evaluate_active_selection_v3.py`; 171 method/budget/condition cases. Full detail is in [ACTIVE_SELECTION_RESULTS.md](ACTIVE_SELECTION_RESULTS.md).

| Method, +1 capture | Exact attribution (6 drift cases) | Median reserve RMSE, px |
|---|---:|---:|
| Finite-effect separation | 6/6 | 0.149 |
| D-optimal / E-optimal / V2 contrast | 6/6 | 0.149 |
| Random | 4/6 | 0.152 |
| Feature count | 0/6 | 0.320 |

**Result.** Geometry matters more than point count: choosing the densest views is worst. The new finite-effect selector **does not beat** D-optimal, E-optimal or the V2 contrast selector. No superiority claim is made for it.

## 6. Failed or withdrawn experiments (kept on purpose)

- **Permissive geometric attribution.** Correct derivatives did not make the diagnosis correct. The proposal assigned a rotation change to TI on `enclosure_off_ten` and a rotation-plus-spurious-lines trial to T. The geometric test separated the fitted wrong field from its rivals while missing the injected cause. It was replaced by the conservative veto-only rule. That replacement was chosen after seeing development outcomes, so it is outcome-informed.
- **First implementation round.** It was stopped after 56 of 68 trials, when regression tests exposed two defects:
  - parsimony could promote an unsupported subset to a unique diagnosis;
  - coordinatewise medians could create an effect vector outside every fold's subspace.

  The defects were fixed in code, with no threshold change. The round's results are excluded.
- **Raw-edge variant.** It removed the last wrong attribution only by abstaining on every detected drift, and it raised a nuisance alarm.
- **Active selection** gave no advantage over D/E/contrast.
- **No new temporal benefit.** The V2 sequential monitor is reused unchanged.

## 7. What is not measured

- Physical rotation, translation and intrinsic accuracy, and accepted-update accuracy. No independently measured fault session exists, and nearest-edge loss is not ground truth.
- The update-acceptance path. The matched comparison is diagnosis-only, so its zero V3 updates say nothing about safe, useful acceptance.
- Calibrated false-alarm or acceptance-risk rates.
- Detection delay for any new V3 temporal signal.
- Other rigs, lenses or sensors. The five simulator profiles are not available yet.
- Matched feature and computation budgets for the selection experiments.

## 8. Bottom line of the initial V3 experiments

V3 shows a verified and useful result for the central question. Which faults are distinguishable depends on viewing geometry; a great-circle view cannot separate yaw from principal point, and wide off-plane views can. The V3 code reports this as an explicit ambiguity class and requests better data instead of guessing.

It does **not** show better exact fault attribution on real recordings, an advantage in observation selection, or better persistent-drift detection than V2. Those need independent physical or simulated fault data. See [RESEARCH_READINESS.md](RESEARCH_READINESS.md).


## 9. Root cause of the missing attribution (development recordings)

Full analysis in [ROOT_CAUSE_ANALYSIS.md](ROOT_CAUSE_ANALYSIS.md). Same V3 inference, only the pairing differs; 28 injected-change trials and 12 no-change trials
on `october_device_one` and `enclosure_off_ten`, two replicates.

| Pairing | No-change alarms | Detections | Exact | Wrong unique | Truth in ambiguity |
|---|---:|---:|---:|---:|---:|
| Reference pairs (anchor's own, a control) | 0/4 | 28/28 | 15/28 | 1 | 12 |
| Nearest edge | 8/12 | 26/28 | 4/28 | 15 | 7 |
| Existing oriented nearest edge | 7/12 | 27/28 | 5/28 | 19 | 4 |
| Responsibility + visibility + balance | 0/12 | 20/28 | 0/28 | 4 | 11 |

Pair identity against the reference pairs is 57 to 62 % overall and falls with the size of the error: 100 % at zero error, 72 % (rotation 0.5 degree), 43 % (1 degree),
30 % (principal point 3 px). The production optimizer, told the correct group, still leaves 0.59 to 1.00 degree of a 1 degree rotation and 4.3 to 4.4 cm of a 6 cm
translation; its best fit has a lower nearest-edge loss than the anchor in 10 of 14 conditions. Rotation against principal point has a signature angle of only
1.4 to 1.9 degrees.

## 10. Frozen-protocol evaluation (evaluation recordings)

Protocol: [PROTOCOL_CORRESPONDENCE.md](PROTOCOL_CORRESPONDENCE.md), committed at `e8beb0e` before this run. Recordings: `enclosure_on_twelve`, `october_device_four`
(not used in the design of the pairing methods; examined earlier in V2/V3 for other purposes, so not blind). 28 drift trials, 12 no-change trials (4 nominal, 8
nuisance), 2 replicates. Source: [results/pairing_evaluation_frozen_protocol.md](results/pairing_evaluation_frozen_protocol.md).

| Method | No-change alarms | Detections | Exact | Wrong unique (all 40) | Ambiguous incl. truth | Median error after / before, alarmed drifts (px) | Accepted updates (no-change; drift, median error) | Seconds / trial |
|---|---|---|---|---|---|---|---|---|
| reference_pairs (control) | 1/4 | 28/28 | 17/28 | 0 | 11 | 0.19 / 2.05 | 0/4; 15/28, 0.17 | 0.02 |
| nearest | 8/12 | 28/28 | 3/28 | 3 | 12 | 1.67 / 2.05 | 0/12; 4/28, 1.81 | 0.04 |
| oriented (existing front end) | 6/12 | 28/28 | 6/28 | 9 | 8 | 1.42 / 2.05 | 0/12; 4/28, 1.13 | 0.04 |
| **geometric (responsibility + visibility + balance)** | **0/12** | 28/28 | 1/28 | **0** | 21 | 1.29 / 2.05 | 0/12; 1/28, 1.00 | 0.08 |
| geometric, no visibility | 0/12 | 28/28 | 2/28 | 0 | 20 | 1.30 / 2.05 | 0/12; 2/28, 0.91 | 0.04 |
| geometric, no confidence | 5/12 | 26/28 | 3/28 | 1 | 14 | 1.49 / 2.05 | 0/12; 1/28, 0.95 | 0.08 |
| geometric, no balancing | 0/12 | 28/28 | 2/28 | 0 | 19 | 1.29 / 2.05 | 0/12; 2/28, 0.98 | 0.08 |

Selective accuracy among unique labels: oriented 6 correct of 15, nearest 3 of 6, geometric 1 of 1 (coverage 1/28), reference pairs 17 of 17. Mean minimal ambiguity
set: geometric 2.81 of 7 hypotheses, oriented 2.47, reference pairs 2.09, so "truth in the set" for the geometric front end is a weaker statement than for the control.
When an alarm was raised on a **no-change** trial, applying its correction introduced a median error of 0.48 px (nearest, 8 trials) and 0.52 px (oriented, 6 trials); the geometric
front end raised none. The control itself raised 1 of 4 nominal alarms here, so it is not noise-free.

**Predeclared expectations.**

| Expectation | Outcome |
|---|---|
| 1. geometric has fewer no-change alarms than oriented and nearest | **Met**: 0/12 against 6/12 and 8/12 |
| 2. geometric has fewer wrong unique attributions than oriented | **Met**: 0 against 9 |
| 3. geometric does not reach the control's exact attribution | **Met** (1/28 against 17/28): the correspondence problem is not solved |
| 4. every ablation is no better than the full method on alarms and wrong labels | **Partly**: confidence weighting is necessary (no-confidence: 5/12 alarms, 1 wrong). Removing visibility or balancing changes neither alarms nor wrong labels, so those two mechanisms' claimed benefit is **withdrawn** |
| 5. no accepted update on a no-change trial | **Met** for every method (0/12) |
| 6. abstention is not identification | Applies: the safety gain is bought with abstention (1 unique label in 40 trials) |

## 11. Matched comparison with the original recorded V3 pipeline

Same recordings, replicates, seeds, perturbations and conditions (nominal + seven drifts = 32 trials). The original V3 numbers are from
`tools/evaluate_fault_diagnostics_v3.py` run on these trials ([source](results/original_v3_pipeline_matched_evaluation_recordings.md)). The two paths differ: the original
uses the production engine's fits and V2's held-out edge evidence (about 7 s per trial including shared fits), the new path is a single-shot signed-residual
inference on responsibility-weighted pairs (0.08 s per trial, no optimizer fits).

| | Original V3 | Signed diagnosis, geometric pairing |
|---|---:|---:|
| No-change alarms (nominal) | 0/4 | 0/4 |
| Detections | 26/28 | 28/28 |
| Exact attribution | 0/28 | 1/28 |
| Wrong unique attribution (32) | 2 | 0 |
| Ambiguous decisions / truth in set | 24 / 19 | 27 / 21 |
| Median projection error after correction, alarmed drifts | not measured (diagnosis-only) | 1.29 px (from 2.05) |

The difference is small and rests on 28 dependent trials on two scenes. It is not evidence of better exact attribution; it is evidence of no regression in safety, slightly higher
detection, and far lower compute, with one added capability (a correction whose recovery can be measured).

## 12. Findings that contradict the improvement claim

* Exact attribution on recorded data is still 1/28 (3.6 %), against 17/28 when correct pairs are available. The gain over the existing front end is safety, not identification.
* The geometric method's recovered projection error (1.29 px from 2.05 px, a 37 % reduction on alarmed drift trials) is far from the control's 0.19 px, and only 1 of 28 updates passed the
  acceptance rule (median error 1.00 px).
* Visibility testing and balancing, designed to help, do not measurably help here. Only the responsibility weighting does.
* The alternating estimator and the unique-pair rule, both principled responses to the pairing problem, failed on the development recordings.
* The control pairs are a proxy built from the anchor itself; they are not verified correspondences.

## 13. Final status of the experiments

The improved V3 establishes **why** recorded attribution failed (pairing identity, with numbers) and a **safer** pairing front end. It does not establish accurate recorded-sensor fault attribution.


## 14. Software verification, CI and desktop protection (improved V3)

* **Tests.** Final working tree: 264 research tests (19 modules, run one process per module with `tools/run_research_tests.py`, 0 failures) and 56 maintenance tests, 0 failures. The new
  `test_correspondence_v3` has 14 tests (responsibility and ambiguity, visibility, balancing, identity accuracy, finite-difference check of the signed Jacobian, translation attribution with
  correct pairs, abstention with too few rows, estimator stability).
* **Clean checkout (what CI sees: no saved checks, no recordings).** The isolated runner passes 264 tests with 51 skipped (they need local saved checks). A single-process
  `unittest discover` run of the same suite **crashed natively** (Windows heap corruption 0xc0000374) while constructing the desktop window in a later test. The earlier V3 commits did not;
  the cause is unresolved (IMPLEMENTATION_LOG.md item 17). CI therefore gates on the isolated runner and keeps the single-process run as an informational, non-gating step.
* **GitHub Actions.** The workflow now runs the maintenance and research suites on Windows and a Linux job. It has **not been executed on GitHub from this session**; the same commands were run locally
  in a clean checkout. The Linux job is marked non-gating until observed green.
* **Desktop and workflow protection.** `Calibration maintenance/`, `Targetless calibration/` and all application launch scripts are unchanged relative to the original application branch; the only
  application file changed is `gui/result_visuals.py` (overlay alignment banner). Changes to existing engine modules are 45 inserted and 5 deleted lines: an optional read-only fold observer, an optional
  reflectivity-sample argument (both default off), an empty-basis LAPACK fix and CLI commands. Smoke runs, all exit code 0: `tools/verify_desktop_bridge.py` (offscreen desktop-to-child-process run),
  `python -m research_calibration diagnose-v3 --dataset october_device_one` (output `DRIFT_AMBIGUOUS`; the V3 entry point works), and `tools/verify_initialization.py` on `creep_three` (targetless
  initialization, 209 s). The maintenance tests pass.
* **Not tested:** any physical device (reading a calibration over SSH, capture, writing and restoring it), because no hardware is connected; the Linux job on a real runner; and the application on a
  display (all desktop tests are offscreen).
