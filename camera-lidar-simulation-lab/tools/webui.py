"""Browser-based launcher (local only, standard library server).

    python tools/webui.py            # opens http://127.0.0.1:8765
Opening the page never renders. Jobs run only when you press Generate / Build / Test GPU.
POST requests need the per-session token embedded in the page, so other websites cannot trigger jobs.
"""
from __future__ import annotations
import base64
import io
import json
import os
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from launcher import (LIDARS, QUALITIES, SCENE_INFO, SCENES, default_values, find_blender,  # noqa: E402
                      make_config, new_output)
from simulator.gpu import best_device, blender_devices, live_stats, nvidia_info  # noqa: E402
from simulator.lidar import LidarModel  # noqa: E402
from simulator.previews import LIDAR_VIEW, camera_preview, lidar_preview, scan_pattern  # noqa: E402
from simulator.resources import LOAD_LEVELS, apply_load_limits, child_environment  # noqa: E402
from simulator import mass, studio  # noqa: E402
from launcher import triple  # noqa: E402

TOKEN = secrets.token_urlsafe(16)
PORT = int(os.environ.get("SIMLAB_PORT", 8765))  # SIMLAB_PORT lets a second copy run for testing
HTML_PATH = ROOT / "tools" / "web" / "index.html"
LOCK = threading.Lock()
PICKER_LOCK = threading.Lock()
JOB = dict(running=False, lines=[], code=None, title="", last_run=None, device=None, progress=None, step="", started=None,
           proc=None, cancelled=False, output=None, last_scene=None, mass=None)
_cache: dict = {}
LOAD = dict(level="responsive", announced=False)   # how much of the PC the running job may take


def describe(error):
    """Readable text for an exception (a bare KeyError would show just the key name)."""
    return f"Missing setting: {error.args[0]}" if isinstance(error, KeyError) and error.args else str(error)


def png_bytes(img):
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def scan_cache(profile):
    key = ("scan", profile)
    if key not in _cache:
        _cache[key] = scan_pattern(profile, 1.0, 12000)
    return _cache[key]


def lidar_png(profile):
    if profile not in _cache:
        _cache[profile] = png_bytes(lidar_preview(profile, (352, 220)))
    return _cache[profile]


def log(line):
    with LOCK:
        JOB["lines"].append(line)


def start_job(title, target, on_done=None):
    with LOCK:
        if JOB["running"]:
            raise ValueError("Another job is running; wait for it to finish.")
        JOB.update(running=True, lines=[], code=None, title=title, progress=None, step="", started=time.time(),
                   proc=None, cancelled=False, mass=None)

    def worker():
        code = 1
        try:
            code = target()
            if code == 0 and on_done:
                on_done()  # still inside the job, so its log lines reach the page before it stops polling
        except Exception as error:  # reported in the log
            log(f"ERROR: {error}")
            code = 1 if code == 0 else code
        with LOCK:
            was_cancelled = JOB["cancelled"]
        if was_cancelled:  # logged before the job is marked finished so the page still receives it
            log("Cancelled by user." + (f" Files already written stay in {JOB['output']} (the run is incomplete)." if JOB.get("output") and title.startswith("Generating") else ""))
        with LOCK:
            JOB.update(running=False, code=code, proc=None, **(dict(progress=1.0) if code == 0 else {}))
    threading.Thread(target=worker, daemon=True).start()


def api_cancel():
    """Stop the running job and everything it started (Blender included). Files already written stay on disk."""
    with LOCK:
        proc = JOB["proc"]
        if not JOB["running"]:
            raise ValueError("Nothing is running.")
        JOB["cancelled"] = True
    if proc is not None and proc.poll() is None:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            proc.terminate()


_JOB_HANDLE = None


def _bind_to_server_lifetime(proc):
    """Windows: put the child (and Blender it starts) in a kill-on-close job object.

    If this server is closed or killed mid-run, the render stops with it instead of lingering on the GPU and
    holding the single-job lock. Best effort: any failure leaves normal behaviour unchanged.
    """
    global _JOB_HANDLE
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes

        class Basic(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

        class Counters(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in ("ReadOps", "WriteOps", "OtherOps", "ReadBytes", "WriteBytes", "OtherBytes")]

        class Extended(ctypes.Structure):
            _fields_ = [("Basic", Basic), ("Io", Counters), ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        if _JOB_HANDLE is None:
            handle = k32.CreateJobObjectW(None, None)
            info = Extended()
            info.Basic.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not handle or not k32.SetInformationJobObject(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
                return
            _JOB_HANDLE = handle
        k32.AssignProcessToJobObject(_JOB_HANDLE, wintypes.HANDLE(int(proc._handle)))
    except Exception:  # noqa: BLE001 - never let this helper break a run
        pass


def run_process(args):
    log("Running: " + subprocess.list2cmdline(args))
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    with subprocess.Popen(args, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                          encoding="utf-8", errors="replace", creationflags=flags, env=child_environment()) as p:
        _bind_to_server_lifetime(p)
        text = apply_load_limits(p.pid, LOAD["level"])
        if text and not LOAD["announced"]:
            LOAD["announced"] = True
            log(text)
        with LOCK:
            JOB["proc"] = p
        for line in p.stdout:
            if line.startswith("SIMLAB_PROGRESS "):
                try:
                    _, fraction, step = line.rstrip().split(" ", 2)
                    with LOCK:
                        changed = step != JOB["step"]
                        share = min(1.0, max(0.0, float(fraction)))
                        batch = JOB.get("mass")
                        if batch and batch.get("active"):  # a mass capture: this run is one slice of the whole job
                            share = (batch["index"] + share) / batch["total"]
                        JOB.update(progress=share, step=step)
                        started = JOB["started"] or time.time()
                    if changed:
                        seconds = int(time.time() - started)
                        log(f"[{seconds // 60}:{seconds % 60:02d}] {step}")
                except ValueError:
                    pass
                continue
            log(line.rstrip())
        return p.wait()


def render_flags(device):
    return ["--allow-render", "--device", device] + (["--allow-gpu"] if device in ("OPTIX", "CUDA") else [])


def summarize_run(output):
    """Results block for the Activity log: per-capture numbers from the manifest plus the independent verifier."""
    out = Path(output)
    manifest = json.loads((out / "evaluation" / "manifest.json").read_text(encoding="utf-8"))
    log("")
    log("=== Results ===")
    log(f"Run folder: {out}")
    log(f"Scene {manifest['scene']} | LiDAR {manifest['sensor']} | image source: {manifest['renderer']} | generated in {manifest['elapsed_s']:.1f} s")
    log("  #   LiDAR points  visible to camera  occluded  reprojection error")
    for i, c in enumerate(manifest["captures"], 1):
        err = c.get("max_ray_reprojection_error_px")
        log(f"  {i:<3} {c['valid_returns']:>12,}  {c['visible_to_camera']:>17,}  {c['occluded']:>8,}  {'n/a' if err is None else f'{err:.1e} px':>18}")
    truth = out / "evaluation" / "batches.json"
    if truth.is_file():
        for b in json.loads(truth.read_text(encoding="utf-8")):
            log(f"  Batch {b['batch'] + 1}: {len(b['capture_ids'])} captures share one true calibration")
    try:
        from simulator.validation import verify_run
        result = verify_run(out)
        log("Verification: " + ("PASSED" if result.get("passed") else "FAILED") + (" - " + "; ".join(result.get("errors", [])[:3]) if result.get("errors") else ""))
    except Exception as error:  # the run itself succeeded; only the check could not run
        log(f"Verification could not run: {error}")
    log("Measurements are in inference/, ground truth in evaluation/ (kept separate).")


def report_device(output):
    for path in sorted(Path(output).rglob("blender.log")):
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("SIMLAB_RENDER_RESULT "):
                dev = json.loads(line.split(" ", 1)[1]).get("device", {})
                log(f"Rendered on: {dev.get('actual')} ({', '.join(dev.get('devices', []))})")
                JOB["device"] = dev.get("actual")
                return


def blender_path(values):
    p = Path(values["blender"])
    if not p.is_file():
        raise ValueError("Blender executable not found; set it under More settings.")
    return str(p)


def set_load(values):
    """Remember the PC-responsiveness choice for the job that is about to start."""
    level = str(values.get("load") or "responsive")
    LOAD.update(level=level if level in LOAD_LEVELS else "responsive", announced=False)


def api_generate(values):
    set_load(values)
    if not str(values.get("output", "")).strip():
        raise ValueError("Choose an output folder.")
    output = Path(values["output"]).expanduser().resolve()
    if output.exists():
        raise ValueError("Output folder already exists; use 'New run name' under More settings.")
    config = make_config(values)
    directory = ROOT / "configs" / "gui"
    directory.mkdir(parents=True, exist_ok=True)
    cfg = directory / f"experiment_{output.name}.yaml"
    n = 2
    while cfg.exists():  # the folder name was used before (e.g. its run was deleted): keep the old config, use a new file
        cfg = directory / f"experiment_{output.name}-{n}.yaml"
        n += 1
    with cfg.open("x", encoding="utf-8") as s:
        yaml.safe_dump(config, s, sort_keys=False)
    cmd = [sys.executable, "-m", "simulator", "generate", str(cfg)]
    if values["renderer"] == "blender":
        cmd += ["--blender", blender_path(values)] + render_flags(values["device"])
    JOB["device"] = None

    JOB["output"] = str(output)

    def target():
        return run_process(cmd)

    def done():
        JOB["last_run"] = str(output)
        JOB["last_scene"] = config["scene"]
        report_device(output)
        summarize_run(output)
    start_job("Generating captures", target, done)


def mass_plan(values):
    """Validate a mass-capture request against the chosen save folder: (folder, parameters, combinations with their status)."""
    parent = Path(str(values.get("parent") or "")).expanduser()
    if not parent.is_dir():
        raise ValueError("Choose the folder to save into first.")
    parent = parent.resolve()
    params, combos = mass.plan_runs(values, SCENES, LIDARS, parent)
    mass.check_paths(parent, combos)
    return parent, params, combos


def api_mass_check(values):
    """What a mass capture would do in the chosen folder: which runs are saved already, unfinished, or clash with other data."""
    parent, params, combos = mass_plan(values)
    todo = [c for c in combos if c["status"] in ("new", "incomplete")]
    caps = {}                                    # captures still to render, per camera model (a continued run only needs its missing ones)
    for c in todo:
        left = params["captures"] - (c["resume"]["done"] if c["continue"] else 0)
        caps[c["camera"]["model"]] = caps.get(c["camera"]["model"], 0) + left
    count = lambda status: sum(c["existing"] == status for c in combos)  # noqa: E731
    return dict(total=len(combos), new=count("new"), incomplete=count("incomplete"), done=count("done"), different=count("different"),
                copies=sum(c["copy"] for c in combos), todo=len(todo), todo_captures=sum(caps.values()), todo_caps=caps,
                continuing=sum(c["continue"] for c in todo), kept_captures=sum(c["resume"]["done"] for c in todo if c["continue"]),
                seed=params["seed"], seed_automatic=params["seed_auto"],
                unfinished=[dict(name=c["name"], done=c["resume"]["done"], total=params["captures"], will_continue=c["continue"]) for c in combos if c["existing"] == "incomplete"],
                saved={c["name"]: c["existing"] for c in combos if c["existing"] != "new"})


def api_mass_scan(values):
    """Read-only look at the chosen folder: which runs are saved there, how many batches, and whether each finished."""
    parent = Path(str(values.get("parent") or "")).expanduser()
    if not parent.is_dir():
        raise ValueError("Choose the folder to save into first.")
    return mass.scan_folder(parent.resolve())


def api_mass(values):
    """Mass capture: one self-contained run folder per configuration, saved directly in the chosen folder.

    Runs already saved there with the same settings are skipped and unfinished ones are redone, so a stopped mass capture
    can simply be started again with the same options. Nothing existing is deleted or overwritten.
    """
    with LOCK:
        if JOB["running"]:
            raise ValueError("Another job is running; wait for it to finish.")
    set_load(values)
    parent, params, combos = mass_plan(values)
    renderer = values.get("renderer", "blender")
    blender = blender_path(values) if renderer == "blender" else None
    todo = [c for c in combos if c["status"] in ("new", "incomplete")]
    if not todo:
        raise ValueError("Everything you selected is already saved in this folder, so there is nothing to capture.")
    for scene in sorted({c["scene"] for c in todo}):
        folder = ROOT / "blender" / "scenes" / scene
        if not (folder / "mesh.npz").is_file() or (renderer == "blender" and not (folder / "scene.blend").is_file()):
            raise ValueError(f"Build the {scene} scene first (Setup, More settings, Build missing scene).")
    total, captures = len(todo), params["captures"]
    initial = dict(new="not run yet", incomplete="not run yet", done="skipped", different="conflict")
    runs = [dict(name=c["name"], scene=c["scene"], lidar=c["lidar"], camera=c["camera"], intrinsics_drift=c["drift"], status=initial[c["status"]]) for c in combos]
    JOB["device"] = None
    JOB["output"] = str(parent)

    def target():
        failed = 0
        saved, clashes = sum(c["status"] == "done" for c in combos), sum(c["status"] == "different" for c in combos)
        copies = sum(c["copy"] for c in combos)
        if saved:
            log(f"{saved} configuration{'s' if saved != 1 else ''} already saved in this folder with the same settings: skipped.")
        if clashes:
            log(f"{clashes} folder{'s' if clashes != 1 else ''} with a matching name but different settings left untouched (not overwritten).")
        if copies:
            log(f"{copies} configuration{'s' if copies != 1 else ''} already saved here: new copies are made next to them (named _v2, _v3, ...); the existing ones are not touched.")
        with tempfile.TemporaryDirectory(prefix="simlab_mass_") as scratch:
            for pos, combo in enumerate(todo):
                with LOCK:
                    if JOB["cancelled"]:
                        break
                entry, cam, begin = runs[combo["index"]], combo["camera"], time.time()
                try:
                    if combo["status"] == "incomplete" and combo["continue"]:
                        left = captures - combo["resume"]["done"]
                        log(f"Continuing {combo['name']}: {combo['resume']['done']} of {captures} captures were already complete and are kept; "
                            f"capturing the remaining {left}.")
                    elif combo["status"] == "incomplete":
                        moved = mass.set_aside(parent, combo["name"])
                        log(f"An unfinished earlier attempt of {combo['name']} was moved to {mass.ASIDE}\\{moved.name} and the run starts fresh.")
                    plan = mass.plan_combo(combo, params)
                    run_values = dict(values, scene=combo["scene"], lidar=combo["lidar"], camera=cam["model"], width=str(cam["width"]),
                                      height=str(cam["height"]), focal=str(cam["focal_px"]), poses=plan["poses"], mounts=plan["mounts"],
                                      batch_ids=plan["batch_ids"], cameras=plan["cameras"], output=str(parent / combo["name"]))
                    config = make_config(run_values)
                    # identity of this run, saved inside the run itself (evaluation/config.json): a later mass capture recognises it
                    config["mass"] = dict(fingerprint=combo["fingerprint"], name=combo["name"], intrinsics_drift=combo["drift"],
                                          batches=params["batches"], captures_per_batch=params["per_batch"], plan_seed=params["seed"],
                                          plan_seed_automatic=params["seed_auto"])
                    cfg = Path(scratch) / f"{combo['name']}.yaml"
                    cfg.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
                    with LOCK:
                        entry.update(status="running", started=time.time())
                        JOB["mass"] = dict(active=True, index=pos, total=total, name=combo["name"], scene=combo["scene"], lidar=combo["lidar"], runs=runs,
                                           camera=dict(model=cam["model"], width=cam["width"], height=cam["height"], focal=cam["focal_px"]),
                                           drift=combo["drift"], poses=plan["poses"], batch_ids=plan["batch_ids"], batches=plan["batches"],
                                           nominal=nominal_camera(combo), folder=str(parent))
                    log("")
                    log(f"=== Configuration {pos + 1} of {total}: {combo['name']} ({captures} captures) ===")
                    cmd = [sys.executable, "-m", "simulator", "generate", str(cfg)]
                    if combo["continue"]:
                        cmd += ["--resume"]
                    if renderer == "blender":
                        cmd += ["--blender", blender] + render_flags(values["device"])
                    code = run_process(cmd)
                    with LOCK:
                        cancelled = JOB["cancelled"]
                    if cancelled:
                        with LOCK:
                            entry["status"] = "cancelled"
                        break
                    if code:
                        raise RuntimeError(f"the generator stopped with exit code {code} (see the log above)")
                    out = parent / combo["name"]
                    try:
                        from simulator.validation import verify_run
                        result = verify_run(out)
                    except Exception as error:  # noqa: BLE001 - the run itself succeeded
                        result = dict(passed=None, errors=[f"verification could not run: {error}"])
                    try:
                        mass.write_run_csv(out, combo["name"])
                    except OSError:
                        pass  # the same numbers are in evaluation/batches.json
                    with LOCK:
                        entry.update(status="done", seconds=round(time.time() - begin, 1), verification_passed=result.get("passed"),
                                     verification_errors=(result.get("errors") or [])[:3])
                    JOB["last_run"], JOB["last_scene"] = str(out), combo["scene"]
                    if JOB["device"] is None:
                        report_device(out)
                    log(f"Configuration {pos + 1} of {total} done in {entry['seconds']:.0f} s. Verification: "
                        + ("PASSED" if result.get("passed") else "FAILED" if result.get("passed") is False else "not run"))
                except Exception as error:  # noqa: BLE001 - one failed configuration must not lose the rest of the mass capture
                    failed += 1
                    with LOCK:
                        entry.update(status="failed", seconds=round(time.time() - begin, 1),
                                     error=describe(error) if isinstance(error, KeyError) else str(error))
                    log(f"Configuration {pos + 1} of {total} FAILED: {entry['error']}")
        with LOCK:
            if JOB["mass"]:
                JOB["mass"]["active"] = False
            cancelled = JOB["cancelled"]
        done = sum(r["status"] == "done" for r in runs)
        log("")
        log(f"=== Mass capture {'stopped' if cancelled else 'finished'}: {done} of {total} configurations saved now"
            + (f", {saved} were already saved" if saved else "") + (f", {failed} failed" if failed else "") + " ===")
        log(f"Each configuration is its own folder in: {parent}")
        if done < total:
            log("To finish the rest, open Mass capture again with the same options and the same folder: saved ones are skipped, only the missing ones run.")
        return 0 if (done == total and not cancelled) else 1
    start_job("Generating mass capture", target)


def nominal_camera(combo):
    """Nominal camera of a combination (batch 1), used by the page to show how far later batches drift."""
    from simulator.camera import Camera
    return Camera.from_dict(combo["camera"]).to_dict()


def api_choose_output(values=None, parent_only=False):
    values = values or {}
    scene = str(values.get("scene", "warehouse"))
    captures = int(values.get("captures") or 1)
    with LOCK:
        if JOB["running"]:
            raise ValueError("Wait for the current capture job to finish.")
    if not PICKER_LOCK.acquire(blocking=False):
        raise ValueError("The save-folder picker is already open.")
    try:
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        result = subprocess.run([sys.executable, str(ROOT / "tools/pick_output.py"), scene, str(captures)] + (["parent"] if parent_only else []), cwd=ROOT,
                                capture_output=True, text=True, encoding="utf-8", errors="replace",
                                creationflags=flags, env=child_environment())
        if result.returncode:
            raise ValueError("Could not open the save-folder picker. " + result.stderr.strip()[-400:])
        return json.loads(result.stdout)
    finally:
        PICKER_LOCK.release()


def api_scene(values, build):
    set_load(values)
    if build and JOB["running"]:
        raise ValueError("Another job is running; wait for it to finish.")
    scene = values["scene"]
    path = ROOT / "blender" / "scenes" / scene / "scene.blend"
    blender = blender_path(values)
    if build:
        if path.is_file():
            raise ValueError("Scene already built.")
        start_job("Building scene", lambda: run_process(
            [sys.executable, "-m", "simulator", "build-scene", scene, "--blender", blender, "--samples", values["samples"]]
            + render_flags(values["device"])))
    else:
        if not path.is_file():
            raise ValueError("Build this scene first.")
        subprocess.Popen([blender, str(path)], cwd=ROOT)


def api_test_gpu(values):
    blender = blender_path(values)

    def target():
        info = blender_devices(blender)
        log(f"Blender {info['blender']} Cycles devices: {json.dumps(info['devices'])}")
        best = best_device(info)
        log(f"Best available device: {best}")
        return 0 if best != "CPU" else 1
    start_job("Listing GPU devices (nothing is rendered)", target)


def state():
    values = default_values()
    lidars = []
    for p in LIDARS:
        meta = LidarModel(p).get_metadata()
        lidars.append(dict(id=p, caption=LIDAR_VIEW[p][2], rate_khz=meta["nominal_point_rate_hz"] / 1000,
                           range=[meta["range_min_m"], meta["range_max_m"]], fidelity=meta["fidelity"].replace("_", " ")))
    return dict(values=values, gpu=nvidia_info(), qualities={k: list(v) for k, v in QUALITIES.items()}, load_levels={k: list(v[:2]) for k, v in LOAD_LEVELS.items()}, lidars=lidars,
                scenes=[dict(id=s, info=SCENE_INFO[s], built=(ROOT / "blender/scenes" / s / "scene.blend").is_file(),
                             has_preview=(ROOT / "blender/scenes" / s / "preview.png").is_file()) for s in SCENES])


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def send(self, body, ctype="application/json", code=200):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def host_ok(self):
        return self.headers.get("Host", "").split(":")[0] in ("127.0.0.1", "localhost")

    def do_GET(self):
        if not self.host_ok():
            return self.send("forbidden", "text/plain", 403)
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path == "/":
                return self.send(HTML_PATH.read_text(encoding="utf-8").replace("__TOKEN__", TOKEN), "text/html; charset=utf-8")
            if u.path == "/api/state":
                return self.send(state())
            if u.path == "/api/stats":
                return self.send(live_stats())
            if u.path.startswith("/preview/scene/"):
                name = u.path.rsplit("/", 1)[1].removesuffix(".png")
                if name in SCENES and (ROOT / "blender/scenes" / name / "preview.png").is_file():
                    return self.send((ROOT / "blender/scenes" / name / "preview.png").read_bytes(), "image/png")
                return self.send("", "text/plain", 404)
            if u.path.startswith("/preview/lidar/"):
                name = u.path.rsplit("/", 1)[1].removesuffix(".png")
                if name in LIDARS:
                    return self.send(lidar_png(name), "image/png")
                return self.send("", "text/plain", 404)
            if u.path == "/api/camera":
                img, info = camera_preview(q["model"], int(q["w"]), int(q["h"]), float(q["f"]), size=(352, 220))
                return self.send(dict(image="data:image/png;base64," + base64.b64encode(png_bytes(img)).decode(), **info))
            if u.path == "/api/scan":
                if q["lidar"] not in LIDARS:
                    raise ValueError("Unknown LiDAR")
                return self.send(scan_cache(q["lidar"]))
            if u.path == "/api/studio/random":
                # Only proposes poses with thumbnails; nothing is generated until the user presses Generate.
                cam = dict(model=q["model"], width=int(q["w"]), height=int(q["h"]), focal_px=float(q["f"]))
                poses = studio.random_poses(q["scene"], int(q["n"]), float(q["z"]), float(q.get("roll", 0)), float(q.get("pitch", 0)), int(q["seed"]))
                out = []
                for p in poses:
                    r = studio.pose_view(q["scene"], q["lidar"], cam, p[:3], p[3:], triple(q["cxyz"], "camera position"),
                                         triple(q["crpy"], "camera rotation"), max_width=240, target_points=1500)
                    out.append(dict(pose=p, thumb="data:image/png;base64," + base64.b64encode(png_bytes(r["image"])).decode()))
                return self.send(dict(poses=out))
            if u.path == "/api/studio/batches":
                # Proposes batches only (poses, per-batch mount, thumbnails); generation stays a separate user action.
                cam = dict(model=q["model"], width=int(q["w"]), height=int(q["h"]), focal_px=float(q["f"]))
                base = triple(q["cxyz"], "camera position") + triple(q["crpy"], "camera rotation")
                plan = studio.batch_plan(q["scene"], int(q["batches"]), int(q["per"]), float(q["rot"]), float(q["trans"]), base,
                                         float(q["z"]), float(q.get("roll", 0)), float(q.get("pitch", 0)), int(q["seed"]),
                                         camera_cfg=cam, vary_intrinsics=q.get("intrinsics") == "1",
                                         focal_percent=float(q.get("focal_percent", .3)),
                                         principal_px=float(q.get("principal_px", .5)),
                                         distortion_delta=float(q.get("distortion_delta", 0)))
                for b in plan:
                    for i, p in enumerate(b["poses"]):
                        r = studio.pose_view(q["scene"], q["lidar"], b["camera"], p[:3], p[3:], b["mount"][:3], b["mount"][3:],
                                             max_width=240, target_points=1500)
                        b["poses"][i] = dict(pose=p, thumb="data:image/png;base64," + base64.b64encode(png_bytes(r["image"])).decode())
                return self.send(dict(batches=plan))
            if u.path == "/api/studio/map":
                img, meta = studio.floor_plan(q["scene"], float(q["cut"]))
                return self.send(dict(image="data:image/png;base64," + base64.b64encode(png_bytes(img)).decode(), **meta))
            if u.path == "/api/studio/view":
                cam = dict(model=q["model"], width=int(q["w"]), height=int(q["h"]), focal_px=float(q["f"]))
                r = studio.pose_view(q["scene"], q["lidar"], cam, triple(q["xyz"], "position"), triple(q["rpy"], "orientation"),
                                     triple(q["cxyz"], "camera position"), triple(q["crpy"], "camera rotation"),
                                     accum=float(q.get("accum", 0.1)))
                img = r.pop("image")
                return self.send(dict(image="data:image/png;base64," + base64.b64encode(png_bytes(img)).decode(), **r))
            if u.path == "/api/truth":
                run = JOB["last_run"]
                f = Path(run) / "evaluation/ground_truth.json" if run else None
                if not f or not f.is_file():
                    return self.send(dict(run=None, captures=[]))
                from scipy.spatial.transform import Rotation
                out = []
                for t in json.loads(f.read_text(encoding="utf-8")):
                    WL, CL = np.array(t["T_WL"]), np.array(t["T_CL"])
                    out.append(dict(id=t["capture_id"], lidar_xyz=WL[:3, 3].round(4).tolist(),
                                    lidar_rpy=Rotation.from_matrix(WL[:3, :3]).as_euler("xyz", degrees=True).round(3).tolist(),
                                    T_CL_t=CL[:3, 3].round(4).tolist(),
                                    T_CL_rpy=Rotation.from_matrix(CL[:3, :3]).as_euler("xyz", degrees=True).round(3).tolist(),
                                    K=np.array(t["camera"]["K"]).round(2).tolist(), model=t["camera"]["model"]))
                return self.send(dict(run=run, captures=out))
            if u.path == "/api/job":
                start = int(q.get("from", 0))
                with LOCK:
                    return self.send(dict(running=JOB["running"], code=JOB["code"], title=JOB["title"], device=JOB["device"], progress=JOB["progress"], step=JOB["step"], cancelled=JOB["cancelled"],
                                          elapsed=(time.time() - JOB["started"]) if JOB["running"] and JOB["started"] else 0,
                                          lines=JOB["lines"][start:], next=len(JOB["lines"]), last_run=JOB["last_run"], last_scene=JOB["last_scene"],
                                          mass=JOB["mass"]))
            if u.path == "/api/result.png":
                run = JOB["last_run"]
                f = Path(run) / "inference/capture_0000/image.png" if run else None
                if f and f.is_file():
                    return self.send(f.read_bytes(), "image/png")
                return self.send("", "text/plain", 404)
            if u.path == "/api/new_output":
                parent = Path(q["parent"]) if q.get("parent") else None
                if parent is not None and not parent.is_dir():
                    return self.send(dict(error="That save folder no longer exists; choose it again."))
                return self.send(dict(path=str(new_output(parent, q.get("scene", "warehouse"), int(q.get("captures", 1))))))
        except (ValueError, KeyError, TypeError, OSError) as error:
            return self.send(dict(error=describe(error)), code=400)
        except Exception as error:  # noqa: BLE001 - keep the page informed instead of dropping the connection
            return self.send(dict(error=f"Unexpected error: {error}"), code=500)
        self.send("not found", "text/plain", 404)

    def do_POST(self):
        if not self.host_ok() or self.headers.get("X-Token") != TOKEN:
            return self.send(dict(error="forbidden"), code=403)
        try:
            values = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            action = urlparse(self.path).path
            if action == "/api/choose_output":
                return self.send(api_choose_output(values))
            elif action == "/api/choose_folder":
                return self.send(api_choose_output(values, parent_only=True))
            elif action == "/api/generate":
                api_generate(values)
            elif action == "/api/mass_check":
                return self.send(api_mass_check(values))
            elif action == "/api/mass_scan":
                return self.send(api_mass_scan(values))
            elif action == "/api/mass":
                api_mass(values)
            elif action == "/api/build_scene":
                api_scene(values, True)
            elif action == "/api/open_scene":
                api_scene(values, False)
            elif action == "/api/cancel":
                api_cancel()
            elif action == "/api/test_gpu":
                api_test_gpu(values)
            elif action == "/api/view_dataset":
                run = JOB["last_run"]
                if not run:
                    raise ValueError("Generate captures first.")
                subprocess.Popen([sys.executable, "-m", "simulator", "dataset-view", run], cwd=ROOT, env=child_environment())
            else:
                return self.send(dict(error="unknown action"), code=404)
            self.send(dict(ok=True))
        except (ValueError, KeyError, OSError, TypeError) as error:
            self.send(dict(error=describe(error)), code=400)
        except Exception as error:  # noqa: BLE001
            self.send(dict(error=f"Unexpected error: {error}"), code=500)


def main():
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}/"
    print("Camera–LiDAR Simulation Lab running at", url, "(Ctrl+C to stop)")
    if "--no-browser" not in sys.argv:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
