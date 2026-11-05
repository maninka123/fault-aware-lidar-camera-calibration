"""ROS1 bag reading without a ROS installation (uses the pure-Python `rosbags`).

Each capture is a ~10 s stationary recording.  We turn it into:
  * one temporal-median camera image (all frames are the same static view, so the
    median removes sensor noise and gives sub-pixel-stable checkerboard corners);
  * one merged LiDAR cloud (the Livox Avia scans a non-repetitive pattern, so
    accumulating frames increases angular density on the board).

Decoded data are cached as compact .npz files so the bags are read only once.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

CACHE_VERSION = 2


@dataclass
class Capture:
    name: str
    scenario: str
    bag: Path
    image: np.ndarray          # BGR uint8, temporal median
    image_std: float           # mean |frame - median| (grey levels); static-scene check
    n_images: int
    xyz: np.ndarray            # (N,3) float64, metres, LiDAR frame
    intensity: np.ndarray      # (N,) float64, Livox reflectivity 0-255
    frame: np.ndarray          # (N,) int, index of the LiDAR message each point came from
    frame_time: np.ndarray     # (F,) float, record time of each LiDAR message relative to first image
    n_frames: int

    def cloud(self, n_frames: int | None = None, start: int | None = None):
        """Return xyz/intensity of `n_frames` consecutive LiDAR messages.

        None means every message in the capture. `start` defaults to centring the
        window in the recording (the same rule as the paper's bag reader).
        """
        if n_frames is None or n_frames >= self.n_frames:
            return self.xyz, self.intensity
        if start is None:
            start = (self.n_frames - n_frames) // 2
        keep = (self.frame >= start) & (self.frame < start + n_frames)
        return self.xyz[keep], self.intensity[keep]


_BAYER = {"bayer_rggb8": 46, "bayer_bggr8": 48, "bayer_gbrg8": 47, "bayer_grbg8": 49}  # filled with cv2 codes below
try:
    import cv2 as _cv2
    _BAYER = {"bayer_rggb8": _cv2.COLOR_BayerBG2BGR, "bayer_bggr8": _cv2.COLOR_BayerRG2BGR,
              "bayer_gbrg8": _cv2.COLOR_BayerGR2BGR, "bayer_grbg8": _cv2.COLOR_BayerGB2BGR}
except ImportError:  # pragma: no cover - OpenCV is a hard requirement elsewhere
    _BAYER = {}


def _decode_image(msg) -> np.ndarray:
    data = np.frombuffer(msg.data, np.uint8)
    enc = msg.encoding.lower()
    if enc in ("rgb8", "bgr8"):
        img = data.reshape(msg.height, msg.step)[:, : msg.width * 3].reshape(msg.height, msg.width, 3)
        return img[:, :, ::-1] if enc == "rgb8" else img
    if enc in ("mono8", "8uc1"):
        gray = data.reshape(msg.height, msg.step)[:, : msg.width]
        return np.repeat(gray[:, :, None], 3, axis=2)
    if enc in _BAYER:
        # Raw colour-filter mosaic (e.g. FLIR cameras): demosaic to BGR. The OpenCV code names follow the
        # pixel pair that *starts the second row*, hence the cv_bridge mapping below.
        import cv2
        mosaic = np.ascontiguousarray(data.reshape(msg.height, msg.step)[:, : msg.width])
        return cv2.cvtColor(mosaic, _BAYER[enc])
    if enc in ("bgra8", "rgba8"):
        img = data.reshape(msg.height, msg.step)[:, : msg.width * 4].reshape(msg.height, msg.width, 4)
        return img[:, :, [2, 1, 0]] if enc == "rgba8" else img[:, :, :3]
    raise ValueError(f"Unsupported image encoding {msg.encoding} (supported: rgb8, bgr8, rgba8, bgra8, mono8, "
                     "bayer_rggb8, bayer_bggr8, bayer_gbrg8, bayer_grbg8)")


def _decode_cloud(msg) -> np.ndarray:
    """PointCloud2 -> (N,4) float32 [x, y, z, intensity]."""
    offsets = {f.name: f.offset for f in msg.fields}
    rec = np.frombuffer(msg.data, np.uint8).reshape(-1, msg.point_step)
    out = np.empty((len(rec), 4), np.float32)
    for i, name in enumerate(("x", "y", "z", "intensity")):
        if name in offsets:
            o = offsets[name]
            out[:, i] = rec[:, o : o + 4].copy().view("<f4").ravel()
        else:
            out[:, i] = 1.0
    return out


def read_bag(bag: Path, image_topic: str, cloud_topic: str):
    from rosbags.highlevel import AnyReader

    images, image_t, clouds, cloud_t = [], [], [], []
    with AnyReader([bag]) as reader:
        conns = [c for c in reader.connections if c.topic in (image_topic, cloud_topic)]
        topics = {c.topic for c in conns}
        missing = {image_topic, cloud_topic} - topics
        if missing:
            raise RuntimeError(f"{bag}: missing topics {sorted(missing)}")
        for con, stamp, raw in reader.messages(connections=conns):
            msg = reader.deserialize(raw, con.msgtype)
            # Record time is used (as in the paper reader): the Livox header stamp
            # is sensor time and is not on the same clock as the camera.
            if con.topic == image_topic:
                images.append(_decode_image(msg)); image_t.append(stamp * 1e-9)
            else:
                clouds.append(_decode_cloud(msg)); cloud_t.append(stamp * 1e-9)
    return images, np.asarray(image_t), clouds, np.asarray(cloud_t)


def load_capture(bag: Path, scenario: str, cache_dir: Path, image_topic: str, cloud_topic: str,
                 min_range_m: float = 0.05) -> Capture:
    name = bag.parent.name
    cache = cache_dir / scenario / f"{name}.npz"
    if cache.exists():
        z = np.load(cache)
        if int(z["version"]) == CACHE_VERSION:
            return Capture(name, scenario, bag, z["image"], float(z["image_std"]), int(z["n_images"]),
                           z["xyz_mm"].astype(np.float64) / 1000.0, z["intensity"].astype(np.float64),
                           z["frame"].astype(int), z["frame_time"], int(z["n_frames"]))

    images, image_t, clouds, cloud_t = read_bag(bag, image_topic, cloud_topic)
    if not images or not clouds:
        raise RuntimeError(f"{bag}: no image or cloud messages")
    stack = np.stack(images)
    median = np.median(stack, axis=0).astype(np.uint8)
    image_std = float(np.abs(stack.astype(np.float32) - median).mean())
    frame = np.concatenate([np.full(len(c), i, np.uint16) for i, c in enumerate(clouds)])
    pts = np.concatenate(clouds)
    good = np.isfinite(pts).all(1) & (np.linalg.norm(pts[:, :3], axis=1) > min_range_m)
    pts, frame = pts[good], frame[good]
    # Room-scale data: int16 millimetres (+/-32 m) is lossless for LiDAR precision
    # and keeps the cache ~4x smaller than float64.
    xyz_mm = np.clip(np.rint(pts[:, :3] * 1000.0), -32767, 32767).astype(np.int16)
    intensity = np.clip(np.rint(pts[:, 3]), 0, 255).astype(np.uint8)
    frame_time = cloud_t - image_t[0]
    cache.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(cache, version=CACHE_VERSION, image=median, image_std=image_std, n_images=len(images),
                        xyz_mm=xyz_mm, intensity=intensity, frame=frame, frame_time=frame_time,
                        n_frames=len(clouds))
    return Capture(name, scenario, bag, median, image_std, len(images), xyz_mm.astype(np.float64) / 1000.0,
                   intensity.astype(np.float64), frame.astype(int), frame_time, len(clouds))
