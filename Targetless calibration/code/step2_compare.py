"""Step 2: compare the targetless calibration with the Oct 29 checkerboard calibration.

Same stacked captures, same devices. Measures:
  * board check (independent of the targetless method, which never saw the board): RMS of the
    Oct 29 LiDAR board corners projected into the image vs the camera corners, per capture.
    The Oct 29 numbers are its own leave-one-capture-out (held-out) errors on the same boards.
  * pose and intrinsics differences, and how many pixels apart the two calibrations put the
    LiDAR points at 0.5-1.5 / 1.5-3 / 3-5 / 5-10 m;
  * scene alignment of both calibrations (edge-alignment lift, NID) - what the targetless
    method optimises, so not an independent check;
  * stability: translation change when one capture is left out (both methods).
Writes results/comparison.csv, results/figures/, results/<device>/comparison/ and ../README.md.

Usage:  python step2_compare.py [--devices pair_4]
"""
from __future__ import annotations

import argparse
from pathlib import Path
import csv
import json

from common import ROOT, devices, image_circle, imwrite, load_config, load_frames, log, output_dir

import cv2  # noqa: E402
import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from scipy.spatial.transform import Rotation  # noqa: E402

import calib as cb  # noqa: E402
import evaluate as ev  # noqa: E402
import image_edges as ie  # noqa: E402
import lidar_edges as le  # noqa: E402

BLUE, ORANGE = "#2a78d6", "#eb6834"          # validated categorical slots 1-2 (dataviz palette)
INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
BANDS = ((0.5, 1.5), (1.5, 3), (3, 5), (5, 10))


def params_from(K, D, T, R0, delta=0.0):
    p = np.zeros(13)
    p[:3] = Rotation.from_matrix(T[:3, :3] @ np.asarray(R0).T).as_rotvec()
    p[3:6] = T[:3, 3]
    p[6:10] = K[0, 0], K[1, 1], K[0, 2], K[1, 2]
    p[10:12] = np.ravel(D)[:2]
    p[12] = delta
    return p


def pooled_rms(errors):
    v = np.array(list(errors.values()))
    return float(np.sqrt(np.mean(v ** 2))) if len(v) else float("nan")


def side_by_side(frame, model, pa, pb, la, lb, step=2):
    from step1_calibrate import depth_overlay
    a = depth_overlay(frame, model, pa, la, step)
    b = depth_overlay(frame, model, pb, lb, step)
    return np.hstack([a, np.full((a.shape[0], 6, 3), 255, np.uint8), b])


def board_zoom(frame, corners, K, D, Ta, Tb, height=700):
    """Crop around the board: camera corners (white +), Oct 29 projection (blue o), targetless (orange x)."""
    xyz, uv = corners
    lo, hi = uv.min(0) - 12, uv.max(0) + 12
    x0, y0 = np.maximum(np.floor(lo).astype(int), 0)
    x1, y1 = np.minimum(np.ceil(hi).astype(int), frame.image.shape[1::-1])
    scale = height / (y1 - y0)
    img = cv2.resize(frame.image[y0:y1, x0:x1], None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    to = lambda p: (int(round((p[0] - x0 + 0.5) * scale - 0.5)), int(round((p[1] - y0 + 0.5) * scale - 0.5)))
    for (Kk, Dk, Tk), col, mk in (((K[0], D[0], Ta), (214, 120, 42), "o"), ((K[1], D[1], Tb), (52, 104, 235), "x")):
        for p in ev.project(xyz, Kk, Dk, Tk):
            c = to(p)
            if mk == "o":
                cv2.circle(img, c, 9, col, 2, cv2.LINE_AA)
            else:
                cv2.drawMarker(img, c, col, cv2.MARKER_TILTED_CROSS, 18, 3, cv2.LINE_AA)
    for p in uv:
        cv2.drawMarker(img, to(p), (255, 255, 255), cv2.MARKER_CROSS, 14, 2, cv2.LINE_AA)
    cv2.rectangle(img, (0, 0), (img.shape[1], 28), (0, 0, 0), -1)
    cv2.putText(img, "board zoom: + camera, o Oct 29, x targetless", (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    return img


def compare_device(cfg, device):
    out = output_dir(cfg) / device
    cal = json.loads((out / "calibration.json").read_text())
    K = np.array(cal["intrinsics"]["camera_matrix"]); D = np.array(cal["intrinsics"]["distortion_coefficients"])
    T = np.array(cal["extrinsics"]["transform_lidar_to_camera"])
    delta = np.radians(cal["beam_inflation_deg"])
    o = ev.oct29(cfg, device)
    corners = ev.board_corners(cfg, device)
    e_t = ev.board_errors(corners, K, D, T)
    e_o_in = ev.board_errors(corners, o["K"], o["D"], o["T"])
    e_o = o["heldout"]
    drot, dt = ev.pose_difference(T, o["T"])

    frames = load_frames(cfg, device)
    circle = image_circle(frames)
    model = cb.Model(cfg["prior"]["rotation_lidar_to_camera"], frames[0].image.shape[1::-1], circle)
    p_t = params_from(K, D, T, model.R0, delta)
    p_o = params_from(o["K"], o["D"], o["T"], model.R0, delta)       # same LiDAR beam model for both
    rng = np.random.default_rng(cfg["seed"])
    caps = []
    for f in frames:
        c = cb.from_edges(f.short, le.extract(f, cfg["lidar"], cfg["seed"])[0], ie.extract(f.image, circle, cfg["image"]))
        cb.prepare_nid(c, f, cfg["calib"]["nid"]["points_per_capture"], cfg["calib"]["nid"]["bins"], rng)
        caps.append(c)
    s = cfg["calib"]["selection"]
    lift_t = cb.lift(caps, model, p_t, s["gate_px"], s["orientation_deg"], s["shift_px"])[0]
    lift_o = cb.lift(caps, model, p_o, s["gate_px"], s["orientation_deg"], s["shift_px"])[0]
    nid_t, nid_o = cb.nid(caps, model, p_t, cfg["calib"]["nid"]["bins"]), cb.nid(caps, model, p_o, cfg["calib"]["nid"]["bins"])
    band_lift = {}
    for lo, hi in BANDS:                                   # scene-edge alignment of each calibration by range
        sub = []
        for c in caps:
            m = (np.linalg.norm(c.xyz, axis=1) >= lo) & (np.linalg.norm(c.xyz, axis=1) < hi)
            sub.append(cb.Capture(c.name, c.xyz[m], c.dir[m], c.typ[m], c.sgn[m], c.img))
        if sum(len(c.xyz) for c in sub) >= 300:
            for tag, pp in (("targetless", p_t), ("oct29", p_o)):
                band_lift[f"lift_{lo:g}_{hi:g}m_{tag}"] = cb.lift(sub, model, pp, s["gate_px"], s["orientation_deg"], s["shift_px"])[0]

    # pixel disagreement between the two calibrations, by range
    pts = np.concatenate([f.xyz[::20] for f in frames])
    r = np.linalg.norm(pts, axis=1)
    ua, va, oka = model.project(model.to_camera(pts, np.zeros(len(pts)), p_t), p_t)
    ub, vb, okb = model.project(model.to_camera(pts, np.zeros(len(pts)), p_o), p_o)
    ok = oka & okb
    dpx = np.hypot(ua - ub, va - vb)
    band = {f"disagreement_{lo:g}_{hi:g}m_px": float(np.median(dpx[ok & (r >= lo) & (r < hi)])) if (ok & (r >= lo) & (r < hi)).sum() > 100 else None
            for lo, hi in BANDS}

    cdir = out / "comparison"
    for f in frames:
        img = side_by_side(f, model, p_o, p_t, f"{device} {f.short}: Oct 29 checkerboard", "targetless (no target)")
        if f.short in corners:
            z = board_zoom(f, corners[f.short], (o["K"], K), (o["D"], D), o["T"], T, img.shape[0])
            img = np.hstack([img, np.full((img.shape[0], 6, 3), 255, np.uint8), z[:img.shape[0]]])
        imwrite(cdir / f"{f.short}.jpg", img)

    u = cal["uncertainty"]["leave_one_out_translation_mm"]
    row = dict(device=device, captures=len(frames), board_captures=len(corners),
               board_rms_targetless_px=pooled_rms(e_t), board_rms_oct29_heldout_px=pooled_rms(e_o),
               board_rms_oct29_insample_px=pooled_rms(e_o_in),
               board_median_targetless_px=float(np.median(list(e_t.values()))),
               board_median_oct29_heldout_px=float(np.median(list(e_o.values()))),
               rotation_difference_deg=drot, translation_difference_mm=dt * 1000,
               fx_t=K[0, 0], fy_t=K[1, 1], cx_t=K[0, 2], cy_t=K[1, 2], model_t=cal["intrinsics"]["distortion_model"],
               fx_o=o["K"][0, 0], fy_o=o["K"][1, 1], cx_o=o["K"][0, 2], cy_o=o["K"][1, 2], model_o=o["model"],
               t_t=np.round(T[:3, 3], 3).tolist(), t_o=np.round(o["T"][:3, 3], 3).tolist(),
               loo_t_median_targetless_mm=u["median"], loo_t_max_targetless_mm=u["max"],
               loo_t_median_oct29_mm=o["loo_t_median_mm"], loo_t_max_oct29_mm=o["loo_t_max_mm"],
               lift_targetless=lift_t, lift_oct29=lift_o, nid_targetless=nid_t, nid_oct29=nid_o,
               beam_inflation_deg=cal["beam_inflation_deg"], **band, **band_lift)
    per_capture = [dict(device=device, capture=k, targetless_px=e_t[k], oct29_heldout_px=e_o.get(k), oct29_insample_px=e_o_in[k])
                   for k in sorted(e_t)]
    log(f"{device}: board RMS targetless {row['board_rms_targetless_px']:.2f} px vs Oct 29 held-out "
        f"{row['board_rms_oct29_heldout_px']:.2f}; {drot:.2f} deg / {dt * 1000:.0f} mm apart; lift {lift_t:.2f} vs {lift_o:.2f}")
    return row, per_capture


# ------------------------------------------------------------------ figure
def board_figure(per_capture, path):
    devs = sorted({r["device"] for r in per_capture})
    fig, axes = plt.subplots(1, len(devs), figsize=(3.1 * len(devs), 3.4), sharey=True, facecolor=SURFACE)
    axes = np.atleast_1d(axes)
    for ax, d in zip(axes, devs):
        rows = [r for r in per_capture if r["device"] == d]
        x = np.arange(len(rows))
        ax.set_facecolor(SURFACE)
        for xi, r in zip(x, rows):
            ax.plot([xi - 0.12, xi + 0.12], [r["oct29_heldout_px"], r["targetless_px"]], color=GRID, lw=2, zorder=1)
        ax.scatter(x - 0.12, [r["oct29_heldout_px"] for r in rows], s=64, marker="o", color=BLUE, edgecolor=SURFACE, lw=2,
                   zorder=3, label="Oct 29 checkerboard (held-out)")
        ax.scatter(x + 0.12, [r["targetless_px"] for r in rows], s=72, marker="D", color=ORANGE, edgecolor=SURFACE, lw=2,
                   zorder=3, label="Targetless (never saw the board)")
        ax.set_yscale("log")
        ax.set_yticks([0.2, 0.5, 1, 2, 5]); ax.set_yticklabels(["0.2", "0.5", "1", "2", "5"])
        ax.set_ylim(0.15, 6)
        ax.set_xticks(x); ax.set_xticklabels([r["capture"][:6] for r in rows], rotation=45, ha="right", fontsize=7, color=INK2)
        ax.set_xlim(-0.6, len(rows) - 0.4)
        ax.set_title(d.replace("_", " "), fontsize=10, color=INK, loc="left")
        ax.grid(axis="y", color=GRID, lw=0.8); ax.set_axisbelow(True)
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
        for sp in ("left", "bottom"):
            ax.spines[sp].set_color(GRID)
        ax.tick_params(colors=INK2, length=0)
    axes[0].set_ylabel("board corner error, RMS (px)", color=INK2, fontsize=9)
    h, l = axes[0].get_legend_handles_labels()
    fig.legend(h, l, loc="upper left", ncol=2, frameon=False, fontsize=9, bbox_to_anchor=(0.01, 1.0), labelcolor=INK)
    fig.text(0.01, 0.005, "Each capture with a LiDAR-detected board. Lower is better; 1 px ~ 0.25 deg.", fontsize=7.5, color=INK2)
    fig.tight_layout(rect=(0, 0.03, 1, 0.9))
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=160, facecolor=SURFACE)
    plt.close(fig)


# ------------------------------------------------------------------ README
def readme(cfg, rows):
    f = lambda v, n=2: "–" if v is None or (isinstance(v, float) and not np.isfinite(v)) else f"{v:.{n}f}"
    lines = []
    for r in rows:
        lines.append(f"| {r['device']} | {r['board_captures']} | **{f(r['board_rms_targetless_px'])}** | {f(r['board_rms_oct29_heldout_px'])} | "
                     f"{f(r['loo_t_median_targetless_mm'], 0)} / {f(r['loo_t_max_targetless_mm'], 0)} | "
                     f"{f(r['loo_t_median_oct29_mm'], 0)} / {f(r['loo_t_max_oct29_mm'], 0)} | "
                     f"{f(r['rotation_difference_deg'])} | {f(r['translation_difference_mm'], 0)} | "
                     + " / ".join(f(r.get(f"disagreement_{lo:g}_{hi:g}m_px"), 1) for lo, hi in BANDS) + " |")
    intr = []
    for r in rows:
        intr.append(f"| {r['device']} | targetless | {r['model_t']} | {r['fx_t']:.1f} | {r['fy_t']:.1f} | {r['cx_t']:.1f} | {r['cy_t']:.1f} | "
                    f"{', '.join(f'{v:.3f}' for v in r['t_t'])} | {f(r['lift_targetless'])} | {f(r['beam_inflation_deg'])} |")
        intr.append(f"| | Oct 29 | {r['model_o']} | {r['fx_o']:.1f} | {r['fy_o']:.1f} | {r['cx_o']:.1f} | {r['cy_o']:.1f} | "
                    f"{', '.join(f'{v:.3f}' for v in r['t_o'])} | {f(r['lift_oct29'])} | |")
    bl = []
    for r in rows:
        cells = []
        for lo, hi in BANDS:
            a, b = r.get(f"lift_{lo:g}_{hi:g}m_targetless"), r.get(f"lift_{lo:g}_{hi:g}m_oct29")
            cells.append("–" if a is None else f"{a:.2f} / {b:.2f}")
        bl.append(f"| {r['device']} | " + " | ".join(cells) + " |")
    tmpl = (ROOT / "code" / "README_template.md").read_text(encoding="utf-8")
    text = (tmpl.replace("{{RESULTS}}", "\n".join(lines)).replace("{{INTRINSICS}}", "\n".join(intr))
            .replace("{{BANDLIFT}}", "\n".join(bl)))
    (ROOT / "README.md").write_text(text, encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--devices", nargs="*")
    ap.add_argument("--config", help="alternative config.yaml (experiments)")
    a = ap.parse_args()
    cfg = load_config(Path(a.config) if a.config else None)
    rows, per = [], []
    for d in a.devices or devices(cfg):
        r, pc = compare_device(cfg, d)
        rows.append(r); per += pc
    res = output_dir(cfg)
    for name, data in (("comparison.csv", rows), ("board_check_per_capture.csv", per)):
        with (res / name).open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(data[0]))
            w.writeheader(); w.writerows(data)
    board_figure(per, res / "figures" / "board_check.png")
    if not a.config:          # experiments do not touch the README
        readme(cfg, rows)
    log("done")


if __name__ == "__main__":
    main()
