"""
Tests for the /video single-device codec sweeps (modes codecs_cpu / codecs_gpu),
the split of the old "compare all" box into three.

Covers: run_job dispatch routing, persist._summarise for the new modes (so the
Previous-Runs list shows Best/Fastest), analyse_all on single-side input, and the
preview-cmd endpoint returning the 3 read-only commands for one device.
"""
import asyncio
from pathlib import Path

import main
import persist
import video


def _mk(label, wh, t, mb, vmaf, flag="🟢"):
    return {"preset_label": label, "preset_key": label.lower().replace(" ", "_"),
            "output_size_mb": mb, "vmaf": vmaf,
            "energy": {"delta_e_wh": wh, "delta_t_s": t, "w_base": 57,
                       "confidence": {"flag": flag},
                       "co2e": {"grams": wh * 0.03, "intensity": {"g_per_kwh": 30}}},
            "thermals": {}}


def _cpu_result():
    codecs = {
        "h264": {"cpu": _mk("H.264 CPU", 1.2, 40, 10, 95)},
        "h265": {"cpu": _mk("H.265 CPU", 1.8, 80, 8, 96)},
        "av1":  {"cpu": _mk("AV1 CPU",   2.5, 120, 7, 97)},
    }
    return {"mode": "codecs_cpu", "side": "cpu", "codecs": codecs,
            "analysis": video.analyse_all(codecs)}


# ── analyse_all on a single device ──────────────────────────────────────────

def test_analyse_all_single_side():
    a = _cpu_result()["analysis"]
    assert a["most_efficient"]["codec"] == "h264"      # cheapest Wh
    assert a["most_efficient"]["label"] == "H.264 CPU"
    assert a["fastest"]["codec"] == "h264"             # fastest s
    assert a["codec_summaries"] == {}                  # no CPU-vs-GPU pairing


# ── persist summary feeds Previous-Runs ─────────────────────────────────────

def test_summarise_codecs_cpu():
    s = persist._summarise("video", _cpu_result())
    assert s["mode"] == "codecs_cpu"
    assert s["most_efficient"] == "H.264 CPU"
    assert s["best_delta_e_wh"] == 1.2
    assert s["fastest"] == "H.264 CPU"
    assert s["all_green"] is True


def test_summarise_codecs_gpu_all_green_false():
    codecs = {
        "h264": {"gpu": _mk("H.264 GPU", 0.5, 8, 10, 92, flag="🟢")},
        "h265": {"gpu": _mk("H.265 GPU", 0.6, 9, 8, 94, flag="🟡")},
    }
    res = {"mode": "codecs_gpu", "side": "gpu", "codecs": codecs,
           "analysis": video.analyse_all(codecs)}
    s = persist._summarise("video", res)
    assert s["mode"] == "codecs_gpu"
    assert s["most_efficient"] == "H.264 GPU"
    assert s["all_green"] is False                     # one 🟡 present


# ── run_job dispatch routing ────────────────────────────────────────────────

def test_run_job_routes_codecs_cpu(monkeypatch):
    captured = {}

    async def _fake(input_path, job_id, jobs, side="cpu"):
        captured["side"] = side
        return {"mode": f"codecs_{side}", "codecs": {}, "analysis": {}}

    monkeypatch.setattr(main, "run_codecs_single_measurement", _fake)
    monkeypatch.setattr(main, "save_result", lambda *a, **k: None)
    jid = "vjob01"
    main.jobs[jid] = {}
    asyncio.run(main.run_job(jid, Path("/tmp/x.mp4"), "codecs_cpu", delete_after=False))
    assert captured["side"] == "cpu"
    assert main.jobs[jid]["status"] == "done"
    del main.jobs[jid]


def test_run_job_routes_codecs_gpu(monkeypatch):
    captured = {}

    async def _fake(input_path, job_id, jobs, side="cpu"):
        captured["side"] = side
        return {"mode": f"codecs_{side}", "codecs": {}, "analysis": {}}

    monkeypatch.setattr(main, "run_codecs_single_measurement", _fake)
    monkeypatch.setattr(main, "save_result", lambda *a, **k: None)
    jid = "vjob02"
    main.jobs[jid] = {}
    asyncio.run(main.run_job(jid, Path("/tmp/x.mp4"), "codecs_gpu", delete_after=False))
    assert captured["side"] == "gpu"
    del main.jobs[jid]


# ── preview-cmd endpoint ────────────────────────────────────────────────────

def test_sweep_requests_idle_wait(monkeypatch, tmp_path):
    """The GPU/CPU sweep must call the cooldown dispatcher with a non-None
    reference_w and respect_toggle left True — i.e. idle-wait CAPABLE, not a
    forced fixed sleep. Regression guard for 'sweep used a fixed 10s cooldown'."""
    calls = []

    async def fake_baseline(polls=10):
        return {"w_base": 79.0, "samples_w": [79.0] * polls}

    async def fake_run_single(*a, **k):
        return {"preset_key": "k", "preset_label": "L", "output_size_mb": 1.0,
                "vmaf": 95.0, "thermals": {},
                "energy": {"delta_e_wh": 0.5, "delta_t_s": 8.0,
                           "confidence": {"flag": "🟢"},
                           "co2e": {"grams": 0.01, "intensity": {"g_per_kwh": 30}}}}

    async def fake_cooldown(**kw):
        calls.append(kw)
        return {"method": "idle", "waited_s": 6.0, "settled": True,
                "final_w": 80.0, "timed_out": False}

    async def fake_vmaf(*a, **k):
        return None

    monkeypatch.setattr(video, "focus_mode_enter", lambda: [])
    monkeypatch.setattr(video, "focus_mode_exit", lambda stopped: None)
    monkeypatch.setattr(video, "LOCK_FILE", tmp_path / "lock")
    monkeypatch.setattr(video, "measure_baseline", fake_baseline)
    monkeypatch.setattr(video, "run_single", fake_run_single)
    monkeypatch.setattr(video, "cooldown_between_runs", fake_cooldown)
    monkeypatch.setattr(video, "_attach_vmaf", fake_vmaf)

    jobs = {"j": {}}
    res = asyncio.run(video.run_codecs_single_measurement(
        tmp_path / "in.mp4", "j", jobs, side="gpu"))

    # 3 codecs → 2 inter-codec cooldowns
    assert len(calls) == 2
    for kw in calls:
        assert kw["reference_w"] == 79.0          # idle floor passed, not None
        assert kw.get("respect_toggle", True) is True   # not forced fixed
    # stamped so the run is self-describing
    assert res["mode"] == "codecs_gpu"
    assert len(res["cooldowns"]) == 2
    assert all(c["method"] == "idle" for c in res["cooldowns"])


def test_preview_cmd_codecs_single():
    cpu = asyncio.run(main.video_preview_cmd("codecs_cpu"))
    assert cpu["mode"] == "all_codecs"
    assert set(cpu["cmds"].keys()) == {"cpu", "h265_cpu", "av1_cpu"}
    gpu = asyncio.run(main.video_preview_cmd("codecs_gpu"))
    assert set(gpu["cmds"].keys()) == {"gpu", "h265_gpu", "av1_gpu"}
