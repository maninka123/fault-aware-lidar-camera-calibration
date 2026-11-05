# Fault-Aware Camera–LiDAR Calibration

Targetless camera–LiDAR calibration that decides **what** may have drifted, checks whether the data can actually tell, and **keeps your current calibration** when the evidence is not enough.

> Research prototype. Numerically verified, but novelty and physical fault-classification accuracy are **not** established. See [limitations](#status-and-limits).

## What it does

- **Conditional observability**: finds which rotation, translation and intrinsic directions the measurements support (measurement-only information, priors excluded).
- **Constrained fault hypotheses**: compares rotation-only, translation-only, extrinsics, intrinsics and joint updates, and reports when explanations are indistinguishable.
- **Capture selection**: ranks already-recorded captures using training data only.
- **Guarded acceptance**: independent held-out check; a rejected update returns the exact input calibration.
- **Reports**: JSON + Markdown per assessment. Nothing is written to hardware.

Built on the existing [Calibration optimizer](docs/ORIGINAL_APP_README.md) (edge extraction, targetless initialization, desktop app), which still works unchanged (`legacy` mode).

## Quick start

Python 3.10/3.11, `pip install -r requirements.txt`.

```powershell
python -B verify_research.py                     # 28 baseline + 37 research tests
python -B -m research_calibration assess --calibration current.json --captures my_captures --output out/check
python -B -m research_calibration benchmark --dataset enclosure_off_ten --output out/compare
```

```python
from research_calibration import assess
result = assess(calibration="current.json", captures="my_captures", strategy="fault_aware", output="out/check")
print(result.status, result.recommended_action)
```

Strategies: `fault_aware`, `joint`, `no_observability`, `no_selection`, `single_variant`, `legacy_optimizer`, `legacy`. `calibrate_from_scratch` / `initialize` runs the targetless initializer. Details: [RESEARCH_README.md](RESEARCH_README.md), [data formats](docs/DATA_FORMAT.md).

## Status and limits

- Recorded 10-capture result: best candidate gained 0.62 % (< 1 % threshold), so the reference was kept.
- No evidence yet that capture selection or the correspondence ensemble beats random/feature-count baselines.
- No independently labelled faults, nominal-session false-alarm tests, or other rigs/cameras.

## Docs

[Final report](docs/research/FINAL_TECHNICAL_REPORT.md) · [Method](docs/research/MATHEMATICAL_METHOD.md) · [Prior art](docs/research/PRIOR_ART_REVIEW.md) · [Novelty](docs/research/NOVELTY_ASSESSMENT.md) · [Verification](docs/research/VERIFICATION_RESULTS.md)

Recordings are not distributed; `research_data/manifest.json` references local paths and hashes.
