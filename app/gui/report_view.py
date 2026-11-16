"""Report tab: the written account of a check, laid out as a readable page instead of the raw report.md.

Built from the saved assessment (assessment.json), so everything is real data: the verdict, how the explanations compared, what
the data could see, the proposed and accepted changes, the inputs and the limits of the assessment. When the maintenance
comparison exists its headline is added. The page can be saved as a PDF (the page itself is rendered, so the PDF looks like
the screen), its summary copied, and the original report.md opened.
"""
from __future__ import annotations

import math
import os
from datetime import datetime
from pathlib import Path

from PyQt5 import QtCore, QtGui, QtPrintSupport, QtWidgets
from PyQt5.QtCore import Qt

import review_adapter as ra
from result_visuals import HYP, GROUP, gain_rows
from ui_common import open_path

BLUE, GOOD, WARN, BAD = "#007aff", "#248a3d", "#9b6500", "#d70015"
SOFT = dict(blue="#edf5ff", good="#eaf6ed", warn="#fff6e5", bad="#fff0f1", grey="#eeeef2")
INK, MUTED, LINE = "#1d1d1f", "#6e6e73", "#e5e5ea"
MONO = '"Cascadia Mono", Consolas, monospace'

ACTION = {
    "KEEP_REFERENCE": "Keep your current calibration.",
    "KEEP_REFERENCE_AND_COLLECT_MORE_DIVERSE_CAPTURES": "Keep your current calibration, and collect more varied captures before checking again.",
    "REVIEW_SUPPORTED_CANDIDATE": "Review the supported candidate before using it.",
}
UNCERTAINTY = {
    "INSUFFICIENT_CLUSTER_RANK": "Error bars could not be estimated: too few independent capture groups.",
    "CONDITIONAL_ONLY": "Error bars are conditional on the matched edges and the selected directions.",
}


def num(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _label(text="", name=None, rich=False, wrap=True):
    w = QtWidgets.QLabel(text)
    if name:
        w.setObjectName(name)
    w.setWordWrap(wrap)
    if rich:
        w.setTextFormat(Qt.RichText)
    return w


def _card(title=None, blurb=None):
    f = QtWidgets.QFrame()
    f.setObjectName("card")
    lay = QtWidgets.QVBoxLayout(f)
    lay.setContentsMargins(24, 20, 24, 22)
    lay.setSpacing(12)
    if title:
        lay.addWidget(_label(title, "headline"))
    if blurb:
        lay.addWidget(_label(blurb, "muted"))
    return f, lay


def _tile(title, value, sub, tone=INK):
    f = QtWidgets.QFrame()
    f.setObjectName("tile")
    lay = QtWidgets.QVBoxLayout(f)
    lay.setContentsMargins(16, 14, 16, 14)
    lay.setSpacing(3)
    lay.addWidget(_label(title, "muted"))
    v = _label(value, wrap=False)
    v.setStyleSheet(f"font-size: 24px; font-weight: 600; color: {tone};")
    lay.addWidget(v)
    lay.addWidget(_label(sub, "footnote"))
    return f


def _chip(text, fg, bg):
    c = QtWidgets.QLabel(text)
    c.setStyleSheet(f"background: {bg}; color: {fg}; border-radius: 11px; padding: 3px 12px; font-size: 13px; font-weight: 600;")
    return c


def _table(headers, rows, aligns, widths=None):
    """A read-only table sized to its content; aligns: 'l' / 'r' / 'c' per column."""
    t = QtWidgets.QTableWidget(len(rows), len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.verticalHeader().hide()
    t.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
    t.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
    t.setFocusPolicy(Qt.NoFocus)
    t.setShowGrid(False)
    t.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    t.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    head = t.horizontalHeader()
    head.setHighlightSections(False)
    head.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
    for c in range(1, len(headers)):
        head.setSectionResizeMode(c, QtWidgets.QHeaderView.Fixed)
        t.setColumnWidth(c, (widths or {}).get(c, 150))
    mono = QtGui.QFont("Cascadia Mono")
    mono.setStyleHint(QtGui.QFont.Monospace)
    mono.setPixelSize(13)
    for r, row in enumerate(rows):
        for c, cell in enumerate(row):
            text, color, bold, use_mono = (cell + (None, False, False))[:4] if isinstance(cell, tuple) else (cell, None, False, False)
            it = QtWidgets.QTableWidgetItem(str(text))
            it.setTextAlignment({"l": Qt.AlignLeft, "r": Qt.AlignRight, "c": Qt.AlignCenter}[aligns[c]] | Qt.AlignVCenter)
            if color:
                it.setForeground(QtGui.QColor(color))
            f = QtGui.QFont(mono if use_mono else t.font())
            f.setBold(bool(bold))
            it.setFont(f)
            t.setItem(r, c, it)
        t.setRowHeight(r, 38)
    for c, h in enumerate(headers):
        it = t.horizontalHeaderItem(c)
        it.setTextAlignment({"l": Qt.AlignLeft, "r": Qt.AlignRight, "c": Qt.AlignCenter}[aligns[c]] | Qt.AlignVCenter)
    t.setFixedHeight(t.horizontalHeader().height() + 38 * len(rows) + 6)
    return t


class GainBarDelegate(QtWidgets.QStyledItemDelegate):
    """A small diverging bar around zero (right = better than keeping the current calibration) with the value."""

    def __init__(self, scale, parent=None):
        super().__init__(parent)
        self.scale = max(scale, 0.5)

    def paint(self, p, option, index):
        value = index.data(Qt.UserRole)
        p.save()
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        r = QtCore.QRectF(option.rect).adjusted(8, 10, -64, -10)
        mid = r.center().x()
        p.setPen(Qt.NoPen)
        p.setBrush(QtGui.QColor("#f0f0f4"))
        p.drawRoundedRect(r, 4, 4)
        if value is not None:
            half = r.width() / 2
            w = min(abs(value) / self.scale, 1.0) * half
            p.setBrush(QtGui.QColor("#9cc7ff" if value >= 0 else "#ffb3ba"))
            p.drawRoundedRect(QtCore.QRectF(mid if value >= 0 else mid - w, r.top(), max(w, 2), r.height()), 4, 4)
        p.setPen(QtGui.QPen(QtGui.QColor("#8e8e93"), 1))
        p.drawLine(QtCore.QPointF(mid, r.top() - 3), QtCore.QPointF(mid, r.bottom() + 3))
        f = p.font()
        f.setPixelSize(13)
        p.setFont(f)
        p.setPen(QtGui.QColor(INK if value is not None else MUTED))
        p.drawText(QtCore.QRectF(option.rect.right() - 60, option.rect.top(), 54, option.rect.height()), Qt.AlignRight | Qt.AlignVCenter,
                   f"{value:+.2f} %" if value is not None else "–")
        p.restore()


class ReportView(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.folder = self.result = self.status = self.review = None
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.body = QtWidgets.QWidget()
        self.body.setObjectName("page")
        self.lay = QtWidgets.QVBoxLayout(self.body)
        self.lay.setContentsMargins(0, 0, 12, 0)
        self.lay.setSpacing(16)
        self.scroll.setWidget(self.body)
        outer.addWidget(self.scroll)
        self.clear()

    # ---------------------------------------------------------------- public
    def clear(self, message="Open a finished check to read its report here."):
        self.folder = self.result = self.status = self.review = None
        self._reset()
        card, lay = _card("Report", message)
        self.lay.addWidget(card)
        self.lay.addStretch(1)

    def set_result(self, folder, result, status, names=None, units=None, review=None):
        """status: (title, colour, soft background, meaning). names/units: parameter labels and display units."""
        self.folder, self.result, self.status, self.review = Path(folder), result if isinstance(result, dict) else {}, status, review
        self.names, self.units = names or {}, units or {}
        self.rebuild()

    def set_review(self, summary):
        """The maintenance comparison's saved summary (or None); only its headline card changes."""
        if self.folder is not None:
            self.review = summary
            self.rebuild()

    # ---------------------------------------------------------------- building
    def _reset(self):
        while self.lay.count():
            item = self.lay.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()

    def rebuild(self):
        self._reset()
        for build in (self._hero, self._glance, self._compare, self._seen, self._changes, self._review_card, self._inputs, self._limits):
            try:
                widget = build()
            except Exception as err:  # noqa: BLE001 - one damaged section must not blank the report
                widget = None
                import logging
                logging.getLogger("faultaware").warning("Report section %s: %s", build.__name__, err)
            if widget is not None:
                self.lay.addWidget(widget)
        self.lay.addStretch(1)

    @property
    def diag(self):
        d = self.result.get("diagnostics")
        return d if isinstance(d, dict) else {}

    @property
    def decision(self):
        d = self.diag.get("decision")
        return d if isinstance(d, dict) else {}

    def _hero(self):
        title, color, soft, meaning = self.status or (str(self.result.get("status", "Report")).replace("_", " ").capitalize(), MUTED, SOFT["grey"], "")
        box = QtWidgets.QFrame()
        box.setStyleSheet(f"QFrame#hero {{ background: {soft}; border-radius: 16px; }} QLabel {{ background: transparent; }}")
        box.setObjectName("hero")
        lay = QtWidgets.QVBoxLayout(box)
        lay.setContentsMargins(26, 20, 26, 20)
        lay.setSpacing(6)
        top = QtWidgets.QHBoxLayout()
        top.addWidget(_label("FAULT-AWARE CALIBRATION REPORT", "caps"), 1)
        for text, tip, slot in (("Save as PDF…", "Save this page as a PDF", self.save_pdf), ("Copy summary", "Copy the key results as text", self.copy_summary),
                                ("Open report.md", "The raw report written by the assessment", self.open_md),
                                ("Show in folder", "Open this check's folder", self.show_folder)):
            b = QtWidgets.QPushButton(text)
            b.setToolTip(tip)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, s=slot: s())
            top.addWidget(b)
        lay.addLayout(top)
        t = _label(title)
        t.setStyleSheet(f"color: {color}; font-size: 26px; font-weight: 700;")
        lay.addWidget(t)
        action = ACTION.get(self.result.get("recommended_action"), "")
        lay.addWidget(_label(meaning + (f" {self.decision.get('reason')}" if self.decision.get("reason") else ""), "muted"))
        if action:
            a = _label(f"<b>What to do:</b> {action}", rich=True)
            a.setStyleSheet(f"color: {INK}; font-size: 15px;")
            lay.addWidget(a)
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(8)
        caps = (self.diag.get("input") or {}).get("captures") if isinstance(self.diag.get("input"), dict) else None
        facts = [("Method", str(self.diag.get("strategy") or "–").replace("_", " ")), ("Captures", str(len(caps)) if isinstance(caps, list) else "–")]
        sha = (self.diag.get("input") or {}).get("reference_sha256") if isinstance(self.diag.get("input"), dict) else None
        if sha:
            facts.append(("Reference", str(sha)[:12]))
        try:
            facts.append(("Made", datetime.fromtimestamp((self.folder / "assessment.json").stat().st_mtime).strftime("%d %b %Y, %H:%M")))
        except OSError:
            pass
        for k, v in facts:
            chip = _chip(f"{k}: {v}", INK, "rgba(255,255,255,0.7)")
            if k == "Reference":
                chip.setToolTip(f"SHA-256 of the reference calibration: {sha}")
            row.addWidget(chip)
        row.addStretch(1)
        lay.addSpacing(4)
        lay.addLayout(row)
        return box

    def _glance(self):
        r, dec = self.result, self.decision
        if r.get("status") == "INITIAL_CALIBRATION_CANDIDATE":
            init = self.diag.get("initialization") or {}
            tiles = [("Estimate", "Not validated", "All captures were used to estimate it", WARN),
                     ("Self-check label", str(init.get("inherited_heuristic_label") or "–").title(), "A heuristic from the initializer", INK)]
        else:
            best, gate = num(dec.get("best_relative_gain")), num((dec.get("thresholds") or {}).get("min_relative_gain") if isinstance(dec.get("thresholds"), dict) else None)
            outer = (r.get("validation") or {}).get("outer_test") if isinstance(r.get("validation"), dict) else None
            tests = (outer or {}).get("test_ids") or []
            gain = num((outer or {}).get("relative_gain"))
            observable = r.get("observable_parameters") if isinstance(r.get("observable_parameters"), list) else []
            unc = r.get("uncertainty") if isinstance(r.get("uncertainty"), dict) else {}
            tiles = [("Best improvement", f"{best * 100:.2f} %" if best is not None else "–",
                      (f"needs at least {gate * 100:.0f} %" + (" (met; other checks still apply)" if best is not None and best >= gate else ""))
                      if gate is not None else "over keeping the current calibration", INK),
                     ("Final independent test", "Not run" if not tests else ("Passed" if (outer or {}).get("passed") else "Not passed"),
                      "no captures were kept aside" if not tests else (f"gain {gain * 100:.2f} %" if gain is not None else "could not be scored"), MUTED if not tests else INK),
                     ("Directions seen", str(len(observable)), ", ".join(observable) if observable else "none on their own", INK),
                     ("Error bars", "Unavailable" if "INSUFFICIENT" in str(unc.get("status", "")) else "Conditional",
                      f"{unc.get('clusters', '?')} capture groups", WARN if "INSUFFICIENT" in str(unc.get("status", "")) else INK)]
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(12)
        for t in tiles:
            row.addWidget(_tile(*t), 1)
        w = QtWidgets.QWidget()
        w.setLayout(row)
        row.setContentsMargins(0, 0, 0, 0)
        return w

    def _compare(self):
        rows, gate = gain_rows(self.result)
        if not rows:
            return None
        card, lay = _card("How the explanations compared",
                          "Each explanation of what might have changed was refitted with one capture held out and scored on it. Edge error is the typical "
                          "distance from a LiDAR edge to the nearest image edge; the bar shows the improvement over keeping the current calibration.")
        chosen = self.decision.get("candidate_hypothesis")
        data = []
        for r in rows:
            n = len(r["folds"])
            tag = "baseline" if r["keep"] else ("candidate" if r["key"] == chosen else "")
            color = BLUE if r["key"] == chosen and not r["keep"] else None
            data.append([(r["name"] + (f"   {tag}" if tag else ""), color, r["key"] == chosen or r["keep"], False),
                         (f"{r['px']:.2f} px" if num(r["px"]) is not None else "–", None, False, True), "",
                         (f"{r['wins']} of {n}" if not r["keep"] and n else "–", MUTED, False, False)])
        t = _table(["Explanation", "Edge error", "Improvement vs keeping current", "Better on"], data, "lrcr", {1: 110, 2: 300, 3: 110})
        scale = max([abs(r["gain"]) for r in rows if num(r["gain"]) is not None] + [gate or 0, 0.5]) * 1.15
        t.setItemDelegateForColumn(2, GainBarDelegate(scale, t))
        for i, r in enumerate(rows):
            it = t.item(i, 2)
            it.setData(Qt.UserRole, None if r["keep"] else num(r["gain"]))
        lay.addWidget(t)
        if gate is not None:
            lay.addWidget(_label(f"An explanation has to improve held-out error by at least {gate:g} %, and do so consistently, before a change is supported. "
                                 "Scores are a nearest-edge proxy, not true reprojection error.", "footnote"))
        return card

    def _seen(self):
        obs = self.diag.get("observability") or {}
        groups = obs.get("groups") if isinstance(obs, dict) else None
        if not groups:
            return None
        card, lay = _card("What the data could see", "A calibration can only be corrected along directions the captures are sensitive to.")
        line = (self.diag.get("configuration") or {}).get("minimum_singular", 0.02)
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(8)
        for k in ("R", "T", "I"):
            g = groups.get(k) or {}
            vals = [num(v) for v in (g.get("unique_singular_values") or [])]
            seen = sum(1 for v in vals if v is not None and v >= line)
            fg, bg = (GOOD, SOFT["good"]) if vals and seen == len(vals) else ((WARN, SOFT["warn"]) if seen else (BAD, SOFT["bad"]))
            row.addWidget(_chip(f"{GROUP[k]}: {seen} of {len(vals)} directions seen", fg, bg))
        row.addStretch(1)
        lay.addLayout(row)
        pair = obs.get("pairwise") or {}
        close = []
        for key, v in pair.items():
            angles = [num(a) for a in (v.get("principal_angles_deg") or []) if num(a) is not None]
            if angles and min(angles) < 5 and "|" in key:
                a, b = key.split("|")
                close.append(f"{GROUP.get(a, a).lower()} and {GROUP.get(b, b).lower()} ({min(angles):.1f}°)")
        if close:
            lay.addWidget(_label("Almost indistinguishable in these captures: " + "; ".join(close) + ". The app cannot say which of them changed, so it does not guess.", "muted"))
        unc = (self.result.get("uncertainty") or {}).get("status") if isinstance(self.result.get("uncertainty"), dict) else None
        if unc:
            lay.addWidget(_label(UNCERTAINTY.get(unc, str(unc).replace("_", " ").capitalize()), "muted"))
        support = (self.diag.get("stable_support") or {}).get("candidate_update_supported_fraction") if isinstance(self.diag.get("stable_support"), dict) else None
        if num(support) is not None:
            lay.addWidget(_label(f"{support * 100:.1f} % of the proposed change lies in directions these captures can measure.", "muted"))
        return card

    def _changes(self):
        accepted = self.result.get("parameter_updates") if isinstance(self.result.get("parameter_updates"), dict) else {}
        proposed = self.diag.get("candidate_parameter_updates") if isinstance(self.diag.get("candidate_parameter_updates"), dict) else {}
        names = list(accepted) or list(proposed)
        if not names:
            return None
        card, lay = _card("Proposed and accepted changes",
                          "Changes from your current calibration. “Accepted” stays zero whenever the current calibration is kept; “proposed” is what the optimiser suggested before validation.")
        rows = []
        for n in names:
            unit, scale, digits = self.units.get(n, ("", 1.0, 4))

            def cell(v):
                v = num(v)
                if v is None:
                    return ("–", MUTED, False, True)
                return ("0", MUTED, False, True) if abs(v) < 1e-12 else (f"{v * scale:+.{digits}f}", None, False, True)
            rows.append([self.names.get(n, n), (unit, MUTED, False, False), cell(proposed.get(n)), cell(accepted.get(n))])
        lay.addWidget(_table(["Parameter", "Unit", "Proposed", "Accepted"], rows, "llrr", {1: 80, 2: 160, 3: 160}))
        return card

    def _review_card(self):
        s = self.review
        if not isinstance(s, dict) or not s.get("verdict"):
            return None
        card, lay = _card("Maintenance comparison", "The original calibration maintenance analysis of the same calibration and captures. A separate calculation; details are in the Calibration review tab.")
        shift, unc = num(s.get("shift_median_px")), num(s.get("shift_uncertainty_px"))
        lay.addWidget(_label(f"<b>{str(s['verdict']).capitalize()}.</b> " +
                             (f"The refined calibration would move a typical LiDAR point by {shift:.2f} px" + (f" (± {unc:.2f} px)" if unc is not None else "") + "." if shift is not None else ""), rich=True))
        return card

    def _inputs(self):
        caps = (self.diag.get("input") or {}).get("captures") if isinstance(self.diag.get("input"), dict) else None
        if not isinstance(caps, list) or not caps:
            return None
        card, lay = _card("Inputs")
        rows = [[(self._time(c.get("id")), None, False, True), (f"{int(num(c.get('points')) or 0):,}", None, False, True),
                 (f"{int(num(c.get('used_edges')) or 0):,}", None, False, True)] for c in caps if isinstance(c, dict)]
        lay.addWidget(_table(["Capture", "LiDAR points", "Edges used"], rows, "lrr", {1: 160, 2: 160}))
        src = (self.diag.get("input") or {}).get("source")
        if src:
            lay.addWidget(_label(f"Source: {src}", "footnote"))
        return card

    @staticmethod
    def _time(name):
        part = str(name or "").split("_")[0]
        return f"{part[:2]}:{part[2:4]}:{part[4:6]}" if len(part) == 6 and part.isdigit() else str(name or "–")

    def _limits(self):
        items = [str(x) for x in (self.diag.get("limitations") or []) if x] if isinstance(self.diag.get("limitations"), list) else []
        card, lay = _card("Limits of this assessment")
        lay.addWidget(_label("Hypothesis names describe mathematical parameter constraints; they are not verified physical fault labels.", "muted"))
        for x in items:
            lay.addWidget(_label(f"•  {x}", "muted"))
        return card

    # ---------------------------------------------------------------- actions
    def summary_text(self):
        r, dec = self.result, self.decision
        title = (self.status or ("", ))[0] or str(r.get("status", ""))
        lines = [f"Fault-aware calibration report: {title}", ACTION.get(r.get("recommended_action"), "")]
        best = num(dec.get("best_relative_gain"))
        if best is not None:
            lines.append(f"Best improvement over keeping the current calibration: {best * 100:.2f} %")
        if dec.get("reason"):
            lines.append(str(dec["reason"]))
        if isinstance(self.review, dict) and self.review.get("verdict"):
            lines.append(f"Maintenance comparison: {str(self.review['verdict']).capitalize()}")
        if self.folder:
            lines.append(f"Check: {self.folder.name}")
        return "\n".join(x for x in lines if x)

    def copy_summary(self):
        QtWidgets.QApplication.clipboard().setText(self.summary_text())

    def open_md(self):
        md = (self.folder or Path()) / "report.md"
        if md.is_file():
            open_path(md)
        else:
            QtWidgets.QMessageBox.information(self, "No report.md", "This check has no report.md.")

    def show_folder(self):
        if self.folder is not None and self.folder.exists():
            open_path(self.folder)

    def save_pdf(self, path=None):
        """Render the page itself into a single tall PDF page, so the file looks like the screen."""
        if self.folder is None:
            return False
        if path is None:
            path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save the report as PDF", str(self.folder.parent / f"{self.folder.name}_report.pdf"), "PDF (*.pdf)")
        if not path:
            return False
        try:
            width = max(self.body.width(), 900)
            self.body.resize(width, max(self.body.sizeHint().height(), self.body.height()))
            printer = QtPrintSupport.QPrinter(QtPrintSupport.QPrinter.ScreenResolution)
            printer.setResolution(144)
            printer.setOutputFormat(QtPrintSupport.QPrinter.PdfFormat)
            printer.setOutputFileName(str(path))
            mm = 25.4 / 96
            printer.setPageSizeMM(QtCore.QSizeF(self.body.width() * mm, self.body.height() * mm))
            printer.setPageMargins(0, 0, 0, 0, QtPrintSupport.QPrinter.Millimeter)
            painter = QtGui.QPainter(printer)
            scale = printer.pageRect().width() / self.body.width()
            painter.scale(scale, scale)
            self.body.render(painter)
            painter.end()
        except Exception as err:  # noqa: BLE001
            QtWidgets.QMessageBox.warning(self, "Could not save the PDF", str(err))
            return False
        return Path(path).is_file()
