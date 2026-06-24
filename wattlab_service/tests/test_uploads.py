"""
Tests for the unified upload module (uploads.py) + its wiring into the three
upload routes. Pure-function lifecycle tests + TestClient checks that each page's
upload accepts `retention` and stores with the right prefix.
"""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import settings
import uploads


# --------------------------------------------------------------------------
# Naming + retention parsing (incl. legacy enhance names)
# --------------------------------------------------------------------------
def test_make_name_roundtrip():
    n = uploads.make_name("My Clip!.MP4", "keep", "video")
    assert n.startswith("keep_video_")
    assert n.endswith(".mp4")
    assert uploads.retention_of(n) == "keep"


def test_make_name_defaults_unknown_retention():
    n = uploads.make_name("x.mp4", "bogus", "rem")
    assert uploads.retention_of(n) == uploads.DEFAULT_RETENTION  # evict


@pytest.mark.parametrize("name,expected", [
    ("evict_video_aa_x.mp4", "evict"),
    ("proc_enhance_bb_x.mov", "proc"),
    ("keep_rem_cc_x.mkv", "keep"),
    ("upload_keep_dd_x.mp4", "keep"),     # legacy enhance
    ("upload_ee_x.mp4", "evict"),         # legacy enhance
    ("meridian_120s.mp4", None),          # curated staged clip — not an upload
    ("normalized_ff_x.nut", None),        # derived artifact
])
def test_retention_of(name, expected):
    assert uploads.retention_of(name) == expected
    assert uploads.is_owl_upload(name) is (expected is not None)


def test_is_immediate_and_kept():
    assert uploads.is_immediate("proc_video_a_x.mp4") is True
    assert uploads.is_immediate("evict_video_a_x.mp4") is False
    assert uploads.is_kept("keep_video_a_x.mp4") is True


# --------------------------------------------------------------------------
# save + eviction ("remove when short of space")
# --------------------------------------------------------------------------
def test_save_writes_with_prefix(tmp_path):
    saved = uploads.save(b"hello", "clip.mp4", retention="keep",
                         feature="video", dest_dir=tmp_path, min_free_gb=0)
    assert saved["retention"] == "keep"
    assert saved["path"].is_file()
    assert saved["name"].startswith("keep_video_")
    assert saved["size_mb"] == round(5 / 1024 / 1024, 2)


def test_evict_until_free_removes_oldest_evict_only(tmp_path, monkeypatch):
    # Three uploads: two evict (different ages) + one keep. Force "always short".
    old = tmp_path / "evict_video_old_a.mp4"; old.write_bytes(b"x")
    new = tmp_path / "evict_video_new_b.mp4"; new.write_bytes(b"x")
    kept = tmp_path / "keep_video_c.mp4"; kept.write_bytes(b"x")
    import os
    os.utime(old, (1000, 1000))      # oldest
    os.utime(new, (2000, 2000))
    os.utime(kept, (500, 500))       # older than both, but KEEP → never evicted

    # disk always below threshold until both evict files are gone, then OK.
    state = {"freed": 0}
    def fake_free(_):
        return 100 if state["freed"] >= 2 else 0
    monkeypatch.setattr(uploads, "free_gb", lambda p: fake_free(p))
    orig_unlink = Path.unlink
    def counting_unlink(self, missing_ok=False):
        state["freed"] += 1
        return orig_unlink(self, missing_ok=missing_ok)
    monkeypatch.setattr(Path, "unlink", counting_unlink)

    deleted = uploads.evict_until_free(tmp_path, min_gb=50)
    assert set(deleted) == {"evict_video_old_a.mp4", "evict_video_new_b.mp4"}
    assert deleted[0] == "evict_video_old_a.mp4"   # oldest first
    assert kept.exists()                            # keep is sacrosanct


def test_evict_noop_when_space_ok(tmp_path, monkeypatch):
    (tmp_path / "evict_video_a.mp4").write_bytes(b"x")
    monkeypatch.setattr(uploads, "free_gb", lambda p: 999)
    assert uploads.evict_until_free(tmp_path, min_gb=50) == []


# --------------------------------------------------------------------------
# cleanup_after_job
# --------------------------------------------------------------------------
def test_cleanup_proc_deletes(tmp_path):
    p = tmp_path / "proc_video_a_x.mp4"; p.write_bytes(b"x")
    uploads.cleanup_after_job(tmp_path, p.name)
    assert not p.exists()


def test_cleanup_evict_and_keep_touch_not_delete(tmp_path):
    for ret in ("evict", "keep"):
        p = tmp_path / f"{ret}_video_a_x.mp4"; p.write_bytes(b"x")
        uploads.cleanup_after_job(tmp_path, p.name)
        assert p.exists()


def test_cleanup_ignores_staged_clip(tmp_path):
    p = tmp_path / "meridian_120s.mp4"; p.write_bytes(b"x")
    uploads.cleanup_after_job(tmp_path, p.name)
    assert p.exists()   # never delete a non-upload


# --------------------------------------------------------------------------
# sweep (TTL backstop + extra prefixes; never keep/proc)
# --------------------------------------------------------------------------
def test_sweep_removes_old_evict_and_extra_not_keep(tmp_path):
    import os
    old_evict = tmp_path / "evict_video_a.mp4"; old_evict.write_bytes(b"x")
    old_norm = tmp_path / "normalized_b.nut"; old_norm.write_bytes(b"x")
    old_keep = tmp_path / "keep_video_c.mp4"; old_keep.write_bytes(b"x")
    fresh_evict = tmp_path / "evict_video_d.mp4"; fresh_evict.write_bytes(b"x")
    for p in (old_evict, old_norm, old_keep):
        os.utime(p, (1, 1))   # ancient
    swept = uploads.sweep(tmp_path, ttl_h=1, extra_prefixes=("normalized_",))
    assert set(swept) == {"evict_video_a.mp4", "normalized_b.nut"}
    assert old_keep.exists()      # keep never swept, even when ancient
    assert fresh_evict.exists()   # fresh evict survives the TTL


# --------------------------------------------------------------------------
# Route wiring — each page's upload accepts `retention` (TestClient = Lab)
# --------------------------------------------------------------------------
import main  # noqa: E402

client = TestClient(main.app)
_LAB = {"x-real-ip": "127.0.0.1"}


def _fake_save(monkeypatch, tmp_path):
    """Redirect uploads.save to write into tmp_path and record the retention."""
    rec = {}
    real = uploads.save
    def spy(blob, orig, *, retention, feature, dest_dir, min_free_gb=None):
        rec["retention"] = retention
        rec["feature"] = feature
        return real(blob, orig, retention=retention, feature=feature,
                    dest_dir=tmp_path, min_free_gb=0)
    monkeypatch.setattr(uploads, "save", spy)
    return rec


def test_video_upload_accepts_retention(monkeypatch, tmp_path):
    # The queue worker isn't started under a bare TestClient; stub enqueue
    # (the upload-store behaviour is what this test asserts).
    import queue_control
    monkeypatch.setattr(queue_control, "enqueue", lambda *a, **k: 1)
    rec = _fake_save(monkeypatch, tmp_path)
    r = client.post("/video/upload", headers=_LAB,
                    files={"file": ("clip.mp4", b"data", "video/mp4")},
                    data={"preset": "cpu", "retention": "keep"})
    assert r.status_code == 200
    assert rec["retention"] == "keep" and rec["feature"] == "video"
    assert r.json()["job_id"]


def test_prepare_rem_upload_accepts_retention(monkeypatch, tmp_path):
    # rem upload probes the file; monkeypatch the probe so no ffprobe needed.
    import rem_prep
    monkeypatch.setattr(rem_prep, "_probe_props",
                        lambda p: {"width": 1920, "height": 1080, "fps": "30"})
    rec = _fake_save(monkeypatch, tmp_path)
    r = client.post("/prepare-rem/upload", headers=_LAB,
                    files={"file": ("clip.mp4", b"data", "video/mp4")},
                    data={"retention": "proc"})
    assert r.status_code == 200
    assert rec["retention"] == "proc" and rec["feature"] == "rem"
    assert r.json()["retention"] == "proc"
