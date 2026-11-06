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
