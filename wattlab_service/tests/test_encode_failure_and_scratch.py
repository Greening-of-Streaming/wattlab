"""GoS2 demo failures, 23 Nov 2026.

1. /tmp/wattlab_uploads was created only at import. On a node that stays up
   for weeks the OS can remove it (macOS clears idle /tmp entries nightly), and
   every encode then failed with ffmpeg unable to open its output.
   video.scratch() recreates it on each use.
2. The failed encode still produced a ΔW/ΔE from a 0.1 s window, stored and
   shown as a result. run_single now raises, so the route reports the ffmpeg
   error and saves nothing.
3. A node with a router in `disabled_routers` (Pixop enhancement on GoS2) must
   not link to that router's pages from the nav, the home grid or the tour.
"""
import asyncio

import pytest
from fastapi.testclient import TestClient

import main
import ui
import video

LAB = {"x-real-ip": "127.0.0.1"}
ANON = {"x-real-ip": "8.8.8.8"}


def test_scratch_recreates_a_removed_folder(monkeypatch, tmp_path):
    gone = tmp_path / "wattlab_uploads"
    monkeypatch.setattr(video, "UPLOAD_DIR", gone)
    assert not gone.exists()
    out = video.scratch("job_h264_gpu_out.mp4")
    assert gone.is_dir()
    assert out == gone / "job_h264_gpu_out.mp4"
    gone.rmdir()                                   # swept again between jobs
    assert video.scratch("next.mp4").parent.is_dir()


def _failing_encode(monkeypatch, tmp_path):
    monkeypatch.setattr(video, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(video, "_probe_duration", lambda p: None)
    monkeypatch.setattr(video, "transcode", lambda cmd, progress_cb=None: {
        "success": False, "duration_s": 0.0, "ffmpeg_cmd": " ".join(map(str, cmd)),
        "stderr": "Error opening output /tmp/x.mp4: No such file or directory\n"})
    async def polls(stop):
        await stop.wait()
        return [{"watts": 8.05}]                   # one poll: the GoS2 demo case
    monkeypatch.setattr(video, "poll_during_task", polls)
    return next(iter(video.PRESETS))


def test_failed_encode_raises_instead_of_reporting_energy(monkeypatch, tmp_path):
    preset_key = _failing_encode(monkeypatch, tmp_path)
    baseline = {"w_base": 8.20, "baseline_samples_w": [8.2] * 5,
                "cpu_temp_base": None, "gpu_temp_base": None}
    with pytest.raises(RuntimeError) as e:
        asyncio.run(video.run_single(tmp_path / "in.mp4", "j1", preset_key, baseline))
    assert "encode failed" in str(e.value)
    assert "No such file or directory" in str(e.value)   # the ffmpeg reason is shown


def test_failed_single_run_releases_the_lock(monkeypatch, tmp_path):
    preset_key = _failing_encode(monkeypatch, tmp_path)
    lock = tmp_path / "lock"
    monkeypatch.setattr(video, "LOCK_FILE", lock)
    monkeypatch.setattr(video, "focus_mode_enter", lambda: [])
    monkeypatch.setattr(video, "focus_mode_exit", lambda stopped: None)
    async def base(polls=10):
        return {"w_base": 8.20, "baseline_samples_w": [8.2] * 5,
                "cpu_temp_base": None, "gpu_temp_base": None}
    monkeypatch.setattr(video, "measure_baseline", base)
    jobs = {"j2": {}}
    async def go():
        with pytest.raises(RuntimeError):
            await video.run_video_measurement(tmp_path / "in.mp4", "j2", preset_key, jobs)
        await asyncio.sleep(0)                     # let the focus-mode executor call settle
    asyncio.run(go())
    assert not lock.exists()
    assert "result" not in jobs["j2"]


def _with_routers_off(monkeypatch, *names):
    real = ui.cfg.load
    def load():
        d = real(); d["disabled_routers"] = list(names); return d
    monkeypatch.setattr(ui.cfg, "load", load)


def test_router_on_follows_the_setting(monkeypatch):
    _with_routers_off(monkeypatch)
    assert ui.router_on("routes_enhance") and ui.router_on("routes_decode")
    _with_routers_off(monkeypatch, "routes_enhance")
    assert not ui.router_on("routes_enhance")
    assert ui.router_on("routes_decode")


def test_no_surface_links_to_a_disabled_enhance_router(monkeypatch):
    c = TestClient(main.app)
    _with_routers_off(monkeypatch)
    home = c.get("/", headers=LAB).text
    assert 'href="/enhance-run"' in home and 'href="/decode"' in home
    assert "next=/enhance-run" in c.get("/demo", headers=ANON).text

    _with_routers_off(monkeypatch, "routes_enhance")
    home = c.get("/", headers=LAB).text
    assert "/enhance-run" not in home              # home grid and nav
    assert 'href="/decode"' in home                # the other feature stays
    tour = c.get("/demo", headers=ANON).text
    assert "next=/enhance-run" not in tour         # member link in the tour step
    assert 'href="/enhance-run"' not in tour
    assert "{ENHANCE_MEMBER_LINK}" not in tour
    assert "/enhance-run" not in c.get("/video", headers=LAB).text
