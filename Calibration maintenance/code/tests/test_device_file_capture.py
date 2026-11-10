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

    def test_resolution_requires_file_or_explicit_live_image(self):
        raw = {k: v for k, v in RAW.items() if not k.startswith('image_')}
        with self.assertRaisesRegex(ValueError, 'dimensions'):
            dm.file_params(raw)
        p = dm.file_params(raw, image_size=(640, 480))
        self.assertEqual((p['image_width'], p['image_height']), (640, 480))
        self.assertIn('received camera image', p['notes'][0])

    def test_yaml_errors_are_reported(self):
        for text in ('', 'other: {}', 'pointcloud_colorizer: ['):
            with self.assertRaises(ValueError):
                device_yaml.read_params(text)

    def test_view_contains_exact_matrices_and_source(self):
        view = device_ui.device_calibration_view(dm.file_params(RAW), 'rock@sensor — /config/pipeline.yaml')
        blocks = view.findChildren(QtWidgets.QPlainTextEdit)
        self.assertEqual(len(blocks), 2)
        self.assertTrue(all(b.isReadOnly() for b in blocks))
        self.assertIn('251', blocks[0].toPlainText())
        self.assertIn('-0.05', blocks[1].toPlainText())
        self.assertIn('/config/pipeline.yaml', ' '.join(w.text() for w in view.findChildren(QtWidgets.QLabel)))
        view.close()

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
            grid = next(g for g in page.cloud_topic.parentWidget().findChildren(QtWidgets.QGridLayout)
                        if g.indexOf(page.cloud_topic) >= 0)
            self.assertEqual(grid.getItemPosition(grid.indexOf(page.cloud_topic))[0],
                             grid.getItemPosition(grid.indexOf(page.lidar_frames.parentWidget()))[0])
            self.assertEqual(page.lidar_window()[1], 10)
            page.lidar_frames.setValue(1)
            self.assertEqual(page.lidar_window()[1], 1)
            self.assertLess(grid.getItemPosition(grid.indexOf(page.n_caps))[0],
                            grid.getItemPosition(grid.indexOf(page.img_topic))[0])
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
        self.assertEqual([x['k'] for x in events if 'countdown' in x], [1, 2])

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
