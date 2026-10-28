"""MLX-native image engine (mflux) on a Mac node — same warm-model session as
the diffusers runner, so an MPS run and an MLX run differ only by the stack."""
import asyncio
import io
import json
import sys

import pytest
from fastapi.testclient import TestClient

import hosts
import image_gen
import main
import peer
import power
import remote_ai
import routes_peer
import settings as cfg

client = TestClient(main.app)
LAB = {"x-real-ip": "127.0.0.1"}
PEER_HOST = {"enabled": True, "label": "GoS2", "chip": "Apple M6", "driver": "peer",
             "url": "http://10.0.0.9:8000", "meters": ["10.0.0.1"], "engines": {}}
MODEL = {"m": {"label": "M", "repo": "r", "gpu_steps": 4, "size_px": 64, "params": "4B"}}


def _fake_runner(tmp_path):
    f = tmp_path / "fake_mflux.py"
    f.write_text(
        "import json,sys\n"
        "a=json.loads(sys.argv[1])\n"
        "print(json.dumps({'ev':'ready','load_s':2.0,'warmup_s':1.0,'mflux':'0.24.0','mlx':'0.33',"
        "'seen_model':a.get('mflux_model')}),flush=True)\n"
        "for l in sys.stdin:\n"
        "    if l.strip()=='GO': break\n"
        "for p in range(len(a['prompts'])):\n"
        "    for k in range(a['per_prompt']):\n"
        "        print(json.dumps({'ev':'img','p':p,'k':k}),flush=True)\n"
        "print(json.dumps({'ev':'done','gen_s':0.2,'n_images':len(a['prompts'])*a['per_prompt'],"
        "'s_per_image':0.05,'per_prompt_s':[0.1],'device':'mlx','peak_memory_gb':9.5}),flush=True)\n")
    return f


@pytest.fixture
def session_env(tmp_path, monkeypatch):
    import video
    monkeypatch.setattr(remote_ai, "RUNNER_MFLUX", _fake_runner(tmp_path))
    monkeypatch.setattr(remote_ai, "local_mflux_python", lambda: sys.executable)
    monkeypatch.setattr(remote_ai, "mlx_image_models", lambda: {"m": "flux2_klein_4b"})
    monkeypatch.setattr(image_gen, "IMAGE_MODELS", dict(MODEL))
    monkeypatch.setattr(video, "focus_mode_enter", lambda: [])
    monkeypatch.setattr(video, "focus_mode_exit", lambda s: None)

    async def fake_baseline(polls, read_watts, **kw):
        return {"w_base": 1.4, "samples_w": [1.4] * polls}

    async def fake_task(stop, read_watts, tuples=False, **kw):
        out = []
        while not stop.is_set():
            out.append((__import__("time").time(), 21.4))
            await asyncio.sleep(0.02)
        return out
    monkeypatch.setattr(power, "sample_baseline", fake_baseline)
    monkeypatch.setattr(power, "sample_task", fake_task)


def test_mflux_session_runs_the_mlx_runner_and_stamps_the_stack(session_env):
    r = asyncio.run(remote_ai.run_image_session("local", "m", per_prompt=2, settle_s=0,
                                                prompts=["a"], runtime="mflux"))
    assert r["mode"] == "session" and r["generation"]["n_images"] == 2
    assert "MLX · mflux" in r["engine"]["label"] and r["engine"]["runtime"] == "mflux 0.24.0"
    assert r["versions"] == {"mflux": "0.24.0", "mlx": "0.33"}
    assert r["model_mflux"] == "flux2_klein_4b" and r["peak_memory_gb"] == 9.5
    assert r["energy"]["delta_w"] == 20.0                   # same arithmetic as the MPS path
    assert "MLX (mflux)" in r["scope"]


def test_mflux_needs_a_registered_model_on_this_node(session_env, monkeypatch):
    with pytest.raises(ValueError, match="no MLX"):
        asyncio.run(remote_ai.run_image_session("local", "other", runtime="mflux"))
    with pytest.raises(ValueError, match="Unknown image runtime"):
        asyncio.run(remote_ai.run_image_session("local", "m", runtime="coreml"))


def test_diffusers_session_records_its_runtime_too(tmp_path, monkeypatch, session_env):
    f = tmp_path / "fake_diffusers.py"
    f.write_text(_fake_runner(tmp_path).read_text().replace(
        "'mflux':'0.24.0','mlx':'0.33'", "'torch':'2.14','diffusers':'0.37.1'"))
    monkeypatch.setattr(remote_ai, "RUNNER_LOCAL", f)
    r = asyncio.run(remote_ai.run_image_session("local", "m", per_prompt=1, settle_s=0, prompts=["a"]))
    assert r["engine"]["runtime"] == "diffusers 0.37.1" and "model_mflux" not in r


def test_session_route_validates_runtime(monkeypatch):
    monkeypatch.setattr(remote_ai, "mlx_image_models", lambda: {})
    key = next(iter(image_gen.IMAGE_MODELS), None)
    if key is None:
        pytest.skip("no image model cached on this host")
    for rt in ("coreml", "mflux"):          # unknown runtime; mflux not registered here
        r = client.post("/image/session", headers=LAB, data={"host": "local", "model_key": key,
                                                             "runtime": rt})
        assert r.status_code == 400, rt


def test_peer_info_advertises_mlx_image_models(monkeypatch):
    real = cfg.load
    monkeypatch.setattr(cfg, "load", lambda: {**real(), "local_mlx_image_models":
                                              {"flux2-klein-4b": "flux2_klein_4b"}})
    info = asyncio.run(routes_peer.peer_info())
    assert info["mlx_image_models"] == ["flux2-klein-4b"]


def test_image_panel_offers_mlx_only_when_the_peer_has_it(monkeypatch):
    monkeypatch.setattr(hosts, "all_remote", lambda: {"gos2": dict(PEER_HOST)})
    base = {"engines": {}, "llm_models": [], "mlx_models": [], "image_models": ["flux2-klein-4b"]}
    monkeypatch.setattr(peer, "info", lambda h, max_age=20: {**base, "mlx_image_models": ["flux2-klein-4b"]})
    t = client.get("/image", headers=LAB).text
    assert "runRemoteImage('gos2','mflux')" in t and '"gos2": ["flux2-klein-4b"]' in t
    monkeypatch.setattr(peer, "info", lambda h, max_age=20: dict(base))
    assert "runRemoteImage('gos2','mflux')" not in client.get("/image", headers=LAB).text


def test_runner_session_protocol(monkeypatch, capsys):
    """owl_mfluxgen.session in-process with the model faked: ready → GO → img × n → done."""
    sys.path.insert(0, str(remote_ai.RUNNER_MFLUX.parent))
    import owl_mfluxgen as rn
    from PIL import Image

    class Gen:                                    # mflux returns a wrapper with .image
        image = Image.new("RGB", (64, 64))

    class Model:
        def generate_image(self, **kw):
            assert kw["num_inference_steps"] == 4 and kw["width"] == 64
            return Gen()
    monkeypatch.setattr(rn, "_load", lambda a: Model())
    monkeypatch.setattr(rn, "_versions", lambda: {"mflux": "t", "mlx": "t"})
    monkeypatch.setattr(rn, "_peak_gb", lambda: 1.0)
    monkeypatch.setattr(sys, "stdin", io.StringIO("GO\n"))
    rn.session({"mode": "session", "mflux_model": "flux2_klein_4b", "prompts": ["a", "b"],
                "per_prompt": 2, "steps": 4, "size_px": 64, "warmup": 1})
    evs = [json.loads(l) for l in capsys.readouterr().out.splitlines()]
    assert evs[0]["ev"] == "ready" and evs[-1]["ev"] == "done"
    assert sum(e["ev"] == "img" for e in evs) == 4 and evs[-1]["n_images"] == 4
    assert evs[-1]["device"] == "mlx" and evs[-1]["thumb_b64_png"]
