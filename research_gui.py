"""Fault-aware calibration - desktop app.

Visual language follows the Calibration maintenance app (soft grey page, white 16 px cards,
tinted verdict banner, option cards, metric tiles) with Apple HIG type scale in px:
Large Title 28, Title 20, Headline 15 semibold, Body 14, Callout 13, Footnote 12 (minimum),
metric numerals 30. 8 px spacing grid.

Runs the offline `research_calibration` CLI in a child process. Read-only: never writes to a
device and never overwrites the input calibration.
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

for _n in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_n, "1")
from PyQt5 import QtCore, QtGui, QtWidgets  # noqa: E402

ROOT = Path(__file__).resolve().parent
# Reuse the maintenance app's calibration loading, suggestions, entry dialog and viewer.
sys.path.insert(0, str(ROOT / "Calibration maintenance" / "code"))
import appcore as core  # noqa: E402  (sets BLAS thread limits before numpy loads)
from ui_common import ManualDialog, calibration_view  # noqa: E402

STRATEGIES = [
    ("Fault-aware (recommended)", "fault_aware"),
    ("Joint optimisation", "joint"),
    ("No observability gating", "no_observability"),
    ("No capture selection", "no_selection"),
    ("Single association gate", "single_variant"),
    ("Legacy optimiser", "legacy_optimizer"),
    ("Original workflow", "legacy"),
]
FONT = '"SF Pro Text", "Segoe UI Variable Text", "Segoe UI", "Helvetica Neue", Arial'
MONO = '"SF Mono", "Cascadia Mono", Consolas, monospace'

BLUE, GOOD, WARN, BAD = "#007aff", "#248a3d", "#9b6500", "#d70015"
SOFT = dict(blue="#edf5ff", good="#eaf6ed", warn="#fff6e5", bad="#fff0f1", grey="#eeeef2")
INK, MUTED, LINE, BG = "#1d1d1f", "#6e6e73", "#e5e5ea", "#f5f5f7"

# status -> (headline, colour, soft tint, explanation)
STATUS = {
    "KEEP_CURRENT": ("Keep the current calibration", GOOD, "good",
                     "No update is supported by the evidence. Your calibration is unchanged."),
    "UPDATE_SUPPORTED": ("Update supported", BLUE, "blue",
                         "A validated candidate exists. Review it before using it."),
    "INSUFFICIENT_EVIDENCE": ("Not enough evidence", WARN, "warn",
                              "The data cannot decide between explanations. Your calibration is unchanged."),
    "INVALID_OR_UNRELIABLE_DATA": ("Data unreliable", BAD, "bad",
                                   "The inputs failed checks. Your calibration is unchanged."),
    "INITIAL_CALIBRATION_CANDIDATE": ("Initial candidate", WARN, "warn",
                                      "Unvalidated starting calibration. Needs independent review."),
}
HYPOTHESES = {"KEEP": "Keep current", "R": "Rotation", "T": "Translation", "I": "Camera intrinsics",
              "RT": "Rotation + translation", "RI": "Rotation + intrinsics", "TI": "Translation + intrinsics",
              "RTI": "Everything"}
PARAM_NAMES = {"wx": "Rotation x", "wy": "Rotation y", "wz": "Rotation z", "tx": "Translation x",
               "ty": "Translation y", "tz": "Translation z", "fx": "Focal length fx", "fy": "Focal length fy",
               "cx": "Principal point cx", "cy": "Principal point cy", "k1": "Distortion k1",
               "k2": "Distortion k2", "beam": "Beam offset"}

QSS = f"""
* {{ font-family: {FONT}; font-size: 14px; color: {INK}; }}
QMainWindow, QWidget#page {{ background: {BG}; }}
QScrollArea {{ border: none; background: transparent; }}
QLabel {{ background: transparent; }}
QLabel#largeTitle {{ font-size: 28px; font-weight: 700; }}
QLabel#title {{ font-size: 20px; font-weight: 600; }}
QLabel#headline {{ font-size: 15px; font-weight: 600; }}
QLabel#muted {{ font-size: 13px; color: {MUTED}; }}
QLabel#footnote {{ font-size: 12px; color: {MUTED}; }}
QLabel#metric {{ font-size: 30px; font-weight: 500; }}
QFrame#card {{ background: white; border: 1px solid {LINE}; border-radius: 16px; }}
QFrame#source {{ background: {SOFT['grey']}; border: 1px solid {LINE}; border-radius: 12px; }}
QFrame#option {{ background: white; border: 1px solid {LINE}; border-radius: 12px; }}
QFrame#optionBest {{ background: white; border: 2px solid {BLUE}; border-radius: 12px; }}
QLabel#err {{ color: {BAD}; background: {SOFT['bad']}; border-radius: 6px; padding: 6px 10px; font-size: 13px; }}
QLabel#small {{ font-size: 12px; color: {MUTED}; }}
QLabel#caps {{ font-size: 12px; font-weight: 600; color: {MUTED}; }}
QLabel#h3 {{ font-size: 14px; font-weight: 600; }}
QFrame#subtle {{ background: #f8f9fb; border: 1px solid {LINE}; border-radius: 8px; }}
QDialog {{ background: {BG}; }}
QGroupBox {{ background: white; border: 1px solid {LINE}; border-radius: 12px; margin-top: 16px; padding: 16px 12px 12px; font-weight: 600; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 4px; }}
QTabBar::tab {{ padding: 6px 16px; border-radius: 8px; color: {MUTED}; }}
QTabBar::tab:selected {{ background: #e9e9ee; color: {INK}; }}
QFrame#tile {{ background: white; border: 1px solid {LINE}; border-radius: 12px; }}
QPushButton {{ background: white; border: 1px solid #dcdce2; border-radius: 9px; padding: 0 16px;
    min-height: 36px; font-weight: 600; }}
QPushButton:hover {{ background: #f8f8fa; border-color: #bdbdc5; }}
QPushButton:disabled {{ color: #a0a6ae; }}
QPushButton#primary {{ background: {BLUE}; color: white; border-color: {BLUE}; min-height: 40px;
    padding: 0 32px; font-size: 15px; }}
QPushButton#primary:hover {{ background: #1686ff; border-color: #1686ff; }}
QPushButton#primary:disabled {{ background: #a9c7ec; border-color: #a9c7ec; color: white; }}
QPushButton#link {{ border: none; background: transparent; color: {BLUE}; padding: 0 4px; min-height: 24px; }}
QPushButton#seg {{ background: transparent; border: none; color: {MUTED}; border-radius: 8px;
    min-height: 32px; padding: 0 24px; }}
QPushButton#seg:checked {{ background: white; color: {INK}; }}
QFrame#segbar {{ background: #e9e9ee; border-radius: 10px; }}
QComboBox, QLineEdit {{ background: white; border: 1px solid #dcdce2; border-radius: 9px; padding: 0 12px;
    min-height: 36px; selection-background-color: {BLUE}; }}
QComboBox:focus, QLineEdit:focus {{ border: 2px solid {BLUE}; }}
QComboBox::drop-down {{ border: none; width: 28px; }}
QComboBox QAbstractItemView {{ background: white; border: 1px solid {LINE}; selection-background-color: {BLUE};
    selection-color: white; outline: none; }}
QPlainTextEdit, QTextBrowser {{ background: white; border: 1px solid {LINE}; border-radius: 12px; padding: 12px; }}
QPlainTextEdit {{ font-family: {MONO}; font-size: 13px; }}
QTableWidget {{ background: white; border: none; gridline-color: transparent; }}
QTableWidget::item {{ padding: 4px 12px; border-bottom: 1px solid {LINE}; }}
QHeaderView::section {{ background: white; color: {MUTED}; border: none; border-bottom: 1px solid {LINE};
    padding: 8px 12px; font-size: 12px; font-weight: 600; }}
QProgressBar {{ background: #e9e9ee; border: none; border-radius: 2px; max-height: 4px; min-height: 4px; }}
QProgressBar::chunk {{ background: {BLUE}; border-radius: 2px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{ background: #c9c9d0; border-radius: 5px; min-height: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
"""


def label(text="", name=None, wrap=True, rich=False):
    w = QtWidgets.QLabel(text)
    if name:
        w.setObjectName(name)
    w.setWordWrap(wrap)
    if rich:
        w.setTextFormat(QtCore.Qt.RichText)
    return w


def frame(name, margins=(24, 24, 24, 24), spacing=16):
    f = QtWidgets.QFrame()
    f.setObjectName(name)
    lay = QtWidgets.QVBoxLayout(f)
    lay.setContentsMargins(*margins)
    lay.setSpacing(spacing)
    return f, lay


def fmt(v):
    if v is None:
        return "–"
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if v == 0:
            return "0"
        return f"{v:.4g}" if abs(v) < 1e4 else f"{v:.3e}"
    return str(v)


class Source(QtWidgets.QFrame):
    """Step card like the maintenance app: title, suggested-item list, link buttons, summary."""

    def __init__(self, title, subtitle, combo_hint, items, parent=None):
        super().__init__(parent)
        self.setObjectName("source")
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(8)
        lay.addWidget(label(title, "headline"))
        lay.addWidget(label(subtitle, "footnote"))
        self.combo = QtWidgets.QComboBox()
        self.combo.addItem(combo_hint, None)
        for name, path in items:
            self.combo.addItem(name, path)
        self.combo.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Fixed)
        self.combo.setMaxVisibleItems(16)
        lay.addWidget(self.combo)
        self.buttons = QtWidgets.QHBoxLayout()
        self.buttons.setSpacing(8)
        self.buttons.addStretch(1)
        lay.addLayout(self.buttons)
        self.summary = label("", "muted")
        self.summary.hide()
        lay.addWidget(self.summary)
        self.error = label("", "err")
        self.error.hide()
        lay.addWidget(self.error)
        self.extra = QtWidgets.QVBoxLayout()
        lay.addLayout(self.extra)
        self.path = ""

    def add_button(self, text, slot):
        b = QtWidgets.QPushButton(text)
        b.setObjectName("link")
        b.setCursor(QtCore.Qt.PointingHandCursor)
        b.clicked.connect(slot)
        self.buttons.insertWidget(self.buttons.count() - 1, b)
        return b

    def show_error(self, msg):
        self.error.setText(msg)
        self.error.setVisible(bool(msg))


class Pager(QtWidgets.QFrame):
    changed = QtCore.pyqtSignal(int)

    def __init__(self, names):
        super().__init__()
        self.setObjectName("segbar")
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)
        self.buttons = []
        for i, n in enumerate(names):
            b = QtWidgets.QPushButton(n)
            b.setObjectName("seg")
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, i=i: self.select(i))
            lay.addWidget(b)
            self.buttons.append(b)
        self.select(0, emit=False)

    def select(self, i, emit=True):
        for k, b in enumerate(self.buttons):
            b.setChecked(k == i)
        if emit:
            self.changed.emit(i)


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Fault-Aware Calibration")
        self.resize(1120, 820)
        self.setMinimumSize(900, 640)
        self.output = None
        self.process = None
        page = QtWidgets.QWidget()
        page.setObjectName("page")
        self.setCentralWidget(page)
        outer = QtWidgets.QVBoxLayout(page)
        outer.setContentsMargins(32, 28, 32, 20)
        outer.setSpacing(16)

        top = QtWidgets.QHBoxLayout()
        top.addWidget(label("Calibration review", "largeTitle", wrap=False), 1)
        self.state = label("Ready", "muted", wrap=False)
        top.addWidget(self.state)
        outer.addLayout(top)

        # source cards
        try:
            sug = core.suggestions()
        except Exception:  # noqa: BLE001 - suggestions are optional
            sug = dict(calibrations=[], data=[])
        # Recordings of this research checkout (research_data/manifest.json), when present on this machine.
        try:
            man = json.loads((ROOT / "research_data" / "manifest.json").read_text(encoding="utf-8"))
            base = (ROOT / man["workspace_root_relative_to_repository"]).resolve()
            seen_c = {p for _, p in sug["calibrations"]}
            seen_d = {p for _, p in sug["data"]}
            for d in man["datasets"]:
                cal = base / d["reference_calibration"]["path"]
                dat = base / d["data_directory"]
                if cal.is_file() and str(cal) not in seen_c:
                    sug["calibrations"].append((f"Reference: {d['id'].replace('_', ' ')}", str(cal)))
                    seen_c.add(str(cal))
                if dat.is_dir() and str(dat) not in seen_d:
                    sug["data"].append((f"Stacked: {d['id'].replace('_', ' ')}", str(dat)))
                    seen_d.add(str(dat))
        except Exception:  # noqa: BLE001
            pass
        src = QtWidgets.QHBoxLayout()
        src.setSpacing(8)
        src.setAlignment(QtCore.Qt.AlignTop)
        self.cal = Source("Existing calibration", "The camera settings and alignment in use now",
                          "Choose a suggested calibration…", sug["calibrations"])
        self.cap = Source("Captures", "Stacked captures (.npz) recorded with this rig",
                          "Choose a suggested capture folder…", sug["data"])
        self.cal.combo.activated.connect(lambda k: self.cal.combo.itemData(k) and self.load_cal(self.cal.combo.itemData(k)))
        self.cap.combo.activated.connect(lambda k: self.cap.combo.itemData(k) and self.load_data(self.cap.combo.itemData(k)))
        self.cal.add_button("Open file…", self.open_cal)
        self.cal.add_button("Enter values…", self.enter_cal)
        self.cap.add_button("Choose folder…", self.open_data)
        self.cal_details = None
        self.strategy = QtWidgets.QComboBox()
        for name, key in STRATEGIES:
            self.strategy.addItem(name, key)
        for w in (self.cal, self.cap):
            src.addWidget(w, 1, QtCore.Qt.AlignTop)
        outer.addLayout(src)

        self.progress = QtWidgets.QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 1)
        outer.addWidget(self.progress)

        bar = QtWidgets.QHBoxLayout()
        self.pager = Pager(["Result", "Report", "Log"])
        bar.addWidget(self.pager)
        bar.addStretch()
        bar.addWidget(label("Method", "muted", wrap=False))
        self.strategy.setMinimumWidth(220)
        bar.addWidget(self.strategy)
        self.prev_btn = QtWidgets.QPushButton("Open earlier result…")
        self.prev_btn.clicked.connect(self.open_previous)
        self.run_btn = QtWidgets.QPushButton("Run assessment")
        self.run_btn.setObjectName("primary")
        self.run_btn.clicked.connect(self.run)
        bar.addWidget(self.prev_btn)
        bar.addWidget(self.run_btn)
        outer.addLayout(bar)

        self.stack = QtWidgets.QStackedWidget()
        outer.addWidget(self.stack, 1)
        self.stack.addWidget(self.build_result())
        self.stack.addWidget(self.build_report())
        self.stack.addWidget(self.build_log())
        self.pager.changed.connect(self.stack.setCurrentIndex)
        outer.addWidget(label("Offline · reads recordings only · never writes to a device or overwrites your calibration",
                              "footnote"))
        self.show_empty()

    # ---- pages
    def build_result(self):
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        body = QtWidgets.QWidget()
        body.setObjectName("page")
        self.rlay = QtWidgets.QVBoxLayout(body)
        self.rlay.setContentsMargins(0, 0, 12, 0)
        self.rlay.setSpacing(16)
        scroll.setWidget(body)

        self.banner = QtWidgets.QFrame()
        bl = QtWidgets.QVBoxLayout(self.banner)
        bl.setContentsMargins(24, 16, 24, 16)
        bl.setSpacing(4)
        self.b_title = label("", "title")
        self.b_body = label("", "muted")
        bl.addWidget(self.b_title)
        bl.addWidget(self.b_body)
        self.rlay.addWidget(self.banner)

        self.cards_frame, cl = frame("card")
        cl.addWidget(label("Which change does the evidence support?", "headline"))
        self.cards_row = QtWidgets.QGridLayout()
        self.cards_row.setSpacing(8)
        cl.addLayout(self.cards_row)
        self.cards_note = label("", "footnote")
        cl.addWidget(self.cards_note)
        self.rlay.addWidget(self.cards_frame)

        self.tiles = QtWidgets.QHBoxLayout()
        self.tiles.setSpacing(16)
        self.rlay.addLayout(self.tiles)

        self.table_frame, tl = frame("card", spacing=8)
        tl.addWidget(label("Parameter changes", "headline"))
        self.table = QtWidgets.QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Parameter", "Data supports", "Accepted change", "Candidate change"])
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(36)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.table.setFocusPolicy(QtCore.Qt.NoFocus)
        self.table.setShowGrid(False)
        self.table.setMinimumHeight(36 * 14 + 40)
        tl.addWidget(self.table)
        tl.addWidget(label("“Accepted” is zero whenever the current calibration is kept. “Candidate” is what the "
                           "optimiser proposed before validation.", "footnote"))
        self.rlay.addWidget(self.table_frame)
        self.rlay.addStretch()
        return scroll

    def build_report(self):
        self.report = QtWidgets.QTextBrowser()
        self.report.setOpenExternalLinks(True)
        wrap = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.report)
        row = QtWidgets.QHBoxLayout()
        row.addStretch()
        self.folder_btn = QtWidgets.QPushButton("Show in folder")
        self.folder_btn.setEnabled(False)
        self.folder_btn.clicked.connect(lambda: QtGui.QDesktopServices.openUrl(
            QtCore.QUrl.fromLocalFile(str(self.output))))
        row.addWidget(self.folder_btn)
        lay.addLayout(row)
        return wrap

    def build_log(self):
        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        return self.log

    # ---- helpers
    def clear(self, layout):
        while layout.count():
            it = layout.takeAt(0)
            if it.widget():
                it.widget().deleteLater()

    def style_banner(self, color, soft):
        self.banner.setStyleSheet(f"QFrame{{background:{SOFT[soft]}; border:none; border-radius:16px;}}"
                                  f"QLabel{{background:transparent;}}")
        self.b_title.setStyleSheet(f"color:{color}; font-size:20px; font-weight:600;")

    def show_empty(self):
        self.style_banner(MUTED, "grey")
        self.b_title.setText("No result yet")
        self.b_body.setText("Choose a calibration and a captures folder, then run an assessment. "
                            "Or open an earlier result.")
        self.cards_frame.hide()
        self.table_frame.hide()

    # ---- existing calibration (same choices as the maintenance app)
    def load_cal(self, path):
        try:
            info = core.calibration_info(path)
        except (ValueError, KeyError, TypeError, OSError) as err:
            self.cal.path = ""
            return self.cal.show_error(str(err))
        self.cal.show_error("")
        self.cal.path = info["path"]
        self.cal_info = info
        i = info["intrinsics"]
        size = f" · {i['image_size'][0]}×{i['image_size'][1]}" if i.get("image_size") else ""
        p = Path(info["path"])
        self.cal.summary.setText(f"<b>{p.parent.name}/{p.name}</b><br>fx {core.fmt(i['fx'])} · fy {core.fmt(i['fy'])}{size}"
                                 f" · {info['extrinsics']['mounting_label']}")
        self.cal.summary.setTextFormat(QtCore.Qt.RichText)
        self.cal.summary.show()
        while self.cal.extra.count():
            w = self.cal.extra.takeAt(0).widget()
            if w:
                w.hide()
                w.deleteLater()
        self.cal.extra.addWidget(self.make_details_toggle(info))

    def make_details_toggle(self, info):
        box = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        toggle = QtWidgets.QPushButton("Show all values")
        toggle.setObjectName("link")
        toggle.setCursor(QtCore.Qt.PointingHandCursor)
        view = calibration_view(info)
        view.hide()
        toggle.clicked.connect(lambda: (view.setVisible(not view.isVisible()),
                                        toggle.setText("Hide values" if view.isVisible() else "Show all values")))
        row = QtWidgets.QHBoxLayout()
        row.addWidget(toggle)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addWidget(view)
        return box

    def open_cal(self):
        start = str(Path(self.cal.path).parent) if self.cal.path else str(core.PROJECT)
        p, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Existing calibration", start, "Calibration (*.json)")
        if p:
            self.cal.combo.setCurrentIndex(0)
            self.load_cal(p)

    def enter_cal(self):
        prefill = getattr(self, "cal_info", None) if self.cal.path else None
        d = ManualDialog(self, prefill)
        if d.exec_() == QtWidgets.QDialog.Accepted:
            self.cal.combo.setCurrentIndex(0)
            self.load_cal(d.path)

    # ---- captures
    def load_data(self, path):
        try:
            info = core.inspect_data(path)
        except (ValueError, OSError) as err:
            self.cap.path = ""
            return self.cap.show_error(str(err))
        self.cap.path = info["path"]
        kind = {"raw": "raw bags", "stacked": "stacked captures", "paired": "image + PCD pairs"}[info["kind"]]
        n = len(info["captures"])
        self.cap.summary.setText(f"<b>{n} {kind}</b><br>{Path(info['path']).name}")
        self.cap.summary.setTextFormat(QtCore.Qt.RichText)
        self.cap.summary.show()
        if info["kind"] != "stacked":
            self.cap.show_error("The research assessment currently needs stacked captures (.npz).")
        else:
            self.cap.show_error("")

    def open_data(self):
        p = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose captures folder", self.cap.path or str(ROOT))
        if p:
            self.cap.combo.setCurrentIndex(0)
            self.load_data(p)

    def warn(self, msg):
        QtWidgets.QMessageBox.information(self, "Missing input", msg)

    # ---- running
    def run(self):
        cal, cap = Path(self.cal.path or "."), Path(self.cap.path or ".")
        if not cal.is_file():
            return self.warn("Choose a calibration JSON file.")
        if not cap.is_dir():
            return self.warn("Choose the folder that contains your captures.")
        self.output = ROOT / "research_artifacts" / datetime.now().strftime("gui_%Y%m%d_%H%M%S")
        self.log.clear()
        self.run_btn.setEnabled(False)
        self.progress.setRange(0, 0)
        self.state.setText("Running…")
        self.style_banner(BLUE, "blue")
        self.b_title.setText("Running assessment…")
        self.b_body.setText("Comparing constrained changes. This can take a few minutes.")
        self.cards_frame.hide()
        self.table_frame.hide()
        p = QtCore.QProcess(self)
        p.setWorkingDirectory(str(ROOT))
        env = QtCore.QProcessEnvironment.systemEnvironment()
        for n in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
            env.insert(n, "1")
        env.insert("PYTHONUTF8", "1")
        env.insert("PYTHONDONTWRITEBYTECODE", "1")
        p.setProcessEnvironment(env)
        p.setProcessChannelMode(QtCore.QProcess.MergedChannels)
        p.readyReadStandardOutput.connect(self.read_output)
        p.finished.connect(self.finished_run)
        p.errorOccurred.connect(lambda e: self.fail("Could not start the assessment."))
        exe = Path(sys.executable)
        if exe.name.lower() == "pythonw.exe":
            exe = exe.with_name("python.exe")
        self.process = p
        p.start(str(exe), ["-X", "utf8", "-B", "-m", "research_calibration", "assess", "--calibration", str(cal),
                           "--captures", str(cap), "--strategy", self.strategy.currentData(),
                           "--output", str(self.output)])

    def read_output(self):
        t = bytes(self.process.readAllStandardOutput()).decode("utf-8", errors="replace").rstrip()
        if t:
            self.log.appendPlainText(t)

    def finished_run(self, code, *_):
        self.read_output()
        self.progress.setRange(0, 1)
        self.run_btn.setEnabled(True)
        if code == 0 and (self.output / "assessment.json").exists():
            self.load(self.output)
        else:
            self.fail("The assessment stopped. Your calibration is unchanged. See the Log tab.")

    def fail(self, msg):
        self.progress.setRange(0, 1)
        self.run_btn.setEnabled(True)
        self.state.setText("Stopped")
        self.style_banner(BAD, "bad")
        self.b_title.setText("Assessment stopped")
        self.b_body.setText(msg)

    def open_previous(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose a result folder (contains assessment.json)",
                                                       str(ROOT / "research_artifacts"))
        if not d:
            return
        if (Path(d) / "assessment.json").exists():
            self.output = Path(d)
            self.load(self.output)
        else:
            self.warn("That folder has no assessment.json.")

    # ---- presenting results
    def load(self, folder):
        try:
            r = json.loads((Path(folder) / "assessment.json").read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            return self.fail(f"Could not read the result: {e}")
        diag = r.get("diagnostics") or {}
        dec = diag.get("decision") or {}
        status = r.get("status", "")
        title, color, soft, meaning = STATUS.get(status, (status.replace("_", " ").capitalize(), MUTED, "grey", ""))
        self.state.setText("Finished")
        self.style_banner(color, soft)
        self.b_title.setText(title)
        reason = dec.get("reason")
        self.b_body.setText(meaning + (f" {reason}" if reason else ""))

        # hypothesis cards
        losses = dec.get("mean_losses") or {}
        diffs = dec.get("differences_vs_best") or {}
        self.clear(self.cards_row)
        keep = losses.get("KEEP")
        cand = dec.get("candidate_hypothesis")
        for i, (k, v) in enumerate(losses.items()):
            self.cards_row.addWidget(self.option_card(k, v, keep, diffs.get(k), k == cand, k == "KEEP"), i // 4, i % 4)
        for c in range(4):
            self.cards_row.setColumnStretch(c, 1)
        self.cards_frame.setVisible(bool(losses))
        self.cards_note.setText(f"{dec.get('captures', '?')} captures · held-out loss, lower is better · "
                                "percentages compare with keeping the current calibration · "
                                + str(dec.get("uncertainty_scope", "")))

        # metric tiles
        self.clear(self.tiles)
        obs = r.get("observable_parameters") or []
        outer_t = (r.get("validation") or {}).get("outer_test") or {}
        unc = r.get("uncertainty") or {}
        gain = outer_t.get("relative_gain")
        thr = (dec.get("thresholds") or {}).get("min_relative_gain")
        best = dec.get("best_relative_gain")
        tiles = [
            ("Best gain vs current", f"{best * 100:.2f} %" if best is not None else "–",
             f"Needs ≥ {thr * 100:.0f} %" if thr else ""),
            ("Outer test gain", f"{gain * 100:.2f} %" if gain is not None else "–",
             "Passed" if outer_t.get("passed") else "Not passed"),
            ("Supported directions", str(len(obs)), ", ".join(obs) if obs else "none"),
            ("Uncertainty", "Limited" if "INSUFFICIENT" in str(unc.get("status", "")) else str(unc.get("status", "–")).title(),
             f"{unc.get('clusters', '?')} capture clusters"),
        ]
        for t in tiles:
            self.tiles.addWidget(self.tile(*t), 1)

        # parameter table
        acc = r.get("parameter_updates") or {}
        cand_u = diag.get("candidate_parameter_updates") or {}
        names = list(acc) or list(cand_u)
        self.table.setRowCount(len(names))
        for i, n in enumerate(names):
            vals = [PARAM_NAMES.get(n, n), "●" if n in obs else "", fmt(acc.get(n)),
                    fmt(cand_u.get(n)) if isinstance(cand_u, dict) else "–"]
            for j, v in enumerate(vals):
                it = QtWidgets.QTableWidgetItem(v)
                if j:
                    it.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
                self.table.setItem(i, j, it)
        self.table_frame.setVisible(bool(names))

        md = Path(folder) / "report.md"
        self.report.setMarkdown(md.read_text(encoding="utf-8") if md.exists() else "_No report.md in this folder._")
        self.folder_btn.setEnabled(True)
        self.pager.select(0)

    def option_card(self, key, loss, keep, diff, best, is_keep):
        f, lay = frame("optionBest" if best else "option", (16, 16, 16, 16), 8)
        head = QtWidgets.QHBoxLayout()
        head.addWidget(label(HYPOTHESES.get(key, key), "headline"), 1)
        if best:
            tag = label("Best candidate", "footnote", wrap=False)
            tag.setStyleSheet(f"color:{WARN}; font-weight:600;")
            head.addWidget(tag)
        lay.addLayout(head)
        lay.addWidget(label(f"{loss:.4f}", "metric", wrap=False))
        if is_keep:
            lay.addWidget(label("Baseline", "footnote"))
        elif keep:
            rel = (keep - loss) / keep * 100
            col = GOOD if rel > 0 else BAD
            t = label(f"{abs(rel):.2f} % {'lower' if rel > 0 else 'higher'} loss", "footnote")
            t.setStyleSheet(f"color:{col}; font-weight:600;")
            lay.addWidget(t)
        if diff and not is_keep:
            lay.addWidget(label(f"Gap to best: {diff.get('mean', 0):.4f}", "footnote"))
        lay.addStretch()
        f.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
        f.setMinimumHeight(120)
        return f

    def tile(self, title, value, sub):
        f, lay = frame("tile", (16, 16, 16, 16), 4)
        lay.addWidget(label(title, "muted"))
        lay.addWidget(label(value, "metric", wrap=False))
        lay.addWidget(label(sub, "footnote"))
        return f


def main():
    app = QtWidgets.QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(QSS)
    win = MainWindow()
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    shot = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--shot=")), None)
    if args and (Path(args[0]) / "assessment.json").exists():
        win.output = Path(args[0])
        win.load(win.output)
    if "--tall" in sys.argv:
        win.resize(1120, 1700)
    win.show()
    if shot:  # offscreen screenshot for visual checks
        win.pager.select(int(next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--tab=")), "0")))
        QtCore.QTimer.singleShot(500, lambda: (win.grab().save(shot), app.quit()))
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
