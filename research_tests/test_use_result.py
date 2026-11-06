"""Use the result: accept, write to the device, restore, check again. The device is an in-memory fake that behaves like
the SSH target (read / backup / checksum-verified write / restart) and holds a realistic pipeline.yaml; real hardware
is not available to the tests."""
import copy
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "gui"))

import numpy as np  # noqa: E402
import use_result as ur  # noqa: E402
from PyQt5 import QtWidgets  # noqa: E402

APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
APP.setStyle("Fusion")

CHECKS = sorted(p for p in (ROOT / "research_artifacts").glob("gui_*") if (p / "assessment.json").exists() and p.with_name(p.name + ".gui.json").exists())


def result_with_candidate():
    for check in reversed(CHECKS):
        r = json.loads((check / "assessment.json").read_text(encoding="utf-8"))
        if ur.valid_calibration(((r.get("diagnostics") or {}).get("candidate_calibration"))) and ur.mode_for(((r.get("diagnostics") or {}).get("decision") or {}).get("candidate_hypothesis")):
            return check, r
    return None, None


CHECK, RESULT = result_with_candidate()


class PureTests(unittest.TestCase):
    def test_mode_for_names_what_an_explanation_changes(self):
        self.assertEqual({h: ur.mode_for(h) for h in ("R", "T", "RT", "I", "RI", "TI", "RTI")},
                         dict(R="extrinsic", T="extrinsic", RT="extrinsic", I="intrinsic", RI="full", TI="full", RTI="full"))
        for none in ("KEEP", "", None, "X", 5):
            self.assertIsNone(ur.mode_for(none))

    def test_only_complete_finite_calibrations_are_offered(self):
        good = dict(intrinsics=dict(camera_matrix=[[1, 0, 2], [0, 1, 3], [0, 0, 1]]), extrinsics=dict(transform_lidar_to_camera=np.eye(4).tolist()))
        self.assertTrue(ur.valid_calibration(good))
        bad = copy.deepcopy(good)
        bad["extrinsics"]["transform_lidar_to_camera"][0][0] = float("nan")
        for broken in (bad, {}, None, {"intrinsics": {}}, dict(good, extrinsics=dict(transform_lidar_to_camera=[[1, 2, 3]])), "x"):
            self.assertFalse(ur.valid_calibration(broken))

    def test_options_for_degenerate_results(self):
        for r in (None, {}, [], {"diagnostics": 5}, {"diagnostics": {"decision": {"candidate_hypothesis": "R"}}}, {"status": "INITIAL_CALIBRATION_CANDIDATE"}):
            self.assertEqual(ur.options_for(r), [])

    def test_a_from_scratch_estimate_is_offered_but_never_called_supported(self):
        cal = dict(intrinsics=dict(camera_matrix=[[1, 0, 2], [0, 1, 3], [0, 0, 1]]), extrinsics=dict(transform_lidar_to_camera=np.eye(4).tolist()))
        r = dict(status="INITIAL_CALIBRATION_CANDIDATE", updated_calibration=cal)
        options = ur.options_for(r)
        self.assertEqual([o["key"] for o in options], ["scratch"])
        self.assertFalse(ur.advised(r))

    def test_only_an_update_supported_verdict_backs_a_change(self):
        for status, expected in (("UPDATE_SUPPORTED", True), ("KEEP_CURRENT", False), ("INSUFFICIENT_EVIDENCE", False), ("INVALID_OR_UNRELIABLE_DATA", False), (None, False)):
            self.assertEqual(ur.advised({"status": status}), expected)
        self.assertFalse(ur.advised(None))

    def test_accept_never_overwrites_and_records_where_it_went(self):
        with tempfile.TemporaryDirectory() as tmp:
            check, root = Path(tmp) / "check", Path(tmp) / "root"
            check.mkdir()
            option = dict(key="fault_aware", source="fault-aware", calibration=dict(a=1))
            first = ur.accept(check, option, "rig 1/odd name", root, "UPDATE_SUPPORTED")
            second = ur.accept(check, dict(option, calibration=dict(a=2)), "rig 1/odd name", root)
            self.assertNotEqual(first, second)
            self.assertEqual(json.loads(first.read_text()), dict(a=1), "the first accepted file must not be replaced")
            self.assertEqual(json.loads(second.read_text()), dict(a=2))
            self.assertEqual(first.parent, root / "accepted")
            self.assertNotIn("/", first.name)
            self.assertEqual(len(ur.accepted_records(check)), 2)

    def test_damaged_record_files_read_as_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / ur.USE_DIR).mkdir()
            for name, text in (("accepted.json", "{not json"), ("device_writes.json", '{"a": 1}')):
                (Path(tmp) / ur.USE_DIR / name).write_text(text)
            self.assertEqual(ur.accepted_records(tmp), [])
            self.assertEqual(ur.device_writes(tmp), [])

    def test_no_device_means_no_write_package(self):
        with self.assertRaises(ValueError):
            ur.base_info(tempfile.gettempdir(), {}, {})
        self.assertIsNone(ur.device_dir({"device_source": str(tempfile.gettempdir())}))


class FakeSSH:
    """What the maintenance dialogs need of a device: read, backup, checksum-verified write, restart."""
    password = "secret"

    def __init__(self, files):
        self.files, self.backups, self.restarts, self.closed = files, [], 0, 0

    def read(self, path):
        return self.files[path]

    def backup(self, path, stamp):
        name = f"{path}.calib_backup_{stamp}"
        self.files[name] = self.files[path]
        self.backups.append(name)
        return name

    def write(self, path, text):
        self.files[path] = text

    def restart(self, password):
        assert password == self.password
        self.restarts += 1
        return "active"

    def close(self):
        self.closed += 1


@unittest.skipUnless(RESULT, "needs a saved check with a candidate")
class DeviceFlow(unittest.TestCase):
    def setUp(self):
        import device_model as dm
        import device_ui
        import device_yaml as dy
        self.dm, self.ui, self.dy = dm, device_ui, dy
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        tmp = Path(self.tmp.name)
        self.check = tmp / "gui_20261106_000000"
        self.check.mkdir()
        meta = json.loads(CHECK.with_name(CHECK.name + ".gui.json").read_text(encoding="utf-8"))
        reference = json.loads(Path(meta["calibration"]).read_text(encoding="utf-8")) if Path(meta["calibration"]).is_file() else RESULT["updated_calibration"]
        raw, _ = dm.to_device(reference)
        params = dm.device_params(raw, effective=True)
        self.path = "/home/rock/pipeline.yaml"
        note = "original"
        yaml_text = "node_pc:\n  rate: 10\npointcloud_colorizer:\n  image_width: 484\n  image_height: 366\n  other_setting: 7\n"
        yaml_text += "\n".join(dy._fmt(k, np.ravel(raw[k]), 2)[0] if k == "dist_coeffs" else "\n".join(dy._fmt(k, np.ravel(raw[k]), 2))
                               for k in ("camera_matrix", "dist_coeffs", "extrinsic_matrix")) + "\n"
        self.original_yaml = yaml_text
        self.fake = FakeSSH({self.path: yaml_text})
        device = dict(key="dev1", name="Device 1", source="added", ssh_host="127.0.0.1", ssh_user="rock", ssh_port=22, master_uri=None)
        capture = tmp / "device_captures" / "cap1"
        capture.mkdir(parents=True)
        (capture / "device.json").write_text(json.dumps(dict(device=device, params=params, params_raw=raw, params_source="test", theta_max_deg=55.0), default=float))
        self.meta = dict(meta, device_source=str(capture), with_review=False)
        self.result = copy.deepcopy(RESULT)
        self.asked, self.warned = [], []
        self.patches = [mock.patch.object(device_ui, "ssh_session", lambda parent, dev: self.fake),
                        mock.patch.object(device_ui, "read_device_yaml", lambda parent, s, dev: (self.path, self.fake.read(self.path))),
                        mock.patch.object(device_ui, "busy", lambda parent, text, fn, *a: fn(*a)),
                        mock.patch.object(device_ui, "ask", lambda *a, **k: self.asked.append(a[1]) or True),
                        mock.patch.object(device_ui, "warn", lambda parent, title, text: self.warned.append((title, text))),
                        mock.patch.object(QtWidgets.QMessageBox, "information", lambda *a, **k: self.asked.append("info:" + str(a[2]))),
                        mock.patch.object(QtWidgets.QDialog, "exec_", lambda s: QtWidgets.QDialog.Accepted)]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        self.option = ur.options_for(self.result)[0]

    def test_write_changes_only_the_calibration_keys_and_keeps_a_backup(self):
        info = ur.package(self.check, self.meta, self.result, self.option)
        dialog = self.ui.WriteDialog(None, info)
        dialog.connect_and_diff()
        self.assertEqual(dialog.pages.currentIndex(), 1, "the file change must be shown before anything is written")
        self.assertIn("pointcloud_colorizer", self.original_yaml)
        self.assertEqual(self.fake.files[self.path], self.original_yaml, "reviewing must not write")
        dialog.write()
        written = self.fake.files[self.path]
        self.assertNotEqual(written, self.original_yaml)
        self.assertEqual(self.fake.backups and self.fake.files[self.fake.backups[0]], self.original_yaml, "the previous file is kept on the device")
        for line in ("node_pc:", "rate: 10", "other_setting: 7"):
            self.assertIn(line, written, "nothing outside the calibration keys may change")
        self.assertIn("Fault-aware calibration", written, "the note says which tool changed it")
        records = ur.device_writes(self.check)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["backup"], self.fake.backups[0])
        self.assertTrue(list((self.check / ur.USE_DIR).glob("device_backup_*")), "a copy of the old file is saved with the check")
        self.assertTrue(list((self.check / ur.USE_DIR).glob("device_written_*")))
        self.assertEqual(self.fake.restarts, 1)
        self.assertTrue(any("Restart" in q for q in self.asked), "the restart is confirmed separately")

    def test_cancelling_at_the_confirmation_writes_nothing(self):
        info = ur.package(self.check, self.meta, self.result, self.option)
        dialog = self.ui.WriteDialog(None, info)
        dialog.connect_and_diff()
        with mock.patch.object(self.ui, "ask", lambda *a, **k: False):
            dialog.write()
        self.assertEqual(self.fake.files[self.path], self.original_yaml)
        self.assertEqual(self.fake.backups, [])
        self.assertEqual(ur.device_writes(self.check), [])

    def test_a_failing_device_leaves_the_file_and_says_so(self):
        info = ur.package(self.check, self.meta, self.result, self.option)
        dialog = self.ui.WriteDialog(None, info)
        dialog.connect_and_diff()

        def explode(path, text):
            raise RuntimeError("checksum mismatch")
        self.fake.write = explode
        dialog.write()
        self.assertEqual(self.fake.files[self.path], self.original_yaml)
        self.assertTrue(any("Writing failed" in t for t, _ in self.warned))
        self.assertEqual(ur.device_writes(self.check), [], "a failed write must not be recorded as done")

    def test_restore_puts_the_backup_back(self):
        info = ur.package(self.check, self.meta, self.result, self.option)
        dialog = self.ui.WriteDialog(None, info)
        dialog.connect_and_diff()
        dialog.write()
        self.assertNotEqual(self.fake.files[self.path], self.original_yaml)
        self.ui.RestoreDialog.run(None, ur.base_info(self.check, self.meta, self.result))
        self.assertEqual(self.fake.files[self.path], self.original_yaml)
        records = ur.device_writes(self.check)
        self.assertEqual(records[-1]["restored_from"], self.fake.backups[0])

    def test_restore_with_nothing_written_does_nothing(self):
        self.ui.RestoreDialog.run(None, ur.base_info(self.check, self.meta, self.result))
        self.assertEqual(self.fake.files[self.path], self.original_yaml)

    def test_the_card_gates_each_action_correctly(self):
        card = ur.UseResultCard()
        card.set_check(self.check, self.result, self.meta, None, ("Keep the current calibration", "#000", "#fff", "x"))
        self.assertTrue(card.accept_btn.isEnabled() and card.write_btn.isEnabled())
        self.assertFalse(card.restore_btn.isEnabled(), "nothing has been written yet")
        no_device = dict(self.meta, device_source=None)
        card.set_check(self.check, self.result, no_device, None, None)
        self.assertFalse(card.write_btn.isEnabled(), "a check made from files has no device to write to")
        info = ur.package(self.check, self.meta, self.result, self.option)
        dialog = self.ui.WriteDialog(None, info)
        dialog.connect_and_diff()
        dialog.write()
        card.set_check(self.check, self.result, self.meta, None, None)
        self.assertTrue(card.restore_btn.isEnabled())

    def test_an_unsupported_verdict_needs_an_explicit_yes_and_defaults_to_no(self):
        card = ur.UseResultCard()
        unsupported = dict(self.result, status="KEEP_CURRENT")
        card.set_check(self.check, unsupported, self.meta, None, ("Keep the current calibration", "#000", "#fff", "x"))
        with mock.patch.object(QtWidgets.QMessageBox, "question", return_value=QtWidgets.QMessageBox.No) as ask:
            card.do_accept()
            card.do_write()
        self.assertEqual(ask.call_count, 2)
        self.assertEqual(ur.accepted_records(self.check), [])
        self.assertEqual(self.fake.files[self.path], self.original_yaml)
        self.assertEqual(ask.call_args[0][4], QtWidgets.QMessageBox.No, "the default button must be No")

    def test_an_update_supported_verdict_does_not_nag_for_accept(self):
        card = ur.UseResultCard()
        supported = dict(self.result, status="UPDATE_SUPPORTED")
        card.set_check(self.check, supported, self.meta, None, None)
        with mock.patch.object(QtWidgets.QMessageBox, "question") as ask, mock.patch.object(ur, "accept", return_value=Path("x.json")) as accept:
            card.do_accept()
        ask.assert_not_called()
        accept.assert_called_once()

    def test_accepting_does_not_touch_the_calibration_the_check_started_from(self):
        import review_adapter
        cal = Path(self.meta["calibration"])
        before = hashlib.sha1(cal.read_bytes()).hexdigest() if cal.is_file() else None
        card = ur.UseResultCard()
        card.set_check(self.check, dict(self.result, status="UPDATE_SUPPORTED"), self.meta, None, None)
        root = Path(self.tmp.name) / "repo"
        with mock.patch.object(review_adapter, "ROOT", root):
            card.do_accept()
        saved = list((root / "accepted").glob("*.json"))
        self.assertEqual(len(saved), 1)
        self.assertEqual(json.loads(saved[0].read_text()), self.option["calibration"])
        self.assertIn("Device_1", saved[0].name, "the file is named after the device the check came from")
        if before is not None:
            self.assertEqual(before, hashlib.sha1(cal.read_bytes()).hexdigest())
        self.assertEqual(len(ur.accepted_records(self.check)), 1)


@unittest.skipUnless(CHECKS, "no saved check")
class MainWindowIntegration(unittest.TestCase):
    def setUp(self):
        sys.argv = ["research_gui.py"]
        import research_gui as g
        APP.setStyleSheet(g.QSS)
        self.g = g
        self.win = g.MainWindow()
        self.addCleanup(self.win.review.shutdown)

    def test_the_result_tab_has_the_card_and_check_again_restores_the_setup(self):
        self.win.open_run(str(CHECKS[-1]))
        self.assertFalse(self.win.use_card.isHidden())
        self.assertEqual(self.win.use_card.folder, CHECKS[-1])
        meta = json.loads(CHECKS[-1].with_name(CHECKS[-1].name + ".gui.json").read_text(encoding="utf-8"))
        self.win.check_again()
        self.assertEqual(self.win.pages.currentIndex(), 0, "back on the New check page")
        if meta.get("captures") and Path(meta["captures"]).is_dir():
            self.assertEqual(self.win.cap.path, meta["captures"])

    def test_accepted_and_written_marks_show_in_the_check_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "research_artifacts" / "gui_20990101_000000"
            folder.mkdir(parents=True)
            (folder / "assessment.json").write_text(json.dumps(dict(status="KEEP_CURRENT")))
            folder.with_name(folder.name + ".gui.json").write_text(json.dumps(dict(captures="x")))
            (folder / ur.USE_DIR).mkdir()
            with mock.patch.object(self.g, "ROOT", Path(tmp)):
                self.win.refresh_runs()
                plain = self.win.runs.item(0).text()
                (folder / ur.USE_DIR / "accepted.json").write_text(json.dumps([dict(date="2099-01-01T00:00:00", path="p")]))
                (folder / ur.USE_DIR / "device_writes.json").write_text(json.dumps([dict(backup="b", device="Device 1", date="2099-01-01T00:00:00")]))
                self.win.refresh_runs()
                marked = self.win.runs.item(0).text()
        self.assertNotIn("accepted", plain)
        self.assertIn("accepted", marked)
        self.assertIn("written to device", marked)

    def test_device_capture_is_remembered_by_the_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.win.pending_device = Path(tmp)
            self.win.run_btn.setEnabled(False)
            self.assertEqual(str(self.win.pending_device), tmp)


if __name__ == "__main__":
    unittest.main()
