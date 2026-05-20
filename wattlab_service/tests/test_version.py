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
