"""Time-indexed beam schedules in the common x-forward, y-left, z-up frame.

This module generates rays, not depth-derived points. Intersection and measurement
noise belong to the simulation pipeline. See docs/SENSOR_MODELS.md for fidelity.
"""
from __future__ import annotations

from functools import lru_cache
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np


MODEL_VERSION = "1.0.0"
PROFILES = (
    "livox_avia", "livox_mid360", "velodyne_vlp16", "ouster_os1_64", "hesai_at128",
)
_LIMITS = {
    "livox_avia": (0.1, 190.0),
    "livox_mid360": (0.1, 40.0),
    "velodyne_vlp16": (1.0, 100.0),
    "ouster_os1_64": (0.5, 100.0),
    "hesai_at128": (0.5, 260.0),
}
_COMMON_OPTIONS = {"stride", "scan_mode", "range_min_m", "range_max_m"}
_PROFILE_OPTIONS = {
    "livox_avia": {"pattern_path"},
    "livox_mid360": {"pattern_path"},
    "velodyne_vlp16": {"rotation_hz", "azimuth_phase_deg"},
    "ouster_os1_64": {"rotation_hz", "columns_per_rotation", "beam_elevations_deg", "beam_azimuth_offsets_deg", "azimuth_phase_deg"},
    "hesai_at128": {"rotation_hz", "beam_elevations_deg", "beam_azimuth_offsets_deg"},
}


def _positive_integer(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return int(value)


def _finite(value: Any, name: str) -> float:
    try:
        result = float(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if isinstance(value, bool) or not np.isfinite(result):
        raise ValueError(f"{name} must be a finite number")
    return result


def _regular_indices(start: float, end: float, rate: float, stride: int) -> np.ndarray:
    # nextafter handles exact floating point frame boundaries without admitting
    # a beam before the requested interval; a final time filter is still applied.
    first = int(np.ceil(np.nextafter(start * rate, -np.inf)))
    stop = int(np.ceil(np.nextafter(end * rate, -np.inf)))
    first += (-first) % stride
    if (stop - first) / stride > 1_000_000:
        raise ValueError("Conservative execution limit: at most one million rays; reduce duration or increase stride")
    ids = np.arange(first, max(first, stop), stride, dtype=np.int64)
    times = ids / rate
    return ids[(times >= start) & (times < end)]


def _directions(azimuth_deg: np.ndarray, elevation_deg: np.ndarray) -> np.ndarray:
    azimuth = np.deg2rad(azimuth_deg)
    elevation = np.deg2rad(elevation_deg)
    c = np.cos(elevation)
    return np.column_stack((c * np.cos(azimuth), c * np.sin(azimuth), np.sin(elevation)))


def _beam_table(options: dict, key: str, default: np.ndarray, count: int) -> np.ndarray:
    result = np.asarray(options.get(key, default), dtype=np.float64)
    if result.shape != (count,) or not np.all(np.isfinite(result)):
        raise ValueError(f"{key} must contain exactly {count} finite angles in degrees")
    if key == "beam_elevations_deg" and np.any(np.abs(result) >= 90):
        raise ValueError("beam_elevations_deg must be strictly between -90 and 90 degrees")
    return result


@lru_cache(maxsize=4)
def _load_pattern(path_string: str) -> tuple[np.ndarray, str]:
    path = Path(path_string)
    if not path.is_file():
        raise FileNotFoundError(
            f"Livox scan pattern missing: {path}. Reinstall simulator package data "
            "or provide options.pattern_path; no synthetic fallback is used."
        )
    if path.suffix.lower() == ".npz":
        with np.load(path, allow_pickle=False) as archive:
            data = np.asarray(archive["data"], dtype=np.float64)
            checksum = str(archive["source_csv_sha256"].item())
        # Bundled data is verified against the versioned provenance manifest.
        manifest_path = path.parent / "provenance.json"
        if manifest_path.is_file():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            expected = manifest.get("files", {}).get(path.stem)
            if expected and (hashlib.sha256(path.read_bytes()).hexdigest() != expected["npz_sha256"]
                             or checksum != expected["source_csv_sha256"]):
                raise ValueError("Livox packaged pattern checksum differs from provenance manifest")
    else:
        data = np.loadtxt(path, delimiter=",", skiprows=1, dtype=np.float64)
        checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    if data.ndim != 2 or data.shape[1] != 3 or len(data) < 2 or not np.all(np.isfinite(data)):
        raise ValueError("Livox CSV must have a header and finite Time,Azimuth,Zenith rows")
    if np.any(np.diff(data[:, 0]) <= 0):
        raise ValueError("Livox source first column must be strictly increasing")
    if np.any((data[:, 2] < 0) | (data[:, 2] > 180)):
        raise ValueError("Livox Zenith/deg values must lie within [0,180]")
    data.flags.writeable = False
    return data, checksum


def generate_rays(profile: str, start_time: float, duration: float,
                  options: dict | None = None) -> dict:
    """Return rays in the half-open absolute-time window [start, start+duration).

    ``stride`` selects every kth *global* scheduled beam, retaining true times.
    It reduces simulation density; it never changes the declared physical rate.
    Livox channel IDs are -1 because the source CSV does not identify emitters.
    """
    if profile not in PROFILES:
        raise ValueError(f"Unknown LiDAR profile {profile!r}; choose one of {PROFILES}")
    start = _finite(start_time, "start_time")
    length = _finite(duration, "duration")
    if start < 0 or length <= 0:
        raise ValueError("start_time must be nonnegative and duration must be positive")
    end = start + length
    if not np.isfinite(end) or end <= start or end > 1e9:
        raise ValueError("Use sequence-relative times below 1e9 seconds with representable positive duration")
    if options is not None and not isinstance(options, dict):
        raise ValueError("LiDAR options must be a mapping")
    options = dict(options or {})
    unknown = set(options) - _COMMON_OPTIONS - _PROFILE_OPTIONS[profile]
    if unknown:
        raise ValueError(f"Unsupported {profile} options: {sorted(unknown)}")
    stride = _positive_integer(options.get("stride", 1), "stride")
    range_min = _finite(options.get("range_min_m", _LIMITS[profile][0]), "range_min_m")
    range_max = _finite(options.get("range_max_m", _LIMITS[profile][1]), "range_max_m")
    if range_min < 0 or range_max <= range_min:
        raise ValueError("Range cutoffs must satisfy 0 <= range_min_m < range_max_m")
    mode = options.get("scan_mode", "nonrepetitive" if profile.startswith("livox") else "single_return")
    expected_mode = "nonrepetitive" if profile.startswith("livox") else "single_return"
    if mode != expected_mode:
        raise ValueError(f"{profile} supports only scan_mode={expected_mode!r}; requested {mode!r}")
    meta = {
        "profile": profile, "model_version": MODEL_VERSION,
        "frame": "lidar", "axes": "x-forward, y-left, z-up", "angle_units": "degrees",
        "timestamp_units": "seconds", "start_time": start, "duration": length,
        "scan_mode": mode, "stride": stride,
        "range_min_m": range_min, "range_max_m": range_max,
        "range_limits_are_configurable_cutoffs": True,
        "single_origin_approximation": True,
    }
    if profile.startswith("livox"):
        name = "avia.npz" if profile == "livox_avia" else "mid360.npz"
        default_path = Path(__file__).resolve().parent / "patterns" / name
        data, checksum = _load_pattern(str(Path(options.get("pattern_path", default_path)).resolve()))
        rate = 240_000.0 if profile == "livox_avia" else 200_000.0
        ids = _regular_indices(start, end, rate, stride)
        rows = ids % len(data)
        directions = _directions(data[rows, 1], 90.0 - data[rows, 2])
        times = ids / rate
        channels = np.full(len(ids), -1, dtype=np.int16)
        meta.update(
            fidelity="official_pattern_replay", pattern_sha256=checksum,
            pattern_rows=len(data), pattern_period_s=len(data) / rate,
            pattern_source="https://github.com/Livox-SDK/livox_laser_simulation",
            pattern_reference_commit="1cce1073633a062b92e30243a4c2920e45551bb5",
            pattern_license="MIT; Copyright (c) 2021 livox",
            channel_identity="unavailable_in_reference_csv",
            timing_model="uniform nominal point rate; reference row order preserved",
            timing_limitation=("CSV seconds agree with nominal schedule within rounding; periodic replay after file end"
                               if profile == "livox_avia" else
                               "CSV Time/s column is an integer row counter; reconstructed at 200000 Hz; periodic replay"),
            nominal_point_rate_hz=rate,
            limitations=["Finite reference pattern repeats after its recorded duration; not a hardware-exact indefinite scanner",
                         "Avia repetitive line mode unavailable and rejected; multiple returns unsupported",
                         "No physical beam divergence or internal optical-origin offsets"],
        )
        if "pattern_path" in options:
            meta.update(fidelity="user_supplied_pattern_replay",
                        pattern_source="user-supplied CSV; SHA-256 identifies consumed contents",
                        pattern_reference_commit=None, pattern_license="user must establish source license")
    elif profile == "velodyne_vlp16":
        hz = _finite(options.get("rotation_hz", 10), "rotation_hz")
        if not 5 <= hz <= 20:
            raise ValueError("VLP-16 rotation_hz must be between 5 and 20")
        cycle = 55.296e-6
        first_cycle = int(np.floor(start / cycle))
        final_cycle = int(np.ceil(end / cycle))
        first_id = first_cycle * 16
        first_id += (-first_id) % stride
        stop_id = final_cycle * 16
        if (stop_id - first_id) / stride > 1_000_000:
            raise ValueError("Conservative execution limit: at most one million rays; reduce duration or increase stride")
        ids = np.arange(first_id, max(first_id, stop_id), stride, dtype=np.int64)
        times = (ids // 16) * cycle + (ids % 16) * 2.304e-6
        keep = (times >= start) & (times < end)
        ids, times = ids[keep], times[keep]
        channels = (ids % 16).astype(np.int16)
        elevations = np.array([-15, 1, -13, 3, -11, 5, -9, 7, -7, 9, -5, 11, -3, 13, -1, 15], float)
        phase = _finite(options.get("azimuth_phase_deg", 0), "azimuth_phase_deg")
        directions = _directions((times * hz * 360 + phase) % 360, elevations[channels])
        rate = 16 / cycle
        meta.update(fidelity="nominal_channel_geometry_documented_firing_timing", rotation_hz=hz,
                    nominal_point_rate_hz=rate, firing_cycle_s=cycle, channel_spacing_s=2.304e-6,
                    beam_elevations_deg=elevations.tolist(),
                    limitations=["Shared origin omits channel optical-centre offsets", "No unit-specific angle/range corrections", "Single return only"])
    else:
        count = 64 if profile == "ouster_os1_64" else 128
        hz = _finite(options.get("rotation_hz", 10), "rotation_hz")
        if hz not in (10, 20):
            raise ValueError(f"{profile} rotation_hz must be 10 or 20")
        if profile == "ouster_os1_64":
            columns = _positive_integer(options.get("columns_per_rotation", 1024), "columns_per_rotation")
            if columns not in (512, 1024, 2048) or (columns == 2048 and hz == 20):
                raise ValueError("OS1 modes: 512x10, 512x20, 1024x10, 1024x20, 2048x10")
            default_elevations = np.linspace(-22.5, 22.5, count)
        else:
            # AT128P nominal far-field configuration: 0.1 deg at 10 Hz,
            # 0.2 deg at 20 Hz. Internal firing/correction tables unavailable.
            columns = 1200 if hz == 10 else 600
            default_elevations = np.linspace(-12.5, 12.9, count)
        elevations = _beam_table(options, "beam_elevations_deg", default_elevations, count)
        offsets = _beam_table(options, "beam_azimuth_offsets_deg", np.zeros(count), count)
        rate = hz * columns * count
        ids = _regular_indices(start, end, rate, stride)
        times = ids / rate
        channels = (ids % count).astype(np.int16)
        column = (ids // count) % columns
        if profile == "ouster_os1_64":
            phase = _finite(options.get("azimuth_phase_deg", 0), "azimuth_phase_deg")
            azimuth = column * 360.0 / columns + phase
        else:
            azimuth = -60 + column * 120.0 / columns
        directions = _directions(azimuth + offsets[channels], elevations[channels])
        meta.update(fidelity="nominal_specification_approximation", rotation_hz=hz,
                    columns_per_rotation=columns, nominal_point_rate_hz=rate,
                    beam_elevations_deg=elevations.tolist(), beam_azimuth_offsets_deg=offsets.tolist(),
                    timing_model="sequential uniform per-channel times within each column; nominal, not verified hardware firing order",
                    beam_configuration="user-supplied" if "beam_elevations_deg" in options else "nominal uniform",
                    limitations=["No hardware-specific angle correction or validated firing order", "Shared ray origin", "Single return only"])
        if profile == "hesai_at128":
            meta["hardware_reference"] = "AT128P public manual A02-en-260110 linked from AT128 download page"
            meta["limitations"].append("Far-field lattice used at all ranges; near-field channel/resolution switching not modeled")
    meta["generated_ray_count"] = len(times)
    meta["effective_nominal_point_rate_hz"] = meta["nominal_point_rate_hz"] / stride
    return {"directions": directions, "timestamps": times, "channel": channels,
            "beam_id": ids, "metadata": meta}


class LidarModel:
    """Small common sensor interface for config-driven callers."""

    def __init__(self, profile: str, options: dict | None = None):
        if profile not in PROFILES:
            raise ValueError(f"Unknown LiDAR profile: {profile}")
        self.profile = profile
        self.options = dict(options or {})

    def get_rays(self, start_time: float, duration: float) -> dict:
        return generate_rays(self.profile, start_time, duration, self.options)

    def get_metadata(self) -> dict:
        return self.get_rays(0.0, 1e-9)["metadata"]
