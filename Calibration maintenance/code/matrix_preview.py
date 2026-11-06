"""Compact bracketed matrices, with inline deltas and an expandable body."""
import numpy as np
from scipy.spatial.transform import Rotation
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import Qt
from ui_common import BAD, BLUE, INK, LINE, MUTED, hbox, label
from option_help import OPTIONS


class BracketedMatrix(QtWidgets.QWidget):
    def __init__(self, rows, columns, make_cell):
        super().__init__()
        self.grid = QtWidgets.QGridLayout(self)
        self.grid.setContentsMargins(17, 5, 17, 5)
        self.grid.setHorizontalSpacing(12)
        self.grid.setVerticalSpacing(6)
        for row in range(rows):
            for column in range(columns):
                self.grid.addWidget(make_cell(row, column), row, column)
        self.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setPen(QtGui.QPen(QtGui.QColor('#8794a6'), 1.6, Qt.SolidLine, Qt.SquareCap))
        for x, sign in ((4, 1), (self.width() - 4, -1)):
            p.drawLine(QtCore.QPointF(x + sign * 8, 4), QtCore.QPointF(x, 4))
            p.drawLine(QtCore.QPointF(x, 4), QtCore.QPointF(x, self.height() - 4))
            p.drawLine(QtCore.QPointF(x, self.height() - 4), QtCore.QPointF(x + sign * 8, self.height() - 4))
        p.end()


class MatrixPreview(QtWidgets.QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName('matrixPreview')
        self.setStyleSheet(f'QFrame#matrixPreview {{ background: white; border: 1px solid {LINE}; border-radius: 12px; }}')
        self.calibrations, self.cells, self.frames, self.states, self.groups = {}, {}, {}, {}, []
        self.mode = 'existing'
        self.view = 'candidate'        # what the cells show: 'candidate', 'current' or 'difference'
        self.expanded = True
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(14, 10, 14, 10)
        outer.setSpacing(8)
        outer.setSizeConstraint(QtWidgets.QLayout.SetNoConstraint)
        self.heading = label('', 'h3')
        self.toggle = QtWidgets.QToolButton()
        self.toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.toggle.setCheckable(True)
        self.toggle.setChecked(True)
        self.toggle.setCursor(Qt.PointingHandCursor)
        self.toggle.setStyleSheet('QToolButton { border: none; background: transparent; color: #48484a; '
                                 'padding: 3px; font-size: 9pt; } QToolButton:hover { color: #007aff; }')
        self.toggle.toggled.connect(self.set_expanded)
        outer.addWidget(hbox(self.heading, self.toggle, stretch_at=1))
        self.body = QtWidgets.QWidget()
        body_layout = QtWidgets.QVBoxLayout(self.body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(4)
        self.columns = QtWidgets.QBoxLayout(QtWidgets.QBoxLayout.LeftToRight)
        self.columns.setSpacing(12)
        for key, title, notation, rows, cols in (
                ('K', 'Camera intrinsics', 'K · 3 × 3 · pixels', 3, 3),
                ('T', 'LiDAR → camera extrinsics', 'T · 4 × 4 · translation in metres', 4, 4)):
            group = QtWidgets.QFrame()
            group.setObjectName('matrixGroup')
            group.setStyleSheet('QFrame#matrixGroup { background: #f8f9fb; border: 1px solid #edf0f4; border-radius: 8px; }')
            lay = QtWidgets.QVBoxLayout(group)
            lay.setContentsMargins(12, 9, 12, 9)
            lay.setSpacing(6)
            state = label('', 'small')
            self.states[key] = state
            lay.addWidget(hbox(label(title, 'h3'), state, stretch_at=1))
            lay.addWidget(label(notation, 'small'))
            matrix = BracketedMatrix(rows, cols, lambda r, c, key=key: self.make_cell((key, r, c)))
            lay.addWidget(matrix, 0, Qt.AlignHCenter)
            if key == 'K':
                dmatrix = BracketedMatrix(1, 4, lambda r, c: self.make_cell(('D', 0, c), f'k{c + 1}'))
                lay.addWidget(label('Distortion coefficients', 'small'))
                lay.addWidget(dmatrix, 0, Qt.AlignHCenter)
            else:
                lay.addStretch(1)
            self.groups.append(group)
            self.columns.addWidget(group, 1)
        body_layout.addLayout(self.columns)
        self.note = label('', 'small', wrap=True)
        self.note.hide()
        body_layout.addWidget(self.note)
        outer.addWidget(self.body)
        self.set_expanded(True)

    def set_expanded(self, expanded):
        self.expanded = expanded
        self.update_heading()
        self.body.setVisible(expanded)
        self.toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.toggle.setText('Hide matrices' if expanded else 'Show matrices')
        self.toggle.setAccessibleName('Collapse calibration matrices' if expanded else 'Expand calibration matrices')
        if self.toggle.isChecked() != expanded:
            self.toggle.setChecked(expanded)
        self.updateGeometry()

    def make_cell(self, key, name=None):
        frame = QtWidgets.QFrame()
        layout = QtWidgets.QHBoxLayout(frame)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(7)
        if name:
            layout.addWidget(label(name, 'small'))
        value = label('—', sel=True)
        value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        value.setStyleSheet(f'font-family: Consolas; font-size: 10pt; font-weight: 400; color: {INK}; background: transparent;')
        delta = label('', 'small', sel=True)
        delta.setObjectName('matrixDelta')
        delta.hide()
        layout.addWidget(value)
        layout.addWidget(delta)
        self.cells[key], self.frames[key] = (value, delta), frame
        return frame

    def set_calibrations(self, calibrations):
        self.calibrations = calibrations or {}

    def update_heading(self):
        self.heading.setText(OPTIONS[self.mode][0] if self.expanded else 'Calibration matrices')

    def set_view(self, view):
        """candidate: the previewed option's values with the changes marked; current: the values in use now;
        difference: only how much each value changes."""
        if view in ('candidate', 'current', 'difference') and view != self.view:
            self.view = view
            self.set_mode(self.mode)

    def set_mode(self, mode):
        self.mode = mode
        self.update_heading()
        current, candidate = self.calibrations.get('existing'), self.calibrations.get(mode)
        if not current or not candidate:
            for key, (value, delta) in self.cells.items():
                value.setText('—')
                delta.setText('')
                delta.hide()
                self.frames[key].setStyleSheet('background: transparent; border: none;')
            for state in self.states.values():
                state.setText('Unavailable')
            self.note.setText('This option’s fitted matrices were not saved. Run Compare update options to calculate them.')
            self.note.show()
            return
        self.note.hide()
        def arrays(cal):
            return dict(K=np.asarray(cal['intrinsics']['camera_matrix'], float),
                        T=np.asarray(cal['extrinsics']['transform_lidar_to_camera'], float),
                        D=np.r_[np.ravel(cal['intrinsics'].get('distortion_coefficients', [])), np.zeros(4)][:4][None])
        before, after = arrays(current), arrays(candidate)
        angle = np.degrees(Rotation.from_matrix(after['T'][:3, :3] @ before['T'][:3, :3].T).magnitude())
        for key, state in self.states.items():
            count = int((np.abs(after[key] - before[key]) > 1e-9).sum())
            if key == 'K':
                count += int((np.abs(after['D'] - before['D']) > 1e-9).sum())
            state.setText(f'{count} changed values' if count else '')
            state.setStyleSheet(f'color: {BLUE}; font-size: 9pt;')
        for index, (value, delta_label) in self.cells.items():
            key, row, col = index
            old, new = before[key][row, col], after[key][row, col]
            delta, changed = new - old, abs(new - old) > 1e-9
            if key == 'K':
                large = abs(delta) >= (abs(old) * .05 if row == col and old else 5.)
                text, digits = f'Δ {delta:+.3f} px', 4
            elif key == 'T':
                large = abs(delta) >= .02 if col == 3 else angle >= 5.
                text = f'Δ {delta * 1000:+.2f} mm' if col == 3 and row < 3 else f'Δ {delta:+.5f}'
                digits = 5 if col == 3 else 6
            else:
                large, text, digits = abs(delta) >= .05, f'Δ {delta:+.5f}', 6
            colour = BAD if changed and large else BLUE if changed else MUTED
            border = '#e5a8af' if changed and large else '#b7cbe2'
            shown = {'candidate': new, 'current': old, 'difference': delta}[self.view]
            self.frames[index].setStyleSheet('QFrame { background: transparent; border: none; }')
            value.setText(f'{shown:+.{digits}f}' if self.view == 'difference' else f'{shown:.{digits}f}')
            value.setStyleSheet(f'font-family: Consolas; font-size: 10pt; font-weight: 400; '
                               f'color: {INK}; background: transparent;')
            delta_label.setText(text if changed else '')
            delta_label.setVisible(bool(changed) and self.view == 'candidate')
            delta_label.setStyleSheet(f'QLabel#matrixDelta {{ font-size: 8pt; color: {colour}; '
                                     f'background: transparent; border: 1px solid {border}; '
                                     'border-radius: 4px; padding: 2px 4px; }')
            value.setToolTip(f'Current: {old:.12g}\nPreview: {new:.12g}\nChange: {delta:+.12g}')
        QtCore.QTimer.singleShot(0, self.arrange)

    def arrange(self):
        needed = sum(group.minimumSizeHint().width() for group in self.groups) + 40
        self.columns.setDirection(QtWidgets.QBoxLayout.LeftToRight if self.width() >= needed
                                  else QtWidgets.QBoxLayout.TopToBottom)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.arrange()


class ResultHeader(QtWidgets.QWidget):
    def __init__(self, banner, matrices):
        super().__init__()
        self.matrices = matrices
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Maximum)
        self.box = QtWidgets.QVBoxLayout(self)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(8)
        self.box.addWidget(banner)
        self.box.addWidget(matrices)
