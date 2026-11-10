import importlib.util
import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from simulator.adapters import export_paired, export_stacked, sequence_entries, validate_optimizer_camera


@pytest.fixture
def run(tmp_path):
    root = tmp_path / "run"
    capture = root / "inference/capture_0000"
    capture.mkdir(parents=True)
    image_bgr = np.zeros((12, 16, 3), np.uint8)
    image_bgr[:, :, 2] = 255
    ok, encoded = cv2.imencode(".png", image_bgr)
    assert ok
    (capture / "image.png").write_bytes(encoded)
    (capture / "cloud.pcd").write_text("sentinel point cloud", encoding="ascii")
    np.savez(capture / "lidar.npz", xyz=np.array([[100, 2, 3], [4, 5, 6]], float),
             intensity=np.array([20, 30], np.float32), timestamps=np.array([1.25, 1.26]),
             directions=np.array([[1, 0, 0], [0, 1, 0]]), channel=np.array([0, 1]))
    (root / "inference/sequence.json").write_text(json.dumps([
        dict(capture_id="capture_0000", timestamp=1.25, path="capture_0000")]))
    (root / "inference/initial_calibration.json").write_text(json.dumps(dict(
        intrinsics=dict(model="fisheye", camera_matrix=[[8, 0, 8], [0, 8, 6], [0, 0, 1]],
                        distortion_coefficients=[0, 0, 0, 0]),
        extrinsics=dict(transform_lidar_to_camera=np.eye(4).tolist()))))
    (root / "evaluation").mkdir()
    (root / "evaluation/ground_truth.json").write_text('"SECRET_TRUTH"')
    return root


def test_stacked_units_color_timing_and_no_truth(run, tmp_path):
    target = export_stacked(run, tmp_path / "stacked")
    with np.load(target / "capture_0000.npz") as data:
        assert data["image"].dtype == np.uint8
        assert data["image"][0, 0].tolist() == [0, 0, 255]
        assert data["xyz_mm"][0, 0] == 100000  # exceeds int16; no range clipping
        np.testing.assert_array_equal(data["frame_time"][data["frame"]], [1.25, 1.25])
        np.testing.assert_allclose(data["point_time"], [1.25, 1.26])
    assert not any("SECRET_TRUTH" in path.read_text(errors="ignore") for path in target.glob("*.json"))
    assert not (target / "ground_truth.json").exists()


def test_paired_export_is_measurements_only(run, tmp_path):
    target = export_paired(run, tmp_path / "paired")
    assert (target / "capture_0000/cloud.pcd").read_text() == "sentinel point cloud"
    assert set(p.name for p in target.iterdir()) == {"capture_0000", "initial_calibration.json", "export_metadata.json"}
    with pytest.raises(FileExistsError):
        export_paired(run, target)


def test_rejects_inference_path_escape(run, tmp_path):
    sequence = run / "inference/sequence.json"
    sequence.write_text(json.dumps([dict(capture_id="x", timestamp=0, path="../evaluation")]))
    with pytest.raises(ValueError, match="inside inference"):
        sequence_entries(run)


def test_rejects_invalid_timestamps(run):
    (run / "inference/sequence.json").write_text(json.dumps([
        dict(capture_id="x", timestamp=float("nan"), path="capture_0000")]))
    with pytest.raises(ValueError, match="timestamps"):
        sequence_entries(run)


@pytest.mark.parametrize("model,coefficients", [("pinhole", [0]*5), ("fisheye", [0, 0, .1, 0])])
def test_rejects_unsupported_optimizer_projection(model, coefficients):
    with pytest.raises(ValueError):
        validate_optimizer_camera(dict(intrinsics=dict(model=model, distortion_coefficients=coefficients)))


def test_ros_rotation_conversion_without_ros():
    script = Path(__file__).resolve().parents[1] / "ros1/scripts/replay_dataset.py"
    spec = importlib.util.spec_from_file_location("ros_replay", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    from scipy.spatial.transform import Rotation
    for angle in ([0, 0, 0], [180, 0, 0], [30, 50, -70]):
        rotation = Rotation.from_euler("xyz", angle, degrees=True)
        q = module.quaternion_from_rotation(rotation.as_matrix())
        np.testing.assert_allclose(Rotation.from_quat(q).as_matrix(), rotation.as_matrix(), atol=1e-12)
