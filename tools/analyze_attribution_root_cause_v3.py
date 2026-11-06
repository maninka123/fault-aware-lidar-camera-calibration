"""Root-cause experiments for the unsolved fault-attribution problem on recorded data (development use only).

Truth here is *relative to each recording's anchor* (its reference refined on all of its captures), which is itself not
physical truth. A perturbation of the anchor is the "current" calibration under diagnosis; the correct answer is the
perturbation's parameter group and its correct correction is the anchor. Proxy reference correspondences are the
pairings the anchor itself establishes under a strict gate; they are not independently verified.

Experiments per condition (all share captures, perturbation and seed):
  E1  identity accuracy of each pairing front end at the perturbed calibration against the anchor's pairs
  E2  parameter recovery of the existing production optimizer for every hypothesis, and whether its optimum has a lower
      objective than the anchor (model/association bias) or a higher one (optimizer did not arrive)
  E3  geometry of the retained rows at the anchor: principal angles between rotation, translation and intrinsics
  E4  signed-residual diagnosis (the V3 oracle inference) fed with (a) the anchor's pairs and (b) each front end's pairs,
      so the same geometry and inference are compared across correspondence quality

Usage from the repository root:
  python -B tools/analyze_attribution_root_cause_v3.py --datasets october_device_one --replicates 2 --output research_artifacts/v3_root_cause_X
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
import shutil
import tempfile
import time
import zlib
import numpy as np
import cv2
cv2.setNumThreads(1)
from scipy.spatial.transform import Rotation
from research_calibration.benchmark import dataset_paths
from research_calibration.calibration_pipeline import fit_hypothesis
from research_calibration.config import ResearchConfig
from research_calibration.fault_diagnostics import DiagnosticsConfig, perturbations as P
from research_calibration.fault_diagnostics_v3 import SignatureConfig
from research_calibration.fault_diagnostics_v3 import correspondence as C
from research_calibration.fault_diagnostics_v3.diagnostic_inference import infer_signatures
from research_calibration.fault_diagnostics_v3 import joint_estimation as JE
from research_calibration.fault_diagnostics_v3.hypothesis_separation import signature_report
from research_calibration.geometry import ProjectionModel, parameters
from research_calibration.legacy_adapter import load_capture_bundle
from research_calibration.parameter_hypotheses import HYPOTHESES, parameter_scales
from research_calibration.reporting import serializable
from research_calibration.residuals import evaluate_capture
from evaluate_fault_diagnostics import anchor_calibration, params_in, subset_bundle, DRIFTS

GROUPS = {h.name: tuple(h.groups) for h in HYPOTHESES}
ALARM = ('DRIFT_SUPPORTED', 'DRIFT_AMBIGUOUS')
STRICT = C.CorrespondenceConfig(gate_px=2., orientation_deg=15., candidates=1, visibility=False, confidence=False, balance=False)
EM_VARIANTS = {
    'em': C.CorrespondenceConfig(),
    'em_no_visibility': C.CorrespondenceConfig(visibility=False),
    'em_no_confidence': C.CorrespondenceConfig(confidence=False),
    'em_no_balance': C.CorrespondenceConfig(balance=False),
}
FRONT_ENDS = {
    'nearest': lambda cap, m, p: C.associate_nearest(cap, m, p, 8.),
    'oriented': lambda cap, m, p: C.associate_oriented(cap, m, p, 9., 30.),
    'geometric': lambda cap, m, p: C.associate(cap, m, p, C.CorrespondenceConfig()),
    'unique': lambda cap, m, p: C.associate(cap, m, p, C.CorrespondenceConfig(ambiguity_radius_px=12., confidence=False)),
    'unique_visible': lambda cap, m, p: C.associate(cap, m, p, C.CorrespondenceConfig(ambiguity_radius_px=12.)),
    'unique_visible_r4': lambda cap, m, p: C.associate(cap, m, p, C.CorrespondenceConfig(ambiguity_radius_px=4.0)),
    'unique_visible_r6': lambda cap, m, p: C.associate(cap, m, p, C.CorrespondenceConfig(ambiguity_radius_px=6.0)),
    'unique_visible_r8': lambda cap, m, p: C.associate(cap, m, p, C.CorrespondenceConfig(ambiguity_radius_px=8.0)),
    'unique_visible_r16': lambda cap, m, p: C.associate(cap, m, p, C.CorrespondenceConfig(ambiguity_radius_px=16.0)),
    'geometric_no_visibility': lambda cap, m, p: C.associate(cap, m, p, C.CorrespondenceConfig(visibility=False)),
    'geometric_no_confidence': lambda cap, m, p: C.associate(cap, m, p, C.CorrespondenceConfig(confidence=False)),
    'geometric_no_balance': lambda cap, m, p: C.associate(cap, m, p, C.CorrespondenceConfig(balance=False)),
}


def rotation_error_deg(w_fit, w_true):
    return float(np.degrees(np.linalg.norm((Rotation.from_rotvec(w_fit) * Rotation.from_rotvec(w_true).inv()).as_rotvec())))


def recovery(p_fit, p_true):
    return dict(rotation_deg=rotation_error_deg(p_fit[:3], p_true[:3]), translation_m=float(np.linalg.norm(p_fit[3:6] - p_true[3:6])),
                principal_point_px=float(np.hypot(*(p_fit[8:10] - p_true[8:10]))),
                focal_rel=float(abs(p_fit[6] / p_true[6] - 1)))


def stack(caps, model, p, assoc_by_name, scales, max_rows, rng):
    """Signed rows over captures (subsampled per capture) -> (jacobian, residual, variance, capture ids)."""
    J, r, var, ids = [], [], [], []
    for cap in caps:
        rows = C.signed_rows(cap, assoc_by_name[cap.name], model, p)
        n = len(rows['residual'])
        if not n:
            continue
        pick = np.sort(rng.choice(n, max_rows, replace=False)) if n > max_rows else np.arange(n)
        J.append(rows['jacobian'][pick]); r.append(rows['residual'][pick])
        var.append(1. / np.maximum(rows['weight'][pick], .05)); ids += [cap.name] * len(pick)
    if not J:
        return None
    return np.vstack(J), np.concatenate(r), np.concatenate(var), np.array(ids)


def diagnose(rows, scales, cfg):
    if rows is None:
        return dict(status='INSUFFICIENT_EVIDENCE', hypothesis=None, ambiguity_set=[], supported=[], rows=0)
    J, r, var, ids = rows
    try:
        out = infer_signatures(J, -r, scales, covariance=var, capture_ids=ids, config=cfg)
    except ValueError as error:
        return dict(status='INSUFFICIENT_EVIDENCE', hypothesis=None, ambiguity_set=[], supported=[], rows=len(r), reason=str(error))
    return dict(status=out['status'], hypothesis=out.get('hypothesis'), ambiguity_set=out.get('ambiguity_set', []),
                supported=out.get('supported', []), rows=out['rows'], reason=out.get('reason'))


def score(res, truth):
    change = truth is not None
    alarm = res['status'] in ALARM
    g = tuple(GROUPS[res['hypothesis']]) if res['status'] == 'DRIFT_SUPPORTED' and res.get('hypothesis') else None
    amb = [tuple(GROUPS[h]) for h in res.get('ambiguity_set') or []]
    return dict(alarm=alarm, exact=bool(change and g is not None and set(g) == set(truth)),
                wrong=bool(g is not None and (not change or set(g) != set(truth))),
                ambiguous_has_truth=bool(change and res['status'] == 'DRIFT_AMBIGUOUS' and any(set(a) == set(truth) for a in amb)))


def run(args):
    cfg, diag = ResearchConfig(), DiagnosticsConfig()
    sig = SignatureConfig()
    out = Path(args.output)
    if out.exists() and any(out.iterdir()):
        raise FileExistsError('Use a new output directory')
    out.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix='v3rc_', dir=os.environ.get('LOCALAPPDATA')))
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
                conditions = [('nominal', None, None)] + [('drift', k, m) for k, m in DRIFTS] + \
                             [('nuisance', 'spurious_lines_all', None), ('nuisance', 'ghost_all', None)]
                for ctype, kind, magnitude in conditions:
                    started = time.perf_counter()
                    crng = np.random.default_rng([rep, zlib.crc32(f'{ctype}|{kind}|{magnitude}'.encode())])
                    cal, truth, delta = anchor, None, np.zeros(13)
                    caps = base.caps
                    if ctype == 'drift':
                        delta, truth = P.calibration_change(p_anchor, kind, magnitude, crng)
                        cal = P.perturbed_calibration(anchor, amodel, p_anchor, delta)
                    if ctype == 'nuisance':
                        caps = P.apply_nuisance(base.caps, base.circle, kind, crng)
                    cmodel = ProjectionModel(cal, base.size, base.circle, cfg.max_angle_rad)
                    p_cur = parameters(cal)
                    p_true = params_in(anchor, cmodel)
                    scales = parameter_scales(p_cur)
                    label = f'{ctype}:{kind}:{magnitude}' if ctype == 'drift' else f'{ctype}:{kind}' if kind else ctype
                    row = dict(dataset=dataset, replicate=rep, condition=label, condition_type=ctype,
                               truth_groups=list(truth) if truth else None, captures=len(caps))
                    # E1 identity accuracy at the current calibration
                    assoc = {name: {c.name: f(c, cmodel, p_cur) for c in caps} for name, f in FRONT_ENDS.items()}
                    if args.em:
                        for name, cc in EM_VARIANTS.items():
                            fit = JE.em_refine(caps, cmodel, p_cur, cc)
                            assoc[name] = JE.keep_confident(fit['pairs'], JE.EMConfig().final_min_confidence)
                            row.setdefault('em_recovery', {})[name] = dict(recovery(fit['parameters'], p_true),
                                                                          moved_from_current=recovery(fit['parameters'], p_cur))
                    if ctype != 'nuisance':
                        row['identity'] = {}
                        for name, by_cap in assoc.items():
                            agg = dict(matched=0, correct=0, wrong=0, unverifiable=0, reference=0)
                            for c in caps:
                                a = C.pair_accuracy(by_cap[c.name], truth_pairs[c.name])
                                for k in agg:
                                    agg[k] += a[k]
                            agg['precision_verifiable'] = agg['correct'] / max(agg['correct'] + agg['wrong'], 1)
                            agg['recall'] = agg['correct'] / max(agg['reference'], 1)
                            row['identity'][name] = agg
                    # E4 signed-residual diagnosis with the anchor's pairs and each front end's pairs
                    methods = dict(reference_pairs={c.name: truth_pairs[c.name] for c in caps}, **assoc) if ctype != 'nuisance' else assoc
                    row['diagnosis'] = {}
                    for name, by_cap in methods.items():
                        rows = stack(caps, cmodel, p_cur, by_cap, scales, sig.max_rows_per_capture, np.random.default_rng(5))
                        res = diagnose(rows, scales, sig)
                        row['diagnosis'][name] = dict(res, score=score(res, truth))
                    # E3 geometry of the retained rows at the anchor (reference pairs)
                    if ctype == 'nominal':
                        rows = stack(caps, amodel, p_anchor, truth_pairs, parameter_scales(p_anchor), sig.max_rows_per_capture, np.random.default_rng(5))
                        if rows is not None:
                            rep_ = signature_report(rows[0] * parameter_scales(p_anchor), np.zeros(13))
                            row['geometry'] = dict(rows=int(len(rows[1])), principal_angles_deg={k: [float(x) for x in v] for k, v in rep_['principal_angles_deg'].items()},
                                                   range_m=[float(x) for x in np.percentile(np.concatenate([truth_pairs[c.name]['range'] for c in caps]), [5, 50, 95])])
                    # E2 parameter recovery of the production optimizer
                    if args.fits and ctype == 'drift' and rep == 0:
                        row['recovery'] = {}
                        loss_of = lambda p: float(np.mean([evaluate_capture(c, cmodel, p, p_cur, cfg.evaluation_cap_px)['loss'] for c in caps]))
                        row['loss_at_anchor'], row['loss_at_current'] = loss_of(p_true), loss_of(p_cur)
                        for h in HYPOTHESES:
                            if h.name == 'KEEP':
                                continue
                            fitted = fit_hypothesis(caps, cmodel, p_cur, h, cfg, 'fault_aware')
                            if fitted['success']:
                                row['recovery'][h.name] = dict(recovery(fitted['parameters'], p_true), loss=loss_of(fitted['parameters']))
                    row['seconds'] = time.perf_counter() - started
                    sink.write(json.dumps(serializable(row)) + '\n'); sink.flush()
                    d = row['diagnosis']
                    print(f"{dataset[:10]} r{rep} {label:30s} " + ' '.join(f"{k[:8]}={v['status'][:9]}/{v.get('hypothesis')}" for k, v in d.items() if k in ('reference_pairs', 'nearest', 'oriented', 'em')), flush=True)
    finally:
        sink.close()
        shutil.rmtree(scratch, ignore_errors=True)


def summarize(path):
    rows = [json.loads(l) for l in Path(path).read_text(encoding='utf-8').splitlines() if l.strip()]
    methods = sorted({m for r in rows for m in r['diagnosis']})
    lines = ['| Pairing front end | Identity: correct / wrong (verifiable) | Alarm no-change | Alarm drift | Exact | Wrong unique | Ambiguous incl. truth |', '|---|---|---|---|---|---|---|']
    for m in methods:
        drift = [r for r in rows if r['condition_type'] == 'drift' and m in r['diagnosis']]
        quiet = [r for r in rows if r['condition_type'] != 'drift' and m in r['diagnosis']]
        ident = [r['identity'][m] for r in rows if 'identity' in r and m in r['identity'] and r['condition_type'] == 'drift']
        c = sum(i['correct'] for i in ident); w = sum(i['wrong'] for i in ident)
        s = lambda rs, k: sum(r['diagnosis'][m]['score'][k] for r in rs)
        rowsn = sum(i['matched'] for i in ident)
        lines.append(f"| {m} | {c} / {w} ({100 * c / max(c + w, 1):.0f} % right; {rowsn} matched rows) | {s(quiet, 'alarm')}/{len(quiet)} | {s(drift, 'alarm')}/{len(drift)} | "
                     f"{s(drift, 'exact')}/{len(drift)} | {s(quiet + drift, 'wrong')} | {s(drift, 'ambiguous_has_truth')} |")
    return '\n'.join(lines)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--datasets', nargs='+', required=True)
    parser.add_argument('--replicates', type=int, default=2)
    parser.add_argument('--em', action='store_true', help='also run the annealed alternating estimator variants')
    parser.add_argument('--fits', action='store_true', help='E2: also run the production optimizer for every hypothesis (slower)')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    run(args)
    text = summarize(Path(args.output) / 'trials.jsonl')
    (Path(args.output) / 'summary.md').write_text(text + '\n', encoding='utf-8')
    print(text)
