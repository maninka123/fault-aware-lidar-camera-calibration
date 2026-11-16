"""Photometric Blender cubemap resampling and exact geometry from independent camera rays."""
from pathlib import Path
import subprocess
import cv2
import numpy as np
from .geometry import apply, inverse
from .io import json_read, json_write
from .resources import child_environment, render_permission


def camera_geometry(scene, camera, T_WC):
    d = camera.pixel_rays()
    valid = np.isfinite(d).all(axis=1)
    # Rays outside the supported forward hemisphere become missing pixels.
    safe = d.copy()
    safe[~valid] = [0, 0, 1]
    hit = scene.cast(T_WC[:3, 3], safe @ T_WC[:3, :3].T)
    hit["valid"] &= valid
    ranges = hit["ranges"].copy()
    ranges[~hit["valid"]] = np.nan
    shape = (camera.height, camera.width)
    normals_c = hit["normals"] @ T_WC[:3, :3]
    normals_c[~hit["valid"]] = 0
    segmentation = hit["object_ids"].copy()
    segmentation[~hit["valid"]] = -1
    return dict(depth_range_m=ranges.reshape(shape),
                depth_z_m=(ranges*safe[:, 2]).reshape(shape),
                normals_camera=normals_c.reshape(*shape, 3),
                segmentation=segmentation.reshape(shape), hit=hit, rays_c=safe)


def debug_rgb(geometry, camera):
    """Geometry diagnostic only, explicitly NOT a photorealistic renderer."""
    hit = geometry["hit"]
    light = np.array([.3, -.4, .85])
    light /= np.linalg.norm(light)
    shading = .25 + .75*np.abs(hit["normals"] @ light)
    rgb = np.clip(hit["colors"] * shading[:, None], 0, 1)
    rgb[~hit["valid"]] = [.11, .15, .23]
    return (rgb.reshape(camera.height, camera.width, 3)*255).astype(np.uint8)


CUBE_FACES = ("px", "nx", "py", "ny", "pz", "nz")
_FACE_FORWARD = dict(px=(1., 0., 0.), nx=(-1., 0., 0.), py=(0., 1., 0.), ny=(0., -1., 0.), pz=(0., 0., 1.), nz=(0., 0., -1.))
_FACES_CACHE: dict = {}


def needed_faces(camera, margin=1e-6):
    """Cube faces this camera can sample from, so only those need rendering (the result is identical to using all six).

    cubemap_rgb takes every pixel ray from the face whose forward axis it is most aligned with, so a face is needed exactly
    when some valid pixel ray points mostly along it. ``margin`` also keeps a face whose axis ties within rounding of the best
    one, so the answer can only be a superset of the faces actually sampled. Narrow lenses need as few as three faces; the
    back face is never needed because valid rays always point forward (fisheye angles stop below 90 degrees).
    """
    key = (camera.model, camera.width, camera.height, camera.K.tobytes(), camera.D.tobytes())
    if key not in _FACES_CACHE:
        rays = camera.pixel_rays()
        rays = rays[np.isfinite(rays).all(axis=1)]
        if not len(rays):
            _FACES_CACHE[key] = list(CUBE_FACES)
        else:
            along = rays @ np.array([_FACE_FORWARD[f] for f in CUBE_FACES]).T
            used = ((along >= along.max(axis=1, keepdims=True) - margin) & (along > 0)).any(axis=0)
            _FACES_CACHE[key] = [f for f, u in zip(CUBE_FACES, used) if u]
    return list(_FACES_CACHE[key])


def cubemap_rgb(camera, T_WC, directory):
    directory = Path(directory)
    meta = json_read(directory/"cube_metadata.json")
    faces = meta["faces"]
    rays_c = camera.pixel_rays()
    valid = np.isfinite(rays_c).all(axis=1)
    rays_w = np.nan_to_num(rays_c) @ T_WC[:3, :3].T
    rgb = np.zeros((len(rays_w), 3), np.uint8)
    best = np.full(len(rays_w), -np.inf)
    for face in faces:
        face_pose = np.asarray(face["T_WC"], float)
        if not np.allclose(face_pose[:3, 3], T_WC[:3, 3], atol=1e-7):
            raise ValueError("Cubemap origin differs from capture camera origin")
        d = rays_w @ face_pose[:3, :3]
        K = np.asarray(face["K"], float)
        image = cv2.imread(str(directory/face["image"]), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("Missing rendered cubemap face: " + face["image"])
        z = d[:, 2]
        safe_z = np.maximum(z, 1e-12)
        u = K[0, 0]*d[:, 0]/safe_z + K[0, 2]
        v = K[1, 1]*d[:, 1]/safe_z + K[1, 2]
        # Exact cube-edge ties can differ by ~1e-13 after camera/world rotations.
        edge_epsilon = 1e-7
        sel = valid & (z > best) & (z > 0) & (u >= -.5-edge_epsilon) & (u <= image.shape[1]-.5+edge_epsilon) & (v >= -.5-edge_epsilon) & (v <= image.shape[0]-.5+edge_epsilon)
        ids = np.flatnonzero(sel)
        if len(ids):
            # OpenCV remap has an int16 image-dimension limit, including output rows.
            for start in range(0, len(ids), 16000):
                part = ids[start:start+16000]
                sampled = cv2.remap(image, u[part].astype(np.float32).reshape(-1, 1),
                                    v[part].astype(np.float32).reshape(-1, 1), cv2.INTER_LINEAR,
                                    borderMode=cv2.BORDER_REPLICATE).reshape(-1, 3)
                rgb[part] = sampled[:, ::-1]
            best[ids] = z[ids]
    if np.any(valid & ~np.isfinite(best)):
        raise ValueError("Cubemap does not cover every valid camera ray")
    return rgb.reshape(camera.height, camera.width, 3)


def render_cubemap(blender, blend, T_WC, directory, samples=8, size=256, device="CPU", *, allow_render=False, allow_gpu=False, exist_ok=False, faces=None):
    render_permission(device, allow_render, allow_gpu)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=exist_ok)
    json_write(directory/"pose.json", dict(T_WC=T_WC.tolist()))
    script = Path(__file__).resolve().parents[1]/"blender"/"build_scene.py"
    cmd = [str(blender), "--background", "--python", str(script), "--", "--blend", str(Path(blend).resolve()),
           "--pose-json", str((directory/"pose.json").resolve()), "--output", str(directory.resolve()),
           "--cubemap", "--cube-size", str(size), "--width", str(size), "--height", str(size), "--samples", str(samples), "--device", device,
           "--allow-render"]
    if allow_gpu:
        cmd += ["--allow-gpu"]
    if faces is not None and set(faces) != set(CUBE_FACES):
        cmd += ["--faces", ",".join(faces)]   # only the faces the camera samples; the rest would never be read
    with (directory/"blender.log").open("w", encoding="utf-8") as log:
        subprocess.run(cmd, check=True, stdout=log, stderr=subprocess.STDOUT, env=child_environment(), timeout=600)
    return directory


def degrade(rgb, settings, rng):
    allowed = {"noise_std", "blur_sigma", "jpeg_quality", "exposure_stops", "white_balance"}
    if set(settings)-allowed:
        raise ValueError("Unsupported camera noise settings: " + str(set(settings)-allowed))
    x = rgb.astype(float)/255
    gain = 2**float(settings.get("exposure_stops", 0))
    wb = np.asarray(settings.get("white_balance", [1, 1, 1]), float)
    if wb.shape != (3,) or not np.isfinite(wb).all() or np.any(wb <= 0) or not np.isfinite(gain):
        raise ValueError("white_balance must contain three positive finite RGB gains")
    x *= gain*wb
    sigma = float(settings.get("noise_std", 0))
    blur = float(settings.get("blur_sigma", 0))
    if not np.isfinite([sigma, blur]).all() or min(sigma, blur) < 0:
        raise ValueError("noise_std and blur_sigma must be finite and nonnegative")
    if sigma:
        x += rng.normal(0, sigma/255, x.shape)
    if blur:
        x = cv2.GaussianBlur(x, (0, 0), blur)
    result = np.round(np.clip(x, 0, 1)*255).astype(np.uint8)
    if "jpeg_quality" in settings:
        quality = settings["jpeg_quality"]
        if not isinstance(quality, int) or not 1 <= quality <= 100:
            raise ValueError("jpeg_quality must be an integer from 1 to 100")
        ok, encoded = cv2.imencode(".jpg", result[:, :, ::-1], [cv2.IMWRITE_JPEG_QUALITY, quality])
        if not ok:
            raise RuntimeError("JPEG encoding failed")
        result = cv2.imdecode(encoded, cv2.IMREAD_COLOR)[:, :, ::-1]
    return result
