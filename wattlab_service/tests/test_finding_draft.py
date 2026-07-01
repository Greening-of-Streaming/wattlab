"""
Tests for the Lab-only LLM-assisted finding drafter (CREATE_FINDING).

Two halves:
  - engine/guardrails (finding_draft.py): context derivation, the validation
    layer (GoS framing ban, confidence honesty, scope integrity, number
    consistency), and the save round-trip — all with the LLM stubbed out.
  - routes (routes_finding_draft.py): Lab-gating (Anonymous/Member 403 via an
    8.8.8.8 X-Real-IP), feature-flag 404, and the no-write contract of POST
    /findings/draft.
"""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import finding_draft as fd
import findings as findings_mod
import settings as cfg
import main as main_mod


client = TestClient(main_mod.app)

# A real cited source from a published finding — guaranteed on disk, 🟢.
GOOD_RID = "video/e18a9d57"
ANON = {"x-real-ip": "8.8.8.8"}        # public IP → Anonymous tier
LAB = {"x-real-ip": "127.0.0.1"}       # loopback → Lab tier (TestClient host is not an IP)


def _good_json(prompt, model):
    return (
        'thinking... {"headline": "AV1 hardware uses 55% less energy than '
        'software at 1500 kbps", "claim_short": "0.32 Wh vs 0.71 Wh", '
        '"tags": ["video", "av1"], "caveats": ["single 120 s clip"], '
        '"body_md": "# Result\nThe GPU path used 0.32 Wh.\n"}'
    )


# --- context assembly ------------------------------------------------------

def test_gather_context_derives_confidence_and_scope():
    ctx = fd.gather_context([GOOD_RID])
    assert ctx["confidence"] in {"green", "yellow", "red"}
    assert ctx["scope"]                       # pulled from the result, not invented
    assert ctx["numbers"]                     # numbers harvested for the lint
    assert ctx["results"][0]["type"] == "video"


def test_gather_context_raises_on_unresolvable():
    with pytest.raises(fd.DraftError) as ei:
        fd.gather_context(["video/does-not-exist-xyz"])
    # The error coaches the type-vs-page-name slip and lists known types.
    assert "Known types" in str(ei.value)


def test_normalize_rid_corrects_page_name_prefix():
    # The page is /enhance-run but the stored result TYPE is 'enhance'. A token
    # that only exists under enhance/ must be auto-corrected.
    norm = fd.normalize_rid("enhance-run/8675abb9")
    assert norm == "enhance/8675abb9"
    assert findings_mod.resolve_result_path(norm) is not None


def test_draft_stores_normalized_source_ids():
    res = fd.draft_finding(["video/e18a9d57"], generate=_good_json, today="2026-06-24")
    assert res["draft"]["source_result_ids"] == ["video/e18a9d57"]


# --- draft happy path ------------------------------------------------------

def test_draft_finding_derives_fields_not_from_llm():
    res = fd.draft_finding([GOOD_RID], generate=_good_json, today="2026-06-24")
    assert res["ok"] is True
    d = res["draft"]
    # LLM-authored
    assert "AV1 hardware" in d["headline"]
    # Derived, never from the LLM
    assert d["confidence"] == fd.gather_context([GOOD_RID])["confidence"]
    assert d["source_result_ids"] == [GOOD_RID]
    assert d["first_measured"] == "2026-06-24"
    assert d["methodology_ref"] == fd.DEFAULT_METHODOLOGY_REF
    assert findings_mod._SLUG_RE.match(d["slug"])


def test_key_metrics_surfaces_nested_vqa_score():
    """The quality axis for /enhance-run findings is nested as <side>.vqa.score,
    not a flat key — it must be extracted (else the LLM has no quality numbers
    and writes an energy-only story), and the vqa scoring-time must NOT leak."""
    data = {"ml": {"vqa": {"score": 7.2, "model": "CompressedVQA-HDR (NR)",
                            "duration_s": 7.5},
                   "energy": {"delta_e_wh": 1.56}}}
    metrics = fd._key_metrics(data)
    assert "ml.vqa.score = 7.2 NR-VQA (higher = better quality)" in metrics
    assert "ml.energy.delta_e_wh = 1.56 Wh" in metrics
    # scoring overhead inside the vqa dict is noise — must be skipped
    assert not any("vqa.duration_s" in m for m in metrics)


def test_angle_steers_the_prompt():
    ctx = fd.gather_context([GOOD_RID])
    sig = fd.detect_signals(ctx)
    p = fd.build_prompt(ctx, sig, angle="lead with the quality gain")
    assert "HIGHEST-PRIORITY framing" in p
    assert "lead with the quality gain" in p
    # absent by default
    assert "HIGHEST-PRIORITY framing" not in fd.build_prompt(ctx, sig)


def test_default_prompt_carries_quality_budget_framing():
    ctx = fd.gather_context([GOOD_RID])
    p = fd.build_prompt(ctx, fd.detect_signals(ctx))
    assert "what you get for your energy budget" in p


def test_draft_route_passes_angle(monkeypatch):
    captured = {}
    def cap(prompt, model):
        captured["prompt"] = prompt
        return _good_json(prompt, model)
    monkeypatch.setattr(fd, "_default_generate", cap)
    monkeypatch.setattr(fd, "measurement_in_progress", lambda: False)
    r = client.post("/findings/draft",
                    json={"source_result_ids": [GOOD_RID], "angle": "quality-first lens"},
                    headers=LAB)
    assert r.status_code == 200
    assert "quality-first lens" in captured["prompt"]


def test_extract_json_tolerates_reasoning_preamble_and_raw_newlines():
    obj = fd._extract_json('reasoning <think> {"a": "x\ny", "b": 1} trailing')
    assert obj == {"a": "x\ny", "b": 1}


# --- guardrails ------------------------------------------------------------

def _meta(**over):
    base = dict(slug="tmp-test", version=1, first_measured="2026-06-24",
                last_refined="2026-06-24", headline="h", claim_short="c",
                methodology_ref="m", source_result_ids=[GOOD_RID],
                confidence="green", scope="")
    base.update(over)
    return base


def test_lint_blocks_bandwidth_to_network_energy():
    ctx = fd.gather_context([GOOD_RID])
    issues = fd.validate_draft(_meta(scope=ctx["scope"]),
                              "Higher bitrate means more network energy.", ctx=ctx)
    assert any(i["code"] == "bandwidth_network_energy" and i["severity"] == "error"
               for i in issues)


def test_lint_allows_networks_use_energy_without_data_link():
    ctx = fd.gather_context([GOOD_RID])
    issues = fd.validate_draft(_meta(scope=ctx["scope"]),
                              "Networks use energy, with attribution caveats.", ctx=ctx)
    assert not any(i["code"] == "bandwidth_network_energy" for i in issues)


def test_confidence_inflation_is_an_error():
    ctx = dict(confidence="yellow", scopes=["S"], numbers=set(),
               results=[{"id": GOOD_RID}])
    issues = fd.validate_draft(_meta(confidence="green", scope="S"), "body", ctx=ctx)
    assert any(i["code"] == "confidence_inflated" for i in issues)


def test_red_source_blocks():
    ctx = dict(confidence="red", scopes=["S"], numbers=set(),
               results=[{"id": GOOD_RID}])
    issues = fd.validate_draft(_meta(confidence="red", scope="S"), "body", ctx=ctx)
    assert any(i["code"] == "red_source" and i["severity"] == "error" for i in issues)


def test_scope_must_match_cited_result():
    ctx = fd.gather_context([GOOD_RID])
    issues = fd.validate_draft(_meta(scope="a scope I made up"), "body", ctx=ctx)
    assert any(i["code"] == "scope_mismatch" for i in issues)


def test_unverified_number_is_warned():
    ctx = fd.gather_context([GOOD_RID])
    issues = fd.validate_draft(_meta(scope=ctx["scope"]),
                              "It drew 99999.9 Wh on the run.", ctx=ctx)
    assert any(i["code"] == "unverified_number" and i["severity"] == "warning"
               for i in issues)


def test_number_check_accepts_derived_deltas_and_dedupes():
    """A finding naturally states differences of measured values (an ML-vs-ffmpeg
    energy delta, a before/after size change). Those must NOT warn, a genuine
    fabrication MUST, and each distinct untraceable figure is reported once."""
    ctx = fd.gather_context([GOOD_RID])
    # pick two real salient values and state their difference + a fabrication,
    # repeating the fabrication to prove dedupe.
    vals = sorted(ctx["salient"])
    a, b = vals[-1], vals[0]
    delta = round(a - b, 4)
    body = (f"The delta was {delta} Wh. Again {delta} Wh. "
            f"But 88888.8 Wh is invented, and 88888.8 Wh once more.")
    issues = [i for i in fd.validate_draft(_meta(scope=ctx["scope"]), body, ctx=ctx)
              if i["code"] == "unverified_number"]
    msgs = " ".join(i["message"] for i in issues)
    assert "88888.8" in msgs                       # fabrication caught
    assert str(delta) not in msgs                  # derived delta accepted
    assert len(issues) == 1                         # deduped, not 2


def test_number_check_basis_is_tight_not_whole_json():
    """Regression: the prose-number basis is the figures handed to the LLM
    (~dozens), not every value in the JSON (~hundreds) — else a fabrication
    spuriously matches some unrelated raw number and is waved through."""
    ctx = fd.gather_context([GOOD_RID])
    assert len(ctx["allowed"]) < len(ctx["numbers"])


def test_dangling_source_is_error():
    issues = fd.validate_draft(_meta(source_result_ids=["video/nope"]), "b")
    assert any(i["code"] == "dangling_source" for i in issues)


def test_motto_is_warned():
    issues = fd.validate_draft(_meta(), "We are not eco-warriors, just careful.")
    assert any(i["code"] == "motto" and i["severity"] == "warning" for i in issues)


# --- measurement-integrity guard -------------------------------------------

def test_draft_refuses_during_measurement(monkeypatch):
    monkeypatch.setattr(fd, "measurement_in_progress", lambda: True)
    with pytest.raises(fd.DraftError):
        fd.draft_finding([GOOD_RID], generate=_good_json)


# --- save round-trip (writes a throwaway finding, then cleans up) ----------

def test_save_draft_round_trips_through_loader():
    slug = "zz-finding-draft-selftest"
    path = Path(findings_mod._FINDINGS_DIR) / f"{slug}.md"
    ctx = fd.gather_context([GOOD_RID])
    meta = _meta(slug=slug, headline="Selftest finding", claim_short="x",
                 confidence=ctx["confidence"], scope=ctx["scope"],
                 related_findings=[], supersedes=None, tags=["test"], caveats=[])
    try:
        written = fd.save_draft(meta, "# Selftest\n\nA throwaway body.")
        assert written == path and path.exists()
        loaded = findings_mod.load(slug)
        assert loaded is not None and loaded.headline == "Selftest finding"
    finally:
        path.unlink(missing_ok=True)
        findings_mod._CACHE.pop(slug, None)


def test_save_refuses_with_blocking_error():
    with pytest.raises(fd.DraftError):
        fd.save_draft(_meta(source_result_ids=["video/nope"], slug="zz-should-not-write"),
                      "body")
    assert not (Path(findings_mod._FINDINGS_DIR) / "zz-should-not-write.md").exists()


# --- route gating ----------------------------------------------------------

def test_draft_route_lab_ok(monkeypatch):
    monkeypatch.setattr(fd, "_default_generate", _good_json)
    monkeypatch.setattr(fd, "measurement_in_progress", lambda: False)
    r = client.post("/findings/draft", json={"source_result_ids": [GOOD_RID]},
                    headers=LAB)
    assert r.status_code == 200, r.text[:300]
    body = r.json()
    assert body["ok"] is True
    assert body["draft"]["confidence"] in {"green", "yellow", "red"}


def test_draft_route_rejects_anonymous():
    r = client.post("/findings/draft", json={"source_result_ids": [GOOD_RID]},
                    headers=ANON)
    assert r.status_code == 403


def test_draft_save_route_rejects_anonymous():
    r = client.post("/findings/draft/save",
                    json={"meta": _meta(), "body_md": "x"}, headers=ANON)
    assert r.status_code == 403


def test_draft_page_rejects_anonymous():
    r = client.get("/findings/draft", headers=ANON)
    assert r.status_code == 403


def test_draft_page_lab_renders():
    r = client.get("/findings/draft", headers=LAB)
    assert r.status_code == 200
    assert "Draft a finding" in r.text


def test_draft_route_400_without_ids():
    r = client.post("/findings/draft", json={"source_result_ids": []}, headers=LAB)
    assert r.status_code == 400


def test_catalog_shows_draft_entrypoint_for_lab():
    r = client.get("/findings", headers=LAB)
    assert r.status_code == 200
    assert 'href="/findings/draft"' in r.text
    assert "Draft a finding" in r.text


def test_catalog_hides_draft_entrypoint_for_anonymous():
    r = client.get("/findings", headers=ANON)
    assert r.status_code == 200
    assert 'href="/findings/draft"' not in r.text


def test_draft_route_404_when_findings_disabled(monkeypatch):
    real = cfg.load
    monkeypatch.setattr(cfg, "load", lambda: {**real(), "findings_enabled": False})
    r = client.post("/findings/draft", json={"source_result_ids": [GOOD_RID]},
                    headers=LAB)
    assert r.status_code == 404
