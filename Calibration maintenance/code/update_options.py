"""Compare constrained calibration updates on identical, independently fitted folds."""
from __future__ import annotations

import math

import numpy as np

MODES = ('extrinsic', 'intrinsic', 'full')
LABELS = {'existing': 'Keep current', 'extrinsic': 'Alignment only',
          'intrinsic': 'Camera settings only', 'full': 'Camera + alignment'}


def free_parameters(mode, distortion_model):
    if mode not in MODES:
        raise ValueError(f'Unknown refinement mode: {mode}')
    indices = [12]  # beam-widening nuisance, fitted for every alternative
    if mode in ('extrinsic', 'full'):
        indices += list(range(6))
    if mode in ('intrinsic', 'full'):
        indices += list(range(6, 11)) + ([11] if distortion_model == 'k1-k2' else [])
    return sorted(indices)


def valid_solution(parameters):
    """Reject nonfinite, negative-focal and folded fisheye solutions."""
    if not np.isfinite(parameters).all() or min(parameters[6:8]) <= 0:
        return False
    theta_squared = np.linspace(0, np.pi / 2, 100) ** 2
    derivative = 1 + 3 * parameters[10] * theta_squared + 5 * parameters[11] * theta_squared ** 2
    return bool(np.all(derivative > 0))


def constrained_start(start, existing, mode):
    value = np.asarray(start).copy()
    if mode == 'extrinsic':
        value[6:12] = existing[6:12]
    elif mode == 'intrinsic':
        value[:6] = existing[:6]
    return value


def recommend(folds, minimum_gain=0.01, majority=0.66, min_folds=3):
    """Prefer the smaller update unless a paired held-out gain supports extra freedom.

    The two-standard-error rule is a conservative decision heuristic, not a confidence
    interval: image-region folds overlap and are not independent scene samples.
    """
    valid = [f for f in folds if all(math.isfinite(f['scores'][m]['on_edge_share'])
                                   for m in ('existing',) + MODES)]
    scores = {m: float(np.mean([f['scores'][m]['on_edge_share'] for f in valid])) if valid else None
              for m in ('existing',) + MODES}
    result = dict(selected=None, status='inconclusive', reason='Collect more captures to compare update options.',
                  scores=scores, folds=len(valid), minimum_gain=minimum_gain, paired_checks={})
    if len(valid) < min_folds:
        return result

    def beats(candidate, baseline):
        differences = np.array([f['scores'][candidate]['on_edge_share'] - f['scores'][baseline]['on_edge_share']
                                for f in valid])
        gain = float(differences.mean())
        error = float(differences.std(ddof=1) / np.sqrt(len(differences)))
        wins = int((differences > 0).sum())
        supported = gain >= minimum_gain and gain > 2 * error and wins / len(valid) >= majority
        result['paired_checks'][candidate + '_vs_' + baseline] = dict(
            gain=gain, standard_error=error, wins=wins, total=len(valid), supported=bool(supported))
        return supported

    simple = [m for m in ('extrinsic', 'intrinsic') if beats(m, 'existing')]
    selected = 'extrinsic' if 'extrinsic' in simple else (simple[0] if simple else None)
    if len(simple) == 2 and beats('intrinsic', 'extrinsic'):
        selected = 'intrinsic'
    full_improves = beats('full', 'existing')
    # A joint update must beat every simpler alternative, not just the weakest one.
    if full_improves and all(beats('full', m) for m in ('extrinsic', 'intrinsic')):
        selected = 'full'
    if selected:
        result.update(selected=selected, status='supported',
                      reason={'extrinsic': 'Update alignment; keep the current camera settings.',
                              'intrinsic': 'Update camera settings; keep the current alignment.',
                              'full': 'Update both camera settings and alignment.'}[selected])
    else:
        result.update(status='keep', reason='No update has a clear advantage. Keep the current calibration.')
    return result


def compare(caps, model, existing, distortion_model, cfg, refine_cfg, prior, alignment, progress=None):
    """Fit each fold from the existing calibration using training data only.

    Capture holdouts are used when there are at least three captures; otherwise
    source LiDAR edges are held out by image region. All alternatives are scored
    on the same visible test points. No all-data solution seeds a held-out fit.
    """
    import calib as cb

    decision = cfg['decision']
    quiet = lambda *args: None

    def subset(capture, mask):
        return cb.Capture(capture.name, capture.xyz[mask], capture.dir[mask],
                          capture.typ[mask], capture.sgn[mask], capture.img)

    if len(caps) >= 3:
        folds = [(c.name, caps[:index] + caps[index + 1:], [c]) for index, c in enumerate(caps)]
        method = 'leave-one-capture-out'
    else:
        regions = []
        count = decision['regions']
        for capture in caps:
            u, v, visible = model.project(model.to_camera(capture.xyz, capture.sgn, existing), existing)
            angle = np.arctan2(v - model.circle['cy'], u - model.circle['cx'])
            radius = np.hypot(u - model.circle['cx'], v - model.circle['cy'])
            region = np.where(radius < model.circle['radius'] * 0.35, count - 1,
                              np.floor((angle + np.pi) / (2 * np.pi) * (count - 1)).astype(int) % (count - 1))
            regions.append(np.where(visible, region, -1))
        folds = [(f'Image region {index + 1}',
                  [subset(c, (r >= 0) & (r != index)) for c, r in zip(caps, regions)],
                  [subset(c, r == index) for c, r in zip(caps, regions)]) for index in range(count)]
        method = 'leave-one-image-region-out'

    results = []
    for index, (name, train, test) in enumerate(folds):
        if min(sum(len(c.xyz) for c in train), sum(len(c.xyz) for c in test)) < 100:
            continue
        if progress:
            progress(f'Comparing update options: check {index + 1} of {len(folds)}')
        baseline, _ = cb.refine(train, model, existing.copy(), [12], refine_cfg, prior,
                                log=quiet, gates=[4, 3, 2, 2], passes=2)
        coarse_cfg = dict(cfg['calib']['coarse'], per_focal=1)
        proposals = [baseline]
        for _, _, proposal in cb.coarse(train, model, baseline, coarse_cfg,
                                         np.random.default_rng(cfg['seed'] + index), quiet, fixed_intrinsics=True):
            proposal = proposal.copy()
            proposal[7], proposal[12] = existing[7], baseline[12]
            proposals.append(proposal)
        fitted = {'existing': baseline}
        for mode in MODES:
            candidates = []
            for start in proposals[:1] if mode == 'intrinsic' else proposals:
                try:
                    parameters, _ = cb.refine(train, model, constrained_start(start, existing, mode),
                                              free_parameters(mode, distortion_model), refine_cfg, prior,
                                              log=quiet, passes=cfg['refine']['passes'])
                except (ValueError, FloatingPointError, np.linalg.LinAlgError):
                    continue
                if valid_solution(parameters):
                    lift = alignment(train, model, parameters, cfg)['lift']
                    if np.isfinite(lift):
                        candidates.append((lift, parameters))
            if not candidates:
                break
            fitted[mode] = max(candidates, key=lambda item: item[0])[1]
        if len(fitted) != 4:
            continue
        common = []
        original_count = sum(len(c.xyz) for c in test)
        for capture in test:
            mask = np.ones(len(capture.xyz), dtype=bool)
            for parameters in fitted.values():
                _, _, visible = model.project(model.to_camera(capture.xyz, capture.sgn, parameters), parameters)
                mask &= visible
            common.append(subset(capture, mask))
        common_count = sum(len(c.xyz) for c in common)
        if common_count < 100 or common_count < original_count * 0.5:
            continue
        scores = {mode: alignment(common, model, parameters, cfg) for mode, parameters in fitted.items()}
        if max(value['matches'] for value in scores.values()) < decision['min_region_matches']:
            continue
        results.append(dict(left_out=name, common_points=common_count, scores=scores))
    result = recommend(results, decision.get('comparison_min_gain', 0.01), decision['heldout_majority'])
    result.update(method=method, checks=results,
                  limitation='Repeated views of one scene cannot independently establish that the lens changed.')
    return result
