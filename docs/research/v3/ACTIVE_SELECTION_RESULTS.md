# Active selection: frozen numerical comparison

Executed **6 November 2026**. The finite-effect selector resolves a deliberately constructed geometry ambiguity with one added observation, but **does not outperform D-optimal, E-optimal or the existing V2 contrast selector in this experiment**. Retain it as an experimental alternative, not an established performance contribution.

## Protocol and provenance

Tool: `tools/evaluate_active_selection_v3.py`. Reproduce into a **new** directory:

```powershell
python -B tools/evaluate_active_selection_v3.py --output research_artifacts/v3_active_selection_replication
```

Final-source artifacts: `research_artifacts/v3_active_selection_final_20261106/protocol.json` and `results.json`. The tool wrote its protocol, fixed seeds/budgets/geometry/threshold choices and source hashes **before** executing trials; it refuses to overwrite a nonempty output directory. The end-of-run source check was `true`.

Protocol SHA-256: `35c40ac1268379113f78804cd65ac87f410b9198a9e2c5ad43a739fcff8bfd71`.

**Correctness rerun:** round 1 is preserved in `v3_active_selection_round1_20261106`. Subsequently, the core API began enforcing its declared minimum capture count and corrected the active selector's nuisance-profiled information tiebreak. Round 2 freezes those final source hashes and explicitly sets `SignatureConfig(min_captures=2)` for this numerical two-capture leave-one-out exercise. The production/default research minimum remains four captures. Detection/separation tolerances, seeds, conditions, budgets and candidate geometry were not changed, and all classification counts remained identical. This is a documented software-correctness rerun, not a fresh blind test or result-dependent threshold optimization.

The final-source rerun additionally captures the subsequent covariance-unit/candidate-policy corrections. All nontiming summary values match round 2 exactly (`source_unchanged=true`). These numerical inputs retain `pixel_sigma=1`; no experiment configuration, conditions or thresholds were changed. Its protocol/source hashes and timings below supersede round 2 for reproducibility. The recorded conservative-policy replay is a separate development evaluation and is not exercised by this exact-correspondence inference API.

This is a **numerical nonlinear-projection experiment with exact correspondences**, not a sensor simulator, recorded-data validation or physical-fault experiment. Independent Gaussian pixel noise has standard deviation 0.15 px. Derivatives and inference use the repository's V3 implementation; observations are generated through its nonlinear `ProjectionModel`. The equidistant camera has focal lengths 240 px, principal point (400,400), zero distortion and identity reference extrinsics.

Each of seeds 0, 1 and 2 supplies:

- One initial observation with 120 returns on a horizontal great circle and varied range. A yaw effect and horizontal principal-point displacement are confounded there.
- Six available candidate observations: great-circle 480 and 240 returns; narrow angular/depth-rich 240; wide angular/depth-poor 120; wide angular/depth-rich 120 and 240.
- One **reserved** wide angular/depth-rich observation with 240 different returns and an independent noise draw. It is never used for effects, selection or diagnosis.
- Nominal, 1 degree yaw and 4 px horizontal principal-point change conditions. The geometry and noise draw are shared across conditions for paired comparisons; these are dependent development cases.

The R and I candidate effects are fitted separately, with beam nuisance, **only to the initial noisy measurements**. The active selector sees these fitted effects and candidate geometry/Jacobians; it never sees an injected label or candidate residual while choosing captures. It must select even in the nominal condition; the nominal result therefore does not establish useful selection when no fault is present.

All methods receive the same initial observation and then add 1, 2 or 3 candidates. Random uses a frozen per-seed permutation. Feature-count takes the largest counts. D/E/contrast reuse the existing `select_captures` **score calculation** on each initial+chosen+candidate subset with `strategy='all'`, followed by the same greedy ranking/tie rules. This wrapper is needed because the existing public selector does not accept a fixed initial matrix. The matrices are already whitened/scaled, so it receives unit parameter scales. Shared nuisance is profiled after stacking. The all-data reference adds all six captures and is explicitly **outside the matched budgets**.

After selection, each method receives the chosen observations. Diagnosis uses the V3 API/default detection and separation tolerances with supplied variance, capture IDs and the explicitly recorded numerical minimum of two captures. At +1 this means two-capture leave-one-out fitting, which is a controlled numerical check and cannot validate physical replication or independence. The best leave-one-capture-out model is fitted on all available chosen measurements and predicts the reserve observation. Reserve prediction error is an independent **known-correspondence pixel error of that local model**, not nearest-edge loss, physical extrinsic error or a validated update recommendation. No hardware/candidate-file writing occurs.

## Results

Each matched method/budget has **6 drift and 3 nominal cases**. All methods detect 6/6 drifts, produce 0/3 nominal false alarms and make zero wrong unique attributions. Differences below are exact attribution versus honest ambiguity.

| Method | Exact, +1 capture | Exact, +2 captures | Exact, +3 captures | Ambiguous including truth, +1 | Unique coverage, +1 |
|---|---:|---:|---:|---:|---:|
| Finite-effect separation | 6/6 | 6/6 | 6/6 | 0/6 | 100% |
| Random | 4/6 | 6/6 | 6/6 | 2/6 | 67% |
| Feature count | 0/6 | 0/6 | 0/6 | 6/6 | 0% |
| D-optimal | 6/6 | 6/6 | 6/6 | 0/6 | 100% |
| E-optimal | 6/6 | 6/6 | 6/6 | 0/6 | 100% |
| V2 contrast score | 6/6 | 6/6 | 6/6 | 0/6 | 100% |
| All six candidates, unmatched reference | — | — | — | 0/6 | 100% at +6 |

Selective accuracy is 100% among unique drift diagnoses for every method producing one; feature count's selective accuracy is undefined because it abstains on all drift cases. The all-data reference gives 6/6 exact diagnoses. In this finite grid, all six drift cases are exactly attributed by +1 for active/D/E/contrast and by +2 for random. Feature count has not done so by +3. This is a descriptive first tested budget, not a statistically reliable sample-complexity result.

| Method, +1 candidate | Median reserve RMSE over **drift cases**, px | Median selection, ms | Median diagnosis + reserve check, ms |
|---|---:|---:|---:|
| Finite-effect separation | 0.1492 | 2.654 | 3.406 |
| Random | 0.1524 | 0.029 | 2.906 |
| Feature count | 0.3199 | 0.004 | 3.995 |
| D-optimal | 0.1492 | 3.098 | 3.210 |
| E-optimal | 0.1492 | 3.339 | 3.204 |
| V2 contrast score | 0.1492 | 3.162 | 3.254 |

For all six candidates, median diagnosis+reserve time is 13.667 ms. Shared geometry/Jacobian preparation takes median 3.021 ms per seed; initial-effect fitting takes median 0.071 ms per seed/condition. Active uses that effect fit, whereas the geometry-only baselines need not. Selection times are small local timings, without acquisition, extraction or application loading. The complete 171 method/budget/condition cases took 1.654 seconds inside the experiment timer. Source/library loading is outside that timer. Do not generalize these small timing differences to operational speed.

The JSON summary's reserve-RMSE median pools drift and nominal conditions. The table above deliberately reports the six **drift-only** cases; nominal fits otherwise hide the failure of extrapolating a confounded model. Per-case data remain available in `results.json`.

## Interpretation and negative outcomes

For drift cases, finite-effect/D/E/contrast all choose the wide/depth-rich 240-return observation first. They therefore have identical first-budget predictive performance. Random chooses a narrow observation for one seed and remains ambiguous on that seed's two drift cases. Count chooses the dense great-circle observation, which adds repeated ambiguous geometry. Its two next largest candidates still do not resolve the alias at the declared tolerances.

This experiment demonstrates that **geometry can matter more than point count**, and that the active API can use initial-data-derived effects without consulting truth. It does **not** demonstrate added diagnosis value over the existing information selectors. The modest active-versus-random result depends on a deliberately diagnostic candidate pool and only three seeds. No significance test, confidence interval or operational false-alarm guarantee is justified.

Capture budgets are matched, **feature/row counts are not**: at +1, median measurement rows are 720 for active/D/E/contrast, 480 for random and 1200 for count, including initial rows. This intentionally tests whether point-rich confounded geometry can be inferior. It does not establish superiority at matched feature or total computation budgets. All methods use the same fitting code, but larger selections have more rows and cross-validation folds.

Independent reserve observations verify prediction beyond the selected geometry; they are still generated by the same mathematical camera/noise model. They provide no sensor-model, correspondence-front-end, physical accuracy or independent-session generalization evidence. Tests for translation, distortion, joint faults, correlated noise, timing, visibility and other sensors remain outside this small active-design experiment. The broader V3 numerical/recorded evaluations must be read separately.

**Decision:** keep finite-effect selection available for its interpretable effect-conditioned utility, while explicitly withdrawing any present claim that it improves on D/E/V2 contrast. Further evaluation should include unknown correspondences, shared session nuisance, matched feature/compute budgets and independently measured fault sessions before promoting it as a central contribution.
