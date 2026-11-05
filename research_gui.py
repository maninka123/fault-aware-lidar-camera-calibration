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
import re
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
from ui_common import ManualDialog, np_to_pixmap  # noqa: E402

NUM = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
CAL_FILTER = "Calibration files (*.json *.txt);;JSON (*.json);;Text (*.txt);;All files (*)"


def maintenance_text_to_calibration(p, text):
    """The .txt the maintenance app exports (format = calibration-maintenance-v1, INI-like sections)."""
    sections, cur = {}, None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            cur = sections.setdefault(line[1:-1], {})
        elif cur is not None and "=" in line:
            k, v = line.split("=", 1)
            cur[k.strip()] = v.strip()
    try:
        K = [core.numbers(sections["camera_matrix"][f"row_{i}"]) for i in (1, 2, 3)]
        T = [core.numbers(sections["transform_lidar_to_camera"][f"row_{i}"]) for i in (1, 2, 3, 4)]
        D = core.numbers(sections.get("distortion_coefficients", {}).get("values", ""))
    except KeyError as err:
        raise ValueError(f"The calibration text is missing {err.args[0]}.") from None
    if any(len(r) != 3 for r in K) or any(len(r) != 4 for r in T):
        raise ValueError("camera_matrix rows need 3 numbers and the transform rows need 4.")
    meta = {}
    try:
        meta = json.loads(sections.get("metadata", {}).get("json", "{}"))
    except ValueError:
        pass
    if sections.get("calibration", {}).get("translation_unit", "metres").startswith("mill"):
        for r in T[:3]:
            r[3] /= 1000.0
    c = dict(method=f"imported from {p.name} (maintenance export)",
             convention="p_camera = R @ p_lidar + t (metres); OpenCV fisheye model",
             intrinsics=dict(distortion_model=(meta.get("intrinsics") or {}).get("distortion_model", "k1-k2-k3-k4"),
                             camera_matrix=K, distortion_coefficients=(D + [0.0] * 4)[:4]),
             extrinsics=dict(transform_lidar_to_camera=T))
    if meta.get("image_size"):
        c["image_size"] = meta["image_size"]
    dst = core.INPUTS / f"imported_{datetime.now():%Y%m%d_%H%M%S_%f}.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(c, indent=2), encoding="utf-8")
    return str(dst)


def text_to_calibration(path):
    """intrinsics.txt / extrinsics.txt (as written by the targetless pipeline) -> a calibration.json path.

    Select either file; the sibling is found beside it. One text file that holds both (fx.. keys plus a
    3x4 / 4x4 matrix) also works. Translation is read as metres, or millimetres when |t| > 20.
    """
    p = Path(path)
    texts = [p.read_text(encoding="utf-8", errors="replace")]
    if "[camera_matrix]" in texts[0] and "[transform_lidar_to_camera]" in texts[0]:
        return maintenance_text_to_calibration(p, texts[0])
    for sib in ("intrinsics.txt", "extrinsics.txt"):
        s = p.with_name(sib)
        if s != p and s.is_file():
            texts.append(s.read_text(encoding="utf-8", errors="replace"))
    joined = "\n".join(texts)
    vals = {}
    for k in ("fx", "fy", "cx", "cy", "k1", "k2"):
        m = re.search(rf"^\s*{k}\s*[:=]?\s*({NUM})\s*$", joined, re.M | re.I)
        if m:
            vals[k] = m.group(1)
    missing = [k for k in ("fx", "fy", "cx", "cy") if k not in vals]
    rows = []
    for text in texts:
        lines = text.splitlines()
        head = next((i for i, l in enumerate(lines) if re.search(r"T_lidar_to_camera", l, re.I)), None)
        cand = lines[head + 1:] if head is not None else (lines if "fx" not in text else [])
        found = []
        for line in cand:
            if line.lstrip().startswith("#") or re.match(r"\s*[A-Za-z]", line):
                if found:
                    break
                continue
            n = core.numbers(line)
            if len(n) == 4:
                found.append(n)
            elif found:
                break
        if len(found) >= 3:
            rows = found
            break
    if missing or len(rows) < 3:
        need = []
        if missing:
            need.append("intrinsics (" + ", ".join(missing) + " missing; keep intrinsics.txt beside the file)")
        if len(rows) < 3:
            need.append("a 3x4 or 4x4 LiDAR → camera matrix (keep extrinsics.txt beside the file)")
        raise ValueError("This text file is not a complete calibration. It needs " + " and ".join(need) + ".")
    size = re.search(r"image\s+(\d+)\s*[x×]\s*(\d+)", joined, re.I) or re.search(
        r"image_width\s+(\d+)[\s\S]*?image_height\s+(\d+)", joined, re.I)
    v = dict(vals, ext_mode="matrix", matrix="\n".join(" ".join(map(repr, r)) for r in rows[:4]))
    if size:
        v.update(width=size.group(1), height=size.group(2))
    dst = Path(core.manual_calibration(v))
    c = json.loads(dst.read_text(encoding="utf-8"))
    c["method"] = f"imported from {p.name} (text)"
    dst.write_text(json.dumps(c, indent=2), encoding="utf-8")
    return str(dst)


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
QFrame#sidebar {{ background: #efeff3; border-right: 1px solid {LINE}; }}
QListWidget#runs {{ background: transparent; border: none; outline: none; }}
QListWidget#runs::item {{ padding: 10px 8px; border-radius: 10px; margin: 2px 2px; }}
QListWidget#runs::item:hover {{ background: #f3f5f8; }}
QListWidget#runs::item:selected {{ background: #dceaff; color: {INK}; }}
QCheckBox {{ spacing: 8px; }}
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


class CalibrationDialog(QtWidgets.QDialog):
    """Read-only view of a calibration's values (HIG sizes: 14 px values, 12 px captions)."""

    def __init__(self, parent, info, shown):
        super().__init__(parent)
        self.setWindowTitle("Calibration values")
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(16)
        lay.addWidget(label(f"{Path(shown).parent.name}/{Path(shown).name}", "headline"))
        if info.get("method"):
            lay.addWidget(label(info["method"], "footnote"))
        i, e = info["intrinsics"], info["extrinsics"]
        size = f"{i['image_size'][0]} × {i['image_size'][1]}" if i.get("image_size") else "–"
        lay.addWidget(self.group("Intrinsics", [
            ("fx (px)", core.fmt(i["fx"])), ("fy (px)", core.fmt(i["fy"])), ("Image size", size),
            ("cx (px)", core.fmt(i["cx"])), ("cy (px)", core.fmt(i["cy"])), ("Distortion", str(i["model"])),
            ("k1", core.fmt(i["k1"], 4)), ("k2", core.fmt(i["k2"], 4)), ("", "")]))
        lay.addWidget(self.group("Extrinsics (LiDAR → camera)", [
            ("Translation x (mm)", core.fmt(e["tx"], 1)), ("Translation y (mm)", core.fmt(e["ty"], 1)),
            ("Translation z (mm)", core.fmt(e["tz"], 1)), ("Tilt (°)", core.fmt(e["tilt"], 3)),
            ("Pan (°)", core.fmt(e["pan"], 3)), ("Roll (°)", core.fmt(e["roll"], 3))],
            note="Mounting: " + e["mounting_label"]))
        mat = QtWidgets.QPlainTextEdit("\n".join("  ".join(f"{x:>11.6f}" for x in row) for row in e["matrix"]))
        mat.setReadOnly(True)
        mat.setFixedHeight(112)
        lay.addWidget(label("4 × 4 transform", "headline"))
        lay.addWidget(mat)
        close = QtWidgets.QPushButton("Done")
        close.setObjectName("primary")
        close.clicked.connect(self.accept)
        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        row.addWidget(close)
        lay.addLayout(row)
        self.setMinimumWidth(620)

    @staticmethod
    def group(title, items, note=None):
        f, lay = frame("card", (20, 16, 20, 16), 8)
        lay.addWidget(label(title, "headline"))
        if note:
            lay.addWidget(label(note, "footnote"))
        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(12)
        for k, (cap, val) in enumerate(items):
            box = QtWidgets.QVBoxLayout()
            box.setSpacing(2)
            box.addWidget(label(cap, "footnote"))
            v = label(val, wrap=False)
            v.setStyleSheet("font-size:14px; font-weight:600;")
            box.addWidget(v)
            grid.addLayout(box, k // 3, k % 3)
        lay.addLayout(grid)
        return f


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


class StepHeader(QtWidgets.QWidget):
    """Numbered badge + title + subtitle, as in the maintenance app."""

    def __init__(self, n, title, subtitle):
        super().__init__()
        self.n = n
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        self.badge = QtWidgets.QLabel()
        self.badge.setFixedSize(28, 28)
        self.badge.setAlignment(QtCore.Qt.AlignCenter)
        lay.addWidget(self.badge)
        txt = QtWidgets.QVBoxLayout()
        txt.setSpacing(0)
        txt.addWidget(label(title, "headline", wrap=False))
        txt.addWidget(label(subtitle, "footnote", wrap=False))
        lay.addLayout(txt, 1)
        self.set_done(False)

    def set_done(self, done):
        col = GOOD if done else "#c9ced6"
        self.badge.setText("✓" if done else str(self.n))
        self.badge.setStyleSheet(f"background:{col}; color:white; border-radius:14px; font-size:13px; font-weight:600;")


class Step(QtWidgets.QFrame):
    """White step card: header (+ optional link), picker row (list, 'or', buttons), summary, error, extras."""

    def __init__(self, n, title, subtitle, combo_hint, items):
        super().__init__()
        self.setObjectName("card")
        self.lay = QtWidgets.QVBoxLayout(self)
        self.lay.setContentsMargins(24, 20, 24, 20)
        self.lay.setSpacing(12)
        self.header = StepHeader(n, title, subtitle)
        self.head_row = QtWidgets.QHBoxLayout()
        self.head_row.addWidget(self.header, 1)
        self.lay.addLayout(self.head_row)
        self.combo = QtWidgets.QComboBox()
        self.combo.addItem(combo_hint, None)
        for name, path in items:
            self.combo.addItem(name, path)
        self.combo.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.combo.setMaxVisibleItems(16)
        self.row = QtWidgets.QHBoxLayout()
        self.row.setSpacing(12)
        self.row.addWidget(self.combo, 1)
        self.row.addWidget(label("or", "muted", wrap=False))
        self.lay.addLayout(self.row)
        self.summary = label("", "muted")
        self.summary.setTextFormat(QtCore.Qt.RichText)
        self.summary.hide()
        self.lay.addWidget(self.summary)
        self.error = label("", "err")
        self.error.hide()
        self.lay.addWidget(self.error)
        self.extra = QtWidgets.QVBoxLayout()
        self.lay.addLayout(self.extra)
        self.path = ""

    def add_button(self, text, slot):
        b = QtWidgets.QPushButton(text)
        b.setCursor(QtCore.Qt.PointingHandCursor)
        b.clicked.connect(slot)
        self.row.addWidget(b)
        return b

    def add_header_link(self, text, slot):
        b = QtWidgets.QPushButton(text)
        b.setObjectName("link")
        b.setCursor(QtCore.Qt.PointingHandCursor)
        b.clicked.connect(slot)
        self.head_row.addWidget(b)
        return b

    def show_error(self, msg):
        self.error.setText(msg)
        self.error.setVisible(bool(msg))

    def clear_extra(self):
        def wipe(layout):
            while layout.count():
                it = layout.takeAt(0)
                if it.widget():
                    it.widget().hide()
                    it.widget().deleteLater()
                elif it.layout():
                    wipe(it.layout())
        wipe(self.extra)


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Fault-Aware Calibration")
        self.resize(1240, 860)
        self.setMinimumSize(1000, 680)
        self.output = None
        self.process = None
        self.data = None
        self.cal_info = None
        self.result_cal = None
        self.mode = "check"

        # ---- sidebar
        side = QtWidgets.QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(256)
        sl = QtWidgets.QVBoxLayout(side)
        sl.setContentsMargins(16, 20, 12, 16)
        sl.setSpacing(10)
        sl.addWidget(label("Fault-aware<br>calibration", "title", rich=True))
        sl.addWidget(label("Camera–LiDAR · offline", "footnote"))
        sl.addSpacing(8)
        self.nav_new = QtWidgets.QPushButton("New check")
        self.nav_new.setObjectName("primary")
        self.nav_new.clicked.connect(self.show_setup)
        self.nav_open = QtWidgets.QPushButton("Open result folder…")
        self.nav_open.clicked.connect(self.open_previous)
        sl.addWidget(self.nav_new)
        sl.addWidget(self.nav_open)
        sl.addSpacing(6)
        sl.addWidget(label("CHECKS", "caps"))
        self.runs = QtWidgets.QListWidget()
        self.runs.setObjectName("runs")
        self.runs.itemClicked.connect(lambda it: self.open_run(it.data(QtCore.Qt.UserRole)))
        sl.addWidget(self.runs, 1)

        # ---- pages
        self.pages = QtWidgets.QStackedWidget()
        self.pages.addWidget(self.build_setup())
        self.pages.addWidget(self.build_run_page())
        central = QtWidgets.QWidget()
        central.setObjectName("page")
        cl = QtWidgets.QHBoxLayout(central)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(side)
        cl.addWidget(self.pages, 1)
        self.setCentralWidget(central)
        self.show_empty()
        self.refresh_runs()
        self.update_ready()

    # ---- setup page (three numbered steps, like the maintenance app's New check)
    def suggestions(self):
        try:
            sug = core.suggestions()
        except Exception:  # noqa: BLE001 - suggestions are optional
            sug = dict(calibrations=[], data=[])
        try:  # recordings of this research checkout, when present on this machine
            man = json.loads((ROOT / "research_data" / "manifest.json").read_text(encoding="utf-8"))
            base = (ROOT / man["workspace_root_relative_to_repository"]).resolve()
            seen_c = {p for _, p in sug["calibrations"]}
            seen_d = {p for _, p in sug["data"]}
            for d in man["datasets"]:
                cal = base / d["reference_calibration"]["path"]
                dat = base / d["data_directory"]
                if cal.is_file() and str(cal) not in seen_c:
                    sug["calibrations"].append((f"Reference: {d['id'].replace('_', ' ')}", str(cal)))
                if dat.is_dir() and str(dat) not in seen_d:
                    sug["data"].append((f"Stacked: {d['id'].replace('_', ' ')}", str(dat)))
        except Exception:  # noqa: BLE001
            pass
        return sug

    def build_setup(self):
        sug = self.suggestions()
        page = QtWidgets.QWidget()
        page.setObjectName("page")
        v = QtWidgets.QVBoxLayout(page)
        v.setContentsMargins(32, 28, 32, 32)
        v.setSpacing(16)
        v.addWidget(label("New check", "largeTitle", wrap=False))
        v.addWidget(label("Choose a calibration and recorded captures. We’ll check which parameters the data can "
                          "support changing, and keep your calibration unless the evidence is strong enough.", "muted"))

        self.cal = Step(1, "Existing calibration", "The camera settings and alignment in use now",
                        "Choose a suggested calibration…", sug["calibrations"])
        self.cal.combo.activated.connect(lambda k: self.cal.combo.itemData(k) and self.load_cal(self.cal.combo.itemData(k)))
        self.cal.add_button("Open file…", self.open_cal)
        self.cal.add_button("Enter values…", self.enter_cal)
        v.addWidget(self.cal)

        self.cap = Step(2, "New captures", "Image + PCD pairs, recorded bags or stacked captures",
                        "Choose a suggested capture folder…", sug["data"])
        self.cap.combo.activated.connect(lambda k: self.cap.combo.itemData(k) and self.load_data(self.cap.combo.itemData(k)))
        self.cap.add_button("Choose folder…", self.open_data)
        self.cap.add_header_link("Capture format", self.show_capture_format)
        self.pair_box = QtWidgets.QWidget()
        pl = QtWidgets.QVBoxLayout(self.pair_box)
        pl.setContentsMargins(0, 4, 0, 0)
        pl.setSpacing(8)
        self.pair_units = QtWidgets.QComboBox()
        self.pair_units.addItem("Metres (m)", "m")
        self.pair_units.addItem("Millimetres (mm)", "mm")
        self.pair_units.setMinimumWidth(180)
        self.pair_units.currentIndexChanged.connect(self.validate_paired)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(label("PCD units", "headline", wrap=False))
        row.addWidget(self.pair_units)
        row.addStretch(1)
        pl.addLayout(row)
        self.pair_status = label("", "muted")
        pl.addWidget(self.pair_status)
        self.units_confirm = QtWidgets.QCheckBox("I confirm these coordinate units")
        self.units_confirm.toggled.connect(self.update_ready)
        self.units_confirm.hide()
        pl.addWidget(self.units_confirm)
        self.pair_box.hide()
        self.cap.lay.addWidget(self.pair_box)
        v.addWidget(self.cap)

        step3, l3 = frame("card", (24, 20, 24, 20), 12)
        self.step3 = StepHeader(3, "Run the check", "Compare the possible changes, then review the verdict")
        l3.addWidget(self.step3)
        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(24)
        grid.addWidget(label("What to do", "headline", wrap=False), 0, 0)
        grid.addWidget(label("Method", "headline", wrap=False), 0, 1)
        self.mode_combo = QtWidgets.QComboBox()
        self.mode_combo.addItem("Check my existing calibration", "check")
        self.mode_combo.addItem("Calibrate from scratch (no calibration needed)", "scratch")
        self.mode_combo.currentIndexChanged.connect(self.mode_changed)
        self.strategy = QtWidgets.QComboBox()
        for name, key in STRATEGIES:
            self.strategy.addItem(name, key)
        grid.addWidget(self.mode_combo, 1, 0)
        grid.addWidget(self.strategy, 1, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        l3.addLayout(grid)
        self.run_btn = QtWidgets.QPushButton("Run check")
        self.run_btn.setObjectName("primary")
        self.run_btn.clicked.connect(self.run)
        self.hint = label("", "muted")
        r3 = QtWidgets.QHBoxLayout()
        r3.setSpacing(16)
        r3.addWidget(self.run_btn)
        r3.addWidget(self.hint, 1)
        l3.addLayout(r3)
        v.addWidget(step3)
        v.addWidget(label("Offline · reads recordings only · never writes to a device or overwrites your calibration",
                          "footnote"))
        v.addStretch(1)
        sc = QtWidgets.QScrollArea()
        sc.setWidgetResizable(True)
        sc.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        sc.setWidget(page)
        return sc

    def build_run_page(self):
        page = QtWidgets.QWidget()
        page.setObjectName("page")
        outer = QtWidgets.QVBoxLayout(page)
        outer.setContentsMargins(32, 28, 32, 20)
        outer.setSpacing(16)
        top = QtWidgets.QHBoxLayout()
        self.run_title = label("Result", "largeTitle", wrap=False)
        top.addWidget(self.run_title, 1)
        self.state = label("", "muted", wrap=False)
        top.addWidget(self.state)
        outer.addLayout(top)
        self.progress = QtWidgets.QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 1)
        outer.addWidget(self.progress)
        bar = QtWidgets.QHBoxLayout()
        self.pager = Pager(["Result", "Report", "Log"])
        bar.addWidget(self.pager)
        bar.addStretch()
        self.cal_btn = QtWidgets.QPushButton("View calibration after this check…")
        self.cal_btn.clicked.connect(self.view_result_calibration)
        self.cal_btn.hide()
        bar.addWidget(self.cal_btn)
        outer.addLayout(bar)
        self.stack = QtWidgets.QStackedWidget()
        outer.addWidget(self.stack, 1)
        self.stack.addWidget(self.build_result())
        self.stack.addWidget(self.build_report())
        self.stack.addWidget(self.build_log())
        self.pager.changed.connect(self.stack.setCurrentIndex)
        return page

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
                it.widget().hide()
                it.widget().deleteLater()

    def style_banner(self, color, soft):
        self.banner.setStyleSheet(f"QFrame{{background:{SOFT[soft]}; border:none; border-radius:16px;}}"
                                  f"QLabel{{background:transparent;}}")
        self.b_title.setStyleSheet(f"color:{color}; font-size:20px; font-weight:600;")

    # ---- navigation and history
    def show_setup(self):
        self.runs.clearSelection()
        self.pages.setCurrentIndex(0)

    def show_empty(self):
        self.run_title.setText("Result")
        self.style_banner(MUTED, "grey")
        self.b_title.setText("No result yet")
        self.b_body.setText("Start a new check, or choose an earlier one from the list.")
        self.cards_frame.hide()
        self.table_frame.hide()
        self.cal_btn.hide()

    @staticmethod
    def result_file(folder):
        folder = Path(folder)
        for p in (folder / "assessment.json", folder / "assessment" / "assessment.json"):
            if p.exists():
                return p
        return None

    @staticmethod
    def title_of(folder):
        name = Path(folder).name
        try:
            return "Check " + datetime.strptime(name[4:19], "%Y%m%d_%H%M%S").strftime("%d %b %Y, %H:%M")
        except ValueError:
            return name.replace("_", " ").capitalize()

    @staticmethod
    def dot(color, size=14):
        pm = QtGui.QPixmap(size * 2, size * 2)
        pm.fill(QtCore.Qt.transparent)
        p = QtGui.QPainter(pm)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor(color))
        p.drawEllipse(4, 4, size * 2 - 8, size * 2 - 8)
        p.end()
        return QtGui.QIcon(pm)

    def refresh_runs(self):
        current = str(self.output) if self.output else None
        self.runs.clear()
        base = ROOT / "research_artifacts"
        folders = sorted((p for p in base.glob("gui_*") if p.is_dir()), reverse=True) if base.exists() else []
        for f in folders:
            rf = self.result_file(f)
            running = self.process is not None and self.process.state() != QtCore.QProcess.NotRunning \
                and self.output is not None and Path(self.output) == f
            status, color = "stopped", MUTED
            if running:
                status, color = "running…", BLUE
            elif rf:
                try:
                    st = json.loads(rf.read_text(encoding="utf-8")).get("status", "")
                    status = STATUS.get(st, (st.replace("_", " ").lower(),))[0]
                    color = STATUS.get(st, (None, MUTED))[1]
                except (OSError, ValueError):
                    pass
            when = datetime.strptime(f.name[4:], "%Y%m%d_%H%M%S").strftime("%Y-%m-%d %H:%M") \
                if len(f.name) >= 19 else f.name
            it = QtWidgets.QListWidgetItem(self.dot(color), f"{when}\n{status}")
            it.setData(QtCore.Qt.UserRole, str(f))
            it.setToolTip(str(f))
            self.runs.addItem(it)
            if current and str(f) == current:
                it.setSelected(True)

    def open_run(self, folder):
        folder = Path(folder)
        self.output = folder
        if self.result_file(folder):
            self.load(folder)
        else:
            self.fail("This check has no result. It may have stopped before finishing.")
        self.pages.setCurrentIndex(1)

    def open_previous(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose a result folder (contains assessment.json)",
                                                       str(ROOT / "research_artifacts"))
        if not d:
            return
        if self.result_file(d):
            self.open_run(d)
        else:
            self.warn("That folder has no assessment.json.")

    def warn(self, msg):
        QtWidgets.QMessageBox.information(self, "Missing input", msg)

    # ---- step 1: existing calibration (json, text, typed values, suggestions)
    def load_cal(self, path):
        shown = Path(path)
        try:
            if shown.suffix.lower() != ".json":
                path = text_to_calibration(path)
            info = core.calibration_info(path)
        except (ValueError, KeyError, TypeError, OSError) as err:
            self.cal.path = ""
            self.cal.summary.hide()
            self.cal.clear_extra()
            self.cal.show_error(str(err))
            return self.update_ready()
        self.cal.show_error("")
        self.cal.path = info["path"]
        self.cal_info = info
        i = info["intrinsics"]
        size = f" · {i['image_size'][0]}×{i['image_size'][1]}" if i.get("image_size") else ""
        self.cal.summary.setText(f"<b>{shown.parent.name}/{shown.name}</b><br>fx {core.fmt(i['fx'])} · "
                                 f"fy {core.fmt(i['fy'])}{size} · {info['extrinsics']['mounting_label']}")
        self.cal.summary.show()
        self.cal.clear_extra()
        link = QtWidgets.QPushButton("View all values…")
        link.setObjectName("link")
        link.setCursor(QtCore.Qt.PointingHandCursor)
        link.clicked.connect(lambda: CalibrationDialog(self, info, shown).exec_())
        row = QtWidgets.QHBoxLayout()
        row.addWidget(link)
        row.addStretch(1)
        self.cal.extra.addLayout(row)
        self.update_ready()

    def open_cal(self):
        start = str(Path(self.cal.path).parent) if self.cal.path else str(core.PROJECT)
        p, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Existing calibration", start, CAL_FILTER)
        if p:
            self.cal.combo.setCurrentIndex(0)
            self.load_cal(p)

    def enter_cal(self):
        d = ManualDialog(self, self.cal_info if self.cal.path else None)
        if d.exec_() == QtWidgets.QDialog.Accepted:
            self.cal.combo.setCurrentIndex(0)
            self.load_cal(d.path)

    # ---- step 2: captures (image + PCD pairs, raw bags, stacked)
    def load_data(self, path):
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            info = core.inspect_data(path)
        except (ValueError, OSError) as err:
            self.data, self.cap.path = None, ""
            self.cap.summary.hide()
            self.cap.clear_extra()
            self.pair_box.hide()
            self.cap.show_error(str(err))
            QtWidgets.QApplication.restoreOverrideCursor()
            return self.update_ready()
        self.data = info
        self.cap.show_error("")
        self.cap.path = info["path"]
        kind = {"raw": "raw captures, decoded during the check", "stacked": "stacked captures",
                "paired": "image + PCD pairs"}[info["kind"]]
        self.cap.summary.setText(f"<b>{len(info['captures'])} {kind}</b> &nbsp; "
                                 f"<span style='color:{MUTED}'>{Path(info['path']).name}</span>")
        self.cap.summary.show()
        self.cap.clear_extra()
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(12)
        for c in info["captures"][:6]:
            box = QtWidgets.QVBoxLayout()
            box.setSpacing(2)
            thumb = QtWidgets.QLabel()
            thumb.setFixedSize(120, 90)
            thumb.setAlignment(QtCore.Qt.AlignCenter)
            src = c.get("npz") or c.get("image")
            try:
                if not src:
                    raise ValueError
                pm = np_to_pixmap(core.capture_image(src)).scaled(120, 90, QtCore.Qt.KeepAspectRatio,
                                                                 QtCore.Qt.SmoothTransformation)
                thumb.setPixmap(pm)
            except Exception:  # noqa: BLE001 - raw bags and unreadable images get a placeholder
                thumb.setText(f"raw bag\n{c['size_mb']:.0f} MB" if c.get("size_mb") else "no preview")
                thumb.setStyleSheet(f"background:{SOFT['grey']}; border-radius:8px; color:{MUTED}; font-size:12px;")
            box.addWidget(thumb)
            name = str(c["name"]).replace("capture_", "").replace("_enclosure_on", "").replace("_enclosure_off", "")
            box.addWidget(label(name[:22], "footnote", wrap=False))
            row.addLayout(box)
        row.addStretch(1)
        holder = QtWidgets.QWidget()
        holder.setLayout(row)
        holder.setMinimumHeight(122)
        self.cap.extra.addWidget(holder)
        self.pair_box.setVisible(info["kind"] == "paired")
        QtWidgets.QApplication.restoreOverrideCursor()
        if info["kind"] == "paired":
            self.validate_paired()
        else:
            self.update_ready()

    def open_data(self):
        p = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose captures folder", self.cap.path or str(ROOT))
        if p:
            self.cap.combo.setCurrentIndex(0)
            self.load_data(p)

    def validate_paired(self):
        if not self.data or self.data["kind"] != "paired":
            return
        from paired_data import validate_pairs
        from settings import load_config
        self.data.pop("paired_validation", None)
        self.units_confirm.setChecked(False)
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            checked = validate_pairs(self.data["path"], self.pair_units.currentData(),
                                     load_config()["decision"]["probe_range_m"])
            self.data["paired_validation"] = checked
            self.units_confirm.setVisible(checked["units_review"])
            if checked["units_review"]:
                text, color = next(r["message"] for r in checked["reports"] if r["units_review"]), WARN
            elif not checked["analysis_usable"]:
                lo, hi = checked["probe_range_m"]
                text, color = f"Too few points at {lo:g}–{hi:g} m. Check units or use nearer scene structure.", BAD
            else:
                med = sorted(r["median_range_m"] for r in checked["reports"])[len(checked["reports"]) // 2]
                text, color = f"{len(checked['captures'])} pairs checked · files readable · typical range {med:.2f} m", GOOD
        except (ValueError, OSError) as err:
            text, color = str(err), BAD
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        self.pair_status.setText(text)
        self.pair_status.setStyleSheet(f"color:{color};")
        self.update_ready()

    def show_capture_format(self):
        from capture_help import CaptureFormatDialog
        CaptureFormatDialog(self).exec_()

    # ---- step 3
    def mode_changed(self):
        self.mode = self.mode_combo.currentData()
        scratch = self.mode == "scratch"
        self.cal.setEnabled(not scratch)
        self.strategy.setEnabled(not scratch)
        self.run_btn.setText("Calibrate" if scratch else "Run check")
        self.update_ready()

    def update_ready(self):
        if not hasattr(self, "run_btn"):
            return
        scratch = self.mode == "scratch"
        self.cal.header.set_done(bool(self.cal.path) and not scratch)
        self.cap.header.set_done(bool(self.cap.path))
        reason = ""
        if not scratch and not self.cal.path:
            reason = "Choose an existing calibration to continue."
        elif not self.cap.path:
            reason = "Choose a captures folder to continue."
        elif self.data and self.data["kind"] == "paired":
            checked = self.data.get("paired_validation")
            if scratch:
                reason = "Calibrating from scratch needs stacked or raw captures, not image + PCD pairs."
            elif not checked or not checked["analysis_usable"]:
                reason = "Fix the image + PCD pair problems above to continue."
            elif checked["units_review"] and not self.units_confirm.isChecked():
                reason = "Confirm the PCD coordinate units to continue."
        self.run_btn.setEnabled(not reason and not self.is_running())
        self.hint.setText(reason or ("Takes about 10 minutes. Nothing is written to a device." if scratch
                                      else "Takes a few minutes. Nothing is written to a device."))
        self.step3.set_done(False)

    def is_running(self):
        return self.process is not None and self.process.state() != QtCore.QProcess.NotRunning

    # ---- running
    def run(self):
        scratch = self.mode == "scratch"
        self.output = ROOT / "research_artifacts" / datetime.now().strftime("gui_%Y%m%d_%H%M%S")
        self.log.clear()
        self.run_btn.setEnabled(False)
        self.progress.setRange(0, 0)
        self.run_title.setText("Calibrating from scratch" if scratch else "Checking calibration")
        self.state.setText("Running…")
        self.style_banner(BLUE, "blue")
        self.b_title.setText("Running…")
        self.b_body.setText("This can take a few minutes. Open the Log tab to follow it." if not scratch else
                            "Estimating a new calibration, then checking it. This takes about 10 minutes.")
        self.cards_frame.hide()
        self.table_frame.hide()
        self.cal_btn.hide()
        self.tiles_clear()
        self.pager.select(0)
        self.pages.setCurrentIndex(1)
        args = ["initialize", "--captures", self.cap.path] if scratch else [
            "assess", "--calibration", self.cal.path, "--captures", self.cap.path,
            "--strategy", self.strategy.currentData()]
        args += ["--output", str(self.output)]
        if self.data and self.data["kind"] == "paired":
            args += ["--cloud-units", self.pair_units.currentData()]
            if self.units_confirm.isChecked():
                args.append("--confirm-cloud-units")
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
        p.errorOccurred.connect(lambda e: self.fail("Could not start the check."))
        exe = Path(sys.executable)
        if exe.name.lower() == "pythonw.exe":
            exe = exe.with_name("python.exe")
        self.process = p
        p.start(str(exe), ["-X", "utf8", "-B", "-W", "ignore::RuntimeWarning", "-m", "research_calibration"] + args)
        self.refresh_runs()

    def tiles_clear(self):
        self.clear(self.tiles)

    def read_output(self):
        t = bytes(self.process.readAllStandardOutput()).decode("utf-8", errors="replace").rstrip()
        if t:
            self.log.appendPlainText(t)

    def finished_run(self, code, *_):
        self.read_output()
        self.progress.setRange(0, 1)
        self.update_ready()
        if code == 0 and self.result_file(self.output):
            self.load(self.output)
        else:
            lines = [l for l in self.log.toPlainText().splitlines() if l.strip()]
            self.fail("The check stopped, and your calibration is unchanged. "
                      + (lines[-1] if lines else "See the Log tab."))
        self.refresh_runs()

    def fail(self, msg):
        self.progress.setRange(0, 1)
        self.update_ready()
        self.state.setText("Stopped")
        self.run_title.setText("Check stopped")
        self.style_banner(BAD, "bad")
        self.b_title.setText("Could not finish")
        self.b_body.setText(msg)
        self.cards_frame.hide()
        self.table_frame.hide()
        self.cal_btn.hide()
        self.tiles_clear()

    def view_result_calibration(self):
        try:
            info = core.describe(self.result_cal)
            info["name"] = "result"
        except (KeyError, ValueError, TypeError):
            return self.warn("This result has no readable calibration.")
        CalibrationDialog(self, info, self.output).exec_()

    # ---- presenting results
    def load(self, folder):
        try:
            r = json.loads(self.result_file(folder).read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            return self.fail(f"Could not read the result: {e}")
        diag = r.get("diagnostics") or {}
        dec = diag.get("decision") or {}
        status = r.get("status", "")
        title, color, soft, meaning = STATUS.get(status, (status.replace("_", " ").capitalize(), MUTED, "grey", ""))
        self.state.setText("Finished")
        self.run_title.setText(self.title_of(folder))
        self.result_cal = r.get("updated_calibration") if isinstance(r.get("updated_calibration"), dict) else None
        self.cal_btn.setVisible(bool(self.result_cal))
        self.cal_btn.setText("View calibration produced…" if status == "INITIAL_CALIBRATION_CANDIDATE"
                             else "View calibration after this check…")
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
            ("Uncertainty", "Limited" if "INSUFFICIENT" in str(unc.get("status", "")) else str(unc.get("status", "–")).replace("_", " ").capitalize(),
             f"{unc.get('clusters', '?')} capture clusters"),
        ]
        if status == "INITIAL_CALIBRATION_CANDIDATE":
            init = diag.get("initialization") or {}
            tiles = [
                ("Estimate", "Unvalidated", "Needs independent review"),
                ("Self-check label", str(init.get("inherited_heuristic_label") or "–").title(),
                 "Heuristic from the initializer"),
                ("Validation", "None", "All captures were used to estimate"),
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

        md = self.result_file(folder).with_name("report.md")
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
    if args and MainWindow.result_file(args[0]):
        win.open_run(args[0])
    win.resize(1240, 1700 if "--tall" in sys.argv else 860)
    win.show()
    if shot:  # offscreen screenshot for visual checks
        win.pager.select(int(next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--tab=")), "0")))
        QtCore.QTimer.singleShot(500, lambda: (win.grab().save(shot), app.quit()))
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
