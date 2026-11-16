#!/usr/bin/env python3
"""ROS 1 replay/bag export; deliberately independent of the simulator package.

Python 3.8 compatible for Ubuntu 20.04/Noetic. Default TF uses the INITIAL
calibration estimate. Exact TF requires explicitly supplying --ground-truth.
"""
import argparse
import json
import math
import struct
import time
from pathlib import Path

import cv2
import numpy as np


def _inference_root(run):
    root = Path(run).resolve()
    return root / "inference" if (root / "inference").is_dir() else root


def _sequence(root):
    data = json.loads((root / "sequence.json").read_text(encoding="utf-8"))
    captures = data if isinstance(data, list) else data["captures"]
    previous = -math.inf
    for entry in captures:
        stamp = float(entry["timestamp"])
        if not math.isfinite(stamp) or stamp < 0 or stamp < previous:
            raise ValueError("Capture timestamps must be finite, nonnegative and ordered")
        previous = stamp
        directory = (root / entry["path"]).resolve()
        if root not in directory.parents or not directory.is_dir():
            raise ValueError("Capture path is outside inference tree")
        yield entry, directory


def quaternion_from_rotation(matrix):
    """Numerically stable proper-rotation -> xyzw quaternion, without scipy."""
    r = np.asarray(matrix, np.float64)
    if r.shape != (3, 3) or not np.allclose(r.T @ r, np.eye(3), atol=1e-6) or not np.isclose(np.linalg.det(r), 1, atol=1e-6):
        raise ValueError("TF rotation must be a proper orthogonal 3x3 matrix")
    k = np.array([[r[0, 0]-r[1, 1]-r[2, 2], r[1, 0]+r[0, 1], r[2, 0]+r[0, 2], r[2, 1]-r[1, 2]],
                  [r[1, 0]+r[0, 1], r[1, 1]-r[0, 0]-r[2, 2], r[2, 1]+r[1, 2], r[0, 2]-r[2, 0]],
                  [r[2, 0]+r[0, 2], r[2, 1]+r[1, 2], r[2, 2]-r[0, 0]-r[1, 1], r[1, 0]-r[0, 1]],
                  [r[2, 1]-r[1, 2], r[0, 2]-r[2, 0], r[1, 0]-r[0, 1], r.trace()]]) / 3
    eigenvalues, vectors = np.linalg.eigh(k)
    q = vectors[:, np.argmax(eigenvalues)]
    return q if q[3] >= 0 else -q


def transform_message(parent, child, matrix, stamp):
    from geometry_msgs.msg import TransformStamped
    matrix = np.asarray(matrix, np.float64)
    if matrix.shape != (4, 4) or not np.isfinite(matrix).all() or not np.allclose(matrix[3], [0, 0, 0, 1]):
        raise ValueError("Expected finite homogeneous transform")
    message = TransformStamped()
    message.header.stamp = stamp
    message.header.frame_id = parent
    message.child_frame_id = child
    message.transform.translation.x, message.transform.translation.y, message.transform.translation.z = matrix[:3, 3]
    q = quaternion_from_rotation(matrix[:3, :3])
    message.transform.rotation.x, message.transform.rotation.y, message.transform.rotation.z, message.transform.rotation.w = q
    return message


def camera_message(calibration, shape, stamp):
    from sensor_msgs.msg import CameraInfo
    message = CameraInfo()
    message.header.stamp = stamp
    message.header.frame_id = "camera_optical"
    message.height, message.width = shape[:2]
    intrinsics = calibration["intrinsics"]
    k = np.asarray(intrinsics["camera_matrix"], np.float64)
    d = np.ravel(np.asarray(intrinsics.get("distortion_coefficients", []), np.float64))
    model = intrinsics.get("model", intrinsics.get("distortion_model", ""))
    if model in ("fisheye", "opencv_fisheye", "equidistant", "k1", "k1-k2"):
        message.distortion_model = "equidistant"
        if len(d) > 4:
            raise ValueError("OpenCV fisheye accepts four distortion coefficients")
        d = np.pad(d, (0, 4-len(d)))
    elif model in ("pinhole", "opencv_pinhole", "plumb_bob"):
        message.distortion_model = "plumb_bob"
        if len(d) not in (0, 4, 5):
            raise ValueError("This adapter supports pinhole plumb_bob with 0, 4 or 5 coefficients")
        d = np.pad(d, (0, 5-len(d)))
    else:
        raise ValueError("Unsupported camera model: " + repr(model))
    if k.shape != (3, 3) or not np.isfinite(k).all() or not np.isfinite(d).all():
        raise ValueError("Invalid camera intrinsics")
    message.D = d.tolist()
    message.K = k.ravel().tolist()
    message.R = np.eye(3).ravel().tolist()
    message.P = np.column_stack((k, np.zeros(3))).ravel().tolist()
    return message


def truth_records(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    records = data if isinstance(data, list) else data["captures"]
    return {record["capture_id"]: record for record in records}


def write_bag_message(bag, topic, message, stamp):
    header = None
    if topic == "/tf_static":
        header = dict(topic=topic, type=message._type, md5sum=message._md5sum,
                      message_definition=message._full_text, latching="1")
    bag.write(topic, message, t=stamp, connection_header=header)


def messages_for_capture(root, entry, directory, calibration, truth=None):
    import rospy
    from sensor_msgs.msg import Image, PointCloud2, PointField
    from std_msgs.msg import Header
    from tf2_msgs.msg import TFMessage
    from rosgraph_msgs.msg import Clock
    stamp = rospy.Time.from_sec(float(entry["timestamp"]))
    image = cv2.imdecode(np.frombuffer((directory / "image.png").read_bytes(), np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Unreadable image in " + str(directory))
    image_msg = Image(header=Header(stamp=stamp, frame_id="camera_optical"),
                      height=image.shape[0], width=image.shape[1], encoding="bgr8",
                      is_bigendian=0, step=image.shape[1]*3, data=image.tobytes())
    active = calibration
    t_wl = np.eye(4)
    t_cl = np.asarray(calibration["extrinsics"]["transform_lidar_to_camera"], float)
    if truth is not None:
        t_wl = np.asarray(truth["T_WL"], float)
        t_cl = np.asarray(truth["T_CL"], float)
        if "camera" in truth:
            c = truth["camera"]
            active = dict(intrinsics=dict(camera_matrix=c.get("K", c.get("camera_matrix")),
                distortion_coefficients=c.get("D", c.get("distortion_coefficients", [])),
                model=c.get("model", "fisheye")))
    info = camera_message(active, image.shape, stamp)
    with np.load(directory / "lidar.npz", allow_pickle=False) as data:
        xyz = np.asarray(data["xyz"], np.float32)
        intensity = np.asarray(data["intensity"], np.float32)
        point_time = np.asarray(data["timestamps"], np.float64)
        channel = np.asarray(data["channel"], np.uint16)
    if xyz.ndim != 2 or xyz.shape[1] != 3 or any(len(a) != len(xyz) for a in (intensity, point_time, channel)):
        raise ValueError("PointCloud array lengths differ")
    # Packed structured array preserves float64 absolute point timestamps.
    dtype = np.dtype([("x", "<f4"), ("y", "<f4"), ("z", "<f4"), ("intensity", "<f4"),
                      ("time", "<f8"), ("ring", "<u2")])
    packed = np.empty(len(xyz), dtype=dtype)
    for index, name in enumerate(("x", "y", "z")):
        packed[name] = xyz[:, index]
    packed["intensity"], packed["time"], packed["ring"] = intensity, point_time, channel
    fields = [PointField(name, dtype.fields[name][1], PointField.FLOAT64 if name == "time" else
                        PointField.UINT16 if name == "ring" else PointField.FLOAT32, 1) for name in dtype.names]
    cloud_msg = PointCloud2(header=Header(stamp=stamp, frame_id="lidar"), height=1, width=len(xyz),
        fields=fields, is_bigendian=False, point_step=dtype.itemsize, row_step=len(xyz)*dtype.itemsize,
        data=packed.tobytes(), is_dense=bool(np.isfinite(xyz).all()))
    dynamic = TFMessage([transform_message("world", "lidar", t_wl, stamp),
                         transform_message("lidar", "camera_optical", np.linalg.inv(t_cl), stamp)])
    static = TFMessage([transform_message("lidar", "lidar_sensor", np.eye(4), stamp)])
    return [("/clock", Clock(stamp)), ("/tf_static", static), ("/tf", dynamic),
            ("/camera/camera_info", info), ("/camera/image_raw", image_msg), ("/lidar/points", cloud_msg)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--ground-truth", type=Path, help="Explicit evaluation-only opt-in for exact camera info and TF")
    parser.add_argument("--bag", type=Path, help="Export entire sequence as ROS1 bag without a ROS master")
    parser.add_argument("--bag-dir", type=Path, help="Export capture_*/rig_0.bag static pairs")
    parser.add_argument("--rate", type=float, default=1.0, help="Wall-clock playback speed multiplier")
    parser.add_argument("--lidar-topic", default="/lidar/points")
    parser.add_argument("--loop", action="store_true")
    args = parser.parse_args()
    if args.rate <= 0 or not math.isfinite(args.rate):
        parser.error("--rate must be finite and positive")
    if args.bag and args.bag_dir:
        parser.error("Choose --bag or --bag-dir")
    root = _inference_root(args.run)
    calibration = json.loads((root / "initial_calibration.json").read_text(encoding="utf-8"))
    captures = list(_sequence(root))
    if not captures:
        parser.error("Sequence has no captures")
    truth = truth_records(args.ground_truth) if args.ground_truth else None
    print("TF/camera info source: " + ("explicit evaluation ground truth" if truth else "initial estimate; nominal identity world-to-lidar pose"))

    def messages(entry, directory):
        for topic, message in messages_for_capture(root, entry, directory, calibration,
                truth[entry["capture_id"]] if truth is not None else None):
            yield args.lidar_topic if topic == "/lidar/points" else topic, message

    if args.bag or args.bag_dir:
        import rosbag
        import rospy
        if args.bag:
            args.bag.parent.mkdir(parents=True, exist_ok=True)
            if args.bag.exists():
                raise FileExistsError(str(args.bag))
            with rosbag.Bag(str(args.bag), "w") as bag:
                for entry, directory in captures:
                    for topic, message in messages(entry, directory):
                        write_bag_message(bag, topic, message, rospy.Time.from_sec(float(entry["timestamp"])))
        else:
            for index, (entry, directory) in enumerate(captures):
                target = args.bag_dir / ("capture_%04d" % index) / "rig_0.bag"
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    raise FileExistsError(str(target))
                with rosbag.Bag(str(target), "w") as bag:
                    for topic, message in messages(entry, directory):
                        write_bag_message(bag, topic, message, rospy.Time.from_sec(float(entry["timestamp"])))
        print("ROS bag export complete")
        return
    import rospy
    rospy.init_node("camera_lidar_simulation_replay")
    rospy.set_param("/use_sim_time", True)
    publishers = {topic: rospy.Publisher(topic, type(message), queue_size=4, latch=topic == "/tf_static")
                  for topic, message in messages(*captures[0])}
    time.sleep(0.5)
    while not rospy.is_shutdown():
        previous = captures[0][0]["timestamp"]
        for entry, directory in captures:
            delay = max(0, (float(entry["timestamp"]) - float(previous)) / args.rate)
            time.sleep(delay)
            if rospy.is_shutdown():
                return
            for topic, message in messages(entry, directory):
                publishers[topic].publish(message)
            previous = entry["timestamp"]
        if not args.loop:
            # Allow transport threads to flush the final capture.
            time.sleep(0.5)
            return


if __name__ == "__main__":
    main()
