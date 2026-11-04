"""Test tool: make a copy of a calibration with a known drift (as vibration would cause), to check
that the maintenance pipeline detects it and recovers the original.

Usage:  python simulate_drift.py <calibration.json> <out.json> --tilt 0.5 --pan 0.3 --roll 0 --dx 15 --dy 0 --dz 0
        (rotations in degrees about the camera x / y / z axes, translations in mm)
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("calibration")
    ap.add_argument("out")
    for k in ("tilt", "pan", "roll", "dx", "dy", "dz"):
        ap.add_argument(f"--{k}", type=float, default=0.0)
    a = ap.parse_args()
    c = json.loads(Path(a.calibration).read_text())
    T = np.array(c["extrinsics"]["transform_lidar_to_camera"], float)
    dR = Rotation.from_euler("xyz", [a.tilt, a.pan, a.roll], degrees=True).as_matrix()
    T[:3, :3] = dR @ T[:3, :3]
    T[:3, 3] = dR @ T[:3, 3] + np.array([a.dx, a.dy, a.dz]) / 1000
    c["extrinsics"] = dict(transform_lidar_to_camera=T.tolist())
    c["simulated_drift"] = dict(source=a.calibration, tilt_deg=a.tilt, pan_deg=a.pan, roll_deg=a.roll,
                                dx_mm=a.dx, dy_mm=a.dy, dz_mm=a.dz)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(c, indent=2))
    print(f"wrote {a.out}: drift tilt {a.tilt} pan {a.pan} roll {a.roll} deg, translation ({a.dx}, {a.dy}, {a.dz}) mm")


if __name__ == "__main__":
    main()
