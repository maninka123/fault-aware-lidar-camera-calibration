"""Option inspection shows real, constrained matrices without applying a calibration."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import copy
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import appcore
import numpy as np
from PyQt5 import QtCore, QtWidgets, QtTest
from matrix_preview import MatrixPreview, ResultHeader
from maintenance_model import Model
from ui_common import BAD, INK, QSS, button
from ui_widgets import OptionsResults, action_flow, PageTabs
from update_options import candidate_calibration, fit_candidates, projection_movement

APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
APP.setStyleSheet(QSS)


def calibration():
    return dict(intrinsics=dict(camera_matrix=[[200., 0., 100.], [0., 200., 100.], [0., 0., 1.]],
                                distortion_coefficients=[0., 0., 0., 0.]),
                extrinsics=dict(transform_lidar_to_camera=np.eye(4).tolist()))


class MatrixPreviewTests(unittest.TestCase):
    def test_matrices_collapse_without_blank_space_or_kept_labels(self):
        parent = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(parent)
        preview = MatrixPreview()
        preview.set_calibrations(dict(existing=calibration(), extrinsic=calibration()))
        preview.set_mode('existing')
        header = ResultHeader(QtWidgets.QLabel('Result'), preview)
        layout.addWidget(header)
        layout.addWidget(QtWidgets.QWidget(), 1)
        parent.resize(1600, 900)
        parent.show()
        APP.processEvents()
        expanded = header.height()
        self.assertTrue(all(not delta.text() for value, delta in preview.cells.values()))
        preview.set_expanded(False)
        preview.set_mode('extrinsic')
        APP.processEvents()
        APP.processEvents()
        self.assertTrue(preview.body.isHidden())
        self.assertLess(header.height(), expanded)
        preview.set_expanded(True)
        self.assertFalse(preview.body.isHidden())
        parent.close()

    def test_history_names_use_the_capture_folder(self):
        self.assertEqual(appcore.capture_label('C:/captures/Bags_2026_G51/'), 'Bags_2026_G51')
        self.assertEqual(appcore.capture_label('C:\\captures\\Bags_2026_G51'), 'Bags_2026_G51')
        self.assertEqual(appcore.capture_label(None), '')

    def test_candidates_preserve_the_group_that_the_option_keeps_fixed(self):
        original = calibration()
        untouched = copy.deepcopy(original)
        model = Model(np.eye(3), (200, 200), dict(cx=100., cy=100., radius=95.), np.zeros(4))
        parameters = np.zeros(13)
        parameters[3] = .03
        parameters[6:10] = [220., 210., 101., 102.]
        parameters[10:12] = [.01, .02]
        alignment = candidate_calibration(original, model, parameters, 'extrinsic')
        camera = candidate_calibration(original, model, parameters, 'intrinsic')
        self.assertEqual(alignment['intrinsics'], original['intrinsics'])
        self.assertEqual(camera['extrinsics'], original['extrinsics'])
        self.assertNotEqual(alignment['extrinsics'], original['extrinsics'])
        self.assertNotEqual(camera['intrinsics'], original['intrinsics'])
        self.assertEqual(original, untouched)

    def test_card_selection_changes_matrices_and_only_the_icon_opens_help(self):
        original = calibration()
        alignment = copy.deepcopy(original)
        alignment['extrinsics']['transform_lidar_to_camera'][0][3] = .04
        camera = copy.deepcopy(original)
        camera['intrinsics']['camera_matrix'][0][0] = 220.
        data = dict(selected='extrinsic', status='supported', reason='Update alignment.', folds=3,
                    scores=dict(existing=.1, extrinsic=.2, intrinsic=.18, full=.21),
                    movements=dict(extrinsic=dict(median_px=18.66)),
                    calibrations=dict(existing=original, extrinsic=alignment, intrinsic=camera))
        untouched = copy.deepcopy(data)
        cards = OptionsResults(data)
        preview = MatrixPreview()
        preview.set_calibrations(data['calibrations'])
        cards.mode_changed.connect(preview.set_mode)
        cards.resize(1500, 300)
        cards.show()
        APP.processEvents()
        for mode, expected in [('existing', '200.0000'), ('intrinsic', '220.0000'), ('extrinsic', '200.0000')]:
            QtTest.QTest.mouseClick(cards.tiles[mode], QtCore.Qt.LeftButton)
            self.assertEqual(preview.mode, mode)
            self.assertEqual(preview.cells['K', 0, 0][0].text(), expected)
            self.assertIsNone(cards.detail_dialog)
        self.assertIn(INK, preview.cells['T', 0, 3][0].styleSheet())
        self.assertNotIn(BAD, preview.cells['T', 0, 3][0].styleSheet())
        self.assertIn(BAD, preview.cells['T', 0, 3][1].styleSheet())
        self.assertIn('+40.00 mm', preview.cells['T', 0, 3][1].text())
        cards.help_buttons['extrinsic'].click()
        self.assertTrue(cards.detail_dialog.isVisible())
        self.assertEqual(preview.mode, 'extrinsic')
        cards.detail_dialog.close()
        preview.set_mode('full')
        self.assertEqual(preview.cells['K', 0, 0][0].text(), '—')
        self.assertIn('not saved', preview.note.text())
        self.assertEqual(data, untouched)
        cards.close()

    def test_heading_tracks_the_option_only_when_expanded(self):
        preview = MatrixPreview()
        preview.set_mode('intrinsic')
        self.assertEqual(preview.heading.text(), 'Camera only')
        preview.set_expanded(False)
        self.assertEqual(preview.heading.text(), 'Calibration matrices')
        preview.set_mode('full')
        self.assertEqual(preview.heading.text(), 'Calibration matrices')
        preview.set_expanded(True)
        self.assertEqual(preview.heading.text(), 'Camera + alignment')
        preview.close()

    def test_preview_fitting_keeps_constrained_parameters_fixed(self):
        model = Model(np.eye(3), (200, 200), dict(cx=100., cy=100., radius=95.), np.zeros(4))
        existing = np.zeros(13)
        existing[6:10] = [200., 200., 100., 100.]
        start = existing.copy()
        start[:6] = .1
        start[6:12] += .1
        def refine(caps, model, parameters, free, *args, **kwargs):
            value = parameters.copy()
            value[free] += .001
            return value, {}
        with patch('calib.refine', side_effect=refine):
            for mode, fixed in [('extrinsic', slice(6, 12)), ('intrinsic', slice(0, 6))]:
                candidates = fit_candidates([], model, [('start', start)], existing, mode, 'k1-k2',
                                            dict(refine=dict(passes=1)), {}, {}, lambda *args: dict(lift=2.))
                self.assertEqual(len(candidates), 1)
                np.testing.assert_array_equal(candidates[0]['p'][fixed], existing[fixed])

    def test_movement_is_projection_displacement_and_current_is_zero(self):
        model = SimpleNamespace(to_camera=lambda xyz, signs, p: xyz + np.array([p[0], 0., 0.]),
                                project=lambda xyz, p: (xyz[:, 0], xyz[:, 1], np.ones(len(xyz), bool)))
        points = np.array([[0., 0., 1.], [1., 1., 2.]])
        self.assertEqual(projection_movement(model, [0.], [18.66], points)['median_px'], 18.66)
        self.assertEqual(projection_movement(model, [0.], [0.], points)['median_px'], 0.)

    def test_actions_share_a_row_when_space_allows_and_wrap_without_overlapping(self):
        controls = [button(text) for text in ['Save calibration', 'Accept calibration', 'Open folder', 'Show report',
                                             'Check again', 'Full calibration from scratch']]
        widget = action_flow(controls)
        needed = sum(control.sizeHint().width() for control in controls) + 8 * (len(controls) - 1)
        widget.resize(needed + 1, 150)
        widget.show()
        APP.processEvents()
        self.assertEqual(len({control.y() for control in controls}), 1)
        widget.resize(500, 250)
        APP.processEvents()
        self.assertGreater(len({control.y() for control in controls}), 1)
        for index, control in enumerate(controls):
            for other in controls[index + 1:]:
                self.assertFalse(control.geometry().intersects(other.geometry()))
        widget.close()


if __name__ == '__main__':
    unittest.main()
