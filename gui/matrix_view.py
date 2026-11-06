"""A calibration's matrices, side by side: camera intrinsics K with the distortion terms, and the LiDAR to camera transform T.

Shown on the New check page as soon as a calibration is loaded (from a file, typed values or the example), so the
values can be read at a glance without opening a dialog. Uses the maintenance app's bracketed-matrix widget, so the
numbers look the same as in the Calibration review.
"""
from __future__ import annotations

import numpy as np
from PyQt5 import QtWidgets
from PyQt5.QtCore import Qt

import review_adapter  # noqa: F401  (puts the maintenance code on the path)
from matrix_preview import BracketedMatrix

INK, MUTED, LINE = "#1d1d1f", "#6e6e73", "#e5e5ea"
MONO = '"Cascadia Mono", Consolas, monospace'


def matrices_of(calibration):
    """(K 3x3, distortion 4, T 4x4) as float arrays, or None when the calibration does not hold them."""
    try:
        K = np.asarray(calibration["intrinsics"]["camera_matrix"], float)
        D = np.r_[np.ravel(calibration["intrinsics"].get("distortion_coefficients", [])), np.zeros(4)][:4].astype(float)
        T = np.asarray(calibration["extrinsics"]["transform_lidar_to_camera"], float)
    except (KeyError, TypeError, ValueError, AttributeError):
        return None
    return (K, D, T) if K.shape == (3, 3) and T.shape == (4, 4) else None


def _cell(text, name=None):
    frame = QtWidgets.QWidget()
    lay = QtWidgets.QHBoxLayout(frame)
    lay.setContentsMargins(2, 2, 2, 2)
    lay.setSpacing(6)
    if name:
        n = QtWidgets.QLabel(name)
        n.setStyleSheet(f"color: {MUTED}; font-size: 12px; background: transparent;")
        lay.addWidget(n)
    value = QtWidgets.QLabel(text)
    value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    value.setTextInteractionFlags(Qt.TextSelectableByMouse)
    value.setStyleSheet(f"font-family: {MONO}; font-size: 13px; color: {INK}; background: transparent;")
    lay.addWidget(value)
    return frame


class MatrixPair(QtWidgets.QWidget):
    """K (and distortion) on the left, T on the right; stacked when the window is narrow."""

    def __init__(self, calibration):
        super().__init__()
        found = matrices_of(calibration)
        self.valid = found is not None
        self.box = QtWidgets.QBoxLayout(QtWidgets.QBoxLayout.LeftToRight, self)
        self.box.setContentsMargins(0, 4, 0, 0)
        self.box.setSpacing(12)
        self.groups = []
        if not self.valid:
            return
        K, D, T = found
        self.groups.append(self._group("Camera intrinsics", "K · 3 × 3 · pixels",
                                       BracketedMatrix(3, 3, lambda r, c: _cell(f"{K[r, c]:.4f}")),
                                       ("Distortion coefficients", BracketedMatrix(1, 4, lambda r, c: _cell(f"{D[c]:.6f}", f"k{c + 1}")))))
        self.groups.append(self._group("LiDAR → camera extrinsics", "T · 4 × 4 · translation in metres",
                                       BracketedMatrix(4, 4, lambda r, c: _cell(f"{T[r, c]:.{5 if c == 3 else 6}f}"))))
        for g in self.groups:
            self.box.addWidget(g, 1)

    @staticmethod
    def _group(title, notation, matrix, extra=None):
        group = QtWidgets.QFrame()
        group.setStyleSheet("QFrame#matrixGroup { background: #f8f9fb; border: 1px solid #edf0f4; border-radius: 8px; } "
                            "QLabel { background: transparent; border: none; }")
        group.setObjectName("matrixGroup")
        lay = QtWidgets.QVBoxLayout(group)
        lay.setContentsMargins(12, 9, 12, 9)
        lay.setSpacing(6)
        head = QtWidgets.QLabel(f"<b>{title}</b>")
        lay.addWidget(head)
        small = QtWidgets.QLabel(notation)
        small.setStyleSheet(f"color: {MUTED}; font-size: 12px;")
        lay.addWidget(small)
        lay.addWidget(matrix, 0, Qt.AlignHCenter)
        if extra:
            caption = QtWidgets.QLabel(extra[0])
            caption.setStyleSheet(f"color: {MUTED}; font-size: 12px;")
            lay.addWidget(caption)
            lay.addWidget(extra[1], 0, Qt.AlignHCenter)
        else:
            lay.addStretch(1)
        return group

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.groups:
            needed = sum(g.minimumSizeHint().width() for g in self.groups) + 24
            self.box.setDirection(QtWidgets.QBoxLayout.LeftToRight if self.width() >= needed else QtWidgets.QBoxLayout.TopToBottom)
