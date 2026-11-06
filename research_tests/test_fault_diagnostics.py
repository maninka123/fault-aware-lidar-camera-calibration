"""Experimental fault diagnostics (v2): cues, counterfactual evidence, policy, persistence monitor.

The synthetic captures below are small verification fixtures (straight 3D edges in front of a textured plane,
rendered through the production projection), not a sensor simulator.
"""
import copy
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
import cv2
from research_calibration.config import ResearchConfig
from research_calibration.geometry import ProjectionModel, parameters, retract
from research_calibration.legacy_adapter import legacy_modules
from research_calibration.residuals import evaluate_capture
from research_calibration.fault_diagnostics import DiagnosticsConfig
from research_calibration.fault_diagnostics.cues import CaptureCues
from research_calibration.fault_diagnostics.evidence import collect_evidence
from research_calibration.fault_diagnostics.policy import decide_experimental, PolicySwitches, ABLATIONS
from research_calibration.fault_diagnostics import sequential as S
from research_calibration.fault_diagnostics import perturbations as P
from test_mathematics import reference

SIZE = [484, 366]
CIRCLE = dict(cx=241.5, cy=182.5, radius=183.)


def _pattern(x, y, phase):
    return .5 + .25*np.sin(2.3*x + phase) * np.cos(1.9*y - phase) + .25*np.sin(.7*x*y + 3*phase)


def synthetic_capture(seed, clutter=False, name=None):
    """Straight 3D edges (LiDAR crease edges) in front of a reflectivity-textured plane z = 4 m."""
    rng = np.random.default_rng(seed)
    cal = reference(); model = ProjectionModel(cal, SIZE, CIRCLE); p = parameters(cal)
    phase = rng.uniform(0, np.pi)
    g = np.linspace(-6, 6, 700)
    X, Y = np.meshgrid(g, g); X, Y = X.ravel(), Y.ravel()
    plane = np.c_[X, Y, np.full(len(X), 4.)]
    u, v, ok = model.project(plane, p)
    image = np.zeros(SIZE[::-1], np.float32); count = np.zeros_like(image)
    ui = np.clip(np.rint(u[ok]).astype(int), 0, SIZE[0]-1); vi = np.clip(np.rint(v[ok]).astype(int), 0, SIZE[1]-1)
    np.add.at(image, (vi, ui), 60 + 120*_pattern(X[ok], Y[ok], phase)); np.add.at(count, (vi, ui), 1)
    image = np.where(count > 0, image/np.maximum(count, 1), 0)
    filled = cv2.dilate(image, np.ones((3, 3), np.uint8))
    image = np.where(count > 0, image, filled)
    xyz, dirs = [], []
    for _ in range(45):
        z = rng.uniform(2., 3.6)
        a = rng.uniform(-.75, .75, 2)*z
        d = rng.normal(size=3); d[2] *= .2; d /= np.linalg.norm(d)
        L = rng.uniform(.5, 1.3)
        t = np.arange(0, L, .01)
        pts = np.c_[a[0] + t*d[0], a[1] + t*d[1], z + t*d[2]]
        uu, vv, vis = model.project(pts, p)
        if vis.sum() < 20:
            continue
        value = float(rng.choice([15., 245.]))
        poly = np.c_[uu[vis], vv[vis]].astype(np.int32)
        cv2.polylines(image, [poly], False, value, 2, cv2.LINE_AA)
        xyz.append(pts[vis]); dirs.append(np.tile(d, (vis.sum(), 1)))
    if clutter:
        # Dense unrelated texture in the lower image: edges with no LiDAR counterpart.
        for _ in range(250):
            x0, y0 = rng.uniform(120, 360), rng.uniform(250, 330)
            b = rng.uniform(0, np.pi)
            cv2.line(image, (int(x0), int(y0)), (int(x0 + 12*np.cos(b)), int(y0 + 12*np.sin(b))), float(rng.choice([20., 230.])), 1)
    legacy = legacy_modules(); cfg = legacy.settings.load_config()
    img = legacy.image.extract(cv2.cvtColor(np.clip(image, 0, 255).astype(np.uint8), cv2.COLOR_GRAY2BGR), CIRCLE, cfg['image'])
    xyz = np.concatenate(xyz); dirs = np.concatenate(dirs)
    keep = rng.choice(len(xyz), min(1200, len(xyz)), replace=False)
    cap = legacy.cb.Capture(name or f'synthetic_{seed}', xyz[keep], dirs[keep], np.ones(len(keep), int), np.zeros(len(keep)), img)
    s = rng.choice(len(X), 20000, replace=False)
    refl = _pattern(X[s], Y[s], phase)
    cap.nid_xyz = plane[s]
    cap.nid_bin = np.argsort(np.argsort(refl + rng.uniform(0, 1e-6, len(s))))/len(s)*31
    return cap


def shifted(p, d_cy=0., d_cx=0., rx_deg=0.):
    d = np.zeros(13); d[8] = d_cx; d[9] = d_cy; d[0] = np.radians(rx_deg)
    return retract(p, d)


class CueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = ProjectionModel(reference(), SIZE, CIRCLE); cls.p = parameters(reference())
        cls.cap = synthetic_capture(1)
        cls.clutter = synthetic_capture(1, clutter=True)

    def test_contrast_is_positive_when_aligned_and_falls_with_misalignment(self):
        cc = CaptureCues(self.cap, self.model, self.p)
        aligned, off = cc.edge(self.p), cc.edge(shifted(self.p, d_cy=4.))
        self.assertTrue(aligned.valid)
        self.assertGreater(aligned.contrast, .1)
        self.assertLess(off.contrast, aligned.contrast - .05)
        i0, i1 = cc.intensity(self.p), cc.intensity(shifted(self.p, d_cy=4.))
        self.assertGreater(i0.contrast, 0.)
        self.assertGreater(i0.contrast, i1.contrast)

    def test_misleading_dense_edges_reward_the_production_loss_but_not_the_contrast(self):
        """Unrelated clutter below the scene: moving projections down lowers the nearest-edge loss."""
        down = shifted(self.p, d_cy=6.)
        loss = lambda cap, q: evaluate_capture(cap, self.model, q, self.p)['loss']
        clean_gain = loss(self.cap, self.p) - loss(self.cap, down)
        clutter_gain = loss(self.clutter, self.p) - loss(self.clutter, down)
        self.assertGreater(clutter_gain, clean_gain)          # the clutter makes the wrong calibration look better
        cc = CaptureCues(self.clutter, self.model, self.p)
        self.assertGreater(cc.edge(self.p).contrast, cc.edge(down).contrast + .05)   # the contrast does not

    def test_invisible_points_count_as_unmatched(self):
        cc = CaptureCues(self.cap, self.model, self.p)
        far = self.p.copy(); far[5] = -10.   # everything behind the camera
        e = cc.edge(far)
        self.assertEqual(e.value, 0.)
        self.assertEqual(e.points, len(cc.edge_support))

    def test_poor_visibility_capture_is_uninformative(self):
        cap = P.blur(self.cap, CIRCLE, sigma=12.)
        cap = P.low_light(cap, CIRCLE, np.random.default_rng(0), gain=.05, noise=6.)
        cc = CaptureCues(cap, self.model, self.p)
        cfg = DiagnosticsConfig()
        self.assertLess(cc.edge(self.p).contrast, cfg.edge_informative_contrast)

    def test_ghost_edges_mislead_edges_but_the_intensity_cue_prefers_the_truth(self):
        cap = P.ghost(self.cap, CIRCLE, offset=(0., 5.), weight=.9)
        cc = CaptureCues(cap, self.model, self.p)
        ghost_pose = shifted(self.p, d_cy=5.)
        # Both the true and the ghost-aligned calibration find parallel edges...
        self.assertGreater(cc.edge(ghost_pose).contrast, .05)
        # ...but reflectivity agrees with the true one.
        self.assertGreater(cc.intensity(self.p).contrast, cc.intensity(ghost_pose).contrast)


def _evidence(gains_edge, gains_int, ref_edge=.08, ref_int=.006, names=('R', 'T', 'I'), attribution=True,
              production_gain=0.):
    """Hand-built evidence table: gains_*[h] = per-capture changes."""
    n = len(next(iter(gains_edge.values())))
    tests = [f'c{i}' for i in range(n)]
    reference_ = {t: dict(edge_contrast=ref_edge, edge_valid=True, intensity_contrast=ref_int, intensity_valid=True,
                          edge_share=ref_edge + .1) for t in tests}
    folds = {'KEEP': {t: dict(success=True) for t in tests}}
    groups = {'R': ('R',), 'T': ('T',), 'I': ('I',), 'RT': ('R', 'T'), 'RI': ('R', 'I'), 'TI': ('T', 'I'), 'RTI': ('R', 'T', 'I')}
    for h in gains_edge:
        folds[h] = {t: dict(success=True, edge_change=gains_edge[h][i], edge_share_change=gains_edge[h][i],
                            edge_contrast=ref_edge + gains_edge[h][i], intensity_change=gains_int[h][i],
                            intensity_contrast=ref_int + gains_int[h][i], production_gain=production_gain, chance_gain=production_gain,
                            attribution_support={g: attribution for g in groups[h]}) for i, t in enumerate(tests)}
    informative = {t: dict(edge=True, intensity=True) for t in tests}
    return dict(tests=tests, reference=reference_, folds=folds, informative=informative)


PROD_KEEP = dict(status='KEEP_CURRENT', best_relative_gain=0.)


class PolicyTests(unittest.TestCase):
    def test_persistent_drift_supported_by_both_cues(self):
        ev = _evidence({'R': [.04]*7, 'T': [.0]*7}, {'R': [.002]*7, 'T': [0.]*7})
        d = decide_experimental(ev, PROD_KEEP)
        self.assertEqual(d['status'], 'DRIFT_SUPPORTED'); self.assertEqual(d['hypothesis'], 'R')
        self.assertFalse(d['update_recommended'])          # no independent outer captures
        outer = dict(available=True, hypothesis='R', supported_update=True, edge_confirms=True, intensity_contradicts=False)
        self.assertTrue(decide_experimental(ev, PROD_KEEP, outer=outer)['update_recommended'])
        bad = dict(outer, edge_confirms=False)
        self.assertFalse(decide_experimental(ev, PROD_KEEP, outer=bad)['update_recommended'])

    def test_misleading_edge_gain_without_intensity_agreement_is_not_a_drift(self):
        ev = _evidence({'R': [.03]*7}, {'R': [-.001]*7}, production_gain=.03)
        d = decide_experimental(ev, dict(status='CANDIDATE_SUPPORTED', best_relative_gain=.03))
        self.assertNotIn(d['status'], ('DRIFT_SUPPORTED', 'DRIFT_AMBIGUOUS'))
        self.assertEqual(d['status'], 'NUISANCE_SUSPECTED')
        self.assertEqual(decide_experimental(ev, dict(status='CANDIDATE_SUPPORTED', best_relative_gain=.03),
                                             switches=ABLATIONS['no_intensity_cue'])['status'], 'DRIFT_SUPPORTED')

    def test_apparent_production_gain_without_chance_corrected_gain_is_nuisance(self):
        ev = _evidence({'R': [0.]*7}, {'R': [0.]*7}, production_gain=.05)
        d = decide_experimental(ev, dict(status='CANDIDATE_SUPPORTED', best_relative_gain=.05))
        self.assertEqual(d['status'], 'NUISANCE_SUSPECTED')
        self.assertEqual(decide_experimental(ev, dict(status='CANDIDATE_SUPPORTED', best_relative_gain=.05),
                                             switches=ABLATIONS['no_nuisance_counterfactual'])['status'], 'KEEP_CONFIRMED')

    def test_indistinguishable_parameter_changes_are_reported_as_ambiguous(self):
        ev = _evidence({'R': [.04]*7, 'I': [.041]*7}, {'R': [.002]*7, 'I': [.002]*7})
        d = decide_experimental(ev, PROD_KEEP)
        self.assertEqual(d['status'], 'DRIFT_AMBIGUOUS')
        self.assertEqual(set(d['ambiguity_set']), {'R', 'I'})
        self.assertIsNone(d['hypothesis'])

    def test_nested_tie_prefers_the_simpler_explanation(self):
        ev = _evidence({'R': [.04]*7, 'RT': [.041]*7}, {'R': [.002]*7, 'RT': [.002]*7})
        d = decide_experimental(ev, PROD_KEEP)
        self.assertEqual((d['status'], d['hypothesis']), ('DRIFT_SUPPORTED', 'R'))

    def test_failed_attribution_support_withholds_the_group(self):
        ev = _evidence({'R': [.04]*7}, {'R': [.002]*7}, attribution=False)
        self.assertEqual(decide_experimental(ev, PROD_KEEP)['status'], 'DRIFT_AMBIGUOUS')

    def test_one_corrupted_capture_cannot_create_a_drift(self):
        """Temporary corruption: a single held-out capture with a huge gain, the others unchanged."""
        ev = _evidence({'R': [.6, 0, 0, 0, 0, 0, 0]}, {'R': [.02, 0, 0, 0, 0, 0, 0]})
        self.assertNotIn(decide_experimental(ev, PROD_KEEP)['status'], ('DRIFT_SUPPORTED', 'DRIFT_AMBIGUOUS'))
        self.assertEqual(decide_experimental(ev, PROD_KEEP, switches=ABLATIONS['no_robust_aggregation'])['status'], 'DRIFT_SUPPORTED')

    def test_insufficient_observations(self):
        ev = _evidence({'R': [.04]*3}, {'R': [.002]*3})
        self.assertEqual(decide_experimental(ev, PROD_KEEP)['status'], 'INSUFFICIENT_EVIDENCE')
        ev = _evidence({'R': [.04]*7}, {'R': [.002]*7})
        for t in ev['tests'][2:]:
            ev['informative'][t] = dict(edge=False, intensity=False)
        self.assertEqual(decide_experimental(ev, PROD_KEEP)['status'], 'INSUFFICIENT_EVIDENCE')

    def test_reference_confirmation_and_rejection(self):
        ev = _evidence({'R': [0.]*7}, {'R': [0.]*7})
        self.assertEqual(decide_experimental(ev, PROD_KEEP)['status'], 'KEEP_CONFIRMED')
        ev = _evidence({'R': [.005]*7}, {'R': [0.]*7}, ref_edge=0., ref_int=0.)
        d = decide_experimental(ev, PROD_KEEP)
        self.assertEqual(d['status'], 'REFERENCE_NOT_CONFIRMED')
        self.assertEqual(decide_experimental(ev, PROD_KEEP, switches=ABLATIONS['no_reference_confirmation'])['status'], 'KEEP_CONFIRMED')

    def test_single_cue_basis_is_reported_and_needs_its_margin(self):
        ev = _evidence({'R': [.008]*7}, {'R': [0.]*7})
        for t in ev['tests']:
            ev['informative'][t]['intensity'] = False
        self.assertNotEqual(decide_experimental(ev, PROD_KEEP)['status'], 'DRIFT_SUPPORTED')
        ev = _evidence({'R': [.03]*7}, {'R': [0.]*7})
        for t in ev['tests']:
            ev['informative'][t]['intensity'] = False
        d = decide_experimental(ev, PROD_KEEP)
        self.assertEqual((d['status'], d['evidence_basis']), ('DRIFT_SUPPORTED', 'edges only'))


class SequentialTests(unittest.TestCase):
    cfg = DiagnosticsConfig()

    def stream(self, rng, n=16, change=None, drop=.04, spike=None):
        x = .1 + .005*rng.normal(size=n)
        if change is not None:
            x[change:] -= drop
        if spike is not None:
            x[spike] -= .08
        return x

    def test_persistent_change_is_detected_after_it_starts(self):
        rng = np.random.default_rng(3)
        r = S.monitor(self.stream(rng, change=8), self.cfg)
        self.assertEqual(r['status'], 'PERSISTENT_CHANGE')
        self.assertGreaterEqual(r['cusum']['alarm'], 8)

    def test_temporary_corruption_is_not_persistent(self):
        rng = np.random.default_rng(4)
        r = S.monitor(self.stream(rng, spike=9), self.cfg)
        self.assertNotEqual(r['status'], 'PERSISTENT_CHANGE')

    def test_insufficient_stream(self):
        self.assertEqual(S.monitor([.1, .1, .1], self.cfg)['status'], 'INSUFFICIENT_EVIDENCE')

    def test_mixture_betting_function_is_a_density(self):
        # integral_a^1 f(p) dp = 1 - (1 - a)/(-ln a) exactly; it tends to 1 as a -> 0 (f is a valid bet).
        a = 1e-6
        s = np.linspace(np.log(a), 0, 40001); p = np.exp(s)
        integral = float(np.trapz([S._mixture_bet(x)*x for x in p], s))
        self.assertAlmostEqual(integral, 1 - (1 - a)/(-np.log(a)), places=3)
        self.assertAlmostEqual(S._mixture_bet(1.), .5)

    def test_conformal_martingale_false_alarms_respect_ville_bound(self):
        rng = np.random.default_rng(5)
        alarms = sum(S.conformal_martingale(rng.normal(size=40), .05, rng, start=4)['alarm'] is not None for _ in range(400))
        self.assertLessEqual(alarms/400, .05 + .03)


class ParityTests(unittest.TestCase):
    def test_fold_observer_does_not_change_the_production_result(self):
        import test_pipeline
        from test_pipeline import PipelineTests
        records = []
        original_assess = test_pipeline.assess
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            plain, _ = PipelineTests('run_fixture').run_fixture(False, a)
            with patch('test_pipeline.assess',
                       side_effect=lambda *x, **k: original_assess(*x, **k, fold_observer=records.append)):
                observed, _ = PipelineTests('run_fixture').run_fixture(False, b)
        self.assertEqual(plain.status, observed.status)
        self.assertEqual(plain.validation['folds'], observed.validation['folds'])
        self.assertEqual(plain.diagnostics['decision'], observed.diagnostics['decision'])
        self.assertTrue(any(r['stage'] == 'fold' for r in records))
        self.assertTrue(any(r['stage'] == 'final' for r in records))


class EvidenceIntegrationTests(unittest.TestCase):
    """Production engine + experimental diagnostics on synthetic captures (slow-ish, seconds)."""

    @classmethod
    def setUpClass(cls):
        cls.caps = [synthetic_capture(10 + i, name=f'cap_{i}') for i in range(6)]
        cls.bundle = SimpleNamespace(caps=cls.caps, size=SIZE, circle=CIRCLE, metadata=[], source='synthetic fixture')

    def run_case(self, calibration):
        from research_calibration.fault_diagnostics.runner import assess_with_diagnostics
        with tempfile.TemporaryDirectory() as folder:
            payload, result = assess_with_diagnostics(calibration, 'unused', output=folder,
                                                      config=ResearchConfig(bootstrap_reps=50), bundle=self.bundle)
            self.assertTrue(os.path.exists(os.path.join(folder, 'fault_diagnostics.json')))
        return payload, result

    def test_nominal_is_not_an_alarm_and_a_rotation_drift_is(self):
        nominal, _ = self.run_case(reference())
        self.assertNotIn(nominal['experimental']['proposed']['status'], ('DRIFT_SUPPORTED', 'DRIFT_AMBIGUOUS'))
        cal = reference(); model = ProjectionModel(cal, SIZE, CIRCLE); p = parameters(cal)
        drifted = P.perturbed_calibration(cal, model, p, np.r_[np.radians([1.2, 0, 0]), np.zeros(10)])
        drift, _ = self.run_case(drifted)
        self.assertIn(drift['experimental']['proposed']['status'], ('DRIFT_SUPPORTED', 'DRIFT_AMBIGUOUS'))


if __name__ == '__main__':
    unittest.main()
