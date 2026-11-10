"""Mass capture: plan every combination of environment, LiDAR, camera resolution and intrinsics drift.

Planning and bookkeeping only (no rendering), so the web page, the server and the tests share one definition.
Every combination becomes one ordinary, self-contained run folder (inference/ + evaluation/) saved directly in the
folder the user chose, exactly like a single capture run, so a mass capture that stopped half way can be started again
with the same options in the same folder: finished runs are recognised and skipped, unfinished ones are redone.
Poses and mount changes are seeded per environment: every sensor and resolution of an environment sees the same
poses and the same simulated mount changes, and the drift on/off pair differs only in the camera intrinsics.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import shutil
from datetime import datetime
from pathlib import Path

LIDAR_CODE = dict(livox_avia="avia", livox_mid360="mid360", velodyne_vlp16="vlp16", ouster_os1_64="os1", hesai_at128="at128")
CAMERA_CODE = dict(fisheye="fish", pinhole="pin")
DRIFT_MODES = {"off": [False], "on": [True], "both": [False, True]}
MAX_RUNS = 200
MAX_PIXELS = 1_048_576
PATH_LIMIT = 255                                  # Windows MAX_PATH is 260 including the terminator
LONGEST_INSIDE_RUN = len("\\evaluation\\capture_0099\\ideal_lidar_accumulated.npz") + 8
ASIDE = "_incomplete"                             # unfinished attempts are moved here, never deleted
SETTINGS = ("renderer", "samples", "cube_size", "duration", "accumulate", "stride", "interval", "seed")   # change the data itself


def combo_name(scene, lidar, model, width, height, drift, captures):
    """Short, readable and stable, e.g. warehouse_avia_fish_1024x768_drift_25 (the last number is the captures per run)."""
    return f"{scene}_{LIDAR_CODE.get(lidar, lidar)}_{CAMERA_CODE[model]}_{width}x{height}_{'drift' if drift else 'fixed'}_{captures}"


def _number(spec, key, label, lo, hi, kind=float, default=None):
    raw = spec.get(key, default)
    try:
        value = kind(raw)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a number.") from None
    if not math.isfinite(value) or not lo <= value <= hi:
        raise ValueError(f"{label} must be between {lo:g} and {hi:g}.")
    return value


def _choose(values, allowed, label):
    values = list(dict.fromkeys(values or []))
    if not values:
        raise ValueError(f"Choose at least one {label}.")
    unknown = [v for v in values if v not in allowed]
    if unknown:
        raise ValueError(f"Unknown {label}: {', '.join(map(str, unknown))}")
    return [v for v in allowed if v in values]  # keep the application's order, so naming/order is stable


def _digest(obj, length=16):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:length]


def parse_spec(spec, scenes, lidars):
    """Validate a mass-capture request. Returns (parameters, combinations); raises ValueError with a readable message."""
    scene_list = _choose(spec.get("scenes"), scenes, "environment")
    lidar_list = _choose(spec.get("lidars"), lidars, "LiDAR")
    settings = []
    for cam in spec.get("cameras") or []:
        model = cam.get("model")
        if model not in CAMERA_CODE:
            raise ValueError(f"Unknown camera model: {model}")
        for res in cam.get("resolutions") or []:
            try:
                w, h = int(res[0]), int(res[1])
            except (TypeError, ValueError, IndexError):
                raise ValueError("Each resolution needs a width and a height.") from None
            if min(w, h) < 2 or w * h > MAX_PIXELS:
                raise ValueError(f"Resolution {w}x{h} is not allowed (at least 2 px per side, at most {MAX_PIXELS:,} pixels).")
            if (model, w, h) not in settings:
                settings.append((model, w, h))
    if not settings:
        raise ValueError("Choose at least one camera resolution.")
    drift = spec.get("drift", "off")
    if drift not in DRIFT_MODES:
        raise ValueError("Intrinsics drift must be off, on or both.")
    batches = _number(spec, "batches", "Batches", 1, 20, int, 1)
    per_batch = _number(spec, "per_batch", "Captures per batch", 1, 50, int, 5)
    captures = batches * per_batch
    if captures > 100:
        raise ValueError(f"At most 100 captures per run (you asked for {captures}).")
    if True in DRIFT_MODES[drift] and batches < 2:
        raise ValueError("Intrinsics drift needs at least 2 batches: batch 1 always keeps the nominal intrinsics.")
    rig = spec.get("rig") or []
    mount = spec.get("base_mount") or []
    if len(rig) != 3 or len(mount) != 6 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in list(rig) + list(mount)):
        raise ValueError("The rig height/tilt and the camera mount are needed.")
    params = dict(batches=batches, per_batch=per_batch, captures=captures, drift=drift,
                  rot=_number(spec, "rot", "Mount rotation tolerance", 0, 10, float, 0),
                  trans=_number(spec, "trans", "Mount translation tolerance", 0, 100, float, 0),
                  focal_percent=_number(spec, "focal_percent", "Focal tolerance", 0, 5, float, .3),
                  principal_px=_number(spec, "principal_px", "Principal point tolerance", 0, 10, float, .5),
                  distortion_delta=_number(spec, "distortion_delta", "Distortion tolerance", 0, .001, float, 0),
                  base_focal=_number(spec, "base_focal", "Focal length", 1e-6, 1e6, float),
                  base_width=_number(spec, "base_width", "Image width", 2, 1e5, int),
                  rig=[float(v) for v in rig], base_mount=[float(v) for v in mount])
    typed = spec.get("pose_seed")          # not "seed": that key is the simulator's own random seed
    if typed in (None, ""):
        # The poses must be the same whenever the same options are chosen again, so a rerun matches the earlier runs.
        params["seed"] = int(_digest(dict(b=batches, n=per_batch, rot=params["rot"], tr=params["trans"], rig=params["rig"], m=params["base_mount"]), 8), 16) % 2 ** 31
        params["seed_auto"] = True
    else:
        params["seed"] = _number(spec, "pose_seed", "Pose seed", 0, 2 ** 31 - 1, int)
        params["seed_auto"] = False
    combos = []
    for scene in scene_list:
        for lidar in lidar_list:
            for model, w, h in settings:
                for d in DRIFT_MODES[drift]:
                    combos.append(dict(index=len(combos), name=combo_name(scene, lidar, model, w, h, d, captures), scene=scene, lidar=lidar, drift=d,
                                       camera=dict(model=model, width=w, height=h, focal_px=round(params["base_focal"] * w / params["base_width"], 2))))
    if len(combos) > MAX_RUNS:
        raise ValueError(f"{len(combos)} runs is too many in one mass capture (the limit is {MAX_RUNS}). Choose fewer options.")
    return params, combos


def fingerprint(combo, params, spec):
    """Identity of everything that decides a run's data. Two runs with the same fingerprint are interchangeable."""
    own = dict(combo=dict(scene=combo["scene"], lidar=combo["lidar"], camera=combo["camera"], drift=combo["drift"]),
               plan={k: params[k] for k in ("batches", "per_batch", "rot", "trans", "seed", "rig", "base_mount")},
               settings={k: str(spec.get(k)) for k in SETTINGS})
    if combo["drift"]:
        own["drift_limits"] = {k: params[k] for k in ("focal_percent", "principal_px", "distortion_delta")}
    return _digest(own)


def existing_status(parent, name, fp):
    """What is already at parent/name: new (nothing), done (finished, same settings), incomplete (stopped half way), different."""
    folder = Path(parent) / name
    if not folder.exists():
        return "new"
    if not (folder / "evaluation" / "manifest.json").is_file():      # written last: its absence means the run did not finish
        return "incomplete"
    try:
        saved = json.loads((folder / "evaluation" / "config.json").read_text(encoding="utf-8")).get("mass", {}).get("fingerprint")
    except (OSError, ValueError, AttributeError):
        saved = None
    return "done" if saved == fp else "different"


def copy_name(parent, name):
    """First free <name>_v2, <name>_v3, ... so an existing folder is never reused."""
    n = 2
    while (Path(parent) / f"{name}_v{n}").exists():
        n += 1
    return f"{name}_v{n}"


def resume_info(parent, name, fp, captures):
    """For an unfinished run: how many captures are already complete, and whether it can be continued (same settings)."""
    ev = Path(parent) / name / "evaluation"
    done = len(list(ev.glob("capture_*/verification.json")))
    try:
        saved = json.loads((ev / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return dict(resumable=False, done=done)
    same = (saved.get("mass") or {}).get("fingerprint") == fp and int(saved.get("captures") or 0) == captures
    return dict(resumable=bool(same), done=done)


def plan_runs(spec, scenes, lidars, parent):
    """parse_spec plus, for every combination, its fingerprint and what already sits in the save folder.

    ``existing`` is what was found. With spec["skip_existing"] true (the default) finished or clashing folders are skipped; with it
    false each gets a new copy under a free name (_v2, _v3, ...). Existing data is never overwritten either way. Unfinished
    attempts are always redone (the partial folder is moved aside first).
    """
    params, combos = parse_spec(spec, scenes, lidars)
    skip = spec.get("skip_existing", True) is not False
    mode = "redo" if spec.get("unfinished") == "redo" else "continue"      # what to do with a run that stopped part-way
    for c in combos:
        c["fingerprint"] = fingerprint(c, params, spec)
        c["existing"] = existing_status(parent, c["name"], c["fingerprint"]) if parent else "new"
        c["status"], c["copy"] = c["existing"], False
        c["continue"], c["resume"] = False, dict(resumable=False, done=0)
        if c["existing"] == "incomplete":
            c["resume"] = resume_info(parent, c["name"], c["fingerprint"], params["captures"])
            c["continue"] = mode == "continue" and c["resume"]["resumable"]
        if c["existing"] in ("done", "different") and not skip:
            c["name"], c["status"], c["copy"] = copy_name(parent, c["name"]), "new", True
    return params, combos


def describe_run(folder):
    """What a saved run folder is (from its own evaluation/ files), or None when it does not look like a run."""
    folder = Path(folder)
    try:
        config = json.loads((folder / "evaluation" / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    camera, render, tag = config.get("camera") or {}, config.get("render") or {}, config.get("mass") or {}
    ids = [b for b in config.get("batch_ids") or [] if isinstance(b, int) and b >= 0]
    batches = len(set(ids))
    drift = tag.get("intrinsics_drift")
    if drift is None and batches > 1:
        try:
            cameras = [json.dumps(b.get("camera"), sort_keys=True) for b in json.loads((folder / "evaluation" / "batches.json").read_text(encoding="utf-8"))]
            drift = len(set(cameras)) > 1
        except (OSError, ValueError, AttributeError):
            drift = None
    captures = int(config.get("captures") or 0)
    done = len(list((folder / "evaluation").glob("capture_*/verification.json")))
    return dict(name=folder.name, captures_done=done, scene=config.get("scene"), lidar=config.get("lidar"), model=camera.get("model"), width=camera.get("width"),
                height=camera.get("height"), drift=drift, batches=batches, captures=captures, per_batch=captures // batches if batches else captures,
                samples=render.get("samples"), cube=render.get("cubemap_size"), renderer=config.get("renderer"),
                finished=(folder / "evaluation" / "manifest.json").is_file(), from_mass=bool(tag), fingerprint=tag.get("fingerprint"))


def scan_folder(parent, limit=500):
    """Every run folder directly inside ``parent``: what it holds and whether it finished. Read-only."""
    parent = Path(parent)
    runs, other, aside = [], 0, 0
    for entry in sorted(os.scandir(parent), key=lambda e: e.name.lower()):
        if not entry.is_dir():
            continue
        if entry.name == ASIDE:
            aside = sum(e.is_dir() for e in os.scandir(entry.path))
            continue
        info = describe_run(entry.path)
        if info is None:
            if (Path(entry.path) / "inference").is_dir() or (Path(entry.path) / "evaluation").is_dir():
                other += 1            # looks like a run that stopped before it wrote its config
            continue
        runs.append(info)
        if len(runs) >= limit:
            break
    return dict(folder=str(parent), runs=runs, finished=sum(r["finished"] for r in runs), unfinished=sum(not r["finished"] for r in runs),
                unreadable=other, set_aside=aside)


def set_aside(parent, name):
    """Move an unfinished attempt to <parent>/_incomplete/<name>_<time> so the run can start clean. Nothing is deleted."""
    target = Path(parent) / ASIDE
    target.mkdir(exist_ok=True)
    destination = target / f"{name}_{datetime.now():%Y%m%d_%H%M%S}"
    shutil.move(str(Path(parent) / name), str(destination))
    return destination


def check_paths(parent, combos):
    """Refuse a save location whose deepest file would exceed the Windows path limit (260 characters)."""
    longest = max(len(c["name"]) for c in combos)
    total = len(str(Path(parent).resolve())) + 1 + longest + LONGEST_INSIDE_RUN
    if total > PATH_LIMIT:
        raise ValueError(f"The save folder path is too long ({total} characters needed, Windows allows {PATH_LIMIT}). Choose a shorter folder.")


def plan_combo(combo, params):
    """Poses, per-capture mounts and cameras for one run (what the Studio's batch mode would create)."""
    from .studio import batch_plan
    plan = batch_plan(combo["scene"], params["batches"], params["per_batch"], params["rot"], params["trans"], params["base_mount"],
                      params["rig"][0], params["rig"][1], params["rig"][2], params["seed"], camera_cfg=combo["camera"],
                      vary_intrinsics=combo["drift"], focal_percent=params["focal_percent"],
                      principal_px=params["principal_px"], distortion_delta=params["distortion_delta"])
    out = dict(poses=[], mounts=[], batch_ids=[], cameras=[], batches=[])
    for b in plan:
        out["batches"].append(dict(batch=b["batch"], mount=b["mount"], camera=b["camera"], start=len(out["poses"]), count=len(b["poses"])))
        for p in b["poses"]:
            out["poses"].append(p)
            out["mounts"].append(b["mount"])
            out["batch_ids"].append(b["batch"])
            out["cameras"].append(b["camera"])
    return out


CSV_COLUMNS = ["run", "batch", "captures", "fx", "fy", "cx", "cy", "k1", "rotation_deg", "translation_mm",
               "fx_percent", "fy_percent", "cx_px", "cy_px", "k1_change"]


def summary_rows(run_dir, name):
    """One row per batch: the true intrinsics and how far the mount/intrinsics sit from nominal (ground truth)."""
    path = Path(run_dir) / "evaluation" / "batches.json"
    if not path.is_file():
        return []
    rows = []
    for b in json.loads(path.read_text(encoding="utf-8")):
        K, D, change = b["camera"]["K"], b["camera"]["D"], b.get("change_from_nominal") or {}
        rows.append(dict(run=name, batch=b["batch"] + 1, captures=len(b["capture_ids"]), fx=K[0][0], fy=K[1][1], cx=K[0][2], cy=K[1][2],
                         k1=D[0], rotation_deg=change.get("rotation_deg"), translation_mm=change.get("translation_mm"),
                         fx_percent=change.get("fx_percent"), fy_percent=change.get("fy_percent"), cx_px=change.get("cx_px"),
                         cy_px=change.get("cy_px"), k1_change=change.get("k1")))
    return rows


def write_run_csv(run_dir, name):
    """evaluation/intrinsics_by_batch.csv inside the run itself, so the folder stays self-contained."""
    rows = summary_rows(run_dir, name)
    if not rows:
        return None
    path = Path(run_dir) / "evaluation" / "intrinsics_by_batch.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return path
