# Fault-Aware Camera-LiDAR Calibration

Windows desktop app for checking an existing calibration, comparing update options, collecting device captures, and reviewing camera intrinsics and LiDAR-to-camera extrinsics.

## Install from GitHub

1. Download/extract or clone the **whole repository** into a short, writable folder, such as `C:/FaultAware`. Keep all subfolders together.
2. Install **64-bit Python 3.10 or 3.11**. Run **Setup.bat** once; it finds Python or asks you to select `python.exe`, creates a dedicated runtime in your Windows user-data folder, installs requirements, and checks the installation. Internet is needed during setup.
3. Open **Start.bat**. Future launches use this checkout's environment; Anaconda, ROS, and developer-specific paths are not required.

After pulling code updates, rerun Setup.bat if requirements changed. Run Setup.bat on each PC; do not copy the generated `.runtime.json` between PCs. Source and dependencies are included or declared in requirements.txt. A short local runtime path avoids OneDrive path-length limits.

## Capture and check

- Open **Devices**. If the Central Monitoring Platform configuration folder cannot be found, select the folder containing `config.json`. The app remembers it on this PC. **Platform folder...** changes it later; devices can also be added manually.
- Connect and read the device calibration file. Choose camera and LiDAR topics from the dropdowns or type them; defaults are `/camera/image_raw` and `/livox/lidar`.
- Choose a save folder on the first capture. Each session stays together:

```text
Chosen folder/
  Device_5_<date and time>/
    pairs/     camera-LiDAR captures and previews
    results/   assessment, report, comparison and update history
```

The session also keeps its source-calibration metadata. The save location is remembered per PC. Use **Save location...** to change it. **Add captures** appends to the session; **Update results** refreshes the same check. **View existing results** returns to its result. Previous results are retained inside the check.

For imported recordings, use **New check** and select the calibration and captures. Supported inputs: raw `capture_*/rig_0.bag`, stacked `.npz`, or matched image/PCD pairs. Confirm PCD units when asked. One captured pair is insufficient for the fault-aware check; start with five varied scenes. Multiple LiDAR frames within one capture remain one sample.

## Device updates and restore

In **Calibration review**, choose camera-only, extrinsics-only, or both, then **Write to the device...**. Review values and the exact file changes before confirming. A backup is saved; **Restore previous device calibration...** restores it after review and confirmation. Pipeline restart is confirmed separately. Nothing is written to a device automatically. Unsupported fault-aware verdicts require an additional confirmation. The Results tab has no device-write controls.

Beside device values, **Edit manually...** imports or edits TXT values and previews existing/new differences. **Use in Calibration review** sends them to the review tab; the popup never writes. The selected camera/alignment/both option controls which parameters are replaced. Restore offers the previous update or the original backup.

Camera models are labelled explicitly. Native pinhole values are kept for Keep current and alignment-only. Fisheye-to-pinhole conversion shows its error and angular coverage and must be acknowledged before writing. The current colorizer integration writes pinhole parameters; a device declaring a different projection model is blocked rather than given incompatible coefficients.

## Settings and troubleshooting

Folder choices, device settings and logs are stored per user in `%LOCALAPPDATA%/FaultAwareCalibration`; recordings stay in the chosen save folder. Device SSH credentials are requested on each PC. No local recordings, credentials, or device settings belong in Git.

If startup fails, check `app.log` in that settings folder. Missing modules: rerun Setup.bat and launch Start.bat. Long-path errors: use a shorter install/save folder. A missing or moved platform/save folder opens a folder picker again. Existing capture sessions can be reopened using their calibration metadata and `pairs` folder; do not recapture merely because processing failed.

## Repository layout

`app/` holds the desktop interface and its supporting algorithms. `research/` groups the engine, configs, dataset manifests, tests and historical outputs. `labs/` holds the simulator; `data/` holds legacy local captures. `docs/`, `examples/`, `tools/`, `packaging/` and `launchers/` keep their respective files together. Start.bat, Setup.bat and the command-line engine entry point stay at the root. New captures and results go to the save folder you choose.

## Details

[Desktop guide](docs/DESKTOP_APP.md) - [Data formats](docs/DATA_FORMAT.md) - [Engine/CLI](docs/RESEARCH_README.md) - [Troubleshooting](docs/TROUBLESHOOTING.md) - [Method and limits](docs/research/FINAL_TECHNICAL_REPORT.md) - [Simulation lab](labs/camera-lidar-simulation-lab/README.md)

Research prototype: fault attribution and physical calibration accuracy are not established. Insufficient evidence keeps the current calibration. Experimental V2/V3 diagnostics are separate from the app?s verdict.

Optional EXE build: install PyInstaller and run `python packaging/build_portable.py --output <new-folder>`. This is not required to install from GitHub; the current Windows EXE build has not passed verification.

[MIT license](LICENSE). Third-party libraries retain their own licenses.
