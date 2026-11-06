"""Use the result: accept a calibration into the accepted history, write it to the connected device, restore the
previous one there, or check again with the same inputs.

Writing and restoring reuse the maintenance app's own dialogs (device_ui.WriteDialog / RestoreDialog): a review of the
change, the exact file diff, a backup on the device and a copy in the check, a checksum-verified write, and a separate
confirmation before the sensor pipeline restarts. Nothing here happens without the user pressing a button and
confirming, and a calibration the fault-aware assessment does not support needs an additional, explicit confirmation.
The calibration file a check started from is never changed.
"""
from __future__ import annotations

import json
import math
import re
from datetime import datetime
from pathlib import Path

from PyQt5 import QtCore, QtWidgets
from PyQt5.QtCore import Qt

import review_adapter as ra          # also puts the maintenance code on the path
import result_sections
from calibration_io import MODE_LABELS
from result_visuals import HYP
from ui_widgets import action_flow

USE_DIR = "use"                                   # inside the check; short because of Windows' 260 character limit
SUPPORTED = {"UPDATE_SUPPORTED"}                  # fault-aware statuses that back changing the calibration
# the maintenance dialogs speak in maintenance verdicts
VERDICT_FOR = {"UPDATE_SUPPORTED": "UPDATE RECOMMENDED", "KEEP_CURRENT": "NO UPDATE NEEDED"}
BLUE, GOOD, WARN, BAD, MUTED, LINE = "#007aff", "#248a3d", "#9b6500", "#d70015", "#6e6e73", "#e5e5ea"


# ------------------------------------------------------------------ pure helpers (no Qt)
def mode_for(hypothesis):
    """Which parameters a fault-aware explanation changes, in the maintenance dialogs' words; None for 'keep'."""
    h = str(hypothesis or "")
    if not h or h == "KEEP":
        return None
    exterior, interior = any(c in h for c in "RT"), "I" in h
    return "full" if exterior and interior else "intrinsic" if interior else "extrinsic" if exterior else None


def valid_calibration(cal):
    """A calibration that can be written: a finite 3x3 camera matrix and a finite 4x4 LiDAR-to-camera transform."""
    try:
        K = cal["intrinsics"]["camera_matrix"]
        T = cal["extrinsics"]["transform_lidar_to_camera"]
        flat = [float(x) for row in K for x in row] + [float(x) for row in T for x in row]
        return len(K) == 3 and len(T) == 4 and all(len(r) == 3 for r in K) and all(len(r) == 4 for r in T) and all(math.isfinite(x) for x in flat)
    except (KeyError, TypeError, ValueError):
        return False


def options_for(result, review_info=None):
    """Calibrations this check can offer: the fault-aware candidate, a from-scratch estimate, and the maintenance
    options when the Calibration review has been run. Each is a dict(key, label, calibration, mode, source)."""
    r = result if isinstance(result, dict) else {}
    diag = r.get("diagnostics") if isinstance(r.get("diagnostics"), dict) else {}
    options = []
    if r.get("status") == "INITIAL_CALIBRATION_CANDIDATE" and valid_calibration(r.get("updated_calibration")):
        options.append(dict(key="scratch", label="Calibration estimated from scratch (not validated)", calibration=r["updated_calibration"],
                            mode="full", source="initialization"))
    hypothesis = (diag.get("decision") or {}).get("candidate_hypothesis") if isinstance(diag.get("decision"), dict) else None
    mode = mode_for(hypothesis)
    if mode and valid_calibration(diag.get("candidate_calibration")):
        options.append(dict(key="fault_aware", label=f"Fault-aware candidate: {HYP.get(hypothesis, hypothesis)}",
                            calibration=diag["candidate_calibration"], mode=mode, source="fault-aware"))
    if review_info:
        try:
            found = result_sections.export_calibrations(review_info)
        except Exception:  # noqa: BLE001 - a damaged saved comparison only removes its options
            found = {}
        for key in ("extrinsic", "intrinsic", "full"):
            if valid_calibration(found.get(key)):
                options.append(dict(key="maintenance_" + key, label="Maintenance comparison: " + MODE_LABELS[key],
                                    calibration=found[key], mode=key, source="maintenance"))
    return options


def advised(result):
    """Whether the fault-aware assessment backs changing the calibration."""
    return (result or {}).get("status") in SUPPORTED


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def accepted_records(check):
    out = read_json(Path(check) / USE_DIR / "accepted.json", [])
    return out if isinstance(out, list) else []


def device_writes(check):
    out = read_json(Path(check) / USE_DIR / "device_writes.json", [])
    return out if isinstance(out, list) else []


def accept(check, option, label, root, status=None):
    """Save the calibration as a new dated file in <root>/accepted/ and record it in the check. Never overwrites a file."""
    folder = Path(root) / "accepted"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", str(label or Path(check).name)).strip("_") or "check"
    for n in range(100):
        dst = folder / f"{safe}_{stamp}{'' if n == 0 else f'_{n}'}.json"
        try:
            with open(dst, "x", encoding="utf-8") as handle:        # 'x': fails rather than replacing an existing file
                json.dump(option["calibration"], handle, indent=2)
            break
        except FileExistsError:
            continue
    else:
        raise OSError("no free file name in the accepted folder")
    use = Path(check) / USE_DIR
    use.mkdir(parents=True, exist_ok=True)
    records = accepted_records(check) + [dict(date=datetime.now().isoformat(timespec="seconds"), path=str(dst), option=option["key"],
                                              source=option["source"], fault_aware_status=status)]
    (use / "accepted.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    return dst


def device_dir(meta):
    """The folder of the device capture this check was made from (it holds device.json), or None."""
    p = Path((meta or {}).get("device_source") or "")
    return p if (p / "device.json").is_file() else None


def base_info(check, meta, result):
    """What the maintenance write / restore dialogs need to know about the check and its device."""
    source = device_dir(meta)
    if source is None:
        raise ValueError("This check was not made from a connected device, so there is no device to write to.")
    device = json.loads((source / "device.json").read_text(encoding="utf-8"))
    use = Path(check) / USE_DIR
    use.mkdir(parents=True, exist_ok=True)
    stacked = Path(check) / "inputs" / "stacked" / "data"
    status = (result or {}).get("status")
    return dict(name=Path(check).name, out=use, device=device, device_writes=device_writes(check),
                summary=dict(mode="extrinsic", verdict=VERDICT_FOR.get(status, "INCONCLUSIVE"), device=(device.get("device") or {}).get("name", "")),
                captures_dir=stacked if stacked.is_dir() else source / "captures", tool="Fault-aware calibration")


def package(check, meta, result, option):
    """base_info plus the calibration to write, saved in the check as use/refined_calibration.json."""
    info = base_info(check, meta, result)
    info["summary"]["mode"] = option["mode"]
    (info["out"] / "refined_calibration.json").write_text(json.dumps(option["calibration"], indent=2), encoding="utf-8")
    return info


# ------------------------------------------------------------------ the card
def _label(text="", name=None, rich=False):
    w = QtWidgets.QLabel(text)
    if name:
        w.setObjectName(name)
    w.setWordWrap(True)
    if rich:
        w.setTextFormat(Qt.RichText)
    return w


class UseResultCard(QtWidgets.QFrame):
    check_again = QtCore.pyqtSignal()
    changed = QtCore.pyqtSignal()          # something was accepted, written or restored

    def __init__(self):
        super().__init__()
        self.setObjectName("card")
        self.folder = self.result = self.meta = self.verdict = self.review_info = None
        self.lay = QtWidgets.QVBoxLayout(self)
        self.lay.setContentsMargins(24, 20, 24, 22)
        self.lay.setSpacing(12)
        self.hide()

    def clear(self):
        self.folder = self.result = self.meta = self.verdict = self.review_info = None
        self.hide()

    def set_check(self, folder, result, meta, review_info=None, verdict=None):
        self.folder, self.result, self.meta, self.review_info, self.verdict = Path(folder), result, meta or {}, review_info, verdict
        self.rebuild()

    def set_review(self, review_info):
        """The maintenance comparison finished (or was replaced): its options join the list."""
        if self.folder is not None:
            self.review_info = review_info
            self.rebuild()

    # ---- building
    def rebuild(self):
        while self.lay.count():
            item = self.lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._drop(item.layout())
        self.options = options_for(self.result, self.review_info)
        self.lay.addWidget(_label("Use the result", "headline"))
        ok = advised(self.result)
        title = self.verdict[0] if self.verdict else str((self.result or {}).get("status", "")).replace("_", " ").capitalize()
        tone = GOOD if ok else WARN
        self.lay.addWidget(_label(
            f"<span style='color:{tone}'><b>Fault-aware verdict: {title}.</b></span> " +
            ("The evidence supports this change; review it before using it." if ok else
             "Accepting or writing a calibration is not advised. You will be asked to confirm."), "muted", rich=True))
        if not self.options:
            self.lay.addWidget(_label("No candidate calibration exists for this check, so there is nothing to accept or write. Run the maintenance "
                                      "comparison in the Calibration review tab to get alignment and camera options.", "muted"))
        else:
            row = QtWidgets.QHBoxLayout()
            row.addWidget(_label("Calibration to use", "muted"))
            self.combo = QtWidgets.QComboBox()
            for opt in self.options:
                self.combo.addItem(opt["label"], opt["key"])
            row.addWidget(self.combo, 1)
            self.lay.addLayout(row)
        self.accept_btn = self._button("Accept into accepted history…", self.do_accept)
        self.write_btn = self._button("Write to the device…", self.do_write)
        self.restore_btn = self._button("Restore the previous calibration on the device…", self.do_restore)
        self.again_btn = self._button("Check again with these inputs", self.check_again.emit)
        self.lay.addWidget(action_flow([self.accept_btn, self.write_btn, self.restore_btn, self.again_btn]))   # wraps on narrow windows
        has_device = device_dir(self.meta) is not None
        self.accept_btn.setEnabled(bool(self.options))
        self.write_btn.setEnabled(bool(self.options) and has_device)
        self.restore_btn.setEnabled(has_device and any(w.get("backup") for w in device_writes(self.folder)))
        self.again_btn.setEnabled(bool(self.meta.get("calibration") or self.meta.get("mode") == "scratch") and bool(self.meta.get("captures")))
        self.write_btn.setToolTip("Write the chosen calibration to the sensor device this check was captured from." if has_device else
                                  "Only a check captured from a connected device (Devices) can be written back to it.")
        self.restore_btn.setToolTip("Put back the file the last write replaced (the backup kept on the device).")
        self.status = _label("", "footnote", rich=True)
        self.lay.addWidget(self.status)
        self.lay.addWidget(_label("Accepting saves a new dated file in <i>accepted/</i>. Writing asks to review the exact file change, keeps a backup "
                                  "on the device and in this check, verifies the write, and asks again before the sensor pipeline restarts. The "
                                  "calibration this check started from is never changed.", "footnote", rich=True))
        self._refresh_status()
        self.show()

    def _drop(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    @staticmethod
    def _button(text, slot):
        b = QtWidgets.QPushButton(text)
        b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(lambda _=False: slot())
        return b

    def _refresh_status(self):
        lines = []
        for rec in accepted_records(self.folder)[-1:]:
            lines.append(f"Accepted {rec.get('date', '').replace('T', ' ')}: {rec.get('path', '')}")
        writes = [w for w in device_writes(self.folder) if w.get("backup")]
        if writes:
            w = writes[-1]
            lines.append(f"Last written to {w.get('device', 'the device')} {w.get('date', '').replace('T', ' ')}" +
                         (" (pipeline restarted)" if w.get("restarted") else " (used after the next pipeline restart)"))
        restores = [w for w in device_writes(self.folder) if w.get("restored_from")]
        if restores:
            lines.append(f"Previous calibration restored {restores[-1].get('date', '').replace('T', ' ')}")
        self.status.setText("<br>".join(lines))

    def current(self):
        if not self.options:
            return None
        key = self.combo.currentData()
        return next((o for o in self.options if o["key"] == key), self.options[0])

    # ---- actions (each needs a click and a confirmation)
    def confirm_unsupported(self, what):
        """The fault-aware assessment does not back a change: say so and default to No."""
        if advised(self.result):
            return True
        title = self.verdict[0] if self.verdict else "no supported update"
        box = QtWidgets.QMessageBox.question(self, f"{what} anyway?",
                                             f"The fault-aware verdict is “{title}”: the evidence does not support changing this calibration.\n\n{what} anyway?",
                                             QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No, QtWidgets.QMessageBox.No)
        return box == QtWidgets.QMessageBox.Yes

    def do_accept(self):
        opt = self.current()
        if opt is None or not self.confirm_unsupported("Accept"):
            return
        import review_adapter
        try:
            label = (json.loads((device_dir(self.meta) / "device.json").read_text(encoding="utf-8")).get("device") or {}).get("name") \
                if device_dir(self.meta) else Path(self.meta.get("captures") or "").name
            dst = accept(self.folder, opt, label, review_adapter.ROOT, (self.result or {}).get("status"))
        except (OSError, ValueError, KeyError) as error:
            QtWidgets.QMessageBox.warning(self, "Could not accept", str(error))
            return
        self._refresh_status()
        self.status.setText(self.status.text() + f"<br><b>Accepted:</b> {dst}. The calibration this check started from is unchanged.")
        self.changed.emit()

    def do_write(self):
        opt = self.current()
        if opt is None or not self.confirm_unsupported("Write"):
            return
        try:
            info = package(self.folder, self.meta, self.result, opt)
        except (OSError, ValueError, KeyError) as error:
            QtWidgets.QMessageBox.warning(self, "Cannot prepare the write", str(error))
            return
        import device_ui
        try:
            dialog = device_ui.WriteDialog(self.window(), info)
        except (ValueError, KeyError, RuntimeError, OSError) as error:      # e.g. no pinhole model reproduces the lens
            QtWidgets.QMessageBox.warning(self, "Cannot write this calibration to the device", str(error))
            return
        dialog.exec_()
        self.rebuild()
        self.changed.emit()

    def do_restore(self):
        try:
            info = base_info(self.folder, self.meta, self.result)
        except (OSError, ValueError, KeyError) as error:
            QtWidgets.QMessageBox.warning(self, "Cannot restore", str(error))
            return
        import device_ui
        device_ui.RestoreDialog.run(self.window(), info)
        self.rebuild()
        self.changed.emit()
