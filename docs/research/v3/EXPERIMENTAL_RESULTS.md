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

## 8. Bottom line

V3 shows a verified and useful result for the central question. Which faults are distinguishable depends on viewing geometry; a great-circle view cannot separate yaw from principal point, and wide off-plane views can. The V3 code reports this as an explicit ambiguity class and requests better data instead of guessing.

It does **not** show better exact fault attribution on real recordings, an advantage in observation selection, or better persistent-drift detection than V2. Those need independent physical or simulated fault data. See [RESEARCH_READINESS.md](RESEARCH_READINESS.md).
