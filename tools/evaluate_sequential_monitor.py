"""Persistence monitor on time-ordered recorded captures: persistent change vs one corrupted capture.

Streams use the captures of one recording in capture-time order with the recording's anchor calibration
(see evaluate_fault_diagnostics.py). A persistent change from index tau is represented exactly by scoring
captures i >= tau at the anchor composed with a known change (data recorded under a changed calibration and
projected with the old one are equivalent to the old data projected with the changed one). A temporary
corruption alters one capture's image only. Monitored statistics per capture:

  edge contrast, intensity contrast (proposed, decoy-referenced)  vs  production nearest-edge loss (comparator)

The same robust CUSUM (declared constants) is applied to each; the conformal test martingale is reported for
the contrasts. Streams are short (10-15 captures); results are descriptive.
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
import tempfile
import shutil
import numpy as np
import cv2
cv2.setNumThreads(1)
from research_calibration.benchmark import dataset_paths
from research_calibration.config import ResearchConfig
from research_calibration.geometry import ProjectionModel, parameters
from research_calibration.legacy_adapter import load_capture_bundle, REPOSITORY
from research_calibration.residuals import evaluate_capture
from research_calibration.reporting import serializable
from research_calibration.fault_diagnostics import DiagnosticsConfig
from research_calibration.fault_diagnostics.cues import CaptureCues
from research_calibration.fault_diagnostics import perturbations as P
from research_calibration.fault_diagnostics import sequential as S
from evaluate_fault_diagnostics import anchor_calibration

CHANGES = (('R', .5), ('R', 1.), ('T', .03), ('I_pp', 3.))
TEMPORARY = ('desync_one', 'ghost_one', 'blur_one')


def stream_values(caps, model, p_anchor, p_changed, tau, corrupt=None, circle=None, rng=None, cfg=None):
    edge, inten, loss = [], [], []
    for i, cap in enumerate(caps):
        p = p_changed if (tau is not None and i >= tau) else p_anchor
        if corrupt is not None and i == corrupt[0]:
            kind = corrupt[1]
            cap = (P.desynchronised(cap, circle) if kind == 'desync_one' else P.ghost(cap, circle) if kind == 'ghost_one'
                   else P.blur(cap, circle))
        cc = CaptureCues(cap, model, p_anchor, cfg)
        edge.append(cc.edge(p).contrast); inten.append(cc.intensity(p).contrast)
        loss.append(evaluate_capture(cap, model, p, p_anchor)['loss'])
    return dict(edge=edge, intensity=inten, production_loss=loss)


def run_monitors(values, cfg, rng):
    out = {}
    floors = dict(edge=cfg.edge_informative_contrast, intensity=cfg.intensity_informative_contrast)
    for key in ('edge', 'intensity'):
        out[key] = S.monitor(values[key], cfg, rng=rng, informative_floor=floors[key])
    # Comparator: the same CUSUM on the production loss (higher is worse, so negate).
    out['production_loss'] = S.monitor([-v for v in values['production_loss']], cfg, rng=rng)
    alarms = [out[k].get('cusum', {}).get('alarm') for k in ('edge', 'intensity')]
    alarms = [a for a in alarms if a is not None]
    statuses = {out[k].get('status') for k in ('edge', 'intensity')}
    if statuses <= {'UNINFORMATIVE', 'INSUFFICIENT_EVIDENCE'}:
        out['combined'] = dict(alarm=None, status='UNINFORMATIVE')
        return out
    order = ('PERSISTENT_CHANGE', 'CHANGE_AT_END_UNCONFIRMED', 'TRANSIENT_DEVIATION')
    out['combined'] = dict(alarm=min(alarms) if alarms else None,
                           status=next((s for s in order if s in statuses), 'NO_CHANGE'))
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--datasets', nargs='+', required=True)
    parser.add_argument('--replicates', type=int, default=3)
    parser.add_argument('--output', required=True)
    parser.add_argument('--from-streams', help='Re-run only the monitors on the values saved in an earlier streams.json')
    args = parser.parse_args()
    cfg = ResearchConfig(); diag = DiagnosticsConfig()
    output = Path(args.output)
    if output.exists() and any(output.iterdir()):
        raise FileExistsError('Use a new output directory')
    output.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix='fdseq_', dir=os.environ.get('LOCALAPPDATA')))
    rows = []
    if args.from_streams:
        args.datasets = []
        for row in json.loads(Path(args.from_streams).read_text(encoding='utf-8')):
            mon = run_monitors(row['values'], diag, np.random.default_rng(row['replicate']))
            row['monitors'] = {k: dict(status=v.get('status'), cusum_alarm=v.get('cusum', {}).get('alarm') if 'cusum' in v else v.get('alarm'),
                                       conformal_alarm=v.get('conformal', {}).get('alarm'),
                                       conformal_cusum_alarm=v.get('conformal', {}).get('conformal_cusum_alarm')) for k, v in mon.items()}
            rows.append(row)
    try:
        for dataset in args.datasets:
            ref, data = dataset_paths(dataset)
            bundle = load_capture_bundle(data, scratch/dataset, cfg.max_features_per_capture, cfg.seed,
                                         intensity_points=diag.intensity_points, intensity_bins=diag.intensity_bins)
            caps = sorted(bundle.caps, key=lambda c: (getattr(c, 'capture_time', None) or 0., c.name))
            anchor = anchor_calibration(dataset, ref, bundle, cfg)
            model = ProjectionModel(anchor, bundle.size, bundle.circle, cfg.max_angle_rad)
            p0 = parameters(anchor)
            n = len(caps); W = diag.monitor_reference_window
            tau = W + max(1, (n - W)//3)
            for rep in range(args.replicates):
                rng = np.random.default_rng(500 + rep)
                cases = [('nominal', None, None, None)]
                cases += [('persistent', k, m, None) for k, m in CHANGES]
                cases += [('temporary', t, None, (int(rng.integers(W, n)), t)) for t in TEMPORARY]
                for ctype, kind, magnitude, corrupt in cases:
                    p1 = p0; t0 = None
                    if ctype == 'persistent':
                        delta, _ = P.calibration_change(p0, kind, magnitude, rng)
                        p1 = P.perturbed(p0, delta); t0 = tau
                    values = stream_values(caps, model, p0, p1, t0, corrupt, bundle.circle, rng, diag)
                    mon = run_monitors(values, diag, np.random.default_rng(rep))
                    row = dict(dataset=dataset, replicate=rep, case=ctype, kind=kind, magnitude=magnitude, tau=t0,
                               corrupt_index=corrupt[0] if corrupt else None, length=n, values=values,
                               monitors={k: dict(status=v.get('status'), cusum_alarm=v.get('cusum', {}).get('alarm') if 'cusum' in v else v.get('alarm'),
                                                 conformal_alarm=v.get('conformal', {}).get('alarm'),
                                                 conformal_cusum_alarm=v.get('conformal', {}).get('conformal_cusum_alarm'))
                                         for k, v in mon.items()})
                    rows.append(row)
                    print(dataset, rep, ctype, kind, magnitude, {k: (v['status'], v['cusum_alarm']) for k, v in row['monitors'].items()}, flush=True)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    (output/'streams.json').write_text(json.dumps(serializable(rows), indent=1) + '\n', encoding='utf-8')
    # Summary: alarm rates per case for each monitored statistic.
    summary = {}
    for stat in ('combined', 'edge', 'intensity', 'production_loss'):
        res = {}
        for case in ('nominal', 'persistent', 'temporary'):
            sel = [r for r in rows if r['case'] == case]
            alarms = [r['monitors'][stat]['cusum_alarm'] for r in sel]
            persistent = [r['monitors'][stat]['status'] == 'PERSISTENT_CHANGE' for r in sel]
            delays = [a - r['tau'] for a, r in zip(alarms, sel) if a is not None and r['tau'] is not None]
            early = [a is not None and r['tau'] is not None and a < r['tau'] for a, r in zip(alarms, sel)]
            res[case] = dict(n=len(sel), alarm=sum(a is not None for a in alarms), persistent_label=sum(persistent),
                             early_alarms=sum(early), median_delay=float(np.median(delays)) if delays else None)
        summary[stat] = res
    (output/'summary.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(summary, indent=1))


if __name__ == '__main__':
    main()
