"""Camera-LiDAR edge correspondences with explicit identity, visibility and confidence.

The recorded front end of the repository pairs every projected LiDAR edge point with its nearest oriented image edge.
A nearby edge is not necessarily the corresponding edge: clutter, repeated structure and the calibration error being
diagnosed all create close but wrong pairs, and a wrong pair yields a smooth, plausible but wrong residual. This
module makes the pairing an explicit, testable object.

Model. For a projected point x with candidate edge elements k within a gate, let d_k be the signed normal distance and
a_k the angle between the projected 3D edge tangent and the image edge. Matching noise is Gaussian in d with std
sigma and in a with std sigma_a, and an outlier (no true counterpart) has constant likelihood exp(-c_out). The posterior
responsibility of candidate k (a standard Gaussian-mixture E-step, not a calibrated probability) is

    r_k = exp(-c_k) / (sum_j exp(-c_j) + exp(-c_out)),   c_k = d_k^2 / (2 sigma^2) + a_k^2 / (2 sigma_a^2).

An ambiguous point (two similar candidates) therefore receives a small responsibility, a lone close candidate a large
one. Three optional, separately switchable mechanisms follow:

  visibility  a point is dropped when a LiDAR return that is nearer to the camera projects within a few pixels of it
              (z-buffer test), since it is not a surface the camera can see at that location;
  confidence  rows are weighted by responsibility (False: every gated oriented match counts equally, like V2);
  balance     the total weight of one image cell x range bin is capped relative to the median cell, so a single
              region or distance cannot dominate the evidence.

  unique      (``ambiguity_radius_px`` > 0) a pair is kept only if NO compatible rival edge element lies within that radius,
              i.e. the pairing is the same for every calibration error up to the radius. A responsibility computed with a
              narrow sigma cannot see a rival 8 px away; the plausible displacement of the unknown error can.

Everything here is conditional on the calibration used to project; none of it is a ground-truth correspondence.
"""
from dataclasses import dataclass, asdict
import numpy as np
from scipy.ndimage import minimum_filter
from scipy.spatial import cKDTree
from .geometry_signatures import projection_jacobian


@dataclass(frozen=True)
class CorrespondenceConfig:
    gate_px: float = 8.
    orientation_deg: float = 30.
    sigma_px: float = 1.5            # matching noise in normal distance
    sigma_angle_deg: float = 10.     # matching noise in orientation
    outlier_cost: float = 4.5        # c_out: an unmatched point is as likely as a 3-sigma match
    candidates: int = 4
    visibility: bool = True
    confidence: bool = True
    balance: bool = True
    ambiguity_radius_px: float = 0.   # > 0: drop a pair if a compatible rival edge lies within this radius (see below)
    rival_separation_px: float = 3.   # edge points closer than this are the same edge element, not rivals
    occluder_radius_px: int = 2
    occluder_margin_m: float = .2
    occluder_margin_rel: float = .03
    grid: tuple = (4, 3)             # image cells (x, y)
    range_bins: int = 3
    cell_cap_factor: float = 1.5     # a cell's total weight may be at most this multiple of the median cell's
    min_confidence: float = .05      # rows below this carry no usable evidence

    def to_dict(self):
        return asdict(self)


_TREES = {}


def _tree(img):
    """KD-tree of the capture's sub-pixel image edges (cached per image-edge dictionary)."""
    key = id(img)
    hit = _TREES.get(key)
    if hit is None or hit[0] is not img:
        hit = (img, cKDTree(img['q']))
        if len(_TREES) > 64:
            _TREES.clear()
        _TREES[key] = hit
    return hit[1]


def project_with_tangent(cap, model, p):
    """Projection u, v, validity, unit image tangent and camera-frame range of every LiDAR edge point of ``cap``."""
    camera = model.to_camera(cap.xyz, cap.sgn, p)
    u, v, ok = model.project(camera, p)
    rotation, _ = model.unpack(p)
    eps = (.01 + .01 * np.linalg.norm(camera, axis=1))[:, None]
    u2, v2, _ = model.project(camera + eps * (cap.dir @ rotation.T), p)
    tangent = np.c_[u2 - u, v2 - v]
    tangent /= np.maximum(np.linalg.norm(tangent, axis=1, keepdims=True), 1e-9)
    return u, v, ok & np.isfinite(u) & np.isfinite(v), tangent, camera[:, 2]


def visible_mask(model, p, depth, u, v, ok, occluders, cfg, shape):
    """False where a nearer LiDAR return covers the pixel neighbourhood (a surface the camera cannot see there)."""
    h, w = shape
    vis = np.ones(len(u), bool)
    if occluders is None or not len(occluders):
        return vis
    camera = model.to_camera(occluders, np.zeros(len(occluders)), p)
    ou, ov, ook = model.project(camera, p)
    ook &= np.isfinite(ou) & np.isfinite(ov) & (ou >= 0) & (ou < w) & (ov >= 0) & (ov < h)
    buffer = np.full((h, w), np.inf)
    np.minimum.at(buffer, (ov[ook].astype(int), ou[ook].astype(int)), camera[ook, 2])
    r = int(cfg.occluder_radius_px)
    near = minimum_filter(buffer, size=2 * r + 1, mode='nearest')
    inside = ok & (u >= 0) & (u < w) & (v >= 0) & (v < h)
    ui, vi = u[inside].astype(int), v[inside].astype(int)
    margin = np.maximum(cfg.occluder_margin_m, cfg.occluder_margin_rel * depth[inside])
    vis[inside] = near[vi, ui] >= depth[inside] - margin
    return vis


def _candidate_table(cap, u, v, tangent, rows, cfg):
    """Gated, oriented candidates of the given point rows: arrays shaped (rows, K); invalid entries are NaN."""
    img = cap.img
    k = max(1, int(cfg.candidates))
    distance, neighbour = _tree(img).query(np.c_[u[rows], v[rows]], k=k, distance_upper_bound=cfg.gate_px)
    distance = distance.reshape(len(rows), -1)
    neighbour = neighbour.reshape(len(rows), -1)
    present = np.isfinite(distance)
    j = np.where(present, neighbour, 0)
    n = img['n'][j]                                           # (rows, K, 2)
    q = img['q'][j]
    dn = np.einsum('rkc,rkc->rk', np.stack([u[rows], v[rows]], 1)[:, None, :] - q, n)
    cos = np.abs(-tangent[rows, None, 0] * n[..., 1] + tangent[rows, None, 1] * n[..., 0])
    angle = np.degrees(np.arccos(np.clip(cos, 0., 1.)))
    good = present & (np.abs(dn) <= cfg.gate_px) & (angle <= cfg.orientation_deg)
    return j, q, n, np.where(good, dn, np.nan), np.where(good, angle, np.nan)


def _distinct(cost, dn, separation):
    """Mask of candidates that are distinct edge LINES: samples of one edge share a normal distance and must not compete.

    Greedy by increasing cost: a candidate is kept if its normal distance differs by more than ``separation`` from every
    kept one. Image edges are sampled about once per pixel along their length, so without this the responsibility of the
    one true edge would be divided among its own samples.
    """
    m, k = cost.shape
    order = np.argsort(np.where(np.isfinite(cost), cost, np.inf), axis=1)
    kept = np.zeros((m, k), bool)
    kept_dn = np.full((m, k), np.nan)
    rows = np.arange(m)
    for t in range(k):
        idx = order[:, t]
        c, d = cost[rows, idx], dn[rows, idx]
        free = np.isfinite(c) & np.all(np.isnan(kept_dn) | (np.abs(d[:, None] - kept_dn) > separation), axis=1)
        kept[rows[free], idx[free]] = True
        kept_dn[rows[free], t] = d[free]
    return kept


def _has_rival(cap, u, v, tangent, rows, best_dn, cfg):
    """True where a compatible edge LINE other than the chosen one lies within ``ambiguity_radius_px``.

    Uses every image edge point inside the radius (not a short nearest-neighbour list) and compares normal distances:
    points of the chosen edge itself, however far along it, are not rivals; a different edge line is.
    """
    img = cap.img
    cos_min = np.cos(np.radians(cfg.orientation_deg))
    hits = _tree(img).query_ball_point(np.c_[u[rows], v[rows]], r=cfg.ambiguity_radius_px)
    out = np.zeros(len(rows), bool)
    for t, ids in enumerate(hits):
        if len(ids) < 2:
            continue
        ids = np.asarray(ids)
        n = img['n'][ids]
        d = np.einsum('kc,kc->k', np.array([u[rows[t]], v[rows[t]]]) - img['q'][ids], n)
        ok = np.abs(-tangent[rows[t], 0] * n[:, 1] + tangent[rows[t], 1] * n[:, 0]) >= cos_min
        out[t] = bool(np.any(ok & (np.abs(d - best_dn[t]) > cfg.rival_separation_px)))
    return out


def associate(cap, model, p, cfg=None, *, occluders='auto'):
    """Correspondences of one capture at calibration ``p``.

    Returns a dict with the rows kept (``index`` into ``cap.xyz``), their image edge point ``q``, unit normal ``n``,
    responsibility ``confidence``, final ``weight``, camera ``range`` and a ``stages`` count of what each mechanism
    removed. With every mechanism off this reduces to the best gated, oriented candidate with unit weight.
    """
    cfg = cfg or CorrespondenceConfig()
    empty = dict(index=np.empty(0, int), q=np.empty((0, 2)), n=np.empty((0, 2)), confidence=np.empty(0),
                 weight=np.empty(0), range=np.empty(0), stages=dict(projected=0))
    if not len(cap.xyz) or not len(cap.img['q']):
        return empty
    u, v, ok, tangent, depth = project_with_tangent(cap, model, p)
    stages = dict(points=int(len(cap.xyz)), projected=int(ok.sum()))
    if cfg.visibility:
        occ = getattr(cap, 'nid_xyz', None) if isinstance(occluders, str) and occluders == 'auto' else occluders
        h, w = cap.img['gray'].shape
        seen = visible_mask(model, p, depth, u, v, ok, occ, cfg, (h, w))
        stages['occluded'] = int((ok & ~seen).sum())
        ok = ok & seen
    rows = np.flatnonzero(ok)
    if not len(rows):
        return dict(empty, stages=stages)
    j, q, n, dn, angle = _candidate_table(cap, u, v, tangent, rows, cfg)
    cost = dn ** 2 / (2 * cfg.sigma_px ** 2) + angle ** 2 / (2 * cfg.sigma_angle_deg ** 2)
    distinct = _distinct(cost, dn, cfg.rival_separation_px)
    like = np.where(np.isfinite(cost) & distinct, np.exp(-cost), 0.)
    resp = like / (like.sum(axis=1) + np.exp(-cfg.outlier_cost))[:, None]
    best = np.argmax(np.where(np.isfinite(cost), -cost, -np.inf), axis=1)
    has = np.isfinite(cost[np.arange(len(rows)), best])
    stages['gated'] = int(has.sum())
    pick = np.arange(len(rows))[has]
    sel = rows[has]
    b = best[has]
    conf = resp[pick, b] if cfg.confidence else np.ones(len(sel))
    if cfg.ambiguity_radius_px > 0 and len(sel):
        rival = _has_rival(cap, u, v, tangent, sel, dn[pick, b], cfg)
        stages['rivals'] = int(rival.sum())
        conf = np.where(rival, 0., conf)
    keep = conf >= (cfg.min_confidence if (cfg.confidence or cfg.ambiguity_radius_px > 0) else 0.)
    stages['low_confidence'] = int((~keep).sum())
    sel, b, pick, conf = sel[keep], b[keep], pick[keep], conf[keep]
    out_q, out_n = q[pick, b], n[pick, b]
    weight = conf.copy()
    if cfg.balance and len(sel):
        weight = _balance(weight, u[sel], v[sel], depth[sel], cap.img['gray'].shape, cfg)
    stages['kept'] = int(len(sel))
    return dict(index=sel, q=out_q, n=out_n, confidence=conf, weight=weight, range=depth[sel], stages=stages)


def _balance(weight, u, v, depth, shape, cfg):
    """Cap the total weight of any image-cell x range-bin so that no region or distance dominates."""
    h, w = shape
    gx, gy = cfg.grid
    cx = np.clip((u / w * gx).astype(int), 0, gx - 1)
    cy = np.clip((v / h * gy).astype(int), 0, gy - 1)
    edges = np.quantile(depth, np.linspace(0, 1, cfg.range_bins + 1)[1:-1]) if len(depth) > cfg.range_bins else []
    rb = np.searchsorted(edges, depth) if len(edges) else np.zeros(len(depth), int)
    cell = (rb * gy + cy) * gx + cx
    total = np.bincount(cell, weights=weight)
    used = total[total > 0]
    cap_total = cfg.cell_cap_factor * np.median(used)
    scale = np.where(total > cap_total, cap_total / np.maximum(total, 1e-12), 1.)
    return weight * scale[cell]


def associate_nearest(cap, model, p, gate_px=8.):
    """Baseline: nearest image edge pixel within the gate, no orientation test, no confidence (the simplest front end)."""
    u, v, ok, _tangent, depth = project_with_tangent(cap, model, p)
    rows = np.flatnonzero(ok)
    if not len(rows) or not len(cap.img['q']):
        return dict(index=np.empty(0, int), q=np.empty((0, 2)), n=np.empty((0, 2)), weight=np.empty(0),
                    confidence=np.empty(0), range=np.empty(0), stages={})
    distance, j = _tree(cap.img).query(np.c_[u[rows], v[rows]], k=1, distance_upper_bound=gate_px)
    has = np.isfinite(distance)
    sel, j = rows[has], j[has]
    return dict(index=sel, q=cap.img['q'][j], n=cap.img['n'][j], confidence=np.ones(len(sel)),
                weight=np.ones(len(sel)), range=depth[sel], stages=dict(kept=int(len(sel))))


def associate_oriented(cap, model, p, gate_px=9., orientation_deg=30.):
    """The repository's existing orientation-aware nearest-edge pairing (gate 9 px, 30 degrees)."""
    cfg = CorrespondenceConfig(gate_px=gate_px, orientation_deg=orientation_deg, candidates=1,
                               visibility=False, confidence=False, balance=False)
    return associate(cap, model, p, cfg)


def signed_rows(cap, assoc, model, p, *, capture_id=None):
    """Signed point-to-line residual and its 13-column physical Jacobian for associated rows.

    ``residual = (projection - q) . n``. The weight enters as measurement variance sigma^2 / weight by the caller.
    Rows whose projection is invalid are dropped (never treated as zero-residual evidence).
    """
    idx = assoc['index']
    if not len(idx):
        return dict(residual=np.empty(0), jacobian=np.empty((0, 13)), weight=np.empty(0), index=idx)
    uv, jac, valid = projection_jacobian(model, p, cap.xyz[idx], cap.sgn[idx])
    n = assoc['n']
    residual = np.sum((uv - assoc['q']) * n, axis=1)
    jacobian = np.einsum('ni,nij->nj', n, jac)
    valid &= np.isfinite(residual) & np.isfinite(jacobian).all(axis=1)
    return dict(residual=residual[valid], jacobian=jacobian[valid], weight=assoc['weight'][valid], index=idx[valid],
                range=assoc['range'][valid])


def pair_accuracy(assoc, truth, tolerance_px=2.):
    """Identity accuracy of ``assoc`` against reference pairs ``truth`` (same LiDAR point index -> image edge point q).

    correct: the same LiDAR point is paired to an image edge point within ``tolerance_px`` of the reference;
    wrong:   the same point is paired elsewhere;
    unverifiable: the point has no reference counterpart, so the match cannot be checked.
    """
    ref = dict(zip(truth['index'].tolist(), truth['q']))
    correct = wrong = extra = 0
    for i, q in zip(assoc['index'].tolist(), assoc['q']):
        r = ref.get(i)
        if r is None:
            extra += 1
        elif np.hypot(*(q - r)) <= tolerance_px:
            correct += 1
        else:
            wrong += 1
    total = len(assoc['index'])
    return dict(matched=total, correct=correct, wrong=wrong, unverifiable=extra, reference=len(ref),
                recall=correct / max(len(ref), 1), precision_verifiable=correct / max(correct + wrong, 1))
