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

## Repository layout

| Folder / file | What it holds |
|---|---|
| `start_research_gui.bat` | Start the desktop app (fault-aware assessment) |
| `start_app.bat` | Start the original calibration maintenance app |
| `gui/` | The desktop app: window, Processing tab, result figures, Calibration review, icon |
| `research_calibration/` | The assessment engine (observability, hypotheses, decision policy) |
| `Calibration maintenance/` | The maintenance analysis and app that the review tab reuses |
| `Targetless calibration/` | Edge extraction and the targetless initializer (read by both apps) |
| `research_tests/` | Tests for the engine and the app |
| `tools/` | Verification, ablation and report-building scripts |
| `docs/` | Method, results, data formats and the research report |
| `research_configs/`, `research_data/`, `examples/`, `multi_capture_calibration/` | Settings, dataset manifests, sample calibrations, the multi-capture helpers |
| `research_artifacts/` | Your checks (created on first use; not committed) |

## Quick start

Python 3.10/3.11, `pip install -r requirements.txt.

Desktop app: double-click **start_research_gui.bat** (or `python gui/research_gui.py`). Same inputs as the maintenance app: calibration as `.json`, exported/targetless `.txt`, or typed values; captures as raw `capture_*/rig_0.bag`, stacked `.npz`, or image + PCD pairs (with PCD units). Check an existing calibration or calibrate from scratch (raw/stacked); past checks are listed in the sidebar.

```powershell
python -B tools/verify_research.py                     # 28 baseline + 37 research tests
python -B -m research_calibration assess --calibration current.json --captures my_captures --output out/check
python -B -m research_calibration benchmark --dataset enclosure_off_ten --output out/compare
```

```python
from research_calibration import assess
result = assess(calibration="current.json", captures="my_captures", strategy="fault_aware", output="out/check")
print(result.status, result.recommended_action)
```

Strategies: `fault_aware`, `joint`, `no_observability`, `no_selection`, `single_variant`, `legacy_optimizer`, `legacy`. `calibrate_from_scratch` / `initialize` runs the targetless initializer. Details: [RESEARCH_README.md](docs/RESEARCH_README.md), [data formats](docs/DATA_FORMAT.md).

## Desktop app

Windows 10/11, Python 3.10/3.11. Start it with **start_research_gui.bat** (or the shortcut). Other systems are untested.

- **New check** takes an existing calibration and a folder of recorded captures. **Devices** connects to a sensor, reads its calibration and captures a sample to check (read-only: nothing is ever written to a device).
- The app **remembers** your last calibration, captures folder, options, where you last browsed, and the window size and position (in `%LOCALAPPDATA%\FaultAwareCalibration\settings.json`). It never starts a check by itself; *Forget* on the New check page clears it. Loading a calibration shows its camera and LiDAR matrices side by side straight away.
- **Processing** follows the check stage by stage: captures appearing as they are stacked, edges per capture, and every explanation's held-out result drawn as each fold completes. **Stop check** ends it safely. Finished checks can be replayed from their saved results.
- **Use the result** (bottom of Result) accepts a calibration into `accepted/`, writes it to the connected device or restores the previous one, and re-runs a check with the same inputs. Everything the maintenance app does is here: see [docs/FEATURES.md](docs/FEATURES.md).
- When *Also run the maintenance comparison* is ticked, the comparison runs as the last Processing stage, so every tab is complete when the check finishes.
- **Report** is the written account of a check as a designed page (verdict, how the explanations compared, what the data could see, changes, inputs, limits). It can be saved as a PDF or copied as a summary.
- **Result** is the fault-aware assessment. **Calibration review** shows the original maintenance analysis of the same calibration and captures (four update choices, RMSE, parameter changes, leave-one-out evidence, matrices, images). It is a separate calculation: it runs after a new check when the option on the setup page is ticked, or on demand for any older check, and never changes the fault-aware verdict.
- Every check is saved under `research_artifacts/<check>/` (the maintenance comparison in its `review/` folder). Your calibration files are never modified.

## Troubleshooting

- **"Windows stops at 260 characters"**: the repository sits too deep. Move it to a short folder such as `C:\FaultAware`, or turn on long paths in Windows.
- **A problem report** needs the version (bottom of the sidebar) and the log `%LOCALAPPDATA%\FaultAwareCalibration\app.log`. The log contains file paths from your machine.
- **Closing the app during a check** asks first and stops the check. A stopped or failed check keeps its partial folder and is marked as such in the list.
- **Temporary files**: the maintenance comparison runs in `%LOCALAPPDATA%\FaultAwareReview` and removes it when it finishes.

## Status and limits

- Recorded 10-capture result: best candidate gained 0.62 % (< 1 % threshold), so the reference was kept.
- No evidence yet that capture selection or the correspondence ensemble beats random/feature-count baselines.
- No independently labelled faults, nominal-session false-alarm tests, or other rigs/cameras.
- The scores are a nearest-edge proxy, not true reprojection error; no ground truth exists for these recordings.
- The maintenance comparison and the fault-aware assessment answer different questions and can disagree; the app shows both and says so.

## Docs

[Final report](docs/research/FINAL_TECHNICAL_REPORT.md) · [Method](docs/research/MATHEMATICAL_METHOD.md) · [Prior art](docs/research/PRIOR_ART_REVIEW.md) · [Novelty](docs/research/NOVELTY_ASSESSMENT.md) · [Verification](docs/research/VERIFICATION_RESULTS.md)

Recordings are not distributed; `research_data/manifest.json` references local paths and hashes.

