"""Compare constrained calibration updates on identical, independently fitted folds."""
from __future__ import annotations

import math
import copy

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
        indices += list(range(6, 11)) + ([11] if distortion_model != 'k1' else [])
    return sorted(indices)


def valid_solution(parameters, higher_order=(0.0, 0.0), theta_max=np.pi / 2):
    """Reject nonfinite, negative-focal and folded fisheye solutions."""
    if not np.isfinite(parameters).all() or min(parameters[6:8]) <= 0:
        return False
    theta_squared = np.linspace(0, theta_max, 100) ** 2
    derivative = 1 + 3 * parameters[10] * theta_squared + 5 * parameters[11] * theta_squared ** 2
    derivative += 7 * higher_order[0] * theta_squared ** 3 + 9 * higher_order[1] * theta_squared ** 4
    return bool(np.all(derivative > 0))


def constrained_start(start, existing, mode):
    value = np.asarray(start).copy()
    if mode == 'extrinsic':
        value[6:12] = existing[6:12]
    elif mode == 'intrinsic':
        value[:6] = existing[:6]
    return value


def edge_distance_metrics(caps, model, parameters):
    """Median nearest-image-edge distance over all common visible held-out points.

    Unlike the matched-edge residual, there is no 2 px acceptance gate here.
    This is an edge-distance proxy, not a known-correspondence reprojection error.
    """
    from scipy.spatial import cKDTree

    distances = []
    for capture in caps:
        if not len(capture.img['q']):
            return None
        u, v, visible = model.project(model.to_camera(capture.xyz, capture.sgn, parameters), parameters)
        visible &= np.isfinite(u) & np.isfinite(v)
        if np.any(visible):
            distance, _ = cKDTree(capture.img['q']).query(np.c_[u[visible], v[visible]])
            distances.append(distance)
    if not distances:
        return None
    distance = np.concatenate(distances)
    squared_sum = float(np.dot(distance, distance))
    return dict(median_edge_distance_px=float(np.median(distance)), edge_rmse_px=float(np.sqrt(squared_sum / len(distance))),
                edge_squared_error_sum=squared_sum, edge_test_points=int(len(distance)))


def edge_distance_error(caps, model, parameters):
    metrics = edge_distance_metrics(caps, model, parameters)
    return metrics['median_edge_distance_px'] if metrics else None


def rmse_changes(comparison):
    """Pool squared edge distances on the same held-out points for every option."""
    modes = ('existing',) + MODES
    squared, count, folds = dict.fromkeys(modes, 0.), 0, 0
    for check in comparison.get('rmse_checks', comparison.get('checks', [])):
        values = [check.get('scores', {}).get(mode, {}) for mode in modes]
        counts = [value.get('edge_test_points') for value in values]
        sums = [value.get('edge_squared_error_sum') for value in values]
        if not all(isinstance(n, (int, float)) and math.isfinite(n) and n > 0 for n in counts):
            continue
        if len(set(counts)) != 1 or not all(isinstance(x, (int, float)) and math.isfinite(x) and x >= 0 for x in sums):
            continue
        count += int(counts[0])
        folds += 1
        for mode, value in zip(modes, sums):
            squared[mode] += value
    if not count:
        return {}
    errors = {mode: math.sqrt(value / count) for mode, value in squared.items()}
    before = errors['existing']
    return {mode: dict(before_px=before, after_px=after, reduction_px=before - after,
                       reduction_percent=(before - after) / before * 100 if before else None,
                       points=count, checks=folds) for mode, after in errors.items()}


def error_changes(comparison):
    """Summarise the same finite folds for every option; support older saved runs.

    Older runs only saved residuals for their accepted matches. Keep that metric
    visibly distinct and never infer pixel errors from the edge-match percentages.
    """
    modes = ('existing',) + MODES
    checks = comparison.get('checks', [])
    for metric, title, scope in (
            ('median_edge_distance_px', 'Edge error', 'All tested edges'),
            ('median_residual_px', 'Matched-edge error', 'Matched edges only')):
        paired = []
        for check in checks:
            values = [check.get('scores', {}).get(mode, {}).get(metric) for mode in modes]
            shares = [check.get('scores', {}).get(mode, {}).get('on_edge_share') for mode in modes]
            if all(isinstance(value, (int, float)) and math.isfinite(value) and value >= 0 for value in values) \
                    and all(isinstance(value, (int, float)) and math.isfinite(value) for value in shares):
                paired.append(values)
        if not paired:
            continue
        means = np.mean(paired, axis=0)
        before = float(means[0])
        return {mode: dict(before_px=before, after_px=float(after),
                           reduction_px=before - float(after),
                           reduction_percent=(before - float(after)) / before * 100 if before > 0 else None,
                           metric=metric, title=title, scope=scope, checks=len(paired))
                for mode, after in zip(modes, means)}
    return {}


def error_readout(change, mode):
    """Short card copy, including deterioration and unavailable denominators."""
    if not change:
        return 'Pixel error unavailable', 'Run Compare update options to measure it.'
    before, after = change['before_px'], change['after_px']
    digits = 2 if max(before, after) < 10 else 1
    values = f'{before:.{digits}f} px' if mode == 'existing' else f'{before:.{digits}f} → {after:.{digits}f} px'
    heading = f'{change["title"]}: {values}'
    if mode == 'existing':
        detail = 'Current error · ' + change['scope'].lower()
    elif abs(change['reduction_px']) < 1e-9:
        detail = 'No measured error change'
    else:
        percent = change['reduction_percent']
        absolute = f'{abs(change["reduction_px"]):.{digits}f} px'
        direction = 'less' if change['reduction_px'] > 0 else 'more'
        detail = f'{abs(percent):.1f}% {direction} error · {absolute} {direction}' if percent is not None \
            else f'{absolute} {direction} error · percentage unavailable'
    if change['metric'] == 'median_residual_px':
        detail = detail.replace('less error', 'lower matched residual').replace('more error', 'higher matched residual')
    return heading, detail


def fit_candidates(caps, model, starts, existing, mode, distortion_model, cfg, refine_cfg, prior, alignment):
    """Fit actual full-data candidates for one option, keeping its fixed group fixed."""
    import calib as cb

    candidates = []
    for name, start in starts:
        q = constrained_start(start, existing, mode)
        try:
            p, info = cb.refine(caps, model, q, free_parameters(mode, distortion_model), refine_cfg, prior,
                                log=lambda *args: None, passes=cfg['refine']['passes'])
        except (ValueError, FloatingPointError, np.linalg.LinAlgError):
            continue
        theta = model.validation_angle(caps, p) if hasattr(model, 'validation_angle') else np.pi / 2
        if not valid_solution(p, getattr(model, 'higher_order', (0., 0.)), theta):
            continue
        lift = alignment(caps, model, p, cfg)['lift']
        if math.isfinite(lift):
            candidates.append(dict(start=name, p=p, info=info, lift=lift))
    return candidates


def candidate_calibration(original, model, parameters, mode):
    """Store each fitted matrix, preserving the fixed group's original exact values."""
    result = copy.deepcopy(original)
    K, D, T = model.matrices(parameters)
    if mode in ('intrinsic', 'full'):
        result['intrinsics'].update(camera_matrix=K.tolist(), distortion_coefficients=D.tolist())
    if mode in ('extrinsic', 'full'):
        result['extrinsics'] = dict(transform_lidar_to_camera=T.tolist())
    return result


def projection_movement(model, existing, candidate, points):
    """Movement between projections; neither residual error nor quality improvement."""
    zero = np.zeros(len(points))
    u0, v0, valid0 = model.project(model.to_camera(points, zero, existing), existing)
    u1, v1, valid1 = model.project(model.to_camera(points, zero, candidate), candidate)
    distance = np.hypot(u1 - u0, v1 - v0)
    valid = valid0 & valid1 & np.isfinite(distance)
    if not np.any(valid):
        return None
    return dict(median_px=float(np.median(distance[valid])),
                p90_px=float(np.percentile(distance[valid], 90)), points=int(valid.sum()))


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
                theta_max = model.validation_angle(caps, parameters) if hasattr(model, 'validation_angle') else np.pi / 2
                if valid_solution(parameters, getattr(model, 'higher_order', (0.0, 0.0)), theta_max):
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
        for mode, parameters in fitted.items():
            metrics = edge_distance_metrics(common, model, parameters)
            if metrics:
                scores[mode].update(metrics)
        results.append(dict(left_out=name, common_points=common_count, scores=scores))
    result = recommend(results, decision.get('comparison_min_gain', 0.01), decision['heldout_majority'])
    result.update(method=method, checks=results,
                  limitation='Repeated views of one scene cannot independently establish that the lens changed.')
    return result
