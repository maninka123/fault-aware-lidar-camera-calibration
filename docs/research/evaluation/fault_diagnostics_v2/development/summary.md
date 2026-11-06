# Development round 3 (policy recomputed with the final development constants)

Trials: 104 (errors: 0). Rates with Wilson 95 % intervals (dependent trials: intervals are optimistic).

| Method | False alarm, nominal | False alarm, nuisance | Detection, drift | Correct attribution | Ambiguous incl. truth | Wrong attribution (all) | Updates on no-change |
|---|---|---|---|---|---|---|---|
| production | 0/6 (0 %, 0-39) | 0/48 (0 %, 0-7) | 13/48 (27 %, 17-41) | 3/48 (6 %, 2-17) | - | 10/102 (10 %, 5-17) | 0/54 (0 %, 0-7) |
| proposed | 0/6 (0 %, 0-39) | 1/48 (2 %, 0-11) | 34/48 (71 %, 57-82) | 1/48 (2 %, 0-11) | 18/48 (38 %, 25-52) | 5/102 (5 %, 2-11) | 0/54 (0 %, 0-7) |
| no_chance_correction | 0/6 (0 %, 0-39) | 3/48 (6 %, 2-17) | 36/48 (75 %, 61-85) | 3/48 (6 %, 2-17) | 16/48 (33 %, 22-47) | 4/102 (4 %, 2-10) | 0/54 (0 %, 0-7) |
| no_intensity_cue | 0/6 (0 %, 0-39) | 1/48 (2 %, 0-11) | 34/48 (71 %, 57-82) | 2/48 (4 %, 1-14) | 17/48 (35 %, 23-50) | 4/102 (4 %, 2-10) | 0/54 (0 %, 0-7) |
| no_quality_gating | 0/6 (0 %, 0-39) | 0/48 (0 %, 0-7) | 23/48 (48 %, 34-62) | 0/48 (0 %, 0-7) | 16/48 (33 %, 22-47) | 3/102 (3 %, 1-8) | 0/54 (0 %, 0-7) |
| no_robust_aggregation | 0/6 (0 %, 0-39) | 3/48 (6 %, 2-17) | 33/48 (69 %, 55-80) | 1/48 (2 %, 0-11) | 17/48 (35 %, 23-50) | 1/102 (1 %, 0-5) | 0/54 (0 %, 0-7) |
| no_reference_confirmation | 0/6 (0 %, 0-39) | 1/48 (2 %, 0-11) | 34/48 (71 %, 57-82) | 1/48 (2 %, 0-11) | 18/48 (38 %, 25-52) | 5/102 (5 %, 2-11) | 0/54 (0 %, 0-7) |
| no_nuisance_counterfactual | 0/6 (0 %, 0-39) | 1/48 (2 %, 0-11) | 34/48 (71 %, 57-82) | 1/48 (2 %, 0-11) | 18/48 (38 %, 25-52) | 5/102 (5 %, 2-11) | 0/54 (0 %, 0-7) |

## Status counts by condition (proposed and production)

| Condition | Production | Proposed |
|---|---|---|
| drift:I_focal:0.02 | INSUFFICIENT_EVIDENCE 5, KEEP_CURRENT 1 | DRIFT_AMBIGUOUS 3, NUISANCE_SUSPECTED 3 |
| drift:I_pp:3.0 | INSUFFICIENT_EVIDENCE 3, KEEP_CURRENT 3 | DRIFT_AMBIGUOUS 4, KEEP_CONFIRMED 1, NUISANCE_SUSPECTED 1 |
| drift:R:0.5 | INSUFFICIENT_EVIDENCE 5, KEEP_CURRENT 1 | DRIFT_AMBIGUOUS 6 |
| drift:R:1.0 | INSUFFICIENT_EVIDENCE 5, KEEP_CURRENT 1 | DRIFT_AMBIGUOUS 4, DRIFT_SUPPORTED 1, NUISANCE_SUSPECTED 1 |
| drift:RT:(0.5, 0.03) | INSUFFICIENT_EVIDENCE 3, KEEP_CURRENT 3 | DRIFT_AMBIGUOUS 5, NUISANCE_SUSPECTED 1 |
| drift:T:0.03 | INSUFFICIENT_EVIDENCE 4, KEEP_CURRENT 2 | DRIFT_AMBIGUOUS 2, DRIFT_SUPPORTED 1, KEEP_CONFIRMED 1, NUISANCE_SUSPECTED 2 |
| drift:T:0.06 | INSUFFICIENT_EVIDENCE 2, KEEP_CURRENT 4 | DRIFT_AMBIGUOUS 4, KEEP_CONFIRMED 2 |
| drift_nuisance:spurious_lines_all | INSUFFICIENT_EVIDENCE 5, KEEP_CURRENT 1 | DRIFT_AMBIGUOUS 1, DRIFT_SUPPORTED 3, NUISANCE_SUSPECTED 2 |
| nominal | INSUFFICIENT_EVIDENCE 3, KEEP_CURRENT 3 | KEEP_CONFIRMED 3, NUISANCE_SUSPECTED 3 |
| nuisance:blur_all | INSUFFICIENT_EVIDENCE 3, KEEP_CURRENT 3 | DRIFT_SUPPORTED 1, KEEP_CONFIRMED 3, NUISANCE_SUSPECTED 2 |
| nuisance:desync_one | INSUFFICIENT_EVIDENCE 2, KEEP_CURRENT 4 | KEEP_CONFIRMED 4, NUISANCE_SUSPECTED 2 |
| nuisance:ghost_all | INSUFFICIENT_EVIDENCE 3, KEEP_CURRENT 3 | KEEP_CONFIRMED 3, NUISANCE_SUSPECTED 3 |
| nuisance:ghost_one | INSUFFICIENT_EVIDENCE 3, KEEP_CURRENT 3 | KEEP_CONFIRMED 3, NUISANCE_SUSPECTED 3 |
| nuisance:lidar_dropout_all | INSUFFICIENT_EVIDENCE 4, KEEP_CURRENT 2 | KEEP_CONFIRMED 2, NUISANCE_SUSPECTED 4 |
| nuisance:low_light_all | KEEP_CURRENT 6 | KEEP_CONFIRMED 6 |
| nuisance:occlusion_all | KEEP_CURRENT 6 | KEEP_CONFIRMED 6 |
| nuisance:spurious_lines_all | KEEP_CURRENT 6 | KEEP_CONFIRMED 6 |

Median production seconds per trial: 4.2; added diagnostics: 0.8 s; extra fits: 13.
