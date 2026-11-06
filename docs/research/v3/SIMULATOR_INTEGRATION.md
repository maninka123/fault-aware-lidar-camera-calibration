# Simulator integration contract

The separate photorealistic simulator is not implemented here. Its five LiDAR profiles can export the same versioned format; `lidar_profile` identifies provenance rather than selecting an invented beam model. The present implementation accepts only the repository's OpenCV equidistant polynomial camera model and canonical metre calibration translations.

`research_calibration/fault_diagnostics_v3/simulator_adapter.py` implements `load_signature_dataset`. This first adapter targets exact-correspondence numerical verification. It does not convert simulator truth into automatic edge correspondences or claim to validate the image/LiDAR front end. For end-to-end matching, export paired images and PCD clouds in the existing [data format](../../DATA_FORMAT.md), and pass their folder to `diagnose-v3`.

An exact-correspondence export has a UTF-8 JSON manifest:

```json
{
  "schema_version": "fault-signatures-v3/1",
  "role": "test",
  "recording_id": "independent_session_001",
  "lidar_profile": "simulator_defined_profile",
  "projection": "opencv_fisheye",
  "pose_convention": "T_camera_from_lidar",
  "calibration_translation_units": "m",
  "point_units": "m",
  "image_size": [800, 800],
  "max_angle_rad": 1.0,
  "calibration_under_test": {
    "intrinsics": {
      "camera_matrix": [[240, 0, 400], [0, 240, 400], [0, 0, 1]],
      "distortion_coefficients": [0, 0, 0, 0]
    },
    "extrinsics": {
      "transform_lidar_to_camera": [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
    }
  },
  "captures": [{"id": "capture_001", "file": "capture_001.npz", "sha256": "64_hex_characters"}]
}
```

Each NPZ contains `xyz` `(N,3)` LiDAR points and observed `uv` `(N,2)` camera pixels for the same physical features. Optional arrays are `signs` `(N,)` beam-side labels, `visible` `(N,)` true joint visibility, and `sigma_px` `(N,2)` positive declared per-coordinate noise scales. Pickle loading is disabled. The adapter checks schema, role, predeclared recording IDs, pose convention, projection family, paths within the dataset folder, file hashes and array shapes. Millimetre point arrays are converted to metres; calibration translations stay in metres. Invalid/occluded/nonfinite projections are excluded explicitly.

```python
from research_calibration.fault_diagnostics_v3.simulator_adapter import load_signature_dataset
from research_calibration.fault_diagnostics_v3 import infer_signatures

data = load_signature_dataset("manifest.json", expected_role="test",
                              declared_ids=["independent_session_001"])
result = infer_signatures(data["jacobian"], data["residual_change"], data["scales"],
                          covariance=data["covariance"], capture_ids=data["capture_ids"])
```

`residual_change` is observed target minus the projection under the calibration being diagnosed. It is supplied measurement information, not a parameter-fault label. Pose/intrinsic ground truth, actual injected fault groups, scene seed, renderer/simulator commit, lens model, sensor profile, timestamps, occlusion identity, depth, feature identity and point-correlation provenance belong in the evaluation manifest. Labels and true calibration must be withheld from fitting and observation utility. The adapter retains provenance but does not use fault labels in inference.

Declare complete recording-level development, calibration and test partitions and hashes before inspecting test outcomes. Shared scene seeds, camera paths and overlapping accumulation windows must not cross a supposedly independent split. The current adapter supports diagonal pixel covariance; `infer_signatures` additionally accepts a full positive-definite covariance when independently justified. The active-selection API supports block-diagonal covariance between candidate captures only; joint prewhitening of an entire pool followed by row selection is invalid.

Required future experiments include known mount rotations/translations, principal-point/focal/distortion changes, combined faults, camera occlusion, missing returns, timing offsets, motion during accumulation, lighting changes and real correspondence failure. Report parameter errors against true poses/intrinsics separately from nearest-edge alignment. No imported simulator or physical dataset has yet established those results.
