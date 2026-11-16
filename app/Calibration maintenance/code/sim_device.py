"""Test tool: serve a recorded capture (ROS1 bag) as if it were a sensor device, so the device mode of
the app can be tried without hardware.

It answers like the Sensor_Computer software does, read-only:
  ROS master   http://127.0.0.1:<port>      getTopicTypes, getSystemState, lookupNode, getParam
  publisher    TCPROS, the bag's /camera/image_raw and /livox/lidar replayed in a loop at recorded speed
  ROSBridge    ws://127.0.0.1:<bridge port>  subscribe (CBOR or JSON)
  parameters   /pointcloud_colorizer/{camera_matrix, dist_coeffs, extrinsic_matrix, image_width, image_height}
               from a calibration.json (converted to the device's pinhole model), optionally with a
               known drift, or from a Sensor_Computer pipeline.yaml

Usage:
  python sim_device.py --bag "<capture>/rig_0.bag" --calibration <calibration.json> [--tilt 0.8 --pan 0.6 --dx 20]
  python sim_device.py --bag ... --pipeline-yaml <pipeline.yaml> [--port 11311] [--bridge-port 9090]
"""
from __future__ import annotations

import argparse
import json
import socket
import struct
import sys
import threading
import time
from pathlib import Path
from xmlrpc.server import SimpleXMLRPCRequestHandler, SimpleXMLRPCServer

sys.dont_write_bytecode = True
import numpy as np  # noqa: E402
from scipy.spatial.transform import Rotation  # noqa: E402

import device_model as dm  # noqa: E402
from ros_link import IMAGE, CLOUD, MD5, _parse_header, _recv_exact  # noqa: E402

PUB = "/sim_sensor_device"


class Quiet(SimpleXMLRPCRequestHandler):
    def log_message(self, *a):
        pass


def load_bag(bag):
    from rosbags.highlevel import AnyReader
    msgs = {}
    with AnyReader([Path(bag)]) as r:
        for con, t, raw in r.messages():
            ty = {"sensor_msgs/msg/Image": IMAGE, "sensor_msgs/msg/PointCloud2": CLOUD}.get(con.msgtype)
            if ty:
                msgs.setdefault(con.topic, (ty, []))[1].append((t * 1e-9, bytes(raw)))
    return msgs


def colorizer_params(a):
    if a.pipeline_yaml:
        import yaml
        p = yaml.safe_load(Path(a.pipeline_yaml).read_text())["pointcloud_colorizer"]
        return {k: p[k] for k in ("camera_matrix", "dist_coeffs", "extrinsic_matrix", "image_width", "image_height") if k in p}
    cal = json.loads(Path(a.calibration).read_text())
    T = np.array(cal["extrinsics"]["transform_lidar_to_camera"], float)
    T[:3, :3] = Rotation.from_rotvec(np.radians([a.tilt, a.pan, a.roll])).as_matrix() @ T[:3, :3]
    T[:3, 3] += np.array([a.dx, a.dy, a.dz]) / 1000.0
    cal["extrinsics"]["transform_lidar_to_camera"] = T.tolist()
    p, rep = dm.to_device(cal, theta_max_deg=50.0)
    print(f"device model: {rep['direction']} {rep['rms_px']:.3f} px rms", flush=True)
    return dict(camera_matrix=[float(x) for x in np.ravel(p["camera_matrix"])], dist_coeffs=p["dist_coeffs"],   # flat, as the colorizer reads it
                extrinsic_matrix=[float(x) for x in np.ravel(p["extrinsic_matrix"])], image_width=p["image_width"],
                image_height=p["image_height"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bag", required=True)
    ap.add_argument("--calibration")
    ap.add_argument("--pipeline-yaml")
    ap.add_argument("--port", type=int, default=11311)
    ap.add_argument("--bridge-port", type=int, default=0, help="also serve ROSBridge on this port (0 = off)")
    for k in ("tilt", "pan", "roll", "dx", "dy", "dz"):
        ap.add_argument(f"--{k}", type=float, default=0.0)
    a = ap.parse_args()
    if not (a.calibration or a.pipeline_yaml):
        ap.error("give --calibration or --pipeline-yaml")
    msgs = load_bag(a.bag)
    params = colorizer_params(a)
    host = "127.0.0.1"

    # ---- TCPROS publisher
    tcp = socket.socket()
    tcp.bind((host, 0))
    tcp.listen(8)
    tcp_port = tcp.getsockname()[1]

    def serve_conn(c):
        try:
            hdr = _parse_header(_recv_exact(c, struct.unpack("<I", _recv_exact(c, 4))[0]))
            topic = hdr.get("topic")
            if topic not in msgs:
                body = b"error=unknown topic"
                c.sendall(struct.pack("<II", len(body) + 4, len(body)) + body)
                return
            ty, lst = msgs[topic]
            fields = [f"callerid={PUB}", f"topic={topic}", f"type={ty}", f"md5sum={MD5[ty]}", "latching=0"]
            body = b"".join(struct.pack("<I", len(f)) + f.encode() for f in fields)
            c.sendall(struct.pack("<I", len(body)) + body)
            t0 = lst[0][0]
            while True:
                start = time.time()
                for t, raw in lst:
                    time.sleep(max(0.0, (t - t0) - (time.time() - start)))
                    c.sendall(struct.pack("<I", len(raw)) + raw)
        except OSError:
            pass
        finally:
            c.close()

    def accept_loop():
        while True:
            c, _ = tcp.accept()
            threading.Thread(target=serve_conn, args=(c,), daemon=True).start()
    threading.Thread(target=accept_loop, daemon=True).start()

    # ---- publisher node XML-RPC
    node = SimpleXMLRPCServer((host, 0), requestHandler=Quiet, allow_none=True, logRequests=False)
    node_uri = f"http://{host}:{node.server_address[1]}/"
    node.register_function(lambda caller, topic, protos: [1, "ok", ["TCPROS", host, tcp_port]], "requestTopic")
    threading.Thread(target=node.serve_forever, daemon=True).start()

    # ---- master XML-RPC
    master = SimpleXMLRPCServer((host, a.port), requestHandler=Quiet, allow_none=True, logRequests=False)
    topics = [[t, ty] for t, (ty, _) in msgs.items()]

    def get_param(caller, key):
        nonlocal params
        if a.pipeline_yaml:
            params = colorizer_params(a)                  # follow edits of the file, as a pipeline restart would
        key = key.rstrip("/")
        if key == "/pointcloud_colorizer":
            return [1, "ok", params]
        if key.startswith("/pointcloud_colorizer/") and key.split("/")[-1] in params:
            return [1, "ok", params[key.split("/")[-1]]]
        return [-1, f"parameter {key} is not set", 0]
    master.register_function(lambda caller: [1, "ok", topics], "getTopicTypes")
    master.register_function(lambda caller, sub="": [1, "ok", topics], "getPublishedTopics")
    master.register_function(lambda caller: [1, "ok", [[[t, [PUB]] for t, _ in topics], [], []]], "getSystemState")
    master.register_function(lambda caller, name: [1, "ok", node_uri] if name == PUB else [-1, "unknown node", ""], "lookupNode")
    master.register_function(lambda caller: [1, "ok", f"http://{host}:{a.port}/"], "getUri")
    master.register_function(get_param, "getParam")
    print(f"simulated device: ROS master http://{host}:{a.port}  topics {[t for t, _ in topics]}", flush=True)

    # ---- ROSBridge
    if a.bridge_port:
        threading.Thread(target=serve_bridge, args=(host, a.bridge_port, msgs), daemon=True).start()
        print(f"simulated device: ROSBridge ws://{host}:{a.bridge_port}", flush=True)
    master.serve_forever()


def serve_bridge(host, port, msgs):
    import cbor2
    from rosbags.typesys import Stores, get_typestore
    from websockets.sync.server import serve
    ts = get_typestore(Stores.ROS1_NOETIC)

    def as_dict(ty, raw):
        m = ts.deserialize_ros1(raw, ty.replace("/", "/msg/"))
        if ty == IMAGE:
            return dict(height=m.height, width=m.width, encoding=m.encoding, is_bigendian=m.is_bigendian, step=m.step, data=bytes(m.data))
        return dict(height=m.height, width=m.width, point_step=m.point_step, row_step=m.row_step, is_dense=m.is_dense, data=bytes(m.data),
                    fields=[dict(name=f.name, offset=f.offset, datatype=f.datatype, count=f.count) for f in m.fields])

    def handler(ws):
        for frame in ws:
            req = json.loads(frame)
            if req.get("op") != "subscribe" or req.get("topic") not in msgs:
                continue
            ty, lst = msgs[req["topic"]]
            t0, start = lst[0][0], time.time()
            while True:
                for t, raw in lst:
                    time.sleep(max(0.0, (t - t0) - (time.time() - start)))
                    ws.send(cbor2.dumps(dict(op="publish", topic=req["topic"], msg=as_dict(ty, raw))))
                start = time.time()

    with serve(handler, host, port, max_size=None) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
