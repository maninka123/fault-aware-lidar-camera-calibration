"""Behaviour a product evaluation depends on: stopping a check, closing the app mid-run, two windows, path limits,
unhandled errors, and opening other checks while one is running."""
import json
import logging
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "gui"))

import review_adapter as ra  # noqa: E402
from PyQt5 import QtCore, QtGui, QtWidgets  # noqa: E402

APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
APP.setStyle("Fusion")

CHECKS = sorted(p for p in (ROOT / "research_artifacts").glob("gui_*") if (p / "assessment.json").exists() and p.with_name(p.name + ".gui.json").exists())
SLEEPER = ["-c", "import time; time.sleep(120)"]


def spin(condition, seconds=10):
    end = time.time() + seconds
    while time.time() < end and not condition():
        APP.processEvents()
        time.sleep(0.02)
    return condition()


class Window:
    """A MainWindow whose dialogs cannot block the test, plus a stand-in for a running check."""

    def __init__(self):
        sys.argv = ["research_gui.py"]
        import research_gui as g
        if APP.styleSheet() != g.QSS:  # re-applying re-polishes every live window; that aborted natively on the Linux runner
            APP.setStyleSheet(g.QSS)
        self.g = g
        self.win = g.MainWindow()
        self.dialogs = []
        self.patches = [mock.patch.object(QtWidgets.QMessageBox, "information", lambda *a, **k: self.dialogs.append(a[2] if len(a) > 2 else "")),
                        mock.patch.object(QtWidgets.QMessageBox, "warning", lambda *a, **k: self.dialogs.append(a[2] if len(a) > 2 else ""))]
        for p in self.patches:
            p.start()

    def start_fake_run(self, folder):
        p = QtCore.QProcess(self.win)
        p.finished.connect(self.win.finished_run)
        p.start(sys.executable, SLEEPER)
        assert p.waitForStarted(5000)
        self.win.process, self.win.run_output, self.win.output = p, Path(folder), Path(folder)
        self.win.stopping = False
        self.win.processing.begin(folder, False, 4)
        self.win.stop_btn.show()
        return p

    def close(self):
        if self.win.process is not None and self.win.is_running():
            self.win.process.kill()
            self.win.process.waitForFinished(3000)
        self.win.review.shutdown()
        for p in self.patches:
            p.stop()


class StopAndClose(unittest.TestCase):
    def setUp(self):
        self.w = Window()
        self.addCleanup(self.w.close)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_stop_ends_the_process_and_says_so_plainly(self):
        self.w.start_fake_run(self.tmp.name)
        self.assertTrue(self.w.win.is_running())
        self.w.win.stop_run()
        self.assertTrue(spin(lambda: not self.w.win.is_running()), "kill() must end a console process on Windows")
        spin(lambda: self.w.win.b_title.text() == "Check stopped", 3)
        self.assertEqual(self.w.win.b_title.text(), "Check stopped")
        self.assertIn("unchanged", self.w.win.b_body.text())
        self.assertTrue(self.w.win.processing.model.cancelled)
        self.assertTrue(self.w.win.stop_btn.isHidden())
        self.assertFalse(self.w.win.stopping, "the stop flag must not leak into the next run")

    def test_stop_without_a_run_is_harmless(self):
        self.w.win.stop_run()
        self.assertFalse(self.w.win.stopping)

    def test_a_second_run_is_refused_while_one_is_running(self):
        self.w.start_fake_run(self.tmp.name)
        self.w.win.run()
        self.assertTrue(any("already running" in d for d in self.w.dialogs))

    def test_closing_asks_first_and_can_be_cancelled(self):
        proc = self.w.start_fake_run(self.tmp.name)
        event = QtGui.QCloseEvent()
        with mock.patch.object(QtWidgets.QMessageBox, "question", return_value=QtWidgets.QMessageBox.No):
            self.w.win.closeEvent(event)
        self.assertFalse(event.isAccepted())
        self.assertEqual(proc.state(), QtCore.QProcess.Running)

    def test_closing_confirmed_stops_the_child(self):
        proc = self.w.start_fake_run(self.tmp.name)
        event = QtGui.QCloseEvent()
        with mock.patch.object(QtWidgets.QMessageBox, "question", return_value=QtWidgets.QMessageBox.Yes):
            self.w.win.closeEvent(event)
        self.assertTrue(event.isAccepted())
        self.assertEqual(proc.state(), QtCore.QProcess.NotRunning, "no orphaned python process may be left behind")

    def test_closing_when_idle_needs_no_question(self):
        event = QtGui.QCloseEvent()
        with mock.patch.object(QtWidgets.QMessageBox, "question") as ask:
            self.w.win.closeEvent(event)
        ask.assert_not_called()
        self.assertTrue(event.isAccepted())

    def test_a_crashing_child_is_reported_not_swallowed(self):
        p = QtCore.QProcess(self.w.win)
        p.finished.connect(self.w.win.finished_run)
        self.w.win.process, self.w.win.run_output, self.w.win.output = p, Path(self.tmp.name), Path(self.tmp.name)
        self.w.win.processing.begin(self.tmp.name, False, None)
        p.start(sys.executable, ["-c", "import sys; print('Traceback: something broke'); sys.exit(3)"])
        self.assertTrue(spin(lambda: p.state() == QtCore.QProcess.NotRunning))
        spin(lambda: self.w.win.b_title.text() == "Could not finish", 3)
        self.assertEqual(self.w.win.b_title.text(), "Could not finish")
        self.assertIn("something broke", self.w.win.b_body.text())
        self.assertTrue(self.w.win.processing.model.failure)


@unittest.skipUnless(len(CHECKS) >= 2, "needs two saved checks")
class OtherChecksWhileRunning(unittest.TestCase):
    def setUp(self):
        self.w = Window()
        self.addCleanup(self.w.close)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_opening_another_check_does_not_hijack_the_live_processing_view(self):
        self.w.start_fake_run(self.tmp.name)
        live_model = self.w.win.processing.model
        self.w.win.open_run(str(CHECKS[-1]))
        self.assertIs(self.w.win.processing.model, live_model)
        self.assertEqual(self.w.win.run_output, Path(self.tmp.name), "the running check must stay the running check")
        self.assertNotEqual(self.w.win.output, self.w.win.run_output)

    def test_a_finished_run_loads_its_own_folder_even_if_another_check_is_open(self):
        self.w.start_fake_run(self.tmp.name)
        self.w.win.output = CHECKS[-1]
        (Path(self.tmp.name) / "assessment.json").write_text("{}")
        with mock.patch.object(self.w.win, "load") as load, mock.patch.object(self.w.win, "result_file", return_value=True), \
                mock.patch.object(self.w.win, "refresh_runs"):
            self.w.win.process.finished.disconnect()       # drive the end of the run by hand, once
            self.w.win.process.kill()
            self.w.win.process.waitForFinished(3000)
            self.w.win.finished_run(0)
        load.assert_called_once_with(Path(self.tmp.name))


class PathLimits(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows path limit")
    def test_preflight_flags_only_what_windows_would_refuse(self):
        import research_gui as g
        with tempfile.TemporaryDirectory() as caps:
            (Path(caps) / "capture_20261105_185316_547419_enclosure_off").mkdir()
            self.assertIsNone(g.path_problem(Path("C:/short/gui_20261106_120000"), caps))
            with mock.patch.dict(sys.modules, {"winreg": None}):      # no registry answer: the plain limit applies
                message = g.path_problem(Path("C:/" + "x" * 240 + "/gui_20261106_120000"), caps)
            self.assertIn("Windows stops at 260", message)
            self.assertIn("shorter folder", message)

    @unittest.skipUnless(os.name == "nt", "Windows path limit")
    def test_the_real_repository_location_is_not_rejected(self):
        import research_gui as g
        real = ROOT / "research_artifacts" / "gui_20261106_120000"
        names = "capture_20261105_191640_838463_enclosure_on"
        with tempfile.TemporaryDirectory() as caps:
            (Path(caps) / names).mkdir()
            expected = len(str(real)) + len("\\inputs\\stacked\\data\\") + len(names) + 4
            self.assertEqual(g.path_problem(real, caps) is None, expected <= 259)

    @unittest.skipUnless(os.name == "nt", "Windows path limit")
    def test_review_reports_a_check_that_is_too_deep(self):
        deep = Path("C:/" + "d" * 240 + "/gui_20261106_120000")
        self.assertTrue(ra.too_deep(deep))
        self.assertFalse(ra.too_deep(Path("C:/short/gui_20261106_120000")))
        inputs, reason = ra.inputs_for(dict(mode="check", calibration=__file__, captures=str(ROOT)), deep)
        self.assertIsNone(inputs)
        self.assertIn("too deep", reason)


class TwoWindows(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.dict(os.environ, {"LOCALAPPDATA": self.tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.check = Path(self.tmp.name) / "gui_x"
        self.check.mkdir()

    def test_pid_alive_never_signals_the_process(self):
        self.assertTrue(ra._pid_alive(os.getpid()))
        child = subprocess.Popen([sys.executable] + SLEEPER)
        try:
            self.assertTrue(ra._pid_alive(child.pid))
            self.assertIsNone(child.poll(), "checking a process must not terminate it")
        finally:
            child.kill()
            child.wait()
        self.assertFalse(ra._pid_alive(child.pid))
        self.assertFalse(ra._pid_alive("junk"))
        self.assertFalse(ra._pid_alive(None))

    def test_a_live_lock_from_another_process_blocks_a_second_run(self):
        child = subprocess.Popen([sys.executable] + SLEEPER)
        try:
            ra.work_root(self.check).mkdir(parents=True)
            (ra.work_root(self.check) / "lock.json").write_text(json.dumps(dict(pid=child.pid)))
            with self.assertRaises(RuntimeError):
                ra.prepare(self.check, dict(calibration="a", captures="b"))
            self.assertTrue((ra.work_root(self.check) / "lock.json").exists(), "the other window's files must be left alone")
        finally:
            child.kill()
            child.wait()

    def test_a_stale_lock_is_ignored_and_the_run_takes_over(self):
        child = subprocess.Popen([sys.executable, "-c", "pass"])
        child.wait()
        ra.work_root(self.check).mkdir(parents=True)
        (ra.work_root(self.check) / "lock.json").write_text(json.dumps(dict(pid=child.pid)))
        ra.prepare(self.check, dict(calibration="a", captures="b"))
        self.assertEqual(json.loads((ra.work_root(self.check) / "lock.json").read_text())["pid"], os.getpid())
        ra.release(self.check)
        self.assertFalse(ra.work_root(self.check).exists())


class CrashHandler(unittest.TestCase):
    def test_unhandled_errors_are_logged_and_shown_not_fatal(self):
        import research_gui as g
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(g, "LOG_DIR", Path(tmp)):
            for h in list(logging.getLogger("faultaware").handlers):
                logging.getLogger("faultaware").removeHandler(h)
            g.setup_logging()
            shown = []
            with mock.patch.object(QtWidgets.QMessageBox, "exec_", lambda self: shown.append(self.text()) or 0):
                try:
                    raise ValueError("synthetic failure")
                except ValueError:
                    g.excepthook(*sys.exc_info())
            for h in list(logging.getLogger("faultaware").handlers):
                h.flush()
                h.close()
                logging.getLogger("faultaware").removeHandler(h)
            self.assertTrue(shown and "synthetic failure" in shown[0])
            self.assertIn("calibration files were not changed", shown[0])
            self.assertIn("synthetic failure", (Path(tmp) / "app.log").read_text(encoding="utf-8"))

    def test_the_hook_survives_a_dialog_that_cannot_open(self):
        import research_gui as g
        with mock.patch.object(QtWidgets.QMessageBox, "exec_", side_effect=RuntimeError("no display")):
            try:
                raise KeyError("k")
            except KeyError:
                g.excepthook(*sys.exc_info())     # must not raise


class SmallThings(unittest.TestCase):
    def test_open_path_falls_back_when_startfile_is_missing_or_fails(self):
        sys.path.insert(0, str(ROOT / "Calibration maintenance" / "code"))
        import ui_common
        with mock.patch.object(QtGui.QDesktopServices, "openUrl", return_value=True) as opener:
            with mock.patch.object(ui_common.os, "startfile", side_effect=OSError("no handler"), create=True):
                self.assertTrue(ui_common.open_path("C:/x"))
            opener.assert_called_once()
        saved = getattr(ui_common.os, "startfile", None)
        try:
            if saved is not None:
                del ui_common.os.startfile              # what a non-Windows system looks like
            with mock.patch.object(QtGui.QDesktopServices, "openUrl", return_value=True) as opener:
                self.assertTrue(ui_common.open_path("/tmp"))
                opener.assert_called_once()
        finally:
            if saved is not None:
                ui_common.os.startfile = saved

    def test_short_durations_are_not_reported_as_zero(self):
        import processing_view as pv
        self.assertEqual(pv._secs(0.2), "< 1 s")
        self.assertEqual(pv._secs(14.6), "15 s")

    @unittest.skipUnless(CHECKS, "no saved check")
    def test_history_list_parses_each_assessment_once(self):
        w = Window()
        try:
            w.win.refresh_runs()
            first = len(w.win.history_cache)
            self.assertGreater(first, 0)
            real_loads = json.loads

            def loads(text, *args, **kwargs):
                assert len(text) < 5000, "re-parsed an unchanged assessment"      # assessments are tens of KB; metadata is tiny
                return real_loads(text, *args, **kwargs)
            with mock.patch("json.loads", side_effect=loads):
                w.win.refresh_runs()
            self.assertEqual(len(w.win.history_cache), first)
        finally:
            w.close()

    def test_version_is_defined_and_shown(self):
        import version
        w = Window()
        try:
            texts = " ".join(l.text() for l in w.win.findChildren(QtWidgets.QLabel))
            self.assertIn(version.VERSION, texts)
        finally:
            w.close()


if __name__ == "__main__":
    unittest.main()
