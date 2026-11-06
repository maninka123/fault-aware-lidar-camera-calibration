"""Summarise trials.jsonl from evaluate_fault_diagnostics.py into rates with Wilson 95 % intervals.

Rates are over trials that share recordings and captures, so they are dependent; the intervals describe
binomial counting only and understate the true uncertainty.
"""
import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
import numpy as np


def wilson(k, n, z=1.96):
    if n == 0:
        return None
    p = k/n; d = 1 + z*z/n
    c = (p + z*z/(2*n))/d; h = z*math.sqrt(p*(1-p)/n + z*z/(4*n*n))/d
    return [max(0., c-h), min(1., c+h)]


def rate(rows, key):
    k = sum(bool(r[key]) for r in rows); n = len(rows)
    return dict(k=k, n=n, rate=k/n if n else None, wilson95=wilson(k, n))


def recompute(trials):
    """Development aid: re-apply the current policy code to the saved per-capture evidence.

    Never use this to change constants after looking at held-out trials."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from research_calibration.fault_diagnostics import DiagnosticsConfig
    from research_calibration.fault_diagnostics.policy import ABLATIONS, decide_experimental
    from evaluate_fault_diagnostics import score
    cfg = DiagnosticsConfig()
    for t in trials:
        if 'evidence' not in t:
            continue
        exp = {}
        for name, sw in ABLATIONS.items():
            d = decide_experimental(t['evidence'], t['production_decision'], cfg, sw)
            if d['status'] == 'DRIFT_SUPPORTED' and (t.get('outer') or {}).get(d['hypothesis']):
                d = decide_experimental(t['evidence'], t['production_decision'], cfg, sw, outer=t['outer'][d['hypothesis']])
            exp[name] = d
        t['experimental'] = exp
        if 'score' in t:
            t['score'] = score(t)
    return trials


def summarize(path, recompute_policy=False):
    trials = [json.loads(l) for l in Path(path).read_text(encoding='utf-8').splitlines() if l.strip()]
    if recompute_policy:
        trials = recompute(trials)
    errors = [t for t in trials if 'error' in t]
    scored = [t for t in trials if 'score' in t]
    methods = list(scored[0]['score']) if scored else []
    out = dict(trials=len(trials), errors=[dict(dataset=t['dataset'], condition=t['condition'], error=t['error']) for t in errors],
               methods={})
    for m in methods:
        groups = defaultdict(list)
        for t in scored:
            s = t['score'][m]
            ctype = t['condition_type']
            if ctype == 'drift_nuisance':
                ctype = 'drift'
            groups[ctype].append(s)
            groups['by_condition:' + t['condition']].append(s)
            groups['dataset:' + t['dataset'] + ':' + ctype].append(s)
        res = {}
        for g, rows in groups.items():
            change = g.endswith('drift') or g.startswith('by_condition:drift')
            entry = dict(alarm=rate(rows, 'alarm'), update=rate(rows, 'update'),
                         wrong_attribution=rate(rows, 'wrong_attribution'))
            if change:
                entry['correct_attribution'] = rate(rows, 'correct_attribution')
                if 'ambiguous_contains_truth' in rows[0]:
                    entry['ambiguous_contains_truth'] = rate(rows, 'ambiguous_contains_truth')
            statuses = defaultdict(int)
            for r in rows:
                statuses[r['status']] += 1
            entry['statuses'] = dict(statuses)
            res[g] = entry
        out['methods'][m] = res
    seconds = [t['cost']['production_seconds'] for t in scored]
    evidence = [t['cost']['evidence_seconds'] for t in scored]
    out['cost'] = dict(production_median_s=float(np.median(seconds)) if seconds else None,
                       diagnostics_median_s=float(np.median(evidence)) if evidence else None,
                       extra_fits=sum(t['cost']['extra_fits'] for t in scored))
    drift = [t for t in scored if t['condition_type'] in ('drift', 'drift_nuisance')]
    cur = [t['current_pixel_error_vs_anchor'] for t in drift if t['current_pixel_error_vs_anchor'] is not None]
    upd = [(t['current_pixel_error_vs_anchor'], t['candidate_pixel_error_vs_anchor']) for t in drift
           if t['score']['production']['update'] and t['candidate_pixel_error_vs_anchor'] is not None]
    out['alignment'] = dict(drift_current_median_px=float(np.median(cur)) if cur else None,
                            production_updates_px=[dict(before=a, after=b) for a, b in upd])
    return out


def markdown(summary, title):
    lines = [f'# {title}', '', f"Trials: {summary['trials']} (errors: {len(summary['errors'])}). Rates with Wilson 95 % intervals "
             '(dependent trials: intervals are optimistic).', '',
             '| Method | False alarm, nominal | False alarm, nuisance | Detection, drift | Correct attribution | '
             'Ambiguous incl. truth | Wrong attribution (all) | Updates on no-change |', '|---|---|---|---|---|---|---|---|']

    def f(e):
        if not e or e['n'] == 0:
            return '-'
        lo, hi = e['wilson95']
        return f"{e['k']}/{e['n']} ({100*e['rate']:.0f} %, {100*lo:.0f}-{100*hi:.0f})"
    for m, res in summary['methods'].items():
        nom, nui, dr = res.get('nominal', {}), res.get('nuisance', {}), res.get('drift', {})
        allrows = {k: v for k, v in res.items() if k in ('nominal', 'nuisance', 'drift')}
        wrong_k = sum(v['wrong_attribution']['k'] for v in allrows.values()); wrong_n = sum(v['wrong_attribution']['n'] for v in allrows.values())
        upd_k = sum(res[k]['update']['k'] for k in ('nominal', 'nuisance') if k in res)
        upd_n = sum(res[k]['update']['n'] for k in ('nominal', 'nuisance') if k in res)
        lines.append(f"| {m} | {f(nom.get('alarm'))} | {f(nui.get('alarm'))} | {f(dr.get('alarm'))} | {f(dr.get('correct_attribution'))} | "
                     f"{f(dr.get('ambiguous_contains_truth'))} | {f(dict(k=wrong_k, n=wrong_n, rate=wrong_k/wrong_n if wrong_n else 0, wilson95=wilson(wrong_k, wrong_n)))} | "
                     f"{f(dict(k=upd_k, n=upd_n, rate=upd_k/upd_n if upd_n else 0, wilson95=wilson(upd_k, upd_n)))} |")
    lines += ['', '## Status counts by condition (proposed and production)', '', '| Condition | Production | Proposed |', '|---|---|---|']
    prod, prop = summary['methods'].get('production', {}), summary['methods'].get('proposed', {})
    for g in sorted(k for k in prop if k.startswith('by_condition:')):
        lines.append(f"| {g[13:]} | {', '.join(f'{k} {v}' for k, v in sorted(prod[g]['statuses'].items()))} | "
                     f"{', '.join(f'{k} {v}' for k, v in sorted(prop[g]['statuses'].items()))} |")
    c = summary['cost']
    lines += ['', f"Median production seconds per trial: {c['production_median_s']:.1f}; added diagnostics: {c['diagnostics_median_s']:.1f} s; "
              f"extra fits: {c['extra_fits']}.", '']
    return '\n'.join(lines)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('trials'); parser.add_argument('--title', default='Fault diagnostics v2 evaluation')
    parser.add_argument('--recompute', action='store_true', help='Development only: re-apply the current policy to saved evidence')
    args = parser.parse_args()
    s = summarize(args.trials, args.recompute)
    folder = Path(args.trials).parent
    stem = 'summary_recomputed' if args.recompute else 'summary'
    (folder/(stem + '.json')).write_text(json.dumps(s, indent=2) + '\n', encoding='utf-8')
    (folder/(stem + '.md')).write_text(markdown(s, args.title), encoding='utf-8')
    print(markdown(s, args.title))
