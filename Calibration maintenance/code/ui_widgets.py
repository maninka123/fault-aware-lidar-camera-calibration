"""Compact shared controls for inputs, update choices and comparison results."""
from __future__ import annotations

import os
from pathlib import Path

from PyQt5 import QtCore, QtWidgets
from PyQt5.QtCore import Qt
import appcore as core

from ui_common import BLUE, BLUE_SOFT, LINE, MUTED, button, hbox, label
from option_help import OPTIONS, OptionHelpDialog
from update_options import rmse_changes

MODE_NAMES = {'compare': 'Compare update options', 'extrinsic': 'Alignment only',
              'intrinsic': 'Camera only', 'full': 'Camera + alignment'}
RECOMMEND_BORDER, RECOMMEND_BG, RECOMMEND_INK = '#cbbd9b', '#ffffff', '#716344'


class ActionFlow(QtWidgets.QLayout):
    """Keep actions together, wrapping at the available width."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.items = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(8)

    def addItem(self, item):
        self.items.append(item)

    def count(self):
        return len(self.items)

    def itemAt(self, index):
        return self.items[index] if 0 <= index < len(self.items) else None

    def takeAt(self, index):
        return self.items.pop(index) if 0 <= index < len(self.items) else None

    def expandingDirections(self):
        return Qt.Orientations(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self.arrange(QtCore.QRect(0, 0, width, 0), True)

    def minimumSize(self):
        size = QtCore.QSize()
        for item in self.items:
            size = size.expandedTo(item.minimumSize())
        return size

    def sizeHint(self):
        return self.minimumSize()

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self.arrange(rect, False)

    def arrange(self, rect, measure):
        x, y, row_height = rect.x(), rect.y(), 0
        for item in self.items:
            size = item.sizeHint()
            if x > rect.x() and x + size.width() > rect.right() + 1:
                x = rect.x()
                y += row_height + self.spacing()
                row_height = 0
            if not measure:
                item.setGeometry(QtCore.QRect(QtCore.QPoint(x, y), size))
            x += size.width() + self.spacing()
            row_height = max(row_height, size.height())
        return y + row_height - rect.y()


def action_flow(buttons):
    widget = QtWidgets.QWidget()
    layout = ActionFlow(widget)
    for control in buttons:
        layout.addWidget(control)
    return widget


class PageTabs(QtWidgets.QTabBar):
    """Tab navigation inside page content, so it scrolls with that page."""
    def __init__(self, tabs):
        super().__init__()
        self.setExpanding(False)
        self.setDrawBase(False)
        self.setElideMode(Qt.ElideNone)
        self.addTab('Processing')
        self.addTab('Result')
        self.setCurrentIndex(tabs.currentIndex())
        self.currentChanged.connect(tabs.setCurrentIndex)
        tabs.currentChanged.connect(self.setCurrentIndex)


class EvidenceColumns(QtWidgets.QWidget):
    def __init__(self, groups):
        super().__init__()
        self.box = QtWidgets.QBoxLayout(QtWidgets.QBoxLayout.LeftToRight, self)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(16)
        for title, view in groups:
            widget = QtWidgets.QWidget()
            layout = QtWidgets.QVBoxLayout(widget)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(5)
            layout.addWidget(label(title, 'h3'))
            layout.addWidget(view)
            layout.addStretch(1)
            self.box.addWidget(widget, 1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.box.setDirection(QtWidgets.QBoxLayout.LeftToRight if self.width() >= 1100 else QtWidgets.QBoxLayout.TopToBottom)


class UpdateChoice(QtWidgets.QComboBox):
    def __init__(self):
        super().__init__()
        for mode, name in MODE_NAMES.items():
            self.addItem(name + ('  (recommended)' if mode == 'compare' else ''), mode)
        self.setMinimumWidth(280)
        self.setToolTip('Alignment = extrinsics: position and rotation. Camera settings = intrinsics: '
                        'focal length, image centre and distortion. Compare tests all choices on held-out data.')
        self.setAccessibleName('What to update')


class ElidedPath(QtWidgets.QLabel):
    def __init__(self):
        super().__init__()
        self.path_text = ''
        self.setObjectName('small')
        self.setMinimumWidth(0)
        self.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Fixed)

    def set_path(self, path):
        self.path_text = str(path or 'Not selected')
        self.setToolTip(self.path_text)
        self.setText(self.fontMetrics().elidedText(self.path_text, Qt.ElideMiddle, self.width()))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.setText(self.fontMetrics().elidedText(self.path_text, Qt.ElideMiddle, self.width()))


class SourceLocation(QtWidgets.QFrame):
    def __init__(self, title):
        super().__init__()
        self.setObjectName('sourceItem')
        self.path = None
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(2)
        self.open_button = button('Open \u2197', 'link', self.open)
        self.open_button.setAccessibleName('Open ' + title.lower())
        layout.addWidget(hbox(label(title, 'h3'), self.open_button, stretch_at=1))
        self.path_label = ElidedPath()
        layout.addWidget(self.path_label)

    def set_path(self, path):
        self.path = Path(path) if path else None
        self.path_label.set_path(core.short(self.path) if self.path else None)
        self.path_label.setToolTip(str(self.path) if self.path else 'Not selected')
        self.open_button.setEnabled(self.path is not None and self.path.exists())

    def open(self):
        if self.path and self.path.exists():
            try:
                os.startfile(str(self.path))
            except OSError as error:
                QtWidgets.QMessageBox.information(self, 'Could not open', str(error))


class SourceStrip(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(8)
        self.locations = []
        for index, title in enumerate(('Existing calibration', 'New captures', 'Results')):
            if index:
                layout.addWidget(label('\u2192', 'muted'))
            location = SourceLocation(title)
            self.locations.append(location)
            layout.addWidget(location, 1)

    def set_paths(self, calibration, captures, results):
        for location, path in zip(self.locations, (calibration, captures, results)):
            location.set_path(path)


class OptionsResults(QtWidgets.QWidget):
    mode_changed = QtCore.pyqtSignal(str)

    def __init__(self, comparison):
        super().__init__()
        self.comparison = comparison
        self.detail_dialog = None
        self.tiles = {}
        self.help_buttons = {}
        self.active_mode = None
        rmse = rmse_changes(comparison)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSizeConstraint(QtWidgets.QLayout.SetNoConstraint)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        recommendation = QtWidgets.QFrame()
        recommendation.setObjectName('recommendation')
        recommendation.setStyleSheet(f'QFrame#recommendation {{ background: {RECOMMEND_BG}; '
                                    f'border: 1px solid {RECOMMEND_BORDER}; border-radius: 12px; }}')
        action_layout = QtWidgets.QVBoxLayout(recommendation)
        action_layout.setContentsMargins(14, 10, 14, 12)
        action_layout.setSpacing(3)
        action_title = label('Recommended next step', 'small')
        action_title.setStyleSheet(f'color: {RECOMMEND_INK}; font-weight: 600;')
        action_layout.addWidget(action_title)
        action_layout.addWidget(label(comparison.get('recommendation', comparison['reason']), 'h2', wrap=True))
        layout.addWidget(recommendation)
        self.row = QtWidgets.QGridLayout()
        self.row.setSpacing(10)
        selected = comparison['selected'] or ('existing' if comparison['status'] == 'keep' else None)
        for mode, option in OPTIONS.items():
            title = option[0]
            tile = QtWidgets.QFrame()
            tile.setObjectName('optionTile')
            tile.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
            tile.setMinimumWidth(0)
            tile.setCursor(Qt.PointingHandCursor)
            tile.setFocusPolicy(Qt.StrongFocus)
            tile.installEventFilter(self)
            tile.setProperty("mode", mode)
            chosen = mode == selected
            tile.setStyleSheet(f'QFrame#optionTile {{ background: white; '
                              f'border: 1px solid {RECOMMEND_BORDER if chosen else LINE}; border-radius: 12px; }}')
            box = QtWidgets.QVBoxLayout(tile)
            box.setContentsMargins(14, 12, 14, 12)
            box.setSpacing(6)
            title_label = label(title, 'h3', wrap=True)
            if chosen:
                recommended = label('Recommended', 'small')
                recommended.setStyleSheet(f'color: {RECOMMEND_INK}; font-weight: 600;')
                box.addWidget(hbox(title_label, recommended, stretch_at=1))
            else:
                box.addWidget(title_label)
            score = comparison['scores'].get(mode)
            number = label(f'{score * 100:.1f}%' if score is not None else '\u2014')
            number.setStyleSheet('font-size: 23pt; font-weight: 600;')
            error = rmse.get(mode)
            if mode == 'existing':
                gain_text = 'Current calibration · baseline'
            elif error and error['reduction_percent'] is not None:
                percent = error['reduction_percent']
                gain_text = f'RMSE {abs(percent):.1f}% ' + ('lower' if percent >= 0 else 'higher')
            else:
                gain_text = 'RMSE not measured'
            gain_label = label(gain_text, 'small', wrap=True)
            if error and mode != 'existing':
                gain_label.setStyleSheet('color: ' + ('#248a3d' if error['reduction_px'] >= 0 else '#d70015') + ';')
            score_row = hbox(number, gain_label, spacing=12)
            score_row.layout().setStretch(1, 1)
            box.addWidget(score_row)
            bar = QtWidgets.QProgressBar()
            bar.setRange(0, 1000)
            bar.setValue(round(score * 1000) if score is not None else 0)
            bar.setTextVisible(False)
            bar.setFixedHeight(5)
            bar.setAccessibleName(title + ' held-out alignment')
            box.addWidget(bar)
            box.addWidget(label(f'≈ {round(score * 100)} in 100 tested edge points match' if score is not None
                                else 'Not enough held-out data', 'small', wrap=True))
            rmse_text = (f"{error['before_px']:.2f} px" if mode == 'existing' else
                         f"{error['before_px']:.2f} → {error['after_px']:.2f} px") if error else 'Not measured'
            rmse_label = label('Edge RMSE: ' + rmse_text, 'h3', wrap=True)
            rmse_label.setToolTip('Root mean squared distance to the nearest image edge over all common visible held-out '
                                  'LiDAR edge points. No 2 px match gate. Lower is better. '
                                  'This is an alignment proxy, not known-correspondence reprojection error.')
            box.addWidget(rmse_label)
            movement = comparison.get('movements', {}).get(mode)
            if mode == 'existing':
                movement = dict(median_px=0.)
            movement_text = (f"{movement['median_px']:.2f} px" if movement and movement.get('median_px') is not None
                             else 'Not saved for this option')
            box.addWidget(label('Median projection shift: ' + movement_text, 'h3', wrap=True))
            if movement and movement.get('p90_px') is not None:
                box.addWidget(label(f"90% of points move less than {movement['p90_px']:.2f} px", 'small', wrap=True))
            help_button = QtWidgets.QToolButton()
            help_button.setText('i')
            help_button.clicked.connect(lambda checked=False, mode=mode: self.show_option(mode))
            help_button.setCursor(Qt.PointingHandCursor)
            help_button.setAccessibleName(f'Explain {title}')
            help_button.setToolTip('What changes and what the numbers mean')
            help_button.setFixedSize(22, 22)
            help_button.setStyleSheet(f'QToolButton {{ color: {RECOMMEND_INK if chosen else BLUE}; '
                                     'border: 1px solid #cbd2dc; border-radius: 11px; background: transparent; '
                                     'font-family: Georgia; font-style: italic; font-size: 11pt; padding: 0; } '
                                     'QToolButton:hover, QToolButton:focus { background: #edf5ff; border-color: #007aff; }')
            if chosen:
                box.itemAt(0).widget().layout().addWidget(help_button)
            else:
                box.takeAt(0)
                box.insertWidget(0, hbox(title_label, help_button, stretch_at=1))
            self.help_buttons[mode] = help_button
            tile.setAccessibleName(f'{title}: {number.text()}. ' + ('Recommended in comparison.' if chosen else ''))
            self.tiles[mode] = tile
            for child in tile.findChildren(QtWidgets.QWidget):
                if child is not help_button and not isinstance(child, QtWidgets.QAbstractButton):
                    child.installEventFilter(self)
                    child.setProperty('mode', mode)
        layout.addLayout(self.row)
        layout.addWidget(label(f'{comparison["folds"]} held-out checks · percentages are edge-match scores. Higher is better. '
                               'Click a card to preview matrices · the info icon explains the option.', 'small', wrap=True))
        self.arrange_tiles()
        self.select_mode(selected or 'existing')

    def eventFilter(self, watched, event):
        mode = watched.property('mode')
        if mode and ((event.type() == QtCore.QEvent.MouseButtonRelease and event.button() == Qt.LeftButton)
                     or (event.type() == QtCore.QEvent.KeyPress and event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space))):
            self.select_mode(mode)
            return True
        return super().eventFilter(watched, event)

    def select_mode(self, mode):
        self.active_mode = mode
        recommended = self.comparison['selected'] or ('existing' if self.comparison['status'] == 'keep' else None)
        for key, tile in self.tiles.items():
            chosen, active = key == recommended, key == mode
            border = RECOMMEND_BORDER if chosen else BLUE if active else LINE
            tile.setStyleSheet(f'QFrame#optionTile {{ background: white; '
                              f'border: {2 if active else 1}px solid {border}; border-radius: 12px; }}')
            tile.setAccessibleDescription('Previewing matrices' if active else 'Click to preview matrices')
        self.mode_changed.emit(mode)

    def arrange_tiles(self):
        columns = 4 if self.width() >= 1000 else 2
        while self.row.count():
            self.row.takeAt(0)
        for index, tile in enumerate(self.tiles.values()):
            self.row.addWidget(tile, index // columns, index % columns)
        for index in range(4):
            self.row.setColumnStretch(index, 1 if index < columns else 0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.arrange_tiles()

    def show_option(self, mode):
        if self.detail_dialog is None:
            self.detail_dialog = OptionHelpDialog(self.comparison, mode, self)
        else:
            self.detail_dialog.set_mode(mode)
        self.detail_dialog.tabs.setCurrentIndex(0)
        self.detail_dialog.open()
