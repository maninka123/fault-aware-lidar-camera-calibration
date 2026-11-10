"""Exercise the cloned optimizer without writing into its repository.

Use --solve to attempt its existing maintenance refinement after data ingestion.
No solver-success assertion is made: all failures and estimated errors are saved.
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

import numpy as np

sys.dont_write_bytecode = True
PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from simulator.adapters import export_stacked, inference_root, validate_optimizer_camera


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--optimizer", type=Path, default=PROJECT / "research_references/calibration-optimizer")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--solve", action="store_true")
    parser.add_argument("--ground-truth", type=Path, help="Explicit evaluation-only input for candidate errors")
    args = parser.parse_args()
    output = args.output.resolve()
    optimizer = args.optimizer.resolve()
    if output == optimizer or optimizer in output.parents:
        parser.error("Output must be outside the reference optimizer repository")
    output.mkdir(parents=True, exist_ok=True)
    report = dict(optimizer=str(optimizer), solver_attempted=False, ingestion_success=False)
    try:
        initial = inference_root(args.run) / "initial_calibration.json"
        calibration = json.loads(initial.read_text(encoding="utf-8"))
        validate_optimizer_camera(calibration)
        stacked = export_stacked(args.run, output / "stacked")
        sys.path.insert(0, str(optimizer / "Calibration maintenance/code"))
        import settings
        settings.results_dir = lambda: output / "solver_results"
        frames = settings.load_stacked(stacked)
        loaded = settings.load_calibration(initial)
        report.update(ingestion_success=True, captures=len(frames),
                      points=[len(frame.xyz) for frame in frames],
                      image_shapes=[list(frame.image.shape) for frame in frames],
                      loaded_transform=loaded.T.tolist())
        if args.solve:
            report["solver_attempted"] = True
            import maintain
            maintain.run(initial, stacked, "simulation_check", mode="extrinsic")
            candidate = output / "solver_results/simulation_check/refined_calibration.json"
            report["solver_returned_candidate"] = candidate.is_file()
            if candidate.is_file():
                report["candidate"] = str(candidate)
                if args.ground_truth:
                    truth = json.loads(args.ground_truth.read_text(encoding="utf-8"))
                    truth = truth if isinstance(truth, list) else truth["captures"]
                    estimate = np.asarray(json.loads(candidate.read_text())["extrinsics"]["transform_lidar_to_camera"])
                    errors = []
                    for capture in truth:
                        target = np.asarray(capture["T_CL"], float)
                        relative = estimate[:3, :3] @ target[:3, :3].T
                        angle = float(np.degrees(np.arccos(np.clip((np.trace(relative)-1)/2, -1, 1))))
                        errors.append(dict(capture_id=capture["capture_id"], rotation_error_deg=angle,
                                           translation_error_m=float(np.linalg.norm(estimate[:3, 3]-target[:3, 3]))))
                    report["evaluation_errors"] = errors
    except (Exception, SystemExit) as error:
        report.update(error=repr(error), traceback=traceback.format_exc())
    (output / "optimizer_check.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report.get("ingestion_success") and not report.get("error") else 1


if __name__ == "__main__":
    raise SystemExit(main())
