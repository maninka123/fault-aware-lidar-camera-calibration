"""Deterministic calibration perturbations; initialization and physical drift stay separate."""
from copy import deepcopy
import numpy as np
from scipy.spatial.transform import Rotation
from .camera import Camera
from .geometry import transform, validate_transform


def perturb(T_CL, camera, fault):
    """Left rotation in C around L origin, plus translation in C, independent magnitudes."""
    allowed = {"rotation_deg", "translation_m", "focal_scale", "principal_offset_px", "distortion_delta"}
    if set(fault) - allowed:
        raise ValueError(f"Unsupported fault keys: {set(fault)-allowed}")
    T = validate_transform(T_CL).copy()
    r = np.asarray(fault.get("rotation_deg", [0., 0., 0.]), float)
    t = np.asarray(fault.get("translation_m", [0., 0., 0.]), float)
    if r.shape != (3,) or t.shape != (3,) or not np.isfinite(r).all() or not np.isfinite(t).all():
        raise ValueError("Fault rotation_deg and translation_m require three finite components")
    T[:3, :3] = Rotation.from_euler("xyz", r, degrees=True).as_matrix() @ T[:3, :3]
    T[:3, 3] += t
    c = deepcopy(camera.to_dict())
    K, D = np.array(c["K"]), np.array(c["D"])
    scale = np.broadcast_to(np.asarray(fault.get("focal_scale", 1.), float), (2,))
    offset = np.broadcast_to(np.asarray(fault.get("principal_offset_px", [0., 0.]), float), (2,))
    delta = np.asarray(fault.get("distortion_delta", np.zeros(len(D))), float)
    if delta.shape != D.shape:
        raise ValueError("distortion_delta must match the camera D length")
    K[0, 0] *= scale[0]
    K[1, 1] *= scale[1]
    K[:2, 2] += offset
    c.update(K=K.tolist(), D=(D+delta).tolist())
    return validate_transform(T), Camera.from_dict(c)


def calibration_dict(T_CL, camera):
    """Optimizer layout; retain explicit projection model to forbid silent model changes."""
    return dict(image_size=[camera.width, camera.height],
                intrinsics=dict(model="opencv_fisheye" if camera.model == "fisheye" else "pinhole",
                distortion_model="opencv_fisheye" if camera.model == "fisheye" else "plumb_bob",
                camera_matrix=camera.K.tolist(), distortion_coefficients=camera.D.tolist(),
                image_size=[camera.width, camera.height]),
                extrinsics=dict(transform_lidar_to_camera=validate_transform(T_CL).tolist(), translation_units="m"))
