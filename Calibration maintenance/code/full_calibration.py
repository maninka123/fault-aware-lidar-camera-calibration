"""Full calibration from scratch, then the usual maintenance check against the existing calibration.

For when the existing calibration is too far off to refine (LARGE CHANGE / INCONCLUSIVE): the
targetless calibration (../../Targetless calibration, read-only; no target, no starting values, the
camera mounting found automatically) runs on the same captures, its outputs written to
results/<run>/from_scratch/. Its result is then one of the starts of maintain.py in "full" mode
(intrinsics and extrinsics), so the report compares it with the existing calibration exactly like a
normal check, with the same evidence and verdict.

Usage:  python full_calibration.py --calibration <existing calibration.json> --data <stacked captures folder> --name <run> [--device <label>]
"""
from __future__ import annotations

import argparse
import copy
import json
from datetime import datetime
from pathlib import Path

from settings import load_config, log, results_dir, write_json

import maintain  # noqa: E402


def stage(out, message, images=()):
    write_json(out / "progress.json", dict(run=out.name, finished=False, stages=[dict(
        stage="scratch", message=message, images=[str(Path(i).relative_to(out)) for i in images], table=None,
        time=datetime.now().isoformat(timespec="seconds"))]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--calibration", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--device")
    ap.add_argument('--cloud-units', choices=['m', 'mm'], default='m')
    ap.add_argument('--confirm-cloud-units', action='store_true')
    a = ap.parse_args()
    out = results_dir() / a.name
    out.mkdir(parents=True, exist_ok=True)
    data = Path(a.data).resolve()
    original_data = data
    stage(out, "calibrating from scratch on the captures (targetless: no target and no starting values; the camera "
               "mounting is found automatically). This takes a few minutes")
    import step1_calibrate  # Targetless calibration (read-only)
    cfg = copy.deepcopy(load_config())
    if not next(data.glob('*.npz'), None):
        frames, _ = maintain.get_frames(data, out, cfg, a.cloud_units, a.confirm_cloud_units)
        from paired_data import save_stacked
        data = out / 'captures'
        save_stacked(frames, data)
    cfg["stacked_dir"] = str(data.parent)
    cfg["output_dir"] = str(out / "from_scratch")
    cfg["prior"]["rotation_lidar_to_camera"] = "auto"
    log("calibration from scratch ...")
    step1_calibrate.run_device(cfg, data.name)
    res = out / "from_scratch" / data.name
    cal = json.loads((res / "calibration.json").read_text())
    conf = cal.get("confidence", {})
    K = cal["intrinsics"]["camera_matrix"]
    stage(out, f"calibration from scratch: fx {K[0][0]:.1f}, fy {K[1][1]:.1f}, mounting {cal['mounting']['chosen']}, "
               f"edge alignment {cal['quality']['edge_alignment_lift']:.2f} x chance, self-check {str(conf.get('verdict', '?')).upper()}"
               + (f" ({'; '.join(conf['failed'])})" if conf.get("failed") else "")
               + ". It is now refined and compared with the existing calibration like a normal check",
          sorted(res.glob("captures/*/edge_alignment.png")))
    maintain.run(a.calibration, str(original_data), a.name, "full", a.device,
                 [("calibration from scratch", str(res / "calibration.json"))], a.cloud_units, a.confirm_cloud_units)


if __name__ == "__main__":
    main()
