"""Orchestration regressions using declared scalar-loss fixtures, not sensor benchmarks."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import numpy as np
from research_calibration.calibration_pipeline import assess
from research_calibration.config import ResearchConfig
from research_calibration.geometry import parameters
from test_mathematics import reference


class PipelineTests(unittest.TestCase):
    def run_fixture(self,bad_outer,folder,unsupported_final=False):
        original=reference(); untouched=copy.deepcopy(original)
        caps=[SimpleNamespace(name='capture_'+str(i)) for i in range(10)]
        cfg=ResearchConfig(bootstrap_reps=50)
        outer=set(np.random.default_rng(cfg.seed).permutation(10)[:3])
        outer_ids={caps[i].name for i in outer}; fitted_ids=[]
        bundle=SimpleNamespace(caps=caps,size=[484,366],circle=dict(cx=242,cy=183,radius=180),metadata=[],source='algebra fixture')
        def fit(training,model,baseline,hypothesis,config,strategy):
            fitted_ids.extend(c.name for c in training)
            p=baseline.copy(); p[0]=.1 if hypothesis.name=='R' else .2 if hypothesis.name!='KEEP' else 0
            return dict(success=True,parameters=p,rank=1 if hypothesis.name in ('KEEP','R') else 2,
                supported_update=not (unsupported_final and len(training)==7),
                attribution_support=dict(R=True,T=True,I=True),uncertainty=dict(status='CONDITIONAL_ONLY'),
                support=dict(basis=np.eye(13)[:,:1],unobservable_directions=np.eye(13)[:,1:]))
        def evaluate(cap,model,p,baseline,cap_px):
            loss=1. if p[0]==0 else .5 if p[0]==.1 else .7
            if bad_outer and cap.name in outer_ids and p[0]!=0: loss=2.
            return dict(valid=True,loss=loss,capped_edge_rmse_px=loss**.5,coverage=1.,points=1)
        with patch('research_calibration.calibration_pipeline.fit_hypothesis',side_effect=fit),patch(
            'research_calibration.calibration_pipeline.evaluate_capture',side_effect=evaluate),patch(
            'research_calibration.calibration_pipeline._training_selection',side_effect=lambda c,*a:(c,dict(training_only=True))):
            result=assess(original,'unused',output=folder,config=cfg,_bundle=bundle)
        self.assertEqual(original,untouched)
        self.assertFalse(outer_ids.intersection(fitted_ids))
        for name,folds in result.validation['folds'].items():
            for fold in folds: self.assertNotIn(fold['test_id'],fold['training_ids'])
        self.assertEqual(set(result.validation['outer_test']['test_ids']),outer_ids)
        json.loads((Path(folder)/'assessment.json').read_text(encoding='utf-8'))
        return result,original

    def test_bad_outer_rejects_previously_selected_update_and_preserves_reference(self):
        with tempfile.TemporaryDirectory() as folder:
            result,original=self.run_fixture(True,folder)
            self.assertEqual(result.diagnostics['decision']['status'],'CANDIDATE_SUPPORTED')
            self.assertEqual(result.selected_hypothesis,'KEEP')
            self.assertEqual(result.updated_calibration,original)
            self.assertTrue(all(v==0 for v in result.parameter_updates.values()))
            self.assertGreater(result.diagnostics['candidate_parameter_updates']['wx'],0)

    def test_success_requires_independent_outer_test(self):
        with tempfile.TemporaryDirectory() as folder:
            result,_=self.run_fixture(False,folder)
            self.assertEqual(result.status,'UPDATE_SUPPORTED')
            self.assertEqual(result.selected_hypothesis,'R')
            self.assertTrue(result.validation['outer_test']['passed'])
            with self.assertRaises(FileExistsError): assess(reference(),'unused',output=folder)

    def test_final_recomputed_support_can_reject_a_comparison_winner(self):
        with tempfile.TemporaryDirectory() as folder:
            result,original=self.run_fixture(False,folder,unsupported_final=True)
            self.assertEqual(result.diagnostics['decision']['status'],'CANDIDATE_SUPPORTED')
            self.assertTrue(result.validation['outer_test']['passed'])
            self.assertEqual(result.selected_hypothesis,'KEEP')
            self.assertEqual(result.updated_calibration,original)

    def test_existing_calibration_in_output_folder_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'updated_calibration.json'
            text=json.dumps(reference(),indent=2)
            path.write_text(text,encoding='utf-8')
            with self.assertRaises(FileExistsError): assess(path,'unused',output=folder)
            self.assertEqual(path.read_text(encoding='utf-8'),text)


if __name__=='__main__': unittest.main()
