"""Capture stacked data from a connected device (live topics) in the same format as decoded bags.

One capture = the camera images and LiDAR frames of a few seconds: median image + merged cloud
(frames with many changed points, e.g. a person walking through, are dropped like in decode_bags).
Saved as <folder>/capture_<date>_<time>_<usec>_live.npz (+ .png), which maintain.py and the
targetless calibration read directly. The device is only read.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

import ros_link as rl
from settings import load_config

CACHE_VERSION = 2


def _collect(link, topic, msgtype, seconds, decode, stop, on_item, out, every_s=None,
             max_frames=None, finished=None, min_frames=0):
    """Thread body: decoded messages of one topic for `seconds`; with every_s, at most one message
    per every_s seconds (the reader pauses in between, so the device does not send the rest)."""
    try:
        stream = link.subscribe(topic, msgtype, throttle_s=every_s)
    except Exception as e:  # noqa: BLE001
        out["error"] = e
        return
    t0 = time.monotonic()
    try:
        while not stop.is_set() and time.monotonic() - t0 < seconds:
            if finished is not None and finished.is_set() and len(out["items"]) >= min_frames:
                break
            t, m = stream.next()
            if time.monotonic() - t0 > seconds:
                break
            if every_s and out["items"] and t - out["items"][-1][0] < 0.5 * every_s:
                continue                                 # a message buffered during the pause
            item = decode(m)
            out["items"].append((t, item))
            on_item(item)
            if max_frames is not None and len(out["items"]) >= max_frames:
                break
            if every_s:
                stop.wait(max(0.0, every_s - (time.time() - t)))
    except Exception as e:  # noqa: BLE001
        out["error"] = e
    finally:
        stream.close()


def collect_sample(link, image_topic, cloud_topic, seconds=1.0, lidar_frames=None,
                   progress=None, stop=None, image_hz=2.5, min_images=1, frame_timeout=120.0):
    """Read a timed LiDAR window or exactly N messages; camera follows the same window.

    A missing/slow stream raises an error rather than silently returning fewer requested frames.
    Camera may finish its minimum image count after a very short LiDAR sample.
    """
    if lidar_frames is not None and (int(lidar_frames) != lidar_frames or lidar_frames < 1):
        raise ValueError("LiDAR frame count must be a positive integer")
    if seconds <= 0:
        raise ValueError("LiDAR duration must be positive")
    stop = stop or threading.Event()
    imgs, clouds = dict(items=[]), dict(items=[])
    finished = threading.Event()
    started, last_emit = time.monotonic(), [0.0]
    timeout = frame_timeout if lidar_frames is not None else seconds

    def emit(force=False):
        now = time.monotonic()
        if progress is None or (not force and now - last_emit[0] < .25):
            return
        last_emit[0] = now
        frames = list(clouds['items'])
        # Preview is bounded; the saved data retains every selected LiDAR frame.
        sample = [c[::max(1, int(np.ceil(len(c) * max(1, len(frames)) / 60000)))] for _, c in frames]
        cloud = np.concatenate(sample) if sample else np.empty((0, 4), np.float32)
        progress(dict(images=len(imgs['items']), clouds=len(frames),
                      image=imgs['items'][-1][1] if imgs['items'] else None, cloud=cloud,
                      elapsed=now-started, target_frames=lidar_frames, target_seconds=seconds))

    def lidar_work():
        try:
            _collect(link, cloud_topic, rl.CLOUD, timeout, rl.decode_cloud, stop,
                     lambda _: emit(), clouds, max_frames=lidar_frames)
        finally:
            finished.set()

    camera = threading.Thread(target=_collect, args=(link, image_topic, rl.IMAGE,
        max(timeout, min_images / image_hz + 2), rl.decode_image, stop, lambda _: None, imgs, 1/image_hz),
        kwargs=dict(finished=finished, min_frames=min_images), daemon=True)
    lidar = threading.Thread(target=lidar_work, daemon=True)
    camera.start(); lidar.start()
    lidar.join(timeout + 12)
    camera.join(max(12, min_images / image_hz + 2))
    if stop.is_set():
        raise InterruptedError("capture stopped")
    if lidar.is_alive() or camera.is_alive():
        raise rl.LinkError("Sensor collection did not finish within its timeout")
    if lidar_frames is not None and len(clouds['items']) != lidar_frames:
        reason = clouds.get('error') or 'stream timeout'
        raise rl.LinkError(f"Received {len(clouds['items'])} of {lidar_frames} requested LiDAR frames: {reason}")
    emit(force=True)
    return imgs, clouds


def capture_once(link, image_topic, cloud_topic, seconds, folder, progress=None, stop=None, image_hz=2.5,
                 lidar_frames=None):
    """One stacked capture; returns (npz path, summary). Images at most image_hz (a median of ~10 is
    plenty; the camera's 35 Hz is not needed); every LiDAR frame (the stacked cloud's density)."""
    stop = stop or threading.Event()
    dc = load_config()["decode"]
    imgs, clouds = collect_sample(link, image_topic, cloud_topic, seconds, lidar_frames,
                                  progress, stop, image_hz, min_images=3)
    if stop.is_set():
        raise InterruptedError("capture stopped")
    for what, d in (("camera images", imgs), ("LiDAR frames", clouds)):
        if d.get("error") and not d["items"]:
            raise rl.LinkError(f"no {what}: {d['error']}")
    if len(imgs["items"]) < 3 or len(clouds["items"]) < 1:
        raise rl.LinkError(f"too little data: {len(imgs['items'])} images, {len(clouds['items'])} LiDAR frames in {seconds:.0f} s")

    cloud_t = np.array([t for t, _ in clouds["items"]])
    cl = [c for _, c in clouds["items"]]
    keep = np.ones(len(cl), dtype=bool)
    if lidar_frames is None and len(cl) >= 3:
        import decode_bags  # Targetless calibration (read-only): moving-object frame filter
        keep = decode_bags.lidar_keep(cl, dc)[0]
    sel = np.flatnonzero(keep)
    stack = np.stack([im for _, im in imgs["items"]])
    median = np.median(stack, axis=0).astype(np.uint8)
    pts = np.concatenate([cl[k] for k in sel])
    frame = np.concatenate([np.full(len(cl[k]), j, np.uint16) for j, k in enumerate(sel)])
    good = np.isfinite(pts).all(1) & (np.linalg.norm(pts[:, :3], axis=1) > 0.05)
    pts, frame = pts[good], frame[good]
    stamp = datetime.now()
    out = Path(folder) / f"capture_{stamp:%Y%m%d_%H%M%S}_{stamp:%f}_live.npz"
    out.parent.mkdir(parents=True, exist_ok=True)
    t0 = imgs["items"][0][0]
    np.savez_compressed(out, version=CACHE_VERSION, image=median, image_std=float(np.abs(stack.astype(np.float32) - median).mean()),
                        n_images=len(stack), xyz_mm=np.clip(np.rint(pts[:, :3] * 1000), -32767, 32767).astype(np.int16),
                        intensity=np.clip(np.rint(pts[:, 3]), 0, 255).astype(np.uint8), frame=frame,
                        frame_time=cloud_t[sel] - t0, n_frames=len(sel))
    cv2.imwrite(str(out.with_suffix(".png")), median)
    return out, dict(capture=out.stem, images=len(stack), lidar_frames=len(cl), lidar_frames_used=len(sel),
                     lidar_frames_dropped=int((~keep).sum()), lidar_points=len(pts), seconds=seconds,
                     lidar_target_frames=lidar_frames, image_size=list(median.shape[1::-1]))


def snapshot(link, image_topic, cloud_topic, seconds=1.0, lidar_frames=None, progress=None, stop=None):
    """One image and ~1 s of LiDAR for a quick look (not saved)."""
    imgs, clouds = collect_sample(link, image_topic, cloud_topic, seconds, lidar_frames, progress, stop)
    errs = [d["error"] for d in (imgs, clouds) if d.get("error") and not d["items"]]
    if errs and not imgs["items"] and not clouds["items"]:
        raise rl.LinkError(str(errs[0]))
    image = imgs["items"][-1][1] if imgs["items"] else None
    cloud = np.concatenate([c for _, c in clouds["items"]]) if clouds["items"] else np.zeros((0, 4), np.float32)
    rate = lambda d: (len(d["items"]) - 1) / max(d["items"][-1][0] - d["items"][0][0], 1e-6) if len(d["items"]) > 1 else 0.0
    return dict(image=image, cloud=cloud, image_hz=rate(imgs), cloud_hz=rate(clouds),
                lidar_frames=len(clouds['items']), lidar_target_frames=lidar_frames, lidar_seconds=seconds,
                errors={name: str(data['error']) for name, data in (("camera", imgs), ("LiDAR", clouds))
                        if data.get("error") and not data["items"]})


def overlay(image, xyz, params, max_points=60000):
    """LiDAR points drawn on the image with the device's own camera model, coloured by range:
    what the device's colouring uses right now."""
    import device_model as dm
    p = dm.device_params(params)
    K, D, T = np.array(p["camera_matrix"]), np.array(p["dist_coeffs"]), np.array(p["extrinsic_matrix"])
    pts = xyz[:: max(1, len(xyz) // max_points), :3].astype(float)
    c = pts @ T[:3, :3].T + T[:3, 3]
    th = np.arctan2(np.hypot(c[:, 0], c[:, 1]), np.maximum(c[:, 2], 1e-9))
    ph = np.arctan2(c[:, 1], c[:, 0])
    u, v = dm.pinhole_uv(th, ph, K[0, 0], K[1, 1], K[0, 2], K[1, 2], D)
    ok = (c[:, 2] > 0) & (th < np.radians(dm.pinhole_fold_deg(D))) & (u >= 0) & (u < image.shape[1]) & (v >= 0) & (v < image.shape[0])
    rng = np.linalg.norm(pts, axis=1)
    img = (image.astype(np.float32) * 0.55).astype(np.uint8)
    col = cv2.applyColorMap(np.clip((np.log(np.clip(rng[ok], 0.5, 30)) - np.log(0.5)) / (np.log(30) - np.log(0.5)) * 255, 0, 255)
                            .astype(np.uint8).reshape(-1, 1), cv2.COLORMAP_TURBO).reshape(-1, 3)
    order = np.argsort(-rng[ok])                      # near points drawn last
    for (x, y), cc in zip(np.stack([u[ok], v[ok]], 1)[order].astype(int), col[order]):
        img[y, x] = cc
    return img, int(ok.sum())
