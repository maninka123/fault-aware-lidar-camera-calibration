# Preregistration: fault diagnostics v2 held-out evaluation

This document is committed on branch `research/fault-diagnostics-v2` **before** any held-out recording is
evaluated. The held-out results are reported as obtained. Changing a constant, rule or scoring definition
after they are seen invalidates the evaluation, and any such change must be reported as a new, separate
development round.

## Data roles

| Role | Recordings | Status when this document was written |
|---|---|---|
| Development | `creep_three`, `enclosure_off_ten`, `october_device_one` | Inspected while designing and tuning the method |
| Held-out | `enclosure_on_twelve` (12 captures, Sep 29 board reference), `october_device_four` (15 captures, pair_4 board reference) | Not evaluated by any v2 code; only file hashes and capture counts were read |

Roles are recorded in `research_data/manifest.json` (`evaluation_role`). The evaluation tool refuses to run a
held-out role on a development recording, and the reverse.

## Frozen constants

- **Diagnostics:** `DiagnosticsConfig` defaults in `research_calibration/fault_diagnostics/config.py` at the commit
  of this document.
- **Production engine:** `ResearchConfig` defaults, unchanged.
- **Ablation switches:** `ABLATIONS` in `policy.py`.
- **Conditions:** `DRIFTS`, `NUISANCES` and the drift-plus-nuisance condition in
  `tools/evaluate_fault_diagnostics.py`, and `CHANGES` and `TEMPORARY` in `tools/evaluate_sequential_monitor.py`.
- **Replicates:** 3 per recording (seeded), for both tools.

## Truth and scoring (per trial)

- **Anchor.** The recording's reference, refined by the production engine (RTI, four iterations, all
  captures). It is data-consistent, not physical truth.
- **No-change conditions** (nominal, nuisance): the correct verdict is no change.
  - *Alarm*: production decision CANDIDATE_SUPPORTED, or experimental DRIFT_SUPPORTED or DRIFT_AMBIGUOUS.
  - *Update*: production UPDATE_SUPPORTED, or experimental `update_recommended`.
- **Drift conditions:** the correct verdict is the injected group.
  - *Detection* means an alarm.
  - *Correct attribution* means the attributed groups equal the injected groups. Production attributes when
    it alarms; the experimental layer attributes on DRIFT_SUPPORTED.
  - *Ambiguous including truth* means DRIFT_AMBIGUOUS with an ambiguity set that contains the injected group.
  - *Wrong attribution* means an attributed group set that differs from the truth, or any attribution under
    no change.
- **Alignment.** The median pixel displacement from the anchor, before the update and after any production
  update.
- **Sequential monitor:**
  - alarm rate on nominal and single-capture corruption streams;
  - alarm and PERSISTENT_CHANGE rates on persistent streams;
  - median delay;
  - the same CUSUM applied to the production loss, as comparator.

## Predeclared expectations (falsifiable)

1. **E1.** Experimental false alarms on no-change trials are no higher than production's. A higher rate falsifies
   the claim that the method is more reliable.
2. **E2.** Experimental detection on drift trials is higher than production's.
3. **E3.** Experimental wrong attributions are no more frequent than production's.
4. **E4.** On held-out recordings, the experimental layer never recommends an update on no-change trials.
5. **E5.** The persistence monitor raises no alarm on single-capture corruption streams, and alarms on more
   persistent streams than the production-loss CUSUM.

Each ablation is reported against the full method. If an ablation is no worse on every metric, that
component's claimed benefit is withdrawn.

## What this evaluation cannot validate

- **Physical faults.** No physical faults are labelled. All labels are relative to a refined anchor.
- **Statistical independence.** Captures and trials within a recording are dependent, so the Wilson intervals
  understate uncertainty.
- **False-alarm rate or detection delay in operation.** Neither is calibrated for real deployments.
- **Other platforms.** Other rigs, lenses, scenes and sessions are not covered: there are two held-out
  recordings, and both are enclosure-on board-calibration sessions of this hardware family.
