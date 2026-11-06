# Held-out evaluation (preregistered, commit 5125560)

Trials: 104 (errors: 0). Rates with Wilson 95 % intervals (dependent trials: intervals are optimistic).

| Method | False alarm, nominal | False alarm, nuisance | Detection, drift | Correct attribution | Ambiguous incl. truth | Wrong attribution (all) | Updates on no-change |
|---|---|---|---|---|---|---|---|
| production | 3/6 (50 %, 19-81) | 9/48 (19 %, 10-32) | 16/48 (33 %, 22-47) | 4/48 (8 %, 3-20) | - | 24/102 (24 %, 16-33) | 0/54 (0 %, 0-7) |
| proposed | 0/6 (0 %, 0-39) | 0/48 (0 %, 0-7) | 29/48 (60 %, 46-73) | 1/48 (2 %, 0-11) | 18/48 (38 %, 25-52) | 3/102 (3 %, 1-8) | 0/54 (0 %, 0-7) |
| no_chance_correction | 0/6 (0 %, 0-39) | 0/48 (0 %, 0-7) | 28/48 (58 %, 44-71) | 1/48 (2 %, 0-11) | 20/48 (42 %, 29-56) | 0/102 (0 %, 0-4) | 0/54 (0 %, 0-7) |
| no_intensity_cue | 0/6 (0 %, 0-39) | 0/48 (0 %, 0-7) | 42/48 (88 %, 75-94) | 0/48 (0 %, 0-7) | 30/48 (62 %, 48-75) | 3/102 (3 %, 1-8) | 0/54 (0 %, 0-7) |
| no_quality_gating | 0/6 (0 %, 0-39) | 0/48 (0 %, 0-7) | 26/48 (54 %, 40-67) | 0/48 (0 %, 0-7) | 19/48 (40 %, 27-54) | 1/102 (1 %, 0-5) | 0/54 (0 %, 0-7) |
| no_robust_aggregation | 0/6 (0 %, 0-39) | 0/48 (0 %, 0-7) | 31/48 (65 %, 50-77) | 1/48 (2 %, 0-11) | 19/48 (40 %, 27-54) | 2/102 (2 %, 1-7) | 0/54 (0 %, 0-7) |
| no_reference_confirmation | 0/6 (0 %, 0-39) | 0/48 (0 %, 0-7) | 29/48 (60 %, 46-73) | 1/48 (2 %, 0-11) | 18/48 (38 %, 25-52) | 3/102 (3 %, 1-8) | 0/54 (0 %, 0-7) |
| no_nuisance_counterfactual | 0/6 (0 %, 0-39) | 0/48 (0 %, 0-7) | 29/48 (60 %, 46-73) | 1/48 (2 %, 0-11) | 18/48 (38 %, 25-52) | 3/102 (3 %, 1-8) | 0/54 (0 %, 0-7) |

## Status counts by condition (proposed and production)

| Condition | Production | Proposed |
|---|---|---|
| drift:I_focal:0.02 | INSUFFICIENT_EVIDENCE 6 | DRIFT_AMBIGUOUS 2, NUISANCE_SUSPECTED 4 |
| drift:I_pp:3.0 | INSUFFICIENT_EVIDENCE 3, KEEP_CURRENT 3 | DRIFT_AMBIGUOUS 4, KEEP_CONFIRMED 2 |
| drift:R:0.5 | INSUFFICIENT_EVIDENCE 3, KEEP_CURRENT 3 | DRIFT_AMBIGUOUS 3, KEEP_CONFIRMED 1, NUISANCE_SUSPECTED 2 |
| drift:R:1.0 | INSUFFICIENT_EVIDENCE 3, KEEP_CURRENT 3 | DRIFT_AMBIGUOUS 4, DRIFT_SUPPORTED 1, NUISANCE_SUSPECTED 1 |
| drift:RT:(0.5, 0.03) | INSUFFICIENT_EVIDENCE 4, KEEP_CURRENT 2 | DRIFT_AMBIGUOUS 2, DRIFT_SUPPORTED 2, NUISANCE_SUSPECTED 2 |
| drift:T:0.03 | INSUFFICIENT_EVIDENCE 3, KEEP_CURRENT 3 | DRIFT_AMBIGUOUS 1, KEEP_CONFIRMED 2, NUISANCE_SUSPECTED 3 |
| drift:T:0.06 | INSUFFICIENT_EVIDENCE 3, KEEP_CURRENT 3 | DRIFT_AMBIGUOUS 4, DRIFT_SUPPORTED 1, NUISANCE_SUSPECTED 1 |
| drift_nuisance:spurious_lines_all | INSUFFICIENT_EVIDENCE 3, KEEP_CURRENT 3 | DRIFT_AMBIGUOUS 5, NUISANCE_SUSPECTED 1 |
| nominal | INSUFFICIENT_EVIDENCE 3, KEEP_CURRENT 3 | KEEP_CONFIRMED 3, NUISANCE_SUSPECTED 3 |
| nuisance:blur_all | INSUFFICIENT_EVIDENCE 3, KEEP_CURRENT 3 | KEEP_CONFIRMED 3, NUISANCE_SUSPECTED 3 |
| nuisance:desync_one | INSUFFICIENT_EVIDENCE 3, KEEP_CURRENT 3 | KEEP_CONFIRMED 3, NUISANCE_SUSPECTED 3 |
| nuisance:ghost_all | INSUFFICIENT_EVIDENCE 3, KEEP_CURRENT 3 | KEEP_CONFIRMED 3, NUISANCE_SUSPECTED 3 |
| nuisance:ghost_one | INSUFFICIENT_EVIDENCE 3, KEEP_CURRENT 3 | KEEP_CONFIRMED 3, NUISANCE_SUSPECTED 3 |
| nuisance:lidar_dropout_all | INSUFFICIENT_EVIDENCE 2, KEEP_CURRENT 4 | KEEP_CONFIRMED 4, NUISANCE_SUSPECTED 2 |
| nuisance:low_light_all | KEEP_CURRENT 6 | KEEP_CONFIRMED 6 |
| nuisance:occlusion_all | KEEP_CURRENT 6 | KEEP_CONFIRMED 6 |
| nuisance:spurious_lines_all | KEEP_CURRENT 6 | KEEP_CONFIRMED 6 |

Median production seconds per trial: 6.9; added diagnostics: 1.1 s; extra fits: 7.
