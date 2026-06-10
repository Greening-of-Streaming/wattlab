"""
Tests for the Pixop partner-transcode wrapper (pixop.py) + the hidden,
Lab-only /enhance-run routes.

The suite runs as Lab (TestClient is loopback) and has NO real docker/license,
so every docker call is monkeypatched and Anonymous is simulated with an
`x-real-ip` header. Ground-truth contract pinned here: mounts are
/mnt/host/{input,output,presets}, the preset flag is `--option-file` (not `-p`),
and NO license env is passed (it's baked into the image).
"""
import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import audience
import persist
import pixop
import routes_enhance
import main

client = TestClient(main.app)

ANON = {"x-real-ip": "8.8.8.8"}      # non-loopback → Anonymous
LAB = {"x-real-ip": "127.0.0.1"}     # loopback → Lab


def _cfg(tmp_path) -> dict:
    return {
        "image_tag": "pixop/live:test",
        "workdir": str(tmp_path),
        "license_path": str(tmp_path / "license.jwt"),
        "presets": [],
        "cooldown_s": 1,
        "docker_timeout_s": 60,
        "baseline_polls": 2,
        "vqa_enabled": True,
        "vqa_dir": str(tmp_path / "vqa-eval"),   # nonexistent → probe fail-softs
        "vqa_timeout_s": 60,
        "template_sdr": "tpl_sdr.args",          # CR-064 — stage via _stage_templates
        "template_hdr": "tpl_hdr.args",
        "upload_ttl_h": 12,
    }


# --- read_preset_args: mirror Jon's bash parser -----------------------------

def test_read_preset_args_strips_comments(tmp_path):
    p = tmp_path / "p.args"
    p.write_text("# full-line comment\n-c hevc\n\n--cbr 20000 # trailing comment\n  --gop-len 60  \n")
    assert pixop.read_preset_args(p) == ["-c", "hevc", "--cbr", "20000", "--gop-len", "60"]


# --- realtime / Live feasibility --------------------------------------------

def test_parse_encode_stats():
    line = "encoded 705 frames, 51.91 fps, 18067.47 kbps, 63.27 MB"
    assert pixop.parse_encode_stats(line) == {"frames": 705, "fps": 51.91}
    assert pixop.parse_encode_stats("no summary here") is None
    assert pixop.parse_encode_stats(None) is None


@pytest.mark.parametrize("rtf,verdict", [
    (2.2, "live"), (1.15, "live"), (1.05, "marginal"), (1.0, "marginal"),
    (0.34, "file"), (None, "unknown"),
])
def test_realtime_verdict_thresholds(rtf, verdict):
    assert pixop.realtime_verdict(rtf) == verdict


def test_build_realtime_steady_state_headline():
    rt = pixop.build_realtime(content_s=30.0, source_fps=24.0,
                              encode_stats={"frames": 705, "fps": 51.9},
                              encode_wall_s=19.7)
    assert rt["rtf_steady"] == 2.16          # 51.9 / 24
    assert rt["rtf_wall"] == 1.52            # 30 / 19.7 (cold-start incl.)
    assert rt["verdict"] == "live"


def test_build_realtime_falls_back_to_wall_when_no_encode_fps():
    rt = pixop.build_realtime(content_s=30.0, source_fps=24.0,
                              encode_stats=None, encode_wall_s=88.8)
    assert rt["rtf_steady"] is None
    assert rt["verdict"] == "file"           # 30/88.8 = 0.34 → sub-realtime


def test_build_realtime_live_sustained_vs_behind():
    # Live (1x-paced): verdict is about sustaining realtime (wall ≈ content), not headroom.
    ok = pixop.build_realtime(30.0, 24.0, {"frames": 720, "fps": 24.0}, 30.5, live=True)
    assert ok["live"] is True and ok["verdict"] == "live_sustained"
    behind = pixop.build_realtime(30.0, 24.0, {"frames": 720, "fps": 8.0}, 88.8, live=True)
    assert behind["verdict"] == "live_behind"   # dragged to 0.34× by back-pressure


# --- 1× "Serve as Live" pacer ----------------------------------------------

def test_build_pacer_cmd(tmp_path, monkeypatch):
    monkeypatch.setattr(pixop, "config", lambda: _cfg(tmp_path))
    cmd = pixop.build_pacer_cmd("clip.mov")
    joined = " ".join(cmd)
    assert "-re" in cmd and "-c copy" in joined          # paced, stream-copy (no decode)
    assert joined.endswith("-f mpegts -")
    assert f"{tmp_path}/input/clip.mov" in joined


def test_build_docker_cmd_live_reads_stdin(tmp_path, monkeypatch):
    (tmp_path / "presets").mkdir()
    (tmp_path / "presets" / "preset.args").write_text("-c hevc")
    monkeypatch.setattr(pixop, "config", lambda: _cfg(tmp_path))
    cmd = pixop.build_docker_cmd("clip.mov", "preset.args", "out.mp4", live=True)
    joined = " ".join(cmd)
    assert "--input-format mpegts -i -" in joined        # pipes the TS in
    assert "/mnt/host/input/clip.mov" not in joined      # NOT reading the file
    assert "docker run --rm --gpus all --network host -v" in joined
    assert " --init -i --user" in joined                 # stdin kept open


# --- build_docker_cmd: the verified container contract ----------------------

def test_build_docker_cmd_contract(tmp_path, monkeypatch):
    (tmp_path / "presets").mkdir()
    (tmp_path / "presets" / "preset.args").write_text("-c hevc --cbr 20000\n--output-res 1920x1080")
    monkeypatch.setattr(pixop, "config", lambda: _cfg(tmp_path))
    cmd = pixop.build_docker_cmd("clip.mov", "preset.args", "out.mp4")
    joined = " ".join(cmd)
    assert "--gpus all" in joined
    assert "--network host" in joined
    assert f"{tmp_path}/license.jwt:/opt/pixop/license.jwt:ro" in joined
    assert f"{tmp_path}:/mnt/host" in joined
    assert "--init" in joined
    assert "--user " in joined
    assert "NVIDIA_DRIVER_CAPABILITIES=all" in joined
    # Preset args are expanded host-side into argv (not --option-file).
    assert "-c hevc --cbr 20000 --output-res 1920x1080" in joined
    assert "-i /mnt/host/input/clip.mov" in joined
    assert "-o /mnt/host/output/out.mp4" in joined
    # Contract guards: NO `--option-file`, NO `-p` shorthand, NO license env
    # (license is mounted, not passed as PIXOP_LICENSE_*).
    assert "--option-file" not in joined
    assert " -p " not in joined
    assert "PIXOP_LICENSE" not in joined


# --- self_test --------------------------------------------------------------

def test_self_test_command_shape(tmp_path, monkeypatch):
    monkeypatch.setattr(pixop, "config", lambda: _cfg(tmp_path))
    monkeypatch.setattr(pixop, "LOCK_FILE", tmp_path / "nolock")
    captured = {}

    class _R:
        returncode = 0
        stdout = "NVEncC device 0: RTX 5080"
        stderr = ""

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return _R()

    monkeypatch.setattr(pixop.subprocess, "run", fake_run)
    out = pixop.self_test()
    assert captured["cmd"] == ["docker", "run", "--rm", "--gpus", "all",
                               "pixop/live:test", "--check-device"]
    assert out["ok"] is True
    assert "RTX 5080" in out["stdout_tail"]


def test_self_test_refuses_when_locked(tmp_path, monkeypatch):
    monkeypatch.setattr(pixop, "config", lambda: _cfg(tmp_path))
    lock = tmp_path / "lock"
    lock.write_text("busy")
    monkeypatch.setattr(pixop, "LOCK_FILE", lock)
    out = pixop.self_test()
    assert out["ok"] is False
    assert "progress" in out["error"]


# --- preflight matrix -------------------------------------------------------

def _stage(tmp_path, *, preset=False, inp=False, license=False):
    for sub in ("input", "output", "presets"):
        (tmp_path / sub).mkdir(exist_ok=True)
    if preset:
        (tmp_path / "presets" / "p.args").write_text("--codec hevc")
    if inp:
        (tmp_path / "input" / "clip.mov").write_text("x")
    if license:
        (tmp_path / "license.jwt").write_text("jwt")


def test_preflight_image_only(tmp_path, monkeypatch):
    monkeypatch.setattr(pixop, "config", lambda: _cfg(tmp_path))
    monkeypatch.setattr(pixop, "_image_present", lambda c: True)
    _stage(tmp_path)  # dirs but no preset/input/license
    pf = pixop.preflight()
    assert pf["ok_selftest"] is True
    assert pf["ok_transcode"] is False
    assert any("preset" in r for r in pf["reasons"])
    assert any("input" in r for r in pf["reasons"])
    assert any("license" in r for r in pf["reasons"])


def test_preflight_missing_license(tmp_path, monkeypatch):
    monkeypatch.setattr(pixop, "config", lambda: _cfg(tmp_path))
    monkeypatch.setattr(pixop, "_image_present", lambda c: True)
    _stage(tmp_path, preset=True, inp=True)  # everything but the license
    pf = pixop.preflight()
    assert pf["license_present"] is False
    assert pf["ok_transcode"] is False
    assert any("license" in r for r in pf["reasons"])


def test_preflight_fully_configured(tmp_path, monkeypatch):
    monkeypatch.setattr(pixop, "config", lambda: _cfg(tmp_path))
    monkeypatch.setattr(pixop, "_image_present", lambda c: True)
    _stage(tmp_path, preset=True, inp=True, license=True)
    pf = pixop.preflight()
    assert pf["ok_transcode"] is True
    assert pf["presets"] == ["p.args"]
    assert pf["inputs"] == ["clip.mov"]
    # missing VQA sandbox is informational only — never a blocking reason
    assert pf["vqa_ok"] is False
    assert pf["reasons"] == []


def test_preflight_no_image(tmp_path, monkeypatch):
    monkeypatch.setattr(pixop, "config", lambda: _cfg(tmp_path))
    monkeypatch.setattr(pixop, "_image_present", lambda c: False)
    _stage(tmp_path, preset=True, inp=True)
    pf = pixop.preflight()
    assert pf["ok_selftest"] is False
    assert pf["ok_transcode"] is False


# --- run_enhance_measurement (docker + harness mocked) ----------------------

def test_run_enhance_measurement_shape(tmp_path, monkeypatch):
    _stage(tmp_path, preset=True, inp=True, license=True)  # so build_docker_cmd reads p.args
    monkeypatch.setattr(pixop, "config", lambda: _cfg(tmp_path))
    monkeypatch.setattr(pixop, "preflight",
                        lambda c=None: {"ok_transcode": True,
                                        "inputs": ["clip.mov"], "presets": ["p.args"],
                                        "reasons": []})
    monkeypatch.setattr(pixop, "LOCK_FILE", tmp_path / "lock")
    monkeypatch.setattr(pixop, "focus_mode_enter", lambda: [])
    monkeypatch.setattr(pixop, "focus_mode_exit", lambda stopped: None)

    async def fake_baseline(polls=10):
        return {"w_base": 50.0, "baseline_samples_w": [50.0, 50.1],
                "cpu_temp_base": 40.0, "gpu_temp_base": 35.0}

    async def fake_poll(stop_event):
        return [{"t": 1.0, "watts": 130.0, "cpu_tctl": 60.0,
                 "gpu_junction": 70.0, "gpu_ppt_w": 250.0},
                {"t": 2.0, "watts": 132.0, "cpu_tctl": 61.0,
                 "gpu_junction": 71.0, "gpu_ppt_w": 255.0}]

    async def fake_cooldown(**kw):
        return {"method": "fixed", "waited_s": 1, "settled": True}

    monkeypatch.setattr(pixop, "measure_baseline", fake_baseline)
    monkeypatch.setattr(pixop, "poll_during_task", fake_poll)
    monkeypatch.setattr(pixop, "cooldown_between_runs", fake_cooldown)
    monkeypatch.setattr(pixop, "probe_output_stream",
                        lambda p: {"codec": "hevc", "width": 1920, "height": 1080,
                                   "pix_fmt": "yuv420p10le", "bit_rate_bps": 35_000_000})
    monkeypatch.setattr(pixop, "run_transcode_subprocess",
                        lambda cmd, t, pacer_cmd=None: {"success": True, "returncode": 0,
                                        "duration_s": 19.7, "docker_cmd": " ".join(cmd),
                                        "live": False, "stdout_tail": "", "stderr_tail": "",
                                        "encode_stats": {"frames": 705, "fps": 51.9}})
    monkeypatch.setattr(pixop, "_probe_input", lambda p: (30.0, 24.0))
    monkeypatch.setattr(pixop, "probe_vqa_nr",
                        lambda p, c=None: {"score": 9.5, "model": "CompressedVQA-HDR (NR)"})
    # stage the output so the VQA gate (transcode.success + output exists) passes
    (tmp_path / "output" / "clip__p.mp4").write_text("y")

    jobs = {"j1": {}}
    res = asyncio.run(
        pixop.run_enhance_measurement("clip.mov", "p.args", "j1", jobs))

    assert res["mode"] == "enhance"
    # Single run = LAST measured pass → no trailing cooldown (probe/VQA are
    # terminal; the next job protects itself). Same rule as compare's ffmpeg
    # pass and video's all-codecs loop.
    assert res["cooldown"] is None
    e = res["result"]["energy"]
    assert e["delta_w"] == 81.0          # 131 mean − 50 base
    assert e["delta_e_wh"] is not None
    assert "flag" in e["confidence"]
    assert res["result"]["stream"]["codec"] == "hevc"
    assert res["result"]["thermals"]["gpu_peak"] == 71.0
    # Realtime / Live verdict rides along on the result.
    assert res["result"]["realtime"]["verdict"] == "live"
    assert res["result"]["realtime"]["rtf_steady"] == 2.16
    # NR VQA on input + output (nullable fields, mocked here)
    assert res["result"]["source_vqa"]["score"] == 9.5
    assert res["result"]["vqa"]["score"] == 9.5
    assert jobs["j1"]["stage"] == "done"
    assert res["scope"].startswith("Device layer only")
    # Lock released.
    assert not (tmp_path / "lock").exists()


def test_run_enhance_measurement_live_mode(tmp_path, monkeypatch):
    _stage(tmp_path, preset=True, inp=True, license=True)
    monkeypatch.setattr(pixop, "config", lambda: _cfg(tmp_path))
    monkeypatch.setattr(pixop, "preflight",
                        lambda c=None: {"ok_transcode": True,
                                        "inputs": ["clip.mov"], "presets": ["p.args"],
                                        "reasons": []})
    monkeypatch.setattr(pixop, "LOCK_FILE", tmp_path / "lock")
    monkeypatch.setattr(pixop, "focus_mode_enter", lambda: [])
    monkeypatch.setattr(pixop, "focus_mode_exit", lambda stopped: None)

    async def fake_baseline(polls=10):
        return {"w_base": 50.0, "baseline_samples_w": [50.0],
                "cpu_temp_base": 40.0, "gpu_temp_base": 35.0}

    async def fake_poll(stop_event):
        return [{"t": 1.0, "watts": 120.0, "cpu_tctl": 60.0,
                 "gpu_junction": 70.0, "gpu_ppt_w": 200.0}]

    async def fake_cooldown(**kw):
        return {"method": "fixed", "waited_s": 1}

    captured = {}

    def fake_run(cmd, t, pacer_cmd=None):
        captured["pacer"] = pacer_cmd
        return {"success": True, "returncode": 0, "duration_s": 30.5,
                "docker_cmd": " ".join(cmd), "live": pacer_cmd is not None,
                "stdout_tail": "", "stderr_tail": "",
                "encode_stats": {"frames": 720, "fps": 24.0}}

    monkeypatch.setattr(pixop, "measure_baseline", fake_baseline)
    monkeypatch.setattr(pixop, "poll_during_task", fake_poll)
    monkeypatch.setattr(pixop, "cooldown_between_runs", fake_cooldown)
    monkeypatch.setattr(pixop, "probe_output_stream", lambda p: {"codec": "hevc"})
    monkeypatch.setattr(pixop, "_probe_input", lambda p: (30.0, 24.0))
    monkeypatch.setattr(pixop, "run_transcode_subprocess", fake_run)

    res = asyncio.run(
        pixop.run_enhance_measurement("clip.mov", "p.args", "j3", {"j3": {}}, live=True))

    assert captured["pacer"] is not None                 # a 1× pacer was built + passed
    assert res["result"]["live"] is True
    assert res["result"]["realtime"]["live"] is True
    assert res["result"]["realtime"]["verdict"] == "live_sustained"
    assert "Live" in res["result"]["preset_label"]


def test_run_enhance_measurement_rejects_unknown_input(tmp_path, monkeypatch):
    monkeypatch.setattr(pixop, "config", lambda: _cfg(tmp_path))
    monkeypatch.setattr(pixop, "preflight",
                        lambda c=None: {"ok_transcode": True,
                                        "inputs": ["clip.mov"], "presets": ["p.args"],
                                        "reasons": []})
    with pytest.raises(RuntimeError, match="unknown input"):
        asyncio.run(
            pixop.run_enhance_measurement("evil.mov", "p.args", "j2", {"j2": {}}))


# --- Route gating (Lab vs Anonymous) ----------------------------------------

def test_start_route_forbidden_for_anonymous():
    r = client.post("/enhance-run/start",
                    data={"input_name": "x", "preset_name": "y"}, headers=ANON)
    assert r.status_code == 403


def test_self_test_route_forbidden_for_anonymous():
    r = client.post("/enhance-run/self-test", headers=ANON)
    assert r.status_code == 403


def test_start_route_409_when_not_configured(monkeypatch):
    monkeypatch.setattr(pixop, "preflight",
                        lambda c=None: {"ok_transcode": False,
                                        "inputs": [], "presets": [],
                                        "reasons": ["no input clip staged"]})
    # Lab header → passes the ENHANCE_RUN cap, hits the body → 409 from preflight.
    r = client.post("/enhance-run/start",
                    data={"input_name": "x", "preset_name": "y"}, headers=LAB)
    assert r.status_code == 409
    assert "reasons" in r.json()


def test_enhance_page_blocked_for_anonymous():
    # Secret: the PAGE itself (not just the run) is gated — anonymous can't even
    # see it exists. (Earlier it was PUBLIC_PAGE, which leaked the whole page.)
    r = client.get("/enhance-run", headers=ANON)
    assert r.status_code == 403


def test_enhance_page_renders_for_member_and_is_hidden():
    r = client.get("/enhance-run", headers=LAB)   # Lab ≥ Member
    assert r.status_code == 200
    # Vendor-neutral: never names the partner on the page.
    assert "Pixop" not in r.text
    assert "NVEncC" not in r.text
    # Hidden: not linked from the member nav grid.
    home = client.get("/").text
    assert "/enhance-run" not in home


# --- Output route (download/preview) ----------------------------------------

def test_output_route_forbidden_for_anonymous():
    r = client.get("/enhance-run/output/anything.mp4", headers=ANON)
    assert r.status_code == 403


def test_output_route_404_for_missing(tmp_path, monkeypatch):
    for sub in ("input", "output", "presets"):
        (tmp_path / sub).mkdir()
    monkeypatch.setattr(pixop, "config", lambda: _cfg(tmp_path))
    r = client.get("/enhance-run/output/nope.mp4", headers=LAB)
    assert r.status_code == 404


def test_output_route_404_on_traversal(tmp_path, monkeypatch):
    for sub in ("input", "output", "presets"):
        (tmp_path / sub).mkdir()
    (tmp_path / "secret.txt").write_text("nope")
    monkeypatch.setattr(pixop, "config", lambda: _cfg(tmp_path))
    # A traversal name must never escape the output dir.
    r = client.get("/enhance-run/output/..%2Fsecret.txt", headers=LAB)
    assert r.status_code == 404


def test_output_route_serves_existing_file(tmp_path, monkeypatch):
    for sub in ("input", "output", "presets"):
        (tmp_path / sub).mkdir()
    (tmp_path / "output" / "clip__p.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42")
    monkeypatch.setattr(pixop, "config", lambda: _cfg(tmp_path))
    r = client.get("/enhance-run/output/clip__p.mp4", headers=LAB)
    assert r.status_code == 200
    assert r.headers["content-type"] == "video/mp4"


def test_input_route_forbidden_for_anonymous():
    r = client.get("/enhance-run/input/clip.mov", headers=ANON)
    assert r.status_code == 403


def test_input_route_serves_existing_file(tmp_path, monkeypatch):
    for sub in ("input", "output", "presets"):
        (tmp_path / sub).mkdir()
    (tmp_path / "input" / "clip.mov").write_bytes(b"\x00\x00\x00\x18ftypqt  ")
    monkeypatch.setattr(pixop, "config", lambda: _cfg(tmp_path))
    r = client.get("/enhance-run/input/clip.mov", headers=LAB)
    assert r.status_code == 200
    assert r.headers["content-type"] == "video/mp4"


# --- Capability table -------------------------------------------------------

def test_enhance_run_is_member_tier():
    # S40: lowered Lab→Member so allowlisted members (Jon/Tania) can run the
    # hidden demo off-LAN via magic-link. Anonymous is still denied.
    import capabilities
    from audience import Tier
    assert capabilities.can(Tier.Anonymous, capabilities.ENHANCE_RUN) is False
    assert capabilities.can(Tier.Member, capabilities.ENHANCE_RUN) is True
    assert capabilities.can(Tier.Lab, capabilities.ENHANCE_RUN) is True


# --- ffmpeg comparison: preset spec + gating --------------------------------

def test_parse_preset_spec_upscale_only(tmp_path, monkeypatch):
    (tmp_path / "presets").mkdir(parents=True)
    (tmp_path / "presets" / "up.args").write_text(
        "--codec hevc\n--output-res 1920x1080\n--cbr 12000\n--transfer bt709\n")
    monkeypatch.setattr(pixop, "config", lambda: _cfg(tmp_path))
    spec = pixop.parse_preset_spec("up.args")
    assert spec["width"] == 1920 and spec["height"] == 1080
    assert spec["bitrate_kbps"] == 12000
    assert spec["hdr_convert"] is False
    assert spec["stays_sdr"] is True
    assert pixop.ffmpeg_comparable("up.args") is True


def test_parse_preset_spec_scale_factor(tmp_path, monkeypatch):
    (tmp_path / "presets").mkdir(parents=True)
    (tmp_path / "presets" / "sr.args").write_text("--output-res 0x0,scale=2\n--cbr 20000\n")
    monkeypatch.setattr(pixop, "config", lambda: _cfg(tmp_path))
    spec = pixop.parse_preset_spec("sr.args")
    assert spec["scale_factor"] == 2.0
    assert spec["width"] is None  # 0x0 → relative, no absolute dims


def test_ffmpeg_comparable_false_for_hdr_convert(tmp_path, monkeypatch):
    (tmp_path / "presets").mkdir(parents=True)
    (tmp_path / "presets" / "hdr.args").write_text(
        "--output-res 3840x2160\n--vpp-colorspace sdr_to_hdr=on\n--cbr 40000\n")
    monkeypatch.setattr(pixop, "config", lambda: _cfg(tmp_path))
    assert pixop.parse_preset_spec("hdr.args")["hdr_convert"] is True
    assert pixop.ffmpeg_comparable("hdr.args") is False


# --- build_ffmpeg_upscale_cmd -----------------------------------------------

def test_build_ffmpeg_upscale_cmd_shape(tmp_path, monkeypatch):
    monkeypatch.setattr(pixop, "config", lambda: _cfg(tmp_path))
    monkeypatch.setattr(pixop.cfg, "load", lambda: {"ffmpeg_bin": "ffmpeg-x"})
    cmd = pixop.build_ffmpeg_upscale_cmd("clip.mov", "out.mp4", 1920, 1080,
                                         12000, "lanczos")
    s = " ".join(cmd)
    assert cmd[0] == "ffmpeg-x"
    assert "scale=1920:1080:flags=lanczos" in s
    assert "-b:v" in cmd and "12000k" in cmd
    assert "-re" not in cmd                      # batch by default
    assert s.endswith("out.mp4")


def test_build_ffmpeg_upscale_cmd_live_adds_re(tmp_path, monkeypatch):
    monkeypatch.setattr(pixop, "config", lambda: _cfg(tmp_path))
    monkeypatch.setattr(pixop.cfg, "load", lambda: {"ffmpeg_bin": "ffmpeg"})
    cmd = pixop.build_ffmpeg_upscale_cmd("clip.mov", "out.mp4", 1280, 720,
                                         None, "bicubic", live=True)
    assert "-re" in cmd
    assert "scale=1280:720:flags=bicubic" in " ".join(cmd)
    # falls back to the default bitrate when the preset has none
    assert f"{pixop._DEFAULT_FF_BITRATE_KBPS}k" in cmd


def test_resolve_target_dims_prefers_ml_output(tmp_path):
    spec = {"width": 1920, "height": 1080, "scale_factor": None}
    ml = {"result": {"stream": {"width": 3840, "height": 2160}}}
    assert pixop._resolve_target_dims(spec, ml, tmp_path / "x") == (3840, 2160)


def test_build_comparison_ratios_and_quality_tbd():
    ml = {"result": {"output_size_mb": 60.0,
                     "energy": {"delta_e_wh": 0.40, "delta_w": 200.0, "delta_t_s": 30.0}}}
    ff = {"result": {"output_size_mb": 40.0,
                     "energy": {"delta_e_wh": 0.10, "delta_w": 50.0, "delta_t_s": 25.0}}}
    c = pixop._build_comparison(ml, ff)
    assert c["energy_ratio"] == 4.0      # 0.40 / 0.10
    assert c["size_ratio"] == 1.5        # 60 / 40
    assert c["quality"] == "TBD"
    assert "VMAF" in c["quality_note"]


# --- complexity probes (pure parsers) ---------------------------------------

def test_parse_siti_summary_takes_last_block():
    # siti prints an empty init block (Total frames: 0, nan) then the real one.
    text = (
        "[Parsed_siti_0] SITI Summary:\n"
        "Total frames: 0\n\nSpatial Information:\nAverage: -nan\nMax: 0.000000\nMin: 0.000000\n"
        "\nTemporal Information:\nAverage: -nan\nMax: 0.000000\nMin: 0.000000\n"
        "[Parsed_siti_0] SITI Summary:\n"
        "Total frames: 48\n\nSpatial Information:\nAverage: 102.436302\nMax: 104.224983\nMin: 99.5\n"
        "\nTemporal Information:\nAverage: 15.155403\nMax: 17.224213\nMin: 0.0\n")
    out = pixop._parse_siti_summary(text)
    assert out == {"si_mean": 102.44, "si_max": 104.22,
                   "ti_mean": 15.16, "ti_max": 17.22}


def test_parse_siti_summary_none_when_no_real_block():
    text = ("SITI Summary:\nTotal frames: 0\nSpatial Information:\nAverage: -nan\n"
            "Max: 0.0\nTemporal Information:\nAverage: -nan\nMax: 0.0\n")
    assert pixop._parse_siti_summary(text) is None


def test_aggregate_frame_sizes():
    frames = [
        {"pict_type": "I", "pkt_size": "10240"},   # 10 KB
        {"pict_type": "P", "pkt_size": "5120"},    # 5 KB
        {"pict_type": "B", "pkt_size": "2048"},    # 2 KB
        {"pict_type": "B", "pkt_size": "2048"},
        {"pict_type": "I", "pkt_size": "10240"},
        {"pict_type": "X"},                         # no size → skipped
    ]
    out = pixop._aggregate_frame_sizes(frames)
    assert out["frames"] == 5
    assert out["keyframes"] == 2
    assert out["i_mean_kb"] == 10.0
    assert out["p_mean_kb"] == 5.0
    assert out["b_mean_kb"] == 2.0
    assert out["max_kb"] == 10.0


def test_aggregate_frame_sizes_none_when_empty():
    assert pixop._aggregate_frame_sizes([]) is None
    assert pixop._aggregate_frame_sizes([{"pict_type": "I"}]) is None


def test_parse_psnr_and_ssim():
    psnr_line = "[Parsed_psnr_4] PSNR y:26.56 u:23.56 v:21.04 average:24.541559 min:24.3 max:24.9"
    ssim_line = "[Parsed_ssim_4] SSIM Y:0.858 (8.4) U:0.79 (6.9) V:0.77 (6.4) All:0.834249 (7.8)"
    assert pixop._parse_psnr(psnr_line) == 24.54
    assert pixop._parse_ssim(ssim_line) == 0.8342
    assert pixop._parse_psnr("PSNR y:inf average:inf min:inf") == float("inf")
    assert pixop._parse_psnr("no metric here") is None
    assert pixop._parse_ssim("no metric here") is None


def test_probe_ab_quality_identical_is_json_safe(monkeypatch):
    # PSNR=inf (bit-identical) must not leak a non-JSON float into the result.
    monkeypatch.setattr(pixop, "_run_ab_metric",
                        lambda a, b, m: ("average:inf" if m == "psnr" else "SSIM All:1.000000 (x)"))
    out = pixop.probe_ab_quality("a.mp4", "b.mp4")
    assert out == {"psnr_db": None, "identical": True, "ssim": 1.0}


# --- No-reference VQA (CompressedVQA-HDR) ------------------------------------

def test_parse_vqa_score():
    # Warning noise before the score line is the normal case.
    assert pixop._parse_vqa_score(
        "UserWarning: blah\nQuality score: 9.7559\n") == 9.76
    assert pixop._parse_vqa_score("Quality score: 7.9") == 7.9
    assert pixop._parse_vqa_score("no score here") is None
    assert pixop._parse_vqa_score("") is None
    assert pixop._parse_vqa_score(None) is None


def test_probe_vqa_nr_missing_sandbox_fail_soft(tmp_path, monkeypatch):
    # Empty vqa_dir → None, and no subprocess is ever spawned.
    spawned = []
    monkeypatch.setattr(pixop.subprocess, "run",
                        lambda *a, **k: spawned.append(a))
    assert pixop.probe_vqa_nr(tmp_path / "x.mp4", _cfg(tmp_path)) is None
    assert spawned == []


def test_probe_vqa_nr_disabled(tmp_path):
    c = _cfg(tmp_path)
    c["vqa_enabled"] = False
    assert pixop.probe_vqa_nr(tmp_path / "x.mp4", c) is None


def _stage_vqa_sandbox(c) -> Path:
    """Fake the sandbox tree so _vqa_paths resolves; returns the NR dir."""
    root = Path(c["vqa_dir"])
    (root / "venv" / "bin").mkdir(parents=True)
    (root / "venv" / "bin" / "python").write_text("")
    nr = root / "CompressedVQA-HDR" / "NR"
    (nr / "ckpts").mkdir(parents=True)
    (nr / "VQA_NR.py").write_text("")
    (nr / "ckpts" / "NR_HDR_VQA.pth").write_text("")
    (nr / "ckpts" / "NR_HDR_VQA.npy").write_text("")
    return nr


def test_probe_vqa_nr_invocation_contract(tmp_path, monkeypatch):
    # Verified contract: run from cwd=NR dir (relative ckpt paths + cwd import).
    c = _cfg(tmp_path)
    nr = _stage_vqa_sandbox(c)
    clip = tmp_path / "clip.mp4"
    clip.write_text("x")
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"], seen["cwd"] = cmd, kw.get("cwd")
        class R:
            stdout = "some warning\nQuality score: 9.7559\n"
            stderr = ""
        return R()

    monkeypatch.setattr(pixop.subprocess, "run", fake_run)
    out = pixop.probe_vqa_nr(clip, c)
    assert out["score"] == 9.76
    assert out["model"] == "CompressedVQA-HDR (NR)"
    assert seen["cwd"] == str(nr)
    assert seen["cmd"][0] == str(Path(c["vqa_dir"]) / "venv" / "bin" / "python")
    assert "--distorted" in seen["cmd"] and str(clip) in seen["cmd"]


def test_probe_vqa_nr_parse_failure_fail_soft(tmp_path, monkeypatch):
    c = _cfg(tmp_path)
    _stage_vqa_sandbox(c)
    clip = tmp_path / "clip.mp4"
    clip.write_text("x")

    def fake_run(cmd, **kw):
        class R:
            stdout = "Traceback (most recent call last): boom"
            stderr = "boom"
        return R()

    monkeypatch.setattr(pixop.subprocess, "run", fake_run)
    assert pixop.probe_vqa_nr(clip, c) is None


# --- run_enhance_compare_measurement (harness mocked) -----------------------

def _mock_harness(monkeypatch, tmp_path, *, out_w=1920, out_h=1080):
    monkeypatch.setattr(pixop, "config", lambda: _cfg(tmp_path))
    monkeypatch.setattr(pixop, "preflight",
                        lambda c=None: {"ok_transcode": True,
                                        "inputs": ["clip.mov"], "presets": ["up.args"],
                                        "reasons": []})
    monkeypatch.setattr(pixop, "LOCK_FILE", tmp_path / "lock")
    monkeypatch.setattr(pixop, "focus_mode_enter", lambda: [])
    monkeypatch.setattr(pixop, "focus_mode_exit", lambda stopped: None)

    async def fake_baseline(polls=10):
        return {"w_base": 50.0, "baseline_samples_w": [50.0, 50.1],
                "cpu_temp_base": 40.0, "gpu_temp_base": 35.0}

    async def fake_poll(stop_event):
        return [{"t": 1.0, "watts": 250.0, "cpu_tctl": 60.0,
                 "gpu_junction": 70.0, "gpu_ppt_w": 300.0}]

    async def fake_cooldown(**kw):
        return {"method": "fixed", "waited_s": 1, "settled": True}

    monkeypatch.setattr(pixop, "measure_baseline", fake_baseline)
    monkeypatch.setattr(pixop, "poll_during_task", fake_poll)
    monkeypatch.setattr(pixop, "cooldown_between_runs", fake_cooldown)
    monkeypatch.setattr(pixop, "probe_output_stream",
                        lambda p: {"codec": "hevc", "width": out_w, "height": out_h})
    monkeypatch.setattr(pixop, "_probe_input", lambda p: (30.0, 24.0))
    monkeypatch.setattr(pixop, "probe_complexity",
                        lambda p, c=None: {"si_mean": 50.0, "frames": 10, "keyframes": 1})
    monkeypatch.setattr(pixop, "probe_ab_quality",
                        lambda a, b: {"psnr_db": 38.5, "ssim": 0.97})
    monkeypatch.setattr(pixop, "probe_vqa_nr",
                        lambda p, c=None: {"score": 9.5, "model": "CompressedVQA-HDR (NR)"})
    monkeypatch.setattr(pixop, "run_transcode_subprocess",
                        lambda cmd, t, pacer_cmd=None: {"success": True, "returncode": 0,
                                        "duration_s": 20.0, "docker_cmd": " ".join(cmd),
                                        "live": pacer_cmd is not None, "stdout_tail": "",
                                        "stderr_tail": "", "encode_stats": None})


def test_run_enhance_compare_shape(tmp_path, monkeypatch):
    (tmp_path / "presets").mkdir(parents=True)
    (tmp_path / "presets" / "up.args").write_text("--output-res 1920x1080\n--cbr 12000\n")
    (tmp_path / "input").mkdir(exist_ok=True)
    (tmp_path / "input" / "clip.mov").write_text("x")
    _mock_harness(monkeypatch, tmp_path)

    jobs = {"j1": {}}
    res = asyncio.run(
        pixop.run_enhance_compare_measurement("clip.mov", "up.args", "j1", jobs))

    assert res["mode"] == "enhance_compare"
    assert res["ml"]["result"]["preset_key"] == "up.args"
    assert res["ffmpeg"]["result"]["preset_key"] == "ffmpeg:lanczos"
    assert res["target_res"] == "1920x1080"
    # (energy_ratio is 0/None here only because the mocked transcode is instant;
    #  the ratio maths is covered by test_build_comparison_ratios)
    assert "energy_ratio" in res["comparison"]
    assert res["comparison"]["quality"] == "TBD"
    # the coarse stage advanced to done; both passes wrote distinct outputs
    assert jobs["j1"]["stage"] == "done"
    assert res["ml"]["result"]["output_name"] != res["ffmpeg"]["result"]["output_name"]
    # terminal complexity probe attached to both passes + source
    assert res["ml"]["result"]["complexity"]["si_mean"] == 50.0
    assert res["ffmpeg"]["result"]["complexity"]["frames"] == 10
    assert res["source_complexity"]["si_mean"] == 50.0
    # A↔B differential quality on the comparison
    assert res["comparison"]["ab_quality"] == {"psnr_db": 38.5, "ssim": 0.97}
    # NR VQA scores on source + both outputs (all nullable in the envelope)
    assert res["source_vqa"]["score"] == 9.5
    assert res["ml"]["result"]["vqa"]["score"] == 9.5
    assert res["ffmpeg"]["result"]["vqa"]["score"] == 9.5


def test_run_enhance_compare_rejects_hdr_preset(tmp_path, monkeypatch):
    (tmp_path / "presets").mkdir(parents=True)
    (tmp_path / "presets" / "up.args").write_text(
        "--output-res 3840x2160\n--vpp-colorspace sdr_to_hdr=on\n")
    (tmp_path / "input").mkdir(exist_ok=True)
    (tmp_path / "input" / "clip.mov").write_text("x")
    _mock_harness(monkeypatch, tmp_path)
    with pytest.raises(RuntimeError, match="SDR→HDR"):
        asyncio.run(
            pixop.run_enhance_compare_measurement("clip.mov", "up.args", "j9", {"j9": {}}))


# --- start-compare route gating ---------------------------------------------

def test_start_compare_route_forbidden_for_anonymous():
    r = client.post("/enhance-run/start-compare",
                    data={"input_name": "x", "preset_name": "y"}, headers=ANON)
    assert r.status_code == 403


def test_start_compare_route_409_when_not_configured(monkeypatch):
    monkeypatch.setattr(pixop, "preflight",
                        lambda c=None: {"ok_transcode": False, "inputs": [],
                                        "presets": [], "reasons": ["no input clip"]})
    r = client.post("/enhance-run/start-compare",
                    data={"input_name": "x", "preset_name": "y"}, headers=LAB)
    assert r.status_code == 409


# ═══ CR-064 — /enhance-run revamp ════════════════════════════════════════════

_TPL_SDR = """# General
--avsw
-c hevc
--gop-len 60
--vpp-resize pixop-live
--vpp-pixop-live dnn_scaling=on,sdr_to_hdr=off,input_mat=bt709
--output-res 1920x1080
--output-depth 10
--colormatrix bt709
--transfer bt709
--output-csp yuv422
--cbr 20000
--audio-copy
"""

_TPL_HDR = """# General
--avsw
-c hevc
--gop-len 60
--vpp-resize pixop-live
--vpp-pixop-live dnn_scaling=on,sdr_to_hdr=on,input_mat=bt709
--output-res 1920x1080
--output-depth 10
--colormatrix bt2020nc
--transfer smpte2084
--output-csp yuv422
--cbr 20000
--audio-copy
"""


def _stage_templates(tmp_path):
    pre = tmp_path / "presets"
    pre.mkdir(parents=True, exist_ok=True)
    (pre / "tpl_sdr.args").write_text(_TPL_SDR)
    (pre / "tpl_hdr.args").write_text(_TPL_HDR)


# --- generated preset matrix --------------------------------------------------

def test_generate_presets_full_matrix(tmp_path):
    c = _cfg(tmp_path)
    _stage_templates(tmp_path)
    combos = pixop.generate_presets(c)
    # hdr_4k is excluded: sdr_to_hdr=on aborts pixop-live at a 4K target
    # (2026-06-10 bisect) — pending Jon's input-agnostic HDR template.
    assert set(combos) == {"sdr_sd", "sdr_hd", "sdr_4k", "hdr_sd", "hdr_hd"}
    # Substitution: ONLY --output-res and --cbr change; template lines survive.
    f = tmp_path / "presets" / combos["sdr_4k"]["preset"]
    text = f.read_text()
    assert "--output-res 3840x2160" in text
    assert "--cbr 35000" in text
    assert "--transfer bt709" in text          # untouched template line
    assert "sdr_to_hdr=off" in text
    # 4:2:0 by default (owner decision 2026-06-10) — Main10, browser-decodable.
    assert "--output-csp yuv420" in text
    assert "yuv422" not in text
    hdr_sd = (tmp_path / "presets" / combos["hdr_sd"]["preset"]).read_text()
    assert "--output-res 854x480" in hdr_sd
    assert "--cbr 5000" in hdr_sd
    assert "--transfer smpte2084" in hdr_sd
    # Metadata for the UI (args = raw file text for the advanced editor).
    hd = combos["hdr_hd"]
    assert hd["preset"] == "generated/owl_hdr_hd_20mbps.args"
    assert (hd["format"], hd["target"], hd["res"], hd["mbps"]) == ("HDR", "HD", "1920x1080", 20)
    assert hd["template"] == "tpl_hdr.args"
    assert hd["args"] == (tmp_path / "presets" / hd["preset"]).read_text()
    # Idempotent — second call leaves identical content.
    before = f.read_text()
    pixop.generate_presets(c)
    assert f.read_text() == before


def test_generate_presets_missing_template_drops_format(tmp_path):
    c = _cfg(tmp_path)
    pre = tmp_path / "presets"
    pre.mkdir(parents=True, exist_ok=True)
    (pre / "tpl_sdr.args").write_text(_TPL_SDR)   # no HDR template staged
    combos = pixop.generate_presets(c)
    assert set(combos) == {"sdr_sd", "sdr_hd", "sdr_4k"}


def test_resolve_combo(tmp_path, monkeypatch):
    monkeypatch.setattr(pixop, "config", lambda: _cfg(tmp_path))
    _stage_templates(tmp_path)
    combo = pixop.resolve_combo("hdr", "hd")
    assert combo["preset"] == "generated/owl_hdr_hd_20mbps.args"
    assert pixop.resolve_combo("hdr", "4k") is None    # excluded (known-bad)
    assert pixop.resolve_combo("sdr", "8k") is None
    assert pixop.resolve_combo("dolby", "hd") is None


def test_preset_origin():
    assert pixop.preset_origin("generated/owl_sdr_hd_20mbps.args") == "generated"
    assert pixop.preset_origin("nvencc_fhd_709_20mbps.args") == "staged"


def test_generated_preset_spec_and_compare_gate(tmp_path, monkeypatch):
    monkeypatch.setattr(pixop, "config", lambda: _cfg(tmp_path))
    _stage_templates(tmp_path)
    c = _cfg(tmp_path)
    combos = pixop.generate_presets(c)
    spec = pixop.parse_preset_spec(combos["hdr_hd"]["preset"], c)
    assert spec["width"] == 1920 and spec["height"] == 1080
    assert spec["bitrate_kbps"] == 20000
    assert spec["hdr_convert"] is True
    assert spec["output_csp"] == "yuv420" and spec["output_depth"] == 10
    # HDR combos have no apples-to-apples ffmpeg baseline; SDR combos do.
    assert pixop.ffmpeg_comparable(combos["hdr_hd"]["preset"], c) is False
    assert pixop.ffmpeg_comparable(combos["sdr_hd"]["preset"], c) is True


def test_preflight_includes_combos(tmp_path, monkeypatch):
    monkeypatch.setattr(pixop, "config", lambda: _cfg(tmp_path))
    monkeypatch.setattr(pixop, "_image_present", lambda c: True)
    _stage(tmp_path, preset=True, inp=True, license=True)
    _stage_templates(tmp_path)
    pf = pixop.preflight()
    assert len(pf["combos"]) == 5     # 6 minus the excluded hdr_4k
    assert pixop._preset_known("generated/owl_sdr_hd_20mbps.args", pf)
    assert pixop._preset_known("p.args", pf)
    assert not pixop._preset_known("evil.args", pf)


# --- ffmpeg baseline format match (4:2:2 10-bit) -------------------------------

def test_ffmpeg_pix_fmt_mapping(monkeypatch):
    class _Nv:
        vendor = "nvidia"
    class _Amd:
        vendor = "amd"
    monkeypatch.setattr(pixop.gpu, "BACKEND", _Nv())
    assert pixop._ffmpeg_pix_fmt({"output_csp": "yuv422", "output_depth": 10}) == "p210le"
    assert pixop._ffmpeg_pix_fmt({"output_csp": "yuv420", "output_depth": 10}) == "p010le"
    assert pixop._ffmpeg_pix_fmt({"output_csp": None, "output_depth": None}) is None
    monkeypatch.setattr(pixop.gpu, "BACKEND", _Amd())
    assert pixop._ffmpeg_pix_fmt({"output_csp": "yuv422", "output_depth": 10}) is None


def test_build_ffmpeg_upscale_cmd_pix_fmt(tmp_path, monkeypatch):
    monkeypatch.setattr(pixop, "config", lambda: _cfg(tmp_path))
    cmd = pixop.build_ffmpeg_upscale_cmd("in.mov", "out.mp4", 1920, 1080,
                                         20000, "lanczos", _cfg(tmp_path),
                                         pix_fmt="p210le")
    i = cmd.index("-pix_fmt")
    assert cmd[i + 1] == "p210le"
    cmd2 = pixop.build_ffmpeg_upscale_cmd("in.mov", "out.mp4", 1920, 1080,
                                          20000, "lanczos", _cfg(tmp_path))
    assert "-pix_fmt" not in cmd2


# --- upload route ---------------------------------------------------------------

def test_upload_forbidden_for_anonymous():
    r = client.post("/enhance-run/upload",
                    files={"file": ("c.mp4", b"x", "video/mp4")}, headers=ANON)
    assert r.status_code == 403


def test_upload_lab_uncapped(tmp_path, monkeypatch):
    monkeypatch.setattr(pixop, "config", lambda: _cfg(tmp_path))
    monkeypatch.setattr(pixop, "probe_input_stream",
                        lambda p: {"duration_s": 120.0, "width": 1920, "height": 1080,
                                   "color_transfer": "bt709", "hdr": False})
    r = client.post("/enhance-run/upload",
                    files={"file": ("My Clip (1).mp4", b"\x00" * 64, "video/mp4")},
                    headers=LAB)
    assert r.status_code == 200
    d = r.json()
    assert d["name"].startswith("upload_") and d["name"].endswith(".mp4")
    assert d["duration_s"] == 120.0           # Lab: no duration cap applied
    assert (tmp_path / "input" / d["name"]).exists()
    assert d["input_stream"]["hdr"] is False


def test_upload_member_duration_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(pixop, "config", lambda: _cfg(tmp_path))
    monkeypatch.setattr(audience, "tier", lambda r: audience.Tier.Member)
    monkeypatch.setattr(pixop, "probe_input_stream", lambda p: {"duration_s": 90.0})
    r = client.post("/enhance-run/upload",
                    files={"file": ("c.mp4", b"x" * 32, "video/mp4")}, headers=LAB)
    assert r.status_code == 413
    assert "60s" in r.json()["error"]
    assert not list((tmp_path / "input").glob("upload_*"))   # rejected file removed


def test_upload_member_size_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(pixop, "config", lambda: _cfg(tmp_path))
    monkeypatch.setattr(audience, "tier", lambda r: audience.Tier.Member)
    monkeypatch.setattr(routes_enhance.cfg, "load",
                        lambda: {"enhance_upload_max_mb": 0,
                                 "enhance_upload_max_duration_s": 60})
    r = client.post("/enhance-run/upload",
                    files={"file": ("c.mp4", b"x" * 1024, "video/mp4")}, headers=LAB)
    assert r.status_code == 413
    assert "MB" in r.json()["error"]


def test_upload_member_unprobeable_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(pixop, "config", lambda: _cfg(tmp_path))
    monkeypatch.setattr(audience, "tier", lambda r: audience.Tier.Member)
    monkeypatch.setattr(pixop, "probe_input_stream", lambda p: None)
    r = client.post("/enhance-run/upload",
                    files={"file": ("c.mp4", b"not a video", "video/mp4")}, headers=LAB)
    assert r.status_code == 400


def test_upload_bad_extension(tmp_path, monkeypatch):
    monkeypatch.setattr(pixop, "config", lambda: _cfg(tmp_path))
    r = client.post("/enhance-run/upload",
                    files={"file": ("evil.txt", b"x", "text/plain")}, headers=LAB)
    assert r.status_code == 400


def test_cleanup_upload_touches_not_deletes(tmp_path, monkeypatch):
    # Owner amendment 2026-06-10: job end must NOT delete the input (the
    # result card compares source vs outputs) — it touches the mtime so the
    # TTL sweep counts from the run.
    monkeypatch.setattr(pixop, "config", lambda: _cfg(tmp_path))
    (tmp_path / "input").mkdir(parents=True, exist_ok=True)
    f = tmp_path / "input" / "upload_abc_clip.mp4"
    f.write_text("x")
    import os
    os.utime(f, (1_000_000, 1_000_000))   # ancient mtime
    routes_enhance._cleanup_upload("upload_abc_clip.mp4")
    assert f.exists()
    assert f.stat().st_mtime > 1_000_000  # clock restarted at run end


def test_sweep_ephemeral_uploads(tmp_path):
    import os
    import time as _t
    c = _cfg(tmp_path)
    (tmp_path / "input").mkdir(parents=True, exist_ok=True)
    old = _t.time() - 13 * 3600           # past the 12h TTL
    expired = tmp_path / "input" / "upload_old_clip.mp4"
    kept = tmp_path / "input" / "upload_keep_old_clip.mp4"
    fresh = tmp_path / "input" / "upload_new_clip.mp4"
    staged = tmp_path / "input" / "clip.mov"
    for f in (expired, kept, fresh, staged):
        f.write_text("x")
    os.utime(expired, (old, old))
    os.utime(kept, (old, old))
    os.utime(staged, (old, old))
    swept = pixop.sweep_ephemeral_uploads(c)
    assert swept == ["upload_old_clip.mp4"]
    assert not expired.exists()
    assert kept.exists() and fresh.exists() and staged.exists()


# --- start routes: combo resolution -------------------------------------------

def test_start_route_rejects_unknown_combo(tmp_path, monkeypatch):
    monkeypatch.setattr(pixop, "config", lambda: _cfg(tmp_path))
    monkeypatch.setattr(pixop, "preflight",
                        lambda c=None: {"ok_transcode": True, "inputs": ["clip.mov"],
                                        "presets": [], "combos": {}, "reasons": []})
    _stage_templates(tmp_path)
    r = client.post("/enhance-run/start",
                    data={"input_name": "clip.mov", "output_format": "sdr",
                          "sr_target": "8k"}, headers=LAB)
    assert r.status_code == 400
    assert "not available" in r.json()["error"]


def test_start_route_requires_some_preset(monkeypatch):
    monkeypatch.setattr(pixop, "preflight",
                        lambda c=None: {"ok_transcode": True, "inputs": ["clip.mov"],
                                        "presets": [], "combos": {}, "reasons": []})
    r = client.post("/enhance-run/start",
                    data={"input_name": "clip.mov"}, headers=LAB)
    assert r.status_code == 400
    assert "No preset" in r.json()["error"]


# --- page: new controls ---------------------------------------------------------

def test_enhance_page_has_cr064_controls():
    r = client.get("/enhance-run", headers=LAB)
    assert r.status_code == 200
    assert "Super Resolution" in r.text
    assert 'name="outFmt"' in r.text
    assert "srSel" in r.text
    assert "preSel" not in r.text             # raw preset select is gone
    assert "prev-runs" in r.text              # previous-runs section present
    assert "viewing environment" in r.text    # HDR footnote
    assert "upFile" in r.text                 # upload control
    assert "wl-1x" in r.text                  # 1× native video sizing


# --- persist: summarisers + CSV --------------------------------------------------

def test_summarise_enhance_single():
    rec = {"job_id": "j1", "saved_at": "2026-06-10T20:00:00", "mode": "enhance",
           "result": {"preset_key": "generated/owl_sdr_hd_20mbps.args",
                      "preset_label": "Partner GPU transcode / upscale",
                      "input_name": "clip.mov", "live": True,
                      "energy": {"delta_e_wh": 1.23, "delta_t_s": 31.0,
                                 "confidence": {"flag": "🟢", "label": "Repeatable"}},
                      "vqa": {"score": 8.61}}}
    s = persist._summarise("enhance", rec)
    assert "unrecognised_mode" not in s
    assert s["mode"] == "enhance"
    assert s["delta_e_wh"] == 1.23
    assert s["confidence"] == "🟢"
    assert s["vqa_score"] == 8.61
    assert s["preset_key"] == "generated/owl_sdr_hd_20mbps.args"


def test_summarise_enhance_compare():
    rec = {"job_id": "j2", "saved_at": "t", "mode": "enhance_compare",
           "preset_key": "generated/owl_sdr_hd_20mbps.args",
           "input_name": "clip.mov", "ff_filter": "lanczos",
           "target_res": "1920x1080",
           "comparison": {"ml_delta_e_wh": 2.0, "ff_delta_e_wh": 1.0,
                          "energy_ratio": 2.0},
           "ml": {"result": {"energy": {"confidence": {"flag": "🟢"}},
                             "vqa": {"score": 9.1}}},
           "ffmpeg": {"result": {"energy": {"confidence": {"flag": "🟡"}},
                                 "vqa": {"score": 8.7}}}}
    s = persist._summarise("enhance", rec)
    assert "unrecognised_mode" not in s
    assert s["energy_ratio"] == 2.0
    assert s["ml_confidence"] == "🟢" and s["ff_confidence"] == "🟡"
    assert s["ml_vqa_score"] == 9.1 and s["ff_vqa_score"] == 8.7


def test_enhance_csv_two_rows_for_compare():
    rec = {"job_id": "j2", "saved_at": "t", "mode": "enhance_compare",
           "input_name": "clip.mov",
           "ml": {"result": {"preset_key": "p", "preset_origin": "generated",
                             "live": True, "output_size_mb": 10.0,
                             "stream": {"width": 1920, "height": 1080},
                             "energy": {"delta_e_wh": 2.0, "confidence": {"flag": "🟢"}},
                             "transcode": {"docker_cmd": "docker run …"}}},
           "ffmpeg": {"result": {"preset_key": "ffmpeg:lanczos",
                                 "energy": {"delta_e_wh": 1.0,
                                            "confidence": {"flag": "🟡"}}}}}
    csv_text = persist.to_csv("enhance", rec)
    lines = [l for l in csv_text.splitlines() if l and not l.startswith("#")]
    assert len(lines) == 3                    # header + ai + ffmpeg
    assert lines[1].split(",")[3] == "ai"
    assert lines[2].split(",")[3] == "ffmpeg"


def test_results_list_accepts_enhance():
    r = client.get("/results/enhance/list", headers=LAB)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


# --- CR-064: advanced args editor (custom presets) ---------------------------

def test_write_custom_preset_and_origin(tmp_path, monkeypatch):
    monkeypatch.setattr(pixop, "config", lambda: _cfg(tmp_path))
    name = pixop.write_custom_preset("-c hevc\n--cbr 1234", "abcd1234")
    assert name == "custom/custom_abcd1234.args"
    assert (tmp_path / "presets" / name).read_text() == "-c hevc\n--cbr 1234\n"
    assert pixop.preset_origin(name) == "custom"


def test_preset_known_custom_strict(tmp_path, monkeypatch):
    monkeypatch.setattr(pixop, "config", lambda: _cfg(tmp_path))
    pf = {"presets": [], "combos": {}}
    name = pixop.write_custom_preset("-c hevc", "j1")
    assert pixop._preset_known(name, pf, _cfg(tmp_path)) is True
    # Nonexistent custom file, and traversal-shaped names, are rejected.
    assert pixop._preset_known("custom/custom_nope.args", pf, _cfg(tmp_path)) is False
    assert pixop._preset_known("custom/../p.args", pf, _cfg(tmp_path)) is False
    assert pixop._preset_known("custom/custom_../x.args", pf, _cfg(tmp_path)) is False


def test_start_route_custom_args_writes_preset(tmp_path, monkeypatch):
    monkeypatch.setattr(pixop, "config", lambda: _cfg(tmp_path))
    _stage(tmp_path, preset=True, inp=True, license=True)
    _stage_templates(tmp_path)
    monkeypatch.setattr(pixop, "_image_present", lambda c: True)
    # Stub the queue (its jobs dict only exists after app startup) — the
    # route's custom-args file write happens BEFORE enqueue, which is what
    # this test pins.
    monkeypatch.setattr(routes_enhance.queue_control, "enqueue",
                        lambda job_id, t, l, coro, request=None, page=None: 1)

    r = client.post("/enhance-run/start",
                    data={"input_name": "clip.mov", "output_format": "sdr",
                          "sr_target": "hd", "custom_args": "-c hevc\n--cbr 9999"},
                    headers=LAB)
    assert r.status_code == 200
    job_id = r.json()["job_id"]
    custom = tmp_path / "presets" / "custom" / f"custom_{job_id}.args"
    assert custom.read_text() == "-c hevc\n--cbr 9999\n"


def test_enhance_page_has_args_editor():
    r = client.get("/enhance-run", headers=LAB)
    assert "Encoder command" in r.text
    assert "argsBox" in r.text


# --- CR-064: keep-after-run checkbox + Lab delete of uploads ------------------

def test_upload_keep_flag_encodes_name(tmp_path, monkeypatch):
    monkeypatch.setattr(pixop, "config", lambda: _cfg(tmp_path))
    monkeypatch.setattr(pixop, "probe_input_stream", lambda p: {"duration_s": 10.0})
    r = client.post("/enhance-run/upload", data={"keep": "true"},
                    files={"file": ("c.mp4", b"x" * 16, "video/mp4")}, headers=LAB)
    assert r.status_code == 200
    assert r.json()["name"].startswith("upload_keep_")
    r2 = client.post("/enhance-run/upload", data={"keep": "false"},
                     files={"file": ("c.mp4", b"x" * 16, "video/mp4")}, headers=LAB)
    assert r2.json()["name"].startswith("upload_")
    assert not r2.json()["name"].startswith("upload_keep_")


def test_upload_is_ephemeral_rule():
    assert routes_enhance._upload_is_ephemeral("upload_ab12_clip.mp4") is True
    assert routes_enhance._upload_is_ephemeral("upload_keep_ab12_clip.mp4") is False
    assert routes_enhance._upload_is_ephemeral("meridian_hd_p3pq_clip_30s.mov") is False


def test_input_delete_lab_only_and_uploads_only(tmp_path, monkeypatch):
    monkeypatch.setattr(pixop, "config", lambda: _cfg(tmp_path))
    (tmp_path / "input").mkdir(parents=True, exist_ok=True)
    up = tmp_path / "input" / "upload_keep_aa_clip.mp4"
    up.write_text("x")
    staged = tmp_path / "input" / "clip.mov"
    staged.write_text("x")
    # Anonymous: gated out entirely (SETTINGS_WRITE).
    r = client.delete("/enhance-run/input/upload_keep_aa_clip.mp4", headers=ANON)
    assert r.status_code == 403
    # Staged clips are protected.
    r = client.delete("/enhance-run/input/clip.mov", headers=LAB)
    assert r.status_code == 400
    assert staged.exists()
    # Traversal-shaped names rejected.
    r = client.delete("/enhance-run/input/..%2Fupload_x.mp4", headers=LAB)
    assert r.status_code in (400, 404)
    # Uploaded clip deletes.
    r = client.delete("/enhance-run/input/upload_keep_aa_clip.mp4", headers=LAB)
    assert r.status_code == 200 and r.json()["ok"] is True
    assert not up.exists()
    # Already gone → 404.
    r = client.delete("/enhance-run/input/upload_keep_aa_clip.mp4", headers=LAB)
    assert r.status_code == 404


def test_page_keep_checkbox_and_delete_button_by_tier(monkeypatch):
    r = client.get("/enhance-run", headers=LAB)
    assert 'id="keepTog" checked' in r.text     # Lab default: keep
    assert 'id="delBtn"' in r.text              # Lab sees the ✕
    monkeypatch.setattr(audience, "tier", lambda req: audience.Tier.Member)
    r = client.get("/enhance-run", headers=LAB)
    assert 'id="keepTog" checked' not in r.text  # Member default: ephemeral
    assert "keepTog" in r.text
    # The ✕ BUTTON is absent for Members (the JS that references delBtn is
    # static and null-guarded, so check the element, not the string).
    assert 'id="delBtn"' not in r.text


def test_settings_page_exposes_enhance_upload_caps():
    r = client.get("/settings", headers=LAB)
    assert r.status_code == 200
    assert 'id="enhance_upload_max_mb"' in r.text
    assert 'id="enhance_upload_max_duration_s"' in r.text
    assert 'id="enhance_upload_ttl_h"' in r.text
