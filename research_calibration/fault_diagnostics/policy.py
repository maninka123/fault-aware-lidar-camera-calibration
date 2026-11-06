"""Experimental decision rules over chance-corrected, multi-cue held-out evidence.

This is deliberately separate from ``decision_policy.decide`` (production). It never changes a production
verdict; it states a second, experimental verdict next to it.

Statuses
    DRIFT_SUPPORTED          one explanation's chance-corrected gain replicates on the held-out captures, the
                             intensity cue does not contradict it, and the engine's attribution support holds
    DRIFT_AMBIGUOUS          a calibration change is supported, but several explanations remain tied
                             (non-nested), or the attribution support of the winner fails: detected, not attributed
    NUISANCE_SUSPECTED       the production loss shows an apparent improvement that the chance-corrected evidence
                             does not reproduce (edge-density / correspondence artefact); keep the calibration
    KEEP_CONFIRMED           no explanation is supported and the held-out captures confirm the current calibration
                             (it beats the displaced decoys consistently)
    REFERENCE_NOT_CONFIRMED  no explanation is supported, the captures carry evidence, but the current calibration
                             does not beat chance: it may be far off (outside the local fit) - recalibrate or review
    INSUFFICIENT_EVIDENCE    too few captures, or too few informative captures for any cue

Only DRIFT_SUPPORTED with a passing independent outer check sets ``update_recommended``. Counts and medians are
descriptive; the sign-consistency rule is not a calibrated significance test because static captures of one
scene are dependent.
"""
from dataclasses import dataclass, asdict, replace
import math
import numpy as np
from ..parameter_hypotheses import HYPOTHESES
from .config import DiagnosticsConfig

GROUPS = {h.name: frozenset(h.groups) for h in HYPOTHESES}


@dataclass(frozen=True)
class PolicySwitches:
    """Ablation switches. All True is the proposed method."""
    chance_correction: bool = True       # decoy-referenced contrasts (False: raw matched share)
    intensity_cue: bool = True           # NID veto / confirmation (False: edges only)
    quality_gating: bool = True          # count only informative captures (False: every capture)
    robust_aggregation: bool = True      # sign consistency + median (False: plain mean)
    reference_confirmation: bool = True  # distinguish KEEP_CONFIRMED / REFERENCE_NOT_CONFIRMED (False: KEEP)
    nuisance_counterfactual: bool = True # flag apparent production gains not reproduced (False: plain KEEP)

    def to_dict(self):
        return asdict(self)


ABLATIONS = {
    'proposed': PolicySwitches(),
    'no_chance_correction': PolicySwitches(chance_correction=False),
    'no_intensity_cue': PolicySwitches(intensity_cue=False),
    'no_quality_gating': PolicySwitches(quality_gating=False),
    'no_robust_aggregation': PolicySwitches(robust_aggregation=False),
    'no_reference_confirmation': PolicySwitches(reference_confirmation=False),
    'no_nuisance_counterfactual': PolicySwitches(nuisance_counterfactual=False),
}

ALARM = ('DRIFT_SUPPORTED', 'DRIFT_AMBIGUOUS')


def _finite(values):
    return [float(v) for v in values if v is not None and np.isfinite(v)]


def _consistent(values, margin, cfg, robust, sign=1):
    """Gain (sign=+1) or loss (sign=-1) beyond margin that replicates over captures."""
    x = [sign*v for v in _finite(values)]
    n = len(x)
    if n < cfg.min_informative_captures:
        return False, dict(n=n, plus=0, minus=0, median=None, mean=None)
    plus = sum(v > margin for v in x); minus = sum(v < -margin for v in x)
    stats = dict(n=n, plus=int(plus), minus=int(minus), median=float(sign*np.median(x)), mean=float(sign*np.mean(x)))
    if robust:
        return bool(plus >= math.ceil(cfg.consistency*n) and np.median(x) > margin), stats
    return bool(np.mean(x) > margin), stats


def _confirmed(values, floor, cfg, robust):
    x = _finite(values)
    if len(x) < cfg.min_informative_captures:
        return False, dict(n=len(x), median=None, positive_share=None)
    stats = dict(n=len(x), median=float(np.median(x)), positive_share=float(np.mean(np.asarray(x) > 0)))
    if robust:
        return bool(np.median(x) >= floor and stats['positive_share'] >= cfg.consistency), stats
    return bool(np.mean(x) >= floor), stats


def decide_experimental(evidence, production_decision, cfg=None, switches=None, *, min_captures=4, outer=None):
    cfg = cfg or DiagnosticsConfig(); sw = switches or PolicySwitches()
    tests = evidence['tests']; folds = evidence['folds']; reference = evidence['reference']
    edge_key = 'edge_change' if sw.chance_correction else 'edge_share_change'
    out = dict(switches=sw.to_dict(), status='INSUFFICIENT_EVIDENCE', hypothesis=None, ambiguity_set=[],
               update_recommended=False, captures=len(tests), counterfactuals={},
               scope='Descriptive replication counts over dependent captures; not fault probabilities.')
    if len(tests) < min_captures:
        out['reason'] = 'Too few held-out captures for the declared comparison.'
        return out
    if sw.quality_gating:
        edge_set = [t for t in tests if evidence['informative'][t]['edge']]
        int_set = [t for t in tests if evidence['informative'][t]['intensity']]
    else:
        edge_set = [t for t in tests if reference[t]['edge_valid']]
        int_set = [t for t in tests if reference[t]['intensity_valid']]
    out['informative_captures'] = dict(edge=edge_set, intensity=int_set)
    # Reference confirmation (does the current calibration beat chance on the held-out captures?).
    # (The no_chance_correction ablation changes only the candidate evidence below, not this check.)
    edge_ok, edge_stats = _confirmed([reference[t]['edge_contrast'] for t in edge_set], cfg.edge_informative_contrast,
                                     cfg, sw.robust_aggregation)
    int_ok, int_stats = (_confirmed([reference[t]['intensity_contrast'] for t in int_set], cfg.intensity_informative_contrast,
                                    cfg, sw.robust_aggregation) if sw.intensity_cue else (False, {}))
    out['reference_confirmation'] = dict(edge=edge_ok, edge_stats=edge_stats, intensity=int_ok, intensity_stats=int_stats)
    supported = []
    two_cues = bool(sw.intensity_cue and len(int_set) >= cfg.min_informative_captures)
    out['evidence_basis'] = 'edges and intensity' if two_cues else 'edges only'
    for h, rows in folds.items():
        if h == 'KEEP':
            continue
        complete = all(rows.get(t, {}).get('success') for t in tests)
        edge_values = [rows.get(t, {}).get(edge_key) for t in edge_set]
        edge_ok_h, e_stats = _consistent(edge_values, cfg.edge_gain_margin, cfg, sw.robust_aggregation)
        strict_ok, _ = _consistent(edge_values, cfg.single_cue_edge_margin, cfg, sw.robust_aggregation)
        contra, _ = (_consistent([rows.get(t, {}).get('intensity_change') for t in int_set], cfg.intensity_gain_margin,
                                 cfg, sw.robust_aggregation, sign=-1) if sw.intensity_cue else (False, {}))
        # Reported with gains as 'plus' and losses as 'minus'.
        agree, i_stats = (_consistent([rows.get(t, {}).get('intensity_change') for t in int_set], cfg.intensity_gain_margin,
                                      cfg, sw.robust_aggregation) if sw.intensity_cue else (False, {}))
        prod = _finite([rows.get(t, {}).get('production_gain') for t in tests])
        chance = _finite([rows.get(t, {}).get('chance_gain') for t in tests])
        attribution = all(all(rows.get(t, {}).get('attribution_support', {}).get(g, False) for g in GROUPS[h]) for t in tests)
        out['counterfactuals'][h] = dict(complete=complete, edge=e_stats, edge_supported=edge_ok_h,
            intensity=i_stats, intensity_contradicts=contra, intensity_agrees=agree,
            production_mean_gain=float(np.mean(prod)) if prod else None,
            chance_predicted_mean_gain=float(np.mean(chance)) if chance else None,
            attribution_support_all_folds=attribution)
        # Two informative cues: both must show a replicated gain (independent physics must agree).
        # One cue (intensity uninformative): edges must clear the doubled margin.
        # Ablation without the intensity cue: edges at the base margin.
        if not sw.intensity_cue:
            ok = edge_ok_h
        elif two_cues:
            ok = edge_ok_h and agree and not contra
        else:
            ok = strict_ok
        out['counterfactuals'][h]['supported'] = bool(complete and ok)
        if complete and ok:
            supported.append(h)
    out['supported'] = supported
    production_gain = production_decision.get('best_relative_gain')
    apparent = bool(production_decision.get('status') == 'CANDIDATE_SUPPORTED' or
                    (production_gain is not None and production_gain >= cfg.production_min_relative_gain))
    if supported:
        score = {h: out['counterfactuals'][h]['edge']['median'] for h in supported}
        best = max(supported, key=lambda h: (score[h], -len(GROUPS[h]), h))
        tied = [best]
        for h in supported:
            if h == best:
                continue
            diffs = [folds[best][t].get(edge_key) - folds[h][t].get(edge_key) for t in edge_set
                     if folds[best].get(t, {}).get(edge_key) is not None and folds[h].get(t, {}).get(edge_key) is not None
                     and np.isfinite(folds[best][t][edge_key]) and np.isfinite(folds[h][t][edge_key])]
            better, _ = _consistent(diffs, cfg.edge_gain_margin, cfg, sw.robust_aggregation)
            if not better:
                tied.append(h)
        # Parsimony: keep only the minimal tied explanations (no tied explanation uses a proper subset of
        # their groups). One minimal explanation is chosen; several (e.g. R and I) remain an ambiguity set.
        minimal = [h for h in tied if not any(GROUPS[o] < GROUPS[h] for o in tied)]
        out['tied_set'] = sorted(tied, key=lambda h: (len(GROUPS[h]), h))
        out['ambiguity_set'] = sorted(minimal, key=lambda h: (len(GROUPS[h]), h))
        if len(minimal) > 1:
            out.update(status='DRIFT_AMBIGUOUS', reason='A calibration change is supported, but explanations '
                       + ' / '.join(out['ambiguity_set']) + ' fit the held-out captures equally well.')
            return out
        chosen = minimal[0]
        out['hypothesis'] = chosen
        if not out['counterfactuals'][chosen]['attribution_support_all_folds']:
            out.update(status='DRIFT_AMBIGUOUS', reason='A change is supported, but the engine cannot attribute it to '
                       + chosen + ' separately from other parameter groups in every fold.')
            return out
        out.update(status='DRIFT_SUPPORTED', reason='The chance-corrected gain of ' + chosen +
                   ' replicates on held-out captures and the intensity cue does not contradict it.')
        if outer is None or not outer.get('available'):
            out['update_reason'] = 'No independent outer captures; a supported drift is reported but no update is recommended.'
        else:
            out['outer'] = outer
            ok = bool(outer.get('hypothesis') == chosen and outer.get('supported_update') and outer.get('edge_confirms')
                      and not (sw.intensity_cue and outer.get('intensity_contradicts')))
            out['update_recommended'] = ok
            out['update_reason'] = 'Outer captures confirm the chance-corrected gain.' if ok else 'The outer check does not confirm the candidate.'
        return out
    if apparent and sw.nuisance_counterfactual:
        out.update(status='NUISANCE_SUSPECTED', reason='The production loss improves, but no explanation improves the '
                   'chance-corrected evidence consistently: the apparent gain is attributed to edge density or correspondence artefacts.')
        return out
    if not sw.reference_confirmation:
        out.update(status='KEEP_CONFIRMED', reason='No explanation is supported (reference confirmation disabled).')
        return out
    if edge_ok or int_ok:
        out.update(status='KEEP_CONFIRMED', reason='No explanation is supported and the current calibration beats chance on the held-out captures.')
        return out
    if len(edge_set) < cfg.min_informative_captures and len(int_set) < cfg.min_informative_captures:
        out.update(status='INSUFFICIENT_EVIDENCE', reason='Too few informative captures: the scenes cannot separate aligned from displaced data.')
        return out
    out.update(status='REFERENCE_NOT_CONFIRMED', reason='No explanation is supported, and the current calibration does not beat chance '
               'although some captures are informative; it may lie outside the local fit. Review or recalibrate.')
    return out
