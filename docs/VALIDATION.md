# Validation scope

Recorded checks used the included camera–LiDAR integration for [Sensor_Computer](https://github.com/maninka123/Sensor_Computer), with ROS 1 topics on Windows and Python 3.10. Configure the topics, camera model, frames and device integration for another setup.

## Updated results and interface preview

[The ten-capture example](RESULTS.md) includes all-edge RMSE, per-option projection movement, matrix previews and compact evidence tables. RMSE fell from **20.54 px to 14.78 px** with alignment only; the final verdict was still **Large change**.

The new screenshots and RMSE calculation come from the updated development build. This documentation update leaves the published application source unchanged. The three-capture evaluation below describes the earlier source revision.

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

- 28 automated checks: update selection, insufficient evidence, invalid lens fits, fixed parameter groups, inverse-pose geometry, dropdown consistency, source opening, table alignment, responsive pose layout, capture folder/array formats and unclipped help tabs. Paired imports also cover both folder layouts, nested/incomplete captures, unmatched files, ambiguous names, all three standard PCD encodings, missing intensity, unreadable files, image resolution, unit checks, UI gating and solver input preparation.
- Native Windows application/window icons and explicit taskbar identity checked.
- Full app startup, screenshot capture and clean shutdown checked.
- Saved-run views rendered and inspected; older comparison plots refreshed.

No calibration was applied to live hardware during these checks. SSH write, backup and restore operations require a connected device and explicit review.

The same three recorded captures were also exported to PNG and binary-compressed PCD in metres, then run through paired import and the complete comparison pipeline. The check completed with the same **Borderline** verdict and 1.41 px median candidate shift. This verifies the import route; it is not an independent calibration accuracy benchmark.

## Decision limits

Comparison uses a minimum one-percentage-point gain, a paired two-standard-error heuristic and a majority of improved folds. A joint update must beat both simpler update choices. Overlapping image regions are not independent observations, so this is not a formal confidence interval.

Repeated captures of one static scene cannot independently establish a lens change. Scene geometry, incorrect intrinsics and alignment can compensate for one another. Use diverse captures and inspect the mounting when changes are large.
