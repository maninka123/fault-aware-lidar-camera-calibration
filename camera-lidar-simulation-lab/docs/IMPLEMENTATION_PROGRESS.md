# Implementation progress — 5 November 2026

Independent project: `camera-lidar-simulation-lab`. The existing calibration optimizer and fault-aware workspace are read-only references. No GitHub push or dataset publication has occurred.

## Current execution constraint

The user reported Windows blue screens and asked to prioritize host stability. Native rendering, GPU work, WSL jobs, solver optimization and stress/performance tests are suspended for this session. Development continues through source edits and small single-thread CPU checks. No Windows settings, drivers, global Python packages, WSL configuration or installed ROS files are changed.

Read-only Windows System event inspection found bugcheck records at **2026-11-05 19:55:09 +11:00** (`0x7e`) and **19:57:29 +11:00** (`0x3b`). Event messages point to `C:\Windows\Minidump\110526-13375-01.dmp` and `110526-14437-01.dmp`. These records do not establish cause; dump analysis has not been performed. No Blender/simulator Python process was active when checked after the user's message. Existing VS Code WSL processes were left alone.

## Implemented

- Separate Python project and local virtual environment; no calibration source changes.
- Proper SE(3) transforms and documented Blender/OpenCV/LiDAR frames in metres.
- OpenCV pinhole and four-coefficient fisheye projection/inversion.
- Independent CPU mesh ray casting for each LiDAR and the camera, using evaluated Blender render geometry.
- Five time-dependent LiDAR schedules; real MIT Livox pattern data bundled with provenance. OS1/AT128 nominal approximations are explicit.
- Ideal and noisy ranges, angular jitter, dropout, quantization, approximate incidence/range intensity; no NIR-physics claim.
- Four editable procedural Blender scenes with previews, shared meshes and object IDs. Actual OptiX rendering on RTX4080 was recorded before the stability restriction. These remain visibly procedural, especially urban; publication-grade photorealism is unfinished.
- Licensed Poly Haven CC0 HDRI downloaded and packed into urban scene; recorded source/license/hash.
- Configuration CLI, five-sensor batch comparison, multi-capture sequences, separately stored initial errors and boundary-aligned physical drift.
- Measurement-only paired/stacked exports, separate evaluation ground truth/labels/ideal depth/normals/segmentation.
- Reload/hash verification, visibility-aware overlays, supplied-calibration error metrics and decision evaluation.
- Optional ROS1 Noetic replay/bag code, package and launch configuration.
- Local Tk launcher; interactive GUI operation has not been verified.

## Actual verification to date

- Initial sensor tests: 37 passed. Expanded mathematical/export suite: 83 passed before the host-stability change.
- All four scene files, mesh exports, previews and a six-face cubemap were generated and visually inspected; see `RENDER_VERIFICATION.json`.
- Generated complete `outputs/noisy_pinhole` (19,372 returns); full reload/hashes passed. 5,939 shared visible ideal points; maximum camera inverse-projection error 1.05e-12 px and visible-surface intersection difference 3.95e-6 m.
- `outputs/warehouse_avia_v2` and all five `outputs/five_lidars_v2/<sensor>` have completion manifests. Final reload audit follows without rerendering.
- Earlier `warehouse_avia`, `warehouse_avia_verified`, `five_lidars`, and `longitudinal_drift` runs encountered RGB remapping errors; they remain as incomplete diagnostic artifacts and must not be used as verified data.
- Fixes: OpenCV remap's 32,767-row restriction now handled with small chunks; floating cube-edge ties accept 1e-7 pixel rounding tolerance. Proper rotation validation uses zero relative tolerance. Ray-cast chunk sizes validated.
- Livox wheel installed into an isolated target and generated both profiles without the reference checkout. Final wheel needs rebuilding after ongoing source changes.
- Actual Noetic bag serialization/deserialization fixture and isolated catkin package build passed before the stability restriction. Live RViz/publishing and generated-run bag integration are not yet verified.
- Optimizer interface source inspected. It supports OpenCV fisheye k1/k2 only. Pinhole and nonzero k3/k4 are rejected for solver invocation. A real calibration solver run is pending; do not claim convergence or integration success from an I/O fixture.

## Stability changes in progress

Process-local BLAS/OpenMP thread limits and Open3D thread count are one. The CLI takes an OS-released exclusive job lock. New native renders require `--allow-render`; non-CPU devices additionally require `--allow-gpu`. Blender defaults to CPU and one thread. These are resource controls, not proof that a host with undiagnosed kernel crashes is safe to stress.

## Remaining work

Finish small regression checks, consolidated documentation and exact output audit. Complete longitudinal verification using existing outputs or a tiny CPU diagnostic fixture. Native render retries, performance benchmarks, full optimizer solving, actual-run ROS bag replay, GUI interaction and visual realism work remain deferred while the Windows issue is unresolved. Sensor hardware timing/angle validation, physical Avia comparison, motion distortion and physically validated material/weather/multiple-return models remain future research work.

## Continuation after the Windows-stability instruction

- No further Blender/GPU/WSL/optimization jobs launched. CPU work uses one thread. The local launcher defaults to a 160×120 geometry diagnostic with explicit native/GPU opt-ins unchecked.
- Final small regression suite: **105 passed in 3.67 s**; JUnit evidence `docs/TEST_RESULTS.xml`. Python source AST checks passed. Tests include full tiny pipelines for all five sensors, fault separation, seeded noise, cubemap seam/remap regressions, corrupted metadata and resource controls.
- Final output audit: Avia, Mid-360, VLP-16 and OS1 runs passed reload/hash validation. Despite an existing manifest, original `five_lidars_v2/hesai_at128` contains damaged JSON and **fails**. It is preserved and excluded from valid data. Manifests are now published using atomic flushed JSON writes, but filesystem integrity after a host crash still requires hash/reload verification.
- Generated `outputs/hesai_recovered_existing_rgb` with 153,600 AT128 returns using the preserved verified cubemap and CPU geometry. It passed all reload/hash checks. No new RGB rendering occurred.
- Generated and verified `outputs/cpu_check`, a tiny stable→physical-rotation sequence with separate truth and unchanged initial estimate. This uses diagnostic geometry RGB, not photorealistic RGB.
- Actual reference optimizer ingestion succeeded for three Avia captures with 24,000 points each. Source remained read-only; outputs are `outputs/optimizer_ingestion_verified`. Solver optimization was not attempted.
- Existing ROS live fixture evidence was discovered in `outputs/ros_serialization_fixture/live_verification.json`: isolated loopback pub/sub received the six required topics for two points. This earlier fixture check does not validate full generated-run replay or RViz, and was not repeated after the restriction.
- Added README, environment snapshot, precise verification report and implementation handoff. The implementation remains incomplete under the master brief; no full-platform, photorealism or hardware-fidelity completion claim is made.

## Launcher redesign and GPU checks (6 November 2026, user request)

- `tools/launcher.py`: main choices (environment, LiDAR, camera lens, capture count, image mode) are on top, each with a live preview. Environment shows the saved Blender render; LiDAR shows its real scan pattern (`simulator/previews.py`, coloured by firing time); camera shows the lens FOV/distortion from the same `Camera.unproject` used for datasets. All other settings are collapsed under **More settings** (lens/resolution, placement, timing, sampling, output, rendering/GPU/Blender, log).
- GPU: `simulator/gpu.py` detects the NVIDIA GPU (nvidia-smi) at start-up and sets the device to CPU if none is found. **Test GPU in Blender** lists Cycles OptiX/CUDA devices without rendering. Observed: Blender 5.0.1 lists `NVIDIA GeForce RTX 4080` under both OPTIX and CUDA, driver 610.88.
- `blender/build_scene.py`: a GPU request no longer falls back silently to CPU; it raises. OptiX→CUDA fallback is still recorded in the render metadata. The launcher reports the device actually used after each run.
- Not done: no new Cycles render was run in this session (the earlier Windows crash cause is still undiagnosed), so end-to-end OptiX rendering from the new GUI is unverified here. LiDAR ray casting is CPU-only (Open3D/Embree).
- Tests: 105 → 112 passing (`tests/test_previews.py`).
- **Browser UI (replaces Tk as default)**: `tools/webui.py` + `tools/web/index.html`, started by `start_simulator.bat` (http://127.0.0.1:8765, standard library only). Picture cards for 4 environments, 5 LiDARs (real scan patterns) and 2 lens models (live FOV/distortion preview); capture count on top; all other options under a collapsed **More settings**; GPU badge, activity log, latest-result image. Local only: Host check plus per-session token on all POSTs (verified 403 without). Old window kept as `start_simulator_classic.bat`. Verified by headless-Edge screenshot and HTTP endpoint checks; Generate/Build were not clicked (no render run this session).
- **Studio tab (place & capture)**: floor-plan cut-away of the selected environment (click = place rig, drag = aim, cut height slider), sliders for the rig's world pose (x, y, z, roll, pitch, yaw) and for the LiDAR→camera relative pose (camera position in the LiDAR frame + roll/pitch/yaw relative to the default mounting, via `simulator.geometry.camera_extrinsic`), a live geometry camera view using the chosen lens with LiDAR returns overlaid (`simulator/studio.py`, CPU only, ~0.2 s), and "Capture this pose" to build a multi-pose list. Generate writes `poses` + `T_CL` into the config; ground truth (`evaluation/ground_truth.json`) is shown in the side panel and kept separate from `inference/`. Verified through the HTTP API with a geometry-renderer run (2 poses, custom mounting): saved T_CL and T_WL equal the requested values (max abs difference 0.0). The live view is a geometry diagnostic, not the Cycles render. Generating with the Cycles/GPU renderer from the Studio was not run this session.
- **Camera resolution presets** (320×240 … 1280×800, or custom) with focal length scaling to keep the field of view (optional) and K / FOV readout. Resolution is limited to 1,048,576 pixels per capture by the existing `Camera` check.
- Tests: 114 passing.

## Progress bar, flat output folders, accumulated scans

- Generate shows a progress bar (`SIMLAB_PROGRESS` lines from the CLI, parsed by the web UI).
- Output layout flattened to `inference/capture_NNNN/` and `evaluation/capture_NNNN/`; Blender cubemap faces are written into the evaluation capture folder. `simulator.io.capture_dir` still reads the older `captures/` layout.
- New config key `accumulate_s` saves a longer static-rig LiDAR integration (`lidar_accumulated.npz`, `cloud_accumulated.pcd`, `ideal_lidar_accumulated.npz`) beside the 0.1 s snapshot. The GUI defaults it to 1.0 s; verification still checks only the snapshot.
- Browser animation of the Livox non-repetitive scan filling the field of view (Setup tab, Studio floor plan). Not run: a Cycles/OptiX render with the new layout.

## Batches, random poses, run names, progress ETA

- Studio **Create batches**: B batches x N captures. Rig poses are random and valid (floor below, 0.8 m clearance, facing a real surface); the LiDAR-camera mount is fixed inside a batch. Batch 1 uses the nominal mount; each later batch adds an independent uniform offset within the user's rotation (deg) and translation (mm) tolerance. Optional step-by-step animation in the Studio. Nothing is generated until the user presses Generate.
- Pipeline: `T_CLs` (true camera<-LiDAR per capture) and `batch_ids`; `inference/initial_calibration.json` stays the nominal mount. Ground truth gains `batch`; `evaluation/batches.json` lists each batch's capture ids and T_CL; `sequence.json` entries carry `batch`.
- Studio **Random poses**: N random valid poses, only added to the capture list.
- Run folders are named `<environment>_<YYYYMMDD>_<HHMMSS>_<captures>`.
- Progress bar shows elapsed time and an estimated time remaining (server reports elapsed, so it survives a page reload).
- Not run: a Cycles/OptiX render of a batch dataset from the GUI.

## Cancel, richer log, hardening (corner-case review)

- Cancel button (bar) while a job or batch creation runs, with a confirmation dialog. Cancelling stops the process tree (Blender included); files already written stay and the log says so. Batch creation cancel discards the partial batches and restores the mount sliders.
- Activity log: per-step lines with elapsed time, per-capture LiDAR point counts, render time/device, projection check, and a final Results table plus the independent verifier result. Lines are logged inside the job so the page never misses them.
- Child processes are bound to the server's lifetime (Windows kill-on-close job object): closing/killing the server mid-run stops the render instead of leaving it on the GPU holding the job lock. Verified with a hard-killed server.
- Fixed: re-using a run name crashed with `[Errno 17] File exists` on the saved config (now unique); the page disabled the dialog's own buttons while a job ran; unreadable Python errors for bad numbers, blank output, missing parameters; "Scene already built" shown instead of "Another job is running"; unexpected server errors now return a message instead of dropping the connection.
- Changing environment with captured poses now asks first (poses belong to the old scene) and is blocked while batches are being created.
- Verified: 24 invalid-input generate cases, access control, 17 bad Studio parameter cases, double start, cancel races; browser flows (batches with removed poses -> ground truth, cancel mid-animation, reload mid-job, Esc on dialog, environment switch). A real Detailed OptiX run on the RTX 4080 (5 captures, flat layout, 1 s accumulation) passes `verify`.

## 7 November 2026 - requested layout and save-folder continuation

- Studio uses a left workspace for the floor plan, camera view, captures and Ground truth; world-rig and relative camera pose controls are stacked on the right. Activity spans both columns below the content. Existing batch creation and cancellation controls are retained.
- Generate opens the native save-folder picker and remembers its last selected parent across restarts. Cancelling starts no job and saves no capture configuration. Generation validation failures now release the busy state after folder selection.
- Verified persistent-folder selection/fallback, cancelled selection, busy-job guards, DOM placement and Python/JavaScript syntax. An isolated headless Edge layout check confirms right-side pose controls, left-side truth, bottom Activity and no horizontal overflow at 980, 700 or 390 pixels. No simulation render, GPU test, WSL job or live-server restart was performed for these edits.
