import numpy as np
import pytest
import importlib.util
from pathlib import Path
import shutil

from simulator.lidar import PROFILES, LidarModel, generate_rays


@pytest.mark.parametrize("profile", PROFILES)
def test_unit_vectors_time_window_and_repeatability(profile):
    a = generate_rays(profile, .123, .041, {"stride": 7})
    b = generate_rays(profile, .123, .041, {"stride": 7})
    assert a["directions"].shape == (len(a["timestamps"]), 3)
    assert len(a["timestamps"]) > 100
    np.testing.assert_allclose(np.linalg.norm(a["directions"], axis=1), 1, atol=1e-14)
    assert np.all(a["timestamps"] >= .123)
    assert np.all(a["timestamps"] < .164)
    assert np.all(np.diff(a["timestamps"]) > 0)
    for key in ("directions", "timestamps", "channel", "beam_id"):
        np.testing.assert_array_equal(a[key], b[key])


@pytest.mark.parametrize("profile", PROFILES)
def test_accumulation_is_union_of_adjacent_windows(profile):
    whole = generate_rays(profile, 0, .1, {"stride": 13})
    first = generate_rays(profile, 0, .037, {"stride": 13})
    second = generate_rays(profile, .037, .063, {"stride": 13})
    for key in ("directions", "timestamps", "channel", "beam_id"):
        np.testing.assert_array_equal(whole[key], np.concatenate([first[key], second[key]]))


@pytest.mark.parametrize("profile", PROFILES)
def test_stride_retains_absolute_beam_schedule(profile):
    all_rays = generate_rays(profile, .001, .003)
    sampled = generate_rays(profile, .001, .003, {"stride": 11})
    mask = all_rays["beam_id"] % 11 == 0
    np.testing.assert_array_equal(sampled["beam_id"], all_rays["beam_id"][mask])
    np.testing.assert_array_equal(sampled["directions"], all_rays["directions"][mask])
    np.testing.assert_array_equal(sampled["timestamps"], all_rays["timestamps"][mask])


def test_avia_reference_fov_rate_replay_and_channel_unknown():
    rays = generate_rays("livox_avia", 0, .1)
    assert len(rays["timestamps"]) == 24000
    assert rays["metadata"]["pattern_period_s"] == 4
    np.testing.assert_array_equal(rays["channel"], -np.ones(24000))
    az = np.rad2deg(np.arctan2(rays["directions"][:, 1], rays["directions"][:, 0]))
    el = np.rad2deg(np.arcsin(rays["directions"][:, 2]))
    assert -35.4 < az.min() < -30 and 30 < az.max() < 35.4
    assert -38.7 < el.min() < -30 and 30 < el.max() < 38.7
    np.testing.assert_allclose([az[0], el[0]], [-35.27109427, -2.24293826], atol=1e-10)
    later = generate_rays("livox_avia", 4, .1)
    np.testing.assert_array_equal(rays["directions"], later["directions"])
    assert not np.array_equal(rays["directions"], generate_rays("livox_avia", .1, .1)["directions"])


def test_mid360_reference_timing_coverage_and_limits():
    rays = generate_rays("livox_mid360", 0, .1)
    assert len(rays["timestamps"]) == 20000
    assert rays["metadata"]["pattern_rows"] == 800000
    assert "integer row counter" in rays["metadata"]["timing_limitation"]
    az = np.rad2deg(np.arctan2(rays["directions"][:, 1], rays["directions"][:, 0]))
    el = np.rad2deg(np.arcsin(rays["directions"][:, 2]))
    assert np.ptp(az) > 359
    assert -7.3 < el.min() < -6 and 50 < el.max() < 52.3
    assert rays["metadata"]["range_min_m"] == .1


def test_vlp16_published_channel_table_and_firing_timing():
    rays = generate_rays("velodyne_vlp16", 0, 55.296e-6 * 2)
    assert len(rays["timestamps"]) == 32
    expected = np.array([-15, 1, -13, 3, -11, 5, -9, 7, -7, 9, -5, 11, -3, 13, -1, 15])
    np.testing.assert_allclose(np.rad2deg(np.arcsin(rays["directions"][:16, 2])), expected, atol=1e-12)
    np.testing.assert_allclose(rays["timestamps"][:16], np.arange(16) * 2.304e-6, atol=1e-15)
    assert rays["timestamps"][16] == 55.296e-6
    assert rays["timestamps"][16] - rays["timestamps"][15] > 18e-6
    az = np.unwrap(np.arctan2(rays["directions"][:, 1], rays["directions"][:, 0]))
    np.testing.assert_allclose(az, rays["timestamps"] * 20 * np.pi, atol=1e-14)


def test_os1_64_configuration_and_nominal_elevations():
    rays = generate_rays("ouster_os1_64", 0, .1)
    assert len(rays["timestamps"]) == 64 * 1024
    np.testing.assert_allclose(np.rad2deg(np.arcsin(rays["directions"][:64, 2])), np.linspace(-22.5, 22.5, 64))
    assert rays["metadata"]["fidelity"] == "nominal_specification_approximation"
    assert len(generate_rays("ouster_os1_64", 0, .1, {"columns_per_rotation": 512})["timestamps"]) == 32768


def test_hesai_at128_lattice_rate_and_forward_coverage():
    rays = generate_rays("hesai_at128", 0, .1)
    assert len(rays["timestamps"]) == 153600
    np.testing.assert_allclose(np.rad2deg(np.arcsin(rays["directions"][:128, 2])), np.linspace(-12.5, 12.9, 128))
    az = np.rad2deg(np.arctan2(rays["directions"][:, 1], rays["directions"][:, 0]))
    assert np.isclose(az.min(), -60) and np.isclose(az.max(), 59.9)
    assert np.all(rays["directions"][:, 0] > 0)
    fast = generate_rays("hesai_at128", 0, .05, {"rotation_hz": 20})
    assert len(fast["timestamps"]) == 76800
    assert fast["metadata"]["columns_per_rotation"] == 600


@pytest.mark.parametrize("start,duration", [(-1, .1), (0, 0), (0, -1), (np.nan, .1), (0, np.inf), (1e10, .1)])
def test_invalid_windows_rejected(start, duration):
    with pytest.raises(ValueError):
        generate_rays("velodyne_vlp16", start, duration)


@pytest.mark.parametrize("profile,options", [
    ("livox_avia", {"scan_mode": "repetitive"}),
    ("livox_avia", {"stride": 0}),
    ("livox_avia", {"stride": 1.5}),
    ("livox_avia", {"stride": True}),
    ("livox_avia", {"unimplemented_option": 1}),
    ("velodyne_vlp16", {"rotation_hz": 21}),
    ("ouster_os1_64", {"rotation_hz": 20, "columns_per_rotation": 2048}),
    ("ouster_os1_64", {"beam_elevations_deg": [1, 2]}),
    ("hesai_at128", {"rotation_hz": 15}),
    ("hesai_at128", {"scan_mode": "dual_return"}),
])
def test_invalid_options_fail_explicitly(profile, options):
    with pytest.raises(ValueError):
        generate_rays(profile, 0, .1, options)


def test_sensor_interface_and_custom_beam_configuration():
    model = LidarModel("ouster_os1_64", {"beam_elevations_deg": np.zeros(64).tolist()})
    rays = model.get_rays(0, .001)
    np.testing.assert_array_equal(rays["directions"][:, 2], np.zeros(len(rays["timestamps"])))
    assert model.get_metadata()["beam_configuration"] == "user-supplied"


def test_default_patterns_work_in_installed_layout_without_reference_clone(tmp_path):
    # Simulate a relocated site-packages module with just its declared package
    # data. There is deliberately no research_references directory alongside it.
    import simulator.lidar as source
    package = tmp_path / "site-packages" / "simulator"
    package.mkdir(parents=True)
    shutil.copy2(source.__file__, package / "lidar.py")
    shutil.copytree(Path(source.__file__).parent / "patterns", package / "patterns")
    spec = importlib.util.spec_from_file_location("relocated_lidar", package / "lidar.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for profile in ("livox_avia", "livox_mid360"):
        before = generate_rays(profile, .025, .01)
        relocated = module.generate_rays(profile, .025, .01)
        np.testing.assert_array_equal(before["directions"], relocated["directions"])
        assert relocated["metadata"]["pattern_sha256"] == before["metadata"]["pattern_sha256"]
