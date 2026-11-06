# V2 versus V3: measured comparison

V3's geometric model explains local fault aliases and can veto an attribution. It has **not solved exact attribution on the recorded data**. The final conservative default reduces unique wrong decisions by abstaining more often; its only remaining unique attribution in the 68-trial comparison is wrong. Detection gains over unchanged V2 are already obtained by removing V2's harmful intensity-agreement requirement.

## Evidence tiers

1. **Historical V2 evaluation:** two recordings, three replicates, 102 scored trials plus two unlabelled references. Saved outcomes were reproduced without recomputing policy. These recordings are now V3 development data.
2. **Fresh matched V3 development experiment:** four previously inspected recordings, one replicate, 68 scored trials, identical shared production fits and partitions. This tests the implemented finite-effect attribution proposal, with independent correctness fixes applied before execution.
3. **Final conservative policy replay:** the same 68 trial records and stored geometric outputs, rescored after reviewing the proposal's negative attribution results. This is explicitly outcome-informed development, not a fresh or blind validation.
4. **Physical validation:** unavailable. Known perturbations are relative to an estimated anchor. Nearest-edge loss and anchor displacement are not physical accuracy ground truth.

## Matched recorded-data outcomes

Counts below use common data and fits. There are 36 no-change and 32 changed-calibration trials. Exact attribution means the inferred parameter-group set equals the injected set, including joint faults. Wrong attribution counts unique wrong explanations over all 68 trials. Ambiguity truth inclusion requires an exactly matching hypothesis, not merely a joint superset.

| Method | No-change alarms | Drift detections | Exact attribution | Wrong attribution | Ambiguous | Truth in ambiguity |
|---|---:|---:|---:|---:|---:|---:|
| Production policy, fresh fits | 4/36 | 9/32 | 1/32 | 12/68 | unavailable | unavailable |
| Unchanged V2, same fresh fits | 0/36 | 22/32 | 0/32 | 4/68 | 18/32 | 12/18 |
| V2 without intensity / V3 without geometry | 0/36 | 27/32 | 1/32 | 3/68 | 23/32 | 16/23 |
| V3 finite-effect proposal, fresh experiment | 0/36 | 27/32 | 0/32 | 2/68 | 25/32 | 18/25 |
| V3 conservative default, policy replay | 0/36 | 27/32 | 0/32 | 1/68 | 26/32 | 18/26 |
| Conservative V3 without quality evidence, replay | 0/36 | 25/32 | 0/32 | 1/68 | 24/32 | 17/24 |
| Conservative V3 raw edges, replay | 1/36 | 28/32 | 0/32 | 0/68 | 28/32 | 17/28 |

Source summaries: [fresh experiment](results/matched_development_finite_effect.md), [final policy replay](results/matched_development_conservative_replay.md). Full inspectable metric dictionaries include per-fault counts, selective accuracy and coverage.

The conservative default's exact selective accuracy is 0/1, with unique-attribution coverage 1/68 (1.47%). Its mean ambiguity-set size is 2.42. Truth inclusion is 18/26 (69.2%) conditional on ambiguous drift decisions, or 18/32 across all drift trials. These broad/dependent counts do not establish calibrated ambiguity coverage. With geometry disabled, one exact attribution is retained but three unique explanations are wrong. This is a trade-off in abstention, not demonstrated accurate fault identification.

The raw-edge variant removes the remaining unique wrong attribution by returning ambiguity for every detected drift, but introduces a nuisance alarm. It is not uniformly better. Restoring decoy correction in the default was an explicitly outcome-informed development choice, with the raw alternative retained as an ablation. Numerical thresholds were unchanged.

## Why the stronger attribution proposal was rejected

Correct fisheye derivatives do not establish that the selected edge correspondences or fitted explanation are physically correct. For example, the fresh finite-effect experiment uniquely assigns a rotation perturbation to TI on `enclosure_off_ten`, while only TI has held-out edge support. Another rotation-plus-spurious-lines trial is uniquely assigned to T. The geometric test can confidently distinguish the fitted wrong field from its rivals while failing to identify the injected cause.

The final rule therefore requires an existing unique held-out attribution and the same uniquely supported hypothesis under every stored actual fold effect. Geometry may veto that attribution; it cannot promote an ambiguous V2-style result. The rule is shared by the executable backend and policy replay. It gives no operational false-attribution guarantee and cannot repair false matches or weak anchors.

## Update safety and calibration accuracy

| Property | V2 | V3 |
|---|---|---|
| Production application | Preserved baseline | Preserved; experimental sidecar only |
| Hardware writes from experimental diagnosis | None | None; `hardware_write_authorized=False` |
| Supported drift automatically authorizes update | No | No |
| Final candidate gate | Supported fit and reserved outer evidence | Supported fit, every-fold/candidate geometric check, conditional uncertainty and disjoint reserved evidence |
| Accepted-update accuracy on independently known physical faults | Unavailable | Unavailable |
| V3 final update acceptance in matched experiment | Not applicable | Not exercised: diagnostic-only comparison |
| Physical rotation, translation and intrinsic accuracy | Unavailable | Unavailable |

Zero recommended V3 updates in this diagnostic comparison is a consequence of the API boundary, not evidence of zero false-update risk. Numerical decision-contract and end-to-end API tests verify software behavior under fixtures; they do not validate physical update accuracy.

## Computational cost

In the fresh 68-trial experiment, median shared production-plus-V2 wall time is 6.982 s per trial. Median production fitting/assessment is 5.905 s and median V2 evidence processing 0.906 s; these component medians need not sum to the total median. All 68 complete trial wall times sum to 487.57 s, excluding dataset setup/anchor construction outside each trial.

The finite-effect V3 sidecar adds a mean 0.0192 s per trial (95th percentile 0.0731 s), totaling 1.304 s over the 68 trials. Geometry is actually available/evaluated on 26 trials, with median 0.0470 s on those trials. The all-trial median of 0.0007 s mostly reflects early returns on captures without supported drift and understates geometric processing cost.

Final conservative replay performs no new sensor fitting or geometry computation. Its reported sub-millisecond policy medians measure only the replay rule and must not replace the original pipeline cost. These timings were measured on this workstation under local thread caps; they are not real-time or hardware-independent guarantees.

## Frozen maintenance optimizer comparison

This is a separate, fresh 16-trial experiment on two recordings: two nominal and 14 drift trials. The frozen legacy refinement routine is used at the common declared fitting budget. Its hypothesis set differs from the production engine, so this is an optimizer comparison rather than an identical full legacy-app protocol. No nuisance conditions or independently known physical changes are included.

| Method on the same legacy-optimizer fits | No-change alarms | Detections | Exact attribution | Wrong attribution | Ambiguous / truth included |
|---|---:|---:|---:|---:|---:|
| Frozen maintenance optimizer policy | 0/2 | 5/14 | 0/14 | 5/16 | unavailable |
| V2 | 0/2 | 12/14 | 0/14 | 5/16 | 7 / 2 |
| V2 without intensity | 0/2 | 12/14 | 0/14 | 4/16 | 8 / 3 |
| V3 finite-effect proposal | 0/2 | 12/14 | 0/14 | 3/16 | 9 / 6 |
| Final conservative V3 replay | 0/2 | 12/14 | 0/14 | 0/16 | 12 / 6 |

Sources: [fresh optimizer experiment](results/legacy_optimizer_finite_effect.md), [conservative policy replay](results/legacy_optimizer_conservative_replay.md). The final replay abstains on every detected drift; zero wrong attributions here does not demonstrate successful identification. Median shared fitting-plus-V2 cost is 4.097 s per trial. The 16 trial wall times sum to 67.60 s. Conditional V3 geometric-processing median is 0.0396 s.

## Historical V2 numbers are not a matched V3 test

The historical V2 result is reproduced as 29/48 detections, 0/54 no-change alarms, 1/48 exact attribution and 3/102 wrong attribution; its sequential monitor reports 17/24 persistent alarms and 0/18 temporary alarms. Different recordings/replicate counts and the changed development role prevent interpreting 27/32 versus 29/48 as an independent V3 improvement. The existing sequential monitor is reused; no improved V3 temporal detection rate is established.

The data support an executable, more explicit geometric ambiguity analysis and a conservative attribution contract. They do not establish better exact real-sensor fault attribution, accepted physical update accuracy, publication novelty or independent validation readiness.
