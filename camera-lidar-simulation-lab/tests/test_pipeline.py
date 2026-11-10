"""Tiny CPU-only fixtures exercise exported measurements and fault semantics."""
from copy import deepcopy
import numpy as np
import pytest
from simulator.pipeline import generate, validate_config
from simulator.validation import verify_run
from simulator.io import json_read
from simulator.evaluation import calibration_errors
from simulator.lidar import PROFILES


@pytest.fixture
def room_mesh(tmp_path):
    # Enclosed 12x12x6 metre room, rig at (0,0,1.6), ray-cast triangles only.
    v = np.array([[-6,-6,0],[6,-6,0],[6,6,0],[-6,6,0],
                  [-6,-6,6],[6,-6,6],[6,6,6],[-6,6,6]], np.float32)
    f = np.array([[0,1,2],[0,2,3],[4,6,5],[4,7,6],[0,4,5],[0,5,1],
                  [1,5,6],[1,6,2],[2,6,7],[2,7,3],[3,7,4],[3,4,0]], np.int32)
    p = tmp_path/"mesh.npz"
    np.savez(p, vertices=v, triangles=f, face_ids=np.arange(12), colors=np.tile([.5,.4,.3], (12,1)))
    return p


def config(mesh, out):
    return dict(mesh=str(mesh), output=str(out), renderer="geometry", lidar="livox_avia",
                camera=dict(model="fisheye",width=32,height=24,focal_px=20,D=[.02,-.005,0,0]),
                duration=.01, captures=1, interval=1., lidar_options=dict(stride=10),seed=14)


@pytest.mark.parametrize("sensor", PROFILES)
def test_five_sensors_export_reload_and_visibility(room_mesh, tmp_path, sensor):
    c = config(room_mesh, tmp_path/sensor)
    c["lidar"] = sensor
    # A full nominal frame is needed for scanners whose first milliseconds face away.
    c.update(duration=.1, lidar_options=dict(stride=100))
    out = generate(c)
    result = verify_run(out)
    assert result["passed"], result["errors"]
    assert result["captures"][0]["points"] > 0
    assert result["captures"][0]["visible_to_camera"] > 0


def test_initial_error_does_not_change_physical_measurements(room_mesh,tmp_path):
    a = config(room_mesh,tmp_path/"clean")
    b = deepcopy(a)
    b.update(output=str(tmp_path/"initial"), initial_fault=dict(rotation_deg=[1,2,3],translation_m=[.1,0,0]))
    ra, rb = generate(a), generate(b)
    for filename in ("image.png", "lidar.npz", "cloud.pcd"):
        assert (ra/"inference/capture_0000"/filename).read_bytes() == (rb/"inference/capture_0000"/filename).read_bytes()
    assert json_read(ra/"evaluation/ground_truth.json") == json_read(rb/"evaluation/ground_truth.json")
    assert json_read(ra/"inference/initial_calibration.json") != json_read(rb/"inference/initial_calibration.json")


def test_physical_change_updates_true_camera_and_preserves_initial_estimate(room_mesh,tmp_path):
    c = config(room_mesh,tmp_path/"drift")
    c.update(captures=3,events=[dict(time=1.,label="rotation",fault=dict(rotation_deg=[0,4,0]))])
    run = generate(c)
    truth = json_read(run/"evaluation/ground_truth.json")
    assert truth[0]["fault_label"] == "stable"
    assert truth[1]["fault_label"] == "rotation"
    assert not np.allclose(truth[0]["T_WC"],truth[1]["T_WC"])
    assert truth[0]["T_WL"] == truth[1]["T_WL"]
    initial = json_read(run/"inference/initial_calibration.json")
    assert initial["extrinsics"]["transform_lidar_to_camera"] == truth[0]["T_CL"]
    result = verify_run(run)
    assert result["passed"], result["errors"]


def test_seeded_noisy_measurements_are_reproducible(room_mesh,tmp_path):
    a = config(room_mesh,tmp_path/"noise_a")
    a.update(noise=dict(range_std_m=.02,angular_std_deg=.05,dropout=.1),camera_noise=dict(noise_std=3))
    b = deepcopy(a)
    b["output"] = str(tmp_path/"noise_b")
    ra, rb = generate(a), generate(b)
    with np.load(ra/"inference/capture_0000/lidar.npz") as x, np.load(rb/"inference/capture_0000/lidar.npz") as y:
        for key in x.files:
            np.testing.assert_array_equal(x[key],y[key])
    assert (ra/"inference/capture_0000/image.png").read_bytes() == (rb/"inference/capture_0000/image.png").read_bytes()


def test_true_estimate_has_zero_geometric_error(room_mesh,tmp_path):
    run = generate(config(room_mesh,tmp_path/"metrics"))
    t = json_read(run/"evaluation/ground_truth.json")[0]
    with np.load(run/"evaluation/capture_0000/ideal_lidar.npz") as d:
        result = calibration_errors(t["calibration"],t,d["xyz"])
    assert result["rotation_error_deg"] == 0
    assert result["translation_error_m"] == 0
    assert result["reprojection_rmse_px"] == 0


def test_blender_is_blocked_before_output_creation(room_mesh,tmp_path):
    c = config(room_mesh,tmp_path/"blocked")
    c["renderer"] = "blender"
    with pytest.raises(ValueError,match="disabled by default"):
        generate(c)
    assert not (tmp_path/"blocked").exists()


@pytest.mark.parametrize("bad", [{"duration":-1},{"captures":0},{"interval":float('nan')},
                               {"noise":{"dropout":1.1}},{"typo":1}])
def test_invalid_config(bad):
    with pytest.raises(ValueError):
        validate_config(bad)


def test_corrupted_sequence_is_reported_as_invalid(room_mesh,tmp_path):
    run=generate(config(room_mesh,tmp_path/"corrupt"))
    (run/"inference/sequence.json").write_bytes(b"\x00\x00")
    result=verify_run(run)
    assert not result["passed"]
    assert "Incomplete or invalid" in result["errors"][0]


def test_flat_layout_progress_and_legacy_reader(tmp_path, room_mesh):
    """Captures sit directly under inference/ and evaluation/, progress is monotonic, older runs stay readable."""
    from simulator.io import capture_dir
    steps = []
    c = dict(scene="warehouse", renderer="geometry", camera=dict(model="pinhole", width=32, height=24, focal_px=30),
             duration=.01, captures=2, interval=1., lidar_options=dict(stride=40), seed=3,
             output=str(tmp_path/"run"))
    c["mesh"] = str(room_mesh)
    run = generate(c, progress=lambda f, m: steps.append((f, m)))
    assert (run/"inference/capture_0000/image.png").is_file() and (run/"evaluation/capture_0001/ideal_lidar.npz").is_file()
    assert not (run/"inference/captures").exists() and not (run/"evaluation/captures").exists()
    fractions = [f for f, _ in steps]
    assert fractions == sorted(fractions) and fractions[0] == 0 and fractions[-1] == 1
    assert capture_dir(run, "evaluation", "capture_0000") == run/"evaluation/capture_0000"
    legacy = tmp_path/"old"/"evaluation"/"captures"/"capture_0000"
    legacy.mkdir(parents=True)
    assert capture_dir(tmp_path/"old", "evaluation", "capture_0000") == legacy


def test_accumulated_scan_saved_beside_snapshot(tmp_path, room_mesh):
    """A non-repetitive scanner integrated for 1 s covers more rays than the 0.1 s snapshot; both are saved."""
    c = dict(scene="warehouse", renderer="geometry", camera=dict(model="pinhole", width=32, height=24, focal_px=30),
             lidar="livox_avia", duration=.1, accumulate_s=1.0, captures=1, lidar_options=dict(stride=40), seed=5,
             output=str(tmp_path/"run"))
    c["mesh"] = str(room_mesh)
    run = generate(c)
    short = np.load(run/"inference/capture_0000/lidar.npz")["xyz"]
    long = np.load(run/"inference/capture_0000/lidar_accumulated.npz")["xyz"]
    assert len(long) > 5*len(short)
    assert (run/"inference/capture_0000/cloud_accumulated.pcd").is_file()
    assert (run/"evaluation/capture_0000/ideal_lidar_accumulated.npz").is_file()
    meta = json_read(run/"inference/capture_0000/lidar_metadata.json")
    assert meta["accumulated"]["duration_s"] == 1.0
    bad = dict(c, accumulate_s=0.05)
    with pytest.raises(ValueError):
        validate_config(bad)


def test_batches_carry_their_own_true_calibration(tmp_path, room_mesh):
    """Per-batch T_CL is ground truth; the initial estimate given to an algorithm stays the nominal mount."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    from launcher import default_values, make_config
    from simulator.geometry import camera_extrinsic
    v = default_values()
    v.update(output=str(tmp_path/"run"), renderer="geometry", width="32", height="24", focal="30", stride="40",
             accumulate="0", poses=[[1, 0, 1.6, 0, 0, 0], [2, 1, 1.6, 0, 0, 30], [3, -1, 1.6, 0, 0, 90]],
             mounts=[[.05, -.15, .03, 0, 0, 0], [.05, -.15, .03, 0, 0, 0], [.053, -.147, .028, .4, -.3, .6]],
             batch_ids=[0, 0, 1])
    config = make_config(v)
    config["mesh"] = str(room_mesh)
    run = generate(config)
    truth = json_read(run/"evaluation/ground_truth.json")
    assert [t["batch"] for t in truth] == [0, 0, 1]
    assert np.allclose(truth[2]["T_CL"], camera_extrinsic([.053, -.147, .028], [.4, -.3, .6]))
    assert np.allclose(truth[0]["T_CL"], truth[1]["T_CL"]) and not np.allclose(truth[0]["T_CL"], truth[2]["T_CL"])
    # the algorithm-facing initial calibration is the nominal one, not any batch's true value
    initial = json_read(run/"inference/initial_calibration.json")
    assert np.allclose(np.asarray(initial["extrinsics"]["transform_lidar_to_camera"]), camera_extrinsic([.05, -.15, .03], [0, 0, 0]))
    batches = json_read(run/"evaluation/batches.json")
    assert [b["capture_ids"] for b in batches] == [["capture_0000", "capture_0001"], ["capture_0002"]]
    assert all(b["same_calibration"] for b in batches)
    assert [s.get("batch") for s in json_read(run/"inference/sequence.json")] == [0, 0, 1]
    assert verify_run(run)["passed"]
    with pytest.raises(ValueError):
        validate_config(dict(config, batch_ids=[0, 1]))


def test_batch_plan_is_within_tolerance_and_batch_zero_is_nominal(monkeypatch):
    from simulator import studio
    from simulator.studio import batch_plan
    monkeypatch.setattr(studio, "random_poses", lambda name, n, *args, **kwargs: [[0, 0, 1.6, 0, 0, 0]] * n)
    base = [0.05, -0.15, 0.03, 0, 0, 0]
    plan = batch_plan("warehouse", 4, 3, tol_rot_deg=0.5, tol_trans_mm=5, base_mount=base, seed=2)
    assert plan[0]["mount"] == base and all(len(b["poses"]) == 3 for b in plan)
    for b in plan[1:]:
        d = np.asarray(b["mount"]) - np.asarray(base)
        assert np.all(np.abs(d[:3]) <= 0.005 + 1e-4) and np.all(np.abs(d[3:]) <= 0.5 + 1e-3)
    assert len({tuple(b["mount"]) for b in plan}) == 4            # batches differ from one another
    with pytest.raises(ValueError):
        batch_plan("warehouse", 11, 10, 0.5, 5, base)             # more than 100 captures in total


def test_batch_intrinsics_are_bounded_seeded_and_independent(monkeypatch):
    from simulator import studio
    from simulator.camera import Camera
    monkeypatch.setattr(studio, "random_poses", lambda name, n, *args, **kwargs: [[0, 0, 1.6, 0, 0, 0]] * n)
    cam = dict(model="fisheye", width=32, height=24, focal_px=20, D=[0., 0., 0., 0.])
    args = ("warehouse", 4, 2, .5, 5, [.05, -.15, .03, 0, 0, 0])
    options = dict(camera_cfg=cam, vary_intrinsics=True, focal_percent=.5, principal_px=1., distortion_delta=.0001, seed=7)
    plan = studio.batch_plan(*args, **options)
    assert plan == studio.batch_plan(*args, **options)
    baseline = Camera.from_dict(cam).to_dict()
    assert plan[0]["camera"] == baseline
    unchanged = studio.batch_plan(*args, camera_cfg=cam, seed=7)
    assert all(b["camera"] == baseline for b in unchanged)
    assert [b["mount"] for b in plan] == [b["mount"] for b in unchanged]
    for b in plan[1:]:
        K, D = np.array(b["camera"]["K"]), np.array(b["camera"]["D"])
        assert np.all(np.abs(K[[0, 1], [0, 1]] / 20 - 1) <= .005)
        assert np.all(np.abs(K[:2, 2] - np.array(baseline["K"])[:2, 2]) <= 1)
        assert abs(D[0]) <= .0001 and np.all(D[1:] == 0)
        assert b["camera"] != baseline
    fixed_mount = studio.batch_plan("warehouse", 3, 2, 0, 0, args[-1], **options)
    assert all(b["mount"] == fixed_mount[0]["mount"] for b in fixed_mount)
    assert fixed_mount[1]["camera"] != fixed_mount[0]["camera"]
    for bad in (dict(focal_percent=float("nan")), dict(principal_px=-1), dict(distortion_delta=.01)):
        with pytest.raises(ValueError, match="Intrinsics limits"):
            studio.batch_plan(*args, **(options | bad))


def test_batch_intrinsics_change_measurements_and_save_truth(room_mesh, tmp_path):
    import sys
    from pathlib import Path
    from simulator.camera import Camera
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    from launcher import default_values, make_config
    nominal = Camera.from_dict(dict(width=32, height=24, focal_px=20)).to_dict()
    changed = deepcopy(nominal)
    changed["K"][0][0] *= 1.005
    changed["K"][1][1] *= .997
    changed["K"][0][2] += .7
    changed["D"][0] = .0001
    values = default_values()
    values.update(output=str(tmp_path/"batch_intrinsics"), renderer="geometry", width="32", height="24", focal="20",
                  accumulate="0", duration="0.01", stride="10", poses=[[0, 0, 1.6, 0, 0, 0]] * 3,
                  cameras=[nominal, nominal, changed], batch_ids=[0, 0, 1])
    c = make_config(values)
    c["mesh"] = str(room_mesh)
    run = generate(c)
    truth = json_read(run/"evaluation/ground_truth.json")
    assert [t["camera"] for t in truth] == [nominal, nominal, changed]
    assert all(t["T_CL"] == truth[0]["T_CL"] for t in truth)
    initial = json_read(run/"inference/initial_calibration.json")["intrinsics"]
    assert initial["camera_matrix"] == nominal["K"]
    assert initial["distortion_coefficients"] == nominal["D"]
    batches = json_read(run/"evaluation/batches.json")
    assert [b["camera"] for b in batches] == [nominal, changed]
    assert all(b["same_calibration"] for b in batches)
    # the drift is recorded relative to the nominal calibration, which is also saved
    nominal_saved = json_read(run/"evaluation/nominal_calibration.json")
    assert nominal_saved["camera"] == nominal and np.allclose(nominal_saved["T_CL"], truth[0]["T_CL"])
    assert batches[0]["change_from_nominal"] == dict(rotation_deg=0, translation_mm=0, fx_percent=0, fy_percent=0, cx_px=0, cy_px=0, k1=0)
    change = batches[1]["change_from_nominal"]
    assert change["fx_percent"] == pytest.approx(.5) and change["fy_percent"] == pytest.approx(-.3)
    assert change["cx_px"] == pytest.approx(.7) and change["cy_px"] == pytest.approx(0) and change["k1"] == pytest.approx(1e-4)
    assert change["rotation_deg"] == pytest.approx(0) and change["translation_mm"] == pytest.approx(0)
    assert (run/"inference/capture_0000/image.png").read_bytes() == (run/"inference/capture_0001/image.png").read_bytes()
    assert (run/"inference/capture_0000/image.png").read_bytes() != (run/"inference/capture_0002/image.png").read_bytes()
    assert verify_run(run)["passed"]
    with pytest.raises(ValueError, match="every capture"):
        validate_config(c | dict(cameras=[nominal]))
    bad = deepcopy(changed)
    bad["width"] = 33
    with pytest.raises(ValueError, match="model and image dimensions"):
        validate_config(c | dict(cameras=[nominal, nominal, bad]))


def test_a_stopped_run_continues_and_equals_an_uninterrupted_one(room_mesh, tmp_path):
    import shutil
    c = config(room_mesh, tmp_path/"full")
    c.update(captures=3)
    full = generate(deepcopy(c))
    part = tmp_path/"part"
    shutil.copytree(full, part)
    # what a stop leaves behind: no summary files, and capture 2 cut off before the last file a capture writes
    for rel in ("evaluation/manifest.json", "evaluation/ground_truth.json", "evaluation/events.json", "inference/sequence.json",
                "evaluation/capture_0002/verification.json", "inference/capture_0002/image.png"):
        (part/rel).unlink()
    watched = ("inference/capture_0000/image.png", "inference/capture_0001/lidar.npz", "evaluation/capture_0001/verification.json")
    before = {rel: (part/rel).read_bytes() for rel in watched}
    c2 = deepcopy(c)
    c2["output"] = str(part)
    said = []
    out = generate(c2, resume=True, report=said.append)
    assert out == part and verify_run(part)["passed"]
    assert {rel: (part/rel).read_bytes() for rel in watched} == before                    # finished captures were not touched
    assert sum("already complete" in t for t in said) == 2
    for name in ("evaluation/ground_truth.json", "inference/sequence.json"):
        assert json_read(part/name) == json_read(full/name)
    assert (part/"inference/capture_0002/image.png").read_bytes() == (full/"inference/capture_0002/image.png").read_bytes()
    a, b = json_read(full/"evaluation/manifest.json"), json_read(part/"evaluation/manifest.json")
    assert b["resumed_captures_kept"] == 2 and [x["valid_returns"] for x in b["captures"]] == [x["valid_returns"] for x in a["captures"]]
    with pytest.raises(ValueError, match="already finished"):
        generate(deepcopy(c2), resume=True)


def test_a_run_cannot_be_continued_with_other_settings_or_from_nothing(room_mesh, tmp_path):
    import shutil
    c = config(room_mesh, tmp_path/"full")
    c.update(captures=2)
    full = generate(deepcopy(c))
    part = tmp_path/"part"
    shutil.copytree(full, part)
    (part/"evaluation/manifest.json").unlink()
    other = deepcopy(c)
    other.update(output=str(part), lidar="velodyne_vlp16")
    with pytest.raises(ValueError, match="different settings"):
        generate(other, resume=True)
    with pytest.raises(ValueError, match="Nothing to continue"):
        generate(dict(deepcopy(c), output=str(tmp_path/"nothing_here")), resume=True)
