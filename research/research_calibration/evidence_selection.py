"""Training-only recorded-capture selection; no acquisition or probability model.

Raw Jacobians are stacked before a *shared* nuisance is profiled out. The
contrast score is a finite-variant, local-linear design diagnostic, not a
global experimental-design guarantee or a physical fault probability.
"""
from __future__ import annotations

from itertools import combinations
import numpy as np


def _basis(matrix, rtol, atol):
    if not matrix.size:
        return np.empty((matrix.shape[0], 0))
    u, s, _ = np.linalg.svd(matrix, full_matrices=False)
    threshold = max(atol, rtol * (s[0] if len(s) else 0.0))
    return u[:, s > threshold]


def _profile(target, rival, rtol, atol):
    q = _basis(rival, rtol, atol)
    return target - q @ (q.T @ target)


def _minimum_information(matrix, rtol, atol, reference_scale=0.0):
    """Return zero for every rank-deficient column space, including wide J."""
    if not matrix.shape[1] or matrix.shape[0] < matrix.shape[1]:
        return 0.0
    s = np.linalg.svd(matrix, compute_uv=False)
    threshold = max(atol, rtol * max(reference_scale, s[0] if len(s) else 0.0))
    if len(s) < matrix.shape[1] or s[-1] <= threshold:
        return 0.0
    return float(s[-1] ** 2)


def select_captures(jacobian_variants, scales, groups, *, capture_ids=None,
                    training_ids=None, nuisance=(12,), budget=None,
                    strategy='contrast', seed=0, rtol=1e-8, atol=1e-10):
    """Select from an explicitly declared training pool.

    ``jacobian_variants[i][v]`` is the raw (m, 13) measurement Jacobian for
    capture i and association variant v. Variants may have different row
    counts, but every capture must provide the same number of variants.
    ``groups`` maps names (normally R/T/I) to disjoint parameter columns.
    ``scales`` contains positive parameter units. No prior rows are allowed.

    The contrast strategy maximizes the worst variant and worst directed
    pair-group contrast minimum eigenvalue. Each group is projected away
    from its rival and the shared nuisance *after* stacking captures. For a
    single group the rival is KEEP (no calibration columns). Rank loss gives
    exactly zero, never a misleading positive pseudodeterminant.

    Ties use prior-free logdet(I + information), then minimum eigenvalue;
    final ties preserve input order. D-optimal is this explicitly regularized
    proxy, not an unregularized determinant. Baselines: all/random/
    feature_count/d_optimal/e_optimal. ``all`` ignores budget intentionally.
    Nonfinite or incompatible variants fail explicitly, without discarding
    difficult captures. This function never consults held-out losses.
    """
    if strategy not in {'contrast', 'all', 'random', 'feature_count', 'd_optimal', 'e_optimal'}:
        raise ValueError('Unknown selection strategy: ' + str(strategy))
    scale = np.asarray(scales, dtype=float)
    if scale.shape != (13,) or not np.isfinite(scale).all() or np.any(scale <= 0):
        raise ValueError('scales must contain 13 positive finite parameter units')
    if not np.isfinite([rtol, atol]).all() or rtol < 0 or atol < 0:
        raise ValueError('SVD tolerances must be nonnegative')
    if isinstance(jacobian_variants, dict):
        if capture_ids is not None:
            raise ValueError('Mapping inputs already specify capture IDs')
        capture_ids = list(jacobian_variants)
        jacobian_variants = list(jacobian_variants.values())
    variants = []
    for capture in jacobian_variants:
        if isinstance(capture, np.ndarray) and capture.ndim == 2:
            capture = [capture]
        values = [np.asarray(j, dtype=float) for j in capture]
        if not values or any(j.ndim != 2 or j.shape[1] != 13 or not np.isfinite(j).all() for j in values):
            raise ValueError('Every variant must be a finite (m,13) Jacobian')
        variants.append(values)
    if variants and len({len(v) for v in variants}) != 1:
        raise ValueError('Every capture must provide the same declared variants')
    ids = list(capture_ids) if capture_ids is not None else [str(i) for i in range(len(variants))]
    if len(ids) != len(variants) or len(set(ids)) != len(ids):
        raise ValueError('capture_ids must be unique and match the Jacobian pool')
    training = set(ids if training_ids is None else training_ids)
    if not training.issubset(set(ids)):
        raise ValueError('training_ids contains a capture outside the supplied pool')
    eligible = [i for i, name in enumerate(ids) if name in training]
    if budget is None:
        budget = len(eligible)
    if isinstance(budget, bool) or int(budget) != budget or budget < 0:
        raise ValueError('budget must be a nonnegative integer')
    budget = min(int(budget), len(eligible))
    group_columns = {str(g): tuple(int(i) for i in cols) for g, cols in groups.items()}
    nuisance = tuple(int(i) for i in nuisance)
    calibration = tuple(i for cols in group_columns.values() for i in cols)
    columns = calibration + nuisance
    if not group_columns or any(not c for c in group_columns.values()):
        raise ValueError('At least one nonempty calibration group is required')
    if len(set(columns)) != len(columns) or any(i < 0 or i >= 13 for i in columns):
        raise ValueError('Group and nuisance columns must be disjoint valid indices')
    names = list(group_columns)
    pairs = list(combinations(names, 2)) if len(names) > 1 else [(names[0], None)]

    def evaluate(indices):
        scores = []
        for v in range(len(variants[0]) if variants else 1):
            raw = np.vstack([variants[i][v] for i in indices]) if indices else np.empty((0, 13))
            a = raw * scale
            n = a[:, nuisance]
            conditional = _profile(a[:, calibration], n, rtol, atol)
            spectrum = np.linalg.svd(conditional, compute_uv=False)
            d_score = float(np.log1p(spectrum ** 2).sum())
            e_score = _minimum_information(conditional, rtol, atol, np.linalg.norm(a[:, calibration]))
            contrasts = {}
            for left, right in pairs:
                for target, rival in [(left, right)] + ([(right, left)] if right is not None else []):
                    rival_columns = nuisance + (() if rival is None else group_columns[rival])
                    c = _profile(a[:, group_columns[target]], a[:, rival_columns], rtol, atol)
                    contrasts[target + '_given_' + (rival or 'KEEP')] = _minimum_information(
                        c, rtol, atol, np.linalg.norm(a[:, group_columns[target]]))
            scores.append(dict(contrast=min(contrasts.values()), d_optimal=d_score,
                               e_optimal=e_score, feature_count=int(len(raw)), contrasts=contrasts))
        return dict(contrast=min(s['contrast'] for s in scores),
                    d_optimal=min(s['d_optimal'] for s in scores),
                    e_optimal=min(s['e_optimal'] for s in scores),
                    feature_count=min(s['feature_count'] for s in scores), variants=scores)

    selected, history = [], []
    if strategy == 'all':
        selected = eligible[:]
    elif strategy == 'random':
        selected = [int(i) for i in np.random.default_rng(seed).permutation(eligible)[:budget]]
    else:
        while len(selected) < budget:
            candidates = []
            for i in eligible:
                if i in selected:
                    continue
                s = evaluate(selected + [i])
                if strategy == 'contrast':
                    key = (s['contrast'], s['d_optimal'], s['e_optimal'])
                else:
                    key = (s[strategy],)
                candidates.append((key, i, s))
            _, winner, score = max(candidates, key=lambda x: x[0])
            selected.append(winner)
            history.append(dict(capture_id=ids[winner], index=winner, scores=score))
    return dict(selected_indices=selected, selected_ids=[ids[i] for i in selected],
                scores=evaluate(selected), diagnostics=dict(
                    strategy=strategy, seed=int(seed), budget=budget, available_training_ids=[ids[i] for i in eligible],
                    excluded_ids=[ids[i] for i in range(len(ids)) if i not in eligible],
                    variants=len(variants[0]) if variants else 0, selection_history=history,
                    parameter_scales=scale.tolist(), nuisance_columns=list(nuisance), rtol=rtol, atol=atol,
                    d_optimal_definition='sum(log(1 + singular_value_squared)); unit ridge in scaled parameter space',
                    scope='Training-only, local fixed-association design over declared variants; no statistical guarantee.'))
