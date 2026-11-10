# Fault-Aware Camera–LiDAR Calibration

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Python 3.10 | 3.11](https://img.shields.io/badge/python-3.10%20%7C%203.11-blue)
![Windows 10/11](https://img.shields.io/badge/platform-Windows%2010%2F11-lightgrey)

Targetless camera–LiDAR calibration that decides **what** may have drifted, checks whether the data can actually tell, and **keeps your current calibration** when the evidence is not enough. A desktop app walks you through it and shows its working.

> **Research prototype.** Numerically verified, but novelty and physical fault-classification accuracy are **not** established. See [status and limits](#status-and-limits).

<p align="center"><img src="docs/images/app/gallery.png" alt="The desktop app: processing, result figures, calibration review and report" width="100%"></p>

## What it does

- **Finds what the data can see.** Which rotation, translation and camera directions the captures actually constrain, and which explanations look alike.
- **Compares explanations fairly.** Every possible cause (rotation, translation, camera, and combinations) is refitted with one capture held out and scored on it.
- **Keeps your calibration unless the evidence is strong.** An update needs a real, consistent improvement; otherwise the exact input calibration is returned.
- **Shows its working.** Live processing, interactive result figures, a written report, and the original maintenance analysis side by side.
- **Never changes your files silently.** Accepting, writing to a device and restoring are explicit, confirmed actions.

## Quick start

```powershell
pip install -r requirements.txt        # Python 3.10 or 3.11
```

Start the app with **`launchers/start_research_gui.bat`** (or `python gui/research_gui.py`), choose a calibration and a folder of recorded captures, and press **Check calibration**.

From the command line:

```powershell
python -B -m research_calibration assess --calibration current.json --captures my_captures --output out/check
```

## Results at a glance

| Follow it live | See the change on the image | Read the report |
| --- | --- | --- |
| <img src="docs/images/app/processing-testing.png" alt="Processing: the held-out result of every explanation" width="260"> | <img src="docs/images/app/result-overlay.png" alt="LiDAR points drawn on the camera image" width="260"> | <img src="docs/images/app/report.png" alt="The written report" width="260"> |
| Every explanation's held-out result appears as it is computed. | Real LiDAR points on the real photo; slide from the current to the proposed calibration. | Verdict, comparison, what the data could see, changes and limits. |

## Camera–LiDAR simulation lab

The **[Camera–LiDAR Simulation Lab](camera-lidar-simulation-lab/README.md)** generates synthetic RGB and LiDAR captures with exact calibration ground truth for controlled calibration and fault experiments. Its browser app supports four procedural environments, five LiDAR profiles, pinhole/fisheye cameras, and batch changes to sensor mounting and camera intrinsics.

![Camera–LiDAR simulator environments: warehouse, laboratory, street and corridor](camera-lidar-simulation-lab/docs/images/environments.png)

The simulator has its own environment, dependencies, tests and setup steps. **[Open the simulator README →](camera-lidar-simulation-lab/README.md)** for installation, examples, batch settings and the separation between algorithm inputs and evaluation truth. Generated scenes and full datasets are built locally.

## Documentation

| | |
| --- | --- |
| **[Desktop app guide](docs/DESKTOP_APP.md)** | Every tab with screenshots: New check, Processing, Result, Calibration review, Report, Use the result, Devices |
| [Camera–LiDAR Simulation Lab](camera-lidar-simulation-lab/README.md) | Synthetic datasets, browser Studio, batch calibration changes, mass capture and ground-truth exports |
| [Features](docs/FEATURES.md) | Everything the maintenance app does, and where it lives here |
| [Troubleshooting](docs/TROUBLESHOOTING.md) | Path limits, logs, stopped checks, devices, resetting |
| [Repository layout](docs/REPOSITORY_LAYOUT.md) | Folders, modules, and what a saved check contains |
| [Engine and command line](docs/RESEARCH_README.md) | The assessment engine, strategies, Python API |
| [Data formats](docs/DATA_FORMAT.md) | Calibration files and capture layouts |
| [Method and report](docs/research/FINAL_TECHNICAL_REPORT.md) | Mathematical method, verification, prior art |
| [Experimental diagnostics V2/V3](docs/research/v3/README.md) | Optional research layer, not used by the app: method, root-cause analysis, results, [generalization audit](docs/research/v3/GENERALIZATION_AUDIT.md) |

## Status and limits

- Recorded 10-capture result: the best candidate gained 0.62 % (< 1 % threshold), so the reference was kept.
- No evidence yet that capture selection or the correspondence ensemble beats random or feature-count baselines.
- No independently labelled faults, nominal-session false-alarm tests, or other rigs and cameras.
- Scores are a nearest-edge proxy, not true reprojection error; no ground truth exists for these recordings.
- The maintenance comparison and the fault-aware assessment answer different questions and can disagree; the app shows both and says so.
- The experimental V2/V3 diagnostics (`python -m research_calibration diagnose` / `diagnose-v3`) are optional and never change a verdict, a file or a device. Exact fault attribution on recorded data and generalization to new scenes and sensors are **not established** (see the [generalization audit](docs/research/v3/GENERALIZATION_AUDIT.md)).
- Writing to a device has been tested against an in-memory stand-in, not real hardware. Try it first on a spare device.

Recordings are not distributed; `research_data/manifest.json` references local paths and hashes.

## License

[MIT](LICENSE). Third-party libraries keep their own licences; notably **PyQt5 is GPL v3 / commercial**. This repository only imports it and does not bundle it, but if you redistribute a packaged build, check each dependency's licence first.
