import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from research_calibration.resources import check_resources
from research_calibration.calibration_pipeline import calibrate_from_scratch
from research_calibration.reporting import AssessmentResult
from test_mathematics import reference
from research_calibration.legacy_adapter import io_path


class ResourceAndInitializationTests(unittest.TestCase):
    def test_long_local_file_path_without_windows_setting_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=io_path(Path(temporary)/('a'*230+'.txt'))
            try:
                path.write_text('local path verification',encoding='utf-8')
                self.assertEqual(path.read_text(encoding='utf-8'),'local path verification')
            finally:
                if path.exists(): path.unlink()

    def test_low_available_or_excess_process_memory_stops_work(self):
        for state in (dict(available_mb=3000,process_mb=100),dict(available_mb=8000,process_mb=2100)):
            with patch('research_calibration.resources.memory_status',return_value=state):
                with self.assertRaises(MemoryError): check_resources()

    def test_initialization_adapter_preserves_initializer_and_does_not_claim_fault_diagnosis(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); captures=root/'captures'; captures.mkdir(); (captures/'one.npz').touch()
            output=root/'new_run'; invoked=[]
            def initializer(cfg,name):
                invoked.append((cfg,name))
                folder=Path(cfg['output_dir'])/name; folder.mkdir(parents=True)
                (folder/'calibration.json').write_text(json.dumps(reference()),encoding='utf-8')
            result=AssessmentResult('KEEP_CURRENT','KEEP',[],[],{},dict(status='UNAVAILABLE'),{},'KEEP',reference(),dict(limitations=[],input={}))
            with patch.dict('sys.modules',{'step1_calibrate':SimpleNamespace(run_device=initializer)}),patch(
                'research_calibration.calibration_pipeline.assess',return_value=result) as assessment:
                final=calibrate_from_scratch(captures,output=output)
            self.assertEqual(invoked[0][1],'captures')
            self.assertEqual(invoked[0][0]['prior']['rotation_lidar_to_camera'],'auto')
            self.assertEqual(final.status,'INITIAL_CALIBRATION_CANDIDATE')
            self.assertIn('no trustworthy',final.diagnostics['historical_fault_attribution'])
            self.assertIn('Initializer used all captures',final.diagnostics['limitations'][-1])
            self.assertEqual(assessment.call_args.args[2],'joint')
            self.assertEqual(final.updated_calibration,reference())
            self.assertEqual(final.uncertainty['status'],'UNVALIDATED_INITIALIZATION')
            self.assertIsNone(final.unobservable_directions)
            self.assertTrue((output/'assessment/conditional_assessment.json').exists())
            with self.assertRaises(FileExistsError): calibrate_from_scratch(captures,output=output)


if __name__=='__main__': unittest.main()
