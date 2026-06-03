"""
Guards against a class of bug where a page's JS calls a shared helper that lives
in a bundle the page doesn't include — a runtime ReferenceError that silently
breaks the poll loop (e.g. the frozen /llm/compare progress, 2026-06-02).

If a page CALLS wlCooldownDialog / wlCooldownSummary, it must also DEFINE it.
These pages render for PUBLIC_PAGE, so the (Anonymous) TestClient can fetch them.
"""
import pytest
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)

PAGES = ["/llm/compare", "/rag/compare", "/rag", "/image", "/video", "/enhance-run"]
# Fetch as Lab so member-gated pages (e.g. /enhance-run) are still inspectable;
# the public pages render identically for Lab.
LAB = {"x-real-ip": "127.0.0.1"}


@pytest.mark.parametrize("path", PAGES)
def test_cooldown_dialog_defined_where_called(path):
    html = client.get(path, headers=LAB).text
    if "wlCooldownDialog(" in html:
        assert "window.wlCooldownDialog =" in html, f"{path} calls wlCooldownDialog but never defines it"
        assert "window.wlCooldownDialogClose =" in html, f"{path} calls the dialog but lacks wlCooldownDialogClose"


@pytest.mark.parametrize("path", PAGES)
def test_cooldown_summary_defined_where_called(path):
    html = client.get(path, headers=LAB).text
    if "wlCooldownSummary(" in html:
        assert "window.wlCooldownSummary =" in html, f"{path} calls wlCooldownSummary but never defines it"
