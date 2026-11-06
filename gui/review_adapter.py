"""Adapter between a fault-aware check and the maintenance app's saved results (the Calibration review tab).

A check (research_artifacts/<check>/) never contains maintenance numbers by itself. They are produced only when
the user presses "Run maintenance comparison", by the unchanged maintenance backend (maintain.py --mode compare),
into research_artifacts/<check>/maintenance_review/maintenance/. Nothing here starts a run: this module only
decides whether one is possible, describes the state, builds the command, and reads what was saved.
"""
from __future__ import annotations

import hashlib
import json
import re
import os
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]      # the repository root (this file lives in gui/)
CODE = ROOT / "Calibration maintenance" / "code"
if str(CODE) not in sys.path:
    sys.path.insert(0, str(CODE))

import appcore as core  # noqa: E402  (maintenance logic, no GUI)

# Short names on purpose: Windows refuses paths over 260 characters, and a check folder already sits deep in the repository.
REVIEW_DIR = "review"               # inside the check's folder
RUN_NAME = "run"                    # the maintenance run inside that folder
SKIP = ("stacked", "decode")        # large caches the review never reads; they stay in the scratch folder
FAULT_KEEP = {"KEEP_CURRENT", "INSUFFICIENT_EVIDENCE", "INVALID_OR_UNRELIABLE_DATA"}
MAINTENANCE_UPDATE = {"UPDATE RECOMMENDED", "LARGE CHANGE"}


def review_root(check):
    return Path(check) / REVIEW_DIR


def run_folder(check):
    """The finished comparison saved inside the check."""
    return review_root(check) / RUN_NAME


def work_root(check):
    """Short scratch folder the comparison runs in (decoded captures need paths the check's own folder is too deep for)."""
    base = Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()) / "FaultAwareReview"
    return base / hashlib.sha1(str(Path(check).resolve()).encode("utf-8")).hexdigest()[:8]


def work_run(check):
    return work_root(check) / RUN_NAME


def _long(path):
    """Extended-length form of a path, which Windows accepts beyond 260 characters."""
    p = str(Path(path).resolve())
    return "\\\\?\\" + p if os.name == "nt" and not p.startswith("\\\\?\\") else p


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ------------------------------------------------------------------ can a comparison be run?
def inputs_for(meta, check=None):
    """(inputs, reason). inputs: calibration, captures, cloud_units; reason is None when a comparison can be run.

    Uses only what the check saved about itself; a check that did not start from an existing calibration, or
    whose files have moved, is reported as unavailable instead of guessing."""
    meta = meta or {}
    if check is not None and too_deep(check):
        return None, ("This check sits in a folder that is too deep for Windows to hold the comparison's files "
                      f"({len(str(check))} characters before they start; the limit is 260). Move the repository to a shorter "
                      "path such as C:\\FaultAware, or enable long paths in Windows.")
    if meta.get("mode") == "scratch":
        return None, "This check calibrated from scratch, so there is no existing calibration to compare an update against."
    cal, cap = meta.get("calibration"), meta.get("captures")
    if not cal or not cap:
        return None, "This check did not record which calibration and captures it used."
    if not Path(cal).is_file():
        return None, f"The calibration file this check used is no longer there: {cal}"
    if not Path(cap).is_dir():
        return None, f"The capture folder this check used is no longer there: {cap}"
    units = meta.get("cloud_units")
    paired = False
    try:
        from paired_data import has_pairs
        data = Path(cap)
        paired = not next(data.glob("*.npz"), None) and not any((p / "rig_0.bag").exists() for p in data.glob("capture_*")) and has_pairs(data)
    except Exception:  # noqa: BLE001 - detection is a convenience; unreadable folders fail later with a clear message
        paired = False
    if paired and not units:
        return None, "This check used image + PCD pairs but did not save their coordinate units, so they cannot be re-read safely."
    return dict(calibration=str(cal), captures=str(cap), cloud_units=units or "m", confirm_units=bool(meta.get("confirm_cloud_units"))), None


SAVED_PATH_RESERVE = len("\\" + REVIEW_DIR + "\\" + RUN_NAME + "\\stages\\image_edges_185316_547419.png") + 12


def too_deep(check):
    """True when the longest file the review saves into this check would pass Windows' 260 character limit."""
    return os.name == "nt" and len(str(Path(check))) + SAVED_PATH_RESERVE > 259


def _pid_alive(pid):
    """Whether a process with this id is running (never signals it: os.kill(pid, 0) would terminate it on Windows)."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if os.name == "nt":
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x00100000, False, pid)   # SYNCHRONIZE
        if not handle:
            return False
        try:
            return ctypes.windll.kernel32.WaitForSingleObject(handle, 0) == 0x102   # WAIT_TIMEOUT: still running
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def lock_holder(check):
    """The id of another live process that is running this check's comparison, or None."""
    info = read_json(work_root(check) / "lock.json")
    if info and info.get("pid") != os.getpid() and _pid_alive(info.get("pid")):
        return info.get("pid")
    return None


def command(check, inputs):
    """(python arguments, environment overrides, working folder) for the maintenance comparison of this check."""
    args = ["-X", "utf8", "-B", str(CODE / "maintain.py"), "--calibration", inputs["calibration"], "--data", inputs["captures"],
            "--name", RUN_NAME, "--mode", "compare", "--device", "fault-aware", "--cloud-units", inputs["cloud_units"]]
    if inputs.get("confirm_units"):
        args.append("--confirm-cloud-units")
    env = {"MAINTENANCE_RESULTS_DIR": str(work_root(check)), "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1",
           "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1"}
    return args, env, str(CODE)


def prepare(check, inputs, fault_status=None):
    """Create a clean scratch folder for the run and record what it belongs to (called when a run is started).
    A comparison already saved in the check stays where it is until a new one has finished."""
    holder = lock_holder(check)
    if holder:
        raise RuntimeError(f"Another window (process {holder}) is already running the maintenance comparison for this check.")
    shutil.rmtree(_long(work_root(check)), ignore_errors=True)
    out = work_run(check)
    out.mkdir(parents=True, exist_ok=True)
    (work_root(check) / "lock.json").write_text(json.dumps(dict(pid=os.getpid(), started=datetime.now().isoformat(timespec="seconds"))))
    review_root(check).mkdir(parents=True, exist_ok=True)
    (review_root(check) / "link.json").write_text(json.dumps(dict(
        check=Path(check).name, started=datetime.now().isoformat(timespec="seconds"), inputs=inputs,
        fault_aware_status=fault_status, backend="maintain.py --mode compare",
        note="Separate from the fault-aware assessment; the original calibration files are never changed."), indent=2), encoding="utf-8")
    return out


# ------------------------------------------------------------------ what exists
def finished(folder):
    prog = read_json(Path(folder) / "progress.json")
    return bool(prog and prog.get("finished") and (Path(folder) / "summary.json").exists())


def state(check):
    """'ready' (a finished comparison is saved in the check), 'partial' (a run started and did not finish) or 'none'."""
    if finished(run_folder(check)):
        return "ready"
    scratch = work_run(check)
    if scratch.exists() and not finished(scratch):
        return "partial"
    return "partial" if run_folder(check).exists() else "none"


def publish(check):
    """Copy a finished run from the scratch folder into the check (without the large caches). (ok, message)."""
    src, dst = work_run(check), run_folder(check)
    if not finished(src):
        return False, "The comparison did not finish, so nothing was saved into the check."
    try:
        shutil.rmtree(_long(dst), ignore_errors=True)
        shutil.copytree(_long(src), _long(dst), ignore=shutil.ignore_patterns(*SKIP))
        history = work_root(check) / "history.csv"
        if history.exists():
            shutil.copy2(_long(history), _long(review_root(check) / "history.csv"))
    except OSError as error:
        return False, f"The comparison finished but could not be saved into the check: {error}"
    release(check)
    return True, ""


def release(check, keep_logs=False):
    """Give up the scratch folder (and with it the lock). keep_logs keeps it so a failed run can still show its log."""
    try:
        (work_root(check) / "lock.json").unlink()
    except OSError:
        pass
    if not keep_logs:
        shutil.rmtree(_long(work_root(check)), ignore_errors=True)


def _live(check):
    """Where progress and the log are read from: the scratch folder while a run is going or was left behind."""
    return work_run(check) if work_run(check).exists() else run_folder(check)


def progress_text(check):
    """Name of the stage the running comparison has reached, for the progress line."""
    prog = read_json(_live(check) / "progress.json") or {}
    done = [s["stage"] for s in prog.get("stages", []) if s.get("stage") != "start"]
    titles = dict((k, t) for k, _, t, _ in core_stage_table())
    nxt = next((k for k in core.STAGES if k not in done), None)
    return titles.get(nxt, "Working") if nxt else "Finishing"


def core_stage_table():
    from ui_common import STAGES  # the maintenance app's own stage titles
    return STAGES


# stages of a maintenance comparison, in the order the maintenance backend reports them
REVIEW_STEPS = ["data", "features", "health", "options", "search", "refined", "evidence", "verdict"]
SUB = re.compile(r"check\s+(\d+)\s+of\s+(\d+)")


def live_progress(check):
    """How far a running (or just finished) comparison has got, from its own saved files:
    dict(done, step, message, sub, images). sub is (i, n) while it compares the update choices capture by capture."""
    folder = _live(check)
    prog = read_json(folder / "progress.json") or {}
    stages = [s for s in prog.get("stages", []) if isinstance(s, dict) and s.get("stage") != "start"]
    reached = {s.get("stage") for s in stages}
    step = next((k for k in REVIEW_STEPS if k not in reached), None)
    images = []
    for s in stages:
        for rel in s.get("images") or []:
            p = folder / str(rel)
            if str(rel).lower().endswith(".png") and p.is_file():
                images.append(p)
    tail = [l for l in log_tail(check, 3) if l.strip()]
    line = re.sub(r"^\[\s*[\d.]+s\]\s*", "", tail[-1]) if tail else ""
    m = SUB.search(line)
    return dict(done=len(reached & set(REVIEW_STEPS)), step=step, message=line, sub=(int(m.group(1)), int(m.group(2))) if m else None, images=images)


def log_tail(check, n=12):
    p = _live(check) / "run.log"
    try:
        return p.read_text(errors="replace").splitlines()[-n:]
    except OSError:
        return []


def load(check):
    """The maintenance app's `run_info` for this check's comparison (None unless it finished)."""
    if state(check) != "ready":
        return None
    info = core.run_info_at(run_folder(check), RUN_NAME, accepted=None)
    return info if info.get("summary") else None


def is_stale(info, meta):
    """True when the comparison was made from different files than the check now points at."""
    if not info or not meta:
        return False
    s = info["summary"]
    def same(a, b):
        try:
            return Path(a).resolve() == Path(b).resolve()
        except OSError:
            return False
    return not (same(core.resolve(s["existing"]), meta.get("calibration", "")) and same(core.resolve(s["data"]), meta.get("captures", "")))


# ------------------------------------------------------------------ verdicts
def agreement(fault_status, maintenance_verdict):
    """One sentence relating the two analyses. The fault-aware verdict is the scientific one."""
    keep = fault_status in FAULT_KEEP
    update = maintenance_verdict in MAINTENANCE_UPDATE
    if keep and not update:
        return "agree", "Both analyses point the same way: the current calibration should be kept."
    if keep and update:
        return "differ", ("The analyses differ. The maintenance comparison sees a change in how points project, but the fault-aware "
                          "assessment found no explanation that held up on captures it was not fitted to. Treat the maintenance "
                          "result as a diagnostic, not as a reason to update.")
    if fault_status == "UPDATE_SUPPORTED" and update:
        return "agree", "Both analyses support a change. Review it before using it."
    if fault_status == "UPDATE_SUPPORTED":
        return "differ", "The fault-aware assessment supports a change that the maintenance comparison does not recommend."
    return "info", "The two analyses answer different questions and are shown side by side."


# ------------------------------------------------------------------ safe export
def check_export_path(path, protected=()):
    """Raise ValueError when an export would overwrite an input calibration (or anything the check relies on)."""
    target = Path(path).resolve()
    for p in protected:
        if p and Path(p).resolve() == target:
            raise ValueError("That would overwrite the calibration file this check started from. Choose a new file name.")
    return target
