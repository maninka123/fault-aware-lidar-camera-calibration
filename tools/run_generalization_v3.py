"""Freeze and run the grouped generalization evaluation.

    python -B tools/run_generalization_v3.py --freeze          # write docs/research/v3/FROZEN_GENERALIZATION.json (before any run)
    python -B tools/run_generalization_v3.py --run NEW_FOLDER # verify the freeze, then run every method on every group

The run refuses to start if the constants or any listed source file differ from the freeze, so tuning after seeing results is a separate,
declared development round. Methods receive only a calibration and captures; the per-group anchor is an evaluation-truth device built from
that group's own captures (``evaluate_fault_diagnostics.anchor_calibration``).
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import argparse
import json
import os
import subprocess
import time
from research_calibration.fault_diagnostics_v3 import SignatureConfig, correspondence as C, joint_estimation as JE, generalization as G
from research_calibration.config import ResearchConfig
from research_calibration.fault_diagnostics import DiagnosticsConfig
from research_calibration.legacy_adapter import REPOSITORY

FROZEN = REPOSITORY / 'docs/research/v3/FROZEN_GENERALIZATION.json'
SOURCES = ['research_calibration/fault_diagnostics_v3/correspondence.py', 'research_calibration/fault_diagnostics_v3/joint_estimation.py',
           'research_calibration/fault_diagnostics_v3/config.py', 'research_calibration/fault_diagnostics_v3/diagnostic_inference.py',
           'research_calibration/fault_diagnostics_v3/hypothesis_separation.py', 'research_calibration/fault_diagnostics_v3/geometry_signatures.py',
           'research_calibration/fault_diagnostics_v3/generalization.py', 'research_calibration/fault_diagnostics/policy.py',
           'research_calibration/fault_diagnostics/cues.py', 'research_calibration/fault_diagnostics/config.py',
           'research_calibration/calibration_pipeline.py', 'tools/evaluate_pairing_v3.py', 'tools/evaluate_fault_diagnostics_v3.py',
           'tools/evaluate_fault_diagnostics.py', 'tools/analyze_attribution_root_cause_v3.py', 'tools/summarize_generalization_v3.py',
           'docs/research/v3/PROTOCOL_GENERALIZATION.md']
# Groups of the study, by manifest id, with their declared roles (see research_data/groups_v3.json).
STUDY = dict(development=['enclosure_off_ten', 'october_device_one'], evaluation=['enclosure_on_twelve', 'october_device_four'],
             not_used_in_design=['generalization_pair2', 'generalization_pair3', 'generalization_nov5_off', 'generalization_nov5_on'])
VARIANTS = ['oriented', 'geometric', 'geometric_no_visibility', 'geometric_no_balance', 'geometric_no_confidence']


def constants():
    from evaluate_pairing_v3 import MAX_STD, EDGE_MARGIN, QUICK_DRIFTS, METHODS
    return dict(correspondence=C.CorrespondenceConfig().to_dict(), signature=SignatureConfig().to_dict(), em=JE.EMConfig().to_dict(),
                research=ResearchConfig().to_dict(), diagnostics=DiagnosticsConfig().to_dict(), recovery_max_std=MAX_STD, acceptance_edge_margin=EDGE_MARGIN,
                quick_drifts=QUICK_DRIFTS, methods=METHODS, variants=VARIANTS, study=STUDY, replicates=1, scene_min_inliers=20,
                selection_cost='(no_change_alarms + wrong_unique, -detections, -exact) summed over training groups',
                comparators=['production', 'v2', 'v2_no_intensity', 'v3', 'original_optimizer(legacy_optimizer strategy, policy "production")'])


def freeze():
    FROZEN.write_text(json.dumps(dict(constants_sha256=G.canonical_hash(constants()), constants=constants(),
                                      source_sha256=G.file_hashes(SOURCES, REPOSITORY)), indent=2, default=str) + '\n', encoding='utf-8')
    print('Frozen:', FROZEN)


def verify():
    frozen = json.loads(FROZEN.read_text(encoding='utf-8'))
    G.check_frozen(frozen, constants(), G.file_hashes(SOURCES, REPOSITORY))
    return frozen


def run(output):
    verify()
    out = Path(output)
    if out.exists() and any(out.iterdir()):
        raise FileExistsError('Use a new output directory')
    out.mkdir(parents=True, exist_ok=True)
    head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=REPOSITORY, capture_output=True, text=True).stdout.strip()
    dirty = bool(subprocess.run(['git', 'status', '--porcelain', '--'] + SOURCES, cwd=REPOSITORY, capture_output=True, text=True).stdout.strip())
    (out / 'run.json').write_text(json.dumps(dict(source_commit=head, frozen_sources_dirty=dirty, frozen_file=str(FROZEN), started=time.time()), indent=2) + '\n', encoding='utf-8')
    env = dict(os.environ, PYTHONIOENCODING='utf8', PYTHONDONTWRITEBYTECODE='1')
    py = [sys.executable, '-B']
    jobs = []
    all_ids = [d for ds in STUDY.values() for d in ds]
    for role, ids in STUDY.items():
        jobs.append(('pairing_' + role, py + ['tools/evaluate_pairing_v3.py', '--datasets', *ids, '--role', role, '--replicates', '1', '--quick', '--output', str(out / ('pairing_' + role))]))
    jobs.append(('pipeline', py + ['tools/evaluate_fault_diagnostics_v3.py', '--datasets', *all_ids, '--replicates', '1', '--quick', '--only', 'nominal', 'drift', '--output', str(out / 'pipeline')]))
    jobs.append(('original_optimizer', py + ['tools/evaluate_fault_diagnostics_v3.py', '--datasets', *all_ids, '--replicates', '1', '--quick', '--only', 'nominal', 'drift',
                                             '--strategy', 'legacy_optimizer', '--output', str(out / 'original_optimizer')]))
    for name, cmd in jobs:
        started = time.perf_counter()
        with (out / (name + '.log')).open('w', encoding='utf-8') as log:
            code = subprocess.run(cmd, cwd=REPOSITORY, env=env, stdout=log, stderr=subprocess.STDOUT).returncode
        print(f'{name}: exit {code} in {time.perf_counter() - started:.0f} s', flush=True)
        if code:
            raise SystemExit(f'{name} failed; see {out / (name + ".log")}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--freeze', action='store_true')
    parser.add_argument('--run')
    a = parser.parse_args()
    if a.freeze:
        freeze()
    elif a.run:
        run(a.run)
    else:
        parser.error('Choose --freeze or --run')
