"""Run the unchanged production assessment and add the experimental fault diagnostics beside it."""
import json
import math
import time
from pathlib import Path
import numpy as np
from ..config import ResearchConfig
from ..calibration_pipeline import assess, fit_hypothesis, _training_selection
from ..geometry import ProjectionModel, parameters
from ..legacy_adapter import load_capture_bundle, read_calibration
from ..parameter_hypotheses import HYPOTHESES, parameter_scales
from ..reporting import serializable
from .config import DiagnosticsConfig
from .cues import CaptureCues
from .evidence import collect_evidence
from . import sequential as S
from .policy import ABLATIONS, decide_experimental, _consistent

LIMITATIONS = [
    'Experimental verdict: it does not change the production verdict, files or thresholds.',
    'Contrasts are measured against displaced copies of the same capture; they remove first-order edge-density '
    'effects but not a scene structure that repeats at the decoy offset.',
    'Replication counts over static captures of one scene are descriptive; captures are not independent samples.',
    'No physically labelled faults exist; detection and attribution rates come from known perturbations of '
    'recorded data relative to a reference whose own error is unknown.',
]


def outer_evidence(hypothesis, parameters_, supported_update, outer_caps, model, current, cfg):
    rows = []
    for cap in outer_caps:
        cc = CaptureCues(cap, model, current, cfg)
        e0, e1 = cc.edge(current), cc.edge(parameters_)
        i0, i1 = cc.intensity(current), cc.intensity(parameters_)
        rows.append(dict(id=cap.name, edge_change=e1.contrast - e0.contrast if e0.valid and e1.valid else None,
                         intensity_change=i1.contrast - i0.contrast if i0.valid and i1.valid else None))
    # Outer blocks are few (usually three): require every finite one to agree.
    strict = DiagnosticsConfig(**{**cfg.to_dict(), 'consistency': 1., 'min_informative_captures': 3})
    edge_ok, edge_stats = _consistent([r['edge_change'] for r in rows], cfg.edge_gain_margin, strict, True)
    contra, int_stats = _consistent([r['intensity_change'] for r in rows], cfg.intensity_gain_margin,
                                    DiagnosticsConfig(**{**cfg.to_dict(), 'min_informative_captures': 3}), True, sign=-1)
    return dict(available=len(rows) >= 3, hypothesis=hypothesis, supported_update=bool(supported_update), rows=rows,
                edge_confirms=edge_ok, edge=edge_stats, intensity_contradicts=contra, intensity=int_stats)


def persistence_report(caps, model, current, cfg):
    """Persistence monitor over every capture in capture-time order (needs capture times)."""
    times = [getattr(c, 'capture_time', None) for c in caps]
    if any(t is None for t in times):
        return dict(status='UNAVAILABLE', reason='Capture times are not available for every capture.')
    order = sorted(range(len(caps)), key=lambda i: (times[i], caps[i].name))
    edge, inten = [], []
    for i in order:
        cc = CaptureCues(caps[i], model, current, cfg)
        edge.append(cc.edge(current).contrast); inten.append(cc.intensity(current).contrast)
    out = dict(order=[caps[i].name for i in order],
               edge=S.monitor(edge, cfg, informative_floor=cfg.edge_informative_contrast),
               intensity=S.monitor(inten, cfg, informative_floor=cfg.intensity_informative_contrast))
    labels = {out['edge'].get('status'), out['intensity'].get('status')}
    out['status'] = next((s for s in ('PERSISTENT_CHANGE', 'CHANGE_AT_END_UNCONFIRMED', 'TRANSIENT_DEVIATION', 'NO_CHANGE',
                                      'INSUFFICIENT_EVIDENCE') if s in labels), 'UNINFORMATIVE')
    out['note'] = ('Assumes the first captures are nominal; detects a change during the recording, not a change '
                   'that happened before it (that is the batch assessment\'s job).')
    return out


def assess_with_diagnostics(calibration, captures, *, output, config=None, diagnostics=None, bundle=None,
                            strategy='fault_aware', ablations=None, write=True, records_out=None):
    cfg = config if isinstance(config, ResearchConfig) else ResearchConfig(**(config or {}))
    diag = diagnostics or DiagnosticsConfig()
    ablations = ablations or ABLATIONS
    output = Path(output)
    production_folder = output
    if bundle is None:
        # Layout: <output>/inputs (decoded captures), <output>/production (the unchanged assessment files),
        # <output>/fault_diagnostics.json. Existing runs are never overwritten.
        if output.exists() and any(output.iterdir()):
            raise FileExistsError('Use a new empty output folder; existing files will not be overwritten')
        bundle = load_capture_bundle(captures, output/'inputs', cfg.max_features_per_capture, cfg.seed,
                                     intensity_points=diag.intensity_points, intensity_bins=diag.intensity_bins)
        production_folder = output/'production'
    records = []
    started = time.perf_counter()
    result = assess(calibration, captures, strategy, output=production_folder, config=cfg, _bundle=bundle,
                    fold_observer=records.append)
    if records_out is not None:
        # Optional experimental consumer. Detached copies cannot affect fits,
        # production decisions, or the records used by V2 below.
        import copy
        records_out.extend(copy.deepcopy(records))
    production_seconds = time.perf_counter() - started
    begin = time.perf_counter()
    original = read_calibration(calibration)
    model = ProjectionModel(original, bundle.size, bundle.circle, cfg.max_angle_rad)
    current = parameters(original)
    evidence = collect_evidence(records, bundle.caps, model, current, diag, cfg.evaluation_cap_px)
    evidence_seconds = time.perf_counter() - begin
    final = next((r for r in records if r.get('stage') == 'final'), None)
    outer_ids = set(final['outer_ids']) if final else set()
    outer_caps = [c for c in bundle.caps if c.name in outer_ids]
    train = [c for c in bundle.caps if c.name not in outer_ids]
    production_decision = result.diagnostics['decision']
    outer_cache = {}
    extra_fits = 0

    def outer_for(h):
        nonlocal extra_fits
        if h in outer_cache:
            return outer_cache[h]
        if not outer_caps or h is None:
            outer_cache[h] = dict(available=False)
        elif final and final['hypothesis'] == h:
            outer_cache[h] = outer_evidence(h, final['parameters'], final['supported_update'] and final['success'],
                                            outer_caps, model, current, diag)
        else:
            # The experimental winner differs from the production candidate: one extra training-only fit.
            hyp = next(x for x in HYPOTHESES if x.name == h)
            selected, _ = _training_selection(train, model, current, parameter_scales(current), cfg, strategy)
            fitted = fit_hypothesis(selected, model, current, hyp, cfg, strategy)
            extra_fits += 1
            outer_cache[h] = (outer_evidence(h, fitted['parameters'], fitted.get('supported_update', False) and fitted['success'],
                                             outer_caps, model, current, diag) if fitted['success'] else dict(available=False))
        return outer_cache[h]

    decisions = {}
    for name, switches in ablations.items():
        first = decide_experimental(evidence, production_decision, diag, switches, min_captures=cfg.min_capture_blocks)
        if first['status'] == 'DRIFT_SUPPORTED' and outer_caps:
            first = decide_experimental(evidence, production_decision, diag, switches, min_captures=cfg.min_capture_blocks,
                                        outer=outer_for(first['hypothesis']))
        decisions[name] = first
    persistence = persistence_report(bundle.caps, model, current, diag)
    payload = dict(
        persistence=persistence,
        production=dict(status=result.status, decision_status=production_decision.get('status'),
                        candidate=production_decision.get('candidate_hypothesis'), selected=result.selected_hypothesis,
                        best_relative_gain=production_decision.get('best_relative_gain'),
                        ambiguity_set=production_decision.get('ambiguity_set'), reason=production_decision.get('reason')),
        experimental=decisions, evidence=evidence, outer={k: v for k, v in outer_cache.items()},
        cost=dict(production_seconds=production_seconds, evidence_seconds=evidence_seconds, extra_fits=extra_fits,
                  folds=len([r for r in records if r.get('stage') == 'fold'])),
        configuration=dict(research=cfg.to_dict(), diagnostics=diag.to_dict()), limitations=LIMITATIONS)
    if write:
        (output/'fault_diagnostics.json').write_text(json.dumps(serializable(payload), indent=2, allow_nan=False) + '\n',
                                                     encoding='utf-8')
    return payload, result
