"""
Tests for the "Prepare REM Files" feature (rem_prep.py + routes_rem.py).

Pattern mirrors test_capabilities / test_pixop: pure-function unit tests for the
bitrate-search math + concat assembly, a monkeypatched end-to-end of the VMAF
search (video.transcode / video.compute_vmaf scripted to a VMAF-vs-bitrate
curve), and TestClient checks for route gating + the un-gated share link.
"""
import math
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import rem_prep
import settings
import video


# --------------------------------------------------------------------------
# Bitrate-search math (pure)
# --------------------------------------------------------------------------
def test_next_bitrate_secant_within_bracket():
    # below=(90 @ 4000), above=(94 @ 8000); target 92 → halfway-ish by VMAF.
    samples = [(4000, 90.0), (8000, 94.0)]
    nb = rem_prep._next_bitrate(samples, 92.0)
    assert 4000 < nb < 8000


def test_next_bitrate_bumps_up_when_all_below_target():
    samples = [(2000, 80.0), (4000, 88.0)]
    assert rem_prep._next_bitrate(samples, 92.0) > 4000


def test_next_bitrate_drops_when_all_above_target():
    samples = [(6000, 95.0), (8000, 97.0)]
    assert rem_prep._next_bitrate(samples, 92.0) < 6000


def test_accept_prefers_lowest_bitrate_in_band():
    samples = [(4000, 90.0), (6000, 92.4), (9000, 97.0)]
    bps, v = rem_prep._accept(samples, 92.0, 0.5)
    assert bps == 6000 and v == 92.4


def test_accept_falls_back_to_closest_when_none_reach_target():
    samples = [(2000, 80.0), (4000, 89.0)]
    bps, v = rem_prep._accept(samples, 92.0, 0.5)
    assert bps == 4000 and v == 89.0  # closest to target


def test_accept_keeps_within_tolerance_probe_just_under_target():
    # Regression: the H.265 Meridian run (afc416c2) converged on 2850 kbps @ 91.99
    # (Δ −0.01, inside ±0.5) but _accept's old hard `>= target` floor discarded it
    # and fell back to the 4050 kbps seed @ 93.66 — overshooting quality AND bitrate
    # (above the parallel H.264 run's 3200 kbps). Acceptance must honor the same
    # symmetric band the search stops on.
    samples = [(4050, 93.66), (2450, 91.43), (2850, 91.99)]
    bps, v = rem_prep._accept(samples, 92.0, 0.5)
    assert bps == 2850 and v == 91.99


def test_accept_excludes_probes_below_the_band():
    # 91.0 is outside ±0.5 of 92 → must not be accepted over the in-band 92.3.
    samples = [(2000, 91.0), (3000, 92.3), (5000, 95.0)]
    bps, v = rem_prep._accept(samples, 92.0, 0.5)
    assert bps == 3000 and v == 92.3


def test_pick_better_prefers_lower_bitrate_within_band():
    # Both full-clip encodes clear quality (>= 91.5); pick the cheaper one rather
    # than the higher-bitrate overshoot.
    lo = {"vmaf": 91.99, "bps": 2850, "output_path": "/nonexistent/lo.mp4"}
    hi = {"vmaf": 93.62, "bps": 4050, "output_path": "/nonexistent/hi.mp4"}
    assert rem_prep._pick_better(hi, lo, 92.0, 0.5) is lo
    assert rem_prep._pick_better(lo, hi, 92.0, 0.5) is lo


def test_pick_better_falls_back_to_closest_when_both_under_band():
    a = {"vmaf": 88.0, "bps": 2000, "output_path": "/nonexistent/a.mp4"}
    b = {"vmaf": 90.5, "bps": 3000, "output_path": "/nonexistent/b.mp4"}
    assert rem_prep._pick_better(a, b, 92.0, 0.5) is b  # closer to target


def test_slope_from_bracket_is_positive():
    samples = [(4000, 90.0), (8000, 94.0)]
    s = rem_prep._slope(samples, 92.0)
    assert s is not None and s > 0


def test_clamp_and_round():
    assert rem_prep._round50(4123) == 4100
    assert rem_prep._clamp_bps(50) == rem_prep._BPS_FLOOR
    assert rem_prep._clamp_bps(999999) == rem_prep._BPS_CEIL


# --------------------------------------------------------------------------
# encode_to_vmaf — convergence with a scripted VMAF curve
# --------------------------------------------------------------------------
def _curve(bps: float) -> float:
    """Monotone diminishing-returns curve crossing 92 around ~4600 kbps."""
    return min(100.0, max(0.0, 80.0 + 10.0 * math.log2(bps / 2000.0)))


@pytest.fixture
def scripted_encoder(monkeypatch):
    """Fake video.transcode (parses -b:v, records call) + video.compute_vmaf
    (returns the curve at the last bitrate). Also pins the parity seed off."""
    holder = {"bps": None, "calls": 0}

    def fake_transcode(cmd, progress_cb=None):
        holder["calls"] += 1
        i = cmd.index("-b:v")
        holder["bps"] = int(cmd[i + 1].rstrip("k"))
        return {"success": True, "ffmpeg_cmd": " ".join(map(str, cmd))}

    def fake_vmaf(distorted, reference, s=None):
        return round(_curve(holder["bps"]), 2)

    monkeypatch.setattr(video, "transcode", fake_transcode)
    monkeypatch.setattr(video, "compute_vmaf", fake_vmaf)
    import budget_data
    monkeypatch.setattr(budget_data, "latest_artifact_path", lambda: None)
    return holder


@pytest.mark.asyncio
async def test_encode_to_vmaf_converges(scripted_encoder, tmp_path):
    out = await rem_prep.encode_to_vmaf(
        Path("excerpt.mp4"), tmp_path, "h264", "cpu", 1080,
        target=92.0, tol=0.5, max_iters=8, jobs=None, job_id="t1")
    assert out["converged"] is True
    assert abs(out["excerpt_vmaf"] - 92.0) <= 0.5
    assert out["slope"] and out["slope"] > 0
    assert out["bps"] > 0


@pytest.mark.asyncio
async def test_encode_to_vmaf_respects_max_iters(scripted_encoder, tmp_path):
    # tol=0 is unreachable on a 50-kbps-rounded grid → it must stop at max_iters.
    out = await rem_prep.encode_to_vmaf(
        Path("excerpt.mp4"), tmp_path, "h264", "cpu", 1080,
        target=92.0, tol=0.0, max_iters=3, jobs=None, job_id="t2")
    assert scripted_encoder["calls"] <= 3
    assert len(out["iterations"]) <= 3


@pytest.mark.asyncio
async def test_encode_to_vmaf_writes_progress_to_jobs(scripted_encoder, tmp_path):
    jobs = {"j": {}}
    await rem_prep.encode_to_vmaf(
        Path("excerpt.mp4"), tmp_path, "h264", "cpu", 1080,
        target=92.0, tol=0.5, max_iters=8, jobs=jobs, job_id="j")
    assert jobs["j"]["stage"] == "searching"
    assert jobs["j"]["iter_done"] >= 1
    assert isinstance(jobs["j"]["iterations"], list)


# --------------------------------------------------------------------------
# build_encode_cmd — pins 4:2:0 + audio; reuses the live fragments
# --------------------------------------------------------------------------
def test_build_encode_cmd_cpu_pins_pix_fmt_and_audio():
    cmd = rem_prep.build_encode_cmd("h264", "cpu", 720, 3000, "in.mp4", "out.mp4")
    assert "libx264" in cmd
    assert "-pix_fmt" in cmd and cmd[cmd.index("-pix_fmt") + 1] == "yuv420p"
    assert "scale=-2:720" in cmd
    assert "3000k" in cmd
    # constant audio for concat compatibility
    assert "-ar" in cmd and "48000" in cmd and "-ac" in cmd


def test_build_encode_cmd_forces_width_when_given():
    cmd = rem_prep.build_encode_cmd("h264", "cpu", 1080, 3000, "in.mp4", "out.mp4",
                                    width=1920)
    assert "scale=1920:1080,setsar=1" in cmd


# --------------------------------------------------------------------------
# assemble_rem_file — concat order + filter fallback
# --------------------------------------------------------------------------
def test_assemble_copy_path_uses_segment_order(monkeypatch, tmp_path):
    captured = {}

    def fake_run(cmd, capture_output=True, text=True):
        # demuxer copy path: read the list file (arg after -i), record + create out.
        listfile = Path(cmd[cmd.index("-i") + 1])
        captured["list"] = listfile.read_text()
        Path(cmd[-1]).write_bytes(b"x")
        return type("R", (), {"returncode": 0, "stderr": ""})()

    monkeypatch.setattr(rem_prep.subprocess, "run", fake_run)
    segs = [tmp_path / n for n in ("timer", "black", "white", "black2", "video", "tail")]
    out = tmp_path / "final.mp4"
    res = rem_prep.assemble_rem_file(segs, out, "h264", "cpu", 4000)
    assert res == {"method": "copy", "ok": True}
    lines = [l for l in captured["list"].splitlines() if l]
    assert lines[0].endswith("timer'") and lines[-1].endswith("tail'")
    assert len(lines) == 6


def test_assemble_falls_back_to_filter_on_copy_failure(monkeypatch, tmp_path):
    calls = {"n": 0}

    def fake_run(cmd, capture_output=True, text=True):
        calls["n"] += 1
        is_copy = "concat" in cmd and "copy" in cmd
        if is_copy:
            return type("R", (), {"returncode": 1, "stderr": "boom"})()
        # filter re-encode path
        assert "-filter_complex" in cmd
        Path(cmd[-1]).write_bytes(b"x")
        return type("R", (), {"returncode": 0, "stderr": ""})()

    monkeypatch.setattr(rem_prep.subprocess, "run", fake_run)
    segs = [tmp_path / "a", tmp_path / "b"]
    out = tmp_path / "final.mp4"
    res = rem_prep.assemble_rem_file(segs, out, "h264", "cpu", 4000)
    assert res["method"] == "filter" and res["ok"] is True
    assert calls["n"] == 2


# --------------------------------------------------------------------------
# Share-token registry — un-gated link resolution
# --------------------------------------------------------------------------
def test_share_token_register_and_resolve(monkeypatch, tmp_path):
    monkeypatch.setattr(rem_prep.cfg, "load",
                        lambda: {**settings.DEFAULTS, "rem_output_dir": str(tmp_path)})
    out_dir, _, _ = rem_prep.rem_dirs()
    (out_dir / "rem_abc_h264_1080p.mp4").write_bytes(b"video")
    token = rem_prep.register_share_token(out_dir, "rem_abc_h264_1080p.mp4")
    assert len(token) >= 16
    resolved = rem_prep.resolve_share_token(token)
    assert resolved is not None and resolved.name == "rem_abc_h264_1080p.mp4"
    assert rem_prep.resolve_share_token("deadbeef" * 4) is None


def test_share_token_rejects_traversal(monkeypatch, tmp_path):
    monkeypatch.setattr(rem_prep.cfg, "load",
                        lambda: {**settings.DEFAULTS, "rem_output_dir": str(tmp_path)})
    out_dir, _, _ = rem_prep.rem_dirs()
    # An index entry with a non-basename value must not resolve.
    (out_dir / "share_tokens.json").write_text('{"feedface": "../secret.mp4"}')
    assert rem_prep.resolve_share_token("feedface") is None


# --------------------------------------------------------------------------
# Route gating (TestClient is loopback == Lab; public IP == Anonymous)
# --------------------------------------------------------------------------
import main  # noqa: E402

client = TestClient(main.app)
_LAB = {"x-real-ip": "127.0.0.1"}
_ANON = {"x-real-ip": "8.8.8.8", "accept": "text/html"}
_ANON_FETCH = {"x-real-ip": "8.8.8.8", "accept": "*/*"}


def test_page_renders_for_lab():
    r = client.get("/prepare-rem", headers=_LAB)
    assert r.status_code == 200
    assert "Prepare REM Files" in r.text
    # Lab → controls enabled, no read-only banner.
    assert "Read-only preview" not in r.text
    assert "Generate REM File(s)" in r.text


def test_page_readonly_for_member(monkeypatch):
    import auth
    monkeypatch.setattr(auth, "member_email_from_request",
                        lambda req: "simon@example.org")
    r = client.get("/prepare-rem", headers=_ANON)
    assert r.status_code == 200
    assert "Read-only preview" in r.text
    # The run button is disabled for non-Lab.
    assert 'id="runBtn"' in r.text
    assert "disabled>Generate REM File(s)" in r.text


def test_page_403_for_anonymous():
    r = client.get("/prepare-rem", headers=_ANON)
    assert r.status_code == 403


def test_run_denied_for_anonymous():
    r = client.post("/prepare-rem/run", headers=_ANON_FETCH,
                    data={"source_key": "meridian_120s", "codec": "h264"})
    assert r.status_code == 403


def test_run_rejects_bad_codec_for_lab():
    r = client.post("/prepare-rem/run", headers=_LAB,
                    data={"source_key": "meridian_120s", "codec": "vp9"})
    assert r.status_code == 400


def test_share_link_is_public(monkeypatch, tmp_path):
    monkeypatch.setattr(rem_prep.cfg, "load",
                        lambda: {**settings.DEFAULTS, "rem_output_dir": str(tmp_path)})
    out_dir, _, _ = rem_prep.rem_dirs()
    (out_dir / "rem_xyz_h264_1080p.mp4").write_bytes(b"video-bytes")
    token = rem_prep.register_share_token(out_dir, "rem_xyz_h264_1080p.mp4")
    # Anonymous (public IP) can fetch the share link — it is intentionally un-gated.
    r = client.get(f"/rem-file/{token}", headers=_ANON_FETCH)
    assert r.status_code == 200
    assert r.content == b"video-bytes"


def test_share_link_bad_token_404():
    r = client.get("/rem-file/notavalidtoken", headers=_ANON_FETCH)
    assert r.status_code == 404


# --------------------------------------------------------------------------
# Target mode: VMAF (search) vs Bitrate (direct) — end-to-end produce run
# --------------------------------------------------------------------------
@pytest.fixture
def e2e_env(monkeypatch, tmp_path):
    """Patch the heavy I/O so run_rem_prep_job runs to a result dict in-process:
    ffprobe → fixed dims, every ffmpeg/transcode → touch its output file."""
    import json as _json

    def fake_run(cmd, capture_output=True, text=True, check=False, **kwargs):
        cmd = [str(c) for c in cmd]
        if "-show_entries" in cmd:  # ffprobe
            out = _json.dumps({"streams": [{"width": 1920, "height": 1080,
                                            "r_frame_rate": "30/1"}]})
            return type("R", (), {"returncode": 0, "stdout": out, "stderr": ""})()
        Path(cmd[-1]).write_bytes(b"x")  # ffmpeg/concat: create the output
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    def fake_transcode(cmd, progress_cb=None):
        cmd = [str(c) for c in cmd]
        if not ("-f" in cmd and "null" in cmd):   # skip the null-sink decode probe
            Path(cmd[-1]).write_bytes(b"x")
        return {"success": True, "ffmpeg_cmd": " ".join(cmd)}

    monkeypatch.setattr(rem_prep.subprocess, "run", fake_run)
    monkeypatch.setattr(video, "transcode", fake_transcode)
    monkeypatch.setattr(video, "compute_vmaf", lambda d, r, s=None: 93.0)
    monkeypatch.setattr(video, "probe_output_stream",
                        lambda p: {"pix_fmt": "yuv420p", "codec_name": "h264"})
    monkeypatch.setattr(video, "_probe_duration", lambda p: 10.0)
    monkeypatch.setattr(video, "focus_mode_enter", lambda: [])
    monkeypatch.setattr(video, "focus_mode_exit", lambda stopped: None)
    monkeypatch.setattr(video, "LOCK_FILE", tmp_path / "lock")
    monkeypatch.setattr(rem_prep.cfg, "load",
                        lambda: {**settings.DEFAULTS, "rem_output_dir": str(tmp_path),
                                 "public_base_url": "https://owl.example.org"})
    # A real uploaded source the job can stat/trim (under rem_dirs()'s _uploads).
    up_dir = tmp_path / "_uploads"
    up_dir.mkdir(parents=True, exist_ok=True)
    (up_dir / "src.mp4").write_bytes(b"src")
    return tmp_path


@pytest.mark.asyncio
async def test_bitrate_mode_skips_search(e2e_env, monkeypatch):
    # In bitrate mode the VMAF search must never run.
    def _boom(*a, **k):
        raise AssertionError("encode_to_vmaf must not be called in bitrate mode")
    monkeypatch.setattr(rem_prep, "encode_to_vmaf", _boom)

    res = await rem_prep.run_rem_prep_job(
        "bm01", jobs=None, upload_name="src.mp4", source_key=None,
        codec="h264", device="cpu", height=1080,
        fixed_bitrate_kbps=5000, batch_id="batch123abc", metered=False)

    assert res["target_mode"] == "bitrate"
    assert res["target_vmaf"] is None
    assert res["target_bitrate_kbps"] == 5000
    assert res["achieved_bitrate_kbps"] == 5000
    assert res["converged"] is True
    assert res["search"]["skipped"] is True
    assert res["batch_id"] == "batch123abc"


@pytest.mark.asyncio
async def test_share_url_is_absolute_public(e2e_env):
    res = await rem_prep.run_rem_prep_job(
        "su01", jobs=None, source_key=None, upload_name="src.mp4",
        codec="h264", device="cpu", height=1080,
        fixed_bitrate_kbps=4000, metered=False)
    su = res["output"]["share_url"]
    assert su.startswith("https://owl.example.org/rem-file/")
    assert "localhost" not in su


def test_public_base_strips_trailing_slash(monkeypatch):
    monkeypatch.setattr(rem_prep.cfg, "load",
                        lambda: {"public_base_url": "https://owl.example.org/"})
    assert rem_prep._public_base() == "https://owl.example.org"


# --------------------------------------------------------------------------
# Decode/encode energy split (Simon 2026-06-26) — metered runs
# --------------------------------------------------------------------------
def test_build_decode_cmd_cpu_is_null_sink_no_encoder():
    cmd = rem_prep.build_decode_cmd("h264", "cpu", 720, "in.mp4")
    assert cmd[-3:] == ["-f", "null", "-"]      # sinks to null, no output file
    assert "-c:v" not in cmd                     # no encoder
    assert "scale=-2:720" in cmd                 # decode + scale (CPU reference)


@pytest.fixture
def metered_env(e2e_env, monkeypatch):
    """e2e_env + mocked power instrumentation so the metered path (baseline +
    polling) runs in-process."""
    import power

    async def fake_baseline(polls=10):
        return {"w_base": 80.0, "baseline_samples_w": [80.0] * 5,
                "cpu_temp_base": 40.0, "gpu_temp_base": 35.0}

    async def fake_poll(stop_event):
        return [{"watts": 120.0, "cpu_tctl": 55.0, "gpu_junction": 50.0}
                for _ in range(8)]

    monkeypatch.setattr(video, "measure_baseline", fake_baseline)
    monkeypatch.setattr(video, "poll_during_task", fake_poll)
    monkeypatch.setattr(power, "meters_summary", lambda *a, **k: None)
    return e2e_env


@pytest.mark.asyncio
async def test_decode_encode_split_present(metered_env):
    res = await rem_prep.run_rem_prep_job(
        "ds01", jobs=None, source_key=None, upload_name="src.mp4",
        codec="h264", device="cpu", height=1080,
        fixed_bitrate_kbps=4000, metered=True)
    es = res["energy_split"]
    assert es is not None
    assert es["method"] == "transcode_minus_decode"
    # encode = max(0, transcode − decode), and the transcode figure matches `energy`.
    assert es["encode_wh"] == round(max(0.0, es["transcode_wh"] - es["decode_wh"]), 4)
    assert es["transcode_wh"] == res["energy"]["delta_e_wh"]
    assert es["decode"]["poll_count"] == 8        # the probe was actually metered


@pytest.mark.asyncio
async def test_decode_split_fail_soft(metered_env, monkeypatch):
    # If the decode probe fails, the split is dropped but the deliverable + its
    # transcode energy survive.
    def ft(cmd, progress_cb=None):
        cmd = [str(c) for c in cmd]
        if "-f" in cmd and "null" in cmd:
            return {"success": False, "ffmpeg_cmd": " ".join(cmd), "stderr": "boom"}
        Path(cmd[-1]).write_bytes(b"x")
        return {"success": True, "ffmpeg_cmd": " ".join(cmd)}
    monkeypatch.setattr(video, "transcode", ft)
    res = await rem_prep.run_rem_prep_job(
        "df01", jobs=None, source_key=None, upload_name="src.mp4",
        codec="h264", device="cpu", height=1080,
        fixed_bitrate_kbps=4000, metered=True)
    assert res["energy_split"] is None
    assert res["energy"] is not None


# --------------------------------------------------------------------------
# VMAF: REM-specific subsample/threads (A) + bitrate-mode skip toggle (C)
# --------------------------------------------------------------------------
def test_rem_vmaf_subsamples_and_doubles_for_4k(monkeypatch):
    captured = {}
    monkeypatch.setattr(video, "compute_vmaf",
                        lambda d, r, s=None: captured.update(s) or 95.0)
    monkeypatch.setattr(rem_prep.cfg, "load",
                        lambda: {**settings.DEFAULTS, "rem_vmaf_n_subsample": 5,
                                 "rem_vmaf_n_threads": 24})
    rem_prep._rem_vmaf("d.mp4", "r.mp4", 1080)
    assert captured["vmaf_n_subsample"] == 5 and captured["vmaf_n_threads"] == 24
    rem_prep._rem_vmaf("d.mp4", "r.mp4", 2160)   # 4K → doubled
    assert captured["vmaf_n_subsample"] == 10


@pytest.mark.asyncio
async def test_bitrate_mode_can_skip_vmaf(e2e_env, monkeypatch):
    # compute_vmaf must NOT be called when scoring is skipped in bitrate mode.
    def _boom(*a, **k):
        raise AssertionError("VMAF must not be scored when skipped")
    monkeypatch.setattr(video, "compute_vmaf", _boom)
    res = await rem_prep.run_rem_prep_job(
        "sv01", jobs=None, source_key=None, upload_name="src.mp4",
        codec="h264", device="cpu", height=1080,
        fixed_bitrate_kbps=4000, score_vmaf=False, metered=False)
    assert res["achieved_vmaf"] is None


@pytest.mark.asyncio
async def test_vmaf_mode_forces_scoring_even_if_skip_passed(e2e_env, monkeypatch):
    # In VMAF mode score_vmaf=False is overridden — the search needs VMAF.
    import budget_data
    monkeypatch.setattr(budget_data, "latest_artifact_path", lambda: None)
    res = await rem_prep.run_rem_prep_job(
        "vf01", jobs=None, source_key=None, upload_name="src.mp4",
        codec="h264", device="cpu", height=1080,
        target_vmaf=92.0, score_vmaf=False, metered=False)
    assert res["target_mode"] == "vmaf"
    assert res["achieved_vmaf"] is not None


def test_run_route_forces_vmaf_in_quality_mode(monkeypatch):
    import routes_rem
    seen = {}

    def fake_enqueue(job_id, kind, label, coro, request=None, page=None):
        seen["coro"] = coro
        return 1
    monkeypatch.setattr(routes_rem.queue_control, "enqueue", fake_enqueue)
    # Even if the form sends compute_vmaf=false, quality mode keeps VMAF on.
    r = client.post("/prepare-rem/run", headers=_LAB,
                    data={"source_key": "meridian_120s", "codec": "h264",
                          "target_mode": "vmaf", "compute_vmaf": "false"})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_decode_split_disabled_by_setting(metered_env, monkeypatch):
    # rem_measure_decode_split=False → encode still metered, but no decode probe/split.
    monkeypatch.setattr(rem_prep.cfg, "load",
                        lambda: {**settings.DEFAULTS, "rem_output_dir": str(metered_env),
                                 "public_base_url": "https://owl.example.org",
                                 "rem_measure_decode_split": False})
    res = await rem_prep.run_rem_prep_job(
        "dd01", jobs=None, source_key=None, upload_name="src.mp4",
        codec="h264", device="cpu", height=1080,
        fixed_bitrate_kbps=4000, metered=True)
    assert res["energy_split"] is None
    assert res.get("energy") is not None


# --------------------------------------------------------------------------
# run-route: multi-codec → N jobs sharing one batch_id; partial-enqueue
# --------------------------------------------------------------------------
def test_run_multicodec_returns_batch(monkeypatch):
    seen = []

    def fake_enqueue(job_id, kind, label, coro, request=None, page=None):
        seen.append((job_id, label))
        return len(seen)  # position 1, 2, ...

    import routes_rem
    monkeypatch.setattr(routes_rem.queue_control, "enqueue", fake_enqueue)

    r = client.post("/prepare-rem/run", headers=_LAB,
                    data={"source_key": "meridian_120s",
                          "codec": ["h264", "av1"], "target_mode": "vmaf"})
    assert r.status_code == 200
    j = r.json()
    assert len(j["jobs"]) == 2
    assert {x["codec"] for x in j["jobs"]} == {"h264", "av1"}
    # All share one batch_id, but each has a distinct job_id.
    assert j["batch_id"]
    assert len({x["job_id"] for x in j["jobs"]}) == 2
    assert j["rejected"] == []


def test_run_multicodec_partial_enqueue_records_rejected(monkeypatch):
    import routes_rem
    calls = {"n": 0}

    def fake_enqueue(job_id, kind, label, coro, request=None, page=None):
        calls["n"] += 1
        return None if calls["n"] == 2 else 1  # 2nd codec rejected (queue full)

    monkeypatch.setattr(routes_rem.queue_control, "enqueue", fake_enqueue)
    r = client.post("/prepare-rem/run", headers=_LAB,
                    data={"source_key": "meridian_120s",
                          "codec": ["h264", "av1"]})
    assert r.status_code == 200
    j = r.json()
    assert len(j["jobs"]) == 1 and len(j["rejected"]) == 1


def test_run_rejects_bad_bitrate(monkeypatch):
    r = client.post("/prepare-rem/run", headers=_LAB,
                    data={"source_key": "meridian_120s", "codec": "h264",
                          "target_mode": "bitrate", "target_bitrate": "0"})
    assert r.status_code == 400


def test_run_requires_at_least_one_codec():
    r = client.post("/prepare-rem/run", headers=_LAB,
                    data={"source_key": "meridian_120s", "codec": "vp9"})
    assert r.status_code == 400


# --------------------------------------------------------------------------
# Energy CSV — association columns first; null-safe; batch aggregation
# --------------------------------------------------------------------------
def _rem_result(job_id, batch_id, fname, energy=True):
    return {
        "mode": "rem_prep", "job_id": job_id, "batch_id": batch_id,
        "saved_at": "2026-06-26T10:00:00", "codec": "h264", "device": "cpu",
        "height": 1080, "target_mode": "vmaf", "target_vmaf": 92,
        "achieved_vmaf": 92.3, "achieved_bitrate_kbps": 4200, "converged": True,
        "energy": ({"w_base": 80.0, "w_task": 130.0, "delta_w": 50.0,
                    "delta_t_s": 12.0, "delta_e_wh": 0.16, "poll_count": 12,
                    "confidence": {"label": "🟢", "flag": "🟢"}} if energy else None),
        "energy_split": ({"transcode_wh": 0.16, "decode_wh": 0.04, "encode_wh": 0.12}
                         if energy else None),
        "thermals": ({"cpu_base": 40, "cpu_peak": 60} if energy else None),
        "segment_layout_s": {"total": 600},
        "output": {"filename": fname, "share_token": "tok_" + job_id,
                   "concat_method": "copy", "size_mb": 210.0},
    }


def test_to_csv_rem_association_columns_first():
    import persist
    csv_text = persist.to_csv("rem", _rem_result("j1", "b1", "rem_j1_h264.mp4"))
    header = csv_text.splitlines()[0]
    cols = header.split(",")
    assert cols[0] == "output_filename" and cols[1] == "share_token"
    assert "rem_j1_h264.mp4" in csv_text and "tok_j1" in csv_text
    # decode/encode split columns present + populated.
    assert "decode_wh" in cols and "encode_wh" in cols
    assert "0.04" in csv_text and "0.12" in csv_text


def test_to_csv_rem_handles_produce_only_energy_none():
    import persist
    # Must not throw when energy/thermals are None (produce-only run).
    csv_text = persist.to_csv("rem", _rem_result("j2", "b1", "x.mp4", energy=False))
    assert "x.mp4" in csv_text


def test_rem_batch_csv_aggregates_by_batch(monkeypatch, tmp_path):
    import json as _json
    import persist
    monkeypatch.setattr(persist, "RESULTS_DIR", tmp_path)
    rem_dir = tmp_path / "rem"
    rem_dir.mkdir()
    (rem_dir / "2026-06-26_j1.json").write_text(
        _json.dumps(_rem_result("j1", "bX", "a.mp4")))
    (rem_dir / "2026-06-26_j2.json").write_text(
        _json.dumps(_rem_result("j2", "bX", "b.mp4")))
    (rem_dir / "2026-06-26_j3.json").write_text(
        _json.dumps(_rem_result("j3", "OTHER", "c.mp4")))
    csv_text = persist.rem_batch_csv("bX")
    assert "a.mp4" in csv_text and "b.mp4" in csv_text
    assert "c.mp4" not in csv_text  # different batch excluded
