"""Image edges of a stacked camera image, with sub-pixel position and normal direction.

The median-stacked image is nearly noise-free, so plain Canny edges are reliable (thresholds fixed,
or "auto": percentiles of the image's own gradient magnitude); each edge
pixel is moved to the gradient-magnitude peak along its normal (parabola fit) and keeps its
unit normal, giving point-to-line residuals. A nearest-edge lookup table (distance transform
with indices) makes correspondence search a single array read.
"""
from __future__ import annotations

import cv2
import numpy as np
from scipy import ndimage


def _bilinear(img, x, y):
    h, w = img.shape
    x = np.clip(x, 0, w - 1.001); y = np.clip(y, 0, h - 1.001)
    x0, y0 = x.astype(int), y.astype(int)
    fx, fy = x - x0, y - y0
    return (img[y0, x0] * (1 - fx) * (1 - fy) + img[y0, x0 + 1] * fx * (1 - fy)
            + img[y0 + 1, x0] * (1 - fx) * fy + img[y0 + 1, x0 + 1] * fx * fy)


def extract(image, circle, ic):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float32)
    g = cv2.GaussianBlur(gray, (0, 0), ic["smooth_sigma"])
    gx, gy = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3), cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
    mag = np.hypot(gx, gy)
    h, w = gray.shape
    yy, xx = np.mgrid[:h, :w]
    inside = (xx - circle["cx"]) ** 2 + (yy - circle["cy"]) ** 2 <= (circle["radius"] * ic["circle_shrink"]) ** 2
    u8 = np.clip(g, 0, 255).astype(np.uint8)
    if ic["canny"] == "auto":       # thresholds from this image's own gradient statistics (any lighting / contrast)
        mu = np.hypot(cv2.Sobel(u8, cv2.CV_32F, 1, 0, ksize=3), cv2.Sobel(u8, cv2.CV_32F, 0, 1, ksize=3))[inside]
        lo, hi = (float(np.percentile(mu, q)) for q in ic["canny_percentiles"])
    else:
        lo, hi = ic["canny"]
    e = (cv2.Canny(u8, lo, hi, L2gradient=True) > 0) & inside
    ys, xs = np.nonzero(e)
    n = np.c_[gx[ys, xs], gy[ys, xs]]
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-9)
    m0 = mag[ys, xs]
    mp = _bilinear(mag, xs + n[:, 0], ys + n[:, 1])
    mm = _bilinear(mag, xs - n[:, 0], ys - n[:, 1])
    den = mm - 2 * m0 + mp
    off = np.clip(np.where(den < -1e-6, 0.5 * (mm - mp) / np.where(den < -1e-6, den, 1), 0), -0.5, 0.5)
    q = np.c_[xs + off * n[:, 0], ys + off * n[:, 1]]
    ids = np.full((h, w), -1, np.int32)
    ids[ys, xs] = np.arange(len(xs))
    dist, (iy, ix) = ndimage.distance_transform_edt(~e, return_indices=True)
    return dict(q=q, n=n, strength=m0, nearest=ids[iy, ix], dist=dist.astype(np.float32), mask=e, inside=inside,
                gray=gray)
