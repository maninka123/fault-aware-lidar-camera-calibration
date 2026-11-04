"""The sensor devices the app can connect to.

Read from the Central Monitoring Platform's configuration (the installed copy in
%APPDATA%/central-monitoring-platform, read-only), plus devices added in this app. Per-device choices
made here (topics, SSH user, trusted SSH host key, path of pipeline.yaml) are kept in devices.json in
this folder; the platform's files are never written.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse

from appcore import ROOT

CMP_DIR = Path(os.environ.get("APPDATA", "")) / "central-monitoring-platform"
LOCAL = ROOT / "devices.json"
DEFAULT_TOPICS = dict(image_topic="/camera/image_raw", cloud_topic="/livox/lidar")


def _env(path):
    out = {}
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$", line)
        if m and not line.lstrip().startswith("#"):
            out[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return out


def cmp_devices(folder=CMP_DIR):
    """Devices of the Central Monitoring Platform (config.json + device_configs/*.env)."""
    cfg_path = Path(folder) / "config.json"
    if not cfg_path.exists():
        return []
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    out = []
    for entry in cfg.get("devices", {}).get("list", []):
        f = entry.get("configFile")
        env = _env(Path(folder) / f) if f and (Path(folder) / f).exists() else {}
        name = env.get("DEVICE_NAME") or entry.get("name") or f"Device {entry.get('id', len(out) + 1)}"
        master = env.get("ROS_MASTER_URI", "")
        bridge = f"ws://{env['ROSBRIDGE_IP']}:{env.get('ROSBRIDGE_PORT') or 9090}{env.get('ROSBRIDGE_PATH', '')}" if env.get("ROSBRIDGE_IP") \
            else entry.get("serverUrl", "")
        host = env.get("SSH_HOST") or urlparse(master).hostname or urlparse(bridge).hostname or ""
        out.append(dict(key=f"cmp:{env.get('DEVICE_ID') or entry.get('id') or name}", name=name, source="Central Monitoring Platform",
                        enabled=(env.get("DEVICE_ENABLED", str(entry.get("enabled", True))).lower() != "false"),
                        master_uri=master, bridge_url=bridge, ssh_host=host, ssh_user=env.get("SSH_USER") or "rock",
                        ssh_port=int(env.get("SSH_PORT") or 22), color=env.get("DEVICE_COLOR") or entry.get("color") or "#2a78d6"))
    return out


def _local():
    try:
        return json.loads(LOCAL.read_text(encoding="utf-8"))
    except Exception:
        return dict(devices=[], settings={})


def platform_dir():
    """The Central Monitoring Platform folder whose config.json is read: the installed copy, or a
    source checkout chosen in the app."""
    return Path(_local().get("platform_dir") or CMP_DIR)


def set_platform_dir(folder):
    data = _local()
    data["platform_dir"] = str(folder)
    LOCAL.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load():
    """All devices: the platform's, then the ones added here; with the choices saved here.
    Like the platform, an entry with a configFile takes its addresses from that .env file; an entry
    without one uses its serverUrl (ROSBridge only)."""
    data = _local()
    out = []
    for d in cmp_devices(platform_dir()) + data.get("devices", []):
        d = dict(DEFAULT_TOPICS, **d)
        d.update(data.get("settings", {}).get(d["key"], {}))
        out.append(d)
    return out


def save_settings(key, **values):
    data = _local()
    data.setdefault("settings", {}).setdefault(key, {}).update(values)
    LOCAL.write_text(json.dumps(data, indent=2), encoding="utf-8")


def add(name, host, master_port=11311, bridge_port=9090, ssh_user="rock", ssh_port=22):
    data = _local()
    key = f"local:{name}"
    data["devices"] = [d for d in data.get("devices", []) if d["key"] != key] + [dict(
        key=key, name=name, source="added in this app", enabled=True,
        master_uri=f"http://{host}:{master_port}" if master_port else "", bridge_url=f"ws://{host}:{bridge_port}" if bridge_port else "",
        ssh_host=host, ssh_user=ssh_user, ssh_port=int(ssh_port), color="#2a78d6")]
    LOCAL.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return key


def remove(key):
    data = _local()
    data["devices"] = [d for d in data.get("devices", []) if d["key"] != key]
    data.get("settings", {}).pop(key, None)
    LOCAL.write_text(json.dumps(data, indent=2), encoding="utf-8")
