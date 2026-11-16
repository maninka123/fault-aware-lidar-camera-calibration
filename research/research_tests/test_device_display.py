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

    def test_missing_camera_fit_shows_current_values_and_the_real_reason(self):
        shown = display.display_options(dict(existing=self.cal, full=self.cal), self.meta)
        preview = MatrixPreview(); preview.set_calibrations(shown); preview.set_mode('intrinsic')
        self.assertEqual(preview.cells[('K', 0, 0)][0].text(), '236.578852')
        self.assertIn('held-out fits', preview.note.text())
        self.assertIn('unchanged current values', preview.note.text())
        self.assertEqual(preview.states['K'].text(), 'Current values only')
        self.assertNotIn('intrinsic', shown)
        preview.close()

    def test_failed_device_conversion_is_not_misreported_as_a_missing_fit(self):
        with patch.object(dm, 'to_device', side_effect=ValueError('cannot reproduce this lens')):
            shown = display.display_options(dict(existing=self.cal, intrinsic=self.cal), self.meta)
        preview = MatrixPreview(); preview.set_calibrations(shown); preview.set_mode('intrinsic')
        self.assertIn('cannot reproduce this lens', preview.note.text())
        self.assertNotIn('were not saved', preview.note.text())
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

    def test_matrix_edit_write_readback_and_restore_for_all_three_modes(self):
        import research_gui as g
        import device_ui as ui
        import device_yaml as dy
        from manual_device_calibration import ManualDeviceCalibrationDialog, template
        from device_update_review import saved_comparison, SavedDeviceUpdateDialog

        class Page(QtWidgets.QWidget):
            def set_params(self, raw, source):
                self.params = dm.file_params(raw)
                self.params_source = source
            def render_params(self):
                pass

        class Device:
            password = 'test'
            def __init__(self):
                self.files = {'/pipeline.yaml': template(PARAMS)}
                self.writes = 0
            def read(self, path):
                return self.files[path]
            def backup(self, path, stamp):
                backup = path + '.calib_backup_' + stamp
                self.files[backup] = self.files[path]
                return backup
            def write(self, path, value):
                self.files[path] = value
                self.writes += 1
            def restart(self, password):
                return 'active'
            def close(self):
                pass

        for mode, direct in ((mode, direct) for mode in ('intrinsic', 'extrinsic', 'full') for direct in (False, True)):
            with self.subTest(mode=mode, direct=direct):
                window = g.MainWindow(); page = Page()
                page.params = copy.deepcopy(PARAMS)
                page.current = dict(self.record['device'], master_uri=None)
                page.main = window
                device = Device(); original = device.files['/pipeline.yaml']
                popup = ManualDeviceCalibrationDialog(page, allow_write=direct)
                try:
                    popup.values_table.item(0, 2).setText('239.578852')
                    popup.values_table.item(9, 2).setText('84.04')
                    popup.mode.setCurrentIndex(popup.mode.findData(mode))
                    if not direct:
                        popup.send_to_review()
                    self.assertEqual(device.writes, 0, 'Preview and handoff cannot write to the device')
                    panel = popup if direct else window.review.manual_panel
                    panel.folder = Path(self.tmp.name) / (mode + str(direct))
                    panel.refresh_restore()
                    self.assertEqual(panel.mode.currentData(), mode)

                    opened_comparisons = []
                    def interact(dialog):
                        if isinstance(dialog, SavedDeviceUpdateDialog):
                            opened_comparisons.append(dialog)
                        if isinstance(dialog, ui.WriteDialog):
                            dialog.restart.setChecked(False)
                            dialog.connect_and_diff()
                            self.assertEqual(device.writes, 0, 'The file diff is shown before a write')
                            dialog.write()
                        return QtWidgets.QDialog.Accepted

                    with patch.object(ui.devreg, 'load', return_value=[]), \
                            patch.object(ui, 'ssh_session', return_value=device), \
                            patch.object(ui, 'read_device_yaml', side_effect=lambda *a: ('/pipeline.yaml', device.read('/pipeline.yaml'))), \
                            patch.object(ui, 'busy', side_effect=lambda parent, text, fn, *args: fn(*args)), \
                            patch.object(ui, 'ask', return_value=True) as confirmations, \
                            patch.object(ui.core, 'mark_history'), \
                            patch.object(QtWidgets.QDialog, 'exec_', new=interact), \
                            patch.object(QtWidgets.QMessageBox, 'information'):
                        panel.write_button.click()
                        self.assertEqual(device.writes, 1)
                        actual = dm.file_params(dy.read_params(device.read('/pipeline.yaml')))
                        expected = copy.deepcopy(PARAMS)
                        if mode != 'extrinsic':
                            expected['camera_matrix'][0][0] = 239.578852
                        if mode != 'intrinsic':
                            expected['extrinsic_matrix'][0][3] = .08404
                        for key in ('camera_matrix', 'dist_coeffs', 'extrinsic_matrix'):
                            np.testing.assert_array_equal(actual[key], expected[key])
                            np.testing.assert_array_equal(page.params[key], actual[key])
                        self.assertTrue(saved_comparison(panel.folder)['verified'])
                        self.assertEqual(len(opened_comparisons), 1)
                        comparison = opened_comparisons[0]
                        self.assertEqual(comparison.before_file.toPlainText(), original)
                        self.assertEqual(comparison.after_file.toPlainText(), device.files['/pipeline.yaml'])
                        self.assertTrue(comparison.before_file.isReadOnly())
                        self.assertTrue(comparison.after_file.isReadOnly())
                        self.assertGreater(len(comparison.after_file.extraSelections()), 0)
                        self.assertTrue(panel.saved_update_button.isEnabled())
                        self.assertTrue(panel.restore_button.isEnabled())
                        panel.restore_button.click()
                        self.assertEqual(device.files['/pipeline.yaml'], original)
                        for key in ('camera_matrix', 'dist_coeffs', 'extrinsic_matrix'):
                            np.testing.assert_array_equal(page.params[key], PARAMS[key])
                        self.assertFalse(panel.write_button.isEnabled())
                        self.assertGreaterEqual(confirmations.call_count, 2)
                finally:
                    popup.close(); window.close(); page.close()


if __name__ == '__main__':
    unittest.main()
