"""Persistence monitoring of timestamped captures under a fixed current calibration.

Each capture i yields a scalar per cue: its decoy-referenced contrast x_i at the current calibration (larger is
better aligned). A calibration change lowers x for every later capture; a temporary nuisance (one blurred,
occluded or desynchronised capture) lowers it once. Two monitors are provided:

1. Robust CUSUM (Page 1954) on scores z_i = (m - x_i)/s, where m and s are the median and the scaled MAD of the
   first W captures (the reference window, assumed nominal):  S_i = max(0, S_{i-1} + z_i - k), alarm when
   S_i > h. k and h are declared constants; no false-alarm rate is claimed for them.

2. Conformal test martingale (Vovk et al., "Testing randomness online", Stat. Sci. 2021). The smoothed
   conformal p-value of x_i among x_1..x_i (small when x_i is unusually low) is passed through the mixture
   betting function  f(p) = integral_0^1 eps p^(eps-1) d eps, and M_i = prod_j f(p_j). If x_1, x_2, ... are
   exchangeable (no change), P(sup_i M_i >= 1/alpha) <= alpha (Ville's inequality). A CUSUM-style restarted
   variant (the "conformal CUSUM") detects later changes faster; its own guarantee is weaker and is not claimed.
   Exchangeability is an assumption: dependent static captures of one scene, or slowly varying scenes, violate it.

``classify`` labels the stream: PERSISTENT_CHANGE (alarm, and the post-alarm median stays below the reference
range), TRANSIENT_DEVIATION (isolated low scores that do not accumulate) or NO_CHANGE.
"""
import numpy as np


def robust_scores(values, window, scale_floor=.25):
    x = np.asarray(values, float)
    ref = x[:window][np.isfinite(x[:window])]
    if len(ref) < 2:
        raise ValueError('The reference window needs at least two finite values')
    m = float(np.median(ref))
    mad = float(np.median(np.abs(ref - m)))*1.4826
    # A window of a few captures under-represents capture-to-capture variation: floor the spread at a declared
    # fraction of the reference magnitude.
    s = max(mad, scale_floor*abs(m), 1e-6)
    return (m - x)/s, dict(median=m, scale=s, window=int(window))


def cusum(scores, drift, threshold, start, clip=np.inf):
    """One-sided CUSUM on Huber-clipped scores: S_i = max(0, S_{i-1} + min(z_i, clip) - drift)."""
    S, path, alarm = 0., [], None
    for i, z in enumerate(scores):
        if i < start or not np.isfinite(z):
            path.append(0. if i < start else S); continue
        S = max(0., S + min(float(z), clip) - drift)
        path.append(S)
        if alarm is None and S > threshold:
            alarm = i
    return dict(path=path, alarm=alarm)


def _mixture_bet(p):
    # integral_0^1 eps p^(eps-1) d eps, closed form; equals 1/2 at p=1 and grows as p -> 0.
    p = min(max(float(p), 1e-12), 1.)
    if abs(p - 1.) < 1e-12:
        return .5
    L = np.log(p)
    return float((p*L - p + 1.)/(p*L*L))


def conformal_martingale(values, alpha, rng=None, start=1):
    """Smoothed conformal p-values of low values (degradation) and the mixture test martingale."""
    rng = rng or np.random.default_rng(0)
    x = np.asarray(values, float)
    M, C, pvals, mpath, cpath = 1., 1., [], [], []
    alarm = alarm_cusum = None
    for i in range(len(x)):
        if not np.isfinite(x[i]):
            pvals.append(None); mpath.append(M); cpath.append(C); continue
        past = x[:i+1][np.isfinite(x[:i+1])]
        lower = float(np.sum(past < x[i])); equal = float(np.sum(past == x[i]))
        p = (lower + rng.uniform()*equal)/len(past)
        pvals.append(p)
        if i >= start:
            b = _mixture_bet(p)
            M *= b
            C = max(1., C*b)
        mpath.append(M); cpath.append(C)
        if alarm is None and M >= 1/alpha:
            alarm = i
        if alarm_cusum is None and C >= 1/alpha:
            alarm_cusum = i
    return dict(p_values=pvals, martingale=mpath, alarm=alarm, conformal_cusum=cpath, conformal_cusum_alarm=alarm_cusum)


def monitor(values, cfg, times=None, rng=None, informative_floor=None):
    """values: per-capture contrasts in time order (one cue). Returns both monitors and a stream label.

    ``informative_floor``: when the reference-window median is below it, the cue cannot show a degradation
    (it is already at chance) and the stream is reported as uninformative instead of monitored."""
    x = np.asarray(values, float)
    order = np.argsort(times, kind='stable') if times is not None else np.arange(len(x))
    x = x[order]
    W = int(cfg.monitor_reference_window)
    if len(x) <= W:
        return dict(status='INSUFFICIENT_EVIDENCE', reason='The stream is not longer than the reference window.',
                    order=order.tolist())
    window = x[:W][np.isfinite(x[:W])]
    if informative_floor is not None and (len(window) < 2 or np.median(window) < informative_floor):
        return dict(status='UNINFORMATIVE', reason='The reference captures do not beat chance for this cue.',
                    order=order.tolist(), values=x.tolist())
    z, ref = robust_scores(x, W, cfg.monitor_scale_floor)
    cs = cusum(z, cfg.monitor_drift_allowance, cfg.monitor_threshold, W, cfg.monitor_score_clip)
    cm = conformal_martingale(x, cfg.monitor_alpha, rng, start=W)
    return dict(order=order.tolist(), values=x.tolist(), reference=ref, scores=z.tolist(), cusum=cs, conformal=cm,
                status=classify(z, cs['alarm'], cfg), assumptions=[
                    'The first captures of the stream are nominal (reference window).',
                    'Conformal guarantee needs exchangeable captures under no change; static captures may violate it.',
                    'CUSUM constants are declared, not calibrated to a false-alarm rate.'])


def classify(scores, alarm, cfg):
    z = np.asarray(scores, float)
    W = int(cfg.monitor_reference_window)
    tail = z[W:]
    if alarm is None:
        # Isolated captures far below the reference range, which the clipped CUSUM did not accumulate.
        high = int(np.sum(tail > cfg.monitor_score_clip))
        return 'TRANSIENT_DEVIATION' if high else 'NO_CHANGE'
    after = z[alarm:]
    # Persistent: the scores after the alarm stay above the allowance (median), not one isolated spike.
    if len(after) >= 2 and np.median(after) > cfg.monitor_drift_allowance:
        return 'PERSISTENT_CHANGE'
    if len(after) < 2:
        return 'CHANGE_AT_END_UNCONFIRMED'
    return 'TRANSIENT_DEVIATION'
