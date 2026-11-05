"""Measure held-out all-edge RMSE for a saved run; preserve its calibration and verdict."""
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
from update_options import compare, rmse_changes


def prepare(name):
    out = results_dir() / name
    summary = json.loads((out / 'summary.json').read_text())
    cal = load_calibration(summary['existing'])
    cfg = load_config()
    frames = load_stacked(out / 'stacked' / 'data') or load_stacked(summary['data'])
    if not frames:
        raise ValueError('No cached stacked captures. Run Compare update options again.')
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
    model = Model(cal.T[:3, :3], frames[0].image.shape[1::-1], circle, cal.D)
    refine_cfg = copy.deepcopy(cfg)
    refine_cfg['calib']['gates_px'] = cfg['refine']['gates_px']
    refine_cfg['prior']['principal_point_sigma_px'] = cfg['refine']['principal_point_sigma_px']
    result = compare(caps, model, params_of(cal, model.R0), cal.model, cfg, refine_cfg,
                     dict(cx=cal.K[0, 2], cy=cal.K[1, 2]), alignment, log)
    temporary = out / 'option_errors.tmp.json'
    write_json(temporary, dict(checks=result['checks'], method=result['method'], configuration=cfg,
                               definition='Nearest-image-edge RMSE over common held-out visible LiDAR edges; no match gate'))
    temporary.replace(out / 'option_errors.json')
    log('Saved held-out RMSE; original calibration, verdict and match scores kept.')
    for mode, value in rmse_changes(result).items():
        log(f'{mode}: {value["after_px"]:.3f} px RMSE')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True)
    prepare(parser.parse_args().run)
