#!/usr/bin/env python3
"""Deserialize a simulator bag and compare measurement payloads to its source."""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np
import rosbag
from sensor_msgs import point_cloud2

from replay_dataset import _inference_root, _sequence, quaternion_from_rotation


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("bag", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--lidar-topic", default="/lidar/points")
    args = parser.parse_args()
    root = _inference_root(args.run)
    captures = list(_sequence(root))
    expected_topics = {"/camera/image_raw", "/camera/camera_info", args.lidar_topic, "/tf", "/tf_static", "/clock"}
    counts = {topic: 0 for topic in expected_topics}
    matched = []
    with rosbag.Bag(str(args.bag), "r") as bag:
        topics = set(bag.get_type_and_topic_info().topics)
        if topics != expected_topics:
            raise AssertionError("Unexpected topics: " + str(topics))
        for topic, message, stamp in bag.read_messages():
            index = counts[topic]
            counts[topic] += 1
            entry, directory = captures[index]
            if abs(stamp.to_sec()-float(entry["timestamp"])) > 1e-8:
                raise AssertionError("Bag timestamp mismatch")
            if topic == args.lidar_topic:
                points = np.array(list(point_cloud2.read_points(message, field_names=("x", "y", "z", "intensity", "time", "ring"))))
                with np.load(directory / "lidar.npz", allow_pickle=False) as original:
                    np.testing.assert_allclose(points[:, :3], original["xyz"], atol=1e-5, rtol=1e-6)
                    np.testing.assert_allclose(points[:, 3], original["intensity"], atol=1e-5, rtol=1e-6)
                    np.testing.assert_array_equal(points[:, 4], original["timestamps"])
                    np.testing.assert_array_equal(points[:, 5], original["channel"])
                if message.header.frame_id != "lidar":
                    raise AssertionError("Point frame mismatch")
                matched.append(dict(capture_id=entry["capture_id"], points=len(points)))
            if topic == "/camera/image_raw":
                original = cv2.imdecode(np.frombuffer((directory / "image.png").read_bytes(), np.uint8), cv2.IMREAD_COLOR)
                actual = np.frombuffer(message.data, np.uint8).reshape(message.height, message.width, 3)
                np.testing.assert_array_equal(original, actual)
                if message.encoding != "bgr8":
                    raise AssertionError("Image encoding mismatch")
            if topic == "/tf":
                if [(t.header.frame_id, t.child_frame_id) for t in message.transforms] != [("world", "lidar"), ("lidar", "camera_optical")]:
                    raise AssertionError("TF frame chain mismatch")
    if any(count != len(captures) for count in counts.values()):
        raise AssertionError("Message count mismatch")
    report = dict(success=True, captures=matched, topic_counts=counts, image_payload_exact=True,
                  point_timestamp_payload_exact=True, point_coordinates_float32_tolerance_m=1e-5,
                  note="Serialization verification; live ROS master/RViz operation is a separate check.")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
