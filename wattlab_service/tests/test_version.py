"""Tests for the version / build stamp."""
import version


def test_version_dict_shape():
    d = version.version_dict()
    for k in ("version", "sha", "dirty", "built_at"):
        assert k in d
    assert isinstance(d["dirty"], bool)
    assert d["version"]


def test_version_string_includes_semver():
    s = version.version_string()
    assert s.startswith("OWL v")
    assert version.version_dict()["version"] in s


def test_dirty_marker(monkeypatch):
    monkeypatch.setattr(version, "_INFO",
                        {"version": "9.9.9", "sha": "deadbee",
                         "dirty": True, "built_at": "2026-01-01"})
    s = version.version_string()
    assert "OWL v9.9.9" in s and "deadbee" in s and s.endswith("-local")
    monkeypatch.setattr(version, "_INFO",
                        {"version": "9.9.9", "sha": "deadbee",
                         "dirty": False, "built_at": "2026-01-01"})
    assert not version.version_string().endswith("-local")


# --- Option A: version auto-derives from `git describe --tags` --------------

def test_describe_version_on_a_tag(monkeypatch):
    # `git describe --long` on the tag → "-0-g" → clean semver, no +N suffix.
    monkeypatch.setattr(version, "_git", lambda *a: "v1.0.0-0-g42b4198")
    assert version._describe_version() == "1.0.0"


def test_describe_version_ahead_of_tag(monkeypatch):
    monkeypatch.setattr(version, "_git", lambda *a: "v1.0.0-127-g42b4198")
    assert version._describe_version() == "1.0.0+127"


def test_describe_version_empty_without_tag(monkeypatch):
    # No tag reachable → describe --always returns a bare sha → caller falls
    # back to the VERSION file.
    monkeypatch.setattr(version, "_git", lambda *a: "42b4198")
    assert version._describe_version() == ""


# --- dirty flag ignores live-state settings.json ---------------------------

def test_dirty_ignores_only_settings_json(monkeypatch):
    monkeypatch.setattr(version, "_git", lambda *a: " M settings.json")
    assert version._dirty() is False               # live state, not "-local"


def test_dirty_true_on_real_code_change(monkeypatch):
    monkeypatch.setattr(
        version, "_git",
        lambda *a: " M settings.json\n M wattlab_service/video.py")
    assert version._dirty() is True                # uncommitted code → dirty


def test_dirty_false_on_clean_tree(monkeypatch):
    monkeypatch.setattr(version, "_git", lambda *a: "")
    assert version._dirty() is False
