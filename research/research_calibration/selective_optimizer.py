"""Finite-step constrained optimization in a supplied measurement-supported subspace."""
import numpy as np
from scipy.optimize import least_squares


def optimize_selective(residual_fun, reference, free_indices, scales, basis=None, retract=None,
                        valid=None, max_normalized_step=3., max_nfev=80):
    reference, scales = np.asarray(reference,float),np.asarray(scales,float)
    if reference.ndim!=1 or scales.shape!=reference.shape or not np.isfinite(reference).all() or not np.isfinite(scales).all() or np.any(scales<=0):
        raise ValueError('Finite reference and positive matching scales required')
    free = list(free_indices)
    B = np.eye(len(reference))[:,free] if basis is None else np.asarray(basis,float)
    if B.ndim!=2 or B.shape[0]!=len(reference) or not np.isfinite(B).all():
        raise ValueError('Invalid reduced basis')
    forbidden = [i for i in range(len(reference)) if i not in free]
    if forbidden and np.any(np.abs(B[forbidden])>1e-10):
        raise ValueError('Basis permits a forbidden parameter update')
    initial = np.asarray(residual_fun(reference),float)
    if initial.ndim!=1 or not len(initial) or not np.isfinite(initial).all():
        raise ValueError('Finite nonempty residual required')
    if not B.shape[1]:
        return dict(parameters=reference.copy(),success=True,message='No supported update directions',nfev=0,cost=float(initial@initial/2))
    def physical(z):
        delta = scales*(B@z)
        candidate = retract(reference,delta) if retract else reference+delta
        if forbidden:
            candidate[forbidden] = reference[forbidden]
        return candidate
    def residual(z):
        p = physical(z)
        if valid and not valid(p):
            return np.full_like(initial,1e3)
        r = np.asarray(residual_fun(p),float)
        if r.shape!=initial.shape or not np.isfinite(r).all():
            raise ValueError('Residual contract changed during optimization')
        return r
    solution = least_squares(residual,np.zeros(B.shape[1]),bounds=(-max_normalized_step,max_normalized_step),
                             max_nfev=max_nfev,loss='linear',x_scale='jac',ftol=1e-7,xtol=1e-7,gtol=1e-7)
    p = physical(solution.x)
    okay = bool(solution.success and (valid(p) if valid else True))
    return dict(parameters=p if okay else reference.copy(),success=okay,message=solution.message,
                nfev=int(solution.nfev),cost=float(solution.cost),normalized_update=B@solution.x)
