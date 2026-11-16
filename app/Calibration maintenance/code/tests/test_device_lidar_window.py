"""Verify selected LiDAR frames are exactly the frames previewed and saved."""
import sys
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import device_capture as dc


class Stream:
    def __init__(self, image=False, available=None):
        self.image, self.available, self.count, self.closed = image, available, 0, False

    def next(self):
        time.sleep(.002)
        if self.available is not None and self.count >= self.available:
            raise TimeoutError('test stream ended')
        self.count += 1
        value = (np.full((3, 4, 3), self.count % 255, dtype=np.uint8) if self.image else
                 np.array([[float(self.count), .2, .3, 20], [float(self.count), .4, .5, 30]], dtype=np.float32))
        return time.time(), value

    def close(self):
        self.closed = True


class Link:
    def __init__(self, available=None):
        self.camera, self.lidar = Stream(image=True), Stream(available=available)

    def subscribe(self, topic, msgtype, throttle_s=None):
        return self.camera if topic == '/image' else self.lidar


class LidarWindowTests(unittest.TestCase):
    def setUp(self):
        self.image_patch = patch.object(dc.rl, 'decode_image', side_effect=lambda x: x)
        self.cloud_patch = patch.object(dc.rl, 'decode_cloud', side_effect=lambda x: x)
        self.image_patch.start(); self.cloud_patch.start()

    def tearDown(self):
        self.image_patch.stop(); self.cloud_patch.stop()

    def test_exact_one_and_ten_frames_in_preview(self):
        for target in (1, 10):
            link, events = Link(), []
            result = dc.snapshot(link, '/image', '/cloud', lidar_frames=target, progress=events.append)
            self.assertEqual(link.lidar.count, target)
            self.assertEqual(result['lidar_frames'], target)
            self.assertEqual(len(result['cloud']), 2 * target)
            self.assertEqual(events[-1]['clouds'], target)
            self.assertEqual(len(events[-1]['cloud']), 2 * target)
            self.assertTrue(link.lidar.closed and link.camera.closed)

    def test_duration_reads_multiple_frames_for_selected_time(self):
        link = Link()
        started = time.monotonic()
        _, cloud = dc.collect_sample(link, '/image', '/cloud', seconds=.035, image_hz=1000)
        self.assertGreaterEqual(time.monotonic() - started, .03)
        self.assertGreater(len(cloud['items']), 1)
        self.assertLess(len(cloud['items']), 30)

    def test_short_stream_fails_instead_of_claiming_ten_frames(self):
        with self.assertRaisesRegex(dc.rl.LinkError, '2 of 10'):
            dc.collect_sample(Link(available=2), '/image', '/cloud', lidar_frames=10,
                              image_hz=1000, frame_timeout=.05)

    def test_stop_prevents_completion(self):
        stop = threading.Event()
        with self.assertRaises(InterruptedError):
            dc.collect_sample(Link(), '/image', '/cloud', lidar_frames=100, image_hz=1000,
                              stop=stop, progress=lambda _: stop.set())

    def test_exact_frames_saved_without_motion_filter_dropping_them(self):
        for target in (1, 10):
            with tempfile.TemporaryDirectory() as tmp, \
                    patch.object(dc, 'load_config', return_value={'decode': {}}), \
                    patch.dict(sys.modules, {'decode_bags': SimpleNamespace(
                        lidar_keep=lambda *_: self.fail('Exact-frame capture must retain the selected frames'))}):
                path, summary = dc.capture_once(Link(), '/image', '/cloud', 1, tmp,
                                                image_hz=1000, lidar_frames=target)
                with np.load(path) as saved:
                    self.assertEqual(int(saved['n_frames']), target)
                    self.assertEqual(len(saved['xyz_mm']), 2 * target)
                self.assertEqual(summary['lidar_frames'], target)
                self.assertEqual(summary['lidar_frames_used'], target)


if __name__ == '__main__':
    unittest.main()
