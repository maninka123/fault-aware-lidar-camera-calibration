# Prior-art review, second pass (6 November 2026, fault diagnostics v2)

This review covers, for each method:

- what it measures;
- the statistic it decides on;
- what that statistic assumes;
- what it cannot separate: a calibration change versus misleading correspondences, weak scene geometry,
  temporary degradation, or sensor nuisances.

It complements [PRIOR_ART_REVIEW.md](PRIOR_ART_REVIEW.md) (5 November). Access is stated for each item and
summarised in the ledger at the end. The method this review motivates is in
[FAULT_DIAGNOSTICS_V2.md](FAULT_DIAGNOSTICS_V2.md).

## OCaMo and LTO (Moravec and Šára, IEEE T-RO 40, 2024, doi 10.1109/TRO.2023.3347130)

**Access.** We read the author page, the supplement, the ICRA 2024 slides and the released Python inference code
(`moravecj/OCaMo`, CC BY-NC, kept external). We did not retrieve the full journal equations.

**Mathematics, as released in the code.**

- The quality criterion is a kernel correlation over projected LiDAR corner points and their k nearest Canny
  edge pixels:

  F(θ) = − Σ_i Σ_k exp(−d_ik² / 2σ²), with σ = 9 px and k = 10.
- **LTO** evaluates F on a fixed 3×3×3 rotation grid of ±0.01 rad. The fraction of grid neighbours that score
  at least as well as the reference is mapped to a validity index p_c/(p_c + p_d). The two Beta densities are
  fitted on calibrated and decalibrated training sequences.
- **OCaMo** tracks θ by stochastic gradient with an adaptive (Schaul) step and a bounded memory. Its validity
  index is a product of per-axis Gaussian tail probabilities that the tracked offset lies inside 3ω.

**Contribution.** A local-optimality certificate: the reference is valid if no nearby parameter explains the
data better. Once the rank distributions are learned, the certificate becomes probabilistic.

**Limitations.**

- The criterion is a raw edge-proximity score. It rises when projections move into edge-dense regions, so the
  rank inherits the bias we measured in our own nearest-edge loss (see the failure-mode table in
  FAULT_DIAGNOSTICS_V2.md).
- The Beta likelihoods need labelled calibrated and decalibrated sequences from the same platform.
- It covers rotation (the Python release) or the six extrinsic parameters, with intrinsics fixed.
- It does not say which parameter group changed.
- The authors note that uncompensated latency can look like decalibration, so this nuisance is not separated
  from a fault.

**What we keep and change.** We keep the certificate idea. Instead of comparing the reference with nearby
parameters, we compare the capture with displaced copies of its own image (decoys). This removes the
edge-density bias and needs no labelled training sequences.

## MiCaDe (Sgaravatti et al., arXiv 2611.04912, 3 November 2026)

**Access.** We read the full arXiv HTML and our cached text. The code repository contains no inference code.

**Mathematics.**

- 3D detector boxes are projected with the nominal P₀. They are matched to 2D detections by Hungarian IoU
  assignment, within the same class and with IoU ≥ 0.1.
- Each match gives a seven-element vector:
  - the centre offset (x, y, magnitude, and the sine and cosine of its angle);
  - the IoU;
  - a ground-plane depth inconsistency.
- Batches of n = 15 matches give a nine-dimensional feature: the means, plus two variances.
- A Gaussian mixture φ₀ is fitted by EM on calibrated reference sequences, with the number of components
  chosen by BIC.
- The stream l_k = log p_φ₀(f_k) is monitored by the nonparametric Lepage change-point model of Ross et al.
  Thresholds are set for a target ARL₀ using synthetic i.i.d. data.

**Contribution.** A sequential test that needs no labels once the nominal model is fitted, with an explicit
false-alarm design target, change-point localisation and per-degree-of-freedom delay analysis.

**Limitations stated by the authors.**

- ARL₀ holds only approximately, because the batch features are not i.i.d.
- It depends on 3D–2D object matches, which fail in sparse scenes.
- Translation is detected slowly (t_y: 91 s, FNR 0.27).
- Intrinsics are assumed known.
- It does not attribute a change to a parameter group.

**Limitations we add.**

- The nominal density must come from calibrated data of the same platform.
- A static rig with few objects produces no matches.
- Any drop in detector confidence (night, rain) moves the likelihood stream without a calibration change, and
  this nuisance is not modelled.

**What we keep and change.** We also monitor a per-capture statistic sequentially. Ours is already referenced
to chance inside each capture, and the reference window only sets the scale. The CUSUM is Huber-clipped, so
one corrupted capture cannot raise an alarm. We also run a conformal test martingale, whose bound needs
exchangeability rather than a fitted nominal density. We do not claim an ARL.

## Visibility-guided geometric edge matching (IEEE TIP, 2026)

**Access: not located.** We searched arXiv, IEEE Xplore listings and general indexes and found no TIP 2026
paper matching this description.

The closest accessible works share one idea: model visibility at depth discontinuities, so that a foreground
LiDAR edge is matched only with the image edge it can actually produce.

- Tong et al., *Meas. Sci. Technol.* 2026, doi 10.1088/1361-6501/ae9210 (abstract only). It weights matches
  near occlusion boundaries by a confidence map built from the LiDAR range map.
- P2O-Calib, arXiv 2311.02413. It filters 2D–3D matches by occlusion direction.
- Galibr, arXiv 2406.11599. It aligns occlusion-edge points with image edges.

**We assert no equations of the requested paper. Its title or DOI is needed to review it.**

**Relevance.** Visibility-aware matching removes wrong correspondences at their source. It does not tell the
decision layer how much of a remaining improvement is chance. Our engine already:

- fixes the evaluation support to the points visible under the reference;
- penalises points that become invisible;
- models the beam-divergence widening at depth edges (η).

The decoy contrast is complementary: it audits whatever matcher is used.

## Environment-Driven Online Calibration, EdO-LCEC (Huang et al., arXiv 2502.00801, v3 November 2025)

**Access.** We read the full arXiv HTML. IEEE Xplore entry 11224389 was inspected at listing level only.

**Mathematics.**

- A scene discriminator computes a feature density ρ = ρ_t·ρ_s from MobileSAM masks and Depth Anything depth:
  - ρ_t is the log of the squared corner count;
  - ρ_s is a sum of log mask-area ratios.
- The number of virtual LiDAR views is a density ratio between the camera and LiDAR projections.
- Dual-path matching keeps mutual-best matches under a combined cost:
  - a structural cost (mask-corner geometry plus neighbour vectors);
  - a textural cost (L1 difference of depth patches).
- Calibration minimises Σ G(ε), where G is a depth-weighted robust kernel. This is done over per-scene PnP
  solutions and then over a density-weighted subset of scenes.

**Contribution.** Scene-conditioned effort: the number of views, and the weight given to each scene, follow
measured feature density.

**Limitations.**

- Density is a proxy for informativeness, not for correctness. A cluttered region raises ρ exactly where
  chance alignment is easiest.
- There is no confidence or abstention output.
- It relies on learned depth and segmentation front ends.
- It estimates extrinsics only.

**What we change.** We condition on measured discriminability ("does this capture beat its own displaced
copies?") instead of density. A capture that does not is reported as missing evidence.

## Uncertainty-aware online extrinsic calibration (Cocheteux et al., WACV 2025, arXiv 2501.06878)

**Access.** We read the full text.

**Mathematics.**

- Monte Carlo dropout gives a mean and a σ for each parameter.
- Split conformal prediction uses the score s = |ŷ − y| / σ̂. It takes the ⌈(m + 1)(1 − α)⌉-th
  calibration score as Q_{1−α} and reports the interval ŷ ± Q·σ̂.
- Coverage is marginal, and holds when calibration and test samples are exchangeable.

**Contribution.** Distribution-free coverage of parameter intervals on top of any regressor.

**Limitations.**

- It needs ground-truth parameters on the calibration split; the authors use synthetic decalibrations of
  KITTI and DSEC.
- Coverage is averaged over that distribution, not conditional on a scene.
- It neither detects nor attributes faults.
- Exchangeability fails across sessions and rigs.

**Consequence for us.** Without labels we cannot calibrate parameter intervals. We use the conformal idea only
where its assumption can be stated without labels: a conformal test martingale over a capture stream, under
the hypothesis of no change.

## Observability, fault isolation and sequential detection

**Fault subspaces and nuisance rejection.**

- Fouladirad and Nikiforov (*Automatica* 41, 2005; abstract and course copy) derive invariant tests that are
  optimal under unknown, non-random nuisance parameters.
- Matched-subspace detectors (Scharf and Friedlander, *IEEE TSP* 1994; standard result, not re-read) project out
  an interference subspace before testing a signal subspace.
- Dunia and Qin, and Ding et al., define isolability through fault-direction subspaces.

Our engine's nuisance-residualised (Schur-complement) information and its group-unique stable support are
instances of these ideas. Their consequence is the rule used in v2: **a change can be attributed only if its
signature remains after the nuisance and the rival groups are projected out.** In the fisheye recordings, R
and the principal point are nearly collinear (principal angle about 1.8°). A correct procedure must therefore
report "R or I" rather than pick one of them.

**Observability-aware selection.** Lv et al. (OA-LICalib), Fu et al. (arXiv 1903.06141), Das et al. (RA-L 2023)
and Scott et al. (ICRA 2016) select data by information content or cost-profile shape. They all assume the cost
is correct. None asks whether an apparent gain in information is chance alignment.

**Sequential change detection.** All of the following are standard, and our use of them is not a contribution:

- Page's CUSUM (1954) and Lorden's minimax delay (1971).
- The nonparametric change-point models of Ross et al., used by MiCaDe.
- Conformal test martingales (Vovk et al., "Testing randomness online", *Stat. Sci.* 36, 2021; "Retrain or not
  retrain", COPA 2021). Under exchangeability, P(sup_n M_n ≥ 1/α) ≤ α by Ville's inequality.
- Robust (Huber-clipped) CUSUM variants, which bound the influence of any single observation.

## What remains open after both reviews

None of the reviewed methods measures how much of an observed improvement in cross-modal alignment would also
be produced, at the same image location, by unrelated image structure. Equivalently, none uses negative-control
(decoy) references to make its statistic invariant to edge or texture density.

- MiCaDe and OCaMo calibrate their statistics on nominal training data.
- EdO-LCEC weights scenes by density.
- The conformal methods need labels.

This gap is what v2 addresses. Its novelty is assessed in [NOVELTY_ASSESSMENT.md](NOVELTY_ASSESSMENT.md).
Missing indexed matches do not prove novelty.

## Access ledger

| Item | What we accessed |
|---|---|
| OCaMo / LTO | Author page, supplement and slides; released code read (lto/ocamo monitoring, kernel correlation) |
| MiCaDe | Full arXiv HTML and cached text |
| TIP 2026 visibility-guided edge matching | Not located; closest works at abstract level |
| EdO-LCEC | Full arXiv HTML |
| Cocheteux et al., WACV 2025 | Full text |
| Fouladirad and Nikiforov 2005 | Abstract and metadata |
| Vovk et al. 2021 | Abstracts and search summaries |
| Page 1954; Lorden 1971; Scharf and Friedlander 1994 | Standard results; not re-read |
