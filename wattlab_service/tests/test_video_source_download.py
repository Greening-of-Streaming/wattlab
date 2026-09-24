"""The "Download Source Video" button on the /video Source picker and the
`/video/source/{key}/download` route behind it.

Both are driven by sources.SOURCES (via get_grouped_sources / PRELOADED),
so a variant added to sources.py gets the button and the download for
free. These tests therefore pin the *invariant* — one button per radio,
same key — against a fake registry, plus the route contract, rather
than any hand-typed list of the current seven files.
"""
import re
from pathlib import Path

from fastapi.testclient import TestClient

import main
import routes_video

client = TestClient(main.app)


def _fake_grouped():
    return [{
        "id": "fake", "name": "Fake source", "character": None,
        "credit": "nobody", "license": "CC0", "source_url": None,
        "vignette": None,
        "variants": [
            {"key": "fake_120s", "variant_label": "2 min extract",
             "description": "d1", "size_mb": 12.3},
            {"key": "fake_full", "variant_label": "Full",
             "description": "d2"},          # no size_mb → still renders
        ],
    }]


def _fake_preloaded(path):
    return {"fake_120s": {"label": "Fake — 2 min extract", "description": "d",
                          "path": path, "credit": "nobody", "_parent": "fake"}}


# --- picker ---

def test_picker_renders_one_download_button_per_variant(monkeypatch):
    monkeypatch.setattr(routes_video, "get_grouped_sources", _fake_grouped)
    html = routes_video._video_source_picker_html()
    radios = re.findall(r'name="source" value="([^"]+)"', html)
    links = re.findall(r'href="/video/source/([^"]+)/download"', html)
    assert radios == ["fake_120s", "fake_full"]
    assert links == radios
    assert html.count("Download Source Video") == 2


def test_picker_download_button_is_an_attachment_link_inside_the_row(monkeypatch):
    monkeypatch.setattr(routes_video, "get_grouped_sources", _fake_grouped)
    html = routes_video._video_source_picker_html()
    row = html.split("</label>")[0]
    assert 'href="/video/source/fake_120s/download" download' in row
    assert "12.3 MB" in row                     # size surfaces in the title
    assert row.count("<label") == 1


def test_video_page_offers_a_download_for_every_available_source():
    """Live registry: every variant whose file exists on this box must show
    the button on /video — the picker and the route share one schema."""
    import sources
    html = client.get("/video").text
    for info in sources.get_all_sources():
        assert f'href="/video/source/{info["key"]}/download"' in html


# --- route ---

def test_download_route_serves_the_source_file_as_attachment(tmp_path, monkeypatch):
    f = tmp_path / "fake_120s.mp4"
    f.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"x" * 64)
    monkeypatch.setattr(routes_video, "PRELOADED", _fake_preloaded(f))
    r = client.get("/video/source/fake_120s/download")
    assert r.status_code == 200
    assert r.content == f.read_bytes()
    assert 'filename="fake_120s.mp4"' in r.headers["content-disposition"]
    assert r.headers["content-type"].startswith("video/mp4")


def test_download_route_is_open_to_anonymous(tmp_path, monkeypatch):
    f = tmp_path / "fake_120s.mp4"
    f.write_bytes(b"x" * 16)
    monkeypatch.setattr(routes_video, "PRELOADED", _fake_preloaded(f))
    r = client.get("/video/source/fake_120s/download",
                   headers={"X-Real-IP": "8.8.8.8"})
    assert r.status_code == 200


def test_download_route_404s_unknown_key(monkeypatch):
    monkeypatch.setattr(routes_video, "PRELOADED", {})
    assert client.get("/video/source/not_a_key/download").status_code == 404


def test_download_route_404s_when_file_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_video, "PRELOADED",
                        _fake_preloaded(tmp_path / "missing.mp4"))
    assert client.get("/video/source/fake_120s/download").status_code == 404


# --- "Replicate a run on your own server" dropdown (bottom of /video) ---

def test_video_page_has_collapsed_replicate_howto_at_the_bottom():
    """A <details> block in the 'About this test' style, closed by default,
    placed after the previous-runs list. Its steps name the three surfaces
    it points at: the source download button, the ffmpeg command preview
    and the Reproduce-this zip — so a rename of any of them breaks here."""
    html = client.get("/video").text
    start = html.index('<details id="replicate-howto"')
    assert start > html.index('id="prev-runs"')
    block = html[start:html.index("</details>", start)]
    assert "<details id=\"replicate-howto\" open" not in block
    assert "Replicate a run on your own server" in block
    assert "Download the source" in block
    assert "ffmpeg command" in block
    assert "Reproduce this" in block
    assert "Meter wall power" in block
