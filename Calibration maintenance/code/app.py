"""Calibration maintenance - desktop app (PyQt5).

Start:  start_app.bat   (or: python app.py)

Connected devices (device_ui.py): connect to one sensor device at a time (Central Monitoring Platform
devices), capture a few seconds of its camera + LiDAR data, check its calibration, and - only after
review and confirmation - write the new calibration into the device (SSH, with a backup).
Manual check: 1. the previous calibration (a suggested one, a calibration.json, or values typed in);
2. the new captures (raw bags or stacked *.npz); 3. Calculate.
Either way maintain.py runs in the background and the window follows it stage by stage (what is detected
in the LiDAR and the image, how each step went), then shows the verdict, previous vs new intrinsics and
extrinsics with whether each change is real, the images, and save / accept / write to the device.
Earlier checks are listed on the left. A previous calibration file is never changed.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path

sys.dont_write_bytecode = True      # no __pycache__ next to the code (or in the Targetless folder it imports)
import appcore as core  # noqa: E402  first: sets the BLAS thread limits before numpy is loaded

from PyQt5 import QtCore, QtGui, QtWidgets  # noqa: E402
from PyQt5.QtCore import Qt  # noqa: E402
from pose_view import CalibrationPosePanel, ComparisonColumns  # noqa: E402
from ui_widgets import MODE_NAMES, OptionsResults, SourceStrip, UpdateChoice  # noqa: E402

from ui_common import (BAD, BAD_SOFT, BG, BLUE, BLUE_SOFT, GOOD, GOOD_SOFT, INFO_SOFT, INK, INK2, MUTED, MONO, ORANGE, PARAMS, QSS,  # noqa: E402
                       STAGES, VERDICT, WARN, WARN_SOFT, Gauge, ImageView, ManualDialog, StepTracker, app_icon, badge_icon, button, calibration_view,
                       card, clear, dot_icon, hbox, image_grid, img_label, label, np_to_pixmap, scroll, table)


SCRATCH = ("scratch", "Scratch", "Calibration from scratch",
           "The targetless calibration ran on the same captures without any starting values (camera mounting found "
           "automatically). Its result is one of the refinement starts below; the check then compares the outcome with the "
           "existing calibration as usual. Each image: LiDAR edges on image edges with the from-scratch calibration.")


def stage_def(key):
    if key == 'options':
        return ('options', 'Options', 'Compare update options', 'Higher held-out alignment is better.')
    return next((x for x in STAGES + [SCRATCH] if x[0] == key), (key, key, key, ""))


# ================================================================== page: new check
class StepHeader(QtWidgets.QWidget):
    def __init__(self, n, title, subtitle):
        super().__init__()
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        self.badge = QtWidgets.QLabel()
        self.n = n
        self.set_done(False)
        lay.addWidget(self.badge)
        txt = QtWidgets.QVBoxLayout()
        txt.setSpacing(0)
        txt.addWidget(label(title, "h2"))
        txt.addWidget(label(subtitle, "muted"))
        lay.addLayout(txt, 1)

    def set_done(self, done):
        self.badge.setPixmap(badge_icon(GOOD if done else "#c9ced6", "✓" if done else str(self.n), 15).pixmap(30, 30))


class SetupPage(QtWidgets.QWidget):
    run_requested = QtCore.pyqtSignal(str, str, str, str)

    def __init__(self):
        super().__init__()
        self.cal = self.data = None
        sug = core.suggestions()
        page = QtWidgets.QWidget()
        page.setObjectName("page")
        v = QtWidgets.QVBoxLayout(page)
        v.setContentsMargins(32, 26, 32, 32)
        v.setSpacing(16)
        v.addWidget(label("New check", "h1"))
        v.addWidget(label("Choose a calibration and new captures. We\u2019ll check what needs updating.", "muted", wrap=True))

        # 1. previous calibration
        c1, l1 = card()
        self.h1 = StepHeader(1, "Existing calibration", "The camera settings and alignment in use now")
        l1.addWidget(self.h1)
        self.cal_combo = QtWidgets.QComboBox()
        self.cal_combo.addItem("Choose a suggested calibration…", None)
        for name, path in sug["calibrations"]:
            self.cal_combo.addItem(name, path)
        self.cal_combo.activated.connect(lambda k: self.cal_combo.itemData(k) and self.load_cal(self.cal_combo.itemData(k)))
        l1.addWidget(hbox(self.cal_combo, label("or", "muted"), button("Open file…", slot=self.open_cal),
                          button("Enter values…", slot=self.enter_cal)))
        self.cal_err = label("", "err", wrap=True)
        self.cal_err.hide()
        l1.addWidget(self.cal_err)
        self.cal_box = QtWidgets.QVBoxLayout()
        l1.addLayout(self.cal_box)
        v.addWidget(c1)

        # 2. new captures
        c2, l2 = card()
        self.h2 = StepHeader(2, "New captures", "Choose recorded or stacked captures")
        l2.addWidget(self.h2)
        self.data_combo = QtWidgets.QComboBox()
        self.data_combo.addItem("Choose a suggested capture folder…", None)
        for name, path in sug["data"]:
            self.data_combo.addItem(name, path)
        self.data_combo.activated.connect(lambda k: self.data_combo.itemData(k) and self.load_data(self.data_combo.itemData(k)))
        l2.addWidget(hbox(self.data_combo, label("or", "muted"), button("Choose folder…", slot=self.open_data)))
        self.data_err = label("", "err", wrap=True)
        self.data_err.hide()
        l2.addWidget(self.data_err)
        self.data_box = QtWidgets.QVBoxLayout()
        l2.addLayout(self.data_box)
        v.addWidget(c2)

        # 3. calculate
        c3, l3 = card()
        l3.addWidget(StepHeader(3, "Check for changes", "Compare the options, then review the recommendation"))
        self.update_choice = UpdateChoice()
        self.device = QtWidgets.QLineEdit("rig")
        self.device.setMaximumWidth(260)
        opts = QtWidgets.QGridLayout()
        opts.setHorizontalSpacing(30)
        opts.addWidget(label("What to check", "h3"), 0, 0)
        opts.addWidget(self.update_choice, 1, 0)
        opts.addWidget(label("Device name", "h3"), 0, 1)
        opts.addWidget(self.device, 1, 1)
        opts.setColumnStretch(0, 1)
        l3.addLayout(opts)
        for combo in (self.cal_combo, self.data_combo):
            combo.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
            combo.setMaxVisibleItems(16)
        self.go = button("Check calibration", "primary", self.calculate)
        self.go.setStyleSheet("padding: 10px 36px; font-size: 11pt;")
        self.hint = label("", "muted", wrap=True)
        self.update_choice.currentIndexChanged.connect(self.update_ready)
        l3.addWidget(hbox(self.go, self.hint, stretch_at=2, spacing=16))
        v.addWidget(c3)
        v.addStretch(1)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(scroll(page))
        self.update_ready()

    # ---- previous calibration
    def load_cal(self, path):
        try:
            self.cal = core.calibration_info(path)
        except (ValueError, KeyError, TypeError) as err:
            self.cal_err.setText(str(err))
            self.cal_err.show()
            return
        self.cal_err.hide()
        clear(self.cal_box)
        self.cal_box.addWidget(calibration_view(self.cal))
        self.cal_box.addWidget(hbox(button("Edit these values…", slot=lambda: self.enter_cal(self.cal)), stretch_at=1))
        self.update_ready()

    def open_cal(self):
        start = str(Path(self.cal["path"]).parent) if self.cal else str(core.PROJECT)
        p, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Previous calibration", start, "Calibration (*.json)")
        if p:
            self.cal_combo.setCurrentIndex(0)
            self.load_cal(p)

    def enter_cal(self, prefill=False):
        d = ManualDialog(self, prefill or None)
        if d.exec_() == QtWidgets.QDialog.Accepted:
            self.cal_combo.setCurrentIndex(0)
            self.load_cal(d.path)

    # ---- new captures
    def load_data(self, path):
        QtWidgets.QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.data = core.inspect_data(path)
            self.data_err.hide()
            clear(self.data_box)
            d = self.data
            kind = "raw captures, decoded during the check" if d["kind"] == "raw" else "stacked captures"
            head = label(f"<b>{len(d['captures'])} {kind}</b> &nbsp; <span style='color:{MUTED}; font-family:Consolas'>{d['name']}</span>", rich=True)
            self.data_box.addWidget(head)
            row = QtWidgets.QHBoxLayout()
            row.setSpacing(12)
            for c in d["captures"][:6]:
                box = QtWidgets.QVBoxLayout()
                box.setSpacing(2)
                if c["npz"]:
                    iv = ImageView(pixmap=np_to_pixmap(core.capture_image(c["npz"])), caption=c["name"])
                else:
                    iv = label(f"raw bag\n{c['size_mb']:.0f} MB")
                    iv.setAlignment(Qt.AlignCenter)
                    iv.setMinimumHeight(120)
                    iv.setStyleSheet(f"background: {INFO_SOFT}; border-radius: 8px; color: {MUTED};")
                iv.setMaximumWidth(260)
                box.addWidget(iv)
                cap = label(c["name"].replace("capture_", "").replace("_enclosure_on", "").replace("_enclosure_off", ""), "small")
                box.addWidget(cap)
                row.addLayout(box)
            row.addStretch(1)
            self.data_box.addLayout(row)
        except (ValueError, OSError, KeyError) as err:
            self.data = None
            self.data_err.setText(str(err))
            self.data_err.show()
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        self.update_ready()

    def open_data(self):
        start = self.data["path"] if self.data else str(core.TARGETLESS)
        p = QtWidgets.QFileDialog.getExistingDirectory(self, "Folder with the new captures", start)
        if p:
            self.data_combo.setCurrentIndex(0)
            self.load_data(p)

    # ---- calculate
    def update_ready(self):
        self.h1.set_done(bool(self.cal))
        self.h2.set_done(bool(self.data))
        ready = bool(self.cal and self.data)
        self.go.setEnabled(ready)
        self.hint.setText(("Tests four update choices. Allow a few minutes." if self.update_choice.currentData() == 'compare'
                           else f"Checks {len(self.data['captures'])} captures.") if ready
                          else "Choose a calibration and captures to continue.")

    def calculate(self):
        self.run_requested.emit(self.cal["path"], self.data["path"], self.update_choice.currentData(),
                                self.device.text().strip() or "rig")

    def prefill(self, cal, data, device=None):
        if cal and Path(cal).exists():
            self.load_cal(cal)
        if data and Path(data).exists():
            self.load_data(data)
        if device:
            self.device.setText(device)


# ================================================================== page: a run
class RunPage(QtWidgets.QWidget):
    check_again = QtCore.pyqtSignal(str, str, str)
    accepted_run = QtCore.pyqtSignal()

    def __init__(self, main):
        super().__init__()
        self.main = main
        self.name = None
        page = QtWidgets.QWidget()
        page.setObjectName("page")
        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(28, 20, 28, 16)
        v.setSpacing(12)

        self.title = label("", "h1")
        self.pill = label("")
        self.sources = SourceStrip()
        head = QtWidgets.QVBoxLayout()
        head.setSpacing(2)
        head.addWidget(hbox(self.title, self.pill, stretch_at=1))
        head.addWidget(self.sources)
        v.addLayout(head)

        self.banner = label("", wrap=True, rich=True)
        self.banner.hide()
        v.addWidget(self.banner)

        self.tracker = StepTracker()
        self.tracker.clicked.connect(self.select_stage_key)
        v.addWidget(self.tracker)

        self.tabs = QtWidgets.QTabWidget()
        self.tabs.tabBar().setExpanding(False)
        self.tabs.tabBar().setElideMode(Qt.ElideNone)
        self.tabs.currentChanged.connect(lambda index: self.tracker.setVisible(index == 0))
        v.addWidget(self.tabs, 1)

        # processing tab
        proc = QtWidgets.QWidget()
        pl = QtWidgets.QVBoxLayout(proc)
        pl.setContentsMargins(0, 8, 0, 0)
        split = QtWidgets.QSplitter()
        split.setHandleWidth(10)
        self.stage_list = QtWidgets.QListWidget()
        self.stage_list.setObjectName("stages")
        self.stage_list.setIconSize(QtCore.QSize(20, 20))
        self.stage_list.setMinimumWidth(270)
        self.stage_list.setMaximumWidth(340)
        self.stage_list.setWordWrap(True)
        self.stage_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.stage_list.currentRowChanged.connect(self.show_stage)
        self.stage_list.itemClicked.connect(lambda *_: setattr(self, "follow", False))
        self.stage_stack = QtWidgets.QStackedWidget()
        split.addWidget(self.stage_list)
        split.addWidget(self.stage_stack)
        split.setStretchFactor(1, 1)
        pl.addWidget(split, 1)
        self.log_btn = button("Show log", "link")
        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setStyleSheet(f"font-family: {MONO}; font-size: 9pt;")
        self.log.setMaximumHeight(200)
        self.log.hide()
        self.log_btn.clicked.connect(lambda: self.toggle_log(not self.log.isVisible()))
        pl.addWidget(hbox(self.log_btn, stretch_at=1))
        pl.addWidget(self.log)
        self.tabs.addTab(proc, "Processing")

        # result tab
        self.result_holder = QtWidgets.QWidget()
        self.result_lay = QtWidgets.QVBoxLayout(self.result_holder)
        self.result_lay.setContentsMargins(0, 0, 0, 0)
        self.tabs.addTab(self.result_holder, "Result")

    def toggle_log(self, show):
        self.log.setVisible(show)
        self.log_btn.setText("Hide log" if show else "Show log")

    # ---- open / refresh
    def open(self, name):
        self.name, self.n_shown, self.built, self.follow, self.waiting = name, 0, False, True, None
        self.stage_list.clear()
        while self.stage_stack.count():
            w = self.stage_stack.widget(0)
            self.stage_stack.removeWidget(w)
            w.deleteLater()
        clear(self.result_lay)
        self.banner.hide()
        self.toggle_log(False)
        self.tabs.setTabEnabled(1, False)
        self.tabs.setCurrentIndex(0)
        self.refresh()

    def refresh(self):
        if not self.name:
            return
        info = core.run_info(self.name)
        running = self.main.is_running(self.name)
        failed = not running and not info["finished"] and self.main.exit_code(self.name) not in (None, 0)
        inp = info["inputs"]
        self.title.setText(inp.get("device") or self.name)
        dev = info.get("device")
        self.sources.set_paths(core.resolve(inp['calibration']) if inp.get('calibration') else None,
                               core.resolve(inp['data']) if inp.get('data') else None, info['out'])
        st_text, fg, bg = (("Running…", BLUE, BLUE_SOFT) if running else ("Finished", GOOD, GOOD_SOFT) if info["finished"]
                           else ("Stopped with an error", BAD, BAD_SOFT) if failed else ("Incomplete", MUTED, INFO_SOFT))
        self.pill.setText(st_text)
        self.pill.setStyleSheet(f"color: {fg}; background: {bg}; border-radius: 11px; padding: 4px 14px; font-weight: 700;")

        stages = [s for s in info["stages"] if s["stage"] != "start"]
        done = {s["stage"] for s in stages}
        nxt = next((k for k, *_ in STAGES if k not in done), None)
        self.tracker.set_states(["done" if k in done else "active" if k == nxt and running else "failed" if k == nxt and failed else ""
                                 for k, *_ in STAGES])
        # new stages only: images already shown are not reloaded
        if self.waiting is not None:
            self.stage_list.takeItem(self.stage_list.row(self.waiting))
            self.waiting = None
        for s in stages[self.n_shown:]:
            title = stage_def(s["stage"])[2]
            it = QtWidgets.QListWidgetItem(badge_icon(GOOD, "✓", 12), f"{title}\n{(s.get('time') or '')[11:]}")
            it.setData(Qt.UserRole, s["stage"])
            self.stage_list.addItem(it)
            self.stage_stack.addWidget(self.stage_widget(s))
        new = len(stages) > self.n_shown
        self.n_shown = len(stages)
        if running and nxt:
            title = next(t for k, _, t, _ in STAGES if k == nxt)
            if stages and stages[-1]["stage"] == "scratch":
                title = "Calibration from scratch (a few minutes)"
            self.waiting = QtWidgets.QListWidgetItem(badge_icon(BLUE, "…", 12), f"Working on: {title}")
            self.waiting.setFlags(Qt.NoItemFlags)
            self.waiting.setForeground(QtGui.QColor(BLUE))
            self.stage_list.addItem(self.waiting)
        if new and (self.follow or self.stage_list.currentRow() < 0):
            self.stage_list.setCurrentRow(self.n_shown - 1)
        self.log.setPlainText("\n".join(info["log"]))
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())
        if failed:
            self.toggle_log(True)
        if info["summary"] and not self.built:
            self.built = True
            self.build_results(info)
            self.tabs.setTabEnabled(1, True)
            self.tabs.setCurrentIndex(1)

    def select_stage_key(self, idx):
        key = STAGES[idx][0]
        for r in range(self.stage_list.count()):
            if self.stage_list.item(r).data(Qt.UserRole) == key:
                self.follow = False
                self.tabs.setCurrentIndex(0)
                self.stage_list.setCurrentRow(r)
                return

    def show_stage(self, row):
        if 0 <= row < self.stage_stack.count():
            self.stage_stack.setCurrentIndex(row)

    def stage_widget(self, s):
        key = s["stage"]
        _, _, title, check = stage_def(key)
        page = QtWidgets.QWidget()
        page.setObjectName("page")
        lay = QtWidgets.QVBoxLayout(page)
        lay.setContentsMargins(6, 0, 6, 10)
        lay.setSpacing(10)
        c, cl = card()
        cl.addWidget(hbox(label(title, "h2"), label((s.get("time") or "")[11:], "small"), stretch_at=1))
        msg = s["message"]
        cl.addWidget(label(msg[:1].upper() + msg[1:], wrap=True, sel=True))
        if check:
            box = QtWidgets.QFrame()
            box.setObjectName("soft")
            bl = QtWidgets.QVBoxLayout(box)
            bl.setContentsMargins(12, 8, 12, 8)
            bl.addWidget(label(f"<b style='color:{BLUE}'>What to look for:</b> {check}", wrap=True, rich=True))
            box.hide()
            help_button = button('What to look for', 'link', lambda: box.setVisible(not box.isVisible()))
            cl.addWidget(hbox(help_button, stretch_at=1))
            cl.addWidget(box)
        if s.get("table"):
            rows = s["table"]
            cols = list(rows[0])
            cell = lambda v: ("✓" if v else "—") if isinstance(v, bool) else core.fmt(v, 3) if isinstance(v, float) else str(v)
            cl.addWidget(table([c_.replace("_", " ") for c_ in cols], [[cell(r[c_]) for c_ in cols] for r in rows],
                               numeric=[j for j, c_ in enumerate(cols) if isinstance(rows[0][c_], (int, float)) and not isinstance(rows[0][c_], bool)],
                               highlight=[i for i, r in enumerate(rows) if r.get("chosen")]))
        imgs = [p for p in s.get("images", []) if Path(p).exists()]
        if imgs:
            cl.addWidget(image_grid(imgs, 2 if key == "features" or len(imgs) in (2, 4) else min(3, len(imgs))))
        lay.addWidget(c)
        lay.addStretch(1)
        return scroll(page)

    # ---- results
    def build_results(self, info):
        s, cmp_ = info["summary"], info["comparison"]
        fg, bg, icon, todo = VERDICT.get(s["verdict"], VERDICT["INCONCLUSIVE"])
        reason = core.verdict_message(s)
        self.banner.setText(f"<span style='font-size:14pt; font-weight:600; color:{fg}'>{s['verdict'].capitalize()}</span><br>"
                            f"<span style='color:{INK2}'>{reason}</span>")
        self.banner.setStyleSheet(f"background: {bg}; border: 1px solid transparent; border-radius: 14px; padding: 14px 18px;")
        self.banner.show()

        page = QtWidgets.QWidget()
        page.setObjectName("page")
        v = QtWidgets.QVBoxLayout(page)
        v.setContentsMargins(4, 10, 4, 20)
        v.setSpacing(14)

        if s.get('strategy_comparison'):
            c, cl = card('What should you update?')
            cl.addWidget(OptionsResults(s['strategy_comparison']))
            v.addWidget(c)

        # metrics
        o, n = s["existing_on_new_data"], s["refined_on_new_data"]
        z = s.get("z")
        zword = "" if not core.fin(z) else "within noise" if z < 2 else "borderline" if z < 3 else "statistically significant"
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(12)
        for title_, value, note in (
                ("Point shift", core.fmt(s["shift_median_px"], 2, " px"), "Median across the scene"),
                ("Uncertainty", "± " + core.fmt(s["shift_uncertainty_px"], 2, " px"),
                 f'Shift is {core.fmt(z, 1)}× uncertainty' if core.fin(z) else 'More captures needed'),
                ("Regions improved", f"{s['heldout_improved']} / {s['heldout_total']}", "Tested outside the fit"),
                ("Edge alignment", f"{n['on_edge_share'] * 100:.1f} %", f"Previously {o['on_edge_share'] * 100:.1f} %")):
            c, cl = card()
            cl.setSpacing(2)
            cl.addWidget(label(title_, "small"))
            big = label(value)
            big.setStyleSheet("font-size: 19pt; font-weight: 700;")
            cl.addWidget(big)
            cl.addWidget(label(note, "small", wrap=True))
            row.addWidget(c, 1)
        v.addLayout(row)

        # gauge
        c, cl = card("How much did the calibration change?")
        bands = "   ·   ".join(f"{core.fmt(x)} px at {k}" for k, x in (s.get("shift_by_range_px") or {}).items())
        cl.addWidget(label(f"By distance: {bands}", "muted"))
        cl.addWidget(Gauge(s["shift_median_px"], s["shift_uncertainty_px"]))
        v.addWidget(c)

        # previous vs new
        if cmp_:
            candidate_note = {'extrinsic': 'Candidate: alignment only · camera settings kept',
                              'intrinsic': 'Candidate: camera settings only · alignment kept',
                              'full': 'Candidate: camera settings and alignment'}
            c, cl = card("Previous vs new calibration", candidate_note.get(s['mode'], 'Review the candidate values'))
            rows, groups, group = [], [], None
            for x in cmp_["rows"]:
                if x["group"] != group:
                    group = x["group"]
                    groups.append(len(rows))
                    rows.append(["Intrinsics (camera)" if group == "intrinsics" else "Extrinsics (LiDAR → camera)"])
                name, unit, nd = PARAMS[x["key"]]
                u = f" {unit}" if unit else ""
                if not x["refined"]:
                    rows.append([(name, MUTED), (core.fmt(x["previous"], nd, u), MUTED), (core.fmt(x["new"], nd, u), MUTED), ("—", MUTED),
                                 ("—", MUTED), ("kept (not refined)", MUTED), ("—", MUTED)])
                    continue
                stat = x["statistical"] or "–"
                sc = {"within noise": (INK2, INFO_SOFT), "borderline": (WARN, WARN_SOFT), "significant": (BLUE, BLUE_SOFT)}.get(stat, (INK2, None))
                pr = x["practical"] or ""
                pc = {"negligible": (GOOD, GOOD_SOFT), "small": (WARN, WARN_SOFT), "large": (BAD, BAD_SOFT)}.get(pr, (INK2, None))
                rows.append([name, core.fmt(x["previous"], nd, u), (core.fmt(x["new"], nd, u), INK, None, True), core.sgn(x["change"], nd, u),
                             "± " + core.fmt(x["uncertainty"], nd, u) if core.fin(x["uncertainty"]) else "–",
                             (stat + (f"  ({core.fmt(x['z'], 1)}×)" if core.fin(x["z"]) else ""), sc[0], sc[1], True),
                             (f"{core.fmt(x['pixel_effect'], 1)} px  {pr}" if core.fin(x["pixel_effect"]) else "–", pc[0], pc[1], True)])
            comparison_table = table(["Parameter", "Previous", "New", "Change", "Uncertainty", "Evidence", "Pixel effect"],
                                     rows, numeric=[1, 2, 3, 4], group_rows=groups, stretch=(0, 5, 6))
            comparison_table.setToolTip('Evidence: change divided by uncertainty. Below 2×: within noise; '
                                        '2–3×: borderline; above 3×: significant. Pixel effect: that parameter alone, '
                                        'with translation evaluated at 3 m.')
            table_column = QtWidgets.QWidget()
            table_layout = QtWidgets.QVBoxLayout(table_column)
            table_layout.setContentsMargins(0, 0, 0, 0)
            table_layout.addWidget(comparison_table)
            table_layout.addWidget(label('Pixel effect: each change on its own. The overall shift above guides the decision.',
                                         'small', wrap=True))
            table_layout.addStretch(1)
            cl.addWidget(ComparisonColumns(table_column, CalibrationPosePanel(cmp_)))
            v.addWidget(c)

        # images
        c, cl = card("Images: previous vs refined")
        views = [(x["name"], x["image"], x["flicker"] if x["flicker"].exists() else None) for x in info["captures"]]
        views += [(img_label(p), p, None) for p in info["extra"]]
        sel = QtWidgets.QComboBox()
        for name, *_ in views:
            sel.addItem(name)
        b_side, b_flick = button("Side by side"), button("Flicker (previous ↔ refined)")
        for b in (b_side, b_flick):
            b.setCheckable(True)
        grp = QtWidgets.QButtonGroup(c)
        grp.addButton(b_side)
        grp.addButton(b_flick)
        b_side.setChecked(True)
        cl.addWidget(hbox(sel, b_side, b_flick, stretch_at=3))
        view = ImageView(views[0][1] if views else None, caption=views[0][0] if views else "")
        cl.addWidget(view)
        legend = label(f"<span style='color:#2fb84f'>●</span> LiDAR edge on an image edge &nbsp; <span style='color:#e8c21e'>●</span> 1-3 px off "
                       f"&nbsp; <span style='color:#d94040'>●</span> further off &nbsp; <span style='color:{BLUE}'>●</span> previous &nbsp; "
                       f"<span style='color:{ORANGE}'>●</span> refined<br>Top: LiDAR edges on image edges with the previous and the refined "
                       "calibration. Bottom: how far the refinement moves each LiDAR point, and zooms. Click the image to enlarge.",
                       "muted", wrap=True, rich=True)
        cl.addWidget(legend)

        def show_view(k=None):
            k = sel.currentIndex() if k is None else k
            if k < 0:
                return
            name, img, gif = views[k]
            b_flick.setEnabled(gif is not None)
            if gif is None:
                b_side.setChecked(True)
            view.caption = name
            view.set_source(gif if b_flick.isChecked() and gif else img)
            legend.setVisible(k < len(info["captures"]))
        sel.currentIndexChanged.connect(show_view)
        grp.buttonClicked.connect(lambda *_: show_view())
        if views:
            show_view(0)
        v.addWidget(c)

        # evidence
        ev = [("capture " + x["left_out"], x) for x in s.get("leave_one_out") or []] + [(x["left_out"], x) for x in s.get("leave_one_region_out") or []]
        if ev:
            c, cl = card("Evidence: leave one out", "Each row: refine without that capture or image region, then compare previous "
                         "and refined on what was left out (share of LiDAR edges on an image edge).")
            cl.addWidget(table(["Left out", "Shift of the refit", "Previous on it", "Refined on it", "Fits it better?"],
                               [[name, core.fmt(x["shift_px"], 2, " px"), f"{x['heldout_existing_share'] * 100:.1f} %",
                                 f"{x['heldout_refined_share'] * 100:.1f} %",
                                 ("✓ yes", GOOD, GOOD_SOFT, True) if x["improved"] else ("no", MUTED)] for name, x in ev],
                               numeric=[1, 2, 3]))
            v.addWidget(c)

        # actions
        c, cl = card("Use the result")
        out = info["out"]
        not_advised = s["verdict"] in ("NO UPDATE NEEDED", "INCONCLUSIVE", "BORDERLINE")
        self.accept_btn = button("✓ Accepted" if info["accepted"] else "Accept refined calibration", slot=lambda: self.accept_run(s, not_advised))
        self.accept_btn.setEnabled(not info["accepted"])
        cl.addWidget(hbox(button("Save refined calibration…", "primary", lambda: self.save_refined(out)), self.accept_btn,
                          button("Open results folder", slot=lambda: os.startfile(str(out))),
                          button("Show report", slot=lambda: self.show_report(out)),
                          button("Check again with these inputs", slot=lambda: self.check_again.emit(
                              info["inputs"].get("calibration", ""), info["inputs"].get("data", ""), info["inputs"].get("device", ""))),
                          stretch_at=5))
        extra = []
        if info.get("device"):
            extra.append(button("Write to the device…", "primary", lambda: self.write_device(info)))
            if any(w.get("backup") for w in info.get("device_writes") or []):
                extra.append(button("Restore the previous calibration on the device…", slot=lambda: self.restore_device(info)))
        if s["verdict"] in ("LARGE CHANGE", "INCONCLUSIVE") and info["inputs"].get("script") != "full_calibration.py" \
                and not any(x.get("stage") == "scratch" for x in info["stages"]):
            extra.append(button("Full calibration from scratch", slot=lambda: self.main.launch_scratch(info)))
        if extra:
            cl.addWidget(hbox(*extra, stretch_at=len(extra)))
            if info.get("device"):
                writes = [w for w in info.get("device_writes") or [] if w.get("backup")]
                cl.addWidget(label(("Last written to the device: " + writes[-1]["date"].replace("T", " ")
                                    + (" (pipeline restarted)" if writes[-1].get("restarted") else " (used after the next pipeline restart)"))
                                   if writes else
                                   "Write to the device: shows the change and the exact file edit first, asks before writing and again "
                                   "before restarting the sensor pipeline, and keeps a backup on the device.", "muted", wrap=True))
        self.accept_note = label(
            f"Accepted: {info['accepted']}" if info["accepted"] else
            (f"The verdict is <b>{s['verdict'].lower()}</b>, so accepting is not advised. " if not_advised else
             "Accepting writes the refined calibration as a new dated file in <i>accepted/</i> and records it in the history. ")
            + " The previous calibration file is never changed.", "muted", wrap=True, rich=True)
        cl.addWidget(self.accept_note)
        v.addWidget(c)
        v.addStretch(1)
        self.result_lay.addWidget(scroll(page))

    def write_device(self, info):
        from device_ui import WriteDialog
        WriteDialog(self, info).exec_()
        self.main.refresh_runs()
        self.open(self.name)

    def restore_device(self, info):
        from device_ui import RestoreDialog
        RestoreDialog.run(self, info)
        self.main.refresh_runs()
        self.open(self.name)

    def save_refined(self, out):
        src = Path(out) / "refined_calibration.json"
        p, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save refined calibration",
                                                     str(Path.home() / "Downloads" / f"{self.name}_refined_calibration.json"),
                                                     "Calibration (*.json)")
        if p:
            shutil.copyfile(src, p)

    def accept_run(self, s, not_advised):
        if not_advised and QtWidgets.QMessageBox.question(
                self, "Accept anyway?", f"The verdict is {s['verdict']}. Accept the refined calibration anyway?") != QtWidgets.QMessageBox.Yes:
            return
        from accept import accept
        dst = accept(self.name)
        self.accept_btn.setText("✓ Accepted")
        self.accept_btn.setEnabled(False)
        self.accept_note.setText(f"Accepted: {dst}. The previous calibration file is not changed.")
        self.accepted_run.emit()

    def show_report(self, out):
        d = QtWidgets.QDialog(self)
        d.setWindowTitle(f"Report: {self.name}")
        lay = QtWidgets.QVBoxLayout(d)
        tb = QtWidgets.QTextBrowser()
        tb.setMarkdown((Path(out) / "report.md").read_text(encoding="utf-8"))
        lay.addWidget(tb)
        d.resize(1000, 760)
        d.exec_()


# ================================================================== main window
class Main(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Calibration maintenance")
        self.setWindowIcon(app_icon())
        self.procs = {}

        side = QtWidgets.QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(246)
        sl = QtWidgets.QVBoxLayout(side)
        sl.setContentsMargins(14, 18, 10, 14)
        sl.setSpacing(10)
        logo = QtWidgets.QLabel()
        logo.setPixmap(app_icon().pixmap(36, 36))
        sl.addWidget(hbox(logo, label("<b style='font-size:12pt'>Calibration<br>maintenance</b>", rich=True), stretch_at=2, spacing=10))
        self.nav_dev = button("Connected devices", "primary", self.show_devices)
        self.nav_man = button("Manual check", slot=self.new_check)
        sl.addWidget(self.nav_dev)
        sl.addWidget(self.nav_man)
        sl.addSpacing(6)
        sl.addWidget(label("CHECKS", "caps"))
        self.runs = QtWidgets.QListWidget()
        self.runs.setObjectName("runs")
        self.runs.setIconSize(QtCore.QSize(14, 14))
        self.runs.itemClicked.connect(lambda it: self.open_run(it.data(Qt.UserRole)))
        sl.addWidget(self.runs, 1)

        self.setup = SetupPage()
        self.setup.run_requested.connect(self.start_run)
        self.run_page = RunPage(self)
        self.run_page.check_again.connect(self.check_again)
        self.run_page.accepted_run.connect(self.refresh_runs)
        from device_ui import DevicePage
        self.devices = DevicePage(self)
        self.devices.run_ready.connect(self.launch)
        self.stack = QtWidgets.QStackedWidget()
        self.stack.addWidget(self.setup)
        self.stack.addWidget(self.run_page)
        self.stack.addWidget(self.devices)
        self.stack.setCurrentWidget(self.devices)

        central = QtWidgets.QWidget()
        cl = QtWidgets.QHBoxLayout(central)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(side)
        cl.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(1000)
        self.refresh_runs()

    # ---- runs
    def is_running(self, name):
        p = self.procs.get(name)
        return p is not None and p.poll() is None

    def exit_code(self, name):
        p = self.procs.get(name)
        return None if p is None else p.poll()

    def start_run(self, cal, data, mode, device):
        name, out, args = core.new_run(cal, data, mode, device)
        self.launch(name, args)

    def launch_scratch(self, info):
        """Full calibration from scratch on the same captures, compared with the same existing calibration."""
        inp = info["inputs"]
        if not ask_yes(self, "Full calibration from scratch", "Calibrate from scratch on the same captures (targetless, no "
                       "starting values, takes a few minutes), then compare the result with the existing calibration like a normal check?"):
            return
        dev = inp.get("device") or "rig"
        name = core.run_name(dev, "_scratch")
        out = core.RESULTS / name
        out.mkdir(parents=True, exist_ok=True)
        if info.get("device"):
            shutil.copyfile(info["out"] / "device.json", out / "device.json")
        _, _, args = core.new_run(inp["calibration"], inp["data"], "full", dev, name=name, script="full_calibration.py")
        self.launch(name, args)

    def launch(self, name, args):
        out = core.RESULTS / name
        exe = Path(sys.executable)
        if exe.name.lower() == "pythonw.exe":
            exe = exe.with_name("python.exe")
        logf = open(out / "run.log", "w")
        self.procs[name] = subprocess.Popen([str(exe)] + args, cwd=str(core.CODE), stdout=logf, stderr=subprocess.STDOUT,
                                            env=dict(os.environ, PYTHONIOENCODING="utf-8"),
                                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.refresh_runs()
        self.open_run(name)

    def tick(self):
        if self.stack.currentWidget() is self.run_page and self.run_page.name:
            p = self.procs.get(self.run_page.name)
            if p is not None and (p.poll() is None or not getattr(p, "_final", False)):
                if p.poll() is not None:
                    p._final = True                  # one last refresh after the run ends
                self.run_page.refresh()
        for name, p in list(self.procs.items()):
            if p.poll() is not None and not getattr(p, "_seen", False):
                p._seen = True
                self.refresh_runs()

    def refresh_runs(self):
        cur = self.run_page.name if self.stack.currentWidget() is self.run_page else None
        self.runs.clear()
        for r in core.list_runs():
            running = self.is_running(r["name"])
            if running:
                col, sub = BLUE, "running…"
            elif r["verdict"]:
                col = VERDICT.get(r["verdict"], VERDICT["INCONCLUSIVE"])[0]
                sub = f"{r['verdict'].lower()} · {core.fmt(r['shift'])} px" + (" · accepted" if r["accepted"] else "")
            else:
                col, sub = MUTED, "stopped with an error" if self.exit_code(r["name"]) not in (None, 0) else "incomplete"
            when = r["date"].replace("T", " ")[:16] if r["date"] else datetime.fromtimestamp(r["time"]).strftime("%Y-%m-%d %H:%M")
            title = r["device"] if r["device"] and r["device"] != "rig" else r["name"]
            it = QtWidgets.QListWidgetItem(dot_icon(col), f"{title}\n{sub}\n{when}")
            it.setData(Qt.UserRole, r["name"])
            it.setToolTip(r["name"])
            self.runs.addItem(it)
            if r["name"] == cur:
                it.setSelected(True)

    def open_run(self, name):
        for b in (self.nav_dev, self.nav_man):
            b.setObjectName("")
            b.style().unpolish(b)
            b.style().polish(b)
        self.stack.setCurrentWidget(self.run_page)
        self.run_page.open(name)
        for k in range(self.runs.count()):
            self.runs.item(k).setSelected(self.runs.item(k).data(Qt.UserRole) == name)

    def nav(self, page):
        self.runs.clearSelection()
        self.stack.setCurrentWidget(page)
        for b, on in ((self.nav_dev, page is self.devices), (self.nav_man, page is self.setup)):
            b.setObjectName("primary" if on else "")
            b.style().unpolish(b)
            b.style().polish(b)

    def show_devices(self):
        self.nav(self.devices)

    def new_check(self):
        self.nav(self.setup)

    def check_again(self, cal, data, device):
        self.new_check()
        self.setup.prefill(cal, data, device)

    def closeEvent(self, e):
        running = [n for n in self.procs if self.is_running(n)]
        if running and QtWidgets.QMessageBox.question(
                self, "A check is running", "A check is still running. Stop it and close?") != QtWidgets.QMessageBox.Yes:
            e.ignore()
            return
        for n in running:
            self.procs[n].terminate()
        self.devices.shutdown()
        e.accept()


def ask_yes(parent, title, text):
    m = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Question, title, text, parent=parent)
    y = m.addButton("Start", QtWidgets.QMessageBox.AcceptRole)
    m.setDefaultButton(m.addButton("Cancel", QtWidgets.QMessageBox.RejectRole))
    m.exec_()
    return m.clickedButton() is y


def excepthook(kind, value, tb):
    text = "".join(traceback.format_exception(kind, value, tb))
    try:
        (core.RESULTS / "app_error.log").write_text(text)
    except OSError:
        pass
    QtWidgets.QMessageBox.critical(None, "Something went wrong", text[-1500:])


def main():
    if sys.platform == "win32":
        import ctypes

        # Give this app its own taskbar group instead of inheriting pythonw's icon.
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("UNSW.AMT.CalibrationMaintenance")
    sys.excepthook = excepthook
    QtWidgets.QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QtWidgets.QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QtWidgets.QApplication(sys.argv)
    app.setStyle("Fusion")
    pal = app.palette()
    pal.setColor(QtGui.QPalette.Window, QtGui.QColor(BG))
    pal.setColor(QtGui.QPalette.Base, QtGui.QColor("white"))
    pal.setColor(QtGui.QPalette.Text, QtGui.QColor(INK))
    pal.setColor(QtGui.QPalette.WindowText, QtGui.QColor(INK))
    pal.setColor(QtGui.QPalette.ButtonText, QtGui.QColor(INK))
    pal.setColor(QtGui.QPalette.Highlight, QtGui.QColor(BLUE))
    app.setPalette(pal)
    app.setStyleSheet(QSS)
    app.setWindowIcon(app_icon())
    w = Main()
    app.aboutToQuit.connect(w.devices.shutdown)
    screen = app.primaryScreen().availableGeometry()
    w.resize(min(1680, int(screen.width() * 0.92)), min(1020, int(screen.height() * 0.90)))
    w.show()
    arg = lambda k: sys.argv[sys.argv.index(k) + 1] if k in sys.argv else None
    if arg("--run"):                                 # open a run directly: python app.py --run creep_vs_sep29
        w.open_run(arg("--run"))
    if "--manual" in sys.argv:
        w.new_check()
    if arg("--prefill"):                             # python app.py --prefill <calibration.json> <captures folder>
        w.setup.prefill(arg("--prefill"), sys.argv[sys.argv.index("--prefill") + 2])
    if arg("--tab"):
        w.run_page.tabs.setCurrentIndex(int(arg("--tab")))
    if arg("--snap"):                                # save a screenshot of the window and close: --snap out.png
        QtCore.QTimer.singleShot(3000, lambda: (w.grab().save(arg("--snap")), app.quit()))
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
