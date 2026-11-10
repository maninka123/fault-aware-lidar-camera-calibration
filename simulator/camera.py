"""OpenCV pinhole Brown–Conrady and four-coefficient equidistant fisheye."""
from dataclasses import dataclass
import cv2
import numpy as np


@dataclass
class Camera:
    model: str
    width: int
    height: int
    K: np.ndarray
    D: np.ndarray

    def __post_init__(self):
        self.K = np.asarray(self.K, float)
        self.D = np.asarray(self.D, float).reshape(-1)
        if self.model not in ("pinhole", "fisheye"):
            raise ValueError("camera.model must be pinhole or fisheye")
        if not isinstance(self.width, int) or not isinstance(self.height, int) or min(self.width, self.height) < 2:
            raise ValueError("Image dimensions must be integers >= 2")
        if self.width*self.height > 1_048_576:
            raise ValueError("Conservative execution limit: at most 1,048,576 camera pixels per capture")
        if self.K.shape != (3, 3) or not np.isfinite(self.K).all() or self.K[0, 0] <= 0 or self.K[1, 1] <= 0:
            raise ValueError("camera.K must be finite 3x3 with positive focal lengths")
        if not np.allclose(self.K[2], [0, 0, 1]) or self.K[0, 1] != 0 or self.K[1, 0] != 0:
            raise ValueError("Only zero-skew OpenCV K is supported")
        if len(self.D) not in ((4,) if self.model == "fisheye" else (4, 5)) or not np.isfinite(self.D).all():
            raise ValueError("D must have four fisheye or four/five pinhole coefficients")
        if self.model == "fisheye":
            theta = np.linspace(0, np.pi / 2 - 1e-5, 4096)
            derivative = np.ones_like(theta)
            for i, k in enumerate(self.D):
                derivative += (2*i+3)*k*theta**(2*i+2)
            if np.min(derivative) <= 0:
                raise ValueError("Fisheye polynomial must be monotonic over the forward hemisphere")

    @classmethod
    def from_dict(cls, d):
        if set(d)-{"model", "width", "height", "K", "D", "focal_px"}:
            raise ValueError("Unsupported camera keys: " + str(set(d)-{"model", "width", "height", "K", "D", "focal_px"}))
        w, h = d.get("width", 484), d.get("height", 366)
        f = d.get("focal_px", 200.)
        return cls(d.get("model", "fisheye"), w, h,
                   np.array(d.get("K", [[f, 0, (w-1)/2], [0, f, (h-1)/2], [0, 0, 1]])),
                   np.array(d.get("D", [0., 0., 0., 0.])))

    def to_dict(self):
        return dict(model=self.model, width=self.width, height=self.height, K=self.K.tolist(), D=self.D.tolist())

    def project(self, points):
        p = np.asarray(points, float).reshape(-1, 3)
        finite = np.isfinite(p).all(axis=1) & (p[:, 2] > 1e-9)
        uv = np.full((len(p), 2), np.nan)
        if finite.any():
            if self.model == "fisheye":
                v, _ = cv2.fisheye.projectPoints(p[finite, None, :], np.zeros(3), np.zeros(3), self.K, self.D)
            else:
                v, _ = cv2.projectPoints(p[finite], np.zeros(3), np.zeros(3), self.K, self.D)
            uv[finite] = v.reshape(-1, 2)
        valid = finite & (uv[:, 0] >= 0) & (uv[:, 0] < self.width) & (uv[:, 1] >= 0) & (uv[:, 1] < self.height)
        return uv, valid

    def unproject(self, pixels):
        p = np.asarray(pixels, float).reshape(-1, 2)
        if self.model == "fisheye":
            # Solve theta_d(theta) directly, avoiding OpenCV's +/-pi/2 theta_d clamp.
            q = (p - self.K[:2, 2]) / np.diag(self.K)[:2]
            rd = np.linalg.norm(q, axis=1)
            lo, hi = np.zeros(len(p)), np.full(len(p), np.pi/2 - 1e-7)
            def poly(t):
                return t * (1 + sum(k*t**(2*i+2) for i, k in enumerate(self.D)))
            valid = rd <= poly(hi)
            for _ in range(55):
                mid = (lo + hi)/2
                sel = poly(mid) < rd
                lo = np.where(sel, mid, lo)
                hi = np.where(sel, hi, mid)
            theta = (lo+hi)/2
            scale = np.divide(np.sin(theta), rd, out=np.ones_like(rd), where=rd > 1e-14)
            rays = np.c_[q * scale[:, None], np.cos(theta)]
            rays[~valid] = np.nan
        else:
            q = cv2.undistortPointsIter(p[:, None, :], self.K, self.D, None, None,
                (cv2.TERM_CRITERIA_COUNT | cv2.TERM_CRITERIA_EPS, 100, 1e-12)).reshape(-1, 2)
            rays = np.c_[q, np.ones(len(q))]
            rays /= np.linalg.norm(rays, axis=1)[:, None]
        uv, _ = self.project(rays)
        if np.any(np.isfinite(rays).all(axis=1) & (np.linalg.norm(uv-p, axis=1) > 1e-5)):
            raise ValueError("Camera distortion inversion failed; reduce field of view or distortion")
        return rays

    def pixel_rays(self):
        u, v = np.meshgrid(np.arange(self.width), np.arange(self.height))
        return self.unproject(np.c_[u.ravel(), v.ravel()])
