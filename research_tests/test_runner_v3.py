"""Experimental runner regression and offline integration tests."""
import copy
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import unittest
import numpy as np
from test_mathematics import reference
from research_calibration.geometry import parameters
from research_calibration.parameter_hypotheses import parameter_scales
from research_calibration.fault_diagnostics_v3.runner import diagnose_from_records, diagnose_v3


class RunnerV3Tests(unittest.TestCase):
    def fixture(self, supported='RT', ambiguity=None):
        cal = reference(); p = parameters(cal); scales = parameter_scales(p)
        caps = [SimpleNamespace(name=str(i)) for i in range(4)]
        bundle = SimpleNamespace(caps=caps, size=[484, 366], circle=dict(cx=242, cy=183, radius=180))
        records = [dict(stage='fold', hypothesis=supported, test_id=str(i), success=True,
                        parameters=p+scales*np.r_[2., np.zeros(12)]) for i in range(4)]
        base = dict(status='DRIFT_AMBIGUOUS', supported=[supported], ambiguity_set=ambiguity or [supported],
                    hypothesis=None, reason='fixture', counterfactuals={supported: dict(edge=dict(median=.1))},
                    informative_captures=dict(edge=[c.name for c in caps]))
        payload = dict(evidence={}, production=dict(decision_status='KEEP_CURRENT'))
        return cal, p, scales, bundle, records, base, payload

    def test_geometry_cannot_promote_unsupported_subset_to_unique_diagnosis(self):
        cal, p, scales, bundle, records, base, payload = self.fixture()
        a = np.zeros((60, 13)); a[:, 0] = np.tile([-1, 1], 30)
        sig = dict(jacobian=a/scales, rows=60, scene=dict(valid=False))
        with patch('research_calibration.fault_diagnostics_v3.runner.decide_experimental', return_value=base), \
             patch('research_calibration.fault_diagnostics_v3.runner.capture_signature', return_value=sig):
            result = diagnose_from_records(cal, bundle, records, payload)
        self.assertEqual(result['status'], 'DRIFT_AMBIGUOUS')
        self.assertIn('RT', result['ambiguity_set'])

    def test_fold_aliases_cannot_be_rejected_by_coordinate_median(self):
        cal, p, scales, bundle, records, base, payload = self.fixture('R')
        a = np.zeros((60, 13)); a[:, :3] = np.tile(np.eye(3), (20, 1))
        a[:, 8] = a[:, :3]@np.array([1, -1, 0]); a[:, 9] = a[:, :3]@np.array([1, 0, -1])
        for row, d in zip(records, ([2, -1, -1], [-1, 2, -1], [-1, -1, 2], [2, -1, -1])):
            row['parameters'] = p.copy(); row['parameters'][:3] += scales[:3]*d
        sig = dict(jacobian=a/scales, rows=60, scene=dict(valid=False))
        with patch('research_calibration.fault_diagnostics_v3.runner.decide_experimental', return_value=base), \
             patch('research_calibration.fault_diagnostics_v3.runner.capture_signature', return_value=sig):
            result = diagnose_from_records(cal, bundle, records, payload)
        self.assertEqual(result['status'], 'DRIFT_AMBIGUOUS')
        self.assertIn('I', result['ambiguity_set'])

    def test_nominal_end_to_end_preserves_reference_and_baselines(self):
        from test_fault_diagnostics import synthetic_capture, SIZE, CIRCLE
        from research_calibration.config import ResearchConfig
        cal = reference(); before = copy.deepcopy(cal)
        bundle = SimpleNamespace(caps=[synthetic_capture(30+i, name='v3_'+str(i)) for i in range(6)],
                                 size=SIZE, circle=CIRCLE, metadata=[], source='synthetic numerical fixture')
        with tempfile.TemporaryDirectory() as folder:
            result = diagnose_v3(cal, 'unused', output=folder, bundle=bundle, config=ResearchConfig(bootstrap_reps=50))
            self.assertTrue((Path(folder)/'fault_diagnostics_v3.json').exists())
            self.assertTrue((Path(folder)/'baseline'/'fault_diagnostics.json').exists())
            self.assertTrue((Path(folder)/'baseline'/'assessment.json').exists())
        self.assertFalse(result['v3']['hardware_write_authorized'])
        self.assertEqual(cal, before)
        self.assertNotIn(result['v3']['status'], ('DRIFT_SUPPORTED', 'UPDATE_CANDIDATE_VALIDATED'))

    def test_final_candidate_check_replaces_best_bank_when_minimal_hypothesis_differs(self):
        """A best RTI fold bank must test the actual final R candidate's effect."""
        cal = reference(); p = parameters(cal)
        caps = [SimpleNamespace(name=str(i)) for i in range(7)]
        bundle = SimpleNamespace(caps=caps, size=[484, 366], circle=dict(cx=242, cy=183, radius=180))
        records = []
        for hypothesis, rotation in [('R', [.02, 0., 0.]), ('RTI', [0., .03, 0.])]:
            old = p.copy(); old[:3] = rotation
            records.extend(dict(stage='fold', hypothesis=hypothesis, test_id=str(i), success=True,
                                parameters=old.copy()) for i in range(4))
        records.append(dict(stage='final', hypothesis='RTI', outer_ids=['4', '5', '6']))
        candidate = p.copy(); candidate[:3] = [.004, .005, .006]
        diagnosis = dict(status='DRIFT_SUPPORTED', hypothesis='R', ambiguity_set=['R'],
                         best_evidence_hypothesis='RTI', uncertainty=dict(calibrated=False),
                         update_recommended=False, hardware_write_authorized=False)
        # A changed final correction is now R/I ambiguous; even passing outer
        # evidence and estimability must not validate this candidate as unique R.
        candidate_check = dict(diagnosis, status='DRIFT_AMBIGUOUS', hypothesis=None, ambiguity_set=['R', 'I'])
        payload = dict(experimental=dict(proposed=dict(status='DRIFT_AMBIGUOUS')),
                       production=dict(status='KEEP_CURRENT'), cost={}, persistence=dict(status='UNAVAILABLE'))
        def baseline(*args, records_out, **kwargs):
            records_out.extend(copy.deepcopy(records))
            return payload, SimpleNamespace()
        fitted = dict(success=True, parameters=candidate, supported_update=True,
                      uncertainty=dict(status='CONDITIONAL_ONLY'))
        validation = dict(available=True, edge_confirms=True, intensity_contradicts=False)
        prefix = 'research_calibration.fault_diagnostics_v3.runner.'
        with tempfile.TemporaryDirectory() as folder, \
             patch(prefix+'assess_with_diagnostics', side_effect=baseline), \
             patch(prefix+'diagnose_from_records', side_effect=[copy.deepcopy(diagnosis), candidate_check]) as diagnose, \
             patch(prefix+'_training_selection', return_value=(caps[:4], {})), \
             patch(prefix+'fit_hypothesis', return_value=fitted), \
             patch(prefix+'outer_evidence', return_value=validation), \
             patch(prefix+'evaluate_capture', return_value=dict(coverage=1.)):
            result = diagnose_v3(cal, 'unused', output=folder, bundle=bundle, write=False)
        self.assertEqual(diagnose.call_count, 2)
        checked_records = diagnose.call_args_list[1].args[2]
        best_bank = [r for r in checked_records if r.get('stage') == 'fold' and r['hypothesis'] == 'RTI']
        self.assertEqual(len(best_bank), 4)
        for row in best_bank:
            np.testing.assert_allclose(row['parameters'], candidate,
                                       err_msg='Final geometry check reused stale RTI effects instead of the actual R candidate')
        self.assertFalse(result['v3']['update_recommended'])
        self.assertEqual(result['v3']['candidate_geometry_check']['ambiguity_set'], ['R', 'I'])


if __name__ == '__main__':
    unittest.main()
