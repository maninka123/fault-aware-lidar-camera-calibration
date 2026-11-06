# Fault diagnostics v2: chance-referenced, multi-cue evidence for calibration faults

Branch `research/fault-diagnostics-v2`. This is an experimental layer beside the production assessment. It never
changes a production verdict, threshold or output file. Code: `research_calibration/fault_diagnostics/`. Tests:
`research_tests/test_fault_diagnostics.py`. Tools: `tools/probe_loss_bias.py`, `tools/evaluate_fault_diagnostics.py`,
`tools/evaluate_sequential_monitor.py`, `tools/summarize_fault_diagnostics.py`. Command line:
`python -B -m research_calibration diagnose --calibration current.json --captures folder --output new_folder`.

Related documents: [prior-art review, second pass](PRIOR_ART_REVIEW_V2.md),
[preregistration](PREREGISTRATION_V2.md), [verification results](VERIFICATION_RESULTS.md#fault-diagnostics-v2),
[novelty](NOVELTY_ASSESSMENT.md#fault-diagnostics-v2-6-november-2026).

## 1. Failure modes of the current backend

### 1.1 The held-out loss rewards edge density

The production comparison scores each candidate on a held-out capture with

    L_c(p) = mean_i min(d_i(p), 30)^2 / 30^2,

where d_i is the distance from projected LiDAR edge point i to the nearest image edge pixel. A useful model is
d_i = a_i + c_i, with:

- a_i, the alignment term (small when point i lies on its true image edge);
- c_i, the chance term (the distance to the nearest *unrelated* edge).

Most points have no visible counterpart: share at 1.5 px is 5–17 %. For those points d_i = c_i. The expected
c_i falls where edges are dense, so `L` decreases whenever projections move towards denser image regions,
whether or not alignment improves.

**Measurement** (`tools/probe_loss_bias.py`, no fitting). Each recording's reference was shifted by known offsets.
For each offset we compared three things, averaged over captures:

- the production loss change;
- the change predicted by the *decoys*: the same capture with its edges displaced 8 px in 8 directions, which
  keeps the density but destroys the geometry;
- the chance-referenced contrasts (§2).

| Recording | Offset | Production loss | Chance-predicted | Edge contrast | NID contrast (×1e-3) |
|---|---|---:|---:|---:|---:|
| creep_three | cy +4 px | **−15.5 %** | −13.1 % | −0.028 | −8.65 |
| creep_three | rx −1° | **−15.0 %** | −12.6 % | −0.021 | −8.69 |
| creep_three | ty +5 cm | **−11.7 %** | −9.8 % | −0.019 | −4.62 |
| october_device_one | cy −4 px | **−10.2 %** | −10.7 % | −0.049 | −5.94 |
| october_device_one | rx +1° | **−10.6 %** | −11.2 % | −0.047 | −5.97 |
| enclosure_off_ten | cy +4 px | **−5.4 %** | −5.1 % | 0.000 | −0.74 |

In every recording the production loss falls *linearly* along one image direction. The direction depends on
the scene: creep "improves" downwards, device one upwards. Over 4 px it falls by 5–15 %, 5 to 15 times the 1 %
acceptance threshold. The decoys predict 75–105 % of that fall. Both chance-referenced contrasts instead drop
in *both* directions, so the reference is their local optimum on creep and device one.

**Consequence.** A candidate's held-out "gain" can be produced entirely by edge density. On the recorded
10-capture run the best production candidate (R) gained 0.62 %, and its decoys predict 0.60 %.

### 1.2 A KEEP verdict is not a confirmation

On `enclosure_off_ten` the reference matches chance at the decoy level:

- edge share 6–7 % against a decoy share of 6–7 %;
- per-capture lift 0.81–1.09;
- intensity contrast about 0.

The maintenance analysis of the same captures reports LARGE CHANGE: alignment at 0.96× chance and an 18.7 px
refinement. Its refined calibration differs from the reference by about 30 cm and 3°. The production backend
returns KEEP_CURRENT, because its local fits cannot reach 18 px and the biased loss shows no 1 % gain. The
policy cannot distinguish "the data confirm the calibration" from "the data cannot see the calibration".

### 1.3 Other observed mechanisms

- **Weak or confounded geometry.** In these fisheye recordings, rotation and principal-point changes are
  nearly collinear (principal angle about 1.8°). Translation is weakly constrained without depth variation.
  In the development trials, larger hypotheses (TI, RTI) always fit held-out data slightly better than the
  true single group. The production policy then reports a wrong group or abstains.
- **Optimiser non-convergence looks like drift.** Fits that start from a data-consistent anchor still gain
  0.2–0.7 contrast points on held-out captures, because two more re-association passes keep moving in the
  same direction. Any margin must exceed this.
- **Dependent captures.** All captures of a recording view one static scene, so a scene-level artefact is
  shared by every fold. Replication across folds therefore cannot by itself separate drift from scene bias.
  Only a physically different cue, or a different scene, can.
- **Temporary corruption.** One blurred, ghosted or desynchronised capture changes one fold's evidence; a
  mean-based rule can be moved by a single capture.

## 2. Method

Notation: p is the current calibration, p_H the fit of hypothesis H ∈ {R, T, I, RT, RI, TI, RTI} on the training
captures of a leave-one-capture-out fold, and c the held-out capture. Fits, folds, selection and outer split
are the production engine's, unchanged. The diagnostics read them through a fold observer.

### 2.1 Decoy-referenced contrasts (chance controls)

For capture c, define the decoy offsets s_k = r(cos 2πk/K, sin 2πk/K), with K = 8 and r = 8 px.

**Edge cue.** Let S_c(p, s) be the share of the edge points visible under p (a fixed support) that satisfy all
of the following after their projection is displaced by s:

- an image edge lies within g = 1.5 px, both by distance transform and by point-to-line distance;
- the projected 3D edge direction is parallel to it within 15°.

Points that become invisible count as unmatched. The contrast is

    E_c(p) = S_c(p, 0) − (1/K) Σ_k S_c(p, s_k).

**Intensity cue.** Let N_c(p, s) be the normalised information distance between histogram-equalised LiDAR
reflectivity (20 000 points) and image intensity sampled at the displaced projections (32 bins, soft
histogram, as in Koide et al.). The contrast is

    I_c(p) = (1/K) Σ_k N_c(p, s_k) − N_c(p, 0).

A displaced image keeps its own edge density, orientation statistics and intensity histogram but breaks the
geometric link to the LiDAR data. A change of p that only moves projections into denser or more textured
regions therefore changes the aligned and displaced terms alike, to first order. A capture whose image cannot
tell aligned from displaced data has a contrast near zero for every calibration. This is the decoy
counterpart of lift, the matched-to-chance ratio that the original application already reports. The two cues
measure different physics (geometric discontinuities versus reflectivity and appearance) and use different
LiDAR samples.

**Counterfactual quantities per fold and hypothesis.**

- dE_c(H) = E_c(p_H) − E_c(p) and dI_c(H) = I_c(p_H) − I_c(p).
- The *chance-predicted* production gain, which is the nuisance counterfactual: the production loss computed
  against the decoy edges, giving (Ld_c(p) − Ld_c(p_H)) / L_c(p).

### 2.2 Scene-conditioned evidence quality

- **Informative capture.** Capture c is informative for a cue if the reference, or any fitted hypothesis,
  beats its decoys by a declared margin: E ≥ 0.02 for edges, I ≥ 0.003 for intensity. Only informative
  captures count for that cue.
- **Reference confirmation.** The reference is confirmed by a cue if its contrast has median ≥ that margin
  and is positive on at least 2/3 of the informative captures.

### 2.3 Replication rule and cue agreement

For hypothesis H and a cue with informative captures C (|C| ≥ 3), H gains if both of the following hold:

- at least ⌈2/3·|C|⌉ captures have a change above the cue margin;
- the median change is above that margin.

The margins are 0.01 for edges and 0.0005 for intensity. Sign replication plus a median bounds the influence of
any single capture (temporary corruption).

H is **supported** when either:

- intensity is informative, the edge rule holds, and the intensity rule also holds (agreement, not merely the
  absence of contradiction); or
- intensity is uninformative for the recording, and the edge rule holds. The verdict then records
  `evidence_basis = "edges only"`.

A doubled edges-only margin was tried during development and removed. It cost 7 of 15 detections on
`enclosure_off_ten` and prevented no false alarm.

### 2.4 Attribution with ambiguity

Let A be the set of supported hypotheses, and b the one with the largest median edge change. A rival h is
*tied* with b unless b beats h on the paired per-capture differences under the same replication rule. Among the
tied set we keep the minimal explanations: those for which no tied explanation uses a proper subset of their
groups.

- One minimal explanation, with the engine's group-unique attribution support in every fold:
  **DRIFT_SUPPORTED(H)**.
- Several minimal explanations, for example R and I: **DRIFT_AMBIGUOUS** with that set.
- Attribution support fails: also **DRIFT_AMBIGUOUS**.

An update is recommended only for DRIFT_SUPPORTED, and only when independent outer captures (never used for
fitting or selection) all show the edge gain without an intensity contradiction.

### 2.5 Rejection states

| Status | Condition |
|---|---|
| NUISANCE_SUSPECTED | No hypothesis is supported, but the production loss shows an apparent improvement (production candidate supported, or best gain ≥ 1 %) |
| KEEP_CONFIRMED | No hypothesis is supported, and the reference is confirmed by at least one cue |
| REFERENCE_NOT_CONFIRMED | No hypothesis is supported, the reference is not confirmed, and some captures are informative |
| INSUFFICIENT_EVIDENCE | Fewer than 4 held-out captures, or fewer than 3 informative captures for both cues |

### 2.6 Persistence over capture time

When capture times exist, the contrasts of the current calibration are monitored in time order. The first W = 4
captures form a reference window, assumed nominal, with median m and spread s = max(1.4826·MAD, 0.25·|m|). The
score is z_i = (m − x_i)/s.

- **Clipped CUSUM.** S_i = max(0, S_{i−1} + min(z_i, 2) − 0.5); alarm when S_i > 4. The clip below the
  threshold means no single capture can raise an alarm; at least three degraded captures are needed.
- **Labels.** PERSISTENT_CHANGE if the scores after the alarm stay above the allowance (median); otherwise
  TRANSIENT_DEVIATION. A cue whose window median is below the informative margin is UNINFORMATIVE.
- **Conformal test martingale.** Reported alongside, using smoothed conformal p-values of low values and the
  mixture bet f(p) = ∫₀¹ ε p^(ε−1) dε = (p ln p − p + 1)/(p ln² p). Under exchangeability its false-alarm
  probability is at most α by Ville's inequality. With 10–15 captures it has almost no power. A capture that
  ranks lowest among n = 11 multiplies the martingale by only f(1/11) ≈ 1.3, apart from rare randomised ties,
  so reaching 1/α = 20 needs many consecutive extreme captures. We report this as a limitation, not as a
  guarantee in use.

## 3. What is and is not claimed

- No fault probability, coverage or ARL is claimed. Replication counts over dependent captures are descriptive.
- Decoys remove first-order density effects. They do not remove structure that repeats at the decoy offset
  (periodic textures), and they do not detect a ghost image that is geometrically consistent with a wrong
  calibration, unless the intensity cue disagrees.
- Attribution is reported only to the precision the data support. R and I are frequently one class here.
- Semi-synthetic labels are relative to an anchor calibration whose own error is unknown (§4).

## 4. Evaluation design

See [PREREGISTRATION_V2.md](PREREGISTRATION_V2.md) for the frozen protocol. Results are in
[VERIFICATION_RESULTS.md](VERIFICATION_RESULTS.md#fault-diagnostics-v2).

## 5. Outcome in one paragraph (held out, preregistered)

The evaluation used two held-out recordings, 104 trials scored from identical folds. Compared with the
production policy, the experimental layer:

- raised **no false alarm in 54 no-change trials**, against 12 for production;
- **detected 29 of 48** injected changes, against 16;
- made **3 wrong attributions**, against 24;
- recommended no update in a no-change trial (production also recommended none).

Its persistence monitor alarmed on 17/24 persistent changes and on 0/18 single-capture corruptions; the
production-loss CUSUM alarmed on none.

The ablations do not support every component:

- The **intensity agreement rule** cost 13 detections without preventing a false alarm and should be
  withdrawn or redesigned.
- **Decoy subtraction** inside the decision rule was no better than the raw oriented matched share.
- **Quality gating** is the component that consistently helped.

**Correct single-group attribution remains rare** (1/48; production 4/48). What the method mostly reports is an
honest ambiguity set.

## 6. Recommended next steps (not done here)

1. Remove the intensity agreement requirement, or weight it by the cue's own per-recording informativeness.
   Then re-evaluate on *new* held-out recordings; the current ones are now spent.
2. Attribution: test depth-stratified signatures (translation parallax ∝ 1/z) and collect scenes with depth
   variety, so that T separates from R and I. Report R/I as one class unless the lens geometry separates them.
3. Collect genuinely labelled sessions: a measured mount rotation, a shim translation, a refocused lens, and
   nuisance-only sessions (wet or dirty window, low light). Collect sequences long enough (≥ 30 captures) for
   the conformal monitor to have power.
