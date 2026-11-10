"""Connected-devices mode of the desktop app.

Devices page: the devices of the Central Monitoring Platform (+ ones added here) with their status;
connect to one at a time (read-only: ROS master / TCPROS, or ROSBridge), see what it sees with the
calibration it uses now, read that calibration, capture a few seconds of camera + LiDAR data and run
the check. Write dialog: after a check, put the new calibration into the device's pipeline.yaml over
SSH - review, file diff, explicit confirmation, backup on the device and here, verification, and the
pipeline restart only when confirmed separately. Restore dialog: put the backup back.
"""
from __future__ import annotations

import json
import shutil
import threading
from datetime import datetime
from pathlib import Path

import numpy as np
from PyQt5 import QtCore, QtWidgets
from PyQt5.QtCore import Qt
from scipy.spatial.transform import Rotation

import appcore as core
import device_model as dm
import device_file
import devices as devreg
from ui_common import (BAD, BAD_SOFT, BLUE, BLUE_SOFT, GOOD, INK2, MONO, MUTED, VERDICT, WARN, WARN_SOFT,
                       ImageView, button, card, clear, dot_icon, hbox, label, np_to_pixmap, scroll, table)
from ui_widgets import UpdateChoice
from capture_cards import CaptureModeToggle, PreviewImage, capture_row, sensor_panel


# ================================================================== background work
class Task(QtCore.QThread):
    """fn(progress, stop, *args) in a thread; signals done(result) / failed(message) / progress(obj)."""
    done = QtCore.pyqtSignal(object)
    failed = QtCore.pyqtSignal(str)
    progress = QtCore.pyqtSignal(object)

    def __init__(self, fn, *args, parent=None):
        super().__init__(parent)
        self.fn, self.args, self.stop = fn, args, threading.Event()

    def run(self):
        try:
            self.done.emit(self.fn(self.progress.emit, self.stop, *self.args))
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e) or type(e).__name__)


def busy(parent, text, fn, *args, with_progress=False, on_progress=None, stop=None):
    """Run fn(*args) in a thread behind a small modal 'working' window; return its result or raise."""
    dlg = QtWidgets.QDialog(parent)
    dlg.setWindowTitle("Working")
    dlg.setWindowFlags(dlg.windowFlags() & ~Qt.WindowCloseButtonHint)
    lay = QtWidgets.QVBoxLayout(dlg)
    lay.setContentsMargins(24, 20, 24, 20)
    status = label(text, wrap=True)
    lay.addWidget(status)
    bar = QtWidgets.QProgressBar()
    bar.setRange(0, 0)
    lay.addWidget(bar)
    dlg.setMinimumWidth(420)
    box = {}
    if stop is not None:
        lay.addWidget(button("Stop", slot=stop.set))
    t = Task(lambda _p, _s: fn(_p, *args) if with_progress else fn(*args), parent=dlg)
    if with_progress:
        def report(value):
            target = value.get('target_frames')
            extent = f"{value['clouds']} / {target} LiDAR frames" if target else f"{value['elapsed']:.1f} / {value['target_seconds']:g} s · {value['clouds']} LiDAR frames"
            status.setText(text + "\n" + extent)
            if on_progress:
                on_progress(value)
        t.progress.connect(report)
    t.done.connect(lambda r: (box.update(result=r), dlg.accept()))
    t.failed.connect(lambda m: (box.update(error=m), dlg.accept()))
    t.start()
    dlg.exec_()
    t.wait()
    if "error" in box:
        raise RuntimeError(box["error"])
    return box.get("result")


def warn(parent, title, text):
    QtWidgets.QMessageBox.warning(parent, title, text)


def ask(parent, title, text, yes="Yes", no="Cancel"):
    """Question with Cancel as the default button."""
    m = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Question, title, text, parent=parent)
    y = m.addButton(yes, QtWidgets.QMessageBox.AcceptRole)
    n = m.addButton(no, QtWidgets.QMessageBox.RejectRole)
    m.setDefaultButton(n)
    m.exec_()
    return m.clickedButton() is y


# ================================================================== SSH
class PasswordDialog(QtWidgets.QDialog):
    def __init__(self, parent, device, user, why=""):
        super().__init__(parent)
        self.setWindowTitle(f"SSH login: {device['name']}")
        lay = QtWidgets.QFormLayout(self)
        if why:
            lay.addRow(label(why, "muted", wrap=True))
        self.user = QtWidgets.QLineEdit(user)
        self.pw = QtWidgets.QLineEdit()
        self.pw.setEchoMode(QtWidgets.QLineEdit.Password)
        self.remember = QtWidgets.QCheckBox("Remember the password (Windows Credential Manager)")
        lay.addRow("Device", label(f"{device['ssh_host']}:{device.get('ssh_port', 22)}"))
        lay.addRow("User", self.user)
        lay.addRow("Password", self.pw)
        lay.addRow("", self.remember)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addRow(bb)
        self.pw.setFocus()


def ssh_session(parent, device):
    """A logged-in DeviceSSH for this device, or None if the user cancelled. Uses a saved password
    (Central Monitoring Platform / this app) when there is one; asks to trust a new host key."""
    import device_ssh as ds
    host, user, port = device.get("ssh_host"), device.get("ssh_user") or "rock", int(device.get("ssh_port") or 22)
    if not host:
        warn(parent, "No SSH address", "This device has no SSH address in its configuration.")
        return None
    pw, src = ds.saved_password(host, user, port)
    remember = False
    if pw is None:
        d = PasswordDialog(parent, device, user)
        if d.exec_() != QtWidgets.QDialog.Accepted:
            return None
        user, pw, remember = d.user.text().strip() or user, d.pw.text(), d.remember.isChecked()
        if user != device.get("ssh_user"):
            devreg.save_settings(device["key"], ssh_user=user)
    s = ds.DeviceSSH(host, user, port)
    try:
        fp, state = busy(parent, f"Connecting to {user}@{host}:{port} …", s.open, device.get("ssh_fingerprint"))
    except RuntimeError as e:
        warn(parent, "SSH connection failed", str(e))
        return None
    if state == "new":
        if not ask(parent, "Trust this device?", f"This is the first SSH connection to {host} from this computer.\n\n"
                   f"Its host key fingerprint is:\n{fp}\n\nTrust it only if this is the sensor device you expect "
                   "(compare with `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` on the device).", yes="Trust and continue"):
            s.close()
            return None
        devreg.save_settings(device["key"], ssh_fingerprint=fp)
    try:
        busy(parent, "Logging in …", s.login, pw)
    except RuntimeError as e:
        if src is None:
            warn(parent, "SSH login failed", str(e))
            return None
        d = PasswordDialog(parent, device, user, why=f"The password {src} was rejected. Enter the current password.")
        if d.exec_() != QtWidgets.QDialog.Accepted:
            return None
        pw, remember = d.pw.text(), d.remember.isChecked()
        s = ds.DeviceSSH(host, user, port)
        try:
            busy(parent, "Logging in …", lambda: (s.open(device.get("ssh_fingerprint") or fp), s.login(pw)))
        except RuntimeError as e2:
            warn(parent, "SSH login failed", str(e2))
            return None
    if remember:
        ds.remember_password(host, user, port, pw)
    s.password = pw
    return s


def read_device_yaml(parent, s, device, choose_path=False):
    """(path, text) of the device's pipeline.yaml."""
    try:
        path = busy(parent, "Looking for pipeline.yaml …", s.find_yaml, device.get("yaml_path"))
    except RuntimeError:
        if not choose_path:
            raise
        path = device.get("yaml_path") or ""
    if choose_path:
        path, ok = QtWidgets.QInputDialog.getText(parent, "Device calibration file",
            f"Calibration file on {s.host} (absolute path):", text=path)
        if not ok or not path.strip():
            raise InterruptedError("Calibration file selection cancelled.")
        path = path.strip()
        if not path.startswith("/"):
            raise ValueError("Enter an absolute path on the selected device, starting with /.")
    text = busy(parent, f"Reading {path} …", s.read, path)
    devreg.save_settings(device["key"], yaml_path=path)
    device["yaml_path"] = path
    return path, text


# ================================================================== showing device calibrations
def as_calibration(params):
    """Device parameters in the calibration.json layout (for the mounting / angle description)."""
    p = dm.device_params(params)
    return dict(intrinsics=dict(camera_matrix=p["camera_matrix"], distortion_coefficients=p["dist_coeffs"][:2], distortion_model="pinhole"),
                extrinsics=dict(transform_lidar_to_camera=p["extrinsic_matrix"]), image_size=[p["image_width"], p["image_height"]])


def device_calibration_view(params, source):
    from ui_common import value_grid
    p = dm.device_params(params)
    K, D = p["camera_matrix"], p["dist_coeffs"]
    e = core.describe(as_calibration(p))["extrinsics"]
    w = QtWidgets.QFrame()
    w.setObjectName("subtle")
    lay = QtWidgets.QVBoxLayout(w)
    lay.setContentsMargins(14, 10, 14, 12)
    matrices = QtWidgets.QGridLayout()
    matrices.setHorizontalSpacing(16)
    for column, (title, matrix) in enumerate((("Camera matrix K (pixels)", K),
                          ("LiDAR → camera transform T (translation in metres)", p["extrinsic_matrix"]))):
        matrices.addWidget(label(title, "caps", wrap=True), 0, column)
        matrix_panel = QtWidgets.QFrame()
        matrix_panel.setObjectName('matrixPanel')
        matrix_panel.setStyleSheet('QFrame#matrixPanel {background: white; border: 1px solid #e5e7eb; border-radius: 14px;}')
        matrix_panel.setFixedHeight(194)
        panel_layout = QtWidgets.QVBoxLayout(matrix_panel)
        panel_layout.setContentsMargins(10, 8, 10, 10)
        panel_layout.setSpacing(4)
        values = [[f"{v: .9g}" for v in row] for row in matrix]
        widths = [max(len(row[j]) for row in values) for j in range(len(values[0]))]
        block = QtWidgets.QPlainTextEdit("\n".join("[  " + "    ".join(value.rjust(widths[j]) for j, value in enumerate(row)) + "  ]" for row in values))
        block.setReadOnly(True)
        block.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        block.setMinimumWidth(0)
        option = block.document().defaultTextOption()
        option.setAlignment(Qt.AlignHCenter)
        block.document().setDefaultTextOption(option)
        block.setStyleSheet(f"font-family: {MONO}; font-size: 18px; padding: 8px; border: none; background: transparent;")
        block.ensurePolished()
        block.setFixedHeight(int(block.fontMetrics().lineSpacing() * len(matrix)
                                 + 2 * block.document().documentMargin() + 40))
        block.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        panel_layout.addWidget(block)
        if column == 0:
            panel_layout.addWidget(label("Distortion [k1, k2, p1, p2, k3]", "small", wrap=True))
            distortion = label("[ " + "   ".join(f"{v:.9g}" for v in D) + " ]", wrap=True)
            distortion.setStyleSheet(f'font-family: {MONO}; font-size: 14px; color: #1d1d1f;')
            panel_layout.addWidget(distortion)
        panel_layout.addStretch(1)
        matrices.addWidget(matrix_panel, 1, column)
        matrices.setColumnStretch(column, 1)
    lay.addLayout(matrices)
    lay.addWidget(label(f"Source: {source} · OpenCV pinhole model · values read from the calibration file", "small", wrap=True))
    cols = QtWidgets.QHBoxLayout()
    cols.setSpacing(16)
    left = QtWidgets.QVBoxLayout()
    left.setSpacing(6)
    left.addWidget(label("INTRINSICS", "caps"))
    left.addWidget(value_grid([("fx (px)", core.fmt(K[0][0])), ("fy (px)", core.fmt(K[1][1])), ("image", f"{p['image_width']} × {p['image_height']}"),
                               ("cx (px)", core.fmt(K[0][2])), ("cy (px)", core.fmt(K[1][2])), ("", ""),
                               ("k1", core.fmt(D[0], 4)), ("k2", core.fmt(D[1], 4)), ("k3", core.fmt(D[4], 4)),
                               ("p1", core.fmt(D[2], 4)), ("p2", core.fmt(D[3], 4))]))
    left.addStretch(1)
    right = QtWidgets.QVBoxLayout()
    right.setSpacing(6)
    right.addWidget(label("EXTRINSICS  (LIDAR → CAMERA)", "caps"))
    right.addWidget(value_grid([("t x (mm)", core.fmt(e["tx"], 1)), ("t y (mm)", core.fmt(e["ty"], 1)), ("t z (mm)", core.fmt(e["tz"], 1)),
                                ("tilt (°)", core.fmt(e["tilt"], 3)), ("pan (°)", core.fmt(e["pan"], 3)), ("roll (°)", core.fmt(e["roll"], 3))]))
    right.addStretch(1)
    cols.addLayout(left, 1)
    cols.addLayout(right, 1)
    lay.addLayout(cols)
    for n in params.get("notes", []):
        lay.addWidget(note_label(n, WARN, WARN_SOFT))
    return w


def note_label(text, fg=INK2, bg=BLUE_SOFT):
    lab = label(text, wrap=True)
    lab.setStyleSheet(f"background: {bg}; color: {fg}; border-radius: 7px; padding: 7px 10px;")
    return lab


# ================================================================== the devices page
class DevicePage(QtWidgets.QWidget):
    run_ready = QtCore.pyqtSignal(str, list)          # run name, script arguments

    def __init__(self, main, choose_mode=True):
        """choose_mode=False hides the maintenance "What to check" options (the Fault-aware app has its own check)."""
        super().__init__()
        self.main = main
        self.choose_mode = choose_mode
        self.devices, self.status = [], {}
        self.link = self.current = self.params = None
        self.params_raw, self.params_source, self.topics, self.snap = None, "", {}, None
        self.tasks = []
        self.closing = False
        self.capture_running = False
        self.pending_capture = None
        self.capture_goal = None
        self.delete_after_stop = set()
        self.calibration_file_text = None
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 16)
        lay.setSpacing(16)

        left, ll = card()
        left.setFixedWidth(330)
        ll.addWidget(label("Devices", "h2"))
        ll.addWidget(label("Select a device to inspect its calibration.", "small", wrap=True))
        self.list = QtWidgets.QListWidget()
        self.list.setObjectName("runs")
        self.list.setIconSize(QtCore.QSize(14, 14))
        self.list.currentItemChanged.connect(lambda it, _: it and self.select(it.data(Qt.UserRole)))
        ll.addWidget(self.list, 1)
        ll.addWidget(hbox(button("Refresh", slot=self.refresh_list), button("Add device…", slot=self.add_device), stretch_at=2))
        self.plat = label("", "small", wrap=True)
        ll.addWidget(self.plat)
        ll.addWidget(hbox(button("Platform folder…", "link", self.choose_platform), stretch_at=1))
        lay.addWidget(left)

        self.right = QtWidgets.QWidget()
        self.right.setObjectName("page")
        self.rl = QtWidgets.QVBoxLayout(self.right)
        self.rl.setContentsMargins(0, 0, 0, 0)
        self.rl.setSpacing(14)
        self.scroller = scroll(self.right)
        right_column = QtWidgets.QVBoxLayout()
        right_column.setSpacing(8)
        right_column.addWidget(self.scroller, 1)
        self.finish_bar = QtWidgets.QFrame()
        self.finish_bar.setFixedHeight(68)
        self.finish_bar.setStyleSheet('QFrame {background: white; border-radius: 12px;}')
        self.finish_layout = QtWidgets.QHBoxLayout(self.finish_bar)
        self.finish_layout.setContentsMargins(12, 12, 12, 12)
        self.finish_bar.hide()
        right_column.addWidget(self.finish_bar)
        lay.addLayout(right_column, 1)

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.probe_all)
        self.timer.start(15000)
        self.refresh_list()

    # ---- device list and status
    def choose_platform(self):
        p = QtWidgets.QFileDialog.getExistingDirectory(self, "Central Monitoring Platform folder (with config.json)", str(devreg.platform_dir()))
        if not p:
            return
        if not (Path(p) / "config.json").exists():
            warn(self, "Not a platform folder", f"There is no config.json in {p}.")
            return
        devreg.set_platform_dir(p)
        self.refresh_list()

    def refresh_list(self):
        self.devices = devreg.load()
        self.plat.setText(f"Platform settings read from {devreg.platform_dir()}")
        keep = self.current["key"] if self.current else None
        self.list.blockSignals(True)
        self.list.clear()
        for d in self.devices:
            it = QtWidgets.QListWidgetItem()
            it.setData(Qt.UserRole, d["key"])
            self.list.addItem(it)
            self.paint_item(it, d)
            if d["key"] == keep:
                it.setSelected(True)
                self.list.setCurrentItem(it)
        self.list.blockSignals(False)
        self.probe_all()
        if not self.current:
            self.show_empty()

    def paint_item(self, it, d):
        st = self.status.get(d["key"])
        connected = self.link is not None and self.current and self.current["key"] == d["key"]
        if connected:
            col, s = BLUE, f"connected · {self.link.kind == 'native' and 'native ROS' or 'ROSBridge'}"
        elif st is None:
            col, s = "#c9ced6", "checking…"
        elif st["online"]:
            col, s = GOOD, f"online · {st['via']}"
        else:
            col, s = MUTED, "offline"
        addr = (d.get("master_uri") or d.get("bridge_url") or "no address").replace("http://", "").replace("ws://", "")
        it.setIcon(dot_icon(col))
        it.setText(f"{d['name']}{'' if d.get('enabled', True) else '  (disabled in the platform)'}\n{addr}\n{s}")

    def probe_all(self):
        if self.closing or any(task.isRunning() for task in self.tasks):
            return
        import ros_link as rl
        devs = list(self.devices)

        def work(progress, stop):
            for d in devs:
                if stop.is_set():
                    break
                progress((d["key"], rl.probe(d, timeout=0.8)))
        t = Task(work, parent=self)
        t.progress.connect(self.on_probe)
        t.finished.connect(lambda: self.tasks.remove(t) if t in self.tasks else None)
        self.tasks.append(t)
        t.start()

    def shutdown(self):
        """Finish workers before their widgets are destroyed; never start a new probe."""
        if self.closing:
            return
        self.closing = True
        self.timer.stop()
        tasks = list(self.tasks)
        capture = getattr(self, 'cap_task', None)
        if capture is not None:
            tasks.append(capture)
        for task in tasks:
            task.stop.set()
        if self.link is not None:
            self.link.close()
            self.link = None
        for task in tasks:
            task.wait()

    def on_probe(self, kv):
        if self.closing:
            return
        key, st = kv
        self.status[key] = st
        for k in range(self.list.count()):
            it = self.list.item(k)
            if it.data(Qt.UserRole) == key:
                device = self.device(key)
                if device is not None:
                    self.paint_item(it, device)

    def device(self, key):
        return next((d for d in self.devices if d["key"] == key), None)

    # ---- right side
    def show_empty(self):
        clear(self.rl)
        c, cl = card("Connect to a device")
        cl.addWidget(label("Select a device, then connect to see its camera, LiDAR and calibration.", "muted", wrap=True))
        cl.addWidget(label("Changes are applied only after you review and confirm them." if self.choose_mode else "Read-only: this app never writes to a device.", "small", wrap=True))
        self.rl.addWidget(c)
        self.rl.addStretch(1)

    def select(self, key):
        d = self.device(key)
        if d is None:
            return
        if self.link is not None and self.current["key"] == key:
            self.show_connected()
            return
        self.sel = d
        clear(self.rl)
        c, cl = card()
        cl.addWidget(label(d["name"], "h1"))
        cl.addWidget(label(d.get("source", ""), "small"))
        rows = [("ROS master", d.get("master_uri") or "–"), ("ROSBridge", d.get("bridge_url") or "–"),
                ("SSH", f"{d.get('ssh_user') or 'rock'}@{d.get('ssh_host') or '–'}:{d.get('ssh_port') or 22}"),
                ("Topics", f"{d.get('image_topic')}  ·  {d.get('cloud_topic')}")]
        grid = QtWidgets.QFormLayout()
        for k, v in rows:
            v_ = label(v, sel=True)
            v_.setStyleSheet(f"font-family: {MONO};")
            grid.addRow(label(k, "muted"), v_)
        cl.addLayout(grid)
        st = self.status.get(key)
        if st is not None and not st["online"]:
            cl.addWidget(note_label("Not reachable right now (no answer from its ROS master or ROSBridge). Check that it is on "
                                    "and that this PC is on its network.", WARN, WARN_SOFT))
        btns = [button("Connect", "primary", lambda: self.connect(d))]
        if d["key"].startswith("local:"):
            btns.append(button("Remove", slot=lambda: self.remove_device(d)))
        cl.addWidget(hbox(*btns, stretch_at=len(btns)))
        if self.link is not None:
            cl.addWidget(label(f"Connected to {self.current['name']} now; connecting here disconnects it first (one device at a time).",
                               "small", wrap=True))
        self.rl.addWidget(c)
        self.rl.addStretch(1)

    def add_device(self):
        d = QtWidgets.QDialog(self)
        d.setWindowTitle("Add a device")
        f = QtWidgets.QFormLayout(d)
        name, host = QtWidgets.QLineEdit(), QtWidgets.QLineEdit()
        mport, bport, user = QtWidgets.QLineEdit("11311"), QtWidgets.QLineEdit("9090"), QtWidgets.QLineEdit("rock")
        for k, w in (("Name", name), ("Address (IP)", host), ("ROS master port (blank: none)", mport),
                     ("ROSBridge port (blank: none)", bport), ("SSH user", user)):
            f.addRow(k, w)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(d.accept)
        bb.rejected.connect(d.reject)
        f.addRow(bb)
        if d.exec_() == QtWidgets.QDialog.Accepted and name.text().strip() and host.text().strip():
            key = devreg.add(name.text().strip(), host.text().strip(), int(mport.text() or 0), int(bport.text() or 0), user.text().strip() or "rock")
            self.refresh_list()
            self.select(key)

    def remove_device(self, d):
        if ask(self, "Remove device", f"Remove {d['name']} from this app's list?", yes="Remove"):
            devreg.remove(d["key"])
            self.current = None if self.current and self.current["key"] == d["key"] else self.current
            self.refresh_list()

    # ---- connecting
    def connect(self, d):
        if self.capture_running or self.pending_capture is not None:
            warn(self, "Captures pending", "Finish and process, or discard the capture set before changing devices.")
            return
        if self.link is not None:
            if not ask(self, "One device at a time", f"Disconnect from {self.current['name']} and connect to {d['name']}?", yes="Switch"):
                return
            self.disconnect(quiet=True)
        import device_capture as dcap
        import ros_link as rl

        def work(progress, stop):
            link = rl.open_link(d)
            topics = link.topics()
            snap = None
            try:
                snap = dcap.snapshot(link, d["image_topic"], d["cloud_topic"], lidar_frames=10)
            except Exception as e:  # noqa: BLE001
                snap = dict(error=str(e))
            return dict(link=link, topics=topics, snap=snap)
        try:
            r = busy(self, f"Connecting to {d['name']} …", work, None, None)
        except RuntimeError as e:
            warn(self, "Could not connect", f"{d['name']}: {e}")
            return
        self.link, self.current, self.topics, self.snap = r["link"], d, r["topics"], r["snap"]
        self.params = self.params_raw = None
        self.params_source = ""
        self.calibration_file_text = None
        self.refresh_list()
        self.show_connected()
        self.read_from_file()

    def disconnect(self, quiet=False):
        if self.capture_running or self.pending_capture is not None:
            warn(self, "Captures pending", "Finish and process, or discard the capture set before disconnecting.")
            return
        if self.link is not None:
            self.link.close()
        self.link = self.params = self.params_raw = self.snap = None
        self.params_source = ""
        prev, self.current = self.current, None
        self.refresh_list()
        if not quiet and prev:
            self.select(prev["key"])

    def set_params(self, raw, source):
        self.params_raw, self.params_source = raw, source
        try:
            image = (self.snap or {}).get("image")
            size = tuple(image.shape[1::-1]) if image is not None else None
            self.params = dm.file_params(raw, image_size=size) if raw else None
        except (ValueError, KeyError, TypeError) as e:
            self.params = None
            warn(self, "Calibration not readable", str(e))

    # ---- connected view
    def show_connected(self):
        self.go = None
        d = self.current
        clear(self.rl)
        c, cl = card()
        pill = label(f"Connected · {self.link.describe()}")
        pill.setStyleSheet(f"color: {BLUE}; background: {BLUE_SOFT}; border-radius: 11px; padding: 4px 14px; font-weight: 700;")
        cl.addWidget(hbox(label(d["name"], "h1"), pill, button("Disconnect", slot=self.disconnect), stretch_at=1))
        self.rl.addWidget(c)

        # live view
        c, cl = card()
        self.lidar_frames = QtWidgets.QSpinBox()
        self.lidar_frames.setRange(1, 1000)
        self.lidar_frames.setValue(10)
        self.lidar_frames.setSuffix(" frames")
        self.live_box = QtWidgets.QVBoxLayout()
        cl.addLayout(self.live_box)
        self.refresh_preview_btn = button("Refresh", slot=self.refresh_snapshot)
        cl.addWidget(hbox(self.refresh_preview_btn, stretch_at=1))
        self.render_snapshot()
        self.rl.addWidget(c)

        # calibration on the device
        c, cl = card("Calibration on the device")
        self.cal_box = QtWidgets.QVBoxLayout()
        cl.addLayout(self.cal_box)
        file_method = "WSL" if device_file.uses_wsl(d) else "SSH"
        self.read_cal_btn = button(f"Read device calibration file ({file_method})…", slot=self.read_from_file)
        cl.addWidget(hbox(self.read_cal_btn, stretch_at=1))
        self.render_params()
        self.rl.addWidget(c)

        # check
        c, cl = card("Check the calibration", "Capture a short sample, then check what needs updating." if self.choose_mode else
                     "Capture a short sample from this device, then check whether its calibration still holds.")
        g = QtWidgets.QGridLayout()
        g.setHorizontalSpacing(16)
        g.setVerticalSpacing(12)
        g.setColumnMinimumWidth(0, 160)
        g.setColumnMinimumWidth(1, 280)
        self.img_topic, self.cloud_topic = QtWidgets.QComboBox(), QtWidgets.QComboBox()
        for combo, ty, cur in ((self.img_topic, "sensor_msgs/Image", d["image_topic"]), (self.cloud_topic, "sensor_msgs/PointCloud2", d["cloud_topic"])):
            combo.setEditable(True)
            opts = sorted(t for t, typ in self.topics.items() if typ == ty) or [cur]
            combo.addItems(opts if cur in opts else [cur] + opts)
            combo.setCurrentText(cur)
            combo.setFixedWidth(280)
        self.n_caps = QtWidgets.QSpinBox()
        self.n_caps.setRange(1, 1000)
        self.n_caps.setValue(5)
        self.n_caps.setMaximumWidth(120)
        self.n_caps.valueChanged.connect(self.update_go)
        self.capture_mode = CaptureModeToggle()
        self.capture_interval = QtWidgets.QSpinBox()
        self.capture_interval.setRange(1, 3600)
        self.capture_interval.setValue(10)
        self.capture_interval.setSuffix(" s")
        self.capture_interval.setFixedWidth(120)
        self.interval_label = label("Wait between captures", "muted")
        self.capture_mode.currentIndexChanged.connect(self.update_go)
        self.update_choice = UpdateChoice()
        for i, (k, w) in enumerate((("Camera topic", self.img_topic), ("LiDAR topic", self.cloud_topic))):
            g.addWidget(label(k, "muted"), i + 1, 0)
            g.addWidget(w, i + 1, 1)
        g.addWidget(label("Capture target", "muted"), 0, 0)
        g.addWidget(self.n_caps, 0, 1, alignment=Qt.AlignLeft)
        lidar_window = hbox(label("LiDAR frames per capture", "muted"), self.lidar_frames)
        lidar_window.setFixedWidth(320)
        g.addWidget(lidar_window, 2, 2, 1, 2)
        lidar_window.setToolTip("Applies to Refresh and each recorded capture. One frame is one PointCloud2 message.")
        mode_label = label("What to check", "muted")
        g.addWidget(mode_label, 3, 0)
        g.addWidget(self.update_choice, 3, 1, 1, 3)
        if not self.choose_mode:
            mode_label.hide()
            self.update_choice.hide()
        g.addWidget(label("Capture mode", "muted"), 4, 0)
        g.addWidget(self.capture_mode, 4, 1, 1, 3)
        g.addWidget(self.interval_label, 5, 0)
        g.addWidget(self.capture_interval, 5, 1)
        g.setColumnStretch(4, 1)
        cl.addLayout(g)
        self.go = button("Capture and check", "primary", self.capture_and_check)
        self.go.setFixedSize(220, 44)
        self.go.setStyleSheet("padding: 0 16px; min-height: 0px; max-height: 42px; font-size: 14px;")
        self.go_hint = label("", "muted", wrap=True)
        self.go_hint.setFixedHeight(44)
        cl.addWidget(hbox(self.go, self.go_hint, stretch_at=2, spacing=16))
        self.cap_box = QtWidgets.QWidget()
        cb = QtWidgets.QVBoxLayout(self.cap_box)
        cb.setContentsMargins(0, 0, 0, 0)
        self.cap_img = ImageView(clickable=False)
        self.cap_img.setFixedSize(124, 132)
        from cloud_view import CloudView
        self.cap_cloud = CloudView(np.empty((0, 4)), show_info=False)
        self.cap_cloud.setMinimumSize(0, 0)
        self.cap_cloud.setFixedSize(180, 132)
        cv = QtWidgets.QVBoxLayout()
        self.cap_text = label("", wrap=True)
        self.cap_bar = QtWidgets.QProgressBar()
        self.cap_stop = button("Stop", slot=self.stop_capture)
        self.cap_finish = button("Finish capturing and process", "primary", self.process_captures)
        self.cap_finish.setFixedHeight(44)
        self.cap_finish.setStyleSheet('padding: 0 16px; min-height: 0px; max-height: 42px;')
        clear(self.finish_layout)
        self.finish_layout.addWidget(self.cap_finish)
        self.cap_finish.hide()
        self.finish_bar.hide()
        self.cap_next = button("Capture next", "primary", self.trigger_next_capture)
        self.cap_next.hide()
        cv.addWidget(self.cap_text)
        cv.addWidget(self.cap_bar)
        cv.addWidget(hbox(self.cap_next, self.cap_stop, stretch_at=2))
        cv.addStretch(1)
        self.active_capture = QtWidgets.QWidget()
        active_row = QtWidgets.QHBoxLayout(self.active_capture)
        active_row.setContentsMargins(0, 0, 0, 0)
        active_row.addWidget(self.cap_img)
        active_row.addWidget(self.cap_cloud)
        active_row.addWidget(label("Collecting the next sample…", "muted"), 1)
        cb.addWidget(self.active_capture)
        cb.addLayout(cv, 1)
        self.cap_box.hide()
        cl.addWidget(self.cap_box)
        self.capture_rows = QtWidgets.QGridLayout()
        self.capture_rows.setSpacing(10)
        self.capture_rows.setColumnStretch(0, 1)
        self.capture_rows.setColumnStretch(1, 1)
        cl.addLayout(self.capture_rows)
        self.rl.addWidget(c)
        self.rl.addStretch(1)
        self.cap_task = None
        self.update_go()

    def update_go(self):
        locked = self.capture_running or self.pending_capture is not None
        ok = self.params is not None and not self.capture_running
        self.go.setEnabled(ok)
        automatic = self.capture_mode.currentData() == "automatic"
        self.capture_interval.setVisible(True)
        self.interval_label.setVisible(True)
        self.go.setText("Start automatic captures" if automatic else "Capture first sample")
        self.go_hint.setText(("First capture starts now; the interval is the wait after each completed capture."
                              if automatic else "Trigger each capture when ready. Finish capturing and process when the full set is ready.")
                             if self.params is not None else "Read the calibration file from this device to continue.")
        if self.pending_capture is not None:
            count = len(self.pending_capture[3])
            self.go.setText(f"Add {self.n_caps.value()} captures")
            self.go_hint.setText(f"{count} samples saved. The next batch adds {self.n_caps.value()} samples with the selected settings.")
        for control in (self.img_topic, self.cloud_topic, self.read_cal_btn, self.update_choice):
            control.setEnabled(not locked)
        for control in (self.n_caps, self.lidar_frames, self.capture_mode, self.refresh_preview_btn):
            control.setEnabled(not self.capture_running)
        self.capture_interval.setEnabled(automatic and not self.capture_running)
        self.interval_label.setEnabled(automatic and not self.capture_running)

    def required_captures(self):
        return self.capture_goal if self.capture_goal is not None else self.n_caps.value()

    def stop_capture(self):
        if self.capture_running and self.cap_task is not None:
            self.cap_task.stop.set()
        elif self.pending_capture is not None:
            _, _, out, _ = self.pending_capture
            shutil.rmtree(out, ignore_errors=True)
            self.pending_capture = None
            self.capture_goal = None
            clear(self.capture_rows)
            self.cap_finish.hide()
            self.finish_bar.hide()
            self.cap_box.hide()
            self.update_go()

    def process_captures(self):
        if self.capture_running or self.pending_capture is None:
            return
        d, name, out, caps = self.pending_capture
        if len(caps) < self.required_captures() or len(list((out / 'captures').glob('*.npz'))) != len(caps):
            warn(self, "Capture set incomplete", "Collect the full requested capture set before processing.")
            return
        try:
            self.prepare_capture_check(d, name, out, caps)
        except Exception as error:
            warn(self, "Could not prepare the capture set", str(error))

    def add_capture_card(self, index, out, summary):
        filename = summary.get('file', '')
        callback = (lambda _checked=False, filename=filename: self.delete_capture(filename)) if filename else None
        card = capture_row(index, out / 'captures' / filename, summary, on_delete=callback)
        slot = self.capture_rows.count()
        self.capture_rows.addWidget(card, slot // 2, slot % 2)

    def delete_capture(self, filename):
        if self.capture_running:
            self.delete_after_stop.add(filename)
            self.cap_task.stop.set()
            return
        if self.pending_capture is None:
            return
        d, name, out, caps = self.pending_capture
        if not any(sample.get('file') == filename for sample in caps):
            return
        root = (out / 'captures').resolve()
        path = (root / filename).resolve()
        if path.parent != root or path.suffix != '.npz':
            warn(self, 'Cannot delete pair', 'The capture file is outside this capture set.')
            return
        try:
            path.unlink(missing_ok=True)
            path.with_suffix('.png').unlink(missing_ok=True)
        except OSError as error:
            warn(self, 'Cannot delete pair', str(error))
            return
        self.captured(d, name, out, [sample for sample in caps if sample.get('file') != filename])

    def lidar_window(self):
        return 1.0, self.lidar_frames.value()

    def trigger_next_capture(self):
        if not self.capture_running and self.pending_capture is not None:
            self.capture_and_check(additional=True)
            return
        self.cap_next.setEnabled(False)
        self.cap_next.hide()
        self.next_capture.set()

    def render_snapshot(self):
        clear(self.live_box)
        self.camera_preview = None
        s = self.snap or {}
        if s.get("error"):
            self.live_box.addWidget(note_label(f"No camera / LiDAR data: {s.get('error', 'nothing received')}. Check the topics below.",
                                               BAD, BAD_SOFT))
        from cloud_view import CloudView
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(16)
        if s.get("image") is not None:
            self.camera_preview = PreviewImage(pixmap=np_to_pixmap(s["image"]), caption="Camera image", max_height=320)
            camera_view = self.camera_preview
        else:
            camera_view = note_label("No camera image received. Check the camera topic.", WARN, WARN_SOFT)
        self.cloud_preview = CloudView(s.get("cloud", np.empty((0, 4))), show_info=False)
        count = s.get('lidar_frames')
        extent = f"{count} {'frame' if count == 1 else 'frames'} · " if count is not None else ""
        camera_rate = s.get('image_hz', 0)
        camera_footer = (f"{camera_rate:.1f} Hz · click image to enlarge" if camera_rate > 0 else 'Click image to enlarge') if s.get('image') is not None else 'Waiting for camera'
        lidar_footer = f"{extent}{self.cloud_preview.total:,} points · drag to rotate · scroll to zoom"
        row.addWidget(sensor_panel('Camera', camera_view, camera_footer, s.get('image') is not None), 1)
        row.addWidget(sensor_panel('LiDAR', self.cloud_preview, lidar_footer, self.cloud_preview.total > 0), 1)
        self.live_box.addLayout(row)
        for message in s.get("errors", {}).values():
            self.live_box.addWidget(note_label(str(message), WARN, WARN_SOFT))

    def refresh_snapshot(self):
        if self.capture_running:
            return
        import device_capture as dcap
        seconds, frames = self.lidar_window()
        stop = threading.Event()
        def work(report):
            return dcap.snapshot(self.link, self.img_topic.currentText(), self.cloud_topic.currentText(),
                                 seconds=seconds, lidar_frames=frames, progress=report, stop=stop)
        try:
            self.snap = busy(self, "Reading selected LiDAR window…", work,
                             with_progress=True, stop=stop)
        except RuntimeError as e:
            if not stop.is_set():
                warn(self, "Could not refresh the sample", str(e))
            return
        self.render_snapshot()

    def render_params(self):
        clear(self.cal_box)
        if self.params is None:
            method = "Read the configured file from WSL." if device_file.uses_wsl(self.current or {}) else "Connect over SSH and select the calibration file on this device."
            self.cal_box.addWidget(note_label("Device calibration file has not been read. " + method +
                                              " Calibration values stay empty until the file is read.", WARN, WARN_SOFT))
        else:
            self.cal_box.addWidget(device_calibration_view(self.params, self.params_source))
        if getattr(self, "go", None) is not None:
            self.update_go()

    def read_from_file(self):
        if self.capture_running or self.pending_capture is not None:
            return
        import device_yaml as dy
        self.params = self.params_raw = None
        self.params_source = ""
        self.calibration_file_text = None
        self.render_params()
        self.render_snapshot()
        if device_file.uses_wsl(self.current):
            try:
                path, text, source = busy(self, "Reading the device calibration file from WSL…",
                                          device_file.read_wsl, self.current)
                raw = dy.read_params(text)
            except (RuntimeError, ValueError, KeyError) as error:
                warn(self, "Could not read the calibration file", str(error))
                return
            self.set_params(raw, f"{source}, read {datetime.now():%Y-%m-%d %H:%M:%S}")
            if self.params is not None:
                self.calibration_file_text = text
            self.render_params()
            self.render_snapshot()
            return
        s = ssh_session(self, self.current)
        if s is None:
            return
        try:
            path, text = read_device_yaml(self, s, self.current, choose_path=True)
            raw = dy.read_params(text)
        except InterruptedError:
            return
        except (RuntimeError, ValueError, KeyError) as e:
            warn(self, "Could not read the calibration", str(e))
            return
        finally:
            s.close()
        self.set_params(raw, f"{s.user}@{s.host}:{s.port} — {path} (SSH), read {datetime.now():%Y-%m-%d %H:%M:%S}")
        if self.params is not None:
            self.calibration_file_text = text
        self.render_params()
        self.render_snapshot()

    # ---- capture and check
    def capture_and_check(self, additional=False):
        if self.capture_running or self.params is None:
            return
        import device_capture as dcap
        from capture_schedule import run_sequence
        d = dict(self.current, image_topic=self.img_topic.currentText().strip(), cloud_topic=self.cloud_topic.currentText().strip())
        devreg.save_settings(d["key"], image_topic=d["image_topic"], cloud_topic=d["cloud_topic"])
        previous = []
        if self.pending_capture is not None:
            d, name, out, previous = self.pending_capture
            previous = list(previous)
            goal = (max(len(previous) + 1, self.required_captures()) if additional
                    else len(previous) + self.n_caps.value())
        else:
            name = core.run_name(d["name"])
            out = core.RESULTS / name
            clear(self.capture_rows)
            goal = self.n_caps.value()
        self.capture_goal = goal
        n, link = goal, self.link
        offset = len(previous)
        collected = list(previous)
        self.pending_capture = None
        secs, frame_count = self.lidar_window()
        automatic = self.capture_mode.currentData() == "automatic"
        interval = float(self.capture_interval.value()) if automatic else 0
        self.next_capture = threading.Event()

        def work(progress, stop):
            def report(value):
                progress(dict(value, k=offset + value['k']))
            def capture(k):
                f, s = dcap.capture_once(link, d["image_topic"], d["cloud_topic"], secs, out / "captures",
                                         progress=lambda x, k=k: report(dict(x, k=k)), stop=stop, lidar_frames=frame_count)
                s = dict(s, file=f.name, capture_mode='automatic' if automatic else 'manual',
                         lidar_target_frames=frame_count, interval_after_capture_s=interval if automatic else None)
                collected.append(s)
                return s
            return previous + run_sequence(capture, n - offset, stop, report,
                                            next_capture=None if automatic else self.next_capture, interval=interval)
        self.capture_running = True
        self.update_go()
        self.cap_next.hide()
        self.cap_finish.hide()
        self.finish_bar.hide()
        self.cap_stop.setText("Stop")
        self.active_capture.show()
        self.cap_cloud.set_cloud(np.empty((0, 4)))
        self.cap_box.show()
        QtCore.QTimer.singleShot(100, lambda: self.scroller.ensureWidgetVisible(self.cap_box, 0, 40))
        self.cap_bar.setRange(0, n)
        self.cap_bar.setValue(offset)
        self.cap_text.setText("Starting …")
        t = Task(work, parent=self)
        self.cap_task = t
        last = {"t": 0.0}

        def on_progress(x):
            import time
            self.cap_bar.setValue(x["k"] + (1 if x.get("done") else 0))
            if x.get("waiting"):
                self.active_capture.hide()
                self.cap_text.setText(f"{x['k']} of {n} captured. Prepare the scene, then capture sample {x['k'] + 1}.")
                self.cap_next.setText(f"Capture sample {x['k'] + 1}")
                self.cap_next.setEnabled(True)
                self.cap_next.show()
                return
            if "countdown" in x:
                self.active_capture.hide()
                self.cap_text.setText(f"{x['k']} of {n} captured. Next capture in {x['countdown']} s…")
                return
            self.active_capture.setVisible(not x.get('done', False))
            if x.get('done'):
                summary = x.get('summary', {})
                self.add_capture_card(x['k'] + 1, out, summary)
            self.cap_text.setText(f"Capture {x['k'] + 1} of {n}: {x['images']} images, {x['clouds']} LiDAR frames"
                                  + ("  ✓" if x.get("done") else " …"))
            if x.get('target_frames'):
                self.cap_text.setText(f"Capture {x['k'] + 1} of {n}: {x['clouds']} / {x['target_frames']} LiDAR frames")
            elif 'elapsed' in x:
                self.cap_text.setText(f"Capture {x['k'] + 1} of {n}: {x['elapsed']:.1f} / {secs:g} s · {x['clouds']} LiDAR frames")
            if x.get('cloud') is not None:
                self.cap_cloud.set_cloud(x['cloud'])
            if x.get("image") is not None and time.time() - last["t"] > 0.4:
                last["t"] = time.time()
                self.cap_img.set_source(pixmap=np_to_pixmap(x["image"]))
        t.progress.connect(on_progress)
        t.done.connect(lambda caps: self.captured(d, name, out, caps))
        def failed(message):
            self.capture_running = False
            self.cap_next.hide()
            if collected:
                self.captured(d, name, out, collected)
            else:
                self.cap_box.hide()
                shutil.rmtree(out, ignore_errors=True)
                self.update_go()
            if not t.stop.is_set():
                warn(self, "Capture failed", message)
        t.failed.connect(failed)
        t.start()

    def captured(self, d, name, out, caps):
        self.capture_running = False
        if self.capture_goal is None:
            self.capture_goal = self.n_caps.value()
        self.active_capture.hide()
        self.cap_next.setText("Capture another" if len(caps) >= self.required_captures() else "Continue capturing")
        self.cap_next.setEnabled(True)
        self.cap_next.show()
        self.pending_capture = (d, name, out, caps)
        clear(self.capture_rows)
        for index, summary in enumerate(caps, 1):
            self.add_capture_card(index, out, summary)
        self.cap_text.setText(f"{len(caps)} of {self.required_captures()} samples captured. Ready when you have finished capturing.")
        self.cap_bar.setValue(len(caps))
        self.cap_finish.setEnabled(len(caps) >= self.required_captures())
        self.cap_finish.show()
        self.finish_bar.setVisible(len(caps) >= self.required_captures())
        self.cap_stop.setText("Discard captures")
        self.update_go()
        deferred = list(self.delete_after_stop)
        self.delete_after_stop.clear()
        for filename in deferred:
            self.delete_capture(filename)

    def prepare_capture_check(self, d, name, out, caps):
        files = sorted((out / "captures").glob("*.npz"))
        xyz = np.concatenate([np.load(f)["xyz_mm"][::25] for f in files]).astype(float) / 1000.0
        theta = dm.lidar_theta_max(xyz, self.params["extrinsic_matrix"])
        cal, rep = dm.to_calibration(self.params, f"{d['name']} ({self.params_source})", theta_max_deg=theta)
        (out / "device_calibration.json").write_text(json.dumps(cal, indent=2))
        if self.calibration_file_text is not None:
            (out / "source_device_pipeline.yaml").write_text(self.calibration_file_text, encoding="utf-8")
        modes = {sample['capture_mode'] for sample in caps if sample.get('capture_mode')}
        frame_targets = {sample['lidar_target_frames'] for sample in caps if sample.get('lidar_target_frames') is not None}
        info = dict(device={k: d.get(k) for k in ("key", "name", "source", "master_uri", "bridge_url", "ssh_host", "ssh_user", "ssh_port",
                                                "calibration_transport", "file_master_uri", "wsl_distro", "yaml_path")},
                    transport=self.link.describe(), params=self.params, params_raw=self.params_raw, params_source=self.params_source,
                    conversion=rep, theta_max_deg=theta, topics=dict(image=d["image_topic"], cloud=d["cloud_topic"]), captures=caps,
                    capture_mode='mixed' if len(modes) > 1 else next(iter(modes), self.capture_mode.currentData()),
                    lidar_window_mode="frames", lidar_seconds=None,
                    lidar_target_frames=next(iter(frame_targets)) if len(frame_targets) == 1 else None,
                    interval_after_capture_s=self.capture_interval.value() if self.capture_mode.currentData() == "automatic" else None,
                    date=datetime.now().isoformat(timespec="seconds"))
        (out / "device.json").write_text(json.dumps(info, indent=2, default=float))
        mode = self.update_choice.currentData()
        _, _, args = core.new_run(out / "device_calibration.json", out / "captures", mode, d["name"], name=name)
        self.pending_capture = None
        self.capture_goal = None
        self.cap_finish.hide()
        self.finish_bar.hide()
        self.cap_box.hide()
        self.update_go()
        self.run_ready.emit(name, args)


def same_params(a, b, tol=1e-6):
    return all(np.allclose(np.ravel(a[k]), np.ravel(b[k]), atol=tol) for k in ("camera_matrix", "dist_coeffs", "extrinsic_matrix"))


# ================================================================== writing to the device
def rotation_change_deg(a, b):
    Ra, Rb = np.array(a["extrinsic_matrix"])[:3, :3], np.array(b["extrinsic_matrix"])[:3, :3]
    return float(np.degrees(Rotation.from_matrix(Rb @ Ra.T).magnitude()))


def param_rows(prev, new):
    P, N = dm.device_params(prev), dm.device_params(new)
    rows = []
    for name, f in (("fx (px)", lambda p: p["camera_matrix"][0][0]), ("fy (px)", lambda p: p["camera_matrix"][1][1]),
                    ("cx (px)", lambda p: p["camera_matrix"][0][2]), ("cy (px)", lambda p: p["camera_matrix"][1][2]),
                    ("k1", lambda p: p["dist_coeffs"][0]), ("k2", lambda p: p["dist_coeffs"][1]), ("p1", lambda p: p["dist_coeffs"][2]),
                    ("p2", lambda p: p["dist_coeffs"][3]), ("k3", lambda p: p["dist_coeffs"][4]),
                    ("t x (mm)", lambda p: p["extrinsic_matrix"][0][3] * 1000), ("t y (mm)", lambda p: p["extrinsic_matrix"][1][3] * 1000),
                    ("t z (mm)", lambda p: p["extrinsic_matrix"][2][3] * 1000)):
        a, b = f(P), f(N)
        nd = 4 if name[0] in "kp" else 2
        changed = abs(b - a) > 10 ** -(nd + 1)
        rows.append([name, f"{a:.{nd}f}", (f"{b:.{nd}f}", BLUE if changed else MUTED, None, changed), core.sgn(b - a, nd) if changed else "—"])
    rows.append(["rotation", "", "", f"{rotation_change_deg(P, N):.3f}° turned"])
    return rows


class WriteDialog(QtWidgets.QDialog):
    """Review -> connect + file diff -> write (confirmed) -> restart (confirmed separately) -> verify."""

    def __init__(self, parent, info):
        super().__init__(parent)
        self.info, self.dev = info, info["device"]
        self.d = devreg.load()
        self.device = next((x for x in self.d if x["key"] == self.dev["device"]["key"]), self.dev["device"])
        s = info["summary"]
        self.setWindowTitle(f"Write the new calibration to {self.device['name']}")
        self.resize(900, 720)
        refined = json.loads((info["out"] / "refined_calibration.json").read_text())
        self.prev = self.dev["params"]
        self.new, self.rep = dm.to_device(refined, previous=self.prev, intrinsics=s["mode"] in ('full', 'intrinsic'), theta_max_deg=self.dev["theta_max_deg"])
        if s['mode'] == 'intrinsic':
            self.new['extrinsic_matrix'] = dm.device_params(self.prev)['extrinsic_matrix']
        files = sorted(Path(info.get("captures_dir") or info["out"] / "captures").glob("*.npz"))
        xyz = np.concatenate([np.load(f)["xyz_mm"][::30] for f in files]).astype(float) / 1000.0 if files else np.zeros((0, 3))
        r = np.linalg.norm(xyz, axis=1)
        sh = dm.shift_px(self.prev, self.new, xyz[(r > 1.5) & (r < 10)]) if len(xyz) else np.array([np.nan])
        self.shift = float(np.median(sh)) if len(sh) else float("nan")

        lay = QtWidgets.QVBoxLayout(self)
        self.pages = QtWidgets.QStackedWidget()
        lay.addWidget(self.pages, 1)
        self.foot = QtWidgets.QHBoxLayout()
        lay.addLayout(self.foot)

        # page 1: review
        p1 = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(p1)
        fg, bg, icon, _ = VERDICT.get(s["verdict"], VERDICT["INCONCLUSIVE"])
        v.addWidget(label(f"<span style='font-size:13pt; font-weight:700; color:{fg}'>{icon} The check said: {s['verdict']}</span>", rich=True))
        if s["verdict"] not in ("UPDATE RECOMMENDED", "LARGE CHANGE"):
            v.addWidget(note_label("The check did not recommend an update. Writing is possible, but not advised.", WARN, WARN_SOFT))
        v.addWidget(label(f"With the new calibration, the device's colouring moves LiDAR points by <b>{core.fmt(self.shift)} px</b> "
                          "(median, 1.5-10 m) compared with now.", wrap=True, rich=True))
        v.addWidget(table(["", "on the device now", "new", "change"], param_rows(self.prev, self.new), numeric=[1, 2, 3]))
        conv = ("The device's camera settings are kept unchanged." if s["mode"] == 'extrinsic' else
                f"The new intrinsics were converted to the device's pinhole model: {self.rep['rms_px']:.3f} px rms, "
                f"{self.rep['max_px']:.3f} px at most, for every LiDAR ray (up to {self.rep['covered_deg']:.0f}° off the camera axis).")
        v.addWidget(label(conv, "muted", wrap=True))
        if self.prev.get("notes"):
            v.addWidget(note_label("On the device now: " + " ".join(self.prev["notes"]) + ". The new file writes camera_matrix as a flat "
                                   "list, so the colorizer reads it.", WARN, WARN_SOFT))
        self.restart = QtWidgets.QCheckBox("Then restart the sensor pipeline (node-pc.service) so the new calibration is used. The device "
                                           "stops sending data for 1-2 minutes. You will be asked again before it restarts.")
        self.restart.setChecked(True)
        v.addWidget(self.restart)
        v.addStretch(1)
        self.pages.addWidget(p1)

        # page 2: the file change
        p2 = QtWidgets.QWidget()
        v2 = QtWidgets.QVBoxLayout(p2)
        self.p2_head = label("", wrap=True, rich=True)
        v2.addWidget(self.p2_head)
        self.p2_warn = note_label("", WARN, WARN_SOFT)
        self.p2_warn.hide()
        v2.addWidget(self.p2_warn)
        self.diff = QtWidgets.QPlainTextEdit()
        self.diff.setReadOnly(True)
        self.diff.setStyleSheet(f"font-family: {MONO}; font-size: 9pt;")
        v2.addWidget(self.diff, 1)
        self.pages.addWidget(p2)

        # page 3: done
        p3 = QtWidgets.QWidget()
        v3 = QtWidgets.QVBoxLayout(p3)
        self.log = label("", wrap=True, rich=True, sel=True)
        v3.addWidget(self.log)
        v3.addStretch(1)
        self.pages.addWidget(p3)
        self.ssh = None
        self.show_page(0)

    def set_buttons(self, *buttons):
        clear(self.foot)
        self.foot.addStretch(1)
        for b in buttons:
            self.foot.addWidget(b)

    def show_page(self, k):
        self.pages.setCurrentIndex(k)
        if k == 0:
            cancel = button("Cancel", slot=self.reject)
            cancel.setDefault(True)
            self.set_buttons(cancel, button("Next: connect to the device", "primary", self.connect_and_diff))
        elif k == 1:
            cancel = button("Cancel", slot=self.reject)
            cancel.setDefault(True)
            self.set_buttons(button("Back", slot=lambda: self.show_page(0)), cancel, button("Write to the device…", "primary", self.write))
        else:
            self.set_buttons(button("Close", "primary", self.accept))

    def connect_and_diff(self):
        import device_yaml as dy
        if self.ssh is None:
            self.ssh = ssh_session(self, self.device)
            if self.ssh is None:
                return
        try:
            self.path, self.old_text = read_device_yaml(self, self.ssh, self.device)
            self.stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.backup_name = f"{Path(self.path).name}.calib_backup_{self.stamp}"
            note = (f"Calibration updated {datetime.now():%Y-%m-%d %H:%M} by {self.info.get('tool', 'Calibration maintenance')} (run {self.info['name']}, "
                    f"{self.info['summary']['verdict'].lower()}); previous file: {self.backup_name}")
            self.new_text = dy.update(self.old_text, self.new, note)
            in_file = dm.device_params(dy.read_params(self.old_text), effective=True)
        except (RuntimeError, ValueError, KeyError) as e:
            warn(self, "Could not prepare the change", str(e))
            return
        self.p2_head.setText(f"<b>{self.device['name']}</b> · <span style='font-family:Consolas'>{self.path}</span><br>"
                             "Only these lines of the file change. The current file is kept on the device as "
                             f"<span style='font-family:Consolas'>{self.backup_name}</span> and a copy is saved with this check.")
        if not same_params(in_file, self.prev):
            self.p2_warn.setText("The calibration in this file is not the one the check started from (the file changed since the "
                                 "pipeline started, or the check used another source). Writing replaces it anyway.")
            self.p2_warn.show()
        self.diff.setPlainText(dy.diff(self.old_text, self.new_text, Path(self.path).name))
        self.show_page(1)

    def write(self):
        name = self.device["name"]
        if not ask(self, "Write to the device?", f"Write the new calibration into {self.path} on {name} now?\n\n"
                   f"The current file is kept as {self.backup_name} on the device and a copy is saved with this check. "
                   "Nothing else on the device changes.", yes="Write"):
            return
        out = self.info["out"]
        steps = []
        try:
            backup = busy(self, "Backing up the current file on the device …", self.ssh.backup, self.path, self.stamp)
            (out / f"device_backup_{self.stamp}_pipeline.yaml").write_text(self.old_text, encoding="utf-8")
            steps.append(f"✓ backup on the device: {backup}")
            busy(self, "Writing the new file …", self.ssh.write, self.path, self.new_text)
            (out / f"device_written_{self.stamp}_pipeline.yaml").write_text(self.new_text, encoding="utf-8")
            steps.append(f"✓ written and verified (checksum): {self.path}")
        except RuntimeError as e:
            warn(self, "Writing failed", f"{e}\n\nThe device's file was not changed, or the backup is in place.")
            return
        record = dict(date=datetime.now().isoformat(timespec="seconds"), device=self.device["name"], key=self.device["key"],
                      path=self.path, backup=backup, previous=self.prev, new=self.new, restarted=False, verified=None)
        restarted = False
        if self.restart.isChecked():
            if ask(self, "Restart the sensor pipeline?", f"Restart node-pc.service on {name} now, so the colorizer loads the new "
                   "calibration? The device stops sending data for 1-2 minutes.", yes="Restart now", no="Not now"):
                try:
                    state = busy(self, "Restarting the sensor pipeline (this waits until it is running) …", self.ssh.restart, self.ssh.password)
                    restarted = True
                    steps.append(f"✓ sensor pipeline restarted ({state})")
                except RuntimeError as e:
                    steps.append(f"✗ restart failed: {e}. The new calibration is used after the next restart / reboot.")
            else:
                steps.append("– pipeline not restarted: the new calibration is used after the next restart / reboot")
        else:
            steps.append("– pipeline not restarted: the new calibration is used after the next restart / reboot")
        record["restarted"] = restarted
        if restarted and self.device.get("master_uri"):
            ok = busy(self, "Checking that the device loaded the new calibration …", verify_loaded, self.device["master_uri"], self.new)
            record["verified"] = ok
            steps.append("✓ the device's parameter server holds the new calibration" if ok else
                         "✗ the device's parameter server does not show the new calibration yet; check the pipeline")
        writes = json.loads((out / "device_writes.json").read_text()) if (out / "device_writes.json").exists() else []
        (out / "device_writes.json").write_text(json.dumps(writes + [record], indent=2, default=float))
        core.mark_history(self.info["name"], f"written to {name} {record['date']}")
        self.ssh.close()
        self.ssh = None
        self.log.setText("<br>".join(steps) + "<br><br>To undo: <b>Restore the previous calibration on the device…</b> in this check's result.")
        self.show_page(2)

    def reject(self):
        if self.ssh is not None:
            self.ssh.close()
        super().reject()


def verify_loaded(master_uri, new, wait_s=150):
    """After a restart: poll the device's parameter server until it holds the new calibration."""
    import time

    import ros_link as rl
    end = time.time() + wait_s
    while time.time() < end:
        try:
            p = rl.NativeLink(master_uri, 2.0).colorizer_params()
            if p and same_params(dm.device_params(p, effective=True), dm.device_params(new)):
                return True
        except Exception:  # noqa: BLE001
            pass
        time.sleep(5)
    return False


class RestoreDialog:
    """Put the backup of the last write back on the device (confirmed), optionally restart."""

    @staticmethod
    def run(parent, info):
        writes = info.get("device_writes") or []
        if not writes:
            return
        w = writes[-1]
        device = next((x for x in devreg.load() if x["key"] == w["key"]), info["device"]["device"])
        s = ssh_session(parent, device)
        if s is None:
            return
        import device_yaml as dy
        try:
            cur = busy(parent, "Reading the current file …", s.read, w["path"])
            old = busy(parent, "Reading the backup …", s.read, w["backup"])
        except RuntimeError as e:
            warn(parent, "Could not read", str(e))
            s.close()
            return
        d = QtWidgets.QDialog(parent)
        d.setWindowTitle(f"Restore the previous calibration on {device['name']}")
        d.resize(860, 560)
        v = QtWidgets.QVBoxLayout(d)
        v.addWidget(label(f"Puts <span style='font-family:Consolas'>{w['backup']}</span> back as "
                          f"<span style='font-family:Consolas'>{w['path']}</span>. Changes:", wrap=True, rich=True))
        t = QtWidgets.QPlainTextEdit(dy.diff(cur, old, Path(w["path"]).name) or "(the file is already the same as the backup)")
        t.setReadOnly(True)
        t.setStyleSheet(f"font-family: {MONO}; font-size: 9pt;")
        v.addWidget(t, 1)
        bb = QtWidgets.QDialogButtonBox()
        bb.addButton("Cancel", QtWidgets.QDialogButtonBox.RejectRole).setDefault(True)
        bb.addButton("Restore…", QtWidgets.QDialogButtonBox.AcceptRole)
        bb.accepted.connect(d.accept)
        bb.rejected.connect(d.reject)
        v.addWidget(bb)
        if d.exec_() != QtWidgets.QDialog.Accepted or not ask(parent, "Restore?", f"Put the previous calibration back on {device['name']} now?", yes="Restore"):
            s.close()
            return
        steps = []
        try:
            busy(parent, "Restoring …", s.write, w["path"], old)
            steps.append(f"✓ {w['path']} restored from {w['backup']}")
            if ask(parent, "Restart the sensor pipeline?", f"Restart node-pc.service on {device['name']} now so the restored calibration "
                   "is used? The device stops sending data for 1-2 minutes.", yes="Restart now", no="Not now"):
                steps.append(f"✓ pipeline restarted ({busy(parent, 'Restarting the sensor pipeline …', s.restart, s.password)})")
            else:
                steps.append("– not restarted: used after the next restart / reboot")
        except RuntimeError as e:
            steps.append(f"✗ {e}")
        finally:
            s.close()
        out = info["out"]
        (out / "device_writes.json").write_text(json.dumps(writes + [dict(date=datetime.now().isoformat(timespec="seconds"), device=device["name"],
                                                                            key=device["key"], path=w["path"], restored_from=w["backup"])], indent=2, default=float))
        core.mark_history(info["name"], f"restored on {device['name']} {datetime.now():%Y-%m-%dT%H:%M:%S}")
        QtWidgets.QMessageBox.information(parent, "Restore", "\n".join(steps))
