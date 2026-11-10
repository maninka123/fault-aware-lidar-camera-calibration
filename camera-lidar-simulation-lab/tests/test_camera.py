"""Projection agreement and declared lens inversion (verification C)."""
import cv2
import numpy as np
import pytest

from simulator.camera import Camera
from simulator.geometry import apply, default_extrinsic


def camera(model="fisheye", distortion=None):
    return Camera(model, 320, 240, [[150, 0, 159.5], [0, 155, 119.5], [0, 0, 1]],
                  [0, 0, 0, 0] if distortion is None else distortion)


@pytest.mark.parametrize("model,D", [("pinhole", [.04, -.005, .001, -.002, .0003]),
                                    ("fisheye", [.02, -.001, .0001, 0])])
def test_inverse_rays_project_to_pixels_and_opencv_agrees(model, D):
    c = camera(model, D)
    u, v = np.meshgrid(np.linspace(0, 319, 15), np.linspace(0, 239, 12))
    pixels = np.c_[u.ravel(), v.ravel()]
    rays = c.unproject(pixels)
    np.testing.assert_allclose(np.linalg.norm(rays, axis=1), 1, atol=1e-13)
    uv, _ = c.project(rays * np.linspace(1, 80, len(rays))[:, None])
    np.testing.assert_allclose(uv, pixels, atol=1e-8)
    if model == "fisheye":
        cv_rays = cv2.fisheye.undistortPoints(pixels[:, None, :], c.K, c.D).reshape(-1, 2)
        expected, _ = cv2.fisheye.projectPoints(rays[:, None, :], np.zeros(3), np.zeros(3), c.K, c.D)
    else:
        cv_rays = cv2.undistortPointsIter(pixels[:, None, :], c.K, c.D, None, None,
            (cv2.TERM_CRITERIA_COUNT | cv2.TERM_CRITERIA_EPS, 100, 1e-12)).reshape(-1, 2)
        expected, _ = cv2.projectPoints(rays, np.zeros(3), np.zeros(3), c.K, c.D)
    expected_rays = np.c_[cv_rays, np.ones(len(cv_rays))]
    expected_rays /= np.linalg.norm(expected_rays, axis=1)[:, None]
    np.testing.assert_allclose(rays, expected_rays, atol=1e-8)
    np.testing.assert_allclose(uv, expected.reshape(-1, 2), atol=1e-8)


def test_pinhole_known_metric_fixture():
    c = camera("pinhole")
    uv, valid = c.project([[0, 0, 5], [1, 2, 10], [-2, -1, 5]])
    np.testing.assert_allclose(uv, [[159.5, 119.5], [174.5, 150.5], [99.5, 88.5]], atol=1e-12)
    assert valid.all()


def test_brown_conrady_against_explicit_equations():
    D = [.04, -.005, .001, -.002, .0003]
    c = camera("pinhole", D)
    p = np.array([[1, 2, 10], [-2, 1, 6], [3, -2, 8]], float)
    x, y = (p[:, :2] / p[:, 2:]).T
    r2 = x*x + y*y
    radial = 1 + D[0]*r2 + D[1]*r2*r2 + D[4]*r2*r2*r2
    xd = x*radial + 2*D[2]*x*y + D[3]*(r2 + 2*x*x)
    yd = y*radial + D[2]*(r2 + 2*y*y) + 2*D[3]*x*y
    expected = np.c_[150*xd+159.5, 155*yd+119.5]
    np.testing.assert_allclose(c.project(p)[0], expected, atol=1e-12)


def test_equidistant_fisheye_known_angle_fixture():
    c = camera("fisheye")
    theta = np.deg2rad(30)
    uv, _ = c.project([[np.sin(theta), 0, np.cos(theta)], [0, 0, 10]])
    np.testing.assert_allclose(uv, [[159.5 + 150*theta, 119.5], [159.5, 119.5]], atol=1e-12)


def test_declared_lidar_to_camera_ground_truth_projection():
    c = camera("pinhole")
    # Camera is 0.5 m left of L origin; world forward at L(5,0,0)
    # appears 0.5 m to the right of the camera's optical axis.
    points_C = apply(default_extrinsic([0, .5, 0]), [[5, 0, 0], [5, .5, 0]])
    uv, _ = c.project(points_C)
    np.testing.assert_allclose(uv, [[174.5, 119.5], [159.5, 119.5]], atol=1e-12)


@pytest.mark.parametrize("model", ["pinhole", "fisheye"])
def test_behind_camera_and_nonfinite_points_are_invalid(model):
    uv, valid = camera(model).project([[0, 0, -1], [0, 0, 0], [np.nan, 0, 5], [0, np.inf, 5]])
    assert not valid.any()
    assert np.isnan(uv).all()


@pytest.mark.parametrize("override", [
    {"model": "artistic"}, {"width": 0}, {"height": 1.5},
    {"K": [[np.nan, 0, 160], [0, 150, 120], [0, 0, 1]]},
    {"K": [[0, 0, 160], [0, 150, 120], [0, 0, 1]]},
    {"K": [[150, .1, 160], [0, 150, 120], [0, 0, 1]]},
    {"D": [np.inf, 0, 0, 0]}, {"D": [0, 0]}, {"D": [-1, 0, 0, 0]},
])
def test_invalid_camera_configuration_rejected(override):
    arguments = dict(model="fisheye", width=320, height=240,
                     K=[[150, 0, 160], [0, 150, 120], [0, 0, 1]], D=[0, 0, 0, 0])
    arguments.update(override)
    with pytest.raises(ValueError):
        Camera(**arguments)


def test_camera_json_round_trip():
    source = camera("fisheye", [.01, -.001, 0, 0])
    rebuilt = Camera.from_dict(source.to_dict())
    np.testing.assert_array_equal(source.pixel_rays(), rebuilt.pixel_rays())
