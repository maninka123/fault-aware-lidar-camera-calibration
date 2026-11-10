"""Process one simulator run (batches of captures) with the app's own algorithms. No new calibration algorithm is implemented here.

What it does, in order (each stage is skipped if its output already exists, so it can be resumed):

  1. convert  simulator captures -> the app's stacked-capture format (image + the 1 s accumulated LiDAR cloud split into 0.1 s frames, like the
              real recordings). This is a data-format adapter only.
  2. initial  the app's "calibrate from scratch" (targetless initializer, `python -m research_calibration initialize`) on batch 1 (batch 0) only.
  3. check    for every other batch, ONE AT A TIME, against the calibration from step 2: the app's fault-aware check (`assess`), the maintenance
              comparison (`assess --strategy legacy`) and the experimental V3 diagnosis (`diagnose-v3`, not part of the app).
  4. control  the same checks against the simulator's own provided initial calibration (it equals batch 0's true mount), to separate the
              effect of the checks from the error of the initial calibration.
  5. score    every calibration and update is compared with the simulator's ground-truth mount of each batch (evaluation/ground_truth.json).
              Ground truth is never given to an algorithm.

    python tools/process_simulator_run.py "<...>/Simulator/<run folder made by the simulator lab>"

Results: research_artifacts/simulator/<dataset name>/ (one folder per dataset; not committed), heavy scratch files in %LOCALAPPDATA%/FaultAwareSim
(Windows' 260-character path limit). Run from the repository root with an environment that has the app's requirements. See
docs/research/simulator/README.md.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
import numpy as np
import cv2

HERE = Path(__file__).resolve().parent
IN_REPO = (HERE.parent / 'research_calibration').is_dir()          # normally the tool sits in tools/ of the repository
REPO = HERE.parent if IN_REPO else HERE.parent / 'repository'
RESULTS = REPO / 'research_artifacts' / 'simulator' if IN_REPO else HERE / 'runs'
PY = sys.executable
SCRATCH = Path(os.environ.get('LOCALAPPDATA', str(HERE))) / 'FaultAwareSim'
FRAME_S = 0.1


def lp(path):
    """Extended-length Windows path (the results folder is deep)."""
    p = str(Path(path).resolve())
    return Path(p if p.startswith('\\\\?\\') or os.name != 'nt' else '\\\\?\\' + p)


def log(*a):
    print(time.strftime('%H:%M:%S'), *a, flush=True)


# ------------------------------------------------------------------ 1. convert
def convert_capture(capture_dir, out_file):
    z = np.load(capture_dir / 'lidar_accumulated.npz')
    xyz, inten, t = z['xyz'].astype(np.float64), z['intensity'].astype(np.float64), z['timestamps'].astype(np.float64)
    image = cv2.imread(str(capture_dir / 'image.png'), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f'Cannot read {capture_dir / "image.png"}')
    good = np.isfinite(xyz).all(1) & (np.linalg.norm(xyz, axis=1) > 0.05)
    xyz, inten, t = xyz[good], inten[good], t[good]
    frame = np.floor((t - t.min()) / FRAME_S).astype(np.uint16)
    n_frames = int(frame.max()) + 1
    np.savez_compressed(out_file, version=np.int32(2), image=image, image_std=np.float64(0.), n_images=np.int32(1),
                        xyz_mm=np.clip(np.rint(xyz * 1000), -32767, 32767).astype(np.int16),
                        intensity=np.clip(np.rint(inten), 0, 255).astype(np.uint8), frame=frame,
                        frame_time=(t.min() + FRAME_S * np.arange(n_frames)).astype(np.float64) - t.min(), n_frames=np.int32(n_frames))
    return dict(points=int(len(xyz)), frames=n_frames, clipped=int((np.abs(xyz) > 32.767).any(axis=1).sum()))


def stage_convert(data, work):
    batches = json.loads((data / 'evaluation' / 'batches.json').read_text(encoding='utf-8'))
    info = {}
    for b in batches:
        folder = work / 'stacked' / f"batch_{b['batch']}"
        folder.mkdir(parents=True, exist_ok=True)
        for cid in b['capture_ids']:
            target = folder / f'{cid}.npz'
            if not target.exists():
                info[cid] = convert_capture(data / 'inference' / cid, target)
        log(f"batch {b['batch']}: {len(b['capture_ids'])} captures stacked")
    return batches


# ------------------------------------------------------------------ running the app's commands
def run(cmd, log_file, timeout):
    env = dict(os.environ, OMP_NUM_THREADS='1', MKL_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1')
    started = time.perf_counter()
    with open(log_file, 'w', encoding='utf-8') as f:
        code = subprocess.run(cmd, cwd=REPO, env=env, stdout=f, stderr=subprocess.STDOUT, timeout=timeout).returncode
    return code, time.perf_counter() - started


def stage_initial(work, results):
    out = work / 'initial'
    cal = results / 'initial_calibration_from_batch_0.json'
    if cal.exists():
        return cal
    if out.exists():
        shutil.rmtree(out, ignore_errors=True)
    log('initial calibration from batch 0 (the app\'s calibrate from scratch; this takes several minutes)')
    code, secs = run([PY, '-B', '-m', 'research_calibration', 'initialize', '--captures', str(work / 'stacked' / 'batch_0'), '--output', str(out)],
                     results / 'initial_calibration.log', 3 * 3600)
    found = sorted(out.rglob('calibration.json'))
    log('initialization exit', code, f'{secs:.0f} s', '->', found[0] if found else 'no calibration.json')
    if not found:
        (results / 'initial_calibration_FAILED.txt').write_text(f'exit {code}; see initial_calibration.log\n', encoding='utf-8')
        return None
    shutil.copy2(found[0], cal)
    for extra in out.rglob('assessment.json'):
        shutil.copy2(extra, results / 'initial_calibration_assessment.json')
        break
    return cal


def copy_tree(src, dst):
    src, dst = Path(src), Path(dst)
    for p in src.rglob('*'):
        if p.is_file() and 'stacked' not in p.parts:
            target = lp(dst / p.relative_to(src))
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(lp(p), target)


def stage_check(label, calibration, batches, work, results):
    """label: 'A_initial_from_batch_0' or 'B_control_simulator_initial'. One batch at a time."""
    base = results / label
    for b in batches:
        k = b['batch']
        if k == 0:
            continue
        stacked = work / 'stacked' / f'batch_{k}'
        for name, cmd in (('fault_aware', ['assess', '--strategy', 'fault_aware']), ('maintenance', ['assess', '--strategy', 'legacy']),
                          ('v3_experimental', ['diagnose-v3'])):
            final = base / f'batch_{k}' / name
            if lp(final / 'DONE').exists():
                continue
            scratch = work / 'runs' / label / f'b{k}_{name}'
            if scratch.exists():
                shutil.rmtree(lp(scratch), ignore_errors=True)
            code, secs = run([PY, '-B', '-m', 'research_calibration', cmd[0], *cmd[1:], '--calibration', str(calibration), '--captures', str(stacked),
                              '--output', str(scratch)], base / f'batch_{k}_{name}.log' if False else (results / f'{label}_batch_{k}_{name}.log'), 3 * 3600)
            log(label, f'batch {k}', name, 'exit', code, f'{secs:.0f} s')
            lp(final).mkdir(parents=True, exist_ok=True)
            if scratch.exists():
                copy_tree(scratch, final)
            if name == 'maintenance' and scratch.exists():
                copy_maintenance_run(scratch, final)
            if code:
                # A failure of the app's own algorithm is a result: keep its message next to the outputs.
                text = Path(results / f'{label}_batch_{k}_{name}.log').read_text(encoding='utf-8', errors='replace').strip().splitlines()
                lp(final / 'FAILED.txt').write_text(f'exit code {code}\n' + '\n'.join(text[-3:]) + '\n', encoding='utf-8')
            lp(final / 'DONE').write_text(json.dumps(dict(exit_code=code, seconds=secs)), encoding='utf-8')


def copy_maintenance_run(scratch, final):
    """The strict maintenance run writes into the cloned maintenance project's results folder; bring its files here."""
    try:
        summary = json.loads((scratch / 'assessment.json').read_text(encoding='utf-8'))['validation']['legacy_summary']
        run_dir = REPO / 'Calibration maintenance' / 'results' / summary['run']
        if run_dir.is_dir():
            copy_tree(run_dir, final / 'maintenance_run')
    except (OSError, KeyError, ValueError, TypeError) as error:
        lp(final / 'maintenance_run_copy_failed.txt').write_text(str(error) + '\n', encoding='utf-8')


# ------------------------------------------------------------------ 5. score against ground truth
def rt(T):
    T = np.asarray(T, float)
    return T[:3, :3], T[:3, 3]


def rotation_angle_deg(Ra, Rb):
    c = (np.trace(Ra @ Rb.T) - 1) / 2
    return float(np.degrees(np.arccos(np.clip(c, -1, 1))))


def cal_T(cal):
    return np.asarray(cal['extrinsics']['transform_lidar_to_camera'], float)


def cal_intr(cal):
    K = np.asarray(cal['intrinsics']['camera_matrix'], float)
    D = np.ravel(cal['intrinsics'].get('distortion_coefficients', [0, 0, 0, 0]))
    return dict(fx=K[0, 0], fy=K[1, 1], cx=K[0, 2], cy=K[1, 2], k1=float(D[0]) if len(D) > 0 else 0., k2=float(D[1]) if len(D) > 1 else 0.)


def error_vs(cal, truth_T, truth_K):
    R, t = rt(cal_T(cal))
    Rt, tt = rt(truth_T)
    i = cal_intr(cal)
    return dict(rotation_deg=rotation_angle_deg(R, Rt), translation_mm=float(np.linalg.norm(t - tt) * 1000),
                fx_px=float(i['fx'] - truth_K['fx']), fy_px=float(i['fy'] - truth_K['fy']), cx_px=float(i['cx'] - truth_K['cx']),
                cy_px=float(i['cy'] - truth_K['cy']), k1=float(i['k1']), k2=float(i['k2']))


def read_json(path):
    try:
        return json.loads(Path(lp(path)).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def stage_score(data, batches, results, calibrations):
    truth = {b['batch']: np.asarray(b['T_CL'], float) for b in batches}
    gt = read_json(data / 'evaluation' / 'ground_truth.json')
    K = gt[0]['camera']['K']
    truth_K = dict(fx=K[0][0], fy=K[1][1], cx=K[0][2], cy=K[1][2])
    out = dict(dataset=data.name, truth_true_batch_changes={}, initial={}, checks={})
    for k in truth:
        R, t = rt(truth[k])
        R0, t0 = rt(truth[0])
        out['truth_true_batch_changes'][k] = dict(rotation_deg=rotation_angle_deg(R, R0), translation_mm=float(np.linalg.norm(t - t0) * 1000))
    for label, cal_path in calibrations.items():
        if cal_path is None or not Path(cal_path).exists():
            out['checks'][label] = 'calibration not available'
            continue
        cal = read_json(cal_path)
        out['initial'][label] = dict(error_vs_batch_0_truth=error_vs(cal, truth[0], truth_K), path=str(cal_path))
        rows = {}
        for k in truth:
            if k == 0:
                continue
            base = results / label / f'batch_{k}'
            row = dict(calibration_used_error_vs_this_batch_truth=error_vs(cal, truth[k], truth_K))
            a = read_json(base / 'fault_aware' / 'assessment.json')
            if a:
                diag = a.get('diagnostics', {})
                row['fault_aware'] = dict(status=a['status'], selected=a['selected_hypothesis'], action=a['recommended_action'],
                                          best_relative_gain=diag.get('decision', {}).get('best_relative_gain'),
                                          candidate=diag.get('decision', {}).get('candidate_hypothesis'),
                                          updated_calibration_error=error_vs(a['updated_calibration'], truth[k], truth_K))
                if diag.get('candidate_calibration'):
                    row['fault_aware']['candidate_calibration_error'] = error_vs(diag['candidate_calibration'], truth[k], truth_K)
            m = read_json(base / 'maintenance' / 'maintenance_run' / 'summary.json')
            if m:
                row['maintenance'] = dict(verdict=m.get('verdict'), reason=m.get('reason'), mode=m.get('mode'), shift_median_px=m.get('shift_median_px'),
                                          existing_lift=(m.get('existing_on_new_data') or {}).get('lift'), refined_lift=(m.get('refined_on_new_data') or {}).get('lift'))
                opts = read_json(base / 'maintenance' / 'maintenance_run' / 'option_calibrations.json')
                if opts:
                    row['maintenance']['options_error'] = {name: error_vs(c, truth[k], truth_K) for name, c in (opts.get('calibrations') or {}).items()}
            v = read_json(base / 'v3_experimental' / 'fault_diagnostics_v3.json')
            if v:
                row['v3_experimental'] = dict(status=(v.get('v3') or {}).get('status'), reason=(v.get('v3') or {}).get('reason'))
            rows[k] = row
        out['checks'][label] = rows
    (results / 'results.json').write_text(json.dumps(out, indent=2, default=float) + '\n', encoding='utf-8')
    lines = [f"# Results for {data.name}", '', 'Ground truth: the simulator\'s true camera-LiDAR mount of every batch (never given to any algorithm).', '',
             '## True change between batches (what a perfect check would find)', '', '| Batch | rotation (deg) | translation (mm) |', '|---|---:|---:|']
    lines += [f"| {k} | {v['rotation_deg']:.3f} | {v['translation_mm']:.2f} |" for k, v in out['truth_true_batch_changes'].items()]
    for label, rows in out['checks'].items():
        lines += ['', f'## {label}', '']
        ini = out['initial'].get(label)
        if ini:
            e = ini['error_vs_batch_0_truth']
            lines += [f"Calibration used: error against batch 0 truth: rotation {e['rotation_deg']:.3f} deg, translation {e['translation_mm']:.1f} mm, fx {e['fx_px']:+.1f} px, cx {e['cx_px']:+.1f} px, cy {e['cy_px']:+.1f} px.", '']
        if isinstance(rows, str):
            lines.append(rows)
            continue
        lines += ['| Batch | calibration used: rot deg / trans mm vs this batch | fault-aware verdict (candidate) | its updated calibration: rot / trans | maintenance verdict | V3 experimental |', '|---|---|---|---|---|---|']
        for k, r in rows.items():
            u = r['calibration_used_error_vs_this_batch_truth']
            f = r.get('fault_aware', {}); fe = f.get('updated_calibration_error', {})
            lines.append(f"| {k} | {u['rotation_deg']:.3f} / {u['translation_mm']:.1f} | {f.get('status', '-')} ({f.get('candidate', '-')}) | "
                         f"{fe.get('rotation_deg', float('nan')):.3f} / {fe.get('translation_mm', float('nan')):.1f} | {(r.get('maintenance') or {}).get('verdict', '-')} | {(r.get('v3_experimental') or {}).get('status', '-')} |")
    (results / 'results.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument('dataset')
    p.add_argument('--skip-control', action='store_true')
    p.add_argument('--stages', default='convert,initial,check,control,score')
    a = p.parse_args()
    data = Path(a.dataset).resolve()
    stages = a.stages.split(',')
    work = SCRATCH / data.name
    results = RESULTS / data.name
    results.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    log('dataset', data.name, '| results', results)
    batches = stage_convert(data, work)
    initial = results / 'initial_calibration_from_batch_0.json'
    if 'initial' in stages:
        initial = stage_initial(work, results)
    if 'check' in stages and initial:
        stage_check('A_initial_from_batch_0', initial, batches, work, results)
    simulator_initial = data / 'inference' / 'initial_calibration.json'
    if 'control' in stages and not a.skip_control:
        stage_check('B_control_simulator_initial', simulator_initial, batches, work, results)
    if 'score' in stages:
        stage_score(data, batches, results, {'A_initial_from_batch_0': initial if initial and Path(initial).exists() else None,
                                              'B_control_simulator_initial': simulator_initial})
        log('scored ->', results / 'results.md')


if __name__ == '__main__':
    main()
