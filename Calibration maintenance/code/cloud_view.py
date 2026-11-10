"""Small software-rendered LiDAR viewer; no camera calibration or OpenGL required."""
import math

import cv2
import numpy as np
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import Qt


class CloudView(QtWidgets.QWidget):
    def __init__(self, cloud, show_info=True):
        super().__init__()
        self.show_info = show_info
        self.yaw = self.pitch = 0.0
        self.zoom = 1.0
        self.last_pos = None
        self.setMinimumSize(160, 260)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.setToolTip("Drag to rotate · mouse wheel to zoom · double-click to reset. Colours show distance from LiDAR.")
        self.setCursor(Qt.OpenHandCursor)
        self.set_cloud(cloud)

    def set_cloud(self, cloud):
        xyz = np.asarray(cloud, dtype=float)
        xyz = xyz[:, :3] if xyz.ndim == 2 and xyz.shape[1] >= 3 else np.empty((0, 3))
        self.xyz = xyz[np.isfinite(xyz).all(axis=1)]
        self.total = len(self.xyz)
        self.xyz = self.xyz[::max(1, math.ceil(len(self.xyz) / 60000))]
        distance = np.linalg.norm(self.xyz, axis=1)
        if len(distance):
            low, high = np.percentile(distance, [2, 98])
            value = np.clip((distance - low) / max(high - low, 1e-6), 0, 1)
            self.colors = cv2.applyColorMap(np.uint8((1 - value) * 255), cv2.COLORMAP_TURBO).reshape(-1, 3)
        else:
            self.colors = np.empty((0, 3), dtype=np.uint8)
        self.update()

    def reset_view(self):
        self.yaw = self.pitch = 0.0
        self.zoom = 1.0
        self.update()

    def render_cloud(self, width, height):
        frame = np.full((height, width, 3), (30, 25, 23), dtype=np.uint8)
        if not self.total:
            return frame
        cy, sy = math.cos(self.yaw), math.sin(self.yaw)
        cp, sp = math.cos(self.pitch), math.sin(self.pitch)
        rotation = np.array([[cp * cy, cp * sy, sp], [-sy, cy, 0], [-sp * cy, -sp * sy, cp]])
        points = self.xyz @ rotation.T
        horizontal, vertical = -points[:, 1], -points[:, 2]
        # Keep the fitted bounds fixed while zooming, and fit all sampled finite returns.
        center = np.array([(horizontal.min() + horizontal.max()) / 2,
                           (vertical.min() + vertical.max()) / 2])
        span = np.array([np.ptp(horizontal), np.ptp(vertical)])
        scale = min((width - 24) / max(span[0], .001), (height - 24) / max(span[1], .001)) * self.zoom
        x = np.rint((horizontal - center[0]) * scale + width / 2).astype(int)
        y = np.rint((vertical - center[1]) * scale + height / 2).astype(int)
        valid = (x >= 0) & (x < width) & (y >= 0) & (y < height)
        indices = np.flatnonzero(valid)
        # Keep the nearest point at each raster pixel.
        indices = indices[np.argsort(points[indices, 0])]
        _, first = np.unique(y[indices] * width + x[indices], return_index=True)
        selected = indices[first]
        frame[y[selected], x[selected]] = self.colors[selected]
        return frame

    def paintEvent(self, _):
        frame = self.render_cloud(max(25, self.width()), max(25, self.height()))
        image = QtGui.QImage(frame.data, frame.shape[1], frame.shape[0], frame.strides[0], QtGui.QImage.Format_BGR888)
        painter = QtGui.QPainter(self)
        clip = QtGui.QPainterPath()
        clip.addRoundedRect(QtCore.QRectF(self.rect()), 10, 10)
        painter.setClipPath(clip)
        painter.drawImage(self.rect(), image)
        painter.setPen(QtGui.QColor("#cbd5e1"))
        if not self.total:
            painter.drawText(self.rect(), Qt.AlignCenter, "No LiDAR points received")
        elif self.show_info:
            painter.drawText(10, 21, f"{self.total:,} points · colour = range")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.last_pos = event.pos()
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        if self.last_pos is not None:
            delta = event.pos() - self.last_pos
            self.yaw += delta.x() * .008
            self.pitch = float(np.clip(self.pitch + delta.y() * .008, -1.5, 1.5))
            self.last_pos = event.pos()
            self.update()

    def mouseReleaseEvent(self, event):
        self.last_pos = None
        self.setCursor(Qt.OpenHandCursor)

    def wheelEvent(self, event):
        self.zoom = float(np.clip(self.zoom * 1.15 ** (event.angleDelta().y() / 120), .2, 20))
        self.update()
        event.accept()

    def mouseDoubleClickEvent(self, event):
        self.reset_view()
