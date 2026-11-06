"""Known-answer mathematical tests, distinct from recorded-data performance."""
import unittest
import numpy as np
from research_calibration.fault_diagnostics_v3.config import SignatureConfig
from research_calibration.fault_diagnostics_v3.hypothesis_separation import whiten, effect_separation, signature_report
from research_calibration.fault_diagnostics_v3.diagnostic_inference import infer_signatures
from research_calibration.fault_diagnostics_v3.active_selection import select_observations
from research_calibration.fault_diagnostics_v3.update_policy import update_contract, conservative_attribution
from research_calibration.fault_diagnostics_v3.evaluation import score_decision


class SignatureInferenceTests(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(7)
        self.a = rng.normal(size=(240, 13))
        self.ids = np.repeat(np.arange(4), 60)

    def test_known_single_and_joint_faults(self):
        for h, cols in [('R', [0, 1]), ('T', [3, 4]), ('I', [8, 9]), ('RT', [0, 3]),
                        ('RI', [1, 8]), ('TI', [4, 9]), ('RTI', [2, 5, 10])]:
            with self.subTest(h=h):
                d = np.zeros(13); d[cols] = 2.
                result = infer_signatures(self.a, self.a@d, np.ones(13), capture_ids=self.ids)
                self.assertEqual((result['status'], result['hypothesis']), ('DRIFT_SUPPORTED', h))

    def test_exact_alias_abstains_and_reports_both(self):
        self.a[:, 8] = self.a[:, 0]
        result = infer_signatures(self.a, 2*self.a[:, 0], np.ones(13), capture_ids=self.ids)
        self.assertEqual(result['status'], 'DRIFT_AMBIGUOUS')
        self.assertEqual(set(result['ambiguity_set']), {'R', 'I'})

    def test_nuisance_only_is_not_drift(self):
        result = infer_signatures(self.a, self.a[:, 12]*3, np.ones(13), capture_ids=self.ids)
        self.assertEqual(result['status'], 'KEEP_CONFIRMED')

    def test_rank_deficient_and_insufficient_rows(self):
        result = infer_signatures(np.zeros((60, 13)), np.zeros(60), np.ones(13))
        self.assertEqual(result['status'], 'KEEP_CONFIRMED')
        self.assertEqual(infer_signatures(self.a[:10], np.zeros(10), np.ones(13))['status'], 'INSUFFICIENT_EVIDENCE')

    def test_invalid_capture_ids_columns_and_too_few_blocks(self):
        with self.assertRaises(ValueError):
            infer_signatures(self.a[:, :12], np.zeros(240), np.ones(12))
        with self.assertRaises(ValueError):
            infer_signatures(self.a, np.zeros(240), np.ones(13), capture_ids=np.full(240, np.nan))
        self.assertEqual(infer_signatures(self.a, np.zeros(240), np.ones(13), capture_ids=np.zeros(240))['status'], 'INSUFFICIENT_EVIDENCE')

    def test_normalization_and_covariance_units(self):
        scales = np.arange(1, 14.)
        a, y = whiten(self.a/scales, np.ones(240)*2, scales=scales, covariance=np.ones(240)*4)
        np.testing.assert_allclose(a, self.a/2)
        np.testing.assert_allclose(y, np.ones(240))
        effect = np.zeros(13); effect[0] = 2.
        one = effect_separation(self.a, effect, 'I')['rms']
        two = effect_separation(a*2, effect, 'I')['rms']
        self.assertAlmostEqual(one, two)

    def test_inference_thresholds_are_invariant_to_fallback_measurement_units(self):
        # This effect is above the detection threshold and near the geometric
        # ambiguity boundary. Dividing thresholds again by pixel_sigma would
        # change its diagnosis under an otherwise equivalent unit conversion.
        signal = .3*self.a[:, 0]
        baseline = infer_signatures(self.a, signal, np.ones(13), capture_ids=self.ids,
                                    config=SignatureConfig(pixel_sigma=1.))
        converted = infer_signatures(self.a*2, signal*2, np.ones(13), capture_ids=self.ids,
                                     config=SignatureConfig(pixel_sigma=2.))
        for key in ('status', 'hypothesis', 'ambiguity_set', 'supported'):
            self.assertEqual(baseline[key], converted[key], key)
        for hypothesis in baseline['fold_mse']:
            np.testing.assert_allclose(baseline['fold_mse'][hypothesis], converted['fold_mse'][hypothesis], atol=1e-12)

    def test_inference_thresholds_are_invariant_to_supplied_covariance_units(self):
        # Both diagonal and correlated covariance have measurement-unit squared
        # units. The fallback scale is irrelevant when covariance is supplied.
        a = self.a[:80]
        ids = np.repeat(np.arange(4), 20)
        signal = .3*a[:, 0]
        for covariance in (np.linspace(.8, 1.2, len(a)), .9*np.eye(len(a))+.1*np.ones((len(a), len(a)))):
            with self.subTest(full_covariance=covariance.ndim == 2):
                baseline = infer_signatures(a, signal, np.ones(13), covariance=covariance, capture_ids=ids,
                                            config=SignatureConfig(pixel_sigma=1.))
                converted = infer_signatures(a*2, signal*2, np.ones(13), covariance=covariance*4, capture_ids=ids,
                                             config=SignatureConfig(pixel_sigma=2.))
                for key in ('status', 'hypothesis', 'ambiguity_set', 'supported'):
                    self.assertEqual(baseline[key], converted[key], key)
                for hypothesis in baseline['fold_mse']:
                    np.testing.assert_allclose(baseline['fold_mse'][hypothesis], converted['fold_mse'][hypothesis], atol=1e-12)

    def test_full_correlated_covariance_matches_information(self):
        a = self.a[:40]
        covariance = .7*np.eye(40)+.3*np.ones((40, 40))
        w, _ = whiten(a, covariance=covariance)
        np.testing.assert_allclose(w.T@w, a.T@np.linalg.solve(covariance, a), rtol=1e-12, atol=1e-12)

    def test_common_correlated_repeats_do_not_add_independent_information(self):
        a = np.ones((10, 13))
        independent, _ = whiten(a)
        correlated, _ = whiten(a, covariance=.01*np.eye(10)+.99*np.ones((10, 10)))
        self.assertGreater(np.linalg.norm(independent[:, 0])**2, 9.)
        self.assertLess(np.linalg.norm(correlated[:, 0])**2, 1.02)

    def test_singular_covariance_and_nonfinite_inputs_refused(self):
        for covariance in [np.zeros(240), np.zeros((240, 240)), np.full(240, np.nan)]:
            with self.assertRaises(ValueError):
                whiten(self.a, covariance=covariance)
        with self.assertRaises(ValueError):
            whiten(self.a, scales=np.zeros(13))

    def test_actual_effect_not_minimum_angle(self):
        self.a[:, 8] = self.a[:, 0]
        d = np.zeros(13); d[1] = 2.
        report = signature_report(self.a, d)
        self.assertLess(min(report['principal_angles_deg']['I|R']), .001)
        self.assertGreater(report['distances']['I']['rms'], 1.)

    def test_shared_nuisance_is_profiled_after_stacking(self):
        a = np.zeros((4, 13)); a[:, 0] = [1, 1, -1, -1]; a[:, 12] = 1
        d = np.zeros(13); d[0] = 1
        self.assertAlmostEqual(effect_separation(a, d, 'KEEP')['rms'], 1.)
        self.assertAlmostEqual(effect_separation(a[:2], d, 'KEEP')['rms'], 0.)

    def test_selection_prefers_alias_breaking_capture_and_excludes_test(self):
        alias = np.zeros((8, 13)); alias[:, 0] = 1; alias[:, 8] = 1
        diverse = alias.copy(); diverse[4:, 8] = -1
        effects = {'R': np.eye(13)[0], 'I': np.eye(13)[8]}
        result = select_observations([alias, diverse, diverse*100], effects, [('R', 'I')], budget=1,
                                     capture_ids=['alias', 'diverse', 'outer'], training_ids=['alias', 'diverse'])
        self.assertEqual(result['selected_ids'], ['diverse'])
        self.assertEqual(result['excluded_ids'], ['outer'])

    def test_selection_zero_effect_is_honestly_zero(self):
        result = select_observations([self.a], {'R': np.zeros(13), 'I': np.zeros(13)}, [('R', 'I')], budget=1)
        self.assertEqual(result['scores']['worst_separation'], 0.)

    def test_update_requires_unique_support_uncertainty_disjoint_outer_and_coverage(self):
        diagnosis = dict(status='DRIFT_SUPPORTED', hypothesis='R')
        args = dict(candidate={'offline': True}, observable=True, uncertainty_status='CONDITIONAL_ONLY',
                    training_ids=['t'], validation_ids=['a', 'b', 'c'],
                    validation=dict(available=True, edge_confirms=True, coverage_passed=True))
        accepted = update_contract(diagnosis, **args)
        self.assertEqual(accepted['status'], 'UPDATE_CANDIDATE_VALIDATED')
        self.assertFalse(accepted['hardware_write_authorized'])
        args['validation_ids'] = ['t', 'b', 'c']
        self.assertFalse(update_contract(diagnosis, **args)['update_recommended'])
        diagnosis['status'] = 'DRIFT_AMBIGUOUS'
        self.assertFalse(update_contract(diagnosis, **args)['update_recommended'])

    def test_recorded_geometry_can_veto_but_never_promote_or_change_attribution(self):
        geometric = dict(status='DRIFT_SUPPORTED', hypothesis='R', ambiguity_set=['R'],
                         configuration=dict(geometric_signatures=True), signatures={}, fold_effects={},
                         update_recommended=True)
        cases = [
            (dict(status='DRIFT_AMBIGUOUS', hypothesis=None, ambiguity_set=['R', 'I']), geometric,
             'DRIFT_AMBIGUOUS', None, {'R', 'I'}),
            (dict(status='DRIFT_SUPPORTED', hypothesis='I', ambiguity_set=['I']), geometric,
             'DRIFT_AMBIGUOUS', None, {'R', 'I'}),
            (dict(status='DRIFT_SUPPORTED', hypothesis='R', ambiguity_set=['R']),
             dict(geometric, status='DRIFT_AMBIGUOUS', hypothesis=None, ambiguity_set=['R', 'T']),
             'DRIFT_AMBIGUOUS', None, {'R', 'T'}),
            (dict(status='DRIFT_SUPPORTED', hypothesis='R', ambiguity_set=['R']), geometric,
             'DRIFT_SUPPORTED', 'R', {'R'}),
            (dict(status='DRIFT_SUPPORTED', hypothesis='R', ambiguity_set=['R']),
             dict(geometric, fold_effects=None), 'DRIFT_AMBIGUOUS', None, {'R'}),
        ]
        for base, proposed, status, hypothesis, ambiguity in cases:
            with self.subTest(base=base['status'], proposed=proposed['status'], expected=status):
                result = conservative_attribution(base, proposed)
                self.assertEqual((result['status'], result['hypothesis']), (status, hypothesis))
                self.assertEqual(set(result['ambiguity_set']), ambiguity)
                self.assertFalse(result['update_recommended'])
                self.assertEqual(result['attribution_mode'], 'conservative_veto')

    def test_ambiguity_superset_is_not_exact_truth_coverage(self):
        result = score_decision(dict(status='DRIFT_AMBIGUOUS', ambiguity_set=['RTI']), ['R'])
        self.assertFalse(result['ambiguous_contains_truth'])


if __name__ == '__main__':
    unittest.main()
