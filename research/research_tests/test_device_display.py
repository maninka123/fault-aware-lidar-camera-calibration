"""Device identity and native values stay consistent across capture, Keep, and device review."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'app/gui'), str(ROOT / 'app/Calibration maintenance/code')]
import numpy as np
from PyQt5 import QtWidgets
import device_model as dm
import device_display as display
from matrix_preview import MatrixPreview

APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
PARAMS = dict(camera_matrix=[[236.578852, 0., 246.508397], [0., 233.114979, 190.358231], [0., 0., 1.]],
              dist_coeffs=[.08894868, .002, .001, -.001, .003], image_width=484, image_height=366,
              extrinsic_matrix=[[0., -1., 0., .06404], [0., 0., -1., -.01551], [1., 0., 0., .07094], [0., 0., 0., 1.]])


class DeviceDisplayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.source = Path(self.tmp.name) / 'session'
        self.source.mkdir()
        self.record = dict(device=dict(name='Device 5', key='cmp:5', ssh_host='10.20.0.31'), params=PARAMS,
                           captures=[{}]*5, topics=dict(image='/camera/image_raw', cloud='/livox/lidar'))
        (self.source / 'device.json').write_text(json.dumps(self.record))
        self.meta = dict(device_source=str(self.source), captures=str(self.source / 'pairs'))
        self.cal, _ = dm.to_calibration(PARAMS)

    def test_keep_uses_the_exact_device_values_without_a_round_trip_conversion(self):
        with patch.object(dm, 'to_device', side_effect=AssertionError('KEEP must not refit the camera')):
            result = display.result_calibration(dict(updated_calibration=self.cal, selected_hypothesis='KEEP'), self.meta)
        np.testing.assert_array_equal(result['intrinsics']['camera_matrix'], PARAMS['camera_matrix'])
        np.testing.assert_array_equal(result['intrinsics']['distortion_coefficients'], PARAMS['dist_coeffs'])
        np.testing.assert_array_equal(result['extrinsics']['transform_lidar_to_camera'], PARAMS['extrinsic_matrix'])
        self.assertFalse(np.array_equal(self.cal['intrinsics']['camera_matrix'], PARAMS['camera_matrix']))

    def test_alignment_and_camera_only_displays_match_the_write_modes(self):
        candidate = copy.deepcopy(self.cal)
        candidate['extrinsics']['transform_lidar_to_camera'][0][3] += .02
        shown = display.display_options(dict(existing=self.cal, extrinsic=candidate, intrinsic=candidate, full=candidate), self.meta)
        np.testing.assert_array_equal(shown['extrinsic']['intrinsics']['camera_matrix'], PARAMS['camera_matrix'])
        np.testing.assert_array_equal(shown['extrinsic']['intrinsics']['distortion_coefficients'], PARAMS['dist_coeffs'])
        np.testing.assert_array_equal(shown['intrinsic']['extrinsics']['transform_lidar_to_camera'], PARAMS['extrinsic_matrix'])
        preview = MatrixPreview(); preview.set_calibrations(shown); preview.set_mode('existing')
        self.assertEqual(preview.cells[('K', 0, 0)][0].text(), '236.578852')
        self.assertEqual(preview.coefficient_names[('D', 0, 2)].text(), 'p1')
        self.assertEqual(preview.coefficient_names[('D', 0, 4)].text(), 'k3')
        self.assertFalse(preview.frames[('D', 0, 4)].isHidden())
        preview.close()

    def test_result_heading_identifies_the_device_and_has_no_device_write_controls(self):
        import research_gui as g
        folder = self.source / 'results'; folder.mkdir()
        (folder / 'assessment.json').write_text(json.dumps(dict(status='KEEP_CURRENT', selected_hypothesis='KEEP', updated_calibration=self.cal)))
        g.MainWindow.meta_file(folder).write_text(json.dumps(self.meta))
        window = g.MainWindow()
        try:
            window.load(folder)
            self.assertEqual(window.run_title.text(), 'Device 5')
            self.assertIn('10.20.0.31', window.run_detail.text())
            self.assertIn('5 captured pairs', window.run_detail.text())
            self.assertFalse(window.use_card.device_actions)
            self.assertTrue(window.use_card.write_btn.isHidden())
            self.assertTrue(window.use_card.restore_btn.isHidden())
        finally:
            window.close()

    def test_manual_preview_hands_off_to_the_review_tab_only(self):
        import research_gui as g
        from manual_device_calibration import template, ManualDeviceCalibrationDialog
        window = g.MainWindow()
        page = QtWidgets.QWidget()
        page.params, page.current, page.main = PARAMS, self.record['device'], window
        candidate = copy.deepcopy(PARAMS); candidate['camera_matrix'][0][0] += 3
        popup = ManualDeviceCalibrationDialog(page)
        try:
            popup.editor.setPlainText(template(candidate)); popup.preview(); popup.send_to_review()
            self.assertEqual(window.stack.currentWidget(), window.review)
            self.assertTrue(window.review.manual_panel.allow_write)
            self.assertEqual(window.review.manual_panel.mode.currentData(), 'full')
            self.assertTrue(window.review.manual_panel.write_button.isEnabled())
        finally:
            popup.close(); window.close(); page.close()


if __name__ == '__main__':
    unittest.main()
