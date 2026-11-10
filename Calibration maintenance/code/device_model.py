"""Camera models of the sensor device vs this project, and the conversion between them.

The device's pointcloud_colorizer (Sensor_Computer, src/node_pc/src/pointcloud_colorize.cpp) projects
with the OpenCV *pinhole* model: camera_matrix + dist_coeffs [k1, k2, p1, p2, k3] applied to
x/z, y/z. This project calibrates with the OpenCV *fisheye* model (k1, k2 on the ray angle). Both use
the same extrinsics (p_camera = R p_lidar + t, metres), so only the intrinsics are converted: by
fitting one model to reproduce the other's pixel for every ray that lands in the image. The fit
error (pixels) is reported with every conversion.

Note on the device: the colorizer reads camera_matrix as a flat list of 9 numbers. The nested
[[...], [...], [...]] form in its pipeline.yaml is not read (the node falls back to its built-in
default), so a new camera_matrix is always written flat.
"""
from __future__ import annotations

import numpy as np
from scipy.optimize import least_squares

DEFAULT_SIZE = (484, 366)
# pointcloud_colorize.cpp loadCameraParams(): values used when a parameter cannot be read as a flat list
COLORIZER_DEFAULT_K = [224.514866, 0.0, 243.278429, 0.0, 224.340765, 181.763517, 0.0, 0.0, 1.0]
COLORIZER_DEFAULT_D = [-0.212691, 0.087036, 0.0, 0.0, 0.0]


def _flat(v, n=None):
    """A flat list of numbers as roscpp getParam(std::vector<double>) reads it, else None."""
    if not isinstance(v, (list, tuple)) or not v or any(isinstance(x, (list, tuple, dict)) for x in v):
        return None
    try:
        out = [float(x) for x in v]
    except (TypeError, ValueError):
        return None
    return out if n is None or len(out) == n else None


# ------------------------------------------------------------------ device parameters
def file_params(raw, image_size=None):
    """Read explicit file values, without emulating the colorizer's built-in defaults."""
    if not isinstance(raw, dict):
        raise ValueError("The calibration file needs a pointcloud_colorizer mapping.")
    for key, size in (("camera_matrix", 9), ("dist_coeffs", 5), ("extrinsic_matrix", 16)):
        if key not in raw:
            raise ValueError(f"The device calibration file is missing {key}.")
        values = np.asarray(raw[key], dtype=float)
        if values.size != size or not np.isfinite(values).all():
            raise ValueError(f"{key} needs {size} finite numbers in the device calibration file.")
    data = dict(raw)
    notes = []
    if not data.get("image_width") or not data.get("image_height"):
        if image_size is None:
            raise ValueError("Image dimensions are missing from the file; receive a camera image and read the file again.")
        data["image_width"], data["image_height"] = image_size
        notes.append("Image dimensions come from the received camera image; they are absent from the calibration file.")
    if int(data["image_width"]) <= 0 or int(data["image_height"]) <= 0:
        raise ValueError("Image dimensions must be positive.")
    result = device_params(data)
    result["notes"] = notes
    return result


def device_params(raw, effective=False) -> dict:
    """Normalise pointcloud_colorizer parameters (ROS parameter server or pipeline.yaml).
    effective=True: the values the colorizer really uses, following its C++ rules: camera_matrix must be
    a flat list of 9 (the nested [[...]] form falls back to the built-in default), dist_coeffs any flat
    list (else the default), extrinsic_matrix a flat list of 16 (else identity). 'notes' says which
    fallback applied."""
    notes = []
    if effective:
        K = _flat(raw.get("camera_matrix"), 9)
        if K is None:
            K = COLORIZER_DEFAULT_K
            notes.append("camera_matrix is not a flat list of 9 numbers, so the colorizer ignores it and uses its built-in "
                         "default (fx 224.51, fy 224.34, cx 243.28, cy 181.76)")
        D = _flat(raw.get("dist_coeffs"))
        if D is None:
            D = COLORIZER_DEFAULT_D
            notes.append("dist_coeffs missing or not a flat list: the colorizer uses its built-in default")
        T = _flat(raw.get("extrinsic_matrix"), 16)
        if T is None:
            T = list(np.eye(4).ravel())
            notes.append("extrinsic_matrix is not a flat list of 16 numbers: the colorizer uses the identity")
    else:
        K, D, T = raw["camera_matrix"], raw.get("dist_coeffs", []), raw["extrinsic_matrix"]
    K = np.asarray(K, float).ravel()
    if K.size != 9:
        raise ValueError("camera_matrix must have 9 values")
    D = np.r_[np.asarray(D, float).ravel(), np.zeros(5)][:5]
    T = np.asarray(T, float).ravel()
    if T.size != 16:
        raise ValueError("extrinsic_matrix must have 16 values")
    out = dict(camera_matrix=K.reshape(3, 3).tolist(), dist_coeffs=D.tolist(), extrinsic_matrix=T.reshape(4, 4).tolist(),
               image_width=int(raw.get("image_width") or DEFAULT_SIZE[0]), image_height=int(raw.get("image_height") or DEFAULT_SIZE[1]))
    if notes:
        out["notes"] = notes
    return out


# ------------------------------------------------------------------ the two projections, per ray (angle theta off the axis, azimuth phi)
def _rays(theta_max, n_theta=90, n_phi=96):
    th, ph = np.meshgrid(np.linspace(np.radians(0.5), theta_max, n_theta), np.linspace(-np.pi, np.pi, n_phi, endpoint=False))
    return th.ravel(), ph.ravel()


def pinhole_uv(th, ph, fx, fy, cx, cy, D):
    k1, k2, p1, p2, k3 = D
    r = np.tan(th)
    x, y = r * np.cos(ph), r * np.sin(ph)
    r2 = r * r
    rad = 1 + k1 * r2 + k2 * r2 ** 2 + k3 * r2 ** 3
    xd = x * rad + 2 * p1 * x * y + p2 * (r2 + 2 * x * x)
    yd = y * rad + p1 * (r2 + 2 * y * y) + 2 * p2 * x * y
    return fx * xd + cx, fy * yd + cy


def fisheye_uv(th, ph, fx, fy, cx, cy, k):
    t2 = th * th
    td = th * (1 + k[0] * t2 + k[1] * t2 ** 2 + (k[2] * t2 ** 3 if len(k) > 2 else 0) + (k[3] * t2 ** 4 if len(k) > 3 else 0))
    return fx * td * np.cos(ph) + cx, fy * td * np.sin(ph) + cy


def pinhole_fold_deg(D, limit_deg=89.0):
    """Ray angle where the pinhole radial distortion stops increasing (points beyond fold back)."""
    r = np.tan(np.radians(np.linspace(0, limit_deg, 4000)))
    rho = r * (1 + D[0] * r ** 2 + D[1] * r ** 4 + D[4] * r ** 6)
    bad = np.flatnonzero(np.diff(rho) <= 0)
    return float(np.degrees(np.arctan(r[bad[0]]))) if len(bad) else limit_deg


def _inside(u, v, w, h):
    return (u >= 0) & (u <= w - 1) & (v >= 0) & (v <= h - 1)


def lidar_theta_max(xyz, T, q=99.5, margin_deg=3.0):
    """Largest angle off the camera axis at which this LiDAR's points arrive (degrees): the models
    only have to agree for these rays (Livox Avia: about 50 deg)."""
    c = np.asarray(xyz, float) @ np.asarray(T, float)[:3, :3].T + np.asarray(T, float)[:3, 3]
    c = c[c[:, 2] > 0]
    th = np.degrees(np.arctan2(np.hypot(c[:, 0], c[:, 1]), c[:, 2]))
    return float(min(np.percentile(th, q) + margin_deg, 80.0)) if len(th) else 55.0


# ------------------------------------------------------------------ device -> this project
def to_calibration(params, label="device", theta_max_deg=55.0) -> tuple[dict, dict]:
    """calibration.json (fisheye) reproducing the device's pinhole projection for the rays that reach
    the image within theta_max_deg of the camera axis (the LiDAR's field of view), and the fit report."""
    p = device_params(params)
    K, D, w, h = np.array(p["camera_matrix"]), np.array(p["dist_coeffs"]), p["image_width"], p["image_height"]
    fold = pinhole_fold_deg(D)
    th, ph = _rays(np.radians(min(fold - 0.5, theta_max_deg)))
    u, v = pinhole_uv(th, ph, K[0, 0], K[1, 1], K[0, 2], K[1, 2], D)
    ok = _inside(u, v, w, h)
    th, ph, u, v = th[ok], ph[ok], u[ok], v[ok]
    if len(th) < 50:
        raise ValueError("the device camera model puts almost no rays inside the image")

    def res(x):
        uu, vv = fisheye_uv(th, ph, x[0], x[1], x[2], x[3], x[4:6])
        return np.r_[uu - u, vv - v]
    sol = least_squares(res, np.r_[K[0, 0], K[1, 1], K[0, 2], K[1, 2], 0.0, 0.0], method="lm")
    e = np.hypot(*res(sol.x).reshape(2, -1))
    fx, fy, cx, cy, k1, k2 = sol.x
    report = dict(direction="device pinhole -> fisheye", rms_px=float(np.sqrt(np.mean(e ** 2))), max_px=float(e.max()),
                  lidar_rays_to_deg=theta_max_deg, covered_deg=float(np.degrees(th.max())), pinhole_valid_to_deg=fold)
    T = np.array(p["extrinsic_matrix"])
    cal = dict(method=f"{label}: pointcloud_colorizer parameters (pinhole k1 k2 p1 p2 k3) converted to the OpenCV fisheye model",
               convention="p_camera = R @ p_lidar + t (metres); OpenCV fisheye model", image_size=[w, h],
               intrinsics=dict(distortion_model="k1-k2", camera_matrix=[[fx, 0, cx], [0, fy, cy], [0, 0, 1]],
                               distortion_coefficients=[k1, k2, 0.0, 0.0]),
               extrinsics=dict(transform_lidar_to_camera=T.tolist()), device_parameters=p, conversion=report)
    return cal, report


# ------------------------------------------------------------------ this project -> device
def to_device(cal, previous=None, intrinsics=True, theta_max_deg=55.0) -> tuple[dict, dict]:
    """Device parameters for a calibration.json. intrinsics=False keeps the previous device intrinsics
    untouched (extrinsic-only update: nothing is re-fitted). Otherwise k1, k2 (and k3 if it helps) are
    fitted to the rays within theta_max_deg of the camera axis (the LiDAR's field of view); the radial
    map must keep increasing a few degrees beyond that, so no LiDAR point can fold back into the image."""
    T = np.asarray(cal["extrinsics"]["transform_lidar_to_camera"], float)
    w, h = cal.get("image_size") or ([previous["image_width"], previous["image_height"]] if previous else DEFAULT_SIZE)
    if not intrinsics:
        if previous is None:
            raise ValueError("an extrinsic-only update needs the previous device parameters")
        out = dict(device_params(previous), extrinsic_matrix=T.tolist())
        out.pop("notes", None)
        return out, dict(direction="extrinsics only", rms_px=0.0, max_px=0.0, note="device intrinsics kept unchanged")
    K = np.asarray(cal["intrinsics"]["camera_matrix"], float)
    k = np.r_[np.ravel(cal["intrinsics"]["distortion_coefficients"]), np.zeros(4)][:4]
    th, ph = _rays(np.radians(theta_max_deg))
    u, v = fisheye_uv(th, ph, K[0, 0], K[1, 1], K[0, 2], K[1, 2], k)
    ok = _inside(u, v, w, h)
    th, ph, u, v = th[ok], ph[ok], u[ok], v[ok]
    need = min(theta_max_deg + 5.0, 89.0)
    r_check = np.tan(np.radians(np.linspace(0, need, 400)))

    def fit(free_k3):
        def res(x):
            D = [x[4], x[5], 0.0, 0.0, x[6]]
            uu, vv = pinhole_uv(th, ph, x[0], x[1], x[2], x[3], D)
            rho = r_check * (1 + D[0] * r_check ** 2 + D[1] * r_check ** 4 + D[4] * r_check ** 6)
            fold = np.maximum(0, -np.diff(rho)) * 1e3            # keep the radial map increasing beyond the LiDAR's rays
            return np.r_[uu - u, vv - v, fold]
        full = (lambda x: x) if free_k3 else (lambda x: np.r_[x, 0.0])
        x0 = np.r_[K[0, 0], K[1, 1], K[0, 2], K[1, 2], -0.2, 0.03, 0.0][: 7 if free_k3 else 6]
        x = full(least_squares(lambda x: res(full(x)), x0, method="trf").x)
        D = [x[4], x[5], 0.0, 0.0, x[6]]
        uu, vv = pinhole_uv(th, ph, x[0], x[1], x[2], x[3], D)
        e = np.hypot(uu - u, vv - v)
        return x, D, e, pinhole_fold_deg(D)
    best = None
    for free_k3 in (False, True):
        x, D, e, fold = fit(free_k3)
        rms = float(np.sqrt(np.mean(e ** 2)))
        if fold >= need - 0.5 and (best is None or rms < best[3] - 0.02):
            best = (x, D, e, rms, fold)
    if best is None:
        raise ValueError("no pinhole model without fold-over reproduces this lens; the device cannot use it")
    x, D, e, rms, fold = best
    out = dict(camera_matrix=[[x[0], 0.0, x[2]], [0.0, x[1], x[3]], [0.0, 0.0, 1.0]], dist_coeffs=[float(d) for d in D],
               extrinsic_matrix=T.tolist(), image_width=int(w), image_height=int(h))
    return out, dict(direction="fisheye -> device pinhole", rms_px=rms, max_px=float(e.max()), lidar_rays_to_deg=theta_max_deg,
                     covered_deg=float(np.degrees(th.max())), pinhole_valid_to_deg=fold)


def shift_px(a, b, xyz):
    """How far two sets of device parameters put the same LiDAR points apart (device projection)."""
    out = []
    for p in (a, b):
        p = device_params(p)
        K, D, T = np.array(p["camera_matrix"]), np.array(p["dist_coeffs"]), np.array(p["extrinsic_matrix"])
        c = xyz @ T[:3, :3].T + T[:3, 3]
        z = np.maximum(c[:, 2], 1e-9)
        th = np.arctan2(np.hypot(c[:, 0], c[:, 1]), z)
        ph = np.arctan2(c[:, 1], c[:, 0])
        u, v = pinhole_uv(th, ph, K[0, 0], K[1, 1], K[0, 2], K[1, 2], D)
        out.append((u, v, (c[:, 2] > 0) & _inside(u, v, p["image_width"], p["image_height"]) & (th < np.radians(pinhole_fold_deg(D)))))
    (ua, va, oa), (ub, vb, ob) = out
    m = oa & ob
    return np.hypot(ua - ub, va - vb)[m]
