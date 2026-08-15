"""
Unit tests for `settings.py`.

Mirrors the test pattern set by tests/test_carbon.py: plain `def test_<name>`,
autouse fixture for state isolation, no real I/O.

Primary purpose: lock down the partial-update merge semantics. The
clobbering bug behind this regression test:

  Before 2026-05-01: settings.save() merged against DEFAULTS, not against
  the on-disk state. So calling save({"baseline_polls": 5}) silently reset
  every other key — including the variance_idle_pct / variance_cpu_pct /
  variance_gpu_pct values that are written exclusively by the variance
  calibration run, are tedious to recompute (~10 min calibration), and
  are never re-supplied by a POST /settings UI form. The owner had to
  rerun calibration twice to recover.
"""
from pathlib import Path

import pytest

import settings as cfg


@pytest.fixture(autouse=True)
def isolated_settings_file(tmp_path, monkeypatch):
    """Redirect SETTINGS_FILE to a per-test tmp path so tests can't trample
    the real /home/gos/wattlab/settings.json."""
    test_file = tmp_path / "settings.json"
    monkeypatch.setattr(cfg, "SETTINGS_FILE", test_file)
    yield


# --- load() ----------------------------------------------------------------

def test_load_returns_defaults_when_file_missing():
    out = cfg.load()
    assert out["baseline_polls"] == cfg.DEFAULTS["baseline_polls"]
    assert out["variance_pct"] == cfg.DEFAULTS["variance_pct"]


def test_load_overlays_disk_values_on_top_of_defaults(tmp_path):
    cfg.SETTINGS_FILE.write_text('{"baseline_polls": 99}')
    out = cfg.load()
    assert out["baseline_polls"] == 99
    # Other keys still fall through to DEFAULTS
    assert out["video_cooldown_s"] == cfg.DEFAULTS["video_cooldown_s"]


def test_load_ignores_unrecognised_keys_on_disk():
    cfg.SETTINGS_FILE.write_text('{"baseline_polls": 7, "rogue_key": "ignored"}')
    out = cfg.load()
    assert "rogue_key" not in out


def test_load_falls_back_to_defaults_on_corrupt_file():
    cfg.SETTINGS_FILE.write_text("not-valid-json{{")
    out = cfg.load()
    assert out == cfg.DEFAULTS


# --- save() — the partial-update regression --------------------------------

def test_save_partial_update_preserves_unspecified_keys():
    """REGRESSION: A partial save must not clobber keys that were already
    on disk. Owner-impacting: variance_*_pct values are written only by
    the variance calibration run; the /settings UI never re-supplies them.
    """
    # Seed the on-disk file with calibrated variance values.
    cfg.save({
        "variance_pct":      1.08,
        "variance_idle_pct": 1.79,
        "variance_cpu_pct":  0.82,
        "variance_gpu_pct":  0.64,
    })
    # Now do a partial update — the kind /settings POST sends.
    cfg.save({"baseline_polls": 5})
    after = cfg.load()
    # The calibrated values must still be there.
    assert after["variance_pct"]      == 1.08
    assert after["variance_idle_pct"] == 1.79
    assert after["variance_cpu_pct"]  == 0.82
    assert after["variance_gpu_pct"]  == 0.64
    # And the partial update did its job.
    assert after["baseline_polls"] == 5


def test_save_with_no_existing_file_falls_through_to_defaults():
    """When no file exists yet, save() should still produce a sensible
    result — DEFAULTS overlaid with the partial update."""
    cfg.save({"baseline_polls": 42})
    after = cfg.load()
    assert after["baseline_polls"] == 42
    assert after["video_cooldown_s"] == cfg.DEFAULTS["video_cooldown_s"]


def test_save_drops_unrecognised_keys_from_input():
    """Defence-in-depth: a malicious or buggy POST body containing keys
    we don't define must not pollute the on-disk file."""
    cfg.save({"baseline_polls": 5, "evil_field": "drop me"})
    after = cfg.load()
    assert "evil_field" not in after
    raw = cfg.SETTINGS_FILE.read_text()
    assert "evil_field" not in raw


def test_save_returns_the_persisted_dict():
    """Callers (e.g. /settings POST) return the saved dict to the client.
    It must reflect what's now on disk."""
    out = cfg.save({"baseline_polls": 11})
    assert out["baseline_polls"] == 11
    assert out == cfg.load()


def test_save_with_empty_patch_is_a_noop():
    """Calling save({}) (empty patch) should be a no-op against current state."""
    cfg.save({"baseline_polls": 7, "variance_idle_pct": 1.5})
    before = cfg.load()
    cfg.save({})
    after = cfg.load()
    assert before == after


def test_decode_rig_settings_are_persistable():
    """Every key the /settings 'Decode rig' section edits must be in DEFAULTS —
    save() drops unknown keys, so the section was a silent no-op until
    2026-08-15 (found while adding the idle auto-off keys)."""
    for k in ("decode_cadence_s", "decode_settle_s", "decode_baseline_samples",
              "decode_idle_guard", "decode_idle_tolerance_w",
              "decode_idle_settle_polls", "decode_idle_max_wait_s",
              "decode_screen_startup_skip_s", "rig_master_tapo_ip",
              "rig_shelly_ip", "rig_idle_off_enabled", "rig_idle_off_hours",
              "rig_idle_off_monitor"):
        assert k in cfg.DEFAULTS, k
    assert cfg.DEFAULTS["rig_idle_off_enabled"] is True
    assert cfg.DEFAULTS["rig_idle_off_hours"] == 4.0
    assert cfg.DEFAULTS["rig_idle_off_monitor"] is False
