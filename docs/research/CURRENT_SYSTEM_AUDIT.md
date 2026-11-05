# Current system audit

Audited 5 November 2026. This is a source and local-recordings audit, not a new accuracy benchmark. The original maintenance project was inspected read-only. No calibration, hardware, recording or accepted result was changed.

## Reproducible baseline

The new research checkout starts from public commit `d0931889bf2f2a5ecb2cca9dd3c8a77c9fa8c763`, on branch `research/fault-aware-calibration`. That commit updates documentation, results and images; it does **not** contain all implementation changes used by its development-preview screenshots. Its own `docs/VALIDATION.md` explicitly records the distinction.

Later executable checks distinguish installed OpenCV distribution metadata from the imported binary: `cv2.__version__` is **4.8.1**, while opencv-python 4.7.0.72, opencv-contrib-python 4.8.1.78 and opencv-python-headless 4.10.0 metadata coexist. The environment list below reflects the original distribution-level audit. Recorded research artifacts use the imported version; no global OpenCV installation was changed during this continuation.

Environment actually used: Windows build 26300, Anaconda Python 3.10.14, NumPy 1.26.4, SciPy 1.10.1, OpenCV Python 4.7.0.72, PyYAML 6.0.3, Matplotlib 3.7.0, rosbags 0.10.8 and pypcd4 1.5.1. Python executable: `C:/Users/Pasindu/anaconda3/python.exe`. The checkout's pinned ranges admit these versions. `settings.py` sets BLAS thread defaults to one before importing NumPy because the existing environment has a documented BLAS/OpenCV stability concern.

Executed before research-engine edits:

```powershell
# From Fault-aware calibration/repository
python -B -m unittest discover -s "Calibration maintenance/code/tests"
# Ran 28 tests in 0.521s: OK

# From the original workspace (read-only comparison)
python -B -m unittest discover -s "Calibration maintenance/code/tests"
# Ran 56 tests in 0.867s: OK
```

The 28 committed checks cover constrained selection, invalid fits, fixed parameter groups, geometry/UI controls, capture handling and paired image/PCD import. They are regression checks, not evidence of fault-identification accuracy, covariance coverage or observability guarantees. No independent targetless test suite was found in the checkout.

## Existing numerical pipeline

`Targetless calibration/code/calib.py` defines thirteen parameters:

`wx wy wz tx ty tz fx fy cx cy k1 k2 delta`.

Rotation is a left increment on a mounting rotation, `R = Exp(w) R0`. Translation is in metres and the saved transform is **LiDAR to camera**, `p_camera = R p_lidar + t`. The inverse camera centre is `-R.T @ t`; translation entries are not camera position. `delta` is a sensor-specific angular widening nuisance on depth discontinuities.

The camera projection is OpenCV's equidistant/fisheye polynomial, not a general pluggable projection family. The original solver estimates k1/k2, with k3/k4 zero. It requires front-facing points and a detected circular image region. Supporting another projection family requires an explicit adapter, derivative validation and a separate input/configuration check.

`lidar_edges.py` extracts depth, plane-crease and reflectivity edges on a spherical grid, checks first/second-half consistency, estimates line directions and subsamples features. Angular bounds, minimum range and beam modelling contain assumptions for the existing sensor. They are configurable in part, but this is not demonstrated arbitrary-LiDAR validation. `image_edges.py` uses Canny, gradient directions and a subpixel peak offset.

`associate()` finds a nearest image edge with distance and orientation gates. `refine()` alternates association and fixed-correspondence point-to-image-edge-normal residual minimization, with Cauchy IRLS weights and principal-point/aspect priors. Gates narrow progressively and release more parameters. Coarse edge-distance and normalized information distance proposals supply starts; edge-alignment lift ranks solutions. The Gauss–Newton standard deviations use the final weighted Jacobian and a residual-scale approximation, conditional on selected correspondences and the model.

`step1_calibrate.py` searches mounting/focal hypotheses, jointly refines, checks NID agreement, compares k1 versus k1/k2 and exports calibration JSON/TXT. `step2_compare.py` contains an independently obtained checkerboard comparison route; merely having this route does not supply ground truth for every maintenance recording. `full_calibration.py` runs the existing scratch solver and supplies that result as an additional start for a subsequent joint maintenance check.

`Calibration maintenance/code/update_options.py` already compares keep, extrinsic, intrinsic and full updates. Each comparison fold fits its nuisance baseline, proposals and constrained alternatives using training captures. It scores the intersection of points visible under all four models, requiring sufficient coverage. With at least three captures it leaves one capture out; otherwise it leaves image regions out. Selection uses a one-percentage-point minimum edge-share gain, gain exceeding two paired standard errors and a majority of improved folds. A joint update must outperform both simple updates. These are explicit decision heuristics, not posterior fault probabilities. Intrinsic/extrinsic compensation can leave several physical explanations unresolved.

## Published source versus local development source

The targetless `calib.py` files were byte-identical at audit time (SHA-256 `1a67418426330b57fe4c34dfbe1ad4662cb612825e788236eb16155cd306340a`). Maintenance files differ substantially. The development folder adds matrix previews, compact explanations, TXT calibration I/O, option calibrations/movement sidecars, and an all-edge RMSE calculation.

The important numerical difference is `maintenance_model.py`: it projects and preserves supplied k3/k4 while estimating k1/k2. The February reference has nonzero k3/k4. The public baseline instead ignores these terms during projection and its output logic can zero distortion terms for a model label other than its expected `k1`/`k1-k2`. A research adapter must preserve the supplied camera model and fixed parameter groups; the public workflow cannot be treated as a faithful higher-order reference-model baseline without identifying this mismatch. Keep a frozen legacy mode for comparison and distinguish compatibility corrections from research improvements.

The local development `edge_distance_metrics()` computes nearest-image-edge distances without the 2 px match gate. `rmse_changes()` pools squared distances and counts on identical held-out points, rather than averaging fold RMSE values. This calculation is absent from the audited public source. The ten-capture documentation's 20.54 → 14.78 px numbers come from that development implementation and saved sidecars, not from a newly executed benchmark here.

## Mathematical and validation limitations

- **Matched residuals are conditional.** `maintain.alignment()` reports residuals only for accepted distance/orientation matches. A median near 0.8 px can coexist with poor overall alignment because distant points are excluded. Each option may accept different matches. It is not an all-scene error.
- **Movement is separate from error.** Median/p90 pixel displacement compares candidate projections with reference projections on valid scene probes. It measures the proposed change, not residual misalignment or physical truth. Components do not add as scalar medians.
- **Nearest-edge RMSE is a proxy.** Un-gated nearest-edge distance includes formerly unmatched visible edges, but a nearby unrelated edge can still look good. This is not known-correspondence reprojection RMSE. Report visibility/coverage and edge support alongside it.
- **Selection and final sensitivity checks differ.** The option-comparison fits use training-only starts. In `maintain.py`, later jackknife refits start from the all-data `p_new`, and their baseline nuisance `p_old` was fitted on all data. The targetless scratch leave-one-out fits also start from an all-data solution. These are sensitivity diagnostics, not untouched predictive validation. Their region comparisons do not impose the option comparison's common visibility mask.
- **A development validation-range leak exists.** Higher-order development `compare()` calls `model.validation_angle(caps, parameters)` using all captures, including the test capture. A strict research split must determine that range from training only or from a predeclared camera domain.
- **Invisible residuals can vanish.** `edge_residuals()` returns zero for a projection becoming invalid during fixed-correspondence refinement. A research objective must stop invalid visibility from lowering its loss, for example with a finite penalty or constrained step. Association filtering alone does not guarantee this.
- **Uncertainty is conditional and dependent.** Taking the larger capture/region jackknife spread addresses one optimism source but does not establish calibrated intervals. Static captures, overlapping regions, shared association errors and shared priors remain dependent. A near-zero sensitivity spread cannot establish a confidently identified physical fault.
- **Raw parameter conditioning is unit-dependent.** Rotation, translation, pixels and polynomial coefficients need declared scales before information spectra or identifiable directions can be compared. Priors must be separated from measurement information; nuisance elimination and intrinsic/extrinsic ambiguity need explicit treatment.
- **No drift labels were verified.** Existing verdicts and filenames are not ground truth. Enclosure changes, reference age, camera-model mismatch, scene/feature changes and actual mounting changes may all contribute. A better edge score cannot by itself identify which physical component moved.

## Available real recordings

The path-only manifest is [`research_data/manifest.json`](../../research_data/manifest.json). Its `workspace_root_relative_to_repository` is `../..`; paths resolve relative to that workspace. It records hashes, point counts, dimensions and units for the two primary caches. No recordings were copied into this repository.

| ID | Local cache | Captures | Compressed bytes | Suggested use |
|---|---|---:|---:|---|
| `creep_three` | `Targetless calibration/stacked_data/creep_data` | 3 | 17,008,336 | Small backend smoke/integration evaluation |
| `enclosure_off_ten` | `Calibration maintenance/results/rig_20261104_174529/stacked/data` | 10 | 67,217,832 | Larger identical-input comparison |
| `enclosure_on_twelve` | `Calibration maintenance/results/rig_20261104_202917/stacked/data` | 12 | 70,421,453 | Additional recorded configuration |
| `october_device_one` | `Calibration maintenance/results/rig_20261104_220224/stacked/data` | 11 | 27,041,903 | Additional device/scene recording |
| `october_device_four` | `Calibration maintenance/results/rig_20261104_221306/stacked/data` | 15 | 54,053,136 | Additional device/scene recording |

NPZ inputs contain BGR uint8 images at 484 × 366, `xyz_mm` int16 points, intensity, per-point frame indices and frame timestamps. The existing loader converts millimetres to metres. A capture contains many accumulated scans, not one independent observation per point. The first three-capture file contains 970,185 points; the first ten-capture file contains 1,142,076. Temporal synchronization and physical-unit accuracy cannot be proven by these arrays alone.

Saved three-capture comparison: camera-only selected, final **BORDERLINE**, 1.4085 px candidate movement, 0.1856 px jackknife spread, 4/7 regions improved. Saved ten-capture comparison: extrinsic selected, final **LARGE CHANGE**, 18.6629 px movement, 0.6877 px spread, 5/9 regions improved. These are historical outputs inspected here, not new runs or independently verified accuracy. The ten-capture reference is the February four-term enclosure calibration while cache filenames say enclosure off; this context matters before interpreting the change as mounting drift.

No new simulated drift benchmark was run. Existing `creep_*_drift_test` outputs are deliberately excluded from primary real-data evaluation. Future tests must keep feature extraction, training selection, association, observability and hyperparameter tuning outside the held-out partition. All compared methods must use the same declared test points and report unavailable/failed folds rather than silently manufacturing improvement.
