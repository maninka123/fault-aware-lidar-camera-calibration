"""Refresh saved plots without refitting or changing a calibration result."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from settings import load_calibration, load_config, load_stacked, log, results_dir

import numpy as np
import calib as cb
import image_edges as ie
import lidar_edges as le
from common import image_circle
import figures
from maintain import params_of


def refresh(out):
    summary = json.loads((out / 'summary.json').read_text())
    code = Path(__file__).resolve().parent
    data = out / 'stacked' / 'data'
    if not data.is_dir():
        data = (code / summary['data']).resolve()
    if (out / 'paired_input.json').exists():
        from paired_data import load_pairs
        frames, _ = load_pairs(data, summary.get('cloud_units', 'm'), summary.get('allow_unusual_units', False))
    else:
        frames = load_stacked(data)
    if not frames:
        log(f'Skipped {out.name}: stacked captures are unavailable')
        return False
    cfg = load_config()
    circle = image_circle(frames)
    previous = load_calibration((code / summary['existing']).resolve())
    refined = load_calibration(out / 'refined_calibration.json')
    model = cb.Model(previous.T[:3, :3], frames[0].image.shape[1::-1], circle)
    caps = []
    for frame in frames:
        edges, _ = le.extract(frame, cfg['lidar'], cfg['seed'])
        caps.append(cb.from_edges(frame.short, edges, ie.extract(frame.image, circle, cfg['image'])))
    existing = params_of(previous, model.R0)
    prior = dict(cx=previous.K[0, 2], cy=previous.K[1, 2])
    old, _ = cb.refine(caps, model, existing, [12], cfg, prior,
                        gates=[4, 3, 2, 2], passes=2, log=lambda *args: None)
    new = params_of(refined, model.R0)
    new[12] = np.radians(summary['beam_widening_deg'])
    figures.make_all(out, frames, caps, model, old, new, existing, summary, cfg)
    log(f'Refreshed plots: {out.name}')
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', help='Saved run name; omit to refresh all available runs')
    args = parser.parse_args()
    folders = [results_dir() / args.run] if args.run else sorted(results_dir().iterdir())
    for folder in folders:
        if (folder / 'summary.json').is_file():
            refresh(folder)


if __name__ == '__main__':
    main()
