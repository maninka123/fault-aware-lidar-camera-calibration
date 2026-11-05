"""Hand-specified linear algebra and capture-loss fixtures; no sensor simulation."""
import unittest

import numpy as np

from research_calibration.evidence_selection import select_captures
from research_calibration.decision_policy import decide


SCALES = np.ones(13)
GROUPS = {'R': [0], 'I': [6]}


def jac(rotation, intrinsic, nuisance=None):
    out = np.zeros((len(rotation), 13))
    out[:, 0], out[:, 6] = rotation, intrinsic
    if nuisance is not None:
        out[:, 12] = nuisance
    return out


class SelectionTests(unittest.TestCase):
    def test_training_pool_excludes_informative_heldout_capture(self):
        values = [[jac([1, 0], [0, 1])], [jac([1000, 0], [0, 1000])]]
        out = select_captures(values, SCALES, GROUPS, capture_ids=['fit', 'test'],
                              training_ids=['fit'], budget=1)
        self.assertEqual(out['selected_ids'], ['fit'])
        self.assertEqual(out['diagnostics']['excluded_ids'], ['test'])

    def test_duplicate_groups_have_zero_unique_contrast_even_at_large_scale(self):
        duplicate = jac([1e12, 2e12, 3e12], [1e12, 2e12, 3e12])
        out = select_captures([[duplicate]], SCALES, GROUPS)
        self.assertEqual(out['scores']['contrast'], 0.0)
        self.assertEqual(out['scores']['e_optimal'], 0.0)

    def test_profile_shared_nuisance_after_stacking_not_per_capture(self):
        # Each capture alone aliases rotation with nuisance. Opposite signs
        # across captures distinguish one shared nuisance from rotation.
        first = jac([1], [0], [1])
        second = jac([1], [0], [-1])
        one = select_captures([[first]], SCALES, {'R': [0]})
        both = select_captures([[first], [second]], SCALES, {'R': [0]}, budget=2)
        self.assertEqual(one['scores']['contrast'], 0.0)
        self.assertAlmostEqual(both['scores']['contrast'], 2.0)

    def test_worst_association_variant_rejects_deceptively_sharp_capture(self):
        aliased = jac([10, 10], [10, 10])
        sharp = jac([10, 0], [0, 10])
        stable = jac([1, 0], [0, 1])
        result = select_captures([[sharp, aliased], [stable, stable]], SCALES, GROUPS, budget=1)
        self.assertEqual(result['selected_indices'], [1])
        self.assertAlmostEqual(result['scores']['contrast'], 1.)

    def test_complementary_captures_resolve_individually_aliased_groups(self):
        result = select_captures([[jac([1], [1])], [jac([1], [-1])]], SCALES, GROUPS, budget=2)
        self.assertGreater(result['scores']['contrast'], 1.9)

    def test_scaling_and_deterministic_baselines(self):
        pool = [[jac([v, 0], [0, v])] for v in [1., 3., 2.]]
        for strategy in ['contrast', 'd_optimal', 'e_optimal']:
            out = select_captures(pool, SCALES, GROUPS, budget=1, strategy=strategy)
            self.assertEqual(out['selected_indices'], [1])
        a = select_captures(pool, SCALES, GROUPS, budget=2, strategy='random', seed=19)
        b = select_captures(pool, SCALES, GROUPS, budget=2, strategy='random', seed=19)
        self.assertEqual(a['selected_indices'], b['selected_indices'])
        self.assertEqual(len(select_captures(pool, SCALES, GROUPS, budget=1, strategy='all')['selected_ids']), 3)

    def test_feature_count_and_explicit_failures(self):
        pool = [[jac([1], [1])], [jac([1, 1], [1, -1])]]
        self.assertEqual(select_captures(pool, SCALES, GROUPS, budget=1,
                                        strategy='feature_count')['selected_indices'], [1])
        with self.assertRaises(ValueError):
            select_captures([[jac([np.nan], [1])]], SCALES, GROUPS)
        with self.assertRaises(ValueError):
            select_captures([pool[0], pool[1] * 2], SCALES, GROUPS)
        with self.assertRaises(ValueError):
            select_captures(pool, np.zeros(13), GROUPS)


class DecisionTests(unittest.TestCase):
    def policy(self, losses, groups=None, support=None, **kwargs):
        definitions = groups or {'KEEP': (), 'R': ('R',), 'I': ('I',), 'RI': ('R', 'I')}
        definitions = {k: definitions[k] for k in losses}
        return decide(losses, {k: len(v) for k, v in definitions.items()}, definitions,
                      support if support is not None else {'R': True, 'I': True}, **kwargs)

    def test_supported_candidate_still_requires_independent_outer_validation(self):
        out = self.policy({'KEEP': [10, 11, 12, 13], 'R': [5, 6, 7, 8]})
        self.assertEqual(out['status'], 'CANDIDATE_SUPPORTED')
        self.assertEqual(out['selected_hypothesis'], 'R')
        self.assertIn('independent outer validation', out['reason'])
        self.assertIn('not calibrated', out['uncertainty_scope'])
        self.assertTrue(out['candidate_improvement']['degenerate'])

    def test_nonnested_ties_retain_current(self):
        out = self.policy({'KEEP': [10.] * 5, 'R': [5.] * 5, 'I': [5.] * 5})
        self.assertEqual(out['status'], 'INSUFFICIENT_EVIDENCE')
        self.assertEqual(out['selected_hypothesis'], 'KEEP')
        self.assertEqual(set(out['ambiguity_set']), {'R', 'I'})

    def test_nested_tie_prefers_simpler_model(self):
        out = self.policy({'KEEP': [10.] * 5, 'R': [5.] * 5, 'RI': [5.] * 5})
        self.assertEqual(out['status'], 'CANDIDATE_SUPPORTED')
        self.assertEqual(out['selected_hypothesis'], 'R')

    def test_unsupported_attribution_retains_current_despite_loss_gain(self):
        out = self.policy({'KEEP': [10.] * 5, 'R': [5.] * 5}, support={'R': False})
        self.assertEqual(out['status'], 'INSUFFICIENT_EVIDENCE')
        self.assertTrue(out['retain_current'])

    def test_failed_or_unequal_folds_are_never_dropped(self):
        for bad in [dict(KEEP=[10.] * 4, R=[5., np.nan, 5., 5.]),
                    dict(KEEP=[10.] * 4, R=[5.] * 3), dict(R=[5.] * 4)]:
            self.assertEqual(self.policy(bad)['status'], 'INVALID')

    def test_small_sample_and_negligible_gain(self):
        self.assertEqual(self.policy({'KEEP': [10.] * 3, 'R': [5.] * 3})['status'], 'INSUFFICIENT_EVIDENCE')
        self.assertEqual(self.policy({'KEEP': [10.] * 5, 'R': [9.99] * 5})['status'], 'KEEP_CURRENT')

    def test_paired_uncertain_gains_do_not_force_update(self):
        out = self.policy({'KEEP': [10.] * 6, 'R': [1., 1., 1., 18., 18., 18.]})
        self.assertEqual(out['status'], 'INSUFFICIENT_EVIDENCE')
        self.assertEqual(out['selected_hypothesis'], 'KEEP')


if __name__ == '__main__':
    unittest.main()
