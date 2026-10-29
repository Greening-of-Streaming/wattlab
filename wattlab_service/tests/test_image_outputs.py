"""Full-size session images: storage, peer fetch, same-seed pair score, routes
(owner 2026-10-29)."""
import io
import shutil

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import hosts
import image_outputs
import main
import peer
import routes_image

client = TestClient(main.app)
LAB = {"x-real-ip": "127.0.0.1"}


def _png(color=(10, 20, 30), noise_px=None):
    im = Image.new("RGB", (64, 64), color)
    if noise_px:
        for x, y in noise_px:
            im.putpixel((x, y), (255, 255, 255))
    b = io.BytesIO()
    im.save(b, format="PNG")
    return b.getvalue()


def _result(job_id, png, runtime="diffusers 0.37.1", host="gos1", prompt="a turbine", seed=1234):
    import base64
    outs = image_outputs.save(job_id, [{"p": 0, "seed": seed, "png_b64": base64.b64encode(png).decode()}])
    return {"job_id": job_id, "model_key": "flux2-klein-4b", "host": {"id": host},
            "engine": {"runtime": runtime}, "prompts": [prompt],
            "generation": {"size": 1024, "steps": 4}, "outputs": outs}


@pytest.fixture(autouse=True)
def _tmp_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(image_outputs, "DIR", tmp_path / "image_outputs")


def test_save_rejects_unsafe_job_ids():
    assert image_outputs.save("../etc", [{"p": 0, "png_b64": ""}]) == []
    assert image_outputs.local_path("../etc", 0) is None


def test_identical_images_pair_as_pixel_identical():
    a, b = _result("ja", _png()), _result("jb", _png())
    d = image_outputs.pair(a, b)
    assert d["comparable"] and d["pairs"][0]["identical"] and d["pairs"][0]["ssim"] == 1.0


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_near_identical_images_get_an_ssim_and_psnr():
    a = _result("ja", _png())
    b = _result("jb", _png(noise_px=[(3, 3), (40, 12), (60, 60)]))
    p = image_outputs.pair(a, b)["pairs"][0]
    assert not p["identical"] and 0.9 < p["ssim"] < 1.0 and p["psnr_db"] > 20


def test_mlx_vs_pytorch_noise_is_not_comparable():
    a = _result("ja", _png())
    b = _result("jb", _png(), runtime="mflux 0.24.0")
    d = image_outputs.pair(a, b)
    assert not d["comparable"] and "starting noise" in d["reasons"][0]


def test_different_seed_or_prompt_is_not_paired():
    a = _result("ja", _png())
    assert not image_outputs.pair(a, _result("jb", _png(), seed=99))["comparable"]
    assert not image_outputs.pair(a, _result("jc", _png(), prompt="other"))["comparable"]


def test_peer_image_is_fetched_once_and_cached(monkeypatch):
    r = {"job_id": "gos2-abc", "host": {"id": "gos2"}, "outputs": [{"p": 0}]}
    calls = []
    monkeypatch.setattr(hosts, "get", lambda hid: {"id": hid, "driver": "peer", "url": "http://x"})
    monkeypatch.setattr(peer, "forward", lambda h, m, path, **kw: calls.append(path) or (200, "image/png", _png()))
    f = image_outputs.fetch(r, 0)
    assert f is not None and f.read_bytes() == _png()
    assert image_outputs.fetch(r, 0) == f and calls == ["/peer/image-output/gos2-abc/0"]


def test_output_route_serves_inline_or_as_download(monkeypatch):
    r = _result("jroute", _png())
    monkeypatch.setattr(routes_image, "load_result", lambda t, j, visitor_key=None: r if j == "jroute" else None)
    v = client.get("/image/output/jroute/0.png", headers=LAB)
    assert v.status_code == 200 and v.headers["content-type"] == "image/png"
    assert v.headers["content-disposition"].startswith("inline")
    d = client.get("/image/output/jroute/0.png?download=1", headers=LAB)
    assert d.headers["content-disposition"].startswith("attachment")
    assert "owl_gos1_flux2-klein-4b_jroute_p0.png" in d.headers["content-disposition"]
    assert client.get("/image/output/jroute/5.png", headers=LAB).status_code == 404
    assert client.get("/image/output/nope/0.png", headers=LAB).status_code == 404


def test_pair_route(monkeypatch):
    rs = {"ja": _result("ja", _png()), "jb": _result("jb", _png(), runtime="mflux 0.24.0")}
    monkeypatch.setattr(routes_image, "load_result", lambda t, j, visitor_key=None: rs.get(j))
    d = client.get("/image/pair?a=ja&b=jb", headers=LAB).json()
    assert d["comparable"] is False
    assert client.get("/image/pair?a=ja&b=zz", headers=LAB).status_code == 404


def test_peer_route_serves_this_nodes_file():
    _result("gos2-x", _png())
    path = "/peer/image-output/gos2-x/0"
    ok = client.get(path, headers={**LAB, peer.HEADER: peer.sign("GET", path)})
    assert ok.status_code == 200 and ok.content == _png()
    assert client.get(path, headers=LAB).status_code in (401, 403)
