import json
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
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


if __name__ == "__main__":
    unittest.main()
