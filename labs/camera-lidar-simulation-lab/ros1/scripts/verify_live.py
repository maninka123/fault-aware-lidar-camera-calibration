#!/usr/bin/env python3
"""Verify live topic delivery against a temporary isolated ROS1 master.

Uses an ephemeral localhost port and child-process environment variables, leaving
the user's default ROS master and parameters untouched. Does not launch RViz.
"""
import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from xmlrpc.client import ServerProxy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    master_uri = "http://127.0.0.1:%d" % port
    os.environ["ROS_MASTER_URI"] = master_uri
    os.environ["ROS_HOSTNAME"] = "localhost"
    os.environ.pop("ROS_IP", None)
    log = args.output.with_suffix(".log").open("w")
    master = subprocess.Popen(["roscore", "-p", str(port)], stdout=log, stderr=subprocess.STDOUT,
                              start_new_session=True)
    publisher = None
    report = dict(success=False, isolated_master=master_uri, live_delivery=False)
    try:
        deadline = time.monotonic()+25
        while time.monotonic() < deadline:
            if master.poll() is not None:
                raise RuntimeError("Temporary roscore exited")
            try:
                if ServerProxy(master_uri).getPid("/simulation_verifier")[0] == 1:
                    break
            except (OSError, ConnectionError):
                time.sleep(.1)
        else:
            raise RuntimeError("Temporary roscore did not start")
        import rospy
        from sensor_msgs.msg import Image, CameraInfo, PointCloud2
        from tf2_msgs.msg import TFMessage
        from rosgraph_msgs.msg import Clock
        rospy.init_node("simulation_live_verifier", anonymous=True, disable_signals=True)
        types = {"/camera/image_raw": Image, "/camera/camera_info": CameraInfo,
                 "/lidar/points": PointCloud2, "/tf": TFMessage, "/tf_static": TFMessage, "/clock": Clock}
        seen = {topic: 0 for topic in types}
        samples = {}

        def received(message, topic):
            seen[topic] += 1
            samples[topic] = message

        subscribers = [rospy.Subscriber(topic, cls, received, callback_args=topic, queue_size=4)
                       for topic, cls in types.items()]
        script = Path(__file__).with_name("replay_dataset.py")
        publisher = subprocess.Popen([sys.executable, str(script), str(args.run), "--rate", "100"],
                                     stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        deadline = time.monotonic()+30
        while time.monotonic() < deadline and not all(seen.values()):
            if publisher.poll() is not None and publisher.returncode:
                raise RuntimeError("Replay process failed with code %s" % publisher.returncode)
            time.sleep(.05)
        if not all(seen.values()):
            raise AssertionError("Missing live topics: " + str(seen))
        if samples["/camera/image_raw"].encoding != "bgr8":
            raise AssertionError("Unexpected image encoding")
        cloud = samples["/lidar/points"]
        if cloud.header.frame_id != "lidar" or {f.name for f in cloud.fields} != {"x", "y", "z", "intensity", "time", "ring"}:
            raise AssertionError("Unexpected cloud frame/fields")
        report.update(success=True, live_delivery=True, received_messages=seen,
                      sample_points=cloud.width, use_sim_time=rospy.get_param("/use_sim_time"),
                      note="Live publication and subscriptions verified; RViz visual display not exercised.")
        for subscriber in subscribers:
            subscriber.unregister()
        rospy.signal_shutdown("verification complete")
    except Exception as error:
        report["error"] = repr(error)
    finally:
        for process in (publisher, master):
            if process is not None and process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
        log.close()
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
