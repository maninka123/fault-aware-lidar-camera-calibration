# Verification and recorded-data results

Executed **5 November 2026** in the isolated research checkout. **37 research tests and 28 cloned baseline tests pass.** The backend, five-method recorded comparisons, extra ablations, original maintenance path, full inherited initializer and desktop-to-CLI bridge have run. No simulator, known-fault benchmark, hardware write or publication was performed.

The result is a working offline research prototype. These tests do not establish fault-classification accuracy, calibrated uncertainty, superiority or a publishable novel contribution. Initializer execution establishes feasibility; it does not supply independent calibration truth.

## Reproduction

From `Fault-aware calibration/repository`:

```powershell
python -B verify_research.py --recorded enclosure_off_ten --output research_artifacts/reproduce
python -B -m research_calibration benchmark --dataset creep_three --output research_artifacts/reproduce_small
python -B run_recorded_ablations.py --output research_artifacts/reproduce_ablations
python -B verify_desktop_bridge.py
python -B verify_initialization.py --output research_artifacts/reproduce_initial --timeout 600
python -B -m research_calibration assess --dataset creep_three --strategy legacy --output research_artifacts/reproduce_legacy
```

Each run needs a new output folder. The manifest hashes are checked before recorded evaluation. Inputs remain in their existing workspace folders; no recording is redistributed. Public-checkout users must supply their own paths or compatible recordings. Source hashes, exact configuration, package versions and individual folds are saved with each benchmark.

Local executed evidence:

- `research_artifacts/verified_37/`: final 28 + 37 test logs and commands.
- `research_artifacts/final_verification/recorded/`: primary five-method ten-capture benchmark and per-method JSON/Markdown reports. This preceding run had 32 research tests. Later additions cover output protection, Windows paths and initial-report scoping, without changing maintenance optimization/evaluation equations. Each benchmark retains its execution-time source hashes.
- `research_artifacts/creep_three_final/`: five-method small-data run.
- `research_artifacts/additional_ablations/`: single-variant and four capture-selection baselines.
- `research_artifacts/desktop_bridge.json`: successful real-recording child-process bridge, exit code 0, `INSUFFICIENT_EVIDENCE`.
- `research_artifacts/legacy_original_smoke/`: successful strict original workflow dispatch and retained reference.
- `research_artifacts/guarded_initialization_v2/`: full inherited coarse search, refinement, outputs and watchdog samples; exit code 0.
- `research_artifacts/initialization_scope_verified/`: final report scoping and conditional assessment replayed from that saved initial calibration, without repeating the coarse search.

Local artifacts are ignored by Git because they contain machine paths. A durable computed summary is [evaluation/results_summary.json](evaluation/results_summary.json). It includes versions, source hashes, configurations, folds/outer outcomes and all aggregate comparisons. [build_research_summary.py](../../build_research_summary.py) rebuilds it and the figure from actual run JSON.

## Numerical and integration checks

| Verified behavior | Evidence |
|---|---|
| Rotation composition, metres, LiDAR-to-camera convention | Independent SO(3) matrix product and transformed-point fixtures |
| Jacobians | Nonlinear analytic derivative and left-rotation point derivative compared with central differences |
| Camera projection and fixed terms | OpenCV projectPoints agreement; supplied k3/k4 preserved; unchanged parameter groups retained |
| Conditional information | Thin nuisance projection equals generalized Schur complement with duplicate/zero nuisance columns |
| Aliasing and rank | Identical rival groups have zero unique support; estimability alone cannot prove attribution |
| Association stability | A direction absent from any variant is excluded even if its mean projector score is high |
| Units | Consistent physical-coordinate rescaling preserves conditional information |
| Constraints and failures | Forbidden/null directions frozen; invalid focal/geometry/numeric inputs rejected; lost projections penalized |
| Selection | Shared nuisance profiled after stacking; outer IDs excluded; random/D/E/feature baselines deterministic |
| Conservative comparison | No failed-fold dropping; non-nested ambiguity and small samples abstain; nested ties prefer simpler models |
| Final validation | A CV winner can be rejected by outer loss or final support; rejected outputs exactly preserve reference and zero accepted deltas |
| Uncertainty | Insufficient clusters/rank reported; unsupported scalar directions get unknown uncertainty |
| Export semantics | Old reference quality/uncertainty separated from candidate evidence; frozen groups preserved |
| Windows resource response | Mocked low-memory/excess-process conditions stop work explicitly |
| Windows local paths | Writes/reads a greater-than-260-character path through the local adapter, without changing OS policy |
| Scratch adapter | Calls inherited initializer with automatic mounting; separates initialization evidence from later maintenance support; refuses output reuse |

These are deterministic algebra, geometry and control-flow fixtures, not a sensor simulator or synthetic drift benchmark.

## Three recorded captures

Dataset `creep_three`: three 484×366 stacked captures, approximately 2.9 million raw points in total. Each method used the same extracted evaluation features, seed and folds. Default maximum features were 1,200 per capture; default training association budget was 1,800 rows across selected captures.

All five methods returned `INSUFFICIENT_EVIDENCE`, retained the reference and emitted valid reports. Three capture blocks are below the declared four-block comparison threshold; there was no independent outer test. The fault-aware KEEP proxy had pooled capped edge RMSE **10.8374 px**. This is a feature-subset nearest-edge proxy, not a true calibration error.

Separately, the **strict original workflow** ran with its own original extraction, search and validation settings: **BORDERLINE**, **1.4085 px movement**, **0.1856 px sensitivity spread**, **4/7 image regions improved**, **3/3 held-out captures improved**. It completed in approximately 17 seconds. This reproduces the historical workflow behavior; its different support/metrics must not be compared directly with the research RMSE.

### Full calibration from scratch

The inherited initializer completed on the same three captures in **188.75 s**, including the subsequent conditional backend check. It searched four 90° mounting rolls around a camera looking along LiDAR +x, generated 108 coarse hypotheses per mounting, refined them, compared k1 and k1/k2, and wrote JSON/TXT and images. It selected k1 with approximately fx=229.6 px, fy=227.2 px, cx=259.6 px and cy=177.6 px. These are estimates, not ground truth.

The inherited heuristic label was `RELIABLE`. The research output remains **INITIAL_CALIBRATION_CANDIDATE**, with **UNVALIDATED_INITIALIZATION** uncertainty and no historical fault attribution. All captures entered initialization, so later holdouts cannot independently validate it. Scalar support/nullspace from a later KEEP candidate are not presented as properties of the initializer; conditional assessment is saved separately.

An initial attempt stopped before numerical search because an image output path was exactly 260 characters. The adapter now uses extended Windows paths for local writes; no Windows setting changed. After the full retry completed, final report scoping was replayed on the saved calibration rather than repeating the unchanged search.

## Ten recorded captures: primary comparison

Dataset `enclosure_off_ten`: ten stacked captures, approximately 11.29 million raw points. Seed 7 reserved captures `164327_828105`, `164819_212871` and `164921_130392`; seven other captures supplied leave-one-capture-out comparison. Selection and fitting never accessed the three reserved captures. Defaults were two reassociation iterations, gates 6/9/12 px, four selected fitting captures and a 30 px evaluation cap.

The reference was obtained under an enclosure configuration that differs from the recordings' names. Neither filenames nor historical calibration verdicts establish the true physical cause of any discrepancy.

| Method | KEEP pooled capped RMSE (px) | Best comparison model | Best CV squared-loss reduction | Result |
|---|---:|---|---:|---|
| Legacy refine under common protocol | 15.48597 | unavailable for full suite | unavailable | Insufficient evidence: one invalid RTI fold |
| Unconditional joint candidate | 15.49042 | KEEP | 0% | Keep current |
| Fault-aware | 15.49004 | R, 15.44161 px | 0.6243% | Keep current |
| Without observability/attribution constraints | 15.49004 | R, 15.44161 px | 0.6243% | Keep current |
| Without selection: all training captures | 15.49042 | R, 15.44169 px | 0.6281% | Keep current |

Here R means a rotation-only allowed-change model, not a verified rotation fault. The declared 1% threshold applies to **capture-mean normalized squared loss**, not to percentage RMSE reduction. The fault-aware proxy's RMSE reduction is only about 0.31%. Its outer squared-loss reduction was **0.5871%**, also below the declared threshold.

The legacy comparator's full-model fold leaving out `164652_717058` produced a candidate outside the declared research camera/domain bounds. That fold remains failed; the RTI aggregate is unavailable. Completed legacy KEEP/I/RT folds remain inspectable. This does not imply that all legacy calibration fails, as demonstrated by the separately completed strict workflow.

The five-method benchmark took **27.15 s**, including shared extraction. Individual method times were 4.34, 1.61, 5.04, 5.22 and 5.41 seconds respectively; these are this machine's measurements, not general speed claims. Methods have different candidate counts, selection costs and solver schedules, so this is not a matched-runtime accuracy benchmark.

![Recorded model comparison and loss-gain threshold](evaluation/recorded_comparison.png)

## Additional one-factor ablations

All used the same ten-capture test partitions and unchanged default thresholds. All returned **KEEP_CURRENT**.

| Variation | Best CV squared-loss reduction | Outer squared-loss reduction |
|---|---:|---:|
| Single association gate, conditional-only support | 0.6243% | 0.5871% |
| Seeded random selection | 0.7703% | 1.0009% |
| Feature-count selection | 0.7790% | 1.0009% |
| Regularized D-proxy selection | 0.6439% | 0.8081% |
| E-proxy selection | 0.6211% | 0.5347% |

The single-gate result is essentially identical to the full association ensemble on this dataset. Random/feature selection has a slightly better observed proxy gain than contrast selection. Neither result supports superiority of the proposed additions. Although two outer gains slightly exceed 1%, their CV decision already rejected an update; selecting them afterward based on outer performance would contaminate the test. No threshold/configuration was changed to force acceptance.

The final fault-aware rotation candidate has four reduced directions but only four selected capture clusters; its sandwich covariance rank is three. It correctly reports `INSUFFICIENT_CLUSTER_RANK`, rather than a falsely precise interval. The conservative four-capture default can prevent acceptance of high-dimensional updates. Additional diverse, independently measured sessions are needed to evaluate that tradeoff.

## Windows and environment

All executed numerical runs were sequential CPU work with OMP/MKL/OpenBLAS/OpenCV thread counts limited to one. No GPU job, driver update, service change, OS-setting change or live device operation was performed. Memory was checked at extraction/fold/optimization boundaries. After-method Python memory samples in the primary benchmark were about **148–153 MiB**, with **over 20 GiB** physical memory available at those samples. These are sampled readings, not a measured peak or a crash-prevention guarantee.

Imported versions were Python 3.10.14, NumPy 1.26.4, SciPy 1.10.1 and OpenCV **4.8.1**. Existing distribution metadata also lists opencv-python 4.7.0.72, opencv-contrib-python 4.8.1.78 and opencv-python-headless 4.10.0. The imported binary version is recorded separately because these distributions share the cv2 namespace. They were not changed during this continuation; the cause of the previously reported Windows blue screen was not diagnosed by these calibration tests.

The initializer also ran at below-normal priority under a separate watchdog, with a 600 s deadline and 1.5 GiB child-process threshold. Its largest sampled process reading was **285.72 MiB**; the lowest sampled available physical memory was **25,929.54 MiB**. Neither limit triggered. The supervisor controls only its own child process.

## Claims still unsupported

- No independently verified intrinsic/extrinsic fault labels, true point correspondences or nominal false-alarm calibration.
- No guarantee that repeated static captures are independent, even with capture-block aggregation.
- No validation for other projection families, LiDAR beam models, dynamic timing errors or large initialization errors.
- No independently measured initialization accuracy; successful execution is feasibility evidence only.
- No calibrated fault probability, conformal interval, guaranteed coverage, nonlinear identifiability theorem or acceptance-risk bound.
- No demonstrated advantage from ensemble support or contrast selection in these recordings.
- Full text for A4 and complete B1 journal equations remain unavailable in the review.

See [NOVELTY_ASSESSMENT.md](NOVELTY_ASSESSMENT.md) for the resulting negative/provisional publication assessment and the experiments needed next.
