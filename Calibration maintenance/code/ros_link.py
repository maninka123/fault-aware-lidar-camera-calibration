"""Read-only link to a sensor device's ROS 1 graph (Sensor_Computer software), from Windows, without ROS.

Two transports, the same ones the Central Monitoring Platform uses:
  native   the device's ROS master (XML-RPC, e.g. http://10.20.0.21:11311): topics are read straight
           from their publisher over TCPROS (requestTopic, as `rostopic echo` does), parameters
           with getParam. Nothing is registered with the master and nothing on the device changes.
  bridge   the device's ROSBridge WebSocket (e.g. ws://10.20.0.21:9090), CBOR-compressed.

Messages are returned as plain objects with the ROS field names (encoding, width, height, step,
data / fields, point_step, data), and decode_image / decode_cloud turn them into a BGR image and an
(N, 4) float32 [x, y, z, intensity] cloud.
"""
from __future__ import annotations

import base64
import json
import socket
import struct
import threading
import time
import xmlrpc.client
from types import SimpleNamespace
from urllib.parse import urlparse

import cv2
import numpy as np

CALLER = "/calibration_maintenance"
MD5 = {"sensor_msgs/Image": "060021388200f6f0f447d0fcd9c64743",
       "sensor_msgs/PointCloud2": "1158d486dd51d683ce2f1be655c3c181"}
IMAGE, CLOUD = "sensor_msgs/Image", "sensor_msgs/PointCloud2"
COLORIZER = "/pointcloud_colorizer"


class LinkError(RuntimeError):
    pass


def _typestore():
    from rosbags.typesys import Stores, get_typestore
    return get_typestore(Stores.ROS1_NOETIC)


# ------------------------------------------------------------------ decoding
def decode_image(m) -> np.ndarray:
    """sensor_msgs/Image -> BGR uint8 (rgb8, bgr8, rgba8, bgra8, mono8/16, bayer_*8/16)."""
    enc, h, w, step = m.encoding.lower(), int(m.height), int(m.width), int(m.step)
    buf = np.frombuffer(m.data if isinstance(m.data, (bytes, bytearray)) else np.asarray(m.data, np.uint8).tobytes(), np.uint8)
    rows = buf[: h * step].reshape(h, step)
    if enc in ("rgb8", "bgr8"):
        img = rows[:, : w * 3].reshape(h, w, 3)
        return np.ascontiguousarray(img[:, :, ::-1] if enc == "rgb8" else img)
    if enc in ("rgba8", "bgra8"):
        img = rows[:, : w * 4].reshape(h, w, 4)
        return cv2.cvtColor(img, cv2.COLOR_RGBA2BGR if enc == "rgba8" else cv2.COLOR_BGRA2BGR)
    if enc.endswith("16"):
        rows16 = rows[:, : w * 2].copy().view("<u2" if not getattr(m, "is_bigendian", 0) else ">u2")
        rows = (rows16 >> 8).astype(np.uint8)
        enc = enc[:-2] + "8"
    else:
        rows = rows[:, :w]
    if enc in ("mono8", "8uc1"):
        return cv2.cvtColor(np.ascontiguousarray(rows), cv2.COLOR_GRAY2BGR)
    bayer = {"bayer_rggb8": cv2.COLOR_BayerBG2BGR, "bayer_bggr8": cv2.COLOR_BayerRG2BGR,      # same mapping as cv_bridge
             "bayer_gbrg8": cv2.COLOR_BayerGR2BGR, "bayer_grbg8": cv2.COLOR_BayerGB2BGR}
    if enc in bayer:
        return cv2.cvtColor(np.ascontiguousarray(rows), bayer[enc])
    raise LinkError(f"unsupported image encoding {m.encoding}")


_DT = {1: "i1", 2: "u1", 3: "<i2", 4: "<u2", 5: "<i4", 6: "<u4", 7: "<f4", 8: "<f8"}


def decode_cloud(m) -> np.ndarray:
    """sensor_msgs/PointCloud2 -> (N, 4) float32 [x, y, z, intensity]."""
    data = m.data if isinstance(m.data, (bytes, bytearray)) else np.asarray(m.data, np.uint8).tobytes()
    n = int(m.width) * int(m.height)
    rec = np.frombuffer(data, np.uint8)[: n * int(m.point_step)].reshape(n, int(m.point_step))
    fields = {f.name: f for f in m.fields}
    out = np.ones((n, 4), np.float32)
    for i, name in enumerate(("x", "y", "z", "intensity")):
        if name in fields:
            f = fields[name]
            dt = np.dtype(_DT[int(f.datatype)])
            out[:, i] = rec[:, f.offset: f.offset + dt.itemsize].copy().view(dt).ravel()
    return out


# ------------------------------------------------------------------ native ROS 1 (master XML-RPC + TCPROS)
class _Timeout(xmlrpc.client.Transport):
    def __init__(self, timeout):
        super().__init__()
        self.timeout = timeout

    def make_connection(self, host):
        c = super().make_connection(host)
        c.timeout = self.timeout
        return c


def _proxy(uri, timeout):
    return xmlrpc.client.ServerProxy(uri, transport=_Timeout(timeout), allow_none=True)


def _call(fn, *args):
    code, msg, val = fn(CALLER, *args)
    if code != 1:
        raise LinkError(msg)
    return val


def _recv_exact(sock, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(min(n - len(buf), 1 << 20))
        if not chunk:
            raise LinkError("connection closed by the device")
        buf += chunk
    return bytes(buf)


def _header(fields):
    body = b"".join(struct.pack("<I", len(s)) + s for s in (f"{k}={v}".encode() for k, v in fields.items()))
    return struct.pack("<I", len(body)) + body


def _parse_header(raw):
    out, i = {}, 0
    while i < len(raw):
        n = struct.unpack_from("<I", raw, i)[0]
        k, _, v = raw[i + 4: i + 4 + n].decode(errors="replace").partition("=")
        out[k] = v
        i += 4 + n
    return out


class NativeLink:
    kind = "native"

    def __init__(self, master_uri, timeout=3.0):
        self.uri, self.timeout = master_uri, timeout
        self.host = urlparse(master_uri).hostname
        self._ts = None
        self._lock = threading.Lock()

    @property
    def master(self):
        """A new XML-RPC proxy per call: one proxy's HTTP connection cannot be shared by threads."""
        return _proxy(self.uri, self.timeout)

    def typestore(self):
        with self._lock:
            if self._ts is None:
                self._ts = _typestore()
            return self._ts

    def describe(self):
        return f"native ROS (TCPROS) · master {self.uri}"

    def topics(self) -> dict:
        return {t: ty for t, ty in _call(self.master.getTopicTypes)}

    def publishers(self, topic):
        pubs, _, _ = _call(self.master.getSystemState)
        return next((nodes for t, nodes in pubs if t == topic), [])

    def get_param(self, key):
        return _call(self.master.getParam, key)

    def colorizer_params(self):
        """The calibration the device uses (ROS parameter server, as loaded from its pipeline.yaml)."""
        try:
            return self.get_param(COLORIZER)
        except LinkError:
            return None

    def subscribe(self, topic, msgtype, throttle_s=None):
        """throttle_s is applied by the reader (see grab / device_capture): TCPROS has no rate request,
        but while this client is not reading, the device's publisher drops messages for this
        connection only (its normal slow-subscriber behaviour), so nothing extra is sent."""
        return _TcprosStream(self, topic, msgtype)

    def close(self):
        pass


class _TcprosStream:
    """Messages of one topic, read directly from its publisher."""

    def __init__(self, link, topic, msgtype):
        self.link, self.topic, self.msgtype = link, topic, msgtype
        self.sock = None
        nodes = link.publishers(topic)
        if not nodes:
            raise LinkError(f"nobody publishes {topic} on {link.uri}")
        err = None
        for node in nodes:
            try:
                api = _call(link.master.lookupNode, node)
                proto = _call(_proxy(api, link.timeout).requestTopic, topic, [["TCPROS"]])
                host, port = proto[1], int(proto[2])
                if host in ("localhost", "127.0.0.1") and link.host not in ("localhost", "127.0.0.1"):
                    host = link.host                                  # publisher advertised a loopback name
                s = socket.create_connection((host, port), timeout=max(link.timeout, 5.0))
                s.sendall(_header(dict(callerid=CALLER, topic=topic, type=msgtype, md5sum=MD5.get(msgtype, "*"), tcp_nodelay="1")))
                n = struct.unpack("<I", _recv_exact(s, 4))[0]
                hdr = _parse_header(_recv_exact(s, n))
                if "error" in hdr:
                    s.close()
                    raise LinkError(f"{node}: {hdr['error']}")
                s.settimeout(10.0)
                self.sock = s
                return
            except (OSError, LinkError, xmlrpc.client.Error) as e:
                err = e
        raise LinkError(f"could not read {topic}: {err}")

    def next(self):
        """(receive time, message) of the next message."""
        n = struct.unpack("<I", _recv_exact(self.sock, 4))[0]
        raw = _recv_exact(self.sock, n)
        t = time.time()
        return t, self.link.typestore().deserialize_ros1(raw, self.msgtype.replace("/", "/msg/"))

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


# ------------------------------------------------------------------ ROSBridge (WebSocket)
def _ns(d):
    if isinstance(d, dict):
        return SimpleNamespace(**{k: _ns(v) for k, v in d.items()})
    if isinstance(d, list) and d and isinstance(d[0], dict):
        return [_ns(x) for x in d]
    return d


class BridgeLink:
    kind = "bridge"

    def __init__(self, url, timeout=3.0):
        import websocket  # websocket-client
        self.url, self.timeout = url, timeout
        self.host = urlparse(url).hostname
        self.ws = websocket.create_connection(url, timeout=timeout)
        self.lock = threading.Lock()
        self.n = 0

    def describe(self):
        return f"ROSBridge · {self.url}"

    def _service(self, name, args=None, timeout=3.0):
        import websocket
        with self.lock:
            self.n += 1
            sid = f"cm_srv_{self.n}"
            ws = websocket.create_connection(self.url, timeout=timeout)
        try:
            ws.send(json.dumps(dict(op="call_service", id=sid, service=name, args=args or {})))
            end = time.time() + timeout
            while time.time() < end:
                msg = json.loads(ws.recv())
                if msg.get("op") == "service_response" and msg.get("id") == sid:
                    if not msg.get("result", True):
                        raise LinkError(f"{name}: {msg.get('values')}")
                    return msg.get("values")
        finally:
            ws.close()
        raise LinkError(f"{name}: no answer")

    def topics(self) -> dict:
        """Needs the device's rosapi node; empty if it is not running."""
        try:
            v = self._service("/rosapi/topics")
            return dict(zip(v["topics"], v["types"]))
        except Exception:
            return {}

    def colorizer_params(self):
        try:
            names = self._service("/rosapi/get_param_names")["names"]
            out = {}
            for n in names:
                if n.startswith(COLORIZER + "/"):
                    out[n[len(COLORIZER) + 1:]] = json.loads(self._service("/rosapi/get_param", dict(name=n))["value"])
            return out or None
        except Exception:
            return None

    def subscribe(self, topic, msgtype, throttle_s=None):
        """throttle_s: the device's ROSBridge sends at most one message per throttle_s seconds."""
        return _BridgeStream(self, topic, msgtype, throttle_s)

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


class _BridgeStream:
    def __init__(self, link, topic, msgtype, throttle_s=None):
        import websocket
        self.ws = websocket.create_connection(link.url, timeout=10.0)
        link.n += 1
        self.id, self.topic = f"cm_sub_{link.n}", topic
        self.ws.send(json.dumps(dict(op="subscribe", id=self.id, topic=topic, type=msgtype, compression="cbor", queue_length=1,
                                     throttle_rate=int(1000 * throttle_s) if throttle_s else 0)))

    def next(self):
        import cbor2
        while True:
            frame = self.ws.recv()
            msg = cbor2.loads(frame) if isinstance(frame, (bytes, bytearray)) else json.loads(frame)
            if msg.get("op") != "publish" or msg.get("topic") != self.topic:
                continue
            m = msg["msg"]
            if hasattr(m.get("data"), "value"):                    # CBOR typed-array tag
                m["data"] = bytes(m["data"].value)
            if isinstance(m.get("data"), str):                      # JSON: base64
                m["data"] = base64.b64decode(m["data"])
            return time.time(), _ns(m)

    def close(self):
        try:
            self.ws.send(json.dumps(dict(op="unsubscribe", id=self.id, topic=self.topic)))
            self.ws.close()
        except Exception:
            pass


# ------------------------------------------------------------------ connecting
def open_link(device, timeout=3.0):
    """The device's native ROS master if it has one, else its ROSBridge."""
    errors = []
    if device.get("master_uri"):
        try:
            link = NativeLink(device["master_uri"], timeout)
            link.topics()
            return link
        except (OSError, LinkError, xmlrpc.client.Error) as e:
            errors.append(f"ROS master {device['master_uri']}: {e}")
    if device.get("bridge_url"):
        try:
            return BridgeLink(device["bridge_url"], timeout)
        except Exception as e:
            errors.append(f"ROSBridge {device['bridge_url']}: {e}")
    raise LinkError("; ".join(errors) or "no ROS master or ROSBridge address for this device")


def probe(device, timeout=1.0):
    """Quick reachability check of a device (no subscription)."""
    for key in ("master_uri", "bridge_url"):
        u = device.get(key)
        if not u:
            continue
        p = urlparse(u)
        try:
            with socket.create_connection((p.hostname, p.port or (11311 if key == "master_uri" else 9090)), timeout=timeout):
                return dict(online=True, via="native ROS" if key == "master_uri" else "ROSBridge")
        except OSError:
            pass
    return dict(online=False, via=None)


def grab(link, topic, msgtype, count=1, seconds=None, stop=None, on_message=None):
    """Read `count` messages (or for `seconds`) of one topic; returns [(time, message)]."""
    stream = link.subscribe(topic, msgtype)
    out, t0 = [], time.time()
    try:
        while True:
            if stop is not None and stop.is_set():
                break
            t, m = stream.next()
            out.append((t, m))
            if on_message:
                on_message(t, m)
            if seconds is None and len(out) >= count:
                break
            if seconds is not None and t - t0 >= seconds:
                break
    finally:
        stream.close()
    return out
