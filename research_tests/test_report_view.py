"""Report tab: built from real saved assessments, tolerant of missing pieces, exports a PDF and a text summary."""
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

import report_view as rv  # noqa: E402
from PyQt5 import QtCore, QtGui, QtWidgets  # noqa: E402

APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
APP.setStyle("Fusion")

CHECKS = sorted(p for p in (ROOT / "research_artifacts").glob("gui_*") if (p / "assessment.json").exists())
STATUS = ("Keep the current calibration", "#248a3d", "#eaf6ed", "No update is supported.")


def titles(view):
    APP.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)        # widgets replaced by a rebuild are gone, not just hidden
    return [l.text() for l in view.findChildren(QtWidgets.QLabel) if l.objectName() == "headline"]


class DegenerateInput(unittest.TestCase):
    def test_empty_and_partial_results_still_make_a_readable_page(self):
        view = rv.ReportView()
        for result in (None, {}, [], "x", {"status": "KEEP_CURRENT"}, {"diagnostics": 5}, {"diagnostics": {"decision": 7, "input": "x"}},
                       {"validation": {"folds": "x"}}, {"parameter_updates": {"wx": "nan", "tx": None}}):
            view.set_result(tempfile.gettempdir(), result, None)
            self.assertIn("Limits of this assessment", titles(view), repr(result))

    def test_nan_and_infinite_numbers_never_break_it(self):
        view = rv.ReportView()
        view.set_result(tempfile.gettempdir(), {"parameter_updates": {"wx": float("nan"), "tx": float("inf")},
                                                "diagnostics": {"candidate_parameter_updates": {"wx": float("-inf")},
                                                                "decision": {"best_relative_gain": float("nan")}}}, STATUS)
        self.assertIn("Proposed and accepted changes", titles(view))

    def test_clear_returns_to_the_placeholder(self):
        view = rv.ReportView()
        view.set_result(tempfile.gettempdir(), {"status": "X"}, STATUS)
        view.clear()
        self.assertIsNone(view.folder)
        self.assertEqual(titles(view), ["Report"])

    def test_an_initial_candidate_has_no_comparison_and_says_it_is_not_validated(self):
        view = rv.ReportView()
        view.set_result(tempfile.gettempdir(), {"status": "INITIAL_CALIBRATION_CANDIDATE", "diagnostics": {"initialization": {"inherited_heuristic_label": "reliable"}}}, STATUS)
        texts = " ".join(l.text() for l in view.findChildren(QtWidgets.QLabel))
        self.assertIn("Not validated", texts)
        self.assertNotIn("How the explanations compared", titles(view))

    def test_the_helpers_reject_junk(self):
        self.assertIsNone(rv.num("x"))
        self.assertIsNone(rv.num(float("nan")))
        self.assertEqual(rv.num("2"), 2.0)
        self.assertEqual(rv.ReportView._time("191640_838463"), "19:16:40")
        self.assertEqual(rv.ReportView._time(None), "–")
        self.assertEqual(rv.ReportView._time("odd"), "odd")


@unittest.skipUnless(CHECKS, "needs a saved check")
class RealChecks(unittest.TestCase):
    def test_every_saved_check_builds_a_complete_report(self):
        view = rv.ReportView()
        for check in CHECKS:
            result = json.loads((check / "assessment.json").read_text(encoding="utf-8"))
            view.set_result(check, result, STATUS, {"wx": "Rotation x"}, {"wx": ("deg", 57.29, 4)})
            have = titles(view)
            self.assertIn("Limits of this assessment", have, check.name)
            if (result.get("validation") or {}).get("folds"):
                self.assertIn("How the explanations compared", have, check.name)

    def test_the_comparison_marks_the_decisions_candidate_and_shows_every_explanation(self):
        check = next((c for c in reversed(CHECKS) if (json.loads((c / "assessment.json").read_text(encoding="utf-8")).get("validation") or {}).get("folds")), None)
        if check is None:
            self.skipTest("no check with folds")
        result = json.loads((check / "assessment.json").read_text(encoding="utf-8"))
        view = rv.ReportView()
        view.set_result(check, result, STATUS)
        tables = [t for t in view.findChildren(QtWidgets.QTableWidget) if t.columnCount() == 4 and t.horizontalHeaderItem(0).text() == "Explanation"]
        self.assertEqual(len(tables), 1)
        names = [tables[0].item(r, 0).text() for r in range(tables[0].rowCount())]
        self.assertEqual(len(names), len(result["validation"]["folds"]))
        candidate = result["diagnostics"]["decision"]["candidate_hypothesis"]
        marked = [n for n in names if "candidate" in n]
        self.assertEqual(len(marked), 0 if candidate == "KEEP" else 1)
        self.assertTrue(any("baseline" in n for n in names))

    def test_a_maintenance_summary_adds_its_card_and_removing_it_takes_it_away(self):
        check = CHECKS[-1]
        result = json.loads((check / "assessment.json").read_text(encoding="utf-8"))
        view = rv.ReportView()
        view.set_result(check, result, STATUS)
        self.assertNotIn("Maintenance comparison", titles(view))
        view.set_review({"verdict": "NO UPDATE NEEDED", "shift_median_px": 2.25, "shift_uncertainty_px": 0.33})
        self.assertIn("Maintenance comparison", titles(view))
        texts = " ".join(l.text() for l in view.findChildren(QtWidgets.QLabel))
        self.assertIn("2.25 px", texts)
        view.set_review(None)
        self.assertNotIn("Maintenance comparison", titles(view))

    def test_the_pdf_is_written_and_cancel_writes_nothing(self):
        check = CHECKS[-1]
        view = rv.ReportView()
        view.set_result(check, json.loads((check / "assessment.json").read_text(encoding="utf-8")), STATUS)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "r.pdf"
            self.assertTrue(view.save_pdf(str(out)))
            self.assertEqual(out.read_bytes()[:5], b"%PDF-")
            with mock.patch.object(QtWidgets.QFileDialog, "getSaveFileName", return_value=("", "")):
                self.assertFalse(view.save_pdf())
            self.assertEqual([p.name for p in Path(tmp).iterdir()], ["r.pdf"])
        self.assertFalse(rv.ReportView().save_pdf("x.pdf"), "with nothing open there is nothing to save")

    def test_an_unwritable_pdf_location_reports_instead_of_crashing(self):
        check = CHECKS[-1]
        view = rv.ReportView()
        view.set_result(check, json.loads((check / "assessment.json").read_text(encoding="utf-8")), STATUS)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(QtWidgets.QMessageBox, "warning") as warned:
            blocker = Path(tmp) / "f"
            blocker.write_text("x")
            self.assertFalse(view.save_pdf(str(blocker / "r.pdf")))

    def test_copy_summary_puts_the_verdict_on_the_clipboard(self):
        view = rv.ReportView()
        view.set_result(CHECKS[-1], {"status": "KEEP_CURRENT", "recommended_action": "KEEP_REFERENCE",
                                     "diagnostics": {"decision": {"best_relative_gain": 0.0039, "reason": "Too small."}}}, STATUS)
        view.copy_summary()
        text = QtWidgets.QApplication.clipboard().text()
        self.assertIn("Keep the current calibration", text)
        self.assertIn("0.39 %", text)
        self.assertIn("Keep your current calibration.", text)

    def test_open_report_md_when_missing_says_so(self):
        view = rv.ReportView()
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(QtWidgets.QMessageBox, "information") as info:
            view.set_result(tmp, {"status": "X"}, STATUS)
            view.open_md()
        info.assert_called_once()

    def test_the_gain_bar_delegate_paints_missing_and_extreme_values(self):
        delegate = rv.GainBarDelegate(0.0)
        table = QtWidgets.QTableWidget(2, 1)
        for r, value in enumerate((None, 1e9)):
            item = QtWidgets.QTableWidgetItem("")
            item.setData(rv.Qt.UserRole, value)
            table.setItem(r, 0, item)
        table.setItemDelegateForColumn(0, delegate)
        table.resize(300, 120)
        self.assertFalse(table.grab().isNull())


@unittest.skipUnless(CHECKS, "needs a saved check")
class WindowIntegration(unittest.TestCase):
    def test_the_report_tab_shows_the_open_check(self):
        sys.argv = ["research_gui.py"]
        import research_gui as g
        APP.setStyleSheet(g.QSS)
        win = g.MainWindow()
        self.addCleanup(win.review.shutdown)
        self.assertIs(win.stack.widget(3), win.report_view)
        win.open_run(str(CHECKS[-1]))
        self.assertEqual(win.report_view.folder, CHECKS[-1])
        self.assertIn("Limits of this assessment", titles(win.report_view))
        win.fail("stopped")
        self.assertIsNone(win.report_view.folder, "a failed or empty state must not keep an old report on screen")


if __name__ == "__main__":
    unittest.main()
