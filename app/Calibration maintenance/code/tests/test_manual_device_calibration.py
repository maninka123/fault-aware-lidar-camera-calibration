"""Manual imports and review use local fixtures; no physical device is contacted."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PyQt5 import QtWidgets, QtTest
import yaml
import numpy as np
import manual_device_calibration as manual
import device_ui as ui
import device_model as dm
from calibration_io import write_calibration_txt

APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
CURRENT = dict(camera_matrix=[[236.578852, 0., 246.508397], [0., 233.114979, 190.358231], [0., 0., 1.]],
               dist_coeffs=[.08894868, .002, .001, -.001, .003],
               extrinsic_matrix=[[0., -1., 0., .06404], [0., 0., -1., -.01551], [1., 0., 0., .07094], [0., 0., 0., 1.]],
               image_width=484, image_height=366)


def changed():
    value = copy.deepcopy(CURRENT)
    value['camera_matrix'][0][0] += 3
    value['dist_coeffs'][4] += .01
    value['extrinsic_matrix'][0][3] += .02
    return value


class ManualImports(unittest.TestCase):
    def test_device_editor_entry_has_a_direct_update_button(self):
        page = QtWidgets.QWidget()
        page.params, page.current, page.main = copy.deepcopy(CURRENT), dict(key='test', name='Device 5'), Mock()
        page.capture_running = False
        try:
            with patch.object(manual, 'ManualDeviceCalibrationDialog') as constructor:
                ui.DevicePage.edit_manually(page)
                constructor.assert_called_once_with(page, allow_write=True)
            popup = manual.ManualDeviceCalibrationDialog(page, allow_write=True)
            self.assertEqual(popup.write_button.text(), 'Update device...')
            popup.values_table.item(0, 2).setText('239.578852')
            self.assertTrue(popup.write_button.isEnabled())
            self.assertFalse(popup.restore_button.isHidden())
            popup.close()
        finally:
            page.close()

    def test_matrix_edits_update_comparison_and_reset_cancels_them(self):
        page = QtWidgets.QWidget()
        page.params, page.current, page.main = copy.deepcopy(CURRENT), dict(key='test', name='Device 5'), Mock()
        popup = manual.ManualDeviceCalibrationDialog(page)
        try:
            self.assertNotIsInstance(popup.editor, QtWidgets.QPlainTextEdit)
            popup.show(); APP.processEvents()
            camera = popup.values_table
            self.assertFalse(camera.item(0, 1).flags() & manual.QtCore.Qt.ItemIsEditable)
            self.assertTrue(camera.item(0, 2).flags() & manual.QtCore.Qt.ItemIsEditable)
            QtTest.QTest.mouseClick(camera.viewport(), manual.QtCore.Qt.LeftButton, pos=camera.visualItemRect(camera.item(0, 2)).center())
            entry = camera.findChild(QtWidgets.QLineEdit)
            self.assertIsNotNone(entry)
            QtTest.QTest.keyClick(entry, manual.QtCore.Qt.Key_A, manual.QtCore.Qt.ControlModifier)
            QtTest.QTest.keyClicks(entry, '236.578853')
            QtTest.QTest.keyClick(entry, manual.QtCore.Qt.Key_Return)
            APP.processEvents()
            self.assertEqual(popup.candidate['camera_matrix'][0][0], 236.578853)
            comparison = popup.comparison_layout.itemAt(0).widget()
            self.assertEqual(comparison.item(0, 2).text(), '236.578853')
            self.assertNotEqual(comparison.item(0, 3).text(), '-')
            self.assertTrue(popup.write_button.isEnabled())
            self.assertNotIn(0, popup.values_table.stretch_columns)
            self.assertIn(3, popup.values_table.stretch_columns)
            value, delta = popup.editor.cells['camera_matrix', 0, 0]
            self.assertEqual(value.text(), '236.578853')
            self.assertIn('#c62828', value.styleSheet())
            self.assertIn('+', delta.text())
            self.assertFalse(popup.editor.findChildren(QtWidgets.QLineEdit))
            popup.values_table.item(4, 2).setText('0.09894868')
            coefficient, change = popup.editor.cells['dist_coeffs', 0, 0]
            self.assertEqual(coefficient.text(), '0.09894868')
            self.assertEqual(change.text(), 'Delta +0.01')
            for index in range(5):
                coefficient, _ = popup.editor.cells['dist_coeffs', 0, index]
                self.assertFalse(coefficient.isHidden())
                self.assertNotIn('...', coefficient.text())
            popup.reset_button.click()
            np.testing.assert_array_equal(popup.candidate['camera_matrix'], CURRENT['camera_matrix'])
            self.assertFalse(popup.write_button.isEnabled())
            page.main.review_manual_device.assert_not_called()
        finally:
            popup.close(); page.close()

    def test_invalid_rotation_blocks_apply_and_mode_preserves_unselected_values(self):
        page = QtWidgets.QWidget()
        page.params, page.current, page.main = copy.deepcopy(CURRENT), dict(key='test', name='Device 5'), Mock()
        popup = manual.ManualDeviceCalibrationDialog(page)
        try:
            transform = popup.values_table
            transform.item(12, 2).setText('2')
            self.assertIsNone(popup.candidate)
            self.assertFalse(popup.write_button.isEnabled())
            popup.reset_edits()
            transform.item(9, 2).setText('80')
            self.assertTrue(popup.write_button.isEnabled())
            popup.mode.setCurrentIndex(popup.mode.findData('intrinsic'))
            np.testing.assert_array_equal(popup.candidate['extrinsic_matrix'], CURRENT['extrinsic_matrix'])
            self.assertFalse(transform.item(9, 2).flags() & manual.QtCore.Qt.ItemIsEditable)
            self.assertFalse(popup.write_button.isEnabled())
        finally:
            popup.close(); page.close()

    def test_native_values_and_mode_selection_do_not_convert_other_parameters(self):
        candidate = changed()
        for mode in ('full', 'intrinsic', 'extrinsic'):
            result, _ = manual.parse_values(manual.template(candidate), CURRENT, mode)
            np.testing.assert_array_equal(result['camera_matrix'], CURRENT['camera_matrix'] if mode == 'extrinsic' else candidate['camera_matrix'])
            np.testing.assert_array_equal(result['dist_coeffs'], CURRENT['dist_coeffs'] if mode == 'extrinsic' else candidate['dist_coeffs'])
            np.testing.assert_array_equal(result['extrinsic_matrix'], CURRENT['extrinsic_matrix'] if mode == 'intrinsic' else candidate['extrinsic_matrix'])

    def test_invalid_values_are_rejected(self):
        for key, bad in (('dist_coeffs', [0]*4), ('camera_matrix', [[-1, 0, 1], [0, 1, 1], [0, 0, 1]]),
                         ('extrinsic_matrix', np.zeros((4, 4)).tolist()), ('image_width', 999)):
            values = changed(); values[key] = bad
            with self.subTest(key=key), self.assertRaises(ValueError):
                manual.parse_values(manual.template(CURRENT).split('pointcloud_colorizer:')[0] + yaml.safe_dump({'pointcloud_colorizer': values}), CURRENT)

    def test_project_txt_import_reports_conversion(self):
        with tempfile.TemporaryDirectory() as tmp:
            cal, _ = dm.to_calibration(CURRENT)
            path = Path(tmp) / 'project.txt'
            write_calibration_txt(path, cal, 'full')
            result, note = manual.parse_values(path.read_text(encoding='utf-8'), CURRENT)
            self.assertIn('converted', note.lower())
            self.assertEqual(len(result['dist_coeffs']), 5)

    def test_explicit_pinhole_import_is_not_treated_as_fisheye(self):
        cal = dict(intrinsics=dict(model='opencv_pinhole', camera_matrix=CURRENT['camera_matrix'], distortion_coefficients=CURRENT['dist_coeffs']),
                   extrinsics=dict(transform_lidar_to_camera=CURRENT['extrinsic_matrix']))
        with patch.object(dm, 'to_device', side_effect=AssertionError('Unexpected fisheye conversion')):
            result, note = manual.parse_values(json.dumps(cal), CURRENT)
        np.testing.assert_array_equal(result['dist_coeffs'], CURRENT['dist_coeffs'])
        self.assertNotIn('_conversion_report', result)

    def test_explicit_fisheye_import_has_model_and_fit_report(self):
        cal, _ = dm.to_calibration(CURRENT)
        cal['intrinsics']['model'] = 'opencv_fisheye'
        result, note = manual.parse_values(json.dumps(cal), CURRENT)
        self.assertIn('OpenCV fisheye', note)
        self.assertIn('OpenCV pinhole', note)
        self.assertIn('covered angle', note)
        self.assertIn('_conversion_report', result)

    def test_device_declaring_fisheye_cannot_be_used_with_the_pinhole_writer(self):
        raw = dict(CURRENT, camera_model='opencv_fisheye')
        with self.assertRaisesRegex(ValueError, 'matching projector'):
            dm.file_params(raw)

    def test_popup_only_previews_and_hands_off_to_calibration_review(self):
        page = QtWidgets.QWidget()
        page.params, page.current, page.main = copy.deepcopy(CURRENT), dict(key='test', name='Device 5'), Mock()
        page.main.review_manual_device.return_value = True
        popup = manual.ManualDeviceCalibrationDialog(page)
        try:
            popup.editor.setPlainText(manual.template(changed()))
            self.assertFalse(popup.write_button.isEnabled())
            popup.preview()
            self.assertTrue(popup.write_button.isEnabled())
            self.assertTrue(popup.restore_button.isHidden())
            with patch.object(ui, 'WriteDialog') as write:
                popup.write()
                popup.send_to_review()
                write.assert_not_called()
            page.main.review_manual_device.assert_called_once_with(page, popup.editor.toPlainText(), 'full')
        finally:
            popup.close(); page.close()


class NativeWrites(unittest.TestCase):
    def test_converted_camera_requires_model_review_before_connecting(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(ui.devreg, 'load', return_value=[]), patch.object(ui, 'ssh_session') as ssh:
            cal, _ = dm.to_calibration(CURRENT)
            (Path(tmp) / 'refined_calibration.json').write_text(json.dumps(cal))
            info = dict(name='converted', out=Path(tmp), device=dict(device=dict(key='test', name='Test'), params=CURRENT, theta_max_deg=55),
                        summary=dict(mode='full', verdict='INCONCLUSIVE'))
            dialog = ui.WriteDialog(None, info)
            self.assertFalse(dialog.connect_button.isEnabled())
            dialog.connect_and_diff()
            ssh.assert_not_called()
            dialog.model_ack.setChecked(True)
            self.assertTrue(dialog.connect_button.isEnabled())
            dialog.reject()

    def test_write_preview_uses_exact_native_values_and_respects_the_selected_mode(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(ui.devreg, 'load', return_value=[]), patch.object(ui, 'ssh_session') as ssh:
            for mode in ('full', 'intrinsic', 'extrinsic'):
                info = dict(name='manual', out=Path(tmp), manual=True, import_note='Native device values',
                            device=dict(device=dict(key='test', name='Test', master_uri=None), params=CURRENT, theta_max_deg=55),
                            summary=dict(mode=mode, verdict='INCONCLUSIVE'), device_params_override=changed())
                dialog = ui.WriteDialog(None, info)
                np.testing.assert_array_equal(dialog.new['camera_matrix'], CURRENT['camera_matrix'] if mode == 'extrinsic' else changed()['camera_matrix'])
                np.testing.assert_array_equal(dialog.new['extrinsic_matrix'], CURRENT['extrinsic_matrix'] if mode == 'intrinsic' else changed()['extrinsic_matrix'])
                ssh.assert_not_called()
                dialog.reject()

    def test_two_updates_can_restore_the_original_file(self):
        class SSH:
            password = 'test'
            def __init__(self): self.files = {'/pipeline.yaml': manual.template(CURRENT)}
            def read(self, path): return self.files[path]
            def backup(self, path, stamp):
                name = path + '.' + stamp; self.files[name] = self.files[path]; return name
            def write(self, path, text): self.files[path] = text
            def restart(self, password): return 'active'
            def close(self): pass
        fake = SSH(); original = fake.files['/pipeline.yaml']
        with tempfile.TemporaryDirectory() as tmp, patch.object(ui.devreg, 'load', return_value=[]), \
                patch.object(ui, 'ssh_session', return_value=fake), \
                patch.object(ui, 'read_device_yaml', side_effect=lambda *a: ('/pipeline.yaml', fake.read('/pipeline.yaml'))), \
                patch.object(ui, 'busy', side_effect=lambda parent, text, fn, *args: fn(*args)), \
                patch.object(ui, 'ask', return_value=True), patch.object(ui.core, 'mark_history'), \
                patch.object(QtWidgets.QMessageBox, 'information'), patch.object(QtWidgets.QDialog, 'exec_', return_value=QtWidgets.QDialog.Accepted), \
                patch.object(QtWidgets.QInputDialog, 'getItem', side_effect=lambda parent, title, prompt, items, *a: (items[-1], True)):
            info = dict(name='manual', out=Path(tmp), manual=True, device=dict(device=dict(key='test', name='Test', master_uri=None), params=CURRENT, theta_max_deg=55),
                        summary=dict(mode='full', verdict='INCONCLUSIVE'), device_params_override=changed())
            for increment in (1., 2.):
                info['device_params_override']['camera_matrix'][0][0] += increment
                dialog = ui.WriteDialog(None, info)
                dialog.restart.setChecked(False)
                dialog.connect_and_diff(); dialog.write()
                self.assertIsNotNone(dialog.written_record)
            records = json.loads((Path(tmp) / 'device_writes.json').read_text())
            self.assertNotEqual(records[0]['backup'], records[1]['backup'])
            from device_update_review import saved_comparison
            comparison = saved_comparison(tmp)
            self.assertTrue(comparison['verified'])
            self.assertEqual(comparison['after']['camera_matrix'][0][0], records[-1]['new']['camera_matrix'][0][0])
            written = Path(tmp) / records[-1]['local_written']
            written.write_text(written.read_text() + '\n# changed after verification\n')
            self.assertFalse(saved_comparison(tmp)['verified'])
            failed = ui.WriteDialog(None, info)
            failed.restart.setChecked(False)
            failed.connect_and_diff()
            with patch.object(fake, 'read', return_value='corrupted read-back'), patch.object(ui, 'warn') as warning:
                failed.write()
                warning.assert_called_once()
                self.assertIn('may already have changed', warning.call_args.args[2])
                self.assertIn('did not restart', warning.call_args.args[2])
                self.assertIn('Backup:', warning.call_args.args[2])
            self.assertIsNone(failed.written_record)
            self.assertEqual(failed.pages.currentIndex(), 0, 'Retry must re-read the file and create a fresh backup')
            self.assertEqual(len(json.loads((Path(tmp) / 'device_writes.json').read_text())), 2)
            info['device_writes'] = records
            ui.RestoreDialog.run(None, info)
            self.assertEqual(fake.files['/pipeline.yaml'], original)


if __name__ == '__main__':
    unittest.main()
