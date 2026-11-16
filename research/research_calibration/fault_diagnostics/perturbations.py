"""Known calibration perturbations and sensor nuisances applied to recorded captures (verification only).

These do not simulate a sensor. They change one recorded capture in a declared way so that the correct answer is
known *relative to the recorded reference*:

* calibration perturbation: the calibration under assessment is the reference composed with a known change
  (R, T, I, or joint). The true correction is its inverse; its group is the attribution label. The reference's
  own unknown error is common to every condition, so labels are relative, not absolute physical truth.
* nuisances: the calibration is unchanged; one or all captures are degraded. The correct answer is "no
  calibration change". Image nuisances re-run the unchanged production edge extractor on the altered image.

Ghost edges (a displaced, attenuated copy of the image added to it) imitate a reflection in the enclosure
window: they create parallel edges a few pixels from the true ones, i.e. systematically misleading
correspondences. A desynchronised capture (image translated relative to the LiDAR data) imitates a temporary
timing or rolling-shutter error that is not a calibration change.
"""
import copy
import numpy as np
import cv2
from ..legacy_adapter import legacy_modules
from ..geometry import retract


def _unit(rng, n=3):
    v = rng.normal(size=n)
    return v/np.linalg.norm(v)


def calibration_change(p0, kind, magnitude, rng):
    """Return (delta, groups). magnitude: degrees (R), metres (T), pixels (principal point) or relative (focal)."""
    d = np.zeros(13)
    if kind == 'R':
        d[:3] = np.radians(magnitude)*_unit(rng)
        groups = ('R',)
    elif kind == 'T':
        d[3:6] = magnitude*_unit(rng)
        groups = ('T',)
    elif kind == 'I_pp':
        d[8:10] = magnitude*_unit(rng, 2)
        groups = ('I',)
    elif kind == 'I_focal':
        s = magnitude*(1 if rng.uniform() < .5 else -1)
        d[6] = p0[6]*s; d[7] = p0[7]*s
        groups = ('I',)
    elif kind == 'RT':
        d[:3] = np.radians(magnitude[0])*_unit(rng); d[3:6] = magnitude[1]*_unit(rng)
        groups = ('R', 'T')
    else:
        raise ValueError('Unknown perturbation kind: ' + str(kind))
    return d, groups


def perturbed(p0, delta):
    return retract(np.asarray(p0, float), np.asarray(delta, float))


def perturbed_calibration(original, model, p0, delta):
    from ..geometry import calibration_from_parameters
    cal = calibration_from_parameters(original, model, perturbed(p0, delta))
    cal.pop('method', None)
    return cal


def _with_image(cap, gray, circle):
    legacy = legacy_modules()
    cfg = legacy.settings.load_config()
    bgr = cv2.cvtColor(np.clip(gray, 0, 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)
    img = legacy.image.extract(bgr, circle, cfg['image'])
    out = legacy.cb.Capture(cap.name, cap.xyz, cap.dir, cap.typ, cap.sgn, img)
    for key in ('nid_xyz', 'nid_bin', 'capture_time'):
        if hasattr(cap, key):
            setattr(out, key, getattr(cap, key))
    return out


def _shift(gray, dx, dy):
    M = np.float32([[1, 0, dx], [0, 1, dy]])
    return cv2.warpAffine(gray, M, gray.shape[::-1], borderMode=cv2.BORDER_REFLECT)


def ghost(cap, circle, offset=(0., 5.), weight=.6):
    g = cap.img['gray'].astype(np.float32)
    return _with_image(cap, (g + weight*_shift(g, *offset))/(1 + weight), circle)


def spurious_lines(cap, circle, rng, count=60, contrast=90., length=(15, 60)):
    g = cap.img['gray'].astype(np.float32).copy()
    h, w = g.shape
    for _ in range(count):
        r = circle['radius']*.9*np.sqrt(rng.uniform()); a = rng.uniform(0, 2*np.pi)
        x0, y0 = circle['cx'] + r*np.cos(a), circle['cy'] + r*np.sin(a)
        L = rng.uniform(*length); b = rng.uniform(0, np.pi)
        x1, y1 = x0 + L*np.cos(b), y0 + L*np.sin(b)
        value = float(np.clip(g[int(np.clip(y0, 0, h-1)), int(np.clip(x0, 0, w-1))] + rng.choice([-1, 1])*contrast, 0, 255))
        cv2.line(g, (int(x0), int(y0)), (int(x1), int(y1)), value, 2)
    return _with_image(cap, g, circle)


def occlusion(cap, circle, rng, fraction=.25):
    """A camera-only occluder (dirt or an object outside the LiDAR view) over a sector of the image."""
    g = cap.img['gray'].astype(np.float32).copy()
    h, w = g.shape
    yy, xx = np.mgrid[:h, :w]
    a0 = rng.uniform(0, 2*np.pi); span = 2*np.pi*fraction
    ang = np.mod(np.arctan2(yy - circle['cy'], xx - circle['cx']) - a0, 2*np.pi)
    mask = ang < span
    g[mask] = cv2.GaussianBlur(g, (0, 0), 25)[mask]*.3 + 40
    return _with_image(cap, g, circle)


def blur(cap, circle, sigma=2.5):
    g = cap.img['gray'].astype(np.float32)
    return _with_image(cap, cv2.GaussianBlur(g, (0, 0), sigma), circle)


def low_light(cap, circle, rng, gain=.3, noise=4.):
    g = cap.img['gray'].astype(np.float32)*gain + rng.normal(0, noise, cap.img['gray'].shape)
    return _with_image(cap, g, circle)


def desynchronised(cap, circle, offset=(6., 0.)):
    return _with_image(cap, _shift(cap.img['gray'].astype(np.float32), *offset), circle)


def lidar_dropout(cap, rng, fraction=.4):
    """Remove the LiDAR edge points of one azimuth sector (partial LiDAR occlusion)."""
    legacy = legacy_modules()
    az = np.arctan2(cap.xyz[:, 1], cap.xyz[:, 0])
    lo = rng.uniform(az.min(), az.max())
    span = (az.max() - az.min())*fraction
    keep = ~((az >= lo) & (az <= lo + span))
    out = legacy.cb.Capture(cap.name, cap.xyz[keep], cap.dir[keep], cap.typ[keep], cap.sgn[keep], cap.img)
    for key in ('nid_xyz', 'nid_bin', 'capture_time'):
        if hasattr(cap, key):
            setattr(out, key, getattr(cap, key))
    return out


NUISANCES = ('ghost_all', 'spurious_lines_all', 'occlusion_all', 'blur_all', 'low_light_all',
             'desync_one', 'ghost_one', 'lidar_dropout_all')


def apply_nuisance(caps, circle, name, rng, index=None):
    """``index`` selects the single capture for the *_one nuisances (default: random)."""
    caps = list(caps)
    if name == 'ghost_all':
        return [ghost(c, circle) for c in caps]
    if name == 'spurious_lines_all':
        return [spurious_lines(c, circle, rng) for c in caps]
    if name == 'occlusion_all':
        return [occlusion(c, circle, rng) for c in caps]
    if name == 'blur_all':
        return [blur(c, circle) for c in caps]
    if name == 'low_light_all':
        return [low_light(c, circle, rng) for c in caps]
    if name == 'lidar_dropout_all':
        return [lidar_dropout(c, rng) for c in caps]
    if name in ('desync_one', 'ghost_one'):
        i = int(rng.integers(len(caps))) if index is None else int(index)
        caps[i] = desynchronised(caps[i], circle) if name == 'desync_one' else ghost(caps[i], circle)
        return caps
    raise ValueError('Unknown nuisance: ' + name)
