"""
CR-068 · syntax-check the inline page JS.

~70% of OWL's JS still lives inline in routes_*.py f-strings (the audit's
"single riskiest edit surface"): a stray `{` breaks the f-string, and a JS
syntax slip ships silently — the S38 bug class the static-bundle `node --check`
was built for, but which never covered the per-page inline blocks. This renders
each page and runs `node --check` on every inline <script> body, closing that
gap without moving any code.

Skips when node is unavailable (CI parity with test_ui_config).
"""
import re
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)
_LAB = {"x-real-ip": "127.0.0.1"}  # render Lab-gated pages + all gated JS

# Pages carrying substantial inline JS. Lab header so gated pages/blocks render.
_PAGES = [
    "/", "/video", "/llm", "/rag", "/image", "/settings", "/methodology",
    "/enhance-run", "/demo", "/queue-status", "/benchmark", "/findings",
    "/llm/compare", "/rag/compare",
]

# <script> … </script> with no src= attribute, and not JSON-LD data blocks.
_SCRIPT_RE = re.compile(r"<script(?![^>]*\bsrc=)([^>]*)>(.*?)</script>",
                        re.DOTALL | re.IGNORECASE)


def _inline_scripts(html: str):
    for attrs, body in _SCRIPT_RE.findall(html):
        if "application/ld+json" in attrs.lower():
            continue          # data, not executable JS
        if body.strip():
            yield body


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
@pytest.mark.parametrize("path", _PAGES)
def test_inline_page_js_parses(path, tmp_path):
    r = client.get(path, headers=_LAB)
    assert r.status_code == 200, f"{path} did not render ({r.status_code})"
    blocks = list(_inline_scripts(r.text))
    for i, body in enumerate(blocks):
        f = tmp_path / f"block_{i}.js"
        f.write_text(body)
        res = subprocess.run(["node", "--check", str(f)],
                             capture_output=True, text=True, timeout=30)
        assert res.returncode == 0, (
            f"{path} inline <script> #{i} failed node --check:\n{res.stderr}")


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_pages_actually_have_inline_js_to_check():
    """Guard against the check silently passing because the extractor matched
    nothing (e.g. markup changed) — at least the workbench pages must carry
    inline script."""
    total = sum(len(list(_inline_scripts(client.get(p, headers=_LAB).text)))
                for p in ("/video", "/llm", "/rag"))
    assert total >= 3, "expected inline <script> blocks on the workbench pages"
