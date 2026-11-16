"""Explore each result without changing the recommendation or calibration."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PyQt5 import QtCore, QtWidgets, QtTest
from ui_common import QSS
from ui_widgets import OptionsResults
from option_help import OptionHelpDialog, UpdateIllustration, comparison_explanation

APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
APP.setStyleSheet(QSS)


def comparison():
    return dict(selected='extrinsic', status='supported', reason='Update alignment.', folds=10,
                minimum_gain=.01, scores=dict(existing=.121, extrinsic=.143, intrinsic=.138, full=.151))


class OptionHelpTests(unittest.TestCase):
    def test_only_help_links_open_the_explanation_without_changing_results(self):
        data = comparison()
        original = copy.deepcopy(data)
        widget = OptionsResults(data)
        widget.resize(1500, 300)
        widget.show()
        APP.processEvents()
        for mode, tile in widget.tiles.items():
            QtTest.QTest.mouseClick(tile, QtCore.Qt.LeftButton)
            self.assertTrue(widget.detail_dialog is None or not widget.detail_dialog.isVisible())
            number = next(child for child in tile.findChildren(QtWidgets.QLabel) if child.text().endswith('%'))
            QtTest.QTest.mouseClick(number, QtCore.Qt.LeftButton)
            self.assertTrue(widget.detail_dialog is None or not widget.detail_dialog.isVisible())
            QtTest.QTest.mouseClick(widget.help_buttons[mode], QtCore.Qt.LeftButton)
            dialog = widget.detail_dialog
            self.assertTrue(dialog.isVisible())
            self.assertEqual(dialog.mode, mode)
            self.assertIn('edge matches on held-out data', dialog.score_text.text())
            dialog.close()
            self.assertEqual(dialog.animation.state(), QtCore.QAbstractAnimation.Stopped)
        help_button = widget.help_buttons['full']
        help_button.setFocus()
        QtTest.QTest.keyClick(help_button, QtCore.Qt.Key_Space)
        self.assertEqual(widget.detail_dialog.mode, 'full')
        self.assertTrue(widget.detail_dialog.isVisible())
        widget.detail_dialog.close()
        self.assertEqual(data, original)
        widget.resize(700, 450)
        APP.processEvents()
        self.assertEqual(widget.row.getItemPosition(3)[:2], (1, 1))
        widget.close()

    def test_animation_can_pause_scrub_and_respect_reduced_motion(self):
        with patch('option_help.system_reduces_motion', return_value=False):
            dialog = OptionHelpDialog(comparison(), 'extrinsic')
        dialog.show()
        APP.processEvents()
        dialog.animation.setCurrentTime(1100)
        self.assertAlmostEqual(dialog.canvas.progress, .5, places=2)
        dialog.pause.click()
        self.assertEqual(dialog.animation.state(), QtCore.QAbstractAnimation.Paused)
        dialog.pause.click()
        self.assertEqual(dialog.animation.state(), QtCore.QAbstractAnimation.Running)
        dialog.slider.setValue(25)
        self.assertEqual(dialog.animation.state(), QtCore.QAbstractAnimation.Stopped)
        self.assertEqual(dialog.canvas.progress, .25)
        dialog.reduced.setChecked(True)
        self.assertEqual(dialog.canvas.progress, 1)
        self.assertFalse(dialog.replay.isEnabled())
        dialog.tabs.setCurrentIndex(1)
        self.assertEqual(dialog.animation.state(), QtCore.QAbstractAnimation.Stopped)
        dialog.set_mode('intrinsic')
        self.assertEqual(dialog.animation.state(), QtCore.QAbstractAnimation.Stopped)
        dialog.close()

    def test_illustration_separates_pose_from_lens_changes(self):
        canvas = UpdateIllustration()
        canvas.progress = 1
        outcomes = {}
        for mode in ('existing', 'extrinsic', 'intrinsic', 'full'):
            canvas.mode = mode
            outcomes[mode] = canvas.projected_point(.8, .6)
            self.assertEqual(canvas.sensor_pose() == (0, 0, 0), mode in ('existing', 'intrinsic'))
        self.assertEqual(outcomes['full'], (.8, .6))
        self.assertEqual(len(set(outcomes.values())), 4)

    def test_score_explanation_uses_the_saved_threshold_and_handles_missing_scores(self):
        data = comparison()
        explanation = comparison_explanation(data)
        self.assertIn('0.8 percentage points higher', explanation)
        self.assertIn('below the 1-point minimum', explanation)
        data['minimum_gain'] = .005
        self.assertIn('did not pass all the consistency checks', comparison_explanation(data))
        data['scores']['full'] = None
        dialog = OptionHelpDialog(data, 'full')
        self.assertIn('no reliable score', dialog.score_text.text())
        self.assertNotIn('0.0%', dialog.score_text.text())
        dialog.close()

    def test_explanation_tabs_keep_their_labels_readable(self):
        dialog = OptionHelpDialog(comparison(), 'extrinsic')
        dialog.resize(600, 700)
        dialog.show()
        APP.processEvents()
        bar = dialog.tabs.tabBar()
        for index in range(bar.count()):
            option = QtWidgets.QStyleOptionTab()
            option.initFrom(bar)
            option.rect = bar.tabRect(index)
            option.text = bar.tabText(index)
            option.shape = QtWidgets.QTabBar.RoundedNorth
            text_rect = bar.style().subElementRect(QtWidgets.QStyle.SE_TabBarTabText, option, bar)
            self.assertGreaterEqual(text_rect.width(), bar.fontMetrics().horizontalAdvance(option.text))
        dialog.close()


if __name__ == '__main__':
    unittest.main()
