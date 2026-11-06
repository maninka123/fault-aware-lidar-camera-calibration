import json
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "gui"))
import numpy as np  # noqa: E402

import result_visuals as rv  # noqa: E402

CAL = {"intrinsics": {"camera_matrix": [[200, 0, 240], [0, 200, 180], [0, 0, 1]], "distortion_coefficients": [.1, -.3, 0, 0]},
       "extrinsics": {"transform_lidar_to_camera": [[0, -1, 0, .1], [0, 0, -1, 0], [1, 0, 0, 0], [0, 0, 0, 1]]}}


class GeometryTests(unittest.TestCase):
    def test_blend_endpoints_and_identity(self):
        a = rv.cal_arrays(CAL)
        shifted = json.loads(json.dumps(CAL))
        shifted["intrinsics"]["camera_matrix"][0][0] = 210
        shifted["extrinsics"]["transform_lidar_to_camera"][0][3] = .15
        b = rv.cal_arrays(shifted)
        self.assertTrue(np.allclose(rv.blend(a, b, 0)["t"], a["t"]))
        self.assertTrue(np.allclose(rv.blend(a, b, 1)["f"], b["f"]))
        self.assertTrue(np.allclose(rv.blend(a, a, 3)["R"], a["R"]))

    def test_project_forward_point_hits_principal_point(self):
        a = rv.cal_arrays(CAL)
        u, v, ok = rv.project(np.array([[5., 0., 0.], [-5., 0., 0.]]), a)  # lidar x is camera z
        self.assertTrue(ok[0] and not ok[1])
        self.assertAlmostEqual(u[0], 240 + (0.1 / 5) * 200, delta=1.0)


class ResultTests(unittest.TestCase):
    def setUp(self):
        runs = sorted((ROOT / "research_artifacts").glob("gui_*/assessment.json"))
        runs = [p for p in runs if json.loads(p.read_text(encoding="utf-8")).get("status") == "KEEP_CURRENT"]
        if not runs:
            self.skipTest("no KEEP_CURRENT result saved")
        self.r = json.loads(runs[-1].read_text(encoding="utf-8"))

    def test_checklist_never_claims_ground_truth(self):
        checks = rv.build_checks(self.r)
        self.assertEqual(checks[-1][0], "na")
        self.assertIn("ground truth", checks[-1][1].lower())
        self.assertTrue(any(c[0] == "fail" for c in checks))  # a kept calibration must show what failed

    def test_gain_rows_match_decision(self):
        rows, gate = rv.gain_rows(self.r)
        self.assertEqual(rows[0]["key"], "KEEP")
        self.assertAlmostEqual(rows[0]["gain"], 0.0)
        self.assertAlmostEqual(gate, 1.0)
        best = next(x for x in rows if x["best"])
        self.assertAlmostEqual(best["gain"], self.r["diagnostics"]["decision"]["best_relative_gain"] * 100, places=6)


class AlignmentAndOverlayTests(unittest.TestCase):
    """The figure must say whether the current calibration lines up, and a solid blob must not hide the photo."""

    def test_note_warns_below_the_maintenance_bar_and_confirms_above_it(self):
        text, warn = rv.alignment_note(dict(lift=1.0, share=.065, refined_lift=1.24, min_lift=1.3))
        self.assertTrue(warn)
        self.assertIn("does not clearly line up", text)
        self.assertIn("not a held-out result", text)       # a refit on the same captures is never presented as validation
        self.assertIn("not that the calibration is aligned", text)
        text, warn = rv.alignment_note(dict(lift=1.7, share=.17, min_lift=1.3))
        self.assertFalse(warn)
        self.assertIn("lines up", text)
        self.assertIsNone(rv.alignment_note(None))

    def test_review_files_are_read_and_missing_ones_are_tolerated(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            self.assertIsNone(rv.review_alignment(folder))
            self.assertEqual(rv.review_options(folder), {})
            run = Path(folder) / "review" / "run"
            run.mkdir(parents=True)
            (run / "summary.json").write_text(json.dumps(
                {"existing_on_new_data": {"lift": 1.01, "on_edge_share": .065, "matches": 1470},
                 "refined_on_new_data": {"lift": 1.24}}), encoding="utf-8")
            (run / "option_calibrations.json").write_text(json.dumps(
                {"calibrations": {"extrinsic": CAL, "full": {"broken": True}}}), encoding="utf-8")
            a = rv.review_alignment(folder)
            self.assertAlmostEqual(a["lift"], 1.01)
            self.assertGreaterEqual(a["min_lift"], 1.0)
            self.assertEqual(list(rv.review_options(folder)), ["extrinsic"])   # the malformed option is skipped

    def test_sparse_points_leave_the_photo_visible_and_dense_mode_still_works(self):
        from PyQt5 import QtWidgets
        global _APP
        _APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])   # must stay referenced or Qt aborts
        rng = np.random.default_rng(0)
        P = np.c_[rng.uniform(3, 9, 40000), rng.uniform(-1, 1, 40000), rng.uniform(-1, 1, 40000)]
        canvas = rv.OverlayCanvas()
        a = rv.cal_arrays(CAL)
        canvas.set_scene(np.zeros((366, 484, 3), np.uint8), P, a, a, dict(cx=241.5, cy=182.5, radius=183.))
        sparse = int((canvas._buf[..., 3] > 0).sum())
        shown = int(canvas.state[2].sum())
        self.assertLessEqual(shown, canvas.max_points)
        canvas.set_density(60000)
        dense = int((canvas._buf[..., 3] > 0).sum())
        self.assertGreater(dense, sparse * 2)
        self.assertEqual(float(canvas.moved_stats()[0]), 0.0)    # same calibration at both ends: nothing moves


if __name__ == "__main__":
    unittest.main()


class EmptyAndOddCaptures(unittest.TestCase):
    """The overlay card must survive captures it cannot draw."""

    def card_for(self, xyz):
        import tempfile
        from PyQt5 import QtWidgets
        global _APP
        _APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        folder = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(folder, ignore_errors=True))
        path = Path(folder) / "capture_20260101_000000_000001_x.npz"
        np.savez(path, image=np.zeros((366, 484, 3), np.uint8), xyz_mm=xyz)
        card = rv.OverlayCard([path], CAL, CAL, dict(cx=241.5, cy=182.5, radius=183.), False, {}, None)
        self.addCleanup(card.deleteLater)
        return card

    def test_a_capture_without_lidar_points_is_explained_not_a_crash(self):
        card = self.card_for(np.zeros((0, 3), np.int16))
        self.assertIn("no usable LiDAR points", card.summary.text())
        card.slider.setValue(50)                      # moving the slider afterwards must also be harmless
        card.canvas.update()

    def test_a_single_point_or_nonfinite_points_are_also_refused_gracefully(self):
        self.assertIn("no usable LiDAR points", self.card_for(np.array([[1000, 0, 0]], np.int16)).summary.text())

    def test_a_normal_capture_still_draws(self):
        rng = np.random.default_rng(0)
        xyz = np.c_[rng.uniform(3000, 9000, 500), rng.uniform(-1000, 1000, 500), rng.uniform(-1000, 1000, 500)].astype(np.int16)
        card = self.card_for(xyz)
        self.assertIsNotNone(card.canvas.P)
        self.assertIn("Size of this change", card.summary.text())
