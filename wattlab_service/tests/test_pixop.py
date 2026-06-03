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

import pixop
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

    jobs = {"j1": {}}
    res = asyncio.run(
        pixop.run_enhance_measurement("clip.mov", "p.args", "j1", jobs))

    assert res["mode"] == "enhance"
    e = res["result"]["energy"]
    assert e["delta_w"] == 81.0          # 131 mean − 50 base
    assert e["delta_e_wh"] is not None
    assert "flag" in e["confidence"]
    assert res["result"]["stream"]["codec"] == "hevc"
    assert res["result"]["thermals"]["gpu_peak"] == 71.0
    # Realtime / Live verdict rides along on the result.
    assert res["result"]["realtime"]["verdict"] == "live"
    assert res["result"]["realtime"]["rtf_steady"] == 2.16
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
