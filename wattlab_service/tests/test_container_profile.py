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
