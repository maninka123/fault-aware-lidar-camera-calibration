# Protocol: correspondence front ends for V3 diagnosis (frozen before the evaluation recordings were run)

Written 6 November 2026 and committed before `enclosure_on_twelve` and `october_device_four` were run through any correspondence
experiment. Code and constants are those of the commit that adds this file. Any change after the evaluation is a new development round.

## Question

The V3 signed-residual inference attributes injected faults on recorded geometry when it is fed correct correspondences
([root-cause analysis](ROOT_CAUSE_ANALYSIS.md)). Can an automatic pairing front end supply pairs good enough for the same inference, without
using the anchor, and what does it cost in false alarms, wrong attributions and calibration recovery?

## Data roles (manifest field `pairing_role`)

| Role | Recordings | Use |
|---|---|---|
| development | `october_device_one`, `enclosure_off_ten` | Root-cause experiments, design, diagnosis of failures. Everything in ROOT_CAUSE_ANALYSIS.md was seen here. |
| evaluation | `enclosure_on_twelve`, `october_device_four` | Run once with this protocol. Not used in the design of the pairing methods. |

All four recordings were examined earlier in V2 and V3 development, for the V2 policy and the V3 inference. The evaluation recordings are therefore
**not blind data**; they are only unseen by the *pairing* methods and by every constant below. No physical ground truth exists for any recording.

## Truth

Same as V2/V3: each recording's anchor (its reference refined by the production engine on all of its captures) is the unperturbed calibration;
a perturbation of the anchor is the "current" calibration to diagnose; the correct answer is the perturbation's parameter group, the correct
correction returns to the anchor. **Reference pairs** are the pairs the anchor itself finds under a strict gate (2 px, 15 degrees); they are a
proxy for true correspondences, used only as an upper bound ("reference_pairs") and to measure pairing identity. They are not available to any
method under test.

## Methods (all see the same captures, perturbation, seeds and the V3 `infer_signatures` inference)

| Method | Definition |
|---|---|
| `reference_pairs` | Anchor's pairs, residuals at the current calibration. Upper bound; unavailable in practice. |
| `nearest` | Nearest image edge pixel within 8 px, no orientation test. |
| `oriented` | The repository's existing orientation-aware nearest edge (gate 9 px, 30 degrees). |
| `geometric` | `correspondence.associate` with defaults: gate 8 px, 30 degrees, sigma 1.5 px / 10 degrees, outlier cost 4.5, four candidates; responsibility weights, z-buffer visibility, cell/range balancing. |
| `geometric_no_visibility`, `geometric_no_confidence`, `geometric_no_balance` | One mechanism off each. |

Alternating estimation (`joint_estimation.em_refine`) and the unique-within-radius rule were diagnosed on the development recordings and are **not**
part of the evaluation: they did not help (see ROOT_CAUSE_ANALYSIS.md). They remain as configurable, documented negative results.

## Inference, recovery and acceptance (all frozen)

* Inference: `SignatureConfig()` defaults (detection tolerance 0.25, separation tolerance 0.35 whitened RMS, four capture blocks), at most 400 rows per
  capture, row variance 1 / max(weight, 0.05) px^2.
* Recovery: for an alarmed trial, a one-step truncated-SVD correction over the groups in the ambiguity set (or the unique hypothesis) plus the beam
  nuisance; a direction is corrected only if its implied standard deviation (1 / singular value of the whitened design) is at most 1 normalized unit
  (1 degree, 1 cm, 1 px, 1 % focal). Reported: median projection error of the capture LiDAR points versus the anchor, before and after.
* Acceptance: only for a unique diagnosis (`DRIFT_SUPPORTED`); the correction is fitted on training captures (engine outer-split rule: reserve
  ceil(0.3 n) captures when n >= 7); accepted only if the V2 chance-referenced edge contrast improves by more than 0.01 on every reserved capture.
  This is an offline experiment; no hardware write exists.
* Conditions per recording and replicate: nominal, seven injected changes (R 0.5 / 1 deg, T 3 / 6 cm, principal point 3 px, focal 2 %, RT) and two
  nuisances (spurious lines, ghost edges). Two replicates (seeds identical to the V2/V3 tools). Same-trial comparison with the original recorded
  V3 pipeline uses its own tool on the same recordings, replicates, seeds and conditions.

## Metrics

No-change alarms; detections; exact attribution (unique and equal to the injected set); wrong unique attribution over all trials; ambiguous
decisions whose set contains the exact injected group; median projection error before/after; accepted updates on no-change and drift trials with
their median error; seconds per trial split into pairing and inference. Pairing identity (correct / wrong against reference pairs) is reported
separately by the root-cause tool. Counts come from dependent trials on two static scenes; no confidence interval or error probability is claimed.

## Predeclared expectations (falsifiable)

1. `geometric` raises fewer no-change alarms than `oriented` and `nearest`.
2. `geometric` makes fewer wrong unique attributions than `oriented`.
3. `geometric` does **not** reach the exact attribution of `reference_pairs`; if it does, the correspondence problem is solved on this data.
4. Each ablation of `geometric` is no better than `geometric` on both no-change alarms and wrong attributions; a mechanism whose ablation is
   equal or better is withdrawn.
5. No method produces an accepted update on a no-change trial.
6. A method that only abstains more is reported as that trade-off, not as improved attribution.

## Out of scope

Physical accuracy, calibrated error rates, other rigs or lenses, simulator data, any hardware write, and any claim of novelty beyond the
literature comparison in NOVELTY_COMPARISON.md.
