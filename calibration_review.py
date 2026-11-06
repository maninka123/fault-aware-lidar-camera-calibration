"""Calibration review tab of the fault-aware app: the maintenance app's detailed diagnostics, inside this window.

The fault-aware Result tab stays the scientific assessment. This tab shows what the original calibration
maintenance analysis says about the same calibration and captures: the four update choices, calibration
quality, parameter changes, image comparison, leave-one-out evidence, matrices and exports.

Nothing is computed here by itself. The maintenance numbers exist only after the user presses
"Run maintenance comparison"; they are saved inside the check and shown from there afterwards. This tab never
accepts a calibration and never writes to a device or to the calibration files a check started from.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PyQt5 import QtCore, QtWidgets
from PyQt5.QtCore import Qt

import review_adapter as ra
import appcore as core
import result_sections
from calibration_io import MODE_LABELS, write_calibration_txt
from matrix_preview import MatrixPreview
from ui_common import VERDICT
from ui_widgets import MODE_NAMES, OptionsResults, action_flow

BLUE, GOOD, WARN, BAD = "#007aff", "#248a3d", "#9b6500", "#d70015"
SOFT = dict(blue="#edf5ff", good="#eaf6ed", warn="#fff6e5", bad="#fff0f1", grey="#eeeef2")
INK, MUTED, LINE = "#1d1d1f", "#6e6e73", "#e5e5ea"

# The maintenance widgets name their labels h1/h2/h3/small; give those names the fault-aware type scale (px, not pt).
REVIEW_QSS = f"""
QLabel#h1 {{ font-size: 28px; font-weight: 700; }}
QLabel#h2 {{ font-size: 17px; font-weight: 600; }}
QLabel#h3 {{ font-size: 14px; font-weight: 600; }}
QLabel#small {{ font-size: 12px; color: {MUTED}; }}
QLabel#muted {{ font-size: 14px; color: {MUTED}; }}
QFrame#soft {{ background: {SOFT['blue']}; border-radius: 8px; }}
QPushButton:checked {{ background: {SOFT['blue']}; border-color: {BLUE}; color: {BLUE}; }}
QPushButton#primary {{ background: {BLUE}; color: white; border-color: {BLUE}; padding: 0 20px; }}
QPushButton#primary:disabled {{ background: #a9c7ec; border-color: #a9c7ec; color: white; }}
QPushButton#chip {{ background: white; border: 1px solid {LINE}; border-radius: 15px; min-height: 28px; padding: 0 14px; font-weight: 600; font-size: 13px; }}
QPushButton#chip:hover {{ border-color: {BLUE}; color: {BLUE}; }}
QTableWidget {{ font-size: 13px; }}
QHeaderView::section {{ font-size: 12px; }}
"""


def _label(text="", name=None, rich=False, wrap=True):
    w = QtWidgets.QLabel(text)
    if name:
        w.setObjectName(name)
    w.setWordWrap(wrap)
    if rich:
        w.setTextFormat(Qt.RichText)
    return w


def _frame(title=None, blurb=None):
    f = QtWidgets.QFrame()
    f.setObjectName("card")
    lay = QtWidgets.QVBoxLayout(f)
    lay.setContentsMargins(24, 20, 24, 22)
    lay.setSpacing(12)
    if title:
        lay.addWidget(_label(title, "h2"))
    if blurb:
        lay.addWidget(_label(blurb, "muted"))
    return f, lay


def _button(text, slot=None, name=None):
    b = QtWidgets.QPushButton(text)
    if name:
        b.setObjectName(name)
    b.setCursor(Qt.PointingHandCursor)
    if slot:
        b.clicked.connect(slot)
    return b


def collapsible(card, expanded=True):
    """Make a finished card collapsible: its first widget (the title) stays, everything else folds away."""
    lay = card.layout()
    title = lay.takeAt(0).widget()
    body = QtWidgets.QWidget()
    bl = QtWidgets.QVBoxLayout(body)
    bl.setContentsMargins(0, 0, 0, 0)
    bl.setSpacing(lay.spacing())
    while lay.count():
        item = lay.takeAt(0)
        if item.widget():
            bl.addWidget(item.widget())
        elif item.layout():
            bl.addLayout(item.layout())
    toggle = QtWidgets.QToolButton()
    toggle.setCheckable(True)
    toggle.setCursor(Qt.PointingHandCursor)
    toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
    toggle.setStyleSheet(f"QToolButton {{ border: none; background: transparent; color: {MUTED}; font-size: 13px; padding: 3px; }}"
                         f"QToolButton:hover {{ color: {BLUE}; }}")

    def set_open(on):
        body.setVisible(on)
        toggle.setArrowType(Qt.DownArrow if on else Qt.RightArrow)
        toggle.setText("Hide" if on else "Show")
        toggle.setAccessibleName(("Collapse " if on else "Expand ") + title.text())
    toggle.toggled.connect(set_open)
    toggle.setChecked(expanded)
    set_open(expanded)
    head = QtWidgets.QHBoxLayout()
    head.addWidget(title, 1)
    head.addWidget(toggle)
    lay.addLayout(head)
    lay.addWidget(body)
    card.toggle = toggle
    return card


class CalibrationReview(QtWidgets.QWidget):
    """The tab. set_check() shows a finished fault-aware check; it starts nothing."""
    changed = QtCore.pyqtSignal()   # a comparison started or ended (the host may refresh its lists)

    def __init__(self):
        super().__init__()
        self.setStyleSheet(REVIEW_QSS)
        self.folder = self.result = self.meta = self.verdict = None
        self.inputs = self.reason = None
        self.proc = None
        self.running_folder = None
        self.publish_error = None
        self.progress_label = None
        self.selected_mode = None
        self.export_calibrations = {}
        self.sections = {}
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
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.tick)
        self.clear()

    # ---------------------------------------------------------------- public
    def clear(self):
        """No finished check to review (nothing selected, or a check is still running)."""
        self.folder = self.result = self.meta = self.verdict = None
        self._reset()
        card, lay = _frame("Calibration review", "Open a finished check to see the maintenance analysis of its calibration here.")
        self.lay.addWidget(card)
        self.lay.addStretch(1)

    def set_check(self, folder, result, meta, verdict=None):
        """verdict: (title, colour, soft background, explanation) of the fault-aware result, shown beside the maintenance one."""
        self.folder, self.result, self.meta, self.verdict = Path(folder), result, meta or {}, verdict
        self.inputs, self.reason = ra.inputs_for(self.meta)
        self.rebuild()

    def is_running(self):
        return self.proc is not None and self.proc.poll() is None

    # ---------------------------------------------------------------- building
    def _reset(self):
        self.sections, self.progress_label, self.export_calibrations = {}, None, {}
        while self.lay.count():
            item = self.lay.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()

    def rebuild(self):
        self._reset()
        self.lay.addWidget(self.verdict_card(None))
        if self.running_folder is not None and self.running_folder == self.folder and self.is_running():
            self.lay.addWidget(self.running_card())
        elif ra.state(self.folder) == "ready":
            info = ra.load(self.folder)
            if info:
                self.build_ready(info)
            else:
                self.lay.addWidget(self.failed_card("The saved comparison could not be read."))
        elif ra.state(self.folder) == "partial":
            self.lay.addWidget(self.failed_card("An earlier comparison started but did not finish."))
        else:
            self.lay.addWidget(self.empty_card())
        self.lay.addStretch(1)

    def verdict_card(self, info):
        """The fault-aware verdict and the maintenance recommendation, side by side and clearly separate."""
        card, lay = _frame()
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(16)
        fa_title, fa_color, fa_soft, fa_text = self.verdict or ("Fault-aware assessment", MUTED, SOFT["grey"], "")
        row.addWidget(self._verdict_box("FAULT-AWARE RESEARCH VERDICT", fa_title, fa_color, fa_soft, fa_text), 1)
        if info:
            s = info["summary"]
            fg, bg, _icon, _todo = VERDICT.get(s["verdict"], VERDICT["INCONCLUSIVE"])
            rec = (s.get("strategy_comparison") or {}).get("recommendation")
            message = core.verdict_message(s)
            if rec and rec.rstrip(".").lower() not in message.lower():   # do not say the same thing twice
                message += f" {rec}"
            row.addWidget(self._verdict_box("MAINTENANCE RECOMMENDATION", s["verdict"].capitalize(), fg, bg, message), 1)
        else:
            row.addWidget(self._verdict_box("MAINTENANCE RECOMMENDATION", "Not computed", MUTED, SOFT["grey"],
                                            "Run the maintenance comparison to see it."), 1)
        lay.addLayout(row)
        if info:
            kind, text = ra.agreement((self.result or {}).get("status"), info["summary"]["verdict"])
            colour = {"agree": GOOD, "differ": WARN, "info": MUTED}[kind]
            lay.addWidget(_label(f"<span style='color:{colour}'><b>{'Agreement' if kind == 'agree' else 'Different answers' if kind == 'differ' else 'Note'}:</b></span> {text}", rich=True))
        return card

    @staticmethod
    def _verdict_box(caps, title, color, soft, text):
        box = QtWidgets.QFrame()
        box.setStyleSheet(f"QFrame {{ background: {soft}; border-radius: 14px; }} QLabel {{ background: transparent; }}")
        bl = QtWidgets.QVBoxLayout(box)
        bl.setContentsMargins(20, 14, 20, 16)
        bl.setSpacing(4)
        bl.addWidget(_label(caps, "caps"))
        t = _label(title)
        t.setStyleSheet(f"color: {color}; font-size: 20px; font-weight: 600;")
        bl.addWidget(t)
        bl.addWidget(_label(text, "muted"))
        return box

    # ---- states without results
    def empty_card(self):
        card, lay = _frame("Maintenance comparison not run yet")
        if self.reason:
            lay.addWidget(_label(self.reason, "muted"))
            lay.addWidget(_label("Without those files the maintenance analysis cannot be reproduced, and no numbers are made up.", "small"))
            return card
        lay.addWidget(_label(
            "This tab shows the calibration maintenance analysis of the same calibration and captures: the four update choices "
            "(keep, alignment only, camera only, camera + alignment), edge RMSE, parameter changes with their uncertainty, "
            "leave-one-out evidence, matrices and the image comparison.", "muted"))
        lay.addWidget(_label(
            "It is a separate calculation from the fault-aware assessment, so it is not run automatically. Starting it takes a few "
            "minutes. Its results are saved inside this check (<i>" + ra.REVIEW_DIR + "/</i>) and nothing else changes.", "muted", rich=True))
        row = QtWidgets.QHBoxLayout()
        self.run_button = _button("Run maintenance comparison", self.start, "primary")
        self.run_button.setEnabled(self.ready_to_run())
        row.addWidget(self.run_button)
        row.addStretch(1)
        lay.addLayout(row)
        if self.running_folder is not None and self.is_running():
            lay.addWidget(_label(f"Another comparison is running for {self.running_folder.name}. Wait for it to finish first.", "small"))
        return card

    def ready_to_run(self):
        return self.inputs is not None and not self.is_running()

    def running_card(self):
        card, lay = _frame("Running the maintenance comparison")
        bar = QtWidgets.QProgressBar()
        bar.setRange(0, 0)
        bar.setTextVisible(False)
        lay.addWidget(bar)
        self.progress_label = _label(ra.progress_text(self.folder), "muted")
        lay.addWidget(self.progress_label)
        lay.addWidget(_label("This takes a few minutes. You can keep using the other tabs; this tab updates when it finishes.", "small"))
        row = QtWidgets.QHBoxLayout()
        row.addWidget(_button("Stop", self.stop))
        row.addStretch(1)
        lay.addLayout(row)
        return card

    def failed_card(self, headline):
        card, lay = _frame(headline)
        if self.publish_error:
            lay.addWidget(_label(self.publish_error, "muted"))
        tail = ra.log_tail(self.folder)
        if tail:
            log = QtWidgets.QPlainTextEdit("\n".join(tail))
            log.setReadOnly(True)
            log.setMaximumHeight(170)
            lay.addWidget(log)
        lay.addWidget(_label("Nothing about the fault-aware assessment or your calibration files was changed.", "small"))
        row = QtWidgets.QHBoxLayout()
        self.run_button = _button("Run maintenance comparison again", self.start, "primary")
        self.run_button.setEnabled(self.ready_to_run())
        row.addWidget(self.run_button)
        row.addStretch(1)
        lay.addLayout(row)
        return card

    # ---- finished comparison
    def build_ready(self, info):
        s, cmp_ = info["summary"], info["comparison"]
        self.export_calibrations = result_sections.export_calibrations(info)
        self.selected_mode = s["mode"]
        # replace the placeholder verdict card with one that has both verdicts
        old = self.lay.takeAt(0).widget()
        old.hide()
        old.deleteLater()
        self.lay.insertWidget(0, self.verdict_card(info))

        self.lay.addWidget(self.meta_card(info))
        # as in the maintenance app's Result header: the matrices come first, under the verdicts, expanded,
        # with the option's changes marked; choosing an option card below updates them
        self.matrices = MatrixPreview()
        self.lay.addWidget(self.matrix_block())
        self.lay.addWidget(self.nav_strip())

        comparison = s.get("strategy_comparison")
        # A. update comparison
        card, cl = _frame("Update comparison", "The four things a calibration update could change, tested on captures left out of each fit.")
        self.sections["Compare"] = card
        if comparison:
            self.matrices.set_calibrations(comparison.get("calibrations", {}))
            self.options = OptionsResults(comparison)
            self.options.mode_changed.connect(self.preview_mode)
            cl.addWidget(self.options)
        else:
            self.options = None
            cl.addWidget(_label("This comparison did not test the four update choices, so no option scores were saved.", "muted"))
        self.lay.addWidget(card)

        # B. quality
        card, cl = _frame("Calibration quality", f"Detailed statistics describe the {MODE_NAMES.get(s['mode'], s['mode']).lower()} "
                          "candidate this comparison refined in full. They are not necessarily the recommended option.")
        self.sections["Quality"] = card
        cl.addLayout(result_sections.metric_row(s))
        cl.addWidget(result_sections.shift_card(s))
        self.lay.addWidget(card)

        # C. parameters
        if cmp_:
            card = result_sections.parameter_card(s, cmp_)
            self.sections["Parameters"] = collapsible(card)
            self.lay.addWidget(card)
        else:
            card, cl = _frame("Previous vs new calibration")
            cl.addWidget(_label("The refined calibration was not saved, so parameter changes cannot be listed.", "muted"))
            self.sections["Parameters"] = card
            self.lay.addWidget(card)

        # D. images
        images = result_sections.CaptureComparison(info)
        self.sections["Images"] = collapsible(images)
        self.lay.addWidget(images)

        # E. validation evidence
        evidence = result_sections.evidence_card(s)
        if evidence is not None:
            evidence.capture_clicked.connect(lambda name: images.select_capture(name))
            evidence.layout().insertWidget(2, _label(
                "Click a capture row to open its images above. “Before” and “After” are the held-out edge-match scores "
                "of the previous and refined calibration on the data that was left out of the fit.", "small"))
            self.sections["Evidence"] = collapsible(evidence)
            self.lay.addWidget(evidence)

        # G. export and review actions
        self.lay.addWidget(self.export_card(info))
        self.preview_mode(self.options.active_mode if self.options is not None else s["mode"])

    def meta_card(self, info):
        s = info["summary"]
        stale = ra.is_stale(info, self.meta)
        text = (f"Maintenance comparison run {s['date'].replace('T', ' ')} on {len(s['captures'])} captures with the same calibration "
                f"and capture folder as this check. It is a separate calculation, saved in this check’s {ra.REVIEW_DIR} folder.")
        card = QtWidgets.QFrame()
        card.setObjectName("card")
        lay = QtWidgets.QHBoxLayout(card)
        lay.setContentsMargins(20, 12, 20, 12)
        lay.addWidget(_label(text + ("  <b style='color:%s'>The check now points at different files than this comparison used.</b>" % WARN if stale else ""),
                             "small", rich=True), 1)
        again = _button("Run again…", self.start)
        again.setEnabled(self.ready_to_run())
        lay.addWidget(again)
        return card

    def nav_strip(self):
        wrap = QtWidgets.QWidget()
        row = QtWidgets.QHBoxLayout(wrap)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(_label("Jump to", "small", wrap=False))
        for name in ("Compare", "Quality", "Parameters", "Images", "Evidence", "Matrices", "Export"):
            b = _button(name, name=None)
            b.setObjectName("chip")
            b.clicked.connect(lambda _=False, n=name: self.jump(n))
            row.addWidget(b)
        row.addStretch(1)
        return wrap

    def jump(self, name):
        w = self.sections.get(name)
        if w is not None:
            w.show()
            QtCore.QTimer.singleShot(0, lambda: self.scroll.verticalScrollBar().setValue(max(0, w.mapTo(self.body, QtCore.QPoint(0, 0)).y() - 8)))

    def matrix_block(self):
        """The maintenance app's own matrix preview (K, distortion, T with Δ markers and its Hide / Show), plus a switch
        between the option's values with their changes, the current values, and the differences alone."""
        block = QtWidgets.QWidget()
        self.sections["Matrices"] = block
        bl = QtWidgets.QVBoxLayout(block)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(8)
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(_label("Matrices show", "small", wrap=False))
        self.view_buttons = {}
        group = QtWidgets.QButtonGroup(block)
        for key, text, tip in (("candidate", "Option with changes", "The selected option’s values; changed ones carry their Δ"),
                               ("current", "Current", "The calibration in use now"),
                               ("difference", "Differences only", "Only how much each value changes")):
            b = _button(text)
            b.setCheckable(True)
            b.setToolTip(tip)
            b.setChecked(key == "candidate")
            b.clicked.connect(lambda _=False, k=key: self.matrices.set_view(k))
            group.addButton(b)
            row.addWidget(b)
            self.view_buttons[key] = b
        row.addStretch(1)
        row.addWidget(_label("Pick an option card below to preview its matrices", "small", wrap=False))
        bl.addLayout(row)
        bl.addWidget(self.matrices)
        return block

    def export_card(self, info):
        out = info["out"]
        card, cl = _frame("Export and review", "Take a candidate out of this app for review. Nothing here changes the calibration in use.")
        self.sections["Export"] = card
        self.export_label = _label("", "small")
        cl.addWidget(self.export_label)
        self.export_button = _button("Save calibration TXT…", lambda: self.save_txt(info), "primary")
        buttons = [self.export_button,
                   _button("Save refined JSON…", lambda: self.save_refined(out)),
                   _button("Open results folder", lambda: os.startfile(str(out))),
                   _button("Show report", lambda: self.show_report(out))]
        cl.addWidget(action_flow(buttons))
        cl.addWidget(_label("Accepting a calibration and writing to a device are not offered here: the fault-aware verdict decides whether "
                            "anything should change, and a candidate existing is not a reason to accept it. The calibration file this check "
                            "started from is never changed.", "small"))
        return card

    # ---------------------------------------------------------------- interaction
    def preview_mode(self, mode):
        self.selected_mode = mode
        if self.matrices.calibrations:
            self.matrices.set_mode(mode)
        title = MODE_LABELS.get(mode, mode)
        self.export_label.setText("TXT export: " + title)
        available = bool(self.export_calibrations.get(mode))
        self.export_button.setEnabled(available)
        self.export_button.setToolTip(f"Save the {title} camera intrinsics, distortion and LiDAR → camera extrinsics."
                                      if available else "This option’s fitted calibration was not saved.")

    def protected_paths(self):
        paths = [(self.meta or {}).get("calibration")]
        if self.inputs:
            paths.append(self.inputs["calibration"])
        return paths

    def save_txt(self, info):
        mode = self.selected_mode
        candidate = self.export_calibrations.get(mode)
        if not candidate:
            return
        folder = Path(self.meta.get("captures") or "")
        if not folder.is_dir():
            folder = Path.home() / "Downloads"
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, f"Save {MODE_LABELS.get(mode, mode)} calibration",
                                                        str(folder / f"{self.folder.name}_{mode}_calibration.txt"), "Calibration TXT (*.txt)")
        if not path:
            return
        path = Path(path)
        if not path.suffix:
            path = path.with_suffix(".txt")
        try:
            ra.check_export_path(path, self.protected_paths())
            write_calibration_txt(path, candidate, mode, self.folder.name)
        except (OSError, ValueError) as error:
            QtWidgets.QMessageBox.warning(self, "Could not save calibration", str(error))
            return
        self.export_label.setText(f"Saved {MODE_LABELS.get(mode, mode)}: {path.name}")
        self.export_label.setToolTip(str(path))

    def save_refined(self, out):
        src = Path(out) / "refined_calibration.json"
        if not src.exists():
            QtWidgets.QMessageBox.information(self, "Nothing to save", "This comparison did not save a refined calibration.")
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save refined calibration",
                                                        str(Path.home() / "Downloads" / f"{self.folder.name}_refined_calibration.json"),
                                                        "Calibration (*.json)")
        if not path:
            return
        try:
            ra.check_export_path(path, self.protected_paths())
            Path(path).write_bytes(src.read_bytes())
        except (OSError, ValueError) as error:
            QtWidgets.QMessageBox.warning(self, "Could not save calibration", str(error))

    def show_report(self, out):
        report = Path(out) / "report.md"
        d = QtWidgets.QDialog(self)
        d.setWindowTitle("Maintenance report")
        lay = QtWidgets.QVBoxLayout(d)
        tb = QtWidgets.QTextBrowser()
        tb.setMarkdown(report.read_text(encoding="utf-8") if report.exists() else "_No report.md was saved._")
        lay.addWidget(tb)
        d.resize(1000, 760)
        d.exec_()

    # ---------------------------------------------------------------- running (only when the user asks)
    def start(self, auto=False):
        """Run the maintenance comparison of the open check. auto=True is the new-check option the user ticked on the
        setup page (no extra question); otherwise it is the button. Returns whether a run was started."""
        if self.folder is None or self.inputs is None or self.is_running():
            return False
        if not auto and ra.state(self.folder) != "none":
            if QtWidgets.QMessageBox.question(self, "Run again?", "This replaces the earlier maintenance comparison of this check once the new "
                                              "one has finished. The fault-aware result and your calibration files are not touched.") != QtWidgets.QMessageBox.Yes:
                return False
        self.publish_error = None
        out = ra.prepare(self.folder, self.inputs, (self.result or {}).get("status"))
        args, env_extra, cwd = ra.command(self.folder, self.inputs)
        exe = Path(sys.executable)
        if exe.name.lower() == "pythonw.exe":
            exe = exe.with_name("python.exe")
        log = open(out / "run.log", "w", encoding="utf-8")
        try:
            self.proc = subprocess.Popen([str(exe)] + args, cwd=cwd, stdout=log, stderr=subprocess.STDOUT,
                                         env=dict(os.environ, **env_extra), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as error:
            log.close()
            self.proc = None
            QtWidgets.QMessageBox.warning(self, "Could not start", str(error))
            return False
        self.log_file = log
        self.running_folder = self.folder
        self.timer.start()
        self.rebuild()
        self.changed.emit()
        return True

    def stop(self):
        if self.is_running():
            self.proc.terminate()

    def tick(self):
        if self.proc is None:
            self.timer.stop()
            return
        if self.proc.poll() is None:
            if self.progress_label is not None and self.running_folder == self.folder:
                self.progress_label.setText(ra.progress_text(self.folder))
            return
        self.timer.stop()
        try:
            self.log_file.close()
        except (OSError, AttributeError):
            pass
        finished = self.running_folder
        code = self.proc.returncode
        self.proc = None
        self.running_folder = None
        if code == 0:       # only a finished run replaces what the check already holds
            ok, message = ra.publish(finished)
            self.publish_error = None if ok else message
        if finished == self.folder:
            self.rebuild()
        self.changed.emit()

    def shutdown(self):
        """Stop a running comparison when the app closes."""
        self.timer.stop()
        if self.is_running():
            self.proc.terminate()
