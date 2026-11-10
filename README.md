# Camera–LiDAR Simulation Lab

A standalone, configuration-driven simulator for camera–LiDAR calibration experiments. It uses Blender scenes for RGB, the same evaluated geometry for independent LiDAR intersections, five time-dependent scanning profiles, and separate inference/evaluation data. The calibration optimizer and fault-aware research project remain independent and unmodified.

**Current host constraint:** Windows blue screens were reported on 5 November 2026. New native rendering and GPU use are disabled by default; no further Blender or WSL jobs are being run in this session. Process-local CPU thread counts are one, simulator CLI jobs are serialized, and large per-capture allocations are capped. These controls do not establish that the underlying Windows crash cause is resolved. See [progress and remaining work](docs/IMPLEMENTATION_PROGRESS.md).

## Start locally

The existing `.venv` was created with access to the machine's already-installed scientific packages. No global package upgrade was performed. From this project directory:

```powershell
.\.venv\Scripts\python.exe -m simulator --help
.\.venv\Scripts\python.exe -m simulator verify outputs/warehouse_avia_v2
.\.venv\Scripts\python.exe -m simulator dataset-view outputs/warehouse_avia_v2
```

Double-click `start_simulator.bat` to start the browser app (it opens http://127.0.0.1:8765). Setup picks the environment, LiDAR and camera; the Studio places the rig and captures; Mass capture runs every combination.

To install into a fresh project-local environment on another machine:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

The Livox pattern arrays and MIT attribution ship as package data. Blender is an external application, and ROS is optional. Scene-generation scripts, configuration presets and documentation live in the source checkout; retain the checkout for rendering, even when using an installed Python package.

## Existing verified examples

These paths are local generated artifacts, excluded from Git. Run `verify` before using a dataset; a manifest's presence alone is insufficient after an interrupted host session.

| Example | Local run |
|---|---|
| Avia, fisheye, three capture windows | `outputs/warehouse_avia_v2` |
| Mid-360, same scene/camera conditions | `outputs/five_lidars_v2/livox_mid360` |
| VLP-16, same scene/camera conditions | `outputs/five_lidars_v2/velodyne_vlp16` |
| OS1-64, same scene/camera conditions | `outputs/five_lidars_v2/ouster_os1_64` |
| AT128, existing rendered RGB reused without new rendering | `outputs/hesai_recovered_existing_rgb` |
| Noisy pinhole / VLP-16 in laboratory | `outputs/noisy_pinhole` |
| Tiny CPU sequence with a physical rotation event | `outputs/cpu_check` |

The earlier AT128 run in `five_lidars_v2/hesai_at128` contains damaged metadata and is **invalid**. Other earlier runs without valid manifests are retained as diagnostics. [Machine-readable verification](docs/DATASET_VERIFICATION.json) records the audit.

## Generate and inspect

The small diagnostic preset requires the existing exported warehouse mesh. It produces geometry-shaded RGB, explicitly not a photorealistic image:

```powershell
.\.venv\Scripts\python.exe -m simulator generate configs/experiments/cpu_check.yaml --output outputs/my_cpu_check
.\.venv\Scripts\python.exe -m simulator verify outputs/my_cpu_check
```

Reuse existing Cycles RGB without launching Blender or touching the GPU:

```powershell
.\.venv\Scripts\python.exe -m simulator generate configs/experiments/reuse_warehouse_rgb.yaml --output outputs/my_existing_rgb
```

This checks the camera origin against cubemap metadata. A changed physical camera origin requires different rendered images. Camera rotation and lens remapping can reuse a full cubemap only when its optical centre is unchanged.

`batch CONFIG --output NEW_FOLDER` runs all five sensors with shared scene, camera, seed and capture conditions. Common range limits and `stride` are retained; unsupported sensor-specific options are not transferred. Output destinations must be new, preserving previous experiments.

The `warehouse_avia.yaml`, `longitudinal_drift.yaml` and `noisy_pinhole.yaml` presets describe Cycles generation. They currently stop before rendering unless explicitly enabled. CPU rendering requires `--allow-render --device CPU`; GPU additionally requires `--allow-gpu` and an explicit GPU device. Do not resume native rendering on this host until its stability issue is investigated. [Rendering details](docs/RENDERING.md) describe the already-generated scenes and historical render checks.

## Sensor and camera controls

Select exactly one of `livox_avia`, `livox_mid360`, `velodyne_vlp16`, `ouster_os1_64`, `hesai_at128`. Livox uses ordered official reference patterns rather than random field-of-view samples. VLP-16 uses its firing-order elevation table. OS1 and AT128 are explicitly nominal models. See [sources, timing and fidelity](docs/SENSOR_MODELS.md).

Camera configuration takes `model: fisheye` or `pinhole`, `width`, `height`, `K` or `focal_px`, and `D`. Pinhole D is `[k1,k2,p1,p2,k3]` (four coefficients also accepted); fisheye D is `[k1,k2,k3,k4]`. K must have zero skew. Fisheye distortion must be monotonic over the supported forward hemisphere; unsupported/invertible domains are rejected or masked rather than silently warped. The core camera geometry is global-shutter and static within a scan window.

`lidar_pose: {xyz: [...], rpy_deg: [...]}` sets the world rig pose; `poses` can supply one full `T_WL` matrix per capture. `T_CL` controls the relative mounting. `lidar_options` supports `stride`, `range_min_m`, `range_max_m` and profile-specific scan options. `duration`, `interval`, `start_time`, `captures` and `seed` control the experiment. Resource limits are one million emitted beams and 1,048,576 camera pixels per capture; use shorter windows or explicit beam subsampling for larger accumulations.

`noise` supports `range_std_m`, `range_std_per_m`, `angular_std_deg`, `dropout`, `dropout_per_m`, `range_quantization_m`. Camera degradation supports `noise_std` in 8-bit units, `blur_sigma`, `jpeg_quality`, `exposure_stops`, `white_balance` RGB gains. These are documented approximations, not validated sensor physics.

## Fault experiments

The browser's batch settings include **Vary camera intrinsics between batches** (off by default).
Batch 1 uses the nominal camera. Later batches independently sample bounded offsets from nominal
for fx/fy (default ±0.3%), cx/cy (default ±0.5 pixels), and optionally distortion k1 (default 0/off).
Intrinsics remain fixed within each batch; these are step changes, not cumulative drift or a validated
thermal camera model. Mount variation can be enabled independently. Set the limits before creating
batches, then inspect the intrinsics displayed in each batch heading; recreate batches to change them.
The selected camera is used for thumbnails, image formation, geometry and verification.

Saved YAML uses optional `cameras`, one complete camera configuration per capture, retaining the
baseline camera model and image dimensions. The nominal `camera` still defines the algorithm's
starting calibration. Exact per-capture K/D are in `evaluation/ground_truth.json`, and batch K/D are
also in `evaluation/batches.json`; `same_calibration` checks both intrinsics and extrinsics. Explicit
fault events apply on top of the selected capture camera. An existing running app must be restarted
after its job finishes to load updated Python code.

`initial_fault` changes only the estimate supplied to the calibration algorithm. `events: [{time: 2.0, label: rotation_only, fault: {...}}]` changes the true sensor configuration and regenerates measurements. The latest event's fault is applied relative to the baseline, not cumulatively. Use an empty fault to restore baseline. Events must fall outside or on scan-window boundaries; within-window changes and motion distortion are unsupported.

Fault fields are `rotation_deg` XYZ Euler angles, `translation_m` in camera coordinates, `focal_scale` scalar or `[sx,sy]`, `principal_offset_px`, `distortion_delta`. Rotation left-multiplies `R_CL` around the LiDAR origin; translation is then added independently to `t_CL`. This convention can move the camera centre during a nominal rotation fault. No-fault, extrinsic-only, intrinsics-only and combined experiments use the same interface.

## Mass capture

Setup, card 5, **Open mass capture…** captures every combination you tick: environments x LiDARs x camera
model and image resolution (chosen per camera) x camera-intrinsics drift (off, on, or both). Pick the save
folder first (section 1); **Scan this folder** lists what is already saved there (LiDAR, camera, environment,
drift, batches x captures, samples, finished or not).

Every configuration is its own self-contained run folder saved directly inside the folder you chose, exactly
like a single capture, with no wrapper folder:

```text
<chosen folder>/
  warehouse_avia_fish_1024x768_fixed_25/   one normal dataset per configuration (inference/ + evaluation/)
  warehouse_avia_fish_1024x768_drift_25/   "fixed" = nominal intrinsics, "drift" = later batches drift,
                                           the last number = captures per run
  _incomplete/                             unfinished attempts that were moved aside (never deleted)
```

Each run holds its own identity (`evaluation/config.json`, key `mass`), its true calibrations
(`evaluation/batches.json`, `nominal_calibration.json`, `ground_truth.json`) and
`evaluation/intrinsics_by_batch.csv` (true fx, fy, cx, cy, k1 per batch and their change from nominal).

**Stopped or failed half way?** Open Mass capture again with the same options and the same folder. Runs that are
already saved with the same settings are recognised and skipped, and only the missing configurations are captured. An
unfinished run can be **continued** (the default: its finished captures are kept and only the remaining ones are produced,
so the result is identical to a run that never stopped) or **redone** from the start (the unfinished attempt is moved to
`_incomplete/`, never deleted). A run made with different settings is always redone. Continuing uses
`python -m simulator generate <config> --resume`. Existing data is never overwritten: a folder with the same
name but different settings is left alone, and if you untick "Skip configurations that are already saved here" a
configuration is saved again as a new copy (`..._v2`, `..._v3`). The pose seed is automatic (the same options always give
the same poses, so a rerun matches the earlier runs); type a number to get a different set.

Poses and simulated mount changes are shared by every sensor and resolution of an environment, and a drift/fixed
pair differs only in intrinsics. Focal length scales with the width, keeping the field of view. The Studio follows
along (scene, LiDAR, camera, pose, mount and the true intrinsics of the current batch) unless you untick the live option, and a
progress panel shows an overall bar, a bar for the current configuration, and every configuration with its status. A failed
configuration is recorded and the rest continue. Every batch run also saves `evaluation/nominal_calibration.json` and, in
`batches.json`, `change_from_nominal`. Only the cube faces a camera actually samples are rendered (identical image, fewer
Blender renders). The simulator runs one job at a time, so a mass capture occupies it until it finishes; Cancel stops it and
the runs already saved stay. Restart the app after its current job finishes to load new features.

## Data boundary and evaluation

```text
run/
  inference/                         measurements: all an algorithm may read
    initial_calibration.json         starting (possibly faulty) calibration
    sequence.json                    capture ids, timestamps (and batch number)
    capture_0000/                    one folder per capture (0001, 0002, ...)
      image.png                      camera RGB
      lidar.npz  cloud.pcd           LiDAR snapshot (default 0.1 s)
      lidar_accumulated.npz          LiDAR integrated over `accumulate_s`
      cloud_accumulated.pcd          (default 1 s; the GUI sets it on; absent if unset)
      lidar_metadata.json            sensor, noise, point counts, timing
  evaluation/                        ground truth: never given to an algorithm
    ground_truth.json                poses, true T_CL and camera K per capture
    events.json  config.json         faults, exact settings used
    batches.json                     (batch runs) capture ids, true T_CL and K/D of each batch, change_from_nominal
    nominal_calibration.json         (batch runs) the nominal T_CL and camera the changes are measured from
    manifest.json                    file checksums, timing, limitations
    capture_0000/
      ideal_lidar.npz                noise-free LiDAR (snapshot)
      ideal_lidar_accumulated.npz    noise-free LiDAR (accumulated)
      camera_geometry.npz            exact per-pixel depth, normals, object ids
      calibration_overlay.png        LiDAR projected onto the image
      pointcloud_preview.png         top-down view
      verification.json              projection check
      cube_*.png, blender.log, ...   Blender render files (Blender renderer only)
```

Captures sit directly under `inference/` and `evaluation/`; there are no nested `captures/` or `cubemap/` folders. Older runs that used `captures/<id>/` are still read. Livox Avia and Mid-360 are non-repetitive scanners, so a 0.1 s snapshot covers only part of the field of view; the accumulated 1 s cloud (static rig) covers it much more fully. The app animates this filling-in on the Setup tab and on the Studio floor plan.

Only the inference tree is supplied to an algorithm. Ideal depths, normals, object IDs, true calibration and fault labels stay in evaluation. Images on disk are RGB PNG; OpenCV reads them as BGR. `lidar.npz` stores XYZ in L metres, absolute per-point seconds, actual and nominal directions, channels, intensity and global beam IDs. PCD points are in metres. Camera geometry stores ray distance and optical-axis Z-depth separately, normals in C and integer object IDs. Missing depth is NaN; missing segmentation is -1.

World and LiDAR use +X forward, +Y left, +Z up. OpenCV camera uses +X right, +Y down, +Z forward. `T_AB` maps B to A, so **`T_CL = inverse(T_WC) @ T_WL`** and `p_C = R_CL @ p_L + t_CL`. All transforms use column-vector convention and metres. Blender camera conversion flips its Y and Z axes, preserving handedness.

`verify` reloads images/clouds, compares PCD with NPZ, checks timestamps/rays/transforms/depth semantics and checks file hashes. Visibility verification recasts from the camera at continuous projected pixels to distinguish camera occlusion from LiDAR visibility. Numerical tests, not overlays alone, establish these checks.

`evaluate RUN ESTIMATES.json --output REPORT.json` evaluates external estimates. Records contain `capture_id`, `calibration` in the initial-calibration JSON layout, optional Boolean `detected` and `update_accepted`. It reports rotation/translation/intrinsic errors, common-point reprojection RMSE, stable-period false alarms/updates and sampled detection delay. It does not implement the fault-aware inference algorithm or infer uncertainty/convergence from unavailable solver data.

## Calibration optimizer and ROS1

```powershell
.\.venv\Scripts\python.exe -m simulator export outputs/warehouse_avia_v2 outputs/my_pairs --format paired
.\.venv\Scripts\python.exe -m simulator export outputs/warehouse_avia_v2 outputs/my_stacks --format stacked
```

Paired export uses RGB images and metre PCDs. Stacked export uses BGR `image`, float32 `xyz_mm`, `intensity`, `frame`, `frame_time`, plus preserved `point_time`; it does not clip coordinates to int16. Exporters never read evaluation truth.

The cloned optimizer successfully ingested three generated Avia captures. A full solver attempt is deferred under the host-stability constraint. Its current model is fisheye k1/k2; the integration tool rejects pinhole and nonzero k3/k4 instead of reinterpreting them. [ROS and optimizer instructions](docs/INTEGRATION.md) cover optional Noetic publishing/bags, explicit ground-truth TF mode and verification limits. ROS/WSL never start automatically during generation.

## Verification and remaining limits

Run small CPU tests with `.\.venv\Scripts\python.exe -m pytest -q`. The suite covers ray fixtures, independent occlusions, transform/projection round trips, all five export pipelines, reproducibility, noise, initialization versus physical faults, inference separation, adapter units, cubemap seams and rendering guards. [Progress](docs/IMPLEMENTATION_PROGRESS.md) and [verification report](docs/VERIFICATION_REPORT.md) distinguish completed checks from deferred work.

The four `.blend` scenes are editable detailed procedural environments, with a licensed HDRI for urban lighting. Their visual realism remains below the requested publication standard. Physical sensor validation, indefinitely nonrepetitive Livox timing, complete Avia repetitive mode, hardware angle corrections, motion distortion, weather/scattering/multipath/multiple returns, full solver/ROS/GUI end-to-end checks and performance benchmarking remain unfinished. No publishable benchmark claim is made.
