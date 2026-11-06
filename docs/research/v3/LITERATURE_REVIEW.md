# V3 literature review and implementation consequences

Review date: **6 November 2026**. This is a critical methodology review, not a certification of novelty. Paper results below are not results of this repository. No external implementation was copied into V3.

## Access and scope

The mandatory papers were checked against primary sources on the review date. Methods and relevant supplements were inspected for the accessible papers; this does not mean every cited reference was independently reviewed. Cached preprints are in the external `../research_references/paper_cache/` directory. This review resolves the V2 access gap for the **full OCaMo author manuscript**, located through the authors' institutional repository. Shen et al. remains abstract-only, as does the additional active-FDI sensor-selection comparison. UniCalib's official abstract was accessible; its PDF request returned 403. Unavailable equations are not inferred from abstracts.

## Mandatory calibration and monitoring papers

### OCaMo / LTO — Moravec and Šára, T-RO 2024

[Author manuscript, DOI 10.1109/TRO.2023.3347130](https://dspace.cvut.cz/bitstream/handle/10467/113999/Moravec_Sara__Online_CameraLiDAR_Calibration_Monitoring_and_Rotational_Drift_Tracking__%282023%29_AAM_370622.pdf?isAllowed=y&sequence=-1), [author supplement](https://cmp.felk.cvut.cz/~moravj34/ocamo/), [code](https://github.com/moravecj/OCaMo).

**Access:** full manuscript methods III, learning V, limitations VII; supplement; Python kernel, monitoring and tracking code.

**Mathematics:** kernel correlation sums Gaussian proximity to image edges. OCaMo uses adaptive stochastic tracking and Gaussian tolerance indices; LTO combines local grid ranks with learned calibrated/decalibrated Beta densities. A learned frame classifier rejects unsuitable observations. The journal LTO covers extrinsics; the Python example restricts its grid to rotations.

**Requirements/limits:** known intrinsics, motion compensation and sensor-specific learned settings; poor illumination, distant/dense features and timing error can mislead monitoring. Frame rejection trades stability against response speed. The paper separates monitoring from applying updates.

**V3 consequence:** informative-frame selection and monitor/optimizer separation are already covered. Reuse their experimental questions, not probability thresholds or code. The remaining question is joint intrinsic/extrinsic *fault explanation* under measured ambiguity. Density bias in our backend is not automatically a measured failure of their implementation.

### MiCaDe — Sgaravatti et al., arXiv:2611.04912v1

[Full paper and appendices](https://arxiv.org/html/2611.04912v1), [repository](https://github.com/CarloSgaravatti/MiCaDe).

**Access:** full HTML methods 3–4, experiments 5, appendices A–C. Metadata verifies **3 November 2026**, not a forecast or mistaken identifier.

**Mathematics:** class-consistent Hungarian IoU matching of 3D/2D detector boxes yields geometric metrics. Fixed-size batches produce nine features; a nominal GMM supplies log likelihoods to a Lepage change-point model. Thresholds target nominal average run length under the calibration assumptions.

**Requirements/limits:** synchronized streams, compatible detectors, known intrinsics and nominal reference sequences. Non-independent observations weaken operational false-alarm interpretations. Scene transitions and sensor degradation receive explicit supplementary experiments; they must not be described as entirely untested. Detection does not itself estimate the changed calibration groups. The public checkout inspected here is README-only.

**V3 consequence:** sequential miscalibration detection and disturbance testing are established. Retain V2's existing temporal machinery unless the new signal wins a matched experiment; do not claim MiCaDe's ARL for our static-capture data.

### Koide et al. — ICRA 2023, arXiv:2302.05094v1

[Full method III](https://arxiv.org/html/2302.05094v1), [implementation](https://github.com/koide3/direct_visual_lidar_calibration).

**Access:** full HTML and local NID cost implementation.

**Mathematics:** cross-modal image matching initializes geometric registration; rotation RANSAC and reprojection refinement precede normalized information distance (NID) minimization. NID uses joint/marginal intensity entropies. Camera-view hidden-point removal alternates with registration. Generic projection permits several camera families, and accumulation supports nonrepetitive LiDAR.

**Requirements/limits:** supplied camera model/intrinsics, overlap, useful reflectivity–appearance statistics and suitable initialization. Successful NID alignment does not establish a fault-group label or a calibrated fault probability.

**V3 consequence:** intensity is a possible complementary cue, not a compulsory vote. Visibility-aware filtering and scan accumulation are existing calibration techniques. A longer Avia window only helps if it adds useful geometry without introducing motion/timing error. Compare any NID-inspired statistic with oriented edges; no reproduction of this complete toolbox is claimed.

### EdgeCalib — Li et al., reviewed arXiv:2310.16629v1

[Full preprint, method III](https://arxiv.org/html/2310.16629v1).

**Access:** full HTML methods, experiments and ablations; no verified official source checkout was available locally.

**Mathematics:** SAM mask contours suppress image texture. LiDAR edge weights combine spatial persistence with projection consistency across an aligned local map. A weighted edge-attraction objective estimates extrinsics.

**Requirements/limits:** known intrinsics, synchronization, useful local poses and cross-modal scene edges. Foreground preference at depth jumps is a heuristic visibility treatment, not proof that every selected edge is camera-visible. Projection consistency depends on the current pose, making it potentially circular as independent acceptance evidence.

**V3 consequence:** reliability, geometry edges and multiframe weighting are covered. Distinguish depth-discontinuity edges from depth-continuous creases and test each; adding SAM without a matched benefit would increase complexity and model dependencies. Report the preprint version rather than transferring its reported accuracy to this implementation.

### JointCalib — Yan et al., arXiv:2202.13708v3

[Full paper, method III-C](https://arxiv.org/html/2202.13708v3), [code](https://github.com/OpenCalib/JointCalib).

**Access:** full HTML and local reprojection/camera-calibrator source.

**Mathematics:** jointly optimize camera parameters and LiDAR–camera pose using checkerboard corners and circular holes in a designed target, with constraints linking board geometry and image observations.

**Requirements/limits:** a special target, measurable hole centres and multiple board observations. Its pinhole/radial model is not our equidistant fisheye model. Target constraints supply information unavailable from arbitrary natural edges.

**V3 consequence:** joint intrinsic/extrinsic estimation is established. It illustrates why independent intrinsic constraints can resolve compensation. It is useful as a labelled-target accuracy reference only when its required target data exist; it is not a runnable comparator on the present targetless captures.

## Closest mathematical antecedents

### Matched subspace detectors — Scharf and Friedlander, IEEE TSP 1994

[Full author paper, DOI 10.1109/78.301849](https://www.mssc.mu.edu/~daniel/mscs6960/spring2010/ScharfFriedlanderTSP94.pdf).

**Access:** full PDF, model/projection/GLRT sections III–VIII.

The model is a signal subspace plus deterministic interference and Gaussian noise. Orthogonal projection rejects interference; matched projected energy or an energy ratio produces the appropriate GLRT. Invariance and distributional assumptions underpin its optimality/threshold results. Whitening translates known correlated covariance into this geometry.

This directly covers nuisance projection, conditional subspace energy and much of the proposed fault-signature machinery. Unknown correspondences, robust data-dependent weights and nonlinear projection do not satisfy the ideal model automatically. V3 can use the geometry descriptively but cannot inherit its statistical guarantees. A principal-angle plot is an established diagnostic, not a new inference method.

### Optimal statistical fault detection with nuisance parameters — Fouladirad and Nikiforov, Automatica 2005

[Publisher introduction and abstract, DOI 10.1016/j.automatica.2005.02.004](https://www.sciencedirect.com/science/article/pii/S0005109805000713).

**Access:** publisher introduction/abstract; linked full course PDF timed out twice. Full proofs were **not** reviewed.

Unknown deterministic nuisance and stochastic noise are treated jointly; the stated result relates optimal detection to a GLRT on a parity vector. Fault isolation can treat rival faults as nuisance. This is close prior art to “project rivals away before attribution.” We do not assert applicability of the paper's theorem to our association-dependent residuals. V3 should explicitly report signals lost with nuisance rejection, not count nuisance invariance as new.

### Optimal discrimination designs — Dette and Titoff, Annals of Statistics 2009

[Full paper, arXiv:0908.1912](https://arxiv.org/pdf/0908.1912).

**Access:** full PDF, criterion/equivalence discussion sections 2–4 and experimental comparison 5.

Classical T-optimality maximizes the integrated squared discrepancy from a fixed mean response to a *refitted rival*:

\[
\Delta(\xi)=\inf_{\theta_j}\int[\eta_i(c;\theta_i)-\eta_j(c;\theta_j)]^2\,d\xi(c).
\]

This is already model-discrimination design. The paper connects it with conditional estimation criteria and shows that a discrimination-optimal design can be poor for estimating the larger model. It assumes declared response models and local parameter choices; it is not an automatic remedy for model misspecification.

**V3 consequence:** finite-effect rival-refit separation and capture selection are adaptations of T-optimality. Use a nonzero declared effect, refit a *common* rival across selected captures, retain estimation checks, and compare matched budgets. A per-capture refit allows different faults in every capture and changes the scientific question.

### Multiple and uncertain models — Dette, Melas and Guchenko, Annals of Statistics 2015

[Full methods, Bayesian T-optimal discriminating designs](https://arxiv.org/html/1412.2548).

**Access:** full HTML criterion and equivalence/optimization sections.

Weighted comparisons and averaging over parameter uncertainty extend T-optimal discrimination. The prior is part of the design specification, not evidence that the true parameter distribution is known. Several model comparisons and uncertain effects are therefore not intrinsically novel extensions. V3's worst unresolved pair is a design choice to falsify, with computation and sensitivity to its effect assumptions reported.

### Active FDI test and sensor selection — Awasthi, Palmer and Bollas, J. Process Control 2020

[Publisher abstract/introduction, DOI 10.1016/j.jprocont.2020.06.007](https://www.sciencedirect.com/science/article/pii/S0959152420302419).

**Access:** abstract/introduction only; full optimization implementation not reviewed.

The stated approach chooses tests and sensors using fault/uncertainty sensitivities, Fisher information and KL isolation measures. This independently defeats a broad novelty claim for “choose observations to distinguish faults rather than merely estimate parameters.” Its process-system assumptions do not transfer directly to camera–LiDAR data. A literature-inspired comparator is legitimate only with a clearly stated implementation, not by giving our heuristic this method's name.

### OA-LICalib — Lv et al., T-RO 2022

[Full paper, sections V-A/B](https://arxiv.org/html/2205.03276v1), [code](https://github.com/APRIL-ZJU/OA-LICalib).

**Access:** full HTML and local project/readme/license.

Continuous-time LiDAR–IMU calibration selects informative segments using a minimum information singular value and restricts updates through truncated SVD. Model-specific motion degeneracies motivate the restriction. The authors warn that singular-value magnitudes are not a universal information metric across different sequences.

**V3 consequence:** TSVD updates, information selection and observability-aware calibration already exist. Our existing `observability.py` and `selective_optimizer.py` provide these operations. Reuse them. Normalize physical units and preserve the distinction between supported data directions and regularized estimates; do not transfer LiDAR–IMU motion theorems to fisheye edge diagnosis.

## Additional calibration overlap and unresolved access

| Work and access | Mathematical relevance and decision |
|---|---|
| [Yuan et al., 2021, full cached methods III; arXiv:2103.01627](https://arxiv.org/html/2103.01627v2) | Point-to-image-line residuals, propagated image/LiDAR uncertainty, sensitivity to edge distribution and depth-continuous geometric edge extraction already exist. Visibility/footprint errors mean a depth jump is not automatically a correct correspondence. Reuse these concepts; uncertainty propagation and edge sensitivity are not V3 novelty. |
| [Scott et al., ICRA 2016, cached full author manuscript](https://ori.ox.ac.uk/media/5679/icra2016_scott.pdf) | Scene ranking by normalized NID cost profiles and joint exemplar optimization already connects scene quality to calibration. It is not fault-group diagnosis, but selection of calibration data is covered. |
| [Bultmann et al., arXiv:2610.37350v1, full methods III](https://arxiv.org/html/2610.37350v1) | Learned raw-image correspondences alternate with joint intrinsic, radial-tangential and pose optimization. Priors and scheduled intrinsic freezing stabilize weak estimates. Thus targetless joint calibration and alternating reassociation are covered; priors do not prove intrinsic/extrinsic identifiability. It uses a different camera model; no code release was inspected. |
| [Shen et al., IROS 2025, institutional abstract only](https://researchportal.hkust.edu.hk/en/publications/direct-targetless-and-automatic-joint-calibration-of-lidar-camera/) | Alternating NID-based intrinsic/extrinsic refinement is explicitly described. Exact solver/model and its guarantees remain unverified here. Do not claim targetless joint refinement as new. |
| [UniCalib, WACV 2026, official abstract only](https://openaccess.thecvf.com/content/WACV2026/html/Han_UniCalib_Targetless_LiDAR-camera_Calibration_via_Probabilistic_Flow_on_Unified_Depth_WACV_2026_paper.html) | Probabilistic correspondence flow and reliability maps already address uncertain cross-modal matches. Finite association stress tests are not an equivalent probabilistic model; the PDF request returned 403. |
| [Cocheteux et al., WACV 2025, full methods 3](https://arxiv.org/html/2501.06878v1) | MC-dropout-scaled residual scores and independent labelled conformal calibration create marginal parameter intervals under exchangeability. These are not fault probabilities or simultaneous update-safety guarantees. Our existing recordings cannot supply the required independent labelled calibration split. |

## Source and software ledger

These are **inspected local commits**, not claims that they remain the newest remote commits. Third-party directories stay external to the project source. A missing root license is not permission to copy; vendored libraries do not license the surrounding application.

| Repository | Inspected commit | License/reproduction boundary |
|---|---|---|
| `moravecj/OCaMo` | `1ac55de3c0eabb02f155cd44f7481117536c9526` | Root `LICENSE`: CC BY-NC 4.0. Read Python inference; not copied, reimplemented or benchmarked as full OCaMo here. |
| `CarloSgaravatti/MiCaDe` | `cdcd8af7d1b6f35e3a4f8bc4a34a2a124865fb97` | README-only at inspected commit; no implementation/root license found. Paper license is distinct from source licensing. |
| `koide3/direct_visual_lidar_calibration` | `02a0dc039f5509708f384be4ff3228e0ae09352d` | README and `package.xml` declare MIT; local NID source inspected. Dependencies require separate license review for redistribution. |
| `OpenCalib/JointCalib` | `6cb94c518b25e9dd61ffa88e63156e62db32416a` | No project root license found. Ceres/Eigen third-party licenses do not establish permission for JointCalib itself. Read only. |
| `APRIL-ZJU/OA-LICalib` | `50af68042111c93cf7c1d8ad36e982ec95e125ef` | Root GPL-3.0. Read-only methodological reference; no source copied. |
| EdgeCalib | No inspected official checkout | Paper method reviewed; no source/license/reproduction claim. |

## Research decision

The stronger formulation is **effect-size-aware, nuisance-profiled model discrimination with a verified fisheye measurement model**, rather than a newly named SVD score. Treat the linear algebra and design theory as established. The candidate contribution must come from a tested camera-geometry-specific explanation of ambiguity and an advantage over simpler evidence/selection methods. Full independent physical validation and a comprehensive novelty proof remain incomplete.
