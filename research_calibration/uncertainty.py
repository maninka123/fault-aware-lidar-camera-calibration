"""Conditional capture-cluster sandwich sensitivity, not calibrated fault confidence."""
import numpy as np
from scipy.linalg import null_space


def cluster_uncertainty(jacobian, residuals, cluster_ids, scales, observable_basis, rank_rtol=1e-5, min_clusters=4):
    J,r,ids,D,B = np.asarray(jacobian,float),np.asarray(residuals,float),np.asarray(cluster_ids),np.asarray(scales,float),np.asarray(observable_basis,float)
    if J.ndim!=2 or r.shape!=(len(J),) or ids.shape!=(len(J),) or D.shape!=(J.shape[1],) or B.ndim!=2 or B.shape[0]!=J.shape[1]:
        raise ValueError('Uncertainty array shapes disagree')
    if not np.isfinite(J).all() or not np.isfinite(r).all() or not np.isfinite(D).all() or not np.isfinite(B).all():
        raise ValueError('Nonfinite uncertainty inputs')
    if np.any(D<=0) or not np.allclose(B.T@B,np.eye(B.shape[1]),atol=1e-8):
        raise ValueError('Positive scales and orthonormal reduced basis required')
    clusters = np.unique(ids)
    result = dict(method='capture-cluster conditional sandwich',clusters=len(clusters),
                  calibrated_coverage=False,standard_deviations=[None]*len(D),covariance=None,
                  unobservable_directions=null_space(B.T),limitations=[
                      'Conditional on correspondences, selected subspace and extraction model.',
                      'Capture clusters may remain dependent within one scene/session.'])
    if len(clusters)<min_clusters or not B.shape[1]:
        return dict(result,status='INSUFFICIENT_CLUSTERS_OR_SUPPORT')
    A = (J*D)@B
    if np.linalg.matrix_rank(A,tol=rank_rtol*np.linalg.norm(A,2))<B.shape[1]:
        return dict(result,status='RANK_DEFICIENT')
    # Rank was checked on A. Do not silently truncate again after squaring its spectrum.
    _,s,Vt=np.linalg.svd(A,full_matrices=False)
    bread = (Vt.T/(s*s))@Vt
    scores = np.array([A[ids==cluster].T@r[ids==cluster] for cluster in clusters])
    centered = scores-scores.mean(axis=0)
    meat = centered.T@centered
    cov = bread@meat@bread * len(clusters)/(len(clusters)-1)
    physical = (D[:,None]*B)@cov@(D[:,None]*B).T
    covariance_rank = int(np.linalg.matrix_rank(cov))
    result.update(covariance=physical,covariance_rank=covariance_rank)
    if covariance_rank<B.shape[1] or len(clusters)<=B.shape[1]:
        return dict(result,status='INSUFFICIENT_CLUSTER_RANK')
    projector = B@B.T
    result['standard_deviations'] = [float(np.sqrt(max(0,physical[i,i]))) if projector[i,i]>1-1e-6 else None for i in range(len(D))]
    return dict(result,status='CONDITIONAL_ONLY')
