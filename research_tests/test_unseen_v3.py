"""Admission and freeze rules for genuinely new groups (synthetic registries with known answers)."""
import copy
import unittest
from research_calibration.fault_diagnostics_v3 import generalization as G, unseen as U


def known(gid, names, device='d1', session='s1'):
    return dict(id=gid, device=device, session=session, role='development', used_in=['V3 development'], reference_sha256='r' + gid,
                capture_count=len(names), captures=[dict(name=n, content_fingerprint='fp_' + n) for n in names],
                camera_model='fisheye-A', lidar_model='avia', lidar_scan_pattern='rosette', image_size_wh=[[484, 366]])


def candidate(gid='new', names=('n1', 'n2'), **over):
    c = dict(id=gid, device='d9', session='s9', role='unseen', used_in=[], reference_sha256='rnew', capture_count=len(names),
             captures=[dict(name=n, content_fingerprint='fp_' + n) for n in names], camera_model='fisheye-A', lidar_model='avia',
             lidar_scan_pattern='rosette', image_size_wh=[[484, 366]])
    c.update(over)
    return c


class Admission(unittest.TestCase):
    def reg(self):
        return dict(groups=[known('a', ['a1', 'a2'])], scene_similarity_orb={})

    def test_a_clean_group_is_admitted_and_its_scene_novelty_is_measured(self):
        out = U.admit_unseen(self.reg(), candidate(), {'a': 2})
        self.assertTrue(out['groups'][-1]['scene_is_new'])
        out = U.admit_unseen(self.reg(), candidate(), {'a': 40})
        self.assertFalse(out['groups'][-1]['scene_is_new'])                 # same scene as a known group: cross-device, not cross-scene
        self.assertEqual(out['groups'][-1]['scene_cluster_members'], ['a'])

    def test_prior_use_of_any_kind_is_refused(self):
        with self.assertRaises(G.LeakageError):
            U.admit_unseen(self.reg(), candidate(used_in=['desktop-app checks only']))
        with self.assertRaises(G.LeakageError):
            U.admit_unseen(self.reg(), candidate(role='not_used_in_design'))

    def test_a_capture_already_in_a_known_group_is_not_new_data(self):
        with self.assertRaises(G.LeakageError):
            U.admit_unseen(self.reg(), candidate(names=('n1', 'a2')))

    def test_the_sensor_configuration_must_be_declared(self):
        with self.assertRaises(G.LeakageError):
            U.admit_unseen(self.reg(), candidate(lidar_model=''))

    def test_cross_sensor_claims_need_a_sensor_that_differs(self):
        r = self.reg()
        self.assertFalse(any(U.sensors_differ(r, candidate()).values()))     # same camera and LiDAR: nothing cross-sensor can be said
        self.assertTrue(U.sensors_differ(r, candidate(lidar_model='other', lidar_scan_pattern='repetitive'))['lidar_model'])

    def test_a_duplicate_identifier_is_refused(self):
        with self.assertRaises(G.LeakageError):
            U.admit_unseen(self.reg(), candidate(gid='a'))


class FreezeCheck(unittest.TestCase):
    def setUp(self):
        self.reg = dict(groups=[candidate('u1'), candidate('u2', names=('m1',))])
        self.constants = dict(x=1)
        self.frozen = dict(groups=['u1', 'u2'], fingerprints={'u1': ['fp_n1', 'fp_n2'], 'u2': ['fp_m1']}, constants_sha256=G.canonical_hash(self.constants))

    def test_matching_freeze_passes(self):
        self.assertTrue(U.check_unseen_freeze(self.frozen, self.reg, self.constants, ['u1', 'u2']))

    def test_a_different_group_list_is_refused(self):
        with self.assertRaises(G.FrozenConfigChanged):
            U.check_unseen_freeze(self.frozen, self.reg, self.constants, ['u1'])

    def test_changed_captures_or_constants_are_refused(self):
        reg = copy.deepcopy(self.reg); reg['groups'][0]['captures'][0]['content_fingerprint'] = 'other'
        with self.assertRaises(G.FrozenConfigChanged):
            U.check_unseen_freeze(self.frozen, reg, self.constants, ['u1', 'u2'])
        with self.assertRaises(G.FrozenConfigChanged):
            U.check_unseen_freeze(self.frozen, self.reg, dict(x=2), ['u1', 'u2'])

    def test_a_group_that_acquired_prior_use_is_refused(self):
        reg = copy.deepcopy(self.reg); reg['groups'][0]['used_in'] = ['tuning']
        with self.assertRaises(G.LeakageError):
            U.check_unseen_freeze(self.frozen, reg, self.constants, ['u1', 'u2'])


if __name__ == '__main__':
    unittest.main()
