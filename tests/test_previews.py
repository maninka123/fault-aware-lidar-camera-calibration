import numpy as np
import pytest

from simulator.gpu import best_device
from simulator.lidar import PROFILES
from simulator.previews import camera_preview, lidar_preview


@pytest.mark.parametrize("profile", PROFILES)
def test_lidar_preview_draws_points(profile):
    img = lidar_preview(profile, (200, 140))
    assert img.size == (200, 140)
    # more than background + grid colours: scan points were drawn
    assert len(np.unique(np.asarray(img).reshape(-1, 3), axis=0)) > 10


def test_camera_preview_fov_matches_model():
    _, fisheye = camera_preview("fisheye", 320, 240, 130)
    _, pinhole = camera_preview("pinhole", 320, 240, 130)
    assert fisheye["h_fov"] > pinhole["h_fov"]
    # pinhole: horizontal FOV = 2*atan((w-1)/2 / f)
    assert pinhole["h_fov"] == pytest.approx(np.degrees(2 * np.arctan(159.5 / 130)), abs=0.5)


def test_best_device_prefers_optix_and_never_invents_gpu():
    assert best_device({"devices": {"OPTIX": ["x"], "CUDA": ["x"]}}) == "OPTIX"
    assert best_device({"devices": {"OPTIX": "error: no", "CUDA": ["x"]}}) == "CUDA"
    assert best_device({"devices": {"OPTIX": [], "CUDA": []}}) == "CPU"


def test_camera_extrinsic_default_and_relative_yaw():
    from simulator.geometry import R_LC, apply, camera_extrinsic, default_extrinsic, inverse
    assert np.allclose(camera_extrinsic(), default_extrinsic())
    # +yaw about LiDAR z turns the camera left: its optical axis (L-frame) rotates from +x toward +y.
    T_LC = inverse(camera_extrinsic((0, 0, 0), (0, 0, 90)))
    axis_in_L = T_LC[:3, :3] @ np.array([0, 0, 1.0])
    assert np.allclose(axis_in_L, [0, 1, 0], atol=1e-12)
    assert np.allclose(camera_extrinsic((0.1, 0.2, 0.3))[:3, :3], R_LC.T)


def test_make_config_uses_placed_poses_and_relative_mount(tmp_path):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    from launcher import default_values, make_config
    from simulator.geometry import camera_extrinsic
    v = default_values()
    v.update(output=str(tmp_path / "run"), cam_xyz="0.1, 0.05, 0.08", cam_rpy="2, -3, 5",
             poses=[[1, 0.5, 1.5, 0, 0, 10], [3, -1, 1.2, 1, 2, -40]])
    c = make_config(v)
    assert c["captures"] == 2 and len(c["poses"]) == 2
    assert np.allclose(np.array(c["poses"][0])[:3, 3], [1, 0.5, 1.5])
    assert np.allclose(c["T_CL"], camera_extrinsic([0.1, 0.05, 0.08], [2, -3, 5]))


@pytest.mark.parametrize("profile", PROFILES)
def test_default_settings_are_valid_for_every_lidar(tmp_path, profile):
    """Out-of-the-box GUI values (auto stride, 1 s accumulation) must pass validation for each LiDAR."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    from launcher import default_values, make_config
    v = default_values()
    v.update(lidar=profile, output=str(tmp_path / "run"))
    c = make_config(v)
    assert c["accumulate_s"] == 1.0 and c["lidar_options"]["stride"] >= 1
    assert c["camera"]["width"] * c["camera"]["height"] <= 1048576


@pytest.mark.parametrize("scene", ["warehouse", "laboratory", "urban", "corridor"])
def test_random_poses_are_valid_distinct_and_reproducible(scene):
    from simulator.studio import _scene, random_poses
    a = random_poses(scene, 6, z=1.6, seed=11)
    assert a == random_poses(scene, 6, z=1.6, seed=11)            # same seed, same poses
    assert a != random_poses(scene, 6, z=1.6, seed=12)
    assert len(a) == 6 and all(len(p) == 6 and p[2] == 1.6 for p in a)
    mesh, (x0, x1, y0, y1, _) = _scene(scene)
    assert all(x0 <= p[0] <= x1 and y0 <= p[1] <= y1 for p in a)
    # never inside an object: floor directly below, and no surface within 0.8 m horizontally
    for p in a:
        down = mesh.cast(np.array([p[0], p[1], p[2]]), np.array([0., 0., -1.]))
        assert down["valid"][0] and abs(p[2] - down["ranges"][0]) <= 0.25
    with pytest.raises(ValueError):
        random_poses(scene, 0)
    with pytest.raises(ValueError):
        random_poses(scene, 51)


@pytest.mark.parametrize("scene", ["warehouse", "laboratory", "corridor"])
def test_random_poses_face_real_surfaces_not_the_void(scene):
    import numpy as np
    from simulator.studio import _scene, random_poses
    mesh, _ = _scene(scene)
    for p in random_poses(scene, 20, seed=5):
        yaw = np.deg2rad(p[5])
        hit = mesh.cast(np.array(p[:3]), np.array([np.cos(yaw), np.sin(yaw), 0.0]))
        assert hit["valid"][0] and hit["ranges"][0] >= 2.5   # 15-degree grid + up to 7.5 deg jitter


def test_run_name_is_environment_date_time_captures(tmp_path):
    import sys
    from datetime import datetime
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    from launcher import new_output, run_name
    assert run_name("warehouse", 5, datetime(2026, 11, 6, 22, 52, 42)) == "warehouse_20261106_225242_05"
    assert run_name("urban", 120, datetime(2026, 1, 2, 3, 4, 5)) == "urban_20260102_030405_120"
    first = new_output(tmp_path, "laboratory", 3)
    assert first.name.startswith("laboratory_") and first.name.endswith("_03")
    first.mkdir()
    again = new_output(tmp_path, "laboratory", 3)          # same second: still unique, still ends with the count
    assert again != first and again.name.endswith("_03") and not again.exists()


@pytest.mark.parametrize("key,bad,fragment", [
    ("captures", "abc", "Captures must be a whole number"),
    ("captures", "2.5", "Captures must be a whole number"),
    ("width", "wide", "Image width must be a whole number"),
    ("focal", "nan", "Focal length must be a finite number"),
    ("accumulate", "x", "Accumulated scan must be a number"),
    ("stride", "abc", "Beam stride must be a whole number"),
    ("output", "   ", "Choose an output folder"),
])
def test_bad_settings_give_readable_messages(tmp_path, key, bad, fragment):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    from launcher import default_values, make_config
    v = default_values()
    v.update(output=str(tmp_path / "run"))
    v[key] = bad
    with pytest.raises(ValueError, match=fragment):
        make_config(v)


def test_blank_accumulate_means_off_and_missing_key_is_named():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    from launcher import default_values, make_config
    import webui
    v = default_values()
    v.update(output="x", accumulate="")
    assert "accumulate_s" not in make_config(v)
    assert webui.describe(KeyError("seed")) == "Missing setting: seed"
    assert webui.describe(ValueError("plain")) == "plain"


def test_batch_api_previews_use_each_batch_camera(monkeypatch):
    import json
    import sys
    import threading
    from pathlib import Path
    from urllib.parse import urlencode
    from urllib.request import urlopen
    from PIL import Image
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    import webui
    seen = []
    monkeypatch.setattr(webui.studio, "random_poses", lambda name, n, *args, **kw: [[0, 0, 1.6, 0, 0, 0]] * n)
    def preview(name, lidar, camera, *args, **kwargs):
        seen.append(camera)
        return dict(image=Image.new("RGB", (2, 2)))
    monkeypatch.setattr(webui.studio, "pose_view", preview)
    server = webui.ThreadingHTTPServer(("127.0.0.1", 0), webui.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        params = dict(scene="warehouse", lidar="livox_avia", model="fisheye", w=32, h=24, f=20, z=1.6,
                      batches=2, per=2, rot=0, trans=0, seed=42, cxyz="0.05,-0.15,0.03", crpy="0,0,0",
                      intrinsics=1, focal_percent=.3, principal_px=.5, distortion_delta=.0001)
        with urlopen(f"http://127.0.0.1:{server.server_port}/api/studio/batches?{urlencode(params)}") as response:
            batches = json.load(response)["batches"]
        assert batches[0]["camera"] != batches[1]["camera"]
        assert seen == [batches[0]["camera"]] * 2 + [batches[1]["camera"]] * 2
        assert all(p["thumb"].startswith("data:image/png;base64,") for b in batches for p in b["poses"])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
