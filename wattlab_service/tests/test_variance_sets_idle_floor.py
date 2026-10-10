"""A benchmark's first step after calibration must have an idle reference
(2026-10-10): the calibration reads its idle windows directly, so it has to
hand its measured idle mean to power.LAST_W_BASE — otherwise the pre-step
guard has nothing to wait for and the first video baseline is taken hot."""
import asyncio

import power
import persist
import video


def test_calibration_leaves_its_idle_mean_as_the_rolling_floor(monkeypatch, tmp_path):
    s = dict(video.cfg.load(), variance_runs=2, variance_cooldown_s=0, baseline_polls=2)
    monkeypatch.setattr(video.cfg, "load", lambda: dict(s))
    monkeypatch.setattr(video.cfg, "save", lambda d: None)          # never touch live settings.json
    monkeypatch.setattr(video, "LOCK_FILE", tmp_path / "lock")      # never touch the live lock
    monkeypatch.setattr(video, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(video, "POLL_INTERVAL", 0)
    monkeypatch.setattr(video, "focus_mode_enter", lambda: [])
    monkeypatch.setattr(video, "focus_mode_exit", lambda stopped: None)
    monkeypatch.setattr(persist, "RESULTS_DIR", tmp_path)
    async def watts(): return 70.0
    async def no_cd(**k): return {"method": "fixed"}
    async def polls(stop): await stop.wait(); return [{"watts": 120.0}]
    monkeypatch.setattr(video, "get_power_watts", watts)
    monkeypatch.setattr(video, "cooldown_between_runs", no_cd)
    monkeypatch.setattr(video, "poll_during_task", polls)
    monkeypatch.setattr(video, "transcode", lambda cmd: {"success": True})
    monkeypatch.setattr(power, "LAST_W_BASE", None)
    asyncio.run(video.run_variance_calibration("t1", {"t1": {}}))
    assert power.LAST_W_BASE == 70.0


def test_cancelled_calibration_stops_between_encodes_and_keeps_settings(monkeypatch, tmp_path):
    s = dict(video.cfg.load(), variance_runs=4, variance_cooldown_s=0, baseline_polls=2)
    saved = []
    monkeypatch.setattr(video.cfg, "load", lambda: dict(s))
    monkeypatch.setattr(video.cfg, "save", lambda d: saved.append(d))
    monkeypatch.setattr(video, "LOCK_FILE", tmp_path / "lock")
    monkeypatch.setattr(video, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(video, "POLL_INTERVAL", 0)
    monkeypatch.setattr(video, "focus_mode_enter", lambda: [])
    monkeypatch.setattr(video, "focus_mode_exit", lambda stopped: None)
    async def watts(): return 70.0
    async def no_cd(**k): return {"method": "fixed"}
    async def polls(stop): await stop.wait(); return [{"watts": 120.0}]
    jobs = {"t1": {}}
    encodes = []
    def transcode(cmd):
        encodes.append(cmd)
        jobs["t1"]["cancel_requested"] = True      # operator cancels during the first encode
        return {"success": True}
    monkeypatch.setattr(video, "get_power_watts", watts)
    monkeypatch.setattr(video, "cooldown_between_runs", no_cd)
    monkeypatch.setattr(video, "poll_during_task", polls)
    monkeypatch.setattr(video, "transcode", transcode)
    r = asyncio.run(video.run_variance_calibration("t1", jobs))
    assert r["cancelled"] is True and r["variance_updated"] is False
    assert len(encodes) == 1 and saved == []
    assert not (tmp_path / "lock").exists()
