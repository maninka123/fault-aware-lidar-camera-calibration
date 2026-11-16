"""CPU-only interactive previews for placing the rig: floor-plan cut-away and a camera view
with the LiDAR returns overlaid. Uses the same mesh, camera model and LiDAR schedules as dataset
generation. Never starts Blender or touches the GPU."""
from __future__ import annotations

import threading

import numpy as np
from PIL import Image, ImageDraw

from .camera import Camera
from .geometry import apply, camera_extrinsic, inverse, pose
from .lidar import generate_rays
from .raycast import MeshScene
from .render import camera_geometry, debug_rgb
from .resources import ROOT

_LOCK = threading.Lock()
_SCENES: dict = {}
_MAPS: dict = {}


def _scene(name):
    if name not in _SCENES:
        path = ROOT / "blender" / "scenes" / name / "mesh.npz"
        if not path.is_file():
            raise ValueError(f"Scene '{name}' is not built yet (no mesh.npz)")
        with np.load(path, allow_pickle=False) as m:
            v = np.asarray(m["vertices"], float)
        bounds = (v[:, 0].min(), v[:, 0].max(), v[:, 1].min(), v[:, 1].max(), v[:, 2].max())
        _SCENES[name] = (MeshScene(path), bounds)
    return _SCENES[name]


def floor_plan(name, cut_z, longest=720):
    """Top-down cut-away: rays fall from z=cut_z, so anything above that height is removed."""
    cut_z = round(float(cut_z), 1)
    key = (name, cut_z, longest)
    with _LOCK:
        if key in _MAPS:
            return _MAPS[key]
        scene, (x0, x1, y0, y1, zmax) = _scene(name)
        x0, x1, y0, y1 = x0 - 1, x1 + 1, y0 - 1, y1 + 1
        span = max(x1 - x0, y1 - y0)
        w, h = max(8, int(longest * (x1 - x0) / span)), max(8, int(longest * (y1 - y0) / span))
        xs, ys = np.linspace(x0, x1, w), np.linspace(y1, y0, h)
        gx, gy = np.meshgrid(xs, ys)
        origins = np.c_[gx.ravel(), gy.ravel(), np.full(gx.size, cut_z)]
        hit = scene.cast(origins, np.tile([0., 0., -1.], (len(origins), 1)))
        shade = 0.55 + 0.45 * np.abs(hit["normals"][:, 2])
        rgb = np.clip(hit["colors"] * shade[:, None], 0, 1)
        rgb[~hit["valid"]] = [.08, .11, .18]
        img = Image.fromarray((rgb.reshape(h, w, 3) * 255).astype(np.uint8))
        _MAPS[key] = (img, dict(bounds=[x0, x1, y0, y1], z_max=zmax))
        return _MAPS[key]


def _colour(t):
    t = np.clip(t, 0, 1)[:, None]
    return (np.c_[255 * t, 220 - 120 * np.abs(t - .5) * 2 + 20, 255 * (1 - t)]).astype(int)


def pose_view(name, lidar, camera_cfg, xyz, rpy, cam_xyz, cam_rpy, max_width=420, target_points=6000, accum=0.1):
    with _LOCK:
        scene, _ = _scene(name)
        s = min(1.0, max_width / camera_cfg["width"])
        w, h = max(2, round(camera_cfg["width"] * s)), max(2, round(camera_cfg["height"] * s))
        source = Camera.from_dict(camera_cfg)
        K = source.K.copy()
        K[0] *= w / source.width
        K[1] *= h / source.height
        K[0, 2] += (w / source.width - 1) / 2
        K[1, 2] += (h / source.height - 1) / 2
        cam = Camera(source.model, w, h, K, source.D)
        T_WL, T_CL = pose(xyz, rpy), camera_extrinsic(cam_xyz, cam_rpy)
        T_WC = T_WL @ inverse(T_CL)
        geo = camera_geometry(scene, cam, T_WC)
        img = Image.fromarray(debug_rgb(geo, cam))
        # LiDAR returns over the accumulation window (0.1 s snapshot, or longer for non-repetitive scanners), thinned for speed.
        accum = float(min(max(accum, 0.1), 5.0))
        if accum > 0.1:
            target_points = 2 * target_points  # a longer window shows more of the field being filled
        probe = generate_rays(lidar, 0.0, accum, {"stride": 1})["metadata"]
        stride = max(1, round(probe["generated_ray_count"] / target_points))
        rays = generate_rays(lidar, 0.0, accum, {"stride": stride})
        lm = rays["metadata"]
        hit = scene.cast(T_WL[:3, 3], rays["directions"] @ T_WL[:3, :3].T)
        ok = hit["valid"] & (hit["ranges"] >= lm["range_min_m"]) & (hit["ranges"] <= lm["range_max_m"])
        p_l = rays["directions"][ok] * hit["ranges"][ok, None]
        uv, vis = cam.project(apply(T_CL, p_l))
        draw = ImageDraw.Draw(img)
        col = _colour(hit["ranges"][ok] / min(lm["range_max_m"], 40.0))
        for (u, v), c, seen in zip(uv, col, vis):
            if seen:
                draw.ellipse([u - 1.5, v - 1.5, u + 1.5, v + 1.5], fill=tuple(int(k) for k in c))
        world = apply(T_WL, p_l)
        keep = np.arange(len(world))[:: max(1, len(world) // 2500)]
        ranges = geo["depth_range_m"]
        finite = ranges[np.isfinite(ranges)]
        nearest = float(finite.min()) if finite.size else float("nan")
        warn = None
        if finite.size < 0.2 * ranges.size:
            warn = "Camera sees little geometry here - it may be outside the building or facing open space."
        elif nearest < 0.15:
            warn = "Rig is very close to a surface (<15 cm); it may be inside an object."
        return dict(image=img, points=np.round(world[keep, :2], 2).tolist(), lidar_returns=int(ok.sum() * stride),
                    in_view=int(vis.sum() * stride), nearest_m=nearest, warn=warn, stride=stride, window_s=accum,
                    h_fov=float(np.degrees(2 * np.arctan2(w / 2, f))) if cam.model == "pinhole" else None)


def random_poses(name, n, z=1.6, roll=0.0, pitch=0.0, seed=0, min_spacing=1.5, clearance=0.8, open_view_m=3.0):
    """n random, valid rig poses [x, y, z, roll, pitch, yaw] in the scene.

    A spot is valid when the floor is directly below (not the top of an object), all eight horizontal
    directions are at least ``clearance`` m from a surface, and enough of them hit geometry that the spot
    is inside the building/street. The heading is chosen among directions with at least ``open_view_m`` of
    open space so the camera is not facing a wall. Chosen spots are ``min_spacing`` m apart when possible.
    """
    n = int(n)
    if not 1 <= n <= 50:
        raise ValueError("Choose between 1 and 50 random captures")
    rng = np.random.default_rng(int(seed))
    with _LOCK:
        scene, (x0, x1, y0, y1, _zmax) = _scene(name)
        ring = np.deg2rad(np.arange(0, 360, 45.0))
        ring_dirs = np.c_[np.cos(ring), np.sin(ring), np.zeros(8)]
        yaws = np.deg2rad(np.arange(-180, 180, 15.0))
        yaw_dirs = np.c_[np.cos(yaws), np.sin(yaws), np.zeros(len(yaws))]
        chosen = []
        spacing = float(min_spacing)
        for attempt in range(40):
            m = 600
            pts = np.c_[rng.uniform(x0, x1, m), rng.uniform(y0, y1, m), np.full(m, float(z))]
            down = scene.cast(pts, np.tile([0., 0., -1.], (m, 1)))
            floor_ok = down["valid"] & (np.abs(float(z) - down["ranges"]) <= 0.25 + 0.0)
            side = scene.cast(np.repeat(pts, 8, axis=0), np.tile(ring_dirs, (m, 1)))
            hit = side["valid"].reshape(m, 8)
            dist = np.where(hit, side["ranges"].reshape(m, 8), np.inf)
            ok = floor_ok & (dist.min(axis=1) >= clearance) & (hit.sum(axis=1) >= 4)
            for i in np.flatnonzero(ok):
                if any(np.hypot(*(pts[i, :2] - c[:2])) < spacing for c in chosen):
                    continue
                fwd = scene.cast(np.tile(pts[i], (len(yaws), 1)), yaw_dirs)
                # Need a real surface at least open_view_m away: "no hit" means looking out into the void.
                good = np.flatnonzero(fwd["valid"] & (fwd["ranges"] >= open_view_m))
                if not len(good):
                    continue
                yaw = float(np.degrees(yaws[rng.choice(good)]) + rng.uniform(-7.5, 7.5))
                chosen.append([round(float(pts[i, 0]), 2), round(float(pts[i, 1]), 2), round(float(z), 2),
                               float(roll), float(pitch), round(yaw, 1)])
                if len(chosen) == n:
                    return chosen
            if attempt % 8 == 7:
                spacing *= 0.6  # crowded scene: relax spacing rather than fail
    if not chosen:
        raise ValueError("Could not find a free spot in this scene at that height; try a different height.")
    return chosen


def batch_plan(name, batches, per_batch, tol_rot_deg, tol_trans_mm, base_mount, z=1.6, roll=0.0, pitch=0.0, seed=0,
               *, camera_cfg=None, vary_intrinsics=False, focal_percent=0.3, principal_px=0.5, distortion_delta=0.0):
    """Batches of random rig poses; the LiDAR-camera mount is fixed inside a batch and changes between batches.

    base_mount = [x, y, z (m), roll, pitch, yaw (deg)] of the camera relative to the LiDAR. Batch 0 uses it
    exactly; every later batch adds an independent uniform offset of +-tol_rot_deg per rotation axis and
    +-tol_trans_mm per translation axis. These offsets are the simulated true calibration differences.
    """
    batches, per_batch = int(batches), int(per_batch)
    if not (1 <= batches <= 20 and 1 <= per_batch <= 50 and batches * per_batch <= 100):
        raise ValueError("Use 1-20 batches, 1-50 captures per batch, and at most 100 captures in total")
    if not (0 <= tol_rot_deg <= 10 and 0 <= tol_trans_mm <= 100):
        raise ValueError("Tolerance must be 0-10 degrees and 0-100 mm")
    base = np.asarray(base_mount, float)
    if base.shape != (6,) or not np.isfinite(base).all():
        raise ValueError("Mount needs six finite numbers")
    limits = np.asarray([focal_percent, principal_px, distortion_delta], float)
    if not np.isfinite(limits).all() or np.any(limits < 0) or np.any(limits > [5, 10, .001]):
        raise ValueError("Intrinsics limits must be 0-5 percent focal, 0-10 pixels principal point, and 0-0.001 distortion")
    if vary_intrinsics and camera_cfg is None:
        raise ValueError("Camera settings are required to vary intrinsics")
    camera = Camera.from_dict(camera_cfg) if camera_cfg is not None else None
    # Separate stream preserves the existing mount/pose plan when intrinsics are toggled.
    intrinsic_rng = np.random.default_rng(np.random.SeedSequence([int(seed), 1]))
    rng = np.random.default_rng(int(seed))
    out = []
    for b in range(batches):
        mount = base.copy()
        if b:
            mount[:3] += rng.uniform(-tol_trans_mm, tol_trans_mm, 3) / 1000.0
            mount[3:] += rng.uniform(-tol_rot_deg, tol_rot_deg, 3)
        poses = random_poses(name, per_batch, z, roll, pitch, seed=int(rng.integers(1 << 31)))
        entry = dict(batch=b, mount=[round(float(v), 4) for v in mount], poses=poses)
        if camera is not None:
            K, D = camera.K.copy(), camera.D.copy()
            if b and vary_intrinsics:
                # Independent bounded offsets from nominal, held constant throughout each batch.
                K[0, 0] *= 1 + intrinsic_rng.uniform(-focal_percent, focal_percent) / 100
                K[1, 1] *= 1 + intrinsic_rng.uniform(-focal_percent, focal_percent) / 100
                K[:2, 2] += intrinsic_rng.uniform(-principal_px, principal_px, 2)
                # Vary k1 only; higher-order coefficients can strongly amplify edge distortion.
                D[0] += intrinsic_rng.uniform(-distortion_delta, distortion_delta)
            entry["camera"] = Camera(camera.model, camera.width, camera.height, K, D).to_dict()
        out.append(entry)
    return out
