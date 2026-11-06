"""Frozen exact-correspondence numerical experiment, not a sensor simulator.

Nonlinear projection supplies observations; analytic derivatives are the model
under test. This intentionally separates correspondence-oracle results from
the much harder recorded nearest-edge matching experiment.
"""
import os
for _name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ[_name] = '1'
import argparse
from pathlib import Path
import sys
import json
import time
import hashlib
import numpy as np
from scipy.spatial.transform import Rotation
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research_calibration.geometry import ProjectionModel, parameters, retract
from research_calibration.parameter_hypotheses import parameter_scales
from research_calibration.fault_diagnostics_v3.geometry_signatures import projection_jacobian
from research_calibration.fault_diagnostics_v3.diagnostic_inference import infer_signatures
from research_calibration.fault_diagnostics_v3.evaluation import score_decision
from research_calibration.fault_diagnostics_v3.config import SignatureConfig
from research_calibration.fault_diagnostics_v3.hypothesis_separation import HYPOTHESIS_COLUMNS
from research_calibration.reporting import serializable

SCENES = ('great_circle', 'narrow_depth_rich', 'wide_depth_poor', 'wide_depth_rich')
CONDITIONS = ('nominal', 'R', 'T', 'I_pp', 'I_focal', 'RT', 'RI', 'TI', 'RTI', 'beam_nuisance')


def geometry(seed, scene):
    rng = np.random.default_rng(seed)
    n = 240
    if scene == 'great_circle':
        theta = rng.uniform(-1.1, 1.1, n)
        rays = np.c_[np.sin(theta), np.zeros(n), np.cos(theta)]
    else:
        angle = .08 if scene == 'narrow_depth_rich' else 1.1
        theta = angle*np.sqrt(rng.uniform(size=n)); az = rng.uniform(-np.pi, np.pi, n)
        rays = np.c_[np.sin(theta)*np.cos(az), np.sin(theta)*np.sin(az), np.cos(theta)]
    ranges = np.full(n, 4.) if scene == 'wide_depth_poor' else rng.uniform(1.5, 12., n)
    return rays*ranges[:, None], rng.choice([-1., 1.], n)


def run(output):
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise FileExistsError('Use a new output directory')
    output.mkdir(parents=True, exist_ok=True)
    cal = dict(image_size=[800, 800], intrinsics=dict(camera_matrix=[[240., 0, 400.], [0, 240., 400.], [0, 0, 1]],
               distortion_coefficients=[0., 0., 0., 0.]), extrinsics=dict(transform_lidar_to_camera=np.eye(4).tolist()))
    model = ProjectionModel(cal, [800, 800], dict(cx=400., cy=400., radius=400.), 1.3)
    p = parameters(cal); scales = parameter_scales(p)
    protocol = dict(scenes=SCENES, conditions=CONDITIONS, seeds=list(range(5)), noise_sigma_px=.15,
                    rotation_deg=1., translation_m=.05, principal_point_px=4., focal_fraction=.02,
                    beam_rad=.01, source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    scope='Oracle correspondences; nonlinear generated observations, local fitted signature model; development verification only.')
    source_root = Path(__file__).resolve().parents[1]
    protocol['configuration'] = SignatureConfig().to_dict()
    protocol['source_sha256_all'] = {str(f.relative_to(source_root)): hashlib.sha256(f.read_bytes()).hexdigest()
        for f in [Path(__file__), *sorted((source_root/'research_calibration').rglob('*.py'))]}
    (output/'protocol.json').write_text(json.dumps(protocol, indent=2)+'\n', encoding='utf-8')
    results = []
    started = time.perf_counter()
    for scene in SCENES:
        for seed in range(5):
            xyz, signs = geometry(seed, scene)
            uv, j, valid = projection_jacobian(model, p, xyz, signs)
            ids = np.repeat(np.arange(4), 60)
            for condition in CONDITIONS:
                d = np.zeros(13)
                groups = None if condition in ('nominal', 'beam_nuisance') else list(condition.split('_')[0])
                if 'R' in (groups or []): d[1] = np.radians(1.)
                if 'T' in (groups or []): d[3] = .05
                if 'I' in (groups or []): d[8] = 4.
                if condition == 'I_focal': d[8] = 0.; d[6:8] = p[6:8]*.02
                if condition == 'beam_nuisance': d[12] = .01
                true = retract(p, d)
                u, v, inside = model.project(model.to_camera(xyz, signs, true), true)
                keep = valid & inside
                y = (np.c_[u, v]-uv)[keep].ravel()
                # Same independent pixel-noise draw across fault conditions.
                y += np.random.default_rng(100+seed).normal(0, .15, len(y))
                result = infer_signatures(j[keep].reshape(-1, 13), y, scales,
                                          covariance=np.full(len(y), .15**2), capture_ids=np.repeat(ids[keep], 2))
                error = None
                if result.get('hypothesis'):
                    free = list((*HYPOTHESIS_COLUMNS[result['hypothesis']], 12))
                    a = j[keep].reshape(-1, 13)*scales
                    estimate = np.zeros(13)
                    estimate[free] = np.linalg.lstsq(a[:, free], y, rcond=1e-7)[0]
                    candidate = retract(p, scales*estimate)
                    error = dict(rotation_deg=float(np.degrees((Rotation.from_rotvec(candidate[:3])*Rotation.from_rotvec(true[:3]).inv()).magnitude())),
                                 translation_m=float(np.linalg.norm(candidate[3:6]-true[3:6])),
                                 focal_px=(candidate[6:8]-true[6:8]).tolist(), principal_point_px=(candidate[8:10]-true[8:10]).tolist(),
                                 distortion=(candidate[10:12]-true[10:12]).tolist(), scope='Conditional exact-correspondence fitted minimal model; not an accepted hardware update.')
                results.append(dict(scene=scene, seed=seed, condition=condition, truth=groups,
                                    decision={k: result.get(k) for k in ('status', 'hypothesis', 'ambiguity_set', 'validation_scope')},
                                    score=score_decision(result, groups), synthetic_parameter_error=error))
    summary = {}
    for scene in SCENES:
        rows = [r for r in results if r['scene'] == scene]
        drift = [r for r in rows if r['truth'] is not None]; nominal = [r for r in rows if r['truth'] is None]
        summary[scene] = dict(drift_n=len(drift), detections=sum(r['score']['alarm'] for r in drift),
                             exact=sum(r['score']['exact'] for r in drift), wrong=sum(r['score']['wrong'] for r in rows),
                             no_change_n=len(nominal), false_alarms=sum(r['score']['alarm'] for r in nominal),
                             ambiguous_truth=sum(r['score']['ambiguous_contains_truth'] for r in drift))
    payload = dict(protocol=protocol, summary=summary, seconds=time.perf_counter()-started, trials=results)
    payload['source_unchanged'] = all(hashlib.sha256((source_root/f).read_bytes()).hexdigest() == digest
                                    for f, digest in protocol['source_sha256_all'].items())
    (output/'results.json').write_text(json.dumps(serializable(payload), indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print(json.dumps(dict(summary=summary, seconds=payload['seconds']), indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    run(parser.parse_args().output)
