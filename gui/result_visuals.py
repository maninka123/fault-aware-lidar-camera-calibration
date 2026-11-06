"""Interactive result visuals for the Fault-aware calibration app.

Everything here is drawn from files a finished check already wrote (assessment.json and the stacked
captures in inputs/), so opening an old result shows the same figures and nothing is recomputed by the
optimiser.  Four cards:

  1. Why this verdict        - a pass / fail / cannot-check list, so it is obvious what was NOT validated.
  2. See it on the image     - the real LiDAR points over the real photo, morphed between the current and
                               the proposed calibration with a slider (optionally magnified).
  3. Is the change worth it  - held-out gain of every explanation, one dot per held-out capture.
  4. What the data can see   - which parts of the calibration the captures can tell apart, and which they cannot.
"""
import math
from pathlib import Path

import numpy as np
from PyQt5 import QtCore, QtGui, QtWidgets
from scipy.spatial.transform import Rotation

BLUE, GOOD, WARN, BAD = "#007aff", "#248a3d", "#9b6500", "#d70015"
INK, MUTED, LINE = "#1d1d1f", "#6e6e73", "#e5e5ea"
SOFT = dict(blue="#edf5ff", good="#eaf6ed", warn="#fff6e5", bad="#fff0f1", grey="#eeeef2")
GREY_BAR, BLUE_BAR = "#c7c7cc", "#9cc7ff"

HYP = {"KEEP": "Keep current", "R": "Rotation", "T": "Translation", "I": "Camera intrinsics",
       "RT": "Rotation + translation", "RI": "Rotation + intrinsics", "TI": "Translation + intrinsics",
       "RTI": "Everything"}
GROUP = {"R": "Rotation", "T": "Translation", "I": "Camera intrinsics"}


# ------------------------------------------------------------------ geometry (numpy only)
def cal_arrays(c):
    """calibration dict -> rotation, translation, [fx, fy, cx, cy], four fisheye distortion terms."""
    T = np.asarray(c["extrinsics"]["transform_lidar_to_camera"], float)
    K = np.asarray(c["intrinsics"]["camera_matrix"], float)
    D = np.r_[np.ravel(c["intrinsics"].get("distortion_coefficients", [])), np.zeros(4)][:4]
    return dict(R=T[:3, :3], t=T[:3, 3], f=np.array([K[0, 0], K[1, 1], K[0, 2], K[1, 2]]), D=D)


def blend(a, b, s):
    """Calibration a moved a fraction s of the way to b (s > 1 magnifies the change)."""
    rv = Rotation.from_matrix(b["R"] @ a["R"].T).as_rotvec()
    return dict(R=Rotation.from_rotvec(s * rv).as_matrix() @ a["R"], t=a["t"] + s * (b["t"] - a["t"]),
                f=a["f"] + s * (b["f"] - a["f"]), D=a["D"] + s * (b["D"] - a["D"]))


def project(P, c, circle=None, max_angle=1.0):
    """OpenCV equidistant fisheye projection of LiDAR points; ok marks points the model scores."""
    Pc = P @ c["R"].T + c["t"]
    z = Pc[:, 2]
    front = z > .2
    zz = np.where(front, z, 1.)
    a, b = Pc[:, 0] / zz, Pc[:, 1] / zz
    r = np.hypot(a, b)
    th = np.arctan(r)
    q = th * th
    D = c["D"]
    k = np.where(r > 1e-12, th * (1 + q * (D[0] + q * (D[1] + q * (D[2] + q * D[3])))) / np.maximum(r, 1e-12), 1.)
    u, v = c["f"][0] * a * k + c["f"][2], c["f"][1] * b * k + c["f"][3]
    ok = front & (th <= max_angle) & np.isfinite(u) & np.isfinite(v)
    if circle:
        ok &= (u - circle["cx"]) ** 2 + (v - circle["cy"]) ** 2 <= (.97 * circle["radius"]) ** 2
    return u, v, ok


def _lut():
    stops = [(0, (68, 1, 84)), (.25, (59, 82, 139)), (.5, (33, 145, 140)), (.75, (94, 201, 98)), (1, (253, 231, 37))]
    x = np.linspace(0, 1, 256)
    return np.stack([np.interp(x, [s[0] for s in stops], [s[1][i] for s in stops]) for i in range(3)], 1).astype(np.uint8)


LUT = _lut()


MIN_LIFT = 1.3          # the maintenance app's own "lines up with the scene" bar (decision.min_lift in its config.yaml)
OPTION_NAMES = (("extrinsic", "Maintenance: alignment only"), ("intrinsic", "Maintenance: camera only"),
                ("full", "Maintenance: camera + alignment"))


def _min_lift():
    try:
        import yaml
        cfg = yaml.safe_load((Path(__file__).resolve().parents[1] / "Calibration maintenance" / "code" / "config.yaml")
                             .read_text(encoding="utf-8"))
        return float(cfg["decision"]["min_lift"])
    except Exception:  # noqa: BLE001  the constant above is the declared default
        return MIN_LIFT


def _read(path):
    import json
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def review_alignment(folder):
    """How well the CURRENT calibration lines up with the captures, from the saved maintenance comparison.

    Edge-alignment lift = share of LiDAR edge points on a parallel image edge divided by the same share when the image
    is shifted (chance).  1.0 means no better than chance.  None when the comparison was not run."""
    s = _read(Path(folder) / "review" / "run" / "summary.json")
    old = (s or {}).get("existing_on_new_data") or {}
    if old.get("lift") is None:
        return None
    new = (s or {}).get("refined_on_new_data") or {}
    return dict(lift=float(old["lift"]), share=old.get("on_edge_share"), matches=old.get("matches"),
                refined_lift=new.get("lift"), min_lift=_min_lift())


def review_options(folder):
    """{key: (label, calibration arrays)} of the maintenance update options saved with the check."""
    d = _read(Path(folder) / "review" / "run" / "option_calibrations.json")
    cals = (d or {}).get("calibrations") or {}
    out = {}
    for key, label in OPTION_NAMES:
        try:
            if key in cals:
                out[key] = (label, cal_arrays(cals[key]))
        except (KeyError, ValueError, TypeError):
            continue
    return out


def capture_label(path):
    """capture_20261105_191917_810991_enclosure_on.npz -> '19:19:17'."""
    parts = Path(path).stem.split("_")
    try:
        t = parts[2]
        return f"{t[0:2]}:{t[2:4]}:{t[4:6]}"
    except IndexError:
        return Path(path).stem


def capture_id(path):
    parts = Path(path).stem.split("_")
    return "_".join(parts[2:4]) if len(parts) > 3 else Path(path).stem


# ------------------------------------------------------------------ small widget helpers
def _label(text="", name=None, rich=False):
    w = QtWidgets.QLabel(text)
    if name:
        w.setObjectName(name)
    w.setWordWrap(True)
    if rich:
        w.setTextFormat(QtCore.Qt.RichText)
    return w


def _inline(text):
    """A label that stays on one line (toolbars)."""
    w = _label(text, "muted")
    w.setWordWrap(False)
    return w


def _card(title, blurb):
    f = QtWidgets.QFrame()
    f.setObjectName("card")
    lay = QtWidgets.QVBoxLayout(f)
    lay.setContentsMargins(24, 24, 24, 24)
    lay.setSpacing(12)
    lay.addWidget(_label(title, "headline"))
    if blurb:
        lay.addWidget(_label(blurb, "muted"))
    return f, lay


def _seg(options, slot):
    """Segmented control; returns (frame, buttons)."""
    bar = QtWidgets.QFrame()
    bar.setObjectName("segbar")
    row = QtWidgets.QHBoxLayout(bar)
    row.setContentsMargins(3, 3, 3, 3)
    row.setSpacing(2)
    group = QtWidgets.QButtonGroup(bar)
    group.setExclusive(True)
    for i, (key, text) in enumerate(options):
        b = QtWidgets.QPushButton(text)
        b.setObjectName("seg")
        b.setCheckable(True)
        b.setChecked(i == 0)
        b.clicked.connect(lambda _=False, k=key: slot(k))
        group.addButton(b)
        row.addWidget(b)
    return bar


def _nice_ticks(lo, hi, n=5):
    span = max(hi - lo, 1e-9)
    raw = span / n
    mag = 10 ** math.floor(math.log10(raw))
    step = min((m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw), default=raw)
    t = math.ceil(lo / step) * step
    out = []
    while t <= hi + 1e-9:
        out.append(round(t, 10))
        t += step
    return out


# ------------------------------------------------------------------ 1. checklist
def build_checks(r):
    """List of (state, title, detail); state is 'pass', 'fail' or 'na' (cannot be checked)."""
    diag = r.get("diagnostics") or {}
    dec = diag.get("decision") or {}
    cfg = diag.get("configuration") or {}
    unc = r.get("uncertainty") or {}
    val = r.get("validation") or {}
    outer = val.get("outer_test") or {}
    folds = val.get("folds") or {}
    th = dec.get("thresholds") or {}
    out = []
    if r.get("status") == "INITIAL_CALIBRATION_CANDIDATE":
        init = diag.get("initialization") or {}
        out.append(("na", "Independent validation", "Every capture was used to estimate this calibration, so nothing was held back to test it."))
        out.append(("na", "Self-check", f"The initialiser's own label is “{init.get('inherited_heuristic_label') or 'unknown'}”. It is a heuristic, not a measured accuracy."))
        out.append(("na", "Ground truth", "No true calibration is known, so accuracy cannot be measured. Review the result by eye before using it."))
        return out

    n, need = dec.get("captures"), th.get("min_captures")
    if n is not None and need is not None:
        ok = n >= need
        out.append(("pass" if ok else "fail", "Enough captures", f"{n} capture{'s' if n != 1 else ''}; at least {need} are needed so each can be held out in turn."))
    best, gate = dec.get("best_relative_gain"), th.get("min_relative_gain")
    cand = dec.get("candidate_hypothesis")
    if best is not None and gate is not None:
        ok = best >= gate
        name = HYP.get(cand, cand or "the best option")
        out.append(("pass" if ok else "fail", "Big enough improvement",
                    f"“{name}” lowers held-out error by {best * 100:.2f} %; an update needs at least {gate * 100:.0f} %."))
    keep = folds.get("KEEP") or []
    cf = folds.get(cand) or []
    if cand and cand != "KEEP" and keep and cf and len(keep) == len(cf):
        better = sum(1 for a, b in zip(keep, cf) if (b.get("metrics") or {}).get("loss", 9) < (a.get("metrics") or {}).get("loss", 0))
        ok = better == len(keep)
        out.append(("pass" if ok else "fail", "Consistent across captures",
                    f"“{HYP.get(cand, cand)}” beats the current calibration on {better} of {len(keep)} held-out captures."))
    tests = outer.get("test_ids") or []
    if tests:
        g = outer.get("relative_gain")
        out.append(("pass" if outer.get("passed") else "fail", "Final independent test",
                    f"{len(tests)} captures never used for fitting or choosing: gain {g * 100:.2f} %." if g is not None
                    else f"{len(tests)} untouched captures were tested."))
    else:
        out.append(("na", "Final independent test", "Not run: no captures were kept aside. Add more captures from separate sessions to enable it."))
    ustat = str(unc.get("status", ""))
    if ustat:
        ok = "INSUFFICIENT" not in ustat
        out.append(("pass" if ok else "fail", "Error bars available",
                    "Uncertainty could be estimated." if ok else
                    f"Not enough independent captures to estimate uncertainty ({unc.get('clusters', '?')} capture groups, rank {unc.get('covariance_rank', '?')}). No confidence interval is claimed."))
    sup = (diag.get("stable_support") or {}).get("candidate_update_supported_fraction")
    floor = cfg.get("support_floor")
    if sup is not None and floor is not None:
        ok = sup >= floor
        out.append(("pass" if ok else "fail", "Change is in directions the data can see",
                    f"{sup * 100:.1f} % of the proposed change lies in directions these captures can actually measure."))
    out.append(("na", "True ground truth", "Not available. Scores are a nearest-edge proxy, not real reprojection error, and no physical fault labels exist for these recordings."))
    return out


class Checklist(QtWidgets.QWidget):
    COLOR = {"pass": (GOOD, SOFT["good"], "✓"), "fail": (BAD, SOFT["bad"], "✕"), "na": (MUTED, SOFT["grey"], "–")}

    def __init__(self, checks):
        super().__init__()
        grid = QtWidgets.QGridLayout(self)
        grid.setContentsMargins(0, 4, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        for i, (state, title, detail) in enumerate(checks):
            fg, bg, mark = self.COLOR[state]
            badge = QtWidgets.QLabel(mark)
            badge.setFixedSize(26, 26)
            badge.setAlignment(QtCore.Qt.AlignCenter)
            badge.setStyleSheet(f"background:{bg}; color:{fg}; border-radius:13px; font-weight:700; font-size:14px;")
            text = _label(f"<b>{title}</b><br><span style='color:{MUTED}; font-size:13px;'>{detail}</span>", rich=True)
            grid.addWidget(badge, i, 0, QtCore.Qt.AlignTop)
            grid.addWidget(text, i, 1)
        grid.setColumnStretch(1, 1)


# ------------------------------------------------------------------ 2. image overlay
class OverlayCanvas(QtWidgets.QWidget):
    hovered = QtCore.pyqtSignal(str)
    K = 2  # overlay supersampling

    def __init__(self):
        super().__init__()
        self.setMouseTracking(True)
        self.setMinimumHeight(500)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.pix = None
        self.P = None
        self.s = 0.0
        self.arrows = False
        self.max_points = 12000      # sparse by default: a solid blob of points hides the photo it is meant to be checked against
        self.keep = None
        self.opacity = .9
        self.overlay = None
        self._buf = None
        self.circle = None
        self.state = None

    def set_scene(self, image_bgr, P, ref, cand, circle):
        h, w = image_bgr.shape[:2]
        self.h, self.w = h, w
        q = QtGui.QImage(np.ascontiguousarray(image_bgr[:, :, ::-1]).data, w, h, w * 3, QtGui.QImage.Format_RGB888)
        self.pix = QtGui.QPixmap.fromImage(q.copy())
        self.P, self.ref, self.cand, self.circle = P, ref, cand, circle
        d = np.linalg.norm(P, axis=1)
        self.lo, self.hi = np.percentile(d, [5, 95])
        self.bins = np.clip((np.log(d) - np.log(self.lo)) / (np.log(self.hi) - np.log(self.lo)) * 255, 0, 255).astype(np.uint8)
        self.u0, self.v0, self.ok0 = project(P, ref, circle)
        self._choose_points()
        # true size of the proposed change
        u1, v1, ok1 = project(P, cand, circle)
        both = self.ok0 & ok1 & self._inside(self.u0, self.v0) & self._inside(u1, v1)
        sh = np.hypot(u1 - self.u0, v1 - self.v0)[both]
        self.real = (float(np.median(sh)), float(np.percentile(sh, 95)), float(sh.max())) if sh.size else None
        self.render(self.s)

    def _inside(self, u, v):
        return (u >= 0) & (u < self.w) & (v >= 0) & (v < self.h)

    def _choose_points(self):
        """The same random subset for every slider position, so points move instead of flickering in and out."""
        n = len(self.P)
        self.keep = np.zeros(n, bool)
        self.keep[np.random.default_rng(2).choice(n, min(self.max_points, n), replace=False)] = True
        kept = np.nonzero(self.keep)[0]
        self.sample = kept[np.random.default_rng(1).choice(len(kept), min(450, len(kept)), replace=False)]   # arrows

    def set_density(self, max_points):
        self.max_points = int(max_points)
        if self.P is not None:
            self._choose_points()
            self.render(self.s)

    def render(self, s):
        if self.P is None:
            return
        self.s = s
        c = blend(self.ref, self.cand, s)
        u, v, ok = project(self.P, c, self.circle)
        valid = ok & self._inside(u, v) & self.keep
        idx = np.nonzero(valid)[0]
        idx = idx[np.argsort(-np.linalg.norm(self.P[idx], axis=1))]
        k = self.K
        arr = np.zeros((self.h * k, self.w * k, 4), np.uint8)
        x, y = (u[idx] * k).astype(int), (v[idx] * k).astype(int)
        col = LUT[self.bins[idx]]
        dense = self.max_points >= 30000
        for dy in ((-1, 0, 1) if dense else (0, 1)):
            for dx in ((-1, 0, 1) if dense else (0, 1)):
                arr[np.clip(y + dy, 0, self.h * k - 1), np.clip(x + dx, 0, self.w * k - 1), :3] = col
                arr[np.clip(y + dy, 0, self.h * k - 1), np.clip(x + dx, 0, self.w * k - 1), 3] = 255
        self._buf = arr
        self.overlay = QtGui.QImage(arr.data, self.w * k, self.h * k, self.w * k * 4, QtGui.QImage.Format_RGBA8888)
        move = np.hypot(u - self.u0, v - self.v0)
        both = valid & self.ok0 & self._inside(self.u0, self.v0)
        self.state = (u, v, valid, move, both)
        self.update()

    def moved_stats(self):
        if not self.state:
            return None
        move, both = self.state[3], self.state[4]
        return (float(np.median(move[both])), float(np.percentile(move[both], 95))) if both.any() else None

    def _rect(self):
        scale = min(self.width() / self.w, self.height() / self.h)
        W, H = self.w * scale, self.h * scale
        return QtCore.QRectF((self.width() - W) / 2, (self.height() - H) / 2, W, H), scale

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHints(QtGui.QPainter.Antialiasing | QtGui.QPainter.SmoothPixmapTransform)
        p.fillRect(self.rect(), QtGui.QColor("#101114"))
        if self.pix is None:
            return
        rect, sc = self._rect()
        p.drawPixmap(rect, self.pix, QtCore.QRectF(self.pix.rect()))
        if self.overlay is not None:
            p.setOpacity(self.opacity)
            p.drawImage(rect, self.overlay)
            p.setOpacity(1)
        if self.circle:
            pen = QtGui.QPen(QtGui.QColor(255, 255, 255, 150), 1.2, QtCore.Qt.DashLine)
            p.setPen(pen)
            p.setBrush(QtCore.Qt.NoBrush)
            r = self.circle["radius"] * .97 * sc
            p.drawEllipse(QtCore.QPointF(rect.left() + self.circle["cx"] * sc, rect.top() + self.circle["cy"] * sc), r, r)
        if self.arrows and self.state:
            u, v, valid, move, both = self.state
            sel = self.sample[both[self.sample] & (move[self.sample] > .25)]
            p.setPen(QtGui.QPen(QtGui.QColor("#ff453a"), 2))
            for i in sel:
                a = QtCore.QPointF(rect.left() + self.u0[i] * sc, rect.top() + self.v0[i] * sc)
                b = QtCore.QPointF(rect.left() + u[i] * sc, rect.top() + v[i] * sc)
                p.drawLine(a, b)
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(QtGui.QColor("white"))
            for i in sel:
                p.drawEllipse(QtCore.QPointF(rect.left() + u[i] * sc, rect.top() + v[i] * sc), 2.2, 2.2)
        # distance legend
        lx, ly = rect.left() + 14, rect.bottom() - 30
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor(0, 0, 0, 150))
        p.drawRoundedRect(QtCore.QRectF(lx - 8, ly - 18, 176, 44), 8, 8)
        grad = QtGui.QLinearGradient(lx, 0, lx + 160, 0)
        for t in np.linspace(0, 1, 6):
            c = LUT[int(t * 255)]
            grad.setColorAt(float(t), QtGui.QColor(int(c[0]), int(c[1]), int(c[2])))
        p.setBrush(grad)
        p.drawRoundedRect(QtCore.QRectF(lx, ly, 160, 8), 4, 4)
        p.setPen(QtGui.QColor("white"))
        f = p.font()
        f.setPixelSize(12)
        p.setFont(f)
        p.drawText(QtCore.QPointF(lx, ly - 4), "LiDAR distance")
        p.drawText(QtCore.QPointF(lx, ly + 22), f"{self.lo:.0f} m")
        p.drawText(QtCore.QRectF(lx, ly + 10, 160, 16), QtCore.Qt.AlignRight, f"{self.hi:.0f} m")

    def mouseMoveEvent(self, e):
        if not self.state or self.pix is None:
            return
        rect, sc = self._rect()
        x, y = (e.x() - rect.left()) / sc, (e.y() - rect.top()) / sc
        u, v, valid, move, _ = self.state
        idx = np.nonzero(valid)[0]
        if not idx.size:
            return
        d2 = (u[idx] - x) ** 2 + (v[idx] - y) ** 2
        j = int(np.argmin(d2))
        if d2[j] > 25:
            self.hovered.emit("")
            return
        i = idx[j]
        dist = float(np.linalg.norm(self.P[i]))
        self.hovered.emit(f"LiDAR point {dist:.1f} m away · moved {move[i]:.2f} px from the current calibration")


def alignment_note(a):
    """(rich text, is_warning) describing how well the current calibration lines up with the captures."""
    if not a:
        return None
    lift, need = a["lift"], a["min_lift"]
    share = f"{a['share'] * 100:.1f} % of LiDAR edge points sit on a matching image edge, " if a.get("share") is not None else ""
    if lift >= need:
        return (f"<b>Alignment of the current calibration:</b> {share}{lift:.2f}× what chance would give "
                f"(the maintenance app asks for at least {need:g}×). It lines up with these captures.", False)
    fit = (f" Fitted on these same captures, the maintenance options reach {a['refined_lift']:.2f}× (not a held-out result)."
           if a.get("refined_lift") is not None else "")
    return (f"<b>The current calibration does not clearly line up with these captures.</b> {share}{lift:.2f}× what chance would give "
            f"(1.0× is no better than chance; the maintenance app asks for at least {need:g}×). Expect the points to look shifted "
            f"against the photo. “Keep” means no tested change was clearly better, not that the calibration is aligned.{fit}", True)


class OverlayCard(QtWidgets.QFrame):
    def __init__(self, captures, ref_cal, cand_cal, circle, accepted, options=None, alignment=None):
        super().__init__()
        self.setObjectName("card")
        self.captures = captures
        self.ref = cal_arrays(ref_cal) if ref_cal else None
        self.cand = cal_arrays(cand_cal)
        self.cand_main = self.cand
        self.options = dict(options or {})
        self.circle = circle
        self.cache = {}
        self.has_ref = self.ref is not None
        self.accepted = accepted
        if not self.has_ref:
            self.ref = self.cand
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(12)
        lay.addWidget(_label("See the change on the camera image", "headline"))
        lay.addWidget(_label(
            "Each dot is a real LiDAR point drawn on the real photo, coloured by distance (purple near, yellow far). Where the "
            "calibration is right, the dots of an object sit on that object in the photo. Drag the slider to morph from the "
            "current calibration to another one and watch how far points actually move.", "muted"))
        note = alignment_note(alignment)
        if note:
            text, warn = note
            box = _label(text, rich=True)
            box.setStyleSheet(f"background:{SOFT['warn' if warn else 'good']}; color:{INK}; border-radius:10px; padding:10px 14px;")
            lay.addWidget(box)

        top = QtWidgets.QHBoxLayout()
        top.setSpacing(12)
        top.addWidget(_inline("Capture"))
        self.combo = QtWidgets.QComboBox()
        for c in captures:
            self.combo.addItem(capture_label(c), str(c))
        self.combo.currentIndexChanged.connect(self.load_capture)
        top.addWidget(self.combo)
        top.addSpacing(12)
        self.target = QtWidgets.QComboBox()
        self.target.addItem("Fault-aware candidate", "fault")
        for key, (label, _cal) in self.options.items():
            self.target.addItem(label, key)
        if self.options:
            top.addWidget(_inline("Compare with"))
            top.addWidget(self.target)
            top.addSpacing(12)
            self.target.currentIndexChanged.connect(self.change_target)
        top.addWidget(_inline("Points"))
        self.density = QtWidgets.QComboBox()
        self.density.addItem("Sparse", 12000)
        self.density.addItem("Dense", 60000)
        self.density.currentIndexChanged.connect(lambda *_: self.canvas.set_density(self.density.currentData()))
        top.addWidget(self.density)
        top.addSpacing(12)
        top.addWidget(_inline("Magnify the change"))
        self.amp = QtWidgets.QComboBox()
        for a in (1, 5, 10, 25, 50):
            self.amp.addItem("×%d" % a + ("  (true size)" if a == 1 else ""), a)
        self.amp.currentIndexChanged.connect(self.changed)
        top.addWidget(self.amp)
        self.arrows = QtWidgets.QCheckBox("Show movement arrows")
        self.arrows.toggled.connect(self.flags)
        top.addWidget(self.arrows)
        top.addStretch(1)
        self.flick = QtWidgets.QPushButton("▶  Flicker")
        self.flick.setCheckable(True)
        self.flick.toggled.connect(self.flicker)
        top.addWidget(self.flick)
        lay.addLayout(top)

        srow = QtWidgets.QHBoxLayout()
        srow.setSpacing(12)
        start = _label("Current", "h3")
        start.setWordWrap(False)
        srow.addWidget(start)
        self.slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.valueChanged.connect(self.changed)
        srow.addWidget(self.slider, 1)
        self.end = _label("", "h3")
        self.end.setWordWrap(False)
        srow.addWidget(self.end)
        lay.addLayout(srow)
        self.state = _label("", "muted", rich=True)
        lay.addWidget(self.state)

        self.canvas = OverlayCanvas()
        self.canvas.hovered.connect(lambda t: self.hover.setText(t or "Hover over a dot for its distance and how far it moved."))
        lay.addWidget(self.canvas)
        self.hover = _label("Hover over a dot for its distance and how far it moved.", "footnote")
        lay.addWidget(self.hover)
        self.summary = _label("", "muted", rich=True)
        lay.addWidget(self.summary)

        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(650)
        self.timer.timeout.connect(self.tick)
        if not self.has_ref:
            for w in (self.slider, self.amp, self.arrows, self.flick, self.target):
                w.setEnabled(False)
            self.state.setText("No reference calibration was saved with this check, so the proposed calibration is shown on its own.")
        self._name_target()
        self.load_capture()

    def target_is_option(self):
        return self.target.currentData() != "fault"

    def _name_target(self):
        """Words for the calibration at the right end of the slider."""
        if self.target_is_option():
            self.target_name = f"the maintenance option “{self.target.currentText().replace('Maintenance: ', '')}”"
            self.end.setText("Option")
        else:
            self.target_name = "the proposed calibration"
            self.end.setText("Proposed" + ("" if self.accepted else " (not accepted)"))

    def change_target(self, *_):
        key = self.target.currentData()
        self.cand = self.cand_main if key == "fault" else self.options[key][1]
        self._name_target()
        self.load_capture()

    def load_capture(self, *_):
        path = self.combo.currentData()
        if path not in self.cache:
            z = np.load(path)
            P = z["xyz_mm"].astype(np.float64) / 1000.0
            if len(P) > 60000:
                P = P[np.random.default_rng(0).choice(len(P), 60000, replace=False)]
            self.cache = {path: (np.array(z["image"]), P)}
        image, P = self.cache[path]
        if len(P) < 2 or not np.isfinite(P).all():
            # Nothing to draw (and the distance scale needs points): say so instead of failing inside the figure.
            self.canvas.P = None
            self.canvas.pix = None
            self.canvas.update()
            self.summary.setText("This capture has no usable LiDAR points, so there is nothing to draw on its photo.")
            self.state.setText("")
            return
        self.canvas.set_scene(image, P, self.ref, self.cand, self.circle)
        self.changed()
        real = self.canvas.real
        if real and self.has_ref:
            med, p95, mx = real
            word = ("practically invisible" if p95 < 1 else "small" if p95 < 3 else "clearly visible" if p95 < 8 else "large")
            self.summary.setText(
                f"<b>Size of this change:</b> a typical point moves <b>{med:.2f} px</b>, 95 % of points move less than "
                f"<b>{p95:.2f} px</b> (largest {mx:.1f} px) on a {self.canvas.w}×{self.canvas.h} image. That is {word}. "
                f"<span style='color:{MUTED}'>This is only how far the change moves points; it does not say whether the current "
                f"calibration lines up. Points outside the dashed circle are not scored.</span>")
        else:
            self.summary.setText("")

    def scale(self):
        return self.slider.value() / 100.0 * float(self.amp.currentData())

    def changed(self, *_):
        a = float(self.amp.currentData())
        s = self.scale()
        self.canvas.render(s)
        if not self.has_ref or self.canvas.P is None:
            return
        if self.slider.value() == 0:
            txt = "Showing the <b>current calibration</b>."
        else:
            frac = self.slider.value()
            txt = f"Showing <b>{frac} %</b> of the way to {self.target_name}"
            if a > 1:
                txt += f", <b style='color:{WARN}'>magnified ×{a:g}</b> so small shifts are visible. This is not the real size."
            elif frac == 100:
                txt = f"Showing <b>{self.target_name}</b> at its true size."
            else:
                txt += "."
        st = self.canvas.moved_stats()
        if st and self.slider.value():
            txt += f" Points have moved by a median of <b>{st[0]:.2f} px</b> (95 % under {st[1]:.2f} px)."
        self.state.setText(txt)

    def flags(self, *_):
        self.canvas.arrows = self.arrows.isChecked()
        self.canvas.update()

    def flicker(self, on):
        self.flick.setText("■  Stop" if on else "▶  Flicker")
        if on:
            self.slider.setValue(0)
            self.timer.start()
        else:
            self.timer.stop()

    def tick(self):
        self.slider.setValue(0 if self.slider.value() else 100)

    def hideEvent(self, e):
        self.timer.stop()
        super().hideEvent(e)


# ------------------------------------------------------------------ 3. gain chart
class GainChart(QtWidgets.QWidget):
    LEFT, RIGHT, TOP, ROW, AXIS = 200, 70, 38, 40, 44

    def __init__(self, rows, gate):
        super().__init__()
        self.rows, self.gate, self.mode = rows, gate, "gain"
        self.hover = -1
        self.setMouseTracking(True)
        self.setMinimumHeight(self.TOP + self.ROW * len(rows) + self.AXIS)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)

    def set_mode(self, mode):
        self.mode = mode
        self.update()

    def _vals(self, row):
        if self.mode == "gain":
            return row["gain"], [f["gain"] for f in row["folds"]]
        return row["px"], [f["px"] for f in row["folds"]]

    def _range(self):
        allv = []
        for r in self.rows:
            v, d = self._vals(r)
            allv += [x for x in [v] + d if x is not None]
        if self.mode == "gain":
            hi = max(allv + [self.gate or 0, .5]) * 1.18
            lo = min(allv + [0]) * 1.18
            lo = min(lo, -hi * .06)
        else:
            lo, hi = 0, max(allv) * 1.08
        return lo, hi

    def _x(self, v, lo, hi):
        w = self.width() - self.LEFT - self.RIGHT
        return self.LEFT + (v - lo) / (hi - lo) * w

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        lo, hi = self._range()
        f = p.font()
        f.setPixelSize(13)
        p.setFont(f)
        gain = self.mode == "gain"
        bottom = self.TOP + self.ROW * len(self.rows)
        for t in _nice_ticks(lo, hi):
            x = self._x(t, lo, hi)
            p.setPen(QtGui.QPen(QtGui.QColor(LINE), 1))
            p.drawLine(QtCore.QPointF(x, self.TOP - 6), QtCore.QPointF(x, bottom))
            p.setPen(QtGui.QColor(MUTED))
            p.drawText(QtCore.QRectF(x - 30, bottom + 4, 60, 18), QtCore.Qt.AlignCenter, f"{t:g}" + (" %" if gain else ""))
        p.setPen(QtGui.QColor(MUTED))
        f2 = p.font()
        f2.setPixelSize(12)
        p.setFont(f2)
        p.drawText(QtCore.QRectF(self.LEFT, bottom + 24, self.width() - self.LEFT - self.RIGHT, 18), QtCore.Qt.AlignCenter,
                   "Improvement in held-out error vs keeping the current calibration   (further right is better)" if gain
                   else "Typical distance from a LiDAR edge to the nearest image edge, in pixels   (smaller is better)")
        p.setFont(f)
        z = self._x(0, lo, hi) if gain else self._x(self.rows[0]["px"], lo, hi)
        p.setPen(QtGui.QPen(QtGui.QColor("#8e8e93"), 1.5))
        p.drawLine(QtCore.QPointF(z, self.TOP - 6), QtCore.QPointF(z, bottom))
        p.setPen(QtGui.QColor(MUTED))
        p.drawText(QtCore.QRectF(z - 184, 8, 180, 18), QtCore.Qt.AlignRight, "keeping current" if gain else "current calibration")
        if gain and self.gate:
            gx = self._x(self.gate, lo, hi)
            p.setPen(QtGui.QPen(QtGui.QColor(WARN), 1.5, QtCore.Qt.DashLine))
            p.drawLine(QtCore.QPointF(gx, self.TOP - 6), QtCore.QPointF(gx, bottom))
            p.setPen(QtGui.QColor(WARN))
            p.drawText(QtCore.QRectF(gx + 4, 8, 180, 18), QtCore.Qt.AlignLeft, f"needed to update: {self.gate:g} %")
        for i, r in enumerate(self.rows):
            y = self.TOP + i * self.ROW
            if i == self.hover:
                p.fillRect(QtCore.QRectF(0, y, self.width(), self.ROW), QtGui.QColor("#f5f7fb"))
            val, dots = self._vals(r)
            p.setPen(QtGui.QColor(INK))
            fb = p.font()
            fb.setBold(r["best"])
            p.setFont(fb)
            p.drawText(QtCore.QRectF(8, y, self.LEFT - 16, self.ROW), QtCore.Qt.AlignVCenter | QtCore.Qt.AlignRight, r["name"])
            p.setFont(f)
            if val is None:
                continue
            x0 = self._x(0 if gain else lo, lo, hi)
            x1 = self._x(val, lo, hi)
            col = QtGui.QColor("#8e8e93") if r["keep"] else QtGui.QColor(BLUE if r["best"] else BLUE_BAR)
            if gain and val < 0 and not r["keep"]:
                col = QtGui.QColor("#ffb3ba")
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(col)
            bar = QtCore.QRectF(min(x0, x1), y + 10, max(abs(x1 - x0), 2), self.ROW - 20)
            p.drawRoundedRect(bar, 4, 4)
            p.setPen(QtGui.QColor(INK))
            tx = max([x0, x1] + [self._x(d, lo, hi) for d in dots if d is not None]) + 12
            p.drawText(QtCore.QRectF(tx, y, 80, self.ROW), QtCore.Qt.AlignVCenter,
                       f"{val:+.2f} %" if gain and not r["keep"] else (f"{val:.2f} px" if not gain else "baseline"))
            for d in dots:
                if d is None:
                    continue
                p.setPen(QtGui.QPen(QtGui.QColor("white"), 1.5))
                p.setBrush(QtGui.QColor(INK))
                p.drawEllipse(QtCore.QPointF(self._x(d, lo, hi), y + self.ROW / 2), 4.2, 4.2)

    def _row_at(self, y):
        i = int((y - self.TOP) // self.ROW)
        return i if 0 <= i < len(self.rows) else -1

    def leaveEvent(self, _):
        self.hover = -1
        self.update()

    def mouseMoveEvent(self, e):
        i = self._row_at(e.y())
        if i != self.hover:
            self.hover = i
            self.update()
        if i < 0:
            return QtWidgets.QToolTip.hideText()
        r = self.rows[i]
        lo, hi = self._range()
        _, dots = self._vals(r)
        yc = self.TOP + i * self.ROW + self.ROW / 2
        for d, fold in zip(dots, r["folds"]):
            if d is not None and abs(self._x(d, lo, hi) - e.x()) < 8 and abs(yc - e.y()) < 12:
                txt = (f"<b>Held-out capture {fold['label']}</b><br>{r['name']}: "
                       f"{fold['gain']:+.2f} % vs keeping current<br>edge error {fold['px']:.2f} px")
                return QtWidgets.QToolTip.showText(e.globalPos(), txt, self)
        if r["keep"]:
            txt = f"<b>Keep current</b><br>held-out loss {r['loss']:.4f}<br>typical edge error {r['px']:.2f} px"
        else:
            txt = (f"<b>{r['name']}</b><br>held-out loss {r['loss']:.4f}<br>{r['gain']:+.2f} % vs keeping current<br>"
                   f"typical edge error {r['px']:.2f} px<br>better on {r['wins']} of {len(r['folds'])} held-out captures")
        QtWidgets.QToolTip.showText(e.globalPos(), txt, self)


def _dict(value):
    return value if isinstance(value, dict) else {}


def gain_rows(r):
    r = _dict(r)
    diag = _dict(r.get("diagnostics"))
    dec = _dict(diag.get("decision"))
    losses = _dict(dec.get("mean_losses"))
    folds = _dict(_dict(r.get("validation")).get("folds"))
    if not losses or "KEEP" not in losses:
        return [], None
    keep = losses["KEEP"]
    kf = {f["test_id"]: f.get("metrics") or {} for f in folds.get("KEEP", [])}
    rows = []
    for k, loss in losses.items():
        fl = []
        for f in folds.get(k, []):
            m = f.get("metrics") or {}
            base = kf.get(f["test_id"], {})
            g = (base["loss"] - m["loss"]) / base["loss"] * 100 if base.get("loss") and "loss" in m else None
            fl.append(dict(label=str(f["test_id"]).split("_")[0][:2] + ":" + str(f["test_id"])[2:4] + ":" + str(f["test_id"])[4:6],
                           gain=g, px=m.get("capped_edge_rmse_px")))
        pxs = [f["px"] for f in fl if f["px"] is not None]
        rows.append(dict(key=k, name=HYP.get(k, k), loss=loss, gain=(keep - loss) / keep * 100, keep=k == "KEEP",
                         best=k == dec.get("candidate_hypothesis"), folds=fl, px=float(np.mean(pxs)) if pxs else None,
                         wins=sum(1 for f in fl if f["gain"] is not None and f["gain"] > 0)))
    rows.sort(key=lambda x: (not x["keep"], -x["gain"]))
    gate = dec.get("thresholds", {}).get("min_relative_gain")
    return rows, (gate * 100 if gate is not None else None)


# ------------------------------------------------------------------ 4. observability
class SingularBars(QtWidgets.QWidget):
    """Log-scale bars: one per direction; solid when it clears the declared visibility line."""
    LEFT, ROW = 100, 22

    def __init__(self, values, line):
        super().__init__()
        self.values, self.line = list(values), line
        self.setMouseTracking(True)
        self.setFixedHeight(self.ROW * max(len(self.values), 1) + 22)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)

    def _x(self, v):
        lo, hi = math.log10(.002), math.log10(1.2)
        w = self.width() - self.LEFT - 60
        return self.LEFT + (min(max(math.log10(max(v, 1e-9)), lo), hi) - lo) / (hi - lo) * w

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        f = p.font()
        f.setPixelSize(12)
        p.setFont(f)
        gx = self._x(self.line)
        for i, v in enumerate(self.values):
            y = i * self.ROW + 3
            seen = v >= self.line
            p.setPen(QtGui.QColor(MUTED))
            p.drawText(QtCore.QRectF(0, y, self.LEFT - 10, self.ROW - 6), QtCore.Qt.AlignVCenter | QtCore.Qt.AlignRight,
                       f"direction {i + 1}")
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(QtGui.QColor(GOOD if seen else "#d2d2d7"))
            p.drawRoundedRect(QtCore.QRectF(self.LEFT, y + 2, max(self._x(v) - self.LEFT, 2), self.ROW - 10), 3, 3)
            p.setPen(QtGui.QColor(INK if seen else MUTED))
            p.drawText(QtCore.QRectF(self._x(v) + 6, y, 70, self.ROW - 6), QtCore.Qt.AlignVCenter, f"{v:.3f}")
        p.setPen(QtGui.QPen(QtGui.QColor(WARN), 1.5, QtCore.Qt.DashLine))
        p.drawLine(QtCore.QPointF(gx, 0), QtCore.QPointF(gx, self.height() - 18))
        p.setPen(QtGui.QColor(WARN))
        p.drawText(QtCore.QRectF(gx - 60, self.height() - 17, 120, 16), QtCore.Qt.AlignCenter, f"seen if beyond {self.line:g}")

    def mouseMoveEvent(self, e):
        i = int(e.y() // self.ROW)
        if 0 <= i < len(self.values):
            v = self.values[i]
            txt = (f"Direction {i + 1}: strength {v:.4f}<br>" +
                   ("beyond the line, so the data can tell it apart from the other groups" if v >= self.line
                    else "below the line, so the data cannot reliably separate it from the other groups"))
            QtWidgets.QToolTip.showText(e.globalPos(), txt, self)


class SupportStrip(QtWidgets.QWidget):
    def __init__(self, vals):
        super().__init__()
        self.vals = list(vals)
        self.setFixedHeight(34)
        self.setMouseTracking(True)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)

    def _cell(self):
        return min(46, (self.width() - 4) / max(len(self.vals), 1))

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        c = self._cell()
        for i, v in enumerate(self.vals):
            col = GOOD if v >= .999 else (WARN if v > .05 else "#d2d2d7")
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(QtGui.QColor(col))
            p.drawRoundedRect(QtCore.QRectF(2 + i * c, 4, c - 5, 26), 5, 5)

    def mouseMoveEvent(self, e):
        i = int((e.x() - 2) // self._cell())
        if 0 <= i < len(self.vals):
            v = self.vals[i]
            txt = ("agreed on by every re-analysis" if v >= .999 else "only some re-analyses agree" if v > .05 else "not seen in any re-analysis")
            QtWidgets.QToolTip.showText(e.globalPos(), f"Combined direction {i + 1}: {v * 100:.0f} % agreement, {txt}", self)


def observability_widget(r):
    diag = r.get("diagnostics") or {}
    ob = diag.get("observability") or {}
    groups = ob.get("groups") or {}
    if not groups:
        return None
    line = (diag.get("configuration") or {}).get("minimum_singular", .02)
    attr = diag.get("attribution") or {}
    box = QtWidgets.QWidget()
    lay = QtWidgets.QVBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(10)
    for k in ("R", "T", "I"):
        g = groups.get(k)
        if not g:
            continue
        vals = g.get("unique_singular_values") or []
        seen = sum(1 for v in vals if v >= line)
        col = GOOD if seen == len(vals) else (WARN if seen else BAD)
        frac = (attr.get(k) or {}).get("candidate_update_supported_fraction")
        extra = f" · {frac * 100:.0f} % of the proposed change is in seen directions" if frac is not None else ""
        lay.addWidget(_label(f"<b>{GROUP[k]}</b> &nbsp;<span style='color:{col}'><b>{seen} of {len(vals)}</b> directions seen on their own</span>"
                             f"<span style='color:{MUTED}; font-size:13px;'>{extra}</span>", rich=True))
        lay.addWidget(SingularBars(vals, line))
    pw = ob.get("pairwise") or {}
    if pw:
        lay.addSpacing(4)
        lay.addWidget(_label("<b>Which changes could be mistaken for each other?</b><br><span style='color:%s; font-size:13px;'>"
                             "The smaller the angle, the more two kinds of error look alike in these captures." % MUTED, rich=True))
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(8)
        for key, v in pw.items():
            a, b = key.split("|")
            ang = min(v.get("principal_angles_deg") or [90])
            fg, bg, word = ((BAD, SOFT["bad"], "almost indistinguishable") if ang < 5 else
                            (WARN, SOFT["warn"], "partly overlap") if ang < 15 else (GOOD, SOFT["good"], "can be told apart"))
            chip = QtWidgets.QFrame()
            chip.setStyleSheet(f"QFrame{{background:{bg}; border-radius:10px;}} QLabel{{background:transparent;}}")
            cl = QtWidgets.QVBoxLayout(chip)
            cl.setContentsMargins(14, 10, 14, 10)
            cl.setSpacing(2)
            cl.addWidget(_label(f"{GROUP[a]} ↔ {GROUP[b]}", "h3"))
            t = _label(f"<span style='color:{fg}; font-size:20px; font-weight:600'>{ang:.1f}°</span><br>"
                       f"<span style='color:{fg}; font-size:13px'>{word}</span>", rich=True)
            cl.addWidget(t)
            chip.setToolTip(f"Smallest angle between what {GROUP[a].lower()} and {GROUP[b].lower()} changes do to the edge "
                            f"alignment: {ang:.1f}°. Under 5° the two cannot be separated reliably.")
            row.addWidget(chip, 1)
        lay.addLayout(row)
    ss = diag.get("stable_support") or {}
    cons = (ss.get("diagnostics") or {}).get("consensus_eigenvalues") or []
    if cons:
        full = sum(1 for v in cons if v >= .999)
        lay.addSpacing(4)
        lay.addWidget(_label(f"<b>Combined directions that every re-analysis agrees on:</b> {full} of {len(cons)}<br>"
                             f"<span style='color:{MUTED}; font-size:13px;'>The analysis is re-run with different edge matchings; a combination is trusted only if it is seen "
                             f"every time. Green = always, amber = sometimes, grey = never.</span>", rich=True))
        lay.addWidget(SupportStrip(cons))
    return box


# ------------------------------------------------------------------ container
class ResultVisuals(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.lay = QtWidgets.QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(16)

    def clear(self):
        while self.lay.count():
            it = self.lay.takeAt(0)
            w = it.widget()
            if w:
                w.hide()
                w.deleteLater()

    def set_result(self, folder, r, reference=None):
        self.clear()
        steps = (self._checks, self._overlay, self._gain, self._observability)
        for build in steps:
            try:
                card = build(Path(folder), r, reference)
            except Exception as err:  # noqa: BLE001  one broken card must not hide the others
                card = None
                print(f"[result_visuals] {build.__name__}: {err}")
            if card is not None:
                self.lay.addWidget(card)
        self.setVisible(self.lay.count() > 0)

    # -- cards
    def _checks(self, folder, r, reference):
        checks = build_checks(r)
        if not checks:
            return None
        n = lambda s: sum(1 for c in checks if c[0] == s)  # noqa: E731
        card, lay = _card("Why this verdict, and what could not be checked",
                          f"{n('pass')} passed · {n('fail')} failed · {n('na')} cannot be checked with this data. "
                          "A calibration is only changed when every check that can be run has passed.")
        lay.addWidget(Checklist(checks))
        return card

    def _overlay(self, folder, r, reference):
        caps = sorted(folder.rglob("stacked/data/*.npz"))
        if not caps:
            return None
        diag = r.get("diagnostics") or {}
        cand = diag.get("candidate_calibration") or r.get("updated_calibration")
        if not cand:
            return None
        circle = (diag.get("input") or {}).get("evaluation_domain", {}).get("circle")
        accepted = r.get("status") in ("UPDATE_SUPPORTED", "INITIAL_CALIBRATION_CANDIDATE")
        ref = reference if reference is not None else (r.get("updated_calibration") if not accepted else None)
        return OverlayCard(caps, ref, cand, circle, accepted, review_options(folder), review_alignment(folder))

    def _gain(self, folder, r, reference):
        rows, gate = gain_rows(r)
        if not rows:
            return None
        card, lay = _card("Is the proposed change worth making?",
                          "Every explanation of what might have changed is tested on captures it was not fitted to. "
                          "Each bar is the average; each dot is one held-out capture. A change is made only when the bar passes the dashed line.")
        top = QtWidgets.QHBoxLayout()
        chart = GainChart(rows, gate)
        top.addWidget(_seg([("gain", "Improvement %"), ("px", "Edge error (px)")], chart.set_mode))
        top.addStretch(1)
        lay.addLayout(top)
        lay.addWidget(chart)
        best = next((x for x in rows if x["best"] and not x["keep"]), None)
        if best and gate is not None:
            verdict = ("clears" if best["gain"] >= gate else "does not reach")
            gains = [f["gain"] for f in best["folds"] if f["gain"] is not None]
            spread = ""
            if len(gains) > 1:
                lo, hi = min(gains), max(gains)
                spread = (f" Held-out captures disagree: its gain ranges from {lo:+.1f} % to {hi:+.1f} %"
                          + (", so the average cannot be told apart from no change." if lo < 0 < hi else "."))
            lay.addWidget(_label(
                f"<b>Reading it:</b> the best option, “{best['name']}”, improves held-out error by {best['gain']:.2f} %, which "
                f"{verdict} the {gate:g} % needed. In pixels, the typical edge mismatch is about {rows[0]['px']:.1f} px with the current "
                f"calibration and {best['px']:.1f} px with “{best['name']}”.{spread} "
                f"<span style='color:{MUTED}'>Scores use a nearest-edge proxy, not true reprojection error.</span>", rich=True))
        return card

    def _observability(self, folder, r, reference):
        body = observability_widget(r)
        if body is None:
            return None
        card, lay = _card("What can these captures actually tell apart?",
                          "A calibration can only be corrected along directions the data is sensitive to. Where two kinds of error "
                          "look alike, the app cannot say which one happened, so it does not guess.")
        lay.addWidget(body)
        return card
