"""Image encodings found in recorded bags decode to BGR with the right colour channels."""
from pathlib import Path
from types import SimpleNamespace
import sys
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'multi_capture_calibration'))
from mcc.bag_io import _decode_image  # noqa: E402


def message(encoding, array):
    h, w = array.shape[:2]
    channels = 1 if array.ndim == 2 else array.shape[2]
    return SimpleNamespace(encoding=encoding, height=h, width=w, step=w * channels, data=array.tobytes())


def mosaic(bgr, pattern):
    """Sample a smooth BGR image through a colour-filter pattern; pattern lists the colours of a 2x2 tile row-major."""
    index = {'r': 2, 'g': 1, 'b': 0}
    out = np.zeros(bgr.shape[:2], np.uint8)
    for k, colour in enumerate(pattern):
        out[k // 2::2, k % 2::2] = bgr[k // 2::2, k % 2::2, index[colour]]
    return out


def test_bayer_patterns_recover_a_smooth_colour_image():
    rng = np.random.default_rng(0)
    base = np.array([200, 60, 20], float)  # strongly blue, so swapped red/blue would be obvious
    bgr = np.clip(base + rng.normal(0, 1, (64, 64, 3)), 0, 255).astype(np.uint8)
    for name, tile in (('bayer_rggb8', 'rggb'), ('bayer_bggr8', 'bggr'), ('bayer_gbrg8', 'gbrg'), ('bayer_grbg8', 'grbg')):
        decoded = _decode_image(message(name, mosaic(bgr, tile)))
        assert decoded.shape == bgr.shape and decoded.dtype == np.uint8
        inner = decoded[8:-8, 8:-8].reshape(-1, 3).mean(axis=0)
        assert np.abs(inner - base).max() < 6, (name, inner)


def test_existing_encodings_and_clear_error_for_unknown():
    rgb = np.zeros((4, 4, 3), np.uint8)
    rgb[..., 0] = 255
    assert _decode_image(message('rgb8', rgb))[0, 0].tolist() == [0, 0, 255]
    try:
        _decode_image(message('yuv422', np.zeros((4, 4), np.uint8)))
    except ValueError as error:
        assert 'bayer_rggb8' in str(error)
    else:
        raise AssertionError('expected ValueError')
