"""Decoy-referenced cross-modal evidence for one capture.

For a calibration p, a cue value m(p) is compared with the same cue computed after displacing the image by
K fixed offsets s_k (|s_k| = decoy radius, K directions). The displaced images keep the capture's own edge
density, edge orientation statistics and intensity histogram, but break the geometric relation to the LiDAR
data. The *contrast*

    C(p) = m(p) - mean_k m_k(p)          (edge cue: matched share; larger is better)
    C(p) = mean_k NID_k(p) - NID(p)      (intensity cue: information distance; smaller NID is better)

is therefore insensitive, to first order, to a calibration change that only moves projections into image
regions where unrelated edges are denser (or textures more varied). A capture whose image cannot separate
aligned from displaced data has contrast near zero for every calibration, which is reported as missing
evidence rather than as support.

The edge cue counts a projected LiDAR edge point as matched when an image edge lies within ``edge_gate_px``
(both by distance transform and by point-to-line distance) and the projected 3D edge direction is parallel to
the image edge within ``edge_orientation_deg``. Points are always taken from the support visible under the
current calibration, and points that become invisible count as unmatched, so a candidate cannot gain by
discarding evidence.
"""
from dataclasses import dataclass
import numpy as np
from ..legacy_adapter import legacy_modules
from .config import DiagnosticsConfig


def decoy_offsets(cfg):
    angles = np.linspace(0, 2*np.pi, cfg.decoy_count, endpoint=False)
    return np.c_[np.cos(angles), np.sin(angles)]*cfg.decoy_radius_px


def _bilinear(image, u, v):
    h, w = image.shape
    u = np.clip(u, 0, w-1.001); v = np.clip(v, 0, h-1.001)
    u0 = np.floor(u).astype(int); v0 = np.floor(v).astype(int)
    fu = u-u0; fv = v-v0
    return (image[v0, u0]*(1-fu)*(1-fv) + image[v0, u0+1]*fu*(1-fv)
            + image[v0+1, u0]*(1-fu)*fv + image[v0+1, u0+1]*fu*fv)


def _nid(a, b, bins):
    """Normalised information distance of two fractional-bin samples (soft 2D histogram)."""
    a0 = np.floor(a).astype(int); b0 = np.floor(b).astype(int)
    fa = a-a0; fb = b-b0
    a1 = np.minimum(a0+1, bins-1); b1 = np.minimum(b0+1, bins-1)
    H = (np.bincount(a0*bins+b0, (1-fa)*(1-fb), bins*bins) + np.bincount(a1*bins+b0, fa*(1-fb), bins*bins)
         + np.bincount(a0*bins+b1, (1-fa)*fb, bins*bins) + np.bincount(a1*bins+b1, fa*fb, bins*bins))
    H = H.reshape(bins, bins)/max(H.sum(), 1e-12)
    ent = lambda x: float(-np.sum(x[x > 0]*np.log(x[x > 0])))
    joint = ent(H)
    if joint <= 0:
        return 1.
    return 2. - (ent(H.sum(1)) + ent(H.sum(0)))/joint


@dataclass
class CueValue:
    value: float
    decoy: float
    contrast: float
    points: int
    valid: bool


class CaptureCues:
    """Cue evaluator for one capture; the support is fixed by the calibration under assessment."""

    def __init__(self, cap, model, current, cfg=None):
        self.cap, self.model, self.cfg = cap, model, cfg or DiagnosticsConfig()
        self.offsets = decoy_offsets(self.cfg)
        self.current = np.asarray(current, float)
        _, _, visible = model.project(model.to_camera(cap.xyz, cap.sgn, self.current), self.current)
        self.edge_support = np.flatnonzero(visible)
        self.has_intensity = getattr(cap, 'nid_xyz', None) is not None and getattr(cap, 'nid_bin', None) is not None
        if self.has_intensity:
            X = cap.nid_xyz
            u, v, ok = model.project(model.to_camera(X, np.zeros(len(X)), self.current), self.current)
            self.intensity_support = np.flatnonzero(ok)
        self._cache = {}

    # ---------------------------------------------------------------- edges
    def _edge_matches(self, p):
        cap, model, cfg = self.cap, self.model, self.cfg
        ids = self.edge_support
        X, S, D = cap.xyz[ids], cap.sgn[ids], cap.dir[ids]
        Pc = model.to_camera(X, S, p)
        u, v, ok = model.project(Pc, p)
        R, _ = model.unpack(p)
        eps = (0.01 + 0.01*np.linalg.norm(Pc, axis=1))[:, None]
        u2, v2, _ = model.project(Pc + eps*(D @ R.T), p)
        tangent = np.c_[u2-u, v2-v]
        tangent /= np.maximum(np.linalg.norm(tangent, axis=1, keepdims=True), 1e-9)
        cos_min = np.cos(np.radians(cfg.edge_orientation_deg))
        img = cap.img
        h, w = img['dist'].shape

        def matched(shift):
            uu, vv = u+shift[0], v+shift[1]
            inside = ok & (uu >= 0) & (uu <= w-1) & (vv >= 0) & (vv <= h-1)
            ui = np.clip(np.rint(uu).astype(int), 0, w-1); vi = np.clip(np.rint(vv).astype(int), 0, h-1)
            j = img['nearest'][vi, ui]
            q, n = img['q'][j], img['n'][j]
            good = (inside & (img['dist'][vi, ui] <= cfg.edge_gate_px)
                    & (np.abs(((np.c_[uu, vv]-q)*n).sum(1)) <= cfg.edge_gate_px)
                    & (np.abs(-tangent[:, 0]*n[:, 1] + tangent[:, 1]*n[:, 0]) >= cos_min))
            return good

        return matched

    def edge(self, p):
        key = ('edge', np.asarray(p, float).tobytes())
        if key in self._cache:
            return self._cache[key]
        n = len(self.edge_support)
        if n < 30 or not len(self.cap.img['q']):
            out = CueValue(np.nan, np.nan, np.nan, n, False)
        else:
            matched = self._edge_matches(np.asarray(p, float))
            share = float(np.mean(matched((0., 0.))))
            decoy = float(np.mean([np.mean(matched(s)) for s in self.offsets]))
            out = CueValue(share, decoy, share-decoy, n, True)
        self._cache[key] = out
        return out

    # ---------------------------------------------------------------- intensity
    def intensity(self, p):
        key = ('nid', np.asarray(p, float).tobytes())
        if key in self._cache:
            return self._cache[key]
        cfg = self.cfg
        if not self.has_intensity or len(self.intensity_support) < cfg.intensity_min_points:
            out = CueValue(np.nan, np.nan, np.nan, 0 if not self.has_intensity else len(self.intensity_support), False)
            self._cache[key] = out
            return out
        p = np.asarray(p, float)
        ids = self.intensity_support
        X, bins = self.cap.nid_xyz[ids], self.cap.nid_bin[ids]
        u, v, ok = self.model.project(self.model.to_camera(X, np.zeros(len(X)), p), p)
        gray = self.cap.img['gray']
        h, w = gray.shape
        r = cfg.decoy_radius_px
        # One common point set for the aligned and the displaced samples.
        keep = ok & (u >= r) & (u <= w-1-r) & (v >= r) & (v <= h-1-r)
        if keep.sum() < cfg.intensity_min_points:
            out = CueValue(np.nan, np.nan, np.nan, int(keep.sum()), False)
        else:
            a = bins[keep]; uu, vv = u[keep], v[keep]
            scale = (cfg.intensity_bins-1)/256.
            value = _nid(a, _bilinear(gray, uu, vv)*scale, cfg.intensity_bins)
            decoy = float(np.mean([_nid(a, _bilinear(gray, uu+s[0], vv+s[1])*scale, cfg.intensity_bins) for s in self.offsets]))
            out = CueValue(float(value), decoy, decoy-float(value), int(keep.sum()), True)
        self._cache[key] = out
        return out


def capture_cues(caps, model, current, cfg=None):
    return {cap.name: CaptureCues(cap, model, current, cfg) for cap in caps}
