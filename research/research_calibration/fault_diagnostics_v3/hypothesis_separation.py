"""Effect-specific matched-subspace distances using existing nuisance projection.

Distances are descriptive noise-normalized RMS effects, never p-values. Rival
coefficients are unbounded: an implausibly large rival still prevents rejection.
This conservative choice is reported rather than hidden behind a regularizer.
"""
import numpy as np
from scipy.linalg import solve_triangular
from ..observability import profile, supported_svd
from ..parameter_hypotheses import HYPOTHESES, GROUPS, NUISANCE

HYPOTHESIS_COLUMNS = {h.name: tuple(i for g in h.groups for i in GROUPS[g]) for h in HYPOTHESES}
HYPOTHESIS_GROUPS = {h.name: frozenset(h.groups) for h in HYPOTHESES}


def whiten(jacobian, signal=None, *, scales=None, covariance=None, sigma=1.):
    """Apply the SAME whitening to signal, physical Jacobian and nuisance.

    Full positive-definite covariance includes cross-observation correlation.
    A variance vector is the memory-efficient default. Singular covariances are
    rejected: silently dropping deterministic constraints would be incorrect.
    """
    j = np.asarray(jacobian, float)
    if j.ndim != 2 or not np.isfinite(j).all():
        raise ValueError('Finite matrix Jacobian required')
    d = np.ones(j.shape[1]) if scales is None else np.asarray(scales, float)
    if d.shape != (j.shape[1],) or not np.isfinite(d).all() or np.any(d <= 0):
        raise ValueError('Positive matching parameter scales required')
    y = None if signal is None else np.asarray(signal, float)
    if y is not None and (y.shape != (len(j),) or not np.isfinite(y).all()):
        raise ValueError('Finite matching signal required')
    a = j*d
    if covariance is None:
        if not np.isfinite(sigma) or sigma <= 0:
            raise ValueError('Positive noise scale required')
        return a/sigma, None if y is None else y/sigma
    c = np.asarray(covariance, float)
    if not np.isfinite(c).all():
        raise ValueError('Covariance must be finite')
    if c.ndim == 1:
        if c.shape != (len(j),) or np.any(c <= 0):
            raise ValueError('Positive matching measurement variances required')
        s = np.sqrt(c)
        return a/s[:, None], None if y is None else y/s
    if c.shape != (len(j), len(j)) or not np.allclose(c, c.T):
        raise ValueError('Symmetric matching covariance required')
    try:
        l = np.linalg.cholesky(c)
    except np.linalg.LinAlgError as error:
        raise ValueError('Covariance must be positive definite') from error
    return solve_triangular(l, a, lower=True), None if y is None else solve_triangular(l, y, lower=True)


def effect_separation(matrix, normalized_effect, rival, *, nuisance=NUISANCE, rtol=1e-7):
    """min_b ||A d - [A_rival A_nuisance] b|| / sqrt(number of rows).

    Nuisance is shared across all stacked captures; never profile each capture
    independently. The returned coefficients explain the actual alias direction.
    """
    a, d = np.asarray(matrix, float), np.asarray(normalized_effect, float)
    if a.ndim != 2 or d.shape != (a.shape[1],) or not np.isfinite(a).all() or not np.isfinite(d).all():
        raise ValueError('Finite matching matrix and effect required')
    if not np.isfinite(rtol) or rtol <= 0:
        raise ValueError('Positive finite rank tolerance required')
    columns = tuple(dict.fromkeys((*HYPOTHESIS_COLUMNS[rival], *nuisance)))
    if any(i >= a.shape[1] for i in columns):
        raise ValueError('Hypothesis columns exceed Jacobian dimension')
    b = a[:, columns]
    signal = a@d
    residual = profile(signal[:, None], b, rtol).ravel()
    coef = np.linalg.lstsq(b, signal, rcond=rtol)[0] if len(a) else np.zeros(len(columns))
    substitute = np.zeros(a.shape[1]); substitute[list(columns)] = coef
    s = np.linalg.svd(b, compute_uv=False) if b.size else np.array([])
    return dict(rival=rival, rms=float(np.sqrt(np.mean(residual**2))) if len(a) else 0.,
                energy=float(residual@residual), signal_rms=float(np.sqrt(np.mean(signal**2))) if len(a) else 0.,
                rival_normalized_effect=substitute, unexplained=residual,
                rank=int(np.sum(s > rtol*s[0])) if len(s) else 0,
                scope='Local fixed-association, unbounded rival refit; descriptive effect distance.')


def signature_report(matrix, normalized_effect, *, nuisance=NUISANCE, rtol=1e-7):
    a = np.asarray(matrix, float)
    distances = {h: effect_separation(a, normalized_effect, h, nuisance=nuisance, rtol=rtol)
                 for h in HYPOTHESIS_COLUMNS}
    angles = {}
    bases = {}
    for h, cols in HYPOTHESIS_COLUMNS.items():
        bases[h] = supported_svd(profile(a[:, cols], a[:, nuisance], rtol), rtol, 0.)[0]
    for left in ('R', 'T', 'I'):
        for right in ('R', 'T', 'I'):
            if left >= right:
                continue
            q, v = bases[left], bases[right]
            cosines = np.linalg.svd(q.T@v, compute_uv=False) if q.shape[1] and v.shape[1] else np.array([])
            angles[left+'|'+right] = np.degrees(np.arccos(np.clip(cosines, 0., 1.)))
    return dict(distances=distances, principal_angles_deg=angles,
                rows=len(a), nuisance_columns=list(nuisance),
                note='A small principal angle describes some alias; effect distance tests the actual proposed direction.')


def minimal_explanations(names):
    names = list(dict.fromkeys(names))
    return sorted((h for h in names if not any(HYPOTHESIS_GROUPS[o] < HYPOTHESIS_GROUPS[h] for o in names)),
                  key=lambda h: (len(HYPOTHESIS_GROUPS[h]), h))
