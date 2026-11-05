# Numerical design proposal — pending literature comparison

This is a mathematical design proposal, not an implementation or a novelty claim. It separates numerical identifiability from fault attribution and predictive validation. The paper-to-algorithm comparison must be completed before this design is adopted.

## Existing representation and residual contract

The existing backend uses thirteen parameters in this order:

`wx wy wz tx ty tz fx fy cx cy k1 k2 delta`.

`R = Exp(w) R_mount` maps LiDAR coordinates into camera coordinates; translation is expressed in camera-frame metres. `delta` is the existing depth-edge beam-widening nuisance parameter, not a universal LiDAR sensor model. Higher distortion coefficients supplied by a calibration must remain fixed unless the adapter explicitly supports estimating them.

Let the reference calibration be `p0`. The new engine must evaluate the existing image-edge normal residuals on a **fixed association batch** during each local solve. Correspondence search happens outside that solve. Thus a Jacobian describes a smooth local, fixed-correspondence residual, not a derivative of nearest-neighbour search or the complete ICP procedure. Each reassociation invalidates the previous local information calculation and requires a new one.

Use a left rotation perturbation `R(d) = Exp(d_rotation) R(p0)`, additive translation, and additive intrinsic/nuisance increments. Conversion back to the existing rotation-vector storage occurs through SO(3), never by editing matrix entries. A retraction callback lets the numerical solver remain independent of this storage convention. Candidate checks reject nonfinite parameters, nonpositive focal lengths, invalid projections and nonmonotone lens maps over the actual supported angular domain.

The generic callable is `residual_fun(parameters) -> finite one-dimensional array`. Its dimension and association ordering must remain constant throughout a local solve. Parameter priors, if used for fitting, are returned separately from measurement residuals and excluded from measurement observability.

## Scaled measurement information

Let `J` be the Jacobian with respect to local physical increments. Declare a positive diagonal scale matrix `D`; one normalized parameter unit represents a documented physically meaningful change. Candidate default scales are one degree rotation, one centimetre translation, one percent focal length, one image pixel principal point, `0.01` distortion and `0.1` degree beam nuisance. These scales are conventions requiring sensitivity analysis, not measured uncertainties.

Let `W` contain nonnegative training-only measurement weights. Robust weights are frozen at the current iterate, so the resulting information is an IRLS local approximation. Residual noise scale and capture normalization must be explicit. Equal weighting per capture can prevent a dense capture from dominating this diagnostic, but does not turn its edges into independent observations.

Define `A = sqrt(W) J D`. Never add prior precision to `A' A` when describing information supplied by observations. Report both numerical rank (`sigma > rtol * sigma_max`) and any separately configured practical sensitivity threshold; a numerical rank alone is not evidence of useful precision.

## Nuisance profiling and conditional group information

Partition `A = [A_C, A_N]` into calibration and nuisance columns. Use a rank-revealing SVD of `A_N`; let `Q_N` contain its supported left singular vectors. Compute

`A_bar = A_C - Q_N (Q_N' A_C)`.

The profiled information is `H_bar = A_bar' A_bar`. It equals the generalized Schur complement `H_CC - H_CN H_NN^+ H_NC`. The projection implementation avoids subtracting large nearly equal normal matrices and remains well defined when nuisance columns are singular. An implementation must not allocate a dense residual-space identity matrix.

For a group `g`, project its scaled Jacobian against nuisance and every *other calibration group*:

`A_unique_g = (I - P_[N,-g]) A_g`.

Its right singular vectors describe group-coordinate directions with effects that cannot be reproduced locally by the competing groups. Report unique information, numerical/practical rank and unique-to-marginal energy ratios. This is stronger than estimability when all other calibration groups are fixed.

Keep two notions separate:

- **Conditional estimability under a hypothesis:** profile nuisance and restrict to that hypothesis's allowed calibration columns. A candidate can be locally estimable when competitors are fixed.
- **Unique evidence for attribution:** additionally profile competing calibration groups. A candidate can fit well while its claimed physical cause remains ambiguous.

Do not reject a mathematical optimizer merely because a larger model contains it. Nested model spaces inevitably overlap. Attribution and prediction are separate outputs.

## Competing effects and ambiguity

For nuisance-profiled group effects, compute rank-revealing orthonormal column bases `Q_g`. Singular values of `Q_g' Q_h` are principal-angle cosines, clipped into `[0,1]` before `arccos`. Empty/zero-rank groups return an explicit unsupported comparison, not a fabricated angle. A shared effect direction is not proof that all directions are indistinguishable: retain the complete angle spectrum and per-direction unique energy.

A diagnostic pairwise contrast may be expressed as

`B_g|h = (I - Q_h Q_h') A_bar_g`.

Its smallest supported singular value measures the weakest normalized change in `g` that `h` cannot mimic locally. This quantity is scale-, residual- and threshold-dependent; it is not a fault probability or guaranteed detection rate.

Build a candidate ambiguity set from insufficient unique evidence plus independently evaluated predictive ties. Only remove a candidate when training evidence and the preregistered validation comparison support doing so. A pairwise local overlap diagnostic alone cannot establish that a fault actually happened. If distinct physical explanations remain plausible, report `INSUFFICIENT_EVIDENCE`, keep the reference calibration and expose the ambiguity set.

## Selective optimization

### Correspondence-stable conditional contrast: narrower research hypothesis

The provisional distinguishing mechanism is robustness of **conditional fault contrast** to plausible correspondence choices, rather than generic observability truncation. This is still a candidate extension: subspace intersections, robust experimental design and geometric fault isolation are established ideas. The prior-art mapping must determine whether this use adds a distinct mechanism.

Construct `V` association variants on training data at the same reference calibration, for example gates of `6`, `9` and `12` pixels, or separately frozen nearest-edge alternatives. These are alternate interpretations of existing observations, not independent measurements and not a sensor simulator. Record the variants and their support. Gate perturbation alone does not span every correspondence error; all variants may share the same incorrect associations.

For variant `v`, form its scaled, weighted Jacobian `A_v`. Row dimensions can differ across variants. Nuisance and competing-group profiling yield the group-conditional matrix `C_gv = (I - P_[N,-g],v) A_gv`. Its supported right-singular basis `V_gv` lies in the common normalized **parameter** coordinates of group `g`; this permits cross-variant comparisons even when residual rows differ. Raw left-singular residual bases from different variants must not be compared without an explicit row correspondence.

Let `P_gv = V_gv V_gv'` and define

`M_g = (1/V) sum_v P_gv`.

The exact intersection consists of eigenvectors with eigenvalue one. A practical near-intersection can propose eigenvectors whose eigenvalues exceed a declared stability threshold such as `0.9`. An average projector threshold by itself is insufficient: with ten variants, a direction completely absent from one variant could still reach `0.9`. Therefore additionally require support under **every** variant.

For a proposed basis `B_g`, evaluate

`support_gv = lambda_min(B_g' P_gv B_g)`

and

`contrast_gv = sigma_min(C_gv B_g)`.

Require the minimum projector support and minimum normalized contrast across all variants to meet explicitly configured thresholds. If a multicolumn basis fails because a mixture points toward an unsupported direction, remove failing eigenvectors or return a smaller/empty basis; never report the whole space as stable merely because each original column separately passed. Report eigenvalues, worst-variant support, worst-variant sensitivity and the variant responsible. All eigenvalues/singular values are clipped only for floating-point roundoff, not to conceal failure.

Apply the same construction to **hypothesis-conditional estimability**, where the only profiled effects are nuisance and the allowed calibration columns belong to that hypothesis. Keep its stable basis distinct from the group-unique stable contrast basis. A hypothesis may produce an estimable update while its historical cause remains unsupported because another group reproduces the same effects across variants.

Within each variant, compute principal-angle spectra between nuisance-profiled group residual spans. Across variants, summarize each pair by its worst overlap or minimum contrast, with unsupported/empty variants retained as failures. Do not compare stacked residual spaces using duplicated association variants as if they supplied extra independent information.

For a selected training capture set `S`, a robust acquisition proxy can rank an additional already-recorded training capture by its gain in the worst unresolved pair's contrast, minimized over association variants. Every candidate subset is stacked within each variant before shared-nuisance profiling. The goal is to resolve a *stable* ambiguity, not to maximize an arbitrarily large Jacobian produced by an unusually permissive gate.

This proposal can fail usefully: the stable unique group subspaces may all be empty. The correct response is to retain the reference and report association-sensitive attribution. Its experimental hypothesis is that stable conditional contrast reduces unsupported attribution relative to one-association observability on identical recorded partitions. Failure to improve independently evaluated decisions, or widespread unnecessary rejection without reduced false attribution, would falsify the advantage. Unlabelled current recordings can demonstrate stability/abstention behavior but cannot verify false fault-attribution rates.

Proposed additional API:

```python
analyze_ensemble_observability(
    jacobians, scales, groups, nuisance_indices,
    row_weights=None, variant_names=None,
    rank_rtol=1e-8, minimum_singular=0.0,
    projector_eigenvalue=0.9, minimum_variant_support=0.9,
)
```

`jacobians` is an ordered list of finite measurement-only arrays with the same parameter columns and possibly different row counts. `row_weights`, when supplied, has one compatible vector per variant. Return each ordinary analysis, stable hypothesis and group bases in normalized parameter coordinates, full projector spectra, worst-variant diagnostics and conservative pairwise summaries. A single variant reduces to ordinary analysis with a clear limitation; empty or invalid variants must be rejected explicitly rather than silently omitted. Held-out observations never enter this API.

For hypothesis `h`, create an orthonormal basis `B_h` in normalized parameter coordinates. Its rows outside allowed calibration/nuisance indices are exactly zero. Obtain its calibration columns from the nuisance-profiled identifiable right singular vectors. Append only supported nuisance directions. In a deliberately more conservative variant, restrict group updates further to their unique-evidence subspaces; report this as an ablation because it may reject legitimate shared directions.

Solve

`min_z sum_i rho(r_i(p0 plus D B_h z)^2)`

using the existing residual geometry, bounded normalized step sizes and the SO(3) retraction. Priors may regularize supported directions but cannot resurrect an unsupported measurement direction. Fixed groups remain bitwise equal to the reference storage. Step bounds apply in identifiable coordinates; physical camera validity is checked explicitly because a rotated affine subspace does not map parameter box bounds to independent box bounds in `z`.

After solving, recompute fixed-correspondence diagnostics, validate the projection model, reassociate and repeat only within the configured iteration budget. If correspondences vanish, residuals change shape, numerical values become invalid, the solve fails, or a step escapes the admissible region, return a failed candidate and preserve the input calibration. Truncated-SVD constrained least squares is established numerical machinery; using it is not by itself a contribution.

## Recorded-capture selection objective

Capture ranking must use training captures only. For a selected set `S`, stack its weighted fixed-association Jacobians, then **profile nuisance after stacking**. In general the sum of independently nuisance-profiled capture matrices is not the global Schur complement when a nuisance is shared across captures.

For unresolved nonnested group pairs, evaluate the weakest supported unique contrast in both directions. A conservative greedy objective is the improvement of the minimum unresolved-pair contrast per processing cost. Use a secondary total-information criterion only to break exact ties. Preserve zero-rank pairs in the objective so a capture set cannot look successful merely by dropping its hardest ambiguity.

This is a decision-oriented local sensitivity proxy, not expected Bayes-risk reduction: no calibrated probability/noise-generating model has yet justified that stronger interpretation. Compare with fixed-count, deterministic random, feature-count and ordinary information selection using identical held-out captures. If candidates are nested, compare the *additional* group's contrast against the simpler model rather than the full spaces' trivial common intersection.

## Uncertainty and validation

For a supported basis, local covariance can be computed in reduced coordinates. Capture-cluster sandwich covariance uses one score sum per capture rather than one independent trial per edge. Report the number of clusters and the covariance rank; with too few independent clusters, report uncertainty as unsupported. Cluster estimates remain limited when repeated captures share the same scene, session or extraction biases.

An unobservable direction has unknown/unbounded uncertainty, not zero uncertainty from a pseudoinverse. Output identifiable covariance together with a nullspace basis. A scalar parameter whose coordinate overlaps the nullspace cannot receive an unconditional finite standard deviation. Capture/session jackknife refits can additionally measure algorithmic instability but are not a calibrated confidence guarantee.

Model selection and final evaluation must be split. With enough captures, use an outer held-out evaluation partition and perform capture selection, hypotheses, scaling, residual-noise estimation and threshold selection solely inside the training partition. Where only leave-one-capture-out comparison is feasible, label it model-comparison evidence; do not report the same score as an untouched final evaluation. Region holdouts are sensitivity checks on one scene, not independent capture evidence.

The final acceptance policy should require successful numerical fitting, acceptable coverage, supported measurement directions, sufficient independent held-out improvement and no unsupported physical attribution. No ground-truth fault labels exist in the current recordings; these recordings cannot establish fault-classification accuracy.

## Proposed numerical APIs

```python
numerical_jacobian(fun, x, scales, retract=None, relative_step=1e-5)
analyze_observability(jacobian, scales, groups, nuisance_indices,
                      row_weights=None, rank_rtol=1e-8,
                      minimum_singular=0.0)
optimize_selective(residual_fun, reference, free_indices, scales,
                   basis=None, retract=None, valid=None,
                   max_normalized_step=3.0, max_nfev=100)
cluster_uncertainty(jacobian, residuals, cluster_ids,
                    scales, observable_basis, rank_rtol=1e-8)
```

Outputs are typed records with JSON-safe diagnostics. Numerical modules consume only the explicitly supplied training arrays and do not open capture files, choose validation folds, or access global held-out data. The adapter owns association batches and source-code conventions.

## Required numerical verification

Use deterministic small algebra/geometry fixtures, not a sensor simulator:

1. Central differences versus independent closed-form derivatives on a nonlinear residual and SO(3) projection example.
2. Orthogonal nuisance projection versus generalized Schur complement, including duplicated and zero nuisance columns.
3. Exact rank/nullspace on constructed matrices; finite principal angles for empty, identical and orthogonal subspaces.
4. Conditional group information becomes zero when another group exactly mimics it.
5. Unit-coordinate rescaling preserves the same physical supported subspace when `D` transforms consistently.
6. Reduced optimization cannot move a forbidden parameter or an unidentifiable direction.
7. Invalid focal/model values, changing residual dimensions and nonfinite inputs fail explicitly.
8. Cluster uncertainty reports insufficient clusters and unsupported null directions rather than false precision.

Projection and thin SVD cost `O(m d^2 + d^3)` for `m` residuals and `d <= 13` parameters. Avoid residual-space projectors of size `m x m`. Reassociation and repeated candidate fits will dominate runtime in real recordings.
