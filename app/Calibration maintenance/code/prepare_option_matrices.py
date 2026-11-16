"""Add measured option previews to an older run without changing its calibration or verdict."""
import argparse
import copy
import json

from settings import load_calibration, load_config, load_stacked, log, results_dir, write_json
import numpy as np
import calib as cb
import image_edges as ie
import lidar_edges as le
from common import image_circle
from maintenance_model import Model
from maintain import alignment, params_of
from update_options import MODES, candidate_calibration, fit_candidates, projection_movement


def prepare(name):
    out = results_dir() / name
    summary = json.loads((out / 'summary.json').read_text())
    cal = load_calibration(summary['existing'])
    cfg = load_config()
    frames = load_stacked(out / 'stacked' / 'data')
    if not frames:
        frames = load_stacked(summary['data'])
    if not frames:
        raise ValueError('No cached stacked captures; run Compare update options again.')
    circle = image_circle(frames)
    rng = np.random.default_rng(cfg['seed'])
    caps = []
    reflectivity = all(np.ptp(frame.intensity) > 0 for frame in frames)
    for frame in frames:
        edges, _ = le.extract(frame, cfg['lidar'], cfg['seed'])
        cap = cb.from_edges(frame.short, edges, ie.extract(frame.image, circle, cfg['image']))
        if reflectivity:
            cb.prepare_nid(cap, frame, cfg['calib']['nid']['points_per_capture'], cfg['calib']['nid']['bins'], rng)
        caps.append(cap)
        log(f'Loaded features: {frame.short}')
    model = Model(cal.T[:3, :3], frames[0].image.shape[1::-1], circle, cal.D)
    existing = params_of(cal, model.R0)
    refine_cfg = copy.deepcopy(cfg)
    refine_cfg['calib']['gates_px'] = cfg['refine']['gates_px']
    refine_cfg['prior']['principal_point_sigma_px'] = cfg['refine']['principal_point_sigma_px']
    prior = dict(cx=cal.K[0, 2], cy=cal.K[1, 2])
    old, _ = cb.refine(caps, model, existing, [12], refine_cfg, prior,
                       log=lambda *args: None, gates=[4, 3, 2, 2], passes=2)
    starts = [('existing calibration', old)]
    coarse = dict(cfg['calib']['coarse'], per_focal=cfg['refine']['search_starts'])
    for proposer, _, p in cb.coarse(caps, model, old, coarse, rng, lambda *args: None, fixed_intrinsics=True):
        p = p.copy()
        p[7], p[12] = old[7], old[12]
        starts.append((proposer, p))
    points = np.concatenate([frame.xyz[::15] for frame in frames])
    ranges = np.linalg.norm(points, axis=1)
    lo, hi = cfg['decision']['probe_range_m']
    points = points[(ranges >= lo) & (ranges <= hi)]
    calibrations = dict(existing=cal.raw)
    movements = dict(existing=projection_movement(model, existing, existing, points))
    for mode in MODES:
        log(f'Preparing {mode} matrices')
        if mode == summary['mode']:
            fitted = load_calibration(out / 'refined_calibration.json')
            calibrations[mode] = fitted.raw
            p = params_of(fitted, model.R0)
        else:
            choices = fit_candidates(caps, model, starts, existing, mode, cal.model,
                                      cfg, refine_cfg, prior, alignment)
            if not choices:
                log(f'No valid {mode} candidate')
                continue
            p = max(choices, key=lambda value: value['lift'])['p']
            calibrations[mode] = candidate_calibration(cal.raw, model, p, mode)
        movements[mode] = projection_movement(model, existing, p, points)
    temporary = out / 'option_calibrations.tmp.json'
    write_json(temporary, dict(calibrations=calibrations, movements=movements))
    temporary.replace(out / 'option_calibrations.json')
    log('Saved option matrices and movements; original calibration and verdict kept.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True)
    prepare(parser.parse_args().run)
