"""Join the grouped evaluation outputs into per-group, per-method tables with worst-group results, generalization gaps and leave-one-group-out selection.

    python -B tools/summarize_generalization_v3.py RUN_FOLDER

Reads RUN_FOLDER/{pipeline,original_optimizer,pairing_*}/trials.jsonl (produced by tools/run_generalization_v3.py) and
research_data/groups_v3.json. Counts only: trials within a group are perturbations of one static scene, so no confidence interval is given.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import json
import numpy as np
from research_calibration.fault_diagnostics_v3 import generalization as G
from research_calibration.legacy_adapter import REPOSITORY

COMPARED = ['original_optimizer', 'production', 'v2', 'v2_no_intensity', 'v3', 'improved_v3']
IMPROVED_VARIANTS = ['oriented', 'geometric', 'geometric_no_visibility', 'geometric_no_balance', 'geometric_no_confidence']
NAMES = {'original_optimizer': 'Original method (frozen maintenance optimizer policy)', 'production': 'Production policy (research engine)',
         'v2': 'V2', 'v2_no_intensity': 'V2 without intensity rule', 'v3': 'Original V3 (recorded pipeline)', 'improved_v3': 'Improved V3 (signed diagnosis, geometric pairing)'}


def read(path):
    p = Path(path)
    return [json.loads(l) for l in p.read_text(encoding='utf-8').splitlines() if l.strip()] if p.exists() else []


def norm_pipeline(score):
    return dict(alarm=bool(score['alarm']), exact=bool(score.get('correct_attribution')), wrong=bool(score.get('wrong_attribution')),
                ambiguous_has_truth=bool(score.get('ambiguous_contains_truth')))


def build(run):
    run = Path(run)
    manifest = json.loads((REPOSITORY / 'research_data/manifest.json').read_text(encoding='utf-8'))
    to_group = {d['id']: d.get('registry_group') for d in manifest['datasets']}
    trials = {}

    def slot(ds, rep, cond, ctype):
        key = (ds, rep, cond)
        return trials.setdefault(key, dict(group=to_group[ds], dataset=ds, replicate=rep, condition=cond, condition_type=ctype, scores={}, seconds={}, recovery={}))
    for r in read(run / 'pipeline/trials.jsonl'):
        t = slot(r['dataset'], r['replicate'], r['condition'], r['condition_type'])
        for src, dst in (('production', 'production'), ('v2', 'v2'), ('v2_no_intensity', 'v2_no_intensity'), ('v3', 'v3')):
            if src in r['score']:
                t['scores'][dst] = norm_pipeline(r['score'][src])
                t['seconds'][dst] = r['shared_seconds'] + r.get('method_seconds', {}).get(src, 0.)
    for r in read(run / 'original_optimizer/trials.jsonl'):
        t = slot(r['dataset'], r['replicate'], r['condition'], r['condition_type'])
        # Under the legacy_optimizer strategy the policy applied to the frozen maintenance fits is scored under this key.
        t['scores']['original_optimizer'] = norm_pipeline(r['score']['legacy_optimizer'])
        t['seconds']['original_optimizer'] = r['shared_seconds']
    for path in sorted(run.glob('pairing_*/trials.jsonl')):
        for r in read(path):
            t = slot(r['dataset'], r['replicate'], r['condition'], r['condition_type'])
            for m, v in r['methods'].items():
                # The headline method is reported as "improved_v3" and also kept under its variant name "geometric", so every table finds it.
                for name in (('improved_v3', 'geometric') if m == 'geometric' else (m,)):
                    t['scores'][name] = dict(alarm=bool(v['score']['alarm']), exact=bool(v['score']['exact']), wrong=bool(v['score']['wrong']),
                                            ambiguous_has_truth=bool(v['score']['ambiguous_has_truth']))
                    t['seconds'][name] = sum(v['seconds'].values())
                    if 'recovery' in v and v['recovery'].get('error_after_px') is not None:
                        t['recovery'][name] = dict(before=r['error_before_px'], after=v['recovery']['error_after_px'])
    return list(trials.values())


def per_group(trials, methods, kinds=('nominal', 'drift')):
    groups = sorted({t['group'] for t in trials})
    table = {}
    for g in groups:
        rows = [t for t in trials if t['group'] == g and t['condition_type'] in kinds]
        table[g] = {m: G.group_metrics(rows, m) for m in methods}
    return table


def fmt(m):
    return (f"{m['no_change_alarms']}/{m['no_change_trials']} | {m['detections']}/{m['drift_trials']} | {m['exact']}/{m['drift_trials']} | "
            f"{m['wrong_unique']} | {m['ambiguous_with_truth']}")


def main(run):
    registry = G.load_registry(REPOSITORY / 'research_data/groups_v3.json')
    roles = {g['id']: g['role'] for g in registry['groups']}
    trials = build(run)
    G.validate_registry(registry)
    lines = ['# Generalization results (generated)', '',
             f'Run: `{Path(run).name}`. Trials: {len(trials)} joined. Counts of dependent trials within a group (one static scene each); no confidence intervals.', '']
    # --- matched comparison on nominal + drift trials common to every compared method
    methods = [m for m in COMPARED if any(m in t['scores'] for t in trials)]
    common = [t for t in trials if t['condition_type'] in ('nominal', 'drift') and all(m in t['scores'] for m in methods)]
    if not common:
        msg = 'No trial has results from every compared method; nothing can be compared. Check the run folder logs.'
        (Path(run) / 'generalization_summary.md').write_text('# Generalization results (generated)\n\n' + msg + '\n', encoding='utf-8')
        print(msg)
        return
    tab = per_group(common, methods)
    out = dict(methods=methods, per_group=tab, roles=roles)
    for m in methods:
        lines += [f'## {NAMES[m]}', '', '| Group | Role | No-change alarms | Detections | Exact | Wrong unique | Ambiguity contains truth | Median s/trial |', '|---|---|---|---|---|---|---|---|']
        for g, row in tab.items():
            secs = [t['seconds'][m] for t in common if t['group'] == g and m in t['seconds']]
            lines.append(f"| {g} | {roles[g]} | " + ' | '.join(fmt(row[m]).split(' | ')) + f" | {np.median(secs):.2f} |")
        lines.append('')
    # --- worst group and gaps
    lines += ['## Worst group and generalization gap (rates over the common nominal+drift trials)', '',
              '| Method | Worst false-alarm group (rate) | Worst detection group (rate) | Worst exact group (rate) | Dev-mean exact | Unseen-mean exact | Exact gap (dev - unseen) | Dev-mean false alarm | Unseen-mean false alarm |',
              '|---|---|---|---|---|---|---|---|---|']
    out['worst'] = {}
    for m in methods:
        per = {g: tab[g][m] for g in tab}
        fa = G.worst_and_gap(per, 'false_alarm_rate', False); de = G.worst_and_gap(per, 'detection_rate', True); ex = G.worst_and_gap(per, 'exact_rate', True)
        dev = [G.rates(per[g]) for g in per if roles[g] == 'development']; unseen = [G.rates(per[g]) for g in per if roles[g] == 'not_used_in_design']
        mean = lambda rs, k: float(np.mean([r[k] for r in rs])) if rs else float('nan')
        out['worst'][m] = dict(false_alarm=fa, detection=de, exact=ex, dev_exact=mean(dev, 'exact_rate'), unseen_exact=mean(unseen, 'exact_rate'),
                               dev_false_alarm=mean(dev, 'false_alarm_rate'), unseen_false_alarm=mean(unseen, 'false_alarm_rate'))
        lines.append(f"| {NAMES[m]} | {fa['worst_group']} ({fa['worst_value']:.2f}) | {de['worst_group']} ({de['worst_value']:.2f}) | {ex['worst_group']} ({ex['worst_value']:.2f}) | "
                     f"{mean(dev, 'exact_rate'):.2f} | {mean(unseen, 'exact_rate'):.2f} | {mean(dev, 'exact_rate') - mean(unseen, 'exact_rate'):+.2f} | "
                     f"{mean(dev, 'false_alarm_rate'):.2f} | {mean(unseen, 'false_alarm_rate'):.2f} |")
    # --- nuisance trials (improved variants only)
    nui = [t for t in trials if t['condition_type'] == 'nuisance']
    if nui:
        lines += ['', '## Nuisance-only trials (spurious lines, ghost edges; improved-V3 variants only)', '', '| Group | ' + ' | '.join(IMPROVED_VARIANTS) + ' |', '|---|' + '---|' * len(IMPROVED_VARIANTS)]
        for g in sorted({t['group'] for t in nui}):
            rows = [t for t in nui if t['group'] == g]
            cell = lambda v: (f"{sum(t['scores'][v]['alarm'] for t in rows if v in t['scores'])}/{sum(1 for t in rows if v in t['scores'])}"
                              if any(v in t['scores'] for t in rows) else 'n/a')
            lines.append(f'| {g} | ' + ' | '.join(cell(v) for v in IMPROVED_VARIANTS) + ' |')
    # --- calibration recovery (improved V3 variants)
    lines += ['', '## Calibration recovery (median projection error vs the anchor on alarmed drift trials; improved-V3 variants; px, before -> after)', '',
              '| Group | ' + ' | '.join(IMPROVED_VARIANTS) + ' |', '|---|' + '---|' * len(IMPROVED_VARIANTS)]
    for g in sorted({t['group'] for t in trials}):
        cells = []
        for v in IMPROVED_VARIANTS:
            rec = [t['recovery'][v] for t in trials if t['group'] == g and t['condition_type'] == 'drift' and v in t['recovery']]
            cells.append(f"{np.median([r['before'] for r in rec]):.2f} -> {np.median([r['after'] for r in rec]):.2f} (n={len(rec)})" if rec else '-')
        lines.append(f'| {g} | ' + ' | '.join(cells) + ' |')
    # --- leave-one-group-out variant selection for the improved front end
    var_tab = per_group([t for t in trials if t['condition_type'] in ('nominal', 'drift') and all(v in t['scores'] for v in IMPROVED_VARIANTS)], IMPROVED_VARIANTS)
    lines += ['', '## Leave-one-out selection of the pairing variant (selection sees training groups only)', '',
              'Declared cost: (no-change alarms + wrong unique labels, then -detections, then -exact) summed over training groups. A fold holds out every group sharing the key value.', '',
              '| Key | Held out | Selected on training groups | Held-out alarms / wrong / detections / exact (selected) | Same for fixed default (geometric) | Best variant in hindsight |', '|---|---|---|---|---|---|']
    out['logo'] = []
    for kind in ('scene', 'session', 'device'):
        for fold in G.folds(registry, kind):
            G.assert_no_leakage(fold, registry)
            train = [g for g in fold['training'] if g in var_tab]; held = [g for g in fold['held_out'] if g in var_tab]
            if not train or not held:
                continue
            sel = G.select_variant(var_tab, IMPROVED_VARIANTS, train)
            add = lambda v: {k: sum(var_tab[g][v][k] for g in held) for k in G.METRICS}
            hindsight = min(IMPROVED_VARIANTS, key=lambda v: G.selection_cost(add(v)))
            s_, d_ = add(sel), add('geometric')
            brief = lambda a: f"{a['no_change_alarms']} / {a['wrong_unique']} / {a['detections']}/{a['drift_trials']} / {a['exact']}"
            lines.append(f"| {kind} | {', '.join(held)} | {sel} | {brief(s_)} | {brief(d_)} | {hindsight} |")
            out['logo'].append(dict(kind=kind, held=held, selected=sel, selected_metrics=s_, default_metrics=d_, hindsight=hindsight))
    # --- scene properties
    lines += ['', '## Group properties next to improved-V3 results', '', '| Group | Device | Session | Range p5/p50/p95 (m) | Edge density | Saturated | Az / El std | Improved-V3 exact | Improved-V3 false alarms |', '|---|---|---|---|---|---|---|---|---|']
    for g in registry['groups']:
        if g['id'] in tab:
            m = tab[g['id']]['improved_v3']; d = g['descriptors']
            lines.append(f"| {g['id']} | {g['device']} | {g['session']} | {'/'.join(f'{x:.1f}' for x in d['range_p5_p50_p95_m'])} | {d['edge_density']:.3f} | {d['saturated_share']:.3f} | "
                         f"{d['azimuth_std_deg']:.0f} / {d['elevation_std_deg']:.0f} | {m['exact']}/{m['drift_trials']} | {m['no_change_alarms']}/{m['no_change_trials']} |")
    (Path(run) / 'generalization_summary.json').write_text(json.dumps(out, indent=2, default=str) + '\n', encoding='utf-8')
    (Path(run) / 'generalization_summary.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('\n'.join(lines))


if __name__ == '__main__':
    main(sys.argv[1])
