# Prior-art review

Review date: **5 November 2026**. The mandatory paper-by-paper mathematical comparison is [PAPER_TO_ALGORITHM.md](PAPER_TO_ALGORITHM.md). It preceded implementation and records assumptions, limitations, adopted concepts, rejected novelty claims and concrete components. This review is bounded by access; it is not an exhaustive originality certification.

## What the literature establishes

| Line of work | Established mathematics | Consequence for this implementation |
|---|---|---|
| [Koide, ICRA 2023](https://arxiv.org/html/2302.05094v1) | Robust matching/RANSAC initialization followed by normalized information distance refinement | Initialization and local refinement are separate. Reuse the existing initializer; do not claim a new initializer or implement an untested NID reproduction. |
| [EdgeCalib](https://arxiv.org/html/2310.16629v1), [Yuan et al.](https://arxiv.org/html/2103.01627v2) | Multiframe edge reliability, image distance fields, point-to-line residuals, Lie updates and local uncertainty | Reuse scene-edge extraction and projection geometry. Weighted edges, Hessians and SO(3) are established components. |
| [JointCalib](https://arxiv.org/html/2202.13708v3), [Shen et al.](https://researchportal.hkust.edu.hk/en/publications/direct-targetless-and-automatic-joint-calibration-of-lidar-camera/), [Bultmann et al.](https://arxiv.org/html/2610.37350v1) | Joint intrinsic/extrinsic estimation; constraints, initialization and priors address compensation and convergence | Joint calibration and freezing weak intrinsics are already established. JointCalib uses a target; it is not an interchangeable natural-edge baseline. |
| [OCaMo author materials](https://cmp.felk.cvut.cz/~moravj34/ocamo/), [Moravec thesis](https://dspace.cuni.cz/handle/20.500.11956/116608), [MiCaDe](https://arxiv.org/html/2611.04912v1) | Robust monitoring/tracking, joint refinement, consistency likelihoods and statistical change detection | Detection is distinct from correction and physical fault attribution. Timing/motion and dependent nominal data matter. A monitoring-plus-optimization framework is not new. |
| [OA-LICalib](https://arxiv.org/html/2205.03276v1), [Fu et al.](https://arxiv.org/html/1903.06141v2) | Information-based segment selection, truncated-SVD identifiable updates, configuration-specific nullspace analysis | Measurement-only scaled rank, TSVD and information selection are established. Derive numerical support for this residual, rather than transferring a plane theorem. |
| [Scott et al., ICRA 2016](https://ori.ox.ac.uk/media/5679/icra2016_scott.pdf) | NID cost-profile descriptors and scene ranking; alternating sensor-pose-graph optimization | For scene j, phi_j(theta)=D_j(g plus theta)-D_j(g); compare each axis profile with the mean profile using K_j,alpha=(mean_phi_alpha dot phi_j,alpha)/||mean_phi_alpha||², then rank by min_alpha K. Known intrinsics and local cost basins are assumed. This is concrete prior art against generic informative-scene selection. Our implementation instead uses local group contrasts; no claim that selection itself is novel. |
| [Cocheteux et al., WACV 2025](https://arxiv.org/html/2501.06878v1) | Dropout-scaled conformal scores and labeled held-out quantiles | No conformal coverage claim without ground-truth parameter labels and an appropriate calibration partition. Current unlabeled recordings cannot supply this. |

## Closest mathematical overlaps outside calibration

Conditional information is a Schur complement / residual-space projection, not a new fault-diagnosis principle. [Dunia and Qin](https://doi.org/10.1002/aic.690440812) and [Ding et al.](https://doi.org/10.1016/j.jprocont.2009.07.005) already study fault subspaces and isolability. These publisher records were inspected at abstract level; no detailed theorem from them is asserted here.

Worst-rival discrimination and robust experimental design are also established: [robust T-optimal design](https://arxiv.org/abs/1309.4652), [multiple-rival design](https://arxiv.org/abs/1306.1320), [Duarte et al.](https://pmc.ncbi.nlm.nih.gov/articles/PMC4909360/), and [DT-optimal design](https://doi.org/10.1016/j.jspi.2007.05.024). The last was reviewed at metadata/abstract level. Our finite-pool greedy proxy has no proven global optimality, submodularity or calibrated risk interpretation.

[UniCalib, WACV 2026](https://openaccess.thecvf.com/content/WACV2026/html/Han_UniCalib_Targetless_LiDAR-camera_Calibration_via_Probabilistic_Flow_on_Unified_Depth_WACV_2026_paper.html) uses probabilistic correspondence flow; its official overview was inspected. Association uncertainty itself is not a new contribution. [Joint LiDAR/camera/IMU calibration](https://arxiv.org/html/2501.02821) also rules out broad multisensor-joint-calibration novelty.

Additional search on 5 November covered combinations of camera/LiDAR calibration, intrinsic/extrinsic fault diagnosis, observability, conditional information, correspondence uncertainty and model selection. [Das et al., RA-L 2023](https://arxiv.org/abs/2212.09579) further establishes observability-based pose selection for multi-LiDAR calibration; its abstract specifies raw angular-rate excitation and mutual-information selection. It is contextual prior art, not a reproduced comparator. Search did not establish exclusivity of our exact decision procedure. Missing indexed matches do not prove novelty.

## Access ledger

- Full arXiv method text inspected: A1, A2, A3, A5, A6, B2, C1, C2, D1 and the additional joint LiDAR/camera/IMU paper.
- C3's Oxford manuscript was downloaded, extracted and its Sections III-B and IV read. This strengthens the initial gate's scene-selection comparison with its exact cost-profile ranking mechanism.
- A4: institutional abstract only; exact alternating objective, constraints and experiments remain unverified.
- B1: author supplement, slides and released inference code inspected; complete journal equations were not retrieved. The code is evidence of released behavior, not a substitute for every paper detail.
- Other access levels are stated next to their claims. No benchmark numbers are imported as our results.

## Reference-repository inspection

These external clones remain outside the new application in `../research_references/`. No implementation was copied from them.

| Repository | Inspected commit | Reusable concept / implementation limit |
|---|---|---|
| [direct_visual_lidar_calibration](https://github.com/koide3/direct_visual_lidar_calibration) | `02a0dc039f5509708f384be4ff3228e0ae09352d` | Preprocessing, initialization/refinement separation and view filtering. README states MIT; no top-level license file observed. No code transplanted. |
| [OA-LICalib](https://github.com/APRIL-ZJU/OA-LICalib) | `50af68042111c93cf7c1d8ad36e982ec95e125ef` | Continuous-time estimation and information selection. GPL-3.0; README says observability-aware module is not released. Our small SVD implementation derives from the stated mathematics. |
| [OCaMo](https://github.com/moravecj/OCaMo) | `1ac55de3c0eabb02f155cd44f7481117536c9526` | Released inference and monitoring assumptions. CC BY-NC 4.0. Kept external. |
| [livox_camera_calib](https://github.com/hku-mars/livox_camera_calib) | `061fdaa647fc806e59d73a8505a05a10dfcfdaa1` | Natural-edge residual/uncertainty concepts. GPL-2.0. Kept external. |
| [JointCalib](https://github.com/OpenCalib/JointCalib) | `6cb94c518b25e9dd61ffa88e63156e62db32416a` | Target geometry and joint constrained optimization. No top-level license found; no code copied. |
| [MiCaDe](https://github.com/CarloSgaravatti/MiCaDe) | `cdcd8af7d1b6f35e3a4f8bc4a34a2a124865fb97` | README promises a future release; no inference implementation available at review. No reproduction claimed. |

The original calibration repository is the integration baseline. Reusing its own extractors is distinguished from reproducing an external paper's complete method.
