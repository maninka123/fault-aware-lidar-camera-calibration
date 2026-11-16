"""Known-correspondence local experiment API; recorded data use the separate runner.

This API deliberately requires signed observations, covariance and capture IDs,
so a synthetic geometric-verification result cannot masquerade as edge matching.
"""
import numpy as np
from ..observability import profile, supported_svd
from ..parameter_hypotheses import NUISANCE
from .config import SignatureConfig
from .hypothesis_separation import whiten, HYPOTHESIS_COLUMNS, minimal_explanations, signature_report


def infer_signatures(jacobian, residual_change, scales, *, covariance=None, capture_ids=None, config=None):
    cfg = config or SignatureConfig()
    raw = np.asarray(jacobian, float)
    if raw.ndim != 2 or raw.shape[1] != 13:
        raise ValueError('The existing thirteen-parameter Jacobian is required')
    a, y = whiten(jacobian, residual_change, scales=scales, covariance=covariance, sigma=cfg.pixel_sigma)
    ids = np.zeros(len(a), int) if capture_ids is None else np.asarray(capture_ids)
    if ids.shape != (len(a),):
        raise ValueError('One capture ID per observation required')
    if any(not isinstance(v, (str, int, float, np.integer, np.floating)) or
           (isinstance(v, (float, np.floating)) and not np.isfinite(v)) for v in ids):
        raise ValueError('Capture IDs must be nonmissing finite numbers or strings')
    result = dict(status='INSUFFICIENT_EVIDENCE', hypothesis=None, supported=[], ambiguity_set=[],
                  update_recommended=False, calibrated_probability=False, rows=len(a),
                  scope='Known fixed correspondence local-model verification; not recorded-sensor validation.')
    if len(a) < cfg.min_rows:
        return dict(result, reason='Too few finite signed measurements.')
    # Full covariance mixes rows across captures. CV must whiten each train/test
    # partition separately; joint whitening would leak held-out observations.
    unique = np.unique(ids)
    if capture_ids is not None and len(unique) < cfg.min_captures:
        return dict(result, reason='Too few declared capture blocks for cross-validation.')
    folds = []
    for block in unique:
        test = ids == block
        train = ~test if len(unique) > 1 else test
        def partition(mask):
            cov = None if covariance is None else np.asarray(covariance)
            cov = cov[mask] if cov is not None and cov.ndim == 1 else cov[np.ix_(mask, mask)] if cov is not None else None
            return whiten(np.asarray(jacobian)[mask], np.asarray(residual_change)[mask], scales=scales,
                          covariance=cov, sigma=cfg.pixel_sigma)
        at, yt = partition(train); av, yv = partition(test)
        row = {}
        for h, cols in HYPOTHESIS_COLUMNS.items():
            free = list((*cols, *NUISANCE))
            beta = np.linalg.lstsq(at[:, free], yt, rcond=cfg.rank_rtol)[0]
            e = yv-av[:, free]@beta
            row[h] = float(np.mean(e**2))
        folds.append(row)
    losses = {h: np.array([f[h] for f in folds]) for h in HYPOTHESIS_COLUMNS}
    best = min(losses, key=lambda h: (float(np.mean(losses[h])), len(HYPOTHESIS_COLUMNS[h])))
    gain = losses['KEEP']-losses[best]
    result['fold_mse'] = {h: v.tolist() for h, v in losses.items()}
    result['validation_scope'] = 'leave-one-capture-out' if len(unique) > 1 else 'same-data numerical fit only'
    if best == 'KEEP' or np.median(gain) <= cfg.detection_rms**2 or np.mean(gain > 0) < 2/3:
        return dict(result, status='KEEP_CONFIRMED', reason='No reproducible signed-signal improvement over nuisance-only fit.')
    supported = [h for h in losses if h != 'KEEP' and
                 np.median(losses['KEEP']-losses[h]) > cfg.detection_rms**2]
    tolerance = cfg.separation_rms**2
    tied = [h for h in supported if np.mean(losses[h])-np.mean(losses[best]) <= tolerance]
    free = list((*HYPOTHESIS_COLUMNS[best], *NUISANCE))
    effect = np.zeros(a.shape[1]); effect[free] = np.linalg.lstsq(a[:, free], y, rcond=cfg.rank_rtol)[0]
    report = signature_report(a, effect, rtol=cfg.rank_rtol)
    if cfg.geometric_signatures:
        tied += [h for h, d in report['distances'].items() if h != 'KEEP' and d['rms'] <= cfg.separation_rms]
    amb = minimal_explanations(tied)
    evidence_minimal = minimal_explanations([h for h in supported if
        np.mean(losses[h])-np.mean(losses[best]) <= tolerance])
    if any(h not in supported for h in amb):
        amb = sorted(set(amb+evidence_minimal), key=lambda h: (len(HYPOTHESIS_COLUMNS[h]), h))
    q, s, b = supported_svd(profile(a[:, free], a[:, NUISANCE]), cfg.rank_rtol, 0.)
    result.update(supported=supported, ambiguity_set=amb, signatures=report, normalized_effect=effect,
                  observable_rank=b.shape[1], singular_values=s)
    if len(amb) == 1 and amb[0] in supported:
        return dict(result, status='DRIFT_SUPPORTED', hypothesis=amb[0], reason='One minimal explanation remains under the declared local effect tolerance.')
    return dict(result, status='DRIFT_AMBIGUOUS', reason='Multiple parameter groups explain the signed effect within the declared tolerance.')
