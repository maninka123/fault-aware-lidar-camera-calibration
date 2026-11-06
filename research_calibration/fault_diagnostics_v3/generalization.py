"""Grouped generalization framework: registry validation, leakage-free folds, frozen-configuration guard, per-group reporting.

The unit of independence is a *group* (a recording of one device in one session and state), never a capture and never a perturbation of a
recording. Groups are clustered into *scenes* by measured image similarity, because several devices photographed the same room. Nothing here
fits anything; it guards the experimental procedure.

Declared roles of the data in an evaluation:

  training group   its results may inform a choice (a variant, a constant) -- never a held-out group's;
  held-out group   scored only; its captures, anchor, descriptors and results are not used for any choice, normalization or selection;
  anchor           a per-group evaluation-truth device (the group's reference refined on that group's own captures). It defines the injected
                   condition and the scoring, is never given to any method, and is never reused across groups.
"""
from dataclasses import dataclass, asdict, field
import hashlib
import json
from pathlib import Path
import numpy as np


class LeakageError(ValueError):
    """The evaluation design would let held-out information reach a decision."""


class FrozenConfigChanged(RuntimeError):
    """A constant or source file changed after the protocol was frozen: this is a new development round, not a test."""


# ------------------------------------------------------------------ registry
def load_registry(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def validate_registry(registry, *, require_fingerprints=True):
    """Raise LeakageError for overlapping capture groups, reused references across devices or mislabelled prior use."""
    groups = registry['groups']
    for g in groups:
        absent = [k for k in ('id', 'device', 'session', 'capture_count', 'captures', 'reference_sha256') if k not in g]
        if absent:
            raise LeakageError(f"Registry group {g.get('id', '?')} lacks required fields: {', '.join(absent)}")
    ids = [g['id'] for g in groups]
    if len(set(ids)) != len(ids):
        raise LeakageError('Duplicate group identifiers')
    seen_fp, seen_name = {}, {}
    for g in groups:
        if g['capture_count'] != len(g['captures']):
            raise LeakageError(f"{g['id']}: capture_count does not match its capture list")
        for c in g['captures']:
            if require_fingerprints and not c.get('content_fingerprint'):
                raise LeakageError(f"{g['id']}: capture without a content fingerprint cannot be checked for overlap")
            for table, key in ((seen_fp, c.get('content_fingerprint')), (seen_name, c['name'])):
                if key is None:
                    continue
                if key in table and table[key] != g['id']:
                    raise LeakageError(f"Capture {c['name']} appears in groups {table[key]} and {g['id']}: overlapping capture groups")
                table[key] = g['id']
    # A reference calibration shared by groups of different devices would let one device's reference anchor another's.
    by_reference = {}
    for g in groups:
        by_reference.setdefault(g['reference_sha256'], set()).add(g['device'])
    for reference, devices in by_reference.items():
        if len(devices) > 1:
            raise LeakageError(f'One reference calibration is shared by different devices {sorted(devices)}: reused calibration anchor')
    for g in groups:
        design_use = [u for u in g.get('used_in', []) if u.startswith(('V2', 'V3', 'pairing'))]
        if g.get('role') == 'not_used_in_design' and design_use:
            raise LeakageError(f"{g['id']} is declared not used in design but lists: {design_use}")
        if g.get('role') == 'development' and not design_use:
            raise LeakageError(f"{g['id']} is declared development data but lists no design use")
    return True


def scene_clusters(registry, min_inliers=20):
    """Single-linkage clusters of groups whose median images share at least ``min_inliers`` homography inliers (ORB audit)."""
    ids = [g['id'] for g in registry['groups']]
    parent = {i: i for i in ids}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for pair, value in registry.get('scene_similarity_orb', {}).items():
        a, b = pair.split('|')
        if value and value['homography_inliers'] >= min_inliers and a in parent and b in parent:
            parent[find(a)] = find(b)
    clusters = {}
    for i in ids:
        clusters.setdefault(find(i), []).append(i)
    return {f'scene_{k + 1}': sorted(v) for k, v in enumerate(sorted(clusters.values(), key=lambda v: sorted(v)[0]))}


def group_key(registry, kind, min_inliers=20):
    """Map group id -> value of the grouping key: 'group', 'device', 'session' or 'scene'."""
    groups = registry['groups']
    if kind == 'group':
        return {g['id']: g['id'] for g in groups}
    if kind in ('device', 'session'):
        return {g['id']: g[kind] for g in groups}
    if kind == 'scene':
        out = {}
        for name, members in scene_clusters(registry, min_inliers).items():
            for m in members:
                out[m] = name
        return out
    raise ValueError('Unknown grouping key ' + kind)


def folds(registry, kind, min_inliers=20):
    """Leave-one-<kind>-out folds: {held_out: [group ids], training: [group ids]}; training never shares the held-out key."""
    key = group_key(registry, kind, min_inliers)
    out = []
    for value in sorted(set(key.values())):
        held = sorted(g for g, v in key.items() if v == value)
        train = sorted(g for g, v in key.items() if v != value)
        out.append(dict(kind=kind, value=value, held_out=held, training=train))
    return out


def assert_no_leakage(fold, registry, min_inliers=20):
    """The held-out groups must share no capture, device, session or scene (as per the fold's own key) with any training group."""
    by_id = {g['id']: g for g in registry['groups']}
    held = set(fold['held_out']); train = set(fold['training'])
    if held & train:
        raise LeakageError('A group is both held out and used for training')
    names = {c['content_fingerprint'] for g in train for c in by_id[g]['captures']}
    for g in held:
        if names & {c['content_fingerprint'] for c in by_id[g]['captures']}:
            raise LeakageError(f'Held-out group {g} shares a capture with the training groups')
    key = group_key(registry, fold['kind'], min_inliers)
    if {key[g] for g in held} & {key[g] for g in train}:
        raise LeakageError(f"Held-out {fold['kind']} {fold['value']} is also present in the training groups")
    return True


# ------------------------------------------------------------------ method inputs versus evaluation truth
@dataclass(frozen=True)
class TrialInput:
    """Everything a method may see for one trial: the calibration under diagnosis and the captures. Nothing else."""
    current_calibration: dict
    captures: tuple
    group_id: str = ''


@dataclass(frozen=True)
class TrialTruth:
    """Evaluation-only: the anchor and the injected change. Never passed to a method."""
    anchor_calibration: dict
    injected_groups: tuple
    anchor_capture_names: tuple = field(default=())


def method_input_fields():
    return tuple(TrialInput.__dataclass_fields__)


def validate_anchor_provenance(provenance, group):
    """An anchor must be built from its own group's captures only (no reuse across groups, no held-out data)."""
    own = {c['name'] for c in group['captures']}
    used = set(provenance.get('captures', []))
    if not used or not used <= own:
        raise LeakageError(f"Anchor of {group['id']} uses captures outside its own group: {sorted(used - own)}")
    return True


# ------------------------------------------------------------------ frozen configuration
def canonical_hash(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode('utf-8')).hexdigest()


def file_hashes(paths, root):
    # Line endings are normalised so a checkout that converts LF to CRLF does not look like a change of the frozen source.
    return {str(Path(p).as_posix()): hashlib.sha256((Path(root) / p).read_bytes().replace(b'\r\n', b'\n')).hexdigest() for p in paths}


def check_frozen(frozen, current_constants, current_sources):
    """Raise FrozenConfigChanged unless constants and source files equal those recorded at the freeze."""
    if canonical_hash(current_constants) != frozen['constants_sha256']:
        raise FrozenConfigChanged('Constants differ from the frozen protocol; any change after seeing results starts a new development round')
    changed = sorted(p for p, h in frozen['source_sha256'].items() if current_sources.get(p) != h)
    if changed:
        raise FrozenConfigChanged('Source files changed after the freeze: ' + ', '.join(changed))
    return True


# ------------------------------------------------------------------ per-group reporting
METRICS = ('no_change_alarms', 'no_change_trials', 'detections', 'drift_trials', 'exact', 'wrong_unique', 'ambiguous_with_truth')


def group_metrics(trials, method):
    """Counts for one method over trials that all belong to one group. Trials: dicts with condition_type and a score dict per method."""
    quiet = [t for t in trials if t['condition_type'] != 'drift' and method in t['scores']]
    drift = [t for t in trials if t['condition_type'] == 'drift' and method in t['scores']]
    s = lambda rows, k: int(sum(bool(r['scores'][method][k]) for r in rows))
    return dict(no_change_alarms=s(quiet, 'alarm'), no_change_trials=len(quiet), detections=s(drift, 'alarm'), drift_trials=len(drift),
                exact=s(drift, 'exact'), wrong_unique=s(quiet + drift, 'wrong'), ambiguous_with_truth=s(drift, 'ambiguous_has_truth'))


def rates(m):
    d = max(m['drift_trials'], 1); q = max(m['no_change_trials'], 1)
    return dict(false_alarm_rate=m['no_change_alarms'] / q, detection_rate=m['detections'] / d, exact_rate=m['exact'] / d,
                wrong_rate=m['wrong_unique'] / max(m['drift_trials'] + m['no_change_trials'], 1))


def worst_and_gap(per_group, rate_name, higher_is_better, held_out=None):
    """Worst group (by the metric's direction) and the generalization gap: mean over other groups minus the held-out/worst group."""
    if not per_group:
        raise ValueError('No groups to compare')
    if held_out is not None and held_out not in per_group:
        raise ValueError(f'Held-out group {held_out} has no results')
    values = {g: rates(m)[rate_name] for g, m in per_group.items()}
    pick = (min if higher_is_better else max)
    worst = pick(values, key=values.get)
    target = held_out or worst
    others = [v for g, v in values.items() if g != target]
    gap = (np.mean(others) - values[target]) if higher_is_better else (values[target] - np.mean(others))
    return dict(worst_group=worst, worst_value=values[worst], target=target, others_mean=float(np.mean(others)) if others else None,
                gap=float(gap) if others else None)


# ------------------------------------------------------------------ leave-one-group-out selection
def selection_cost(m):
    """Declared before any run: fewer false alarms plus wrong labels first, then more detections, then more exact attributions."""
    return (m['no_change_alarms'] + m['wrong_unique'], -m['detections'], -m['exact'])


def select_variant(metrics_by_group, variants, training_groups):
    """Choose the variant with the lowest summed cost over TRAINING groups only. ``metrics_by_group[g][variant]`` is read for g in training."""
    if not training_groups:
        raise ValueError('No training groups: a variant cannot be selected without evidence')
    if not variants:
        raise ValueError('No variants to choose from')
    best, best_cost = None, None
    for v in variants:
        parts = [selection_cost(metrics_by_group[g][v]) for g in training_groups]
        cost = tuple(sum(p[i] for p in parts) for i in range(3))
        if best_cost is None or cost < best_cost:
            best, best_cost = v, cost
    return best
