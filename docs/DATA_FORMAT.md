# Capture inputs

For the new offline research backend, see [RESEARCH_README.md](../RESEARCH_README.md). Existing readers are reused; stacked recordings are the inputs exercised in the recorded research comparisons. The research desktop button currently enables stacked captures only. Research results use a predeclared camera domain and separate fitting/test captures; imported files are never modified.

In **New captures**, click **Capture format** for a visual guide, a copyable folder layout and the stacked-array fields.

For live operation, use the camera and LiDAR topics from [Sensor_Computer](https://github.com/maninka123/Sensor_Computer). Defaults are `/camera/image_raw` and `/livox/lidar`.

## Image + PCD pairs

Select the common parent folder. Two layouts are supported, including nested capture folders:

```text
my_captures/                 <-- select this folder
  photos/                   # folder names can vary
    capture_001.png
    capture_002.png
  lidar_scans/
    capture_001.pcd
    capture_002.pcd
```

```text
my_captures/                 <-- select this folder
  position_a/               # capture folder names can vary
    image.png
    cloud.pcd
  position_b/
    image.png
    cloud.pcd
```

For two separate folders, capture IDs are matched case-insensitively, including common prefixes such as `image_001.png` and `cloud_001.pcd`. Files are never paired by their list order. Each ID must identify one image and one PCD. A capture folder with exactly one image and one PCD identifies its own pair, so those two filenames may differ.

Images: PNG, JPG/JPEG, BMP or TIFF. All images in a check must have the same resolution, matching the calibration when its image size is known. PCD: ASCII, binary and binary-compressed, with scalar `x`, `y`, `z` fields. `intensity`, `reflectivity` or `reflectance` is used if available; missing reflectivity is reported and geometry edges remain available.

**PCD units default to metres.** Select millimetres if that is how the coordinates were exported. The app checks readable files, unique matches, at least 100 finite nonzero XYZ points per cloud, and useful distance ranges. **View pairs** shows each filename, point count, median distance and central 90% distance range. Unmatched files are listed and excluded. Ambiguity or unreadable files blocks import; suspicious units require review. There must be enough points in the configured analysis range (1.5–10 m by default).

Use synchronized image/cloud exports or a still scene, with points in the LiDAR coordinate frame. PCD generally does not declare coordinate units, so range checks do not prove units. Static-pair import cannot recover missing per-point timing. Original files are never modified.

## ROS bags

For recorded ROS 1 data, select a folder containing:

```text
captures/
  capture_001/rig_0.bag
  capture_002/rig_0.bag
  capture_003/rig_0.bag
```

Select **captures/**, not a `capture_001` subfolder. Folder names must start with `capture_`, with a file named exactly `rig_0.bag` immediately inside each. The search is one folder level deep.

Each bag must contain exactly one `sensor_msgs/Image` topic and one `sensor_msgs/PointCloud2` topic. Names are detected by message type; the usual topics are `/camera/image_raw` and `/livox/lidar`. Avoid recording multiple image or point-cloud topics into the same bag. A still window is selected before the image and point cloud are stacked.

## Stacked captures

Stacked captures are `.npz` archives, one per capture, containing:

```text
captures/                 <-- select this folder
  capture_001.npz
  capture_002.npz
  capture_003.npz
```

Stacked files go directly in the selected folder; their names may vary. Keep one input format per selected dataset. Separate image and PCD files use the paired layouts above.

| Key | Contents |
|---|---|
| `image` | H × W × 3 BGR image, uint8 |
| `xyz_mm` | N × 3 LiDAR coordinates in millimetres |
| `intensity` | N reflectivity values |
| `frame` | N source-frame indices |
| `frame_time` | Timestamp for each source LiDAR frame |

Aim for at least three captures from different views, with edges at multiple distances. For bags, record about 4–10 seconds each and keep the rig still during each recording. No sample recordings are distributed with the app.
