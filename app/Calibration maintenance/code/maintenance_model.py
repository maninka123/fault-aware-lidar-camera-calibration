"""Maintenance projection retaining the starting calibration's higher fisheye terms.

The targetless solver refines k1/k2. k3/k4 stay fixed at their supplied values.
"""
from settings import TARGETLESS  # sets import paths and numerical-library thread limits

import numpy as np
import calib as cb


class Model(cb.Model):
    def __init__(self, R_mount, size, circle, distortion):
        super().__init__(R_mount, size, circle)
        self.higher_order = np.asarray(distortion, float)[2:4].copy()

    def project(self, Pc, p):
        if not np.any(self.higher_order):
            return super().project(Pc, p)
        fx, fy, cx, cy, k1, k2 = p[6:12]
        k3, k4 = self.higher_order
        front = Pc[:, 2] > 0.2
        a, b = (Pc[:, :2] / np.where(front, Pc[:, 2], 1.0)[:, None]).T
        r = np.hypot(a, b)
        theta = np.arctan(r)
        t2 = theta * theta
        scale = np.where(r > 1e-9, theta * (1 + t2 * (k1 + t2 * (k2 + t2 * (k3 + t2 * k4))))
                         / np.maximum(r, 1e-9), 1.0)
        u, v = fx * a * scale + cx, fy * b * scale + cy
        c = self.circle
        inside = front & ((u - c['cx']) ** 2 + (v - c['cy']) ** 2 <= (0.97 * c['radius']) ** 2)
        return u, v, inside

    def matrices(self, p):
        K, D, T = super().matrices(p)
        D[2:4] = self.higher_order
        return K, D, T

    def validation_angle(self, caps, p):
        """Check higher-order lenses over the rays present in these captures.

        A calibrated polynomial need not extrapolate to a 180-degree field of view.
        Keep the original validation range for the existing k1/k2 workflow.
        """
        if not np.any(self.higher_order):
            return np.pi / 2
        maximum = 0.0
        for capture in caps:
            camera = self.to_camera(capture.xyz, capture.sgn, p)
            camera = camera[camera[:, 2] > 0.2]
            if len(camera):
                maximum = max(maximum, float(np.arctan2(np.hypot(camera[:, 0], camera[:, 1]), camera[:, 2]).max()))
        return maximum or np.pi / 2
