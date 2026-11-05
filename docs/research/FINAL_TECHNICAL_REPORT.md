# Final technical report

**5 November 2026 · Offline research prototype · Scientific novelty not established**

## Outcome

A working fault-aware calibration backend is implemented in the isolated `Fault-aware calibration/repository` checkout, branch `research/fault-aware-calibration`, based on public commit `d0931889bf2f2a5ecb2cca9dd3c8a77c9fa8c763`. The original maintenance project and recordings remain separate. No push, merge, driver/OS change or hardware calibration write was performed.

The backend reuses existing capture readers, scene-edge extraction, camera geometry and targetless initialization. It adds scaled measurement-only support, conditional group contrasts, correspondence-variant checks, constrained estimation, capture selection, ambiguity handling, conditional uncertainty and independent maintenance validation. The new app copy has a small offline **Research check…** entry point; the same engine runs through Python or CLI.

## Scientific reasoning and limits

The mandatory [paper-to-algorithm comparison](PAPER_TO_ALGORITHM.md) preceded numerical implementation. It identifies central mathematics, assumptions, limitations and concrete adopted/improved/rejected/deferred ideas for all twelve required works. The [prior-art review](PRIOR_ART_REVIEW.md) records access levels, six inspected repository commits and licensing/release limits. No external reference implementation was transplanted. A4 remains abstract-only; complete B1 journal equations were unavailable.

Joint calibration, Schur complements, TSVD, informative selection, robust fault subspaces and abstention are established. The narrow candidate adaptation distinguishes an estimable constrained update from a uniquely attributable one and requires the actual change direction to retain support across training correspondence variants. Its scientific distinctness remains unverified. The current finite-variant procedure has no global identifiability, optimal-design or calibrated-risk guarantee.

## Executed verification

- **37 research tests and all 28 cloned baseline tests pass.** Tests cover independent derivatives, SO(3), projection, conditional information, aliases, rank, every-variant support, constraints, uncertainty, selection, outer rejection, file preservation, Windows paths and initialization semantics.
- Five methods ran on both the three-capture and ten-capture recordings: legacy refine under a common protocol, joint fitting, fault-aware, no observability and no selection.
- Additional single-gate, random, feature-count, D-proxy and E-proxy ablations completed on identical ten-capture partitions.
- The strict original maintenance workflow completed and reproduced **BORDERLINE**, 1.4085 px movement and 0.1856 px sensitivity spread on three captures.
- The complete inherited initializer ran under a low-priority watchdog in **188.75 s**, generating initial calibration JSON/TXT and images. Final initial-report scoping was then replayed from the saved estimate without repeating the unchanged search.
- The desktop-to-CLI bridge completed a real-recording assessment offscreen.

All numerical runs were sequential with one numerical/OpenCV thread. During initialization, the largest sampled child memory was **285.72 MiB**, with at least **25,929.54 MiB** available physical memory at sampled times. A 600 s / 1.5 GiB watchdog did not trigger. These controls are process safeguards, not a guarantee against an underlying kernel/driver fault.

## Recorded result and interpretation

The three-capture research comparisons retained the reference for insufficient evidence. In the ten-capture comparison, the fault-aware best mathematical candidate was rotation-only: its capped nearest-edge proxy changed from **15.49004 to 15.44161 px** pooled RMSE. Its **capture-mean squared-loss reduction was 0.6243%**, below the declared 1% threshold. It therefore kept the reference. One legacy joint-fit fold violated the research camera/domain bounds and remains explicitly failed.

The association ensemble gave essentially the same result as the single-gate method. Random/feature selection slightly improved the observed proxy more than contrast selection; no resulting update passed the full policy. This does not establish superiority of the proposed components. There are no independently verified fault labels or point correspondences, and repeated static captures can remain dependent.

The initializer's inherited `RELIABLE` label is heuristic. The research output remains `INITIAL_CALIBRATION_CANDIDATE`, with `UNVALIDATED_INITIALIZATION` uncertainty and no historical-fault claim. All captures entered initialization, preventing independent validation from those same captures.

## Deliverables

| Deliverable | Location and scope |
|---|---|
| Working source and integration | `research_calibration/`; Python/CLI and a minimal cloned-app bridge |
| Mathematical method | [MATHEMATICAL_METHOD.md](MATHEMATICAL_METHOD.md), including actual thresholds, equations, failure rules and cost |
| Prior-art comparison | [PAPER_TO_ALGORITHM.md](PAPER_TO_ALGORITHM.md), [PRIOR_ART_REVIEW.md](PRIOR_ART_REVIEW.md) |
| Actual verification evidence | [VERIFICATION_RESULTS.md](VERIFICATION_RESULTS.md), [computed JSON](evaluation/results_summary.json) and [figure](evaluation/recorded_comparison.png) |
| Ablation framework | `run_recorded_ablations.py`, `research_calibration/benchmark.py`, `research_configs/` |
| Limits and contribution assessment | [NOVELTY_ASSESSMENT.md](NOVELTY_ASSESSMENT.md) |
| Reproduction and API instructions | [RESEARCH_README.md](../../RESEARCH_README.md) |
| Decisions and debugging history | [IMPLEMENTATION_LOG.md](IMPLEMENTATION_LOG.md) |

## Publication assessment

This is a verified engineering/research foundation, **not an established A* contribution**. Stronger claims need independent physical fault measurements, nominal sessions, cross-rig/camera evaluation, separated threshold/calibration/test datasets and explicit false-attribution/abstention analysis. A potentially stronger technical direction is a camera–LiDAR-specific diagnosability result or independently calibrated acceptance-risk bound under stated association contamination. Those are future research objectives, not results supplied by this prototype.
