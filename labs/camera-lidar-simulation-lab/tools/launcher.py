"""Shared settings and run-folder helpers for the browser app (tools/webui.py) and the save-folder picker.

Defaults, run naming, and building a validated generator config from the page's settings. The old Tk window was removed.
"""
from __future__ import annotations
from datetime import datetime
import glob
import json
import math
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SCENES = ("warehouse", "laboratory", "urban", "corridor")
LIDARS = ("livox_avia", "livox_mid360", "velodyne_vlp16", "ouster_os1_64", "hesai_at128")
QUALITIES = {"Preview": (8, 256), "Standard": (32, 512), "Detailed": (64, 1024)}
SCENE_INFO = {
    "warehouse": "Concrete hall with shelving, pallets, pipes and beams. Main calibration scene.",
    "laboratory": "Indoor lab: desks, monitors, cabinets, windows. Geometric and texture-only edges.",
    "urban": "Street with buildings, parked vehicles, trees and poles. Long range, sunlight.",
    "corridor": "Long repetitive passage with parallel walls. Tests calibration degeneracy.",
}
PREVIEW_SIZE = (260, 172)
PREFERENCES_PATH = ROOT / ".launcher_preferences.json"


def find_blender():
    found = shutil.which("blender")
    matches = sorted(glob.glob("C:/Program Files/Blender Foundation/Blender */blender.exe"), reverse=True)
    return found or (matches[0] if matches else "")


def last_output_parent():
    """Keep the last selected parent across launches; tolerate removed folders/settings."""
    try:
        settings = json.loads(PREFERENCES_PATH.read_text(encoding="utf-8"))
        parent = Path(settings["last_output_parent"])
        if parent.is_dir():
            return parent
    except (OSError, ValueError, KeyError, TypeError):
        pass
    default = ROOT / "outputs"
    return default if default.is_dir() else ROOT


def run_name(scene, captures, when=None):
    """<environment>_<YYYYMMDD>_<HHMMSS>_<captures>, e.g. warehouse_20261106_225242_05."""
    when = when or datetime.now()
    safe = "".join(c if c.isalnum() or c in "-" else "-" for c in str(scene)) or "run"
    return f"{safe}_{when:%Y%m%d_%H%M%S}_{max(0, int(captures)):02d}"


def new_output(parent=None, scene="warehouse", captures=1):
    parent = last_output_parent() if parent is None else Path(parent)
    path = parent / run_name(scene, captures)
    n = 2
    while path.exists():  # two runs in the same second: keep the name pattern, differ before the capture count
        path = parent / run_name(scene, captures).replace(f"_{int(captures):02d}", f"-{n}_{int(captures):02d}")
        n += 1
    return path


def default_values():
    return dict(scene="warehouse", lidar="livox_avia", camera="fisheye", renderer="blender",
                width="1024", height="768", focal="416", captures="1", duration="0.1",
                interval="1", seed="42", xyz="0, 0, 1.6", rpy="0, 0, 0", stride="auto",
                cam_xyz="0.05, -0.15, 0.03", cam_rpy="0, 0, 0", accumulate="1.0",
                samples="32", cube_size="1024", load="responsive", device="OPTIX", blender=find_blender(), output=str(new_output()))


def triple(text, name):
    try:
        values = [float(v.strip()) for v in text.split(",")]
    except ValueError as exc:
        raise ValueError(f"{name} needs three comma-separated numbers") from exc
    if len(values) != 3 or not all(math.isfinite(v) for v in values):
        raise ValueError(f"{name} needs three finite comma-separated numbers")
    return values


def number(values, key, label, kind=float, default=None):
    """Read a setting typed by the user; say which field is wrong instead of leaking a Python error."""
    raw = values.get(key, default)
    if raw is None or str(raw).strip() == "":
        raw = default
    try:
        value = kind(str(raw).strip())
    except (ValueError, TypeError):
        raise ValueError(f"{label} must be {'a whole number' if kind is int else 'a number'} (got '{raw}').") from None
    if kind is float and not math.isfinite(value):
        raise ValueError(f"{label} must be a finite number.")
    return value


def resolve_stride(values, max_rays=800_000):
    """Beam stride. "auto" = densest scan (stride 1) whose longest window stays under the pipeline ray limit."""
    text = str(values.get("stride", "auto")).strip().lower()
    if text not in ("", "auto"):
        return number(values, "stride", "Beam stride", int)
    from simulator.lidar import generate_rays
    window = max(number(values, "duration", "Scan accumulation"), number(values, "accumulate", "Accumulated scan", default=0))
    probe = 0.1  # short probe: the full window could itself exceed the pipeline ray limit
    count = generate_rays(values["lidar"], 0.0, probe, {"stride": 1})["metadata"]["generated_ray_count"] * window / probe
    return max(1, math.ceil(count / max_rays))


def make_config(values):
    if not str(values.get("output", "")).strip():
        raise ValueError("Choose an output folder")
    focal = number(values, "focal", "Focal length")
    config = dict(scene=values["scene"], lidar=values["lidar"],
                  camera=dict(model=values["camera"], width=number(values, "width", "Image width", int),
                              height=number(values, "height", "Image height", int),
                              focal_px=focal, D=[0., 0., 0., 0.]),
                  captures=number(values, "captures", "Captures", int), duration=number(values, "duration", "Scan accumulation"),
                  interval=number(values, "interval", "Capture interval"), seed=number(values, "seed", "Random seed", int),
                  lidar_pose=dict(xyz=triple(values["xyz"], "Rig position"),
                                  rpy_deg=triple(values["rpy"], "Rig orientation")),
                  output=str(Path(values["output"]).expanduser().resolve()),
                  renderer=values.get("renderer", "blender"),
                  lidar_options=dict(stride=resolve_stride(values)),
                  render=dict(samples=number(values, "samples", "Samples", int), cubemap_size=number(values, "cube_size", "Cube pixels", int),
                              device=values["device"]), split="test")
    accumulate = number(values, "accumulate", "Accumulated scan", default=0)
    if accumulate:
        config["accumulate_s"] = accumulate
    from simulator.geometry import camera_extrinsic, pose
    config["T_CL"] = camera_extrinsic(triple(values.get("cam_xyz", "0.05, -0.15, 0.03"), "Camera position in LiDAR frame"),
                                      triple(values.get("cam_rpy", "0, 0, 0"), "Camera rotation relative to LiDAR")).tolist()
    mounts, batch_ids = values.get("mounts"), values.get("batch_ids")
    poses = values.get("poses")
    if poses:
        if not all(isinstance(p, (list, tuple)) and len(p) == 6 and all(isinstance(v, (int, float)) and math.isfinite(v) for v in p) for p in poses):
            raise ValueError("Each captured pose needs x, y, z, roll, pitch, yaw")
        config["poses"] = [pose(p[:3], p[3:]).tolist() for p in poses]
        config["captures"] = len(poses)
        if values.get("cameras") is not None:
            # None entries represent individually placed captures using the current baseline.
            config["cameras"] = [c if c is not None else config["camera"] for c in values["cameras"]]
        if mounts:
            if len(mounts) != len(poses) or not all(isinstance(m, (list, tuple)) and len(m) == 6 and all(isinstance(v, (int, float)) and math.isfinite(v) for v in m) for m in mounts):
                raise ValueError("Each capture needs a six-number camera mount")
            config["T_CLs"] = [camera_extrinsic(m[:3], m[3:]).tolist() for m in mounts]
        if batch_ids and len(batch_ids) == len(poses) and any(b >= 0 for b in batch_ids):
            config["batch_ids"] = [int(b) for b in batch_ids]
    if not math.isfinite(focal) or focal <= 0:
        raise ValueError("Focal length must be finite and positive")
    if config["lidar_options"]["stride"] < 1:
        raise ValueError("Beam stride must be at least 1; use 1 for the full scan")
    if not values["output"].strip():
        raise ValueError("Choose an output folder")
    from simulator.camera import Camera
    from simulator.pipeline import validate_config
    validate_config(config)
    Camera.from_dict(config["camera"])
    return config
