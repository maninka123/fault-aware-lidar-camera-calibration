# Why correct signatures have not solved recorded fault attribution

Analysis date: **6 November 2026**. Correct fisheye derivatives and successful exact-correspondence examples establish a mathematical/software capability. They do not establish that this recorded-data front end supplies the signed measurements or correct fault effects needed to use that capability. This document separates code facts, observed trial examples and hypotheses requiring further experiments. Final aggregate results belong in `EXPERIMENTAL_RESULTS.md`; rolling partial summaries are not final evidence.

## Completed permissive-policy evidence audit

The following counts were read **after** `research_artifacts/v3_final_development_20261106/run_status.json` recorded `status=complete`, 68 completed trials and zero trial errors. `source_integrity.json` reports no source changes during the run. Despite the folder name, this is the completed **permissive attribution policy** evaluated before the final conservative-veto revision. Its `trials.jsonl` and `summary.json` are the evidence; the interrupted preliminary run is excluded. The later outcome-informed policy replay is reported separately below.

| Method | Detection, 32 drift cases | Exact attribution | Wrong unique attribution, all 68 cases | Ambiguous drift cases | True exact fault in ambiguity | False alarms, 36 no-change cases |
|---|---:|---:|---:|---:|---:|---:|
| V2 | 22 | 0 | 4 | 18 | 12 | 0 |
| V2 without mandatory intensity | 27 | 1 | 3 | 23 | 16 | 0 |
| V3 permissive policy | 27 | 0 | 2 | 25 | 18 | 0 |
| V3 without signatures | 27 | 1 | 3 | 23 | 16 | 0 |
| V3 without scene quality | 25 | 0 | 2 | 23 | 17 | 0 |
| V3 raw oriented edges | 28 | 0 | 2 | 27 | 17 | 1 |

Thus signatures provide a modest **abstention/ambiguity tradeoff**, not improved exact identification: compared with the no-signature ablation, the net result is one fewer wrong unique attribution, one fewer correct unique attribution, two more ambiguous drift cases and two more ambiguity sets containing the true exact group. Detection does not change. These are dependent semi-synthetic development cases over four spent recordings; counts do not establish significance or physical-fault accuracy. Removing mandatory intensity explains much of the detection difference from V2. Raw oriented matching gains one detection while introducing a no-change alarm in this run, so it does not dominate the decoy-referenced default.

The paired transitions matter more than the net wrong-attribution count: signatures convert two wrong unique labels to ambiguity, **introduce one wrong unique label from an ambiguous decision**, and convert one correct unique label to ambiguity. The newly wrong case is `enclosure_off_ten` R at 0.5 degrees. The correct T at 3 cm on `october_device_one` becomes ambiguous. The two removed wrong labels occur for enclosure-off rotation-plus-spurious-lines and device-four joint RT. Consequently the mechanism cannot be described as only adding safe abstention or universally preventing false confidence.

Two completed case records illustrate the limits:

- `october_device_one`, `drift:R:0.5`: the best edge-evidence model is R, but the final ambiguity is `{I,R,T}`. The representative correction's rival mismatch is about 0.248 px for I and 0.346 px for T, below the declared 0.35 px separation tolerance. T's mismatch varies across folds from about 0.308 to 0.395 px; the conservative every-fold rejection rule therefore retains it. This is measured local ambiguity of the fitted effect, not evidence that translation physically changed.
- `enclosure_off_ten`, `drift:R:0.5`: edge evidence supports TI alone and V3 reports `DRIFT_SUPPORTED(TI)`, an incorrect exact attribution relative to the injected R label. The geometric audit explains the fitted TI correction and cannot recover the true R cause from a wrong upstream explanation. This is a concrete failure, not an inference success hidden inside an ambiguity set.

Signature reports are available in 26 completed cases, with 562–2373 retained scalar rows per report. The largest absolute substitute coefficient is about 22.9 in the declared normalized parameter units. This flags sensitivity of unbounded rival explanations; it does not by itself prove a substitute calibration is physically invalid. No retrospective coefficient cap or separation-tolerance change was applied.

### Final conservative policy: separate outcome-informed replay

After these outcomes were inspected, `update_policy.conservative_attribution` was introduced so geometry may **veto** a unique attribution but cannot create one from ambiguous held-out evidence. A unique result requires the same unique hypothesis in the baseline and geometric decisions, with available fold effects and signatures. This removes the permissive promotion demonstrated above by a logical contract, not by evidence that the promoted explanation was accurately estimated.

`research_artifacts/v3_conservative_replay_20261106/run_status.json` records a completed 68-case replay with zero errors. It reuses the saved fits, geometry and sensor evidence; no fresh sensor observations or nonlinear fits were obtained. The protocol explicitly labels it **outcome-informed development policy replay**, not an untouched experiment. The final V3 replay gives 27/32 detections, 0/32 exact attributions, 1/68 wrong unique attribution, 26/32 ambiguous drift cases, truth in 18/26 ambiguity sets and 0/36 no-change alarms. The no-geometry comparison remains 27 detections, 1 exact and 3 wrong unique attributions. Zero V3 updates remains untested acceptance behavior in this diagnostic-only evaluation.

The final rule prevents the newly wrong TI promotion by construction. It also does not recover the lost correct T diagnosis, and a wrong baseline label can still survive if geometry supports the same candidate effect. Relative to the completed permissive run, the improved wrong-label count is an outcome-informed conservative restriction, **not independently demonstrated stronger exact diagnosis**. A fresh recorded full-pipeline evaluation and independent physical data are still needed.

## 1. The oracle and recorded paths solve different problems

`diagnostic_inference.infer_signatures` receives a signed observation-change vector, a Jacobian, covariance and capture identities. In the numerical geometry experiment, the observations come from projecting known 3D points through a changed calibration with exact correspondences. Its competing local models are tested against those actual signed measurements.

The recorded `runner.diagnose_from_records` path deliberately reuses V2's nonlinear fits and oriented-edge counterfactuals. It selects a best **fitted hypothesis** by held-out cue improvement, extracts the correction fitted in each training fold, and asks which other parameter groups could reproduce that correction's *predicted displacement*. It does **not** call `infer_signatures` to infer the underlying fault from an independently observed signed displacement field. In particular, `capture_signature` returns residuals, but the recorded runner uses its Jacobian and the old fitted correction rather than fitting those residuals as a new generative fault model.

This distinction is fundamental. If the original fit follows an unrelated edge or an intrinsic/pose compensation direction, a perfectly correct derivative explains that wrong correction faithfully. It cannot identify the actual injected parameter group simply because the injection label is known to the evaluator. The current V3 addition is primarily an **audit of the geometry supporting existing candidate explanations**. Calling it a solved new recorded-data fault estimator would overstate the implementation.

**Next discriminating experiment:** acquire independently annotated/known cross-modal correspondences on a small subset of the recorded geometry and compare signed-oracle versus automatic-association diagnosis using exactly the same points, normals and noise assumptions. This separates front-end correspondence bias from the geometric inference itself. Without those annotations, oracle success and recorded failure do not locate the entire cause.

## 2. One edge normal does not observe a two-dimensional displacement

For an image line normal `n` and projected displacement `delta_u`, the measured local change is

`delta_r = n.T @ delta_u`, with signature `J_line = n.T @ J_pixel`.

A displacement along the edge tangent vanishes. For example, horizontal displacement is invisible to a horizontal edge whose normal is vertical. No additional copies of that same normal restore the missing direction. With unit normals and a consistent isotropic pixel-noise model, normal projection cannot add information relative to the original two-dimensional pixel observations; it may discard the very component that separates two faults.

The numerical geometry/active experiments use both pixel coordinates for every exact correspondence. Recorded calibration predominantly observes scalar point-to-line constraints. These are unequal information contracts. The two-dimensional result is an optimistic controlled case, not a prediction of identical recorded attribution accuracy.

**What to report next:** compare full-2D versus measured-normal versus deliberately co-oriented-normal fixtures at matched 3D geometry, fault size and covariance. Measure the associated normal distribution in each depth/bearing stratum, rather than infer it from all image edges. This is a numerical diagnostic experiment; it does not require building the separate photorealistic simulator.

## 3. Present quality summaries do not certify the retained measurement geometry

`scene_summary` reports depth/range percentiles and image-grid coverage over in-domain projected LiDAR features. Its normal-orientation entropy and edge density use **all extracted image edges**. `capture_signature` subsequently retains a subset selected by orientation-aware nearest-edge associations and optional feature-type filtering. The reported summary therefore is not the distribution of the rows actually entering the signature matrix.

A capture can have broad global image-edge orientation entropy while the matched evidence concentrates on one edge family, one depth layer or one quadrant. The summaries are useful descriptive context, but cannot certify that R/T/I are distinguishable on the retained support. Similarly, `visible_share=1` means in-domain projection, not that camera occlusion is absent. No complete point-cloud surface/visibility oracle is implemented here.

The current geometric-only screen excludes the existing extractor's intensity-edge type and keeps depth/crease labels. Those labels are predictions, not verified physical correspondences. A LiDAR depth boundary can lie on the wrong side of a camera occlusion or be displaced by the beam footprint; a crease may be weak or invisible in appearance. Filtering a label alone cannot solve these effects.

**Next changes worth testing:** expose retained rows by feature type, depth, bearing, normal direction and image cell; quantify association multiplicity/margins; separate predicted in-domain visibility from actual surface occlusion when full geometry is available. Compare depth-only, crease-only and combined support with a common held-out evaluation set. Do not promote a more complicated extractor until those ablations improve outcomes.

## 4. Edge density and association changes survive the new geometry analysis

The V2 audit measured a scene-dependent nearest-edge loss bias. V3's orientation-aware/decoy-reference decision mitigates that specific score behavior; it does not establish correct point identity. Multiple nearby edges with compatible orientation can still provide competing associations, especially under clutter, repeated texture and ghost/nuisance conditions. Candidate-dependent reassociation can then produce a smooth, apparently supported correction unrelated to the injected group.

The recorded signature freezes associations chosen near each fitted candidate and evaluates their sensitivity at the current calibration. That is a local stress-test construction, not an independent correspondence validation. Large candidate motion, correspondence switches or changes near a visibility boundary weaken its linear interpretation. The additional fold/quality checks are safeguards, not a proof that these errors are absent.

Depth/crease screening and decoys also address different questions: the former changes the geometry support; the latter estimates unrelated image structure. Neither provides a calibrated association covariance. The signature uses a declared common pixel scale and deliberately avoids interpreting robust optimizer weights as covariance. Correlation between nearby points and static captures remains an unmeasured limitation.

**Next discriminating experiment:** log correspondence identity and nearest compatible rival-edge margins across frozen association gates, then compare held-out decisions on common support. Include repetitive/texture-rich geometry with known point identity. Adding more image features or more copies of a static capture is not a substitute.

## 5. The fitted effect need not be the true effect, and folds disagree

The final runner chooses an actual fold correction as a medoid. It uses that correction for explanations but evaluates all surviving fold corrections before rejecting a rival. This corrected an earlier problem: coordinate-wise medians need not lie in any actual fitted hypothesis's supported subspace and can cancel directions into a fictitiously easy explanation.

The final trial log includes cases where an injected rotation has a rotation-containing or joint model as best fit, and translation cases whose best fit belongs to a different compound group. The discrepancy is not repaired by assuming the fitted correction is the injection. Its source could include imperfect anchors, scene/association bias, weak geometry, optimization convergence or competing compensation; the current trials do not isolate these causes individually.

The implemented conservative rule rejects a rival only if **every** retained fold correction exceeds the declared effect tolerance. This preserves a rival when one plausible fitted effect remains confounded. It reduces the temptation to overinterpret one fold, but a weak or unstable fold can also prevent unique diagnosis. The fold spread is descriptive variation in normalized parameter units, not a calibrated uncertainty interval or independent replication statistic.

**Next changes worth testing:** compare per-fold corrections against known change vectors on controlled truth-labelled inputs; diagnose association instability versus optimizer nonconvergence separately; assess whether physically independent scene blocks change the effect agreement. Replacing the all-fold condition by a majority just to increase exact labels would trade robustness for coverage and requires its own frozen evaluation.

## 6. Unbounded local rivals can retain implausible aliases

`effect_separation` allows arbitrary coefficients in the rival and nuisance columns. This is intentionally conservative: if a rival subspace can approximate the proposed displacement, geometry alone does not reject it. Some explanations may require large normalized focal/distortion/translation coefficients or leave the valid nonlinear camera domain.

The output contains those substitute coefficients, but the local rival is not independently nonlinear-refitted with the full physical validity constraints. A low local mismatch therefore establishes a *linear alias under the stated unbounded model*, not a physically realizable competing calibration. Conversely, imposing convenient coefficient bounds after seeing outcomes could create unjustified confident attribution.

**Next discriminating experiment:** predeclare physically justified parameter domains and local-linear validity tests using independent camera characterization; compare unbounded subspaces against constrained nonlinear rival refits at equal compute budgets. Report both “local mathematical alias” and “physically feasible rival.” Priors and plausible bounds can improve practical decisions, but must remain distinguishable from information supplied by the scene.

## 7. Cue ties and nested hypotheses impose deliberate limits

R is nested in RT, RI and RTI: those models reproduce pure R whenever their additional components vanish. No choice of observation can separate identical predictions. Exact nonzero physical support requires effect floors or an explicit model-selection convention, not just more points.

The runner preserves the ambiguity classes supplied by independently unresolved held-out cues. Its local signature can add aliases and provide reasons for abstention; it is not allowed to erase a genuine cue tie because a single selected correction appears separable. Minimal explanations express parsimony, while `compatible_hypotheses` retains larger models. A small ambiguity list is not proof that all omitted supersets are physically impossible.

This also limits what the added mechanism can achieve when a compound best fit already has the wrong physical explanation. A signature of that fit cannot automatically reinstate a rejected true label. The intended response is to expose the unresolved evidence and request a different observation, rather than force the injection's label into the answer.

**Next evaluation requirement:** score exact support, ambiguity containing the true exact group, compatible-superset coverage and unknown/abstention separately. Keep the definition of correct attribution unchanged across methods. Report cases where conservative preservation loses exact coverage as well as those where it prevents false confidence.

## 8. Earlier preliminary failures are preserved, not pooled with final results

`research_artifacts/v3_matched_development_20261106/run_status.json` records an intentionally interrupted preliminary run. Independent regression checks exposed unsafe alias promotion and median-effect behavior before source fixes. The partial source archive and trial log remain available. They must not be pooled with the corrected final run or presented as a completed performance evaluation.

The current runner requires the baseline and geometry to support the same unique proposed explanation, uses an actual fold effect rather than a coordinate median, preserves cue ambiguity, and rechecks a final refit's direction before candidate validation in the public API. These are correctness safeguards. They do not establish that the remaining nonlinear fits identify the true injected fault or that a validated hardware update is safe.

The matched development tool is diagnostic-only: it does not execute final candidate refitting and reserved acceptance for every trial. Its absence of V3 update recommendations therefore cannot be used as a measured false-update guarantee. The public API's safety contract and its unit/regression verification are a different evidence tier.

## 9. What remains unsolved and the next decision

The numerical experiments support correct local signatures and explain a controlled R/principal-point alias. They also show that finite-effect selection is useful relative to point count on the constructed example while matching, rather than surpassing, established D/E/V2 selectors. They do not establish reliable recorded exact fault attribution.

Priority should be: obtain independently checked correspondence/geometry evidence; measure retained normal/depth/bearing diversity; validate candidate and rival effects nonlinearly within justified parameter domains; and collect independent, measured physical fault/nuisance sessions. The current four recordings are spent development data and their optimized anchors are not physical truth. Small semi-synthetic perturbations test a consistent software question, but cannot certify the cause of a real sensor change.

Until those gaps are addressed, V3 should remain an explanatory experimental sidecar with explicit ambiguity and conservative candidate acceptance. Additional thresholds, another sequential detector or more code around the same biased effects would not resolve the principal evidence gap.


## Update: the "next discriminating experiment" was run

Section 1 above named the experiment that would separate front-end correspondence bias from the geometric inference itself. It was run with the anchor's own pairs as a
stand-in for known correspondences ([ROOT_CAUSE_ANALYSIS.md](ROOT_CAUSE_ANALYSIS.md)). Result: the same signed-residual inference attributes the injected group exactly in 15 of 28
development trials, returns an ambiguity set containing it in 12 more, and raises no nominal false alarm, while the existing pairings give 4 to 5 exact and 15 to 19 wrong unique labels.
Hypotheses 1, 3, 5 and 7 of the earlier list are confirmed with numbers (wrong pairing; fits that do not recover the truth; objective bias; faithful explanation of a wrong field).
The one-normal information limit (section 2) is not the dominant cause on these scenes: with one normal per point and correct pairs, translation and focal changes are identified.
Section 6 (unbounded rivals) was not tested; no justified fault bound exists. Section 4's association stability is now quantified (identity falls from 100 % to 30 to 50 % as the error grows).
