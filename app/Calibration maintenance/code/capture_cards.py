"""Capture mode toggle and compact, persistent rows of collected sensor samples."""
from pathlib import Path

import numpy as np
from PyQt5 import QtCore, QtGui, QtWidgets

from cloud_view import CloudView
from ui_common import ImageView, label, np_to_pixmap


class PreviewImage(ImageView):
    """Letterbox the camera into the same dark frame as the LiDAR viewer."""
    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        clip = QtGui.QPainterPath()
        clip.addRoundedRect(QtCore.QRectF(self.rect()), 10, 10)
        painter.setClipPath(clip)
        painter.fillRect(self.rect(), QtGui.QColor('#17191e'))
        pixmap = self.current()
        if not pixmap.isNull():
            size = pixmap.size().scaled(self.size(), QtCore.Qt.KeepAspectRatio)
            target = QtCore.QRect(QtCore.QPoint((self.width()-size.width())//2,
                                               (self.height()-size.height())//2), size)
            painter.drawPixmap(target, pixmap)


def sensor_panel(title, view, footer, available):
    panel = QtWidgets.QFrame()
    panel.setStyleSheet('QFrame#sensorPanel {background: white; border: 1px solid #e5e7eb; border-radius: 14px;}')
    panel.setObjectName('sensorPanel')
    layout = QtWidgets.QVBoxLayout(panel)
    layout.setContentsMargins(12, 12, 12, 12)
    layout.setSpacing(10)
    header = QtWidgets.QHBoxLayout()
    header.addWidget(label(title, 'h2'), 1)
    state = label('Received' if available else 'No data', 'small')
    state.setStyleSheet('color: #248a3d; background: #eaf6ed; border-radius: 8px; padding: 4px 8px;'
                       if available else 'color: #9b6500; background: #fff6e5; border-radius: 8px; padding: 4px 8px;')
    header.addWidget(state)
    layout.addLayout(header)
    view.setMinimumWidth(0)
    view.setFixedHeight(320)
    layout.addWidget(view)
    layout.addWidget(label(footer, 'small', wrap=True))
    return panel


class CaptureModeToggle(QtWidgets.QWidget):
    currentIndexChanged = QtCore.pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self.setFixedSize(280, 38)
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(0, 2, 0, 2)
        row.setSpacing(8)
        self.group = QtWidgets.QButtonGroup(self)
        self.buttons = []
        for index, text in enumerate(("Manual", "Automatic")):
            button = QtWidgets.QPushButton(text)
            button.setCheckable(True)
            button.setFixedHeight(34)
            button.setStyleSheet('QPushButton {border: 1px solid #d1d5db; border-radius: 8px; min-height: 0px; max-height: 32px; padding: 0 12px; font-size: 12px; background: white; color: #374151;}'
                                 'QPushButton:checked {background: #007aff; color: white; border-color: #007aff;}')
            self.group.addButton(button, index)
            row.addWidget(button, 1)
            button.clicked.connect(lambda checked, i=index: self.currentIndexChanged.emit(i))
            self.buttons.append(button)
        self.buttons[0].setChecked(True)

    def currentData(self):
        return 'automatic' if self.buttons[1].isChecked() else 'manual'

    def setCurrentIndex(self, index):
        self.buttons[index].setChecked(True)
        self.currentIndexChanged.emit(index)


def capture_row(index, path, summary, on_delete=None):
    row = QtWidgets.QFrame()
    row.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Maximum)
    row.setObjectName('subtle')
    layout = QtWidgets.QVBoxLayout(row)
    layout.setContentsMargins(12, 10, 12, 10)
    layout.setSpacing(10)
    header = QtWidgets.QHBoxLayout()
    header.addWidget(label(f'Capture {index}', 'h2'), 1)
    if on_delete is not None:
        delete = QtWidgets.QPushButton('Delete pair')
        delete.setStyleSheet('color: #d70015; padding: 5px 10px;')
        delete.setToolTip('Remove this camera/LiDAR pair. Active collection will stop; other saved pairs are kept.')
        delete.clicked.connect(on_delete)
        header.addWidget(delete)
    layout.addLayout(header)
    previews = QtWidgets.QHBoxLayout()
    previews.setSpacing(12)
    if Path(path).is_file():
        with np.load(path) as data:
            image = data['image'].copy()
            raw = data['xyz_mm']
            points = raw[::max(1, int(np.ceil(len(raw)/60000)))].astype(np.float32) / 1000
        for title, view in (("Camera", PreviewImage(pixmap=np_to_pixmap(image), caption=f'Capture {index} camera', max_height=132)),
                            ("LiDAR", CloudView(points, show_info=False))):
            column = QtWidgets.QVBoxLayout()
            column.addWidget(label(title, 'small'))
            view.setMinimumSize(0, 0)
            view.setFixedHeight(132)
            view.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
            column.addWidget(view)
            previews.addLayout(column, 1)
    layout.addLayout(previews)
    details = QtWidgets.QVBoxLayout()
    frames = summary.get('lidar_frames', 0)
    details.addWidget(label(f"{frames} LiDAR {'frame' if frames == 1 else 'frames'} · {summary.get('lidar_points', 0):,} points", wrap=True))
    details.addWidget(label(f"{summary.get('images', 0)} camera images · saved", 'small'))
    details.addStretch(1)
    layout.addLayout(details, 1)
    return row
