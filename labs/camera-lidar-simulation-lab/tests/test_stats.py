"""Live hardware readings for the Activity panel: parsing, missing values, caching and the no-GPU case."""
import subprocess
import types

from simulator import gpu


def fake_smi(monkeypatch, stdout, code=0):
    monkeypatch.setattr(gpu.subprocess, "run", lambda *a, **k: types.SimpleNamespace(returncode=code, stdout=stdout, stderr=""))


def test_gpu_usage_is_parsed(monkeypatch):
    fake_smi(monkeypatch, "NVIDIA GeForce RTX 4080, 87, 11890, 16376, 71, 241.50, 320.00\n")
    assert gpu.gpu_usage() == dict(name="NVIDIA GeForce RTX 4080", util=87.0, mem_used_mb=11890.0, mem_total_mb=16376.0,
                                   temp_c=71.0, power_w=241.5, power_limit_w=320.0)


def test_values_a_card_does_not_report_become_none(monkeypatch):
    fake_smi(monkeypatch, "Some GPU, 5, 100, 2000, 40, [N/A], [N/A]\n")
    usage = gpu.gpu_usage()
    assert usage["util"] == 5.0 and usage["power_w"] is None and usage["power_limit_w"] is None


def test_no_nvidia_driver_is_not_an_error(monkeypatch):
    fake_smi(monkeypatch, "", code=9)
    assert gpu.gpu_usage() is None

    def missing(*a, **k):
        raise FileNotFoundError("nvidia-smi")
    monkeypatch.setattr(gpu.subprocess, "run", missing)
    assert gpu.gpu_usage() is None
    monkeypatch.setattr(gpu.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(subprocess.TimeoutExpired("nvidia-smi", 5)))
    assert gpu.gpu_usage() is None


def test_live_stats_shape_and_short_cache(monkeypatch):
    calls = []
    monkeypatch.setattr(gpu, "gpu_usage", lambda: calls.append(1) or dict(name="g", util=1.0))
    gpu._STATS.update(at=0.0, value=None)
    first = gpu.live_stats()
    assert set(first) == {"gpu", "cpu", "ram"}
    if first["cpu"] is not None:                                   # psutil present
        assert 0 <= first["cpu"]["percent"] <= 100 and len(first["cpu"]["cores"]) >= 1
        assert first["ram"]["total_gb"] > first["ram"]["used_gb"] >= 0
    assert gpu.live_stats() is first and len(calls) == 1            # several pages share one reading
    assert gpu.live_stats(max_age=0) is not first and len(calls) == 2
