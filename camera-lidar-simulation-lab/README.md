# Camera–LiDAR Simulation Lab

Synthetic RGB and LiDAR datasets with **known calibration ground truth**, for testing calibration and fault-aware algorithms.

[Parent project](../README.md) | [Sensor models](docs/SENSOR_MODELS.md) | [Rendering](docs/RENDERING.md) | [Exports & ROS](docs/INTEGRATION.md)

![Warehouse, laboratory, street and corridor environments](docs/images/environments.png)

## Features

| Component | Options |
| --- | --- |
| Environments | Warehouse, laboratory/office, outdoor street, corridor |
| LiDAR | Livox Avia, Mid-360, VLP-16, OS1-64, AT128 |
| Camera | Pinhole or fisheye; configurable resolution, focal length, principal point and distortion |
| Calibration changes | Mount and/or camera intrinsics; fixed within a batch, changed between batches |
| Capture tools | Browser Studio, random viewpoints, batch planning, mass capture and resume |
| Rendering | Blender Cycles RGB; independent CPU ray casting from the same scene geometry |

## Install & launch

**Requirements:** Python 3.10/3.11 and Blender installed separately. Example renders used Blender 5.0.1.

From the parent repository root:

```powershell
cd camera-lidar-simulation-lab
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -e ".[dev]"
./.venv/Scripts/python.exe tools/webui.py
```

- Open **http://127.0.0.1:8765**. Later, launch with **`start_simulator.bat`**.
- Use this simulator's own environment, separate from the calibration app.
- Scenes and full datasets are **not bundled**; build scenes locally first.

## Capture workflow

| Step | Action |
| --- | --- |
| **1. Setup** | Select environment, LiDAR and camera. Check the Blender executable path. |
| **2. Build** | Click **Build missing scene** for each environment you need. |
| **3. Studio** | Place viewpoints, use random poses, or create batches. |
| **4. Drift** | Optionally enable mount changes and/or **Vary camera intrinsics between batches**. |
| **5. Generate** | Choose a save folder, generate captures, then verify the run. |

**Batch intrinsics:** batch 1 is nominal; later batches use seeded offsets from nominal. Defaults: focal length **+/-0.3%**, principal point **+/-0.5 px**, distortion k1 **off**. K/D stay fixed within each batch and are saved as ground truth. Recreate batches after changing limits.

**Mass capture:** choose environment x LiDAR x camera/resolution x intrinsics drift. Each combination gets its own run folder. Completed runs can be skipped; unfinished runs can be continued or redone. Existing data is preserved. One simulator job runs at a time.

## Example output

| Camera image | LiDAR projection onto the same image |
| --- | --- |
| ![Synthetic warehouse RGB](docs/images/warehouse-camera.png) | ![Livox Avia evaluation overlay](docs/images/warehouse-lidar-overlay.png) |

*The curved overlay is the simulated Livox scan pattern. [Image provenance](docs/images/README.md).*

## Command line

From this folder, build a scene and generate a new run:

```powershell
./.venv/Scripts/python.exe -m simulator build-scene warehouse --device OPTIX --allow-render --allow-gpu
./.venv/Scripts/python.exe -m simulator generate configs/experiments/warehouse_avia.yaml --output outputs/my_run --device OPTIX --allow-render --allow-gpu
./.venv/Scripts/python.exe -m simulator verify outputs/my_run
```

| Task | Command / setting |
| --- | --- |
| CPU rendering | Replace GPU flags with `--device CPU --allow-render` |
| Continue a run | Add `--resume` to its original `generate` command |
| Export paired captures | `python -m simulator export outputs/my_run outputs/my_pairs --format paired` |
| Run tests | `python -B -m pytest -q` |
| Urban HDRI | Download with `python tools/fetch_assets.py`; build urban with `--hdri assets/industrial_sunset_02_4k.exr` |

Use the simulator virtual environment for the short `python` commands above. New run/export destinations must not already contain data. Geometry mode skips Blender RGB rendering but still needs a built mesh.

## Saved data

| Folder | Contents | Who uses it? |
| --- | --- | --- |
| `inference/` | RGB images, LiDAR NPZ/PCD, sequence and starting calibration | Calibration algorithm |
| `evaluation/` | Exact poses, K/D, fault settings, ideal geometry, overlays and verification | Evaluation only |

Batch runs also save `batches.json`, `nominal_calibration.json` and `intrinsics_by_batch.csv` under `evaluation/`. Exporters read **only `inference/`**.

## Validation & limits

- **192 tests passed, 19 skipped** in the fresh-checkout CPU check on 10 November 2026, using the existing scientific Python environment. Scene-dependent tests need locally built meshes.
- Research simulator: physical sensor fidelity, photorealism and end-to-end calibration accuracy are **not established**. Within-scan motion, multipath and weather are not modelled.
- Conservative thread limits and explicit render/GPU flags remain after earlier host crashes; GPU stability has not been established.
- [Verification report](docs/VERIFICATION_REPORT.md) | [Implementation status](docs/IMPLEMENTATION_PROGRESS.md) | [Sensor assumptions & licences](docs/SENSOR_MODELS.md)
