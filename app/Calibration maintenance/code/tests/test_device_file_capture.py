"""Device file provenance, matrix display, and manual/automatic capture scheduling."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import copy
from pathlib import Path
import sys
import threading
import time
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import device_model as dm
import device_ui
import device_yaml
import device_file
import numpy as np
import yaml
from cloud_view import CloudView
from capture_schedule import run_sequence
from PyQt5 import QtWidgets, QtTest

APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
RAW = dict(camera_matrix=[[250., 0., 180.], [0., 251., 240.], [0., 0., 1.]],
           dist_coeffs=[-.2, .04, .001, .002, .003],
           extrinsic_matrix=[[0., -1., 0., .01], [0., 0., -1., -.05],
                             [1., 0., 0., .02], [0., 0., 0., 1.]],
           image_width=366, image_height=484)


class DeviceFileTests(unittest.TestCase):
    def test_wsl_file_mapping_is_bound_to_its_endpoint(self):
        profile = dict(calibration_transport='wsl', file_master_uri='http://127.0.0.1:11312',
                       master_uri='http://127.0.0.1:11312', wsl_distro='Ubuntu-20.04',
                       yaml_path='/home/device/config/pipeline.yaml')
        self.assertTrue(device_file.uses_wsl(profile))
        completed = Mock(returncode=0, stdout='file contents', stderr='')
        with patch.object(device_file.subprocess, 'run', return_value=completed) as run:
            path, contents, source = device_file.read_wsl(profile)
            self.assertEqual(contents, 'file contents')
            self.assertIn('WSL Ubuntu-20.04', source)
            self.assertEqual(run.call_args.args[0][-2:], ['--', path])
        profile['master_uri'] = 'http://10.20.0.21:11311'
        self.assertFalse(device_file.uses_wsl(profile))
        with self.assertRaises(ValueError):
            device_file.read_wsl(profile)
        self.assertFalse(device_file.uses_wsl(dict(master_uri='http://127.0.0.1:11312')))

    def test_file_values_preserved_including_nested_matrices(self):
        p = dm.file_params(RAW)
        for key in RAW:
            self.assertEqual(p[key], RAW[key])

    def test_missing_invalid_values_do_not_become_colorizer_defaults(self):
        for key in ('camera_matrix', 'dist_coeffs', 'extrinsic_matrix'):
            raw = copy.deepcopy(RAW)
            del raw[key]
            with self.assertRaisesRegex(ValueError, key):
                dm.file_params(raw)
            raw[key] = [float('nan')]
            with self.assertRaisesRegex(ValueError, key):
                dm.file_params(raw)

    def test_legacy_four_distortion_coefficients_use_the_colourizer_zero_k3(self):
        raw = dict(RAW, dist_coeffs=[-.10360109, .31921842, 0., 0.])
        flat = dict(raw, camera_matrix=np.ravel(raw['camera_matrix']).tolist(),
                    extrinsic_matrix=np.ravel(raw['extrinsic_matrix']).tolist())
        text = yaml.safe_dump({'pointcloud_colorizer': flat}, default_flow_style=None)
        result = dm.file_params(device_yaml.read_params(text))
        self.assertEqual(result['dist_coeffs'], raw['dist_coeffs'] + [0.])
        self.assertIn('k3 = 0', result['notes'][0])
        self.assertEqual(len(raw['dist_coeffs']), 4)
        rewritten = device_yaml.read_params(device_yaml.update(text, result, ''))
        np.testing.assert_allclose(rewritten['dist_coeffs'], raw['dist_coeffs'])
        result['dist_coeffs'][4] = .001
        rewritten = device_yaml.read_params(device_yaml.update(text, result, ''))
        np.testing.assert_allclose(rewritten['dist_coeffs'], result['dist_coeffs'])
        with self.assertRaisesRegex(ValueError, 'one to five distortion coefficients'):
            dm.file_params(dict(raw, dist_coeffs=[0.] * 8))

    def test_colourizer_short_arrays_and_invalid_calibration_fields(self):
        distortion = RAW['dist_coeffs']
        for length in range(1, 6):
            with self.subTest(length=length):
                raw = dict(RAW, dist_coeffs=distortion[:length])
                self.assertEqual(dm.file_params(raw)['dist_coeffs'], distortion[:length] + [0.] * (5 - length))
        for key, malformed in (
            ('camera_matrix', np.zeros((1, 3, 3))),
            ('extrinsic_matrix', np.zeros((2, 8))),
            ('dist_coeffs', []), ('dist_coeffs', [True, 0., 0., 0.]),
            ('dist_coeffs', ['not a number']), ('image_width', 366.5), ('image_height', 0),
        ):
            with self.subTest(key=key, malformed=malformed), self.assertRaisesRegex(ValueError, key):
                dm.file_params(dict(RAW, **{key: malformed}), image_size=(640, 480))
        partial = {key: value for key, value in RAW.items() if key != 'image_height'}
        params = dm.file_params(partial, image_size=(640, 480))
        self.assertEqual((params['image_width'], params['image_height']), (366, 480))

    def test_resolution_requires_file_or_explicit_live_image(self):
        raw = {k: v for k, v in RAW.items() if not k.startswith('image_')}
        with self.assertRaisesRegex(ValueError, 'dimensions'):
            dm.file_params(raw)
        p = dm.file_params(raw, image_size=(640, 480))
        self.assertEqual((p['image_width'], p['image_height']), (640, 480))
        self.assertIn('received camera image', p['notes'][0])

    def test_yaml_errors_are_reported(self):
        for text in ('', 'other: {}', 'pointcloud_colorizer: [',
                     'pointcloud_colorizer:\n  ros__parameters: []'):
            with self.assertRaises(ValueError):
                device_yaml.read_params(text)
        for text in ('pointcloud_colorizer:\n  dist_coeffs: [0]\n  dist_coeffs: [1]\n',
                     'pointcloud_colorizer:\n  ros__parameters:\n    camera_matrix: []\n    camera_matrix: []\n'):
            with self.assertRaisesRegex(ValueError, 'more than once.*line'):
                device_yaml.read_params(text)

    def test_device_file_reader_accepts_ros1_and_ros2(self):
        flat = dict(RAW, camera_matrix=np.ravel(RAW['camera_matrix']).tolist(),
                    extrinsic_matrix=np.ravel(RAW['extrinsic_matrix']).tolist())
        for section in (RAW, {'ros__parameters': flat}):
            text = yaml.safe_dump({'pointcloud_colorizer': section})
            with self.subTest(ros2='ros__parameters' in section):
                params = dm.file_params(device_yaml.read_params(text))
                self.assertEqual({key: params[key] for key in RAW}, RAW)

    def test_ros2_file_cannot_use_the_ros1_writer(self):
        text = yaml.safe_dump({'pointcloud_colorizer': {'ros__parameters': RAW}})
        with self.assertRaisesRegex(ValueError, 'ROS 2 deployment'):
            device_yaml.update(text, RAW, '')

    def test_ros1_reader_keeps_the_file_picker_for_native_and_bridge_devices(self):
        old = '/legacy/pipeline.yaml'
        text = yaml.safe_dump({'pointcloud_colorizer': RAW})
        for via_bridge in (False, True):
            with self.subTest(via_bridge=via_bridge), \
                    patch('device_ros2.read_active', return_value=None) as active, \
                    patch.object(device_ui, 'busy', side_effect=lambda parent, message, fn, *args: fn(*args)), \
                    patch.object(QtWidgets.QInputDialog, 'getText', return_value=(old, True)) as picker, \
                    patch.object(device_ui.devreg, 'save_settings') as save:
                ssh = Mock(find_yaml=Mock(return_value=old), read=Mock(return_value=text))
                profile = dict(key='legacy', yaml_path=old)
                self.assertEqual(device_ui.read_device_yaml(None, ssh, profile, choose_path=True,
                                                            prefer_active=via_bridge), (old, text))
                self.assertEqual(active.call_count, int(via_bridge))
                picker.assert_called_once()
                save.assert_called_once_with('legacy', yaml_path=old)

    def test_connected_ros2_panel_reads_active_path_and_uses_running_values_while_pending(self):
        stale = '/home/rock/Sensor_Computer_ROS2/ros2/src/node_pc/config/pipeline.yaml'
        active = '/home/rock/Sensor_Computer/ros2/install/node_pc/share/node_pc/config/pipeline.yaml'
        values = device_yaml.ros2_values(RAW)
        values['camera_matrix'][0], values['camera_matrix'][4] = 235.5668, 229.5212
        values['extrinsic_matrix'][11] = .0385
        values['dist_coeffs'][4] = 0.
        raw = dict(RAW, **values)
        raw['dist_coeffs'] = values['dist_coeffs'][:4]
        text = yaml.safe_dump({'pointcloud_colorizer': {'ros__parameters': raw}})
        with patch.object(device_ui.devreg, 'load', return_value=[]), patch.object(device_ui.DevicePage, 'probe_all'):
            page = device_ui.DevicePage(None, choose_mode=False)
        self.addCleanup(page.close)
        self.addCleanup(page.shutdown)
        page.current = dict(key='sensor', name='Device', yaml_path=stale,
                            image_topic='/camera/image_raw', cloud_topic='/livox/lidar')
        page.link = Mock(kind='bridge')
        page.link.describe.return_value = 'ROSBridge'
        page.show_connected()
        ssh = Mock(user='rock', host='sensor', port=22)
        with patch.object(device_ui, 'ssh_session', return_value=ssh), \
                patch.object(device_ui, 'busy', side_effect=lambda parent, message, fn, *args: fn(*args)), \
                patch.object(QtWidgets.QInputDialog, 'getText') as picker, \
                patch('device_ros2.read_active', return_value=(active, text)), \
                patch('device_ros2.query_runtime', side_effect=[device_yaml.ros2_values(RAW), values]):
            page.read_cal_btn.click()
            self.assertEqual(page.params['camera_matrix'][0][0], RAW['camera_matrix'][0][0])
            self.assertIn('Pending restart', page.calibration_status)
            self.assertIsNone(page.calibration_file_text)
            self.assertIn(active, page.params_source)
            page.read_from_file()
            self.assertEqual(page.calibration_status, '')
            self.assertEqual(page.calibration_file_text, text)
            self.assertIn(active, page.params_source)
            self.assertNotIn(stale, page.params_source)
            matrices = page.cal_box.itemAt(1).widget().findChildren(QtWidgets.QPlainTextEdit)
            self.assertIn('235.5668', matrices[0].toPlainText())
            self.assertIn('229.5212', matrices[0].toPlainText())
            self.assertIn('0.0385', matrices[1].toPlainText())
            picker.assert_not_called()
            ssh.find_yaml.assert_not_called()
        invalid = yaml.safe_dump({'pointcloud_colorizer': {'ros__parameters': dict(raw, dist_coeffs=[])}})
        with patch.object(device_ui, 'ssh_session', return_value=ssh), \
                patch.object(device_ui, 'busy', side_effect=lambda parent, message, fn, *args: fn(*args)), \
                patch('device_ros2.read_active', return_value=(active, invalid)), \
                patch('device_ros2.query_runtime', return_value=values), patch.object(device_ui, 'warn') as warning:
            page.read_cal_btn.click()
            self.assertIsNone(page.params)
            self.assertIn(active, page.calibration_status)
            self.assertIn('dist_coeffs', page.calibration_status)
            self.assertIn(active, warning.call_args.args[2])
            self.assertIn('dist_coeffs', page.cal_box.itemAt(0).widget().text())

    def test_view_contains_exact_matrices_and_source(self):
        view = device_ui.device_calibration_view(dm.file_params(RAW), 'rock@sensor — /config/pipeline.yaml')
        blocks = view.findChildren(QtWidgets.QPlainTextEdit)
        self.assertEqual(len(blocks), 2)
        self.assertTrue(all(b.isReadOnly() for b in blocks))
        self.assertIn('251', blocks[0].toPlainText())
        self.assertIn('-0.05', blocks[1].toPlainText())
        self.assertIn('/config/pipeline.yaml', ' '.join(w.text() for w in view.findChildren(QtWidgets.QLabel)))
        view.close()

    def test_device_8_matrix_is_readable_at_wide_and_narrow_widths(self):
        raw = dict(RAW, extrinsic_matrix=[
            [0.0211139458, -0.999576985, -0.0200013204, -0.0117632719],
            [0.0427803906, 0.0208907401, -0.998866065, -0.028017784],
            [0.998861372, 0.0202343397, 0.0432033798, 0.247156238],
            [0., 0., 0., 1.],
        ])
        view = device_ui.device_calibration_view(dm.file_params(raw), 'Device 8')
        self.addCleanup(view.close)
        view.resize(1200, 650)
        view.show()
        APP.processEvents()
        matrix = view.findChildren(QtWidgets.QPlainTextEdit)[1]
        scrollbar = matrix.horizontalScrollBar()
        self.assertEqual(scrollbar.maximum(), 0)
        self.assertEqual([row.split()[1] for row in matrix.toPlainText().splitlines()],
                         ['0.0211', '0.0428', '0.9989', '0.0000'])

        view.resize(650, 650)
        APP.processEvents()
        self.assertTrue(scrollbar.isVisible())
        self.assertEqual(scrollbar.value(), 0)
        first = matrix.textCursor()
        first.setPosition(0)
        self.assertGreaterEqual(matrix.cursorRect(first).left(), 0)
        last = matrix.textCursor()
        last.setPosition(len(matrix.document().firstBlock().text()))
        scrollbar.setValue(scrollbar.maximum())
        self.assertLessEqual(matrix.cursorRect(last).right(), matrix.viewport().width())

    def test_last_matrix_row_is_inside_the_visible_viewport(self):
        view = device_ui.device_calibration_view(dm.file_params(RAW), 'file source')
        view.resize(1200, 650)
        view.show()
        APP.processEvents()
        for block in view.findChildren(QtWidgets.QPlainTextEdit):
            last = block.blockBoundingGeometry(block.document().lastBlock()).translated(block.contentOffset())
            self.assertLessEqual(last.bottom(), block.viewport().height())
        self.assertFalse(any('Mounting:' in text.text() for text in view.findChildren(QtWidgets.QLabel)))
        view.close()

    def test_connect_never_reads_ros_calibration(self):
        with patch.object(device_ui.devreg, 'load', return_value=[]), \
                patch.object(device_ui.DevicePage, 'probe_all'):
            page = device_ui.DevicePage(None, choose_mode=False)
        device = dict(key='physical:1', name='Sensor', image_topic='/camera/image_raw', cloud_topic='/livox/lidar')
        link = Mock()
        link.topics.return_value = {}
        with patch('ros_link.open_link', return_value=link), \
                patch('device_capture.snapshot', return_value={}), \
                patch.object(device_ui, 'busy', side_effect=lambda parent, text, fn, *args: fn(*args)), \
                patch.object(page, 'refresh_list'), patch.object(page, 'show_connected'), \
                patch.object(page, 'read_from_file') as read:
            page.connect(device)
            link.colorizer_params.assert_not_called()
            self.assertIsNone(page.params)
            read.assert_called_once_with()
        page.shutdown()


class CaptureScheduleTests(unittest.TestCase):
    def test_missing_platform_folder_is_selected_once_and_remembered(self):
        page = self.make_page()
        try:
            with TemporaryDirectory() as tmp:
                root = Path(tmp)
                selected = root / 'selected-platform'
                selected.mkdir()
                (selected / 'config.json').write_text('{}')
                with patch.object(device_ui.devreg, 'LOCAL', root / 'user-settings' / 'devices.json'), \
                        patch.object(device_ui.devreg, 'LEGACY_LOCAL', root / 'no-legacy.json'), \
                        patch.object(device_ui.devreg, 'CMP_DIR', root / 'missing'), \
                        patch.object(QtWidgets.QFileDialog, 'getExistingDirectory', return_value=str(selected)) as choose, \
                        patch.object(page, 'refresh_list'):
                    page.ensure_platform_folder()
                    page.platform_prompted = False  # simulate another visit/session
                    page.ensure_platform_folder()
                    choose.assert_called_once()
                    self.assertEqual(device_ui.devreg.platform_dir(), selected)
        finally:
            page.shutdown()
            page.close()

    def test_processed_set_remains_available_for_more_captures(self):
        page = self.make_page()
        try:
            with TemporaryDirectory() as tmp, patch.object(device_ui.core, 'RESULTS', Path(tmp)):
                out = Path(tmp) / 'test'
                (out / 'captures').mkdir(parents=True)
                np.savez(out / 'captures' / 'one.npz', xyz_mm=np.ones((50, 3))*1000, image=np.zeros((30, 40, 3), np.uint8))
                caps = [dict(file='one.npz', images=3, lidar_frames=10)]
                page.n_caps.setValue(1)
                page.captured(page.current, 'test', out, caps)
                page.process_captures()
                self.assertIsNotNone(page.pending_capture)
                self.assertEqual(len(page.pending_capture[3]), 1)
                page.processed_check = Path(tmp) / 'check'
                page.update_go()
                self.assertIn('Add', page.go.text())
                self.assertFalse(page.existing_results.isHidden())
                self.assertTrue((out / 'captures' / 'one.npz').exists())
        finally:
            page.shutdown()
            page.close()

    def test_topic_dropdowns_keep_defaults_and_allow_custom_topics(self):
        page = self.make_page()
        try:
            for combo, default in ((page.img_topic, '/camera/image_raw'), (page.cloud_topic, '/livox/lidar')):
                self.assertTrue(combo.isEditable())
                self.assertGreaterEqual(combo.findText(default), 0)
                self.assertEqual(combo.currentText(), default)
                combo.setEditText('/custom/topic')
                self.assertEqual(combo.currentText(), '/custom/topic')
                arrow = page.topic_dropdowns[combo]
                self.assertEqual(arrow.arrowType(), device_ui.Qt.DownArrow)
                arrow.click()
                APP.processEvents()
                self.assertTrue(combo.view().isVisible())
                combo.hidePopup()
        finally:
            page.shutdown()
            page.close()

    def test_changed_batch_settings_append_to_existing_set_and_finish_stays_at_bottom(self):
        page = self.make_page()
        page.n_caps.setValue(1)
        page.lidar_frames.setValue(1)
        page.resize(1400, 900)
        page.show()
        number = [0]
        def capture(link, image, cloud, seconds, folder, **kwargs):
            number[0] += 1
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f'sample_{number[0]}.npz'
            np.savez(path, image=np.zeros((30, 40, 3), np.uint8), xyz_mm=np.ones((50, 3), np.int16)*1000)
            return path, dict(images=3, lidar_frames=kwargs['lidar_frames'], lidar_points=50)
        try:
            with TemporaryDirectory() as tmp, patch.object(device_ui.core, 'RESULTS', Path(tmp)), \
                    patch('device_capture.capture_once', side_effect=capture), \
                    patch.object(device_ui.devreg, 'save_settings'), \
                    patch.object(page, 'prepare_capture_check') as prepare:
                page.go.click()
                self.wait_until(lambda: page.pending_capture is not None)
                original = page.pending_capture[2]
                self.assertTrue(page.capture_mode.isEnabled())
                self.assertTrue(page.lidar_frames.isEnabled())
                self.assertTrue(page.n_caps.isEnabled())
                self.assertFalse(page.img_topic.isEnabled())
                page.capture_mode.setCurrentIndex(1)
                page.n_caps.setValue(2)
                page.lidar_frames.setValue(10)
                page.capture_interval.setValue(1)
                page.go.click()
                self.assertFalse(page.capture_mode.isEnabled())
                self.wait_until(lambda: page.pending_capture is not None and len(page.pending_capture[3]) == 3)
                self.assertEqual(page.pending_capture[2], original)
                caps = page.pending_capture[3]
                self.assertEqual([sample['capture_mode'] for sample in caps], ['manual', 'automatic', 'automatic'])
                self.assertEqual([sample['lidar_target_frames'] for sample in caps], [1, 10, 10])
                self.assertEqual(len(list((original/'captures').glob('*.npz'))), 3)
                self.assertIs(page.cap_finish.parentWidget(), page.finish_bar)
                self.assertFalse(page.finish_bar.isHidden())
                APP.processEvents()
                footer = page.finish_bar.geometry()
                page.scroller.verticalScrollBar().setValue(page.scroller.verticalScrollBar().maximum())
                APP.processEvents()
                self.assertEqual(page.finish_bar.geometry(), footer)
                prepare.assert_not_called()
                page.cap_finish.click()
                prepare.assert_called_once()
        finally:
            page.shutdown()
            page.close()

    def test_switching_capture_mode_keeps_fields_and_button_geometry_stable(self):
        page = self.make_page()
        page.resize(1400, 1000)
        page.show()
        APP.processEvents()
        try:
            controls = (page.n_caps, page.img_topic, page.cloud_topic, page.capture_mode, page.go)
            before = [control.geometry() for control in controls]
            self.assertFalse(page.capture_interval.isHidden())
            self.assertFalse(page.capture_interval.isEnabled())
            page.capture_mode.setCurrentIndex(1)
            APP.processEvents()
            self.assertEqual(before, [control.geometry() for control in controls])
            self.assertTrue(page.capture_interval.isEnabled())
            left, right = page.capture_mode.buttons
            self.assertGreaterEqual(right.x() - (left.x() + left.width()), 8)
            for button in (left, right):
                self.assertLessEqual(button.y() + button.height(), page.capture_mode.height())
        finally:
            page.shutdown()
            page.close()

    def test_capture_defaults_toggle_and_lidar_controls_share_topic_row(self):
        page = self.make_page()
        try:
            self.assertEqual(page.n_caps.value(), 5)
            self.assertEqual(page.capture_mode.currentData(), 'manual')
            page.capture_mode.buttons[1].click()
            self.assertEqual(page.capture_mode.currentData(), 'automatic')
            self.assertFalse(page.capture_mode.buttons[0].isChecked())
            self.assertFalse(page.capture_interval.isHidden())
            grid = next(g for g in page.findChildren(QtWidgets.QGridLayout)
                        if g.indexOf(page.cloud_topic.parentWidget()) >= 0)
            self.assertEqual(grid.getItemPosition(grid.indexOf(page.cloud_topic.parentWidget()))[0],
                             grid.getItemPosition(grid.indexOf(page.lidar_frames.parentWidget()))[0])
            self.assertEqual(page.lidar_window()[1], 10)
            page.lidar_frames.setValue(1)
            self.assertEqual(page.lidar_window()[1], 1)
            self.assertLess(grid.getItemPosition(grid.indexOf(page.n_caps))[0],
                            grid.getItemPosition(grid.indexOf(page.img_topic.parentWidget()))[0])
        finally:
            page.shutdown()
            page.close()

    def test_saved_rows_remain_when_capturing_beyond_the_target(self):
        page = self.make_page()
        page.n_caps.setValue(2)
        page.show()
        number = [0]
        def capture(link, image, cloud, seconds, folder, **kwargs):
            number[0] += 1
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f'sample_{number[0]}.npz'
            np.savez(path, image=np.zeros((30, 40, 3), np.uint8), xyz_mm=np.ones((50, 3), np.int16)*1000)
            return path, dict(images=3, lidar_frames=1, lidar_points=50)
        try:
            with TemporaryDirectory() as tmp, patch.object(device_ui.core, 'RESULTS', Path(tmp)), \
                    patch('device_capture.capture_once', side_effect=capture), \
                    patch.object(device_ui.devreg, 'save_settings'), \
                    patch.object(page, 'prepare_capture_check') as prepare:
                page.capture_and_check()
                self.wait_until(lambda: page.capture_rows.count() == 1 and not page.cap_next.isHidden())
                first = next(Path(tmp).glob('*/captures/sample_1.npz'))
                delete_first = next(button for button in page.capture_rows.itemAt(0).widget().findChildren(QtWidgets.QPushButton)
                                    if button.text() == 'Delete pair')
                delete_first.click()
                self.wait_until(lambda: page.pending_capture is not None and len(page.pending_capture[3]) == 0)
                self.assertFalse(first.exists())
                self.assertEqual(page.capture_rows.count(), 0)
                page.cap_next.click()
                self.wait_until(lambda: page.capture_rows.count() == 1 and not page.cap_next.isHidden())
                page.cap_next.click()
                self.wait_until(lambda: page.pending_capture is not None)
                self.assertEqual(page.capture_rows.count(), 2)
                prepare.assert_not_called()
                page.cap_next.click()
                self.wait_until(lambda: page.pending_capture is not None and len(page.pending_capture[3]) == 3)
                self.assertEqual(page.capture_rows.count(), 3)
                self.assertEqual(page.n_caps.value(), 2)
                self.assertEqual(page.required_captures(), 3)
                self.assertEqual(len(list((page.pending_capture[2]/'captures').glob('*.npz'))), 3)
                prepare.assert_not_called()
                deleted = page.pending_capture[2]/'captures'/page.pending_capture[3][1]['file']
                deleted.with_suffix('.png').write_bytes(b'thumbnail')
                keep = Path(tmp)/'keep.npz'
                keep.touch()
                delete = next(button for button in page.capture_rows.itemAt(1).widget().findChildren(QtWidgets.QPushButton)
                              if button.text() == 'Delete pair')
                delete.click()
                self.assertFalse(deleted.exists())
                self.assertFalse(deleted.with_suffix('.png').exists())
                self.assertTrue(keep.exists())
                self.assertEqual(page.capture_rows.count(), 2)
                self.assertEqual(len(page.pending_capture[3]), 2)
                self.assertFalse(page.cap_finish.isEnabled())
                page.cap_next.click()
                self.wait_until(lambda: page.pending_capture is not None and len(page.pending_capture[3]) == 3)
                self.assertEqual(page.capture_rows.getItemPosition(0)[:2], (0, 0))
                self.assertEqual(page.capture_rows.getItemPosition(1)[:2], (0, 1))
                self.assertEqual(page.capture_rows.getItemPosition(2)[:2], (1, 0))
                page.cap_finish.click()
                prepare.assert_called_once()
        finally:
            page.shutdown()
            page.close()

    def test_completed_capture_set_waits_for_explicit_finish(self):
        for count in (1, 3):
            page = self.make_page()
            page.n_caps.setValue(count)
            try:
                with TemporaryDirectory() as tmp, patch.object(page, 'prepare_capture_check') as prepare:
                    out = Path(tmp)
                    (out / 'captures').mkdir()
                    for index in range(count):
                        (out / 'captures' / f'{index}.npz').touch()
                    caps = [dict(images=3, lidar_frames=1) for _ in range(count)]
                    page.captured(page.current, 'test', out, caps)
                    prepare.assert_not_called()
                    self.assertFalse(page.cap_finish.isHidden())
                    self.assertTrue(page.go.isEnabled())
                    page.cap_finish.click()
                    prepare.assert_called_once_with(page.current, 'test', out, caps)
            finally:
                page.shutdown()
                page.close()

    def test_partial_capture_set_cannot_start_processing(self):
        page = self.make_page()
        page.n_caps.setValue(3)
        try:
            with TemporaryDirectory() as tmp, patch.object(page, 'prepare_capture_check') as prepare, \
                    patch.object(device_ui, 'warn') as warn:
                out = Path(tmp)
                (out / 'captures').mkdir()
                (out / 'captures' / 'one.npz').touch()
                page.captured(page.current, 'test', out, [dict(images=3, lidar_frames=1)])
                self.assertFalse(page.cap_finish.isEnabled())
                page.process_captures()
                prepare.assert_not_called()
                warn.assert_called_once()
        finally:
            page.shutdown()
            page.close()

    def test_camera_and_cloud_are_displayed_side_by_side_without_calibration(self):
        page = self.make_page()
        try:
            page.params = None
            page.snap = dict(image=np.zeros((40, 30, 3), dtype=np.uint8),
                             cloud=np.array([[1., 0., 0., 1.], [2., .5, 1., 2.]]),
                             image_hz=2., cloud_hz=1.)
            page.render_snapshot()
            row = page.live_box.itemAt(0).layout()
            self.assertIsInstance(row, QtWidgets.QHBoxLayout)
            self.assertEqual(row.count(), 2)
            self.assertEqual(page.cloud_preview.total, 2)
            self.assertFalse(page.camera_preview.current().isNull())
            page.snap['image'] = None
            page.render_snapshot()
            self.assertEqual(page.cloud_preview.total, 2)
        finally:
            page.shutdown()
            page.close()

    def test_cloud_raster_handles_empty_invalid_and_single_returns(self):
        for cloud in (np.empty((0, 4)), np.array([[np.nan, 0, 0, 1]]),
                      np.array([[1., 2., 3., 4.]])):
            view = CloudView(cloud)
            frame = view.render_cloud(200, 160)
            self.assertEqual(frame.shape, (160, 200, 3))
            self.assertEqual(frame.dtype, np.uint8)
            if view.total:
                self.assertGreater(len(np.unique(frame.reshape(-1, 3), axis=0)), 1)
            view.close()

    def make_page(self):
        with patch.object(device_ui.devreg, 'load', return_value=[]), \
                patch.object(device_ui.DevicePage, 'probe_all'):
            page = device_ui.DevicePage(None, choose_mode=False)
        page.current = dict(key='test:1', name='Test sensor', image_topic='/camera/image_raw', cloud_topic='/livox/lidar')
        page.link = Mock()
        page.link.describe.return_value = 'Test transport'
        page.params = dm.file_params(RAW)
        page.params_source = 'rock@sensor — /config/pipeline.yaml'
        page.topics = {}
        page.show_connected()
        return page

    def wait_until(self, predicate):
        end = time.monotonic() + 3
        while not predicate() and time.monotonic() < end:
            QtTest.QTest.qWait(10)
        self.assertTrue(predicate())

    def test_manual_ui_requires_next_button_and_finishes_only_after_last(self):
        page = self.make_page()
        page.n_caps.setValue(2)
        page.show()
        capture = Mock(return_value=(Path('test.npz'), dict(images=3, lidar_frames=4)))
        try:
            with patch('device_capture.capture_once', capture), \
                    patch.object(device_ui.devreg, 'save_settings'), patch.object(page, 'captured') as completed:
                page.capture_and_check()
                self.wait_until(lambda: not page.cap_next.isHidden())
                self.assertEqual(capture.call_count, 1)
                completed.assert_not_called()
                self.assertFalse(page.capture_mode.isEnabled())
                page.cap_next.click()
                self.wait_until(lambda: completed.call_count == 1)
                self.assertEqual(capture.call_count, 2)
        finally:
            page.shutdown()
            page.close()

    def test_automatic_ui_shows_interval_and_runs_without_next_button(self):
        page = self.make_page()
        page.capture_mode.setCurrentIndex(1)
        page.capture_interval.setValue(1)
        page.n_caps.setValue(2)
        capture = Mock(return_value=(Path('test.npz'), dict(images=3, lidar_frames=4)))
        try:
            self.assertFalse(page.capture_interval.isHidden())
            with patch('device_capture.capture_once', capture), \
                    patch.object(device_ui.devreg, 'save_settings'), patch.object(page, 'captured') as completed:
                page.capture_and_check()
                self.wait_until(lambda: 'Next capture in' in page.cap_text.text())
                self.assertTrue(page.cap_next.isHidden())
                self.assertEqual(capture.call_count, 1)
                self.wait_until(lambda: completed.call_count == 1)
                self.assertEqual(capture.call_count, 2)
        finally:
            page.shutdown()
            page.close()

    def test_manual_waits_for_each_user_trigger(self):
        stop, trigger = threading.Event(), threading.Event()
        captured, waits = [], []
        def progress(value):
            if value.get('waiting'):
                waits.append((value['k'], list(captured)))
                trigger.set()
        def capture(index):
            captured.append(index)
            return dict(images=3, lidar_frames=4)
        result = run_sequence(capture, 3, stop, progress, next_capture=trigger)
        self.assertEqual(waits, [(1, [0]), (2, [0, 1])])
        self.assertEqual(len(result), 3)
        self.assertFalse(trigger.is_set())

    def test_automatic_interval_is_after_completion_with_no_final_wait(self):
        starts, events = [], []
        def capture(index):
            starts.append(time.monotonic())
            return dict(images=3, lidar_frames=4)
        run_sequence(capture, 3, threading.Event(), events.append, interval=.025)
        self.assertGreaterEqual(starts[1] - starts[0], .02)
        self.assertGreaterEqual(starts[2] - starts[1], .02)
        self.assertTrue(events[-1]['done'])
        self.assertEqual(list(dict.fromkeys(x['k'] for x in events if 'countdown' in x)), [1, 2])

    def test_stop_during_manual_wait_prevents_next_capture(self):
        stop = threading.Event()
        capture = Mock(return_value=dict(images=3, lidar_frames=4))
        def progress(event):
            if event.get('waiting'):
                stop.set()
        with self.assertRaises(InterruptedError):
            run_sequence(capture, 3, stop, progress, next_capture=threading.Event())
        self.assertEqual(capture.call_count, 1)

    def test_stop_during_automatic_wait_prevents_next_capture(self):
        stop = threading.Event()
        capture = Mock(return_value=dict(images=3, lidar_frames=4))
        def progress(event):
            if 'countdown' in event:
                stop.set()
        with self.assertRaises(InterruptedError):
            run_sequence(capture, 3, stop, progress, interval=60)
        self.assertEqual(capture.call_count, 1)


if __name__ == '__main__':
    unittest.main()
