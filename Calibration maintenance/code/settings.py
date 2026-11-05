"""Paths, settings and data loading for calibration maintenance.

The edge extraction, camera model and edge refinement come from ../../Targetless calibration/code
(imported read-only; nothing there is changed). Settings = that folder's config.yaml (feature and
solver settings for new datasets) overlaid with this folder's config.yaml (maintenance settings).
"""
from __future__ import annotations

import os
import sys

for _v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_v, "1")  # multi-threaded BLAS + OpenCV crash this numpy build
sys.dont_write_bytecode = True      # read-only imports from other folders must not leave __pycache__ there

import json  # noqa: E402
import time  # noqa: E402
from dataclasses import dataclass  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402
import yaml  # noqa: E402

CODE = Path(__file__).resolve().parent
ROOT = CODE.parent                                  # "Calibration maintenance"
PROJECT = ROOT.parent                               # "#Automated calibration"
TARGETLESS = PROJECT / "Targetless calibration" / "code"
sys.path.append(str(TARGETLESS))                    # after this folder: our modules win on name clashes

T0 = time.time()


def log(msg):
    print(f"[{time.time() - T0:7.1f}s] {msg}", flush=True)


def _merge(a, b):
    out = dict(a)
    for k, v in b.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load_config():
    base = yaml.safe_load((TARGETLESS / "config.yaml").read_text(encoding="utf-8"))
    own = yaml.safe_load((CODE / "config.yaml").read_text(encoding="utf-8"))
    return _merge(base, own)


def results_dir() -> Path:
    return ROOT / "results"


@dataclass
class Calibration:
    K: np.ndarray
    D: np.ndarray          # 4 fisheye coefficients
    T: np.ndarray          # 4 x 4 LiDAR -> camera
    model: str
    source: str
    raw: dict


def load_calibration(path) -> Calibration:
    """Project calibration JSON or a lossless calibration TXT export."""
    from calibration_io import read_calibration
    c = read_calibration(path)
    D = np.r_[np.ravel(c["intrinsics"]["distortion_coefficients"]), np.zeros(4)][:4]
    return Calibration(np.array(c["intrinsics"]["camera_matrix"], float), D,
                       np.array(c["extrinsics"]["transform_lidar_to_camera"], float),
                       c["intrinsics"].get("distortion_model", "k1-k2-k3-k4" if np.any(D[2:]) else "k1-k2" if D[1] else "k1"), str(path), c)


def load_stacked(folder):
    """Stacked captures (*.npz: median image + merged LiDAR cloud) as Targetless `Frame`s."""
    from common import Frame, short_name           # Targetless common (read-only)
    frames = []
    for f in sorted(Path(folder).glob("*.npz")):
        z = np.load(f)
        if "xyz_mm" not in z or "image" not in z:
            continue
        frames.append(Frame(f.stem, short_name(f.stem), z["image"], z["xyz_mm"].astype(np.float64) / 1000.0,
                            z["intensity"].astype(np.float64), z["frame_time"][z["frame"].astype(int)]))
    return frames


def write_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o)))
