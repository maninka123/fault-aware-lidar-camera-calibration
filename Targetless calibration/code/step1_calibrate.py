"""Step 1: targetless calibration of every device (intrinsics + LiDAR->camera extrinsic).

Per device (all stacked captures together):
  1. fisheye image circle from the images; LiDAR edges (depth / crease / reflectivity) of every
     stacked cloud; sub-pixel image edges of every stacked image;
  2. coarse search from the mounting orientation only -> one hypothesis per focal length;
  3. every hypothesis refined (edge alignment, IRLS); the highest edge-alignment lift wins;
  4. final refinement for each distortion model (k1, k1-k2); the model with the better
     leave-one-capture-out lift (alignment on the capture left out) is kept; the same runs
     give the parameter spread;
  5. calibration.json, intrinsics.txt, extrinsics.txt, tables and figures in results/<device>/.
Nothing about any calibration target is used.

Usage:  python step1_calibrate.py [--devices pair_4]
"""
from __future__ import annotations

import argparse
from pathlib import Path
import csv

from common import (CODE, devices, image_circle, imwrite, load_config, load_frames, log, output_dir, write_json)

import cv2  # noqa: E402
import numpy as np  # noqa: E402

import calib as cb  # noqa: E402
import image_edges as ie  # noqa: E402
import lidar_edges as le  # noqa: E402

DIST_INDEX = {"k1": 10, "k2": 11}
TYPE_COLOURS = {"depth": (0, 0, 255), "crease": (0, 220, 0), "intensity": (255, 140, 0)}


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)


def free_params(cfg, model_name):
    free = list(range(10)) + [DIST_INDEX[k] for k in cfg["calib"]["distortion_models"][model_name]]
    if cfg["calib"]["estimate_inflation"]:
        free.append(12)
    return sorted(free)


def lift(caps, model, p, cfg):
    s = cfg["calib"]["selection"]
    return cb.lift(caps, model, p, s["gate_px"], s["orientation_deg"], s["shift_px"])


# ------------------------------------------------------------------ figures
def edge_overlay(frame, cap, model, p, title):
    """Image edges (grey) and the projected LiDAR edges coloured by type."""
    img = (frame.image * 0.45).astype(np.uint8)
    img[cap.img["mask"]] = (150, 150, 150)
    Pc = model.to_camera(cap.xyz, cap.sgn, p)
    u, v, ok = model.project(Pc, p)
    for k, name in enumerate(cb.TYPES):
        m = ok & (cap.typ == k)
        for x, y in zip(u[m], v[m]):
            cv2.circle(img, (int(round(x)), int(round(y))), 1, TYPE_COLOURS[name], -1, cv2.LINE_AA)
    img = cv2.resize(img, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    cv2.putText(img, title, (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
    return img


def depth_overlay(frame, model, p, title, step=3):
    img = frame.image.copy()
    xyz = frame.xyz[::step]
    Pc = model.to_camera(xyz, np.zeros(len(xyz)), p)
    u, v, ok = model.project(Pc, p)
    d = np.linalg.norm(Pc, axis=1)[ok]
    col = cv2.applyColorMap(np.clip((np.log(d) - np.log(0.8)) / (np.log(10) - np.log(0.8)) * 255, 0, 255)
                            .astype(np.uint8).reshape(-1, 1), cv2.COLORMAP_TURBO).reshape(-1, 3)
    ui, vi = np.rint(u[ok]).astype(int), np.rint(v[ok]).astype(int)
    order = np.argsort(-d)
    img[vi[order], ui[order]] = col[order]
    img = cv2.resize(img, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST)
    cv2.putText(img, title, (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
    return img


def assess(cfg, M, second, nid_agrees, t_dev):
    """Self-check of a calibration, so an environment that cannot support it is reported as such.
    reliable: every check passes; check: one fails; unreliable: two or more fail, or the edges
    barely align better than chance."""
    c = cfg["confidence"]
    final = M["info"]["history"][-1]
    checks = [
        (M["lift"] >= c["min_lift"], f"edge-alignment lift {M['lift']:.2f} < {c['min_lift']}"),
        (not np.isfinite(second) or M["lift"] - second >= c["min_margin"],
         f"another solution almost as good (lift {second:.2f} vs {M['lift']:.2f})"),
        (bool(nid_agrees), "NID prefers a different solution"),
        (max(t_dev) * 1000 <= c["max_loo_translation_mm"],
         f"translation moves {max(t_dev) * 1000:.0f} mm when a capture is left out"),
        (final["matches"] >= c["min_matches"], f"only {final['matches']} edge matches"),
    ]
    failed = [msg for ok, msg in checks if not ok]
    verdict = ("unreliable" if len(failed) >= 2 or M["lift"] < c["unreliable_lift"]
               else "check" if failed else "reliable")
    return dict(verdict=verdict, failed=failed, lift=M["lift"], margin=M["lift"] - second if np.isfinite(second) else None,
                nid_agrees=bool(nid_agrees), loo_translation_max_mm=max(t_dev) * 1000, matches=final["matches"])


def mountings(cfg):
    """Mounting rotation(s) to try: the configured one, or with "auto" the four 90-degree rolls of
    a camera looking along LiDAR +x."""
    R = cfg["prior"]["rotation_lidar_to_camera"]
    if R != "auto":
        return [("configured", np.array(R, float))]
    upright = np.array([[0, -1, 0], [0, 0, -1], [1, 0, 0]], float)     # camera x = -LiDAR y, y = -LiDAR z
    out = []
    for k in range(4):
        c, s = np.round(np.cos(np.radians(90 * k))), np.round(np.sin(np.radians(90 * k)))
        out.append((f"roll {90 * k} deg", np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]]) @ upright))
    return out


# ------------------------------------------------------------------ main
def run_device(cfg, device):
    out = output_dir(cfg) / device
    rng = np.random.default_rng(cfg["seed"])
    frames = load_frames(cfg, device)
    circle = image_circle(frames)
    log(f"{device}: {len(frames)} captures, image circle ({circle['cx']:.1f}, {circle['cy']:.1f}) r {circle['radius']:.1f}")

    caps, feat_rows = [], []
    for f in frames:
        edges, aux = le.extract(f, cfg["lidar"], cfg["seed"])
        img = ie.extract(f.image, circle, cfg["image"])
        caps.append(cb.from_edges(f.short, edges, img))
        cb.prepare_nid(caps[-1], f, cfg["calib"]["nid"]["points_per_capture"], cfg["calib"]["nid"]["bins"], rng)
        feat_rows.append(dict(capture=f.short, lidar_points=len(f.xyz), **{f"lidar_{k}_edges": len(v["xyz"]) for k, v in edges.items()},
                              image_edge_pixels=len(img["q"]), moving_bins=int((aux["grid"]["dyn"] & aux["grid"]["valid"]).sum())))
        imwrite(out / "captures" / f.short / "lidar_edges.png",
                cv2.resize(le.figure(edges, aux), None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST))
    write_csv(out / "features.csv", feat_rows)
    log(f"  features: LiDAR edges {[len(c.xyz) for c in caps]}")

    # every hypothesis (per mounting candidate, per focal length) refined, ranked by edge-alignment lift
    rows, sols = [], []
    for mount, R0 in mountings(cfg):
        model = cb.Model(R0, frames[0].image.shape[1::-1], circle)
        p0 = cb.initial_params(model.R0, circle, float(np.mean(cb.focal_grid(cfg["calib"]["coarse"], circle))))
        p0[3:6] = cfg["prior"]["translation_m"]
        for proposer, score, q in cb.coarse(caps, model, p0, cfg["calib"]["coarse"], rng, log):
            p, _ = cb.refine(caps, model, q, list(range(13)), cfg, circle, log=lambda *a: None,
                             gates=cfg["calib"]["hypothesis_gates_px"], passes=2)
            L, a, ch = lift(caps, model, p, cfg)
            rows.append(dict(mounting=mount, proposed_by=proposer, start_focal_px=q[6], coarse_score_px=score, refined_fx=p[6], refined_fy=p[7],
                             lift=L, matched_share=a, chance_share=ch, nid=cb.nid(caps, model, p, cfg["calib"]["nid"]["bins"])))
            sols.append((L, q, p, model, mount))
    best = int(np.argmax([s[0] for s in sols]))
    pb, model, mount = sols[best][2], sols[best][3], sols[best][4]

    probe = np.concatenate([c.xyz for c in caps])[::7]
    zero = np.zeros(len(probe))
    ub, vb, okb = model.project(model.to_camera(probe, zero, pb), pb)

    def same(s):
        """Same solution as the best: the LiDAR edges land within 3 px (median) of the best one's.
        Compared in pixels because rotation and principal point trade off: equivalent solutions
        can differ by degrees in rotation."""
        u, v, ok = s[3].project(s[3].to_camera(probe, zero, s[2]), s[2])
        m = ok & okb
        return m.sum() > 100 and float(np.median(np.hypot(u - ub, v - vb)[m])) <= 3.0
    # runner-up = best hypothesis that ended in a different solution; neighbouring starts reach the
    # same solution, only less converged after the quick refinement
    other = [s[0] for s in sols if not same(s)]
    second = max(other) if other else float("nan")
    for r, s_ in zip(rows, sols):
        r["same_solution_as_best"] = same(s_)
    write_csv(out / "hypotheses.csv", rows)
    if len({s[4] for s in sols}) > 1:
        log("  mounting: " + ", ".join(f"{m} best lift {max(s[0] for s in sols if s[4] == m):.2f}" for m in dict.fromkeys(s[4] for s in sols)))
    log(f"  hypotheses: best {mount}, start f {sols[best][1][6]:.0f} -> fx {pb[6]:.1f}, lift {sols[best][0]:.2f} "
        f"(best different solution {second:.2f})")
    # cross-check with NID (dense, edge-free): does the lowest-NID hypothesis agree with the choice?
    i_nid = int(np.argmin([r["nid"] for r in rows]))
    nid_agrees = same(sols[i_nid])
    log(f"  NID cross-check: lowest NID {rows[i_nid]['nid']:.4f} ({rows[i_nid]['mounting']}, fx {rows[i_nid]['refined_fx']:.0f}) "
        f"{'agrees with' if nid_agrees else 'DISAGREES with'} the choice (NID {rows[best]['nid']:.4f})")

    # final refinement per distortion model + leave-one-capture-out
    models = {}
    for name in cfg["calib"]["distortion_models"]:
        start = sols[best][2].copy()
        if name == "k1":
            start[11] = 0.0
        free = free_params(cfg, name)
        log(f"  model {name}:")
        p, info = cb.refine(caps, model, start, free, cfg, circle, log)
        loo = []
        for k in range(len(caps)):
            rest = caps[:k] + caps[k + 1:]
            pk, _ = cb.refine(rest, model, p, free, cfg, circle, log=lambda *a: None,
                              gates=cfg["calib"]["loo_gates_px"], passes=2)
            Lk, ak, _ = lift([caps[k]], model, pk, cfg)
            loo.append(dict(left_out=caps[k].name, heldout_lift=Lk, heldout_matched_share=ak,
                            **{n: pk[i] for i, n in enumerate(cb.NAMES)}))
        L = lift(caps, model, p, cfg)[0]
        models[name] = dict(p=p, info=info, loo=loo, lift=L, heldout_lift=float(np.mean([r["heldout_lift"] for r in loo])))
        log(f"    lift {L:.3f}, leave-one-capture-out lift {models[name]['heldout_lift']:.3f}")
    # the simpler model unless the extra term improves the held-out lift by > 1 %
    names = list(models)
    chosen = names[0]
    for n in names[1:]:
        if models[n]["heldout_lift"] > models[chosen]["heldout_lift"] * 1.01:
            chosen = n
    M = models[chosen]
    p = M["p"]
    K, D, T = model.matrices(p)
    loo = M["loo"]
    spread = {n: float(np.std([r[n] for r in loo])) for n in cb.NAMES}
    t_dev = [float(np.linalg.norm(np.array([r["tx"], r["ty"], r["tz"]]) - p[3:6])) for r in loo]
    nid = cb.nid(caps, model, p, cfg["calib"]["nid"]["bins"])
    log(f"  chosen {chosen}: fx {p[6]:.1f} fy {p[7]:.1f} cx {p[8]:.1f} cy {p[9]:.1f} k {p[10]:.4f},{p[11]:.4f} "
        f"t {np.round(p[3:6], 3)} delta {np.degrees(p[12]):.3f} deg; LOO t median/max {np.median(t_dev) * 1000:.0f}/"
        f"{np.max(t_dev) * 1000:.0f} mm; NID {nid:.4f}")

    confidence = assess(cfg, M, second, nid_agrees, t_dev)
    log(f"  confidence: {confidence['verdict'].upper()}" + (f" ({'; '.join(confidence['failed'])})" if confidence["failed"] else ""))
    write_csv(out / "leave_one_out.csv", [dict(r, t_deviation_mm=d * 1000) for r, d in zip(loo, t_dev)])
    write_csv(out / "distortion_models.csv", [dict(model=n, lift=m["lift"], heldout_lift=m["heldout_lift"],
                                                   chosen=n == chosen, **{k: m["p"][i] for i, k in enumerate(cb.NAMES)})
                                              for n, m in models.items()])
    I = M["info"]
    res = cb.edge_residuals(model, p, I["X"], I["S"], I["Q"], I["N"])
    write_csv(out / "edge_residuals_by_type.csv",
              [dict(type=t, matches=int((I["T"] == k).sum()),
                    median_abs_px=float(np.median(np.abs(res[I["T"] == k]))) if (I["T"] == k).any() else None)
               for k, t in enumerate(cb.TYPES)])
    write_json(out / "calibration.json", dict(
        device=device,
        method="targetless scene-edge calibration (no calibration target); see ../../README.md",
        convention="p_camera = R @ p_lidar + t (metres); OpenCV fisheye model",
        image_size=list(frames[0].image.shape[1::-1]), captures=[c.name for c in caps], image_circle=circle,
        intrinsics=dict(distortion_model=chosen, camera_matrix=K, distortion_coefficients=D),
        extrinsics=dict(transform_lidar_to_camera=T),
        mounting=dict(chosen=mount, rotation=model.R0),
        beam_inflation_deg=float(np.degrees(p[12])),
        uncertainty=dict(gauss_newton_std=M["info"]["std"], leave_one_out_std=spread,
                         leave_one_out_translation_mm=dict(median=float(np.median(t_dev) * 1000), max=float(np.max(t_dev) * 1000))),
        quality=dict(edge_alignment_lift=M["lift"], heldout_lift=M["heldout_lift"], nid=nid,
                     final_matches=M["info"]["history"][-1]["matches"], median_abs_residual_px=M["info"]["history"][-1]["median_abs_px"]),
        confidence=confidence,
        selection=dict(best_hypothesis_lift=sols[best][0], next_best_lift=second, nid_agrees=bool(nid_agrees)), history=M["info"]["history"]))
    (out / "intrinsics.txt").write_text(
        f"# {device} camera intrinsics (targetless), OpenCV fisheye, image {frames[0].image.shape[1]} x {frames[0].image.shape[0]}\n"
        f"fx {K[0, 0]:.4f}\nfy {K[1, 1]:.4f}\ncx {K[0, 2]:.4f}\ncy {K[1, 2]:.4f}\n"
        f"k1 {D[0]:.6f}\nk2 {D[1]:.6f}\nk3 0\nk4 0\n")
    (out / "extrinsics.txt").write_text(
        f"# {device} LiDAR -> camera (targetless): p_camera = R p_lidar + t, metres\n"
        + "\n".join(" ".join(f"{v: .8f}" for v in row) for row in T) + "\n")
    for f, c in zip(frames, caps):
        imwrite(out / "captures" / f.short / "edge_alignment.png", edge_overlay(f, c, model, p, f"{device} {f.short}: LiDAR edges (red depth, green crease, blue reflectivity)"))
        imwrite(out / "captures" / f.short / "lidar_depth.png", depth_overlay(f, model, p, f"{device} {f.short}: LiDAR depth, targetless calibration"))
    return dict(device=device, p=p, model=chosen)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--devices", nargs="*")
    ap.add_argument("--config", help="alternative config.yaml (experiments)")
    ap.add_argument("--mounting", choices=["auto"], help="try all four 90-degree camera rolls")
    a = ap.parse_args()
    cfg = load_config(Path(a.config) if a.config else None)
    if not a.config and (not a.devices or set(a.devices) <= set(devices(cfg))):
        cfg = load_config(CODE / "config_oct29.yaml")     # the Oct 29 devices always use the frozen settings
    if a.mounting:
        cfg["prior"]["rotation_lidar_to_camera"] = a.mounting
    for d in a.devices or devices(cfg):
        run_device(cfg, d)
    log("done")


if __name__ == "__main__":
    main()
