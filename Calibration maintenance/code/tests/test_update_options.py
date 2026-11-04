"""Decision and geometry checks for choosing which calibration values to update."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import appcore  # sets numerical-library thread limits before numpy is imported
import numpy as np
from scipy.spatial.transform import Rotation

from pose_view import camera_pose
from update_options import constrained_start, free_parameters, recommend, valid_solution


def folds(existing=0.25, extrinsic=0.35, intrinsic=0.26, full=0.354, count=5):
    return [dict(scores={mode: dict(on_edge_share=value) for mode, value in
                         zip(('existing', 'extrinsic', 'intrinsic', 'full'),
                             (existing, extrinsic, intrinsic, full))}) for _ in range(count)]


class UpdateDecisionTests(unittest.TestCase):
    def test_extra_parameters_need_a_clear_advantage(self):
        self.assertEqual(recommend(folds())['selected'], 'extrinsic')

    def test_camera_only_can_win_without_moving_alignment(self):
        self.assertEqual(recommend(folds(extrinsic=0.26, intrinsic=0.40, full=0.405))['selected'], 'intrinsic')

    def test_both_must_beat_both_simpler_options(self):
        self.assertEqual(recommend(folds(extrinsic=0.35, intrinsic=0.36, full=0.45))['selected'], 'full')

    def test_joint_fit_does_not_win_on_training_fit_alone(self):
        result = recommend(folds(extrinsic=0.35, intrinsic=0.26, full=0.28))
        self.assertEqual(result['selected'], 'extrinsic')

    def test_tiny_gains_keep_current_calibration(self):
        result = recommend(folds(extrinsic=0.253, intrinsic=0.252, full=0.256))
        self.assertEqual(result['status'], 'keep')
        self.assertIsNone(result['selected'])

    def test_inconsistent_gain_is_not_enough(self):
        checks = folds(existing=0.30, extrinsic=0.30, intrinsic=0.30, full=0.30)
        checks[0]['scores']['full']['on_edge_share'] = 0.95
        result = recommend(checks)
        self.assertNotEqual(result['selected'], 'full')

    def test_insufficient_or_nonfinite_evidence(self):
        self.assertEqual(recommend(folds(count=2))['status'], 'inconclusive')
        checks = folds(count=3)
        checks[0]['scores']['full']['on_edge_share'] = float('nan')
        self.assertEqual(recommend(checks)['status'], 'inconclusive')

    def test_constrained_starts_preserve_the_unchanged_group(self):
        original = np.arange(13, dtype=float)
        proposed = original + 100
        np.testing.assert_array_equal(constrained_start(proposed, original, 'extrinsic')[6:12], original[6:12])
        np.testing.assert_array_equal(constrained_start(proposed, original, 'intrinsic')[:6], original[:6])
        np.testing.assert_array_equal(proposed, original + 100)
        self.assertFalse(set(free_parameters('extrinsic', 'k1-k2')) & set(range(6, 12)))
        self.assertFalse(set(free_parameters('intrinsic', 'k1-k2')) & set(range(6)))

    def test_camera_position_uses_inverse_extrinsics(self):
        matrix = np.eye(4)
        matrix[:3, :3] = Rotation.from_euler('xyz', [12, -6, 30], degrees=True).as_matrix()
        matrix[:3, 3] = [0.05, -0.02, 0.08]
        centre, axes = camera_pose(matrix)
        np.testing.assert_allclose(matrix[:3, :3] @ centre + matrix[:3, 3], 0, atol=1e-14)
        np.testing.assert_allclose(matrix[:3, :3] @ axes, np.eye(3), atol=1e-14)

    def test_invalid_lens_fit_cannot_be_recommended(self):
        parameters = np.zeros(13)
        parameters[6:8] = 230
        self.assertTrue(valid_solution(parameters))
        parameters[6] = -230
        self.assertFalse(valid_solution(parameters))
        parameters[6] = 230
        parameters[10] = -1
        self.assertFalse(valid_solution(parameters))


if __name__ == '__main__':
    unittest.main()
