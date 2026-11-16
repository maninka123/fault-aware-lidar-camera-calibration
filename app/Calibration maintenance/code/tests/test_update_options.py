"""Decision and geometry checks for choosing which calibration values to update."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import appcore  # sets numerical-library thread limits before numpy is imported
import numpy as np
from scipy.spatial.transform import Rotation

from pose_view import camera_pose
from update_options import (constrained_start, edge_distance_error, error_changes, error_readout,
                            edge_distance_metrics, free_parameters, recommend, rmse_changes, valid_solution)


def folds(existing=0.25, extrinsic=0.35, intrinsic=0.26, full=0.354, count=5):
    return [dict(scores={mode: dict(on_edge_share=value) for mode, value in
                         zip(('existing', 'extrinsic', 'intrinsic', 'full'),
                             (existing, extrinsic, intrinsic, full))}) for _ in range(count)]


class UpdateDecisionTests(unittest.TestCase):
    def test_rmse_pools_squared_distances_instead_of_averaging_fold_rmse(self):
        checks = []
        for count, before, after in [(2, 5., 2.), (8, 2., 1.)]:
            scores = {mode: dict(edge_test_points=count,
                                 edge_squared_error_sum=count * (before if mode == 'existing' else after) ** 2)
                      for mode in ('existing', 'extrinsic', 'intrinsic', 'full')}
            checks.append(dict(scores=scores))
        error = rmse_changes(dict(checks=checks))['extrinsic']
        self.assertAlmostEqual(error['before_px'], np.sqrt(8.2))
        self.assertAlmostEqual(error['after_px'], np.sqrt(1.6))
        self.assertEqual(error['points'], 10)
        self.assertAlmostEqual(error['reduction_percent'], (1 - np.sqrt(1.6 / 8.2)) * 100)

    def test_rmse_requires_real_comparable_measurements(self):
        self.assertEqual(rmse_changes(dict(checks=folds())), {})
        scores = {mode: dict(edge_test_points=2, edge_squared_error_sum=0.)
                  for mode in ('existing', 'extrinsic', 'intrinsic', 'full')}
        self.assertIsNone(rmse_changes(dict(checks=[dict(scores=scores)]))['full']['reduction_percent'])
        scores['full']['edge_test_points'] = 3
        self.assertEqual(rmse_changes(dict(checks=[dict(scores=scores)])), {})

    def test_pixel_error_reduction_uses_measured_errors_instead_of_match_scores(self):
        checks = folds(count=3)
        for check in checks:
            for mode, value in zip(('existing', 'extrinsic', 'intrinsic', 'full'), (18.7, 12.4, 20., 10.)):
                check['scores'][mode]['median_edge_distance_px'] = value
        changes = error_changes(dict(checks=checks))
        alignment = changes['extrinsic']
        self.assertAlmostEqual(alignment['reduction_px'], 6.3)
        self.assertAlmostEqual(alignment['reduction_percent'], 6.3 / 18.7 * 100)
        heading, detail = error_readout(alignment, 'extrinsic')
        self.assertIn('18.7 → 12.4 px', heading)
        self.assertIn('33.7% less error', detail)
        self.assertIn('6.3 px less', detail)
        self.assertIn('more error', error_readout(changes['intrinsic'], 'intrinsic')[1])

    def test_older_errors_are_labelled_and_nonfinite_folds_are_excluded_for_all_options(self):
        checks = folds(count=3)
        for check in checks:
            for mode, value in zip(('existing', 'extrinsic', 'intrinsic', 'full'), (.8, .6, .7, .5)):
                check['scores'][mode]['median_residual_px'] = value
        checks[0]['scores']['full']['median_residual_px'] = float('inf')
        changes = error_changes(dict(checks=checks))
        self.assertEqual(changes['existing']['checks'], 2)
        self.assertEqual(changes['extrinsic']['scope'], 'Matched edges only')
        self.assertIn('Matched-edge error', error_readout(changes['extrinsic'], 'extrinsic')[0])
        self.assertAlmostEqual(changes['extrinsic']['reduction_percent'], 25.)

    def test_zero_baseline_and_missing_pixel_errors_are_not_invented(self):
        self.assertEqual(error_changes(dict(checks=folds())), {})
        self.assertIn('unavailable', error_readout(None, 'extrinsic')[0])
        checks = folds(count=1)
        for score in checks[0]['scores'].values():
            score['median_edge_distance_px'] = 0.
        changes = error_changes(dict(checks=checks))
        self.assertIsNone(changes['extrinsic']['reduction_percent'])
        self.assertEqual(error_readout(changes['extrinsic'], 'extrinsic')[1], 'No measured error change')
        checks[0]['scores']['extrinsic']['median_edge_distance_px'] = 1.
        change = error_changes(dict(checks=checks))['extrinsic']
        self.assertIn('percentage unavailable', error_readout(change, 'extrinsic')[1])

    def test_edge_distance_includes_points_outside_the_match_gate(self):
        capture = SimpleNamespace(xyz=np.array([[0., 0., 1.], [10., 0., 1.], [20., 0., 1.]]),
                                  sgn=np.zeros(3), img=dict(q=np.array([[0., 0.]])))
        model = SimpleNamespace(to_camera=lambda xyz, sgn, p: xyz,
                                project=lambda camera, p: (camera[:, 0], camera[:, 1], np.ones(len(camera), dtype=bool)))
        self.assertEqual(edge_distance_error([capture], model, None), 10.)
        metrics = edge_distance_metrics([capture], model, None)
        self.assertAlmostEqual(metrics['edge_rmse_px'], np.sqrt(500 / 3))
        self.assertEqual(metrics['edge_test_points'], 3)

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
