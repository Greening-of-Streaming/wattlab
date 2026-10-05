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


def test_panel_hidden_for_anonymous(registry):
    html = client.get("/video", headers=_ANON).text
    assert 'id="remote-hosts-panel"' not in html and "runRemote('gos2'" not in html


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
    for page in ("/llm", "/image"):
        assert 'id="remote-hosts-panel"' not in client.get(page, headers=_ANON).text
