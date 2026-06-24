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
    """The download URL constructed from a source_result_id points at the
    finding-source carve-out endpoint, NOT the visitor-scoped /results one
    (which 404s lab-measured finding sources for every non-Lab visitor)."""
    url = findings.result_download_url("video/e18a9d57")
    assert url == "/findings/source/video/e18a9d57/download.json"


# --- finding-source carve-out endpoint ------------------------------------
# Regression guard for the recurring embed 404 ("could not load
# video/<id> (HTTP 404)"). The generic /results/.../download.json applies
# CR-026 visitor scoping, so a non-Lab visitor never matched the
# lab-measured finding sources. The test suite runs as Lab (loopback), which
# is precisely why that 404 stayed invisible here for so long — so these
# tests pin the *content* and the *gate* of the dedicated carve-out, which is
# visitor-independent by construction.

def test_finding_source_endpoint_serves_cited_result():
    r = client.get("/findings/source/video/e18a9d57/download.json")
    assert r.status_code == 200, r.text[:300]
    assert "e18a9d57" in str(r.json().get("job_id"))


def test_finding_source_endpoint_rejects_uncited_result():
    # Scoped carve-out, not a general CR-026 bypass: an id no published
    # finding cites must 404 even if a matching file exists on disk.
    r = client.get("/findings/source/video/not-a-cited-id/download.json")
    assert r.status_code == 404


def test_finding_source_endpoint_rejects_bad_type():
    r = client.get("/findings/source/benchmark/e18a9d57/download.json")
    assert r.status_code == 400


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
# Updated CR-056 (same session): beta link re-points at /findings catalog
# instead of the AV1-specific finding URL.

_VIDEO_BETA_TEXT = "browse the OWL findings catalog"


def test_video_page_shows_beta_findings_link_when_enabled():
    """When findings_enabled=True (default), /video carries a discreet
    [beta] link to the findings catalog. The catalog is the discovery
    surface; visitors enter via the curated index rather than a deep
    link to one specific finding."""
    r = client.get("/video")
    assert r.status_code == 200
    body = r.text
    assert _VIDEO_BETA_TEXT in body, "expected the catalog beta link on /video"
    assert 'href="/findings"' in body
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


def test_video_beta_link_points_at_catalog_not_specific_finding():
    """CR-056 owner direction (2026-05-27): once the catalog page exists,
    the /video beta link points at /findings (the catalog), not directly
    at the specific AV1 finding. The catalog is the right discovery
    surface; deep-linking past it short-circuits the curation."""
    r = client.get("/video")
    body = r.text
    # The link href is /findings (no slug). Be strict: catch the bare href.
    assert 'href="/findings"' in body, "expected /video to link at the catalog"
    # And the AV1-slug-specific URL should NOT be in the beta line.
    # (It can still appear elsewhere in the page legitimately if added later;
    # the brittle check is: don't link the AV1 slug from this specific spot.)
    # Approximate by checking the link text describes the catalog, not a finding.
    assert "browse the OWL findings catalog" in body


# --- CR-056: /findings catalog index ---------------------------------------

def test_findings_catalog_returns_200_and_lists_av1():
    r = client.get("/findings")
    assert r.status_code == 200, r.text[:500]
    body = r.text
    # Page header + AV1 finding row both present
    assert "OWL Findings" in body
    assert f'href="/findings/{AV1_SLUG}"' in body
    # The headline appears (snippet check — full headline is in the row)
    assert "AV1 hardware uses" in body
    # Footer reports a finding count — number depends on how many .md files
    # are under docs/findings/. Pin the format ("N finding(s) ·"), not the
    # specific N, so editorial adds (CR-056) don't break this test.
    import re
    assert re.search(r"\b\d+ findings? ·", body), "footer should report finding count"


def test_findings_catalog_returns_404_when_disabled(monkeypatch):
    """Same flag rollback: catalog must 404 when findings_enabled=false."""
    real_load = cfg.load
    def disabled_load():
        d = real_load()
        d["findings_enabled"] = False
        return d
    monkeypatch.setattr(cfg, "load", disabled_load)

    r = client.get("/findings")
    assert r.status_code == 404


# --- CR-056: bulk-imported findings load + render --------------------------

# Slugs imported in CR-056 (2026-05-27). If any of these is removed in a
# later editorial decision, update this list — the assertion below is a
# regression guard against accidental deletion.
_CR056_SLUGS = [
    "abr-all-codecs-meridian-120s",
    "input-master-sensitivity",
    "llm-cold-inference-mwh-per-token",
    "rag-faithfulness-rem-question",
    "sd-turbo-cpu-image-first-run",
]


def test_cr056_imported_findings_all_loadable():
    """Each of the five CR-056 bulk imports parses, validates, and resolves
    its source_result_ids — same contract every finding holds to."""
    for slug in _CR056_SLUGS:
        f = findings.load(slug)
        assert f is not None, f"finding {slug!r} did not load"
        for rid in f.source_result_ids:
            p = findings.resolve_result_path(rid)
            assert p is not None and p.exists(), (
                f"{slug!r}: source_result_id {rid!r} not on disk"
            )


def test_cr056_imported_findings_all_in_catalog():
    """All five new findings show up in the catalog listing."""
    r = client.get("/findings")
    assert r.status_code == 200
    body = r.text
    for slug in _CR056_SLUGS:
        assert f'href="/findings/{slug}"' in body, (
            f"catalog page does not list {slug!r}"
        )


def test_cr056_image_finding_renders_with_image_dispatcher():
    """Q5 sanity check from the CR-056 design conversation: the SD-Turbo
    finding (image type) must embed a `data-type="image"` placeholder and
    the JS dispatcher must map that to wlRenderImageCard. Without this,
    the embed shows 'no renderer for type=image'."""
    r = client.get("/findings/sd-turbo-cpu-image-first-run")
    assert r.status_code == 200
    body = r.text
    assert 'data-type="image"' in body
    assert 'data-result-id="image/c40acdc1"' in body
    assert "image: window.wlRenderImageCard" in body


def test_calibration_finding_renders_and_serves_artifact():
    """A finding may cite the fingerprint-keyed encode-parity calibration
    artifact (parity.py), not just per-job results. The page must (1) embed a
    `data-type="calibration"` placeholder mapped to wlRenderCalibrationCard,
    and (2) the /findings/source endpoint must serve the matrix artifact —
    resolved by file path, since `calibration` has no per-job loader."""
    r = client.get("/findings/hevc-h264-fallback-energy")
    assert r.status_code == 200
    body = r.text
    assert 'data-type="calibration"' in body
    assert "calibration: window.wlRenderCalibrationCard" in body
    assert "window.wlRenderCalibrationCard = function" in body
    # The cited artifact downloads via the scoped finding-source carve-out.
    dl = client.get("/findings/source/calibration/2026-06-20/download.json")
    assert dl.status_code == 200, dl.text
    assert dl.json().get("schema") == "encode-parity/v1"


def test_calibration_source_rejects_uncited_date():
    """The calibration carve-out is still scoped to cited artifacts only —
    an arbitrary date that no finding cites must 404, not leak a sweep."""
    r = client.get("/findings/source/calibration/1999-01-01/download.json")
    assert r.status_code == 404


# --- CR-058: /demo Findings step rewire ------------------------------------

def test_demo_findings_step_shows_catalog_preview_when_enabled():
    """When findings_enabled=True, the /demo Findings step (step 7) shows
    the curated catalog preview + 'See all findings' link instead of
    echoing the visitor's session runs."""
    r = client.get("/demo")
    assert r.status_code == 200
    body = r.text
    # Body-of-evidence framing copy
    assert "body of evidence" in body
    # The preview links the catalog's newest three findings (the actual
    # contract — was a hardcoded AV1 slug, which broke whenever a newer
    # finding landed; fixed 2026-06-12 when the sweet-spot finding did).
    newest = sorted(findings.list_all(), key=lambda f: f.last_refined,
                    reverse=True)[:3]
    for f in newest:
        assert f'href="/findings/{f.slug}"' in body
    # The "See all findings" catalog link is present
    assert "See all findings" in body
    # Window flag is set (so the JS session-echo skips overwriting)
    assert "OWL_FINDINGS_CATALOG_ENABLED = true" in body


def test_demo_findings_step_falls_back_when_disabled(monkeypatch):
    """Rollback: when findings_enabled=False, /demo step 7 reverts to the
    original 'Loading results…' placeholder + buildSummary() session-echo
    (the prior behaviour). Lab colleagues can revert with one bool flip."""
    real_load = cfg.load
    def disabled_load():
        d = real_load()
        d["findings_enabled"] = False
        return d
    monkeypatch.setattr(cfg, "load", disabled_load)

    r = client.get("/demo")
    assert r.status_code == 200
    body = r.text
    # Original placeholder restored
    assert "Loading results…" in body
    # Catalog preview specifically NOT present
    assert "body of evidence" not in body
    assert "See all findings" not in body
    # The window flag ASSIGNMENT is gone. (The bare identifier still appears
    # in buildSummary()'s early-return guard — that's fine; what gates the
    # behaviour is whether the server sets it to true.)
    assert "OWL_FINDINGS_CATALOG_ENABLED = true" not in body


# --- footer Findings link (owner ask 2026-06-12) ----------------------------

def test_footer_findings_link_present_when_enabled():
    r = client.get("/video")
    assert 'href="/findings"' in r.text
    assert "Beta: Findings" in r.text


def test_footer_findings_link_follows_flag(monkeypatch):
    real_load = cfg.load
    def disabled_load():
        d = real_load()
        d["findings_enabled"] = False
        return d
    monkeypatch.setattr(cfg, "load", disabled_load)
    import ui
    monkeypatch.setattr(ui.cfg, "load", disabled_load)
    r = client.get("/video")
    assert "Beta: Findings" not in r.text   # no dead link when rolled back


def test_every_cited_result_type_is_embeddable():
    """The class of bug behind 'no renderer for type=enhance' (S49): a
    finding can cite any result type, so every type actually cited by the
    published catalog must (1) be accepted by the /findings/source endpoint
    and (2) have a renderer entry in the finding page's hydrate dispatch.
    Both checks run against every published finding, so the next new result
    type fails here at publish time, not on the live page."""
    cited_types = {rid.split("/", 1)[0]
                   for f in findings.list_all() for rid in f.source_result_ids}
    assert cited_types, "expected at least one cited source result"
    for f in findings.list_all():
        page = client.get(f"/findings/{f.slug}")
        assert page.status_code == 200
        for t in cited_types:
            assert f"{t}: window.wlRender" in page.text, (
                f"finding page hydrate JS has no renderer entry for type {t!r}"
            )
    for f in findings.list_all():
        for rid in f.source_result_ids:
            t, tail = rid.split("/", 1)
            r = client.get(f"/findings/source/{t}/{tail.split('_')[-1]}/download.json")
            assert r.status_code == 200, (
                f"finding {f.slug!r}: cited source {rid!r} not downloadable ({r.status_code})"
            )
