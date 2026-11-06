"""Matched V3 development evaluation; existing V2 recordings are never blind V3 tests.

Fits and partitions are shared, not recomputed for each diagnostic ablation. Save the
protocol and code hashes before the first trial. Physical accuracy remains unavailable.
"""
import os
for _thread_variable in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS'):
    os.environ[_thread_variable] = '1'
import argparse
import copy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import zlib
import zipfile

QUICK_DRIFTS = (('R', 1.), ('T', .06), ('I_pp', 3.), ('I_focal', .02), ('RT', (.5, .03)))
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tools'))
import cv2
import numpy as np
cv2.setNumThreads(1)
from evaluate_fault_diagnostics import (DRIFTS, NUISANCES, anchor_calibration,
                                      subset_bundle, params_in, pixel_error, score)
from research_calibration.benchmark import dataset_paths, environment
from research_calibration.config import ResearchConfig
from research_calibration.geometry import ProjectionModel, parameters
from research_calibration.legacy_adapter import load_capture_bundle
from research_calibration.reporting import serializable
from research_calibration.fault_diagnostics import DiagnosticsConfig
from research_calibration.fault_diagnostics import perturbations as P
from research_calibration.fault_diagnostics.runner import assess_with_diagnostics
from research_calibration.fault_diagnostics_v3.config import SignatureConfig


def _git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def summarize(rows):
    """Descriptive counts only: repeated trials and static captures are dependent."""
    attempted = [r for r in rows if r.get('condition_type') != 'reference']
    errors = [r for r in rows if 'error' in r]
    scored = [r for r in rows if 'score' in r]
    methods = sorted({m for r in scored for m in r['score']})
    result = dict(attempted=len(rows), scored=len(scored), errors=errors, methods={},
                  scope='V3 development; dependent semi-synthetic trials; no physical ground truth',
                  update_validation_exercised=False,
                  update_scope='Diagnostic-only sidecar comparison; final candidate fit/outer acceptance is not exercised.')
    for method in methods:
        valid = [r for r in scored if method in r['score']]
        no_change = [r for r in valid if r['truth_groups'] is None]
        drift = [r for r in valid if r['truth_groups'] is not None]
        unique = [r for r in valid if r['score'][method]['attributed'] is not None]
        ambiguous = [r for r in drift if r['score'][method]['status'] == 'DRIFT_AMBIGUOUS']
        count = lambda seq, key: sum(bool(r['score'][method].get(key)) for r in seq)
        per_group = {}
        for groups in sorted({''.join(r['truth_groups']) for r in drift}):
            group_rows = [r for r in drift if ''.join(r['truth_groups']) == groups]
            per_group[groups] = dict(n=len(group_rows), detections=count(group_rows, 'alarm'),
                                     exact=count(group_rows, 'correct_attribution'))
        seconds = [r.get('method_seconds', {}).get(method) for r in valid]
        seconds = [x for x in seconds if x is not None]
        result['methods'][method] = dict(
            no_change_n=len(no_change), false_alarms=count(no_change, 'alarm'),
            drift_n=len(drift), detections=count(drift, 'alarm'),
            misses=len(drift)-count(drift, 'alarm'), exact=count(drift, 'correct_attribution'),
            wrong=count(valid, 'wrong_attribution'), scored_n=len(valid),
            ambiguity_n=len(ambiguous), ambiguity_contains_truth=count(ambiguous, 'ambiguous_contains_truth'),
            ambiguity_mean_size=float(np.mean([len(r['decisions'][method].get('ambiguity_set') or []) for r in ambiguous])) if ambiguous else None,
            selective_accuracy=count(unique, 'correct_attribution')/len(unique) if unique else None,
            unique_coverage=len(unique)/len(valid) if valid else None,
            no_change_updates=count(no_change, 'update'), total_updates=count(valid, 'update'),
            by_fault=per_group, median_policy_seconds=float(np.median(seconds)) if seconds else None,
            physical_rotation_error_deg=None, physical_translation_error_m=None,
            physical_accuracy_reason='No independently measured physical fault or correct anchor is available.')
    result['failed_scored_conditions'] = sum(r.get('condition_type') != 'reference' for r in errors)
    result['attempted_scored_conditions'] = len(attempted)
    return result


def markdown(summary):
    lines = ['# V3 matched development evaluation', '', summary['scope'], '',
             f"Attempted: {summary['attempted']}; scored: {summary['scored']}; errors: {len(summary['errors'])}.", '',
             '| Method | False alarms | Detections | Exact | Wrong | Ambiguous | Truth in ambiguity | No-change updates | Policy median seconds |',
             '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for method, m in summary['methods'].items():
        duration = '-' if m['median_policy_seconds'] is None else f"{m['median_policy_seconds']:.4f}"
        lines.append(f"| {method} | {m['false_alarms']}/{m['no_change_n']} | {m['detections']}/{m['drift_n']} | "
                     f"{m['exact']}/{m['drift_n']} | {m['wrong']}/{m['scored_n']} | {m['ambiguity_n']}/{m['drift_n']} | "
                     f"{m['ambiguity_contains_truth']}/{m['ambiguity_n']} | {m['no_change_updates']}/{m['no_change_n']} | {duration} |")
    lines += ['', 'Policy time excludes the shared production/V2 fitting pass. Trial rows report that complete cost separately.',
              'V3 update acceptance is not exercised by this diagnostic-only comparison. Zero recommended V3 updates is not a measured safety guarantee.',
              'Independent physical calibration accuracy, accepted-update accuracy and operating false-alarm rates are unavailable.', '']
    return '\n'.join(lines)


def run(args):
    from research_calibration.fault_diagnostics_v3.runner import diagnose_from_records
    if args.replicates < 1:
        raise ValueError('At least one replicate is required')
    cfg = ResearchConfig(**(json.loads(Path(args.config).read_text(encoding='utf-8')) if args.config else {}))
    signature_cfg = SignatureConfig(**(json.loads(Path(args.signature_config).read_text(encoding='utf-8'))
                                       if args.signature_config else {}))
    diag = DiagnosticsConfig()
    prereg = ROOT / 'docs/research/v3/PREREGISTRATION_V3.md'
    if not prereg.exists():
        raise RuntimeError('Save the V3 protocol before evaluating any trial')
    output = Path(args.output).resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError('Use a new empty output directory')
    output.mkdir(parents=True, exist_ok=True)
    code = list((ROOT/'research_calibration').rglob('*.py')) + [Path(__file__), prereg]
    protocol = dict(role='development_v3', datasets=args.datasets, replicates=args.replicates,
                    only=args.only, drifts=DRIFTS, nuisances=NUISANCES,
                    research=cfg.to_dict(), diagnostics=diag.to_dict(), signature=signature_cfg.to_dict(),
                    fit_strategy=args.strategy, environment=environment(),
                    head=_git('rev-parse', 'HEAD'), branch=_git('branch', '--show-current'),
                    dirty_status=_git('status', '--short'),
                    source_sha256={str(p.relative_to(ROOT)): _digest(p) for p in code},
                    manifest_sha256=_digest(ROOT/'research_data/manifest.json'),
                    ablations=['v3', 'v3_no_geometry', 'v3_no_scene_quality', 'v3_raw_edges'],
                    physical_truth=False, note='All existing V2 recordings are development data for V3.',
                    omitted_comparisons=['Strict original maintenance workflow',
                                         'Literature implementation at matched budget',
                                         'Active-selection calibration accuracy',
                                         'New temporal signal versus unchanged monitor'])
    (output/'protocol.json').write_text(json.dumps(serializable(protocol), indent=2)+'\n', encoding='utf-8')
    # Zip members avoid Windows long-path problems and preserve the exact implementation.
    with zipfile.ZipFile(output/'src.zip', 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in code:
            payload = path.read_bytes()
            rel = str(path.relative_to(ROOT))
            if hashlib.sha256(payload).hexdigest() != protocol['source_sha256'][rel]:
                raise RuntimeError('Source changed while freezing protocol: '+rel)
            archive.writestr(path.relative_to(ROOT).as_posix(), payload)
    scratch_parent = Path(os.environ.get('LOCALAPPDATA', tempfile.gettempdir())).resolve()
    scratch = Path(tempfile.mkdtemp(prefix='fdv3_', dir=str(scratch_parent))).resolve()
    if scratch.parent != scratch_parent or not scratch.name.startswith('fdv3_'):
        raise RuntimeError('Task scratch directory is outside the declared temporary parent')
    rows = []
    try:
        with (output/'trials.jsonl').open('w', encoding='utf-8') as log:
            for dataset in args.datasets:
                reference_path, data = dataset_paths(dataset)
                full = load_capture_bundle(data, scratch/dataset/'inputs', cfg.max_features_per_capture,
                                           cfg.seed, intensity_points=diag.intensity_points,
                                           intensity_bins=diag.intensity_bins)
                anchor = anchor_calibration(dataset, reference_path, full, cfg)
                (output/(dataset+'_anchor.json')).write_text(json.dumps(serializable(anchor), indent=2)+'\n', encoding='utf-8')
                amodel = ProjectionModel(anchor, full.size, full.circle, cfg.max_angle_rad)
                p_anchor = parameters(anchor)
                for rep in range(args.replicates):
                    rng = np.random.default_rng(1000*rep+17)
                    n = len(full.caps)
                    keep = sorted(rng.choice(n, n-2, replace=False).tolist()) if n > 6 else list(range(n))
                    base = subset_bundle(full, keep)
                    conditions = ([('nominal', None, None)] + [('drift', k, m) for k, m in DRIFTS]
                                  + [('nuisance', k, None) for k in NUISANCES]
                                  + [('drift_nuisance', 'spurious_lines_all', None)])
                    if getattr(args, 'quick', False):
                        conditions = [c for c in conditions if c[0] != 'drift' or (c[1], c[2]) in QUICK_DRIFTS]
                    for ctype, kind, magnitude in conditions:
                        if args.only and ctype not in args.only:
                            continue
                        crng = np.random.default_rng([rep, zlib.crc32(f'{ctype}|{kind}|{magnitude}'.encode())])
                        cal, bundle, truth = copy.deepcopy(anchor), base, None
                        delta = np.zeros(13)
                        if ctype in ('drift', 'drift_nuisance'):
                            delta, truth = P.calibration_change(p_anchor, kind if ctype == 'drift' else 'R',
                                                               magnitude if ctype == 'drift' else 1., crng)
                            cal = P.perturbed_calibration(anchor, amodel, p_anchor, delta)
                        if ctype in ('nuisance', 'drift_nuisance'):
                            bundle = subset_bundle(base, range(len(base.caps)))
                            m = len(base.caps)
                            outer_n = max(2, int(np.ceil(m*cfg.outer_fraction))) if m >= cfg.min_capture_blocks+3 else 0
                            outer_idx = set(np.random.default_rng(cfg.seed).permutation(m)[:outer_n].tolist())
                            inner = [i for i in range(m) if i not in outer_idx]
                            bundle.caps = P.apply_nuisance(base.caps, base.circle, kind, crng, index=int(crng.choice(inner)))
                        label = f'{ctype}:{kind}:{magnitude}' if ctype == 'drift' else f'{ctype}:{kind}' if kind else ctype
                        row = dict(dataset=dataset, replicate=rep, condition=label, condition_type=ctype,
                                   truth_groups=list(truth) if truth else None, delta=delta.tolist(),
                                   captures=[c.name for c in bundle.caps])
                        folder = scratch/'trial'
                        begin = time.perf_counter()
                        try:
                            records = []
                            payload, result = assess_with_diagnostics(cal, data, output=folder, config=cfg,
                                                                     diagnostics=diag, bundle=bundle,
                                                                     records_out=records, strategy=args.strategy)
                            shared_seconds = time.perf_counter()-begin
                            decisions, policy_times = {}, {}
                            for name, overrides in [('v3', {}), ('v3_no_geometry', dict(geometry=False)),
                                                     ('v3_no_scene_quality', dict(scene_quality=False)),
                                                     ('v3_raw_edges', dict(chance_correction=False))]:
                                policy_begin = time.perf_counter()
                                ablation_cfg = replace(signature_cfg,
                                                       geometric_signatures=overrides.get('geometry', signature_cfg.geometric_signatures),
                                                       scene_quality=overrides.get('scene_quality', signature_cfg.scene_quality),
                                                       chance_correction=overrides.get('chance_correction', signature_cfg.chance_correction))
                                decisions[name] = diagnose_from_records(cal, bundle, records, payload,
                                                                       config=cfg, signature_config=ablation_cfg)
                                policy_times[name] = time.perf_counter()-policy_begin
                            v2_comparators = {'v2': payload['experimental']['proposed'],
                                              'v2_no_intensity': payload['experimental']['no_intensity_cue'],
                                              'v2_raw_oriented': payload['experimental']['no_chance_correction']}
                            old_score = score(dict(truth_groups=row['truth_groups'], production=payload['production'],
                                                   experimental=v2_comparators))
                            if args.strategy != 'fault_aware':
                                old_score[args.strategy] = old_score.pop('production')
                            # V3 uses the same alarm/attribution definition; validated candidates remain alarms.
                            for name, decision in decisions.items():
                                normalized = copy.deepcopy(decision)
                                if normalized.get('status') == 'UPDATE_CANDIDATE_VALIDATED':
                                    normalized['status'] = 'DRIFT_SUPPORTED'
                                old_score[name] = score(dict(truth_groups=row['truth_groups'], production=payload['production'],
                                                            experimental={name: normalized}))[name]
                                old_score[name]['status'] = decision.get('status')
                            cmodel = ProjectionModel(cal, bundle.size, bundle.circle, cfg.max_angle_rad)
                            row.update(score=old_score, decisions={**v2_comparators, **decisions}, v2=payload['experimental']['proposed'],
                                       production=payload['production'], shared_cost=payload['cost'],
                                       fold_records=records, v2_evidence=payload['evidence'], v2_outer=payload['outer'],
                                       shared_seconds=shared_seconds, method_seconds=policy_times,
                                       current_pixel_displacement_from_anchor=pixel_error(bundle.caps, cmodel, parameters(cal), params_in(anchor, cmodel)),
                                       physical_rotation_error_deg=None, physical_translation_error_m=None)
                        except Exception as error:
                            row['error'] = repr(error)
                        row['seconds'] = time.perf_counter()-begin
                        rows.append(row)
                        log.write(json.dumps(serializable(row), allow_nan=False)+'\n'); log.flush()
                        print(dataset, rep, label, row.get('error') or {m: s['status'] for m, s in row['score'].items()}, flush=True)
                        resolved = folder.resolve()
                        if folder.exists() and resolved.parent == scratch and scratch.parent == scratch_parent:
                            shutil.rmtree(resolved)
                        summary = summarize(rows)
                        (output/'summary.json').write_text(json.dumps(serializable(summary), indent=2)+'\n', encoding='utf-8')
                        (output/'summary.md').write_text(markdown(summary), encoding='utf-8')
        changes = [str(p.relative_to(ROOT)) for p in code
                   if _digest(p) != protocol['source_sha256'][str(p.relative_to(ROOT))]]
        (output/'source_integrity.json').write_text(json.dumps(dict(source_changed_during_run=changes), indent=2)+'\n', encoding='utf-8')
        (output/'run_status.json').write_text(json.dumps(dict(status='complete', completed_trials=len(rows),
                                                              trial_errors=sum('error' in r for r in rows)), indent=2)+'\n', encoding='utf-8')
    finally:
        # Delete only the exact task-created temporary directory, verified against its parent.
        resolved = scratch.resolve()
        if resolved.name.startswith('fdv3_') and resolved.parent == scratch_parent:
            shutil.rmtree(resolved)
    if any('error' in r for r in rows):
        raise SystemExit('Evaluation recorded trial errors; inspect trials.jsonl')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--datasets', nargs='+', required=True)
    parser.add_argument('--replicates', type=int, default=1)
    parser.add_argument('--only', nargs='*', choices=('nominal', 'drift', 'nuisance', 'drift_nuisance'))
    parser.add_argument('--config')
    parser.add_argument('--signature-config', help='JSON overrides for declared V3 signature tolerances and switches')
    parser.add_argument('--strategy', choices=('fault_aware', 'legacy_optimizer'), default='fault_aware',
                        help='Shared fitting engine; legacy_optimizer uses frozen maintenance refinement at the common budget')
    parser.add_argument('--quick', action='store_true', help='five drift conditions instead of seven (faster, same seeds)')
    parser.add_argument('--output', required=True)
    run(parser.parse_args())
