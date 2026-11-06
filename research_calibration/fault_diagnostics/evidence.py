"""Counterfactual evidence for every fitted hypothesis on every held-out capture.

For each leave-one-capture-out fold the production engine fits each hypothesis H (KEEP, R, T, I, RT, RI, TI,
RTI) on training captures only. This module scores the fitted parameters p_H on the held-out capture c with:

* the production capped nearest-edge loss L_c(p) (unchanged, recorded by the engine);
* the *chance-predicted* production loss Ld_c(p): the same loss against the decoy-displaced edges. Its change
  Ld_c(p_current) - Ld_c(p_H) is the improvement that edge density alone would produce: the explicit
  nuisance counterfactual N;
* the decoy-referenced oriented-edge contrast  E_c(p) and its change dE_c = E_c(p_H) - E_c(p_current);
* the decoy-referenced intensity (NID) contrast I_c(p) and its change dI_c.

The two contrasts measure different physics (geometric discontinuities vs reflectivity/appearance) and are
computed from different LiDAR samples, so a shared artefact of the edge extractors cannot move both.
"""
import numpy as np
from scipy.spatial import cKDTree
from .cues import CaptureCues, decoy_offsets
from .config import DiagnosticsConfig


class ProductionDecoy:
    """Capped nearest-edge loss of the production metric, against decoy-displaced image edges."""

    def __init__(self, cap, model, current, cfg, cap_px=30.):
        self.cap, self.model, self.cap_px = cap, model, cap_px
        _, _, support = model.project(model.to_camera(cap.xyz, cap.sgn, current), current)
        self.support = support
        self.trees = [cKDTree(cap.img['q']+s) for s in decoy_offsets(cfg)] if len(cap.img['q']) else []

    def loss(self, p):
        if not self.trees or not np.any(self.support):
            return np.nan
        pts = self.cap.xyz[self.support]
        u, v, vis = self.model.project(self.model.to_camera(pts, self.cap.sgn[self.support], p), p)
        vis = vis & np.isfinite(u) & np.isfinite(v)
        values = []
        for tree in self.trees:
            d = np.full(len(pts), self.cap_px)
            if np.any(vis):
                d[vis] = tree.query(np.c_[u[vis], v[vis]])[0]
            values.append(np.mean((np.minimum(d, self.cap_px)/self.cap_px)**2))
        return float(np.mean(values))


def _finite(x):
    return x is not None and np.isfinite(x)


def collect_evidence(records, caps, model, current, cfg=None, cap_px=30.):
    """records: fold observer dicts (stage='fold'). Returns a JSON-ready evidence table."""
    cfg = cfg or DiagnosticsConfig()
    by_name = {c.name: c for c in caps}
    current = np.asarray(current, float)
    cues, decoys = {}, {}

    def cue(name):
        if name not in cues:
            cues[name] = CaptureCues(by_name[name], model, current, cfg)
            decoys[name] = ProductionDecoy(by_name[name], model, current, cfg, cap_px)
        return cues[name], decoys[name]

    folds = [r for r in records if r.get('stage') == 'fold']
    tests = list(dict.fromkeys(r['test_id'] for r in folds))
    hypotheses = list(dict.fromkeys(r['hypothesis'] for r in folds))
    reference = {}
    for name in tests:
        cc, dd = cue(name)
        e, i = cc.edge(current), cc.intensity(current)
        keep_loss = next((r['loss'] for r in folds if r['test_id'] == name and r['hypothesis'] == 'KEEP'), None)
        reference[name] = dict(edge_share=e.value, edge_decoy=e.decoy, edge_contrast=e.contrast, edge_valid=e.valid,
                               intensity_nid=i.value, intensity_decoy=i.decoy, intensity_contrast=i.contrast,
                               intensity_valid=i.valid, production_loss=keep_loss, production_decoy_loss=dd.loss(current))
    table = {h: {} for h in hypotheses}
    for r in folds:
        name, h = r['test_id'], r['hypothesis']
        cc, dd = cue(name)
        ref = reference[name]
        row = dict(success=bool(r['success']), supported_update=bool(r.get('supported_update', False)),
                   attribution_support=r.get('attribution_support', {}), training_ids=r.get('training_ids', []))
        if r['success'] and _finite(r.get('loss')) and _finite(ref['production_loss']):
            p = np.asarray(r['parameters'], float)
            e, i = cc.edge(p), cc.intensity(p)
            base = ref['production_loss']
            decoy_loss = dd.loss(p)
            row.update(production_loss=float(r['loss']),
                       production_gain=float((base-r['loss'])/base) if base > 0 else 0.,
                       chance_gain=float((ref['production_decoy_loss']-decoy_loss)/base) if base > 0 and _finite(decoy_loss) else np.nan,
                       edge_contrast=e.contrast, edge_change=e.contrast-ref['edge_contrast'] if e.valid and ref['edge_valid'] else np.nan,
                       edge_share_change=e.value-ref['edge_share'] if e.valid and ref['edge_valid'] else np.nan,
                       intensity_contrast=i.contrast,
                       intensity_change=i.contrast-ref['intensity_contrast'] if i.valid and ref['intensity_valid'] else np.nan)
        table[h][name] = row
    informative = {}
    for name in tests:
        ref = reference[name]
        edge_best = [ref['edge_contrast']] + [table[h][name].get('edge_contrast', np.nan) for h in hypotheses if name in table[h]]
        int_best = [ref['intensity_contrast']] + [table[h][name].get('intensity_contrast', np.nan) for h in hypotheses if name in table[h]]
        edge_best = [x for x in edge_best if _finite(x)]; int_best = [x for x in int_best if _finite(x)]
        informative[name] = dict(edge=bool(edge_best and max(edge_best) >= cfg.edge_informative_contrast),
                                 intensity=bool(int_best and max(int_best) >= cfg.intensity_informative_contrast))
    return dict(tests=tests, hypotheses=hypotheses, reference=reference, folds=table, informative=informative,
                configuration=cfg.to_dict())
