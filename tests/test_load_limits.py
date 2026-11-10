"""Keeping the PC usable while a job runs: lower priority and free CPU cores, inherited by the job's children (Blender)."""
import subprocess
import sys

import pytest

psutil = pytest.importorskip("psutil")

from simulator.resources import LOAD_LEVELS, apply_load_limits

CHILD = "import psutil;p=psutil.Process();print(p.nice(), len(p.cpu_affinity()), flush=True)"
PARENT = ("import subprocess,sys,time;time.sleep(2);"
          "print(subprocess.run([sys.executable,'-c',%r],capture_output=True,text=True).stdout.strip(),flush=True)" % CHILD)


def run_parent(level):
    p = subprocess.Popen([sys.executable, "-c", PARENT], stdout=subprocess.PIPE, text=True)
    text = apply_load_limits(p.pid, level)              # applied just after start, before the parent launches its child
    out, _ = p.communicate(timeout=60)
    return text, out.strip()


def test_levels_are_described_for_the_page():
    assert set(LOAD_LEVELS) == {"max", "responsive", "light"} and all(len(v) == 3 for v in LOAD_LEVELS.values())


def test_max_speed_changes_nothing():
    text, _ = run_parent("max")
    assert text is None
    assert apply_load_limits(0, "no-such-level") is None


@pytest.mark.skipif(sys.platform != "win32", reason="priority classes are inherited this way on Windows")
def test_responsive_lowers_priority_and_frees_cores_for_the_child_too():
    cores = psutil.cpu_count(logical=True)
    if cores < 4:
        pytest.skip("too few cores to leave any free")
    text, out = run_parent("responsive")
    assert text and "of %d CPU cores" % cores in text
    priority, used = out.split()
    assert priority.endswith("BELOW_NORMAL_PRIORITY_CLASS") and int(used) < cores   # the grandchild (Blender's role) is limited as well
    assert int(used) == max(2, int(cores * .75) // 2 * 2)


def test_a_vanished_process_never_breaks_a_job():
    assert apply_load_limits(2 ** 22 + 12345, "responsive") is None
