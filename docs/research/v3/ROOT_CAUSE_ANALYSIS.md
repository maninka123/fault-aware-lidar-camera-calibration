# Root cause of the unresolved fault attribution (numerical analysis)

Run 6 November 2026 on the two **development** recordings (`october_device_one`, `enclosure_off_ten`), two replicates, seven injected changes
(R 0.5 / 1 degree, T 3 / 6 cm, principal point 3 px, focal 2 %, RT), a nominal condition and two nuisances. Tools:
`tools/analyze_attribution_root_cause_v3.py` (evidence in `research_artifacts/v3_root_cause_20261106`, `v3_pairing_development_20261106`).
Truth is relative to each recording's anchor, not physical. "Reference pairs" are the pairs the anchor itself finds under a strict gate (2 px,
15 degrees): a proxy for true correspondences, used here as an experimental control that no real method has.

## Finding in one sentence

The V3 geometric inference is sound on this recorded geometry; **the automatic edge pairing at a mis-calibrated pose is the bottleneck**: it
pairs a large share of points with the wrong edge, the wrong pairs describe a smooth but wrong displacement field, and everything downstream
(optimizer, signatures, attribution) explains that wrong field faithfully.

## The control that isolates it

The same V3 `infer_signatures` inference, same rows per capture, same noise model; only the pairing differs. 28 injected-change trials,
12 no-change trials (4 nominal, 8 nuisance; reference pairs are not defined for nuisance images, so 4 no-change trials).

| Pairing | No-change alarms | Detections | Exact attribution | Wrong unique | Ambiguity set contains the truth |
|---|---:|---:|---:|---:|---:|
| **Reference pairs (control)** | **0/4** | 28/28 | **15/28** | 1 | 12/28 |
| Nearest edge (8 px) | 8/12 | 26/28 | 4/28 | 15 | 7/28 |
| Existing oriented nearest edge (V2 front end) | 7/12 | 27/28 | 5/28 | 19 | 4/28 |
| New: responsibility + visibility + balancing | **0/12** | 20/28 | 0/28 | 4 | 11/28 |

With correct pairs, 27 of 28 injected changes end as either the exact group or an ambiguity set that contains it, with no nominal false alarm.
By condition (4 trials each):

| Injected | Exact | Ambiguity contains truth | Other |
|---|---:|---:|---:|
| R 1 degree | 4 | 0 | 0 |
| R 0.5 degree | 0 | 4 | 0 |
| T 6 cm | 3 | 1 | 0 |
| T 3 cm | 2 | 2 | 0 |
| Focal 2 % | 4 | 0 | 0 |
| Principal point 3 px | 0 | 4 | 0 |
| RT (0.5 degree, 3 cm) | 2 | 1 | 1 |
| Nominal | 0 | 0 (4 correct KEEP) | 0 |

The unavoidable ambiguity appears where mathematics says it must: a small rotation and a principal-point shift are the same displacement field to
within the data (principal angle between their signatures 1.4 to 1.9 degrees on these recordings, versus 13 to 23 degrees for translation
against rotation or intrinsics). Larger effects rise above the alias and are identified.

## Answers to the eight questions

1. **Does nearest-edge matching create incorrect correspondences?** Yes, massively. Against the reference pairs, only 57 % (nearest), 62 % (oriented)
   and 60 % (new method) of verifiable pairings are correct. Identity falls with the size of the error being diagnosed: with the current calibration
   equal to the anchor it is 100 %; rotation 0.5 degree 72 % (oriented; nearest 69 %), rotation 1 degree 43 % (38 %), translation 3 cm 76 %,
   6 cm 51 %, principal point 3 px **30 %** (27 %), focal 2 % 83 %.
2. **Is the correct fault excluded during hypothesis fitting?** No. The production optimizer is allowed to fit exactly the injected group and still
   recovers little. With the correct group fitted, the median residual error against the anchor is 0.20 to 0.33 degree for a 0.5 degree rotation,
   0.59 to 1.00 degree for 1 degree, 4.3 to 4.4 cm for a 6 cm translation, 2.0 to 2.3 px for a 3 px principal-point shift. That is roughly 0 to 60 % of the injected change recovered, with the best case a 0.5 degree rotation.
3. **Does the optimizer converge to a wrong but lower-loss combination?** Yes. The nearest-edge loss at the *best-fitting* hypothesis is lower than at the
   anchor in 10 of 14 conditions, and the perturbed calibration already scores a lower loss than the anchor in 7 of 14. The objective does not prefer the
   truth; the optimizer is doing its job on a biased objective (edge density, wrong pairs). This is an objective problem, not non-convergence.
4. **Is rotation confused with intrinsics?** Partly, and unavoidably: principal angle 1.9 degrees (october_device_one), 1.4 degrees (enclosure_off_ten).
   With correct pairs this appears as correct ambiguity (R 0.5 degree and principal point 3 px: 4/4 ambiguity sets contain the truth), not as a wrong label.
5. **Is translation unobservable for lack of depth variation?** Not here. Retained rows span about 1.5 to 4.7 m (5th to 95th percentile; median 3.1 m) on
   october_device_one and 2.1 to 5.5 m (median 4.7 m) on enclosure_off_ten; translation separates from rotation and intrinsics by 13 to 23 degrees and is identified
   exactly in 5 of 8 trials (and contained in the ambiguity set in 3 more) with correct pairs. This is a shallow-depth scene; a deeper scene was not available.
6. **Do repeated captures give independent information?** Not tested here and not independent: captures of one recording view one static scene. Leave-one-capture-out
   replication therefore cannot separate a scene-level pairing bias from drift. This is why a pairing independent of the calibration under test matters.
7. **Is the signature model applied to physically incorrect associations?** Yes, that is the mechanism. The inference is identical across rows of the table above; with
   incorrect pairs it attributes the wrong group confidently (15 to 19 wrong unique labels of 40) and raises 7 to 8 of 12 no-change alarms.
8. **Parameter bounds and model mismatch.** Not the cause that was isolated, and not tested: no physically justified bound on a *fault* exists in the data
   (the board references carry formal and bootstrap standard deviations of the reference's own estimate, which does not bound drift). Unbounded local
   alternatives are retained and their limitation is stated in MATHEMATICAL_METHOD.md.

## What the new pairing does and does not fix

`correspondence.associate` replaces the nearest-edge pairing by a posterior responsibility over *distinct edge lines* (samples of one edge do not
compete), a z-buffer visibility test, and cell/range balancing. On the development pair it removes almost all false alarms (0/12 against 7 to 8/12)
and cuts wrong unique labels from 15 to 19 down to 4. Ablations on the same 40 trials:

| Variant | No-change alarms | Detections | Exact | Wrong unique | Truth in ambiguity |
|---|---:|---:|---:|---:|---:|
| Full | 0/12 | 20/28 | 0/28 | 4 | 11 |
| No confidence weighting | 7/12 | 26/28 | 4/28 | 14 | 8 |
| No balancing | 1/12 | 26/28 | 1/28 | 7 | 14 |
| No visibility test | 0/12 | 19/28 | 0/28 | 5 | 14 |

The responsibility weighting accounts for the safety gain; balancing and visibility add little on this data. It is a **safety** improvement, not an
identification improvement: exact attribution stays at 0/28, because the pairing is still only 60 % correct and the weighted evidence is too weak to
separate the groups. Abstaining more is not identification, and it is not reported as such.

## Approaches tried and rejected (development recordings, kept for reproducibility)

* **Annealed alternating pairing and calibration estimation** (`joint_estimation.em_refine`). Pairing identity rose to 63 to 67 % and a truncated-SVD
  step stabilised the estimate (a ridge step moved a correct calibration by 1.2 degrees, 5.5 cm, 5.6 px; the truncated step by 0.33 degree, 7 cm, 1 px), but
  pairs chosen at the fitted estimate carry the estimate's own displacement: signed residuals at the current calibration then look like drift even
  when nothing changed. On a single development replicate (10 trials) all 3 no-change trials alarmed and 9 wrong unique labels were produced, with no
  exact attribution. This is the "convenient matches" circularity, not an optimizer failure.
* **Unique-within-radius pairing** (`ambiguity_radius_px`): a pair is kept only if no other compatible edge line lies within the radius. Identity rises
  from 64 % (4 px) to 71 % (12 to 16 px) while the matched rows fall from about 78 000 to 2 400 (the new default pairing keeps 96 000). No radius improved the
  diagnosis: no-change alarms 2 to 12 of 12, exact attribution 0 to 4 of 28, wrong unique labels 6 to 36. Retained as an option.
* **Pairing correctness is a function of the unknown error.** Because identity falls from 100 % to 30 to 50 % as the error grows, no pairing that depends on
  the current calibration estimate can be both unbiased and informative; independent correspondence information (fiducials, a nominal-period map, or
  multi-view structure) is needed. This is the main conclusion for the next experiments.

## Implementation defects found and fixed during this work

Unit tests exposed two defects in the first version of the new pairing: samples of one long edge competed for responsibility (diluting every confidence), and
points of the chosen edge counted as rivals for the unique rule. Both were fixed before any number above was recorded for the final code; the earlier
numbers produced with the defective version are not used.
