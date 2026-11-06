"""Reuse V2 temporal detector; do not assert an unvalidated V3 temporal benefit."""
from ..fault_diagnostics.runner import persistence_report


def temporal_report(caps, model, current, config):
    result = persistence_report(caps, model, current, config)
    return dict(result, algorithm='unchanged V2 edge/intensity monitors', new_v3_temporal_mechanism=False,
                guarantee='No operational false-alarm or exchangeability guarantee established.')
