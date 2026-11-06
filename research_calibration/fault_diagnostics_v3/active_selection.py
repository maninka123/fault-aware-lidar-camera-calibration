"""Finite-effect T-optimal recorded-observation selection, with rival refitting.

This is established model-discrimination design applied to specific surviving
effects. It does not repeat the V2 worst-column singular-value objective.
"""
import numpy as np
from ..observability import profile
from .hypothesis_separation import effect_separation, HYPOTHESIS_GROUPS


def select_observations(jacobians, effects, unresolved_pairs, *, budget, capture_ids=None,
                        training_ids=None, costs=None, quality=None, initial=None):
    """Inputs are ALREADY whitened/scaled Jacobians and training-derived effects.

    Stack first, profile a shared nuisance once. A zero/nested rival gives zero
    utility honestly. Noise correlation across captures must be whitened jointly
    by a subset-specific covariance model, which this API does not provide.
    This API supports block-diagonal covariance BETWEEN captures only; never
    jointly whiten a whole candidate pool and then select its transformed rows.
    """
    matrices = [np.asarray(a, float) for a in jacobians]
    if not matrices or any(a.ndim != 2 or a.shape[1] != 13 or not np.isfinite(a).all() for a in matrices):
        raise ValueError('Nonempty finite (m,13) candidate Jacobians required')
    ids = [str(i) for i in range(len(matrices))] if capture_ids is None else list(capture_ids)
    if len(ids) != len(matrices) or len(set(ids)) != len(ids):
        raise ValueError('Unique matching capture IDs required')
    if type(budget) is not int or budget < 0:
        raise ValueError('Nonnegative integer budget required')
    allowed = set(ids if training_ids is None else training_ids)
    if not allowed.issubset(ids):
        raise ValueError('Training IDs outside candidate pool')
    cost = np.ones(len(ids)) if costs is None else np.asarray(costs, float)
    good = np.ones(len(ids), bool) if quality is None else np.asarray(quality, bool)
    if cost.shape != (len(ids),) or not np.isfinite(cost).all() or np.any(cost <= 0) or good.shape != (len(ids),):
        raise ValueError('Positive costs and matching quality flags required')
    if not unresolved_pairs:
        raise ValueError('Declare at least one unresolved hypothesis pair')
    for left, right in unresolved_pairs:
        if left not in effects or right not in effects or left not in HYPOTHESIS_GROUPS or right not in HYPOTHESIS_GROUPS:
            raise ValueError('Every unresolved hypothesis needs a training-derived effect')
    start = np.empty((0, 13)) if initial is None else np.asarray(initial, float)
    if start.ndim != 2 or start.shape[1] != 13 or not np.isfinite(start).all():
        raise ValueError('Finite (m,13) initial evidence required')
    eligible = [i for i, name in enumerate(ids) if name in allowed and good[i]]

    def score(selected):
        a = np.vstack([start, *[matrices[i] for i in selected]])
        contrasts = {}
        for left, right in unresolved_pairs:
            for target, rival in ((left, right), (right, left)):
                contrasts[target+'|'+rival] = effect_separation(a, effects[target], rival)['energy']
        # Total separation energy, not RMS: independent new rows can add useful
        # evidence. Costs penalize acquisition; no probability interpretation.
        return dict(worst_separation=min(contrasts.values()), directed=contrasts,
                    tie_information=float(np.log1p(np.linalg.svd(profile(a[:, :12], a[:, [12]]), compute_uv=False)**2).sum()))
    selected, history = [], []
    while len(selected) < min(budget, len(eligible)):
        previous = score(selected)
        options = []
        for i in eligible:
            if i in selected:
                continue
            s = score(selected+[i])
            key = ((s['worst_separation']-previous['worst_separation'])/cost[i],
                   (s['tie_information']-previous['tie_information'])/cost[i])
            options.append((key, i, s))
        _, winner, result = max(options, key=lambda row: row[0])
        selected.append(winner); history.append(dict(id=ids[winner], scores=result, cost=float(cost[winner])))
    return dict(selected_ids=[ids[i] for i in selected], selected_indices=selected, history=history, scores=score(selected),
                scope='Conditional on fixed nonzero training-derived effects; not a global identifiability guarantee.',
                excluded_ids=[ids[i] for i in range(len(ids)) if i not in eligible])
