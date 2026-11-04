"""Camera checkerboard detection and OpenCV-fisheye helpers."""
from __future__ import annotations

import cv2
import numpy as np


def detect_corners(image: np.ndarray, board, scales) -> tuple[np.ndarray | None, dict]:
    """findChessboardCornersSB on the temporal-median image, trying upscales and CLAHE.

    Corners found on an image upscaled by s are mapped back with the pixel-centre
    convention x = (x_s + 0.5) / s - 0.5 (plain division by s biases corners by
    0.5 * (1 - 1/s) px towards the origin).
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    variants = [("plain", gray), ("clahe", cv2.createCLAHE(3.0, (8, 8)).apply(gray))]
    for name, g in variants:
        for s in scales:
            test = g if s == 1 else cv2.resize(g, None, fx=s, fy=s, interpolation=cv2.INTER_CUBIC)
            ok, c = cv2.findChessboardCornersSB(test, tuple(board), cv2.CALIB_CB_EXHAUSTIVE | cv2.CALIB_CB_ACCURACY)
            if ok:
                pts = (c.reshape(-1, 2).astype(np.float64) + 0.5) / s - 0.5
                return pts, {"upscale": int(s), "preprocessing": name}
    return None, {"upscale": None, "preprocessing": None}


def board_object_points(board, square: float = 1.0) -> np.ndarray:
    cols, rows = map(int, board)
    obj = np.zeros((cols * rows, 3))
    obj[:, :2] = np.mgrid[0:cols, 0:rows].T.reshape(-1, 2) * square
    return obj


def project(points_cam_or_obj, rvec, tvec, K, D) -> np.ndarray:
    obj = np.asarray(points_cam_or_obj, np.float64).reshape(1, -1, 3)
    return cv2.fisheye.projectPoints(obj, np.asarray(rvec, float).reshape(3, 1), np.asarray(tvec, float).reshape(3, 1),
                                     K, np.asarray(D, float).reshape(4, 1))[0].reshape(-1, 2)


def board_pose(obj, corners, K, D):
    """Camera-only board pose for given intrinsics (PnP on undistorted rays + LM)."""
    n = cv2.fisheye.undistortPoints(corners.reshape(-1, 1, 2), K, np.asarray(D, float).reshape(4, 1))
    ok, rv, tv = cv2.solvePnP(obj, n, np.eye(3), None, flags=cv2.SOLVEPNP_IPPE)
    if not ok:
        ok, rv, tv = cv2.solvePnP(obj, n, np.eye(3), None)
    from scipy.optimize import least_squares
    fit = least_squares(lambda x: (project(obj, x[:3], x[3:], K, D) - corners).ravel(), np.r_[rv.ravel(), tv.ravel()], method="lm")
    err = np.linalg.norm((project(obj, fit.x[:3], fit.x[3:], K, D) - corners), axis=1)
    return fit.x[:3], fit.x[3:], err


def draw_corners(image, corners, board, text=None):
    canvas = image.copy()
    cv2.drawChessboardCorners(canvas, tuple(board), np.ascontiguousarray(corners.reshape(-1, 1, 2), np.float32), True)
    cv2.circle(canvas, tuple(np.rint(corners[0]).astype(int)), 5, (0, 0, 255), 1)
    if text:
        cv2.putText(canvas, text, (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1, cv2.LINE_AA)
    return canvas


def image_circle(image: np.ndarray, margin: float = 4.0):
    """Centre and radius of the fisheye image circle (robust circle fit to the outermost
    scene pixel along rays from the image centre; parts outside the frame are skipped)."""
    from scipy.optimize import least_squares
    g = cv2.GaussianBlur(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float32), (3, 3), 0)
    h, w = g.shape
    border = float(np.median(np.r_[g[:8, :8].ravel(), g[:8, -8:].ravel(), g[-8:, :8].ravel(), g[-8:, -8:].ravel()]))
    c0 = np.array([w / 2, h / 2]); pts = []
    rs_all = np.arange(0.4 * min(w, h), 0.8 * max(w, h), 0.25)
    for a in np.radians(np.arange(0, 360, 1.0)):
        d = np.array([np.cos(a), np.sin(a)]); P = c0 + rs_all[:, None] * d
        inside = (P[:, 0] >= 1) & (P[:, 0] < w - 2) & (P[:, 1] >= 1) & (P[:, 1] < h - 2)
        if inside.all():
            continue
        rs, P = rs_all[inside], P[inside]
        v = cv2.remap(g, P[:, 0].astype(np.float32).reshape(-1, 1), P[:, 1].astype(np.float32).reshape(-1, 1), cv2.INTER_LINEAR).ravel()
        above = np.flatnonzero(v > border + margin)
        if not len(above) or above[-1] >= len(rs) - 8:  # edge must be visible inside the frame
            continue
        pts.append(c0 + rs[above[-1]] * d)
    pts = np.asarray(pts)
    if len(pts) < 30:
        return None
    fit = least_squares(lambda q: np.linalg.norm(pts - q[:2], axis=1) - q[2], [w / 2, h / 2, 0.6 * max(w, h)],
                        loss="soft_l1", f_scale=0.5)
    res = np.linalg.norm(pts - fit.x[:2], axis=1) - fit.x[2]
    return dict(cx=float(fit.x[0]), cy=float(fit.x[1]), radius=float(fit.x[2]), points=len(pts),
                residual_mad_px=float(np.median(np.abs(res))), edge_points=pts)
