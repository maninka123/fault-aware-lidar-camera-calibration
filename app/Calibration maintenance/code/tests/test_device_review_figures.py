"""Device review figures must support portrait, landscape and smaller cameras."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import settings  # adds the targetless modules and sets numerical-library limits
import figures
import numpy as np


class DeviceReviewFigureTests(unittest.TestCase):
    def test_zoom_panel_matches_camera_dimensions_including_portrait(self):
        for width, height in ((366, 484), (484, 366), (640, 480), (320, 240), (48, 32)):
            frame = SimpleNamespace(image=np.zeros((height, width, 3), np.uint8))
            cap = SimpleNamespace(img={'dist': np.zeros((height, width))})
            projection = (np.array([]), np.array([]), np.array([], dtype=bool), np.array([]))
            with patch.object(figures.s4, 'project_edges', return_value=projection):
                panel = figures.zooms(frame, cap, SimpleNamespace(w=width, h=height), None, None)
            self.assertEqual(panel.shape, (height * figures.s4.S, width * figures.s4.S, 3))

    def test_full_portrait_comparison_composes_without_empty_legend_or_height_mismatch(self):
        width, height = 366, 484
        shape = (height * figures.s4.S, width * figures.s4.S, 3)
        frame = SimpleNamespace(image=np.zeros((height, width, 3), np.uint8))
        cap = SimpleNamespace(img={'dist': np.zeros((height, width))})
        projection = (np.array([]), np.array([]), np.array([], dtype=bool), np.array([]))
        with patch.object(figures.s4, 'project_edges', return_value=projection), \
                patch.object(figures.s4, 'alignment_panel', return_value=(np.zeros(shape, np.uint8), 50)), \
                patch.object(figures.s4, 'difference_panel', return_value=np.zeros(shape, np.uint8)):
            image = figures.compare(frame, cap, SimpleNamespace(w=width, h=height), None, None, None, 'Device', 'KEEP')
        self.assertEqual(image.shape, (2 * shape[0] + 42, 2 * shape[1] + 8, 3))


if __name__ == '__main__':
    unittest.main()
