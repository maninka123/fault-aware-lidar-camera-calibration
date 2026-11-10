"""Numerical frame fixtures (mandatory verification B)."""
import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from simulator.geometry import R_LC, T_CB, apply, default_extrinsic, inverse, pose, transform, validate_transform


def test_se3_inverse_and_point_round_trip():
    rng = np.random.default_rng(2026)
    points = rng.uniform(-100, 100, (500, 3))
    for _ in range(20):
        T = transform(Rotation.random(random_state=rng).as_matrix(), rng.uniform(-4, 4, 3))
        np.testing.assert_allclose(inverse(T) @ T, np.eye(4), atol=3e-15)
        np.testing.assert_allclose(apply(inverse(T), apply(T, points)), points, atol=1e-12)


def test_camera_lidar_and_blender_frames_are_right_handed():
    # Explicit axis fixtures prevent a pair of matching but wrong inverses from
    # passing the round-trip test.
    np.testing.assert_array_equal(R_LC @ [1, 0, 0], [0, -1, 0])
    np.testing.assert_array_equal(R_LC @ [0, 1, 0], [0, 0, -1])
    np.testing.assert_array_equal(R_LC @ [0, 0, 1], [1, 0, 0])
    np.testing.assert_array_equal(apply(T_CB, [[1, 2, -3]]), [[1, -2, 3]])
    assert np.linalg.det(R_LC) == 1
    assert np.linalg.det(T_CB[:3, :3]) == 1
    np.testing.assert_array_equal(np.cross(R_LC[:, 0], R_LC[:, 1]), R_LC[:, 2])
    np.testing.assert_array_equal(T_CB @ T_CB, np.eye(4))


def test_default_extrinsic_maps_camera_origin_and_forward_axis():
    baseline = np.array([.05, -.15, .03])
    T_CL = default_extrinsic(baseline)
    np.testing.assert_allclose(apply(T_CL, baseline[None, :]), [[0, 0, 0]], atol=1e-15)
    np.testing.assert_allclose(apply(T_CL, [baseline + [5, 0, 0]]), [[0, 0, 5]], atol=1e-15)
    # Camera right is -L.y, camera down is -L.z.
    np.testing.assert_allclose(apply(T_CL, [baseline + [5, -1, -2]]), [[1, 2, 5]], atol=1e-15)


def test_pose_yaw_and_translation_known_fixture():
    np.testing.assert_allclose(apply(pose([1, 2, 3], [0, 0, 90]), [[1, 0, 0]]), [[1, 3, 3]], atol=1e-14)


@pytest.mark.parametrize("bad", [np.eye(3), np.full((4, 4), np.nan), np.full((4, 4), np.inf),
    np.diag([-1, 1, 1, 1]), np.diag([2, 1, 1, 1]), np.diag([1, 1, 1, 2])])
def test_invalid_transform_rejected(bad):
    with pytest.raises(ValueError):
        validate_transform(bad)


def test_transform_translation_nonfinite_rejected():
    with pytest.raises(ValueError):
        transform(translation=[0, np.nan, 0])
