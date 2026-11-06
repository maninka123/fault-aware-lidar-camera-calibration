"""Leakage, overlap, anchor-reuse and tuning-on-test guards of the grouped generalization framework.

Synthetic registries have known answers; the real registry and the frozen file are checked when they exist.
"""
import copy
import inspect
import json
import sys
import unittest
from pathlib import Path
import numpy as np
from research_calibration.fault_diagnostics_v3 import generalization as G

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))


def group(gid, device, session, names, reference='r0', role='development', used=('V3 development',)):
    return dict(id=gid, device=device, session=session, state='on', role=role, used_in=list(used), reference_sha256=reference,
                capture_count=len(names), captures=[dict(name=n, content_fingerprint='fp_' + n) for n in names])


def registry():
    r = dict(groups=[group('a', 'dev1', 's1', ['a1', 'a2'], 'ra'), group('b', 'dev2', 's1', ['b1', 'b2'], 'rb'),
                     group('c', 'dev3', 's2', ['c1', 'c2'], 'rc', role='not_used_in_design', used=[]),
                     group('d', 'dev1', 's3', ['d1', 'd2'], 'ra', role='not_used_in_design', used=[])],
             scene_similarity_orb={'a|b': dict(ratio_matches=60, homography_inliers=30), 'a|c': dict(ratio_matches=5, homography_inliers=0),
                                   'b|c': dict(ratio_matches=4, homography_inliers=1), 'a|d': dict(ratio_matches=3, homography_inliers=0)})
    return r


class RegistryValidation(unittest.TestCase):
    def test_a_clean_registry_passes(self):
        self.assertTrue(G.validate_registry(registry()))

    def test_overlapping_capture_groups_are_rejected(self):
        r = registry()
        r['groups'][1]['captures'][0] = dict(name='b1', content_fingerprint='fp_a1')        # same content under another name
        with self.assertRaises(G.LeakageError):
            G.validate_registry(r)
        r = registry()
        r['groups'][1]['captures'][0]['name'] = 'a2'                                         # same capture name in two groups
        with self.assertRaises(G.LeakageError):
            G.validate_registry(r)

    def test_a_reference_calibration_shared_by_different_devices_is_a_reused_anchor(self):
        r = registry()
        r['groups'][1]['reference_sha256'] = 'ra'                                            # dev2 reuses dev1's reference
        with self.assertRaises(G.LeakageError):
            G.validate_registry(r)

    def test_the_same_device_may_reuse_its_own_reference_in_a_later_session(self):
        self.assertTrue(G.validate_registry(registry()))                                      # a and d: dev1, same reference

    def test_mislabelled_prior_use_is_rejected(self):
        r = registry()
        r['groups'][2]['used_in'] = ['V3 development']                                        # declared not_used_in_design
        with self.assertRaises(G.LeakageError):
            G.validate_registry(r)
        r = registry()
        r['groups'][0]['used_in'] = []                                                        # declared development but never used
        with self.assertRaises(G.LeakageError):
            G.validate_registry(r)

    def test_a_missing_fingerprint_cannot_be_checked_and_is_rejected(self):
        r = registry()
        del r['groups'][0]['captures'][0]['content_fingerprint']
        with self.assertRaises(G.LeakageError):
            G.validate_registry(r)


class Folds(unittest.TestCase):
    def test_devices_that_view_one_scene_are_one_scene_not_independent_scenes(self):
        clusters = G.scene_clusters(registry())
        self.assertIn(['a', 'b'], clusters.values())

    def test_every_fold_of_every_key_is_leak_free(self):
        r = registry()
        for kind in ('group', 'device', 'session', 'scene'):
            for fold in G.folds(r, kind):
                self.assertTrue(G.assert_no_leakage(fold, r))
                self.assertFalse(set(fold['held_out']) & set(fold['training']))

    def test_leave_one_scene_out_holds_out_all_groups_of_the_scene(self):
        r = registry()
        fold = next(f for f in G.folds(r, 'scene') if 'a' in f['held_out'])
        self.assertEqual(set(fold['held_out']), {'a', 'b'})
        self.assertNotIn('b', fold['training'])

    def test_a_fold_that_trains_on_the_held_out_scene_is_detected(self):
        r = registry()
        bad = dict(kind='scene', value='x', held_out=['a'], training=['b', 'c', 'd'])         # b shares a's scene
        with self.assertRaises(G.LeakageError):
            G.assert_no_leakage(bad, r)

    def test_a_fold_that_trains_on_the_held_out_device_or_session_is_detected(self):
        r = registry()
        with self.assertRaises(G.LeakageError):
            G.assert_no_leakage(dict(kind='device', value='dev1', held_out=['a'], training=['d', 'c']), r)
        with self.assertRaises(G.LeakageError):
            G.assert_no_leakage(dict(kind='session', value='s1', held_out=['a'], training=['b', 'c']), r)

    def test_a_shared_capture_between_held_out_and_training_is_detected(self):
        r = registry()
        r['groups'][2]['captures'][0]['content_fingerprint'] = 'fp_a1'                        # bypass validate_registry on purpose
        with self.assertRaises(G.LeakageError):
            G.assert_no_leakage(dict(kind='group', value='a', held_out=['a'], training=['c']), r)


class AnchorsAndInputs(unittest.TestCase):
    def test_an_anchor_built_from_foreign_captures_is_rejected(self):
        g = registry()['groups'][0]
        self.assertTrue(G.validate_anchor_provenance(dict(captures=['a1', 'a2']), g))
        with self.assertRaises(G.LeakageError):
            G.validate_anchor_provenance(dict(captures=['a1', 'b1']), g)
        with self.assertRaises(G.LeakageError):
            G.validate_anchor_provenance(dict(captures=[]), g)

    def test_methods_receive_a_calibration_and_captures_only(self):
        self.assertEqual(set(G.method_input_fields()), {'current_calibration', 'captures', 'group_id'})
        truth_fields = set(G.TrialTruth.__dataclass_fields__)
        self.assertTrue(truth_fields.isdisjoint(G.method_input_fields()))
        with self.assertRaises(Exception):
            G.TrialInput(dict(), ()).current_calibration = {}                                  # frozen dataclass

    def test_no_pairing_front_end_can_be_given_an_anchor(self):
        from analyze_attribution_root_cause_v3 import FRONT_ENDS
        for name, fn in FRONT_ENDS.items():
            names = list(inspect.signature(fn).parameters)
            self.assertEqual(names, ['cap', 'm', 'p'], name)                                   # capture, projection model, current parameters


class TuningOnTestData(unittest.TestCase):
    def test_selection_reads_training_groups_only(self):
        class Guarded(dict):
            def __init__(self, data, forbidden):
                super().__init__(data)
                self.forbidden = set(forbidden)

            def __getitem__(self, key):
                if key in self.forbidden:
                    raise AssertionError('held-out group was read during selection: ' + key)
                return super().__getitem__(key)
        zero = lambda a, w, d, e: dict(no_change_alarms=a, no_change_trials=4, detections=d, drift_trials=5, exact=e, wrong_unique=w, ambiguous_with_truth=0)
        data = {'train1': {'x': zero(0, 0, 5, 1), 'y': zero(2, 1, 5, 0)}, 'train2': {'x': zero(0, 0, 4, 1), 'y': zero(1, 1, 5, 1)},
                'held': {'x': zero(4, 4, 0, 0), 'y': zero(0, 0, 5, 5)}}
        chosen = G.select_variant(Guarded(data, ['held']), ['x', 'y'], ['train1', 'train2'])
        self.assertEqual(chosen, 'x')                                                          # the held-out group would have preferred y

    def test_a_changed_constant_or_source_after_the_freeze_is_refused(self):
        constants = dict(a=1, b=[1, 2])
        frozen = dict(constants_sha256=G.canonical_hash(constants), source_sha256={'f.py': 'h1'})
        self.assertTrue(G.check_frozen(frozen, constants, {'f.py': 'h1'}))
        with self.assertRaises(G.FrozenConfigChanged):
            G.check_frozen(frozen, dict(a=2, b=[1, 2]), {'f.py': 'h1'})
        with self.assertRaises(G.FrozenConfigChanged):
            G.check_frozen(frozen, constants, {'f.py': 'changed'})

    def test_file_hashes_ignore_line_ending_conversion(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / 'a.py').write_bytes(b'x = 1\ny = 2\n')
            h1 = G.file_hashes(['a.py'], folder)
            (Path(folder) / 'a.py').write_bytes(b'x = 1\r\ny = 2\r\n')
            self.assertEqual(h1, G.file_hashes(['a.py'], folder))

    @unittest.skipUnless((ROOT / 'docs/research/v3/FROZEN_GENERALIZATION.json').exists(), 'protocol not frozen yet')
    def test_the_real_constants_and_sources_still_match_the_frozen_protocol(self):
        """Fails when a frozen constant or source file is edited: that is tuning after the freeze, i.e. a new development round."""
        import run_generalization_v3 as R
        frozen = json.loads((ROOT / 'docs/research/v3/FROZEN_GENERALIZATION.json').read_text(encoding='utf-8'))
        self.assertTrue(G.check_frozen(frozen, R.constants(), G.file_hashes(R.SOURCES, ROOT)))


class Reporting(unittest.TestCase):
    def trials(self):
        mk = lambda ct, alarm, exact=False, wrong=False, amb=False: dict(condition_type=ct, scores=dict(m=dict(alarm=alarm, exact=exact, wrong=wrong, ambiguous_has_truth=amb)))
        return [mk('nominal', False), mk('nominal', True, wrong=True), mk('drift', True, exact=True), mk('drift', True, amb=True), mk('drift', False)]

    def test_group_metrics_count_correctly(self):
        m = G.group_metrics(self.trials(), 'm')
        self.assertEqual((m['no_change_alarms'], m['no_change_trials'], m['detections'], m['drift_trials'], m['exact'], m['wrong_unique'], m['ambiguous_with_truth']),
                         (1, 2, 2, 3, 1, 1, 1))

    def test_worst_group_and_gap(self):
        good = dict(no_change_alarms=0, no_change_trials=4, detections=4, drift_trials=4, exact=4, wrong_unique=0, ambiguous_with_truth=0)
        bad = dict(good, exact=0, no_change_alarms=2)
        per = dict(g1=good, g2=good, g3=bad)
        r = G.worst_and_gap(per, 'exact_rate', True)
        self.assertEqual((r['worst_group'], r['worst_value']), ('g3', 0.0))
        self.assertAlmostEqual(r['gap'], 1.0)
        r = G.worst_and_gap(per, 'false_alarm_rate', False)
        self.assertEqual(r['worst_group'], 'g3')

    @unittest.skipUnless((ROOT / 'research_data/groups_v3.json').exists(), 'registry not generated')
    def test_the_real_registry_has_no_overlap_and_groups_the_oct28_devices_as_one_scene(self):
        reg = G.load_registry(ROOT / 'research_data/groups_v3.json')
        self.assertTrue(G.validate_registry(reg))
        clusters = G.scene_clusters(reg)
        oct28 = {g['id'] for g in reg['groups'] if g['session'] == '2026-10-28'}
        self.assertTrue(any(oct28 <= set(members) for members in clusters.values()), 'Oct 28 devices must not be treated as independent scenes')
        for kind in ('group', 'device', 'session', 'scene'):
            for fold in G.folds(reg, kind):
                G.assert_no_leakage(fold, reg)


if __name__ == '__main__':
    unittest.main()
