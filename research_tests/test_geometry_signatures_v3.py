"""Known-answer numerical geometry fixtures; no physical sensor validation."""
import copy
import unittest
import numpy as np
from scipy.spatial.transform import Rotation
from research_calibration.geometry import ProjectionModel, parameters, retract
from research_calibration.parameter_hypotheses import parameter_scales
from research_calibration.residuals import AssociationBatch
from research_calibration.fault_diagnostics_v3.geometry_signatures import projection_jacobian, residual_signature


def fixture():
    transform = np.eye(4)
    transform[:3, :3] = Rotation.from_rotvec([.05, -.03, .02]).as_matrix()
    transform[:3, 3] = [.02, -.01, .03]
    reference = dict(image_size=[640, 480], intrinsics=dict(
        camera_matrix=[[260., 0., 320.], [0., 250., 240.], [0., 0., 1.]],
        distortion_coefficients=[.03, -.015, .01, -.005]),
        extrinsics=dict(transform_lidar_to_camera=transform.tolist()))
    model = ProjectionModel(reference, [640, 480], dict(cx=320, cy=240, radius=235), max_angle_rad=1.2)
    return reference, model, parameters(reference)


class GeometrySignatureV3Tests(unittest.TestCase):
    def test_all_analytic_columns_against_independent_central_differences(self):
        _, model, p = fixture()
        p[:3], p[12] = [.06, -.08, .04], .009
        rng = np.random.default_rng(21)
        xyz = np.column_stack((rng.uniform(-1.1, 1.1, 30), rng.uniform(-.8, .8, 30), rng.uniform(2., 5., 30)))
        signs = rng.choice([-1., 0., 1.], len(xyz))
        uv, analytic, valid = projection_jacobian(model, p, xyz, signs)
        self.assertTrue(valid.all())
        def project(q):
            u, v, _ = model.project(model.to_camera(xyz, signs, q), q)
            return np.column_stack((u, v))
        np.testing.assert_allclose(uv, project(p), atol=1e-12)
        numeric = np.empty_like(analytic)
        steps = np.array([1e-6]*3 + [1e-5]*3 + [1e-3]*4 + [1e-6]*3)
        for column, step in enumerate(steps):
            delta = np.zeros(13)
            delta[column] = step
            numeric[:, :, column] = (project(retract(p, delta)) - project(retract(p, -delta)))/(2*step)
        np.testing.assert_allclose(analytic, numeric, atol=9e-8, rtol=2e-6)

    def test_left_rotation_does_not_rotate_translation(self):
        reference, _, _ = fixture()
        reference['extrinsics']['transform_lidar_to_camera'] = np.eye(4).tolist()
        model = ProjectionModel(reference, [640, 480], dict(cx=320, cy=240, radius=235))
        p = parameters(reference)
        p[3:6] = [.1, -.2, .3]
        _, jacobian, valid = projection_jacobian(model, p, np.array([[0., 0., 2.]]), np.zeros(1))
        self.assertTrue(valid[0])
        # Rotation about z of a point on the LiDAR/camera z-axis is zero even
        # though the additive translation has nonzero x/y components.
        np.testing.assert_allclose(jacobian[0, :, 2], 0., atol=1e-13)

    def test_wide_angle_derivatives_with_different_intrinsics(self):
        for focal, coefficients in [(220., [0., 0., 0., 0.]),
                                     (285., [-.03, .02, -.01, .004])]:
            with self.subTest(focal=focal):
                reference = dict(image_size=[1024, 1024], intrinsics=dict(
                    camera_matrix=[[focal, 0., 505.], [0., focal*.91, 518.], [0., 0., 1.]],
                    distortion_coefficients=coefficients),
                    extrinsics=dict(transform_lidar_to_camera=np.eye(4).tolist()))
                model = ProjectionModel(reference, [1024, 1024], dict(cx=512, cy=512, radius=505), max_angle_rad=1.3)
                p = parameters(reference)
                xyz = np.array([[2., 1., 1.2], [-1.8, -.8, 1.1], [1., -1.4, 1.]])
                signs = np.array([1., -1., 0.])
                _, analytic, valid = projection_jacobian(model, p, xyz, signs)
                self.assertTrue(valid.all())
                for column in range(13):
                    step = 1e-5 if column < 6 or column > 9 else 1e-3
                    delta = np.zeros(13)
                    delta[column] = step
                    values = []
                    for direction in (1., -1.):
                        candidate = retract(p, direction*delta)
                        u, v, visible = model.project(model.to_camera(xyz, signs, candidate), candidate)
                        self.assertTrue(visible.all())
                        values.append(np.column_stack((u, v)))
                    np.testing.assert_allclose(analytic[:, :, column], (values[0]-values[1])/(2*step),
                                               atol=1e-7, rtol=1e-6)

    def test_optical_axis_limit_and_fixed_higher_order_distortion(self):
        reference, _, _ = fixture()
        reference['extrinsics']['transform_lidar_to_camera'] = np.eye(4).tolist()
        model = ProjectionModel(reference, [640, 480], dict(cx=320, cy=240, radius=235))
        p = parameters(reference)
        _, jacobian, valid = projection_jacobian(model, p, np.array([[0., 0., 2.]]), np.zeros(1))
        self.assertTrue(valid[0])
        np.testing.assert_allclose(jacobian[0, :, 3:6], [[130, 0, 0], [0, 125, 0]], atol=1e-12)
        np.testing.assert_allclose(jacobian[0, :, :3], [[0, 260, 0], [-250, 0, 0]], atol=1e-12)
        np.testing.assert_allclose(jacobian[0, :, 10:12], 0., atol=1e-12)
        xyz = np.array([[.4, .3, 2.]])
        first = projection_jacobian(model, p, xyz, np.zeros(1))[1]
        other = copy.deepcopy(reference)
        other['intrinsics']['distortion_coefficients'][2:] = [.4, -.3]
        alternate = ProjectionModel(other, [640, 480], dict(cx=320, cy=240, radius=235))
        second = projection_jacobian(alternate, p, xyz, np.zeros(1))[1]
        self.assertGreater(np.linalg.norm(first[:, :, :6] - second[:, :, :6]), 1e-4)

    def test_near_axis_series_is_finite_and_continuous(self):
        reference, _, _ = fixture()
        reference['extrinsics']['transform_lidar_to_camera'] = np.eye(4).tolist()
        model = ProjectionModel(reference, [640, 480], dict(cx=320, cy=240, radius=235))
        p = parameters(reference)
        xyz = np.array([[r, r/2, 2.] for r in [0., 1e-14, 1e-8, 1e-5, 1e-4, 1e-3]])
        _, jacobian, valid = projection_jacobian(model, p, xyz, np.zeros(len(xyz)))
        self.assertTrue(valid.all())
        self.assertTrue(np.isfinite(jacobian).all())
        np.testing.assert_allclose(jacobian[:4, :, :6], np.broadcast_to(jacobian[0, :, :6], (4, 2, 6)), atol=.002)

    def test_depth_conditioning_rotation_intrinsics_and_translation(self):
        reference, _, _ = fixture()
        reference['extrinsics']['transform_lidar_to_camera'] = np.eye(4).tolist()
        model = ProjectionModel(reference, [640, 480], dict(cx=320, cy=240, radius=235))
        p = parameters(reference)
        ray = np.array([.2, -.3, 1.])
        xyz = np.array([2*ray, 8*ray])
        _, jacobian, valid = projection_jacobian(model, p, xyz, np.zeros(2))
        self.assertTrue(valid.all())
        np.testing.assert_allclose(jacobian[0, :, :3], jacobian[1, :, :3], atol=1e-11)
        np.testing.assert_allclose(jacobian[0, :, 6:12], jacobian[1, :, 6:12], atol=1e-11)
        np.testing.assert_allclose(jacobian[0, :, 3:6], 4*jacobian[1, :, 3:6], atol=1e-11)

    def test_unit_and_lidar_coordinate_transform_invariance(self):
        reference, model, p = fixture()
        xyz = np.array([[.2, -.3, 2.], [.1, .5, 3.]])
        signs = np.zeros(2)
        uv, jacobian, valid = projection_jacobian(model, p, xyz, signs)
        scaled_p = p.copy()
        scaled_p[3:6] *= 1000
        uv_mm, jacobian_mm, valid_mm = projection_jacobian(model, scaled_p, xyz*1000, signs)
        scale = parameter_scales(p)
        scale_mm = scale.copy()
        scale_mm[3:6] *= 1000
        np.testing.assert_allclose(uv, uv_mm, atol=1e-12)
        np.testing.assert_array_equal(valid, valid_mm)
        np.testing.assert_allclose(jacobian*scale, jacobian_mm*scale_mm, atol=1e-12)
        basis_change = Rotation.from_rotvec([.2, -.1, .3]).as_matrix()
        altered = copy.deepcopy(reference)
        transform = np.array(reference['extrinsics']['transform_lidar_to_camera'])
        transform[:3, :3] = transform[:3, :3]@basis_change.T
        altered['extrinsics']['transform_lidar_to_camera'] = transform.tolist()
        other_model = ProjectionModel(altered, [640, 480], model.circle)
        other_uv, other_j, other_valid = projection_jacobian(other_model, p, xyz@basis_change.T, signs)
        np.testing.assert_allclose(uv, other_uv, atol=1e-12)
        np.testing.assert_allclose(jacobian, other_j, atol=1e-11)
        np.testing.assert_array_equal(valid, other_valid)

    def test_missing_invalid_and_outside_returns_have_mask_and_zero_rows(self):
        _, model, p = fixture()
        xyz = np.array([[0., 0., 0.], [np.nan, 0., 2.], [0., np.inf, 2.], [0., 0., -1.], [50., 0., 1.], [.1, .2, 2.]])
        uv, jacobian, valid = projection_jacobian(model, p, xyz, np.zeros(len(xyz)))
        np.testing.assert_array_equal(valid, [False]*5 + [True])
        np.testing.assert_allclose(uv[~valid], 0.)
        np.testing.assert_allclose(jacobian[~valid], 0.)
        empty = projection_jacobian(model, p, np.empty((0, 3)), np.empty(0))
        self.assertEqual(empty[1].shape, (0, 2, 13))
        with self.assertRaises(ValueError):
            projection_jacobian(model, p, xyz, np.zeros(1))

    def test_frozen_residual_signature_and_explicit_weighting(self):
        _, model, p = fixture()
        xyz = np.array([[.2, -.3, 2.], [.1, .5, 3.]])
        signs = np.array([1., -1.])
        uv, derivative, _ = projection_jacobian(model, p, xyz, signs)
        normals = np.array([[1., 0.], [.6, .8]])
        batch = AssociationBatch(xyz, signs, uv - np.array([[.3, 0.], [.6, .8]]), normals, np.array([.2, .8]), np.zeros(2), 6.)
        result = residual_signature(batch, model, p)
        np.testing.assert_allclose(result['residuals'], [.3, 1.], atol=1e-12)
        np.testing.assert_allclose(result['jacobian'], np.einsum('ni,nij->nj', normals, derivative), atol=1e-12)
        scaled = residual_signature(batch, model, p, scales=parameter_scales(p), weighted=True)
        np.testing.assert_allclose(scaled['residuals'], result['residuals']*batch.weights, atol=1e-12)
        np.testing.assert_allclose(scaled['jacobian'], result['jacobian']*parameter_scales(p)*batch.weights[:, None], atol=1e-12)

    def test_residual_invalid_normals_are_explicitly_excluded(self):
        _, model, p = fixture()
        xyz = np.array([[.2, -.3, 2.], [.1, .5, 3.], [-.2, .3, 4.]])
        batch = AssociationBatch(xyz, np.zeros(3), np.ones((3, 2)),
                                 np.array([[np.nan, 0.], [0., 0.], [1., 0.]]),
                                 np.ones(3), np.zeros(3), 6.)
        result = residual_signature(batch, model, p)
        np.testing.assert_array_equal(result['valid'], [False, False, True])
        np.testing.assert_allclose(result['jacobian'][:2], 0.)
        np.testing.assert_allclose(result['residuals'][:2], 0.)

    def test_equidistant_great_circle_yaw_alias_needs_two_dimensional_coverage(self):
        reference, _, _ = fixture()
        reference['extrinsics']['transform_lidar_to_camera'] = np.eye(4).tolist()
        reference['intrinsics']['distortion_coefficients'] = [0., 0., 0., 0.]
        model = ProjectionModel(reference, [640, 480], dict(cx=320, cy=240, radius=235), max_angle_rad=1.2)
        p = parameters(reference)
        points = np.column_stack((np.linspace(-1.5, 1.5, 20), np.zeros(20), np.full(20, 2.)))
        _, j, valid = projection_jacobian(model, p, points, np.zeros(len(points)))
        self.assertTrue(valid.all())
        np.testing.assert_allclose(j[:, :, 1], p[6]*j[:, :, 8], atol=1e-11)
        points[:, 1] = np.linspace(-1.2, 1.2, len(points))
        _, j2, valid2 = projection_jacobian(model, p, points, np.zeros(len(points)))
        self.assertTrue(valid2.all())
        yaw, principal_point = j2[:, :, 1].ravel(), j2[:, :, 8].ravel()
        fitted = principal_point*(principal_point@yaw)/(principal_point@principal_point)
        self.assertGreater(np.linalg.norm(yaw - fitted)/np.linalg.norm(yaw), .03)


if __name__ == '__main__':
    unittest.main()
