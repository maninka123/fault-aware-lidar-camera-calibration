"""Paths, config, logging and data loading shared by the steps.

Inputs are the stacked captures of ../../Oct 29 test (read-only). The Oct 29 calibration is
loaded only by the comparison step (step3), never by the calibration.
"""
from __future__ import annotations

import os

for _v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_v, "1")  # multi-threaded BLAS + OpenCV crash this numpy build

import sys

sys.dont_write_bytecode = True  # read-only imports from other folders must not leave __pycache__ there

import json
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import yaml

cv2.setNumThreads(1)

CODE = Path(__file__).resolve().parent
ROOT = CODE.parent                      # "Targetless calibration"
PROJECT = ROOT.parent                   # "#Automated calibration"

T0 = time.time()


def log(msg):
    print(f"[{time.time() - T0:7.1f}s] {msg}", flush=True)


def load_config(path: Path | None = None) -> dict:
    return yaml.safe_load((path or CODE / "config.yaml").read_text(encoding="utf-8"))


def oct29_dir(cfg) -> Path:
    return (CODE / cfg["oct29_dir"]).resolve()


def output_dir(cfg) -> Path:
    return (CODE / cfg["output_dir"]).resolve()


def cache_dir(cfg) -> Path:
    return (CODE / cfg["cache_dir"]).resolve()


def stacked_root(cfg) -> Path:
    """Stacked captures decoded by decode_bags.py (new datasets)."""
    return (CODE / cfg["stacked_dir"]).resolve()


def devices(cfg, source="oct29") -> list[str]:
    """Device / dataset names: "oct29" = the four Oct 29 devices, "new" = datasets decoded here."""
    if source == "oct29":
        return sorted(p.name for p in (oct29_dir(cfg) / "stacked_data").glob("pair_*") if p.is_dir())
    return sorted(p.name for p in stacked_root(cfg).glob("*") if p.is_dir())


def device_dir(cfg, device) -> Path:
    for root in (oct29_dir(cfg) / "stacked_data", stacked_root(cfg)):
        if (root / device).is_dir():
            return root / device
    raise FileNotFoundError(f"no stacked captures for {device}")


def short_name(name: str) -> str:
    """capture_20261028_215552_249295_enclosure_on -> 215552_249295 (same rule as Oct 29 test)."""
    p = name.split("_")
    return f"{p[2]}_{p[3]}" if len(p) >= 4 else name


@dataclass
class Frame:
    """One stacked capture: median image + merged LiDAR cloud of the still window."""
    name: str
    short: str
    image: np.ndarray          # BGR uint8
    xyz: np.ndarray            # (N, 3) metres, LiDAR frame of this capture
    intensity: np.ndarray      # (N,) Avia reflectivity
    time: np.ndarray           # (N,) seconds, time of the LiDAR frame each point came from


def load_frames(cfg, device) -> list[Frame]:
    out = []
    for f in sorted(device_dir(cfg, device).glob("capture_*.npz")):
        z = np.load(f)
        out.append(Frame(f.stem, short_name(f.stem), z["image"], z["xyz_mm"].astype(np.float64) / 1000.0,
                         z["intensity"].astype(np.float64), z["frame_time"][z["frame"].astype(int)]))
    return out


def image_circle(frames, shrink=1.0):
    """Fisheye image circle from the images themselves (median over captures)."""
    import sys
    sys.path.insert(0, str(PROJECT / "multi_capture_calibration"))
    from mcc.camera import image_circle as fit  # read-only import
    fits = [c for c in (fit(f.image) for f in frames) if c is not None]
    if not fits:     # not a fisheye with a visible circle: image centre, whole frame valid
        h, w = frames[0].image.shape[:2]
        return dict(cx=w / 2, cy=h / 2, radius=float(np.hypot(w, h) / 2) * shrink, captures=0, fallback=True)
    cx, cy, r = (float(np.median([c[k] for c in fits])) for k in ("cx", "cy", "radius"))
    return dict(cx=cx, cy=cy, radius=r * shrink, captures=len(fits))


def imwrite(path: Path, img):
    """cv2.imwrite fails silently on long paths; encode + write_bytes does not."""
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, buf = cv2.imencode(path.suffix or ".png", img)
    if ok:
        path.write_bytes(buf.tobytes())


def write_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o)))
