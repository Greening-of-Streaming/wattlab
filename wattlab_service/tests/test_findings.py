"""
Unit tests for CR-054 — findings catalog loader, validator, and route.

Five tests, per the CR-054 test plan:
  - schema parsing of the AV1 worked example
  - reference resolution (all source_result_ids exist on disk)
  - route returns 200 with the expected content blocks
  - route returns 404 for an unknown slug
  - citation block is well-formed for copy-paste

Plus a sixth that pins the feature-flag rollback behaviour — flipping
findings_enabled to False must return 404 even on a valid slug.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import findings
import settings as cfg
import main as main_mod


client = TestClient(main_mod.app)
AV1_SLUG = "av1-hw-sw-vmaf-tradeoff"


# --- schema + parsing ------------------------------------------------------

def test_av1_finding_parses_with_required_fields():
    f = findings.load(AV1_SLUG)
    assert f is not None
    # Required fields populated
    assert f.slug == AV1_SLUG
    assert f.version == 1
    assert f.confidence in {"green", "yellow", "red"}
    assert f.headline
    assert f.claim_short
    assert f.scope
    assert f.methodology_ref
    assert isinstance(f.source_result_ids, list) and len(f.source_result_ids) >= 1
    # Dates normalised to YYYY-MM-DD strings
    assert len(f.first_measured) == 10 and f.first_measured.count("-") == 2
    assert len(f.last_refined) == 10 and f.last_refined.count("-") == 2


# --- references resolve to real files -------------------------------------

def test_every_finding_source_result_id_exists_on_disk():
    """Every finding under docs/findings/ must point at result files that
    actually exist. A dangling finding cannot ship."""
    all_findings = findings.list_all()
    assert all_findings, "expected at least one finding (the AV1 worked example)"
    for f in all_findings:
        for rid in f.source_result_ids:
            path = findings.resolve_result_path(rid)
            assert path is not None and path.exists(), (
                f"finding {f.slug!r}: source_result_id {rid!r} resolves to no file"
            )


def test_av1_finding_result_url_shape():
    """The download URL constructed from a source_result_id matches OWL's
    /results/<type>/<job_id>/download.json endpoint shape."""
    url = findings.result_download_url("video/e18a9d57")
    assert url == "/results/video/e18a9d57/download.json"


# --- route ----------------------------------------------------------------

def test_finding_route_returns_200_with_expected_blocks():
    r = client.get(f"/findings/{AV1_SLUG}")
    assert r.status_code == 200, r.text[:500]
    body = r.text
    # Headline + claim + scope all present
    f = findings.load(AV1_SLUG)
    assert "AV1 hardware uses" in body
    assert "1500 kbps ABR" in body
    assert "Device layer only" in body
    # Citation block: stable URL + measurement date
    assert "/findings/" + AV1_SLUG in body
    assert f.first_measured in body
    # Source measurement embed placeholder present (the JS hydrates it)
    assert "finding-embed" in body and 'data-result-id="video/e18a9d57"' in body
    # Source-measurement JS dispatcher includes the four shared renderers
    for fn in ("wlRenderVideoCard", "wlRenderLLMCard", "wlRenderImageCard", "wlRenderRAGCard"):
        assert fn in body, f"renderer {fn} missing from page"


def test_finding_route_returns_404_for_unknown_slug():
    r = client.get("/findings/no-such-finding")
    assert r.status_code == 404


# --- citation block well-formed for copy-paste ----------------------------

def test_citation_block_has_url_and_dates():
    r = client.get(f"/findings/{AV1_SLUG}")
    assert r.status_code == 200
    body = r.text
    # The citation block (rendered inside .cite-text) includes the stable
    # finding URL and the measurement date — those are the two pieces a
    # board-deck citation actually needs.
    f = findings.load(AV1_SLUG)
    # Stable URL appears in the page (both as a link and as text in citation)
    assert AV1_SLUG in body
    # Date appears (in the citation text, the meta line, and the footer)
    assert f.first_measured in body
    # Org line so the citation can't be confused with a vendor benchmark
    assert "Greening of Streaming" in body


# --- rollback insurance: feature flag must gate the route -----------------

def test_findings_disabled_flag_returns_404(tmp_path, monkeypatch):
    """CR-054 rollback path: flipping findings_enabled to False must make
    every /findings/* return 404 — even valid slugs. This is the
    single-bool-flip rollback the CR promises to lab colleagues."""
    # Monkey-patch settings.load to return findings_enabled=False without
    # actually writing settings.json (preserves the live config).
    real_load = cfg.load
    def disabled_load():
        d = real_load()
        d["findings_enabled"] = False
        return d
    monkeypatch.setattr(cfg, "load", disabled_load)

    r = client.get(f"/findings/{AV1_SLUG}")
    assert r.status_code == 404, (
        f"expected 404 with findings_enabled=False, got {r.status_code}"
    )


# --- minimal markdown renderer behaves -------------------------------------

def test_md_to_html_handles_paragraphs_lists_headings_inline():
    src = (
        "# Heading 2\n"
        "\n"
        "Paragraph with **bold** and *italic* and `code`.\n"
        "\n"
        "## Heading 3\n"
        "\n"
        "- item one\n"
        "- item two with [a link](https://example.com)\n"
    )
    html = findings.md_to_html(src)
    assert "<h2>Heading 2</h2>" in html
    assert "<h3>Heading 3</h3>" in html
    assert "<strong>bold</strong>" in html
    assert "<em>italic</em>" in html
    assert "<code>code</code>" in html
    assert "<li>item one</li>" in html
    assert '<a href="https://example.com">a link</a>' in html


def test_md_to_html_escapes_hostile_input():
    src = "Hello <script>alert(1)</script>"
    out = findings.md_to_html(src)
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


# --- /video page beta-link gating (CR-054 owner addition 2026-05-27) -------

_VIDEO_BETA_TEXT = "AV1 hardware vs software"


def test_video_page_shows_beta_findings_link_when_enabled():
    """When findings_enabled=True (default), /video carries a discreet
    [beta] link to the AV1 finding. This is the one nav-promotion CR-054
    ships with — explicitly approved by the owner 2026-05-27."""
    r = client.get("/video")
    assert r.status_code == 200
    body = r.text
    assert _VIDEO_BETA_TEXT in body, "expected the AV1 beta link on /video"
    assert "/findings/av1-hw-sw-vmaf-tradeoff" in body
    # The beta marker chip must be present so the link reads as preview, not production
    assert "beta" in body.lower()


def test_video_page_hides_beta_findings_link_when_disabled(monkeypatch):
    """Rollback insurance for the /video beta link — the same flag that
    removes the /findings route must also remove the link. Lab-colleague
    disapproval = one bool flip, route AND link gone together."""
    real_load = cfg.load
    def disabled_load():
        d = real_load()
        d["findings_enabled"] = False
        return d
    monkeypatch.setattr(cfg, "load", disabled_load)

    r = client.get("/video")
    assert r.status_code == 200
    body = r.text
    assert _VIDEO_BETA_TEXT not in body, (
        "/video still showed the AV1 beta link with findings_enabled=False"
    )
