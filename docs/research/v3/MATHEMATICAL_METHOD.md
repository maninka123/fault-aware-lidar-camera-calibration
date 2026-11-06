# V3 geometry-conditioned fault signatures

This is an experimental local diagnostic model. Its analytic derivatives and known-answer fixtures verify mathematics and software; they do not establish physical fault-identification accuracy. Nuisance projection, principal angles, matched-subspace distances and selective optimization are established methods. The candidate contribution is their sensor-specific use to explain an actual proposed change and the observation geometry required to reject competing explanations. See [novelty comparison](NOVELTY_COMPARISON.md), [protocol](PREREGISTRATION_V3.md) and [experimental results](EXPERIMENTAL_RESULTS.md).

## 1. Coordinates and the existing sensor model

The implementation reuses the thirteen parameters of the research backend:

\[
p=(\omega_x,\omega_y,\omega_z,t_x,t_y,t_z,f_x,f_y,c_x,c_y,k_1,k_2,\eta).
\]

The mounted rotation is a fixed matrix \(R_0\), and \(R=\exp([\omega]_\times)R_0\). A depth-edge return with signed side \(s_i\) is adjusted by the existing beam-inflation nuisance:

\[
\bar X_i=R_z(s_i\eta)X_i,\qquad P_i=R\bar X_i+t.
\]

For crease and intensity edges the existing extractor normally sets \(s_i=0\). \(\eta\) models the repository's signed azimuth displacement; it is not a general model of LiDAR uncertainty or temporal misalignment.

The retraction is \(R' =\exp([\delta\theta]_\times)R\), \(t'=t+\delta t\). This rotates the rotated LiDAR return, **not** the additive translation. Thus

\[
\delta P_i=-[P_i-t]_\times\delta\theta+\delta t
+R\{s_i e_z\mathbin{\times}\bar X_i\}\delta\eta.
\]

Using \(-[P_i]_\times\) here would implement a different SE(3) retraction and is incorrect for the current optimizer. Tests include nonzero translation and nonzero current rotation offset.

The camera uses the OpenCV equidistant polynomial with fixed \(k_3,k_4\). Write

\[
q=(a,b)^T=(P_x/P_z,P_y/P_z)^T,\quad r=\|q\|,\quad\theta=\arctan r,
\]

\[
g(\theta)=\theta+k_1\theta^3+k_2\theta^5+k_3\theta^7+k_4\theta^9,
\quad h(r)=g(\arctan r)/r,
\]

\[
u=\operatorname{diag}(f_x,f_y)h(r)q+(c_x,c_y)^T.
\]

Only front-camera points \(P_z>0.2\), within the declared angular domain and the image/circle masks, are valid. These limits are inherited unchanged. The method does not claim support for an arbitrary camera model, a full sphere or a different beam pattern. Missing/zero/nonfinite LiDAR returns are invalid. Geometry functions return finite zero placeholders plus an authoritative validity mask; those placeholders must never enter an information matrix as observations.

## 2. Analytic fisheye projection derivatives

Let \(F=\operatorname{diag}(f_x,f_y)\), and

\[
Q=\frac{\partial q}{\partial P}=\frac1{P_z}
\begin{bmatrix}1&0&-a\\0&1&-b\end{bmatrix}.
\]

For \(r>0\),

\[
B=\frac{\partial(hq)}{\partial q}=hI+\beta qq^T,
\qquad
\beta=\frac{g'(\theta)r/(1+r^2)-g(\theta)}{r^3},
\]

\[
g'(\theta)=1+3k_1\theta^2+5k_2\theta^4+7k_3\theta^6+9k_4\theta^8.
\]

Then \(G=FBQ=\partial u/\partial P\), and the geometric columns are

\[
J_R=-G[P-t]_\times,\qquad J_T=G,\qquad
J_\eta=GR(s_i e_z\mathbin{\times}\bar X_i).
\]

The intrinsic columns, in their actual pixel/coefficient units, are

\[
J_{f_x}=(ha,0)^T,\quad J_{f_y}=(0,hb)^T,
\quad J_{c_x}=(1,0)^T,\quad J_{c_y}=(0,1)^T,
\]

\[
J_{k_j}=Fq\frac{\theta^{2j+1}}r,\qquad j=1,2.
\]

The fixed \(k_3,k_4\) still affect \(G\); omitting them from the projection derivative would be wrong even though the optimizer does not estimate them.

At the optical axis, \(h\to1\), \(B\to I\), and the distortion columns vanish. For numerical stability at small \(r\), use

\[
h=1+(k_1-1/3)r^2+(1/5-k_1+k_2)r^4+O(r^6),
\]

\[
\beta=2(k_1-1/3)+4(1/5-k_1+k_2)r^2+O(r^4).
\]

The code switches to this series below \(r=10^{-4}\). All thirteen columns are compared against independent central differences of the existing nonlinear projection and SO(3) retraction, including a nonidentity \(R_0\), a nonzero rotation offset and a nonzero beam nuisance.

## 3. What geometry does and does not distinguish

The central projection is homogeneous: \(\pi(\alpha P)=\pi(P)\) for \(\alpha>0\), hence \(G(\alpha P)=G(P)/\alpha\). Translation sensitivity at a fixed camera bearing therefore scales inversely with range. The pinhole \(1/z\) observation is a special case; the angular factors here are those of the fisheye derivative above. With \(t=0\), rotation, intrinsic and beam sensitivities for the same LiDAR ray are independent of its range. With nonzero \(t\), \(J_R=-G[P-t]_\times\) includes a translation-to-range term; unconditional depth invariance should not be claimed.

Depth variation can separate translation from depth-invariant shifts, but depth variation alone cannot resolve a rotation/intrinsic alias. Conversely, many nearby points at the same depth may provide a high feature count with almost no new fault-discriminating geometry. Spatial and depth bins are descriptive diagnostics, not independent statistical samples.

At the optical axis and zero translation,

\[
J_R=\begin{bmatrix}0&f_x&0\\-f_y&0&0\end{bmatrix},
\quad
J_T=\begin{bmatrix}f_x/z&0&0\\0&f_y/z&0\end{bmatrix}.
\]

Thus small yaw and horizontal principal-point shift are locally aliased, as are pitch and vertical principal-point shift. The corresponding translation aliases depend on depth. An axial rotation produces no displacement on the axis, and focal/distortion changes vanish there.

There is a stronger exact counterexample to a generic recommendation of "more field of view." For an undistorted equidistant camera, zero translation and rays on the horizontal great circle \((x,0,z)\), \(u=f_x\arctan(x/z)+c_x\). A local camera-y rotation adds the same angular shift to each bearing, so

\[
J_{\theta_y}=f_xJ_{c_x}
\]

for **all** those rays, including wide horizontal coverage and varied depth. The implementation verifies this exact alias numerically. Two-dimensional off-plane bearing coverage introduces cross-coordinate and bearing-dependent terms that can separate the effects; its usefulness must still be checked against the actual residual normals, distortion, visibility and noise. A horizontal-edge point-to-line residual may discard precisely the displacement component that full 2D correspondences would retain.

These facts motivate computing the actual capture signatures instead of a rule that distinct physical parameter names imply diagnosability.

## 4. From pixels to residual signatures

For a frozen association with image target \(v_i\) and normal \(n_i\),

\[
e_i=n_i^T(\pi(P_i)-v_i),\qquad
J_i=n_i^T[J_R\;J_T\;J_I\;J_\eta].
\]

These are signed pixel residuals. They are conditional on the association: nearest-edge reassociation is nonsmooth, can associate to a different scene feature and can invalidate the local explanation. A visibility boundary is not differentiated. Invalid candidate projections are penalized by the existing evaluation code and do not become zero-loss observations.

`residual_signature` defaults to raw pixel residuals. An explicit `weighted=True` option reproduces the existing robust/capture weights, but those weights must not be interpreted as a measured covariance. The V3 noise normalization is a separate declared model.

Given positive physical coordinate scales \(S=\operatorname{diag}(s_j)\) from the existing `parameter_scales`, and a declared measurement covariance \(\Sigma=LL^T\), define

\[
A=L^{-1}JS,\qquad y=L^{-1}e.
\]

The same whitening is applied to calibration columns, nuisance columns and observations. Independent equal pixel noise is a simple declared approximation, not an empirical uncertainty calibration. A supplied full positive-definite covariance can represent correlated observations. Singular covariances are rejected explicitly rather than silently discarding deterministic constraints. Consistent distance-unit changes divide translation columns and multiply their scales, leaving \(A\) unchanged on the same valid support. Input geometry uses canonical metres; the loader converts millimetre clouds to metres. The inherited \(P_z>0.2\) visibility cutoff is in metres, so directly rescaling input coordinates without also transforming the domain is not a globally equivalent camera model. Parameter scales are physical increments, not prior standard deviations or fault probabilities.

## 5. Rival explanations and an actual-effect distance

Reuse the existing thin SVD nuisance projection: \(P_B^\perp Z=Z-Q_BQ_B^TZ\). No dense observation-space projector is formed. Shared nuisance columns are profiled **after** stacking captures; profiling them separately would give every capture its own nuisance and solve a different problem.

The hypotheses are KEEP, R, T, I, RT, RI, TI and RTI, with the existing group definitions. For a proposed normalized effect \(d\), define the directed rival distance

\[
D(d,H)=\min_{b,\nu}\|Ad-A_Hb-A_N\nu\|_2,
\quad
d_{\rm rms}(d,H)=D(d,H)/\sqrt m.
\]

The optimizer-free linear solution is a least-squares rival refit, equivalently the norm of the nuisance/rival-residualized signal. Report its energy, RMS, rival coefficients and unexplained measurement vector. A rival fit is unbounded: if only an implausibly large rival can explain the effect, the current conservative rule still retains that rival and reports its coefficient. This avoids an undocumented prior or regularizer that manufactures separation, but can increase abstention.

Principal angles between nuisance-profiled group column spaces describe whether **some** directions overlap. A small minimum angle alone does not establish that the observed effect lies in an alias, and a singular-value threshold alone does not diagnose a fault. The directed distance instead asks whether the **actual proposed change** can be explained by each rival at a declared noise-normalized measurement resolution.

The separation and detection tolerances are **dimensionless whitened RMS values**, denoted \(\gamma_{\rm sep}\) and \(\gamma_{\rm det}\). Whitening has already divided out the declared measurement scale; the tolerance must not be divided by `pixel_sigma` a second time. If the RMS distance is below \(\gamma_{\rm sep}\), retain the rival as geometrically consistent. A larger distance permits rejection only under the local projection/correspondence/noise assumptions. For independent equal noise with \(\sigma_{\rm px}=1\) pixel, a whitened RMS of 0.35 happens to equal 0.35 pixels. At \(\sigma_{\rm px}=0.15\) pixel it corresponds to 0.0525 pixels. For heteroscedastic or correlated covariance there is no single physical-pixel equivalent. These constants are descriptive noise-relative resolution choices, not statistical significance levels.

Under a consistent residual-unit conversion \(J'=bJ\), \(e'=be\), \(\Sigma'=b^2\Sigma\), the whitened information, signal and decisions are unchanged. The fallback scalar scale changes as \(\sigma'_{\rm px}=b\sigma_{\rm px}\) only when it supplies the covariance; when an explicit covariance is provided, that fallback scale does not affect whitening or decision thresholds. Numerical regressions test this invariance at an attribution/ambiguity boundary for scalar fallback, diagonal covariance and full correlated covariance. RMS deliberately does not reward repeated identical rows as independent samples; it is a descriptive effect size, not a chi-square statistic, likelihood ratio, p-value or a calibrated rejection guarantee.

Nested models require care. RTI can reproduce any R-only effect, so geometric consistency cannot reject the larger model. The policy reports minimal explanations among consistent sets as an explicit parsimony convention. This does **not** prove that unneeded groups did not change, nor rule out changes in unobservable directions. Broad ambiguity must remain broad rather than being converted into confidence.

## 6. Detection, diagnosis, estimation and validation

Recorded data retain the existing training, comparison and reserved-outer-capture separation. The default detection statistic is the V2 **chance-corrected oriented edge contrast**, with the existing quality gating and descriptive replication rule. The raw oriented matched-share variant is retained as an explicit ablation; it is not the V3 default. The V2 intensity-agreement requirement is disabled because its documented ablation was harmful. Intensity remains descriptive in the shared baseline outputs and is checked for contradiction in the conservative outer update check. No independent contribution from correlated edge/intensity statistics is assumed.

Let \(\mathcal P\) be the edge-supported hypothesis set and let \(\mathcal C\) be the V2-style minimal tied evidence explanations. The best edge-evidence hypothesis is the member of \(\mathcal P\) with largest median held-out contrast gain. This hypothesis can be a compound model even when the tied minimal explanation is smaller. V3 reads its existing training-only fold fits; it performs no new nonlinear optimization during this comparison-side diagnosis.

For comparison capture \(c\), freeze oriented associations at that fold's fitted calibration, then evaluate their raw pixel derivative \(J_c\) at the current reference. With scene quality enabled, retain the existing depth/crease feature types and exclude intensity-only feature rows; the method does not introduce an occlusion oracle or a newly verified edge extractor. Captures must meet the declared reliable-row requirement, and failures are recorded. The reference-domain Jacobians are stacked before any shared rival/nuisance refit:

\[
A=\operatorname{stack}_c(J_cS/\sigma_{\rm px}).
\]

Fold effects use the actual SO(3) correction \(\delta\theta_c=\log(R_cR_{\rm current}^{-1})\), additive differences for the remaining coordinates, and the same physical normalization \(S^{-1}\). A coordinatewise median would need not belong to any fold's supported subspace. Instead the explanatory representative is an **actual medoid fold effect**:

\[
d_*=d_{j_*},\qquad j_*=\arg\min_j\sum_k\|d_j-d_k\|_2.
\]

The representative alone never decides rival rejection. For each rival, compute the distance for **every actual fold effect on the same stacked geometry**. The rival remains geometrically compatible if

\[
\min_c d_{\rm rms}(d_c,H)\leq \gamma_{\rm sep}.
\]

Thus every fold effect must reject a rival before the geometric policy can reject it. This is a conservative finite-fold stability check, not a probability bound. Large fold disagreement can expand ambiguity; a favorable representative cannot conceal an aliased fold. Fold effects, their maximum normalized distance from the representative and the per-rival distances are reported.

Combine geometric aliases with \(\mathcal C\), then propose minimal explanations. A newly admitted subset alias must not erase a preserved supported compound explanation: retain the compound as well when a new smaller alias would replace it. Likewise an edge-unsupported minimal alias cannot become a supported exact attribution. Unique attribution requires one remaining explanation that is itself in \(\mathcal P\), adequate geometric capture support, and

\[
\min_c d_{\rm rms}(d_c,\mathrm{KEEP})>\gamma_{\rm det}.
\]

Otherwise preserve `DRIFT_AMBIGUOUS`; if nuisance-only KEEP can explain an effect within tolerance, report that compatibility explicitly. The default fallback noise scale is \(\sigma_{\rm px}=1\) pixel, while the dimensionless practical tolerances are \(\gamma_{\rm sep}=0.35\) and \(\gamma_{\rm det}=0.25\), with at least four geometric captures and thirty valid rows per admitted capture. These are declared development constants, not measured noise parameters or calibrated error probabilities. All-direction observability and conditional information remain separate descriptive outputs from the existing observability implementation.

Those geometric conditions are **necessary, not sufficient**, for a unique recorded-data diagnosis. The final recorded policy is a conservative attribution veto: retain a unique label only when the unchanged edge-evidence policy already returns `DRIFT_SUPPORTED` for the **same** hypothesis and the geometric report independently remains unique with actual-fold support. Geometry can add aliases or veto that label; it cannot promote an edge-evidence `DRIFT_AMBIGUOUS` result into unique physical attribution, replace its label with another group, or manufacture an alarm from a non-alarm baseline state. When attribution is withheld, preserve the union of the baseline and geometric explanations. The original baseline is the default V2-style chance-corrected edge policy with intensity agreement disabled, not the original unchanged V2 two-cue result.

This restriction followed a failed permissive development variant: an apparently unique local fitted signature did not reliably justify physical attribution from unknown nearest-edge associations. Its results remain a separate failed experiment. The veto rule deliberately gives up the ability to increase uniquely attributed recorded trials relative to that baseline; any value must come from fewer incorrect unique labels, better explained ambiguity or more useful observation recommendations. On a fixed set of inputs it cannot introduce a new differently labeled unique attribution beyond the baseline; that logical relationship is not an operational error-rate guarantee or proof that a retained baseline attribution is true. The separate known-correspondence numerical API continues to study fault identification under explicit geometric-model assumptions and does not apply this unknown-correspondence veto.

Depth and image-region explanations partition the representative's globally rival-residualized measurement vector. Depth cuts are pooled tertiles; image regions are four quadrants around the current principal point. Each bin reports the RMS of its contribution after **one global** rival/nuisance refit. The rival is not refitted separately within bins. These bin values explain where the representative separation occurs; they are not new independent tests or the every-fold attribution criterion.

The known-correspondence numerical API separately fits signed residual changes under the local model. It requires thirteen physical Jacobian columns and validates supplied capture IDs. Declared capture-block runs require the configured minimum number of blocks and use leave-one-capture-out prediction errors. Omitting capture IDs deliberately selects a clearly labeled same-data numerical fit, not an independent validation. Full-covariance whitening is performed separately within train and test partitions to avoid leaking held-out observations through a joint whitening transform. This uses marginal generalized least squares within each partition; correlated training/test noise and reused folds remain dependent, so cross-capture covariance does not make these descriptive scores independent evidence. Median whitened prediction-error improvement must exceed \(\gamma_{\rm det}^2\), and mean prediction-error ties use \(\gamma_{\rm sep}^2\). Prediction-error ties and effect aliases both preserve ambiguity; an unsupported alias cannot gain a unique supported diagnosis merely through parsimony.

An observable subspace supports estimation conditional on the model; unique physical attribution requires rejecting rivals as well. The existing selective optimizer already constrains updates to a supported parameter basis. V3 does not introduce a second unconstrained optimizer. When batch diagnosis is uniquely supported, refit that hypothesis on training captures only, then recheck the **actual final fitted correction**, because its direction can differ from the fold effects. In this dedicated geometric recheck, the actual candidate parameter vector replaces the parameters in every fold bank: if the highest edge-score bank is RTI but the minimal diagnosed hypothesis is R, selecting the RTI bank still audits the final R candidate, not a stale RTI correction. Edge evidence scores and the reserved outer partition remain unchanged. A failed or ambiguous candidate geometry check withholds update validation. This remains a local reference-domain derivative check for a candidate obtained by nonlinear optimization; it is not an exact nonlinear identifiability test or a demonstrated bound on linearization error.

A drift state is not an update authorization. A candidate requires a successful constrained fit, supported update directions, a passing actual-candidate geometry check, `CONDITIONAL_ONLY` cluster uncertainty, and at least three disjoint reserved validation captures. The outer evidence must confirm edge gain, retain the declared coverage and show no intensity contradiction before the action can become `UPDATE_CANDIDATE_VALIDATED`. This is an offline review candidate and never permits a hardware write. The inherited cluster-rank requirements can prevent acceptance at the default four-capture fitting budget, particularly for large joint parameter spaces; zero false updates alone does not demonstrate useful update acceptance. An unconfirmed reference, nuisance-like improvement, missing geometry, missing validation or insufficient captures receives its corresponding explicit abstention state. Precise implemented state semantics and measured limitations are reported in the implementation/readiness documents.

## 7. Observation selection and temporal reuse

A recorded candidate capture is useful when its stacked signature increases the unexplained component for the currently unresolved rival pair. For a proposed subset \(\mathcal S\), let \(A_{\mathcal S}\) include any initial evidence and its candidate rows. For fixed, training-derived nonzero effects \(d_i\), the implemented greedy design uses

\[
U(\mathcal S)=\min_{(i,j)\in\mathcal Q}
\left\{D_{A_{\mathcal S}}(d_i,H_j)^2,
D_{A_{\mathcal S}}(d_j,H_i)^2\right\}.
\]

At each step select the eligible capture maximizing \((U(\mathcal S\cup\{c\})-U(\mathcal S))/\operatorname{cost}(c)\). A nuisance-profiled \(\sum\log(1+\sigma_j^2)\) calibration-information proxy breaks ties. Zero effects and exactly nested rivals honestly give zero primary separation. Total squared separation, rather than RMS, lets independent additional measurement information improve design utility; it does not justify treating correlated repeated rows as independent. This is an established model-discrimination/T-optimal design construction adapted to surviving calibration effects, not a new general experiment-design theorem.

The current selector accepts block-diagonal covariance **between** captures, with any within-capture whitening already applied. Arbitrary cross-capture correlation needs raw subset-specific covariance and fresh whitening for every candidate subset, which this API does not implement. Jointly whitening an entire candidate pool and later selecting transformed row blocks is invalid because it mixes information from unselected captures. The simpler recorded runner uses its explicitly declared common pixel scale.

The ambiguity report can rank already observed comparison captures using rival effect refits of the representative. That ranking recommends a subsequent training design; it does not replace the default fitter's V2 selection or enter the current reserved outer validation. It is conditional on those estimated effects, not a forecast for an unmeasured scene or a guarantee of fewer required captures. The lower-level selector also accepts explicitly supplied training-derived effects, quality flags, acquisition costs, initial evidence and a permitted training-ID pool.

Any greedy maximin selection is a local finite-pool heuristic. It needs matched random, feature-count, D/E and existing V2-contrast baselines, matched capture/fit budgets and runtime measurement. If pair directions are taken from an estimated effect, selection is conditional on that estimate; candidate quality and acquisition costs must be declared. Image/depth bin scores alone do not prove that a proposed viewpoint or accumulation window will solve the ambiguity. Longer accumulation can also increase correlation and motion artifacts.

V3 reuses the V2 clipped sequential detector rather than inventing another CUSUM. The recorded API returns the unchanged V2 persistence output; geometry-based diagnosis does not silently replace its signal or thresholds. A separate adapter can supply a quality-conditioned signal, but that remains an explicitly separate experiment. No historical reference is known nominal merely because it is first in time. The short, static, dependent recordings do not establish operational false-alarm control, average run length or robustness to real timing failures. Any unchanged temporal ablation is identified as unchanged rather than claimed as a new contribution.


## 8. Correspondence-aware signed diagnosis (improved V3)

Sections 1 to 7 take the pairing of LiDAR points with image edges as given. On recorded data it is not: see
[ROOT_CAUSE_ANALYSIS.md](ROOT_CAUSE_ANALYSIS.md). This section states what is added, what is argued and what was only observed.

### 8.1 Signed residual, observation model and what a wrong pair does

For LiDAR point X_i paired with image edge point q_i of unit normal n_i, the signed residual at calibration p is

    r_i(p) = n_i^T (pi(p; X_i) - q_i).

If p* is the true calibration and the pair is correct, r_i(p*) = eps_i (matching noise). At p = p* "plus" delta (a fault delta, left retraction as in
section 1) the local model is r_i(p) = n_i^T J_i delta + eps_i, with J_i the pixel Jacobian of section 2. Writing a_i = n_i^T J_i diag(s) (s the physical
scales) and y_i = -r_i, the correction is the least-squares solution of y = A b, which is exactly the regression `infer_signatures` fits (cross-validated by
capture, with nuisance shared and rival refits). A pair that is wrong adds w_i = n_i^T (q_i - q_i^true) to r_i, so

    b_hat = b* + (A^T W A)^+ A^T W w.

The bias term does not shrink with more rows or more captures of the same static scene (w_i is repeatable), and it is a smooth field because
neighbouring points share the same wrong neighbouring edge. That is why false alarms grow with the number of rows for nearest-edge pairing, and why
V3's correct signatures attribute the wrong group confidently: A is right, y is wrong. The measured share of wrong pairs is 38 to 43 % (development pair).

### 8.2 Responsibility, distinct edge lines, visibility, balance

For point i with candidate edge elements k inside the gate, c_ik = d_ik^2 / (2 sigma^2) + a_ik^2 / (2 sigma_a^2) (normal distance d, orientation angle a), and an
outlier cost c_out. The posterior responsibility (a Gaussian-mixture E-step, not a calibrated probability)

    r_ik = exp(-c_ik) / (sum over DISTINCT k' of exp(-c_ik') + exp(-c_out)).

Two image-edge samples of one physical edge have the same normal distance and must not compete; candidates are therefore reduced to distinct normal-distance
classes (separation 3 px) before normalising. Without this the true edge's responsibility is divided among its own samples (a defect found and fixed during
this work). Row variance is sigma_0^2 / max(w_i, 0.05) with w_i = r_ik times a cell/range balancing factor. Visibility is a z-buffer test: a point is
dropped if a nearer LiDAR return lies within 2 px. Balancing caps the total weight of an image-cell x range-bin at 1.5 times the median cell. All three are
established ingredients (mixture correspondence models, z-buffering, stratified weighting); see NOVELTY_COMPARISON.md.

### 8.3 Unique-pair rule (negative result)

A pair is kept only if no other compatible edge line (normal distance differing by more than 3 px) lies within a radius R, so that the pairing is the same
for every calibration error up to R. This raises pair identity (64 to 71 %) but removes most rows and did not improve the diagnosis (ROOT_CAUSE_ANALYSIS.md).

### 8.4 Why pairing at the estimate is circular (negative result)

Alternating the pairing and the calibration (annealed EM-ICP, `joint_estimation.em_refine`) yields pairs for which r_i(p_hat) is small by construction.
Evaluating the same pairs at the calibration under diagnosis p gives r_i(p) = -a_i (p_hat - p) + eps_i, so the signed inference explains p_hat - p,
not delta. p_hat - p is non-zero whenever the optimum of the pairing objective is not the truth (the objective is biased: its value at the best fit is lower
than at the anchor in 10 of 14 development conditions), so a correct calibration is flagged as drifted. This is an argument for the observed 3 of 3 false
alarms; it is not a proof that no estimator-based pairing can work. A truncated-SVD step was needed even to keep the estimate stable: directions are
moved only if sigma_s / s_k <= tau (implied standard deviation under independent rows, which is optimistic for static captures), with tau = 1 normalized
unit.

### 8.5 Recovery and acceptance contract (offline)

After an alarm, the correction over the groups in the minimal ambiguity set (or the unique hypothesis) plus the beam nuisance is the truncated-SVD
least-squares solution of section 8.1 on whitened rows. An update is **accepted** only for a unique diagnosis whose training-capture correction improves
the V2 decoy-referenced edge contrast by more than 0.01 on every reserved capture. Hardware writes are never authorized. The recovery figure reported is the
median projection error of the captures' LiDAR points against the anchor before and after, a perturbation-recovery proxy, not physical error.

### 8.6 What is not derived

No claim of calibrated covariance, false-alarm probability or acceptance risk. Rows within a capture and captures within a recording are dependent; whitening
by the declared variance treats them as independent. Unbounded rival coefficients remain (Part C of the V3.1 brief): no physically justified bound on a
fault exists in the data, so none was imposed.
