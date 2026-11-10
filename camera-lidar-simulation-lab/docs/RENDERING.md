# Scene generation and Cycles rendering

**Host stability update, 5 November 2026:** new Blender/GPU execution is suspended after the user's reported Windows blue screens. The rendered artifacts and verification below were produced earlier. Scripts now default to CPU with one rendering thread. Any later native render requires `--allow-render`; a GPU device additionally requires `--allow-gpu`. These flags do not resolve or diagnose the host issue. Use existing cubemap images or the small geometry diagnostic while it remains unresolved. Historical commands below will stop unless those explicit flags are supplied.

The scene generator runs inside **Windows Blender 5.0.1**. The first local render detected and used **NVIDIA OptiX on the GeForce RTX 4080**. `metadata.json` records the requested backend, selected backend, selected devices, and failed detection attempts. Device selection tries the requested backend, CUDA, then CPU; the recorded backend is never changed to conceal a fallback. Render errors propagate instead of being reported as successful captures.

Example, from the project root in PowerShell:

```powershell
& 'C:\Program Files\Blender Foundation\Blender 5.0\blender.exe' --background --python blender/build_scene.py -- --scene warehouse --output blender/scenes/warehouse --samples 32 --width 640 --height 480 --device OPTIX
```

`--scene` selects `warehouse`, `laboratory`, `urban`, or `corridor`. Each construction script uses a fixed procedural seed of 42, physical dimensions in metres, and a right-handed world frame with +X forward, +Y left, and +Z up. The default camera origin is `[0, 0, 1.6]`, facing +X, with a 100-degree horizontal perspective field of view. The exact OpenCV camera-to-world pose and intrinsic matrix appear in the metadata. Pixel coordinates refer to pixel centres, so the default principal point is `[(width-1)/2, (height-1)/2]`.

Generated files:

| File | Contents |
|---|---|
| `scene.blend` | Editable geometry, PBR materials, camera, and lights |
| `preview.png` | Actual Cycles render |
| `mesh.npz` | `vertices` V×3 float32 world coordinates; `triangles` F×3 int32 vertex indices; `face_ids` F int32 object IDs; `colors` F×3 float32 nominal material RGB |
| `objects.json` | Object ID, name, and semantic class mapping |
| `metadata.json` | Frames, camera calibration, device, software version, triangle counts, settings, and elapsed time |

Meshes come from Blender's **evaluated dependency graph**, so bevel modifiers and converted text geometry participate in both rendering and LiDAR intersections. There is one geometric world. Procedural noise feeds the material colour and shader bump normal; it does not displace the surface geometry. Nominal material RGB is provided for previews only and is **not calibrated near-infrared reflectance**. The windows are opaque blue emissive panels, not a validated transmission model. Atmospheric effects, multipath, transparent refraction, and multiple LiDAR returns are not simulated by this geometry export.

The warehouse has racks with three shelf heights, cartons, taped packaging, pallets, roof beams, industrial lights, pipes, barrels, doors, a roller shutter, aisle markings, and a forklift. The laboratory has desks, chairs, displays, keyboards, equipment cabinets, doors, windows, floor joints, and ceiling panels. The street has several distances of buildings, repeated window frames, paving, kerbs, lane markings, vehicles, trees, poles, and a traffic sign. The corridor intentionally has parallel walls, repeated piers and crossbeams, low-texture surfaces, dim lighting, pipes, and partial obstructions.

## Arbitrary camera models through cubemap rendering

The core simulator controls the declared pinhole or OpenCV fisheye projection. Blender renders six 90-degree perspective images from the same camera origin; the core maps inverse-projected pixel rays to those rendered faces. This avoids treating Blender's artistic lens settings as OpenCV distortion coefficients.

Write a JSON file with `{"T_WC": [[...], ...]}` in the OpenCV frame (+X right, +Y down, +Z forward), then run:

```powershell
& 'C:\Program Files\Blender Foundation\Blender 5.0\blender.exe' --background --python blender/build_scene.py -- --blend blender/scenes/warehouse/scene.blend --pose-json camera_pose.json --output outputs/cube --cubemap --cube-size 512 --samples 32 --device OPTIX
```

`cube_metadata.json` contains `faces`, a list of objects with `name`, `image`, `T_WC`, and `K`. Face images are `cube_px.png`, `cube_nx.png`, `cube_py.png`, `cube_ny.png`, `cube_pz.png`, and `cube_nz.png`. The axis names refer to the **base OpenCV camera frame**, not the world frame. `camera_base_T_WC` records that base pose. All faces use the same optical centre and fixed 90-degree field of view. The scene frame and mesh do not change. Cubemap resampling introduces finite image resolution and interpolation error, especially at face boundaries; the core geometric depth and segmentation should use independent ray intersections at exact declared camera rays.

## Rendering quality and provenance

These are original, detailed **procedural environments**, generated without redistributed third-party assets. They are useful editable geometry for calibration experiments; they have not been validated as a photorealistic benchmark. No claim of asset-backed photorealism is made. More detailed modelling, photographic textures, professionally authored assets, and wider visual review remain necessary for publication-quality realism.

The urban example includes Poly Haven's CC0 **Industrial Sunset 02** HDRI by Sergej Majboroda. Its reviewed official download URL, exact size, and SHA256 are recorded in `docs/ASSETS.json`. Run `python tools/fetch_assets.py` to download or verify the original asset. The API endpoint returned HTTP 403, but the direct official asset URL was accessible and its actual download was verified. The image is packed into the generated urban `.blend`, so editing the scene does not depend on a personal absolute asset path. Other scenes use procedural environment lighting. An optional local HDRI can be passed with `--hdri <path>` when constructing a scene; retain that asset's provenance and licence. Do not assume an arbitrary HDRI is reusable.

The direct Blender Python backend was chosen to use the already-installed Blender 5.0.1 without replacing its Python runtime. BlenderProc was reviewed as a reference for distance versus Z-depth and segmentation outputs; it is not a project runtime dependency, and no BlenderProc code is copied. This avoids making dataset generation depend on a second Blender installation or untested BlenderProc/Blender version pairing. Sources: [BlenderProc renderer documentation](https://dlr-rm.github.io/BlenderProc/docs/tutorials/renderer.html), [Blender Cycles GPU rendering manual](https://docs.blender.org/manual/en/latest/render/cycles/gpu_rendering.html), [Poly Haven licence](https://polyhaven.com/license).

Use 16–32 samples for composition checks, 64 for routine datasets, and 256 or more when examining fine appearance. These are project presets, not measured guarantees of photorealism. Denoising and adaptive sampling are enabled. Finite Cycles sampling and GPU/software differences can affect RGB reproducibility; deterministic scientific geometry is a separate requirement.

## Browser app

`start_simulator.bat` runs `tools/webui.py`, a local-only browser interface. It selects the scene, LiDAR, pinhole/fisheye camera, image size, focal length, captures, scan timing, render settings, Blender executable and output folder, then saves an inspectable YAML config under `configs/gui` and invokes the same `python -m simulator generate` CLI used by batch experiments. Build and generation run as subprocesses, one job at a time. The shared settings helpers live in `tools/launcher.py` (the old Tk window was removed).
