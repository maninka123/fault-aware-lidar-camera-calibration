"""Accept the refined calibration of a maintenance run.

Copies results/<run>/refined_calibration.json to accepted/<device or run>_<date>.json (or --out) and marks
the run as accepted in results/history.csv. The existing calibration file is never overwritten.

Usage:  python accept.py <run> [--out <path>]
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
from datetime import datetime
from pathlib import Path

from settings import ROOT, results_dir


def accept(run, out=None):
    src = results_dir() / run / "refined_calibration.json"
    if not src.exists():
        raise SystemExit(f"no refined calibration for run {run}")
    summary = json.loads((results_dir() / run / "summary.json").read_text())
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    label = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in (summary.get("device") or run))
    dst = Path(out) if out else ROOT / "accepted" / f"{label}_{stamp}.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    hist = results_dir() / "history.csv"
    if hist.exists():
        with hist.open(newline="") as f:
            rows = list(csv.DictReader(f))
        for r in rows:
            if r["run"] == run:
                r["accepted"] = f"{stamp} -> {dst}"
        with hist.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader(); w.writerows(rows)
    return dst


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--out")
    a = ap.parse_args()
    print(f"accepted: {accept(a.run, a.out)}")


if __name__ == "__main__":
    main()
