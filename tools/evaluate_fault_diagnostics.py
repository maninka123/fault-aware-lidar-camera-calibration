"""Semi-synthetic comparison of the production backend and the experimental fault diagnostics.

Every trial runs the production assessment once (with the read-only fold observer) and scores both the
production verdict and the experimental verdicts (proposed method and its ablations) from the SAME fitted
folds, so data partitions and fitting budgets are identical by construction.

Truth is known only relative to a per-recording *anchor*: the recording's reference calibration refined
(R, T, I jointly, training on all captures of that recording) by the production engine. Conditions:

  nominal                the anchor itself: correct answer "no change"
  drift:<kind>:<size>    the anchor composed with a known change: correct answer is that change's group
  nuisance:<name>        the anchor with degraded captures: correct answer "no change"
  reference              the recording's original (board) reference, unlabelled: reported, not scored

Replicates r = 0..R-1 drop two captures chosen at random (seeded) and draw a perturbation direction, so each
replicate is a paired comparison across conditions and methods.

Usage (from the repository root):
  python -B tools/evaluate_fault_diagnostics.py --datasets october_device_one enclosure_off_ten --role development --output research_artifacts/fault_diagnostics_v2/development
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import os
for _k in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS'):
    os.environ[_k] = '1'
import argparse
import copy
import json
import shutil
import tempfile
import time
import zlib
from types import SimpleNamespace
import numpy as np
import cv2
cv2.setNumThreads(1)
from scipy.spatial.transform import Rotation
from research_calibration.benchmark import dataset_paths, environment
from research_calibration.config import ResearchConfig
from research_calibration.calibration_pipeline import fit_hypothesis
from research_calibration.geometry import ProjectionModel, parameters, calibration_from_parameters
from research_calibration.legacy_adapter import load_capture_bundle, read_calibration, REPOSITORY
from research_calibration.parameter_hypotheses import HYPOTHESES
from research_calibration.reporting import serializable
from research_calibration.fault_diagnostics import DiagnosticsConfig
from research_calibration.fault_diagnostics.policy import ALARM
from research_calibration.fault_diagnostics.runner import assess_with_diagnostics
from research_calibration.fault_diagnostics import perturbations as P

GROUPS = {h.name: tuple(h.groups) for h in HYPOTHESES}
DRIFTS = (('R', .5), ('R', 1.), ('T', .03), ('T', .06), ('I_pp', 3.), ('I_focal', .02), ('RT', (.5, .03)))
NUISANCES = P.NUISANCES
# Development only: the reference of enclosure_off_ten is ~18 px from the scene (outside the local fit), so its
# anchor starts from the maintenance refinement of the same captures. Held-out recordings always start from
# their own reference.
ANCHOR_START = {'enclosure_off_ten': 'Calibration maintenance/results/rig_20261104_174529/refined_calibration.json'}


def params_in(cal, model):
    """Parameters of calibration `cal` expressed in `model`'s rotation chart."""
    p = parameters(cal)
    T = np.asarray(cal['extrinsics']['transform_lidar_to_camera'], float)
    p[:3] = Rotation.from_matrix(T[:3, :3] @ model.R0.T).as_rotvec()
    return p


def pixel_error(caps, model, p, p_true):
    errors = []
    for c in caps:
        u0, v0, ok0 = model.project(model.to_camera(c.xyz, c.sgn, p_true), p_true)
        u1, v1, ok1 = model.project(model.to_camera(c.xyz, c.sgn, p), p)
        ok = ok0 & ok1
        if np.any(ok):
            errors.append(np.hypot(u1[ok]-u0[ok], v1[ok]-v0[ok]))
    return float(np.median(np.concatenate(errors))) if errors else None


def anchor_calibration(dataset, reference_path, bundle, cfg):
    root = (REPOSITORY/json.loads((REPOSITORY/'research_data/manifest.json').read_text(encoding='utf-8'))
            ['workspace_root_relative_to_repository']).resolve()
    start_path = root/ANCHOR_START[dataset] if dataset in ANCHOR_START else reference_path
    start = read_calibration(start_path)
    reference = read_calibration(reference_path)
    for key in ('model', 'camera_model'):
        if key in reference.get('intrinsics', {}) and key not in start.get('intrinsics', {}):
            start['intrinsics'][key] = reference['intrinsics'][key]
    model = ProjectionModel(start, bundle.size, bundle.circle, cfg.max_angle_rad)
    p = parameters(start)
    rti = next(h for h in HYPOTHESES if h.name == 'RTI')
    fitted = fit_hypothesis(bundle.caps, model, p, rti, ResearchConfig(**{**cfg.to_dict(), 'iterations': 4}), 'fault_aware')
    anchor = calibration_from_parameters(start, model, fitted['parameters'] if fitted['success'] else p)
    anchor.pop('method', None)
    anchor['anchor_provenance'] = dict(start=str(start_path), fit_success=bool(fitted['success']),
        note='Refined on all captures of this recording: a data-consistent nominal, not physical truth.')
    return anchor


def subset_bundle(bundle, keep):
    return SimpleNamespace(**{**vars(bundle), 'caps': [bundle.caps[i] for i in keep],
                              'metadata': [bundle.metadata[i] for i in keep]})


def score(row):
    truth = row['truth_groups']
    change = truth is not None
    out = {}
    prod = row['production']
    alarm = prod['decision_status'] == 'CANDIDATE_SUPPORTED'
    groups = tuple(GROUPS.get(prod['candidate'] or 'KEEP', ())) if alarm else None
    out['production'] = dict(status=prod['status'], alarm=alarm, update=prod['status'] == 'UPDATE_SUPPORTED',
        attributed=groups, correct_attribution=bool(change and alarm and set(groups) == set(truth)),
        wrong_attribution=bool(alarm and (not change or set(groups) != set(truth))))
    for name, d in row['experimental'].items():
        alarm = d['status'] in ALARM
        g = tuple(GROUPS[d['hypothesis']]) if d['status'] == 'DRIFT_SUPPORTED' and d.get('hypothesis') else None
        amb = [tuple(GROUPS[h]) for h in d.get('ambiguity_set') or []]
        out[name] = dict(status=d['status'], alarm=alarm, update=bool(d.get('update_recommended')), attributed=g,
            correct_attribution=bool(change and g is not None and set(g) == set(truth)),
            wrong_attribution=bool(g is not None and (not change or set(g) != set(truth))),
            ambiguous_contains_truth=bool(change and d['status'] == 'DRIFT_AMBIGUOUS' and any(set(a) == set(truth) for a in amb)))
    return out


def run(args):
    cfg = ResearchConfig(); diag = DiagnosticsConfig()
    manifest = json.loads((REPOSITORY/'research_data/manifest.json').read_text(encoding='utf-8'))
    roles = {d['id']: d.get('evaluation_role') for d in manifest['datasets']}
    wanted = 'held_out_v2' if args.role == 'held_out' else 'development_v2'
    if any(roles.get(d) != wanted for d in args.datasets):
        raise SystemExit('Every dataset must have evaluation_role ' + wanted + ' in the manifest')
    if args.role == 'held_out' and not (REPOSITORY/'docs/research/PREREGISTRATION_V2.md').exists():
        raise SystemExit('Held-out evaluation requires the committed preregistration document')
    output = Path(args.output)
    if output.exists() and any(output.iterdir()):
        raise FileExistsError('Use a new output directory')
    output.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix='fdv2_', dir=os.environ.get('LOCALAPPDATA', None)))
    (output/'protocol.json').write_text(json.dumps(serializable(dict(role=args.role, datasets=args.datasets,
        replicates=args.replicates, drifts=DRIFTS, nuisances=NUISANCES, research=cfg.to_dict(), diagnostics=diag.to_dict(),
        anchor_start=ANCHOR_START, environment=environment())), indent=2) + '\n', encoding='utf-8')
    results = (output/'trials.jsonl').open('a', encoding='utf-8')
    try:
        for dataset in args.datasets:
            reference_path, data = dataset_paths(dataset)
            full = load_capture_bundle(data, scratch/dataset/'inputs', cfg.max_features_per_capture, cfg.seed,
                                       intensity_points=diag.intensity_points, intensity_bins=diag.intensity_bins)
            anchor = anchor_calibration(dataset, reference_path, full, cfg)
            (output/(dataset + '_anchor.json')).write_text(json.dumps(serializable(anchor), indent=2) + '\n', encoding='utf-8')
            amodel = ProjectionModel(anchor, full.size, full.circle, cfg.max_angle_rad)
            p_anchor = parameters(anchor)
            for rep in range(args.replicates):
                rng = np.random.default_rng(1000*rep + 17)
                n = len(full.caps)
                keep = sorted(rng.choice(n, n - 2, replace=False).tolist()) if n > 6 else list(range(n))
                base = subset_bundle(full, keep)
                conditions = ([('nominal', None, None)] + [('drift', k, m) for k, m in DRIFTS] + [('nuisance', x, None) for x in NUISANCES]
                              + [('drift_nuisance', 'spurious_lines_all', None)])
                if rep == 0:
                    conditions.append(('reference', None, None))
                for ctype, kind, magnitude in conditions:
                    if args.only and ctype not in args.only:
                        continue
                    crng = np.random.default_rng([rep, zlib.crc32(f'{ctype}|{kind}|{magnitude}'.encode())])
                    bundle = base; truth = None; delta = np.zeros(13)
                    if ctype == 'reference':
                        cal = read_calibration(reference_path)
                    else:
                        cal = copy.deepcopy(anchor)
                    if ctype == 'drift':
                        delta, truth = P.calibration_change(p_anchor, kind, magnitude, crng)
                        cal = P.perturbed_calibration(anchor, amodel, p_anchor, delta)
                    if ctype == 'drift_nuisance':
                        delta, truth = P.calibration_change(p_anchor, 'R', 1., crng)
                        cal = P.perturbed_calibration(anchor, amodel, p_anchor, delta)
                    if ctype in ('nuisance', 'drift_nuisance'):
                        bundle = subset_bundle(base, range(len(base.caps)))
                        # Single-capture corruptions hit a comparison (non-outer) capture, using the engine's own rule.
                        m = len(base.caps)
                        outer_n = max(2, int(np.ceil(m*cfg.outer_fraction))) if m >= cfg.min_capture_blocks + 3 else 0
                        outer_idx = set(np.random.default_rng(cfg.seed).permutation(m)[:outer_n].tolist())
                        inner = [i for i in range(m) if i not in outer_idx]
                        bundle.caps = P.apply_nuisance(base.caps, base.circle, kind, crng, index=int(crng.choice(inner)))
                    label = f'{ctype}:{kind}:{magnitude}' if ctype == 'drift' else f'{ctype}:{kind}' if kind else ctype
                    folder = scratch/'t'/f'{dataset[:8]}_{rep}_{len(os.listdir(scratch/"t")) if (scratch/"t").exists() else 0}'
                    started = time.perf_counter()
                    try:
                        payload, result = assess_with_diagnostics(cal, data, output=folder, config=cfg, diagnostics=diag, bundle=bundle)
                    except Exception as error:   # recorded, never hidden
                        row = dict(dataset=dataset, replicate=rep, condition=label, error=repr(error))
                        results.write(json.dumps(row) + '\n'); results.flush(); print('ERROR', label, repr(error), flush=True)
                        continue
                    cmodel = ProjectionModel(cal, bundle.size, bundle.circle, cfg.max_angle_rad)
                    p_true = params_in(anchor, cmodel)
                    final = result.diagnostics.get('candidate_calibration')
                    row = dict(dataset=dataset, replicate=rep, condition=label, condition_type=ctype,
                               truth_groups=list(truth) if truth else None, delta=delta.tolist(), captures=[c.name for c in bundle.caps],
                               production=payload['production'], experimental={k: {kk: v.get(kk) for kk in (
                                   'status', 'hypothesis', 'ambiguity_set', 'update_recommended', 'supported', 'reason')}
                                   for k, v in payload['experimental'].items()},
                               reference_confirmation=payload['experimental']['proposed'].get('reference_confirmation'),
                               counterfactuals=payload['experimental']['proposed'].get('counterfactuals'),
                               # Full per-capture evidence, so every verdict can be recomputed from the saved trial.
                               evidence={k: payload['evidence'][k] for k in ('tests', 'reference', 'folds', 'informative')},
                               production_decision=dict(status=payload['production']['decision_status'],
                                                        best_relative_gain=payload['production']['best_relative_gain']),
                               outer=payload['outer'],
                               current_pixel_error_vs_anchor=pixel_error(bundle.caps, cmodel, parameters(cal), p_true),
                               candidate_pixel_error_vs_anchor=(pixel_error(bundle.caps, cmodel, params_in(final, cmodel), p_true)
                                                                if final else None),
                               cost=payload['cost'], seconds=time.perf_counter() - started)
                    if ctype != 'reference':
                        row['score'] = score(row)
                    results.write(json.dumps(serializable(row)) + '\n'); results.flush()
                    s = row.get('score', {})
                    print(f"{dataset} r{rep} {label:28s} prod={payload['production']['decision_status']:22s}/{payload['production']['candidate']}"
                          f" prop={payload['experimental']['proposed']['status']}/{payload['experimental']['proposed'].get('hypothesis')}"
                          f" err {row['current_pixel_error_vs_anchor'] if row['current_pixel_error_vs_anchor'] is None else round(row['current_pixel_error_vs_anchor'],2)}"
                          f" {row['seconds']:.1f}s", flush=True)
                    shutil.rmtree(folder, ignore_errors=True)
    finally:
        results.close()
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--datasets', nargs='+', required=True)
    parser.add_argument('--role', choices=('development', 'held_out'), required=True)
    parser.add_argument('--replicates', type=int, default=3)
    parser.add_argument('--only', nargs='*', help='Restrict to condition types (nominal drift nuisance reference)')
    parser.add_argument('--output', required=True)
    run(parser.parse_args())
