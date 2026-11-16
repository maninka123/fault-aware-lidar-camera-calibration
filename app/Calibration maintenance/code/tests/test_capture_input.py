"""The capture-format examples must match the actual folder and array loaders."""
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import appcore
import numpy as np
from settings import load_stacked


class CaptureInputTests(unittest.TestCase):
    def test_recorded_layout_selects_the_parent_folder(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / 'my_captures'
            for index in range(1, 4):
                recording = root / f'capture_{index:03}' / 'rig_0.bag'
                recording.parent.mkdir(parents=True)
                recording.touch()  # Folder discovery only; this test does not decode a bag.
            info = appcore.inspect_data(root)
            self.assertEqual(info['kind'], 'raw')
            self.assertEqual(len(info['captures']), 3)
            with self.assertRaises(ValueError):
                appcore.inspect_data(root / 'capture_001')

    def test_documented_stacked_fields_load_with_the_right_units(self):
        with TemporaryDirectory() as temporary:
            np.savez(Path(temporary) / 'capture_001.npz',
                     image=np.zeros((4, 6, 3), dtype=np.uint8),
                     xyz_mm=np.array([[1000, 2000, 3000], [4000, 5000, 6000]]),
                     intensity=np.array([80, 120]), frame=np.array([1, 0], dtype=int),
                     frame_time=np.array([0.0, 0.1]))
            self.assertEqual(appcore.inspect_data(temporary)['kind'], 'stacked')
            frames = load_stacked(temporary)
            self.assertEqual(len(frames), 1)
            np.testing.assert_allclose(frames[0].xyz, [[1, 2, 3], [4, 5, 6]])
            np.testing.assert_allclose(frames[0].time, [0.1, 0.0])


if __name__ == '__main__':
    unittest.main()
