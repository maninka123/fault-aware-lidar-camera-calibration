# Simulator datasets, processed with the app's own algorithms

`tools/process_simulator_run.py` runs a run folder made by the Camera-LiDAR Simulation Lab (batches of captures whose camera-LiDAR mount and
camera intrinsics change between batches, with exact ground truth) through the application's existing pipeline. It implements **no new
calibration algorithm**: it converts the data to the app's stacked-capture format, calls the app's initializer and checks, and scores the
results against the simulator's ground truth, which is never given to any algorithm.

```text
python tools/process_simulator_run.py "<path to the simulator run folder>"
```

Stages (each is skipped when its output exists, so a run can be resumed): `convert`, `initial` (calibrate from scratch on batch 1), `check`
(each later batch, one at a time: fault-aware `assess`, the maintenance comparison, experimental V3 `diagnose-v3`), `control` (the same checks
from the simulator's own initial calibration), `score`. Select stages with `--stages convert,initial,...`; skip the control with
`--skip-control`. Outputs go to `research_artifacts/simulator/<dataset>/` (not committed), including `results.md` and `results.json`.

## First result (preliminary)

[warehouse_20261109_135624_25_results.md](warehouse_20261109_135624_25_results.md): one simulated warehouse run, 5 batches of 5 captures with
mount changes of 0.2-0.55 degrees and 3.5-5.2 mm, no intrinsics drift, 64 samples.

* **Initial calibration from batch 1 (the app's targetless initializer):** the app rates the result unreliable for this simulated fisheye camera,
  and its own assessments reject it, so none of the per-batch checks could run from it. The initializer's rotation error against truth is near 180
  degrees, which may partly be a frame-convention difference between the app's output and the simulator's transform; this has not been ruled out.
* **Control (the simulator's exact batch-1 calibration):** the fault-aware check returned `INSUFFICIENT_EVIDENCE` for every batch (it abstained and
  kept the calibration), the maintenance comparison produced no usable fit, and the experimental V3 diagnosis returned `DRIFT_AMBIGUOUS` or
  `NUISANCE_SUSPECTED`. The true changes are small (below about 0.6 degrees / 5.2 mm), so abstaining is the conservative outcome, not yet a
  measured detection rate.

These are the unmodified algorithms on one dataset. The comparison across datasets, sensors and camera settings, and any conclusion for the
paper, come later.
