# Capture inputs

For live operation, use the camera and LiDAR topics from [Sensor_Computer](https://github.com/maninka123/Sensor_Computer). Defaults are `/camera/image_raw` and `/livox/lidar`.

For recorded ROS 1 data, select a folder containing:

```text
captures/
  capture_001/rig_0.bag
  capture_002/rig_0.bag
  capture_003/rig_0.bag
```

The decoder selects messages by type: `sensor_msgs/Image` and `sensor_msgs/PointCloud2`. A still window is selected before the image and point cloud are stacked.

Stacked captures are `.npz` archives, one per capture, containing:

| Key | Contents |
|---|---|
| `image` | H × W × 3 BGR image, uint8 |
| `xyz_mm` | N × 3 LiDAR coordinates in millimetres |
| `intensity` | N reflectivity values |
| `frame` | N source-frame indices |
| `frame_time` | Timestamp for each source LiDAR frame |

Keep the rig and scene still during each capture. Use edges at multiple distances and vary the view between captures where practical. No sample recordings are distributed with the app.
