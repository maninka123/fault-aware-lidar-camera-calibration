"""Joint targetless calibration: fisheye intrinsics + LiDAR->camera extrinsic from scene edges.

Parameters (13): rotation offset w (rotation vector, R = exp(w) R_mount), translation t,
fx, fy, cx, cy, k1, k2 (OpenCV fisheye, k3 = k4 = 0) and delta, the angle by which the Avia
beam divergence widens foreground objects at depth jumps (applied to depth-edge points only,
towards the foreground).

  1. coarse   grid search from the mounting orientation only (t = 0, equidistant lens):
              mean truncated distance of projected LiDAR edges to image edges, over all
              captures (robust, needs no correspondences).
  2. edges    ICP-style: associate every LiDAR edge point with the nearest image edge within
              a gate (direction must agree), solve point-to-line residuals of all captures
              jointly (Cauchy loss), re-associate, shrink the gate (EdgeDenseCalib); cx, cy
              have a prior at the image-circle centre.
  3. select   every coarse hypothesis is refined; the one with the highest edge-alignment
              lift (matches relative to chance, see lift()) wins.
NID (normalised information distance between LiDAR reflectivity and image intensity, Koide et
al.) is computed for the result as a dense, edge-free cross-check.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass

import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation

NAMES = ["wx", "wy", "wz", "tx", "ty", "tz", "fx", "fy", "cx", "cy", "k1", "k2", "delta"]
TYPES = ["depth", "crease", "intensity"]


@dataclass
class Capture:
    name: str
    xyz: np.ndarray        # LiDAR edge points (LiDAR frame)
    dir: np.ndarray        # 3D line direction
    typ: np.ndarray        # index into TYPES
    sgn: np.ndarray        # +-1: horizontal side of the background (depth edges), else 0
    img: dict              # image_edges.extract output
    nid_xyz: np.ndarray = None
    nid_bin: np.ndarray = None   # LiDAR reflectivity as a fractional histogram bin


def from_edges(name, edges, img):
    xyz, d, typ, sgn = [], [], [], []
    for k, tname in enumerate(TYPES):
        e = edges[tname]
        xyz.append(e["xyz"]); d.append(e["dir"]); typ.append(np.full(len(e["xyz"]), k))
        # bg[:, 1] = +1 when the background is at larger grid column = smaller azimuth
        sgn.append(np.sign(e["bg"][:, 1]) if tname == "depth" else np.zeros(len(e["xyz"])))
    return Capture(name, np.concatenate(xyz), np.concatenate(d), np.concatenate(typ), np.concatenate(sgn), img)


class Model:
    def __init__(self, R_mount, size, circle):
        self.R0 = np.asarray(R_mount, float)
        self.w, self.h = size
        self.circle = circle

    def unpack(self, p):
        return Rotation.from_rotvec(p[:3]).as_matrix() @ self.R0, p[3:6]

    def project(self, Pc, p):
        """OpenCV fisheye projection; returns u, v, inside-image-circle flag."""
        fx, fy, cx, cy, k1, k2 = p[6:12]
        z = Pc[:, 2]
        front = z > 0.2
        zs = np.where(front, z, 1.0)
        a, b = Pc[:, 0] / zs, Pc[:, 1] / zs
        r = np.hypot(a, b)
        th = np.arctan(r)
        th2 = th * th
        s = np.where(r > 1e-9, th * (1 + th2 * (k1 + th2 * k2)) / np.maximum(r, 1e-9), 1.0)
        u, v = fx * a * s + cx, fy * b * s + cy
        c = self.circle
        inside = front & ((u - c["cx"]) ** 2 + (v - c["cy"]) ** 2 <= (0.97 * c["radius"]) ** 2)
        return u, v, inside

    def to_camera(self, xyz, sgn, p):
        R, t = self.unpack(p)
        return inflate(xyz, sgn, p[12]) @ R.T + t

    def matrices(self, p):
        R, t = self.unpack(p)
        K = np.array([[p[6], 0, p[8]], [0, p[7], p[9]], [0, 0, 1.0]])
        T = np.eye(4); T[:3, :3], T[:3, 3] = R, t
        return K, np.r_[p[10], p[11], 0.0, 0.0], T


def inflate(xyz, sgn, delta):
    """Move depth-edge points by delta (rad) in azimuth, away from the background side."""
    if delta == 0 or not np.any(sgn):
        return xyz
    a = delta * sgn
    c, s = np.cos(a), np.sin(a)
    return np.c_[c * xyz[:, 0] - s * xyz[:, 1], s * xyz[:, 0] + c * xyz[:, 1], xyz[:, 2]]


def initial_params(R_mount, circle, f):
    p = np.zeros(13)
    p[6] = p[7] = f
    p[8], p[9] = circle["cx"], circle["cy"]
    return p


# ------------------------------------------------------------------ 1. coarse search
def focal_grid(cc, circle):
    """Focal lengths to try: fixed [start, stop, step], or "auto" from the image-circle radius r:
    an equidistant fisheye maps the circle edge to a half field of view r / f, so a half field of
    view of cc["half_fov_deg"] (e.g. 40-85 deg) gives f = r / angle."""
    if cc["focal_px"] != "auto":
        return np.arange(*cc["focal_px"])
    lo, hi = np.radians(cc["half_fov_deg"])
    r = circle["radius"]
    return np.arange(r / hi, r / lo + 1e-9, r / cc["focal_steps"])



def coarse(caps, model, p_start, cc, rng, log=print, fixed_intrinsics=False):
    """Hypotheses per focal length, proposed by two independent scores over a rotation grid around
    the mounting (t = 0): the mean truncated distance of projected LiDAR edges to image edges
    (chamfer) and the NID between LiDAR reflectivity and image intensity (Koide et al.). For each
    score the best few distinct rotations are kept, each followed by a translation grid and a
    finer rotation grid under the same score.

    Neither score is reliable alone: chamfer favours short focal lengths and chance alignments in
    a single view, NID can prefer a wrong focal length. They only propose; the choice is made after
    refinement (edge-alignment lift)."""
    n_per = max(cc["points"] // len(caps), 50)
    pts, cid = [], []
    for i, c in enumerate(caps):
        s = rng.choice(len(c.xyz), min(n_per, len(c.xyz)), replace=False)
        pts.append(c.xyz[s]); cid.append(np.full(len(s), i))
    X, cid = np.concatenate(pts), np.concatenate(cid)
    D = np.stack([np.minimum(c.img["dist"], cc["cap_px"]) for c in caps])
    zero = np.zeros(len(X))

    def chamfer(p):
        u, v, ok = model.project(model.to_camera(X, zero, p), p)
        ui = np.clip(np.rint(u).astype(int), 0, model.w - 1); vi = np.clip(np.rint(v).astype(int), 0, model.h - 1)
        return float(np.where(ok, D[cid, vi, ui], cc["cap_px"]).mean())

    scores = {"chamfer": chamfer}
    if cc.get("nid_points") and caps[0].nid_xyz is not None:
        scores["nid"] = lambda p: nid_fast(caps, model, p, 16, cc["nid_points"])

    def search(score, p, rots, trans):
        best = (np.inf, p)
        for w in rots:
            for t in trans:
                q = p.copy(); q[:3], q[3:6] = w, t
                s = score(q)
                if s < best[0]:
                    best = (s, q)
        return best

    r0, r1, rs = cc["rotation_deg"]
    ang = np.radians(np.arange(r0, r1 + 1e-9, rs))
    rots = [Rotation.from_euler("xyz", e).as_rotvec() for e in itertools.product(ang, ang, ang)]
    t0, t1, ts = cc["translation_m"]
    tv = np.arange(t0, t1 + 1e-9, ts)
    trans = list(itertools.product(tv, tv, tv))
    fine = np.radians(np.arange(-1.0, 1.0 + 1e-9, 0.5))
    focals = [p_start[6]] if fixed_intrinsics else focal_grid(cc, model.circle)
    sep = np.radians(cc["min_separation_deg"])
    out = []
    for f in focals:
        q0 = p_start.copy()
        q0[6] = q0[7] = f
        for name, score in scores.items():
            scored = []
            for w in rots:
                q = q0.copy(); q[:3] = w
                scored.append((score(q), w))
            starts = []
            for s, w in sorted(scored, key=lambda x: x[0]):              # best few distinct rotations
                if all(np.linalg.norm((Rotation.from_rotvec(w) * Rotation.from_rotvec(o).inv()).as_rotvec()) >= sep for o in starts):
                    starts.append(w)
                if len(starts) == cc["per_focal"]:
                    break
            for w in starts:
                q = q0.copy(); q[:3] = w
                _, q = search(score, q, [q[:3]], trans)
                rots2 = [(Rotation.from_euler("xyz", e) * Rotation.from_rotvec(q[:3])).as_rotvec() for e in itertools.product(fine, fine, fine)]
                _, q = search(score, q, rots2, [q[3:6]])
                out.append((name, chamfer(q), q))
    log(f"    coarse: start {chamfer(p_start):.2f} px; {len(out)} hypotheses ({cc['per_focal']} per focal length and score: "
        f"{', '.join(scores)})")
    return out


# ------------------------------------------------------------------ 2. edge refinement
def associate(caps, model, p, gate, cos_min, type_w):
    """Nearest image edge within the gate whose direction agrees with the projected 3D edge."""
    out = []
    for c in caps:
        Pc = model.to_camera(c.xyz, c.sgn, p)
        u, v, ok = model.project(Pc, p)
        eps = (0.01 + 0.01 * np.linalg.norm(Pc, axis=1))[:, None]
        R, _ = model.unpack(p)
        u2, v2, _ = model.project(Pc + eps * (c.dir @ R.T), p)
        ui = np.clip(np.rint(u).astype(int), 0, model.w - 1); vi = np.clip(np.rint(v).astype(int), 0, model.h - 1)
        ok &= c.img["dist"][vi, ui] <= gate
        j = c.img["nearest"][vi, ui]
        tl = np.c_[u2 - u, v2 - v]
        tl /= np.maximum(np.linalg.norm(tl, axis=1, keepdims=True), 1e-9)
        n = c.img["n"][j]
        ok &= np.abs(tl[:, 0] * -n[:, 1] + tl[:, 1] * n[:, 0]) >= cos_min       # tangents parallel
        q = c.img["q"][j]
        ok &= np.abs(((np.c_[u, v] - q) * n).sum(1)) <= gate
        i = np.flatnonzero(ok)
        out.append(dict(i=i, q=q[i], n=n[i], w=type_w[c.typ[i]]))
    return out


def _stack(caps, corr):
    X = np.concatenate([c.xyz[a["i"]] for c, a in zip(caps, corr)])
    S = np.concatenate([c.sgn[a["i"]] for c, a in zip(caps, corr)])
    T = np.concatenate([c.typ[a["i"]] for c, a in zip(caps, corr)])
    Q = np.concatenate([a["q"] for a in corr]); N = np.concatenate([a["n"] for a in corr])
    W = np.concatenate([a["w"] for a in corr])
    return X, S, T, Q, N, W


def edge_residuals(model, p, X, S, Q, N):
    u, v, ok = model.project(model.to_camera(X, S, p), p)
    return np.where(ok, ((np.c_[u, v] - Q) * N).sum(1), 0.0)


def refine(caps, model, p0, free, cfg, circle, log=print, gates=None, passes=4):
    """Edge alignment by IRLS: Cauchy weights from the current residuals, quadratic priors
    (principal point at the image-circle centre, pixel aspect fx/fy near 1). While the gate is
    wide (many wrong matches) only rotation, translation and focal length are free; principal
    point, distortion and beam widening are released once the gate is tight."""
    cc = cfg["calib"]
    type_w = np.array([cc["weights"][t] for t in TYPES])
    cos_min = np.cos(np.radians(cc["orientation_max_deg"]))
    sig = cfg["prior"]["principal_point_sigma_px"]
    sig_a = cfg["prior"]["aspect_sigma"]
    s_c = cc["loss_scale_px"]
    all_free = np.asarray(free)
    p = p0.copy()
    history = []

    def priors(q):
        out = []
        if 8 in free:
            out += [(q[8] - circle["cx"]) / sig, (q[9] - circle["cy"]) / sig]
        if 7 in free:
            out += [np.log(q[6] / q[7]) / sig_a]
        return np.array(out)

    for gate in gates or cc["gates_px"]:
        free = all_free if gate <= cc["release_gate_px"] else all_free[all_free < 8]
        for _ in range(passes):
            corr = associate(caps, model, p, gate, cos_min, type_w)
            X, S, T, Q, N, W = _stack(caps, corr)
            r0 = edge_residuals(model, p, X, S, Q, N)
            sw = np.sqrt(W / (1 + (r0 / s_c) ** 2))                     # Cauchy IRLS weights

            def fun(x):
                q = p.copy(); q[free] = x
                return np.r_[sw * edge_residuals(model, q, X, S, Q, N), priors(q)]

            sol = least_squares(fun, p[free], x_scale="jac", max_nfev=50)
            step = np.abs(sol.x - p[free])
            p[free] = sol.x
            if np.all(step[:3] < 1e-5) and np.all(step[3:6] < 1e-4):
                break
        r = edge_residuals(model, p, X, S, Q, N)
        history.append(dict(gate_px=gate, matches=len(r), median_abs_px=float(np.median(np.abs(r))),
                            per_type={t: int((T == k).sum()) for k, t in enumerate(TYPES)}))
        log(f"    gate {gate:4.1f} px: {len(r):6d} matches, median |r| {np.median(np.abs(r)):.3f} px, "
            f"f {p[6]:.1f}/{p[7]:.1f}, c {p[8]:.1f},{p[9]:.1f}, t {np.round(p[3:6], 3)}, delta {np.degrees(p[12]):.3f} deg")
    # parameter standard deviations (Gauss-Newton with the final IRLS weights, residual scale from the MAD)
    nres = len(X)
    s2 = (1.4826 * np.median(np.abs(r))) ** 2
    try:
        J = sol.jac
        Jw = np.r_[J[:nres] , J[nres:] / np.sqrt(max(s2, 1e-12))]
        std = np.sqrt(np.diag(np.linalg.inv(Jw.T @ Jw))) * np.sqrt(s2)
    except np.linalg.LinAlgError:
        std = np.full(len(free), np.nan)
    return p, dict(history=history, std=dict(zip([NAMES[k] for k in free], std)), X=X, S=S, T=T, Q=Q, N=N)


# ------------------------------------------------------------------ NID (cross-check)
def prepare_nid(cap, frame, n, bins, rng):
    r = np.linalg.norm(frame.xyz, axis=1)
    ok = np.flatnonzero((r > 0.5) & (r < 20))
    s = rng.choice(ok, min(n, len(ok)), replace=False)
    inten = frame.intensity[s]
    rank = np.argsort(np.argsort(inten + rng.uniform(0, 1e-3, len(s))))       # histogram-equalised reflectivity
    cap.nid_xyz = frame.xyz[s]
    cap.nid_bin = rank / len(s) * (bins - 1)


def _soft_hist(a, b, bins):
    a0, b0 = np.floor(a).astype(int), np.floor(b).astype(int)
    fa, fb = a - a0, b - b0
    a1, b1 = np.minimum(a0 + 1, bins - 1), np.minimum(b0 + 1, bins - 1)
    H = np.zeros((bins, bins))
    for ia, wa in ((a0, 1 - fa), (a1, fa)):
        for ib, wb in ((b0, 1 - fb), (b1, fb)):
            np.add.at(H, (ia, ib), wa * wb)
    return H / max(H.sum(), 1e-12)


def nid_fast(caps, model, p, bins, n):
    """NID on the first n NID points of each capture, nearest-pixel sampling (coarse search)."""
    vals = []
    for c in caps:
        X, a = c.nid_xyz[:n], c.nid_bin[:n]
        u, v, ok = model.project(model.to_camera(X, np.zeros(len(X)), p), p)
        if ok.sum() < 200:
            vals.append(1.0); continue
        vi = np.clip(np.rint(v[ok]).astype(int), 0, model.h - 1); ui = np.clip(np.rint(u[ok]).astype(int), 0, model.w - 1)
        g = c.img["gray"][vi, ui] / 256.0 * (bins - 1)
        a = a[ok]
        a0, b0 = np.floor(a).astype(int), np.floor(g).astype(int)
        fa, fb = a - a0, g - b0
        a1, b1 = np.minimum(a0 + 1, bins - 1), np.minimum(b0 + 1, bins - 1)
        H = (np.bincount(a0 * bins + b0, (1 - fa) * (1 - fb), bins * bins) + np.bincount(a1 * bins + b0, fa * (1 - fb), bins * bins)
             + np.bincount(a0 * bins + b1, (1 - fa) * fb, bins * bins) + np.bincount(a1 * bins + b1, fa * fb, bins * bins))
        H = H.reshape(bins, bins) / H.sum()
        ent = lambda x: -np.sum(x[x > 0] * np.log(x[x > 0]))
        vals.append(2.0 - (ent(H.sum(1)) + ent(H.sum(0))) / ent(H))
    return float(np.mean(vals))


def nid(caps, model, p, bins):
    vals = []
    for c in caps:
        u, v, ok = model.project(model.to_camera(c.nid_xyz, np.zeros(len(c.nid_xyz)), p), p)
        if ok.sum() < 1000:
            vals.append(1.0); continue
        from image_edges import _bilinear
        g = _bilinear(c.img["gray"], u[ok], v[ok]) / 256.0 * (bins - 1)
        H = _soft_hist(c.nid_bin[ok], g, bins)
        hx, hy = H.sum(1), H.sum(0)
        ent = lambda x: -np.sum(x[x > 0] * np.log(x[x > 0]))
        hxy = ent(H)
        vals.append(2.0 - (ent(hx) + ent(hy)) / hxy)
    return float(np.mean(vals))


def lift(caps, model, p, gate=1.5, orient_deg=15.0, shift_px=6.0):
    """Edge-alignment lift: share of projected LiDAR edge points lying on a parallel image edge
    (within `gate`), divided by the same share with the projection shifted by +-shift_px.
    Dividing by this chance level removes the bias of plain match counts towards poses that
    squeeze the LiDAR edges into cluttered (edge-dense) image regions."""
    cosm = np.cos(np.radians(orient_deg))

    def share(sh):
        n = m = 0
        R, _ = model.unpack(p)
        for c in caps:
            Pc = model.to_camera(c.xyz, c.sgn, p)
            u, v, ok = model.project(Pc, p)
            eps = (0.01 + 0.01 * np.linalg.norm(Pc, axis=1))[:, None]
            u2, v2, _ = model.project(Pc + eps * (c.dir @ R.T), p)
            tl = np.c_[u2 - u, v2 - v]
            tl /= np.maximum(np.linalg.norm(tl, axis=1, keepdims=True), 1e-9)
            u, v = u + sh[0], v + sh[1]
            ui = np.clip(np.rint(u).astype(int), 0, model.w - 1); vi = np.clip(np.rint(v).astype(int), 0, model.h - 1)
            j = c.img["nearest"][vi, ui]
            q, nn = c.img["q"][j], c.img["n"][j]
            good = (ok & (c.img["dist"][vi, ui] <= gate) & (np.abs(((np.c_[u, v] - q) * nn).sum(1)) <= gate)
                    & (np.abs(-tl[:, 0] * nn[:, 1] + tl[:, 1] * nn[:, 0]) >= cosm))
            n += good.sum(); m += ok.sum()
        return n / max(m, 1)

    a = share((0.0, 0.0))
    chance = np.mean([share(s) for s in ((shift_px, 0), (-shift_px, 0), (0, shift_px), (0, -shift_px))])
    return float(a / max(chance, 1e-9)), float(a), float(chance)
