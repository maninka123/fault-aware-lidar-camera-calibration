"""Conservative process-local limits and an OS-released exclusive job lock."""
from contextlib import contextmanager
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def render_permission(device, allow_render=False, allow_gpu=False):
    if not allow_render:
        raise ValueError("Native rendering is disabled by default after the reported Windows crashes. "
                         "Use existing images or geometry mode. --allow-render explicitly enables a later CPU render.")
    if device != "CPU" and not allow_gpu:
        raise ValueError("GPU rendering requires explicit --allow-gpu as well as --allow-render. "
                         "The Windows crash cause has not been diagnosed.")


def child_environment():
    env = dict(os.environ)
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        env[name] = "1"
    return env


LOAD_LEVELS = {
    "max": ("Max speed", "Normal priority, every CPU core. Fastest, but the PC can lag while a render runs.", None),
    "responsive": ("Responsive (recommended)", "Lower priority and a quarter of the CPU cores kept free, so the PC stays smooth.", .75),
    "light": ("Very light", "Lower priority and half of the CPU cores kept free. Slowest, for working alongside a render.", .5),
}


def apply_load_limits(pid, level="responsive"):
    """Keep the PC usable while a job runs: lower the process priority and leave CPU cores free.

    Windows (and Linux) children inherit both, so Blender, which the generator starts later, is limited too. The job's own
    results do not change; only how much of the machine it takes. Returns a sentence for the log, or None when nothing was applied.
    """
    if level not in LOAD_LEVELS or LOAD_LEVELS[level][2] is None:
        return None
    try:
        import psutil
        process = psutil.Process(pid)
        process.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS if os.name == "nt" else 10)
        cores = psutil.cpu_count(logical=True) or 1
        use = max(2, int(cores * LOAD_LEVELS[level][2]) // 2 * 2)       # even: keeps hyper-threads of one core together
        if use < cores and hasattr(process, "cpu_affinity"):
            process.cpu_affinity(list(range(cores - use, cores)))        # the last cores; the first ones stay free for Windows itself
        return f"PC responsiveness: {LOAD_LEVELS[level][0]} - lower priority, using {min(use, cores)} of {cores} CPU cores."
    except Exception:  # noqa: BLE001 - limits are a convenience; never stop a job over them
        return None


@contextmanager
def single_job():
    """No stale lock after process termination; blocks parallel simulator jobs only."""
    path = ROOT/".simulation-job.lock"
    with path.open("a+b") as stream:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise ValueError("Another simulator job is active; finish it before starting another") from error
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
