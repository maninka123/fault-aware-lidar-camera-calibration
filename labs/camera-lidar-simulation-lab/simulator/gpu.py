"""GPU detection. ``nvidia_info`` only calls nvidia-smi (read-only). ``blender_devices``
starts Blender headless and lists Cycles devices; it renders nothing."""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

_LIST_SCRIPT = r"""
import bpy, json
prefs = bpy.context.preferences.addons["cycles"].preferences
out = {}
for backend in ("OPTIX", "CUDA"):
    try:
        prefs.compute_device_type = backend
        prefs.get_devices()
        out[backend] = [d.name for d in prefs.devices if d.type == backend]
    except Exception as exc:
        out[backend] = "error: %s" % exc
print("GPUJSON" + json.dumps({"blender": bpy.app.version_string, "devices": out}))
"""


def nvidia_info(timeout=10):
    """Return dict(name, driver, memory_mb) or None when no NVIDIA driver is reachable."""
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=name,driver_version,memory.total",
                            "--format=csv,noheader,nounits"], capture_output=True, text=True,
                           timeout=timeout, creationflags=_NO_WINDOW)
        if r.returncode != 0 or not r.stdout.strip():
            return None
        name, driver, mem = [s.strip() for s in r.stdout.strip().splitlines()[0].split(",")]
        return dict(name=name, driver=driver, memory_mb=int(float(mem)))
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


_STATS = dict(at=0.0, value=None)
_STATS_LOCK = threading.Lock()


def _number(text):
    try:
        return float(text)
    except ValueError:
        return None          # nvidia-smi prints "[N/A]" for values a card does not report


def gpu_usage(timeout=5):
    """Live GPU load/memory/temperature/power from nvidia-smi (read-only), or None when no NVIDIA driver answers."""
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw,power.limit",
                            "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=timeout, creationflags=_NO_WINDOW)
        if r.returncode != 0 or not r.stdout.strip():
            return None
        name, *values = [s.strip() for s in r.stdout.strip().splitlines()[0].split(",")]
        util, used, total, temp, power, limit = (_number(v) for v in values)
        return dict(name=name, util=util, mem_used_mb=used, mem_total_mb=total, temp_c=temp, power_w=power, power_limit_w=limit)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def live_stats(max_age=0.8):
    """GPU, CPU (overall and per logical core) and RAM use right now. Cached briefly so several pages cost one query."""
    with _STATS_LOCK:
        now = time.monotonic()
        if _STATS["value"] is not None and now - _STATS["at"] < max_age:
            return _STATS["value"]
        out = dict(gpu=gpu_usage(), cpu=None, ram=None)
        try:
            import psutil
            cores = psutil.cpu_percent(interval=None, percpu=True)   # since the previous call, so no sleeping here
            memory = psutil.virtual_memory()
            out["cpu"] = dict(percent=sum(cores) / len(cores) if cores else 0.0, cores=cores)
            out["ram"] = dict(used_gb=(memory.total - memory.available) / 2 ** 30, total_gb=memory.total / 2 ** 30, percent=memory.percent)
        except ImportError:
            pass
        _STATS.update(at=now, value=out)
        return out


def blender_devices(blender, timeout=90):
    """List Cycles OptiX/CUDA devices Blender can see. No scene is loaded or rendered."""
    r = subprocess.run([blender, "--background", "--factory-startup", "--python-expr", _LIST_SCRIPT],
                       capture_output=True, text=True, timeout=timeout, creationflags=_NO_WINDOW)
    for line in r.stdout.splitlines():
        if line.startswith("GPUJSON"):
            return json.loads(line[7:])
    raise RuntimeError("Blender did not report devices:\n" + (r.stdout + r.stderr)[-600:])


def best_device(info):
    """Choose OPTIX > CUDA > CPU from a blender_devices() result."""
    for backend in ("OPTIX", "CUDA"):
        if isinstance(info["devices"].get(backend), list) and info["devices"][backend]:
            return backend
    return "CPU"
