"""The legacy example must survive UI entry and project with all fisheye terms."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import appcore as core
import cv2
import numpy as np
from PyQt5 import QtWidgets
from app import SetupPage
from ui_common import ManualDialog
from settings import load_calibration
from maintain import params_of
from maintenance_model import Model
from update_options import free_parameters, valid_solution

APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


class ExampleCalibrationTests(unittest.TestCase):
    def test_example_button_loads_legacy_values(self):
        page = SetupPage()
        self.assertIsNone(page.cal)
        page.example_cal_button.click()
        self.assertEqual(page.cal['path'], str(core.EXAMPLE_CALIBRATION.resolve()))
        self.assertEqual(page.cal_combo.currentText(), core.EXAMPLE_LABEL)
        self.assertEqual(page.cal['intrinsics']['image_size'], [484, 366])
        self.assertEqual(page.cal['intrinsics']['k3'], 0.83268208)
        self.assertEqual(page.cal['intrinsics']['k4'], -0.46339204)
        legacy = core.PROJECT / 'results' / '2025_02_initial_legacy' / 'enclosure'
        if legacy.exists():
            original_i = json.loads((legacy / 'intrinsics.json').read_text())
            original_e = json.loads((legacy / 'extrinsics.json').read_text())
            example = json.loads(core.EXAMPLE_CALIBRATION.read_text())
            self.assertEqual(example['intrinsics']['camera_matrix'], original_i['camera_matrix'])
            self.assertEqual(example['intrinsics']['distortion_coefficients'], original_i['distortion_coefficients'])
            self.assertEqual(example['extrinsics']['transform_lidar_to_camera'], original_e['transform_lidar_to_camera'])
        page.close()

    def test_editing_example_preserves_all_coefficients_and_transform(self):
        original = load_calibration(core.EXAMPLE_CALIBRATION)
        for tab in (0, 1):
            with self.subTest(tab=tab), TemporaryDirectory() as folder, patch.object(core, 'INPUTS', Path(folder)):
                dialog = ManualDialog(None, core.calibration_info(core.EXAMPLE_CALIBRATION))
                dialog.tabs.setCurrentIndex(tab)
                dialog.accept()
                edited = load_calibration(dialog.path)
                np.testing.assert_allclose(edited.K, original.K, atol=1e-10, rtol=0)
                np.testing.assert_array_equal(edited.D, original.D)
                np.testing.assert_allclose(edited.T, original.T, atol=1e-11, rtol=0)
                self.assertEqual(edited.raw['image_size'], [484, 366])
                dialog.close()

    def test_projection_matches_opencv_and_export_retains_higher_terms(self):
        cal = load_calibration(core.EXAMPLE_CALIBRATION)
        model = Model(cal.T[:3, :3], (484, 366), dict(cx=242, cy=183, radius=180), cal.D)
        p = params_of(cal, model.R0)
        points = np.array([[0., 0., 2.], [.5, -.4, 1.], [-1.2, .8, 1.], [2., 1., 2.]])
        u, v, _ = model.project(points, p)
        expected, _ = cv2.fisheye.projectPoints(points.reshape(-1, 1, 3), np.zeros(3), np.zeros(3), cal.K, cal.D)
        np.testing.assert_allclose(np.c_[u, v], expected.reshape(-1, 2), atol=1e-10)
        p[10:12] += .01
        _, distortion, _ = model.matrices(p)
        np.testing.assert_array_equal(distortion[2:], cal.D[2:])
        self.assertIn(11, free_parameters('full', cal.model))

    def test_higher_order_validation_checks_the_capture_ray_range(self):
        cal = load_calibration(core.EXAMPLE_CALIBRATION)
        model = Model(cal.T[:3, :3], (484, 366), dict(cx=242, cy=183, radius=180), cal.D)
        p = params_of(cal, model.R0)
        camera = np.array([[0., 0., 2.], [1., 0., 1.]])
        lidar = (camera - cal.T[:3, 3]) @ cal.T[:3, :3]
        capture = type('Capture', (), dict(xyz=lidar, sgn=np.zeros(2)))()
        angle = model.validation_angle([capture], p)
        self.assertAlmostEqual(angle, np.pi / 4)
        self.assertTrue(valid_solution(p, model.higher_order, angle))
        self.assertFalse(valid_solution(p, model.higher_order, np.radians(70)))


if __name__ == '__main__':
    unittest.main()
