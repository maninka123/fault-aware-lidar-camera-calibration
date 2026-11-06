# Research readiness assessment

**Status: executable experimental V3 research backend; a stronger real-sensor fault-identification method and publication readiness are not established.** Independent physical validation is incomplete. Existing V2 development and historical held-out recordings are all V3 development data.

## Implemented and verified scope

The new package provides analytic fisheye/pose/beam sensitivities, known-correspondence signed-signal inference, effect-specific rival refitting, interpretable scene summaries and depth/image-region contributions, explicit ambiguity, finite-effect recorded-observation design, an offline update contract, a hash-checked future simulator adapter, configuration and CLI. It reuses existing projection/data utilities, nuisance projection, feature associations, selective fitting, uncertainty and temporal monitoring. V2 and production remain available. The application/hardware-write workflow is not replaced.

Independent finite differences verify all thirteen physical derivative columns across rotation conventions, translation, beam offsets, distortion, optical-axis and wide-angle configurations. Deterministic tests exercise exact aliases, joint groups, rank loss, parameter units, correlated covariance, shared nuisance, conservative abstention, training-only selection and independent update gates. Exact-correspondence experiments test nonlinear generated measurements rather than constructing every observation by multiplying the tested Jacobian.

The baseline audit records the original failing responsive-layout test. A platform-font-dependent test width was corrected without changing the application widget. Final executed test counts and artifact provenance are in [experimental results](EXPERIMENTAL_RESULTS.md).

## What the experiments support

The controlled equidistant-camera fixtures distinguish an exact great-circle yaw/principal-point alias from broad two-dimensional bearing geometry that can resolve it. Depth diversity alone does not break that exact angular alias. Translation signatures follow inverse camera range at fixed bearing. These results justify geometry-specific explanations and data requests under the implemented local camera model; they do not establish novelty over all observability literature.

The recorded experiment shares the production engine's fits, folds and budgets with V2 and V3 ablations. It exposes wrong fitted explanations despite apparently separable geometric signatures. This contradicts promotion of local geometric separability into confident physical attribution when cross-modal correspondences are uncertain. The final recorded decision therefore uses geometry conservatively: it can veto an attribution or preserve additional explanations; it cannot upgrade an ambiguous baseline decision. The permissive failed version is retained as a development result.

Finite-effect selection works on a known-correspondence candidate pool, but did not outperform D/E/V2 contrast selectors. It remains an optional experimental utility. Scene-quality indicators are interpretable summaries, not a validated correspondence-noise model. Decoys remain existing controls; their restoration after a raw-share nuisance alarm is an explicitly outcome-informed development decision. Mandatory intensity agreement is not retained. The V2 sequential monitor remains unchanged because no new temporal benefit was demonstrated.

## Candidate scientific contribution

The narrow candidate is a geometry-conditioned **explanation** of finite calibration-fault effects, coupled to conservative ambiguity preservation and an explicit request for observations that might separate rivals. The exact fisheye great-circle example illustrates why generic “wide view” or “more depth” advice is insufficient. A publication claim would need a stronger general characterization and independent evidence that these explanations improve useful diagnosis or data efficiency.

Projection derivatives, normalization, Schur complements, principal angles, matched-subspace tests, selective updates, T-optimal design, CUSUM and abstention are established. Packaging them as V3 does not make them novel. The [review](LITERATURE_REVIEW.md) resolves the full OCaMo manuscript gap but records remaining access limits; absence of a matching paper in that review is not proof of novelty.

## Material limitations and missing evidence

The signed-measurement oracle and recorded nearest-edge audit are different inference paths. The recorded path does not obtain verified image/LiDAR correspondences or recover tangential displacement from a single edge normal. Its geometry is local and conditional on frozen candidate-selected associations. Unknown occlusion, timing, reflective surfaces, camera-model mismatch and shared static-scene artifacts remain possible explanations. Only k1/k2 are variable distortion parameters; k3/k4 are fixed reference terms. Other camera families are rejected.

Rival least-squares coefficients are unbounded, so an unrealistic large rival can conservatively preserve ambiguity. Nested supersets cannot be physically ruled out when their extra effect is zero or unobservable; minimal explanations are a parsimony convention. Captures within a recording are dependent. No fault posterior, calibrated coverage, false-alarm guarantee, operational delay bound or acceptance-risk guarantee is established.

The matched diagnostic comparison does not exercise V3 candidate acceptance; zero updates there is not a successful acceptance result. Default four-capture training can be insufficient for the existing cluster-uncertainty gate at larger reduced dimension. Tests check the update contract, and the full API separately fits/rechecks a candidate and reserved outer evidence. Its useful acceptance rate and accepted-update physical accuracy remain unvalidated.

## Most valuable next physical experiments

1. Independently measured mount rotations and translations with a jig, tracker or other external metrology, repeated over independent sessions. Pair narrow/great-circle, off-plane wide-angle, shallow-depth and depth-rich scenes while matching feature budgets.
2. Independent camera intrinsics before/after a controlled change, including principal point, focal length and distortion; quantify the uncertainty of this reference separately from the algorithm under test.
3. Nuisance-only sessions: low light, enclosure reflections/dirt, occlusion, missing LiDAR returns and known timestamp offsets under motion. Include scene changes with unchanged calibration.
4. Longer timestamped nominal/abrupt/gradual/transient recordings with genuinely nominal history, allowing per-session false alarms and delay to be reported without treating overlapping accumulation windows as independent.
5. Multiple rigs, lenses and the separate simulator's five sensor profiles, with renderer/profile provenance, true visibility, independent scene/session splits and labels withheld from fitting and capture utility.

Freeze these recording-level development/calibration/test partitions before inspecting final labels. Report exact attribution, incorrect attribution, ambiguity size/truth containment, selective coverage, actual parameter errors and accepted-update errors together. A method that only abstains more must be described as that tradeoff. See [simulator integration](SIMULATOR_INTEGRATION.md), [failure analysis](FAILURE_ANALYSIS.md), [selection results](ACTIVE_SELECTION_RESULTS.md) and [V2/V3 comparison](V2_V3_COMPARISON.md).


## Update after the correspondence study (improved V3)

**Status: experimental, diagnostically stronger and safer, but attribution is still not established on recorded sensor data. Not publication-ready.**

What changed: a root-cause analysis with numbers (pairing identity 57 to 62 %, falling with the diagnosed error), a responsibility-weighted pairing front end with a frozen-protocol
evaluation, a signed-residual diagnosis path with recovery and acceptance measurements, negative results for alternating estimation and a unique-pair rule, CI that runs the
research suite, and a per-module test runner.

What the evidence supports: on two evaluation recordings (28 injected changes, 12 no-change trials) the new front end raised 0 no-change alarms (existing front ends 6 to 8 of 12), made 0 wrong
unique attributions (existing 3 to 9), and detected 28 of 28 changes. It gives **1 of 28** exact attributions against 17 of 28 with correct pairs.

What contradicts a stronger claim: exact attribution did not improve over the original recorded V3 (0 to 1 of 28); the improvement is abstention-driven safety; recovered error is 1.29 px against a 0.19 px control; only 1 of
28 updates passed acceptance; visibility and balancing showed no benefit; the control is a proxy from the anchor, not verified correspondences; both pairs of recordings were examined earlier; no physical truth exists.

Merge safety as an experimental, non-default feature: the V3 package, tools, tests and documents are additive. Changes to existing modules are an optional read-only fold observer in `assess` (default off), an optional
reflectivity-sample argument of the capture loader (default off), a fix for an empty-basis LAPACK failure, a `diagnose`/`diagnose-v3` command, one application file (`gui/result_visuals.py`, the overlay alignment banner) and CI. No production decision
rule, hardware path or maintenance code is changed. Remaining merge risks: the desktop-window native crash noted in the CI section (pre-existing, unresolved) and the Linux CI job being unverified.

Most valuable next experiments (unchanged in kind, sharpened by this study): independent correspondence information, since pairing at the current estimate cannot be both unbiased and informative. Options, in order of
cost: fiducial or calibration-target frames inserted into otherwise natural sessions (the Nov 5 board recordings already contain boards); a nominal-period correspondence map re-used across later sessions; multi-view structure;
then physical sessions with independently measured mount rotations, translations and intrinsics.
