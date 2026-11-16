"""Versioned adapter for future exact-correspondence simulator exports.

No simulator is implemented. Only declared OpenCV-fisheye captures are accepted.
Unknown LiDAR profiles remain provenance labels, not fabricated beam models.
"""
import hashlib
import json
from pathlib import Path
import numpy as np
from ..legacy_adapter import read_calibration
from ..geometry import ProjectionModel, parameters
from ..parameter_hypotheses import parameter_scales
from .geometry_signatures import projection_jacobian


def load_signature_dataset(manifest_path, *, expected_role, declared_ids=None):
    """Load hash-checked xyz/uv NPZ captures with recording-level split metadata.

    Calibration translations are always metres; ``point_units`` controls only
    the LiDAR point arrays. NPZ arrays never enable pickle deserialization.
    Returns fixed known-correspondence signatures, not an edge-feature bundle.
    """
    path = Path(manifest_path).resolve()
    manifest = json.loads(path.read_text(encoding='utf-8'))
    if manifest.get('schema_version') != 'fault-signatures-v3/1':
        raise ValueError('Unsupported simulator manifest schema')
    if expected_role not in ('development', 'calibration', 'test') or manifest.get('role') != expected_role:
        raise ValueError('Explicit matching development/calibration/test role required')
    if declared_ids is not None and manifest.get('recording_id') not in set(declared_ids):
        raise ValueError('Recording not in predeclared split')
    if manifest.get('pose_convention') != 'T_camera_from_lidar' or manifest.get('calibration_translation_units') != 'm':
        raise ValueError('Declare T_camera_from_lidar with calibration translations in metres')
    unit = manifest.get('point_units')
    if unit not in ('m', 'mm'):
        raise ValueError('Declare point units as m or mm')
    if manifest.get('projection') != 'opencv_fisheye':
        raise ValueError('Only the implemented OpenCV fisheye projection is supported')
    cal = read_calibration(manifest['calibration_under_test'])
    size = manifest['image_size']; circle = dict(cx=(size[0]-1)/2, cy=(size[1]-1)/2, radius=min(size)/2)
    model = ProjectionModel(cal, size, circle, manifest.get('max_angle_rad', 1.))
    p = parameters(cal)
    rows, signals, variances, ids = [], [], [], []
    capture_ids = set()
    if not manifest.get('captures'):
        raise ValueError('At least one capture required')
    for capture in manifest['captures']:
        name = capture['id']
        if name in capture_ids:
            raise ValueError('Duplicate capture ID')
        capture_ids.add(name)
        data = (path.parent/capture['file']).resolve()
        if not data.is_relative_to(path.parent):
            raise ValueError('Capture path must remain inside dataset folder')
        if hashlib.sha256(data.read_bytes()).hexdigest() != capture['sha256']:
            raise ValueError('Capture content hash mismatch')
        with np.load(data, allow_pickle=False) as arrays:
            xyz = np.asarray(arrays['xyz'], float)*(1. if unit == 'm' else .001)
            target = np.asarray(arrays['uv'], float)
            signs = np.asarray(arrays['signs'], float) if 'signs' in arrays else np.zeros(len(xyz))
            visible = np.asarray(arrays['visible'], bool) if 'visible' in arrays else np.ones(len(xyz), bool)
            sigma = np.asarray(arrays['sigma_px'], float) if 'sigma_px' in arrays else np.ones((len(xyz), 2))
        uv, j, ok = projection_jacobian(model, p, xyz, signs)
        if target.shape != uv.shape or sigma.shape != uv.shape or visible.shape != (len(xyz),):
            raise ValueError('Expected uv/sigma_px (N,2) and visible (N,) arrays')
        ok &= visible & np.isfinite(target).all(axis=1) & np.isfinite(sigma).all(axis=1) & (sigma > 0).all(axis=1)
        rows.append(j[ok].reshape(-1, 13)); signals.append((target[ok]-uv[ok]).ravel())
        variances.append(sigma[ok].ravel()**2); ids.extend([name]*int(2*ok.sum()))
    return dict(jacobian=np.vstack(rows), residual_change=np.concatenate(signals),
                covariance=np.concatenate(variances), capture_ids=np.asarray(ids), scales=parameter_scales(p),
                provenance=manifest, scope='Exact supplied correspondences; not automatic image/LiDAR edge matching.')
