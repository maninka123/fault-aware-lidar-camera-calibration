"""Capture-paired descriptive model comparison with explicit ambiguity/abstention."""
from __future__ import annotations

import numpy as np


def decide(losses: dict[str, list[float]], complexities: dict[str, int],
           hypothesis_groups: dict[str, tuple[str, ...]], attribution_support: dict[str, bool], *,
           min_captures=4, min_relative_gain=.01, bootstrap_reps=500, seed=0):
    """Compare per-capture CV losses; independent outer validation is still needed.

    KEEP is mandatory. All candidates must have identical finite fold counts;
    failed folds are not silently dropped. A paired capture bootstrap produces
    *descriptive* 2.5/97.5-percentile intervals of mean loss differences. It
    provides neither calibrated fault probabilities nor a finite-sample risk
    guarantee. Captures must be representative independent clusters for a
    sampling interpretation; static repeats do not establish that assumption.

    A simpler nested explanation may win an unresolved tie. Non-nested rivals
    remain ambiguous and retain KEEP. Attribution support may be supplied by
    hypothesis name, or by group name (all changed groups must be supported).
    """
    thresholds = dict(min_captures=min_captures, min_relative_gain=min_relative_gain,
                      bootstrap_reps=bootstrap_reps, percentile_interval=[2.5, 97.5], seed=seed)
    result = dict(status='INVALID', selected_hypothesis='KEEP', candidate_hypothesis=None,
                  ambiguity_set=[], retain_current=True, thresholds=thresholds,
                  uncertainty_scope='Descriptive paired capture-bootstrap intervals, not calibrated confidence or fault probabilities.',
                  sampling_assumptions=['Capture blocks are representative independent sampling units.',
                                        'All models use identical folds and evaluation points.',
                                        'Training, model selection and outer-test data remain separate.'],
                  limitations=['Dependent static captures can make bootstrap intervals optimistic.',
                               'Intervals conditional on fitted candidates ignore unmodeled association and sensor effects.',
                               'No physical fault labels or nominal false-alarm calibration are inferred.'])

    def finish(status, reason):
        result.update(status=status, reason=reason)
        return result

    if (not isinstance(min_captures, int) or min_captures < 2 or
            not isinstance(bootstrap_reps, int) or bootstrap_reps < 2 or
            not np.isfinite(min_relative_gain) or min_relative_gain < 0):
        return finish('INVALID', 'Invalid declared comparison thresholds.')
    if not losses or 'KEEP' not in losses:
        return finish('INVALID', 'A KEEP baseline is required.')
    names = list(losses)
    try:
        arrays = {name: np.asarray(losses[name], dtype=float) for name in names}
        if any(a.ndim != 1 for a in arrays.values()):
            raise ValueError('one-dimensional losses required')
        if len({len(a) for a in arrays.values()}) != 1:
            raise ValueError('unequal fold counts')
        if any(not np.isfinite(a).all() or np.any(a < 0) for a in arrays.values()):
            raise ValueError('failed or nonfinite fold')
        if any(name not in complexities or name not in hypothesis_groups for name in names):
            raise ValueError('missing complexity or group definition')
        if any(not isinstance(complexities[name], (int, np.integer)) or complexities[name] < 0 for name in names):
            raise ValueError('invalid complexity')
        groups = {name: frozenset(hypothesis_groups[name]) for name in names}
        if groups['KEEP']:
            raise ValueError('KEEP must contain no changed groups')
    except (TypeError, ValueError) as exc:
        return finish('INVALID', 'Comparison refused: ' + str(exc) + '; no folds were dropped.')
    count = len(arrays['KEEP'])
    result['captures'] = count
    result['mean_losses'] = {name: float(a.mean()) if count else None for name, a in arrays.items()}
    if count < min_captures:
        return finish('INSUFFICIENT_EVIDENCE', 'Too few capture blocks for the declared model-comparison policy.')
    means = result['mean_losses']
    best = min(names, key=lambda name: (means[name], complexities[name], name))
    result['candidate_hypothesis'] = best
    rng = np.random.default_rng(seed)
    samples = rng.integers(0, count, size=(bootstrap_reps, count))

    def interval(difference):
        resampled = difference[samples].mean(axis=1)
        lo, hi = np.percentile(resampled, [2.5, 97.5])
        return dict(mean=float(difference.mean()), lower=float(lo), upper=float(hi),
                    degenerate=bool(np.ptp(resampled) <= np.finfo(float).eps * max(1., abs(float(resampled.mean())))))

    versus_best = {name: interval(arrays[name] - arrays[best]) for name in names}
    result['differences_vs_best'] = versus_best
    ambiguity = [name for name in names if versus_best[name]['lower'] <= 0]
    result['ambiguity_set'] = ambiguity
    if any(value['degenerate'] for name, value in versus_best.items() if name != best):
        result['limitations'].append('At least one resampled difference has zero numerical spread; this is not proof of zero uncertainty.')
    baseline = means['KEEP']
    gain = (baseline - means[best]) / baseline if baseline > 0 else 0.0
    result['best_relative_gain'] = float(gain)
    if best == 'KEEP' or gain < min_relative_gain:
        return finish('KEEP_CURRENT', 'No candidate clears the declared practical loss-improvement threshold.')
    if versus_best['KEEP']['lower'] <= 0:
        return finish('INSUFFICIENT_EVIDENCE', 'The descriptive paired differences do not separate the best candidate from KEEP.')
    candidate_names = [name for name in ambiguity if name != 'KEEP']
    for i, left in enumerate(candidate_names):
        for right in candidate_names[i + 1:]:
            if not (groups[left] <= groups[right] or groups[right] <= groups[left]):
                return finish('INSUFFICIENT_EVIDENCE', 'Non-nested fault explanations remain observationally ambiguous.')
    chosen = min(candidate_names, key=lambda name: (complexities[name], len(groups[name]), means[name], name))
    result['candidate_hypothesis'] = chosen
    chosen_gain = (baseline - means[chosen]) / baseline if baseline > 0 else 0.0
    chosen_vs_keep = interval(arrays['KEEP'] - arrays[chosen])
    result.update(candidate_relative_gain=float(chosen_gain), candidate_improvement=chosen_vs_keep)
    if chosen_gain < min_relative_gain or chosen_vs_keep['lower'] <= 0:
        return finish('INSUFFICIENT_EVIDENCE', 'The simpler tied explanation does not independently clear KEEP.')
    supported = bool(attribution_support.get(chosen, all(attribution_support.get(g, False) for g in groups[chosen])))
    if not groups[chosen] or not supported:
        return finish('INSUFFICIENT_EVIDENCE', 'Group-specific attribution is not supported across declared training variants.')
    result.update(selected_hypothesis=chosen, retain_current=False)
    return finish('CANDIDATE_SUPPORTED', 'A constrained candidate is supported for independent outer validation; no hardware update is authorized.')
