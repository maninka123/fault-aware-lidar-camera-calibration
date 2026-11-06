"""Audit every usable recording for generalization studies: device, session, scene, reference, prior use, duplicates, descriptors.

Writes ``research_data/groups_v3.json`` (the registry used by the grouped evaluation and its leakage tests) and a markdown table. Nothing here
fits or tunes anything. Device and session identity come from the folder history recorded below (a human-declared fact, flagged where unproven);
duplicate captures, descriptors and scene similarity are measured from the files.

    python -B tools/audit_datasets_v3.py --output docs/research/v3/results/dataset_audit
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import argparse
import hashlib
import itertools
import json
import numpy as np
import cv2
from research_calibration.legacy_adapter import REPOSITORY

WORKSPACE = (REPOSITORY / '../..').resolve()

# Declared facts. "used_in" lists every V2/V3 experiment or design decision in which the group's data were seen.
GROUPS = [
    dict(id='rig_sep29_off', device='rig-A', session='2026-09-29', state='enclosure off', manifest_id='enclosure_off_ten',
         data='Calibration maintenance/results/rig_20261104_174529/stacked/data', reference='Calibration maintenance/examples/feb2025_enclosure.json',
         used_in=['V2 development', 'V2 evaluation of anchors', 'V3 development', 'pairing development']),
    dict(id='rig_sep29_on', device='rig-A', session='2026-09-29', state='enclosure on', manifest_id='enclosure_on_twelve',
         data='Calibration maintenance/results/rig_20261104_202917/stacked/data', reference='results/2026_09_29_multi_capture/enclosure_on/calibration.json',
         used_in=['V2 held-out evaluation', 'V3 development', 'pairing evaluation']),
    dict(id='pair1_oct28', device='pair_1', session='2026-10-28', state='enclosure on', manifest_id='october_device_one',
         data='Oct 29 test/stacked_data/pair_1', reference='Oct 29 test/results/pair_1/calibration.json',
         used_in=['V3 development', 'pairing development', 'overlay/app inspection']),
    dict(id='pair2_oct28', device='pair_2', session='2026-10-28', state='enclosure on', manifest_id=None,
         data='Oct 29 test/stacked_data/pair_2', reference='Oct 29 test/results/pair_2/calibration.json', used_in=[]),
    dict(id='pair3_oct28', device='pair_3', session='2026-10-28', state='enclosure on', manifest_id=None,
         data='Oct 29 test/stacked_data/pair_3', reference='Oct 29 test/results/pair_3/calibration.json', used_in=[]),
    dict(id='pair4_oct28', device='pair_4', session='2026-10-28', state='enclosure on', manifest_id='october_device_four',
         data='Oct 29 test/stacked_data/pair_4', reference='Oct 29 test/results/pair_4/calibration.json',
         used_in=['V2 held-out evaluation', 'V3 development', 'pairing evaluation']),
    dict(id='d1_nov5_off', device='pair_1', session='2026-11-05', state='enclosure off', manifest_id=None,
         data='Calibration maintenance/results/rig_20261106_151100/stacked/data', reference='Oct 29 test/results/pair_1/calibration.json',
         device_note='Nov 5 checks were chained from device 1 (pair_1) calibration files; same physical unit is likely but not proven',
         used_in=['desktop-app checks only (no V2/V3 experiment, no design decision)']),
    dict(id='d1_nov5_on', device='pair_1', session='2026-11-05', state='enclosure on', manifest_id=None,
         data='Calibration maintenance/results/rig_20261105_230653/stacked/data', reference='Oct 29 test/results/pair_1/calibration.json',
         device_note='as above; its checks used the Oct 28 device-1 calibration as their existing calibration',
         used_in=['desktop-app checks only (no V2/V3 experiment, no design decision)']),
]
EXCLUDED = [
    dict(id='creep_three', reason='3 captures: below the 4-capture cross-validation floor; same session and scene as rig_sep29_on'),
    dict(id='nov5_on_board / nov5_off_board', reason='4 captures each: after the engine drops two for held-out comparison fewer than 4 remain'),
    dict(id='copies', reason='rig_20261104_204728, creep_raw_bags_vs_sep29, gui_* decoded copies and Calibration maintenance results duplicate captures above; duplicates are detected by content hash'),
]


def sha(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def fingerprint(z):
    """Content identity of a capture independent of the file container."""
    h = hashlib.sha256(np.ascontiguousarray(z['image']).tobytes())
    h.update(np.ascontiguousarray(z['xyz_mm'][:2000]).tobytes())
    return h.hexdigest()


def descriptors(files):
    imgs, rng, az, el, edge, sat, bright, npts = [], [], [], [], [], [], [], []
    for f in files:
        z = np.load(f)
        img = z['image']
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        imgs.append(gray)
        bright.append(float(gray.mean()) / 255.)
        sat.append(float((gray > 250).mean()))
        edge.append(float((cv2.Canny(gray, 50, 120) > 0).mean()))
        xyz = z['xyz_mm'][::50].astype(float) / 1000.
        r = np.linalg.norm(xyz, axis=1)
        keep = (r > .5) & (r < 30)
        rng.append(np.percentile(r[keep], [5, 50, 95]))
        az.append(float(np.degrees(np.arctan2(xyz[keep, 1], xyz[keep, 0])).std()))
        el.append(float(np.degrees(np.arcsin(np.clip(xyz[keep, 2] / r[keep], -1, 1))).std()))
        npts.append(int(len(z['xyz_mm'])))
    rr = np.array(rng)
    return dict(brightness=float(np.mean(bright)), saturated_share=float(np.mean(sat)), edge_density=float(np.mean(edge)),
                range_p5_p50_p95_m=[float(x) for x in rr.mean(axis=0)], depth_ratio_p95_over_p5=float(rr.mean(axis=0)[2] / max(rr.mean(axis=0)[0], 1e-6)),
                azimuth_std_deg=float(np.mean(az)), elevation_std_deg=float(np.mean(el)), points_per_capture=int(np.mean(npts))), imgs


def scene_similarity(images_by_group):
    """ORB match counts between median images of each group pair (a crude, viewpoint-sensitive similarity; not a proof of scene identity)."""
    orb = cv2.ORB_create(1500)
    bf = cv2.BFMatcher(cv2.NORM_HAMMING)
    feats = {}
    for g, imgs in images_by_group.items():
        median = np.median(np.stack(imgs), axis=0).astype(np.uint8)
        feats[g] = orb.detectAndCompute(median, None)
    out = {}
    for a, b in itertools.combinations(feats, 2):
        ka, da = feats[a]
        kb, db = feats[b]
        if da is None or db is None:
            out[f'{a}|{b}'] = None
            continue
        good = [m for m, n in (p for p in bf.knnMatch(da, db, k=2) if len(p) == 2) if m.distance < .75 * n.distance]
        inliers = 0
        if len(good) >= 8:
            src = np.float32([ka[m.queryIdx].pt for m in good]); dst = np.float32([kb[m.trainIdx].pt for m in good])
            _, mask = cv2.findHomography(src, dst, cv2.RANSAC, 5.)
            inliers = int(mask.sum()) if mask is not None else 0
        out[f'{a}|{b}'] = dict(ratio_matches=len(good), homography_inliers=inliers)
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, help='path stem for the markdown/json audit')
    parser.add_argument('--registry', default=str(REPOSITORY / 'research_data/groups_v3.json'))
    args = parser.parse_args()
    registry, images, prints = [], {}, {}
    for g in GROUPS:
        folder = WORKSPACE / g['data']
        files = sorted(folder.glob('*.npz'))
        stats, imgs = descriptors(files)
        images[g['id']] = imgs
        entry = dict(g, data_directory=g['data'], reference_calibration=g['reference'], capture_count=len(files),
                     captures=[], descriptors=stats,
                     role='development' if any(u.startswith(('V2', 'V3', 'pairing')) for u in g['used_in']) else 'not_used_in_design')
        del entry['data'], entry['reference']
        sizes = set()
        for f in files:
            z = np.load(f)
            sizes.add(tuple(z['image'].shape[1::-1]))
            fp = fingerprint(z)
            prints.setdefault(fp, []).append((g['id'], f.name))
            entry['captures'].append(dict(name=f.name, file_sha256=sha(f), content_fingerprint=fp))
        entry['image_size_wh'] = sorted(sizes)
        entry['reference_sha256'] = sha(WORKSPACE / g['reference'])
        registry.append(entry)
        print(g['id'], len(files), flush=True)
    duplicates = {fp: v for fp, v in prints.items() if len({x[0] for x in v}) > 1}
    similarity = scene_similarity(images)
    payload = dict(schema_version=1, workspace_root_relative_to_repository='../..', groups=registry, excluded=EXCLUDED,
                   cross_group_duplicate_captures=duplicates, scene_similarity_orb=similarity,
                   independence_note=('Groups are NOT claimed statistically independent. Captures within a group are one static scene; devices may share a '
                                      'laboratory, the same room layout and the same LiDAR model; Nov 5 groups are likely the same unit as pair_1.'))
    Path(args.registry).write_text(json.dumps(payload, indent=2) + '\n', encoding='utf-8')
    stem = Path(args.output)
    stem.parent.mkdir(parents=True, exist_ok=True)
    lines = ['# Dataset audit (generated by tools/audit_datasets_v3.py)', '',
             '| Group | Device | Session | State | Captures | Image | Brightness | Saturated | Edge density | Range p5/p50/p95 (m) | Az std / El std (deg) | Prior use |',
             '|---|---|---|---|---:|---|---:|---:|---:|---|---|---|']
    for e in registry:
        d = e['descriptors']
        lines.append(f"| {e['id']} | {e['device']} | {e['session']} | {e['state']} | {e['capture_count']} | {e['image_size_wh'][0][0]}x{e['image_size_wh'][0][1]} | "
                     f"{d['brightness']:.2f} | {d['saturated_share']:.3f} | {d['edge_density']:.3f} | {'/'.join(f'{x:.1f}' for x in d['range_p5_p50_p95_m'])} | "
                     f"{d['azimuth_std_deg']:.0f} / {d['elevation_std_deg']:.0f} | {'; '.join(e['used_in']) or 'none'} |")
    lines += ['', f"Cross-group duplicate captures found by content hash: **{len(duplicates)}**.", '', '## Scene similarity (ORB homography inliers between group median images)', '',
              '| Pair | ratio-test matches | homography inliers |', '|---|---:|---:|']
    for k, v in similarity.items():
        lines.append(f"| {k} | {v['ratio_matches'] if v else '-'} | {v['homography_inliers'] if v else '-'} |")
    lines += ['', '## Excluded', ''] + [f"* {x['id']}: {x['reason']}" for x in EXCLUDED]
    stem.with_suffix('.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
