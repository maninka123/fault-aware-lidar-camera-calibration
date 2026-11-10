# Verification report — 5 November 2026

This report describes observed results, not the full requested platform's completion. Native rendering and system-level tests were stopped after the user's Windows-stability request. Subsequent checks used small CPU-only jobs with one thread and existing rendered images. No driver, Windows, WSL or ROS configuration repair was attempted.

## Automated checks

**105 tests passed in 3.67 seconds**, with the exact JUnit record in [TEST_RESULTS.xml](TEST_RESULTS.xml). These are functional tests, not a sustained-load or hardware stability benchmark.

Coverage includes analytical ray/plane distances; independent sensor-origin occlusions; SE(3) round trips and handedness; OpenCV projection/inverse projection; five scan schedules and half-open accumulation windows; deterministic noise; all five complete tiny CPU export pipelines; incorrect initialization versus physical changes; measurement/evaluation separation; PCD/NPZ units; ROS-independent message conversion helpers; cubemap seams and OpenCV remap-size regression; disabled-by-default rendering; exclusive job locking; and large-allocation rejection.

Python source files under `simulator`, `tools`, `blender`, and `ros1/scripts` passed AST syntax checks. CLI help was exercised. The Tk GUI and dataset viewer have not been interactively exercised. The current source is newer than the earlier wheel portability test, so that wheel is not a final release artifact.

## Reloaded generated data

Every successful run below passed image/cloud reload, PCD-to-NPZ agreement, timestamps, unit ray directions, transform consistency, depth semantics and complete manifest hash checks. [DATASET_VERIFICATION.json](DATASET_VERIFICATION.json) contains per-capture details and the explicitly failed run.

| Sensor / experiment | Run | Captures | Valid returns per capture | Shared ideal points visible to camera |
|---|---|---:|---|---|
| Avia fisheye | `outputs/warehouse_avia_v2` | 3 | 24,000 each | 23,751 / 23,784 / 23,802 |
| Avia shared comparison | `outputs/five_lidars_v2/livox_avia` | 3 | 24,000 each | 23,751 / 23,784 / 23,802 |
| Mid-360 | `outputs/five_lidars_v2/livox_mid360` | 3 | 15,441 / 15,461 / 15,461 | 7,434 / 7,484 / 7,475 |
| VLP-16 | `outputs/five_lidars_v2/velodyne_vlp16` | 3 | 20,609 / 20,600 / 20,610 | 10,817 / 10,804 / 10,818 |
| OS1-64 | `outputs/five_lidars_v2/ouster_os1_64` | 3 | 49,149 each | 24,806 each |
| AT128 | `outputs/hesai_recovered_existing_rgb` | 1 | 153,600 | 150,134 |
| Noisy laboratory pinhole/VLP-16 | `outputs/noisy_pinhole` | 1 | 19,372 | 5,939 |
| CPU diagnostic physical drift | `outputs/cpu_check` | 3 | 240 each | 236 / 236 / 240 |

These are **20 capture artifacts**, including the duplicate Avia comparison. They are not 20 independent viewpoints. Shared scene/camera conditions were intentional for the five-sensor comparison. Most capture sequences keep a stationary rig while scan phase evolves.

Maximum camera projection/inversion round-trip difference across these runs is **1.05e-12 px**. This measures the declared projection mathematics, not recovery by a calibration optimizer. The noisy laboratory example has maximum shared visible-surface intersection difference **3.95e-6 m**; its 86 camera-occluded ideal points were excluded from the overlay. Other per-capture geometric tolerances and results are in the JSON audit. Rendering interpolation, antialiasing, shader bump and calibration estimation error are distinct quantities.

The previous `outputs/five_lidars_v2/hesai_at128` has invalid JSON and fails validation. Its files were preserved. The replacement reused the verified warehouse Cycles cubemap at the same optical centre and performed CPU LiDAR/camera geometry generation; it did not launch Blender or GPU work. Earlier failed remapping attempts and interrupted longitudinal native-render outputs are not valid examples.

## Rendering and geometry

Before the stability restriction, all four editable scenes, exported evaluated meshes and 640×480 previews were generated. Actual Cycles device metadata reports **OptiX / NVIDIA GeForce RTX4080**. [RENDER_VERIFICATION.json](RENDER_VERIFICATION.json) records geometry and cubemap checks:

| Scene | Objects | Triangles |
|---|---:|---:|
| Warehouse | 530 | 39,152 |
| Laboratory | 255 | 17,876 |
| Urban | 437 | 42,796 |
| Corridor | 73 | 6,380 |

The warehouse/lab/corridor previews depict coherent procedural environments. The street is visibly simplified. These are not a completed publication-quality photorealistic environment set. The urban HDRI is licensed CC0, downloaded and hashed; see [ASSETS.json](ASSETS.json). No photographic texture pack or third-party model library is bundled.

Blender RGB uses GPU rendering only in the earlier recorded runs. Open3D ray casting uses the CPU and now explicitly requests one thread. No GPU ray-casting or real-time throughput claim is made. Recorded per-capture timing fields are observations from functional runs, not a controlled performance study.

## Optimizer integration

The cloned optimizer's actual `settings.load_stacked` and calibration loader successfully read **three generated 366×484 BGR captures with 24,000 points each**. The report is `outputs/optimizer_ingestion_verified/optimizer_check.json`. Ingestion did not read evaluation truth or modify optimizer source. Stacked exports preserve millimetre floats without int16 clipping.

The solver was **not run** under the stability constraint. No estimated calibration, recovery error, optimization convergence or fault-diagnosis result is claimed. The integration gate rejects unsupported pinhole and nonzero fisheye k3/k4 instead of silently changing the camera model. The fault-aware inference project remains independent.

## ROS1 scope

Existing WSL Ubuntu20.04 / ROS Noetic was detected. Before the restriction, actual rosbag serialization/deserialization and an isolated catkin build passed on a **two-point fixture**. An existing recorded live fixture check at `outputs/ros_serialization_fixture/live_verification.json` also reports one received message on each of `/camera/image_raw`, `/camera/camera_info`, `/lidar/points`, `/tf`, `/tf_static`, `/clock` using an isolated loopback master. The source was not rerun after the stability restriction.

This establishes fixture I/O, not complete simulator-dataset replay or RViz correctness. Full generated-run bag/replay, moving-pose TF checks and RViz visual inspection remain unverified. No system ROS installation was modified.

## Remaining limitations

Finite Livox reference replay, reconstructed Mid-360 timing, nominal OS1/AT128 firing/angle tables, unavailable Avia repetitive-mode pattern, single-origin/single-return rays and phenomenological intensity limit hardware fidelity. Within-window motion/drift, scattering/weather/multipath, calibrated material NIR response and physical-sensor comparison remain unimplemented or unvalidated. Scene photorealism, native longitudinal render verification, full solver integration, GUI interaction and controlled performance measurements remain incomplete. Windows kernel crash diagnosis is a separate unresolved issue.
