"""Scriptable local entry point. Blender and ROS remain separate processes."""
import argparse
from copy import deepcopy
from pathlib import Path
import shutil
import subprocess
from .io import json_write
from .lidar import PROFILES
from .resources import ROOT, render_permission, single_job, child_environment

def _progress(fraction, message):
    """One machine-readable line per step; the browser UI turns these into a progress bar."""
    print(f"SIMLAB_PROGRESS {fraction:.4f} {message}", flush=True)


SCENES = ("warehouse", "laboratory", "urban", "corridor")


def find_blender(explicit=None):
    if explicit:
        return str(Path(explicit).resolve())
    found = shutil.which("blender")
    if found:
        return found
    candidates = sorted(Path("C:/Program Files/Blender Foundation").glob("Blender */blender.exe"))
    if candidates:
        return str(candidates[-1])
    raise ValueError("Blender not found. Supply --blender <executable>")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Camera–LiDAR Simulation Lab")
    subs = parser.add_subparsers(dest="command", required=True)
    p = subs.add_parser("build-scene", help="Construct, export and render an editable Blender scene")
    p.add_argument("scene", choices=SCENES)
    p.add_argument("--blender")
    p.add_argument("--output", type=Path)
    p.add_argument("--samples", type=int, default=32)
    p.add_argument("--hdri", type=Path)
    p.add_argument("--allow-render", action="store_true")
    p.add_argument("--allow-gpu", action="store_true")
    p.add_argument("--device", choices=("CPU", "CUDA", "OPTIX"), default="CPU")
    p = subs.add_parser("generate", help="Generate a configured run")
    p.add_argument("config", type=Path)
    p.add_argument("--resume", action="store_true", help="Continue an unfinished run in its existing folder (finished captures are kept)")
    p.add_argument("--blender")
    p.add_argument("--output", type=Path)
    p.add_argument("--allow-render", action="store_true")
    p.add_argument("--allow-gpu", action="store_true")
    p.add_argument("--device", choices=("CPU", "CUDA", "OPTIX"))
    p = subs.add_parser("batch", help="Same scene/camera/poses/seed across all five sensors")
    p.add_argument("config", type=Path)
    p.add_argument("--blender")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--allow-render", action="store_true")
    p.add_argument("--allow-gpu", action="store_true")
    p.add_argument("--device", choices=("CPU", "CUDA", "OPTIX"))
    p = subs.add_parser("verify", help="Reload outputs, check geometry and hashes")
    p.add_argument("run", type=Path)
    p = subs.add_parser("evaluate", help="Compare supplied estimates and decisions with evaluation truth")
    p.add_argument("run", type=Path)
    p.add_argument("estimates", type=Path)
    p.add_argument("--output", type=Path)
    p = subs.add_parser("export", help="Export inference-only data to optimizer inputs")
    p.add_argument("run", type=Path)
    p.add_argument("destination", type=Path)
    p.add_argument("--format", choices=("paired", "stacked"), default="paired")
    p = subs.add_parser("view", help="Open a generated cloud in Open3D")
    p.add_argument("cloud", type=Path)
    p = subs.add_parser("dataset-view", help="Browse existing RGB images and evaluation overlays")
    p.add_argument("run", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "build-scene":
            render_permission(args.device, args.allow_render, args.allow_gpu)
            out = args.output or ROOT/"blender"/"scenes"/args.scene
            if out.exists() and any(out.iterdir()):
                raise ValueError("Scene destination is not empty; choose a new --output to preserve existing assets")
            cmd = [find_blender(args.blender), "--background", "--python", str(ROOT/"blender"/"build_scene.py"), "--",
                   "--scene", args.scene, "--output", str(out.resolve()), "--samples", str(args.samples),
                   "--device", args.device, "--allow-render"]
            if args.allow_gpu:
                cmd += ["--allow-gpu"]
            if args.hdri:
                cmd += ["--hdri", str(args.hdri.resolve())]
            with single_job():
                subprocess.run(cmd, check=True, env=child_environment(), timeout=600)
        elif args.command in ("generate", "batch"):
            from .pipeline import generate, load_config
            config = load_config(args.config)
            if args.device:
                config.setdefault("render", {})["device"] = args.device
            if config.get("renderer", "blender") == "blender":
                render_permission(config.get("render", {}).get("device", "CPU"), args.allow_render, args.allow_gpu)
                config["blender"] = find_blender(args.blender or config.get("blender"))
            if args.command == "batch":
                if args.output.exists():
                    raise ValueError("Batch destination already exists; choose a new output")
                rgb_cache, cube_cache = {}, {}
                for sensor in PROFILES:
                    current = deepcopy(config)
                    current.update(lidar=sensor, output=str(args.output.resolve()/sensor))
                    # sensor-specific option names are not portable; common stride is preserved.
                    current["lidar_options"] = {k:v for k,v in config.get("lidar_options", {}).items() if k in ("stride", "range_min_m", "range_max_m")}
                    with single_job():
                        print(generate(current, rgb_cache=rgb_cache, cube_cache=cube_cache,
                              allow_render=args.allow_render, allow_gpu=args.allow_gpu), flush=True)
            else:
                if args.output:
                    config["output"] = str(args.output.resolve())
                with single_job():
                    print(generate(config, allow_render=args.allow_render, allow_gpu=args.allow_gpu, progress=_progress, report=lambda text: print(text, flush=True), resume=args.resume), flush=True)
        elif args.command == "verify":
            from .validation import verify_run
            import json
            result = verify_run(args.run)
            print(json.dumps(result, indent=2))
            if not result["passed"]:
                raise SystemExit(1)
        elif args.command == "evaluate":
            from .evaluation import evaluate
            import json
            result = evaluate(args.run, args.estimates)
            if args.output:
                json_write(args.output, result)
            print(json.dumps(result, indent=2))
        elif args.command == "export":
            from .adapters import export_paired, export_stacked
            result = (export_paired if args.format == "paired" else export_stacked)(args.run, args.destination)
            print(result)
        elif args.command == "view":
            import open3d as o3d
            cloud = o3d.io.read_point_cloud(str(args.cloud))
            if cloud.is_empty():
                raise ValueError("Cloud is empty or unreadable")
            o3d.visualization.draw_geometries([cloud], window_name="Simulation Lab — LiDAR frame, metres")
        elif args.command == "dataset-view":
            from .viewer import show_dataset
            show_dataset(args.run)
    except (ValueError, FileNotFoundError, FileExistsError) as e:
        parser.exit(2, f"Error: {e}\n")


if __name__ == "__main__":
    main()
