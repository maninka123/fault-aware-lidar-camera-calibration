"""Failure-mode probe: how each held-out measure responds to known calibration offsets (no fitting).

For a recording and its reference calibration, every capture is scored at the reference composed with fixed
offsets (rotation about each axis, translation along each axis, principal point, focal length). Reported per
offset, averaged over captures:

  production_change   relative change of the production capped nearest-edge loss (negative = "better")
  chance_change       the same change predicted by the decoy-displaced edges alone (edge-density effect)
  edge_contrast       change of the decoy-referenced oriented-edge contrast (negative = worse alignment)
  intensity_contrast  change of the decoy-referenced NID contrast

A measure that keeps improving as the calibration is moved away from the reference in one direction, while
the chance-predicted change follows it, is rewarding edge density rather than alignment.

  python -B tools/probe_loss_bias.py --dataset creep_three --output research_artifacts/fault_diagnostics_v2/probe_creep_three.json
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import os
for _k in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS'):
    os.environ[_k] = '1'
import argparse
import json
import tempfile
import numpy as np
import cv2
cv2.setNumThreads(1)
from research_calibration.benchmark import dataset_paths
from research_calibration.config import ResearchConfig
from research_calibration.geometry import ProjectionModel, parameters, retract
from research_calibration.legacy_adapter import load_capture_bundle, read_calibration
from research_calibration.residuals import evaluate_capture
from research_calibration.fault_diagnostics import DiagnosticsConfig
from research_calibration.fault_diagnostics.cues import CaptureCues
from research_calibration.fault_diagnostics.evidence import ProductionDecoy

OFFSETS = [('rx_deg', a) for a in (-1, -.5, .5, 1)] + [('ry_deg', a) for a in (-1, -.5, .5, 1)] + \
          [('rz_deg', a) for a in (-1, 1)] + [('tx_m', a) for a in (-.05, -.02, .02, .05)] + \
          [('ty_m', a) for a in (-.05, -.02, .02, .05)] + [('tz_m', a) for a in (-.05, .05)] + \
          [('cx_px', a) for a in (-4, -2, 2, 4)] + [('cy_px', a) for a in (-4, -2, 2, 4)] + [('f_rel', a) for a in (-.02, .02)]


def offset(p0, kind, a):
    d = np.zeros(13)
    if kind[0] == 'r':
        d['xyz'.index(kind[1])] = np.radians(a)
    elif kind[0] == 't':
        d[3 + 'xyz'.index(kind[1])] = a
    elif kind == 'cx_px':
        d[8] = a
    elif kind == 'cy_px':
        d[9] = a
    elif kind == 'f_rel':
        d[6], d[7] = p0[6]*a, p0[7]*a
    return retract(p0, d)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dataset', required=True); parser.add_argument('--output', required=True)
    args = parser.parse_args()
    cfg, diag = ResearchConfig(), DiagnosticsConfig()
    ref, data = dataset_paths(args.dataset)
    with tempfile.TemporaryDirectory() as scratch:
        b = load_capture_bundle(data, Path(scratch), cfg.max_features_per_capture, cfg.seed,
                                intensity_points=diag.intensity_points, intensity_bins=diag.intensity_bins)
    cal = read_calibration(ref)
    model = ProjectionModel(cal, b.size, b.circle, cfg.max_angle_rad); p0 = parameters(cal)
    cues = [CaptureCues(c, model, p0, diag) for c in b.caps]
    decoys = [ProductionDecoy(c, model, p0, diag, cfg.evaluation_cap_px) for c in b.caps]

    def measures(p):
        L = np.array([evaluate_capture(c, model, p, p0, cfg.evaluation_cap_px)['loss'] for c in b.caps])
        D = np.array([d.loss(p) for d in decoys])
        E = np.array([c.edge(p).contrast for c in cues]); I = np.array([c.intensity(p).contrast for c in cues])
        return L, D, E, I
    L0, D0, E0, I0 = measures(p0)
    rows = []
    for kind, a in OFFSETS:
        L, D, E, I = measures(offset(p0, kind, a))
        rows.append(dict(offset=kind, amount=a,
                         production_change=float(np.mean((L - L0)/L0)), production_better_share=float(np.mean(L < L0)),
                         chance_change=float(np.mean((D - D0)/L0)),
                         edge_contrast_change=float(np.nanmean(E - E0)), intensity_contrast_change=float(np.nanmean(I - I0))))
    out = dict(dataset=args.dataset, captures=len(b.caps), reference=str(ref),
               reference_measures=dict(production_loss=L0.tolist(), decoy_loss=D0.tolist(), edge_contrast=E0.tolist(),
                                       intensity_contrast=I0.tolist()), offsets=rows,
               note='Known offsets of the recorded reference; no fitting, no fault labels.')
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(out, indent=1) + '\n', encoding='utf-8')
    print(f"{'offset':>8} {'amount':>6} {'prod %':>8} {'chance %':>9} {'edge':>7} {'NID x1e3':>9}")
    for r in rows:
        print(f"{r['offset']:>8} {r['amount']:>6} {100*r['production_change']:8.2f} {100*r['chance_change']:9.2f} "
              f"{r['edge_contrast_change']:7.3f} {1000*r['intensity_contrast_change']:9.2f}")


if __name__ == '__main__':
    main()
