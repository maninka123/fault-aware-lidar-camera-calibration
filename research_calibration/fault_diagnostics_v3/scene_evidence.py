"""Interpretable scene diagnostics on existing LiDAR feature types and associations."""
import numpy as np
from ..residuals import associate, AssociationBatch
from .config import SignatureConfig
from .geometry_signatures import residual_signature


def scene_summary(cap, model, p):
    xyz = np.asarray(cap.xyz, float)
    pc = model.to_camera(xyz, cap.sgn, p)
    u, v, visible = model.project(pc, p)
    valid = visible & np.isfinite(pc).all(axis=1) & np.isfinite(u) & np.isfinite(v)
    valid &= np.isfinite(xyz).all(axis=1) & np.any(xyz != 0, axis=1)
    if not np.any(valid):
        return dict(valid=False, visible_share=0., points=len(xyz), reason='No finite front-camera returns')
    x = pc[valid]; ranges = np.linalg.norm(x, axis=1)
    bearing = np.arctan2(np.linalg.norm(x[:, :2], axis=1), x[:, 2])
    q = np.asarray(cap.img.get('q', [])); n = np.asarray(cap.img.get('n', []))
    angles = np.mod(np.arctan2(n[:, 1], n[:, 0]), np.pi) if len(n) else np.array([])
    hist = np.histogram(angles, bins=8, range=(0, np.pi))[0].astype(float)
    prob = hist[hist > 0]/max(1., hist.sum())
    entropy = float(-np.sum(prob*np.log(prob))/np.log(8))
    cells = np.c_[np.clip((u[valid]/model.w*4).astype(int), 0, 3),
                  np.clip((v[valid]/model.h*4).astype(int), 0, 3)]
    depth = np.percentile(x[:, 2], [10, 50, 90])
    types = np.asarray(getattr(cap, 'typ', np.full(len(xyz), -1)))
    return dict(valid=True, points=len(xyz), visible_points=int(valid.sum()), visible_share=float(valid.mean()),
                depth_percentiles_m=depth, range_percentiles_m=np.percentile(ranges, [10, 50, 90]),
                relative_depth_span=float((depth[2]-depth[0])/max(depth[1], 1e-12)),
                angular_radius_percentiles_deg=np.degrees(np.percentile(bearing, [10, 50, 90])),
                image_grid_coverage=float(len(np.unique(cells, axis=0))/16),
                edge_orientation_entropy=entropy, image_edge_density=float(len(q)/(model.w*model.h)),
                lidar_feature_counts={name: int(np.sum(types == i)) for i, name in enumerate(('depth', 'crease', 'intensity'))},
                limitations=['Depth and crease labels are extractor predictions, not verified cross-modal correspondences.',
                             'Visible means projected in-domain; true camera occlusion is not known from edge points.'])


def capture_signature(cap, model, p, *, association_p=None, config=None):
    """Freeze orientation-aware associations once; never treat robust fit weights as covariance.

    The geometric-only ablation screen uses existing depth/crease edge labels.
    No new edge extractor or occlusion oracle is invented. All valid associated
    edge types remain available when scene_quality=False.
    """
    cfg = config or SignatureConfig()
    anchor = p if association_p is None else association_p
    batch = associate([cap], model, anchor, cfg.association_gate_px, max_rows=cfg.max_rows_per_capture)
    if cfg.scene_quality and len(batch.xyz):
        # Match the existing association output to original feature labels.
        # KD-tree is on LiDAR XYZ, not on image edges, and only retrieves labels.
        from scipy.spatial import cKDTree
        _, index = cKDTree(cap.xyz).query(batch.xyz)
        keep = np.asarray(cap.typ)[index] != 2
        batch = AssociationBatch(batch.xyz[keep], batch.signs[keep], batch.targets[keep], batch.normals[keep],
                                 batch.weights[keep], batch.cluster_ids[keep], batch.gate)
    signed = residual_signature(batch, model, p)
    keep = signed['valid']
    pc = model.to_camera(batch.xyz, batch.signs, p)
    return dict(jacobian=signed['jacobian'][keep], residuals=signed['residuals'][keep],
                xyz=batch.xyz[keep], targets=batch.targets[keep], normals=batch.normals[keep],
                depth=pc[keep, 2], projected=signed['projected'][keep],
                rows=int(keep.sum()), invalid_rows=int((~keep).sum()), scene=scene_summary(cap, model, p),
                noise_model='Declared common pixel scale; robust optimization weights are not measurement covariance.',
                association_scope='Fixed oriented nearest-edge correspondences; wrong associations remain possible.')


def observation_advice(scenes, ambiguity):
    rows = [s for s in scenes if s.get('valid')]
    advice = []
    groups = set(''.join(ambiguity))
    if 'T' in groups:
        advice.append('Record the same overlapping bearings at varied near and far ranges; translation scales inversely with range.')
    if 'R' in groups and 'I' in groups:
        advice.append('Add two-dimensional off-plane peripheral bearings and varied edge directions; even a wide horizontal great circle can alias yaw with principal point.')
    if rows and np.median([s['edge_orientation_entropy'] for s in rows]) < .5:
        advice.append('Seek edges with more varied directions; point-to-line measurements ignore tangential displacement.')
    if not advice:
        advice.append('Use a different scene or viewpoint with depth diversity, wide angular coverage and reliable geometric edges.')
    return dict(actions=advice, accumulation_window='A longer Avia window may add coverage only in a static scene; no predicted timing benefit is available.',
                scope='Geometry-based suggestions, not a simulated acquisition forecast.')
