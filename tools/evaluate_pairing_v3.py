"""Frozen-protocol evaluation of correspondence front ends for V3 signed-residual diagnosis, calibration recovery and update safety.

All trials share captures, perturbation, seeds and inference (V3 ``infer_signatures``); only the pairing differs. Truth is relative
to each recording's anchor (see docs/research/v3/PROTOCOL_CORRESPONDENCE.md): no physical ground truth exists.

Per trial and method:
  diagnosis   status, supported / ambiguity sets, exact / wrong / truth-in-ambiguity scoring
  recovery    when an alarm is raised, a truncated-SVD one-step correction over the diagnosed groups; the projection error versus the
              anchor (median px over the captures' LiDAR points) before and after
  acceptance  an update is accepted only for a unique diagnosis whose correction, fitted on training captures, improves the V2
              chance-referenced edge contrast on EVERY reserved capture (engine outer-split rule); never authorizes a hardware write
  cost        seconds for pairing, row assembly and inference

Usage:
  python -B tools/evaluate_pairing_v3.py --datasets enclosure_on_twelve october_device_four --role evaluation --replicates 2 --output research_artifacts/X
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import os
for _k in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS'):
    os.environ[_k] = '1'
import argparse
import json
import math
import shutil
import tempfile
import time
import zlib
import numpy as np
import cv2
cv2.setNumThreads(1)
from research_calibration.benchmark import dataset_paths, environment
from research_calibration.config import ResearchConfig
from research_calibration.fault_diagnostics import DiagnosticsConfig, perturbations as P
from research_calibration.fault_diagnostics.cues import CaptureCues
from research_calibration.fault_diagnostics_v3 import SignatureConfig, correspondence as C
from research_calibration.geometry import ProjectionModel, parameters, retract
from research_calibration.legacy_adapter import load_capture_bundle, REPOSITORY
from research_calibration.parameter_hypotheses import GROUPS as PARAM_GROUPS, NUISANCE, parameter_scales
from research_calibration.reporting import serializable
from analyze_attribution_root_cause_v3 import FRONT_ENDS, STRICT, GROUPS, ALARM, stack, diagnose, score, recovery
from evaluate_fault_diagnostics import anchor_calibration, params_in, pixel_error, subset_bundle, DRIFTS

QUICK_DRIFTS = (('R', 1.), ('T', .06), ('I_pp', 3.), ('I_focal', .02), ('RT', (.5, .03)))
METHODS = ('reference_pairs', 'nearest', 'oriented', 'geometric', 'geometric_no_visibility', 'geometric_no_confidence', 'geometric_no_balance')
MAX_STD = 1.0                 # normalized units: a direction is corrected only if its implied standard deviation is at most this
EDGE_MARGIN = DiagnosticsConfig().edge_gain_margin


def correction(rows, groups, scales):
    """Truncated-SVD least-squares correction over the diagnosed parameter groups (+ beam nuisance), normalized -> physical units."""
    J, r, var, _ = rows
    free = sorted({i for g in groups for i in PARAM_GROUPS[g]} | set(NUISANCE))
    a = J[:, free] * scales[free] / np.sqrt(var)[:, None]
    y = -r / np.sqrt(var)
    u, s, vt = np.linalg.svd(a, full_matrices=False)
    keep = s >= 1. / MAX_STD
    beta = (vt[keep].T * (1. / s[keep])) @ (u[:, keep].T @ y) if keep.any() else np.zeros(len(free))
    delta = np.zeros(13)
    delta[free] = beta * scales[free]
    return delta, int(keep.sum()), len(free)


def reserved_split(names, cfg):
    perm = np.random.default_rng(cfg.seed).permutation(len(names))
    count = max(2, math.ceil(len(names) * cfg.outer_fraction)) if len(names) >= cfg.min_capture_blocks + 3 else 0
    held = {names[i] for i in perm[:count]}
    return [n for n in names if n not in held], [n for n in names if n in held]


def run(args):
    cfg, diag, sig = ResearchConfig(), DiagnosticsConfig(), SignatureConfig()
    manifest = json.loads((REPOSITORY / 'research_data/manifest.json').read_text(encoding='utf-8'))
    roles = {d['id']: d.get('pairing_role', 'unassigned') for d in manifest['datasets']}
    if any(roles.get(d) != args.role for d in args.datasets):
        raise SystemExit('Every dataset must carry pairing_role=' + args.role + ' in the manifest')
    needed = {'evaluation': 'PROTOCOL_CORRESPONDENCE.md', 'not_used_in_design': 'PROTOCOL_GENERALIZATION.md'}.get(args.role)
    if needed and not (REPOSITORY / 'docs/research/v3' / needed).exists():
        raise SystemExit('The frozen protocol document ' + needed + ' is required before these recordings are used')
    out = Path(args.output)
    if out.exists() and any(out.iterdir()):
        raise FileExistsError('Use a new output directory')
    out.mkdir(parents=True, exist_ok=True)
    (out / 'protocol.json').write_text(json.dumps(serializable(dict(
        role=args.role, datasets=args.datasets, replicates=args.replicates, methods=METHODS, drifts=DRIFTS,
        correspondence=C.CorrespondenceConfig().to_dict(), signature=sig.to_dict(), research=cfg.to_dict(),
        recovery=dict(max_std=MAX_STD), acceptance=dict(edge_margin=EDGE_MARGIN), environment=environment())), indent=2) + '\n', encoding='utf-8')
    scratch = Path(tempfile.mkdtemp(prefix='v3pair_', dir=os.environ.get('LOCALAPPDATA')))
    sink = (out / 'trials.jsonl').open('a', encoding='utf-8')
    try:
        for dataset in args.datasets:
            reference_path, data = dataset_paths(dataset)
            full = load_capture_bundle(data, scratch / dataset, cfg.max_features_per_capture, cfg.seed,
                                       intensity_points=diag.intensity_points, intensity_bins=diag.intensity_bins)
            anchor = anchor_calibration(dataset, reference_path, full, cfg)
            amodel = ProjectionModel(anchor, full.size, full.circle, cfg.max_angle_rad)
            p_anchor = parameters(anchor)
            for rep in range(args.replicates):
                rng0 = np.random.default_rng(1000 * rep + 17)
                n = len(full.caps)
                keep = sorted(rng0.choice(n, n - 2, replace=False).tolist()) if n > 6 else list(range(n))
                base = subset_bundle(full, keep)
                truth_pairs = {c.name: C.associate(c, amodel, p_anchor, STRICT) for c in base.caps}
                train_names, held_names = reserved_split([c.name for c in base.caps], cfg)
                conditions = [('nominal', None, None)] + [('drift', k, m) for k, m in DRIFTS] + \
                             [('nuisance', 'spurious_lines_all', None), ('nuisance', 'ghost_all', None)]
                if args.quick:
                    conditions = [c for c in conditions if c[0] != 'drift' or (c[1], c[2]) in QUICK_DRIFTS]
                for ctype, kind, magnitude in conditions:
                    crng = np.random.default_rng([rep, zlib.crc32(f'{ctype}|{kind}|{magnitude}'.encode())])
                    cal, truth, delta_true = anchor, None, np.zeros(13)
                    caps = base.caps
                    if ctype == 'drift':
                        delta_true, truth = P.calibration_change(p_anchor, kind, magnitude, crng)
                        cal = P.perturbed_calibration(anchor, amodel, p_anchor, delta_true)
                    if ctype == 'nuisance':
                        caps = P.apply_nuisance(base.caps, base.circle, kind, crng)
                    cmodel = ProjectionModel(cal, base.size, base.circle, cfg.max_angle_rad)
                    p_cur = parameters(cal)
                    p_true = params_in(anchor, cmodel)
                    scales = parameter_scales(p_cur)
                    label = f'{ctype}:{kind}:{magnitude}' if ctype == 'drift' else f'{ctype}:{kind}' if kind else ctype
                    by_name = {c.name: c for c in caps}
                    train = [by_name[x] for x in train_names]
                    held = [by_name[x] for x in held_names]
                    row = dict(dataset=dataset, replicate=rep, condition=label, condition_type=ctype,
                               truth_groups=list(truth) if truth else None, captures=len(caps), reserved=len(held),
                               error_before_px=pixel_error(caps, cmodel, p_cur, p_true), methods={})
                    for method in METHODS:
                        if method == 'reference_pairs' and ctype == 'nuisance':
                            continue
                        t0 = time.perf_counter()
                        pairing = ({c.name: truth_pairs[c.name] for c in caps} if method == 'reference_pairs'
                                   else {c.name: FRONT_ENDS[method](c, cmodel, p_cur) for c in caps})
                        t1 = time.perf_counter()
                        rows = stack(caps, cmodel, p_cur, pairing, scales, sig.max_rows_per_capture, np.random.default_rng(5))
                        res = diagnose(rows, scales, sig)
                        t2 = time.perf_counter()
                        entry = dict(res, score=score(res, truth), rows=int(len(rows[1])) if rows else 0,
                                     seconds=dict(pairing=t1 - t0, inference=t2 - t1))
                        if res['status'] in ALARM and rows is not None:
                            groups = sorted({g for h in (res.get('ambiguity_set') or [res.get('hypothesis')]) if h for g in GROUPS[h]}) or ['R', 'T', 'I']
                            d, kept, free = correction(rows, groups, scales)
                            p_new = retract(p_cur, d)
                            entry['recovery'] = dict(groups=groups, identifiable_directions=kept, candidate_directions=free,
                                                     error_after_px=pixel_error(caps, cmodel, p_new, p_true) if cmodel.valid(p_new) else None,
                                                     **recovery(p_new, p_true))
                            # Acceptance: unique diagnosis, correction fitted on training captures, every reserved capture improves.
                            if res['status'] == 'DRIFT_SUPPORTED' and held and len(held) >= 3:
                                tr = stack(train, cmodel, p_cur, pairing, scales, sig.max_rows_per_capture, np.random.default_rng(5))
                                accepted = False
                                if tr is not None:
                                    dt, _, _ = correction(tr, groups, scales)
                                    p_tr = retract(p_cur, dt)
                                    gains = []
                                    for c in held:
                                        cues = CaptureCues(c, cmodel, p_cur, diag)
                                        e0, e1 = cues.edge(p_cur), cues.edge(p_tr)
                                        gains.append(e1.contrast - e0.contrast if e0.valid and e1.valid else float('nan'))
                                    accepted = bool(cmodel.valid(p_tr) and np.all(np.isfinite(gains)) and min(gains) > EDGE_MARGIN)
                                    entry['acceptance'] = dict(accepted=accepted, reserved_gains=gains,
                                                               error_after_px=pixel_error(caps, cmodel, p_tr, p_true) if cmodel.valid(p_tr) else None)
                        row['methods'][method] = entry
                    sink.write(json.dumps(serializable(row)) + '\n'); sink.flush()
                    print(f"{dataset[:10]} r{rep} {label:30s} " + ' '.join(
                        f"{m[:10]}={v['status'][:8]}/{v.get('hypothesis')}" for m, v in row['methods'].items() if m in ('reference_pairs', 'oriented', 'geometric')), flush=True)
    finally:
        sink.close()
        shutil.rmtree(scratch, ignore_errors=True)


def summarize(path):
    rows = [json.loads(l) for l in Path(path).read_text(encoding='utf-8').splitlines() if l.strip()]
    lines = ['| Method | No-change alarms | Detections | Exact | Wrong unique (all) | Ambiguous incl. truth | Median error after, alarmed drifts (px; before) | Accepted updates (no-change / drift, median error) | Median seconds / trial |', '|---|---|---|---|---|---|---|---|---|']
    for m in METHODS:
        drift = [r for r in rows if r['condition_type'] == 'drift' and m in r['methods']]
        quiet = [r for r in rows if r['condition_type'] != 'drift' and m in r['methods']]
        s = lambda rs, k: sum(r['methods'][m]['score'][k] for r in rs)
        alarmed = [r for r in drift if 'recovery' in r['methods'][m] and r['methods'][m]['recovery']['error_after_px'] is not None]
        after = np.median([r['methods'][m]['recovery']['error_after_px'] for r in alarmed]) if alarmed else float('nan')
        before = np.median([r['error_before_px'] for r in alarmed]) if alarmed else float('nan')
        acc_q = sum(1 for r in quiet if r['methods'][m].get('acceptance', {}).get('accepted'))
        acc_d = [r for r in drift if r['methods'][m].get('acceptance', {}).get('accepted')]
        acc_err = np.median([r['methods'][m]['acceptance']['error_after_px'] for r in acc_d]) if acc_d else float('nan')
        sec = np.median([sum(r['methods'][m]['seconds'].values()) for r in rows if m in r['methods']])
        lines.append(f"| {m} | {s(quiet, 'alarm')}/{len(quiet)} | {s(drift, 'alarm')}/{len(drift)} | {s(drift, 'exact')}/{len(drift)} | "
                     f"{s(quiet + drift, 'wrong')} | {s(drift, 'ambiguous_has_truth')} | {after:.2f} ({before:.2f}) | {acc_q}/{len(quiet)}; {len(acc_d)}/{len(drift)}, {acc_err:.2f} | {sec:.2f} |")
    return '\n'.join(lines)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--datasets', nargs='+', required=True)
    parser.add_argument('--role', choices=('development', 'evaluation', 'not_used_in_design'), required=True)
    parser.add_argument('--replicates', type=int, default=2)
    parser.add_argument('--quick', action='store_true', help='five drift conditions instead of seven (faster, same seeds)')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    run(args)
    text = summarize(Path(args.output) / 'trials.jsonl')
    (Path(args.output) / 'summary.md').write_text(text + '\n', encoding='utf-8')
    print(text)
