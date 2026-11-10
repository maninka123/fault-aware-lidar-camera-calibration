"""Reload generated outputs and compute independent geometric checks."""
from pathlib import Path
import cv2
import numpy as np
import open3d as o3d
from .camera import Camera
from .geometry import apply, inverse, validate_transform
from .io import capture_dir, json_read, sha256


def verify_run(run, check_hashes=True):
    try:
        return _verify_run(run, check_hashes)
    except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
        return dict(passed=False, errors=[f"Incomplete or invalid dataset: {type(error).__name__}: {error}"],
                    captures=[], file_hashes_checked=False)


def _verify_run(run, check_hashes=True):
    run = Path(run)
    sequence = json_read(run/"inference"/"sequence.json")
    truth = {v["capture_id"]: v for v in json_read(run/"evaluation"/"ground_truth.json")}
    errors, captures = [], []
    for c in sequence:
        name = c["capture_id"]
        folder = run/"inference"/c["path"]
        t = truth[name]
        cam = Camera.from_dict(t["camera"])
        image = cv2.imread(str(folder/"image.png"))
        if image is None or image.shape != (cam.height, cam.width, 3):
            errors.append(name+": invalid image")
        pcd = np.asarray(o3d.io.read_point_cloud(str(folder/"cloud.pcd")).points)
        with np.load(folder/"lidar.npz", allow_pickle=False) as data:
            xyz = data["xyz"]
            times = data["timestamps"]
            d = data["directions"]
            if not np.isfinite(xyz).all() or not np.isfinite(times).all() or not np.isfinite(d).all():
                errors.append(name+": nonfinite measurements")
            if len(xyz) == 0:
                errors.append(name+": no valid returns")
            if pcd.shape != xyz.shape or not np.allclose(pcd, xyz, atol=1e-6, rtol=1e-6):
                errors.append(name+": PCD/NPZ points disagree")
            if np.any(np.diff(times) < 0) or np.any(times < c["timestamp"]-1e-10) or np.any(times >= c["timestamp"]+c["duration_s"]+1e-10):
                errors.append(name+": point timestamps outside scan window")
            if not np.allclose(np.linalg.norm(d, axis=1), 1, atol=1e-6):
                errors.append(name+": nonunit beam directions")
            radial = np.sum(xyz*d, axis=1)
            if not np.allclose(xyz, d*radial[:, None], atol=1e-5):
                errors.append(name+": point and ray directions disagree")
        T = validate_transform(t["T_CL"])
        T_WL, T_WC = validate_transform(t["T_WL"]), validate_transform(t["T_WC"])
        if not np.allclose(inverse(T_WC) @ T_WL, T, atol=1e-8, rtol=0):
            errors.append(name+": relative pose disagreement")
        with np.load(capture_dir(run, "evaluation", name)/"camera_geometry.npz", allow_pickle=False) as data:
            ranges, depth = data["depth_range_m"], data["depth_z_m"]
            if ranges.shape != (cam.height, cam.width) or depth.shape != ranges.shape:
                errors.append(name+": depth shape disagreement")
            directions = cam.pixel_rays().reshape(cam.height, cam.width, 3)
            if not np.allclose(depth, ranges*directions[:, :, 2], equal_nan=True, atol=1e-5):
                errors.append(name+": range/z depth disagreement")
        geometric = json_read(capture_dir(run, "evaluation", name)/"verification.json")
        if geometric["visible_to_camera"] <= 0:
            errors.append(name+": no shared visible points for projection verification")
        reproj = geometric["max_ray_reprojection_error_px"]
        if reproj is not None and reproj > 1e-5:
            errors.append(name+": camera inverse projection failed")
        captures.append(dict(capture_id=name, points=len(xyz), **geometric))
    manifest = json_read(run/"evaluation"/"manifest.json")
    if check_hashes:
        for entry in manifest["files"]:
            p = run/entry["path"]
            if not p.is_file() or sha256(p) != entry["sha256"]:
                errors.append("Manifest hash mismatch: "+entry["path"])
    # Explicit inference data boundary: no physical fault/ground-truth sidecar or ideal depth inputs.
    forbidden = {"ground_truth.json", "events.json", "ideal_lidar.npz", "camera_geometry.npz", "config.json"}
    for p in (run/"inference").rglob("*"):
        if p.name in forbidden:
            errors.append("Evaluation-only file leaked into inference: "+str(p))
    return dict(passed=not errors, errors=errors, captures=captures, file_hashes_checked=check_hashes)
