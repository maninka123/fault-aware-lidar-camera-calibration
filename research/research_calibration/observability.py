"""Scaled, prior-free conditional information and association-stable parameter subspaces.

Projection/TSVD/Schur complements are established methods; see PAPER_TO_ALGORITHM.md.
"""
import numpy as np
from scipy.linalg import null_space


def _matrix(value):
    result = np.asarray(value, float)
    if result.ndim != 2 or not np.isfinite(result).all():
        raise ValueError('Expected finite two-dimensional Jacobian')
    return result


def supported_svd(matrix, rtol=1e-5, minimum_singular=.02):
    if not np.isfinite([rtol,minimum_singular]).all() or min(rtol,minimum_singular)<0:
        raise ValueError('Finite nonnegative SVD thresholds required')
    A = _matrix(matrix)
    if not A.shape[0] or not A.shape[1]:
        return np.zeros((A.shape[0],0)), np.array([]), np.zeros((A.shape[1],0))
    U, s, Vt = np.linalg.svd(A, full_matrices=False)
    keep = s > max(minimum_singular, rtol*s[0])
    return U[:,keep], s, Vt[keep].T


def profile(matrix, nuisance, rtol=1e-8):
    """Thin orthogonal projection; never allocate an m×m residual projector."""
    A, B = _matrix(matrix), _matrix(nuisance)
    if A.shape[0] != B.shape[0]:
        raise ValueError('Profiled blocks must use the same observations')
    Q, _, _ = supported_svd(B, rtol, 0.)
    return A - Q @ (Q.T @ A)


def numerical_jacobian(fun, x, scales, retract=None, relative_step=1e-4):
    """Physical-coordinate central derivative with a fixed residual contract."""
    x, scales = np.asarray(x,float), np.asarray(scales,float)
    if x.ndim != 1 or scales.shape != x.shape or not np.isfinite(x).all() or not np.isfinite(scales).all() or np.any(scales<=0):
        raise ValueError('Finite vector and positive matching scales required')
    base = np.asarray(fun(x),float)
    if base.ndim != 1 or not np.isfinite(base).all():
        raise ValueError('Residual must be a finite fixed-size vector')
    J = np.empty((len(base),len(x)))
    for index, scale in enumerate(scales):
        step = scale*relative_step
        delta = np.zeros_like(x); delta[index] = step
        plus = retract(x,delta) if retract else x+delta
        minus = retract(x,-delta) if retract else x-delta
        a, b = np.asarray(fun(plus),float), np.asarray(fun(minus),float)
        if a.shape != base.shape or b.shape != base.shape or not np.isfinite(a).all() or not np.isfinite(b).all():
            raise ValueError('Residual shape/finite values changed during differentiation')
        J[:,index] = (a-b)/(2*step)
    return J


def analyze_observability(jacobian, scales, groups, nuisance_indices=(12,), row_weights=None,
                          rank_rtol=1e-5, minimum_singular=.02):
    J = _matrix(jacobian); scales = np.asarray(scales,float)
    if scales.shape != (J.shape[1],) or np.any(scales<=0) or not np.isfinite(scales).all():
        raise ValueError('Positive parameter scales required')
    A = J*scales
    if row_weights is not None:
        weights = np.asarray(row_weights,float)
        if weights.shape != (len(A),) or np.any(weights<0) or not np.isfinite(weights).all():
            raise ValueError('Invalid row weights')
        A = A*np.sqrt(weights[:,None])
    nuisance = A[:,list(nuisance_indices)]
    result = dict(groups={}, pairwise={}, prior_information_included=False)
    bases = {}
    calibration = sorted({i for indices in groups.values() for i in indices})
    for name, indices in groups.items():
        indices = list(indices)
        marginal = profile(A[:,indices],nuisance)
        others = list(nuisance_indices) + [i for i in calibration if i not in indices]
        unique = profile(A[:,indices],A[:,others])
        Q, singular, basis = supported_svd(marginal,rank_rtol,minimum_singular)
        _, unique_singular, unique_basis = supported_svd(unique,rank_rtol,minimum_singular)
        bases[name] = Q
        result['groups'][name] = dict(indices=indices, rank=basis.shape[1], unique_rank=unique_basis.shape[1],
            singular_values=singular, unique_singular_values=unique_singular,
            basis=basis, unique_basis=unique_basis, conditional_information=unique.T@unique,
            marginal_information=marginal.T@marginal,
            unique_energy_ratio=float(np.sum(unique**2)/max(np.sum(marginal**2),1e-30)))
    names = list(groups)
    for i, left in enumerate(names):
        for right in names[i+1:]:
            Q, V = bases[left],bases[right]
            cosines = np.linalg.svd(Q.T@V,compute_uv=False) if Q.shape[1] and V.shape[1] else np.array([])
            result['pairwise'][left+'|'+right] = dict(supported=bool(len(cosines)),
                principal_angles_deg=np.degrees(np.arccos(np.clip(cosines,0,1))))
    return result


def stable_subspace(matrices, rank_rtol=1e-5, minimum_singular=.02, support_floor=.98):
    """Right-space consensus followed by support AND sensitivity in every variant."""
    matrices = [_matrix(matrix) for matrix in matrices]
    if not np.isfinite(support_floor) or not 0<support_floor<=1:
        raise ValueError('Support floor must lie in (0,1]')
    if not matrices or len({matrix.shape[1] for matrix in matrices}) != 1:
        raise ValueError('Nonempty variants with a common parameter space required')
    n = matrices[0].shape[1]
    bases = [supported_svd(matrix,rank_rtol,minimum_singular)[2] for matrix in matrices]
    projectors = [basis@basis.T for basis in bases]
    mean = sum(projectors)/len(projectors)
    values, vectors = np.linalg.eigh(mean)
    order = np.argsort(values)[::-1]
    proposed = vectors[:,order[values[order]>=support_floor]]
    accepted = np.zeros((n,0))
    for column in proposed.T:
        trial = np.column_stack([accepted,column])
        support = min(float(np.linalg.eigvalsh(trial.T@P@trial).min()) for P in projectors)
        sensitivity = min(float(np.linalg.svd(A@trial,compute_uv=False)[-1]) if len(A) else 0. for A in matrices)
        if support >= support_floor-1e-10 and sensitivity > minimum_singular:
            accepted = trial
    checks=[dict(variant=i,support=float(np.linalg.eigvalsh(accepted.T@P@accepted).min()) if accepted.shape[1] else 0.,
                 minimum_singular=float(np.linalg.svd(A@accepted,compute_uv=False)[-1]) if accepted.shape[1] else 0.)
            for i,(A,P) in enumerate(zip(matrices,projectors))]
    return dict(basis=accepted, rank=accepted.shape[1], consensus_eigenvalues=values[::-1],variant_checks=checks,
                variant_ranks=[basis.shape[1] for basis in bases],
                worst_sensitivity=min(check['minimum_singular'] for check in checks),
                worst_support=min((float(np.linalg.eigvalsh(accepted.T@P@accepted).min()) for P in projectors),default=0.) if accepted.shape[1] else 0.)


def hypothesis_basis(jacobians, free_indices, nuisance_indices, scales, ensemble=True,
                     rank_rtol=1e-5, minimum_singular=.02, support_floor=.98):
    scales = np.asarray(scales,float)
    matrices = [_matrix(J)*scales for J in jacobians]
    if not matrices or any(A.shape[1]!=len(scales) for A in matrices):
        raise ValueError('Invalid variant Jacobians')
    free = sorted(set(free_indices)); nuisance = [i for i in nuisance_indices if i in free]
    calibration = [i for i in free if i not in nuisance]
    profiled = [profile(A[:,calibration],A[:,nuisance]) for A in matrices]
    if calibration:
        support = stable_subspace(profiled if ensemble else profiled[:1],rank_rtol,minimum_singular,support_floor)
        B = np.zeros((len(scales),support['rank']))
        B[calibration] = support['basis']
    else:
        support = dict(rank=0,variant_ranks=[0]*len(matrices)); B = np.zeros((len(scales),0))
    if nuisance:
        nuisance_support = stable_subspace([A[:,nuisance] for A in matrices] if ensemble else [matrices[0][:,nuisance]],
                                           rank_rtol,minimum_singular,support_floor)
        N = np.zeros((len(scales),nuisance_support['rank'])); N[nuisance] = nuisance_support['basis']
        B = np.column_stack([B,N])
    # An empty supported basis (e.g. KEEP when the beam nuisance is unobservable because a capture has no depth
    # edges) leaves every direction unobservable; LAPACK rejects the 0-row null-space problem.
    unobservable = null_space(B.T) if B.shape[1] else np.eye(len(scales))
    return dict(basis=B, rank=B.shape[1], calibration_rank=support['rank'],
                unobservable_directions=unobservable, diagnostics=support)


def ensemble_attribution(jacobians, scales, groups, nuisance=(12,), **kwargs):
    A = [_matrix(J)*np.asarray(scales) for J in jacobians]
    all_indices = sorted({i for indices in groups.values() for i in indices})
    result = {}
    for group, indices in groups.items():
        others = list(nuisance) + [i for i in all_indices if i not in indices]
        contrasts = [profile(matrix[:,list(indices)],matrix[:,others]) for matrix in A]
        result[group] = stable_subspace(contrasts,**kwargs)
    return result
