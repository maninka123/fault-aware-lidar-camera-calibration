"""Offline V3 diagnostic sidecar; original production and V2 remain available."""
import json
from dataclasses import replace
from itertools import combinations
import time
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
from ..config import ResearchConfig
from ..geometry import ProjectionModel, parameters, calibration_from_parameters
from ..legacy_adapter import read_calibration, load_capture_bundle
from ..parameter_hypotheses import parameter_scales, HYPOTHESES
from ..observability import analyze_observability
from ..parameter_hypotheses import GROUPS
from ..reporting import serializable
from ..fault_diagnostics.config import DiagnosticsConfig
from ..fault_diagnostics.policy import decide_experimental, PolicySwitches
from ..fault_diagnostics.runner import assess_with_diagnostics, outer_evidence
from ..calibration_pipeline import fit_hypothesis, _training_selection
from ..residuals import evaluate_capture
from .config import SignatureConfig
from .hypothesis_separation import signature_report, minimal_explanations
from .scene_evidence import capture_signature, observation_advice
from .update_policy import update_contract, conservative_attribution
from .active_selection import select_observations

LIMITATIONS = [
    'Experimental offline output; no hardware-write path is called or authorized.',
    'Fixed nearest-edge associations can be wrong even with correct geometric derivatives.',
    'All existing recordings are V3 development data; anchors are not physical ground truth.',
    'Local distances use declared dimensionless whitened-RMS tolerances, not calibrated probabilities.',
    'Unbounded rival refits intentionally preserve aliases requiring large parameter changes.',
    'Static captures can remain dependent; no independent-sample or operational risk guarantee.',
    'Minimal explanations express parsimony; supersets with zero incremental effects cannot be excluded physically.',
]


def diagnose_from_records(calibration, bundle, records, production_payload, *, config=None,
                          signature_config=None, geometry=True, scene_quality=True, chance_correction=None):
    """Read identical existing fits; add no nonlinear fitting and consult no outer data.

    Effect estimates are actual training-only fitted fold corrections. The
    geometric analysis is descriptive on comparison captures, not a new blind
    test. It can expand aliases or replace V2's all-direction attribution veto
    with a check on the actually proposed direction. Cue ties are preserved.
    """
    started = time.perf_counter()
    cfg = config if isinstance(config, ResearchConfig) else ResearchConfig(**(config or {}))
    scfg = signature_config if isinstance(signature_config, SignatureConfig) else SignatureConfig(**(signature_config or {}))
    if not geometry: scfg = replace(scfg, geometric_signatures=False)
    if not scene_quality: scfg = replace(scfg, scene_quality=False)
    if chance_correction is not None: scfg = replace(scfg, chance_correction=chance_correction)
    diag = DiagnosticsConfig()
    base = decide_experimental(production_payload['evidence'],
                               dict(status=production_payload['production']['decision_status'],
                                    best_relative_gain=production_payload['production'].get('best_relative_gain')),
                               diag, PolicySwitches(chance_correction=scfg.chance_correction, intensity_cue=False,
                                                    quality_gating=scfg.scene_quality), min_captures=cfg.min_capture_blocks)
    out = dict(base, method='geometry-conditioned finite-effect V3', configuration=scfg.to_dict(),
               update_recommended=False, hardware_write_authorized=False, candidate_calibration=None,
               compatible_hypotheses=[], parameter_observability={}, expected_effect=None,
               recommended_observations={}, validation=dict(available=False), limitations=LIMITATIONS,
               uncertainty=dict(calibrated=False, fault_probability=None, scope='Descriptive local effect tolerances'))
    supported = base.get('supported', [])
    if not supported:
        out['seconds'] = time.perf_counter()-started
        return out
    best = max(supported, key=lambda h: base['counterfactuals'][h]['edge']['median'])
    out['best_evidence_hypothesis'] = best
    if not scfg.geometric_signatures:
        out.update(seconds=time.perf_counter()-started, reason=base['reason']+' Geometric signature analysis disabled.')
        return out
    original = read_calibration(calibration)
    model = ProjectionModel(original, bundle.size, bundle.circle, cfg.max_angle_rad)
    current = parameters(original); scales = parameter_scales(current)
    by_name = {c.name: c for c in bundle.caps}
    folds = [r for r in records if r.get('stage') == 'fold' and r['hypothesis'] == best]
    matrices, changes, scenes, ids, strata = [], [], [], [], []
    quality_ids = set(base.get('informative_captures', {}).get('edge', []))
    failures = []
    for row in folds:
        if not row['success'] or (scfg.scene_quality and row['test_id'] not in quality_ids):
            continue
        fitted = np.asarray(row['parameters'], float)
        signed = capture_signature(by_name[row['test_id']], model, current, association_p=fitted, config=scfg)
        scenes.append(signed['scene'])
        if signed['rows'] < scfg.min_rows:
            failures.append(dict(id=row['test_id'], rows=signed['rows'], reason='Too few reliable geometric correspondences'))
            continue
        matrices.append(signed['jacobian']*scales/scfg.pixel_sigma)
        delta = fitted-current
        delta[:3] = (Rotation.from_rotvec(fitted[:3])*Rotation.from_rotvec(current[:3]).inv()).as_rotvec()
        changes.append(delta/scales); ids.append(row['test_id'])
        if 'depth' in signed and 'projected' in signed:
            xy = signed['projected']
            region = (xy[:, 0] >= current[8]).astype(int)+2*(xy[:, 1] >= current[9]).astype(int)
            strata.append((signed['depth'], region))
    out['geometry_support'] = dict(capture_ids=ids, failed_captures=failures, scene_summaries=scenes)
    if len(matrices) < scfg.min_captures:
        # Detection came from held-out edges; no unsupported attribution follows.
        out.update(status='DRIFT_AMBIGUOUS', hypothesis=None,
                   reason='Edge evidence supports degradation, but too few captures support geometric diagnosis.',
                   recommended_observations=observation_advice(scenes, base.get('ambiguity_set', supported)),
                   seconds=time.perf_counter()-started)
        return out
    a = np.vstack(matrices); change_matrix = np.stack(changes)
    # Use an actual fold effect as representative. Coordinate medians need not
    # lie in any fold's supported subspace. Every fold must reject a rival before
    # the geometry can reject it; the representative is for explanation only.
    medoid = int(np.argmin(np.linalg.norm(change_matrix[:, None]-change_matrix[None, :], axis=2).sum(axis=1)))
    effect = change_matrix[medoid]
    report = signature_report(a, effect, rtol=scfg.rank_rtol)
    from .hypothesis_separation import effect_separation, HYPOTHESIS_COLUMNS
    fold_distances = {h: [effect_separation(a, d, h, rtol=scfg.rank_rtol)['rms'] for d in changes]
                      for h in HYPOTHESIS_COLUMNS}
    compatible = [h for h, values in fold_distances.items() if h != 'KEEP' and min(values) <= scfg.separation_rms]
    # Preserve held-out cue ties even if a single fitted direction rejects them.
    # A local derivative cannot overturn independently unresolved model evidence.
    compatible = list(dict.fromkeys(compatible+base.get('ambiguity_set', [])))
    ambiguity = minimal_explanations(compatible)
    # An unsupported subset alias must not erase a supported compound model.
    preserved = base.get('ambiguity_set', [])
    if any(h not in supported for h in ambiguity) or any(h not in ambiguity and
            any(set(k) < set(h) for k in ambiguity) for h in preserved):
        ambiguity = sorted(set(ambiguity+preserved), key=lambda h: (len(h), h))
    keep_distance = min(fold_distances['KEEP'])
    out.update(signatures=report, compatible_hypotheses=compatible, ambiguity_set=ambiguity,
               normalized_effect=effect, fold_effects=dict(capture_ids=ids, normalized=change_matrix,
                   representative_capture_id=ids[medoid], max_distance_from_representative=float(np.linalg.norm(change_matrix-effect, axis=1).max()),
                   rival_rms_by_fold=fold_distances, rejection_rule='A rival is rejected only if every fitted fold effect exceeds tolerance.'),
               expected_effect=dict(signal_rms_px=report['distances']['KEEP']['rms']*scfg.pixel_sigma,
                   definition='Representative actual fold correction: RMS point-to-line displacement after shared beam nuisance removal'),
               parameter_observability=analyze_observability(a, np.ones(13), GROUPS,
                   rank_rtol=scfg.rank_rtol, minimum_singular=cfg.minimum_singular),
               recommended_observations=observation_advice(scenes, ambiguity))
    if strata and len(strata) == len(matrices):
        depth = np.concatenate([s[0] for s in strata]); regions = np.concatenate([s[1] for s in strata])
        cuts = np.quantile(depth, [1/3, 2/3]); depth_bin = np.digitize(depth, cuts)
        out['geometric_explanations'] = {}
        for h, d in report['distances'].items():
            r = d['unexplained']*scfg.pixel_sigma
            out['geometric_explanations'][h] = dict(
                depth_cuts_m=cuts, depth_rms_px=[float(np.sqrt(np.mean(r[depth_bin == i]**2))) if np.any(depth_bin == i) else None for i in range(3)],
                image_quadrant_rms_px=[float(np.sqrt(np.mean(r[regions == i]**2))) if np.any(regions == i) else None for i in range(4)],
                scope='Contributions for the representative fitted effect after a single global rival/nuisance refit.')
    if len(ambiguity) > 1:
        effects = {h: report['distances'][h]['rival_normalized_effect'] for h in ambiguity}
        out['recommended_observations']['recorded_training_design'] = select_observations(
            matrices, effects, list(combinations(ambiguity, 2)), budget=min(cfg.training_budget, len(ids)),
            capture_ids=ids, training_ids=ids)
        out['recommended_observations']['recorded_training_design']['purpose'] = 'Prioritize already observed comparison captures for a subsequent training fit; no reserved outer capture is consulted.'
    if len(ambiguity) == 1 and ambiguity[0] in supported and keep_distance > scfg.detection_rms:
        out.update(status='DRIFT_SUPPORTED', hypothesis=ambiguity[0],
                   reason='Held-out edge gain and the fitted effect support one minimal geometric explanation.')
    else:
        out.update(status='DRIFT_AMBIGUOUS', hypothesis=None,
                   reason='Calibration degradation is supported, but competing groups explain the actual effect within the whitened-RMS tolerance.')
        if keep_distance <= scfg.detection_rms:
            out['compatible_hypotheses'].append('KEEP')
            out['reason'] += ' The local effect is also weak against nuisance-only KEEP.'
    out = conservative_attribution(base, out)
    out['seconds'] = time.perf_counter()-started
    return out


def diagnose_v3(calibration, captures, *, output, config=None, signature_config=None, bundle=None, write=True,
                cloud_units='m', allow_unusual_units=False):
    """Executable recorded-capture API with unchanged production/V2 comparisons."""
    cfg = config if isinstance(config, ResearchConfig) else ResearchConfig(**(config or {}))
    scfg = signature_config if isinstance(signature_config, SignatureConfig) else SignatureConfig(**(signature_config or {}))
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise FileExistsError('Use a new empty output folder')
    output.mkdir(parents=True, exist_ok=True)
    if bundle is None:
        dcfg = DiagnosticsConfig()
        bundle = load_capture_bundle(captures, output/'inputs', cfg.max_features_per_capture, cfg.seed, cloud_units, allow_unusual_units,
                                     intensity_points=dcfg.intensity_points, intensity_bins=dcfg.intensity_bins)
    records = []
    payload, result = assess_with_diagnostics(calibration, captures, output=output/'baseline', config=cfg,
                                            bundle=bundle, records_out=records)
    diagnosis = diagnose_from_records(calibration, bundle, records, payload, config=cfg, signature_config=scfg)
    # Only a uniquely supported hypothesis can produce an update candidate.
    if diagnosis['status'] == 'DRIFT_SUPPORTED':
        final = next(r for r in records if r.get('stage') == 'final')
        outer_ids = set(final['outer_ids'])
        train = [c for c in bundle.caps if c.name not in outer_ids]
        outer = [c for c in bundle.caps if c.name in outer_ids]
        original = read_calibration(calibration)
        model = ProjectionModel(original, bundle.size, bundle.circle, cfg.max_angle_rad)
        current = parameters(original)
        hyp = next(h for h in HYPOTHESES if h.name == diagnosis['hypothesis'])
        selected, _ = _training_selection(train, model, current, parameter_scales(current), cfg, 'fault_aware')
        start = time.perf_counter()
        fitted = fit_hypothesis(selected, model, current, hyp, cfg, 'fault_aware')
        diagnosis['candidate_fit_seconds'] = time.perf_counter()-start
        validation = dict(available=False)
        candidate = None
        if fitted['success']:
            candidate = calibration_from_parameters(original, model, fitted['parameters'])
            # The final nonlinear refit can change direction. Recheck its actual
            # geometric attribution before reserved evidence can validate it.
            # The best-scoring evidence bank may be a nested model different
            # from the minimal diagnosed hypothesis. Whichever bank the audit
            # chooses, it must inspect THIS actual refitted candidate.
            candidate_records = [dict(r, parameters=np.array(fitted['parameters'], copy=True))
                                 if r.get('stage') == 'fold' else r for r in records]
            check = diagnose_from_records(original, bundle, candidate_records, payload, config=cfg, signature_config=scfg)
            diagnosis['candidate_geometry_check'] = dict(status=check['status'], hypothesis=check.get('hypothesis'),
                                                        ambiguity_set=check.get('ambiguity_set', []))
            validation = outer_evidence(hyp.name, fitted['parameters'], fitted.get('supported_update'),
                                        outer, model, current, DiagnosticsConfig())
            validation['coverage_passed'] = bool(outer and all(evaluate_capture(c, model, fitted['parameters'], current)['coverage'] >= cfg.min_coverage for c in outer))
        geometry_ok = bool(fitted['success'] and diagnosis.get('candidate_geometry_check', {}).get('status') == 'DRIFT_SUPPORTED'
                           and diagnosis['candidate_geometry_check'].get('hypothesis') == hyp.name)
        diagnosis = update_contract(diagnosis, candidate=candidate, observable=bool(fitted.get('supported_update') and geometry_ok),
                                    uncertainty_status=fitted.get('uncertainty', {}).get('status'),
                                    training_ids=[c.name for c in train], validation_ids=[c.name for c in outer], validation=validation)
        diagnosis['uncertainty']['candidate'] = fitted.get('uncertainty', {})
    response = dict(v3=diagnosis, v2=payload['experimental']['proposed'], production=payload['production'],
                    baseline_cost=payload['cost'], temporal=payload['persistence'], limitations=LIMITATIONS)
    if write:
        (output/'fault_diagnostics_v3.json').write_text(json.dumps(serializable(response), indent=2, allow_nan=False)+'\n', encoding='utf-8')
    return response
