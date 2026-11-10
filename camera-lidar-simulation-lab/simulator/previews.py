"""Cheap CPU-only preview images for the launcher: LiDAR scan pattern and camera lens.

Nothing here renders with Blender or touches the GPU. Both previews are drawn from the
same sensor models that the dataset generator uses, so they show the real geometry.
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .camera import Camera
from .lidar import generate_rays

BG, PANEL, GRID, TEXT, MUTED = (15, 23, 42), (22, 32, 56), (51, 65, 95), (226, 232, 240), (148, 163, 184)

# Vertical/horizontal extent (deg) shown for each profile; azimuth is x-forward, left positive.
LIDAR_VIEW = {
    "livox_avia": ((-40, 40), (-40, 40), "non-repetitive · 70.4° × 77.2° FOV"),
    "livox_mid360": ((-180, 180), (-10, 62), "non-repetitive · 360° × 59° FOV"),
    "velodyne_vlp16": ((-180, 180), (-18, 18), "16 channels · 360° rotating"),
    "ouster_os1_64": ((-180, 180), (-26, 26), "64 channels · 360° rotating"),
    "hesai_at128": ((-70, 70), (-16, 17), "128 channels · 120° forward scan"),
}
# Accumulation window and thinning so the thumbnail stays fast but representative.
_WINDOW = {"livox_avia": (0.1, 4), "livox_mid360": (0.1, 4), "velodyne_vlp16": (0.1, 1),
           "ouster_os1_64": (0.1, 8), "hesai_at128": (0.1, 40)}


def _font(size):
    for name in ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def lidar_preview(profile: str, size=(320, 220)) -> Image.Image:
    """Scan pattern in azimuth/elevation, coloured by firing time within the window."""
    (az0, az1), (el0, el1), caption = LIDAR_VIEW[profile]
    duration, stride = _WINDOW[profile]
    rays = generate_rays(profile, 0.0, duration, {"stride": stride})
    d, t = rays["directions"], rays["timestamps"]
    az = np.degrees(np.arctan2(d[:, 1], d[:, 0]))
    el = np.degrees(np.arcsin(np.clip(d[:, 2], -1, 1)))
    w, h = size
    img = Image.new("RGB", size, BG)
    draw = ImageDraw.Draw(img)
    left, top, right, bottom = 34, 8, w - 8, h - 36
    draw.rectangle([left, top, right, bottom], fill=PANEL, outline=GRID)
    small = _font(9)
    for a in np.arange(np.ceil(az0 / 30) * 30, az1 + 1, 30 if az1 - az0 > 100 else 20):
        x = left + (a - az0) / (az1 - az0) * (right - left)
        draw.line([x, top, x, bottom], fill=GRID)
        draw.text((x, bottom + 3), f"{a:.0f}°", fill=MUTED, font=small, anchor="mt")
    for e in np.arange(np.ceil(el0 / 10) * 10, el1 + 1, 10):
        y = bottom - (e - el0) / (el1 - el0) * (bottom - top)
        draw.line([left, y, right, y], fill=GRID)
        draw.text((left - 4, y), f"{e:.0f}°", fill=MUTED, font=small, anchor="rm")
    keep = (az >= az0) & (az <= az1) & (el >= el0) & (el <= el1)
    px = left + (az[keep] - az0) / (az1 - az0) * (right - left)
    py = bottom - (el[keep] - el0) / (el1 - el0) * (bottom - top)
    tt = (t[keep] - t.min()) / max(np.ptp(t), 1e-12)
    colours = np.c_[56 + 199 * tt, 189 - 100 * tt, 248 - 150 * tt].astype(np.uint8)
    for x, y, c in zip(px, py, colours):
        draw.point((x, y), fill=tuple(int(v) for v in c))
        draw.point((x + 1, y), fill=tuple(int(v) for v in c))
    draw.text((left, bottom + 18), caption, fill=TEXT, font=_font(10))
    draw.text((right, bottom + 18), f"{duration * 1000:.0f} ms window", fill=MUTED, font=small, anchor="ra")
    return img


def camera_preview(model: str, width: int, height: int, focal_px: float, D=(0, 0, 0, 0),
                   size=(320, 220)) -> tuple[Image.Image, dict]:
    """What the lens sees of a synthetic room of lines of constant azimuth/elevation.

    Pixel rays come from the same Camera.unproject used for datasets, so FOV and distortion
    shown here match the generated images. Returns (image, info).
    """
    scale = min(size[0] / width, size[1] / height, 1.0)
    w, h = max(2, int(round(width * scale))), max(2, int(round(height * scale)))
    cam = Camera(model, w, h, np.array([[focal_px * scale, 0, (w - 1) / 2], [0, focal_px * scale, (h - 1) / 2], [0, 0, 1]]), np.array(D, float))
    rays = cam.pixel_rays().reshape(h, w, 3)
    ok = np.isfinite(rays).all(axis=2)
    r = np.nan_to_num(rays)
    az, el = np.degrees(np.arctan2(r[..., 0], r[..., 2])), -np.degrees(np.arcsin(np.clip(r[..., 1], -1, 1)))  # OpenCV y points down
    # Checker floor/ceiling tint plus grid lines every 10 degrees.
    checker = ((np.floor(az / 10) + np.floor(el / 10)) % 2).astype(float)
    img = np.zeros((h, w, 3), float)
    img[...] = np.where(el[..., None] > 0, (30, 58, 110), (24, 78, 70))
    img += checker[..., None] * 18
    line = (np.abs(((az + 5) % 10) - 5) < 0.55) | (np.abs(((el + 5) % 10) - 5) < 0.55)
    img[line] = (226, 232, 240)
    centre = np.hypot(az, el) < 1.2
    img[centre] = (251, 146, 60)
    img[~ok] = BG
    out = Image.new("RGB", size, BG)
    out.paste(Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)), ((size[0] - w) // 2, (size[1] - h) // 2))
    corners = rays[[0, 0, h - 1, h - 1], [0, w - 1, 0, w - 1]]
    angle = np.degrees(np.arccos(np.clip(corners[:, 2], -1, 1)))
    mid_l, mid_r = rays[h // 2, 0], rays[h // 2, w - 1]
    mid_t, mid_b = rays[0, w // 2], rays[h - 1, w // 2]
    def span(a, b):
        return float(np.degrees(np.arccos(np.clip(np.dot(a, b), -1, 1)))) if np.isfinite(a).all() and np.isfinite(b).all() else float("nan")
    info = dict(h_fov=span(mid_l, mid_r), v_fov=span(mid_t, mid_b),
                diagonal_fov=float(np.nanmax(2 * angle)) if np.isfinite(angle).any() else float("nan"))
    return out, info


def scan_pattern(profile: str, seconds: float = 1.0, max_points: int = 12000) -> dict:
    """Time-ordered beam directions (azimuth/elevation, degrees) over ``seconds`` for the browser animation.

    Rows are in firing order, so the first fraction f of the list is the scan after f*seconds.
    Thinned by an integer stride only; no points are invented.
    """
    probe = generate_rays(profile, 0.0, seconds, {"stride": 1})["metadata"]["generated_ray_count"]
    stride = max(1, int(np.ceil(probe / max_points)))
    rays = generate_rays(profile, 0.0, seconds, {"stride": stride})
    d = rays["directions"]
    az = np.degrees(np.arctan2(d[:, 1], d[:, 0]))
    el = np.degrees(np.arcsin(np.clip(d[:, 2], -1, 1)))
    (az0, az1), (el0, el1), caption = LIDAR_VIEW[profile]
    return dict(az=np.round(az, 2).tolist(), el=np.round(el, 2).tolist(), seconds=seconds,
                view=[az0, az1, el0, el1], stride=stride, nominal_points=int(probe), caption=caption)
