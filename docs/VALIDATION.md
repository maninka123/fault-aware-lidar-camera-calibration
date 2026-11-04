# Validation scope

Developed for the FLIR Blackfly S + Livox Avia rig and ROS 1 topics supplied by [Sensor_Computer](https://github.com/maninka123/Sensor_Computer). The desktop checks were run on Windows with Python 3.10. Other hardware, ROS 2 and general camera models are unvalidated.

## Recorded-data check — 4 November 2026

Three stacked captures were compared using leave-one-capture-out fits. Every alternative was scored on common visible test points, without using an all-data solution to initialise the held-out fit.

| Alternative | Mean held-out alignment |
|---|---:|
| Keep current | 27.7% |
| Alignment only | 30.0% |
| Camera settings only | 32.7% |
| Camera + alignment | 32.6% |

Camera-only had the strongest supported score in this comparison. The additional image-region check improved in 4 of 7 regions, so the overall verdict remained **Borderline: collect more captures before updating**. These measurements are one dataset, not a general accuracy benchmark.

Alignment here means the share of visible LiDAR edges associated with a parallel image edge within 2 px. Image-overlay legends separately show the tighter 1 px threshold.

## Automated and visual checks

- 14 automated checks: update selection, insufficient evidence, invalid lens fits, fixed parameter groups, inverse-pose geometry, dropdown consistency, source opening, table alignment and responsive pose layout.
- Native Windows application/window icons and explicit taskbar identity checked.
- Full app startup, screenshot capture and clean shutdown checked.
- Saved-run views rendered and inspected; older comparison plots refreshed.

No calibration was applied to live hardware during these checks. SSH write, backup and restore operations require a connected device and explicit review.

## Decision limits

Comparison uses a minimum one-percentage-point gain, a paired two-standard-error heuristic and a majority of improved folds. A joint update must beat both simpler update choices. Overlapping image regions are not independent observations, so this is not a formal confidence interval.

Repeated captures of one static scene cannot independently establish a lens change. Scene geometry, incorrect intrinsics and alignment can compensate for one another. Use diverse captures and inspect the mounting when changes are large.
