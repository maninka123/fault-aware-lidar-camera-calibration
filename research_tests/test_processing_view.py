"""Processing tab: the run model, the event reader and the widgets, including hostile and degenerate input."""
import json
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "gui"))

import processing_view as pv  # noqa: E402
from PyQt5 import QtWidgets  # noqa: E402

APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
APP.setStyle("Fusion")

SAVED = sorted(p for p in (ROOT / "research_artifacts").glob("gui_*/assessment.json"))


def saved_result():
    for path in reversed(SAVED):
        try:
            r = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if (r.get("validation") or {}).get("folds"):
            return path.parent, r
    return None, None


FOLDER, RESULT = saved_result()


def synthetic(folds=3, hypotheses=("KEEP", "R", "RT")):
    events = [dict(stage="data"), dict(stage="features", captures=[dict(id=f"19000{i}_1", points=1000 * (i + 1), used_edges=500 + i) for i in range(folds)],
                                       max_features=1200),
              dict(stage="folds", total=folds, hypotheses=list(hypotheses), min_relative_gain=0.01)]
    for f in range(folds):
        events.append(dict(stage="fold", index=f, total=folds, test=f"19000{f}_1"))
        for h in hypotheses:
            events.append(dict(stage="fit", fold=f, test=f"19000{f}_1", hypothesis=h, loss=0.2 - (0.001 * f if h == "R" else 0.0), success=True, rank=3))
    events += [dict(stage="decision", status="KEEP_CURRENT", candidate="R", best_relative_gain=0.004, min_relative_gain=0.01, reason="Too small."),
               dict(stage="candidate", hypothesis="R"), dict(stage="outer", count=0, gain=None, passed=False),
               dict(stage="verdict", status="KEEP_CURRENT", action="KEEP_REFERENCE")]
    return events


class ModelTests(unittest.TestCase):
    def test_hostile_events_are_ignored(self):
        m = pv.RunModel()
        for bad in (None, 5, "x", [], {}, {"stage": 3}, {"stage": "nonsense"}, {"stage": "fit"}, {"stage": "fit", "fold": "a", "hypothesis": 1},
                    {"stage": "fit", "fold": -1, "hypothesis": "R"}, {"stage": "features", "captures": "no"}, {"stage": "folds", "total": "many"},
                    {"stage": "fold", "index": "zero"}, {"stage": "decision", "best_relative_gain": "x"}, {"stage": "outer", "count": []}):
            m.apply(bad)       # must not raise
        self.assertIsNone(m.failure)

    def test_a_full_run_ends_with_every_stage_done(self):
        m = pv.RunModel()
        for ev in synthetic():
            self.assertTrue(m.apply(ev) in (True, False))
        self.assertTrue(all(s == "done" for s in m.state.values()), m.state)
        self.assertEqual(m.folds_done(), 3)
        rows = {r["key"]: r for r in m.race_rows()}
        self.assertEqual(rows["KEEP"]["gain"], 0.0)
        self.assertTrue(rows["R"]["best"])
        self.assertGreater(rows["R"]["gain"], 0)

    def test_partial_run_reports_progress_without_inventing_results(self):
        m = pv.RunModel()
        for ev in synthetic(folds=4)[:9]:      # data, features, folds, fold 0 (3 fits), fold 1 start + 1 fit
            m.apply(ev)
        self.assertEqual(m.state["folds"], "active")
        self.assertEqual(m.folds_done(), 1)
        self.assertIsNone(m.decision)
        self.assertNotIn("decision", [k for k, v in m.state.items() if v == "done"])

    def test_duplicates_nan_and_zero_keep_loss(self):
        m = pv.RunModel()
        m.apply(dict(stage="folds", total=1, hypotheses=["KEEP", "R"]))
        for _ in range(3):
            m.apply(dict(stage="fit", fold=0, hypothesis="KEEP", loss=0.0))
        m.apply(dict(stage="fit", fold=0, hypothesis="R", loss=float("nan")))
        self.assertEqual(len(m.fits), 2)
        rows = m.race_rows()          # no division by a zero or missing KEEP loss
        self.assertTrue(all(math.isfinite(r["gain"]) for r in rows))

    def test_out_of_order_events_settle_sensibly(self):
        m = pv.RunModel()
        m.apply(dict(stage="decision", status="X", best_relative_gain=0.0, min_relative_gain=0.01))
        m.apply(dict(stage="verdict", status="X"))
        self.assertEqual(m.state["verdict"], "done")
        self.assertTrue(all(s == "done" for s in m.state.values()))

    def test_unknown_hypothesis_is_added_and_zero_folds_is_fine(self):
        m = pv.RunModel()
        m.apply(dict(stage="folds", total=0, hypotheses=[]))
        m.apply(dict(stage="fit", fold=0, hypothesis="NEW", loss=0.1))
        self.assertIn("NEW", m.hypotheses)
        self.assertEqual(m.folds_total, 1)
        self.assertIsNone(m.eta_seconds())

    def test_failure_is_recorded_once_and_cancel_is_distinct(self):
        m = pv.RunModel()
        m.apply(dict(stage="data"))
        m.mark_failed("first")
        m.mark_failed("second")
        self.assertEqual(m.failure, "first")
        self.assertEqual(m.state["data"], "failed")
        c = pv.RunModel()
        c.mark_cancelled()
        self.assertTrue(c.cancelled)
        self.assertIn("Stopped", c.failure)

    def test_process_output_lines_are_understood_and_junk_is_not(self):
        m = pv.RunModel()
        self.assertTrue(m.apply_log_line("[    3.0s] decoded 191640_838463: still window 4.0 s, 140 images, 41 LiDAR frames"))
        self.assertEqual(m.decoded[0][:2], ("191640_838463", 4.0))
        self.assertTrue(m.apply_log_line("fault_aware: comparison fold 2/4 (191734_206763)"))
        for junk in ("", None, "Traceback (most recent call last):", "decoded: nothing", "\x00\x01"):
            self.assertFalse(m.apply_log_line(junk))

    def test_scratch_mode_has_its_own_stages(self):
        m = pv.RunModel(scratch=True)
        self.assertEqual(m.keys, ["data", "scratch", "verdict"])
        m.apply(dict(stage="scratch", message="working"))
        m.apply(dict(stage="verdict", status="INITIAL_CALIBRATION_CANDIDATE"))
        self.assertTrue(all(s == "done" for s in m.state.values()))

    def test_short_id_and_num(self):
        self.assertEqual(pv.short_id("191640_838463"), "19:16:40")
        self.assertEqual(pv.short_id("capture_20261105_191640_838463_enclosure_on"), "19:16:40")
        self.assertEqual(pv.short_id("weird"), "weird")
        self.assertIsNone(pv.num("x"))
        self.assertIsNone(pv.num(float("inf")))
        self.assertEqual(pv.num("2.5"), 2.5)


class EventTailTests(unittest.TestCase):
    def test_missing_partial_malformed_and_replaced_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "progress.jsonl"
            tail = pv.EventTail(path)
            self.assertEqual(tail.read(), [])                                  # no file yet
            path.write_bytes(b'{"stage": "data"}\n{"stage": "fea')             # half-written last line
            self.assertEqual([e["stage"] for e in tail.read()], ["data"])
            with open(path, "ab") as f:
                f.write(b'tures"}\nnot json\n\n\xff\xfe\n{"stage": "folds", "note": "\xc3\xa9"}\n')
            self.assertEqual([e["stage"] for e in tail.read()], ["features", "folds"])
            path.write_bytes(b'{"stage": "verdict"}\n')                          # file replaced by a shorter one
            self.assertEqual([e["stage"] for e in tail.read()], ["verdict"])
            self.assertEqual(tail.read(), [])


class BackendEventTests(unittest.TestCase):
    """research_calibration.progress_events: best effort, never able to affect an assessment."""

    def test_events_are_written_as_json_lines_with_numpy_and_nan_values(self):
        import numpy as np
        from research_calibration.progress_events import Events, number
        with tempfile.TemporaryDirectory() as tmp:
            ev = Events(tmp)
            ev.emit("fit", loss=number(np.float64(0.25)), rank=int(np.int64(3)), nan=number(float("nan")), arr=np.arange(3), path=Path(tmp))
            lines = (Path(tmp) / "progress.jsonl").read_text(encoding="utf-8").splitlines()
            row = json.loads(lines[0])
            self.assertEqual((row["stage"], row["loss"], row["rank"], row["nan"], row["arr"]), ("fit", 0.25, 3, None, [0, 1, 2]))
            self.assertIn("t", row)

    def test_no_output_folder_or_an_unwritable_one_is_silently_ignored(self):
        from research_calibration.progress_events import Events
        Events(None).emit("data")                                   # no folder: nothing happens
        with tempfile.TemporaryDirectory() as tmp:
            blocker = Path(tmp) / "file"
            blocker.write_text("x")
            Events(blocker / "sub").emit("data")                    # a path that cannot exist: must not raise

    def test_number_handles_junk(self):
        from research_calibration.progress_events import number
        for junk in (None, "x", [], float("inf"), float("-inf"), float("nan")):
            self.assertIsNone(number(junk))
        self.assertEqual(number("3"), 3.0)


class ReconstructionTests(unittest.TestCase):
    def test_degenerate_results_still_give_a_sequence(self):
        for r in (None, {}, [], "x", {"diagnostics": 5}, {"validation": {"folds": "x"}}, {"validation": {"folds": {"KEEP": []}}}):
            events = pv.events_from_result(r)
            self.assertEqual(events[-1]["stage"], "verdict")
            m = pv.RunModel()
            for ev in events:
                m.apply(ev)
            self.assertEqual(m.state["verdict"], "done")

    @unittest.skipUnless(RESULT, "no saved check")
    def test_a_real_saved_check_replays_to_the_saved_verdict(self):
        m = pv.RunModel()
        for ev in pv.events_from_result(RESULT, FOLDER):
            m.apply(ev)
        self.assertEqual(m.verdict["status"], RESULT["status"])
        folds = RESULT["validation"]["folds"]
        self.assertEqual(set(m.hypotheses), set(folds))
        self.assertEqual(m.folds_done(), len(next(iter(folds.values()))))

    def test_count_captures(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            self.assertIsNone(pv.count_captures(t))
            self.assertIsNone(pv.count_captures(t / "missing"))
            (t / "a.npz").write_bytes(b"")
            (t / "b.npz").write_bytes(b"")
            self.assertEqual(pv.count_captures(t), 2)
        with tempfile.TemporaryDirectory() as tmp:
            for n in ("capture_1", "capture_2", "capture_3"):
                (Path(tmp) / n).mkdir()
                (Path(tmp) / n / "rig_0.bag").write_bytes(b"")
            (Path(tmp) / "capture_empty").mkdir()
            self.assertEqual(pv.count_captures(tmp), 3)


class WidgetTests(unittest.TestCase):
    def setUp(self):
        self.view = pv.ProcessingView()
        self.addCleanup(self.view.timer.stop)

    def test_live_run_follows_growing_event_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.view.begin(tmp, False, 3)
            self.assertEqual(self.view.model.active, "data")
            with open(Path(tmp) / "progress.jsonl", "a", encoding="utf-8") as f:
                for ev in synthetic()[:6]:
                    f.write(json.dumps(ev) + "\n")
            self.view.poll()
            self.assertEqual(self.view.model.state["features"], "done")
            self.assertEqual(self.view.model.active, "folds")
            self.assertEqual(self.view.stack.currentIndex(), self.view.model.keys.index("folds"))   # follows the running stage
            self.view.select_stage("data")
            self.view.poll()
            self.assertEqual(self.view.stack.currentIndex(), 0, "after a click the view must stay where the user put it")
            self.view.finish(False, "boom")
            self.assertIn("boom", self.view.model.failure)
            self.assertFalse(self.view.timer.isActive())

    def test_cancel_marks_the_stage_and_stops_the_clock(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.view.begin(tmp, False, None)
            self.view.cancelled()
            self.assertTrue(self.view.model.cancelled)
            self.assertFalse(self.view.timer.isActive())

    def test_scratch_view_and_log_text_of_any_shape(self):
        self.view.reset(scratch=True)
        self.assertEqual(list(self.view.pages), ["data", "scratch", "verdict"])
        for text in ("", None, "x" * 100000, "line\r\nline2\n\n", "✓ unicode é"):
            self.view.feed_log(text)

    @unittest.skipUnless(RESULT, "no saved check")
    def test_finished_check_shows_everything_done_and_can_replay(self):
        self.view.show_result(FOLDER, RESULT)
        self.assertTrue(all(s == "done" for s in self.view.model.state.values()))
        self.assertFalse(self.view.replay_button.isHidden())
        self.view.replay()
        for _ in range(4000):
            if not self.view.replaying:
                break
            self.view._tick()
        self.assertFalse(self.view.replaying, "the replay must finish")
        self.assertEqual(self.view.model.verdict["status"], RESULT["status"])
        self.view.timer.stop()

    def test_degenerate_results_do_not_break_the_view(self):
        for r in (None, {}, {"status": "X"}):
            self.view.show_result(tempfile.gettempdir(), r)
            self.assertEqual(self.view.model.state["verdict"], "done")

    def test_many_captures_are_capped(self):
        with tempfile.TemporaryDirectory() as tmp:
            from PyQt5 import QtGui
            img = QtGui.QImage(40, 30, QtGui.QImage.Format_RGB32)
            img.fill(0x336699)
            for i in range(pv.MAX_THUMBS + 25):
                img.save(str(Path(tmp) / f"capture_20261105_19{i // 60:02d}{i % 60:02d}_1.png"))
            thumbs = self.view.pages["data"]["thumbs"]
            thumbs.add_folder(tmp, fade=False)
            self.assertEqual(thumbs.count, pv.MAX_THUMBS)

    def test_half_written_image_is_retried_not_lost(self):
        with tempfile.TemporaryDirectory() as tmp:
            png = Path(tmp) / "capture_20261105_190000_1.png"
            png.write_bytes(b"\x89PNG not finished")
            thumbs = self.view.pages["data"]["thumbs"]
            self.assertEqual(thumbs.add_folder(tmp, fade=False), 0)
            from PyQt5 import QtGui
            img = QtGui.QImage(40, 30, QtGui.QImage.Format_RGB32)
            img.fill(0x336699)
            img.save(str(png))
            self.assertEqual(thumbs.add_folder(tmp, fade=False), 1)


if __name__ == "__main__":
    unittest.main()
