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


def _collect(link, topic, msgtype, seconds, decode, stop, on_item, out, every_s=None):
    """Thread body: decoded messages of one topic for `seconds`; with every_s, at most one message
    per every_s seconds (the reader pauses in between, so the device does not send the rest)."""
    try:
        stream = link.subscribe(topic, msgtype, throttle_s=every_s)
    except Exception as e:  # noqa: BLE001
        out["error"] = e
        return
    t0 = time.time()
    try:
        while not stop.is_set() and time.time() - t0 < seconds:
            t, m = stream.next()
            if every_s and out["items"] and t - out["items"][-1][0] < 0.5 * every_s:
                continue                                 # a message buffered during the pause
            item = decode(m)
            out["items"].append((t, item))
            on_item(item)
            if every_s:
                stop.wait(max(0.0, every_s - (time.time() - t)))
    except Exception as e:  # noqa: BLE001
        out["error"] = e
    finally:
        stream.close()


def capture_once(link, image_topic, cloud_topic, seconds, folder, progress=None, stop=None, image_hz=2.5):
    """One stacked capture; returns (npz path, summary). Images at most image_hz (a median of ~10 is
    plenty; the camera's 35 Hz is not needed); every LiDAR frame (the stacked cloud's density)."""
    stop = stop or threading.Event()
    dc = load_config()["decode"]
    imgs, clouds = dict(items=[]), dict(items=[])
    last = {}

    def on_img(im):
        last["image"] = im
        if progress:
            progress(dict(images=len(imgs["items"]), clouds=len(clouds["items"]), image=im))

    def on_cloud(c):
        if progress:
            progress(dict(images=len(imgs["items"]), clouds=len(clouds["items"]), image=last.get("image")))
    th = [threading.Thread(target=_collect, args=(link, image_topic, rl.IMAGE, seconds, rl.decode_image, stop, on_img, imgs, 1.0 / image_hz), daemon=True),
          threading.Thread(target=_collect, args=(link, cloud_topic, rl.CLOUD, seconds, rl.decode_cloud, stop, on_cloud, clouds), daemon=True)]
    for t in th:
        t.start()
    for t in th:
        t.join(seconds + 20)
    if stop.is_set():
        raise InterruptedError("capture stopped")
    for what, d in (("camera images", imgs), ("LiDAR frames", clouds)):
        if d.get("error") and not d["items"]:
            raise rl.LinkError(f"no {what}: {d['error']}")
    if len(imgs["items"]) < 3 or len(clouds["items"]) < 3:
        raise rl.LinkError(f"too little data: {len(imgs['items'])} images, {len(clouds['items'])} LiDAR frames in {seconds:.0f} s")

    import decode_bags  # Targetless calibration (read-only): moving-object frame filter
    cloud_t = np.array([t for t, _ in clouds["items"]])
    cl = [c for _, c in clouds["items"]]
    keep, frac = decode_bags.lidar_keep(cl, dc)
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
                     image_size=list(median.shape[1::-1]))


def snapshot(link, image_topic, cloud_topic, seconds=1.2):
    """One image and ~1 s of LiDAR for a quick look (not saved)."""
    stop = threading.Event()
    imgs, clouds = dict(items=[]), dict(items=[])
    th = [threading.Thread(target=_collect, args=(link, image_topic, rl.IMAGE, seconds, rl.decode_image, stop, lambda *_: None, imgs, 0.5), daemon=True),
          threading.Thread(target=_collect, args=(link, cloud_topic, rl.CLOUD, seconds, rl.decode_cloud, stop, lambda *_: None, clouds), daemon=True)]
    for t in th:
        t.start()
    for t in th:
        t.join(seconds + 15)
    errs = [d["error"] for d in (imgs, clouds) if d.get("error") and not d["items"]]
    if errs:
        raise rl.LinkError(str(errs[0]))
    image = imgs["items"][-1][1] if imgs["items"] else None
    cloud = np.concatenate([c for _, c in clouds["items"]]) if clouds["items"] else np.zeros((0, 4), np.float32)
    rate = lambda d: (len(d["items"]) - 1) / max(d["items"][-1][0] - d["items"][0][0], 1e-6) if len(d["items"]) > 1 else 0.0
    return dict(image=image, cloud=cloud, image_hz=rate(imgs), cloud_hz=rate(clouds))


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
