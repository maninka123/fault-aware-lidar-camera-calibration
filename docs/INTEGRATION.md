# Calibration and ROS 1 integration

The simulator is independent of ROS and both calibration workspaces. The public
optimizer was cloned under `research_references/calibration-optimizer` for
read-only inspection. No application source or configuration there is changed.

## Measurement-only exports

```python
from simulator.adapters import export_paired, export_stacked
export_paired("outputs/example", "outputs/paired")
export_stacked("outputs/example", "outputs/stacked")
```

Destinations must be new or empty. The exporter reads `inference/` only and copies
the initial calibration estimate, never `evaluation/ground_truth.json`, fault
labels, or change timestamps. Paths escaping the inference directory are rejected.

Paired output has one `image.png` and `cloud.pcd` inside each capture directory.
PCD coordinates remain **metres in the LiDAR frame**. This is accepted by the
optimizer's `paired_data.py` discovery rules. All images must share a resolution;
the app requires at least 100 usable XYZ points per capture and enough points in
its configured analysis distance range (1.5–10 m by default).

Stacked output follows the optimizer's actual `settings.load_stacked` interface:

| Field | Representation |
|---|---|
| `image` | uint8 H×W×3 **BGR** |
| `xyz_mm` | float32 N×3 millimetres; no int16 clipping |
| `intensity` | float32 N scalar approximate reflectivity |
| `frame` | N zero-valued source-frame indices for a static scan |
| `frame_time` | One absolute capture timestamp in seconds |
| `point_time` | Additional exact per-point timestamps, ignored by current optimizer |

The original `lidar.npz` retains the scan timing and beam metadata. Static-pair
import cannot represent motion compensation or recover an accumulation sequence
from the scan alone. Do not use the static stacked adapter to assert validation of
the algorithm's motion model.

## Existing optimizer check

```powershell
python tools/check_optimizer.py outputs/example --output outputs/optimizer_check
python tools/check_optimizer.py outputs/example --output outputs/optimizer_solve --solve --ground-truth outputs/example/evaluation/ground_truth.json
```

The first command actually invokes the cloned optimizer's calibration and stacked
capture loaders. The second attempts its existing extrinsic maintenance solver,
redirecting **all results to the simulator output directory**. Imports suppress
bytecode writes in the reference repository. `optimizer_check.json` records the
ingestion result, exceptions, candidate path and optional separate evaluation.
The evaluation file is read only after the solver returns a candidate.

The inspected optimizer always projects with an **OpenCV fisheye model using
k1 and k2 only** (`Targetless calibration/code/calib.py`, `Model.project`). Its
loader does not enforce this. The integration tool therefore explicitly rejects
pinhole calibrations and nonzero fisheye k3/k4 rather than reinterpret them.
Exporting a generic paired or stacked dataset remains possible for another solver.

An optimizer result is a test of interoperability, not proof of observability or
convergence. Synthetic appearance, scene structure, sparse scan sampling and
feature assumptions can cause inconclusive decisions or inaccurate estimates.

## Existing WSL ROS environment

The inspected environment is Ubuntu 20.04.6 under WSL2 with ROS **Noetic** and
Python 3.8.10. NumPy 1.17.4, OpenCV 4.2.0, `rospy`, and `rosbag` imported
successfully. No ROS packages were installed, upgraded or removed.

In an Ubuntu WSL shell, set the shared project path once:

```bash
LAB='/mnt/c/path/to/camera-lidar-simulation-lab'
bash "$LAB/ros1/check_environment.sh"
source /opt/ros/noetic/setup.bash
```

Use `/mnt/c/...` paths, quoting spaces in Windows/OneDrive directory names. Dataset
files are read directly from the shared filesystem; no network bridge is needed
for bag generation or WSL-local ROS publication.

### Export a bag without a ROS master

```bash
python3 "$LAB/ros1/scripts/replay_dataset.py" "$LAB/outputs/example" --bag "$LAB/outputs/example.bag"
python3 "$LAB/ros1/scripts/verify_bag.py" "$LAB/outputs/example" "$LAB/outputs/example.bag" --output "$LAB/outputs/ros_verification.json"
```

`--bag-dir DIR` instead exports `capture_0000/rig_0.bag` etc. A single generated
capture is represented by one image and one cloud. These bags are inspectable,
but the calibration app's still-window decoder expects multi-second recordings;
use the paired or stacked adapter for short simulated static captures.

### Publish and inspect in WSL

Run `roscore` in one WSL terminal, then:

```bash
python3 "$LAB/ros1/scripts/replay_dataset.py" "$LAB/outputs/example" --loop --rate 1
rviz -d "$LAB/ros1/config/simulation.rviz"
```

The script sets `/use_sim_time=true` for the running ROS master. Run it in a
dedicated ROS session if other nodes rely on wall time. It publishes:

| Topic | Message |
|---|---|
| `/camera/image_raw` | `sensor_msgs/Image`, BGR8, `camera_optical` frame |
| `/camera/camera_info` | `sensor_msgs/CameraInfo`, equidistant or plumb_bob |
| `/lidar/points` | `sensor_msgs/PointCloud2`, LiDAR frame, metres |
| `/tf` | world→LiDAR and LiDAR→camera optical transforms |
| `/tf_static` | identity LiDAR→lidar_sensor frame alias, latched |
| `/clock` | `rosgraph_msgs/Clock` at each capture timestamp |

The point cloud preserves `x,y,z,intensity,time,ring`: `time` is a float64 absolute
timestamp and `ring` is uint16. `--lidar-topic /livox/lidar` selects the physical
device topic convention without changing message type. Camera and cloud headers
share the capture timestamp; individual beam times remain in the cloud fields.

By default camera info and TF use the **initial calibration estimate**, with a
nominal identity world→LiDAR pose. This prevents truth leaking into inference.
For visualization/evaluation with exact moving poses and per-capture calibration,
explicitly add:

```bash
--ground-truth "$LAB/outputs/example/evaluation/ground_truth.json"
```

This is an evaluation-only mode; do not feed its TF or CameraInfo to an inference
algorithm that is meant to recover those parameters. `T_CL` maps LiDAR points
into the OpenCV camera frame; ROS publishes its inverse as the parent LiDAR→child
camera pose. The ground-truth JSON must contain a capture list with `capture_id`,
`T_WL`, `T_CL`, and optionally camera `K,D,model`.

For catkin use, add `ros1/` to an otherwise independent catkin workspace and run
`catkin_make`, or run `bash "$LAB/ros1/build_check.sh"` to build an isolated
workspace under the simulator's ignored `outputs/ros_catkin_ws/`. Then source its
`devel/setup.bash`; `roslaunch camera_lidar_simulation_lab replay.launch
dataset:=...` provides the same initial-estimate playback. Direct script execution
does not require a catkin build.

## Verification scope

Adapter tests cover BGR conversion, units beyond int16 range, per-point timing,
truth exclusion, inference path traversal, invalid timestamps and projection
compatibility. ROS-independent tests also validate quaternion conversion,
including a 180° rotation.

A two-point serialization fixture under `outputs/ros_serialization_fixture` was
exported by the **actual installed Noetic rosbag API** and read back under WSL.
All six topic payloads were present; images and float64 point timestamps matched
exactly, and float32 coordinates matched within 1e-5 m. This fixture tests message
serialization only and is not a calibration dataset. An actual isolated Noetic
catkin build also completed successfully, including the shared NTFS paths with
spaces. Live ROS master publication and RViz display are separate checks and
must not be inferred from the serialization/build tests.
