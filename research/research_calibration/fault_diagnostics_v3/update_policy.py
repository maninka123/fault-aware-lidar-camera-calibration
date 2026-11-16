"""Offline candidate contract, separate from diagnosis and hardware writes."""


def conservative_attribution(base, geometric):
    """A conditional geometric model may veto, never manufacture, attribution.

    Pure rule shared with the reproducible saved-evidence policy replay. This
    logical monotonicity is not an operational false-attribution guarantee.
    """
    out = dict(geometric, attribution_mode='conservative_veto', update_recommended=False)
    if not geometric.get('configuration', {}).get('geometric_signatures', True):
        return out
    same_unique = (base['status'] == 'DRIFT_SUPPORTED' and geometric['status'] == 'DRIFT_SUPPORTED'
                   and base.get('hypothesis') == geometric.get('hypothesis')
                   and geometric.get('fold_effects') is not None and geometric.get('signatures') is not None)
    if same_unique:
        return out
    if base['status'] in ('DRIFT_SUPPORTED', 'DRIFT_AMBIGUOUS'):
        ambiguity = set(geometric.get('ambiguity_set') or []) | set(base.get('ambiguity_set') or [])
        if base.get('hypothesis'):
            ambiguity.add(base['hypothesis'])
        return dict(out, status='DRIFT_AMBIGUOUS', hypothesis=None,
                    ambiguity_set=sorted(ambiguity, key=lambda h: (len(h), h)),
                    reason='Calibration degradation is supported; conditional geometry cannot promote an ambiguous held-out explanation to unique physical attribution.')
    return dict(out, status=base['status'], hypothesis=base.get('hypothesis'),
                ambiguity_set=base.get('ambiguity_set', []), reason=base.get('reason', ''))


def update_contract(diagnosis, *, candidate=None, observable=False, uncertainty_status=None,
                    training_ids=(), validation_ids=(), validation=None):
    result = dict(diagnosis, candidate_calibration=candidate, update_recommended=False,
                  hardware_write_authorized=False, validation=validation or dict(available=False))
    if diagnosis['status'] != 'DRIFT_SUPPORTED':
        return result
    if candidate is None:
        return dict(result, update_reason='Supported diagnosis has no fitted candidate.')
    train, outer = set(training_ids), set(validation_ids)
    if not outer or train & outer or len(outer) < 3:
        return dict(result, update_reason='Three disjoint reserved validation captures are required.')
    valid = validation or {}
    passed = bool(observable and uncertainty_status == 'CONDITIONAL_ONLY' and valid.get('available')
                  and valid.get('edge_confirms') and valid.get('coverage_passed') and not valid.get('intensity_contradicts'))
    if passed:
        return dict(result, status='UPDATE_CANDIDATE_VALIDATED', update_recommended=True,
                    update_reason='Measurement-supported candidate passes reserved evidence checks; offline review only.')
    return dict(result, update_reason='Candidate support, conditional uncertainty, or reserved validation did not pass.')
