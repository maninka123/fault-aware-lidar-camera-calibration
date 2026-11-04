"""Calibration maintenance - the logic behind the desktop app (app.py), without any GUI.

Reading and describing calibrations, calibrations typed in by hand, capture folders, the runs of
maintain.py (progress, summary, previous vs new values) and the history.
"""
from __future__ import annotations

import os

for _v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_v, "1")  # multi-threaded BLAS + OpenCV crash this numpy build

import csv  # noqa: E402
import itertools  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import re  # noqa: E402
from datetime import datetime  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402
from scipy.spatial.transform import Rotation  # noqa: E402

CODE = Path(__file__).resolve().parent
ROOT = CODE.parent
RESULTS = ROOT / "results"
INPUTS = RESULTS / "_inputs"
PROJECT = ROOT.parent
TARGETLESS = PROJECT / "Targetless calibration"
STAGES = ["data", "features", "health", "search", "refined", "evidence", "verdict"]


# ------------------------------------------------------------------ helpers
def fin(v):
    return isinstance(v, (int, float)) and math.isfinite(v)


def verdict_message(summary):
    """One short explanation and next step for the result banner."""
    shift = fmt(summary.get('shift_median_px'), 1, ' px')
    return {
        'LARGE CHANGE': f'Points move by {shift}. Check the mounting before accepting an update.',
        'UPDATE RECOMMENDED': f'The change is supported by the checks ({shift}). Review and accept the update.',
        'NO UPDATE NEEDED': 'The checks do not support an update. Keep the current calibration.',
        'BORDERLINE': 'The evidence is mixed. Keep the current calibration and collect more captures.',
        'INCONCLUSIVE': 'There is not enough evidence yet. Capture more edges at different distances.',
    }.get(summary.get('verdict'), 'Review the checks below before updating.')


def fmt(v, n=2, unit=""):
    return f"{v:.{n}f}{unit}" if fin(v) else "–"


def sgn(v, n=2, unit=""):
    return f"{'+' if v >= 0 else '−'}{abs(v):.{n}f}{unit}" if fin(v) else "–"


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None


def resolve(p):
    """Paths in summaries are relative to the code folder (where maintain.py runs)."""
    p = Path(p)
    return p if p.is_absolute() else (CODE / p).resolve()


def short(p):
    try:
        return str(Path(p).resolve().relative_to(PROJECT))
    except ValueError:
        return str(p)


# ------------------------------------------------------------------ calibration values
def _mountings():
    """The 24 axis-aligned ways a camera can be mounted on the LiDAR (rotation matrices)."""
    out = []
    for perm in itertools.permutations(range(3)):
        for signs in itertools.product((1, -1), repeat=3):
            M = np.zeros((3, 3))
            for r, (c, s) in enumerate(zip(perm, signs)):
                M[r, c] = s
            if np.linalg.det(M) > 0:
                out.append(M)
    return out


MOUNTINGS = _mountings()


def mounting_label(M):
    ax = lambda row: ("+" if row[int(np.argmax(np.abs(row)))] > 0 else "−") + "XYZ"[int(np.argmax(np.abs(row)))]
    return f"looks along LiDAR {ax(M[2])} · image right = LiDAR {ax(M[0])} · image down = LiDAR {ax(M[1])}"


def mounting_of(R):
    return int(max(range(len(MOUNTINGS)), key=lambda i: np.trace(R @ MOUNTINGS[i].T)))


def describe(c, mounting=None):
    """Intrinsics and extrinsics of a calibration.json in the units shown in the app.
    Rotation = the nearest axis-aligned mounting + small tilt / pan / roll about the camera axes
    (rotation vector of R·M^T, degrees): readable for any mounting, no gimbal lock."""
    K = np.array(c["intrinsics"]["camera_matrix"], float)
    D = np.r_[np.ravel(c["intrinsics"].get("distortion_coefficients", [])), np.zeros(4)][:4]
    T = np.array(c["extrinsics"]["transform_lidar_to_camera"], float)
    if K.shape != (3, 3) or T.shape != (4, 4):
        raise ValueError("camera_matrix must be 3x3 and transform_lidar_to_camera 4x4")
    R, t = T[:3, :3], T[:3, 3]
    m = mounting_of(R) if mounting is None else mounting
    fine = np.degrees(Rotation.from_matrix(R @ MOUNTINGS[m].T).as_rotvec())
    return dict(
        intrinsics=dict(fx=K[0, 0], fy=K[1, 1], cx=K[0, 2], cy=K[1, 2], k1=float(D[0]), k2=float(D[1]),
                        model=c["intrinsics"].get("distortion_model", "k1-k2" if D[1] else "k1"),
                        image_size=c.get("image_size")),
        extrinsics=dict(tx=t[0] * 1000, ty=t[1] * 1000, tz=t[2] * 1000, tilt=fine[0], pan=fine[1], roll=fine[2],
                        mounting=m, mounting_label=mounting_label(MOUNTINGS[m]), matrix=T),
        method=c.get("method") or "")


def calibration_info(path):
    c = read_json(path)
    if not isinstance(c, dict) or "intrinsics" not in c or "extrinsics" not in c:
        raise ValueError("This is not a calibration.json in this project's layout (it needs 'intrinsics' with "
                         "camera_matrix and 'extrinsics' with transform_lidar_to_camera).")
    return dict(path=str(Path(path).resolve()), name=short(path), **describe(c))


def numbers(text):
    return [float(v) for v in re.findall(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?", text or "")]


def manual_calibration(v):
    """Write a calibration.json from values typed into the app; returns its path."""
    f = lambda k, d=None: float(v[k]) if str(v.get(k, "")).strip() else d
    fx, fy, cx, cy = f("fx"), f("fy"), f("cx"), f("cy")
    if None in (fx, fy, cx, cy):
        raise ValueError("fx, fy, cx and cy are needed.")
    k1, k2 = f("k1", 0.0), f("k2", 0.0)
    T = np.eye(4)
    if v.get("ext_mode") == "matrix":
        n = numbers(v.get("matrix"))
        if len(n) not in (12, 16):
            raise ValueError(f"The LiDAR → camera matrix needs 12 or 16 numbers (found {len(n)}).")
        T[:3] = np.reshape(n[:12], (3, 4))
        if abs(T[:3, 3]).max() > 20:
            T[:3, 3] /= 1000.0                   # given in millimetres
        U, _, Vt = np.linalg.svd(T[:3, :3])
        if np.abs(T[:3, :3] - U @ Vt).max() > 1e-2:
            raise ValueError("The rotation part of the matrix is not a rotation (its rows must be orthonormal).")
        T[:3, :3] = U @ Vt
    else:
        T[:3, :3] = Rotation.from_rotvec(np.radians([f("tilt", 0.0), f("pan", 0.0), f("roll", 0.0)])).as_matrix() \
            @ MOUNTINGS[int(v.get("mounting", 0))]
        T[:3, 3] = np.array([f("tx", 0.0), f("ty", 0.0), f("tz", 0.0)]) / 1000.0
    c = dict(method="entered by hand in the maintenance app", convention="p_camera = R @ p_lidar + t (metres); OpenCV fisheye model",
             intrinsics=dict(distortion_model="k1-k2" if k2 else "k1", camera_matrix=[[fx, 0, cx], [0, fy, cy], [0, 0, 1]],
                             distortion_coefficients=[k1, k2, 0.0, 0.0]),
             extrinsics=dict(transform_lidar_to_camera=T.tolist()))
    if f("width") and f("height"):
        c["image_size"] = [int(f("width")), int(f("height"))]
    dst = INPUTS / f"entered_{datetime.now():%Y%m%d_%H%M%S}.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(c, indent=2))
    return dst


# ------------------------------------------------------------------ capture folders
def data_kind(folder):
    folder = Path(folder)
    try:
        if any((p / "rig_0.bag").exists() for p in folder.glob("capture_*")):
            return "raw"
        if next(folder.glob("*.npz"), None) is not None:
            return "stacked"
    except OSError:
        pass
    return None


def inspect_data(folder):
    folder = Path(folder)
    kind = data_kind(folder)
    if kind == "raw":
        caps = [dict(name=p.name, size_mb=(p / "rig_0.bag").stat().st_size / 1e6, npz=None)
                for p in sorted(folder.glob("capture_*")) if (p / "rig_0.bag").exists()]
    elif kind == "stacked":
        caps = [dict(name=p.stem, size_mb=p.stat().st_size / 1e6, npz=str(p)) for p in sorted(folder.glob("*.npz"))]
    else:
        raise ValueError("No captures in this folder: expected capture_*/rig_0.bag (raw) or *.npz (stacked).")
    return dict(path=str(folder.resolve()), name=short(folder), kind=kind, captures=caps)


def capture_image(npz):
    """The stacked camera image of a capture (uint8, gray or BGR)."""
    img = np.load(npz)["image"]
    if img.dtype != np.uint8:
        img = (255 * (img - img.min()) / max(float(np.ptp(img)), 1e-9)).astype(np.uint8)
    return np.ascontiguousarray(img)


def suggestions():
    """Calibrations and capture folders offered in the app."""
    cals = [PROJECT / "results" / "2026_09_29_multi_capture" / s / "calibration.json" for s in ("enclosure_on", "enclosure_off")]
    cals += sorted((TARGETLESS / "results").glob("*/calibration.json"))
    cals += sorted((ROOT / "accepted").glob("*.json"), reverse=True) + sorted((ROOT / "examples").glob("*.json"))

    def label(p):
        if "accepted" in p.parts:
            return f"Accepted: {p.stem}"
        if "examples" in p.parts:
            return f"Test, simulated drift: {p.stem.replace('_', ' ')}"
        if "Targetless calibration" in p.parts:
            return f"Targetless: {p.parent.name.replace('_', ' ')}"
        return f"Checkerboard: Sep 29, {p.parent.name.replace('_', ' ')}"
    data = [p for p in sorted((TARGETLESS / "stacked_data").glob("*")) + sorted((TARGETLESS / "Testing datasets").glob("*"))
            if p.is_dir() and data_kind(p)]
    return (dict(calibrations=[(label(p), str(p)) for p in cals if p.exists()],
                 data=[(f"{'Raw' if data_kind(p) == 'raw' else 'Stacked'}: {p.name.replace('_', ' ')}", str(p)) for p in data]))


# ------------------------------------------------------------------ runs
PARAM_KEYS = {"rotation tilt (about camera x)": "tilt", "rotation pan (about camera y)": "pan",
              "rotation roll (about camera z)": "roll", "translation x": "tx", "translation y": "ty",
              "translation z": "tz", "fx": "fx", "fy": "fy", "cx": "cx", "cy": "cy", "k1": "k1", "k2": "k2"}


def run_name(device, suffix=""):
    return re.sub(r"[^A-Za-z0-9_-]+", "_", (device or "rig").strip()) + suffix + f"_{datetime.now():%Y%m%d_%H%M%S}"


def new_run(calibration, data, mode, device, name=None, script="maintain.py"):
    """Prepare results/<run>/ and return (name, folder, script arguments). script: maintain.py, or
    full_calibration.py (calibration from scratch first)."""
    device = (device or "rig").strip()
    name = name or run_name(device)
    out = RESULTS / name
    out.mkdir(parents=True, exist_ok=True)
    (out / "progress.json").write_text(json.dumps(dict(run=name, finished=False, stages=[])))
    (out / "inputs.json").write_text(json.dumps(dict(calibration=str(calibration), data=str(data), mode=mode, device=device, script=script)))
    args = [str(CODE / script), "--calibration", str(calibration), "--data", str(data), "--name", name, "--device", device]
    if script == "maintain.py":
        args += ["--mode", mode]
    return name, out, args


def mark_history(run, text):
    """Note in history.csv's 'accepted' column (an accepted file or a write to the device)."""
    h = RESULTS / "history.csv"
    rows = history()
    if not rows:
        return
    for r in rows:
        if r["run"] == run:
            r["accepted"] = text
    with h.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def comparison(s, out):
    """Previous vs new value of every intrinsic / extrinsic, with the statistics of the change."""
    prev_c, new_c = read_json(resolve(s["existing"])), read_json(Path(out) / "refined_calibration.json")
    if not prev_c or not new_c:
        return None
    a = describe(prev_c)
    b = describe(new_c, a["extrinsics"]["mounting"])
    stats = {PARAM_KEYS[p["parameter"]]: p for p in s["parameters"] if p["parameter"] in PARAM_KEYS}
    rows = []
    for group, keys in (("intrinsics", ("fx", "fy", "cx", "cy", "k1", "k2")),
                        ("extrinsics", ("tx", "ty", "tz", "tilt", "pan", "roll"))):
        for k in keys:
            st = stats.get(k) or {}
            rows.append(dict(group=group, key=k, previous=a[group][k], new=b[group][k], change=b[group][k] - a[group][k],
                             refined=bool(st) or (group == "intrinsics" and s["mode"] == "full"),
                             uncertainty=st.get("uncertainty"), z=st.get("z"), statistical=st.get("statistical"),
                             pixel_effect=st.get("pixel_effect_px"), practical=st.get("practical")))
    return dict(previous=a, new=b, rows=rows)


def run_info(name):
    """Everything the app shows about a run: progress, inputs, and (when finished) the results."""
    out = RESULTS / name
    prog = read_json(out / "progress.json") or dict(stages=[], finished=False)
    stages = [dict(st, images=[str(out / i) for i in st.get("images", [])]) for st in prog.get("stages", [])]
    s = read_json(out / "summary.json") if prog.get("finished") else None
    inputs = read_json(out / "inputs.json") or {}
    if s:
        inputs = dict(calibration=str(resolve(s["existing"])), data=str(resolve(s["data"])), mode=s["mode"], device=s["device"])
    log = out / "run.log"
    info = dict(name=name, out=out, finished=bool(prog.get("finished")), stages=stages, inputs=inputs,
                log=log.read_text(errors="replace").splitlines()[-40:] if log.exists() else [], summary=s,
                device=read_json(out / "device.json"), device_writes=read_json(out / "device_writes.json") or [])
    if s:
        imgs = out / "images"
        info.update(comparison=comparison(s, out), accepted=accepted_of(name),
                    captures=[dict(name=p.stem, image=p, flicker=imgs / f"{p.stem}_flicker.gif")
                              for p in sorted(imgs.glob("*.png")) if p.stem != "shift_by_range"],
                    extra=[p for p in (imgs / "shift_by_range.png", out / "stages" / "regions.png") if p.exists()])
    return info


def list_runs():
    rows = []
    for p in RESULTS.iterdir() if RESULTS.exists() else []:
        prog = read_json(p / "progress.json")
        if not prog:
            continue
        s = read_json(p / "summary.json") if prog.get("finished") else None
        inp = read_json(p / "inputs.json") or {}
        rows.append(dict(name=p.name, time=(p / "progress.json").stat().st_mtime, finished=bool(prog.get("finished")),
                         verdict=s and s["verdict"], shift=s and s["shift_median_px"],
                         device=(s and s["device"]) or inp.get("device") or "", date=s and s["date"]))
    accepted = {r["run"] for r in history() if r.get("accepted")}
    for r in rows:
        r["accepted"] = r["name"] in accepted
    return sorted(rows, key=lambda r: r["time"], reverse=True)


def history():
    h = RESULTS / "history.csv"
    if not h.exists():
        return []
    with h.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def accepted_of(name):
    return next((r["accepted"] for r in history() if r["run"] == name and r.get("accepted")), None)
