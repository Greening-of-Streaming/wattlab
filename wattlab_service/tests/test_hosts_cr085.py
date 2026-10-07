"""CR-085 — compute-host registry, per-host meters, host/engine provenance,
and the Lab-only /video remote-engine panel."""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient

import hosts
import main
import persist
import power
import remote_ai
import remote_video
import routes_video

_LAB = {"x-real-ip": "127.0.0.1"}
_ANON = {"x-real-ip": "8.8.8.8"}
client = TestClient(main.app)

GOS2 = {
    "enabled": True, "label": "GoS2", "chip": "Apple M6", "machine": "Mac mini",
    "gpu_vendor": "apple", "ssh": "gos@10.0.0.9", "ssh_key": "/k",
    "meters": ["10.0.0.1", "10.0.0.2"], "ffmpeg": "/opt/homebrew/bin/ffmpeg",
    "workdir": "owl",
    "engines": {
        "cpu": {"kind": "cpu", "label": "CPU (software)", "codecs": {
            "h264": {"encoder": "libx264", "args": ["-g", "{gop}"]},
            "av1": {"encoder": "libsvtav1", "args": []}}},
        "hw": {"kind": "hw", "label": "Apple media engine", "codecs": {
            "h264": {"encoder": "h264_videotoolbox", "args": ["-g", "{gop}", "-allow_sw", "0"]}}},
    },
}


@pytest.fixture
def registry(monkeypatch):
    monkeypatch.setattr(hosts, "all_remote", lambda: {"gos2": dict(GOS2)})
    return hosts.get("gos2")


# --- registry -------------------------------------------------------------------

def test_registry_offers_engines_in_order(registry):
    assert hosts.offered(registry) == [
        ("cpu", "CPU (software)", "cpu", ["h264", "av1"]),
        ("hw", "Apple media engine", "hw", ["h264"]),
    ]


def test_disabled_host_is_invisible(monkeypatch):
    monkeypatch.setattr(hosts, "all_remote", lambda: {"gos2": {**GOS2, "enabled": False}})
    assert hosts.remote_hosts() == {} and hosts.get("gos2") is None


def test_encode_cmd_mirrors_presets_and_substitutes_gop(registry):
    cmd = hosts.encode_cmd(registry, "hw", "h264", "owl/test_content/a.mp4",
                           "owl/out/b.mp4", 4000, 120)
    assert "-c:v h264_videotoolbox -b:v 4000k -g 120 -allow_sw 0" in cmd
    assert "-vf scale=-2:1080 -c:a aac -b:a 128k owl/out/b.mp4" in cmd
    with pytest.raises(ValueError):
        hosts.encode_cmd(registry, "hw", "av1", "a", "b", 1500, 120)


# --- provenance -------------------------------------------------------------------

def test_old_results_read_as_gos1():
    assert hosts.result_host({"mode": "single"})["id"] == "gos1"
    assert hosts.result_host({"host": {"id": "gos2", "label": "GoS2"}})["id"] == "gos2"


def test_side_engine_derives_from_preset_and_the_results_own_gpu():
    amd_era = {"gpu_hardware": {"name": "AMD Radeon RX 7800 XT"}}
    e = hosts.side_engine({"preset_key": "h265_gpu"}, amd_era)
    assert e["kind"] == "hw" and "7800 XT" in e["label"]
    assert hosts.side_engine({"preset_key": "av1_cpu"})["encoder"] == "libsvtav1"
    stamped = {"preset_key": "x", "engine": {"id": "hw", "label": "Apple media engine"}}
    assert hosts.side_engine(stamped)["label"] == "Apple media engine"


def test_local_result_is_stamped_gos1(tmp_path, monkeypatch):
    monkeypatch.setattr(persist, "RESULTS_DIR", tmp_path)
    persist.save_result("video", "loc1", {"mode": "single"}, visitor_key=None)
    d = json.loads(next((tmp_path / "video").glob("*_loc1.json")).read_text())
    assert d["host"]["id"] == "gos1" and d["host"]["remote"] is False
    assert d["envelope_version"] == 2


def test_remote_result_never_carries_gos1_hardware(tmp_path, monkeypatch, registry):
    monkeypatch.setattr(persist, "RESULTS_DIR", tmp_path)
    persist.save_result("video", "gos2-abc", {"mode": "single",
                        "host": hosts.identity(registry)}, visitor_key=None)
    d = json.loads(next((tmp_path / "video").glob("*_gos2-abc.json")).read_text())
    assert d["host"]["id"] == "gos2"
    assert d["gpu_hardware"] == {"vendor": "apple", "name": "Apple M6", "host": "gos2"}
    assert d["power_hardware"]["meter_ips"] == ["10.0.0.1", "10.0.0.2"]
    assert d["power_hardware"]["host"] == "gos2"


def test_summary_carries_host_and_engine():
    s = persist._summarise("video", {"mode": "single", "result": {
        "preset_key": "gpu", "preset_label": "H.264 GPU", "energy": {}},
        "gpu_hardware": {"name": "NVIDIA GeForce RTX 5080"}})
    assert s["host"] == "GoS1" and "RTX 5080" in s["engine"]


# --- per-host meters --------------------------------------------------------------

def test_use_meters_is_context_local():
    base = power._meter_ips()

    async def go():
        seen = {}
        with power.use_meters(["10.0.0.1", "10.0.0.2"]):
            async def inner():
                seen["task"] = power._meter_ips()
            t = asyncio.create_task(inner())   # sampler tasks inherit the override
        await t
        seen["after"] = power._meter_ips()
        return seen

    seen = asyncio.run(go())
    assert seen["task"] == ["10.0.0.1", "10.0.0.2"]
    assert seen["after"] == base


def test_remote_baseline_never_moves_gos1_idle_floor(registry, monkeypatch):
    async def fake_sample_baseline(polls, read_watts, **kw):
        assert power._meter_ips() == ["10.0.0.1", "10.0.0.2"]
        power.LAST_W_BASE = 1.35            # what the real sampler does
        return {"w_base": 1.35, "samples_w": [1.35] * polls}
    monkeypatch.setattr(power, "sample_baseline", fake_sample_baseline)
    power.LAST_W_BASE = 79.0
    b = asyncio.run(remote_video._baseline(registry, 5))
    assert b["w_base"] == 1.35
    assert power.LAST_W_BASE == 79.0        # GoS1's floor untouched
    assert remote_video._HOST_FLOOR["gos2"] == 1.35


# --- /video panel + route -----------------------------------------------------------

def test_panel_renders_from_registry_for_lab(registry):
    html = client.get("/video", headers=_LAB).text
    assert 'id="remote-hosts-panel"' in html and "Apple media engine" in html
    assert "runRemote(&#39;gos2&#39;" in html or "runRemote('gos2'" in html
    assert "CPU (software) vs Apple media engine" in html


def test_panel_visible_but_locked_for_anonymous(registry):
    """Owner 2026-10-07: every tier sees the Other-machines panel; only Lab can
    use it. Locked = dimmed, every button disabled, a plain Lab-only badge
    (no Join-GoS pitch: membership doesn't unlock it), no pair tick-box/JS."""
    import re
    html = client.get("/video", headers=_ANON).text
    assert 'id="remote-hosts-panel" class="lock-block"' in html and "🔒 Lab only" in html
    start = html.rindex("<div", 0, html.index('id="remote-hosts-panel"'))
    depth, i = 0, start
    for m in re.finditer(r"<div\b|</div>", html[start:]):
        depth += 1 if m.group(0) != "</div>" else -1
        if depth == 0:
            i = start + m.end(); break
    panel = html[start:i]
    btns = re.findall(r'<button class="remote-btn[^"]*"([^>]*)>', panel)
    assert btns and all("disabled" in b for b in btns)
    assert "Join GoS" not in panel and "also-local-gos2" not in panel
    lab = client.get("/video", headers=_LAB).text
    assert 'class="lock-block"' not in lab[lab.index('id="remote-hosts-panel"'):][:80]


def test_panel_absent_without_hosts(monkeypatch):
    monkeypatch.setattr(hosts, "all_remote", lambda: {})
    assert 'id="remote-hosts-panel"' not in client.get("/video", headers=_LAB).text


def test_remote_route_is_lab_only(registry):
    r = client.post("/video/remote", headers=_ANON, data={
        "source_key": "meridian_120s", "host": "gos2", "codec": "h264", "engine": "hw"})
    assert r.status_code == 403


def test_remote_route_validates_against_registry(registry):
    bad_host = client.post("/video/remote", headers=_LAB, data={
        "source_key": "meridian_120s", "host": "gos9", "codec": "h264", "engine": "hw"})
    assert bad_host.status_code == 400
    no_encoder = client.post("/video/remote", headers=_LAB, data={
        "source_key": "meridian_120s", "host": "gos2", "codec": "av1", "engine": "hw"})
    assert no_encoder.status_code == 400


def test_analyse_accepts_remote_shaped_sides():
    """Regression (first live GoS2 pair, 2026-10-05): analyse() indexes the
    full thermals key set — remote sides must carry it (as None)."""
    from video import analyse
    th = {**{k: None for k in remote_video.REMOTE_THERMAL_KEYS}, "note": "x"}
    def side(key, wh, t):
        return {"preset_key": key, "preset_label": key, "thermals": th,
                "energy": {"delta_e_wh": wh, "delta_t_s": t, "delta_w": 30.0, "w_base": 1.35, "w_task": 31.35, "confidence": {"flag": "🟢"}}}
    a = analyse(side("gos2_h264_cpu", 0.5, 40.0), side("gos2_h264_gpu", 0.17, 20.0))
    assert a["energy_winner"] == "GPU" and a["finding"]


# --- Part 3: remote AI routes ------------------------------------------------------

def test_remote_ai_routes_are_lab_only(registry):
    assert client.post("/image/remote", headers=_ANON,
                       data={"host": "gos2", "model_key": "sd-turbo"}).status_code == 403
    assert client.post("/llm/remote", headers=_ANON,
                       data={"host": "gos2", "model_key": "x", "task_key": "T2"}).status_code == 403


def test_remote_ai_routes_need_capable_host(registry):
    # GOS2 test entry declares neither "python" nor "ollama"
    assert client.post("/image/remote", headers=_LAB,
                       data={"host": "gos2", "model_key": "sd-turbo"}).status_code == 400
    assert client.post("/llm/remote", headers=_LAB,
                       data={"host": "gos2", "model_key": "x", "task_key": "T2"}).status_code == 400


def test_llm_url_param_defaults_to_local(monkeypatch):
    import llm
    seen = {}
    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def __iter__(self): return iter([b'{"response":"hi","done":true,"eval_count":1,"prompt_eval_count":1}'])
    def fake_urlopen(req, timeout=0):
        seen["url"] = req.full_url
        return _Resp()
    monkeypatch.setattr(llm.urllib.request, "urlopen", fake_urlopen)
    llm.run_inference_streaming("m", "p")
    assert seen["url"] == llm.OLLAMA_URL
    llm.run_inference_streaming("m", "p", url="http://127.0.0.1:5555/api/generate")
    assert seen["url"].startswith("http://127.0.0.1:5555")


def test_llm_remote_runtime_validation(monkeypatch):
    monkeypatch.setattr(hosts, "all_remote", lambda: {"gos2": {**GOS2, "ollama": True,
                        "mlx_models": {"qwen3:4b": "mlx-community/Qwen3-4B-4bit"}}})
    bad = client.post("/llm/remote", headers=_LAB, data={
        "host": "gos2", "model_key": "qwen3:4b", "task_key": "T2", "runtime": "vllm"})
    assert bad.status_code == 400
    import routes_llm
    monkeypatch.setattr(routes_llm, "MODELS", {"qwen3:4b": {"label": "Qwen3 4B"},
                                               "qwen3:1.7b": {"label": "Qwen3 1.7B"}})
    no_mlx = client.post("/llm/remote", headers=_LAB, data={
        "host": "gos2", "model_key": "qwen3:1.7b", "task_key": "T2", "runtime": "mlx"})
    assert no_mlx.status_code == 400


def test_image_bench_is_lab_only_and_validated(registry):
    assert client.post("/image/bench", headers=_ANON, data={"host": "local"}).status_code == 403
    assert client.post("/image/bench", headers=_LAB, data={"host": "local", "batch": 500}).status_code == 400
    assert client.post("/image/bench", headers=_LAB, data={"host": "gos2", "batch": 10}).status_code == 400  # no python


def test_llm_and_image_panels_follow_registry(monkeypatch):
    monkeypatch.setattr(hosts, "all_remote", lambda: {"gos2": {**GOS2, "ollama": True, "python": "/p",
                        "mlx_models": {"qwen3:4b": "mlx-community/Qwen3-4B-4bit"}}})
    llm_lab = client.get("/llm", headers=_LAB).text
    assert 'id="remote-hosts-panel"' in llm_lab and "runRemoteLLM('gos2','mlx')" in llm_lab
    img_lab = client.get("/image", headers=_LAB).text
    assert "runRemoteImage('gos2')" in img_lab
    for page in ("/llm", "/image"):   # owner 2026-10-07: shown to all tiers, locked without Lab
        assert 'id="remote-hosts-panel" class="lock-block"' in client.get(page, headers=_ANON).text


# --- warm-model image session ------------------------------------------------------

def test_per_prompt_breakdown_assigns_samples_by_span():
    readings = [(10.5, 30.0), (11.5, 32.0), (12.5, 40.0), (13.5, 42.0)]
    events = [(11.0, 0), (12.0, 0), (13.0, 1), (14.0, 1)]   # last img of p0 at 12.0, p1 at 14.0
    out = remote_ai.per_prompt_breakdown(readings, events, t_go=10.0, w_base=2.0,
                                         n_prompts=2, per_prompt=2)
    assert [o["polls"] for o in out] == [2, 2]
    assert out[0]["delta_w"] == 29.0 and out[1]["delta_w"] == 39.0
    assert out[0]["span_s"] == 2.0


def test_image_session_route_is_lab_only_and_validated(registry):
    assert client.post("/image/session", headers=_ANON, data={"host": "local"}).status_code == 403
    assert client.post("/image/session", headers=_LAB,
                       data={"host": "local", "per_prompt": 0}).status_code == 400
    assert client.post("/image/session", headers=_LAB, data={"host": "gos2"}).status_code == 400


def test_session_runner_protocol_with_fake_runner(tmp_path, monkeypatch):
    """End-to-end over the real subprocess/event plumbing with a fake runner:
    the warm baseline is taken while the runner waits, and the task window
    covers only GO → done."""
    import image_gen, video
    fake = tmp_path / "fake_runner.py"
    fake.write_text(
        "import json,sys,time\n"
        "a=json.loads(sys.argv[1]); print(json.dumps({'ev':'ready','load_s':1.0,'warmup_s':0.5,'torch':'x','diffusers':'y'}),flush=True)\n"
        "for l in sys.stdin:\n"
        "    if l.strip()=='GO': break\n"
        "for p in range(len(a['prompts'])):\n"
        "    for k in range(a['per_prompt']):\n"
        "        time.sleep(0.05); print(json.dumps({'ev':'img','p':p,'k':k}),flush=True)\n"
        "print(json.dumps({'ev':'done','gen_s':0.2,'n_images':len(a['prompts'])*a['per_prompt'],'s_per_image':0.05,'per_prompt_s':[0.1,0.1],'device':'cuda'}),flush=True)\n")
    monkeypatch.setattr(remote_ai, "RUNNER_LOCAL", fake)
    monkeypatch.setattr(image_gen, "IMAGE_MODELS", {"m": {"label": "M", "repo": "r", "gpu_steps": 2,
                                                          "size_px": 64, "params": "1"}})
    monkeypatch.setattr(video, "focus_mode_enter", lambda: [])
    monkeypatch.setattr(video, "focus_mode_exit", lambda s: None)
    calls = []
    async def fake_baseline(polls, read_watts, **kw):
        calls.append("baseline")
        return {"w_base": 80.0, "samples_w": [80.0] * polls}
    async def fake_task(stop, read_watts, tuples=False, **kw):
        out = []
        while not stop.is_set():
            out.append((__import__("time").time(), 250.0))
            await asyncio.sleep(0.02)
        return out
    monkeypatch.setattr(power, "sample_baseline", fake_baseline)
    monkeypatch.setattr(power, "sample_task", fake_task)
    r = asyncio.run(remote_ai.run_image_session("local", "m", per_prompt=2, settle_s=0,
                                                prompts=["a", "b"]))
    assert calls == ["baseline", "baseline"]                 # cold, then warm
    assert r["mode"] == "session" and r["generation"]["n_images"] == 4
    assert r["energy"]["delta_w"] == 170.0                   # 250 − warm 80
    assert len(r["per_prompt"]) == 2 and r["host"]["id"] == "gos1"
    assert r["energy_vs_cold_idle"]["delta_w"] == 170.0     # fake cold == warm here


# --- live power follows the job's host ----------------------------------------------

def test_job_status_reports_remote_host_live_power(monkeypatch):
    import runtime, time as _t
    runtime.jobs["gos2-live1"] = {"status": "running", "stage": "generating",
                                  "meter_ip": "10.0.0.1", "power_host": "GoS2"}
    try:
        monkeypatch.setitem(power.LAST_READING, "10.0.0.1", (31.5, _t.time()))
        st = runtime.job_status("gos2-live1")
        assert st["watts"] == 31.5 and st["watts_host"] == "GoS2"
        monkeypatch.setitem(power.LAST_READING, "10.0.0.1", (31.5, _t.time() - 60))   # stale
        st = runtime.job_status("gos2-live1")
        assert st["watts"] is None and st["watts_host"] == "GoS2"   # never GoS1's number
    finally:
        runtime.jobs.pop("gos2-live1", None)


def test_local_job_status_unchanged():
    import runtime
    runtime.jobs["loc-live"] = {"status": "running"}
    try:
        st = runtime.job_status("loc-live")
        assert "watts_host" not in st and "watts" in st
    finally:
        runtime.jobs.pop("loc-live", None)


def test_remote_ai_results_get_no_cross_machine_anchor(tmp_path, monkeypatch, registry):
    monkeypatch.setattr(persist, "RESULTS_DIR", tmp_path)
    for jid, host in (("loc-anc", None), ("gos2-anc", hosts.identity(registry))):
        data = {"mode": "gpu", "energy": {"delta_e_wh": 0.5}}
        if host:
            data["host"] = host
        persist.save_result("image", jid, data, visitor_key=None)
    loc = json.loads(next((tmp_path / "image").glob("*_loc-anc.json")).read_text())
    rem = json.loads(next((tmp_path / "image").glob("*_gos2-anc.json")).read_text())
    assert "video_relative" in loc["energy"] and "H.265" not in loc["energy"]["video_relative"]["text"]
    assert "video_relative" not in rem["energy"]


def test_remote_image_button_sends_the_prompt(monkeypatch):
    """Bug 2026-10-05: the GoS2 image button ignored the prompt box."""
    monkeypatch.setattr(hosts, "all_remote", lambda: {"gos2": {**GOS2, "python": "/p"}})
    html = client.get("/image", headers=_LAB).text
    i = html.index("async function runRemoteImage")
    js = html[i:i + 1200]
    assert "getElementById('prompt')" in js and "&prompt=" in js


def test_remote_image_panel_offers_gos1_pair_tickbox(monkeypatch):
    monkeypatch.setattr(hosts, "all_remote", lambda: {"gos2": {**GOS2, "python": "/p"}})
    html = client.get("/image", headers=_LAB).text
    assert 'id="also-local-gos2"' in html and "checked" not in html.split('id="also-local-gos2"')[1][:20]
    assert "host=local&model_key=" in html and "/image/session" in html   # clean session on both sides


def test_llm_panel_offers_gos1_pair_tickbox(monkeypatch):
    monkeypatch.setattr(hosts, "all_remote", lambda: {"gos2": {**GOS2, "ollama": True}})
    html = client.get("/llm", headers=_LAB).text
    assert 'id="also-local-gos2"' in html and "runs.push(owlRunLocal(d2.job_id))" in html
    assert "f2.append('device', 'gpu')" in html            # companion forced to GPU


# --- VMAF + probe on the host (no file crosses the network) -------------------------

def test_remote_vmaf_uses_the_same_filter_graph_as_gos1(registry, monkeypatch):
    import quality
    host = {**registry, "vmaf": {"ffmpeg": "/opt/homebrew/bin/ffmpeg", "model": "/m/vmaf_v1.0.16_3d0h.json"}}
    seen = {}
    class R:  # fake ssh result: libvmaf json log on stdout
        stdout = '{"pooled_metrics": {"vmaf": {"mean": 88.6123}}}'
    def fake_run(h, cmd, timeout=60):
        seen["cmd"] = cmd
        return R()
    monkeypatch.setattr(hosts, "run", fake_run)
    out = hosts.remote_vmaf(host, "owl/out/x.mp4", "owl/test_content/r.mp4", (1920, 1080),
                            {"vmaf_n_threads": 12, "vmaf_n_subsample": 1})
    assert out == {"vmaf": 88.61, "vmaf_model": "vmaf_v1.0.16_3d0h", "vmaf_scored_on": "gos2",
                   "vmaf_scorer": "libvmaf (host)"}
    expected = quality.vmaf_lavfi(1920, 1080, 12, 1, "path=/m/vmaf_v1.0.16_3d0h.json", "LOG")
    graph = expected.split("log_path=")[0]
    assert graph in seen["cmd"].replace("'", "")       # identical graph up to the log path


def test_vmaf_on_host_skips_fetch_and_cleans_up(registry, monkeypatch):
    host = {**registry, "vmaf": {"model": "/m/v.json"}}
    calls = []
    monkeypatch.setattr(hosts, "remote_vmaf", lambda h, d, r, dims, s: {"vmaf": 90.0, "vmaf_scored_on": "gos2"})
    monkeypatch.setattr(hosts, "run", lambda h, cmd, timeout=60: calls.append(cmd))
    sides = [{"stream": {"width": 1920, "height": 1080}, "_remote_out": "owl/out/a.mp4"}]
    asyncio.run(remote_video._attach_vmaf_on_host(host, sides, "owl/test_content/r.mp4",
                                                  {"vmaf_enabled": True}, None, "j"))
    assert sides[0]["vmaf"] == 90.0 and "_remote_out" not in sides[0]
    assert any("rm -f owl/out/a.mp4" in c for c in calls)


def test_probe_parsers_are_shared():
    import video
    st = video.stream_from_probe('{"streams":[{"codec_name":"h264","width":1920,"height":1080,"level":40,"bit_rate":"4000000"}]}',
                                 video.gop_from_flags("K__\n___\n___\nK__\n___\n___\nK__"))
    assert st["codec"] == "h264" and st["bit_rate_bps"] == 4000000 and st["gop_avg"] == 3.0


def test_pair_engines_explicit_and_deterministic():
    h = {"engines": {"cpu": {"kind": "cpu", "codecs": {"h264": {}}},
                     "hw": {"kind": "hw", "codecs": {"h264": {}}},
                     "hw_vbr": {"kind": "hw", "codecs": {"h264": {}}}}}
    assert hosts.pair_engines(h, "h264") == ("cpu", "hw")                  # first of each kind
    assert hosts.pair_engines({**h, "pair": {"hw": "hw_vbr"}}, "h264") == ("cpu", "hw_vbr")
    assert hosts.pair_engines(h, "av1") is None



def _panel_html(html):
    import re
    start = html.rindex("<div", 0, html.index('id="remote-hosts-panel"'))
    depth = 0
    for m in re.finditer(r"<div\b|</div>", html[start:]):
        depth += 1 if m.group(0) != "</div>" else -1
        if depth == 0:
            return html[start:start + m.end()]
    return html[start:]


def test_ai_panels_visible_but_locked_for_anonymous(monkeypatch):
    """Owner 2026-10-07: /llm and /image get the /video treatment."""
    import re
    monkeypatch.setattr(hosts, "all_remote", lambda: {"gos2": {**GOS2, "ollama": True, "python": "/p"}})
    for page in ("/llm", "/image"):
        html = client.get(page, headers=_ANON).text
        assert 'id="remote-hosts-panel" class="lock-block"' in html and "🔒 Lab only" in html, page
        panel = _panel_html(html)
        btns = re.findall(r'<button class="remote-btn"([^>]*)>', panel)
        assert btns and all("disabled" in b for b in btns), page
        assert "Join GoS" not in panel and "also-local-gos2" not in panel and "Tick the box" not in panel, page
        assert "function runRemote" not in html and "function owlRunTiles" not in html, page
        lab = client.get(page, headers=_LAB).text
        assert 'id="remote-hosts-panel" class=""' in lab and "function owlRunTiles" in lab, page
