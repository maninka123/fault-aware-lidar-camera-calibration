"""Step 4: projection images to compare the two calibrations by eye.

For every capture of every device, results/<device>/projection_compare/:
  <capture>.png        four panels
     top left    Oct 29: LiDAR edges projected on the image, coloured by the distance to the nearest
                 image edge (green <= 1 px, yellow 1-3 px, red > 3 px)
     top right   targetless: the same
     bottom left difference map: every LiDAR point coloured by how far apart (px) the two
                 calibrations put it
     bottom right zooms at 1-1.5 / 1.5-3 / 3-5 / 5-10 m: Oct 29 (blue dots) and targetless
                 (orange rings) projections of the LiDAR edges on the photo
  <capture>_flicker.gif  the LiDAR depth overlay of the two calibrations, alternating
LiDAR edges from 1 m and LiDAR points from 0.5 m are shown (the calibration itself uses >= 1.5 m),
so the close-range difference is visible. Each calibration is drawn with its own model (the targetless one includes
its beam-widening correction of depth-edge points).

Usage:  python step4_images.py [--devices pair_4]
"""
from __future__ import annotations

import argparse
import json

from common import devices, image_circle, imwrite, load_config, load_frames, log, output_dir

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

import calib as cb  # noqa: E402
import evaluate as ev  # noqa: E402
import image_edges as ie  # noqa: E402
import lidar_edges as le  # noqa: E402
from step2_compare import params_from  # noqa: E402

S = 2                                          # panel upscale
BLUE, ORANGE = (214, 120, 42), (52, 104, 235)  # BGR of #2a78d6 (Oct 29), #eb6834 (targetless)
GOOD, WARN, BAD = (12, 163, 12), (25, 178, 250), (59, 59, 208)   # status palette, BGR
RAMP = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]   # blue 100..700
BANDS = ((1.0, 1.5), (1.5, 3.0), (3.0, 5.0), (5.0, 10.0))
FONT = cv2.FONT_HERSHEY_SIMPLEX


def _bgr(h):
    return tuple(int(h[i:i + 2], 16) for i in (5, 3, 1))


RAMP_BGR = np.array([_bgr(h) for h in RAMP], float)


def ramp(x):
    """0..1 -> blue ramp (light = small difference, dark = large)."""
    t = np.clip(x, 0, 1) * (len(RAMP_BGR) - 1)
    i = np.minimum(t.astype(int), len(RAMP_BGR) - 2)
    f = (t - i)[:, None]
    return RAMP_BGR[i] * (1 - f) + RAMP_BGR[i + 1] * f


def to_panel(u, v):
    return (u + 0.5) * S - 0.5, (v + 0.5) * S - 0.5


def title_bar(width, text, sub=None, h=46):
    bar = np.full((h, width, 3), 255, np.uint8)
    cv2.putText(bar, text, (12, 20), FONT, 0.6, (11, 11, 11), 1, cv2.LINE_AA)
    if sub:
        cv2.putText(bar, sub, (12, 39), FONT, 0.45, (78, 81, 82), 1, cv2.LINE_AA)
    return bar


def legend(img, items, y0=None):
    """items: [(colour, label, kind)], drawn bottom-left on a white strip."""
    h = 22 * len(items) + 10
    y0 = img.shape[0] - h if y0 is None else y0
    w = 12 + max(cv2.getTextSize(t, FONT, 0.45, 1)[0][0] for _, t, _ in items) + 34
    cv2.rectangle(img, (0, y0), (w, y0 + h), (255, 255, 255), -1)
    for k, (col, text, kind) in enumerate(items):
        y = y0 + 16 + 22 * k
        if kind == "ring":
            cv2.circle(img, (20, y - 4), 5, col, 2, cv2.LINE_AA)
        else:
            cv2.circle(img, (20, y - 4), 5, col, -1, cv2.LINE_AA)
        cv2.putText(img, text, (34, y), FONT, 0.45, (11, 11, 11), 1, cv2.LINE_AA)


def base(image, fade=0.55):
    g = cv2.cvtColor(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
    g = cv2.resize(g, None, fx=S, fy=S, interpolation=cv2.INTER_CUBIC)
    return (g * (1 - fade) + 255 * fade * 0.25).astype(np.uint8)


def project_edges(model, cap, p):
    Pc = model.to_camera(cap.xyz, cap.sgn, p)
    u, v, ok = model.project(Pc, p)
    return u, v, ok, np.linalg.norm(cap.xyz, axis=1)


def alignment_panel(frame, cap, model, p, label):
    img = base(frame.image)
    img[cv2.resize(cap.img["mask"].astype(np.uint8), None, fx=S, fy=S, interpolation=cv2.INTER_NEAREST) > 0] = (175, 175, 175)
    u, v, ok, _ = project_edges(model, cap, p)
    ui = np.clip(np.rint(u).astype(int), 0, model.w - 1); vi = np.clip(np.rint(v).astype(int), 0, model.h - 1)
    d = np.where(ok, cap.img["dist"][vi, ui], np.inf)
    pu, pv = to_panel(u, v)
    for x, y, dd, o in zip(pu, pv, d, ok):
        if o:
            cv2.circle(img, (int(round(x)), int(round(y))), 2, GOOD if dd <= 1 else WARN if dd <= 3 else BAD, -1, cv2.LINE_AA)
    on = float(np.mean(d[ok] <= 1)) * 100 if ok.any() else 0.0
    cv2.rectangle(img, (0, 0), (img.shape[1], 30), (255, 255, 255), -1)
    cv2.putText(img, f"{label}:  {on:.0f}% of LiDAR edge points on an image edge (<= 1 px)", (10, 21), FONT, 0.55,
                (11, 11, 11), 1, cv2.LINE_AA)
    legend(img, [(GOOD, "LiDAR edge on image edge (<= 1 px)", "dot"), (WARN, "1-3 px off", "dot"),
                 (BAD, "> 3 px off (or no matching image edge)", "dot"), ((175, 175, 175), "image edges (Canny)", "dot")])
    return img, on


def difference_panel(frame, model, p_o, p_t, cap_max=8.0):
    img = base(frame.image, fade=0.8)
    xyz = frame.xyz[::4]
    xyz = xyz[np.linalg.norm(xyz, axis=1) > 0.5]
    z = np.zeros(len(xyz))
    ua, va, oka = model.project(model.to_camera(xyz, z, p_o), p_o)
    ub, vb, okb = model.project(model.to_camera(xyz, z, p_t), p_t)
    ok = oka & okb
    dpx = np.hypot(ua - ub, va - vb)[ok]
    col = ramp(dpx / cap_max)
    pu, pv = to_panel(ub[ok], vb[ok])
    order = np.argsort(dpx)                          # large differences drawn last (on top)
    for k in order:
        cv2.circle(img, (int(round(pu[k])), int(round(pv[k]))), 1, tuple(int(c) for c in col[k]), -1)
    r = np.linalg.norm(xyz[ok], axis=1)
    stats = []
    for lo, hi in ((0.5, 1.5),) + BANDS[1:]:
        m = (r >= lo) & (r < hi)
        if m.sum() > 50:
            stats.append(f"{lo:g}-{hi:g} m: {np.median(dpx[m]):.1f}")
    cv2.rectangle(img, (0, 0), (img.shape[1], 30), (255, 255, 255), -1)
    cv2.putText(img, "Difference: px between where the two calibrations put each LiDAR point", (10, 21), FONT, 0.55,
                (11, 11, 11), 1, cv2.LINE_AA)
    # colour bar
    x0, y0, w, h = 12, img.shape[0] - 70, 300, 14
    text = "median by range: " + ",  ".join(stats) + " px"
    tw = cv2.getTextSize(text, FONT, 0.42, 1)[0][0]
    cv2.rectangle(img, (0, y0 - 26), (max(x0 + w + 60, x0 + tw + 12), img.shape[0]), (255, 255, 255), -1)
    bar = ramp(np.linspace(0, 1, w)).astype(np.uint8)[None].repeat(h, 0)
    img[y0:y0 + h, x0:x0 + w] = bar
    for val in (0, 2, 4, 6, 8):
        x = x0 + int(val / cap_max * (w - 1))
        cv2.line(img, (x, y0 + h), (x, y0 + h + 4), (78, 81, 82), 1)
        cv2.putText(img, f"{val}" + (" px" if val == 8 else ""), (x - 4, y0 + h + 17), FONT, 0.4, (78, 81, 82), 1, cv2.LINE_AA)
    cv2.putText(img, text, (x0, y0 - 8), FONT, 0.42, (11, 11, 11), 1, cv2.LINE_AA)
    return img


def zoom_panels(frame, cap, model, p_o, p_t, size=48, out=366, ref_label="Oct 29"):
    """One crop per range band where the LiDAR edges are densest; both projections on the photo."""
    uo, vo, oko, r = project_edges(model, cap, p_o)
    ut, vt, okt, _ = project_edges(model, cap, p_t)
    dist = lambda u, v: cap.img["dist"][np.clip(np.rint(v).astype(int), 0, model.h - 1), np.clip(np.rint(u).astype(int), 0, model.w - 1)]
    real = (dist(uo, vo) <= 2) | (dist(ut, vt) <= 2)      # LiDAR edges on real image structure under either calibration
    tiles = []
    used = []
    for lo, hi in BANDS:
        m = okt & oko & (r >= lo) & (r < hi) & real
        tile = np.full((out, out, 3), 245, np.uint8)
        if m.sum() >= 15:
            cell = (np.floor(ut[m] / size * 2).astype(int), np.floor(vt[m] / size * 2).astype(int))   # half-overlapping cells
            keys, counts = np.unique(np.c_[cell], axis=0, return_counts=True)
            for kk in np.argsort(-counts):
                cx, cy = (keys[kk] + 1) * size / 2
                if all(abs(cx - a) > size or abs(cy - b) > size for a, b in used) or kk == np.argsort(-counts)[-1]:
                    break
            used.append((cx, cy))
            x0 = int(np.clip(cx - size / 2, 0, model.w - size)); y0 = int(np.clip(cy - size / 2, 0, model.h - size))
            sc = out / size
            tile = cv2.resize(frame.image[y0:y0 + size, x0:x0 + size], (out, out), interpolation=cv2.INTER_CUBIC)
            tile = (tile * 0.75 + 255 * 0.25).astype(np.uint8)
            sel = np.flatnonzero(okt & oko & (r >= lo) & (r < hi) & (np.abs(ut - cx) < size) & (np.abs(vt - cy) < size))
            to = lambda u, v: (int(round((u - x0 + 0.5) * sc - 0.5)), int(round((v - y0 + 0.5) * sc - 0.5)))
            for k in sel:
                cv2.circle(tile, to(uo[k], vo[k]), 4, BLUE, -1, cv2.LINE_AA)
            for k in sel:
                cv2.circle(tile, to(ut[k], vt[k]), 6, ORANGE, 2, cv2.LINE_AA)
            d = np.median(np.hypot(uo[sel] - ut[sel], vo[sel] - vt[sel]))
            txt = f"{lo:g}-{hi:g} m   shift {d:.1f} px"
        else:
            txt = f"{lo:g}-{hi:g} m: no LiDAR edges"
        cv2.rectangle(tile, (0, 0), (out, 24), (255, 255, 255), -1)
        cv2.putText(tile, txt, (8, 17), FONT, 0.5, (11, 11, 11), 1, cv2.LINE_AA)
        cv2.rectangle(tile, (0, 0), (out - 1, out - 1), (200, 200, 200), 1)
        tiles.append(tile)
    grid = np.vstack([np.hstack(tiles[:2]), np.hstack(tiles[2:])])
    pad = np.full((grid.shape[0], model.w * S - grid.shape[1], 3), 255, np.uint8)
    legend(pad, [(BLUE, ref_label, "dot"), (ORANGE, "targetless", "ring")], y0=8)
    cv2.putText(pad, "zoom x7.6", (12, 80), FONT, 0.45, (78, 81, 82), 1, cv2.LINE_AA)
    cv2.putText(pad, "same LiDAR edges,", (12, 104), FONT, 0.45, (78, 81, 82), 1, cv2.LINE_AA)
    cv2.putText(pad, "two calibrations", (12, 124), FONT, 0.45, (78, 81, 82), 1, cv2.LINE_AA)
    return np.hstack([grid, pad])


def flicker(frame, model, p_o, p_t, path, ref_label="Oct 29 checkerboard"):
    from step1_calibrate import depth_overlay
    a = depth_overlay(frame, model, p_o, ref_label, step=2)
    b = depth_overlay(frame, model, p_t, "targetless", step=2)
    for img, col in ((a, BLUE), (b, ORANGE)):
        cv2.rectangle(img, (0, 0), (img.shape[1] - 1, img.shape[0] - 1), col, 6)
    frames = [Image.fromarray(cv2.cvtColor(x, cv2.COLOR_BGR2RGB)) for x in (a, b)]
    path.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=900, loop=0)


def compare_image(frame, cap, model, p_o, p_t, title, ref_label):
    """The four-panel comparison image (reference vs targetless)."""
    left, on_o = alignment_panel(frame, cap, model, p_o, ref_label)
    right, on_t = alignment_panel(frame, cap, model, p_t, "Targetless (no target)")
    gap = np.full((left.shape[0], 8, 3), 255, np.uint8)
    top = np.hstack([left, gap, right])
    bottom = np.hstack([difference_panel(frame, model, p_o, p_t), gap, zoom_panels(frame, cap, model, p_o, p_t, ref_label=ref_label.split(" (")[0])])
    body = np.vstack([top, np.full((8, top.shape[1], 3), 255, np.uint8), bottom])
    head = title_bar(body.shape[1], title, "Top: alignment of LiDAR edges with image edges (the targetless method optimises this, so "
                     "it is not an independent score). Bottom: where and by how much the two differ.")
    return np.vstack([head, body]), on_o, on_t


def run_device(cfg, device):
    out = output_dir(cfg) / device
    cal = json.loads((out / "calibration.json").read_text())
    K = np.array(cal["intrinsics"]["camera_matrix"]); D = np.array(cal["intrinsics"]["distortion_coefficients"])
    T = np.array(cal["extrinsics"]["transform_lidar_to_camera"])
    o = ev.oct29(cfg, device)
    frames = load_frames(cfg, device)
    circle = image_circle(frames)
    model = cb.Model(cfg["prior"]["rotation_lidar_to_camera"], frames[0].image.shape[1::-1], circle)
    p_t = params_from(K, D, T, model.R0, np.radians(cal["beam_inflation_deg"]))
    p_o = params_from(o["K"], o["D"], o["T"], model.R0, 0.0)
    lc = dict(cfg["lidar"], min_range_m=1.0)          # show closer edges than the calibration uses (1.5 m)
    rows = []
    for f in frames:
        cap = cb.from_edges(f.short, le.extract(f, lc, cfg["seed"])[0], ie.extract(f.image, circle, cfg["image"]))
        img, on_o, on_t = compare_image(f, cap, model, p_o, p_t, f"{device}  capture {f.short}:  Oct 29 checkerboard "
                                        "calibration vs targetless calibration", "Oct 29 checkerboard")
        imwrite(out / "projection_compare" / f"{f.short}.png", img)
        flicker(f, model, p_o, p_t, out / "projection_compare" / f"{f.short}_flicker.gif")
        rows.append((f.short, on_o, on_t))
    log(f"{device}: {len(frames)} images; LiDAR edges on image edges, Oct 29 vs targetless: "
        f"{np.mean([r[1] for r in rows]):.0f}% vs {np.mean([r[2] for r in rows]):.0f}%")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--devices", nargs="*")
    a = ap.parse_args()
    cfg = load_config()
    for d in a.devices or devices(cfg):
        run_device(cfg, d)
    log("done")


if __name__ == "__main__":
    main()
