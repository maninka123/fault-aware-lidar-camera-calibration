"""Explicit attribution scoring; ambiguity is not exact attribution."""
from .hypothesis_separation import HYPOTHESIS_GROUPS

ALARM = {'DRIFT_SUPPORTED', 'DRIFT_AMBIGUOUS', 'UPDATE_CANDIDATE_VALIDATED'}


def score_decision(decision, truth_groups):
    truth = None if truth_groups is None else frozenset(truth_groups)
    attributed = HYPOTHESIS_GROUPS.get(decision.get('hypothesis')) if decision['status'] in {
        'DRIFT_SUPPORTED', 'UPDATE_CANDIDATE_VALIDATED'} else None
    ambiguity = [HYPOTHESIS_GROUPS[h] for h in decision.get('ambiguity_set', [])]
    return dict(alarm=decision['status'] in ALARM, attributed=None if attributed is None else sorted(attributed),
                exact=bool(truth is not None and attributed == truth),
                wrong=bool(attributed is not None and (truth is None or attributed != truth)),
                ambiguous_contains_truth=bool(decision['status'] == 'DRIFT_AMBIGUOUS' and truth in ambiguity),
                ambiguity_size=len(ambiguity), update=bool(decision.get('update_recommended')))
