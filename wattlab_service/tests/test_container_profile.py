"""container/ (2026-10-28) — the container seed settings stay valid as
settings.py and main.py evolve: every key is a real setting (settings.load
silently drops unknown keys), and every disabled router is a real module."""
import json

import paths
import settings


def _template():
    return json.loads(paths.repo("container", "settings.container.json").read_text())


def test_every_container_setting_is_a_known_key():
    unknown = [k for k in _template() if not k.startswith("_") and k not in settings.DEFAULTS]
    assert unknown == []


def test_disabled_routers_name_real_feature_modules():
    src = paths.repo("wattlab_service", "main.py").read_text()
    for name in _template()["disabled_routers"]:
        assert f"import {name}" in src, name


def test_container_keeps_measurement_core_mounted():
    off = set(_template()["disabled_routers"])
    assert not off & {"routes_video", "routes_llm", "routes_image", "routes_rag",
                      "routes_settings", "routes_results", "routes_benchmark"}


# --- node identity: a new node names itself, never "GoS1" (owner 2026-10-28) ---

import hosts


def _fresh_identity(monkeypatch, hostname, env_label=None, local_host=None):
    import env
    import socket
    monkeypatch.setattr(hosts, "_DETECTED", None)
    monkeypatch.setattr(socket, "gethostname", lambda: hostname)
    monkeypatch.setattr(env, "load", lambda: {"OWL_NODE_LABEL": env_label} if env_label else {})
    monkeypatch.setattr(settings, "load", lambda: {"local_host": local_host or {}})
    return hosts.local_host()


def test_env_label_names_the_node(monkeypatch):
    h = _fresh_identity(monkeypatch, "84f3040b65b9", env_label="Akamai Paris 01")
    assert h["label"] == "Akamai Paris 01" and h["id"] == "akamai-paris-01"
    assert h["chip"].startswith(h["cpu"])          # detected CPU (+ GPU), not a hard-coded GoS1 chip


def test_hostname_used_unless_generic(monkeypatch):
    assert _fresh_identity(monkeypatch, "edge-node-7.example.net")["label"] == "edge-node-7"
    assert _fresh_identity(monkeypatch, "localhost")["label"] == "OWL node"
    assert _fresh_identity(monkeypatch, "84f3040b65b9")["label"] == "OWL node"   # Docker container id


def test_settings_local_host_still_wins(monkeypatch):
    h = _fresh_identity(monkeypatch, "whatever", env_label="X",
                        local_host={"id": "gos2", "label": "GoS2", "chip": "Apple M6"})
    assert (h["id"], h["label"], h["chip"]) == ("gos2", "GoS2", "Apple M6")
    assert hosts.local_label() == "GoS2"
