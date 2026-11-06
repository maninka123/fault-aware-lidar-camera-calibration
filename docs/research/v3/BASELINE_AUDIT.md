# V2 baseline audit

Executed 6 November 2026 before V3 source changes. GitHub branch discovery and `git fetch origin research/fault-diagnostics-v2` confirmed that the remote V2 tip and local HEAD are both `51e1c50dcb0008dcfbc8df432ced6ca8584cc6af`. The new local branch is `research/fault-diagnostics-v3`. Nothing was pushed or merged. The existing local modification to `gui/result_visuals.py` was preserved.

During the work, HEAD was independently advanced to `c09361c0e38fb307fc15d15bc3fd12e07b8c7a07` (overlay figure changes), and the initial GUI modification became clean. The baseline/evaluation worker did not create that commit or change the GUI. The numerical V2 parent remains `51e1c50`; new evaluation protocols record the actual HEAD and source hashes rather than assuming the working tree stays fixed.

## Reproduction and baseline exception

Command: `python -B tools/verify_research.py --output research_artifacts/v3_baseline_20261106`.

| Suite | Result | Recorded duration |
|---|---|---:|
| Frozen maintenance | 56 tests passed | 1.61 s |
| Research/desktop | 214 tests executed; 213 passed, one failed | 70.27 s |

The one failure is `test_session_and_flow.MatrixViewTests.test_the_pair_shows_k_and_t_side_by_side_and_stacks_when_narrow`: at line 102, layout direction was `TopToBottom` (2), while the test expected `LeftToRight` (0). This was observed before any V3 implementation. The working tree already contains user changes in the GUI module. The failure is recorded rather than concealed, and those changes are not overwritten. This audit does not infer its cause from the assertion alone. All calibration mathematics, optimizer, pipeline, V2 diagnostic and maintenance tests passed. The V2 documentation's 211-test research count differs from the actual 214-test local suite; the actual count is reported here.

The same single GUI test fails in an isolated fresh Python process, so the failure is not merely test-order contamination. Its widget implementation is `gui/matrix_view.py`; no evidence attributes this failure to `result_visuals.py`.

A read-only widget probe identifies the immediate sizing mismatch under this environment: Helvetica 12, 100 DPI, requested width 1100 px, actual minimum-constrained width 1214 px, and the widget's side-by-side threshold 1226 px (group minimum widths 661 and 541 plus 24). The widget therefore follows its intended stacking rule. A portable regression test must request a width above the measured threshold instead of assuming 1100 px is sufficient for every font configuration.

Algorithm development can proceed in an isolated experimental package with this explicit baseline exception. A fully green desktop regression gate remains outstanding until the layout failure is resolved or independently shown to be environmental. Local logs and commands are in the new artifact folder above.

**Subsequent resolution:** a read-only widget probe found that this environment's font/DPI makes the two groups require more than the test's hard-coded 1100 px. The widget correctly stacks below its computed breakpoint. The test now sizes the wide case from both actual `minimumSizeHint()` widths plus margin, and still checks stacking at 300 px. No production widget code changed. The targeted 35-test session/flow suite passes, and the subsequent complete run passed 246 research plus 56 maintenance tests before the final candidate regression was added. Later final verification is reported separately; the original failed baseline result above is preserved.

Command: `python -B tools/summarize_fault_diagnostics.py research_artifacts/fault_diagnostics_v2/held_out/trials.jsonl --title "V2 cached baseline reproduction"`. No policy recomputation was requested. This reproduces saved trial outcomes; it is not a fresh rerun of every fit.

| Recorded V2 comparator | No-change alarms | Drift detections | Exact attribution | Ambiguous including truth | Wrong attribution | No-change updates |
|---|---:|---:|---:|---:|---:|---:|
| Production | 12/54 | 16/48 | 4/48 | unavailable | 24/102 | 0/54 |
| V2 | 0/54 | 29/48 | 1/48 | 18/48 | 3/102 | 0/54 |
| V2 without intensity | 0/54 | 42/48 | 0/48 | 30/48 | 3/102 | 0/54 |
| V2 raw oriented matching | 0/54 | 28/48 | 1/48 | 20/48 | 0/102 | 0/54 |

All values match the documented historical results. The 104 saved rows comprise **102 scored trials plus two unlabelled board-reference assessments**. The 102 denominator for all-trial attribution and 104 total execution count therefore are consistent. There are no saved errors. Cached median production time is 6.9 s and additional diagnostics 1.1 s, with seven extra training-only fits; these historical measurements are not current V3 costs.

The saved sequential summary reports 17/24 persistent alarms, 16/24 persistent labels, median delay two captures among detected changes, 0/18 temporary-corruption alarms and 0/6 nominal alarms. These are dependent semi-synthetic streams, not operating false-alarm guarantees. The V2 sequential implementation will be reused rather than reimplemented.

## Existing responsibilities: reuse instead of duplication

| Module | Existing responsibility | V3 boundary |
|---|---|---|
| `geometry.py` | Equidistant polynomial projection, fixed k3/k4, left SO(3) retraction, camera validity, serialization | Reuse projection/pose conventions; independently verify new analytic Jacobians |
| `residuals.py` | Frozen oriented associations, robust/capture weights, invalid-visibility penalties, ungated held-out nearest-edge proxy | Reuse associations; do not relabel weighting as measured covariance |
| `observability.py` | Finite derivatives, nuisance/rival residualization, conditional information, principal angles, stable support across correspondence variants | These operations are established V2 machinery, not V3 novelty |
| `parameter_hypotheses.py` | KEEP/R/T/I/joint model definitions, physical parameter scales, beam nuisance | Reuse groups and scaling |
| `evidence_selection.py` | Training-only random/count/D/E/contrast selection; stack before profiling shared nuisance | New selection must condition on actual unresolved effects to differ meaningfully |
| `selective_optimizer.py` | Reduced observable-subspace least squares, forbidden-parameter freezing, validity checks | Reuse optimizer; no automatic all-parameter update |
| `uncertainty.py` | Conditional capture-cluster sandwich with rank checks and explicit unsupported directions | Retain limitations; no calibrated probability claim |
| `decision_policy.py` | Paired loss comparison, practical gain, ties/abstention | Preserve unchanged production policy |
| `calibration_pipeline.py` | Outer split, inner folds, selection, hypothesis fits, final observability/uncertainty/validation, read-only fold observer | Share folds/fits among diagnostic comparators |
| `fault_diagnostics/cues.py` | Fixed-support orientation-aware edges, decoys, NID | Reuse cues; intensity and decoys remain explicit ablations |
| `fault_diagnostics/evidence.py` | Per-hypothesis/per-capture held-out cue changes and production-density counterfactual | Reuse matched evidence rather than rerun fitting |
| `fault_diagnostics/policy.py` | Quality gating, robust replication, reference confirmation, ambiguity, outer checks | Unchanged V2 comparator; scene support is descriptive |
| `fault_diagnostics/runner.py` | Production assessment plus experimental V2 decisions and timing | Optional observer output only, with unchanged default decisions |
| `fault_diagnostics/sequential.py` | Existing clipped CUSUM and conformal monitor | Reuse monitor and state nominal-history/exchangeability assumptions |
| `fault_diagnostics/perturbations.py` | Deterministic calibration perturbations and image/cloud nuisance controls | Reuse for matched development comparisons |

## Failure mechanisms and testable interpretations

1. **R versus principal point:** narrow bearing coverage makes geometric displacement fields nearly collinear. This is scene-dependent identifiability, not solved by a different threshold. Evaluate directional rival residuals over field of view and preserve ambiguity.
2. **Translation:** homogeneous projection gives inverse-range displacement at fixed bearing; weak depth and bearing variation reduce separability. Rank alone must not be interpreted as precise translation diagnosis.
3. **Dense edges:** nearest unrelated edges lower nearest-edge loss without true alignment. Oriented matching, fixed support and negative controls must accompany geometric derivatives; accurate derivatives cannot repair false correspondences.
4. **Intensity:** requiring gain in NID removed 13 historical detections without preventing an alarm. Keep informative intensity descriptive/optional until an independently useful combination is demonstrated.
5. **Decoys:** historical raw oriented matching performs similarly. Decoy bias measurement remains useful, but a central diagnostic advantage was not demonstrated.
6. **Quality gating:** historical ablations consistently support it; stronger quality claims require independent evaluation. Gating using any candidate's outcome is a post-fit descriptive screen, not an independently measured sensor-quality prior.
7. **Selection:** V2 already maximizes worst conditional group information. Repeating this algebra under new names is not a contribution. Test separation of specific surviving fitted effects and count its processing cost; report negative outcomes.

## Data integrity

All existing V2 development and historical held-out recordings are now V3 development data. Static captures and repeated trials share scenes, so trial counting does not yield independent sensor-level confidence. The estimated anchor is not physical ground truth. Independent physical validation remains unavailable. The execution protocol for V3 is in [PREREGISTRATION_V3.md](PREREGISTRATION_V3.md).
