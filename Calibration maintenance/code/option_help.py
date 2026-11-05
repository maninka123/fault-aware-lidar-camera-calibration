"""Plain-language, animated explanations of calibration update choices."""
from __future__ import annotations

import math
import sys
from html import escape

from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import Qt

from ui_common import BLUE, INK, INK2, LINE, MUTED, ORANGE, button, hbox, label, scroll
from update_options import rmse_changes


OPTIONS = {
    'existing': ('Keep current', 'Keep the calibration exactly as it is.',
                 'Use the current lens model and sensor relationship as the baseline.',
                 'Camera model: unchanged', 'Sensor alignment: unchanged'),
    'extrinsic': ('Alignment only', 'Correct where the camera sits and points relative to the LiDAR.',
                  'Update the estimated sensor position and rotation (extrinsics). The physical sensors stay in place.',
                  'Camera model: unchanged', 'Sensor alignment: adjusted'),
    'intrinsic': ('Camera only', 'Correct how the lens maps a viewing direction onto the image.',
                  'Update focal lengths, image centre and distortion (intrinsics). Keep the sensor position and rotation fixed.',
                  'Camera model: adjusted', 'Sensor alignment: unchanged'),
    'full': ('Camera + alignment', 'Adjust the lens model and the relationship between the sensors together.',
             'Update both sets of calibration values. This needs a consistent advantage over simpler updates.',
             'Camera model: adjusted', 'Sensor alignment: adjusted'),
}


def comparison_points(comparison):
    """Use this run's stored scores and threshold, including older saved results."""
    selected = comparison.get('selected')
    if not selected:
        return [comparison.get('reason', 'More evidence is needed before choosing an update.')]
    points = [f'The comparison favours {OPTIONS[selected][0].lower()}.']
    scores = comparison.get('scores', {})
    full, simpler = scores.get('full'), scores.get(selected)
    minimum = comparison.get('minimum_gain', 0.01) * 100
    if selected != 'full' and full is not None and simpler is not None and full > simpler:
        gain = (full - simpler) * 100
        points.append(f'Updating both scores {gain:.1f} percentage points higher.')
        if gain < minimum:
            points.append(f'That is below the {minimum:g}-point minimum gain required to justify the extra changes.')
        else:
            points.append('The extra gain did not pass all the consistency checks.')
    else:
        points.append(f'Extra changes need a score gain of at least {minimum:g} percentage points.')
    points.append('The gain must also be consistent across held-out checks.')
    points.append('Follow the recommended next step; the final decision includes the other result checks.')
    return points


def comparison_explanation(comparison):
    return ' '.join(comparison_points(comparison))


def bullet_text(points):
    return '<ul style="margin-top:0; margin-bottom:0; margin-left:16px;">' + ''.join(
        '<li>' + escape(point) + '</li>' for point in points) + '</ul>'


def system_reduces_motion():
    if sys.platform == 'win32':
        import ctypes
        enabled = ctypes.c_int(1)
        if ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(enabled), 0):
            return not enabled.value
    return False


class UpdateIllustration(QtWidgets.QWidget):
    """Schematic only: rigid alignment and lens warping have separate effects."""
    def __init__(self):
        super().__init__()
        self.mode, self.progress = 'existing', 0.0
        self.setFixedHeight(180)
        self.setAccessibleName('Illustration of sensor alignment and lens calibration')
        self.setAccessibleDescription('Grey outlines are image edges. Orange dots are projected LiDAR edges. '
                                      'Alignment changes sensor pose; camera calibration changes lens mapping.')

    def set_progress(self, value):
        self.progress = float(value)
        self.update()

    def sensor_pose(self):
        amount = self.progress if self.mode in ('extrinsic', 'full') else 0
        return 12 * amount, -8 * amount, -12 * amount

    def projected_point(self, x, y):
        alignment = self.progress if self.mode in ('extrinsic', 'full') else 0
        lens = self.progress if self.mode in ('intrinsic', 'full') else 0
        radius = x * x + y * y
        scale = 1 + (1 - lens) * (0.10 + 0.12 * radius)
        angle = (1 - alignment) * 0.10
        a, b = x * scale, y * scale
        return (a * math.cos(angle) - b * math.sin(angle) + (1 - alignment) * 0.12,
                a * math.sin(angle) + b * math.cos(angle) + (1 - alignment) * 0.08)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.fillRect(self.rect(), QtGui.QColor('#f8fafc'))
        width, height = self.width(), self.height()
        split = width * .31
        painter.setFont(QtGui.QFont('Segoe UI', 9))
        painter.setPen(QtGui.QColor(INK2))
        painter.drawText(QtCore.QRectF(12, 10, split - 20, 30), Qt.AlignCenter, 'Sensor pose')
        painter.drawText(QtCore.QRectF(split, 10, width - split, 30), Qt.AlignCenter, 'LiDAR edges on the image')
        painter.setPen(QtGui.QPen(QtGui.QColor(LINE), 1))
        painter.drawLine(QtCore.QPointF(split, 16), QtCore.QPointF(split, height - 16))
        centre = QtCore.QPointF(split / 2, height / 2)
        painter.setPen(QtGui.QPen(QtGui.QColor(MUTED), 1.5, Qt.DashLine))
        painter.drawLine(centre + QtCore.QPointF(-48, 30), centre + QtCore.QPointF(24, -8))
        painter.setBrush(QtGui.QColor(INK2))
        painter.drawRoundedRect(QtCore.QRectF(centre.x() - 65, centre.y() + 14, 34, 30), 5, 5)
        painter.setPen(QtGui.QColor(INK))
        painter.drawText(centre + QtCore.QPointF(-65, 63), 'LiDAR')
        dx, dy, angle = self.sensor_pose()
        painter.save()
        painter.translate(centre + QtCore.QPointF(27 + dx, -16 + dy))
        painter.rotate(angle)
        painter.setBrush(QtGui.QColor('#edf5ff'))
        painter.setPen(QtGui.QPen(QtGui.QColor(BLUE), 2))
        painter.drawRoundedRect(QtCore.QRectF(-19, -12, 38, 26), 4, 4)
        painter.drawEllipse(QtCore.QPointF(0, 0), 7, 7)
        painter.drawLine(QtCore.QPointF(0, -15), QtCore.QPointF(0, -28))
        painter.drawLine(QtCore.QPointF(0, -28), QtCore.QPointF(-5, -22))
        painter.drawLine(QtCore.QPointF(0, -28), QtCore.QPointF(5, -22))
        painter.restore()
        painter.setPen(QtGui.QColor(BLUE))
        painter.drawText(centre + QtCore.QPointF(0, 32), 'Camera')
        origin = QtCore.QPointF(split + (width - split) / 2, height / 2 + 7)
        scale = min((width - split - 60) / 3.0, (height - 85) / 2.15)

        def screen(x, y):
            return origin + QtCore.QPointF(x * scale, y * scale)

        outlines = [((-1., .75), (-1., -.35)), ((-1., -.35), (-.4, -.8)),
                    ((-.4, -.8), (.2, -.35)), ((.2, -.35), (.2, .75)),
                    ((.2, .75), (-1., .75)), ((.55, .75), (.55, -.1)),
                    ((.55, -.1), (1., -.1)), ((1., -.1), (1., .75)),
                    ((1., .75), (.55, .75))]
        painter.setPen(QtGui.QPen(QtGui.QColor('#64748b'), 2.5))
        for start, end in outlines:
            painter.drawLine(screen(*start), screen(*end))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QtGui.QColor(ORANGE))
        for start, end in outlines:
            for index in range(9):
                t = index / 8
                x, y = (start[axis] * (1 - t) + end[axis] * t for axis in (0, 1))
                painter.drawEllipse(screen(*self.projected_point(x, y)), 2.6, 2.6)
        painter.end()


class OptionHelpDialog(QtWidgets.QDialog):
    def __init__(self, comparison, mode, parent=None):
        super().__init__(parent)
        self.comparison = comparison
        self.movements = comparison.get('movements', {})
        self.rmse = rmse_changes(comparison)
        self.setWindowTitle('Understand the update options')
        self.setWindowModality(Qt.WindowModal)
        self.resize(640, 520)
        outer = QtWidgets.QVBoxLayout(self)
        self.tabs = QtWidgets.QTabWidget()
        self.tabs.tabBar().setExpanding(False)
        self.tabs.tabBar().setElideMode(Qt.ElideNone)
        self.tabs.setStyleSheet('QTabBar::tab { min-width: 125px; padding: 5px 12px; }')
        content = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(content)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)
        self.choice = QtWidgets.QComboBox()
        self.choice.setAccessibleName('Explanation option')
        for key, item in OPTIONS.items():
            self.choice.addItem(item[0], key)
        self.choice.activated.connect(lambda index: self.set_mode(self.choice.itemData(index)))
        layout.addWidget(self.choice)
        self.title = label('', 'h3', wrap=True)
        self.description = label('', wrap=True)
        self.changes = label('', 'small', wrap=True)
        layout.addWidget(self.title)
        layout.addWidget(self.description)
        layout.addWidget(self.changes)
        self.canvas = UpdateIllustration()
        layout.addWidget(self.canvas)
        layout.addWidget(label('Grey: image edges · Orange: LiDAR edges. Illustration only; movement is exaggerated.', 'small', wrap=True))
        self.animation = QtCore.QVariantAnimation(self)
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.setDuration(2200)
        self.animation.setEasingCurve(QtCore.QEasingCurve.InOutCubic)
        self.animation.valueChanged.connect(self.animate_frame)
        self.animation.stateChanged.connect(self.animation_state_changed)
        self.replay = button('Replay', 'link', self.play)
        self.pause = button('Pause', 'link', self.pause_motion)
        self.pause.setEnabled(False)
        self.reduced = QtWidgets.QCheckBox('Reduce motion')
        self.reduced.setChecked(system_reduces_motion())
        self.reduced.toggled.connect(self.motion_preference)
        layout.addWidget(hbox(self.replay, self.pause, self.reduced, stretch_at=2))
        self.slider = QtWidgets.QSlider(Qt.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setAccessibleName('Illustration progress: current estimate to adjusted estimate')
        self.slider.valueChanged.connect(self.scrub)
        layout.addWidget(hbox(label('Current', 'small'), self.slider, label('After this option', 'small')))
        self.score_text = label('', 'h3', wrap=True)
        layout.addWidget(self.score_text)
        score_content = QtWidgets.QWidget()
        score_layout = QtWidgets.QVBoxLayout(score_content)
        score_layout.setContentsMargins(10, 10, 10, 10)
        score_layout.setSpacing(10)
        self.score_heading = label('', 'h2', wrap=True)
        score_layout.addWidget(self.score_heading)
        self.metric_text = label('', wrap=True)
        score_layout.addWidget(self.metric_text)
        self.rmse_heading = label('', 'h3', wrap=True)
        self.rmse_text = label('', wrap=True)
        score_layout.addWidget(self.rmse_heading)
        score_layout.addWidget(self.rmse_text)
        self.error_heading = label('', 'h3', wrap=True)
        score_layout.addWidget(self.error_heading)
        self.error_text = label('', wrap=True)
        score_layout.addWidget(self.error_text)
        score_layout.addWidget(label('Why the highest score may not win', 'h3'))
        score_layout.addWidget(label(bullet_text(comparison_points(comparison)), wrap=True))
        self.tabs.addTab(scroll(content), 'What changes')
        self.tabs.addTab(scroll(score_content), 'Understand scores')
        self.tabs.currentChanged.connect(self.show_tab)
        outer.addWidget(self.tabs)
        outer.addWidget(hbox(label('Explanation only; no values are changed.', 'small', wrap=True),
                             button('Done', slot=self.accept), stretch_at=1))
        self.set_mode(mode)

    def set_mode(self, mode):
        self.animation.stop()
        self.mode = self.canvas.mode = mode
        title, summary, detail, camera, pose = OPTIONS[mode]
        self.choice.setCurrentIndex(self.choice.findData(mode))
        self.title.setText(summary)
        self.description.setText(detail)
        self.changes.setText(camera + ' · ' + pose)
        score = self.comparison.get('scores', {}).get(mode)
        if score is None:
            self.score_text.setText(title + ': no reliable score available')
            metric_points = ['More usable held-out checks are needed before comparing this option.']
        else:
            self.score_text.setText(f'{title}: {score * 100:.1f}% edge matches on held-out data')
            metric_points = [
                f'About {score * 100:.1f} in 100 tested LiDAR edge points match an image edge.',
                'A match means within 2 pixels, with a similar edge direction.',
                f'Averaged across {self.comparison.get("folds", 0)} checks on data left out of fitting. '
                'All options use the same visible test points.',
                'This is an edge-match score, not calibration accuracy.']
        self.metric_text.setText(bullet_text(metric_points))
        self.score_heading.setText(self.score_text.text())
        error = self.rmse.get(mode)
        if error:
            self.rmse_heading.setText(f"Edge RMSE: {error['before_px']:.2f} → {error['after_px']:.2f} px")
            percent = error['reduction_percent']
            change_text = (f"{abs(percent):.1f}% " + ('lower' if percent >= 0 else 'higher')) if percent is not None else 'No percentage available'
            self.rmse_text.setText(bullet_text([
                change_text + ' than Keep current.' if mode != 'existing' else 'Current calibration baseline.',
                f"All common visible edge points, across {error['checks']} held-out checks; no 2 px match gate.",
                'Root mean squared distance to the nearest image edge. Lower is better; this is an alignment proxy.']))
        else:
            self.rmse_heading.setText('Edge RMSE not measured')
            self.rmse_text.setText('Run Compare update options to measure it.')
        movement = self.movements.get(mode)
        if mode == 'existing':
            movement = dict(median_px=0.)
        if movement and movement.get('median_px') is not None:
            self.error_heading.setText(f"Median projection shift: {movement['median_px']:.2f} px")
            points = ['How far projected points move from the current calibration, measured across the scene.',
                      'This is movement between projections, not remaining error.']
            if movement.get('p90_px') is not None:
                points.append(f"90% of tested points move less than {movement['p90_px']:.2f} px.")
        else:
            self.error_heading.setText('Projection movement not saved')
            points = ['Run Compare update options to calculate movement for this option.']
        self.error_text.setText(bullet_text(points))
        self.animate_frame(1.0 if self.reduced.isChecked() else 0.0)
        if self.isVisible():
            self.play()
            QtCore.QTimer.singleShot(0, self.fit_content)

    def show_tab(self, index):
        if index:
            self.animation.stop()
        QtCore.QTimer.singleShot(0, self.fit_content)

    def fit_content(self):
        """Fit the active explanation instead of leaving a large blank panel."""
        if not self.isVisible():
            return
        area = self.tabs.currentWidget()
        content_layout = area.widget().layout()
        width = area.viewport().width()
        height = content_layout.totalHeightForWidth(width)
        if height < 0:
            height = content_layout.sizeHint().height()
        chrome = self.height() - area.viewport().height()
        screen = self.screen().availableGeometry().height()
        self.resize(self.width(), max(320, min(height + chrome + 4, screen - 90)))

    def animate_frame(self, value):
        self.canvas.set_progress(value)
        blocker = QtCore.QSignalBlocker(self.slider)
        self.slider.setValue(round(float(value) * 100))

    def scrub(self, value):
        self.animation.stop()
        self.canvas.set_progress(value / 100)

    def play(self):
        if self.reduced.isChecked():
            self.animate_frame(1.0)
            return
        self.animation.stop()
        self.animation.start()

    def pause_motion(self):
        if self.animation.state() == QtCore.QAbstractAnimation.Paused:
            self.animation.resume()
        elif self.animation.state() == QtCore.QAbstractAnimation.Running:
            self.animation.pause()

    def animation_state_changed(self, state, previous):
        self.pause.setText('Resume' if state == QtCore.QAbstractAnimation.Paused else 'Pause')
        self.pause.setEnabled(state != QtCore.QAbstractAnimation.Stopped)

    def motion_preference(self, reduced):
        self.animation.stop()
        self.replay.setEnabled(not reduced)
        if reduced:
            self.animate_frame(1.0)

    def showEvent(self, event):
        super().showEvent(event)
        self.motion_preference(self.reduced.isChecked())
        self.play()
        QtCore.QTimer.singleShot(0, self.fit_content)

    def hideEvent(self, event):
        self.animation.stop()
        super().hideEvent(event)
