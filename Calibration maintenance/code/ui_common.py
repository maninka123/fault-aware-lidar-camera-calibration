"""Shared look and widgets of the Calibration maintenance desktop app (app.py, device_ui.py)."""
from __future__ import annotations

import math
import os
from pathlib import Path

import appcore as core

from PyQt5 import QtCore, QtGui, QtWidgets  # noqa: E402
from PyQt5.QtCore import Qt  # noqa: E402

BLUE, ORANGE = "#007aff", "#ff9500"
GOOD, GOOD_SOFT = "#248a3d", "#eaf6ed"
WARN, WARN_SOFT = "#9b6500", "#fff6e5"
BAD, BAD_SOFT = "#d70015", "#fff0f1"
INFO_SOFT, BLUE_SOFT = "#eeeeF2", "#edf5ff"
INK, INK2, MUTED, LINE, BG = "#1d1d1f", "#48484a", "#6e6e73", "#e5e5ea", "#f5f5f7"
MONO = "Cascadia Mono, Consolas, monospace"
CHEVRON_DOWN = (Path(__file__).resolve().parent / "assets" / "chevron-down.svg").as_posix()
CHEVRON_UP = (Path(__file__).resolve().parent / "assets" / "chevron-up.svg").as_posix()

VERDICT = {
    "NO UPDATE NEEDED": (GOOD, GOOD_SOFT, "✅", "Keep the previous calibration."),
    "BORDERLINE": (WARN, WARN_SOFT, "⚠️", "Keep the previous calibration for now. Record a few more captures "
                   "(turn the rig a little between them) and check again."),
    "UPDATE RECOMMENDED": (BLUE, BLUE_SOFT, "🔧", "Accept the refined calibration (Result tab, bottom)."),
    "LARGE CHANGE": (BAD, BAD_SOFT, "🚨", "Check the mounting first. Then accept the refined calibration, or recalibrate from scratch."),
    "INCONCLUSIVE": (MUTED, INFO_SOFT, "❔", "Capture a scene with more structure (edges at several depths) and check again."),
}
STAGES = [
    ("data", "Data", "Data: stacked captures",
     "Each image should be sharp and show the scene. Camera and LiDAR frames are stacked over the still part of every capture."),
    ("features", "Detection", "What is detected: LiDAR edges and image edges",
     "Left: LiDAR edges in the LiDAR's own view (red = depth jumps, green = plane creases, blue = reflectivity). "
     "Right: image edges. Both should trace the same object outlines; few edges means little structure in the scene."),
    ("health", "Previous", "Previous calibration on the new data",
     "LiDAR edges projected into the image with the previous calibration. Green = on an image edge, yellow = 1-3 px off, "
     "red = further. Outlines in yellow or red mean drift."),
    ("search", "Search", "Refinement candidates",
     "Refinements started from the previous calibration and from a small search around it (±4°). The one that aligns "
     "the edges best (highest lift over chance) wins."),
    ("refined", "Refined", "Refined calibration",
     "The same view with the refined calibration. Outlines should be greener than with the previous calibration."),
    ("evidence", "Evidence", "Evidence: left-out captures and image regions",
     "The refinement is repeated leaving out one capture or one image region at a time, and tested on what was left "
     "out. A real change also fits regions it never saw. The spread of these refits is the uncertainty."),
    ("verdict", "Verdict", "Verdict", ""),
]
PARAMS = {"fx": ("Focal length fx", "px", 2), "fy": ("Focal length fy", "px", 2), "cx": ("Principal point cx", "px", 2),
          "cy": ("Principal point cy", "px", 2), "k1": ("Distortion k1", "", 4), "k2": ("Distortion k2", "", 4),
          "tx": ("Translation x", "mm", 1), "ty": ("Translation y", "mm", 1), "tz": ("Translation z", "mm", 1),
          "tilt": ("Tilt (camera x)", "°", 3), "pan": ("Pan (camera y)", "°", 3), "roll": ("Roll (camera z)", "°", 3)}

QSS = f"""
QMainWindow, QWidget#page, QScrollArea > QWidget > QWidget#page {{ background: {BG}; }}
QWidget {{ font-family: 'Segoe UI'; font-size: 10.5pt; color: {INK}; }}
QDialog {{ background: {BG}; }}
QFrame#card {{ background: white; border: 1px solid {LINE}; border-radius: 16px; }}
QFrame#sidebar {{ background: #efeff3; border-right: 1px solid {LINE}; }}
QFrame#sourceItem {{ background: #eeeef2; border: 1px solid #e5e5ea; border-radius: 10px; }}
QFrame#soft {{ background: {BLUE_SOFT}; border-radius: 7px; }}
QFrame#subtle {{ background: #f8f9fb; border: 1px solid {LINE}; border-radius: 8px; }}
QLabel#h1 {{ font-size: 22pt; font-weight: 600; }}
QLabel#h2 {{ font-size: 12.5pt; font-weight: 600; }}
QLabel#h3 {{ font-size: 10.5pt; font-weight: 600; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#small {{ color: {MUTED}; font-size: 9pt; }}
QLabel#caps {{ color: {MUTED}; font-size: 8.5pt; font-weight: 700; letter-spacing: 1px; }}
QLabel#err {{ color: {BAD}; background: {BAD_SOFT}; border-radius: 6px; padding: 6px 10px; }}
QPushButton {{ background: white; border: 1px solid #dcdce2; border-radius: 9px; padding: 7px 14px; min-height: 18px; font-weight: 600; }}
QPushButton:hover {{ background: #f8f8fa; border-color: #bdbdc5; }}
QPushButton:pressed {{ background: #e9e9ef; }}
QPushButton:focus {{ border-color: {BLUE}; }}
QPushButton:checked {{ background: {BLUE_SOFT}; border-color: {BLUE}; color: {BLUE}; }}
QPushButton:disabled {{ color: #a0a6ae; }}
QPushButton#primary {{ background: {BLUE}; color: white; border-color: {BLUE}; }}
QPushButton#primary:hover {{ background: #1686ff; border-color: #1686ff; }}
QPushButton#primary:pressed {{ background: #0064d5; border-color: #0064d5; }}
QPushButton#primary:disabled {{ background: #a9c7ec; border-color: #a9c7ec; color: white; }}
QPushButton#big {{ padding: 10px 34px; font-size: 11pt; }}
QPushButton#link {{ border: none; background: transparent; color: {BLUE}; padding: 4px 6px; }}
QListWidget#runs {{ background: transparent; border: none; outline: none; }}
QListWidget#runs::item {{ padding: 10px 8px; border-radius: 10px; margin: 2px 2px; }}
QListWidget#runs::item:hover {{ background: #f3f5f8; }}
QListWidget#runs::item:selected {{ background: #dceaff; color: {INK}; }}
QListWidget#stages {{ background: white; border: 1px solid {LINE}; border-radius: 10px; outline: none; padding: 4px; }}
QListWidget#stages::item {{ padding: 9px 6px; border-radius: 7px; }}
QListWidget#stages::item:selected {{ background: {BLUE_SOFT}; color: {INK}; }}
QComboBox, QLineEdit, QPlainTextEdit, QSpinBox {{ background: white; border: 1px solid #dcdce2; border-radius: 9px; padding: 7px 10px; min-height: 18px; selection-background-color: {BLUE}; }}
QComboBox:focus, QLineEdit:focus, QPlainTextEdit:focus {{ border-color: {BLUE}; }}
QComboBox {{ padding-right: 32px; }}
QComboBox:hover {{ border-color: #a6afbc; }}
QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: top right; width: 28px; border: none; border-top-right-radius: 6px; border-bottom-right-radius: 6px; }}
QComboBox::down-arrow {{ image: url("{CHEVRON_DOWN}"); width: 12px; height: 8px; }}
QComboBox QLineEdit {{ border: none; border-radius: 0; padding: 0; background: transparent; }}
QComboBox QAbstractItemView {{ background: white; border: 1px solid {LINE}; padding: 5px; outline: none; selection-background-color: {BLUE_SOFT}; selection-color: {INK}; }}
QComboBox QAbstractItemView::item {{ min-height: 28px; padding: 3px 8px; }}
QSpinBox {{ padding-right: 28px; }}
QSpinBox::up-button {{ subcontrol-origin: border; subcontrol-position: top right; width: 24px; border: none; background: transparent; }}
QSpinBox::down-button {{ subcontrol-origin: border; subcontrol-position: bottom right; width: 24px; border: none; background: transparent; }}
QSpinBox::up-arrow {{ image: url("{CHEVRON_UP}"); width: 9px; height: 6px; }}
QSpinBox::down-arrow {{ image: url("{CHEVRON_DOWN}"); width: 9px; height: 6px; }}
QGroupBox {{ border: 1px solid {LINE}; border-radius: 12px; margin-top: 16px; padding: 16px 12px 12px; font-weight: 600; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 5px; }}
QProgressBar {{ background: #e8e8ed; border: none; border-radius: 3px; min-height: 5px; text-align: center; }}
QProgressBar::chunk {{ background: {BLUE}; border-radius: 3px; }}
QToolTip {{ color: {INK}; background: white; border: 1px solid {LINE}; padding: 8px; }}
QRadioButton {{ spacing: 8px; }}
QTableWidget {{ background: white; border: none; }}
QTableWidget::item {{ padding: 6px 8px; border-bottom: 1px solid #efeff3; }}
QHeaderView::section {{ background: #fafafc; border: none; border-bottom: 1px solid {LINE}; padding: 8px; font-weight: 600; color: {MUTED}; font-size: 9pt; }}
QTabWidget::pane {{ border: none; }}
QTabBar {{ background: #e9e9ef; border-radius: 10px; }}
QTabBar::tab {{ background: transparent; min-width: 80px; min-height: 22px; padding: 7px 18px; margin: 3px; color: {MUTED}; font-weight: 600; border: 1px solid transparent; border-radius: 8px; }}
QTabBar::tab:selected {{ background: white; color: {INK}; border: 1px solid #dcdce2; }}
QTabBar::tab:disabled {{ color: #c0c5cc; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 12px; margin: 2px 0; }}
QScrollBar::handle:vertical {{ background: #c6cbd3; border-radius: 4px; min-height: 32px; margin: 0 2px; }}
QScrollBar::handle:vertical:hover {{ background: #a6afbc; }}
QScrollBar::handle:vertical:pressed {{ background: #8693a3; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; border: none; background: transparent; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 0 2px; }}
QScrollBar::handle:horizontal {{ background: #c6cbd3; border-radius: 4px; min-width: 32px; margin: 2px 0; }}
QScrollBar::handle:horizontal:hover {{ background: #a6afbc; }}
QScrollBar::handle:horizontal:pressed {{ background: #8693a3; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; border: none; background: transparent; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}
QSplitter::handle {{ background: {LINE}; }}
"""


# ================================================================== small widgets
def open_path(path):
    """Open a file or folder with the system's default program (os.startfile exists on Windows only)."""
    try:
        if hasattr(os, "startfile"):
            os.startfile(str(path))
            return True
    except OSError:
        pass
    return QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(path)))


def label(text="", name=None, wrap=False, rich=False, sel=False):
    w = QtWidgets.QLabel(text)
    if name:
        w.setObjectName(name)
    w.setWordWrap(wrap)
    if rich:
        w.setTextFormat(Qt.RichText)
    if sel:
        w.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return w


def button(text, name=None, slot=None):
    b = QtWidgets.QPushButton(text)
    if name:
        b.setObjectName(name)
    b.setCursor(Qt.PointingHandCursor)
    if slot:
        b.clicked.connect(slot)
    return b


def navigation_icon(kind, selected=False):
    """Small matching outline icons for the two maintenance workflows."""
    pm = QtGui.QPixmap(40, 40)
    pm.fill(Qt.transparent)
    painter = QtGui.QPainter(pm)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    painter.scale(2, 2)
    painter.setPen(QtGui.QPen(QtGui.QColor('white' if selected else INK2), 1.5,
                             Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.setBrush(Qt.NoBrush)
    if kind == 'devices':
        painter.drawLine(QtCore.QPointF(10, 7), QtCore.QPointF(10, 10))
        painter.drawLine(QtCore.QPointF(4, 10), QtCore.QPointF(16, 10))
        for x in (4, 16):
            painter.drawLine(QtCore.QPointF(x, 10), QtCore.QPointF(x, 13))
        for x, y in ((7, 1), (1, 13), (13, 13)):
            painter.drawRoundedRect(QtCore.QRectF(x, y, 6, 5), 1, 1)
    else:
        painter.drawPolyline(QtGui.QPolygonF([QtCore.QPointF(x, y) for x, y in
                             ((12, 1), (4, 1), (4, 18), (17, 18), (17, 6), (12, 1), (12, 6), (17, 6))]))
        painter.drawPolyline(QtGui.QPolygonF([QtCore.QPointF(x, y) for x, y in ((7, 11), (10, 14), (14, 9))]))
    painter.end()
    return QtGui.QIcon(pm)


def card(title=None, subtitle=None):
    f = QtWidgets.QFrame()
    f.setObjectName("card")
    lay = QtWidgets.QVBoxLayout(f)
    lay.setContentsMargins(20, 16, 20, 18)
    lay.setSpacing(10)
    if title:
        lay.addWidget(label(title, "h2"))
    if subtitle:
        lay.addWidget(label(subtitle, "muted", wrap=True))
    return f, lay


def hbox(*widgets, stretch_at=None, spacing=8):
    w = QtWidgets.QWidget()
    lay = QtWidgets.QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(spacing)
    for k, x in enumerate(widgets):
        if k == stretch_at:
            lay.addStretch(1)
        if isinstance(x, QtWidgets.QWidget):
            lay.addWidget(x)
        elif isinstance(x, QtWidgets.QLayout):
            lay.addLayout(x)
    if stretch_at is not None and stretch_at >= len(widgets):
        lay.addStretch(1)
    return w


def scroll(widget):
    s = QtWidgets.QScrollArea()
    s.setWidgetResizable(True)
    s.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    s.setWidget(widget)
    return s


def dot_icon(color, ring=None, size=14):
    pm = QtGui.QPixmap(size * 2, size * 2)
    pm.fill(Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QtGui.QColor(color))
    p.drawEllipse(QtCore.QRectF(size * 0.5, size * 0.5, size, size))
    p.end()
    return QtGui.QIcon(pm)


def badge_icon(color, text, size=22):
    pm = QtGui.QPixmap(size * 2, size * 2)
    pm.fill(Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QtGui.QColor(color))
    p.drawEllipse(QtCore.QRectF(2, 2, size * 2 - 4, size * 2 - 4))
    p.setPen(QtGui.QColor("white"))
    f = QtGui.QFont("Segoe UI")
    f.setBold(True)
    f.setPixelSize(int(size * 1.15))
    p.setFont(f)
    p.drawText(QtCore.QRectF(0, 0, size * 2, size * 2), Qt.AlignCenter, text)
    p.end()
    return QtGui.QIcon(pm)


def app_icon():
    pm = QtGui.QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    p.setBrush(QtGui.QColor(BLUE))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(0, 0, 64, 64, 14, 14)
    pen = QtGui.QPen(QtGui.QColor("white"), 5)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(14, 14, 36, 36)
    p.setBrush(QtGui.QColor("white"))
    p.drawEllipse(27, 27, 10, 10)
    p.end()
    return QtGui.QIcon(pm)


def np_to_pixmap(img):
    h, w = img.shape[:2]
    if img.ndim == 2:
        q = QtGui.QImage(img.data, w, h, img.strides[0], QtGui.QImage.Format_Grayscale8)
    else:
        q = QtGui.QImage(img.data, w, h, img.strides[0], QtGui.QImage.Format_BGR888)
    return QtGui.QPixmap.fromImage(q.copy())


class ImageView(QtWidgets.QWidget):
    """An image (or animated GIF) scaled to the width available; click to enlarge."""

    def __init__(self, path=None, pixmap=None, caption="", max_height=None, clickable=True):
        super().__init__()
        self.movie, self.pix, self.path, self.caption, self.max_height = None, QtGui.QPixmap(), None, caption, max_height
        sp = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        sp.setHeightForWidth(True)
        self.setSizePolicy(sp)
        self.clickable = clickable
        if clickable:
            self.setCursor(Qt.PointingHandCursor)
            self.setToolTip("Click to enlarge")
        self.set_source(path, pixmap)

    def set_source(self, path=None, pixmap=None):
        if self.movie:
            self.movie.stop()
            self.movie.deleteLater()
            self.movie = None
        self.path = str(path) if path else None
        if self.path and self.path.lower().endswith(".gif"):
            self.movie = QtGui.QMovie(self.path)
            self.movie.frameChanged.connect(lambda k: (self.updateGeometry() if k == 0 else None, self.update()))
            self.movie.start()
        else:
            self.pix = pixmap if pixmap is not None else QtGui.QPixmap(self.path) if self.path else QtGui.QPixmap()
        self.updateGeometry()
        self.update()

    def current(self):
        return self.movie.currentPixmap() if self.movie else self.pix

    def ratio(self):
        p = self.current()
        return p.height() / p.width() if not p.isNull() and p.width() else 0.75

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        h = int(w * self.ratio())
        return min(h, self.max_height) if self.max_height else h

    def sizeHint(self):
        return QtCore.QSize(480, self.heightForWidth(480))

    def paintEvent(self, _):
        p = self.current()
        if p.isNull():
            return
        qp = QtGui.QPainter(self)
        qp.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        s = p.size().scaled(self.size(), Qt.KeepAspectRatio)
        r = QtCore.QRect(QtCore.QPoint((self.width() - s.width()) // 2, 0), s)
        qp.drawPixmap(r, p)

    def mouseReleaseEvent(self, e):
        if self.clickable and e.button() == Qt.LeftButton and not self.current().isNull():
            ImageDialog(self.path, self.pix if not self.movie else None, self.caption, self.window()).exec_()


class ImageDialog(QtWidgets.QDialog):
    def __init__(self, path, pixmap, caption, parent):
        super().__init__(parent)
        self.setWindowTitle(caption or "Image")
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        view = ImageView(path, pixmap, clickable=False)
        lay.addWidget(view, 1)
        row = hbox(label(caption, "muted"), button("Open in viewer", slot=lambda: open_path(path)) if path else QtWidgets.QWidget(),
                   button("Close", slot=self.accept), stretch_at=1)
        lay.addWidget(row)
        scr = QtWidgets.QApplication.primaryScreen().availableGeometry()
        r = view.ratio()
        w = min(int(scr.width() * 0.9), int((scr.height() * 0.85) / r))
        self.resize(w, int(w * r) + 60)


class Figure(QtWidgets.QWidget):
    def __init__(self, path, caption):
        super().__init__()
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(3)
        lay.addWidget(ImageView(path, caption=caption))
        lay.addWidget(label(caption, "small"))


def image_grid(paths, columns):
    w = QtWidgets.QWidget()
    g = QtWidgets.QGridLayout(w)
    g.setContentsMargins(0, 0, 0, 0)
    g.setSpacing(12)
    for k, p in enumerate(paths):
        g.addWidget(Figure(p, img_label(p)), k // columns, k % columns)
    for c in range(columns):
        g.setColumnStretch(c, 1)
    return w


def img_label(p):
    f = Path(p).stem
    names = {"data": "Capture", "lidar_edges": "LiDAR edges", "image_edges": "Image edges", "existing": "Previous calibration",
             "refined": "Refined calibration", "motion": "Still window found"}
    for k, v in names.items():
        if f.startswith(k + "_"):
            return f"{v} · {core.capture_display_name(f[len(k) + 1:])}"
    return {"regions": "Image regions (left out one at a time)", "shift_by_range": "How far points move, by distance"}.get(f, f.replace("_", " "))


class ContentTable(QtWidgets.QTableWidget):
    """Share spare width while preserving the space needed by every column."""
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_columns()

    def fit_columns(self):
        if not hasattr(self, 'content_widths'):
            return
        spare = max(0, self.viewport().width() - sum(self.content_widths))
        count = max(1, len(self.stretch_columns))
        for index, width in enumerate(self.content_widths):
            self.setColumnWidth(index, width + (spare // count if index in self.stretch_columns else 0))


def table(headers, rows, numeric=(), group_rows=(), highlight=(), stretch=(0,)):
    """Read-only table that is as tall as its content. A cell is text or (text, colour, background, bold)."""
    t = ContentTable(len(rows), len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.verticalHeader().hide()
    t.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
    t.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
    t.setFocusPolicy(Qt.NoFocus)
    t.setShowGrid(False)
    t.setWordWrap(False)
    t.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    t.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    mono = QtGui.QFont("Consolas", 10)
    for i, row in enumerate(rows):
        if i in group_rows:
            it = QtWidgets.QTableWidgetItem(str(row[0]).upper())
            f = it.font(); f.setBold(True); f.setPointSizeF(8.5); it.setFont(f)
            it.setForeground(QtGui.QColor(MUTED)); it.setBackground(QtGui.QColor("#f8f9fb"))
            t.setItem(i, 0, it)
            t.setSpan(i, 0, 1, len(headers))
            continue
        for j, cell in enumerate(row):
            text, fg, bg, bold = (cell + (None,) * 4)[:4] if isinstance(cell, tuple) else (cell, None, None, False)
            it = QtWidgets.QTableWidgetItem(str(text))
            it.setToolTip(str(text))
            it.setTextAlignment((Qt.AlignRight if j in numeric else Qt.AlignLeft) | Qt.AlignVCenter)
            if j in numeric:
                it.setFont(mono)
            if fg:
                it.setForeground(QtGui.QColor(fg))
            if bg:
                it.setBackground(QtGui.QColor(bg))
            elif i in highlight:
                it.setBackground(QtGui.QColor(BLUE_SOFT))
            if bold:
                f = it.font(); f.setBold(True); it.setFont(f)
            t.setItem(i, j, it)
    hh = t.horizontalHeader()
    hh.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    hh.setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents)
    hh.setStretchLastSection(False)
    for j in numeric:
        it = t.horizontalHeaderItem(j)
        it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
    t.ensurePolished()
    t.resizeColumnsToContents()
    t.content_widths = [t.columnWidth(j) for j in range(len(headers))]
    t.stretch_columns = stretch
    hh.setSectionResizeMode(QtWidgets.QHeaderView.Fixed)
    t.fit_columns()
    t.resizeRowsToContents()
    for i in range(len(rows)):
        t.setRowHeight(i, max(t.rowHeight(i), 30))
    t.setFixedHeight(hh.height() + sum(t.rowHeight(i) for i in range(len(rows))) + 22)
    return t


# ================================================================== painted widgets
class StepTracker(QtWidgets.QWidget):
    clicked = QtCore.pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self.states = [""] * len(STAGES)
        self.setMinimumHeight(64)
        self.setCursor(Qt.PointingHandCursor)

    def set_states(self, states):
        self.states = states
        self.update()

    def paintEvent(self, _):
        qp = QtGui.QPainter(self)
        qp.setRenderHint(QtGui.QPainter.Antialiasing)
        n, W, r, y = len(STAGES), self.width(), 13, 18
        xs = [W * (i + 0.5) / n for i in range(n)]
        for i in range(1, n):
            done = self.states[i - 1] == "done" and self.states[i] in ("done", "active")
            qp.setPen(QtGui.QPen(QtGui.QColor(GOOD if done else LINE), 2))
            qp.drawLine(QtCore.QPointF(xs[i - 1] + r + 3, y), QtCore.QPointF(xs[i] - r - 3, y))
        for i, (x, st) in enumerate(zip(xs, self.states)):
            col, txt, fg = {"done": (GOOD, "✓", "white"), "active": (BLUE, str(i + 1), "white"),
                            "failed": (BAD, "!", "white")}.get(st, (INFO_SOFT, str(i + 1), MUTED))
            qp.setPen(Qt.NoPen)
            qp.setBrush(QtGui.QColor(col))
            qp.drawEllipse(QtCore.QPointF(x, y), r, r)
            qp.setPen(QtGui.QColor(fg))
            qp.setFont(QtGui.QFont("Segoe UI", 9, QtGui.QFont.Bold))
            qp.drawText(QtCore.QRectF(x - r, y - r, 2 * r, 2 * r), Qt.AlignCenter, txt)
            qp.setPen(QtGui.QColor(BLUE if st == "active" else INK2 if st == "done" else MUTED))
            qp.setFont(QtGui.QFont("Segoe UI", 9, QtGui.QFont.Bold if st == "active" else QtGui.QFont.Normal))
            qp.drawText(QtCore.QRectF(x - W / n / 2, y + r + 4, W / n, 20), Qt.AlignHCenter | Qt.AlignTop, STAGES[i][1])

    def mousePressEvent(self, e):
        self.clicked.emit(min(len(STAGES) - 1, int(e.x() / (self.width() / len(STAGES)))))


class Gauge(QtWidgets.QWidget):
    """How far points move, on a scale with the error margin, drift and large-change zones and the likely range."""

    def __init__(self, shift, u):
        super().__init__()
        self.shift, self.u = shift, u if core.fin(u) else 0.0
        self.setMinimumHeight(118)

    def paintEvent(self, _):
        qp = QtGui.QPainter(self)
        qp.setRenderHint(QtGui.QPainter.Antialiasing)
        x0, x1, y, h = 14, self.width() - 14, 36, 16
        mx = max(6, math.ceil(self.shift + 2 * self.u + 1))
        X = lambda v: x0 + (x1 - x0) * min(max(v, 0), mx) / mx
        for a, b, soft, hard in ((0, 1, GOOD_SOFT, GOOD), (1, 5, WARN_SOFT, WARN), (5, mx, BAD_SOFT, BAD)):
            if a >= mx:
                continue
            qp.setPen(QtGui.QPen(QtGui.QColor(hard), 1))
            qp.setBrush(QtGui.QColor(soft))
            qp.drawRoundedRect(QtCore.QRectF(X(a) + 1, y, X(min(b, mx)) - X(a) - 2, h), 4, 4)
        if self.u:
            band = QtGui.QColor(ORANGE)
            band.setAlpha(110)
            qp.setPen(Qt.NoPen)
            qp.setBrush(band)
            lo, hi = max(0, self.shift - 2 * self.u), self.shift + 2 * self.u
            qp.drawRoundedRect(QtCore.QRectF(X(lo), y + 4, X(hi) - X(lo), h - 8), 3, 3)
        xm = X(self.shift)
        qp.setPen(Qt.NoPen)
        qp.setBrush(QtGui.QColor(ORANGE))
        qp.drawRoundedRect(QtCore.QRectF(xm - 2.5, y - 9, 5, h + 18), 2, 2)
        qp.setPen(QtGui.QColor(INK))
        qp.setFont(QtGui.QFont("Segoe UI", 10, QtGui.QFont.Bold))
        qp.drawText(QtCore.QRectF(xm - 80, 2, 160, 22), Qt.AlignCenter, f"{self.shift:.2f} px")
        qp.setFont(QtGui.QFont("Segoe UI", 8))
        qp.setPen(QtGui.QColor(MUTED))
        step = 1 if mx <= 12 else 2
        for t in range(0, mx + 1, step):
            qp.drawText(QtCore.QRectF(X(t) - 15, y + h + 10, 30, 14), Qt.AlignCenter, str(t))
        ly = y + h + 34
        items = [(GOOD_SOFT, GOOD, "within the error margin (< 1 px)"), (WARN_SOFT, WARN, "drift (1-5 px)"),
                 (BAD_SOFT, BAD, "large change (> 5 px)"), (ORANGE, None, "likely range (± 2 × uncertainty)")]
        x = x0
        qp.setFont(QtGui.QFont("Segoe UI", 9))
        fm = qp.fontMetrics()
        for soft, hard, text in items:
            c = QtGui.QColor(soft)
            if hard is None:
                c.setAlpha(120)
            qp.setBrush(c)
            qp.setPen(QtGui.QPen(QtGui.QColor(hard)) if hard else Qt.NoPen)
            qp.drawRoundedRect(QtCore.QRectF(x, ly, 12, 12), 3, 3)
            qp.setPen(QtGui.QColor(INK2))
            qp.drawText(QtCore.QPointF(x + 18, ly + 11), text)
            x += 18 + fm.horizontalAdvance(text) + 22


# ================================================================== calibration display / entry
def value_grid(items, columns=3):
    w = QtWidgets.QWidget()
    g = QtWidgets.QGridLayout(w)
    g.setContentsMargins(0, 0, 0, 0)
    g.setHorizontalSpacing(22)
    g.setVerticalSpacing(8)
    for k, (name, value) in enumerate(items):
        box = QtWidgets.QVBoxLayout()
        box.setSpacing(0)
        box.addWidget(label(name, "small"))
        v = label(value, sel=True)
        v.setStyleSheet(f"font-family: {MONO}; font-size: 11pt; font-weight: 600;")
        box.addWidget(v)
        g.addLayout(box, k // columns, k % columns)
    return w


def calibration_view(c):
    """The intrinsics and extrinsics of a calibration, laid out for reading."""
    i, e = c["intrinsics"], c["extrinsics"]
    w = QtWidgets.QFrame()
    w.setObjectName("subtle")
    lay = QtWidgets.QVBoxLayout(w)
    lay.setContentsMargins(14, 10, 14, 12)
    src = label(c["name"], sel=True)
    src.setStyleSheet(f"font-family: {MONO}; font-size: 9.5pt;")
    lay.addWidget(hbox(src, label(c.get("method", ""), "small"), stretch_at=1))
    cols = QtWidgets.QHBoxLayout()
    cols.setSpacing(30)
    left = QtWidgets.QVBoxLayout()
    left.addWidget(label("INTRINSICS", "caps"))
    size = f"{i['image_size'][0]} × {i['image_size'][1]}" if i.get("image_size") else "–"
    left.addWidget(value_grid([("fx (px)", core.fmt(i["fx"])), ("fy (px)", core.fmt(i["fy"])), ("image size", size),
                               ("cx (px)", core.fmt(i["cx"])), ("cy (px)", core.fmt(i["cy"])), ("distortion", i["model"]),
                               ("k1", core.fmt(i["k1"], 8)), ("k2", core.fmt(i["k2"], 8)),
                               ("k3", core.fmt(i.get("k3", 0), 8)), ("k4", core.fmt(i.get("k4", 0), 8))]))
    if i.get("k3") or i.get("k4"):
        left.addWidget(label("Checks use all four coefficients; refinement keeps k3 and k4 fixed.", "small", wrap=True))
    left.addStretch(1)
    right = QtWidgets.QVBoxLayout()
    right.addWidget(label("EXTRINSICS  (LIDAR → CAMERA)", "caps"))
    right.addWidget(label("Mounting: " + e["mounting_label"], "muted", wrap=True))
    right.addWidget(value_grid([("t x (mm)", core.fmt(e["tx"], 1)), ("t y (mm)", core.fmt(e["ty"], 1)), ("t z (mm)", core.fmt(e["tz"], 1)),
                                ("tilt (°)", core.fmt(e["tilt"], 3)), ("pan (°)", core.fmt(e["pan"], 3)), ("roll (°)", core.fmt(e["roll"], 3))]))
    right.addStretch(1)
    cols.addLayout(left, 1)
    sep = QtWidgets.QFrame()
    sep.setFrameShape(QtWidgets.QFrame.VLine)
    sep.setStyleSheet(f"color: {LINE};")
    cols.addWidget(sep)
    cols.addLayout(right, 1)
    lay.addLayout(cols)
    mat = label("\n".join("  ".join(f"{x:>10.6f}" for x in row) for row in e["matrix"]), sel=True)
    mat.setStyleSheet(f"font-family: {MONO}; font-size: 9pt; color: {INK2};")
    mat.hide()
    tog = button("Show 4 × 4 matrix", "link")
    tog.clicked.connect(lambda: (mat.setVisible(not mat.isVisible()),
                                 tog.setText("Hide 4 × 4 matrix" if mat.isVisible() else "Show 4 × 4 matrix")))
    lay.addWidget(hbox(tog, stretch_at=1))
    lay.addWidget(mat)
    return w


class ManualDialog(QtWidgets.QDialog):
    """Type the previous calibration in: intrinsics, and extrinsics as mounting + angles or a 4 x 4 matrix."""

    def __init__(self, parent, prefill=None):
        super().__init__(parent)
        self.setWindowTitle("Enter the previous calibration")
        self.path = None
        lay = QtWidgets.QVBoxLayout(self)
        lay.setSpacing(12)
        num = QtGui.QDoubleValidator()
        num.setNotation(QtGui.QDoubleValidator.ScientificNotation)
        self.f = {}

        def field(key, default=""):
            le = QtWidgets.QLineEdit(default)
            le.setValidator(num)
            self.f[key] = le
            return le

        intr = QtWidgets.QGroupBox("Intrinsics (OpenCV fisheye, pixels)")
        g = QtWidgets.QGridLayout(intr)
        for k, (key, name) in enumerate((("fx", "fx"), ("fy", "fy"), ("cx", "cx"), ("cy", "cy"), ("k1", "k1"), ("k2", "k2"),
                                          ("k3", "k3"), ("k4", "k4"),
                                          ("width", "image width (optional)"), ("height", "image height (optional)"))):
            g.addWidget(label(name, "small"), (k // 4) * 2, k % 4)
            g.addWidget(field(key, "0" if key in ("k1", "k2", "k3", "k4") else ""), (k // 4) * 2 + 1, k % 4)
        lay.addWidget(intr)

        ext = QtWidgets.QGroupBox("Extrinsics (LiDAR → camera: p_cam = R · p_lidar + t)")
        el = QtWidgets.QVBoxLayout(ext)
        self.tabs = QtWidgets.QTabWidget()
        ang = QtWidgets.QWidget()
        al = QtWidgets.QGridLayout(ang)
        self.mount = QtWidgets.QComboBox()
        for k, M in enumerate(core.MOUNTINGS):
            self.mount.addItem(core.mounting_label(M), k)
        al.addWidget(label("Mounting (how the camera sits on the LiDAR)", "small"), 0, 0, 1, 3)
        al.addWidget(self.mount, 1, 0, 1, 3)
        for k, (key, name) in enumerate((("tilt", "tilt (°, camera x)"), ("pan", "pan (°, camera y)"), ("roll", "roll (°, camera z)"),
                                          ("tx", "t x (mm)"), ("ty", "t y (mm)"), ("tz", "t z (mm)"))):
            al.addWidget(label(name, "small"), 2 + (k // 3) * 2, k % 3)
            al.addWidget(field(key, "0"), 3 + (k // 3) * 2, k % 3)
        self.tabs.addTab(ang, "Mounting + angles")
        self.matrix = QtWidgets.QPlainTextEdit()
        self.matrix.setPlaceholderText("r11 r12 r13 tx\nr21 r22 r23 ty\nr31 r32 r33 tz\n0   0   0   1        (t in metres or millimetres)")
        self.matrix.setStyleSheet(f"font-family: {MONO};")
        self.tabs.addTab(self.matrix, "4 × 4 matrix")
        el.addWidget(self.tabs)
        lay.addWidget(ext)

        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.button(QtWidgets.QDialogButtonBox.Ok).setText("Use these values")
        bb.button(QtWidgets.QDialogButtonBox.Ok).setObjectName("primary")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        if prefill:
            i, e = prefill["intrinsics"], prefill["extrinsics"]
            for k in ("fx", "fy", "cx", "cy", "k1", "k2", "k3", "k4"):
                self.f[k].setText(f"{i.get(k, 0):.12g}")
            if i.get("image_size"):
                self.f["width"].setText(str(i["image_size"][0]))
                self.f["height"].setText(str(i["image_size"][1]))
            self.mount.setCurrentIndex(e["mounting"])
            for k in ("tilt", "pan", "roll"):
                self.f[k].setText(f"{e[k]:.12g}")
            for k in ("tx", "ty", "tz"):
                self.f[k].setText(f"{e[k]:.12g}")
            self.matrix.setPlainText("\n".join("  ".join(f"{x:.17g}" for x in row) for row in e["matrix"]))
        self.resize(640, 0)

    def accept(self):
        v = {k: le.text() for k, le in self.f.items()}
        v.update(mounting=self.mount.currentData(), matrix=self.matrix.toPlainText(),
                 ext_mode="matrix" if self.tabs.currentIndex() == 1 else "angles")
        try:
            self.path = core.manual_calibration(v)
        except ValueError as err:
            QtWidgets.QMessageBox.warning(self, "Check the values", str(err))
            return
        super().accept()



def clear(layout):
    while layout.count():
        it = layout.takeAt(0)
        if it.widget():
            it.widget().hide()                       # gone at once; deleted when the event loop runs
            it.widget().deleteLater()
        elif it.layout():
            clear(it.layout())
