"""Compact shared controls for inputs, update choices and comparison results."""
from __future__ import annotations

import os
from pathlib import Path

from PyQt5 import QtCore, QtWidgets
from PyQt5.QtCore import Qt
import appcore as core

from ui_common import BLUE, BLUE_SOFT, LINE, MUTED, button, hbox, label

MODE_NAMES = {'compare': 'Compare update options', 'extrinsic': 'Alignment only',
              'intrinsic': 'Camera settings only', 'full': 'Camera + alignment'}


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
    def __init__(self, comparison):
        super().__init__()
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(label(comparison.get('recommendation', comparison['reason']), 'h2', wrap=True))
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(10)
        selected = comparison['selected'] or ('existing' if comparison['status'] == 'keep' else None)
        for mode, title in [('existing', 'Keep current'), ('extrinsic', 'Alignment only'),
                            ('intrinsic', 'Camera only'), ('full', 'Camera + alignment')]:
            tile = QtWidgets.QFrame()
            tile.setObjectName('optionTile')
            chosen = mode == selected
            tile.setStyleSheet(f'QFrame#optionTile {{ background: {BLUE_SOFT if chosen else "white"}; '
                              f'border: 1px solid {BLUE if chosen else LINE}; border-radius: 12px; }}')
            box = QtWidgets.QVBoxLayout(tile)
            box.setContentsMargins(14, 12, 14, 12)
            box.setSpacing(6)
            box.addWidget(label(title, 'h3', wrap=True))
            score = comparison['scores'].get(mode)
            number = label(f'{score * 100:.1f}%' if score is not None else '\u2014')
            number.setStyleSheet('font-size: 23pt; font-weight: 600;')
            box.addWidget(number)
            bar = QtWidgets.QProgressBar()
            bar.setRange(0, 1000)
            bar.setValue(round(score * 1000) if score is not None else 0)
            bar.setTextVisible(False)
            bar.setFixedHeight(5)
            bar.setAccessibleName(title + ' held-out alignment')
            box.addWidget(bar)
            box.addWidget(label('Held-out alignment', 'small'))
            row.addWidget(tile, 1)
        layout.addLayout(row)
        note = label(f'{comparison["folds"]} held-out checks \u00b7 higher alignment is better', 'small')
        note.setToolTip('Every option is fitted without the held-out data and scored on the same visible points. '
                        'Extra parameters need a consistent advantage of at least one percentage point. '
                        'This is a decision heuristic, not proof that the lens changed. '
                        + comparison.get('limitation', ''))
        layout.addWidget(note)
