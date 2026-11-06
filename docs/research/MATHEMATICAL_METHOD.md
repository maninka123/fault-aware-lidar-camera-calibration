# Implemented mathematical method

Implementation: `research_calibration/`. This document supersedes the exploratory [draft](MATHEMATICAL_METHOD_DRAFT.md). Established components and literature decisions are identified in [PAPER_TO_ALGORITHM.md](PAPER_TO_ALGORITHM.md). Thresholds are declared engineering choices, not learned fault probabilities or statistical guarantees.

## 1. Parameters and coordinates

Use thirteen coordinates

`p = (w_x,w_y,w_z,t_x,t_y,t_z,f_x,f_y,c_x,c_y,k_1,k_2,eta)`.

The saved convention is `X_camera = R X_lidar + t`, with translation in metres. `R = Exp(w) R_reference`. Left rotation increments compose as `Exp(delta_w) Exp(w)`; translation increments add in camera coordinates. This is a product SO(3) × R³ parameterization, not a coupled SE(3) exponential.

The supported camera adapter is OpenCV's zero-skew equidistant polynomial. With `a=X/Z`, `b=Y/Z`, `r=sqrt(a²+b²)`, `theta=atan(r)`,

`theta_d = theta (1+k1 theta²+k2 theta⁴+k3 theta⁶+k4 theta⁸)`,

`u=fx a theta_d/r+cx`, `v=fy b theta_d/r+cy`, with the continuous axial limit. Supplied k3/k4 remain fixed. Reject other explicitly declared projection families rather than silently interpreting their coefficients. The beam nuisance eta rotates selected depth-edge points in LiDAR azimuth by their signed foreground/background side; it is the existing extractor's sensor-specific model, not a universal LiDAR model.

The predeclared domain is Z>0.2 m, theta<=1 rad, image bounds and an inscribed image circle (centre `(width-1,height-1)/2`, radius `min(width,height)/2`, with the projection's 0.97 radius margin). It is never fitted from held-out image appearance. Require positive plausible focal lengths, principal point inside declared bounds, ||t||<=2 m, |eta|<0.05 rad and positive sampled radial derivative across the angular domain. These are local admissibility checks, not a complete global physical camera proof.

## 2. Residuals and association alternatives

For frozen edge correspondence i, normal n_i and image edge q_i,

`e_i(p)=n_i^T [projection(T(p) inflate(X_i,sgn_i,eta))-q_i]`.

Use inherited edge-type reliability and a Cauchy-style weight frozen at the association point. Each capture is normalized by its retained row count and the number of fitting captures. Thus captures have roughly equal residual weight rather than every accumulated scan being treated as independent evidence. These weights are not experimentally calibrated sensor-noise variances.

Correspondences use distance gates 6, 9 and 12 px and a 30° orientation gate. Each variant has its own rows and fixed weights. A disappearing projection receives a finite penalty of at least max(20,2 gate) px before weighting; it cannot reduce loss to zero. Central finite differences hold the rows fixed. Reassociation occurs between the two default outer optimization iterations.

## 3. Scaled measurement information

Let `J_v = d e_weighted / d p` for training variant v. Central differences use physical step `1e-4 s_j`; rotations use the retraction above. Form `A_v=J_v S`, where S is diagonal with increments:

- 1° for each rotation; 1 cm for each translation.
- 1% of reference fx/fy, 1 px for cx/cy, 0.01 for k1/k2.
- 0.1° for eta.

These are declared coordinate scales, not uncertainty estimates. No prior rows enter rank or conditional information. Retain singular values above `max(0.02,1e-5 sigma_max)` for support diagnostics.

For a nuisance/rival matrix B, compute the thin orthogonal residualization `C=A-Q_B(Q_B^T A)`. This equals `(I-B B^+) A` without allocating an m×m projector. Its information is the generalized Schur complement `C^T C`. Duplicate or zero nuisance columns are handled by SVD.

## 4. Estimation support versus attribution

Hypotheses are KEEP, R, T, I, RT, RI, TI and RTI. R is rotation, T translation, I the six estimated camera parameters; eta is allowed as nuisance in every fit. KEEP means no calibration-group change, while still fitting the nuisance.

For **estimating** hypothesis h, residualize its allowed calibration columns against eta only. For **attributing** group g, residualize g against all other calibration columns plus eta. Shared effects can be estimable under a frozen rival model while lacking unique evidence for a physical cause.

For each variant's supported right basis V_v, set `P_v=V_v V_v^T`. Propose eigenvectors of `mean(P_v)` with eigenvalue >=0.98. Grow a basis B only while BOTH hold for every variant:

`lambda_min(B^T P_v B)>=0.98`, and `sigma_min(C_v B)>0.02`.

Every-variant verification prevents an average projector from hiding a completely unsupported variant. Different variants are compared in common parameter coordinates; incompatible residual rows are never treated as independent repeated observations.

At the final candidate, recompute Jacobians, support and attribution. For the actual scaled change d, report `||B^T d||²/||d||²`. A changed group's attribution requires nonzero change and at least 0.98 of that direction's energy in its stable unique subspace. Merely finding one observable axis in a group is insufficient. The final calibration change must also meet this support check in the hypothesis basis. These remain local-linear diagnostics; they do not prove nonlinear global identifiability or the absence of unmodeled faults.

## 5. Reduced optimization

Embed the supported hypothesis basis in thirteen coordinates, with zero rows for forbidden groups; append supported nuisance directions. Solve

`min_z 0.5 || e_weighted(retract(p_start,S B z)) ||²`, `-3<=z_j<=3`.

Use SciPy least_squares, up to 50 evaluations per reassociation iteration, and enforce camera validity. Frozen groups remain unchanged. Step bounds are in reduced coordinates; physical validity is checked separately. Since weights are frozen, the inner objective is linear-loss weighted least squares, not a fresh robust M-estimator at every trial point. Two reassociation iterations are the default.

A failed/nonfinite solve, fewer than 30 associations in any variant or invalid model yields a failed candidate. Failed folds are retained as failures in comparison; the decision policy never drops them to manufacture a gain.

## 6. Recorded-capture selection

Within each fitting fold only, compute per-capture Jacobians at the reference. For every trial selected set, stack raw rows before profiling the shared nuisance. Independently profiling each capture would incorrectly grant a different nuisance to each capture.

For every directed R/T/I pair and association variant, profile the target against the rival plus nuisance. The primary greedy score is the minimum squared smallest singular value across these contrasts, with zero for deficient target rank. Tie-break using the worst-variant `sum log(1+sigma_j²)` of nuisance-profiled joint calibration information, then its minimum information. This is a pairwise selection proxy; attribution later profiles **all** rivals jointly. Selection is therefore not a guarantee of full fault isolability. All candidate groups are included, rather than claiming an implemented adaptive surviving-rival acquisition strategy.

Default fitting budget is four captures. Alternatives are all, seeded random, feature-count, regularized D proxy and E proxy. Selection scores cost extra preprocessing; report runtime rather than treating them as free. No live capture acquisition occurs.

## 7. Comparison loss and partitions

For each test capture, fix support to the same extracted LiDAR edge points visible under the reference. For every candidate, query the nearest image edge **without** the training association gate. Invalid/lost projections receive 30 px; distances are clipped at 30 px. Compute

`L_c = mean_i min(distance_i,30)² / 30²`.

Also report capped edge RMSE, median edge distance, share within 2 px, valid projection coverage and point count. This is a nearest-edge geometric proxy; no known point correspondence or true reprojection error is available. The benchmark additionally pools squared distances by point count for its displayed RMSE, whereas the decision averages capture losses equally.

With at least seven captures, reserve `max(2,ceil(0.3 N))` captures using seed 7; remaining captures undergo leave-one-capture-out model comparison. Three untouched outer captures are required for acceptance, so some small partitions cannot accept an update. With fewer captures, report comparison only and do not claim independent final validation.

Use paired capture-bootstrap mean-loss differences (500 resamples, descriptive 2.5/97.5 percentiles). Require at least four comparison captures and >=1% practical normalized squared-loss gain. If the best model is not separated from KEEP, abstain. Preserve models whose difference interval includes zero as an ambiguity set. Non-nested tied explanations cause abstention; nested ties prefer fewer supported dimensions. These heuristics are not multiplicity-corrected hypothesis tests, calibrated fault posteriors or selection-adjusted confidence intervals.

Refit only on selected training captures. Accept a candidate only if comparison supports it, final directional attribution/support pass, optimization succeeds, outer mean loss improves >=1%, at least two-thirds of outer captures improve, every outer coverage is >=0.9, and conditional uncertainty has adequate rank. Never refit on outer captures after seeing their scores.

## 8. Conditional uncertainty

For final reduced Jacobian `A=J S B`, let `s_c=sum_(i in capture c) A_i^T r_i`. Compute a centered capture-cluster sandwich

`Cov_z=(A^T A)^-1 [G/(G-1) sum_c (s_c-mean_s)(s_c-mean_s)^T] (A^T A)^-1`.

Inversion uses the already rank-checked thin SVD of A rather than silently truncating its squared information spectrum again. Map back with S B. Report nullspace basis separately. A scalar coordinate receives a standard deviation only if its entire coordinate axis lies in the supported subspace. Otherwise its uncertainty is unknown, not zero.

Require at least four clusters, G greater than reduced dimension, full reduced Jacobian rank and full covariance rank. Four selected captures often cannot support uncertainty for a large joint update; this conservative default can therefore prevent acceptance. Increasing a budget is an experimental design decision, not evidence that static captures become independent. No calibrated coverage is claimed; same-session static captures can remain dependent.

## 9. Outputs, failures and cost

`AssessmentResult` provides status, selected allowed-change model, fully supported scalar coordinates, unobservable directions, accepted parameter updates, conditional uncertainty, validation, action, output calibration and diagnostics. Rejected runs output an exact deep copy of the input reference and zero accepted updates; proposed values/deltas remain explicitly under candidate diagnostics. JSON uses null for unavailable/nonfinite quantities. New output folders prevent overwriting an assessment; no hardware writes occur.

Thin SVD costs O(m d²+d³), d<=13. Central Jacobians require 2d residual evaluations. With C captures, H hypotheses, V variants and K iterations, fitting is roughly O(C H K V) Jacobian/association work; greedy selection adds trial-subset SVDs and currently recomputes per-fold capture Jacobians. There is no claim of realtime performance.

Runs are sequential CPU work with process-local BLAS/OpenCV thread caps. Windows memory checks stop at boundaries if free physical memory falls below 4 GiB or the Python process exceeds a 2 GiB soft budget. These are soft checks, not kernel-crash prevention or a hard allocation limit. No drivers, services or system settings are changed.

## 10. Initial and legacy workflows

`strategy='legacy'` dispatches the untouched cloned maintenance workflow. `legacy_optimizer` uses its frozen refine routine inside the common new evaluation protocol and is explicitly distinguished from strict legacy behavior. Research projection/domain checks apply to that comparator.

`calibrate_from_scratch` preserves the existing targetless coarse initializer and produces an initial candidate, without diagnosing a historical fault. All captures enter initialization; later refinement scores cannot independently validate it. Those maintenance diagnostics are saved separately, and their scalar support/uncertainty are not relabeled as initial-estimator properties. Initial uncertainty is `UNVALIDATED_INITIALIZATION`, with nullspace unreported rather than falsely zero. The complete three-capture execution and watchdog measurements are in VERIFICATION_RESULTS.md.

## Experimental extension: fault diagnostics v2

The held-out loss above is affected by edge density. Over a 4 px offset it changes by 5–15 % in a
scene-dependent direction, and 75–105 % of that change is reproduced by displaced copies of the same image. The
experimental layer in [FAULT_DIAGNOSTICS_V2.md](FAULT_DIAGNOSTICS_V2.md) therefore keeps every fit and fold of
this method and re-scores them:

- with decoy-referenced edge and intensity contrasts;
- with an explicit chance-predicted counterfactual;
- with gating on evidence quality and a replication rule;
- with parsimony-based ambiguity sets;
- with a clipped-CUSUM persistence monitor over capture time.

It does not replace the production decision described here.
