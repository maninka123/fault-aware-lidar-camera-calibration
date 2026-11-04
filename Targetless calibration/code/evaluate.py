"""Evaluation only: the Oct 29 checkerboard calibration and its board corners.

Nothing here is used by the calibration. The board corners found by the Oct 29 pipeline
(LiDAR corners in each capture's LiDAR frame + the matching camera corners) are an
independent check: the targetless calibration never saw them, so its error on them is a
held-out error; the Oct 29 numbers quoted next to it are its own leave-one-capture-out
(held-out) errors on the same boards.
"""
from __future__ import annotations

import json
import pickle
import sys

import numpy as np
from scipy.spatial.transform import Rotation

from common import PROJECT, cache_dir, oct29_dir, short_name


def _fisheye(Pc, K, D):
    z = Pc[:, 2]
    a, b = Pc[:, 0] / z, Pc[:, 1] / z
    r = np.hypot(a, b)
    th = np.arctan(r)
    th2 = th * th
    k = np.r_[np.ravel(D), np.zeros(4)][:4]
    s = np.where(r > 1e-9, th * (1 + th2 * (k[0] + th2 * (k[1] + th2 * (k[2] + th2 * k[3])))) / np.maximum(r, 1e-9), 1)
    return np.c_[K[0, 0] * a * s + K[0, 1] * b * s + K[0, 2], K[1, 1] * b * s + K[1, 2]]


def project(xyz, K, D, T):
    return _fisheye(xyz @ T[:3, :3].T + T[:3, 3], K, D)


def oct29(cfg, device):
    """Oct 29 calibration (K, D, T) and its per-capture held-out board errors."""
    res = oct29_dir(cfg) / "results" / device
    cal = json.loads((res / "calibration.json").read_text())
    import csv
    held = {}   # final model, leave-one-capture-out (after the Oct 29 rig-rotation step where applied)
    with (res / "loo_parameter_spread.csv").open(newline="") as f:
        for row in csv.DictReader(f):
            held[row["left_out"]] = float(row["heldout_px"])
    q = json.loads((res / "quality.json").read_text())
    return dict(K=np.array(cal["intrinsics"]["camera_matrix"]), D=np.array(cal["intrinsics"]["distortion_coefficients"]),
                T=np.array(cal["extrinsics"]["transform_lidar_to_camera"]), model=cal["intrinsics"]["distortion_model"],
                heldout=held, heldout_rms=q["heldout_rms_px"], loo_t_median_mm=q["loo_median_translation_change_mm"],
                loo_t_max_mm=q["loo_max_translation_change_mm"])


def board_corners(cfg, device):
    """{capture short name: (LiDAR corners (n,3), camera corners (n,2))} from the Oct 29 state."""
    cache = cache_dir(cfg) / device / "eval_board_corners.npz"
    if cache.exists():
        z = np.load(cache, allow_pickle=True)
        return z["corners"].item()
    for p in (PROJECT / "multi_capture_calibration", PROJECT / "paper_single_shot_calibration"):
        sys.path.insert(0, str(p))
    from mcc.extrinsics import reorder  # read-only, same pairing as Oct 29 step3_report.py
    import yaml
    board = yaml.safe_load((oct29_dir(cfg) / "code" / "config.yaml").read_text())["checkerboard"]["inner_corners"]
    st = pickle.loads((oct29_dir(cfg) / "results" / device / "state.pkl").read_bytes())
    S = st["S"][device]
    out = {}
    for c in S["caps"]:
        d = c["det"]
        if c["name"] in S["asg"] and d is not None and c["cam"] is not None:
            uv = reorder(c["cam"], board, S["asg"][c["name"]])[d["lattice_indices"]]
            out[c["short"]] = (np.asarray(d["corners_xyz"], float), np.asarray(uv, float).reshape(-1, 2))
    cache.parent.mkdir(parents=True, exist_ok=True)
    np.savez(cache, corners=np.array(out, dtype=object))
    return out


def board_errors(corners, K, D, T):
    """Per-capture RMS (px) of projected LiDAR board corners vs camera corners."""
    return {k: float(np.sqrt(np.mean(np.sum((project(xyz, K, D, T) - uv) ** 2, 1)))) for k, (xyz, uv) in corners.items()}


def pose_difference(Ta, Tb):
    dR = Ta[:3, :3] @ Tb[:3, :3].T
    return float(np.degrees(Rotation.from_matrix(dR).magnitude())), float(np.linalg.norm(Ta[:3, 3] - Tb[:3, 3]))
