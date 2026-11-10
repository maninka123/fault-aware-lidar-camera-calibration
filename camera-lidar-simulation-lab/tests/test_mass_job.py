"""The mass-capture job end to end on the real warehouse mesh, with the geometry renderer and in-process generation
(no GPU, no Blender, and no cross-process job lock, so it never collides with a real render)."""
import json
import sys
import time
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
pytestmark = pytest.mark.skipif(not (ROOT / "blender/scenes/warehouse/mesh.npz").is_file(), reason="warehouse mesh not built")

NAMES = ["warehouse_avia_fish_64x48_fixed_4", "warehouse_avia_fish_64x48_drift_4",
         "warehouse_vlp16_fish_64x48_fixed_4", "warehouse_vlp16_fish_64x48_drift_4"]


@pytest.fixture
def webui():
    import webui as module
    return module


def request(webui, folder, **changes):
    from launcher import default_values
    values = default_values()
    values.update(renderer="geometry", accumulate="0", duration="0.1", stride="80", scenes=["warehouse"],
                  lidars=["livox_avia", "velodyne_vlp16"], cameras=[dict(model="fisheye", resolutions=[[64, 48]])], drift="both",
                  focal_percent=.5, principal_px=1, distortion_delta=.0001, batches=2, per_batch=2, rot=.5, trans=5, pose_seed=None,
                  rig=[1.6, 0, 0], base_mount=[.05, -.15, .03, 0, 0, 0], base_focal=40, base_width=64, parent=str(folder))
    values.update(changes)
    return values


def wait(webui, seconds=240):
    end = time.time() + seconds
    while webui.JOB["running"] and time.time() < end:
        time.sleep(.2)
    assert not webui.JOB["running"], "the mass capture did not finish"


class Asked(list):
    """Run folders the generator was asked for, in order; .resumed says whether each was a continuation."""
    def __init__(self):
        super().__init__()
        self.resumed = []


def in_process(webui, monkeypatch, fail_on=None, leave_partial=False):
    """Generate in this process. Returns the list of run folders it was asked to produce, in order."""
    from simulator.pipeline import generate
    asked = Asked()

    def run(cmd):
        config = yaml.safe_load(Path(cmd[cmd.index("generate") + 1]).read_text(encoding="utf-8"))
        asked.append(Path(config["output"]).name)
        asked.resumed.append("--resume" in cmd)
        if fail_on and fail_on in config["output"]:
            webui.log("simulated failure")
            if leave_partial:                                        # what a crash half way through leaves behind
                (Path(config["output"]) / "inference").mkdir(parents=True)
            return 3
        generate(config, resume="--resume" in cmd)
        return 0
    monkeypatch.setattr(webui, "run_process", run)
    return asked


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def test_every_configuration_is_its_own_self_contained_folder(webui, monkeypatch, tmp_path):
    asked = in_process(webui, monkeypatch)
    webui.api_mass(request(webui, tmp_path))
    wait(webui)
    assert webui.JOB["code"] == 0 and webui.JOB["progress"] == 1.0 and webui.JOB["mass"]["active"] is False
    live = webui.JOB["mass"]["runs"]                                  # what the page lists: every configuration and its status
    assert [r["status"] for r in live] == ["done"] * 4 and all(r["seconds"] > 0 for r in live)
    assert live[0]["camera"]["width"] == 64 and live[1]["intrinsics_drift"] is True and live[2]["lidar"] == "velodyne_vlp16"
    assert asked == NAMES
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(NAMES)          # no wrapper folder, no index files beside them
    for n in NAMES:
        ev = tmp_path / n / "evaluation"
        assert (tmp_path / n / "inference").is_dir() and (ev / "nominal_calibration.json").is_file() and (ev / "manifest.json").is_file()
        assert read(ev / "config.json")["mass"]["name"] == n and read(ev / "config.json")["mass"]["fingerprint"]
        assert len((ev / "intrinsics_by_batch.csv").read_text(encoding="utf-8").splitlines()) == 1 + 2
    # the same poses for every sensor, and the drift pair differs only in intrinsics
    truth = {n: read(tmp_path / n / "evaluation/ground_truth.json") for n in NAMES}
    assert [t["T_WL"] for t in truth[NAMES[0]]] == [t["T_WL"] for t in truth[NAMES[1]]] == [t["T_WL"] for t in truth[NAMES[2]]]
    assert [t["T_CL"] for t in truth[NAMES[0]]] == [t["T_CL"] for t in truth[NAMES[1]]]
    fixed, drift = read(tmp_path / NAMES[0] / "evaluation/batches.json"), read(tmp_path / NAMES[1] / "evaluation/batches.json")
    assert fixed[1]["change_from_nominal"]["fx_percent"] == 0 and fixed[1]["change_from_nominal"]["cx_px"] == 0
    assert fixed[1]["change_from_nominal"]["translation_mm"] > 0                       # the mount still changed
    assert drift[0]["camera"] == fixed[0]["camera"] and drift[1]["camera"] != fixed[1]["camera"]
    assert abs(drift[1]["change_from_nominal"]["cx_px"]) > 0 or abs(drift[1]["change_from_nominal"]["fx_percent"]) > 0


def test_a_failed_run_does_not_stop_the_others(webui, monkeypatch, tmp_path):
    in_process(webui, monkeypatch, fail_on="vlp16_fish_64x48_fixed")
    webui.api_mass(request(webui, tmp_path))
    wait(webui)
    assert webui.JOB["code"] == 1
    runs = webui.JOB["mass"]["runs"]
    assert [r["status"] for r in runs] == ["done", "done", "failed", "done"]
    assert "exit code 3" in runs[2]["error"]


def test_running_again_in_the_same_folder_does_only_what_is_missing(webui, monkeypatch, tmp_path):
    in_process(webui, monkeypatch, fail_on="vlp16_fish_64x48_fixed", leave_partial=True)
    webui.api_mass(request(webui, tmp_path))
    wait(webui)
    assert (tmp_path / NAMES[2] / "inference").is_dir() and not (tmp_path / NAMES[2] / "evaluation").exists()   # the crash left a partial folder
    before = {n: (tmp_path / n / "evaluation/manifest.json").read_bytes() for n in (NAMES[0], NAMES[1], NAMES[3])}
    check = webui.api_mass_check(request(webui, tmp_path))
    assert (check["done"], check["incomplete"], check["new"], check["todo"], check["different"]) == (3, 1, 0, 1, 0)

    asked = in_process(webui, monkeypatch)                           # the problem is fixed; same options, same folder
    webui.api_mass(request(webui, tmp_path))
    wait(webui)
    assert webui.JOB["code"] == 0 and asked == [NAMES[2]]            # only the missing one was captured
    assert [r["status"] for r in webui.JOB["mass"]["runs"]] == ["skipped", "skipped", "done", "skipped"]
    assert webui.JOB["mass"]["total"] == 1
    assert {n: (tmp_path / n / "evaluation/manifest.json").read_bytes() for n in before} == before         # finished runs untouched
    assert (tmp_path / NAMES[2] / "evaluation/manifest.json").is_file()
    aside = list((tmp_path / "_incomplete").iterdir())               # the partial attempt was kept, not deleted
    assert len(aside) == 1 and aside[0].name.startswith(NAMES[2]) and (aside[0] / "inference").is_dir()
    with pytest.raises(ValueError, match="already saved"):           # and now there is nothing left to do
        webui.api_mass(request(webui, tmp_path))


def test_a_folder_with_the_same_name_but_other_settings_is_never_overwritten(webui, monkeypatch, tmp_path):
    asked = in_process(webui, monkeypatch)
    webui.api_mass(request(webui, tmp_path, lidars=["livox_avia"], drift="off"))
    wait(webui)
    first = (tmp_path / NAMES[0] / "evaluation/manifest.json").read_bytes()
    asked.clear()
    webui.api_mass(request(webui, tmp_path, lidars=["livox_avia", "velodyne_vlp16"], drift="off", samples="64"))   # other settings, same names
    wait(webui)
    assert asked == [NAMES[2]]                                       # the clash was left alone; only the new configuration ran
    assert [r["status"] for r in webui.JOB["mass"]["runs"]] == ["conflict", "done"]
    assert (tmp_path / NAMES[0] / "evaluation/manifest.json").read_bytes() == first


@pytest.mark.parametrize("changes, message", [(dict(parent="/no/such/folder"), "Choose the folder"), (dict(scenes=[]), "environment"),
                                              (dict(drift="on", batches=1), "at least 2 batches")])
def test_bad_mass_requests_start_nothing(webui, tmp_path, changes, message):
    with pytest.raises(ValueError, match=message):
        webui.api_mass(request(webui, tmp_path, **changes))
    assert not webui.JOB["running"] and list(tmp_path.iterdir()) == []


def test_unticking_skip_saves_new_copies_and_never_touches_the_existing_ones(webui, monkeypatch, tmp_path):
    asked = in_process(webui, monkeypatch)
    one = dict(lidars=["livox_avia"], drift="off")
    webui.api_mass(request(webui, tmp_path, **one))
    wait(webui)
    original = (tmp_path / NAMES[0] / "evaluation/manifest.json").read_bytes()
    asked.clear()
    check = webui.api_mass_check(request(webui, tmp_path, skip_existing=False, **one))
    assert (check["done"], check["copies"], check["todo"]) == (1, 1, 1)
    webui.api_mass(request(webui, tmp_path, skip_existing=False, **one))
    wait(webui)
    assert asked == [NAMES[0] + "_v2"] and (tmp_path / (NAMES[0] + "_v2") / "evaluation/manifest.json").is_file()
    assert (tmp_path / NAMES[0] / "evaluation/manifest.json").read_bytes() == original            # the original is untouched
    assert webui.JOB["mass"]["runs"][0]["name"] == NAMES[0] + "_v2" and webui.JOB["code"] == 0
    with pytest.raises(ValueError, match="already saved"):                                         # skip on: the original counts, so nothing is left
        webui.api_mass(request(webui, tmp_path, skip_existing=True, **one))


def test_scanning_a_folder_lists_what_is_saved(webui, monkeypatch, tmp_path):
    in_process(webui, monkeypatch)
    assert webui.api_mass_scan(dict(parent=str(tmp_path)))["runs"] == []
    webui.api_mass(request(webui, tmp_path))
    wait(webui)
    (tmp_path / "unfinished_run" / "evaluation").mkdir(parents=True)                               # a run that stopped after writing its config
    (tmp_path / "unfinished_run" / "evaluation" / "config.json").write_text(json.dumps(dict(scene="urban", lidar="livox_avia", captures=6)))
    (tmp_path / "notes").mkdir()                                                                   # not a run: ignored
    scan = webui.api_mass_scan(dict(parent=str(tmp_path)))
    by = {r["name"]: r for r in scan["runs"]}
    assert set(by) == set(NAMES) | {"unfinished_run"} and scan["finished"] == 4 and scan["unfinished"] == 1
    drifting, fixed = by[NAMES[1]], by[NAMES[0]]
    assert (drifting["drift"], drifting["batches"], drifting["per_batch"], drifting["finished"], drifting["from_mass"]) == (True, 2, 2, True, True)
    assert (fixed["drift"], fixed["model"], fixed["width"], fixed["height"], fixed["lidar"], fixed["scene"]) == (False, "fisheye", 64, 48, "livox_avia", "warehouse")
    assert by["unfinished_run"]["finished"] is False
    with pytest.raises(ValueError, match="Choose the folder"):
        webui.api_mass_scan(dict(parent=str(tmp_path / "missing")))


def make_stopped(parent, name):
    """Make a finished 4-capture run look like one cancelled after its second capture, as a stopped mass capture leaves it."""
    run = parent / name
    for rel in ("evaluation/manifest.json", "evaluation/ground_truth.json", "evaluation/events.json", "evaluation/batches.json",
                "inference/sequence.json", "evaluation/capture_0002/verification.json", "evaluation/capture_0003/verification.json",
                "inference/capture_0003/image.png"):
        (run / rel).unlink()


def test_an_unfinished_run_is_continued_from_where_it_stopped(webui, monkeypatch, tmp_path):
    asked = in_process(webui, monkeypatch)
    one = dict(lidars=["livox_avia"], drift="off")
    webui.api_mass(request(webui, tmp_path, **one))
    wait(webui)
    truth = read(tmp_path / NAMES[0] / "evaluation/ground_truth.json")
    kept = (tmp_path / NAMES[0] / "inference/capture_0000/image.png").read_bytes()
    make_stopped(tmp_path, NAMES[0])
    check = webui.api_mass_check(request(webui, tmp_path, **one))
    assert (check["incomplete"], check["continuing"], check["todo"], check["todo_captures"], check["kept_captures"]) == (1, 1, 1, 2, 2)
    assert check["unfinished"] == [dict(name=NAMES[0], done=2, total=4, will_continue=True)]
    asked.clear()
    asked.resumed.clear()
    webui.api_mass(request(webui, tmp_path, **one))
    wait(webui)
    assert webui.JOB["code"] == 0 and asked == [NAMES[0]] and asked.resumed == [True]
    assert not (tmp_path / "_incomplete").exists()                                  # nothing was set aside: it was continued in place
    assert read(tmp_path / NAMES[0] / "evaluation/ground_truth.json") == truth
    assert (tmp_path / NAMES[0] / "inference/capture_0000/image.png").read_bytes() == kept
    assert webui.JOB["mass"]["runs"][0]["verification_passed"] is True


def test_an_unfinished_run_can_be_redone_from_the_start_instead(webui, monkeypatch, tmp_path):
    asked = in_process(webui, monkeypatch)
    one = dict(lidars=["livox_avia"], drift="off")
    webui.api_mass(request(webui, tmp_path, **one))
    wait(webui)
    make_stopped(tmp_path, NAMES[0])
    check = webui.api_mass_check(request(webui, tmp_path, unfinished="redo", **one))
    assert (check["incomplete"], check["continuing"], check["todo_captures"]) == (1, 0, 4)
    asked.clear()
    asked.resumed.clear()
    webui.api_mass(request(webui, tmp_path, unfinished="redo", **one))
    wait(webui)
    assert webui.JOB["code"] == 0 and asked == [NAMES[0]] and asked.resumed == [False]
    aside = list((tmp_path / "_incomplete").iterdir())                              # the unfinished attempt is kept, not deleted
    assert len(aside) == 1 and aside[0].name.startswith(NAMES[0])
    assert (tmp_path / NAMES[0] / "evaluation/manifest.json").is_file()


def test_a_partial_run_made_with_other_settings_is_not_continued(webui, monkeypatch, tmp_path):
    asked = in_process(webui, monkeypatch)
    one = dict(lidars=["livox_avia"], drift="off")
    webui.api_mass(request(webui, tmp_path, **one))
    wait(webui)
    make_stopped(tmp_path, NAMES[0])
    check = webui.api_mass_check(request(webui, tmp_path, samples="64", **one))     # other settings, same folder name
    assert (check["incomplete"], check["continuing"], check["todo_captures"]) == (1, 0, 4)
    asked.clear()
    asked.resumed.clear()
    webui.api_mass(request(webui, tmp_path, samples="64", **one))
    wait(webui)
    assert asked.resumed == [False] and len(list((tmp_path / "_incomplete").iterdir())) == 1
