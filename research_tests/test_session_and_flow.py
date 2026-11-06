"""Remembered inputs, matrices shown on load, the stage timeline, the maintenance comparison inside Processing, and the
controls that were removed from the Calibration review tab."""
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

import matrix_view  # noqa: E402
import processing_view as pv  # noqa: E402
import review_adapter as ra  # noqa: E402
import settings_store  # noqa: E402
from PyQt5 import QtCore, QtGui, QtWidgets  # noqa: E402

APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
APP.setStyle("Fusion")

EXAMPLE = ROOT / "examples" / "calibration.example.json"
REAL = ROOT.parent.parent / "Calibration maintenance" / "results" / "rig_20261106_151654"
CHECKS = sorted(p for p in (ROOT / "research_artifacts").glob("gui_*") if (p / "assessment.json").exists() and p.with_name(p.name + ".gui.json").exists())


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "settings.json"

    def test_missing_and_damaged_files_remember_nothing(self):
        self.assertEqual(settings_store.Store(self.path).data, {})
        for text in ("{not json", "[]", "null", "5", '{"version": 99, "mode": "check"}', ""):
            self.path.write_text(text, encoding="utf-8")
            self.assertEqual(settings_store.Store(self.path).data, {}, text)
        self.path.write_bytes(b"\xff\xfe\x00bad")
        self.assertEqual(settings_store.Store(self.path).data, {})

    def test_wrong_types_and_unknown_keys_are_dropped(self):
        self.path.write_text(json.dumps(dict(version=1, calibration=5, captures="x", auto_review="yes", mode=["a"], evil="y", strategy="s")))
        self.assertEqual(settings_store.Store(self.path).data, dict(captures="x", strategy="s"))

    def test_values_round_trip_including_unicode_and_leave_no_temp_file(self):
        s = settings_store.Store(self.path)
        self.assertTrue(s.update(calibration="C:/donn\u00e9es/\u00e9talonnage \u6821\u51c6.json", auto_review=False, mode="scratch"))
        self.assertFalse(s.update(mode="scratch"), "an unchanged value is not rewritten")
        again = settings_store.Store(self.path)
        self.assertEqual(again.get("calibration"), "C:/donn\u00e9es/\u00e9talonnage \u6821\u51c6.json")
        self.assertIs(again.get("auto_review"), False)
        self.assertEqual([p.name for p in Path(self.tmp.name).iterdir()], ["settings.json"])
        s.update(nonsense=1, mode=7)
        self.assertEqual(settings_store.Store(self.path).get("mode"), "scratch")

    def test_existing_only_offers_paths_that_are_still_there(self):
        s = settings_store.Store(self.path)
        keep = Path(self.tmp.name) / "a.json"
        keep.write_text("{}")
        s.update(calibration=str(keep), captures=str(Path(self.tmp.name)), cal_dir=str(keep))
        self.assertEqual(s.existing("calibration", "file"), str(keep))
        self.assertEqual(s.existing("captures", "dir"), self.tmp.name)
        self.assertIsNone(s.existing("cal_dir", "dir"), "a file is not a folder")
        keep.unlink()
        self.assertIsNone(s.existing("calibration", "file"))
        self.assertIsNone(s.existing("nothing", "file"))

    def test_an_unwritable_location_never_raises(self):
        blocker = Path(self.tmp.name) / "file"
        blocker.write_text("x")
        s = settings_store.Store(blocker / "sub" / "settings.json")
        s.update(mode="check")
        self.assertEqual(s.get("mode"), "check")

    def test_clear_forgets_everything(self):
        s = settings_store.Store(self.path)
        s.update(mode="check")
        s.clear()
        self.assertEqual(settings_store.Store(self.path).data, {})


class MatrixViewTests(unittest.TestCase):
    def test_matrices_of_accepts_only_complete_calibrations(self):
        good = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        K, D, T = matrix_view.matrices_of(good)
        self.assertEqual((K.shape, D.shape, T.shape), ((3, 3), (4,), (4, 4)))
        for bad in (None, {}, "x", {"intrinsics": {}}, dict(good, extrinsics=dict(transform_lidar_to_camera=[[1, 2]])),
                    dict(good, intrinsics=dict(camera_matrix=[[1, 2, 3]]))):
            self.assertIsNone(matrix_view.matrices_of(bad))

    def test_the_pair_shows_k_and_t_side_by_side_and_stacks_when_narrow(self):
        pair = matrix_view.MatrixPair(json.loads(EXAMPLE.read_text(encoding="utf-8")))
        self.assertTrue(pair.valid)
        self.assertEqual(len(pair.groups), 2)
        pair.resize(1100, 300)
        pair.show()
        APP.processEvents()
        self.assertEqual(pair.box.direction(), QtWidgets.QBoxLayout.LeftToRight)
        pair.resize(300, 600)
        APP.processEvents()
        self.assertEqual(pair.box.direction(), QtWidgets.QBoxLayout.TopToBottom)
        self.assertFalse(matrix_view.MatrixPair({}).valid)

    def test_loading_a_calibration_shows_its_matrices_without_opening_anything(self):
        sys.argv = ["research_gui.py"]
        import research_gui as g
        APP.setStyleSheet(g.QSS)
        win = g.MainWindow()
        win.load_cal(str(EXAMPLE))
        self.assertEqual(len(win.cal.findChildren(matrix_view.MatrixPair)), 1)
        win.load_cal(str(EXAMPLE))
        APP.processEvents()
        self.assertEqual(len([p for p in win.cal.findChildren(matrix_view.MatrixPair) if p.isVisibleTo(win)]), 1, "reloading must not pile up copies")
        win.load_cal(str(Path(tempfile.gettempdir()) / "does_not_exist.json"))
        APP.processEvents()
        self.assertEqual([p for p in win.cal.findChildren(matrix_view.MatrixPair) if p.isVisibleTo(win)], [])


class RememberTests(unittest.TestCase):
    def window(self, store_path):
        sys.argv = ["research_gui.py"]
        import research_gui as g
        APP.setStyleSheet(g.QSS)
        win = g.MainWindow()
        win.store = settings_store.Store(store_path)
        self.addCleanup(win.review.shutdown)
        return win

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store_path = Path(self.tmp.name) / "settings.json"

    def test_a_new_window_has_nothing_remembered_and_writes_nothing(self):
        sys.argv = ["research_gui.py"]
        import research_gui as g
        win = g.MainWindow()
        self.assertIsNone(win.store)
        win.load_cal(str(EXAMPLE))
        self.assertFalse(self.store_path.exists())
        self.assertFalse(win.restore_state())

    def test_the_last_calibration_options_and_dialog_folders_come_back(self):
        a = self.window(self.store_path)
        a.load_cal(str(EXAMPLE))
        a.strategy.setCurrentIndex(2)
        a.auto_review.setChecked(False)
        with mock.patch.object(QtWidgets.QFileDialog, "getOpenFileName", return_value=(str(EXAMPLE), "")):
            a.open_cal()
        self.assertEqual(settings_store.Store(self.store_path).get("cal_dir"), str(EXAMPLE.parent))
        b = self.window(self.store_path)
        self.assertTrue(b.restore_state())
        self.assertEqual(b.cal.path, a.cal.path)
        self.assertEqual(b.strategy.currentIndex(), 2)
        self.assertFalse(b.auto_review.isChecked())
        self.assertFalse(b.restored_row.isHidden())
        self.assertIn("calibration", b.restored_text.text())

    def test_a_calibration_that_was_deleted_is_not_offered_and_nothing_breaks(self):
        copy = Path(self.tmp.name) / "c.json"
        shutil.copy(EXAMPLE, copy)
        a = self.window(self.store_path)
        a.load_cal(str(copy))
        copy.unlink()
        b = self.window(self.store_path)
        self.assertFalse(b.restore_state())
        self.assertEqual(b.cal.path, "")
        self.assertTrue(b.restored_row.isHidden())

    def test_calibrating_from_scratch_is_remembered_and_skips_the_calibration(self):
        a = self.window(self.store_path)
        a.load_cal(str(EXAMPLE))
        a.mode_combo.setCurrentIndex(a.mode_combo.findData("scratch"))
        b = self.window(self.store_path)
        b.restore_state()
        self.assertEqual(b.mode, "scratch")
        self.assertEqual(b.cal.path, "", "no calibration is loaded when none is needed")

    def test_window_size_and_position_are_restored(self):
        a = self.window(self.store_path)
        a.resize(1111, 777)
        a.show()
        APP.processEvents()
        a.close()
        self.assertTrue(settings_store.Store(self.store_path).get("geometry"))
        b = self.window(self.store_path)
        b.restore_state()
        self.assertEqual((b.width(), b.height()), (1111, 777))

    def test_forget_clears_the_store(self):
        a = self.window(self.store_path)
        a.load_cal(str(EXAMPLE))
        a.forget_remembered()
        self.assertEqual(settings_store.Store(self.store_path).data, {})

    def test_a_damaged_settings_file_still_starts_normally(self):
        self.store_path.write_text("{garbage")
        a = self.window(self.store_path)
        self.assertFalse(a.restore_state())


class StageListTests(unittest.TestCase):
    def test_the_timeline_shows_every_stage_with_its_state_and_paints(self):
        view = pv.ProcessingView()
        for ev in [dict(stage="data"), dict(stage="features", captures=[], max_features=10), dict(stage="folds", total=2, hypotheses=["KEEP"])]:
            view.model.apply(ev)
        view._sync(force=True)
        self.assertEqual(view.list.count(), 7)
        states = [view.list.item(i).data(QtCore.Qt.UserRole)["state"] for i in range(7)]
        self.assertEqual(states[:3], ["done", "done", "active"])
        self.assertEqual(set(states[3:]), {"pending"})
        self.assertFalse(view.list.item(6).flags() & QtCore.Qt.ItemIsSelectable, "a stage that has not started cannot be selected")
        view.resize(900, 600)
        view.show()
        view.list.set_phase(0.25)
        self.assertFalse(view.list.grab().isNull())
        for key in view.model.keys:
            self.assertTrue(pv.SHORT[key], "every stage has a one-line caption")


def fake_review_run(check, finished=False, steps=("data", "features", "health"), sub="check 8 of 12", with_png=True):
    run = ra.work_run(check)
    run.mkdir(parents=True, exist_ok=True)
    images = []
    if with_png:
        (run / "stages").mkdir(exist_ok=True)
        img = QtGui.QImage(40, 30, QtGui.QImage.Format_RGB32)
        img.fill(0x336699)
        img.save(str(run / "stages" / "data_185316_547419.png"))
        images = ["stages/data_185316_547419.png"]
    stages = [dict(stage="start", message="x", images=[])] + [dict(stage=s, message=s, images=images if s == "data" else []) for s in steps]
    (run / "progress.json").write_text(json.dumps(dict(finished=finished, stages=stages)))
    (run / "run.log").write_text(f"[   1.0s] something\n[ 112.7s] Comparing update options: {sub}\n")
    return run


class ReviewInProcessingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.dict(os.environ, {"LOCALAPPDATA": self.tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.check = Path(self.tmp.name) / "gui_x"
        self.check.mkdir()

    def test_the_review_is_a_stage_after_the_verdict_and_the_verdict_does_not_end_it(self):
        m = pv.RunModel(review=True)
        self.assertEqual(m.keys[-2:], ["verdict", "review"])
        m.review_begin()
        m.apply(dict(stage="verdict", status="KEEP_CURRENT"))
        self.assertEqual(m.state["verdict"], "done")
        self.assertEqual(m.state["review"], "active", "the fault-aware verdict must not finish the maintenance comparison")
        m.review_done({"verdict": "NO UPDATE NEEDED"})
        self.assertEqual(m.state["review"], "done")

    def test_a_failure_while_the_review_runs_is_the_reviews_failure_only(self):
        m = pv.RunModel(review=True)
        m.apply({"stage": "verdict", "status": "KEEP_CURRENT"})
        m.review_begin()
        m.mark_failed("boom")
        self.assertEqual(m.state["review"], "failed")
        self.assertEqual(m.state["verdict"], "done", "the fault-aware result stays valid")

    def test_review_stage_is_not_added_for_scratch_checks(self):
        m = pv.RunModel(scratch=True, review=True)
        m.enable_review()
        self.assertNotIn("review", m.keys)

    def test_live_progress_reads_the_comparisons_own_files(self):
        fake_review_run(self.check)
        info = ra.live_progress(self.check)
        self.assertEqual((info["done"], info["step"], info["sub"]), (3, "options", (8, 12)))
        self.assertEqual(len(info["images"]), 1)
        self.assertNotIn("[", info["message"])

    def test_live_progress_with_nothing_or_junk_is_safe(self):
        self.assertEqual(ra.live_progress(self.check)["done"], 0)
        run = ra.work_run(self.check)
        run.mkdir(parents=True)
        (run / "progress.json").write_text("{junk")
        (run / "run.log").write_bytes(b"\xff\xfe")
        self.assertEqual(ra.live_progress(self.check)["done"], 0)

    def test_the_view_follows_the_running_comparison_and_finishes(self):
        view = pv.ProcessingView()
        view.reset(False, None)
        for ev in ({"stage": "data"}, {"stage": "verdict", "status": "KEEP_CURRENT"}):
            view.model.apply(ev)
        fake_review_run(self.check)
        view.add_review(self.check)
        self.assertIn("review", view.pages)
        self.assertEqual(view.model.state["review"], "active")
        view._poll_review(force=True)
        view._sync(force=True)
        page = view.pages["review"]
        self.assertEqual(page["bar"].value(), 3)
        self.assertFalse(page["sub"].isHidden())
        self.assertEqual((page["sub"].value(), page["sub"].maximum()), (8, 12))
        self.assertEqual(len(page["images"].shown), 1)
        self.assertEqual(view.stack.currentIndex(), view.model.keys.index("review"), "the running stage is followed")
        run = ra.run_folder(self.check)
        run.mkdir(parents=True)
        (run / "summary.json").write_text(json.dumps(dict(verdict="NO UPDATE NEEDED", shift_median_px=2.25)))
        view.review_finished(True)
        self.assertEqual(view.model.state["review"], "done")
        self.assertIn("No update needed", page["summary"].text())
        self.assertIn("2.25", page["summary"].text())

    def test_the_timer_alone_keeps_the_review_page_moving_after_the_fault_aware_run_ended(self):
        view = pv.ProcessingView()
        view.reset(False, None)
        for ev in ({"stage": "data"}, {"stage": "verdict", "status": "KEEP_CURRENT"}):
            view.model.apply(ev)
        self.assertIsNone(view.tail, "the fault-aware process is no longer being followed")
        fake_review_run(self.check)
        view.add_review(self.check)
        for _ in range(40):
            view._tick()          # exactly what the animation timer does; nothing else polls
        page = view.pages["review"]
        self.assertEqual(page["bar"].value(), 3, "live progress must not wait for the comparison to finish")
        self.assertEqual((page["sub"].value(), page["sub"].maximum()), (8, 12))
        view.timer.stop()

    def test_the_review_stage_reports_its_own_duration_not_the_last_events(self):
        import time
        m = pv.RunModel(review=True)
        m.apply({"t": 17.9, "stage": "verdict", "status": "KEEP_CURRENT"})
        m.live = True
        m.review_begin()
        time.sleep(0.05)
        m.review_done({})
        self.assertNotIn(("review", "s"), m.stamp, "a stage that is not an event has no event timestamp")
        self.assertGreater(m.duration("review"), 0.0)
        self.assertLess(m.duration("review"), 5.0)

    def test_a_failed_comparison_says_why(self):
        view = pv.ProcessingView()
        view.reset(False, None)
        view.add_review(self.check)
        view.review_finished(False, "ran out of memory")
        self.assertEqual(view.model.state["review"], "failed")
        self.assertIn("ran out of memory", view.pages["review"]["now"].text())

    def test_finishing_twice_or_without_a_review_is_harmless(self):
        view = pv.ProcessingView()
        view.review_finished(True)
        view.reset(False, None)
        view.add_review(self.check)
        view.review_finished(False, "x")
        view.review_finished(True)
        self.assertEqual(view.model.state["review"], "failed")

    def test_an_older_check_with_a_saved_review_shows_it_as_done(self):
        view = pv.ProcessingView()
        run = ra.run_folder(self.check)
        run.mkdir(parents=True)
        (run / "summary.json").write_text(json.dumps(dict(verdict="BORDERLINE")))
        view.show_result(self.check, {"status": "KEEP_CURRENT"}, "done")
        self.assertEqual(view.model.state["review"], "done")
        self.assertEqual(view.model.review["summary"]["verdict"], "BORDERLINE")
        view.show_result(self.check, {"status": "KEEP_CURRENT"}, None)
        self.assertNotIn("review", view.model.keys)


@unittest.skipUnless(CHECKS, "needs a saved check")
class MainWindowFlow(unittest.TestCase):
    def setUp(self):
        sys.argv = ["research_gui.py"]
        import research_gui as g
        APP.setStyleSheet(g.QSS)
        self.g = g
        self.win = g.MainWindow()
        self.addCleanup(self.win.review.shutdown)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        src = CHECKS[-1]
        self.check = Path(self.tmp.name) / "gui_20990101_000000"
        self.check.mkdir()
        shutil.copy(src / "assessment.json", self.check / "assessment.json")
        meta = json.loads(src.with_name(src.name + ".gui.json").read_text(encoding="utf-8"))
        meta["with_review"] = True
        self.check.with_name(self.check.name + ".gui.json").write_text(json.dumps(meta))

    def finish(self, started):
        self.win.run_output = self.win.output = self.check
        self.win.process = QtCore.QProcess()
        with mock.patch.object(self.win.review, "start", return_value=started), mock.patch.object(self.win, "refresh_runs"):
            self.win.processing.begin(self.check, False, 4, review=True)
            self.win.finished_run(0)

    def test_the_comparison_becomes_the_last_processing_stage_when_it_starts(self):
        self.finish(True)
        m = self.win.processing.model
        self.assertEqual(m.state["verdict"], "done")
        self.assertEqual(m.state["review"], "active")

    def test_a_comparison_that_cannot_start_is_shown_as_failed_in_processing(self):
        with mock.patch.object(ra, "inputs_for", return_value=(None, "the calibration file is gone")):
            self.finish(False)
        self.assertEqual(self.win.processing.model.state["review"], "failed")
        self.assertIn("calibration file is gone", self.win.processing.pages["review"]["now"].text())

    def test_when_the_comparison_ends_processing_follows(self):
        self.finish(True)
        self.win.processing.review_check = self.check
        with mock.patch.object(ra, "state", return_value="ready"), mock.patch.object(self.win.processing, "review_finished") as done:
            self.win.on_review_changed()
        done.assert_called_once()
        self.assertTrue(done.call_args[0][0])

    def test_view_calibration_belongs_to_the_result_tab_only(self):
        self.win.open_run(str(CHECKS[-1]))
        has = bool(self.win.result_cal)
        for index, expected in ((1, has), (0, False), (2, False), (3, False), (1, has)):
            self.win.pager.select(index)
            self.assertEqual(self.win.cal_btn.isHidden(), not expected, f"tab {index}")

    def test_closing_while_a_review_runs_asks_first(self):
        self.finish(True)
        event = QtGui.QCloseEvent()
        with mock.patch.object(self.win.review, "is_running", return_value=True), \
                mock.patch.object(QtWidgets.QMessageBox, "question", return_value=QtWidgets.QMessageBox.No) as ask:
            self.win.closeEvent(event)
        ask.assert_called_once()
        self.assertFalse(event.isAccepted())


@unittest.skipUnless(REAL.exists(), "needs the real maintenance output")
class ReviewTabControls(unittest.TestCase):
    def test_the_removed_controls_are_gone_and_run_again_moved(self):
        import calibration_review
        with tempfile.TemporaryDirectory() as tmp:
            check = Path(tmp) / "gui_x"
            (check / ra.REVIEW_DIR).mkdir(parents=True)
            shutil.copytree(REAL, check / ra.REVIEW_DIR / ra.RUN_NAME, ignore=shutil.ignore_patterns("stacked", "decode"))
            review = calibration_review.CalibrationReview()
            review.set_check(check, {"status": "KEEP_CURRENT"}, {"mode": "check"}, None)
            buttons = {b.text() for b in review.findChildren(QtWidgets.QPushButton)}
            labels = " ".join(label.text() for label in review.findChildren(QtWidgets.QLabel))
            self.assertFalse([b for b in review.findChildren(QtWidgets.QPushButton) if b.objectName() == "chip"], "no 'Jump to' chips")
            self.assertNotIn("Jump to", labels)
            self.assertNotIn("Matrices show", labels)
            self.assertNotIn("Run again\u2026", buttons)
            self.assertNotIn("Option with changes", buttons)
            self.assertIn("Run the comparison again\u2026", buttons)
            self.assertIs(review.sections["Matrices"], review.matrices)
            review.options.select_mode("extrinsic")
            self.assertEqual(review.matrices.mode, "extrinsic", "the matrices follow the selected option card")
            self.assertTrue(any(d.text() for (_v, d) in review.matrices.cells.values()), "the changes are marked")


if __name__ == "__main__":
    unittest.main()
