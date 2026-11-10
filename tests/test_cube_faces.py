"""Rendering only the cube faces a camera samples must give exactly the same image as rendering all six."""
import json
import subprocess

import cv2
import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from simulator import render
from simulator.camera import Camera
from simulator.pipeline import validate_config
from simulator.render import CUBE_FACES, cubemap_rgb, needed_faces, render_cubemap

SIZE = 64
UP = dict(px=((1, 0, 0), (0, -1, 0)), nx=((-1, 0, 0), (0, -1, 0)), py=((0, 1, 0), (0, 0, 1)),
          ny=((0, -1, 0), (0, 0, -1)), pz=((0, 0, 1), (0, -1, 0)), nz=((0, 0, -1), (0, -1, 0)))


def make_cubemap(directory, T_WC, faces=CUBE_FACES, seed=0):
    """Six random-textured 90-degree faces laid out exactly like blender/build_scene.py; only `faces` are written."""
    rng = np.random.default_rng(seed)
    directory.mkdir(parents=True, exist_ok=True)
    K = [[SIZE / 2, 0, (SIZE - 1) / 2], [0, SIZE / 2, (SIZE - 1) / 2], [0, 0, 1]]
    entries = []
    for name in CUBE_FACES:
        image = rng.integers(0, 256, (SIZE, SIZE, 3), dtype=np.uint8)   # drawn for every face so subsets stay comparable
        if name not in faces:
            continue
        f, u = (np.asarray(v, float) for v in UP[name])
        local = np.eye(4)
        local[:3, :3] = np.column_stack((np.cross(f, u), -u, f))
        cv2.imwrite(str(directory / f"cube_{name}.png"), image)
        entries.append(dict(name=name, T_WC=(T_WC @ local).tolist(), K=K, image=f"cube_{name}.png"))
    (directory / "cube_metadata.json").write_text(json.dumps(dict(faces=entries, size=SIZE)))
    return directory


def pose(seed):
    T = np.eye(4)
    T[:3, :3] = Rotation.random(random_state=seed).as_matrix()
    T[:3, 3] = [1., 2., 1.6]
    return T


CAMERAS = {
    "fisheye 4:3": Camera.from_dict(dict(model="fisheye", width=64, height=48, focal_px=26)),
    "fisheye distorted": Camera.from_dict(dict(model="fisheye", width=64, height=48, focal_px=26, D=[.02, -.005, 0, 0])),
    "fisheye very wide": Camera.from_dict(dict(model="fisheye", width=64, height=48, focal_px=10)),
    "pinhole narrow": Camera.from_dict(dict(model="pinhole", width=64, height=48, focal_px=26)),
    "pinhole wide": Camera.from_dict(dict(model="pinhole", width=64, height=48, focal_px=12)),
    "pinhole 16:9": Camera.from_dict(dict(model="pinhole", width=64, height=36, focal_px=40, D=[0, 0, 0, 0, 0])),
}


@pytest.mark.parametrize("name", CAMERAS)
@pytest.mark.parametrize("seed", [0, 1, 2])
def test_the_chosen_faces_give_the_identical_image(tmp_path, name, seed):
    camera, T = CAMERAS[name], pose(seed)
    faces = needed_faces(camera)
    full = cubemap_rgb(camera, T, make_cubemap(tmp_path / "all", T, seed=seed))
    subset = cubemap_rgb(camera, T, make_cubemap(tmp_path / "few", T, faces, seed=seed))
    assert np.array_equal(full, subset)


def test_how_many_faces_each_lens_needs():
    assert needed_faces(CAMERAS["pinhole narrow"]) == ["px", "nx", "pz"]
    assert set(needed_faces(CAMERAS["fisheye 4:3"])) == {"px", "nx", "py", "ny", "pz"}
    for camera in CAMERAS.values():
        assert "nz" not in needed_faces(camera)               # valid rays always point forward


def test_a_missing_needed_face_is_an_error_not_a_black_patch(tmp_path):
    camera, T = CAMERAS["fisheye 4:3"], pose(3)
    short = [f for f in needed_faces(camera) if f != "px"]
    with pytest.raises(ValueError, match="does not cover"):
        cubemap_rgb(camera, T, make_cubemap(tmp_path / "short", T, short))


def test_blender_is_asked_for_only_the_needed_faces(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    kwargs = dict(allow_render=True, allow_gpu=True, exist_ok=True)
    render_cubemap("blender", tmp_path / "s.blend", np.eye(4), tmp_path / "a", device="CPU", faces=["pz", "px", "nx"], **kwargs)
    render_cubemap("blender", tmp_path / "s.blend", np.eye(4), tmp_path / "b", device="CPU", faces=list(CUBE_FACES), **kwargs)
    render_cubemap("blender", tmp_path / "s.blend", np.eye(4), tmp_path / "c", device="CPU", **kwargs)
    assert calls[0][calls[0].index("--faces") + 1] == "pz,px,nx"
    assert "--faces" not in calls[1] and "--faces" not in calls[2]      # all six = the old command line


def test_cube_faces_setting_is_validated():
    base = dict(renderer="geometry")
    validate_config(dict(base, render=dict(cube_faces="all")))
    validate_config(dict(base, render=dict(cube_faces="auto")))
    with pytest.raises(ValueError, match="cube_faces"):
        validate_config(dict(base, render=dict(cube_faces="some")))
