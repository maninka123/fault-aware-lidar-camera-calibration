"""Calibration maintenance - desktop app (PyQt5).

Start:  start_app.bat   (or: python app.py)

Connected devices (device_ui.py): connect to one sensor device at a time (Central Monitoring Platform
devices), capture a few seconds of its camera + LiDAR data, check its calibration, and - only after
review and confirmation - write the new calibration into the device (SSH, with a backup).
Check files: 1. the previous calibration (a suggested one, a JSON/TXT calibration, or values typed in);
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
from ui_widgets import MODE_NAMES, OptionsResults, SourceStrip, UpdateChoice, PageTabs, action_flow, EvidenceColumns  # noqa: E402
from matrix_preview import MatrixPreview, ResultHeader
import result_sections
from capture_help import CaptureFormatDialog  # noqa: E402

from ui_common import (BAD, BAD_SOFT, BG, BLUE, BLUE_SOFT, GOOD, GOOD_SOFT, INFO_SOFT, INK, INK2, MUTED, MONO, ORANGE, PARAMS, QSS,  # noqa: E402
                       STAGES, VERDICT, WARN, WARN_SOFT, Gauge, ImageView, ManualDialog, StepTracker, app_icon, badge_icon, button, calibration_view,
                       card, clear, dot_icon, hbox, image_grid, img_label, label, navigation_icon, np_to_pixmap, scroll, table)
from calibration_io import MODE_LABELS, write_calibration_txt


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
    run_requested = QtCore.pyqtSignal(str, str, str, str, str, bool)

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
        self.example_cal_button = button("Use example values", "link", self.use_example_cal)
        self.example_cal_button.setToolTip("Load the Feb 2025 enclosure camera intrinsics and LiDAR → camera alignment (484 × 366).")
        l1.addWidget(hbox(self.example_cal_button, label("Feb 2025 · enclosure · 484 × 366", "small"), stretch_at=2))
        self.cal_err = label("", "err", wrap=True)
        self.cal_err.hide()
        l1.addWidget(self.cal_err)
        self.cal_box = QtWidgets.QVBoxLayout()
        l1.addLayout(self.cal_box)
        v.addWidget(c1)

        # 2. new captures
        c2, l2 = card()
        self.h2 = StepHeader(2, "New captures", "Choose image + PCD pairs, recorded bags or stacked captures")
        self.capture_format_button = button('Capture format', 'link', self.show_capture_format)
        self.capture_format_button.setAccessibleName('Show accepted capture folder layouts')
        l2.addWidget(hbox(self.h2, self.capture_format_button, stretch_at=1))
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
        self.pair_options = QtWidgets.QWidget()
        pair_layout = QtWidgets.QVBoxLayout(self.pair_options)
        pair_layout.setContentsMargins(0, 4, 0, 0)
        pair_layout.setSpacing(6)
        self.pair_units = QtWidgets.QComboBox()
        self.pair_units.addItem('Metres (m)', 'm')
        self.pair_units.addItem('Millimetres (mm)', 'mm')
        self.pair_units.setAccessibleName('Coordinate units in PCD files')
        self.pair_units.setMinimumWidth(180)
        self.pair_report_button = button('View pairs', 'link', self.show_pair_report)
        pair_layout.addWidget(hbox(label('PCD units', 'h3'), self.pair_units, self.pair_report_button, stretch_at=3))
        self.pair_status = label('', 'small', wrap=True)
        self.pair_status.setToolTip('File names, readability, XYZ fields, image dimensions and coordinate ranges are checked. '
                                    'PCD has no standard unit declaration; ranges are a sanity check, not proof of units.')
        pair_layout.addWidget(self.pair_status)
        self.units_confirm = QtWidgets.QCheckBox('I confirm these coordinate units')
        self.units_confirm.hide()
        pair_layout.addWidget(self.units_confirm)
        self.pair_options.hide()
        l2.addWidget(self.pair_options)
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
        self.research_go = button('Fault-aware check…', slot=self.open_research)
        self.research_go.setToolTip('Open the offline fault-aware assessment with this calibration and these captures. No device writes.')
        self.hint = label("", "muted", wrap=True)
        self.update_choice.currentIndexChanged.connect(self.update_ready)
        l3.addWidget(hbox(self.go, self.hint, stretch_at=2, spacing=16))
        l3.addWidget(hbox(self.research_go, stretch_at=1))
        v.addWidget(c3)
        v.addStretch(1)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(scroll(page))
        self.pair_units.currentIndexChanged.connect(self.validate_paired_data)
        self.units_confirm.toggled.connect(self.update_ready)
        self.update_ready()

    # ---- previous calibration
    def load_cal(self, path):
        try:
            self.cal = core.calibration_info(path)
        except (OSError, ValueError, KeyError, TypeError) as err:
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
        p, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Existing calibration", start,
                                                   "Calibration files (*.json *.txt);;JSON calibration (*.json);;Calibration TXT (*.txt)")
        if p:
            self.cal_combo.setCurrentIndex(0)
            self.load_cal(p)

    def use_example_cal(self):
        index = self.cal_combo.findData(str(core.EXAMPLE_CALIBRATION))
        self.cal_combo.setCurrentIndex(max(0, index))
        self.load_cal(core.EXAMPLE_CALIBRATION)

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
            kind = {'raw': 'raw captures, decoded during the check', 'stacked': 'stacked captures',
                    'paired': 'image + PCD pairs'}[d['kind']]
            self.pair_options.setVisible(d['kind'] == 'paired')
            head = label(f"<b>{len(d['captures'])} {kind}</b> &nbsp; <span style='color:{MUTED}; font-family:Consolas'>{d['name']}</span>", rich=True)
            self.data_box.addWidget(head)
            row = QtWidgets.QHBoxLayout()
            row.setSpacing(12)
            for index, c in enumerate(d["captures"][:6], 1):
                box = QtWidgets.QVBoxLayout()
                box.setSpacing(2)
                if c["npz"] or c.get('image'):
                    iv = ImageView(pixmap=np_to_pixmap(core.capture_image(c['npz'] or c['image'])),
                                   caption=core.capture_display_name(c['name'], index))
                else:
                    iv = label(f"raw bag\n{c['size_mb']:.0f} MB")
                    iv.setAlignment(Qt.AlignCenter)
                    iv.setMinimumHeight(120)
                    iv.setStyleSheet(f"background: {INFO_SOFT}; border-radius: 8px; color: {MUTED};")
                iv.setMaximumWidth(260)
                box.addWidget(iv)
                cap = label(core.capture_display_name(c['name'], index), "small")
                cap.setToolTip(c['name'])
                box.addWidget(cap)
                row.addLayout(box)
            row.addStretch(1)
            self.data_box.addLayout(row)
            if d['kind'] == 'paired':
                self.validate_paired_data()
        except (ValueError, OSError, KeyError) as err:
            self.data = None
            self.pair_options.hide()
            self.data_err.setText(str(err))
            self.data_err.show()
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        self.pair_report_button.setEnabled(bool(self.data and self.data.get('paired_validation')))
        self.update_ready()

    def open_data(self):
        start = self.data["path"] if self.data else str(core.TARGETLESS)
        p = QtWidgets.QFileDialog.getExistingDirectory(self, "Folder with the new captures", start)
        if p:
            self.data_combo.setCurrentIndex(0)
            self.load_data(p)

    def show_capture_format(self):
        if CaptureFormatDialog(self).exec_() == QtWidgets.QDialog.Accepted:
            self.open_data()

    def validate_paired_data(self):
        if not self.data or self.data['kind'] != 'paired':
            return
        from paired_data import validate_pairs
        from settings import load_config
        self.data.pop('paired_validation', None)
        self.units_confirm.setChecked(False)
        QtWidgets.QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            checked = validate_pairs(self.data['path'], self.pair_units.currentData(), load_config()['decision']['probe_range_m'])
            self.data['paired_validation'] = checked
            self.data['cloud_units'] = checked['units']
            self.units_confirm.setVisible(checked['units_review'])
            if checked['units_review']:
                text = next(row['message'] for row in checked['reports'] if row['units_review'])
                colour = WARN
            elif not checked['analysis_usable']:
                lo, hi = checked['probe_range_m']
                text, colour = f'Too few points at {lo:g}–{hi:g} m. Check units or use nearer scene structure.', BAD
            else:
                median = sorted(row['median_range_m'] for row in checked['reports'])[len(checked['reports']) // 2]
                text = f'{len(checked["captures"])} pairs checked · files readable · typical range {median:.2f} m'
                if checked['warnings']:
                    text += f' · {len(checked["warnings"])} notes in View pairs'
                colour = GOOD
            self.pair_status.setText(text)
            self.pair_status.setStyleSheet(f'color: {colour};')
        except (ValueError, OSError) as error:
            self.pair_status.setText(str(error))
            self.pair_status.setStyleSheet(f'color: {BAD};')
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        self.pair_report_button.setEnabled(bool(self.data.get('paired_validation')))
        self.update_ready()

    def show_pair_report(self):
        checked = self.data and self.data.get('paired_validation')
        if not checked:
            return
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle('Pair checks')
        dialog.resize(1000, 500)
        layout = QtWidgets.QVBoxLayout(dialog)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.addWidget(label('Matched image + PCD files', 'h2'))
        layout.addWidget(label('PCD units: ' + ('metres' if checked['units'] == 'm' else 'millimetres'), 'small'))
        root = Path(self.data['path'])
        rows = [[str(Path(row['image']).relative_to(root)), str(Path(row['cloud']).relative_to(root)),
                 f'{row["points"]:,}', f'{row["median_range_m"]:.2f} m',
                 f'{row["range_5_95_m"][0]:.2f}–{row["range_5_95_m"][1]:.2f} m',
                 'Check units' if row['units_review'] else 'Readable'] for row in checked['reports']]
        content = QtWidgets.QWidget()
        details = QtWidgets.QVBoxLayout(content)
        details.addWidget(table(['Image', 'PCD', 'Points', 'Median range', '90% range', 'Check'], rows, numeric=(2, 3, 4), stretch=(0, 1)))
        for note in checked['warnings']:
            details.addWidget(label(note, 'small', wrap=True))
        details.addWidget(label('Use synchronized pairs in the LiDAR coordinate frame. Ranges cannot prove the units.', 'small', wrap=True))
        layout.addWidget(scroll(content))
        layout.addWidget(hbox(button('Done', slot=dialog.accept), stretch_at=0))
        dialog.exec_()

    # ---- calculate
    def update_ready(self):
        self.h1.set_done(bool(self.cal))
        checked = self.data and self.data.get('paired_validation')
        paired_ready = bool(checked and checked['analysis_usable'] and
                            (not checked['units_review'] or self.units_confirm.isChecked()))
        inputs_ready = bool(self.data and (self.data['kind'] != 'paired' or paired_ready))
        self.h2.set_done(inputs_ready)
        ready = bool(self.cal and self.data)
        reason = ''
        if self.data and self.data['kind'] == 'paired':
            ready = ready and paired_ready
            if not paired_ready:
                reason = 'Review the image/PCD checks and coordinate units above.'
            if checked and self.cal and self.cal['intrinsics'].get('image_size'):
                if list(self.cal['intrinsics']['image_size']) != checked['image_size']:
                    ready = False
                    reason = 'Image resolution differs from this calibration. Choose a calibration for this resolution.'
        self.go.setEnabled(ready)
        self.research_go.setEnabled(bool(ready))
        self.hint.setText(("Tests four update choices. Allow a few minutes." if self.update_choice.currentData() == 'compare'
                           else f"Checks {len(self.data['captures'])} captures.") if ready
                          else reason or "Choose a calibration and captures to continue.")

    def calculate(self):
        self.run_requested.emit(self.cal["path"], self.data["path"], self.update_choice.currentData(),
                                self.device.text().strip() or "rig", self.pair_units.currentData(), self.units_confirm.isChecked())

    def open_research(self):
        """Open the fault-aware assessment window (research_gui.py) with the chosen inputs."""
        import subprocess
        gui = Path(__file__).resolve().parents[2] / 'research_gui.py'
        exe = Path(sys.executable)
        if exe.name.lower() == 'python.exe' and exe.with_name('pythonw.exe').exists():
            exe = exe.with_name('pythonw.exe')
        subprocess.Popen([str(exe), str(gui), '--prefill', self.cal['path'], self.data['path']], cwd=str(gui.parent))

    def prefill(self, cal, data, device=None, cloud_units='m', allow_unusual_units=False):
        if cal and Path(cal).exists():
            self.load_cal(cal)
        if data and Path(data).exists():
            self.load_data(data)
            self.pair_units.setCurrentIndex(max(0, self.pair_units.findData(cloud_units)))
            self.units_confirm.setChecked(allow_unusual_units)
        if device:
            self.device.setText(device)


# ================================================================== page: a run
class RunPage(QtWidgets.QWidget):
    check_again = QtCore.pyqtSignal(str, str, str, str, bool)
    accepted_run = QtCore.pyqtSignal()

    def __init__(self, main):
        super().__init__()
        self.main = main
        self.name = None
        self.export_dataset_folder = None
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
        self.matrix_preview = MatrixPreview()
        self.matrix_preview.hide()
        self.result_header = ResultHeader(self.banner, self.matrix_preview)
        v.addWidget(self.result_header)

        self.tracker = StepTracker()
        self.tracker.clicked.connect(self.select_stage_key)
        v.addWidget(self.tracker)

        self.tabs = QtWidgets.QTabWidget()
        self.tabs.tabBar().setExpanding(False)
        self.tabs.tabBar().setElideMode(Qt.ElideNone)
        self.tabs.tabBar().hide()
        self.tabs.currentChanged.connect(lambda index: self.tracker.setVisible(index == 0))
        v.addWidget(self.tabs, 1)

        # processing tab
        proc = QtWidgets.QWidget()
        pl = QtWidgets.QVBoxLayout(proc)
        pl.setContentsMargins(0, 8, 0, 0)
        self.processing_nav = PageTabs(self.tabs)
        pl.addWidget(self.processing_nav, 0, Qt.AlignLeft)
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
        self.matrix_preview.hide()
        self.toggle_log(False)
        self.tabs.setTabEnabled(1, False)
        self.processing_nav.setTabEnabled(1, False)
        self.tabs.setCurrentIndex(0)
        self.refresh()

    def refresh(self):
        if not self.name:
            return
        info = core.run_info(self.name)
        running = self.main.is_running(self.name)
        failed = not running and not info["finished"] and self.main.exit_code(self.name) not in (None, 0)
        inp = info["inputs"]
        self.title.setText(core.capture_label(inp.get('data')) or inp.get("device") or self.name)
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
            self.processing_nav.setTabEnabled(1, True)
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
        dataset = info['inputs'].get('data') or s.get('data')
        self.export_dataset_folder = core.resolve(dataset) if dataset else None
        self.export_txt_btn = None
        self.export_mode_label = None
        self.export_calibrations = result_sections.export_calibrations(info)
        self.selected_result_mode = s['mode']
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
        self.result_nav = PageTabs(self.tabs)
        v.addWidget(self.result_nav, 0, Qt.AlignLeft)

        if s.get('strategy_comparison'):
            c, cl = card('What should you update?')
            comparison = s['strategy_comparison']
            self.matrix_preview.set_calibrations(comparison.get('calibrations', {}))
            self.options_results = OptionsResults(comparison)
            self.options_results.mode_changed.connect(self.preview_mode)
            self.preview_mode(self.options_results.active_mode)
            self.matrix_preview.show()
            cl.addWidget(self.options_results)
            v.addWidget(c)

        # sections shared with the fault-aware app's Calibration review tab (result_sections.py)
        v.addLayout(result_sections.metric_row(s))
        v.addWidget(result_sections.shift_card(s))
        if cmp_:
            v.addWidget(result_sections.parameter_card(s, cmp_))
        v.addWidget(result_sections.CaptureComparison(info))
        evidence = result_sections.evidence_card(s)
        if evidence is not None:
            v.addWidget(evidence)

        # actions
        c, cl = card("Use the result")
        out = info["out"]
        not_advised = s["verdict"] in ("NO UPDATE NEEDED", "INCONCLUSIVE", "BORDERLINE")
        self.accept_btn = button("✓ Accepted" if info["accepted"] else "Accept refined calibration", slot=lambda: self.accept_run(s, not_advised))
        self.accept_btn.setEnabled(not info["accepted"])
        self.export_mode_label = label('', 'small')
        self.export_mode_label.setObjectName('selectedCalibrationMode')
        cl.addWidget(self.export_mode_label)
        self.export_txt_btn = button('Save calibration TXT…', 'primary', self.save_selected_txt)
        self.export_txt_btn.setObjectName('exportCalibrationTxt')
        self.preview_mode(self.selected_result_mode)
        action_buttons = [self.export_txt_btn, button("Save refined JSON…", slot=lambda: self.save_refined(out)), self.accept_btn,
                          button("Open results folder", slot=lambda: os.startfile(str(out))),
                          button("Show report", slot=lambda: self.show_report(out)),
                          button("Check again with these inputs", slot=lambda: self.check_again.emit(
                              info["inputs"].get("calibration", ""), info["inputs"].get("data", ""), info["inputs"].get("device", ""),
                              info['inputs'].get('cloud_units', 'm'), info['inputs'].get('allow_unusual_units', False)))]
        extra = []
        if info.get("device"):
            extra.append(button("Write to the device…", "primary", lambda: self.write_device(info)))
            if any(w.get("backup") for w in info.get("device_writes") or []):
                extra.append(button("Restore the previous calibration on the device…", slot=lambda: self.restore_device(info)))
        if s["verdict"] in ("LARGE CHANGE", "INCONCLUSIVE") and info["inputs"].get("script") != "full_calibration.py" \
                and not any(x.get("stage") == "scratch" for x in info["stages"]):
            extra.append(button("Full calibration from scratch", slot=lambda: self.main.launch_scratch(info)))
        if extra:
            action_buttons.extend(extra)
            if info.get("device"):
                writes = [w for w in info.get("device_writes") or [] if w.get("backup")]
                cl.addWidget(label(("Last written to the device: " + writes[-1]["date"].replace("T", " ")
                                    + (" (pipeline restarted)" if writes[-1].get("restarted") else " (used after the next pipeline restart)"))
                                   if writes else
                                   "Write to the device: shows the change and the exact file edit first, asks before writing and again "
                                   "before restarting the sensor pipeline, and keeps a backup on the device.", "muted", wrap=True))
        cl.insertWidget(1, action_flow(action_buttons))
        self.accept_note = label(
            f"Accepted: {info['accepted']}" if info["accepted"] else
            (f"The verdict is <b>{s['verdict'].lower()}</b>, so accepting is not advised. " if not_advised else
             "Accepting writes the refined calibration as a new dated file in <i>accepted/</i> and records it in the history. ")
            + " The previous calibration file is never changed.", "muted", wrap=True, rich=True)
        cl.addWidget(self.accept_note)
        v.addWidget(c)
        v.addStretch(1)
        self.result_lay.addWidget(scroll(page))

    def preview_mode(self, mode):
        self.selected_result_mode = mode
        if self.matrix_preview.calibrations:
            self.matrix_preview.set_mode(mode)
        title = MODE_LABELS.get(mode, mode)
        if self.export_mode_label is not None:
            self.export_mode_label.setText('TXT export: ' + title)
        if self.export_txt_btn is not None:
            available = bool(self.export_calibrations.get(mode))
            self.export_txt_btn.setEnabled(available)
            self.export_txt_btn.setToolTip(f'Save the {title} camera intrinsics, distortion and LiDAR → camera extrinsics.'
                                          if available else 'This option’s fitted calibration was not saved.')

    def save_selected_txt(self):
        mode = self.selected_result_mode
        candidate = self.export_calibrations.get(mode)
        if not candidate:
            return
        title = MODE_LABELS[mode]
        folder = self.export_dataset_folder
        if folder and folder.is_file():
            folder = folder.parent
        if not folder or not folder.is_dir():
            folder = Path.home() / 'Downloads'
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, f'Save {title} calibration',
            str(folder / f'{self.name}_{mode}_calibration.txt'), 'Calibration TXT (*.txt)')
        if path:
            path = Path(path)
            if not path.suffix:
                path = path.with_suffix('.txt')
            try:
                write_calibration_txt(path, candidate, mode, self.name)
            except (OSError, ValueError) as error:
                QtWidgets.QMessageBox.warning(self, 'Could not save calibration', str(error))
                return
            self.export_mode_label.setText(f'Saved {title}: {path.name}')
            self.export_mode_label.setToolTip(str(path))

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
        self.nav_dev = button("Devices", "primary", self.show_devices)
        self.nav_man = button("Check files", slot=self.new_check)
        for control, kind, selected, tip in ((self.nav_dev, 'devices', True, 'Connect to a sensor device'),
                                             (self.nav_man, 'files', False, 'Check an existing calibration using saved capture files')):
            control.setIcon(navigation_icon(kind, selected))
            control.setIconSize(QtCore.QSize(18, 18))
            control.setToolTip(tip)
            control.setStyleSheet('font-size: 9.5pt; padding: 8px 6px;')
            control.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.nav_dev.setAccessibleName('Connected devices')
        self.nav_man.setAccessibleName('Check calibration from files')
        sl.addWidget(hbox(self.nav_dev, self.nav_man, spacing=8))
        sl.addSpacing(6)
        sl.addWidget(label("CHECKS", "caps"))
        self.runs = QtWidgets.QListWidget()
        self.runs.setObjectName("runs")
        self.runs.setIconSize(QtCore.QSize(14, 14))
        self.runs.setWordWrap(True)
        self.runs.setTextElideMode(Qt.ElideNone)
        self.runs.setResizeMode(QtWidgets.QListView.Adjust)
        self.runs.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
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

    def start_run(self, cal, data, mode, device, cloud_units='m', allow_unusual_units=False):
        name, out, args = core.new_run(cal, data, mode, device, cloud_units=cloud_units, allow_unusual_units=allow_unusual_units)
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
        _, _, args = core.new_run(inp["calibration"], inp["data"], "full", dev, name=name, script="full_calibration.py",
                                cloud_units=inp.get('cloud_units', 'm'), allow_unusual_units=inp.get('allow_unusual_units', False))
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
                sub = f"{r['verdict'].lower()} · {core.fmt(r['shift'])} px"
            else:
                col, sub = MUTED, "stopped with an error" if self.exit_code(r["name"]) not in (None, 0) else "incomplete"
            when = r["date"].replace("T", " ")[:16] if r["date"] else datetime.fromtimestamp(r["time"]).strftime("%Y-%m-%d %H:%M")
            title = r.get('display_name') or (r["device"] if r["device"] and r["device"] != "rig" else r["name"])
            it = QtWidgets.QListWidgetItem(dot_icon(col), f"{title}\n{sub}\n{when}")
            it.setData(Qt.UserRole, r["name"])
            it.setToolTip(r["name"])
            self.runs.addItem(it)
            if r["name"] == cur:
                it.setSelected(True)

    def open_run(self, name):
        for b in (self.nav_dev, self.nav_man):
            b.setObjectName("")
            b.setIcon(navigation_icon('devices' if b is self.nav_dev else 'files'))
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
            b.setIcon(navigation_icon('devices' if b is self.nav_dev else 'files', on))
            b.style().unpolish(b)
            b.style().polish(b)

    def show_devices(self):
        self.nav(self.devices)

    def new_check(self):
        self.nav(self.setup)

    def check_again(self, cal, data, device, cloud_units='m', allow_unusual_units=False):
        self.new_check()
        self.setup.prefill(cal, data, device, cloud_units, allow_unusual_units)

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
