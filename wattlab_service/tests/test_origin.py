"""decode_bench/origin.py — Range semantics the ad-hoc server got wrong."""
import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "decode_bench"))
import origin


@pytest.fixture(scope="module")
def served(tmp_path_factory):
    root = tmp_path_factory.mktemp("streams")
    (root / "clip.mp4").write_bytes(bytes(range(256)) * 4)   # 1024 known bytes
    origin.ROOT = str(root)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), origin.RangeHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _get(url, rng=None):
    req = urllib.request.Request(url)
    if rng:
        req.add_header("Range", rng)
    return urllib.request.urlopen(req, timeout=5)


def test_plain_get_advertises_ranges(served):
    r = _get(served + "/clip.mp4")
    assert r.status == 200
    assert r.headers["Accept-Ranges"] == "bytes"
    assert int(r.headers["Content-Length"]) == 1024
    assert len(r.read()) == 1024


def test_range_returns_206_with_exact_bytes(served):
    r = _get(served + "/clip.mp4", "bytes=10-19")
    assert r.status == 206
    assert r.headers["Content-Range"] == "bytes 10-19/1024"
    body = r.read()
    assert body == bytes(range(10, 20))


def test_open_ended_and_suffix_ranges(served):
    r = _get(served + "/clip.mp4", "bytes=1000-")
    assert r.status == 206
    assert r.headers["Content-Range"] == "bytes 1000-1023/1024"
    assert len(r.read()) == 24
    r = _get(served + "/clip.mp4", "bytes=-16")
    assert r.status == 206
    assert r.headers["Content-Range"] == "bytes 1008-1023/1024"


def test_unsatisfiable_range_416(served):
    with pytest.raises(urllib.error.HTTPError) as e:
        _get(served + "/clip.mp4", "bytes=5000-6000")
    assert e.value.code == 416
    assert e.value.headers["Content-Range"] == "bytes */1024"


def test_head_supports_ranges(served):
    req = urllib.request.Request(served + "/clip.mp4", method="HEAD")
    req.add_header("Range", "bytes=0-99")
    r = urllib.request.urlopen(req, timeout=5)
    assert r.status == 206
    assert int(r.headers["Content-Length"]) == 100
    assert r.read() == b""


def test_missing_file_404(served):
    with pytest.raises(urllib.error.HTTPError) as e:
        _get(served + "/nope.mp4")
    assert e.value.code == 404


def test_status_counts_bytes_and_ranged(served):
    before = json.loads(_get(served + "/status").read())
    _get(served + "/clip.mp4", "bytes=0-99").read()
    after = json.loads(_get(served + "/status").read())
    assert after["requests"] >= before["requests"] + 1
    assert after["bytes_sent"] >= before["bytes_sent"] + 100
    assert after["ranged_requests"] >= before["ranged_requests"] + 1
