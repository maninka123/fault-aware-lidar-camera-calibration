"""Admission rules and freeze checks for genuinely new (unseen) groups.

A new group is admitted as ``unseen`` only if nothing in this repository has used it: no listed prior use, no capture that matches a known group
by content, a declared sensor description, and a measured scene-novelty verdict (a new device in an old scene is cross-device, not cross-scene).
The run itself needs a *committed* freeze of the group list, their capture fingerprints and the study constants, so constants cannot be adjusted
after the outcome of an unseen group is known.
"""
import subprocess
from pathlib import Path
from .generalization import LeakageError, FrozenConfigChanged, canonical_hash, scene_clusters

SENSOR_FIELDS = ('camera_model', 'lidar_model', 'lidar_scan_pattern', 'image_size_wh')


def admit_unseen(registry, candidate, similarity_to_known=None, min_inliers=20):
    """Return the registry with ``candidate`` appended, or raise LeakageError. ``similarity_to_known`` maps known group id -> ORB homography inliers."""
    if candidate.get('role') != 'unseen' or candidate.get('used_in'):
        raise LeakageError('An unseen group must have role "unseen" and no prior use of any kind')
    if candidate['id'] in {g['id'] for g in registry['groups']}:
        raise LeakageError('Group identifier already registered')
    missing = [f for f in SENSOR_FIELDS if not candidate.get(f)]
    if missing:
        raise LeakageError('Declare the sensor configuration before admission (missing: ' + ', '.join(missing) + ')')
    known = {c['content_fingerprint'] for g in registry['groups'] for c in g['captures']}
    shared = [c['name'] for c in candidate['captures'] if c['content_fingerprint'] in known]
    if shared:
        raise LeakageError('Captures already present in a known group (not new data): ' + ', '.join(shared[:5]))
    out = dict(registry, groups=list(registry['groups']) + [candidate])
    sim = dict(registry.get('scene_similarity_orb', {}))
    for gid, inliers in (similarity_to_known or {}).items():
        sim[f"{gid}|{candidate['id']}"] = dict(ratio_matches=0, homography_inliers=int(inliers))
    out['scene_similarity_orb'] = sim
    cluster = next(m for m in scene_clusters(out, min_inliers).values() if candidate['id'] in m)
    candidate['scene_is_new'] = len(cluster) == 1
    candidate['scene_cluster_members'] = [m for m in cluster if m != candidate['id']]
    return out


def sensors_differ(registry, candidate):
    """Which sensor fields differ from every known group (what an unseen result can say about cross-sensor behaviour)."""
    known = [g for g in registry['groups'] if g.get('camera_model') or g.get('lidar_model')]
    out = {}
    for f in SENSOR_FIELDS:
        values = {str(g.get(f)) for g in known if g.get(f)}
        out[f] = bool(values) and str(candidate.get(f)) not in values
    return out


def git_committed_and_clean(path, repo):
    """True when the file is tracked and has no uncommitted change (a freeze that exists only in the working tree is not a freeze)."""
    tracked = subprocess.run(['git', 'ls-files', '--error-unmatch', str(path)], cwd=repo, capture_output=True, text=True).returncode == 0
    dirty = bool(subprocess.run(['git', 'status', '--porcelain', '--', str(path)], cwd=repo, capture_output=True, text=True).stdout.strip())
    return tracked and not dirty


def check_unseen_freeze(frozen, registry, current_constants, group_ids):
    """The unseen freeze must name exactly these groups, with unchanged capture fingerprints, and the same constants as the development freeze."""
    if sorted(frozen['groups']) != sorted(group_ids):
        raise FrozenConfigChanged('The groups to run differ from the frozen unseen group list')
    by_id = {g['id']: g for g in registry['groups']}
    for gid in group_ids:
        now = sorted(c['content_fingerprint'] for c in by_id[gid]['captures'])
        if now != frozen['fingerprints'][gid]:
            raise FrozenConfigChanged(f'Captures of {gid} changed after the freeze')
        if by_id[gid].get('role') != 'unseen' or by_id[gid].get('used_in'):
            raise LeakageError(f'{gid} is no longer an unseen group')
    if canonical_hash(current_constants) != frozen['constants_sha256']:
        raise FrozenConfigChanged('Study constants changed after the unseen freeze')
    return True
