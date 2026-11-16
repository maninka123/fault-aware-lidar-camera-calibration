"""CPU Open3D analytical geometry and independent-viewpoint fixtures (A/C/G)."""
import numpy as np
import pytest

from simulator.camera import Camera
from simulator.geometry import apply, default_extrinsic, inverse
from simulator.raycast import MeshScene


def fixture_mesh(tmp_path, planes):
    vertices, triangles, face_ids, colors = [], [], [], []
    for x, ymin, ymax, zmin, zmax, object_id in planes:
        k = len(vertices)
        vertices.extend([[x, ymin, zmin], [x, ymax, zmin], [x, ymax, zmax], [x, ymin, zmax]])
        triangles.extend([[k, k+1, k+2], [k, k+2, k+3]])
        face_ids.extend([object_id, object_id])
        colors.extend([[.3, .4, .5], [.3, .4, .5]])
    path = tmp_path / "fixture_mesh.npz"
    np.savez(path, vertices=np.array(vertices), triangles=np.array(triangles),
             face_ids=np.array(face_ids), colors=np.array(colors))
    return MeshScene(path)


def test_known_plane_intersection_range_coordinates_and_semantics(tmp_path):
    scene = fixture_mesh(tmp_path, [(5, -10, 10, -10, 10, 42)])
    target = np.array([[5, 0, 0], [5, 3, 4], [5, -1, -2]], float)
    expected = np.linalg.norm(target, axis=1)
    directions = target / expected[:, None]
    result = scene.cast([0, 0, 0], directions, chunk_size=1)
    assert result["valid"].all()
    np.testing.assert_allclose(result["ranges"], expected, atol=2e-6)
    np.testing.assert_allclose(result["ranges"][:, None] * directions, target, atol=2e-6)
    np.testing.assert_array_equal(result["object_ids"], [42, 42, 42])
    np.testing.assert_allclose(result["colors"], [[.3, .4, .5]] * 3, atol=1e-7)
    np.testing.assert_allclose(np.abs(result["normals"]), [[1, 0, 0]] * 3)
    assert "CPU:0" in scene.backend
    full = scene.cast([0, 0, 0], directions)
    for key in ("ranges", "normals", "triangle_ids", "object_ids", "colors", "valid"):
        np.testing.assert_array_equal(result[key], full[key])


def test_parallel_ray_misses_are_explicit(tmp_path):
    scene = fixture_mesh(tmp_path, [(5, -10, 10, -10, 10, 42)])
    result = scene.cast([0, 0, 0], [[0, 1, 0]])
    assert not result["valid"][0]
    assert np.isinf(result["ranges"][0])
    assert result["object_ids"][0] == -1


def test_independent_camera_lidar_origins_have_different_occlusion(tmp_path):
    scene = fixture_mesh(tmp_path, [(2, -.5, .5, -1, 1, 10), (5, -5, 5, -5, 5, 20)])
    target = np.array([5, 0, 0], float)
    lidar_origin = np.array([0, 0, 0], float)
    camera_origin = np.array([0, 2, 0], float)
    lidar_ray = (target-lidar_origin)/np.linalg.norm(target-lidar_origin)
    camera_ray = (target-camera_origin)/np.linalg.norm(target-camera_origin)
    lidar = scene.cast(lidar_origin, [lidar_ray])
    camera = scene.cast(camera_origin, [camera_ray])
    assert lidar["object_ids"][0] == 10  # foreground blocks LiDAR
    assert camera["object_ids"][0] == 20  # camera sees background target
    np.testing.assert_allclose(lidar["ranges"], [2], atol=1e-6)
    np.testing.assert_allclose(camera_origin + camera["ranges"][0]*camera_ray, target, atol=1e-6)


@pytest.mark.parametrize("model", ["pinhole", "fisheye"])
def test_camera_ray_intersections_reproject_under_exact_extrinsic(tmp_path, model):
    scene = fixture_mesh(tmp_path, [(5, -100, 100, -100, 100, 42)])
    camera = Camera.from_dict(dict(model=model, width=320, height=240, focal_px=150, D=[.01, -.001, 0, 0]))
    T_CL = default_extrinsic([.05, -.15, .03])
    T_LC = inverse(T_CL)
    pixels = np.array([[30, 25], [100, 90], [159, 119], [280, 210]], float)
    rays_C = camera.unproject(pixels)
    rays_L = rays_C @ T_LC[:3, :3].T
    origins = T_LC[:3, 3]
    result = scene.cast(origins, rays_L)
    assert result["valid"].all()
    hits_L = origins + result["ranges"][:, None]*rays_L
    uv, _ = camera.project(apply(T_CL, hits_L))
    np.testing.assert_allclose(uv, pixels, atol=1e-7)
    np.testing.assert_allclose(hits_L[:, 0], 5, atol=3e-6)


@pytest.mark.parametrize("origin,direction", [([np.nan, 0, 0], [1, 0, 0]),
    ([0, 0, 0], [np.inf, 0, 0]), ([0, 0, 0], [2, 0, 0]), ([0, 0, 0], [0, 0, 0])])
def test_invalid_ray_rejected(tmp_path, origin, direction):
    scene = fixture_mesh(tmp_path, [(5, -1, 1, -1, 1, 42)])
    with pytest.raises(ValueError):
        scene.cast(origin, [direction])
