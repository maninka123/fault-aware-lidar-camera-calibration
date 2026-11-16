"""Selected calibration exports must survive the real UI/checker import path."""
import copy
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import appcore as core
import numpy as np
from PyQt5 import QtWidgets
from app import RunPage, SetupPage
from calibration_io import MODE_LABELS, read_calibration, write_calibration_txt
from settings import load_calibration
from ui_common import QSS, button, label
from ui_widgets import OptionsResults

APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
APP.setStyleSheet(QSS)


def candidates():
    existing = json.loads(core.EXAMPLE_CALIBRATION.read_text(encoding='utf-8'))
    alignment, camera = copy.deepcopy(existing), copy.deepcopy(existing)
    alignment['extrinsics']['transform_lidar_to_camera'][0][3] += .123456789012345
    camera['intrinsics']['camera_matrix'][0][0] += 12.3456789012345
    camera['intrinsics']['distortion_coefficients'][0] += .0123456789012345
    full = copy.deepcopy(camera)
    full['extrinsics'] = copy.deepcopy(alignment['extrinsics'])
    return dict(existing=existing, extrinsic=alignment, intrinsic=camera, full=full)


class CalibrationTxtTests(unittest.TestCase):
    def test_each_option_round_trips_all_values_and_metadata_at_full_precision(self):
        calibrations = candidates()
        untouched = copy.deepcopy(calibrations)
        with TemporaryDirectory() as temporary:
            for mode, calibration in calibrations.items():
                with self.subTest(mode=mode):
                    path = Path(temporary) / f'{mode}.txt'
                    write_calibration_txt(path, calibration, mode, 'example check')
                    self.assertEqual(read_calibration(path), calibration)
                    loaded = load_calibration(path)
                    np.testing.assert_array_equal(loaded.K, calibration['intrinsics']['camera_matrix'])
                    np.testing.assert_array_equal(loaded.D, calibration['intrinsics']['distortion_coefficients'])
                    np.testing.assert_array_equal(loaded.T, calibration['extrinsics']['transform_lidar_to_camera'])
                    self.assertEqual(loaded.raw['image_size'], calibration['image_size'])
                    self.assertIn(f'# Selected option: {MODE_LABELS[mode]}', path.read_text(encoding='utf-8'))
                    self.assertEqual(core.calibration_info(path)['path'], str(path.resolve()))
        self.assertEqual(calibrations, untouched)

    def test_click_export_open_existing_and_start_a_check_with_the_same_txt(self):
        calibrations = candidates()
        page = RunPage(None)
        page.name = 'roundtrip_check'
        page.export_calibrations = calibrations
        page.export_txt_btn = button('Save TXT', slot=page.save_selected_txt)
        page.export_mode_label = label()
        page.matrix_preview.set_calibrations(calibrations)
        cards = OptionsResults(dict(selected='extrinsic', status='supported', reason='Update alignment.', folds=3,
                                    scores=dict(existing=.1, extrinsic=.2, intrinsic=.15, full=.21)))
        cards.mode_changed.connect(page.preview_mode)
        setup = SetupPage()
        with TemporaryDirectory() as temporary:
            page.export_dataset_folder = Path(temporary)
            for mode in calibrations:
                with self.subTest(mode=mode):
                    cards.select_mode(mode)
                    path = Path(temporary) / f'{mode}.txt'
                    with patch.object(QtWidgets.QFileDialog, 'getSaveFileName', return_value=(str(path), '')) as save_dialog:
                        page.export_txt_btn.click()
                    self.assertEqual(Path(save_dialog.call_args.args[2]).parent, Path(temporary))
                    self.assertEqual(read_calibration(path), calibrations[mode])
                    with patch.object(QtWidgets.QFileDialog, 'getOpenFileName', return_value=(str(path), '')):
                        setup.open_cal()
                    self.assertFalse(setup.cal_err.isVisible())
                    self.assertEqual(setup.cal['path'], str(path.resolve()))
                    self.assertEqual(setup.cal['intrinsics']['fx'], calibrations[mode]['intrinsics']['camera_matrix'][0][0])
                    with patch.object(core, 'RESULTS', Path(temporary) / 'runs'):
                        _, _, command = core.new_run(path, temporary, 'compare', 'test', name=mode)
                    self.assertEqual(command[command.index('--calibration')+1], str(path))
                    np.testing.assert_array_equal(load_calibration(path).T,
                                                  calibrations[mode]['extrinsics']['transform_lidar_to_camera'])
            page.export_calibrations = {'existing': calibrations['existing']}
            page.preview_mode('full')
            self.assertFalse(page.export_txt_btn.isEnabled())
        cards.close()
        page.close()
        setup.close()

    def test_import_rejects_wrong_units_and_transform_direction(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / 'calibration.txt'
            write_calibration_txt(path, candidates()['existing'], 'existing')
            original = path.read_text(encoding='utf-8')
            for old, new in [('translation_unit = metres', 'translation_unit = millimetres'),
                             ('transform_direction = lidar_to_camera', 'transform_direction = camera_to_lidar')]:
                path.write_text(original.replace(old, new), encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'metres.*LiDAR'):
                    read_calibration(path)

    def test_export_rejects_invalid_numbers_before_creating_a_file(self):
        bad = candidates()['existing']
        bad['intrinsics']['camera_matrix'][0][0] = float('nan')
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / 'bad.txt'
            with self.assertRaisesRegex(ValueError, 'finite'):
                write_calibration_txt(path, bad, 'existing')
            self.assertFalse(path.exists())

    def test_capture_names_are_readable_and_distinguishable(self):
        self.assertEqual(core.capture_display_name('164327_828105', 1), 'Capture 01 · 16:43:27')
        self.assertEqual(core.capture_display_name('164411_450626', 2), 'Capture 02 · 16:44:11')
        self.assertEqual(core.capture_display_name('capture_001', 1), 'Capture 01')


if __name__ == '__main__':
    unittest.main()
