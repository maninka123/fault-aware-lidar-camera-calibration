"""Correspondence-aware alternating estimation, then geometry-conditioned diagnosis.

Why. Nearest-edge pairing at a mis-calibrated pose is wrong for a large share of points (measured on the development
recordings, see docs/research/v3/ROOT_CAUSE_ANALYSIS.md): the true counterpart of a point lies a few pixels away,
past other edges. Fault signatures built on those pairs explain the wrong displacement field faithfully and
attribute the wrong parameter group. When the pairs are right, the same signed-residual inference attributes
the injected group on the recorded geometry.

Method. The pairing and the calibration are estimated alternately (EM-ICP with deterministic annealing):

  E-step   responsibilities of candidate edges at the current calibration p (correspondence.associate, matching
           noise sigma_s);
  M-step   weighted Gauss-Newton step on the signed point-to-line residuals r_i with weights w_i = responsibility
           x balance, in normalized parameter units a = J diag(scale), on the identifiable subspace (truncated SVD, direction kept when sigma_s / s_k <= max_std) with a trust-region cap:
               min_b  sum_i w_i (r_i + a_i . b)^2 over that subspace,   p <- retract(p, scale * b);
  anneal   sigma_s and the gate shrink over the stages, so early stages can recover a displaced counterpart and late
           stages reject everything that is not geometrically consistent with the whole field.

All thirteen parameters are candidates, but only identifiable directions move. This stage is used
only to *establish pairings*; which parameter group changed is decided afterwards by ``diagnose_pairs`` from the
signed residuals of those pairings at the ORIGINAL (current) calibration, with the V3 signature inference and its
explicit ambiguity set. The joint estimate itself is not reported as a diagnosis: an alias can absorb part of it.
"""
from dataclasses import dataclass, asdict, replace
import numpy as np
from ..geometry import retract
from ..parameter_hypotheses import parameter_scales
from . import correspondence as C
from .diagnostic_inference import infer_signatures
from .config import SignatureConfig


@dataclass(frozen=True)
class EMConfig:
    sigmas_px: tuple = (4., 2.5, 1.5)
    gates_px: tuple = (14., 10., 7.)
    iterations_per_stage: int = 3
    max_std: float = 1.0              # a direction moves only if sigma_s / s_k <= max_std (normalized parameter units)
    max_step: float = 6.              # trust region: |b|_inf per iteration, normalized units
    min_rows: int = 60
    final_min_confidence: float = .4  # pairs kept for diagnosis must be this responsible at the final stage

    def to_dict(self):
        return asdict(self)


def _pairs(caps, model, p, cc):
    return {c.name: C.associate(c, model, p, cc) for c in caps}


def _normal_equations(caps, model, p, pairs, scales):
    a_all, r_all, w_all = [], [], []
    for c in caps:
        rows = C.signed_rows(c, pairs[c.name], model, p)
        if len(rows['residual']):
            a_all.append(rows['jacobian'] * scales); r_all.append(rows['residual']); w_all.append(rows['weight'])
    if not a_all:
        return None
    return np.vstack(a_all), np.concatenate(r_all), np.concatenate(w_all)


def _fixed_pair_cost(caps, model, p, pairs):
    total = weight = 0.
    for c in caps:
        rows = C.signed_rows(c, pairs[c.name], model, p)
        if len(rows['residual']):
            total += float(np.sum(rows['weight'] * np.minimum(rows['residual'] ** 2, 100.)))
            weight += float(rows['weight'].sum())
    return total / weight if weight > 0 else np.inf


def em_refine(caps, model, p0, correspondence=None, config=None):
    """Annealed alternation of pairing and calibration. Returns the estimate, its pairings and a stage trace."""
    cfg = config or EMConfig()
    base = correspondence or C.CorrespondenceConfig()
    scales = parameter_scales(p0)
    p = np.array(p0, float)
    trace = []
    pairs = None
    for sigma, gate in zip(cfg.sigmas_px, cfg.gates_px):
        cc = replace(base, sigma_px=sigma, gate_px=gate)
        for _ in range(cfg.iterations_per_stage):
            pairs = _pairs(caps, model, p, cc)
            system = _normal_equations(caps, model, p, pairs, scales)
            if system is None or len(system[1]) < cfg.min_rows:
                trace.append(dict(sigma=sigma, rows=0 if system is None else int(len(system[1])), step=0.))
                break
            a, r, w = system
            # Truncated-SVD step in the identifiable subspace: a direction with singular value s_k of sqrt(w) a has an
            # implied estimation std sigma_s / s_k (independent rows assumed, hence optimistic). Directions above
            # ``max_std`` are not moved: weak/aliased combinations stay at the current calibration.
            root = np.sqrt(w)
            u_, s_, vt_ = np.linalg.svd(a * root[:, None], full_matrices=False)
            keep = s_ >= sigma / cfg.max_std
            b = -(vt_[keep].T * (1. / s_[keep])) @ (u_[:, keep].T @ (root * r))
            top = np.max(np.abs(b))
            if top > cfg.max_step:
                b *= cfg.max_step / top
            before = _fixed_pair_cost(caps, model, p, pairs)
            step = 1.
            for _try in range(4):
                candidate = retract(p, step * b * scales)
                if model.valid(candidate) and _fixed_pair_cost(caps, model, candidate, pairs) < before:
                    p = candidate
                    break
                step *= .5
            else:
                step = 0.
            trace.append(dict(sigma=sigma, rows=int(len(r)), cost=float(before), step=float(step * np.max(np.abs(b)))))
    final = replace(base, sigma_px=cfg.sigmas_px[-1], gate_px=cfg.gates_px[-1])
    pairs = _pairs(caps, model, p, final)
    return dict(parameters=p, pairs=pairs, trace=trace)


def keep_confident(pairs, minimum):
    """Restrict pairings to rows whose final responsibility reaches ``minimum`` (others carry no evidence)."""
    out = {}
    for name, a in pairs.items():
        m = a['confidence'] >= minimum
        out[name] = dict(index=a['index'][m], q=a['q'][m], n=a['n'][m], confidence=a['confidence'][m],
                         weight=a['weight'][m], range=a['range'][m], stages=a.get('stages', {}))
    return out


def diagnose_pairs(caps, model, p, pairs, *, signature=None, max_rows=None, seed=5):
    """Signed-residual diagnosis of the *current* calibration ``p`` from fixed pairings (V3 signature inference).

    The residual change to be explained is -r (the correction that would zero each signed residual); each row's
    variance is sigma^2 / weight. Returns the inference result and the stacked row count.
    """
    cfg = signature or SignatureConfig()
    scales = parameter_scales(p)
    rng = np.random.default_rng(seed)
    cap_rows = max_rows or cfg.max_rows_per_capture
    J, r, var, ids = [], [], [], []
    for c in caps:
        rows = C.signed_rows(c, pairs[c.name], model, p)
        n = len(rows['residual'])
        if not n:
            continue
        pick = np.sort(rng.choice(n, cap_rows, replace=False)) if n > cap_rows else np.arange(n)
        J.append(rows['jacobian'][pick]); r.append(rows['residual'][pick])
        var.append(1. / np.maximum(rows['weight'][pick], .05)); ids += [c.name] * len(pick)
    if not J:
        return dict(status='INSUFFICIENT_EVIDENCE', hypothesis=None, ambiguity_set=[], supported=[], rows=0,
                    reason='No usable signed rows.')
    try:
        return infer_signatures(np.vstack(J), -np.concatenate(r), scales, covariance=np.concatenate(var),
                                capture_ids=np.array(ids), config=cfg)
    except ValueError as error:
        return dict(status='INSUFFICIENT_EVIDENCE', hypothesis=None, ambiguity_set=[], supported=[],
                    rows=int(sum(len(x) for x in r)), reason=str(error))


def diagnose_em(caps, model, p_current, *, correspondence=None, em=None, signature=None):
    """Full chain: annealed pairing estimation, confident pairs, signed-residual diagnosis at ``p_current``."""
    emc = em or EMConfig()
    fit = em_refine(caps, model, p_current, correspondence, emc)
    pairs = keep_confident(fit['pairs'], emc.final_min_confidence)
    result = diagnose_pairs(caps, model, p_current, pairs, signature=signature)
    return dict(result, joint_estimate=fit['parameters'], trace=fit['trace'],
                kept_rows=int(sum(len(a['index']) for a in pairs.values())))
