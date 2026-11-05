"""Frozen association batches, explicit visibility penalties and ungated held-out loss."""
from dataclasses import dataclass
import numpy as np
from scipy.spatial import cKDTree
from .legacy_adapter import legacy_modules


@dataclass
class AssociationBatch:
    xyz: np.ndarray
    signs: np.ndarray
    targets: np.ndarray
    normals: np.ndarray
    weights: np.ndarray
    cluster_ids: np.ndarray
    gate: float

    def residual(self,model,p):
        u,v,visible = model.project(model.to_camera(self.xyz,self.signs,p),p)
        signed = np.sum((np.c_[u,v]-self.targets)*self.normals,axis=1)
        # The legacy zero-for-invisible behavior must never reward lost observations.
        signed = np.where(visible,signed,np.sign(np.where(signed==0,1.,signed))*max(20.,2*self.gate))
        return np.nan_to_num(signed,nan=100.,posinf=100.,neginf=-100.)*self.weights


def associate(caps,model,p,gate,orientation_deg=30.,max_rows=4000):
    cb = legacy_modules().cb
    correspondence = cb.associate(caps,model,p,gate,np.cos(np.radians(orientation_deg)),np.array([1.,1.,.7]))
    xyz,signs,targets,normals,weights,clusters = [],[],[],[],[],[]
    budget = max(20,max_rows//max(1,len(caps)))
    for cluster,(cap,rows) in enumerate(zip(caps,correspondence)):
        index = np.arange(len(rows['i']))
        if len(index)>budget:
            index = np.linspace(0,len(index)-1,budget,dtype=int)
        if not len(index):
            continue
        ids = rows['i'][index]
        X,S,Q,N = cap.xyz[ids],cap.sgn[ids],rows['q'][index],rows['n'][index]
        u,v,_ = model.project(model.to_camera(X,S,p),p)
        r = np.sum((np.c_[u,v]-Q)*N,axis=1)
        robust = 1/np.sqrt(1+(r/2.)**2)
        xyz.append(X); signs.append(S); targets.append(Q); normals.append(N)
        weights.append(np.sqrt(rows['w'][index])*robust/np.sqrt(len(index)*len(caps)))
        clusters.append(np.full(len(index),cluster))
    if not xyz:
        return AssociationBatch(np.empty((0,3)),np.array([]),np.empty((0,2)),np.empty((0,2)),np.array([]),np.array([],int),gate)
    return AssociationBatch(np.concatenate(xyz),np.concatenate(signs),np.concatenate(targets),np.concatenate(normals),
                            np.concatenate(weights),np.concatenate(clusters),gate)


def evaluate_capture(cap,model,p,baseline,cap_px=30.):
    """Fixed baseline-visible test support; invalid candidates receive a fixed loss."""
    _,_,support = model.project(model.to_camera(cap.xyz,cap.sgn,baseline),baseline)
    if not np.any(support) or not len(cap.img['q']):
        return dict(valid=False,reason='No baseline-visible evaluation edges',loss=None)
    points = cap.xyz[support]
    u,v,visible = model.project(model.to_camera(points,cap.sgn[support],p),p)
    distances = np.full(len(points),cap_px)
    valid = visible & np.isfinite(u)&np.isfinite(v)
    if np.any(valid):
        distances[valid] = cKDTree(cap.img['q']).query(np.c_[u[valid],v[valid]])[0]
    clipped = np.minimum(distances,cap_px)
    return dict(valid=True,loss=float(np.mean((clipped/cap_px)**2)),
                capped_edge_rmse_px=float(np.sqrt(np.mean(clipped**2))),median_edge_distance_px=float(np.median(distances)),
                edge_match_share=float(np.mean(distances<=2.)),coverage=float(np.mean(valid)),points=len(points),
                lost_projections=int((~valid).sum()),cap_px=cap_px,
                scope='Same baseline-visible held-out edge points; nearest-edge proxy; invalid projections penalized')
