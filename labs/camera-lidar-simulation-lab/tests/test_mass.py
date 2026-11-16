"""Mass capture planning: combinations, naming, validation, shared poses, drift pairs, resuming and the recorded intrinsics."""
import json

import pytest

from simulator import mass, studio

SCENES = ("warehouse", "laboratory", "urban", "corridor")
LIDARS = ("livox_avia", "livox_mid360", "velodyne_vlp16", "ouster_os1_64", "hesai_at128")


def spec(**changes):
    base = dict(scenes=["warehouse"], lidars=["livox_avia"], cameras=[dict(model="fisheye", resolutions=[[1024, 768]])], drift="off",
                batches=3, per_batch=2, rot=.5, trans=5, rig=[1.6, 0, 0], base_mount=[.05, -.15, .03, 0, 0, 0],
                base_focal=416, base_width=1024, renderer="blender", samples="32", cube_size="1024", duration="0.1", accumulate="1.0",
                stride="auto", interval="1", seed="42", pose_seed=None)
    return base | changes


def test_every_combination_is_planned_once_in_a_stable_order():
    params, combos = mass.parse_spec(spec(scenes=["urban", "warehouse"], lidars=["velodyne_vlp16", "livox_avia"], drift="both",
                                          cameras=[dict(model="fisheye", resolutions=[[1024, 768], [640, 480]]),
                                                   dict(model="pinhole", resolutions=[[1024, 768]])]), SCENES, LIDARS)
    assert len(combos) == 2 * 2 * 3 * 2
    assert len({c["name"] for c in combos}) == len(combos)
    assert [c["index"] for c in combos] == list(range(len(combos)))
    assert combos[0]["scene"] == "warehouse" and combos[0]["lidar"] == "livox_avia"      # application order, not click order
    assert combos[0]["name"] == "warehouse_avia_fish_1024x768_fixed_6" and combos[1]["name"] == "warehouse_avia_fish_1024x768_drift_6"
    assert params["batches"] == 3 and params["drift"] == "both" and params["captures"] == 6


def test_focal_length_keeps_the_field_of_view():
    _, combos = mass.parse_spec(spec(cameras=[dict(model="fisheye", resolutions=[[1024, 768], [640, 480]])]), SCENES, LIDARS)
    assert [c["camera"]["focal_px"] for c in combos] == [416.0, 260.0]


@pytest.mark.parametrize("changes, message", [
    (dict(scenes=[]), "environment"), (dict(lidars=[]), "LiDAR"), (dict(cameras=[]), "resolution"),
    (dict(scenes=["moon"]), "Unknown environment"), (dict(cameras=[dict(model="lomo", resolutions=[[10, 10]])]), "Unknown camera"),
    (dict(cameras=[dict(model="fisheye", resolutions=[[2000, 2000]])]), "not allowed"),
    (dict(drift="sometimes"), "drift"), (dict(drift="on", batches=1), "at least 2 batches"),
    (dict(batches=20, per_batch=6), "At most 100"), (dict(rot=11), "rotation"), (dict(base_mount=[0, 0, 0]), "mount"),
    (dict(distortion_delta=.01), "Distortion"), (dict(focal_percent=float("nan")), "Focal"), (dict(pose_seed=-5), "Pose seed")])
def test_bad_requests_say_what_is_wrong(changes, message):
    with pytest.raises(ValueError, match=message):
        mass.parse_spec(spec(**changes), SCENES, LIDARS)


def test_too_many_runs_are_refused():
    with pytest.raises(ValueError, match="too many"):
        mass.parse_spec(spec(scenes=list(SCENES), lidars=list(LIDARS), drift="both",
                             cameras=[dict(model=m, resolutions=[[w, 480] for w in range(100, 600, 100)]) for m in ("fisheye", "pinhole")]),
                        SCENES, LIDARS)


def test_a_save_folder_that_would_break_the_windows_path_limit_is_refused(tmp_path):
    _, combos = mass.parse_spec(spec(), SCENES, LIDARS)
    mass.check_paths(tmp_path, combos)
    with pytest.raises(ValueError, match="too long"):
        mass.check_paths(tmp_path / ("x" * 230), combos)


def test_poses_and_mount_changes_are_shared_and_drift_only_changes_intrinsics(monkeypatch):
    monkeypatch.setattr(studio, "random_poses", lambda name, n, *a, seed=0, **k: [[float(seed % 7), 0, 1.6, 0, 0, 0]] * n)
    params, combos = mass.parse_spec(spec(drift="both", lidars=["livox_avia", "hesai_at128"]), SCENES, LIDARS)
    plans = {c["name"]: mass.plan_combo(c, dict(params, focal_percent=.5, principal_px=1., distortion_delta=.0001)) for c in combos}
    fixed, drifting = plans["warehouse_avia_fish_1024x768_fixed_6"], plans["warehouse_avia_fish_1024x768_drift_6"]
    other = plans["warehouse_at128_fish_1024x768_fixed_6"]
    assert fixed["poses"] == drifting["poses"] == other["poses"]                        # same poses for every sensor
    assert fixed["mounts"] == drifting["mounts"] == other["mounts"]                     # same simulated mount changes
    assert fixed["batch_ids"] == [0, 0, 1, 1, 2, 2]
    assert len({json.dumps(c) for c in fixed["cameras"]}) == 1                          # drift off: nominal everywhere
    assert fixed["cameras"][0] == drifting["cameras"][0]                                # batch 1 stays nominal
    assert drifting["cameras"][2] != drifting["cameras"][0] and drifting["cameras"][4] != drifting["cameras"][2]
    assert [b["start"] for b in drifting["batches"]] == [0, 2, 4] and all(b["count"] == 2 for b in drifting["batches"])


def test_the_automatic_pose_seed_is_the_same_whenever_the_same_options_are_chosen():
    again = lambda **c: mass.parse_spec(spec(**c), SCENES, LIDARS)[0]  # noqa: E731
    assert again()["seed"] == again()["seed"] and again()["seed_auto"] is True
    assert again(batches=4)["seed"] != again()["seed"] and again(rot=1)["seed"] != again()["seed"]
    assert again(drift="both")["seed"] == again()["seed"]                              # drift settings never move the poses
    assert again(pose_seed=123)["seed"] == 123 and again(pose_seed=123)["seed_auto"] is False


def test_fingerprint_follows_what_changes_the_data():
    def fp(drift="off", **changes):
        params, combos = mass.parse_spec(spec(drift=drift, **changes), SCENES, LIDARS)
        return [mass.fingerprint(c, params, spec(drift=drift, **changes)) for c in combos]
    assert fp() == fp()
    assert fp()[0] != fp(samples="64")[0] and fp()[0] != fp(batches=4)[0] and fp()[0] != fp(scenes=["urban"])[0]
    both = fp("both")
    assert both[0] == fp()[0]                                                           # the fixed twin equals a plain fixed run
    assert both[1] != both[0] and both[1] != fp("both", focal_percent=1)[1] and both[0] == fp("both", focal_percent=1)[0]
    assert fp()[0] == fp(focal_percent=2)[0]                                            # drift limits are irrelevant when drift is off


def make_run(parent, name, fingerprint=None, finished=True):
    (parent / name / "evaluation").mkdir(parents=True)
    (parent / name / "inference").mkdir()
    if finished:
        (parent / name / "evaluation" / "manifest.json").write_text("{}")
    (parent / name / "evaluation" / "config.json").write_text(json.dumps(dict(mass=dict(fingerprint=fingerprint))))


def test_what_is_already_in_the_save_folder_is_recognised(tmp_path):
    assert mass.existing_status(tmp_path, "a", "fp") == "new"
    make_run(tmp_path, "done", "fp")
    make_run(tmp_path, "other", "different-fp")
    make_run(tmp_path, "partial", "fp", finished=False)
    (tmp_path / "plain" / "evaluation").mkdir(parents=True)
    (tmp_path / "plain" / "evaluation" / "manifest.json").write_text("{}")      # a finished run made without mass capture: no identity
    assert [mass.existing_status(tmp_path, n, "fp") for n in ("done", "other", "partial", "plain")] == ["done", "different", "incomplete", "different"]


def test_an_unfinished_attempt_is_moved_aside_never_deleted(tmp_path):
    make_run(tmp_path, "partial", "fp", finished=False)
    (tmp_path / "partial" / "inference" / "keep.txt").write_text("evidence")
    moved = mass.set_aside(tmp_path, "partial")
    assert not (tmp_path / "partial").exists() and moved.parent.name == mass.ASIDE and (moved / "inference" / "keep.txt").read_text() == "evidence"


def test_planning_marks_each_combination_with_its_status(tmp_path):
    first, combos = mass.plan_runs(spec(lidars=["livox_avia", "hesai_at128"]), SCENES, LIDARS, tmp_path)
    assert [c["status"] for c in combos] == ["new", "new"]
    make_run(tmp_path, combos[0]["name"], combos[0]["fingerprint"])
    _, again = mass.plan_runs(spec(lidars=["livox_avia", "hesai_at128"]), SCENES, LIDARS, tmp_path)
    assert [c["status"] for c in again] == ["done", "new"]
    _, changed = mass.plan_runs(spec(lidars=["livox_avia", "hesai_at128"], samples="64"), SCENES, LIDARS, tmp_path)
    assert [c["status"] for c in changed] == ["different", "new"]                       # same folder name, other settings: not reused


def test_summary_rows_and_the_per_run_csv_record_the_true_intrinsics(tmp_path):
    run = tmp_path / "run"
    (run / "evaluation").mkdir(parents=True)
    camera = dict(model="fisheye", width=32, height=24, K=[[20.1, 0, 16.7], [0, 19.9, 11.5], [0, 0, 1]], D=[1e-4, 0, 0, 0])
    (run / "evaluation" / "batches.json").write_text(json.dumps([
        dict(batch=0, capture_ids=["a", "b"], camera=camera, change_from_nominal=dict(rotation_deg=0, translation_mm=0, fx_percent=0, fy_percent=0, cx_px=0, cy_px=0, k1=0)),
        dict(batch=1, capture_ids=["c"], camera=camera, change_from_nominal=dict(rotation_deg=.4, translation_mm=5.2, fx_percent=.5, fy_percent=-.3, cx_px=.7, cy_px=0, k1=1e-4))]))
    rows = mass.summary_rows(run, "r1")
    assert [r["batch"] for r in rows] == [1, 2] and rows[1]["captures"] == 1 and rows[1]["fx"] == 20.1 and rows[1]["k1"] == 1e-4
    assert rows[1]["rotation_deg"] == .4 and rows[1]["fx_percent"] == .5
    assert mass.summary_rows(tmp_path / "missing", "x") == [] and mass.write_run_csv(tmp_path / "missing", "x") is None
    path = mass.write_run_csv(run, "r1")
    lines = path.read_text().splitlines()
    assert path == run / "evaluation" / "intrinsics_by_batch.csv" and lines[0].split(",") == mass.CSV_COLUMNS and len(lines) == 3
