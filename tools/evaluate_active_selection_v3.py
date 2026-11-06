"""Frozen exact-correspondence capture-design experiment; not a sensor simulator.

Every method receives identical initial measurements. Active effects are fitted
from those measurements, never from the injected label or candidate residuals.
The existing selector's score routine evaluates baseline greedy subsets including
the same initial rows. A fresh output directory freezes protocol/source hashes
before any trial; results cannot overwrite an earlier run.
"""
import os
for _name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ[_name] = '1'
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evaluate_signature_geometry_v3 import geometry
from research_calibration.geometry import ProjectionModel, parameters, retract
from research_calibration.parameter_hypotheses import GROUPS, parameter_scales
from research_calibration.evidence_selection import select_captures
from research_calibration.fault_diagnostics_v3.active_selection import select_observations
from research_calibration.fault_diagnostics_v3.geometry_signatures import projection_jacobian
from research_calibration.fault_diagnostics_v3.hypothesis_separation import HYPOTHESIS_COLUMNS
from research_calibration.fault_diagnostics_v3.diagnostic_inference import infer_signatures
from research_calibration.fault_diagnostics_v3.evaluation import score_decision
from research_calibration.fault_diagnostics_v3.config import SignatureConfig
from research_calibration.reporting import serializable

SEEDS = (0, 1, 2)
BUDGETS = (1, 2, 3)
CONDITIONS = ('nominal', 'R', 'I_pp')
METHODS = ('finite_effect', 'random', 'feature_count', 'd_optimal', 'e_optimal', 'contrast')
CANDIDATES = (('great_circle', 480), ('great_circle', 240), ('narrow_depth_rich', 240),
              ('wide_depth_poor', 120), ('wide_depth_rich', 120), ('wide_depth_rich', 240))
SIGMA = .15


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(output):
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise FileExistsError('Use a new output directory; protocol/results are immutable.')
    output.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[1]
    sources = [Path(__file__), root/'tools/evaluate_signature_geometry_v3.py',
               *sorted((root/'research_calibration/fault_diagnostics_v3').glob('*.py')),
               root/'research_calibration/evidence_selection.py']
    protocol = dict(seeds=SEEDS, budgets=BUDGETS, conditions=CONDITIONS, methods=METHODS,
                    candidates=CANDIDATES, initial=dict(scene='great_circle', points=120),
                    independent_validation=dict(scene='wide_depth_rich', points=240),
                    noise_sigma_px=SIGMA, rotation_y_deg=1., principal_point_x_px=4.,
                    thresholds='SignatureConfig defaults except min_captures=2 for explicitly numerical two-capture LOCO; detection/separation tolerances unchanged.',
                    inference_config=SignatureConfig(min_captures=2).to_dict(),
                    source_sha256={str(p.relative_to(root)): digest(p) for p in sources},
                    active_effects='R and I fitted only to noisy initial signed 2D observations; common beam nuisance.',
                    baselines='Existing select_captures all-subset scores, greedy initial+chosen+candidate. Random seeded; count excludes initial constant.',
                    all_comparator='All six candidate captures; unmatched upper-budget reference, never a matched-budget win.',
                    scope='Numerical nonlinear projection with exact correspondences and independent pixel noise; development verification only.')
    (output/'protocol.json').write_text(json.dumps(protocol, indent=2)+'\n', encoding='utf-8')
    started = time.perf_counter()
    cal = dict(image_size=[800, 800], intrinsics=dict(camera_matrix=[[240., 0, 400.], [0, 240., 400.], [0, 0, 1]],
               distortion_coefficients=[0., 0., 0., 0.]), extrinsics=dict(transform_lidar_to_camera=np.eye(4).tolist()))
    model = ProjectionModel(cal, [800, 800], dict(cx=400., cy=400., radius=400.), 1.3)
    p = parameters(cal); scales = parameter_scales(p)
    rows = []
    for seed in SEEDS:
        preprocessing = time.perf_counter()
        def make(scene, count, salt):
            parts = [geometry(salt+seed*100+k, scene) for k in range((count+239)//240)]
            xyz = np.vstack([v[0] for v in parts])[:count]
            signs = np.concatenate([v[1] for v in parts])[:count]
            uv, derivative, valid = projection_jacobian(model, p, xyz, signs)
            if not valid.all():
                raise AssertionError('Protocol requires common valid support')
            j = derivative.reshape(-1, 13)
            return dict(xyz=xyz, signs=signs, uv=uv, j=j, a=j*scales/SIGMA, salt=salt)
        initial = make('great_circle', 120, 1000)
        pool = [make(scene, count, 2000+1000*i) for i, (scene, count) in enumerate(CANDIDATES)]
        reserve = make('wide_depth_rich', 240, 20000)
        preprocessing = time.perf_counter()-preprocessing
        matrices = [c['a'] for c in pool]
        for condition in CONDITIONS:
            delta = np.zeros(13)
            if condition == 'R': delta[1] = np.radians(1.)
            if condition == 'I_pp': delta[8] = 4.
            truth = None if condition == 'nominal' else [condition.split('_')[0]]
            true = retract(p, delta)
            def measure(capture):
                u, v, visible = model.project(model.to_camera(capture['xyz'], capture['signs'], true), true)
                if not visible.all():
                    raise AssertionError('Changing visibility violates frozen experiment support')
                noise = np.random.default_rng(capture['salt']+seed+51).normal(0, SIGMA, capture['uv'].shape)
                return (np.c_[u, v]-capture['uv']+noise).ravel()
            y0 = measure(initial)
            effects = {}
            effect_started = time.perf_counter()
            for hypothesis in ('R', 'I'):
                free = list((*HYPOTHESIS_COLUMNS[hypothesis], 12))
                effect = np.zeros(13)
                effect[free] = np.linalg.lstsq(initial['a'][:, free], y0/SIGMA, rcond=1e-7)[0]
                effects[hypothesis] = effect
            effect_seconds = time.perf_counter()-effect_started
            for budget in (*BUDGETS, len(pool)):
                methods = METHODS if budget in BUDGETS else ('all',)
                for method in methods:
                    select_started = time.perf_counter()
                    if method == 'finite_effect':
                        choice = select_observations(matrices, effects, [('R', 'I')], budget=budget, initial=initial['a'])
                        selected = choice['selected_indices']
                    elif method == 'all':
                        selected = list(range(len(pool)))
                    elif method == 'random':
                        selected = np.random.default_rng(30000+seed).permutation(len(pool))[:budget].tolist()
                    elif method == 'feature_count':
                        selected = sorted(range(len(pool)), key=lambda i: (-len(matrices[i]), i))[:budget]
                    else:
                        selected = []
                        for _ in range(budget):
                            options = []
                            for i in range(len(pool)):
                                if i in selected: continue
                                subset = [initial['a'], *[matrices[k] for k in (*selected, i)]]
                                s = select_captures(subset, np.ones(13), GROUPS, strategy='all')['scores']
                                key = (s['contrast'], s['d_optimal'], s['e_optimal']) if method == 'contrast' else (s[method],)
                                options.append((key, i))
                            selected.append(max(options, key=lambda item: item[0])[1])
                    selection_seconds = time.perf_counter()-select_started
                    # Candidate measurements become available only after selection.
                    chosen = [initial, *[pool[i] for i in selected]]
                    j = np.vstack([c['j'] for c in chosen])
                    y = np.concatenate([y0, *[measure(pool[i]) for i in selected]])
                    ids = np.concatenate([np.full(len(c['j']), i) for i, c in enumerate(chosen)])
                    fit_started = time.perf_counter()
                    result = infer_signatures(j, y, scales, covariance=np.full(len(y), SIGMA**2), capture_ids=ids,
                                              config=SignatureConfig(min_captures=2))
                    best = min(result['fold_mse'], key=lambda h: (np.mean(result['fold_mse'][h]), len(HYPOTHESIS_COLUMNS[h])))
                    free = list((*HYPOTHESIS_COLUMNS[best], 12))
                    beta = np.linalg.lstsq((j*scales)[:, free], y, rcond=1e-7)[0]
                    predicted = (reserve['j']*scales)[:, free]@beta
                    validation = measure(reserve)
                    rmse = float(np.sqrt(np.mean((validation-predicted)**2)))
                    null_rmse = float(np.sqrt(np.mean(validation**2)))
                    fit_seconds = time.perf_counter()-fit_started
                    rows.append(dict(seed=seed, condition=condition, truth=truth, method=method, budget=budget,
                                     initial_captures=1, total_captures=1+len(selected), selected=selected,
                                     selected_scenes=[CANDIDATES[i][0] for i in selected], measurement_rows=len(y),
                                     status=result['status'], hypothesis=result['hypothesis'], ambiguity_set=result['ambiguity_set'],
                                     score=score_decision(result, truth), validation_rmse_px=rmse,
                                     validation_null_rmse_px=null_rmse, best_cv_hypothesis=best,
                                     preprocessing_seconds=preprocessing, effect_fit_seconds=effect_seconds,
                                     selection_seconds=selection_seconds, diagnosis_validation_seconds=fit_seconds))
    summary = []
    for budget in (*BUDGETS, len(pool)):
        for method in (METHODS if budget in BUDGETS else ('all',)):
            group = [r for r in rows if r['budget'] == budget and r['method'] == method]
            drift = [r for r in group if r['truth'] is not None]
            nominal = [r for r in group if r['truth'] is None]
            attributed = [r for r in drift if r['score']['attributed'] is not None]
            summary.append(dict(budget=budget, method=method, drift_n=len(drift), nominal_n=len(nominal),
                                detections=sum(r['score']['alarm'] for r in drift), exact=sum(r['score']['exact'] for r in drift),
                                wrong=sum(r['score']['wrong'] for r in group),
                                ambiguous_truth=sum(r['score']['ambiguous_contains_truth'] for r in drift),
                                false_alarms=sum(r['score']['alarm'] for r in nominal),
                                coverage=len(attributed)/len(drift),
                                selective_accuracy=sum(r['score']['exact'] for r in attributed)/len(attributed) if attributed else None,
                                median_validation_rmse_px=float(np.median([r['validation_rmse_px'] for r in group])),
                                median_selection_ms=1000*float(np.median([r['selection_seconds'] for r in group])),
                                median_diagnosis_validation_ms=1000*float(np.median([r['diagnosis_validation_seconds'] for r in group]))))
    payload = dict(protocol=protocol, source_unchanged=all(digest(root/name) == h for name, h in protocol['source_sha256'].items()),
                   seconds=time.perf_counter()-started, summary=summary, trials=rows)
    (output/'results.json').write_text(json.dumps(serializable(payload), indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print(json.dumps(dict(summary=summary, source_unchanged=payload['source_unchanged'], seconds=payload['seconds']), indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    run(parser.parse_args().output)
