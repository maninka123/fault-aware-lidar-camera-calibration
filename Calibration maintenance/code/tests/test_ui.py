"""Exercise shared controls and responsive layout without a connected sensor."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import appcore
from PyQt5 import QtCore, QtWidgets, QtSvg, QtTest
from ui_common import QSS, CHEVRON_DOWN, table
from ui_widgets import SourceStrip, UpdateChoice
from pose_view import ComparisonColumns, CalibrationPosePanel
import numpy as np

APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
APP.setStyle('Fusion')
APP.setStyleSheet(QSS)


class InterfaceTests(unittest.TestCase):
    def test_dropdown_arrow_is_shared_in_normal_editable_and_disabled_controls(self):
        self.assertTrue(QtSvg.QSvgRenderer(CHEVRON_DOWN).isValid())
        controls = [UpdateChoice(), QtWidgets.QComboBox(), QtWidgets.QComboBox()]
        controls[1].setEditable(True)
        controls[2].setEnabled(False)
        widths = []
        for control in controls:
            control.addItem('Test choice')
            control.resize(320, 40)
            control.ensurePolished()
            option = QtWidgets.QStyleOptionComboBox()
            control.initStyleOption(option)
            rect = control.style().subControlRect(QtWidgets.QStyle.CC_ComboBox, option,
                                                  QtWidgets.QStyle.SC_ComboBoxArrow, control)
            widths.append(rect.width())
            self.assertGreater(rect.width(), 0)
            control.close()
        self.assertEqual(len(set(widths)), 1)

    def test_sources_open_the_correct_file_or_folder(self):
        with TemporaryDirectory() as folder:
            source = Path(folder) / 'current.json'
            source.write_text('{}')
            strip = SourceStrip()
            strip.set_paths(source, folder, folder)
            with patch('ui_widgets.os.startfile', create=True) as open_file:
                for location in strip.locations:
                    location.open_button.click()
                self.assertEqual([call.args[0] for call in open_file.call_args_list],
                                 [str(source), folder, folder])
            strip.close()

    def test_table_columns_keep_text_space_and_matching_alignment(self):
        view = table(['Parameter', 'Previous', 'Pixel effect'],
                     [['Translation x', '123.4 mm', '3.2 px large']], numeric=(1,), stretch=(0, 2))
        for width in (420, 1000):
            view.resize(width, view.height())
            view.show()
            APP.processEvents()
            self.assertTrue(all(view.columnWidth(i) >= view.content_widths[i] for i in range(3)))
            self.assertTrue(view.horizontalHeader().defaultAlignment() & QtCore.Qt.AlignLeft)
            self.assertTrue(view.horizontalHeaderItem(1).textAlignment() & QtCore.Qt.AlignRight)
            self.assertTrue(view.item(0, 2).textAlignment() & QtCore.Qt.AlignLeft)
        view.close()

    def test_pose_moves_with_drag_and_stacks_on_small_windows(self):
        original = np.eye(4)
        refined = np.eye(4)
        refined[:3, 3] = [.04, -.02, .06]
        comparison = {'previous': {'extrinsics': {'matrix': original}},
                      'new': {'extrinsics': {'matrix': refined}}}
        pose = CalibrationPosePanel(comparison)
        widget = ComparisonColumns(QtWidgets.QWidget(), pose)
        widget.resize(1300, 600)
        widget.show()
        APP.processEvents()
        self.assertEqual(widget.box.direction(), QtWidgets.QBoxLayout.LeftToRight)
        canvas = pose.canvas
        before = canvas.yaw
        QtTest.QTest.mousePress(canvas, QtCore.Qt.LeftButton, pos=QtCore.QPoint(80, 80))
        move = type('Move', (), {'pos': lambda self: QtCore.QPoint(110, 95)})()
        canvas.mouseMoveEvent(move)
        QtTest.QTest.mouseRelease(canvas, QtCore.Qt.LeftButton, pos=QtCore.QPoint(110, 95))
        self.assertNotEqual(canvas.yaw, before)
        canvas.reset_view()
        self.assertEqual(canvas.yaw, before)
        widget.resize(850, 1000)
        APP.processEvents()
        self.assertEqual(widget.box.direction(), QtWidgets.QBoxLayout.TopToBottom)
        widget.close()


if __name__ == '__main__':
    unittest.main()
