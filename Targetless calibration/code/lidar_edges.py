"""3D edge features of a stacked Livox Avia cloud, in the LiDAR's own angular grid.

The stacked (non-repetitive scan) cloud is binned on a spherical grid fine enough to match
the camera pixel. Three edge types are extracted, none of which needs the extrinsic:

  depth     near side of a range jump, including jumps into empty (no-return) background
            (EdgeDenseCalib's cross / background-preserving search, done on the dense grid).
            Each point keeps the direction towards the background: the Avia beam (0.28 deg
            horizontal divergence) makes foreground objects look wider, which the calibration
            estimates as one angle.
  crease    where two fitted planes meet (wall corners, desk edges): depth-continuous edges,
            located by intersecting the planes, so free of the beam-divergence bias
            (as in livox_camera_calib, Yuan et al. 2021).
  intensity reflectivity edges on smooth surfaces (posters, screens, any printed pattern).

Moving things are removed by comparing the first and the second half of the capture
(EdgeCalib's multi-frame consistency, applied within a capture). Every point gets a 3D line
direction from its edge neighbours; isolated or blob-like points are dropped.
"""
from __future__ import annotations

import cv2
import numpy as np
from scipy import ndimage
from scipy.spatial import cKDTree

AZ_MAX, EL_MAX = 40.0, 42.0          # Avia FOV is 70.4 x 77.2 deg


def _shift(a, di, dj, fill):
    """out[i, j] = a[i + di, j + dj] (fill outside)."""
    out = np.full_like(a, fill)
    h, w = a.shape[:2]
    out[max(-di, 0):h - max(di, 0), max(-dj, 0):w - max(dj, 0)] = a[max(di, 0):h - max(-di, 0), max(dj, 0):w - max(-dj, 0)]
    return out


def bin_rays(shape, b):
    """Unit ray (LiDAR frame) through each bin centre."""
    i, j = np.mgrid[:shape[0], :shape[1]]
    el = np.radians(EL_MAX - (i + 0.5) * b)
    az = np.radians(AZ_MAX - (j + 0.5) * b)
    return np.stack([np.cos(el) * np.cos(az), np.cos(el) * np.sin(az), np.sin(el)], -1)


def spherical_grid(xyz, inten, t, lc):
    b = lc["bin_deg"]
    H, W = int(2 * EL_MAX / b), int(2 * AZ_MAX / b)
    r = np.linalg.norm(xyz, axis=1)
    ok = (r > lc["min_range_m"]) & (r < lc["max_range_m"]) & (xyz[:, 0] > 0.05)
    xyz, inten, t, r = xyz[ok], inten[ok], t[ok], r[ok]
    az = np.degrees(np.arctan2(xyz[:, 1], xyz[:, 0]))
    el = np.degrees(np.arctan2(xyz[:, 2], np.hypot(xyz[:, 0], xyz[:, 1])))
    i = np.floor((EL_MAX - el) / b).astype(int)
    j = np.floor((AZ_MAX - az) / b).astype(int)
    ok = (i >= 0) & (i < H) & (j >= 0) & (j < W)
    flat = i[ok] * W + j[ok]
    xyz, inten, t, r = xyz[ok], inten[ok], t[ok], r[ok]
    rmin = np.full(H * W, np.inf)
    np.minimum.at(rmin, flat, r)
    surf = r <= rmin[flat] + lc["surface_tol_m"]          # nearest surface of the bin
    f, x, it, tt, rr = flat[surf], xyz[surf], inten[surf], t[surf], r[surf]
    n = np.bincount(f, minlength=H * W).astype(float)
    nz = np.maximum(n, 1)
    P = np.stack([np.bincount(f, x[:, k], H * W) / nz for k in range(3)], -1).reshape(H, W, 3)
    I = (np.bincount(f, it, H * W) / nz).reshape(H, W)
    valid = (n > 0).reshape(H, W)
    # first vs second half of the capture: moving surfaces disagree
    tm = np.median(tt)
    halves = []
    for m in (tt < tm, tt >= tm):
        c = np.bincount(f[m], minlength=H * W)
        halves.append(((np.bincount(f[m], rr[m], H * W) / np.maximum(c, 1)).reshape(H, W), (c > 0).reshape(H, W)))
    R = np.linalg.norm(P, axis=-1)
    both = halves[0][1] & halves[1][1]
    dyn = both & (np.abs(halves[0][0] - halves[1][0]) > np.maximum(lc["dynamic_tol_m"], 0.02 * R))
    dyn = cv2.dilate(dyn.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    hull = ndimage.binary_fill_holes(cv2.morphologyEx(valid.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8)))
    hull = cv2.erode(hull.astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool)
    return dict(P=P, R=np.where(valid, R, np.inf), I=I, valid=valid, dyn=dyn, hull=hull, bin=b, count=n.reshape(H, W))


def depth_edges(g, lc):
    """Foreground side of range jumps; returns mask and background direction (di, dj)."""
    R, valid, hull = g["R"], g["valid"], g["hull"]
    R0 = np.where(valid, R, 0.0)
    # local range noise (median neighbour difference): noisy dark / grazing surfaces need bigger jumps
    both_h = valid & _shift(valid, 0, 1, False)
    both_v = valid & _shift(valid, 1, 0, False)
    diff = np.maximum(np.where(both_h, np.abs(R0 - _shift(R0, 0, 1, 0.0)), 0), np.where(both_v, np.abs(R0 - _shift(R0, 1, 0, 0.0)), 0))
    rough = ndimage.median_filter(diff, size=7)
    thr = np.maximum(np.maximum(lc["jump_abs_m"], lc["jump_rel"] * R0), lc["jump_noise_k"] * rough)
    dense = cv2.blur(valid.astype(np.float32), (5, 5)) >= 0.6             # sparse (grazing, dark) areas: no edges
    edge = np.zeros(R.shape, bool)
    bg = np.zeros(R.shape + (2,), float)
    for di, dj in ((0, 1), (0, -1), (1, 0), (-1, 0)):
        o1, o2 = _shift(R, -di, -dj, np.inf), _shift(R, -2 * di, -2 * dj, np.inf)
        solid = valid & np.isfinite(o1) & np.isfinite(o2)                  # foreground continues inwards
        o1, o2 = np.where(solid, o1, 0.0), np.where(solid, o2, 0.0)
        solid &= (np.abs(o1 - R0) < thr) & (np.abs(o2 - o1) < thr)
        slope = np.clip(R0 - o1, 0.0, None)                                 # range growth per bin (grazing surfaces)
        hit = np.zeros(R.shape, bool)
        empty = np.ones(R.shape, bool)
        for k in range(1, lc["empty_run_bins"] + 1):
            nb = _shift(R, k * di, k * dj, np.inf)
            nbv = np.isfinite(nb)
            hit |= empty & nbv & (np.where(nbv, nb, 0) > R0 + k * slope + thr)   # farther than the surface continues
            empty &= ~nbv
        far_end = _shift(hull, lc["empty_run_bins"] * di, lc["empty_run_bins"] * dj, False)
        hit |= empty & hull & far_end                                       # no return behind: background
        e = solid & hit
        bg[e] += (di, dj)
        edge |= e
    edge &= ~g["dyn"] & hull & dense
    return edge, bg


def _box(a, w):
    return cv2.boxFilter(a, cv2.CV_64F, (w, w), normalize=False, borderType=cv2.BORDER_CONSTANT)


def plane_windows(g, lc):
    """Least-squares plane of every w x w window: centroid, normal, rms, point count."""
    w = lc["plane_window"]
    v = (g["valid"] & ~g["dyn"]).astype(float)
    P = np.where(v[..., None] > 0, g["P"], 0.0)
    n = _box(v, w)
    S = np.stack([_box(P[..., k], w) for k in range(3)], -1)
    SS = np.stack([np.stack([_box(P[..., a] * P[..., b], w) for b in range(3)], -1) for a in range(3)], -2)
    nz = np.maximum(n, 1)[..., None]
    c = S / nz
    C = SS / nz[..., None] - c[..., :, None] * c[..., None, :]
    ok = n >= 0.6 * w * w
    ev, evec = np.linalg.eigh(np.where(ok[..., None, None], C, np.eye(3)))
    rms = np.sqrt(np.maximum(ev[..., 0], 0))
    planar = ok & (rms < lc["plane_rms_max_m"]) & (ev[..., 0] < 0.25 * ev[..., 1])
    return c, evec[..., 0], planar


def crease_edges(g, lc, depth_mask):
    c, nrm, planar = plane_windows(g, lc)
    k = lc["plane_offset"]
    rays = bin_rays(g["R"].shape, g["bin"])
    cos_max = np.cos(np.radians(lc["crease_min_deg"]))
    near_jump = cv2.dilate(depth_mask.astype(np.uint8), np.ones((2 * k + 1, 2 * k + 1), np.uint8)).astype(bool)
    pts, dirs, idx = [], [], []
    for di, dj in ((0, 1), (1, 0)):
        cA, nA, pA = _shift(c, -k * di, -k * dj, 0.0), _shift(nrm, -k * di, -k * dj, 0.0), _shift(planar, -k * di, -k * dj, False)
        cB, nB, pB = _shift(c, k * di, k * dj, 0.0), _shift(nrm, k * di, k * dj, 0.0), _shift(planar, k * di, k * dj, False)
        cand = g["valid"] & ~g["dyn"] & pA & pB & ~near_jump & (np.abs((nA * nB).sum(-1)) < cos_max)
        ii, jj = np.nonzero(cand)
        a, bn, ca, cb, rho = nA[ii, jj], nB[ii, jj], cA[ii, jj], cB[ii, jj], rays[ii, jj]
        d = np.cross(a, bn)
        dn = np.linalg.norm(d, axis=1, keepdims=True)
        p0 = ((a * ca).sum(1, keepdims=True) * np.cross(bn, d) + (bn * cb).sum(1, keepdims=True) * np.cross(d, a)) / dn ** 2
        d = d / dn
        # closest point of the line p0 + s d to the bin ray lambda * rho
        b_ = (d * rho).sum(1)
        dd, e = (d * p0).sum(1), (rho * p0).sum(1)
        den = np.maximum(1 - b_ ** 2, 1e-9)
        s = (b_ * e - dd) / den
        p = p0 + s[:, None] * d
        ang = np.degrees(np.arccos(np.clip((p * rho).sum(1) / np.linalg.norm(p, axis=1), -1, 1)))
        rng = np.linalg.norm(p, axis=1)
        mid = (p - ca) * (cb - ca)
        between = (mid.sum(1) > 0) & (mid.sum(1) < ((cb - ca) ** 2).sum(1))
        ok = (ang < 0.6 * g["bin"]) & (np.abs(rng - g["R"][ii, jj]) < 0.1) & between
        pts.append(p[ok]); dirs.append(d[ok]); idx.append(np.c_[ii[ok], jj[ok]])
    return np.concatenate(pts), np.concatenate(dirs), np.concatenate(idx)


def intensity_edges(g, lc, exclude):
    I = np.log1p(np.where(g["valid"], g["I"], 0))
    _, (iy, ix) = ndimage.distance_transform_edt(~g["valid"], return_indices=True)
    I = I[iy, ix]
    I = cv2.GaussianBlur(I, (0, 0), lc["intensity_smooth_sigma"])
    lo, hi = np.percentile(I[g["valid"]], [1, 99])
    u8 = np.clip((I - lo) / max(hi - lo, 1e-9) * 255, 0, 255).astype(np.uint8)
    e = cv2.Canny(u8, *lc["intensity_canny"], L2gradient=True) > 0
    full = cv2.erode(g["valid"].astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    dense = cv2.blur(g["count"].astype(np.float32), (5, 5)) >= lc["intensity_min_points_per_bin"]
    return e & full & dense & ~g["dyn"] & g["hull"] & ~exclude, u8


def line_directions(xyz, lc, given=None):
    """3D direction of each edge point from its edge neighbours; drops non-linear clusters."""
    if len(xyz) < lc["line_neighbours"] + 1:
        return np.zeros(0, bool), np.zeros((0, 3))
    tree = cKDTree(xyz)
    dist, nn = tree.query(xyz, k=lc["line_neighbours"] + 1)
    scale = 0.03 + 0.01 * np.linalg.norm(xyz, axis=1)            # neighbourhood grows with range
    nb = xyz[nn] - xyz[nn].mean(1, keepdims=True)
    ev, evec = np.linalg.eigh(np.einsum("nki,nkj->nij", nb, nb))
    lin = (ev[:, 2] - ev[:, 1]) / np.maximum(ev[:, 2], 1e-12)
    ok = (lin > lc["line_linearity_min"]) & (dist[:, 3] < scale)
    d = evec[:, :, 2] if given is None else given
    return ok, d


def extract(frame, lc, seed=0):
    """All edge points of one capture: dict(type -> dict(xyz, dir, bg))."""
    g = spherical_grid(frame.xyz, frame.intensity, frame.time, lc)
    rng = np.random.default_rng(seed)
    dmask, bg = depth_edges(g, lc)
    out = {}
    ii, jj = np.nonzero(dmask)
    xyz = g["P"][ii, jj]
    ok, d = line_directions(xyz, lc)
    out["depth"] = dict(xyz=xyz[ok], dir=d[ok], bg=bg[ii, jj][ok], ij=np.c_[ii, jj][ok])
    cp, cd, cij = crease_edges(g, lc, dmask)
    ok, _ = line_directions(cp, lc, cd)
    out["crease"] = dict(xyz=cp[ok], dir=cd[ok], bg=np.zeros((ok.sum(), 2)), ij=cij[ok])
    excl = cv2.dilate((dmask | _mask(cij, dmask.shape)).astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
    imask, u8 = intensity_edges(g, lc, excl)
    ii, jj = np.nonzero(imask)
    xyz = g["P"][ii, jj]
    ok, d = line_directions(xyz, lc)
    out["intensity"] = dict(xyz=xyz[ok], dir=d[ok], bg=np.zeros((ok.sum(), 2)), ij=np.c_[ii, jj][ok])
    for k, v in out.items():
        n = len(v["xyz"])
        if n > lc["max_points_per_type"]:
            s = np.sort(rng.choice(n, lc["max_points_per_type"], replace=False))
            out[k] = {kk: vv[s] for kk, vv in v.items()}
    return out, dict(grid=g, intensity_u8=u8)


def _mask(ij, shape):
    m = np.zeros(shape, bool)
    if len(ij):
        m[ij[:, 0], ij[:, 1]] = True
    return m


def figure(edges, aux):
    """Spherical reflectivity image with the edge types drawn (depth red, crease green, intensity blue)."""
    img = cv2.cvtColor((aux["intensity_u8"] * 0.6).astype(np.uint8), cv2.COLOR_GRAY2BGR)
    img[~aux["grid"]["valid"]] = 0
    img[aux["grid"]["dyn"] & aux["grid"]["valid"]] = (0, 120, 160)
    for k, col in (("intensity", (255, 120, 0)), ("crease", (0, 230, 0)), ("depth", (0, 0, 255))):
        ij = edges[k]["ij"]
        img[ij[:, 0], ij[:, 1]] = col
    return img
