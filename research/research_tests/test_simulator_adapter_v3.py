import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from research_calibration.fault_diagnostics_v3.simulator_adapter import load_signature_dataset


class SimulatorAdapterTests(unittest.TestCase):
    def fixture(self, root, units='m'):
        root = Path(root)
        file = root/'capture.npz'
        xyz = np.array([[0., 0., 2.], [.1, .2, 3.]])
        np.savez(file, xyz=xyz*(1000 if units == 'mm' else 1), uv=np.array([[242., 183.], [248., 196.]]))
        manifest = dict(schema_version='fault-signatures-v3/1', role='test', recording_id='independent',
                        pose_convention='T_camera_from_lidar', calibration_translation_units='m', point_units=units,
                        projection='opencv_fisheye', image_size=[484, 366], lidar_profile='future_profile_1',
                        calibration_under_test=dict(intrinsics=dict(camera_matrix=[[200, 0, 242], [0, 205, 183], [0, 0, 1]],
                            distortion_coefficients=[0, 0, 0, 0]), extrinsics=dict(transform_lidar_to_camera=np.eye(4).tolist())),
                        captures=[dict(id='capture', file='capture.npz', sha256=hashlib.sha256(file.read_bytes()).hexdigest())])
        path = root/'manifest.json'; path.write_text(json.dumps(manifest), encoding='utf-8')
        return path, manifest

    def test_hash_verified_load_and_explicit_split(self):
        with tempfile.TemporaryDirectory() as root:
            path, _ = self.fixture(root)
            result = load_signature_dataset(path, expected_role='test', declared_ids=['independent'])
            self.assertEqual(result['jacobian'].shape, (4, 13))
            with self.assertRaises(ValueError): load_signature_dataset(path, expected_role='development')
            with self.assertRaises(ValueError): load_signature_dataset(path, expected_role='test', declared_ids=['other'])

    def test_millimetre_points_convert_consistently(self):
        with tempfile.TemporaryDirectory() as root:
            path, _ = self.fixture(root)
            metres = load_signature_dataset(path, expected_role='test')
            path, _ = self.fixture(root, 'mm')
            mm = load_signature_dataset(path, expected_role='test')
            np.testing.assert_allclose(metres['jacobian'], mm['jacobian'])

    def test_corruption_projection_and_path_escape_refused(self):
        with tempfile.TemporaryDirectory() as root:
            path, manifest = self.fixture(root)
            manifest['captures'][0]['sha256'] = 'bad'
            path.write_text(json.dumps(manifest))
            with self.assertRaises(ValueError): load_signature_dataset(path, expected_role='test')
            manifest['projection'] = 'pinhole'; path.write_text(json.dumps(manifest))
            with self.assertRaises(ValueError): load_signature_dataset(path, expected_role='test')
            manifest['projection'] = 'opencv_fisheye'; manifest['captures'][0]['file'] = '../escape.npz'
            path.write_text(json.dumps(manifest))
            with self.assertRaises(ValueError): load_signature_dataset(path, expected_role='test')


if __name__ == '__main__':
    unittest.main()
