"""Run every research test module in its own Python process and report per-module results.

Why: when all research modules run inside ONE process, a clean checkout (no saved checks, so many GUI tests skip) has crashed with a
native heap-corruption error (Windows 0xc0000374) while constructing the desktop window in a later test. The crash was not reproduced
by creating windows alone, by any single module, or by the numerical code under test (process-heap validation after each call was
clean), and its root cause is NOT resolved. Isolating modules means a native crash can only fail its own module and is reported as such;
it does not mask other results, and a crash is never counted as a pass.

    python tools/run_research_tests.py                # all modules
    python tools/run_research_tests.py test_mathematics test_correspondence_v3
"""
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main(argv):
    names = argv or sorted(p.stem for p in (ROOT / 'research_tests').glob('test_*.py'))
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1')
    env.setdefault('QT_QPA_PLATFORM', 'offscreen')
    rows, failed = [], False
    for name in names:
        started = time.perf_counter()
        process = subprocess.run([sys.executable, '-X', 'faulthandler', '-m', 'unittest', 'discover', '-s', 'research_tests', '-p', name + '.py'],
                                 cwd=ROOT, env=env, capture_output=True, text=True, timeout=1200)
        text = process.stdout + process.stderr
        ran = re.search(r'Ran (\d+) tests?', text)
        skipped = re.search(r'skipped=(\d+)', text)
        ok = process.returncode == 0 and ran is not None
        failed |= not ok
        rows.append((name, int(ran.group(1)) if ran else 0, int(skipped.group(1)) if skipped else 0,
                     'ok' if ok else ('CRASH' if ran is None else 'FAIL'), time.perf_counter() - started))
        if not ok:
            print(text[-3000:], flush=True)
        print(f'{name:38s} {rows[-1][1]:4d} tests {rows[-1][2]:3d} skipped  {rows[-1][3]:5s} {rows[-1][4]:6.1f} s', flush=True)
    total = sum(r[1] for r in rows)
    print(f'\n{len(rows)} modules, {total} tests, {sum(r[2] for r in rows)} skipped, {"FAILED" if failed else "all passed"}')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
