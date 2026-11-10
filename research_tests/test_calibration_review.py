"""Calibration review tab: loading saved maintenance results, empty / missing / historical states, tab navigation and
safe exports. UI tests use the real maintenance output when it is on this machine and are skipped otherwise;
no metric is fabricated."""
import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "gui"))

import review_adapter as ra  # noqa: E402
from PyQt5 import QtWidgets  # noqa: E402

APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
APP.setStyle("Fusion")

REAL = ROOT.parent.parent / "Calibration maintenance" / "results" / "rig_20261106_151654"
CHECKS = sorted(p for p in (ROOT / "research_artifacts").glob("gui_*") if (p / "assessment.json").exists() and p.with_name(p.name + ".gui.json").exists())


def digest(folder):
    """Name, size and content hash of every file under folder."""
    out = {}
    for p in sorted(Path(folder).rglob("*")):
        if p.is_file():
            out[str(p.relative_to(folder))] = hashlib.sha1(p.read_bytes()).hexdigest()
    return out


def make_check(tmp, with_review=False, drop=()):
    """A scratch copy of a saved check (assessment + metadata), optionally with the real maintenance output inside."""
    src = CHECKS[-1]
    check = Path(tmp) / "gui_test"
    check.mkdir()
    shutil.copy(src / "assessment.json", check / "assessment.json")
    meta = json.loads(src.with_name(src.name + ".gui.json").read_text(encoding="utf-8"))
    check.with_name("gui_test.gui.json").write_text(json.dumps(meta), encoding="utf-8")
    if with_review:
        dst = check / ra.REVIEW_DIR / ra.RUN_NAME
        shutil.copytree(REAL, dst, ignore=shutil.ignore_patterns("stacked", "decode", *drop))
    return check, meta, json.loads((check / "assessment.json").read_text(encoding="utf-8"))


class AdapterTests(unittest.TestCase):
    def test_inputs_need_an_existing_calibration_and_captures(self):
        with tempfile.TemporaryDirectory() as tmp:
            cal, cap = Path(tmp) / "c.json", Path(tmp) / "caps"
            cal.write_text("{}")
            cap.mkdir()
            ok, why = ra.inputs_for(dict(calibration=str(cal), captures=str(cap), mode="check"))
            self.assertIsNone(why)
            self.assertEqual(ok["cloud_units"], "m")
            self.assertIn("scratch", ra.inputs_for(dict(mode="scratch"))[1])
            self.assertIn("did not record", ra.inputs_for({})[1])
            self.assertIn("no longer there", ra.inputs_for(dict(calibration=str(cal) + "x", captures=str(cap)))[1])
            self.assertIn("no longer there", ra.inputs_for(dict(calibration=str(cal), captures=str(cap) + "x"))[1])

    def test_command_is_the_unchanged_backend_with_its_own_output_folder(self):
        args, env, cwd = ra.command("C:/x/check", dict(calibration="a.json", captures="d", cloud_units="m"))
        self.assertTrue(args[3].endswith("maintain.py"))
        self.assertIn("compare", args)
        self.assertEqual(env["MAINTENANCE_RESULTS_DIR"], str(ra.work_root("C:/x/check")))

    def test_state_follows_the_saved_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(ra.state(tmp), "none")
            run = ra.run_folder(tmp)
            run.mkdir(parents=True)
            (run / "progress.json").write_text(json.dumps(dict(finished=False, stages=[])))
            self.assertEqual(ra.state(tmp), "partial")
            (run / "progress.json").write_text(json.dumps(dict(finished=True, stages=[])))
            self.assertEqual(ra.state(tmp), "partial")          # finished flag alone is not a result
            (run / "summary.json").write_text("{}")
            self.assertEqual(ra.state(tmp), "ready")

    def test_agreement_keeps_the_two_verdicts_apart(self):
        self.assertEqual(ra.agreement("KEEP_CURRENT", "NO UPDATE NEEDED")[0], "agree")
        self.assertEqual(ra.agreement("INSUFFICIENT_EVIDENCE", "LARGE CHANGE")[0], "differ")
        self.assertEqual(ra.agreement("UPDATE_SUPPORTED", "NO UPDATE NEEDED")[0], "differ")

    def test_export_never_targets_the_input_calibration(self):
        with tempfile.TemporaryDirectory() as tmp:
            cal = Path(tmp) / "c.json"
            cal.write_text("{}")
            with self.assertRaises(ValueError):
                ra.check_export_path(cal, [str(cal)])
            self.assertEqual(ra.check_export_path(Path(tmp) / "new.txt", [str(cal)]), (Path(tmp) / "new.txt").resolve())


class ScratchFolderTests(unittest.TestCase):
    """The comparison runs in a short scratch folder (Windows rejects paths over 260 characters) and only a
    finished run is published into the check."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch.dict(os.environ, {"LOCALAPPDATA": self.tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)
        self.check = Path(self.tmp.name) / "a_check_with_a_long_enough_name_to_matter"
        self.check.mkdir()

    def fake_run(self, finished=True):
        run = ra.work_run(self.check)
        (run / "images").mkdir(parents=True)
        (run / "stacked" / "data").mkdir(parents=True)
        (run / "decode").mkdir()
        (run / "stacked" / "data" / "capture_20261105_185316_547419_enclosure_off.npz").write_bytes(b"cache")
        (run / "images" / "185316_547419.png").write_bytes(b"png")
        (run / "progress.json").write_text(json.dumps(dict(finished=finished, stages=[])))
        if finished:
            (run / "summary.json").write_text("{}")
        (ra.work_root(self.check) / "history.csv").write_text("run,x\n1,2\n")
        return run

    def test_scratch_folder_is_short_and_per_check(self):
        run = ra.work_run(self.check)
        longest = len(str(run / "stacked" / "data" / "capture_20261105_185316_547419_enclosure_off.npz"))
        self.assertLess(longest, 260 - 80, "caches must fit well inside the Windows limit wherever the repository is")
        self.assertNotEqual(ra.work_root(self.check), ra.work_root(self.check / "other"))

    def test_command_runs_in_the_scratch_folder_not_the_check(self):
        _args, env, _cwd = ra.command(self.check, dict(calibration="a", captures="b", cloud_units="m"))
        self.assertEqual(env["MAINTENANCE_RESULTS_DIR"], str(ra.work_root(self.check)))

    def test_publish_copies_results_without_the_caches_and_cleans_up(self):
        self.fake_run()
        ok, message = ra.publish(self.check)
        self.assertTrue(ok, message)
        self.assertEqual(ra.state(self.check), "ready")
        self.assertTrue((ra.run_folder(self.check) / "images" / "185316_547419.png").exists())
        self.assertFalse((ra.run_folder(self.check) / "stacked").exists())
        self.assertFalse((ra.run_folder(self.check) / "decode").exists())
        self.assertTrue((ra.review_root(self.check) / "history.csv").exists())
        self.assertFalse(ra.work_root(self.check).exists())

    def test_a_failed_rerun_never_destroys_the_saved_comparison(self):
        self.fake_run()
        ra.publish(self.check)
        saved = digest(ra.run_folder(self.check))
        ra.prepare(self.check, dict(calibration="a", captures="b"))
        self.fake_run(finished=False)
        ok, _message = ra.publish(self.check)
        self.assertFalse(ok)
        self.assertEqual(saved, digest(ra.run_folder(self.check)))
        self.assertEqual(ra.state(self.check), "ready")

    def test_unfinished_run_is_reported_as_partial(self):
        self.fake_run(finished=False)
        self.assertEqual(ra.state(self.check), "partial")


@unittest.skipUnless(CHECKS, "no saved fault-aware check on this machine")
class AutoRunOnNewChecks(unittest.TestCase):
    def setUp(self):
        sys.argv = ["research_gui.py"]
        import research_gui as g
        if APP.styleSheet() != g.QSS:  # re-applying re-polishes every live window; that aborted natively on the Linux runner
            APP.setStyleSheet(g.QSS)
        self.win = g.MainWindow()
        self.addCleanup(self.win.review.shutdown)

    def finish(self, with_review):
        from PyQt5 import QtCore
        with tempfile.TemporaryDirectory() as tmp:
            check, meta, _result = make_check(tmp)
            meta["with_review"] = with_review
            check.with_name(check.name + ".gui.json").write_text(json.dumps(meta), encoding="utf-8")
            self.win.output, self.win.process = check, QtCore.QProcess()
            with mock.patch.object(self.win.review, "start", return_value=True) as start, mock.patch.object(self.win, "refresh_runs"):
                self.win.finished_run(0)
            return start

    def test_option_is_on_by_default_and_off_for_calibrating_from_scratch(self):
        self.assertTrue(self.win.auto_review.isChecked())
        self.win.mode_combo.setCurrentIndex(self.win.mode_combo.findData("scratch"))
        self.assertFalse(self.win.auto_review.isEnabled())
        self.win.mode_combo.setCurrentIndex(self.win.mode_combo.findData("check"))
        self.assertTrue(self.win.auto_review.isEnabled())

    def test_a_new_check_with_the_option_starts_the_review_after_its_result(self):
        self.finish(True).assert_called_once_with(auto=True)

    def test_a_new_check_without_the_option_does_not(self):
        self.finish(False).assert_not_called()


@unittest.skipUnless(CHECKS, "no saved fault-aware check on this machine")
class HistoricalChecks(unittest.TestCase):
    def setUp(self):
        import calibration_review
        self.review = calibration_review.CalibrationReview()

    def test_every_saved_check_opens_without_a_comparison(self):
        for check in CHECKS:
            meta = json.loads(check.with_name(check.name + ".gui.json").read_text(encoding="utf-8"))
            result = json.loads((check / "assessment.json").read_text(encoding="utf-8"))
            before = digest(check) if (check / "assessment.json").stat().st_size < 3e6 else None
            self.review.set_check(check, result, meta, ("Verdict", "#000", "#fff", "text"))
            self.assertIsNone(self.review.proc, "opening a check must not start a calculation")
            self.assertEqual(ra.state(check), "none" if not (check / ra.REVIEW_DIR).exists() else ra.state(check))
            if before is not None:
                self.assertEqual(before, digest(check), "opening a check must not write anything into it")

    def test_missing_fields_do_not_break_the_tab(self):
        for result, meta in (({}, {}), (None, None), ({"status": "KEEP_CURRENT"}, {"mode": "scratch"})):
            self.review.set_check(CHECKS[-1], result, meta, None)
            self.assertIsNone(self.review.proc)

    def test_clear_returns_to_the_placeholder(self):
        self.review.clear()
        self.assertIsNone(self.review.folder)


@unittest.skipUnless(CHECKS and REAL.exists(), "needs a saved check and the real maintenance output")
class ReviewWithRealOutput(unittest.TestCase):
    def setUp(self):
        import calibration_review
        self.tmp = tempfile.TemporaryDirectory()
        self.check, self.meta, self.result = make_check(self.tmp.name, with_review=True)
        self.review = calibration_review.CalibrationReview()
        self.review.set_check(self.check, self.result, self.meta, ("Not enough evidence", "#9b6500", "#fff6e5", "x"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_all_sections_are_present(self):
        for name in ("Compare", "Quality", "Parameters", "Images", "Evidence", "Matrices", "Export"):
            self.assertIn(name, self.review.sections)

    def test_option_cards_show_the_saved_scores(self):
        info = ra.load(self.check)
        scores = info["summary"]["strategy_comparison"]["scores"]
        self.assertEqual(set(self.review.options.tiles), {"existing", "extrinsic", "intrinsic", "full"})
        self.assertAlmostEqual(scores["existing"], 0.088, delta=0.01)

    def test_choosing_an_option_updates_matrices_and_export(self):
        self.review.options.select_mode("extrinsic")
        self.assertEqual(self.review.selected_mode, "extrinsic")
        self.assertEqual(self.review.matrices.mode, "extrinsic")
        self.assertTrue(self.review.export_button.isEnabled())
        self.review.matrices.set_view("difference")
        shown = [v.text() for (k, r, c), (v, _d) in self.review.matrices.cells.items() if k == "T" and c == 3 and r < 3]
        self.assertTrue(all(t.startswith(("+", "-")) for t in shown), shown)
        self.review.matrices.set_view("current")
        self.assertTrue(all(not d.isVisible() for _v, d in self.review.matrices.cells.values()))

    def test_clicking_a_capture_row_selects_its_images(self):
        evidence = self.review.sections["Evidence"]
        images = self.review.sections["Images"]
        evidence.capture_clicked.emit(evidence.capture_ids[3])
        self.assertEqual(images.sel.currentIndex(), 3)

    def test_both_verdicts_are_shown_and_distinguished(self):
        texts = " ".join(w.text() for w in self.review.findChildren(QtWidgets.QLabel))
        self.assertIn("FAULT-AWARE RESEARCH VERDICT", texts)
        self.assertIn("MAINTENANCE RECOMMENDATION", texts)

    def test_no_acceptance_or_device_write_is_offered(self):
        labels = " ".join(b.text() for b in self.review.findChildren(QtWidgets.QPushButton))
        self.assertNotIn("Accept refined", labels)
        self.assertNotIn("Write to the device", labels)

    def test_a_comparison_that_lacks_diagnostics_still_opens(self):
        with tempfile.TemporaryDirectory() as tmp:
            check, meta, result = make_check(tmp, with_review=True, drop=("option_calibrations.json", "refined_calibration.json", "images"))
            import calibration_review
            review = calibration_review.CalibrationReview()
            review.set_check(check, result, meta, None)
            self.assertIn("Compare", review.sections)

    def test_export_cannot_overwrite_the_original_calibration(self):
        cal = Path(self.meta["calibration"])
        before = cal.read_bytes() if cal.exists() else None
        with mock.patch.object(QtWidgets.QFileDialog, "getSaveFileName", return_value=(str(cal), "")), \
                mock.patch.object(QtWidgets.QMessageBox, "warning") as warned:
            self.review.save_refined(ra.run_folder(self.check))
        warned.assert_called_once()
        if before is not None:
            self.assertEqual(before, cal.read_bytes())

    def test_text_export_writes_only_the_chosen_file(self):
        self.review.options.select_mode("extrinsic")
        target = Path(self.tmp.name) / "candidate.txt"
        before = digest(self.check)
        with mock.patch.object(QtWidgets.QFileDialog, "getSaveFileName", return_value=(str(target), "")):
            self.review.save_txt(ra.load(self.check))
        self.assertTrue(target.exists())
        self.assertEqual(before, digest(self.check), "an export must not change the check")


@unittest.skipUnless(CHECKS and REAL.exists(), "needs a saved check and the real maintenance output")
class TabNavigation(unittest.TestCase):
    def test_tabs_are_ordered_and_switching_changes_nothing(self):
        sys.argv = ["research_gui.py"]
        import research_gui as g
        if APP.styleSheet() != g.QSS:  # re-applying re-polishes every live window; that aborted natively on the Linux runner
            APP.setStyleSheet(g.QSS)
        win = g.MainWindow()
        names = [b.text() for b in win.pager.buttons]
        self.assertEqual(names, ["Processing", "Result", "Calibration review", "Report"])
        self.assertIs(win.stack.widget(2), win.review)
        with tempfile.TemporaryDirectory() as tmp:
            check, meta, result = make_check(tmp, with_review=True)
            win.open_run(str(check))
            before = digest(check)
            for index in (0, 1, 2, 3, 2, 1, 0, 2):
                win.pager.select(index)
                APP.processEvents()
                self.assertEqual(win.stack.currentIndex(), index)
            self.assertIsNone(win.review.proc, "switching tabs must not start a calculation")
            self.assertEqual(before, digest(check), "switching tabs must not change saved values")
        win.review.shutdown()


if __name__ == "__main__":
    unittest.main()
