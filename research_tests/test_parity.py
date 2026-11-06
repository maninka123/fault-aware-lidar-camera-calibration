"""Feature parity: every user-facing capability of the calibration maintenance app has a home in the fault-aware app.

The table below is the checklist (also written out in docs/FEATURES.md). Each entry is looked up in the real windows,
so removing or renaming a control makes this fail instead of silently losing a feature."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "gui"))

from PyQt5 import QtWidgets  # noqa: E402

APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
APP.setStyle("Fusion")

REAL = ROOT.parent.parent / "Calibration maintenance" / "results" / "rig_20261106_151654"


def texts(root):
    return {b.text().replace("&", "") for b in root.findChildren(QtWidgets.QPushButton)}


class Parity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.argv = ["research_gui.py"]
        import research_gui as g
        APP.setStyleSheet(g.QSS)
        cls.g = g
        cls.win = g.MainWindow()
        cls.win.show_devices()
        cls.devices = cls.win.devices

    @classmethod
    def tearDownClass(cls):
        cls.win.devices.shutdown()
        cls.win.review.shutdown()

    # ---- New check (maintenance: Check files)
    def test_setting_up_a_check(self):
        have = texts(self.win.pages.widget(0))
        for button in ("Open file…", "Enter values…", "Choose folder…", "View pairs", "Check calibration"):
            self.assertIn(button, have)
        links = {b.text() for b in self.win.findChildren(QtWidgets.QPushButton)}
        for link in ("Use example values", "Capture format"):
            self.assertIn(link, links)
        self.assertGreaterEqual(self.win.strategy.count(), 7, "all seven methods stay available")
        self.assertGreaterEqual(self.win.mode_combo.findData("scratch"), 0, "calibrate from scratch")
        self.assertTrue(hasattr(self.win, "pair_units") and hasattr(self.win, "units_confirm"), "PCD units and their confirmation")
        for method in ("load_cal", "enter_cal", "use_example", "load_data", "validate_paired", "show_capture_format", "show_pair_report"):
            self.assertTrue(hasattr(self.win, method), method)

    # ---- Devices
    def test_the_devices_page_has_all_its_functions(self):
        have = texts(self.devices)
        for button in ("Refresh", "Add device…"):
            self.assertIn(button, have)
        for method in ("choose_platform", "refresh_list", "select", "read_from_file", "use_file", "capture_and_check", "shutdown"):
            self.assertTrue(hasattr(self.devices, method), method)
        self.assertFalse(self.devices.choose_mode, "the maintenance 'what to check' choice is replaced by the fault-aware check")

    # ---- Running and following a check
    def test_following_a_check(self):
        have = texts(self.win.processing) | texts(self.win)
        for button in ("Stop check", "Show log"):
            self.assertIn(button, have)
        for name in ("Processing", "Result", "Calibration review", "Report"):
            self.assertIn(name, [b.text() for b in self.win.pager.buttons])

    # ---- Using a result
    def test_using_a_result(self):
        card = self.win.use_card
        card.set_check(tempfile.gettempdir(), {"status": "KEEP_CURRENT"}, {"mode": "check", "calibration": __file__, "captures": tempfile.gettempdir()})
        have = texts(card)
        for button in ("Accept into accepted history…", "Write to the device…", "Restore the previous calibration on the device…",
                       "Check again with these inputs"):
            self.assertIn(button, have)
        self.assertIn("View calibration after this check…", texts(self.win))

    @unittest.skipUnless(REAL.exists(), "needs the real maintenance output")
    def test_the_maintenance_diagnostics_and_exports(self):
        import calibration_review
        import review_adapter as ra
        shutil_ignore = __import__("shutil").ignore_patterns("stacked", "decode")
        with tempfile.TemporaryDirectory() as tmp:
            check = Path(tmp) / "gui_x"
            (check / ra.REVIEW_DIR).mkdir(parents=True)
            __import__("shutil").copytree(REAL, check / ra.REVIEW_DIR / ra.RUN_NAME, ignore=shutil_ignore)
            review = calibration_review.CalibrationReview()
            review.set_check(check, {"status": "KEEP_CURRENT"}, {"mode": "check"}, None)
            have = texts(review)
            for button in ("Save calibration TXT…", "Save refined JSON…", "Open results folder", "Show report", "Run the comparison again…"):
                self.assertIn(button, have)
            for section in ("Compare", "Quality", "Parameters", "Images", "Evidence", "Matrices", "Export"):
                self.assertIn(section, review.sections)
            for view in ("candidate", "current", "difference"):
                review.matrices.set_view(view)

    def test_the_pair_report_is_shared_with_the_maintenance_app(self):
        from ui_widgets import pair_report_dialog
        self.assertIsNone(pair_report_dialog(None, None))
        self.assertIsNone(pair_report_dialog(None, {"path": "x"}))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = dict(path=str(root), paired_validation=dict(
                units="m", warnings=["note"], reports=[dict(image=str(root / "a.png"), cloud=str(root / "a.pcd"), points=1234,
                                                            median_range_m=4.5, range_5_95_m=[1.0, 9.0], units_review=False)]))
            dialog = pair_report_dialog(None, data)
            self.assertIsNotNone(dialog)
            self.assertEqual(dialog.windowTitle(), "Pair checks")
            self.assertTrue(any("1,234" in (t.item(0, 2).text() if t.item(0, 2) else "") for t in dialog.findChildren(QtWidgets.QTableWidget)))
        self.win.data = None
        self.win.show_pair_report()          # nothing to show: must not fail

    def test_the_example_calibration_exists(self):
        self.assertTrue((ROOT / "examples" / "calibration.example.json").is_file())

    def test_the_original_maintenance_app_is_still_launchable_from_here(self):
        self.assertTrue((ROOT / "start_app.bat").is_file())
        self.assertTrue((ROOT / "Calibration maintenance" / "code" / "app.py").is_file())
        text = (ROOT / "Calibration maintenance" / "code" / "app.py").read_text(encoding="utf-8")
        self.assertIn("'gui' / 'research_gui.py'", text, "its button that opens this app must point at the moved file")


if __name__ == "__main__":
    unittest.main()
