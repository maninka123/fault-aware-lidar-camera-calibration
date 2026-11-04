"""Decode raw captures (ROS1 bags) into stacked captures, without any calibration target.

Input:  a folder with capture_*/rig_0.bag (+ capture.json), as recorded by the capture UI.
Output: stacked_data/<name>/<capture>.npz (+ .png), the same format as the Oct 29 stacked data,
        and results/<name>/00_decode/ (motion plots, summary.csv).

For each capture:
  1. images (BGR) and Livox clouds are read (topics found by message type);
  2. still window: natural image corners (KLT) are tracked in every frame against the all-frame
     median image; the window is the longest one (max_s .. min_s) in which 80 % of the corners
     stay within the tolerance of their window median; among equal lengths the stillest wins;
     the tolerance is relaxed step by step only if no window passes. The rig is rigid, so camera
     stillness is LiDAR stillness;
  3. LiDAR frames of the window with many changed points (people walking through) are dropped;
  4. median image + merged cloud are written.

Usage:  python decode_bags.py "<folder with capture_* dirs>" --name creep_data
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from common import PROJECT, image_circle, imwrite, load_config, log, output_dir, short_name, stacked_root

import cv2  # noqa: E402
import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, str(PROJECT / "multi_capture_calibration"))
from mcc.bag_io import CACHE_VERSION, _decode_cloud, _decode_image  # noqa: E402  (read-only import)

BLUE, INK2, GRID, SURFACE = "#2a78d6", "#52514e", "#e4e3df", "#fcfcfb"


def read_bag(bag):
    """Images (BGR), image times, clouds (N, 4), cloud times; topics found by message type."""
    from rosbags.highlevel import AnyReader
    images, image_t, clouds, cloud_t = [], [], [], []
    with AnyReader([bag]) as reader:
        img_c = [c for c in reader.connections if c.msgtype == "sensor_msgs/msg/Image"]
        pc_c = [c for c in reader.connections if c.msgtype == "sensor_msgs/msg/PointCloud2"]
        if len(img_c) != 1 or len(pc_c) != 1:
            raise RuntimeError(f"{bag}: expected one image and one point-cloud topic, got "
                               f"{[c.topic for c in img_c]} / {[c.topic for c in pc_c]}")
        for con, stamp, raw in reader.messages(connections=img_c + pc_c):
            msg = reader.deserialize(raw, con.msgtype)
            if con in img_c:     # record time: the Livox header stamp is on a different clock
                images.append(_decode_image(msg)); image_t.append(stamp * 1e-9)
            else:
                clouds.append(_decode_cloud(msg)); cloud_t.append(stamp * 1e-9)
    return images, np.asarray(image_t), clouds, np.asarray(cloud_t), img_c[0].topic, pc_c[0].topic


def track_features(images, circle, dc):
    """Positions (frames, features, 2) of natural corners tracked from the median image (NaN = lost)."""
    grays = [cv2.cvtColor(im, cv2.COLOR_BGR2GRAY) for im in images]
    ref = np.median(np.stack(grays), axis=0).astype(np.uint8)
    h, w = ref.shape
    yy, xx = np.mgrid[:h, :w]
    mask = (((xx - circle["cx"]) ** 2 + (yy - circle["cy"]) ** 2) <= (0.9 * circle["radius"]) ** 2).astype(np.uint8) * 255
    p0 = cv2.goodFeaturesToTrack(ref, dc["max_features"], 0.01, 7, mask=mask, blockSize=5)
    if p0 is None or len(p0) < 20:
        raise RuntimeError("too few image features to judge stillness")
    lk = dict(winSize=(15, 15), maxLevel=2, criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01))
    out = np.full((len(grays), len(p0), 2), np.nan)
    for i, g in enumerate(grays):
        p1, st, _ = cv2.calcOpticalFlowPyrLK(ref, g, p0, None, **lk)
        pb, st2, _ = cv2.calcOpticalFlowPyrLK(g, ref, p1, None, **lk)
        ok = (st.ravel() == 1) & (st2.ravel() == 1) & (np.linalg.norm((pb - p0).reshape(-1, 2), axis=1) < 0.2)
        out[i, ok] = p1.reshape(-1, 2)[ok]
    return out


def window_motion(tracks, i0, i1, q):
    """q-quantile over features of the largest deviation from the feature's window median."""
    w = tracks[i0:i1]
    med = np.nanmedian(w, axis=0)
    dev = np.nanmax(np.linalg.norm(w - med, axis=2), axis=0)
    dev = dev[np.isfinite(dev)]
    return float(np.quantile(dev, q)) if len(dev) else np.inf


def still_window(tracks, t, dc):
    """(i0, i1, tolerance, motion): longest window passing the tolerance, stillest among equals."""
    fps = (len(t) - 1) / max(t[-1] - t[0], 1e-6)
    for tol in dc["tolerance_px"]:
        for length in np.arange(dc["max_s"], dc["min_s"] - 1e-9, -dc["step_s"]):
            n = int(round(length * fps)) + 1
            if n > len(t):
                continue
            best = None
            for i0 in range(0, len(t) - n + 1):
                m = window_motion(tracks, i0, i0 + n, dc["feature_quantile"])
                if m <= tol and (best is None or m < best[3]):
                    best = (i0, i0 + n, tol, m)
            if best:
                return best
    n = int(round(dc["min_s"] * fps)) + 1           # nothing passed: stillest shortest window
    ms = [window_motion(tracks, i0, i0 + n, dc["feature_quantile"]) for i0 in range(len(t) - n + 1)]
    i0 = int(np.argmin(ms))
    return i0, i0 + n, np.inf, ms[i0]


def lidar_keep(clouds, dc):
    """Drop frames with many changed points relative to the static range image of the window."""
    b = np.radians(dc["lidar_bin_deg"])
    keys, rngs = [], []
    for c in clouds:
        xyz = c[:, :3]
        r = np.linalg.norm(xyz, axis=1)
        ok = r > 0.3
        az = np.arctan2(xyz[ok, 1], xyz[ok, 0]); el = np.arctan2(xyz[ok, 2], np.hypot(xyz[ok, 0], xyz[ok, 1]))
        keys.append(np.floor(az / b).astype(np.int64) * 100000 + np.floor(el / b).astype(np.int64)); rngs.append(r[ok])
    allk = np.concatenate(keys); allr = np.concatenate(rngs)
    uk, inv = np.unique(allk, return_inverse=True)
    order = np.argsort(inv, kind="stable")
    static = np.array([np.median(g) for g in np.split(allr[order], np.cumsum(np.bincount(inv))[:-1])])
    frac = []
    for k, r in zip(keys, rngs):
        s = static[np.searchsorted(uk, k)]
        frac.append(float(np.mean(np.abs(r - s) > np.maximum(dc["lidar_change_abs_m"], dc["lidar_change_rel"] * s))))
    frac = np.array(frac)
    med = np.median(frac); mad = np.median(np.abs(frac - med)) * 1.4826
    return frac <= med + dc["robust_k"] * mad + dc["lidar_change_floor"], frac


def motion_figure(tracks, t, i0, i1, name, path):
    ref = np.nanmedian(tracks[i0:i1], axis=0)
    dev = np.nanmedian(np.linalg.norm(tracks - ref, axis=2), axis=1)
    fig, ax = plt.subplots(figsize=(7, 2.6), facecolor=SURFACE)
    ax.set_facecolor(SURFACE)
    ax.axvspan(t[i0] - t[0], t[i1 - 1] - t[0], color="#cde2fb", lw=0)
    ax.plot(t - t[0], dev, color=BLUE, lw=2)
    ax.text(t[i0] - t[0], ax.get_ylim()[1] * 0.92, " stacked window", color=INK2, fontsize=8, va="top")
    ax.set_xlabel("time (s)", color=INK2, fontsize=9); ax.set_ylabel("image motion (px)", color=INK2, fontsize=9)
    ax.set_title(f"{name}: median motion of natural image corners vs the stacked window", loc="left", fontsize=9)
    ax.grid(axis="y", color=GRID); ax.set_axisbelow(True)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    for sp in ("left", "bottom"):
        ax.spines[sp].set_color(GRID)
    ax.tick_params(colors=INK2, length=0, labelsize=8)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)


def decode_capture(cdir, name, cfg, circle=None):
    dc = cfg["decode"]
    images, image_t, clouds, cloud_t, itopic, ctopic = read_bag(cdir / "rig_0.bag")
    if not images or not clouds:
        raise RuntimeError(f"{cdir}: no images or clouds")
    if circle is None:
        circle = image_circle([type("F", (), {"image": np.median(np.stack(images), axis=0).astype(np.uint8)})])
    tracks = track_features(images, circle, dc)
    i0, i1, tol, motion = still_window(tracks, image_t, dc)
    ta, tb = image_t[i0], image_t[i1 - 1]
    sel = np.flatnonzero((cloud_t >= ta - 0.05) & (cloud_t <= tb + 0.05))
    keep, frac = lidar_keep([clouds[k] for k in sel], dc)
    sel = sel[keep]
    stack = np.stack(images[i0:i1])
    median = np.median(stack, axis=0).astype(np.uint8)
    pts = np.concatenate([clouds[k] for k in sel])
    frame = np.concatenate([np.full(len(clouds[k]), j, np.uint16) for j, k in enumerate(sel)])
    good = np.isfinite(pts).all(1) & (np.linalg.norm(pts[:, :3], axis=1) > 0.05)
    pts, frame = pts[good], frame[good]
    out = stacked_root(cfg) / name / f"{cdir.name}.npz"
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out, version=CACHE_VERSION, image=median,
                        image_std=float(np.abs(stack.astype(np.float32) - median).mean()), n_images=len(stack),
                        xyz_mm=np.clip(np.rint(pts[:, :3] * 1000), -32767, 32767).astype(np.int16),
                        intensity=np.clip(np.rint(pts[:, 3]), 0, 255).astype(np.uint8), frame=frame,
                        frame_time=cloud_t[sel] - image_t[0], n_frames=len(sel))
    imwrite(out.with_suffix(".png"), median)
    motion_figure(tracks, image_t, i0, i1, short_name(cdir.name), output_dir(cfg) / name / "00_decode" / f"motion_{short_name(cdir.name)}.png")
    return dict(capture=short_name(cdir.name), image_topic=itopic, cloud_topic=ctopic, images=len(images),
                clouds=len(clouds), bag_seconds=float(image_t[-1] - image_t[0]), window_start_s=float(ta - image_t[0]),
                window_s=float(tb - ta), tolerance_px=tol, motion_px=motion, tracked_features=int(np.isfinite(tracks[:, :, 0]).all(0).sum()),
                images_stacked=len(stack), lidar_frames_stacked=len(sel), lidar_frames_dropped=int((~keep).sum()),
                lidar_points=len(pts)), circle


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", help="folder with capture_*/rig_0.bag")
    ap.add_argument("--name", required=True, help="dataset name (output folder)")
    a = ap.parse_args()
    cfg = load_config()
    caps = sorted(p for p in Path(a.folder).glob("capture_*") if (p / "rig_0.bag").exists())
    if not caps:
        raise SystemExit(f"no capture_*/rig_0.bag in {a.folder}")
    rows, circle = [], None
    for c in caps:
        row, circle = decode_capture(c, a.name, cfg, circle)
        rows.append(row)
        log(f"{row['capture']}: {row['images']} images / {row['clouds']} clouds over {row['bag_seconds']:.1f} s; "
            f"still window {row['window_s']:.1f} s at {row['window_start_s']:.1f} s (motion {row['motion_px']:.2f} px, "
            f"tolerance {row['tolerance_px']}); stacked {row['images_stacked']} images, {row['lidar_frames_stacked']} LiDAR "
            f"frames ({row['lidar_frames_dropped']} dropped), {row['lidar_points']} points")
    path = output_dir(cfg) / a.name / "00_decode" / "summary.csv"
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)
    log(f"{len(rows)} captures -> {stacked_root(cfg) / a.name}")


if __name__ == "__main__":
    main()
