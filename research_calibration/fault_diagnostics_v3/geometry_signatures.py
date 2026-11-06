"""Analytic sensitivities of the repository's fisheye and beam-inflation model.

Columns use the existing thirteen *physical* local parameter increments. Rotation
is the SO(3) left retraction of ``geometry.retract``; translation is additive and
is NOT rotated by that retraction. These derivatives are conditional on frozen
point/edge associations. They do not differentiate an extractor or visibility.
"""
import numpy as np


def _skew(values):
    out = np.zeros((len(values), 3, 3))
    x, y, z = values.T
    out[:, 0, 1], out[:, 0, 2] = -z, y
    out[:, 1, 0], out[:, 1, 2] = z, -x
    out[:, 2, 0], out[:, 2, 1] = -y, x
    return out


def projection_jacobian(model, p, xyz, signs):
    """Return ``(uv[N,2], J[N,2,13], valid[N])`` in pixel/physical units.

    ``valid`` includes finite nonzero LiDAR returns, the projection's front-camera
    and angular/image/circle masks, and finite derivatives. Invalid output rows
    are zero: callers MUST use the mask, never regard these rows as evidence.
    Visibility boundaries have no derivative. k3/k4 are fixed model constants;
    k1/k2, focal lengths, principal point and the signed beam angle are included.
    """
    p, xyz, signs = np.asarray(p, float), np.asarray(xyz, float), np.asarray(signs, float)
    if p.shape != (13,) or not np.isfinite(p).all() or np.any(p[6:8] <= 0):
        raise ValueError('Expected thirteen finite parameters with positive focal lengths')
    if xyz.ndim != 2 or xyz.shape[1] != 3 or signs.shape != (len(xyz),):
        raise ValueError('Expected LiDAR points (N,3) and matching signs (N,)')
    count = len(xyz)
    uv, jacobian = np.zeros((count, 2)), np.zeros((count, 2, 13))
    source_ok = np.isfinite(xyz).all(axis=1) & np.isfinite(signs) & np.any(xyz != 0, axis=1)
    indices = np.flatnonzero(source_ok)
    valid = np.zeros(count, bool)
    if not len(indices):
        return uv, jacobian, valid
    points, side = xyz[indices], signs[indices]
    # The beam nuisance is a rotation about the LiDAR z axis BEFORE R_CL.
    beam_angle = side * p[12]
    cb, sb = np.cos(beam_angle), np.sin(beam_angle)
    inflated = np.column_stack((cb * points[:, 0] - sb * points[:, 1],
                                sb * points[:, 0] + cb * points[:, 1], points[:, 2]))
    rotation, translation = model.unpack(p)
    rotated = inflated @ rotation.T
    camera = rotated + translation
    finite_front = np.isfinite(camera).all(axis=1) & (camera[:, 2] > .2)
    local = np.flatnonzero(finite_front)
    if not len(local):
        return uv, jacobian, valid
    indices, camera, rotated = indices[local], camera[local], rotated[local]
    inflated, side = inflated[local], side[local]
    u, v, inside = model.project(camera, p)
    a, b = (camera[:, :2] / camera[:, 2, None]).T
    radius = np.hypot(a, b)
    theta = np.arctan(radius)
    t2 = theta * theta
    k1, k2 = p[10:12]
    k3, k4 = model.higher_order
    distorted_theta = theta * (1 + t2 * (k1 + t2 * (k2 + t2 * (k3 + t2 * k4))))
    derivative_theta = 1 + t2 * (3*k1 + t2 * (5*k2 + t2 * (7*k3 + t2 * 9*k4)))
    # s = g(atan(r))/r; beta = s'(r)/r. Series avoids cancellation on axis.
    scale, beta = np.empty_like(radius), np.empty_like(radius)
    near = radius < 1e-4
    r2 = radius[near] ** 2
    c2, c4 = k1 - 1/3, 1/5 - k1 + k2
    scale[near] = 1 + c2*r2 + c4*r2*r2
    beta[near] = 2*c2 + 4*c4*r2
    far = ~near
    rf = radius[far]
    scale[far] = distorted_theta[far] / rf
    beta[far] = (derivative_theta[far] * rf/(1+rf*rf) - distorted_theta[far]) / (rf**3)
    bearing = np.column_stack((a, b))
    d_distorted = scale[:, None, None]*np.eye(2) + beta[:, None, None]*bearing[:, :, None]*bearing[:, None, :]
    d_normalized = np.zeros((len(camera), 2, 3))
    iz = 1 / camera[:, 2]
    d_normalized[:, 0, 0], d_normalized[:, 1, 1] = iz, iz
    d_normalized[:, 0, 2], d_normalized[:, 1, 2] = -a*iz, -b*iz
    d_pixel = p[6:8][None, :, None] * (d_distorted @ d_normalized)
    derivative = np.zeros((len(camera), 2, 13))
    derivative[:, :, :3] = d_pixel @ (-_skew(rotated))
    derivative[:, :, 3:6] = d_pixel
    derivative[:, 0, 6], derivative[:, 1, 7] = a*scale, b*scale
    derivative[:, 0, 8], derivative[:, 1, 9] = 1, 1
    # theta^(2j+1)/r has a zero limit for k_j on the optical axis.
    theta3_over_r = np.divide(theta**3, radius, out=np.zeros_like(radius), where=radius > 0)
    derivative[:, :, 10] = p[6:8]*bearing*theta3_over_r[:, None]
    derivative[:, :, 11] = derivative[:, :, 10]*t2[:, None]
    beam_lidar = side[:, None]*np.column_stack((-inflated[:, 1], inflated[:, 0], np.zeros(len(inflated))))
    beam_camera = beam_lidar @ rotation.T
    derivative[:, :, 12] = np.einsum('nij,nj->ni', d_pixel, beam_camera)
    values = np.column_stack((u, v))
    good = inside & np.isfinite(values).all(axis=1) & np.isfinite(derivative).all(axis=(1, 2))
    valid[indices[good]] = True
    uv[indices[good]], jacobian[indices[good]] = values[good], derivative[good]
    return uv, jacobian, valid


def residual_signature(batch, model, p, *, scales=None, weighted=False):
    """Frozen point-to-line residual and signature with an authoritative row mask.

    Default rows are signed pixel distances, NOT robust or capture-normalized
    scores. ``weighted=True`` explicitly reproduces ``AssociationBatch.weights``;
    these weights are not a measurement covariance. ``scales`` optionally maps
    physical columns to normalized parameter increments by J @ diag(scales).
    """
    uv, derivative, valid = projection_jacobian(model, p, batch.xyz, batch.signs)
    targets, normals = np.asarray(batch.targets, float), np.asarray(batch.normals, float)
    if targets.shape != uv.shape or normals.shape != uv.shape:
        raise ValueError('Targets and normals must match the projected (N,2) rows')
    valid &= np.isfinite(targets).all(axis=1) & np.isfinite(normals).all(axis=1)
    valid &= np.linalg.norm(normals, axis=1) > 0
    residual = np.zeros(len(uv))
    jacobian = np.zeros((len(uv), 13))
    residual[valid] = np.sum((uv[valid] - targets[valid])*normals[valid], axis=1)
    jacobian[valid] = np.einsum('ni,nij->nj', normals[valid], derivative[valid])
    if scales is not None:
        scales = np.asarray(scales, float)
        if scales.shape != (13,) or not np.isfinite(scales).all() or np.any(scales <= 0):
            raise ValueError('Expected thirteen positive finite parameter scales')
        jacobian *= scales
    if weighted:
        weights = np.asarray(batch.weights, float)
        if weights.shape != (len(uv),) or not np.isfinite(weights).all() or np.any(weights < 0):
            raise ValueError('Expected finite nonnegative matching residual weights')
        residual *= weights
        jacobian *= weights[:, None]
    return dict(residuals=residual, jacobian=jacobian, valid=valid, projected=uv)
