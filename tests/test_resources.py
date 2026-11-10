"""Resource-policy tests never start Blender, WSL or a GPU process."""
import os
import pytest
from simulator.resources import render_permission, child_environment, single_job


def test_native_render_requires_explicit_opt_in():
    with pytest.raises(ValueError, match="disabled by default"):
        render_permission("CPU")
    with pytest.raises(ValueError, match="allow-gpu"):
        render_permission("OPTIX", allow_render=True)
    render_permission("CPU", allow_render=True)
    render_permission("OPTIX", allow_render=True, allow_gpu=True)


def test_child_limits_do_not_modify_host_environment(monkeypatch):
    monkeypatch.setenv("OMP_NUM_THREADS", "8")
    env = child_environment()
    assert env["OMP_NUM_THREADS"] == "1"
    assert os.environ["OMP_NUM_THREADS"] == "8"


def test_job_lock_is_released():
    with single_job():
        with pytest.raises(ValueError, match="Another simulator"):
            with single_job():
                pytest.fail("Second simulator must not acquire the lock")
    with single_job():
        pass


def test_large_camera_allocation_rejected():
    from simulator.camera import Camera
    with pytest.raises(ValueError,match="execution limit"):
        Camera.from_dict(dict(width=4096,height=4096))


def test_range_cutoffs_are_configurable_and_validated():
    from simulator.lidar import generate_rays
    r=generate_rays("velodyne_vlp16",0,.001,{"range_min_m":2.,"range_max_m":15.})
    assert r["metadata"]["range_min_m"]==2
    assert r["metadata"]["range_max_m"]==15
    with pytest.raises(ValueError,match="Range cutoffs"):
        generate_rays("velodyne_vlp16",0,.001,{"range_min_m":2.,"range_max_m":1.})
