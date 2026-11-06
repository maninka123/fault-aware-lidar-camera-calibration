"""Pipeline for genuinely new (unseen) groups: register, freeze, run. Nothing here exists in the repository's data today.

    python -B tools/unseen_pipeline_v3.py register --id NEW --device DEV --session YYYY-MM-DD --state "enclosure on" \
        --data-dir PATH_TO_STACKED_NPZ --reference PATH_TO_REFERENCE_JSON --camera-model M --lidar-model L --scan-pattern P
    python -B tools/unseen_pipeline_v3.py freeze        # writes docs/research/v3/FROZEN_UNSEEN.json; COMMIT it
    python -B tools/unseen_pipeline_v3.py run NEW_FOLDER

register refuses a group with prior use, a duplicated capture, or an undeclared sensor, and reports whether its scene is new. run requires the
development freeze to be unchanged, the unseen freeze to be committed and clean, and the group list and capture fingerprints to match it.
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
import numpy as np
import audit_datasets_v3 as A
import run_generalization_v3 as R
from research_calibration.fault_diagnostics_v3 import generalization as G, unseen as U
from research_calibration.legacy_adapter import REPOSITORY

REGISTRY = REPOSITORY / 'research_data/groups_v3.json'
FROZEN_UNSEEN = REPOSITORY / 'docs/research/v3/FROZEN_UNSEEN.json'


def resolve(path):
    p = Path(path)
    return p if p.is_absolute() else (A.WORKSPACE / p)


def register(a):
    registry = G.load_registry(REGISTRY)
    folder = resolve(a.data_dir)
    files = sorted(folder.glob('*.npz'))
    if not folder.is_dir() or not files:
        raise SystemExit(f'No stacked .npz captures in {folder}')
    if not resolve(a.reference).is_file():
        raise SystemExit(f'Reference calibration not found: {resolve(a.reference)}')
    stats, imgs = A.descriptors(files)
    captures, sizes = [], set()
    for f in files:
        z = np.load(f)
        sizes.add(tuple(int(x) for x in z['image'].shape[1::-1]))
        captures.append(dict(name=f.name, file_sha256=A.sha(f), content_fingerprint=A.fingerprint(z)))
    candidate = dict(id=a.id, device=a.device, session=a.session, state=a.state, manifest_id='unseen_' + a.id, role='unseen', used_in=[],
                     data_directory=str(folder), reference_calibration=str(resolve(a.reference)), reference_sha256=A.sha(resolve(a.reference)),
                     capture_count=len(files), captures=captures, descriptors=stats, image_size_wh=sorted(sizes), camera_model=a.camera_model,
                     lidar_model=a.lidar_model, lidar_scan_pattern=a.scan_pattern)
    # Scene similarity against every known group (median images of known groups are re-read; nothing is fitted).
    images = {}
    for g in registry['groups']:
        images[g['id']] = A.descriptors(sorted((A.WORKSPACE / g['data_directory']).glob('*.npz')))[1]
    images[a.id] = imgs
    sim = A.scene_similarity(images)
    to_known = {g['id']: (sim.get(f"{g['id']}|{a.id}") or sim.get(f"{a.id}|{g['id']}") or {}).get('homography_inliers', 0) for g in registry['groups']}
    out = U.admit_unseen(registry, candidate, to_known)
    G.validate_registry(out)
    REGISTRY.write_text(json.dumps(out, indent=2) + '\n', encoding='utf-8')
    print('Registered', a.id, '| new scene:', candidate['scene_is_new'], '| shares a scene with:', candidate['scene_cluster_members'],
          '| sensor fields that differ from every known group:', [k for k, v in U.sensors_differ(registry, candidate).items() if v])


def unseen_ids(registry):
    return [g['id'] for g in registry['groups'] if g['role'] == 'unseen']


def freeze():
    registry = G.load_registry(REGISTRY)
    ids = unseen_ids(registry)
    if not ids:
        raise SystemExit('No unseen groups are registered')
    by_id = {g['id']: g for g in registry['groups']}
    FROZEN_UNSEEN.write_text(json.dumps(dict(groups=ids, fingerprints={i: sorted(c['content_fingerprint'] for c in by_id[i]['captures']) for i in ids},
                                             constants_sha256=G.canonical_hash(R.constants()), created=time.time()), indent=2) + '\n', encoding='utf-8')
    print('Wrote', FROZEN_UNSEEN, '- commit it before running')


def run(output):
    R.verify()                                              # the development freeze (constants and sources) is unchanged
    registry = G.load_registry(REGISTRY)
    G.validate_registry(registry)
    ids = unseen_ids(registry)
    if not FROZEN_UNSEEN.exists() or not U.git_committed_and_clean(FROZEN_UNSEEN.relative_to(REPOSITORY), REPOSITORY):
        raise SystemExit('The unseen freeze must exist and be committed and clean before the run')
    U.check_unseen_freeze(json.loads(FROZEN_UNSEEN.read_text(encoding='utf-8')), registry, R.constants(), ids)
    manifest_ids = [g['manifest_id'] for g in registry['groups'] if g['id'] in ids]
    out = Path(output)
    out.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ, PYTHONIOENCODING='utf8', PYTHONDONTWRITEBYTECODE='1')
    py = [sys.executable, '-B']
    jobs = [('pairing', py + ['tools/evaluate_pairing_v3.py', '--datasets', *manifest_ids, '--role', 'not_used_in_design', '--replicates', '1', '--quick', '--output', str(out / 'pairing_unseen')]),
            ('pipeline', py + ['tools/evaluate_fault_diagnostics_v3.py', '--datasets', *manifest_ids, '--replicates', '1', '--quick', '--only', 'nominal', 'drift', '--output', str(out / 'pipeline')]),
            ('original_optimizer', py + ['tools/evaluate_fault_diagnostics_v3.py', '--datasets', *manifest_ids, '--replicates', '1', '--quick', '--only', 'nominal', 'drift', '--strategy', 'legacy_optimizer',
                                         '--output', str(out / 'original_optimizer')])]
    for name, cmd in jobs:
        code = subprocess.run(cmd, cwd=REPOSITORY, env=env, stdout=(out / (name + '.log')).open('w'), stderr=subprocess.STDOUT).returncode
        print(name, 'exit', code, flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest='cmd', required=True)
    r = sub.add_parser('register')
    for f in ('id', 'device', 'session', 'state', 'data-dir', 'reference', 'camera-model', 'lidar-model', 'scan-pattern'):
        r.add_argument('--' + f, required=True)
    sub.add_parser('freeze')
    x = sub.add_parser('run')
    x.add_argument('output')
    a = p.parse_args()
    {'register': lambda: register(a), 'freeze': freeze, 'run': lambda: run(a.output)}[a.cmd]()
