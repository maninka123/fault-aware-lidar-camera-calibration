"""Column-vector SE(3): T_AB maps B coordinates into A. All lengths are metres."""
import numpy as np
from scipy.spatial.transform import Rotation

# C right/down/forward -> L forward/left/up. Blender camera B right/up/back.
R_LC = np.array([[0., 0., 1.], [-1., 0., 0.], [0., -1., 0.]])
T_CB = np.diag([1., -1., -1., 1.])


def validate_transform(T):
    T = np.asarray(T, dtype=float)
    if T.shape != (4, 4) or not np.isfinite(T).all():
        raise ValueError("Transform must be a finite 4x4 matrix")
    if not np.allclose(T[3], [0, 0, 0, 1], atol=1e-9, rtol=0):
        raise ValueError("Invalid homogeneous transform bottom row")
    R = T[:3, :3]
    if not np.allclose(R.T @ R, np.eye(3), atol=1e-7, rtol=0) or not np.isclose(np.linalg.det(R), 1, atol=1e-7, rtol=0):
        raise ValueError("Transform rotation must be proper orthonormal (det=+1)")
    return T


def transform(rotation=None, translation=(0, 0, 0)):
    T = np.eye(4)
    T[:3, :3] = np.eye(3) if rotation is None else rotation
    T[:3, 3] = translation
    return validate_transform(T)


def pose(xyz=(0, 0, 1.6), rpy_deg=(0, 0, 0)):
    return transform(Rotation.from_euler("xyz", rpy_deg, degrees=True).as_matrix(), xyz)


def inverse(T):
    T = validate_transform(T)
    return transform(T[:3, :3].T, -T[:3, :3].T @ T[:3, 3])


def apply(T, points):
    T = validate_transform(T)
    p = np.asarray(points, dtype=float)
    return p @ T[:3, :3].T + T[:3, 3]


def default_extrinsic(baseline_l=(0.05, -0.15, 0.03)):
    """Camera origin expressed in L. Returns T_CL, NOT camera world pose."""
    return inverse(transform(R_LC, baseline_l))


def camera_extrinsic(camera_xyz_in_lidar=(0.05, -0.15, 0.03), rpy_deg=(0, 0, 0)):
    """T_CL for a camera mounted at ``camera_xyz_in_lidar`` (metres, LiDAR frame x fwd, y left, z up).

    ``rpy_deg`` rotates the camera relative to the default forward-looking mounting, with
    roll/pitch/yaw taken about the LiDAR x/y/z axes (positive yaw turns the camera left).
    Zero rotation reproduces ``default_extrinsic``.
    """
    R_offset = Rotation.from_euler("xyz", rpy_deg, degrees=True).as_matrix()
    return inverse(transform(R_offset @ R_LC, camera_xyz_in_lidar))
