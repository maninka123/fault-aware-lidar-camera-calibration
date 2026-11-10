"""Measurement-only exports for the existing calibration applications.

This module deliberately never opens ``evaluation/``. Export destinations must be
new or empty, preventing accidental mixing of paired and stacked input formats.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import cv2
import numpy as np


def inference_root(run):
    root = Path(run).resolve()
    return root / "inference" if (root / "inference").is_dir() else root


def sequence_entries(run):
    """Return time-ordered captures and reject paths outside the inference tree."""
    root = inference_root(run)
    data = json.loads((root / "sequence.json").read_text(encoding="utf-8"))
    entries = data if isinstance(data, list) else data["captures"]
    previous = -np.inf
    seen = set()
    result = []
    for entry in entries:
        timestamp = float(entry["timestamp"])
        if not np.isfinite(timestamp) or timestamp < 0 or timestamp < previous:
            raise ValueError("Capture timestamps must be finite, nonnegative and time ordered")
        previous = timestamp
        identifier = str(entry["capture_id"])
        if not identifier or identifier in seen or Path(identifier).name != identifier or identifier in {".", ".."}:
            raise ValueError("Capture IDs must be unique simple filenames")
        seen.add(identifier)
        path = (root / entry["path"]).resolve()
        if root not in path.parents or not path.is_dir():
            raise ValueError("Capture path must identify a directory inside inference/")
        result.append(dict(entry, capture_id=identifier, timestamp=timestamp, directory=path))
    if not result:
        raise ValueError("Sequence has no captures")
    return root, result


def _destination(path, source):
    path = Path(path).resolve()
    if path == source or source in path.parents:
        raise ValueError("Export destination must be outside the inference input tree")
    if path.exists() and any(path.iterdir()):
        raise FileExistsError("Export destination must be new or empty: " + str(path))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _copy_initial(root, destination):
    source = root / "initial_calibration.json"
    if source.is_file():
        shutil.copy2(source, destination / "initial_calibration.json")


def export_paired(run, destination):
    """Copy only RGB image/PCD pairs, initial estimate and public timestamps."""
    root, captures = sequence_entries(run)
    destination = _destination(destination, root)
    for capture in captures:
        target = destination / capture["capture_id"]
        target.mkdir()
        for name in ("image.png", "cloud.pcd"):
            shutil.copy2(capture["directory"] / name, target / name)
    _copy_initial(root, destination)
    (destination / "export_metadata.json").write_text(json.dumps(dict(
        format="image_pcd_pairs", coordinate_units="metres", point_frame="lidar",
        captures=[{k: c[k] for k in ("capture_id", "timestamp")} for c in captures],
        timing_note="Per-point timing remains in the original lidar.npz; PCD pair import uses static captures.",
        ground_truth_included=False), indent=2), encoding="utf-8")
    return destination


def export_stacked(run, destination):
    """Export BGR/xyz_mm arrays without int16 range clipping.

    One generated scan is represented as one source frame. Exact per-point times
    are additionally retained in ``point_time``; the current optimizer ignores
    this extension and reads ``frame_time[frame]`` instead.
    """
    root, captures = sequence_entries(run)
    destination = _destination(destination, root)
    for capture in captures:
        image_path = capture["directory"] / "image.png"
        image = cv2.imdecode(np.frombuffer(image_path.read_bytes(), np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("Unreadable image: " + str(image_path))
        with np.load(capture["directory"] / "lidar.npz", allow_pickle=False) as cloud:
            xyz = np.asarray(cloud["xyz"], np.float64)
            intensity = np.asarray(cloud["intensity"], np.float32)
            timestamp = np.asarray(cloud["timestamps"], np.float64)
            if xyz.ndim != 2 or xyz.shape[1] != 3 or not np.isfinite(xyz).all():
                raise ValueError("Expected finite Nx3 LiDAR coordinates")
            if intensity.shape != (len(xyz),) or timestamp.shape != (len(xyz),):
                raise ValueError("LiDAR array lengths do not match")
            np.savez_compressed(destination / (capture["capture_id"] + ".npz"),
                                image=image, xyz_mm=(xyz * 1000).astype(np.float32),
                                intensity=intensity, frame=np.zeros(len(xyz), np.int32),
                                frame_time=np.array([capture["timestamp"]], np.float64),
                                point_time=timestamp)
    _copy_initial(root, destination)
    (destination / "export_metadata.json").write_text(json.dumps(dict(
        format="stacked_npz", image_order="BGR", coordinate_units="millimetres",
        static_scan=True, point_time_units="absolute seconds",
        timing_note="One source frame per generated scan; optimizer does not read point_time.",
        ground_truth_included=False), indent=2), encoding="utf-8")
    return destination


def validate_optimizer_camera(calibration):
    """Reject model reinterpretation unsupported by the reference solver."""
    intrinsics = calibration["intrinsics"]
    model = intrinsics.get("model", intrinsics.get("distortion_model", ""))
    if model not in {"fisheye", "opencv_fisheye", "k1", "k1-k2", "equidistant"}:
        raise ValueError("Reference optimizer requires OpenCV fisheye; this calibration declares " + repr(model))
    coefficients = np.ravel(np.asarray(intrinsics.get("distortion_coefficients", []), float))
    if len(coefficients) > 4 or not np.isfinite(coefficients).all():
        raise ValueError("Invalid fisheye coefficients")
    if len(coefficients) > 2 and np.any(coefficients[2:] != 0):
        raise ValueError("Reference optimizer implements k1,k2 only; nonzero fisheye k3/k4 are unsupported")
    return True
