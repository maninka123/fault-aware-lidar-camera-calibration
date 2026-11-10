"""Static-within-window captures, independent sensor origins, separated evaluation truth."""
from copy import deepcopy
import json
from pathlib import Path
import platform
import time
import cv2
import numpy as np
import yaml
from . import __version__
from .camera import Camera
from .geometry import apply, default_extrinsic, inverse, pose, validate_transform
from .evaluation import change_from_nominal
from .faults import calibration_dict, perturb
from .io import json_read, json_write, sha256, write_pcd
from .lidar import generate_rays, PROFILES
from .raycast import MeshScene
from .render import CUBE_FACES, camera_geometry, cubemap_rgb, debug_rgb, degrade, needed_faces, render_cubemap
from .resources import render_permission

SCENES = ("warehouse", "laboratory", "urban", "corridor")
ROOT = Path(__file__).resolve().parents[1]


def load_config(path):
    path = Path(path).resolve()
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("Experiment configuration must be a mapping")
    for field in ("mesh", "blend", "output", "blender", "cubemap"):
        if field in config:
            p = Path(config[field])
            if not p.is_absolute():
                config[field] = str((path.parent/p).resolve())
    config["_config_path"] = str(path)
    return config


def validate_config(config):
    allowed = {"scene", "mesh", "blend", "output", "blender", "camera", "lidar", "lidar_options", "duration",
               "captures", "interval", "start_time", "seed", "T_CL", "lidar_pose", "poses", "initial_fault",
               "events", "noise", "camera_noise", "renderer", "render", "split", "_config_path", "cubemap", "accumulate_s", "T_CLs", "batch_ids", "cameras", "mass"}
    if set(config)-allowed:
        raise ValueError("Unsupported config keys: " + str(set(config)-allowed))
    if config.get("scene", "warehouse") not in SCENES:
        raise ValueError("scene must be one of " + str(SCENES))
    if config.get("lidar", "livox_avia") not in PROFILES:
        raise ValueError("lidar must be one of " + str(PROFILES))
    for k, default in (("duration", .1), ("interval", 1.)):
        if not np.isfinite(config.get(k, default)) or config.get(k, default) <= 0:
            raise ValueError(k+" must be finite and positive")
    long_s = config.get("accumulate_s")
    if long_s is not None and (not np.isfinite(long_s) or long_s <= config.get("duration", .1) or long_s > 10):
        raise ValueError("accumulate_s must be finite, longer than duration and at most 10 s")
    count = config.get("captures", 1)
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        raise ValueError("captures must be an integer >= 1")
    if not isinstance(config.get("seed", 42), int) or config.get("seed", 42) < 0:
        raise ValueError("seed must be a nonnegative integer")
    if not np.isfinite(config.get("start_time", 0)) or config.get("start_time", 0) < 0:
        raise ValueError("start_time must be finite and nonnegative")
    if config.get("split", "test") not in ("train", "validation", "test"):
        raise ValueError("split must be train, validation or test")
    if config.get("renderer", "blender") not in ("blender", "cubemap", "geometry"):
        raise ValueError("renderer must be blender, cubemap (existing rendered files), or geometry (diagnostic RGB)")
    if config.get("renderer") == "cubemap" and not config.get("cubemap"):
        raise ValueError("renderer=cubemap requires cubemap directory containing cube_metadata.json")
    events = config.get("events", [])
    seen_times = set()
    for e in events:
        if set(e)-{"time", "fault", "label"} or "time" not in e or "fault" not in e:
            raise ValueError("Each event requires time and fault; optional label")
        t = e["time"]
        if not np.isfinite(t) or t < 0 or t in seen_times:
            raise ValueError("Event times must be unique finite nonnegative seconds")
        seen_times.add(t)
    for key in ("T_CLs", "batch_ids", "cameras"):
        if key in config and len(config[key]) != count:
            raise ValueError(key + " must supply one entry for every capture")
    base_camera = Camera.from_dict(config.get("camera", {}))
    for c in config.get("cameras", []):
        camera = Camera.from_dict(c)
        if (camera.model, camera.width, camera.height) != (base_camera.model, base_camera.width, base_camera.height):
            raise ValueError("Per-capture cameras must retain the baseline model and image dimensions")
    if "T_CLs" in config:
        for T in config["T_CLs"]:
            validate_transform(T)
    if "batch_ids" in config and not all(isinstance(b, int) and not isinstance(b, bool) for b in config["batch_ids"]):
        raise ValueError("batch_ids must be integers (negative = not part of a batch)")
    poses = config.get("poses")
    if poses is not None and len(poses) != count:
        raise ValueError("poses must supply one T_WL matrix for every capture")
    noise = config.get("noise", {})
    noise_allowed = {"range_std_m", "range_std_per_m", "angular_std_deg", "dropout", "dropout_per_m", "range_quantization_m"}
    if set(noise)-noise_allowed:
        raise ValueError("Unsupported LiDAR noise keys: " + str(set(noise)-noise_allowed))
    for k, v in noise.items():
        if not np.isfinite(v) or v < 0 or (k == "dropout" and v > 1):
            raise ValueError("LiDAR noise values must be nonnegative finite; dropout <= 1")
    render = config.get("render", {})
    if set(render)-{"samples", "cubemap_size", "device", "cube_faces"}:
        raise ValueError("render supports samples, cubemap_size, device and cube_faces")
    if render.get("cube_faces", "auto") not in ("auto", "all"):
        raise ValueError("render.cube_faces must be auto (only the faces the camera samples) or all")
    for k, default in (("samples", 16), ("cubemap_size", 512)):
        if not isinstance(render.get(k, default), int) or render.get(k, default) < 1:
            raise ValueError("render."+k+" must be a positive integer")
    if render.get("device", "OPTIX") not in ("OPTIX", "CUDA", "CPU", "AUTO"):
        raise ValueError("render.device must be OPTIX, CUDA, CPU or AUTO")


def _measure(scene, T_WL, rays, noise, rng):
    nominal = rays["directions"]
    directions = nominal.copy()
    angular = np.deg2rad(noise.get("angular_std_deg", 0.))
    if angular:
        # Isotropic small-angle perturbation in the tangent plane; approximate beam jitter.
        jitter = rng.normal(0, angular, directions.shape)
        jitter -= (jitter*directions).sum(axis=1)[:, None]*directions
        directions += jitter
        directions /= np.linalg.norm(directions, axis=1)[:, None]
    world_d = directions @ T_WL[:3, :3].T
    hit = scene.cast(T_WL[:3, 3], world_d)
    ranges = hit["ranges"].astype(float)
    valid = hit["valid"].copy()
    mn, mx = rays["metadata"]["range_min_m"], rays["metadata"]["range_max_m"]
    valid &= (ranges >= mn) & (ranges <= mx)
    idx = np.flatnonzero(valid)
    sigma = noise.get("range_std_m", 0) + noise.get("range_std_per_m", 0)*ranges[idx]
    measured = ranges[idx] + rng.normal(0, sigma, len(idx))
    quant = noise.get("range_quantization_m", 0)
    if quant:
        measured = np.round(measured/quant)*quant
    probability = np.clip(noise.get("dropout", 0)+noise.get("dropout_per_m", 0)*ranges[idx], 0, 1)
    keep = (rng.random(len(idx)) >= probability) & (measured >= mn) & (measured <= mx)
    idx, measured = idx[keep], measured[keep]
    # Explicit phenomenological intensity: cosine incidence / range attenuation. NOT PBR or NIR reflectivity.
    cosine = np.abs((hit["normals"][idx]*world_d[idx]).sum(axis=1))
    intensity = (255*cosine/(1+.002*ranges[idx]**2)).astype(np.float32)
    cloud = dict(xyz=(directions[idx]*measured[:, None]).astype(np.float32),
                 intensity=intensity, timestamps=rays["timestamps"][idx],
                 directions=directions[idx].astype(np.float32), nominal_directions=nominal[idx].astype(np.float32),
                 channel=rays["channel"][idx], beam_id=rays["beam_id"][idx])
    # Independent, noiseless nominal beams are evaluation-only observations.
    if angular:
        ideal = scene.cast(T_WL[:3, 3], nominal @ T_WL[:3, :3].T)
    else:
        ideal = hit
    ok = ideal["valid"] & (ideal["ranges"] >= mn) & (ideal["ranges"] <= mx)
    perfect = dict(xyz=(nominal[ok]*ideal["ranges"][ok, None]).astype(np.float32),
                   directions=nominal[ok], timestamps=rays["timestamps"][ok],
                   channel=rays["channel"][ok], beam_id=rays["beam_id"][ok])
    return cloud, perfect, dict(emitted_rays=len(nominal), geometric_returns=int(valid.sum()),
                               valid_returns=len(idx), raycast_elapsed_s=hit["elapsed_s"],
                               raycast_rays_per_second=hit["rays_per_second"], intensity_model="approximate cosine/range, not NIR")


def projection_check(scene, camera, T_WC, T_CL, ideal):
    points_c = apply(T_CL, ideal["xyz"])
    uv, visible = camera.project(points_c)
    ids = np.flatnonzero(visible)
    if not len(ids):
        return dict(in_image=0, visible_to_camera=0, occluded=0, max_ray_reprojection_error_px=None), uv, np.zeros(len(uv), bool)
    # Recast FROM THE CAMERA at continuous projected pixels, not nearest depth-buffer pixels.
    pc = points_c[ids]
    length = np.linalg.norm(pc, axis=1)
    dc = pc/length[:, None]
    camera_hit = scene.cast(T_WC[:3, 3], dc @ T_WC[:3, :3].T)
    residual = np.abs(camera_hit["ranges"]-length)
    tolerance = 5e-4 + length*2e-6
    joint = camera_hit["valid"] & (residual <= tolerance)
    mask = np.zeros(len(uv), bool)
    mask[ids[joint]] = True
    recovered = camera.unproject(uv[ids])
    check_uv, _ = camera.project(recovered)
    return dict(in_image=len(ids), visible_to_camera=int(joint.sum()), occluded=int((~joint).sum()),
                max_ray_reprojection_error_px=float(np.max(np.linalg.norm(check_uv-uv[ids], axis=1))),
                max_visible_surface_error_m=float(residual[joint].max()) if joint.any() else None), uv, mask


def _previews(rgb, camera, T_CL, ideal, uv, visible, out):
    overlay = rgb[:, :, ::-1].copy()
    p = apply(T_CL, ideal["xyz"])
    ids = np.flatnonzero(visible)
    for i in ids[::max(1, len(ids)//15000)]:
        z = float(np.clip(p[i, 2]/25, 0, 1))
        cv2.circle(overlay, tuple(np.rint(uv[i]).astype(int)), 1, (int(255*z), int(255*(1-z)), 255), -1)
    cv2.imwrite(str(out/"calibration_overlay.png"), overlay)
    # Top-down metric preview in LiDAR frame, x forward up / y left left.
    view = np.full((600, 600, 3), 245, np.uint8)
    xyz = ideal["xyz"]
    for x, y in xyz[::max(1, len(xyz)//25000), :2]:
        u, v = int(300-y*10), int(500-x*10)
        if 0 <= u < 600 and 0 <= v < 600:
            view[v, u] = (45, 100, 25)
    cv2.putText(view, "LiDAR XY: 10 px/m, x up, y left", (12, 28), cv2.FONT_HERSHEY_SIMPLEX, .55, (30, 30, 30), 1)
    cv2.imwrite(str(out/"pointcloud_preview.png"), view)


PERFORMANCE_KEYS = ("emitted_rays", "geometric_returns", "valid_returns", "raycast_elapsed_s", "raycast_rays_per_second", "intensity_model")
_RESUME_IGNORED = ("blender", "output")      # where Blender lives / where the folder is does not change the data


def _check_resumable(out, config):
    """A folder can be continued only if it is an unfinished run made with the same settings."""
    saved_path = out/"evaluation"/"config.json"
    if not saved_path.is_file():
        raise ValueError("Nothing to continue: this folder has no saved run settings.")
    if (out/"evaluation"/"manifest.json").is_file():
        raise ValueError("This run is already finished; there is nothing to continue.")

    def comparable(c):
        c = json.loads(json.dumps(c, default=str))
        for key in _RESUME_IGNORED:
            c.pop(key, None)
        if isinstance(c.get("render"), dict):
            c["render"].pop("device", None)
        return c
    if comparable(json_read(saved_path)) != comparable(config):
        raise ValueError("The saved run was made with different settings, so it cannot be continued.")


def generate(config, *, rgb_cache=None, cube_cache=None, allow_render=False, allow_gpu=False, progress=None, report=None, resume=False):
    """progress(fraction 0..1, message) is called as the run advances; it never affects results.

    resume=True continues an unfinished run in its existing folder: captures that finished (their verification.json, the last
    file a capture writes, exists) are kept as they are and only the rest are produced, so the result equals an uninterrupted run."""
    note = progress or (lambda fraction, message: None)
    say = report or (lambda text: None)  # plain result lines for the Activity log; never affects results
    config = deepcopy(config)
    validate_config(config)
    if config.get("renderer", "blender") == "blender":
        render_permission(config.get("render", {}).get("device", "CPU"), allow_render, allow_gpu)
    name = config.get("scene", "warehouse")
    mesh = Path(config.get("mesh", ROOT/"blender"/"scenes"/name/"mesh.npz"))
    if not mesh.is_file():
        raise ValueError(f"Scene mesh not built: {mesh}. Run simlab build-scene first")
    out = Path(config.get("output", ROOT/"outputs"/name/config.get("lidar", "livox_avia")))
    inf, ev = out/"inference", out/"evaluation"
    if resume:
        _check_resumable(out, config)
        inf.mkdir(exist_ok=True)
        ev.mkdir(exist_ok=True)
    else:
        # Refuse to overwrite scientific runs or pre-existing user data.
        out.mkdir(parents=True, exist_ok=False)
        inf.mkdir()
        ev.mkdir()
    scene = MeshScene(mesh)
    camera_base = Camera.from_dict(config.get("camera", {}))
    T_base = validate_transform(config.get("T_CL", default_extrinsic()))
    T_initial, camera_initial = perturb(T_base, camera_base, config.get("initial_fault", {}))
    json_write(inf/"initial_calibration.json", calibration_dict(T_initial, camera_initial))
    if not resume:
        json_write(ev/"config.json", config)   # a continued run keeps the settings it started with
    count, duration, interval = config.get("captures", 1), config.get("duration", .1), config.get("interval", 1.)
    events = sorted(config.get("events", []), key=lambda e: e["time"])
    sequence, truth, stats = [], [], []
    rgb_cache = {} if rgb_cache is None else rgb_cache
    cube_cache = {} if cube_cache is None else cube_cache
    begin = time.perf_counter()
    renderer, kept = config.get("renderer", "blender"), 0
    note(0.0, "Preparing the scene")
    for index in range(count):
        capture_id = f"capture_{index:04d}"
        label = f"capture {index+1} of {count}"
        span = lambda part: (index+part)/count*.97
        timestamp = config.get("start_time", 0.)+index*interval
        window = max(duration, config.get("accumulate_s") or 0)
        if any(timestamp < e["time"] < timestamp+window for e in events):
            raise ValueError("Physical fault occurs within a scan window; use a boundary-aligned event (intra-scan drift unsupported)")
        current_events = [e for e in events if e["time"] <= timestamp]
        event = current_events[-1] if current_events else None
        fault = event["fault"] if event else {}
        # Batches: each capture may carry its own true camera<-LiDAR transform; the initial estimate stays the nominal T_base.
        T_true = validate_transform(config["T_CLs"][index]) if "T_CLs" in config else T_base
        camera_true = Camera.from_dict(config["cameras"][index]) if "cameras" in config else camera_base
        T_CL, camera = perturb(T_true, camera_true, fault)
        T_WL = validate_transform(config["poses"][index]) if "poses" in config else pose(**config.get("lidar_pose", {}))
        T_WC = T_WL @ inverse(T_CL)
        batch = config["batch_ids"][index] if "batch_ids" in config and config["batch_ids"][index] >= 0 else None
        seq_entry = dict(capture_id=capture_id, timestamp=timestamp, duration_s=duration, path=capture_id,
                         **({"batch": batch} if batch is not None else {}))
        truth_entry = dict(capture_id=capture_id, timestamp=timestamp, T_WL=T_WL.tolist(), T_WC=T_WC.tolist(),
                           T_CL=T_CL.tolist(), camera=camera.to_dict(), calibration=calibration_dict(T_CL, camera),
                           fault_label=event.get("label", "physical_change") if event else "stable",
                           physical_fault=fault, change_timestamp=event["time"] if event else None, batch=batch)
        cap, cap_ev = inf/capture_id, ev/capture_id
        if resume and (cap_ev/"verification.json").is_file() and (cap/"lidar_metadata.json").is_file():
            # verification.json is the last file a capture writes: this one finished before the run stopped, so keep its files.
            saved = json_read(cap/"lidar_metadata.json")
            sequence.append(seq_entry)
            truth.append(truth_entry)
            stats.append(dict(capture_id=capture_id, **{k: saved[k] for k in PERFORMANCE_KEYS}, **json_read(cap_ev/"verification.json")))
            kept += 1
            say(f"{label}: already complete, kept")
            note(span(1.0), f"Kept {label}")
            continue
        cap.mkdir(exist_ok=resume)    # a capture that was cut off half way is redone in place
        cap_ev.mkdir(exist_ok=resume)
        # Separate deterministic RNG streams: camera noise identical across sensor comparison batches.
        rng = np.random.default_rng(np.random.SeedSequence([config.get("seed", 42), index, 0]))
        image_rng = np.random.default_rng(np.random.SeedSequence([config.get("seed", 42), index, 1]))
        rays = generate_rays(config.get("lidar", "livox_avia"), timestamp, duration, config.get("lidar_options", {}))
        cloud, perfect, performance = _measure(scene, T_WL, rays, config.get("noise", {}), rng)
        note(span(.1), f"LiDAR scan done, {label}")
        say(f"{label}: rig at ({T_WL[0, 3]:.2f}, {T_WL[1, 3]:.2f}, {T_WL[2, 3]:.2f}) m, heading {np.degrees(np.arctan2(T_WL[1, 0], T_WL[0, 0])):.0f} deg"
            + (f", camera mount batch {config['batch_ids'][index] + 1}" if "batch_ids" in config and config["batch_ids"][index] >= 0 else ""))
        say(f"  LiDAR snapshot: {len(cloud['xyz']):,} points ({performance['geometric_returns']:,} geometric returns from {performance['emitted_rays']:,} beams)")
        long_s = config.get("accumulate_s")
        if long_s:
            # Same static rig, longer integration: a non-repetitive scanner keeps filling the field of view.
            long_rays = generate_rays(config.get("lidar", "livox_avia"), timestamp, long_s, config.get("lidar_options", {}))
            long_rng = np.random.default_rng(np.random.SeedSequence([config.get("seed", 42), index, 2]))
            long_cloud, long_perfect, long_perf = _measure(scene, T_WL, long_rays, config.get("noise", {}), long_rng)
            say(f"  LiDAR accumulated over {long_s:g} s: {len(long_cloud['xyz']):,} points (fills more of the field of view)")
        geometry = camera_geometry(scene, camera, T_WC)
        render = config.get("render", {})
        key = (sha256(mesh), T_WC.tobytes(), str(camera.to_dict()), renderer, str(render), str(config.get("cubemap", "")))
        if key not in rgb_cache:
            if renderer == "blender":
                blend = Path(config.get("blend", mesh.parent/"scene.blend"))
                # Only the cube faces this camera samples are rendered (lossless); render.cube_faces: all restores all six.
                faces = needed_faces(camera) if render.get("cube_faces", "auto") == "auto" else list(CUBE_FACES)
                cube_key = (str(blend.resolve()), T_WC.tobytes(), str(render), tuple(faces))
                if cube_key not in cube_cache:
                    if not config.get("blender"):
                        raise ValueError("Blender RGB requires a blender executable path in config or CLI --blender")
                    note(span(.2), f"Rendering camera image, {label}")
                    t_render = time.perf_counter()
                    cube_cache[cube_key] = render_cubemap(config["blender"], blend, T_WC, cap_ev,
                        samples=render.get("samples", 8), size=render.get("cubemap_size", 256), device=render.get("device", "CPU"),
                        allow_render=allow_render, allow_gpu=allow_gpu, exist_ok=True, faces=faces)
                    meta_path = Path(cube_cache[cube_key]) / "metadata.json"
                    device = json_read(meta_path).get("device", {}) if meta_path.is_file() else {}
                    say(f"  Camera image rendered in {time.perf_counter() - t_render:.1f} s on {device.get('actual', '?')} "
                        f"({', '.join(device.get('devices', [])) or 'device not reported'}), {len(faces)} of 6 cube faces")
                else:
                    say("  Camera image reused from an identical earlier view")
                rgb_cache[key] = cubemap_rgb(camera, T_WC, cube_cache[cube_key])
            elif renderer == "cubemap":
                rgb_cache[key] = cubemap_rgb(camera, T_WC, config["cubemap"])
            else:
                rgb_cache[key] = debug_rgb(geometry, camera)
        note(span(.8), f"Saving files, {label}")
        rgb = degrade(rgb_cache[key], config.get("camera_noise", {}), image_rng)
        if not cv2.imwrite(str(cap/"image.png"), rgb[:, :, ::-1]):
            raise RuntimeError("Failed to write camera image")
        np.savez_compressed(cap/"lidar.npz", **cloud)
        write_pcd(cap/"cloud.pcd", cloud["xyz"], cloud["intensity"], cloud["timestamps"], cloud["channel"])
        extra = {}
        if long_s:
            np.savez_compressed(cap/"lidar_accumulated.npz", **long_cloud)
            write_pcd(cap/"cloud_accumulated.pcd", long_cloud["xyz"], long_cloud["intensity"], long_cloud["timestamps"], long_cloud["channel"])
            np.savez_compressed(cap_ev/"ideal_lidar_accumulated.npz", **long_perfect)
            extra["accumulated"] = dict(duration_s=long_s, files=["lidar_accumulated.npz", "cloud_accumulated.pcd"],
                                         static_rig=True, **long_perf)
        json_write(cap/"lidar_metadata.json", dict(sensor=rays["metadata"], noise=config.get("noise", {}),
            timestamp=timestamp, duration_s=duration, coordinate_frame="L: x forward, y left, z up", units="m", **extra, **performance))
        np.savez_compressed(cap_ev/"ideal_lidar.npz", **perfect)
        np.savez_compressed(cap_ev/"camera_geometry.npz", **{k:geometry[k] for k in (
            "depth_range_m", "depth_z_m", "normals_camera", "segmentation")})
        check, uv, visible = projection_check(scene, camera, T_WC, T_CL, perfect)
        _previews(rgb, camera, T_CL, perfect, uv, visible, cap_ev)
        say(f"  Projection check: {check['visible_to_camera']:,} of {check['in_image']:,} LiDAR points in the image are visible to the camera "
            f"(max reprojection error {check['max_ray_reprojection_error_px'] or 0:.1e} px)")
        json_write(cap_ev/"verification.json", check)
        sequence.append(seq_entry)
        truth.append(truth_entry)
        stats.append(dict(capture_id=capture_id, **performance, **check))
        say("  Saved image, point clouds and ground truth")
        note(span(1.0), f"Finished {label}")
    note(.98, "Writing ground truth and manifest")
    json_write(inf/"sequence.json", sequence)
    json_write(ev/"ground_truth.json", truth)
    json_write(ev/"events.json", events)
    if "batch_ids" in config:
        groups = {}
        for t in truth:
            if t["batch"] is not None:
                groups.setdefault(t["batch"], []).append(t)
        json_write(ev/"batches.json", [dict(batch=b, capture_ids=[t["capture_id"] for t in g], T_CL=g[0]["T_CL"],
                                           camera=g[0]["camera"],
                                           change_from_nominal=change_from_nominal(T_base, camera_base, g[0]["T_CL"], g[0]["camera"]),
                                           same_calibration=all(t["T_CL"] == g[0]["T_CL"] and t["camera"] == g[0]["camera"] for t in g)) for b, g in sorted(groups.items())])
        # The nominal mount and intrinsics the changes above are measured from (batch 0 normally equals it).
        json_write(ev/"nominal_calibration.json", dict(T_CL=T_base.tolist(), camera=camera_base.to_dict()))
    # A separate evaluation manifest can contain truth/config; inference tree only contains measurements + initial estimate.
    versions = dict(simulator=__version__, python=platform.python_version(), numpy=np.__version__,
                    opencv=cv2.__version__, raycasting=scene.backend)
    manifest = dict(schema_version="1.0", scene=name, scene_mesh_sha256=sha256(mesh),
                    split=config.get("split", "test"), sensor=config.get("lidar", "livox_avia"),
                    seed=config.get("seed", 42), versions=versions, elapsed_s=time.perf_counter()-begin,
                    renderer=renderer, captures=stats,
                    limitations=["Scene and rig static within each scan window; no motion distortion or dynamic objects",
                                 "Single returns; no scattering, fog, rain, multipath or validated material NIR reflectivity",
                                 "Procedural Blender environments require further asset/detail work for publication photorealism",
                                 "See sensor metadata for replay periods and nominal sensor approximations",
                                 "Pixel-centre geometry is exact up to float32 intersection error; RGB is sampled/anti-aliased"],
                    files=[dict(path=str(p.relative_to(out)).replace("\\", "/"), sha256=sha256(p), bytes=p.stat().st_size)
                           for p in sorted(out.rglob("*")) if p.is_file()])
    if resume:
        manifest["resumed_captures_kept"] = kept
    json_write(ev/"manifest.json", manifest)
    note(1.0, "Done")
    return out
