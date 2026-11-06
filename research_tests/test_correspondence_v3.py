"""V3 correspondence model: identity, ambiguity, visibility, balance and the signed-residual diagnosis they feed.

Deterministic fixtures with known answers (numerical verification only; no claim about real sensors).
"""
import unittest
from types import SimpleNamespace
import numpy as np
from research_calibration.geometry import ProjectionModel, parameters, retract
from research_calibration.fault_diagnostics_v3 import correspondence as C
from research_calibration.fault_diagnostics_v3 import joint_estimation as JE
from research_calibration.fault_diagnostics_v3 import SignatureConfig
from test_mathematics import reference
from test_fault_diagnostics import synthetic_capture, SIZE, CIRCLE


def column(x, y0, y1, step=.5):
    y = np.arange(y0, y1, step)
    return np.c_[np.full(len(y), x), y]


def hand_capture(model, p, edge_columns):
    """One vertical 3D edge point projecting near the image centre; image edges are vertical columns at given x offsets."""
    X = np.array([[.2, .1, 3.]])
    u, v, ok = model.project(model.to_camera(X, np.zeros(1), p), p)
    assert ok[0]
    q = np.vstack([column(u[0] + dx, v[0] - 10, v[0] + 10) for dx in edge_columns])
    n = np.tile([1., 0.], (len(q), 1))
    gray = np.zeros(SIZE[::-1])
    cap = SimpleNamespace(name='hand', xyz=X, sgn=np.zeros(1), dir=np.array([[0., 1., 0.]]),
                          img=dict(q=q, n=n, gray=gray, strength=np.ones(len(q))))
    return cap, (u[0], v[0])


class ResponsibilityAndAmbiguity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = ProjectionModel(reference(), SIZE, CIRCLE)
        cls.p = parameters(reference())
        cls.off = dict(visibility=False, balance=False)

    def test_a_lone_close_edge_is_confident_and_two_equal_rivals_are_not(self):
        lone, _ = hand_capture(self.model, self.p, [1.])
        both, _ = hand_capture(self.model, self.p, [2.5, -2.5])
        cfg = C.CorrespondenceConfig(**self.off)
        a = C.associate(lone, self.model, self.p, cfg)
        b = C.associate(both, self.model, self.p, cfg)
        self.assertEqual(len(a['index']), 1)
        self.assertGreater(a['confidence'][0], .9)
        self.assertEqual(len(b['index']), 1)
        self.assertLess(b['confidence'][0], .6)             # a split responsibility, not a confident pair
        self.assertGreater(a['confidence'][0], 1.5 * b['confidence'][0])

    def test_a_rival_inside_the_ambiguity_radius_removes_the_pair_but_a_distant_one_does_not(self):
        rival, _ = hand_capture(self.model, self.p, [1., -7.])      # compatible edge 8 px away
        far, _ = hand_capture(self.model, self.p, [1., -20.])        # outside the 12 px radius
        cfg = C.CorrespondenceConfig(ambiguity_radius_px=12., **self.off)
        self.assertEqual(len(C.associate(rival, self.model, self.p, cfg)['index']), 0)
        self.assertEqual(len(C.associate(far, self.model, self.p, cfg)['index']), 1)
        # Without the radius the nearest-edge style pairing keeps the rival-contaminated point.
        self.assertEqual(len(C.associate(rival, self.model, self.p, C.CorrespondenceConfig(**self.off))['index']), 1)

    def test_an_edge_with_the_wrong_orientation_is_not_a_candidate(self):
        cap, (u, v) = hand_capture(self.model, self.p, [1.])
        cap.img['n'] = np.tile([0., 1.], (len(cap.img['q']), 1))      # horizontal edge: its normal is vertical
        self.assertEqual(len(C.associate(cap, self.model, self.p, C.CorrespondenceConfig(**self.off))['index']), 0)

    def test_nothing_in_the_gate_means_no_row(self):
        cap, _ = hand_capture(self.model, self.p, [30.])
        self.assertEqual(len(C.associate(cap, self.model, self.p, C.CorrespondenceConfig(**self.off))['index']), 0)


class VisibilityAndBalance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = ProjectionModel(reference(), SIZE, CIRCLE)
        cls.p = parameters(reference())
        cls.cap = synthetic_capture(3)

    def test_a_nearer_return_over_the_pixel_hides_the_point_and_a_farther_one_does_not(self):
        cfg = C.CorrespondenceConfig()
        u, v, ok, _t, depth = C.project_with_tangent(self.cap, self.model, self.p)
        grid = np.stack(np.meshgrid(np.linspace(-1.5, 1.5, 120), np.linspace(-1.5, 1.5, 120)), -1).reshape(-1, 2)
        near = np.c_[grid, np.full(len(grid), 1.0)]
        far = np.c_[grid * 4, np.full(len(grid), 9.0)]
        hidden = C.visible_mask(self.model, self.p, depth, u, v, ok, near, cfg, SIZE[::-1])
        shown = C.visible_mask(self.model, self.p, depth, u, v, ok, far, cfg, SIZE[::-1])
        self.assertLess(hidden[ok].mean(), .05)
        self.assertTrue(shown[ok].all())
        self.assertTrue(C.visible_mask(self.model, self.p, depth, u, v, ok, None, cfg, SIZE[::-1]).all())

    def test_balance_caps_a_dominant_cell_and_leaves_small_cells_alone(self):
        rng = np.random.default_rng(0)
        u = np.r_[rng.uniform(0, 100, 1000), rng.uniform(300, 480, 60)]
        v = np.r_[rng.uniform(0, 100, 1000), rng.uniform(250, 360, 60)]
        depth = np.full(len(u), 3.)
        weight = np.ones(len(u))
        out = C._balance(weight, u, v, depth, SIZE[::-1], C.CorrespondenceConfig(range_bins=1))
        self.assertLess(out[:1000].sum(), 1000 * .5)         # the dominant corner is capped
        self.assertTrue(np.allclose(out[1000:], 1.))          # a small cell keeps its weight
        self.assertTrue(np.all(out <= weight + 1e-12))


class IdentityAndDerivatives(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = ProjectionModel(reference(), SIZE, CIRCLE)
        cls.p = parameters(reference())
        cls.cap = synthetic_capture(5)
        cls.clutter = synthetic_capture(5, clutter=True)

    def test_pair_accuracy_counts_correct_wrong_and_unverifiable(self):
        truth = dict(index=np.array([0, 1, 2]), q=np.array([[0., 0.], [5., 5.], [9., 9.]]))
        got = dict(index=np.array([0, 1, 7]), q=np.array([[.5, 0.], [15., 5.], [3., 3.]]))
        a = C.pair_accuracy(got, truth)
        self.assertEqual((a['correct'], a['wrong'], a['unverifiable']), (1, 1, 1))
        self.assertAlmostEqual(a['recall'], 1 / 3)

    def test_signed_rows_jacobian_matches_a_finite_difference_of_the_residual(self):
        assoc = C.associate_oriented(self.cap, self.model, self.p)
        rows = C.signed_rows(self.cap, assoc, self.model, self.p)
        self.assertGreater(len(rows['residual']), 100)
        fixed = dict(index=rows['index'], q=assoc['q'][np.isin(assoc['index'], rows['index'])],
                     n=assoc['n'][np.isin(assoc['index'], rows['index'])], weight=np.ones(len(rows['index'])),
                     range=rows['range'])
        step = 1e-5
        for column_index, increment in ((0, np.r_[step, 0, 0]), (4, None), (8, None)):
            delta = np.zeros(13)
            if column_index == 0:
                delta[:3] = increment
            else:
                delta[column_index] = step
            moved = C.signed_rows(self.cap, fixed, self.model, retract(self.p, delta))
            base = C.signed_rows(self.cap, fixed, self.model, self.p)
            keep = np.isin(base['index'], moved['index'])
            numeric = (moved['residual'] - base['residual'][keep]) / step
            analytic = base['jacobian'][keep][:, column_index]
            self.assertTrue(np.allclose(numeric, analytic, rtol=2e-3, atol=2e-3), column_index)

    def test_a_clutter_edge_nearer_than_the_true_one_misleads_nearest_edge_but_not_the_unique_rule(self):
        """True counterpart 7 px away, an unrelated parallel edge 4 px away on the other side (texture with no geometry)."""
        cap, (u, v) = hand_capture(self.model, self.p, [-7., 4.])
        truth = dict(index=np.array([0]), q=np.array([[u - 7., v]]))
        nearest = C.associate_nearest(cap, self.model, self.p, 8.)
        unique = C.associate(cap, self.model, self.p, C.CorrespondenceConfig(ambiguity_radius_px=12., confidence=False, visibility=False, balance=False))
        self.assertEqual(C.pair_accuracy(nearest, truth)['wrong'], 1)       # nearest-edge pairs it with the clutter edge
        self.assertEqual(unique['index'].size, 0)                            # the unique rule abstains instead of guessing
        alone, (u2, v2) = hand_capture(self.model, self.p, [-7.])
        truth2 = dict(index=np.array([0]), q=np.array([[u2 - 7., v2]]))
        kept = C.associate(alone, self.model, self.p, C.CorrespondenceConfig(ambiguity_radius_px=12., confidence=False, visibility=False, balance=False))
        self.assertEqual(C.pair_accuracy(kept, truth2)['correct'], 1)        # with no rival the true edge is kept

    def test_samples_of_one_long_edge_do_not_dilute_confidence_or_count_as_rivals(self):
        cap, _ = hand_capture(self.model, self.p, [1.])                      # a 20 px long edge sampled every half pixel
        self.assertGreater(len(cap.img['q']), 30)
        out = C.associate(cap, self.model, self.p, C.CorrespondenceConfig(ambiguity_radius_px=12., confidence=False, visibility=False, balance=False))
        self.assertEqual(len(out['index']), 1)
        self.assertGreater(out['confidence'][0], .9)


class SignedDiagnosis(unittest.TestCase):
    """With correct pairs the signed inference attributes the injected group; the same engine is the V3 oracle API."""

    @classmethod
    def setUpClass(cls):
        cls.model = ProjectionModel(reference(), SIZE, CIRCLE)
        cls.p = parameters(reference())
        cls.caps = [synthetic_capture(20 + i, name=f'cap{i}') for i in range(6)]
        strict = C.CorrespondenceConfig(gate_px=2., orientation_deg=15., candidates=1, visibility=False,
                                        confidence=False, balance=False)
        cls.truth = {c.name: C.associate(c, cls.model, cls.p, strict) for c in cls.caps}
        cls.config = SignatureConfig(min_captures=4)

    def diagnose(self, delta):
        p = retract(self.p, delta)
        return JE.diagnose_pairs(self.caps, self.model, p, self.truth, signature=self.config)

    @staticmethod
    def gain(out):
        folds = out['fold_mse']
        best = np.min([np.array(v) for h, v in folds.items() if h != 'KEEP'], axis=0)
        return float(np.median(np.array(folds['KEEP']) - best))

    def test_a_translation_is_attributed_and_far_exceeds_the_nominal_residual(self):
        nominal = self.diagnose(np.zeros(13))
        out = self.diagnose(np.r_[0, 0, 0, .15, 0, 0, np.zeros(7)])
        self.assertIn(out['status'], ('DRIFT_SUPPORTED', 'DRIFT_AMBIGUOUS'))
        self.assertIn('T', out['supported'])
        # The fixture's own sub-pixel edge-extraction offset is a small consistent effect; the injected change is far larger.
        self.assertGreater(self.gain(out), 10 * max(self.gain(nominal), 1e-9))

    def test_a_rotation_change_is_detected_and_its_explanation_contains_rotation(self):
        out = self.diagnose(np.r_[np.radians(1.), 0, 0, np.zeros(10)])
        self.assertIn(out['status'], ('DRIFT_SUPPORTED', 'DRIFT_AMBIGUOUS'))
        self.assertTrue(any('R' in h for h in out['supported']))

    def test_too_few_rows_abstains(self):
        few = {name: dict(a, index=a['index'][:2], q=a['q'][:2], n=a['n'][:2], confidence=a['confidence'][:2],
                          weight=a['weight'][:2], range=a['range'][:2]) for name, a in self.truth.items()}
        out = JE.diagnose_pairs(self.caps, self.model, self.p, few, signature=self.config)
        self.assertEqual(out['status'], 'INSUFFICIENT_EVIDENCE')


class EstimatorStability(unittest.TestCase):
    def test_the_estimator_does_not_move_a_correct_calibration_far(self):
        model = ProjectionModel(reference(), SIZE, CIRCLE)
        p = parameters(reference())
        caps = [synthetic_capture(40 + i, name=f'e{i}') for i in range(4)]
        fit = JE.em_refine(caps, model, p, C.CorrespondenceConfig(visibility=False))
        moved = np.abs(fit['parameters'] - p)
        self.assertLess(np.degrees(np.linalg.norm(moved[:3])), .5)
        self.assertLess(np.linalg.norm(moved[3:6]), .1)
        self.assertTrue(model.valid(fit['parameters']))


if __name__ == '__main__':
    unittest.main()
