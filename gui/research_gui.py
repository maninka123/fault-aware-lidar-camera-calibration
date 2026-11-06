"""Fault-aware calibration - desktop app.

Visual language follows the Calibration maintenance app (soft grey page, white 16 px cards,
tinted verdict banner, option cards, metric tiles) with Apple HIG type scale in px:
Large Title 28, Title 20, Headline 15 semibold, Body 14, Callout 13, Footnote 12 (minimum),
metric numerals 30. 8 px spacing grid.

Runs the offline `research_calibration` CLI in a child process. Read-only: never writes to a
device and never overwrites the input calibration.
"""
import json
import logging
import logging.handlers
import os
import re
import shutil
import sys
import traceback
from datetime import datetime
from pathlib import Path

for _n in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_n, "1")
from PyQt5 import QtCore, QtGui, QtWidgets  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]      # the repository root (this file lives in gui/)
# Reuse the maintenance app's calibration loading, suggestions, entry dialog and viewer.
sys.path.insert(0, str(ROOT / "Calibration maintenance" / "code"))
import appcore as core  # noqa: E402  (sets BLAS thread limits before numpy loads)
from ui_common import ManualDialog, np_to_pixmap  # noqa: E402
import app_icon  # noqa: E402
import result_visuals  # noqa: E402
import calibration_review  # noqa: E402
import processing_view  # noqa: E402
import report_view  # noqa: E402
import matrix_view  # noqa: E402
import review_adapter  # noqa: E402
import settings_store  # noqa: E402
import use_result  # noqa: E402
from version import VERSION  # noqa: E402

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

# name -> (unit shown, multiplier from the stored value, decimals).  Stored values stay radians / metres.
PARAM_UNITS = {"wx": ("deg", 180 / 3.141592653589793, 4), "wy": ("deg", 180 / 3.141592653589793, 4),
               "wz": ("deg", 180 / 3.141592653589793, 4), "tx": ("mm", 1000.0, 2), "ty": ("mm", 1000.0, 2),
               "tz": ("mm", 1000.0, 2), "fx": ("px", 1.0, 3), "fy": ("px", 1.0, 3), "cx": ("px", 1.0, 3),
               "cy": ("px", 1.0, 3), "k1": ("", 1.0, 5), "k2": ("", 1.0, 5),
               "beam": ("deg", 180 / 3.141592653589793, 4)}

QSS = f"""
* {{ font-family: {FONT}; font-size: 14px; color: {INK}; }}
QMainWindow, QWidget#page {{ background: {BG}; }}
QScrollArea {{ border: none; background: transparent; }}
QLabel {{ background: transparent; }}
QLabel#largeTitle {{ font-size: 28px; font-weight: 700; }}
QLabel#title {{ font-size: 20px; font-weight: 600; }}
QLabel#headline {{ font-size: 17px; font-weight: 600; }}
QLabel#muted {{ font-size: 14px; color: {MUTED}; }}
QLabel#footnote {{ font-size: 12px; color: {MUTED}; }}
QLabel#metric {{ font-size: 30px; font-weight: 500; }}
QFrame#card {{ background: white; border: 1px solid {LINE}; border-radius: 16px; }}
QFrame#source {{ background: {SOFT['grey']}; border: 1px solid {LINE}; border-radius: 12px; }}
QFrame#option {{ background: white; border: 1px solid {LINE}; border-radius: 12px; }}
QFrame#optionBest {{ background: white; border: 2px solid {BLUE}; border-radius: 12px; }}
QLabel#err {{ color: {BAD}; background: {SOFT['bad']}; border-radius: 6px; padding: 6px 10px; font-size: 13px; }}
QLabel#small {{ font-size: 12px; color: {MUTED}; }}
QLabel#caps {{ font-size: 12px; font-weight: 700; color: {MUTED}; letter-spacing: 1px; }}
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
QPushButton#nav {{ min-height: 34px; padding: 0 8px; font-size: 13px; }}
QPushButton#nav[active="true"] {{ background: {SOFT['blue']}; border-color: {BLUE}; color: {BLUE}; }}
QPushButton#navprimary {{ background: {BLUE}; color: white; border-color: {BLUE}; min-height: 34px; padding: 0 12px; font-size: 14px; }}
QPushButton#navprimary:hover {{ background: #1686ff; border-color: #1686ff; }}
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


def path_problem(output, captures):
    """A message when Windows would refuse the files this check writes (260 character limit), else None."""
    if os.name != "nt":
        return None
    try:
        names = [p.name for p in Path(captures).glob("capture_*")] or [p.stem for p in Path(captures).glob("*.npz")]
    except OSError:
        names = []
    # the longest file written is <output>\inputs\stacked\data\<capture name>.npz (Windows allows 259 characters)
    longest = len(str(output)) + len("\\inputs\\stacked\\data\\") + (max(len(n) for n in names) if names else 44) + len(".npz")
    if longest <= 259:
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\FileSystem") as key:
            if winreg.QueryValueEx(key, "LongPathsEnabled")[0] == 1:
                return None
    except (OSError, ImportError):
        pass
    return (f"The results of this check would need file paths of about {longest} characters, and Windows stops at 260. "
            "Move the repository to a shorter folder (for example C:\\FaultAware) or turn on long paths in Windows, then run the check again.")


LOG_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "FaultAwareCalibration"


def setup_logging():
    """A rotating log file next to the user's other app data, so a problem can be reported with its details."""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(LOG_DIR / "app.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        root = logging.getLogger("faultaware")
        root.setLevel(logging.INFO)
        root.addHandler(handler)
        return root
    except OSError:
        return logging.getLogger("faultaware")


def excepthook(kind, value, tb):
    """Without a hook PyQt5 aborts the whole app on an error inside a slot, with no message at all."""
    text = "".join(traceback.format_exception(kind, value, tb))
    logging.getLogger("faultaware").error("Unhandled error\n%s", text)
    try:
        box = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Critical, "Something went wrong",
                                    "The app hit an unexpected problem. Your calibration files were not changed.\n\n"
                                    f"{kind.__name__}: {value}\n\nDetails were saved to:\n{LOG_DIR / 'app.log'}")
        box.exec_()
    except Exception:  # noqa: BLE001 - reporting must not raise
        pass


def nav_icon(kind):
    """Simple blue outline icons for the two sidebar buttons."""
    pm = QtGui.QPixmap(40, 40)
    pm.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    p.scale(2, 2)
    p.setPen(QtGui.QPen(QtGui.QColor(BLUE), 1.7, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap, QtCore.Qt.RoundJoin))
    p.setBrush(QtCore.Qt.NoBrush)
    if kind == "devices":  # a sensor: rounded body, lens, short stand
        p.drawRoundedRect(QtCore.QRectF(2.5, 3.5, 15, 10), 2.5, 2.5)
        p.drawEllipse(QtCore.QPointF(10, 8.5), 2.6, 2.6)
        p.drawLine(QtCore.QPointF(10, 13.5), QtCore.QPointF(10, 16.5))
        p.drawLine(QtCore.QPointF(6.5, 16.5), QtCore.QPointF(13.5, 16.5))
    else:  # plus in a circle
        p.drawEllipse(QtCore.QPointF(10, 10), 7.6, 7.6)
        p.drawLine(QtCore.QPointF(10, 6.5), QtCore.QPointF(10, 13.5))
        p.drawLine(QtCore.QPointF(6.5, 10), QtCore.QPointF(13.5, 10))
    p.end()
    return QtGui.QIcon(pm)


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


class SourceCard(QtWidgets.QFrame):
    """Run-page strip card: title, 'Open ↗' link and the (shortened) path, as in the maintenance app."""

    def __init__(self, title):
        super().__init__()
        self.setObjectName("source")
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(4)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(label(title, "headline", wrap=False), 1)
        self.link = QtWidgets.QPushButton("Open ↗")
        self.link.setObjectName("link")
        self.link.setCursor(QtCore.Qt.PointingHandCursor)
        self.link.clicked.connect(self.open)
        row.addWidget(self.link)
        lay.addLayout(row)
        self.value = label("–", "footnote", wrap=False)
        self.value.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
        lay.addWidget(self.value)
        self.target = ""
        self.set_path("")

    def set_path(self, p):
        self.target = str(p or "")
        self.link.setVisible(bool(self.target))
        full = self.target or "–"
        self.value.setToolTip(full)
        fm = QtGui.QFontMetrics(self.value.font())
        self.value.setText(fm.elidedText(full, QtCore.Qt.ElideMiddle, 300))

    def open(self):
        if self.target:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(self.target))


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
        txt.addWidget(label(subtitle, "muted", wrap=False))
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
        screen = QtWidgets.QApplication.primaryScreen().availableGeometry()
        self.resize(min(1680, int(screen.width() * 0.92)), min(1020, int(screen.height() * 0.90)))
        self.setMinimumSize(1000, 680)
        self.output = None
        self.process = None
        self.history_cache = {}
        self.store = None            # set by main(): what to remember between sessions (tests and screenshots leave it off)
        self.pending_device = None   # device capture folder of the check about to start (kept in its metadata)
        self.run_output = None      # folder of the check that is running (self.output follows what the user opens)
        self.stopping = False
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
        logo = QtWidgets.QLabel()
        logo.setPixmap(self.logo_pixmap(36))
        head = QtWidgets.QHBoxLayout()
        head.setSpacing(10)
        head.addWidget(logo)
        head.addWidget(label("<b style='font-size:17px'>Fault-aware<br>calibration</b>", rich=True), 1)
        sl.addLayout(head)
        self.devices = None  # built on first use so that starting the app never probes the network
        self.nav_dev = QtWidgets.QPushButton("Devices")
        self.nav_dev.setToolTip("Connect to a sensor device, read its calibration and capture data to check")
        self.nav_dev.clicked.connect(self.show_devices)
        self.nav_new = QtWidgets.QPushButton("New check")
        self.nav_new.setToolTip("Check a calibration using saved capture files")
        self.nav_new.clicked.connect(self.show_setup)
        nav = QtWidgets.QHBoxLayout()
        nav.setSpacing(8)
        for b, kind in ((self.nav_dev, "devices"), (self.nav_new, "check")):
            b.setObjectName("nav")
            b.setIconSize(QtCore.QSize(18, 18))
            b.setCursor(QtCore.Qt.PointingHandCursor)
            b.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
            b.setProperty("kind", kind)
            nav.addWidget(b)
        sl.addLayout(nav)
        sl.addSpacing(6)
        sl.addWidget(label("CHECKS", "caps"))
        self.runs = QtWidgets.QListWidget()
        self.runs.setObjectName("runs")
        self.runs.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.runs.setWordWrap(True)
        self.runs.itemClicked.connect(lambda it: self.open_run(it.data(QtCore.Qt.UserRole)))
        sl.addWidget(self.runs, 1)
        version = label(f"Version {VERSION} · log: {LOG_DIR}", "footnote")
        version.setToolTip("Include the version and the log file when you report a problem.")
        sl.addWidget(version)

        # ---- pages
        self.pages = QtWidgets.QStackedWidget()
        self.pages.addWidget(self.build_setup())
        self.pages.addWidget(self.build_run_page())
        self.pages.currentChanged.connect(self.sync_nav)
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
        self.sync_nav()

    def closeEvent(self, event):
        """Never leave a check running unseen: ask first, then stop it (and the review) cleanly."""
        if self.is_running() or self.review.is_running():
            answer = QtWidgets.QMessageBox.question(self, "A check is running", "Stop the running check or calibration review and close the app? "
                                                    "Nothing is changed; the partial output stays in its folder.")
            if answer != QtWidgets.QMessageBox.Yes:
                event.ignore()
                return
            if self.is_running():
                self.stopping = True
                self.process.kill()
                self.process.waitForFinished(3000)
        self.review.shutdown()
        if self.devices is not None:
            self.devices.shutdown()
        self.remember(geometry=self.saveGeometry().toBase64().data().decode("ascii"))
        event.accept()

    # ---- sidebar navigation
    def sync_nav(self, *_):
        """Highlight the button of the page that is open, and keep the blue icons in step."""
        page = self.pages.currentWidget()
        for b, on in ((self.nav_dev, self.devices is not None and page is self.devices),
                      (self.nav_new, self.pages.currentIndex() == 0)):
            b.setProperty("active", on)
            b.setIcon(nav_icon(b.property("kind")))
            b.style().unpolish(b)
            b.style().polish(b)

    def show_devices(self):
        if self.devices is None:
            from device_ui import DevicePage
            self.devices = DevicePage(self, choose_mode=False)
            self.devices.run_ready.connect(self.device_captured)
            self.pages.addWidget(self.devices)
        self.runs.clearSelection()
        self.pages.setCurrentWidget(self.devices)

    def device_captured(self, name, _args):
        """A device capture finished: keep it in this app's own folder, then run the fault-aware check on it."""
        src = Path(core.RESULTS) / name
        dst = ROOT / "device_captures" / name
        try:
            dst.parent.mkdir(exist_ok=True)
            shutil.move(str(src), str(dst))  # moved, so the maintenance app's history is not touched
        except OSError as err:
            return self.warn(f"Could not keep the capture: {err}")
        self.load_cal(str(dst / "device_calibration.json"))
        self.load_data(str(dst / "captures"))
        self.pending_device = dst        # remembered by the check, so its result can be written back to this device
        self.mode_combo.setCurrentIndex(max(0, self.mode_combo.findData("check")))
        self.update_ready()
        if self.run_btn.isEnabled():
            self.run()
            self.pending_device = None
        else:
            self.pending_device = None
            self.pages.setCurrentIndex(0)
            self.warn(self.hint.text() or "The capture could not be checked.")

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
        self.restored_row = QtWidgets.QWidget()
        rr = QtWidgets.QHBoxLayout(self.restored_row)
        rr.setContentsMargins(0, 0, 0, 0)
        self.restored_text = label("", "footnote", wrap=False)
        rr.addWidget(self.restored_text)
        forget = QtWidgets.QPushButton("Forget")
        forget.setObjectName("link")
        forget.setCursor(QtCore.Qt.PointingHandCursor)
        forget.setToolTip("Stop remembering the calibration, captures and options")
        forget.clicked.connect(self.forget_remembered)
        rr.addWidget(forget)
        rr.addStretch(1)
        self.restored_row.hide()
        v.addWidget(self.restored_row)

        self.cal = Step(1, "Existing calibration", "The camera settings and alignment in use now",
                        "Choose a suggested calibration…", sug["calibrations"])
        self.cal.combo.activated.connect(lambda k: self.cal.combo.itemData(k) and self.load_cal(self.cal.combo.itemData(k)))
        self.cal.add_button("Open file…", self.open_cal)
        self.cal.add_button("Enter values…", self.enter_cal)
        self.cal.add_header_link("Use example values", self.use_example)
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
        self.pair_report_btn = QtWidgets.QPushButton("View pairs")
        self.pair_report_btn.setObjectName("link")
        self.pair_report_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.pair_report_btn.setEnabled(False)
        self.pair_report_btn.clicked.connect(self.show_pair_report)
        row.addWidget(self.pair_report_btn)
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
        self.step3 = StepHeader(3, "Check for changes", "Compare the options, then review the recommendation")
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
        self.strategy.currentIndexChanged.connect(lambda _i: self.remember(strategy=self.strategy.currentData()))
        grid.addWidget(self.mode_combo, 1, 0)
        grid.addWidget(self.strategy, 1, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        l3.addLayout(grid)
        self.auto_review = QtWidgets.QCheckBox("Also run the maintenance comparison for the Calibration review tab")
        self.auto_review.setChecked(True)
        self.auto_review.setToolTip("After the fault-aware result is ready, the original calibration maintenance analysis runs on the same "
                                    "calibration and captures (a few more minutes). Its results appear in the Calibration review tab and "
                                    "never change the fault-aware result. You can also run it later from that tab.")
        l3.addWidget(self.auto_review)
        self.auto_review.toggled.connect(lambda on: (self.remember(auto_review=bool(on)), self.update_ready()))
        self.run_btn = QtWidgets.QPushButton("Check calibration")
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
        self.state = QtWidgets.QLabel("")
        self.state.hide()
        top.addWidget(self.state)
        outer.addLayout(top)
        strip = QtWidgets.QHBoxLayout()
        strip.setSpacing(8)
        self.s_cal, self.s_cap, self.s_out = SourceCard("Existing calibration"), SourceCard("New captures"), SourceCard("Results")
        for i, c in enumerate((self.s_cal, self.s_cap, self.s_out)):
            strip.addWidget(c, 1)
            if i < 2:
                strip.addWidget(label("→", "muted", wrap=False))
        outer.addLayout(strip)
        self.progress = QtWidgets.QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 1)
        outer.addWidget(self.progress)
        self.stack = QtWidgets.QStackedWidget()
        self.processing = processing_view.ProcessingView()
        self.log = self.processing.log
        self.stack.addWidget(self.processing)
        self.stack.addWidget(self.build_result())
        self.review = calibration_review.CalibrationReview()
        self.review.changed.connect(self.on_review_changed)
        self.review.show_processing.connect(lambda: self.pager.select(0))
        self.processing.stop_review.connect(self.review.stop)
        self.stack.addWidget(self.review)
        self.stack.addWidget(self.build_report())
        outer.addWidget(self.banner)
        bar = QtWidgets.QHBoxLayout()
        self.pager = Pager(["Processing", "Result", "Calibration review", "Report"])
        bar.addWidget(self.pager)
        bar.addStretch()
        self.stop_btn = QtWidgets.QPushButton("Stop check")
        self.stop_btn.setToolTip("Stop this check now. Nothing is changed; the partial output is left in its folder.")
        self.stop_btn.clicked.connect(self.stop_run)
        self.stop_btn.hide()
        bar.addWidget(self.stop_btn)
        self.cal_btn = QtWidgets.QPushButton("View calibration after this check…")
        self.cal_btn.clicked.connect(self.view_result_calibration)
        self.cal_btn.hide()
        bar.addWidget(self.cal_btn)
        outer.addLayout(bar)
        outer.addWidget(self.stack, 1)
        self.pager.changed.connect(self.stack.setCurrentIndex)
        self.pager.changed.connect(self.sync_cal_btn)
        return page

    def set_state(self, text):
        tone = {"Finished": (GOOD, SOFT["good"]), "Running…": (BLUE, SOFT["blue"]), "Stopped": (BAD, SOFT["bad"])}
        fg, bg = tone.get(text, (MUTED, SOFT["grey"]))
        self.state.setText(text)
        self.state.setStyleSheet(f"color:{fg}; background:{bg}; border-radius:10px; padding:6px 20px;"
                                 "font-size:14px; font-weight:600;")
        self.state.show()

    @staticmethod
    def logo_pixmap(size):
        return app_icon.logo_pixmap(size)

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

        self.visuals = result_visuals.ResultVisuals()
        self.visuals.hide()
        self.rlay.addWidget(self.visuals)

        self.table_frame, tl = frame("card", spacing=8)
        tl.addWidget(label("Parameter changes", "headline"))
        self.table = QtWidgets.QTableWidget(0, 5)
        heads = ["Parameter", "Unit", "Data can see it", "Accepted change", "Candidate change"]
        self.table.setHorizontalHeaderLabels(heads)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        for c, w in ((1, 80), (2, 150), (3, 170), (4, 170)):
            hh.setSectionResizeMode(c, QtWidgets.QHeaderView.Fixed)
            self.table.setColumnWidth(c, w)
        hh.setHighlightSections(False)
        for c, h in enumerate(heads):  # header text lines up with the column below it
            it = self.table.horizontalHeaderItem(c)
            it.setTextAlignment((QtCore.Qt.AlignLeft if c < 2 else QtCore.Qt.AlignRight if c > 2 else QtCore.Qt.AlignCenter)
                                | QtCore.Qt.AlignVCenter)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(36)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.table.setFocusPolicy(QtCore.Qt.NoFocus)
        self.table.setShowGrid(False)
        self.table.setMinimumHeight(36 * 14 + 40)
        tl.addWidget(self.table)
        tl.addWidget(label("“Accepted” is zero whenever the current calibration is kept. “Candidate” is what the "
                           "optimiser proposed before validation. Values are shown as a change from the current calibration: rotations in "
                           "degrees, translations in millimetres, camera terms in pixels.", "footnote"))
        self.rlay.addWidget(self.table_frame)
        self.use_card = use_result.UseResultCard()
        self.use_card.check_again.connect(self.check_again)
        self.use_card.changed.connect(self.refresh_runs)
        self.rlay.addWidget(self.use_card)
        self.rlay.addStretch()
        return scroll

    def build_report(self):
        self.report_view = report_view.ReportView()
        return self.report_view

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
        self.visuals.hide()
        self.review.clear()
        self.use_card.clear()
        self.report_view.clear()
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

    @staticmethod
    def meta_file(folder):
        return Path(folder).with_name(Path(folder).name + ".gui.json")

    def meta_of(self, folder):
        try:
            return json.loads(self.meta_file(folder).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def remember(self, **values):
        if self.store is not None:
            self.store.update(**values)

    def start_dir(self, key):
        return self.store.existing(key, "dir") if self.store is not None else None

    def forget_remembered(self):
        if self.store is not None:
            self.store.clear()
        self.restored_row.hide()

    def restore_state(self):
        """Pick up where the last session left off: the calibration and captures (if they still exist), the options and
        the window. Never starts a check. Returns whether inputs were restored."""
        s = self.store
        if s is None:
            return False
        restored = []
        try:
            index = self.mode_combo.findData(s.get("mode")) if s.get("mode") else -1
            if index >= 0:
                self.mode_combo.setCurrentIndex(index)
            index = self.strategy.findData(s.get("strategy")) if s.get("strategy") else -1
            if index >= 0:
                self.strategy.setCurrentIndex(index)
            if s.get("auto_review") is not None:
                self.auto_review.setChecked(bool(s.get("auto_review")))
            cal = s.existing("calibration", "file")
            if cal and self.mode != "scratch":
                self.load_cal(cal)
                if self.cal.path:
                    restored.append("calibration")
            cap = s.existing("captures", "dir")
            if cap:
                self.load_data(cap)
                if self.cap.path:
                    restored.append("captures")
            if s.get("geometry"):
                self.restoreGeometry(QtCore.QByteArray.fromBase64(s.get("geometry").encode("ascii")))
        except Exception:  # noqa: BLE001 - remembering is a convenience and must never stop the app
            logging.getLogger("faultaware").exception("Could not restore the last session")
        self.restored_row.setVisible(bool(restored))
        if restored:
            self.restored_text.setText("Picked up from your last session: " + " and ".join(restored) + ".")
        return bool(restored)

    def review_stage_state(self, folder):
        """What the Processing tab should show for the maintenance comparison of this check."""
        if self.review.is_running() and self.review.running_folder == Path(folder):
            return "running"
        return "done" if review_adapter.state(folder) == "ready" else None

    def on_review_changed(self):
        """A maintenance comparison started or finished: Processing and the Use the result options follow."""
        watched = self.processing.review_check
        if watched is not None and not self.review.is_running() and self.processing.model.state.get("review") == "active":
            ok = review_adapter.state(watched) == "ready"
            self.processing.review_finished(ok, self.review.publish_error or "The comparison did not finish. Its log is in the Calibration review tab.")
        folder = self.review.folder
        if folder is not None and self.use_card.folder == folder:
            ready = review_adapter.state(folder) == "ready"
            self.use_card.set_review(review_adapter.load(folder) if ready else None)
            self.report_view.set_review(review_adapter.read_json(review_adapter.run_folder(folder) / "summary.json") if ready else None)

    def sync_cal_btn(self, *_):
        """'View calibration after this check…' belongs to the Result tab only."""
        self.cal_btn.setVisible(bool(self.result_cal) and self.stack.currentIndex() == 1)

    def check_again(self):
        """Back to New check with the calibration, captures and options of the check that is open."""
        meta = self.meta_of(self.output) if self.output else {}
        if meta.get("mode") == "scratch":
            self.mode_combo.setCurrentIndex(max(0, self.mode_combo.findData("scratch")))
        else:
            self.mode_combo.setCurrentIndex(max(0, self.mode_combo.findData("check")))
            if meta.get("calibration") and Path(meta["calibration"]).is_file():
                self.load_cal(meta["calibration"])
            index = self.strategy.findData(meta.get("strategy"))
            if index >= 0:
                self.strategy.setCurrentIndex(index)
        if meta.get("captures") and Path(meta["captures"]).is_dir():
            self.load_data(meta["captures"])
        self.auto_review.setChecked(bool(meta.get("with_review")))
        self.update_ready()
        self.show_setup()

    def refresh_runs(self):
        current = str(self.output) if self.output else None
        self.runs.clear()
        base = ROOT / "research_artifacts"
        folders = sorted((p for p in base.glob("gui_*") if p.is_dir()), reverse=True) if base.exists() else []
        for f in folders:
            rf = self.result_file(f)
            meta = self.meta_of(f)
            running = self.is_running() and self.run_output is not None and Path(self.run_output) == f
            status, color = "stopped with an error" if not running else "running…", MUTED
            if running:
                color = BLUE
            elif rf:
                try:
                    stamp = (str(rf), rf.stat().st_mtime_ns)
                    if stamp not in self.history_cache:       # hundreds of checks must not mean hundreds of JSON parses per refresh
                        r = json.loads(rf.read_text(encoding="utf-8"))
                        st = r.get("status", "")
                        text = STATUS.get(st, (st.replace("_", " ").lower(),))[0].lower()
                        gain = ((r.get("diagnostics") or {}).get("decision") or {}).get("best_relative_gain")
                        if gain is not None:
                            text += f" · {gain * 100:.2f} % gain"
                        self.history_cache[stamp] = (text, STATUS.get(st, (None, MUTED))[1])
                    status, color = self.history_cache[stamp]
                except (OSError, ValueError, AttributeError):
                    pass
            marks = []
            if (f / use_result.USE_DIR / "accepted.json").exists():
                marks.append("accepted")
            if any(w.get("backup") for w in use_result.device_writes(f)):
                marks.append("written to device")
            if marks:
                status += " · " + ", ".join(marks)
            try:
                when = datetime.strptime(f.name[4:19], "%Y%m%d_%H%M%S").strftime("%Y-%m-%d %H:%M")
            except ValueError:
                when = f.name
            title = Path(meta.get("captures", "")).name
            lines = [title, status, when] if title else [status, when]
            it = QtWidgets.QListWidgetItem(self.dot(color), "\n".join(lines))
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
            if not self.is_running():
                self.processing.reset()
            self.fail("This check has no result. It may have stopped before finishing.")
        self.pages.setCurrentIndex(1)

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
        self.remember(calibration=info["path"])
        self.cal_info = info
        i = info["intrinsics"]
        size = f" · {i['image_size'][0]}×{i['image_size'][1]}" if i.get("image_size") else ""
        self.cal.summary.setText(f"<b>{shown.parent.name}/{shown.name}</b><br>fx {core.fmt(i['fx'])} · "
                                 f"fy {core.fmt(i['fy'])}{size} · {info['extrinsics']['mounting_label']}")
        self.cal.summary.show()
        self.cal.clear_extra()
        try:                                  # the matrices, side by side, without opening anything
            shown_cal = json.loads(Path(info["path"]).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            shown_cal = None
        pair = matrix_view.MatrixPair(shown_cal) if isinstance(shown_cal, dict) else None
        if pair is not None and pair.valid:
            self.cal.extra.addWidget(pair)
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
        start = str(Path(self.cal.path).parent) if self.cal.path else (self.start_dir("cal_dir") or str(core.PROJECT))
        p, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Existing calibration", start, CAL_FILTER)
        if p:
            self.remember(cal_dir=str(Path(p).parent))
            self.cal.combo.setCurrentIndex(0)
            self.load_cal(p)

    def enter_cal(self):
        d = ManualDialog(self, self.cal_info if self.cal.path else None)
        if d.exec_() == QtWidgets.QDialog.Accepted:
            self.cal.combo.setCurrentIndex(0)
            self.load_cal(d.path)

    def use_example(self):
        example = ROOT / "examples" / "calibration.example.json"
        if example.is_file():
            self.cal.combo.setCurrentIndex(0)
            self.load_cal(str(example))

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
        self.remember(captures=info["path"])
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
        start = str(Path(self.cap.path).parent) if self.cap.path else (self.start_dir("data_dir") or str(ROOT))
        p = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose captures folder", start)
        if p:
            self.remember(data_dir=str(Path(p).parent))
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
                if checked.get("warnings"):
                    text += f" · {len(checked['warnings'])} notes in View pairs"
        except (ValueError, OSError) as err:
            text, color = str(err), BAD
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        self.pair_status.setText(text)
        self.pair_status.setStyleSheet(f"color:{color};")
        self.pair_report_btn.setEnabled(bool(self.data.get("paired_validation")))
        self.update_ready()

    def show_pair_report(self):
        from ui_widgets import pair_report_dialog
        dialog = pair_report_dialog(self, self.data)
        if dialog is not None:
            dialog.exec_()

    def show_capture_format(self):
        from capture_help import CaptureFormatDialog
        CaptureFormatDialog(self).exec_()

    # ---- step 3
    def mode_changed(self):
        self.mode = self.mode_combo.currentData()
        self.remember(mode=self.mode)
        scratch = self.mode == "scratch"
        self.cal.setEnabled(not scratch)
        self.strategy.setEnabled(not scratch)
        self.auto_review.setEnabled(not scratch)
        self.run_btn.setText("Calibrate" if scratch else "Check calibration")
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
                                      else "Takes a few minutes" + (", then the Calibration review runs for a few more" if self.auto_review.isChecked() else "")
                                      + ". Nothing is written to a device."))
        self.step3.set_done(False)

    def is_running(self):
        return self.process is not None and self.process.state() != QtCore.QProcess.NotRunning

    # ---- running
    def run(self):
        if self.is_running():
            return self.warn("A check is already running. Wait for it to finish or stop it first.")
        scratch = self.mode == "scratch"
        output = ROOT / "research_artifacts" / datetime.now().strftime("gui_%Y%m%d_%H%M%S")
        for n in range(2, 100):          # two checks started in the same second must not share a folder
            if not output.exists() and not self.meta_file(output).exists():
                break
            output = output.with_name(f"{output.name[:19]}_{n}")
        problem = path_problem(output, self.cap.path)
        if problem:
            return self.warn(problem)
        try:
            output.parent.mkdir(parents=True, exist_ok=True)
        except OSError as err:
            return self.warn(f"Cannot create the results folder: {err}")
        self.output = self.run_output = output
        self.stopping = False
        self.meta_file(self.output).write_text(json.dumps(dict(
            calibration="" if scratch else self.cal.path, captures=self.cap.path, mode=self.mode,
            strategy=None if scratch else self.strategy.currentData(),
            cloud_units=self.pair_units.currentData() if self.data and self.data["kind"] == "paired" else None,
            confirm_cloud_units=bool(self.data and self.data["kind"] == "paired" and self.units_confirm.isChecked()),
            with_review=bool(self.auto_review.isChecked() and not scratch),
            device_source=str(self.pending_device) if self.pending_device else None)), encoding="utf-8")
        self.pending_device = None
        self.set_sources(self.output)
        self.log.clear()
        self.run_btn.setEnabled(False)
        self.progress.setRange(0, 0)
        self.run_title.setText("Calibrating from scratch" if scratch else "Checking calibration")
        self.set_state("Running…")
        self.style_banner(BLUE, "blue")
        self.b_title.setText("Running…")
        self.b_body.setText("This can take a few minutes. Follow it in the Processing tab." if not scratch else
                            "Estimating a new calibration, then checking it. This takes about 10 minutes.")
        self.cards_frame.hide()
        self.table_frame.hide()
        self.visuals.hide()
        self.review.clear()
        self.use_card.clear()
        self.report_view.clear()
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
        p.errorOccurred.connect(lambda err: self.fail("Could not start the check.") if err == QtCore.QProcess.FailedToStart else None)
        exe = Path(sys.executable)
        if exe.name.lower() == "pythonw.exe":
            exe = exe.with_name("python.exe")
        self.process = p
        self.processing.begin(self.output, scratch, processing_view.count_captures(self.cap.path),
                              review=bool(self.auto_review.isChecked() and not scratch))
        self.stop_btn.show()
        p.start(str(exe), ["-X", "utf8", "-B", "-W", "ignore::RuntimeWarning", "-m", "research_calibration"] + args)
        self.refresh_runs()

    def stop_run(self):
        """Stop the running check. kill(), not terminate(): terminate() does nothing to a console process on Windows."""
        if not self.is_running():
            return
        self.stopping = True
        self.process.kill()

    def set_sources(self, folder):
        meta = self.meta_of(folder)
        self.s_cal.set_path(meta.get("calibration"))
        self.s_cap.set_path(meta.get("captures"))
        self.s_out.set_path(folder)
        self.s_cal.value.setText("Calibrated from scratch" if meta.get("mode") == "scratch" else self.s_cal.value.text())

    def tiles_clear(self):
        self.clear(self.tiles)

    def read_output(self):
        if self.process is None:
            return
        t = bytes(self.process.readAllStandardOutput()).decode("utf-8", errors="replace").rstrip()
        if t:
            self.processing.feed_log(t)

    def finished_run(self, code, *_):
        self.read_output()
        self.stop_btn.hide()
        self.progress.setRange(0, 1)
        self.update_ready()
        folder = self.run_output or self.output
        if self.stopping:
            self.stopping = False
            self.processing.cancelled()
            self.fail("Stopped by you. Your calibration is unchanged.", title="Check stopped")
        elif code == 0 and folder and self.result_file(folder):
            self.processing.finish(True)
            self.load(folder)
            if self.meta_of(folder).get("with_review"):
                # the user asked for it on the setup page; it never alters the result just shown, and it is followed in Processing
                started = self.review.start(auto=True)
                self.processing.add_review(folder)
                if not started:
                    self.processing.review_finished(False, self.review.reason or "The maintenance comparison could not be started.")
        else:
            lines = [l for l in self.log.toPlainText().splitlines() if l.strip()]
            self.processing.finish(False, "The check stopped: " + (lines[-1] if lines else "no further information."))
            self.fail("The check stopped, and your calibration is unchanged. "
                      + (lines[-1] if lines else "See the log in the Processing tab."))
        self.run_output = None
        self.refresh_runs()

    def fail(self, msg, title="Could not finish"):
        self.progress.setRange(0, 1)
        self.update_ready()
        self.set_state("Stopped")
        self.run_title.setText("Check stopped")
        self.style_banner(BAD, "bad")
        self.b_title.setText(title)
        self.b_body.setText(msg)
        self.cards_frame.hide()
        self.table_frame.hide()
        self.visuals.hide()
        self.review.clear()
        self.use_card.clear()
        self.report_view.clear()
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
        self.set_state("Finished")
        meta = self.meta_of(folder)
        self.run_title.setText(Path(meta.get('captures', '')).name or self.title_of(folder))
        self.set_sources(folder)
        self.result_cal = r.get("updated_calibration") if isinstance(r.get("updated_calibration"), dict) else None
        self.sync_cal_btn()
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
        mono = QtGui.QFont("Cascadia Mono")
        mono.setStyleHint(QtGui.QFont.Monospace)
        mono.setPixelSize(13)
        for i, n in enumerate(names):
            unit, scale, digits = PARAM_UNITS.get(n, ("", 1.0, 4))
            seen = n in obs
            cells = [(PARAM_NAMES.get(n, n), QtCore.Qt.AlignLeft, None),
                     (unit, QtCore.Qt.AlignLeft, MUTED),
                     ("● Seen" if seen else "Not seen", QtCore.Qt.AlignCenter, GOOD if seen else MUTED)]
            for v in (acc.get(n), cand_u.get(n) if isinstance(cand_u, dict) else None):
                if v is None:
                    cells.append(("–", QtCore.Qt.AlignRight, MUTED))
                elif abs(v) < 1e-12:
                    cells.append(("0", QtCore.Qt.AlignRight, MUTED))
                else:
                    cells.append((f"{v * scale:+.{digits}f}", QtCore.Qt.AlignRight, None))
            for j, (text, align, color) in enumerate(cells):
                it = QtWidgets.QTableWidgetItem(text)
                it.setTextAlignment(align | QtCore.Qt.AlignVCenter)
                if j >= 3:
                    it.setFont(mono)
                if color:
                    it.setForeground(QtGui.QColor(color))
                self.table.setItem(i, j, it)
        self.table_frame.setVisible(bool(names))
        self.visuals.set_result(folder, r, self.reference_calibration(meta))
        self.review.set_check(folder, r, meta, (title, color, SOFT[soft], meaning + (f" {reason}" if reason else "")))
        if not self.is_running() and self.processing.model.state.get("review") != "active":     # never replace a live view
            self.processing.show_result(folder, r, self.review_stage_state(folder))
        ready = review_adapter.state(folder) == "ready"
        self.use_card.set_check(folder, r, meta, review_adapter.load(folder) if ready else None,
                                (title, color, SOFT[soft], meaning))

        self.report_view.set_result(folder, r, (title, color, SOFT[soft], meaning), PARAM_NAMES, PARAM_UNITS,
                                    review_adapter.read_json(review_adapter.run_folder(folder) / "summary.json") if ready else None)
        self.pager.select(1)

    @staticmethod
    def reference_calibration(meta):
        """The calibration this check started from, if its file is still there (None otherwise)."""
        path = meta.get("calibration")
        try:
            if path and Path(path).suffix.lower() == ".json":
                c = json.loads(Path(path).read_text(encoding="utf-8"))
                if "intrinsics" in c and "extrinsics" in c:
                    return c
        except (OSError, ValueError):
            pass
        return None

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
    if sys.platform == "win32":  # own taskbar identity so the icon shows instead of Python's
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("UNSW.FaultAwareCalibration")
        except Exception:
            pass
    setup_logging()
    sys.excepthook = excepthook
    QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, True)
    QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps, True)
    app = QtWidgets.QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(QSS)
    app.setWindowIcon(app_icon.app_icon())
    win = MainWindow()
    shot = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--shot=")), None)
    explicit = "--prefill" in sys.argv or any(not a.startswith("--") for a in sys.argv[1:])   # inputs were given on the command line
    if not shot:
        win.store = settings_store.Store()
    logging.getLogger("faultaware").info("Started version %s", VERSION)
    app.aboutToQuit.connect(lambda: win.devices and win.devices.shutdown())
    app.aboutToQuit.connect(win.review.shutdown)
    if "--prefill" in sys.argv:  # python research_gui.py --prefill <calibration> <captures folder>
        k = sys.argv.index("--prefill")
        win.load_cal(sys.argv[k + 1])
        win.load_data(sys.argv[k + 2])
        sys.argv[k:k + 3] = []
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    shot = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--shot=")), None)
    if args and MainWindow.result_file(args[0]):
        win.open_run(args[0])
    win.resize(1240, 1700 if "--tall" in sys.argv else 860)
    win.show()
    if win.store is not None and not explicit:
        QtCore.QTimer.singleShot(0, win.restore_state)     # after the window is up, so a big captures folder never delays it
    if shot:  # offscreen screenshot for visual checks
        win.pager.select(int(next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--tab=")), "1")))
        QtCore.QTimer.singleShot(500, lambda: (win.grab().save(shot), app.quit()))
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
