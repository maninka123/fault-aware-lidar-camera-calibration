"""Interactive comparison of camera poses, expressed in the LiDAR frame."""
from __future__ import annotations

import math

import numpy as np
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import Qt

from ui_common import BLUE, INK, INK2, LINE, MUTED, button, hbox, label


def camera_pose(matrix):
    """Invert p_camera = R p_lidar + t; return camera centre and axes in metres."""
    matrix = np.asarray(matrix, dtype=float)
    rotation = matrix[:3, :3].T
    return -rotation @ matrix[:3, 3], rotation


class PoseCanvas(QtWidgets.QWidget):
    def __init__(self, previous, refined):
        super().__init__()
        self.previous = camera_pose(previous)
        self.refined = camera_pose(refined)
        self.extent = max(np.linalg.norm(p[0]) for p in (self.previous, self.refined))
        self.extent = max(self.extent * 1.8, 0.08)
        self.yaw, self.pitch = -35.0, 25.0
        self.drag = None
        self.setMinimumHeight(260)
        self.setMaximumHeight(320)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.setCursor(Qt.OpenHandCursor)
        self.setToolTip('Drag to rotate. Double-click to reset the view.')

    def reset_view(self):
        self.yaw, self.pitch = -35.0, 25.0
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag = event.pos()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()

    def mouseMoveEvent(self, event):
        if self.drag is not None:
            delta = event.pos() - self.drag
            self.yaw += delta.x() * 0.5
            self.pitch = max(-80, min(80, self.pitch + delta.y() * 0.5))
            self.drag = event.pos()
            self.update()

    def mouseReleaseEvent(self, event):
        self.drag = None
        self.setCursor(Qt.OpenHandCursor)
        event.accept()

    def mouseDoubleClickEvent(self, event):
        self.reset_view()
        event.accept()

    def paintEvent(self, _):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.fillRect(self.rect(), QtGui.QColor('#f8fafc'))
        yaw, pitch = math.radians(self.yaw), math.radians(self.pitch)
        right = np.array([-math.sin(yaw), math.cos(yaw), 0])
        up = np.array([-math.sin(pitch) * math.cos(yaw),
                       -math.sin(pitch) * math.sin(yaw), math.cos(pitch)])
        size = self.extent * 0.22
        points = [np.zeros(3)] + list(np.eye(3) * self.extent * 0.8)
        for position, rotation in (self.previous, self.refined):
            points.append(position)
            points.append(position + rotation[:, 2] * size * 2.5)
            points.extend(position + rotation @ (np.array(point) * size)
                          for point in ((-0.65, -0.45, 1.6), (0.65, -0.45, 1.6),
                                        (0.65, 0.45, 1.6), (-0.65, 0.45, 1.6)))
        screen = np.array([[point @ right, point @ up] for point in points])
        low, high = screen.min(axis=0), screen.max(axis=0)
        centre = (low + high) / 2
        span = np.maximum(high - low, 0.001)
        scale = min((self.width() - 70) / span[0], (self.height() - 75) / span[1])

        def project(point):
            point = np.asarray(point)
            return QtCore.QPointF(self.width() / 2 + float(point @ right - centre[0]) * scale,
                                 self.height() / 2 - float(point @ up - centre[1]) * scale)

        def line(start, end, colour, width=1, dashed=False):
            pen = QtGui.QPen(QtGui.QColor(colour), width,
                             Qt.DashLine if dashed else Qt.SolidLine, Qt.RoundCap)
            painter.setPen(pen)
            painter.drawLine(project(start), project(end))

        def text(point, value, colour, dx=6, dy=-6):
            painter.setPen(QtGui.QColor(colour))
            painter.drawText(project(point) + QtCore.QPointF(dx, dy), value)

        def dot(point, colour, radius=4):
            painter.setPen(QtGui.QPen(QtGui.QColor('white'), 1.5))
            painter.setBrush(QtGui.QColor(colour))
            painter.drawEllipse(project(point), radius, radius)

        painter.setFont(QtGui.QFont('Segoe UI', 8))
        grid = self.extent
        for coordinate in np.linspace(-grid, grid, 9):
            line([coordinate, -grid, 0], [coordinate, grid, 0], '#e9edf3')
            line([-grid, coordinate, 0], [grid, coordinate, 0], '#e9edf3')

        zero = np.zeros(3)
        axes = (('X', '#d65b64'), ('Y', '#399b78'), ('Z', '#6689cb'))
        for axis, (name, colour) in enumerate(axes):
            end = np.eye(3)[axis] * grid * 0.8
            line(zero, end, colour, 1.5)
            text(end, name, colour)

        # The camera pyramids indicate orientation, not calibrated fields of view.
        for (position, rotation), colour, dashed in (
                (self.previous, '#9aa5b5', True), (self.refined, BLUE, False)):
            corners = [position + rotation @ (np.array(point) * size)
                       for point in ((-0.65, -0.45, 1.6), (0.65, -0.45, 1.6),
                                     (0.65, 0.45, 1.6), (-0.65, 0.45, 1.6))]
            for index, corner in enumerate(corners):
                line(position, corner, colour, 1.6, dashed)
                line(corner, corners[(index + 1) % 4], colour, 1.6, dashed)
            forward = position + rotation[:, 2] * size * 2.5
            line(position, forward, colour, 1.3, dashed)
            dot(position, colour)
        line(self.previous[0], self.refined[0], '#eb6834', 2, True)
        dot(zero, INK2, 5)
        text(zero, 'LiDAR', INK2, 7, 17)
        text(self.refined[0] + self.refined[1][:, 2] * size * 2.5, 'Camera', BLUE)

        # A true-scale reference independent of the schematic camera size.
        length = self.extent / 2
        power = 10 ** math.floor(math.log10(length * 1000))
        length = max(1, round(length * 1000 / power)) * power / 1000
        pixels = length * scale
        painter.setPen(QtGui.QPen(QtGui.QColor(MUTED), 1.2))
        y = self.height() - 20
        painter.drawLine(QtCore.QPointF(14, y), QtCore.QPointF(14 + pixels, y))
        for x in (14, 14 + pixels):
            painter.drawLine(QtCore.QPointF(x, y - 3), QtCore.QPointF(x, y + 3))
        painter.drawText(QtCore.QPointF(14, y - 7), f'{length * 1000:g} mm')
        painter.end()


class CalibrationPosePanel(QtWidgets.QFrame):
    def __init__(self, comparison):
        super().__init__()
        self.setObjectName('posePanel')
        self.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Maximum)
        self.setStyleSheet(f'QFrame#posePanel {{ background: #f8fafc; border: 1px solid {LINE}; border-radius: 10px; }}')
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)
        previous = np.asarray(comparison['previous']['extrinsics']['matrix'])
        refined = np.asarray(comparison['new']['extrinsics']['matrix'])
        self.canvas = PoseCanvas(previous, refined)
        layout.addWidget(hbox(label('Camera + LiDAR pose', 'h3'),
                             button('Reset', 'link', self.canvas.reset_view), stretch_at=1))
        layout.addWidget(label('Camera shown in the LiDAR coordinate frame.', 'small', wrap=True))
        layout.addWidget(label(f'<span style="color:#8995a6">-- Previous</span>'
                               f' &nbsp; <span style="color:{BLUE}">\u2501 Refined</span>', rich=True))
        layout.addWidget(self.canvas, 1)
        movement = np.linalg.norm(self.canvas.refined[0] - self.canvas.previous[0]) * 1000
        cosine = (np.trace(refined[:3, :3] @ previous[:3, :3].T) - 1) / 2
        angle = math.degrees(math.acos(float(np.clip(cosine, -1, 1))))
        layout.addWidget(label(f'<b>{movement:.1f} mm</b> camera-centre shift'
                               f' &nbsp; <b>{angle:.2f}\u00b0</b> rotation', rich=True, wrap=True))
        position = self.canvas.refined[0] * 1000
        self.canvas.setToolTip('Drag to rotate · double-click to reset.\n'
                               'Camera centre in LiDAR coordinates (mm): ' +
                               ', '.join(f'{axis} {value:+.1f}' for axis, value in zip('XYZ', position)) +
                               '\nSensor shapes indicate orientation; they are not lens fields of view.')


class ComparisonColumns(QtWidgets.QWidget):
    """Keep the pose beside the table when it fits; stack it on smaller windows."""
    def __init__(self, table_column, pose_panel):
        super().__init__()
        self.pose_panel = pose_panel
        self.box = QtWidgets.QBoxLayout(QtWidgets.QBoxLayout.LeftToRight, self)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(20)
        self.box.addWidget(table_column, 1)
        self.box.addWidget(pose_panel, 0, Qt.AlignTop)
        self.arrange()

    def arrange(self):
        side_by_side = self.width() >= 1120
        direction = QtWidgets.QBoxLayout.LeftToRight if side_by_side else QtWidgets.QBoxLayout.TopToBottom
        self.box.setDirection(direction)
        self.pose_panel.setMinimumWidth(320 if side_by_side else 0)
        self.pose_panel.setMaximumWidth(320 if side_by_side else 16777215)
        self.box.setStretch(0, 1 if side_by_side else 0)
        self.updateGeometry()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.arrange()
