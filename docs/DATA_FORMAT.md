# Capture inputs

In **New captures**, click **Capture format** for a visual guide, a copyable folder layout and the stacked-array fields.

For live operation, use the camera and LiDAR topics from [Sensor_Computer](https://github.com/maninka123/Sensor_Computer). Defaults are `/camera/image_raw` and `/livox/lidar`.

For recorded ROS 1 data, select a folder containing:

```text
captures/
  capture_001/rig_0.bag
  capture_002/rig_0.bag
  capture_003/rig_0.bag
```

Select **captures/**, not a `capture_001` subfolder. Folder names must start with `capture_`, with a file named exactly `rig_0.bag` immediately inside each. The search is one folder level deep.

Each bag must contain exactly one `sensor_msgs/Image` topic and one `sensor_msgs/PointCloud2` topic. Names are detected by message type; the usual topics are `/camera/image_raw` and `/livox/lidar`. Avoid recording multiple image or point-cloud topics into the same bag. A still window is selected before the image and point cloud are stacked.

Stacked captures are `.npz` archives, one per capture, containing:

```text
captures/                 <-- select this folder
  capture_001.npz
  capture_002.npz
  capture_003.npz
```

Stacked files go directly in the selected folder; their names may vary. Use one layout per folder. Loose image and PCD files are not an accepted input here.

| Key | Contents |
|---|---|
| `image` | H × W × 3 BGR image, uint8 |
| `xyz_mm` | N × 3 LiDAR coordinates in millimetres |
| `intensity` | N reflectivity values |
| `frame` | N source-frame indices |
| `frame_time` | Timestamp for each source LiDAR frame |

Aim for at least three recordings of about 4–10 seconds each. Keep the rig and scene still during each capture, use edges at multiple distances and vary the view between captures. No sample recordings are distributed with the app.
