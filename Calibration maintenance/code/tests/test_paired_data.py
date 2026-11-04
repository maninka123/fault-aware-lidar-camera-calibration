"""Pair discovery, real PCD encodings, unit checks and GUI/runner integration."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import appcore
import cv2
import numpy as np
from pypcd4 import PointCloud, Encoding
from paired_data import discover_pairs, validate_pairs, load_pairs, read_cloud, save_stacked


def image(path, shape=(96, 128, 3)):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(cv2.imencode(path.suffix.lower(), np.zeros(shape, dtype=np.uint8))[1].tobytes())


def cloud(path, scale=1, encoding=Encoding.BINARY, intensity=True):
    path.parent.mkdir(parents=True, exist_ok=True)
    xyz = np.column_stack((np.linspace(3, 5, 300), np.linspace(-1, 1, 300), np.full(300, .25))).astype(np.float32) * scale
    value = (PointCloud.from_xyzi_points(np.column_stack((xyz, np.linspace(0, 255, 300))).astype(np.float32))
             if intensity else PointCloud.from_xyz_points(xyz))
    value.save(path, encoding=encoding)
    return xyz


def split_pair(root, scale=1):
    image(root / 'camera export' / 'image_001.PNG')
    return cloud(root / 'Avia scans' / 'cloud_001.PCD', scale)


class PairImportTests(unittest.TestCase):
    def test_arbitrary_folder_names_and_common_filename_prefixes(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            split_pair(root)
            found = discover_pairs(root)
            self.assertEqual(len(found['captures']), 1)
            self.assertEqual(appcore.data_kind(root), 'paired')
            checked = validate_pairs(root)
            self.assertTrue(checked['analysis_usable'])
            self.assertFalse(checked['units_review'])

    def test_nested_capture_folders_identify_single_pairs(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            for folder in ('day_one/position_a', 'day_one/position_b'):
                image(root / folder / 'photo.png')
                cloud(root / folder / 'lidar_points.pcd')
            pairs = discover_pairs(root)['captures']
            self.assertEqual(len(pairs), 2)
            self.assertEqual(len({pair['short'] for pair in pairs}), 2)
            self.assertEqual(len(load_pairs(root)[0]), 2)

    def test_unmatched_files_are_reported_and_not_paired_by_order(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            split_pair(root)
            image(root / 'camera export' / 'image_002.png')
            cloud(root / 'Avia scans' / 'cloud_003.pcd')
            found = discover_pairs(root)
            self.assertEqual(len(found['captures']), 1)
            self.assertEqual(len(found['warnings']), 2)

    def test_incomplete_capture_folders_are_reported(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            image(root / 'position_a' / 'photo.png')
            cloud(root / 'position_a' / 'scan.pcd')
            image(root / 'position_b' / 'photo.png')
            cloud(root / 'position_c' / 'scan.pcd')
            found = discover_pairs(root)
            self.assertEqual(len(found['captures']), 1)
            self.assertEqual(len(found['warnings']), 2)

    def test_duplicate_capture_ids_block_import(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            split_pair(root)
            image(root / 'camera export' / 'capture_001.jpg')
            with self.assertRaisesRegex(ValueError, 'Ambiguous'):
                discover_pairs(root)

    def test_all_standard_pcd_encodings_are_read(self):
        with TemporaryDirectory() as temporary:
            for encoding in (Encoding.ASCII, Encoding.BINARY, Encoding.BINARY_COMPRESSED):
                path = Path(temporary) / f'{encoding.value}.pcd'
                expected = cloud(path, encoding=encoding)
                xyz, intensity, has_intensity, discarded = read_cloud(path)
                np.testing.assert_allclose(xyz, expected, atol=1e-5)
                self.assertTrue(has_intensity)
                self.assertEqual(discarded, 0)

    def test_millimetres_are_flagged_instead_of_silently_rescaled(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = split_pair(root, scale=1000)
            self.assertTrue(validate_pairs(root, 'm')['units_review'])
            with self.assertRaisesRegex(ValueError, 'units'):
                load_pairs(root, 'm')
            frames, checked = load_pairs(root, 'mm')
            self.assertFalse(checked['units_review'])
            np.testing.assert_allclose(frames[0].xyz, original / 1000, atol=1e-6)

    def test_missing_intensity_is_reported(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            image(root / 'pose_a' / 'photo.png')
            cloud(root / 'pose_a' / 'points.pcd', intensity=False)
            frames, checked = load_pairs(root)
            self.assertTrue(any('no intensity' in warning for warning in checked['warnings']))
            np.testing.assert_array_equal(frames[0].intensity, 0)

    def test_unreadable_files_and_mixed_image_sizes_are_rejected(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            split_pair(root)
            bad = root / 'Avia scans' / 'cloud_001.PCD'
            bad.write_bytes(b'not a PCD')
            with self.assertRaisesRegex(ValueError, 'Cannot read PCD'):
                validate_pairs(root)
            cloud(bad)
            image(root / 'camera export' / 'image_002.png', shape=(120, 160, 3))
            cloud(root / 'Avia scans' / 'cloud_002.pcd')
            with self.assertRaisesRegex(ValueError, 'dimensions differ'):
                validate_pairs(root)

    def test_runner_and_stacked_conversion_preserve_metre_coordinates(self):
        from settings import load_config, load_stacked
        from maintain import get_frames
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / 'inputs'
            expected = split_pair(root)
            out = Path(temporary) / 'outputs'
            frames, decoded = get_frames(root, out, load_config(), cloud_units='m')
            self.assertIsNone(decoded)
            self.assertEqual(json.loads((out / 'paired_input.json').read_text())['units'], 'm')
            save_stacked(frames, out / 'prepared')
            restored = load_stacked(out / 'prepared')
            np.testing.assert_allclose(restored[0].xyz, expected, atol=1e-6)
            np.testing.assert_array_equal(restored[0].time, 0)
            from common import load_frames
            cfg = load_config()
            cfg['stacked_dir'] = str(out)
            cfg['oct29_dir'] = str(Path(temporary) / 'not_a_dataset')
            self.assertEqual(len(load_frames(cfg, 'prepared')), 1)

    def test_gui_blocks_wrong_units_and_emits_selected_units(self):
        import app
        from PyQt5 import QtWidgets, QtTest
        qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        qapp.setStyleSheet(app.QSS)
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / 'inputs'
            split_pair(root)
            path = Path(temporary) / 'calibration.json'
            path.write_text(json.dumps(dict(image_size=[128, 96],
                intrinsics=dict(camera_matrix=[[80, 0, 64], [0, 80, 48], [0, 0, 1]], distortion_coefficients=[0, 0, 0, 0]),
                extrinsics=dict(transform_lidar_to_camera=[[0, 0, -1, 0], [0, 1, 0, 0], [1, 0, 0, 0], [0, 0, 0, 1]]))))
            page = app.SetupPage()
            page.load_cal(path)
            page.load_data(root)
            self.assertTrue(page.go.isEnabled())
            page.pair_units.setCurrentIndex(1)
            self.assertFalse(page.go.isEnabled())
            page.pair_units.setCurrentIndex(0)
            self.assertTrue(page.go.isEnabled())
            signal = QtTest.QSignalSpy(page.run_requested)
            page.calculate()
            self.assertEqual(signal[0][4], 'm')
            (root / 'Avia scans' / 'cloud_001.PCD').write_bytes(b'broken PCD')
            page.validate_paired_data()
            self.assertFalse(page.go.isEnabled())
            self.assertFalse(page.pair_report_button.isEnabled())
            page.load_data(Path(temporary) / 'missing_folder')
            self.assertFalse(page.go.isEnabled())
            page.close()


if __name__ == '__main__':
    unittest.main()
