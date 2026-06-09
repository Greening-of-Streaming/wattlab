"""
Unit tests for `capabilities.py`.

Mirrors the test pattern set by tests/test_carbon.py (S16): plain `def test_x()`,
no FastAPI test client — `requires()` is exercised by calling the dependency
function directly with a stub Request.

What's covered:
  - Every defined constant has a row in _REQUIRED_TIER (typo guard)
  - can() respects the tier lattice (Lab can do everything, Anonymous can do
    only Anonymous-tier capabilities)
  - requires() raises 403 when the tier is too low, succeeds when high enough
  - requires() validates the capability name at factory-call time (early fail)
  - The today's-policy snapshot — pins the table contents so silent edits
    are visible in the diff
"""
from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import capabilities
from audience import Tier


# --- Stub Request -----------------------------------------------------------

@dataclass
class StubRequest:
    headers: dict
    client: SimpleNamespace | None


def lab_request():
    return StubRequest(headers={}, client=SimpleNamespace(host="127.0.0.1"))


def anon_request():
    return StubRequest(headers={}, client=SimpleNamespace(host="8.8.8.8"))


def member_request(monkeypatch):
    """Public IP + a stubbed `auth.member_email_from_request` returning an email.

    `audience.tier()` lazy-imports `auth`; we monkeypatch the resolver there
    so the test doesn't depend on real signing keys / cookies. Returned
    StubRequest carries no real cookie — the stub short-circuits the lookup.
    """
    import auth as _auth
    monkeypatch.setattr(_auth, "member_email_from_request",
                        lambda req: "member@example.org")
    return StubRequest(headers={}, client=SimpleNamespace(host="8.8.8.8"))


# --- Capability constants are all in the table ------------------------------

@pytest.mark.parametrize("cap", capabilities.all_capabilities())
def test_every_capability_constant_has_a_required_tier(cap):
    """If a capability is exported, it must have a row in the policy table.
    Catches typos / orphan constants at test time, not first-request time."""
    assert cap in capabilities._REQUIRED_TIER


# --- can() ------------------------------------------------------------------

@pytest.mark.parametrize("cap", capabilities.all_capabilities())
def test_lab_tier_can_do_everything(cap):
    """Tier ordering invariant: Lab >= every required tier."""
    assert capabilities.can(Tier.Lab, cap) is True


def test_anonymous_can_run_video():
    """Today's policy: anyone past gate password can run video. Pin it."""
    assert capabilities.can(Tier.Anonymous, capabilities.VIDEO_RUN) is True


def test_anonymous_cannot_write_settings():
    assert capabilities.can(Tier.Anonymous, capabilities.SETTINGS_WRITE) is False


def test_anonymous_cannot_run_variance():
    assert capabilities.can(Tier.Anonymous, capabilities.VARIANCE_RUN) is False


def test_anonymous_cannot_read_full_settings():
    """SETTINGS_READ_FULL is the editable-vs-read-only render predicate.
    Anonymous gets the read-only view."""
    assert capabilities.can(Tier.Anonymous, capabilities.SETTINGS_READ_FULL) is False


# --- Member-tier policy (CR-001 — "members shape inputs") -------------------

@pytest.mark.parametrize("cap", [
    "custom_prompt",
    "batch_compare",
    "rag_corpus_upload",
    "results_export_csv",
    "benchmark_view",
])
def test_anonymous_cannot_use_member_capabilities(cap):
    """The Member-tier capabilities are the public/private boundary the
    capability matrix calls out. Anonymous must be denied."""
    assert capabilities.can(Tier.Anonymous, cap) is False


@pytest.mark.parametrize("cap", [
    "custom_prompt",
    "batch_compare",
    "rag_corpus_upload",
    "results_export_csv",
    "benchmark_view",
])
def test_member_can_use_member_capabilities(cap):
    assert capabilities.can(Tier.Member, cap) is True


def test_member_can_run_curated_workloads():
    """Tier-lattice: Member inherits everything Anonymous can do."""
    for cap in (capabilities.VIDEO_RUN, capabilities.LLM_RUN,
                capabilities.IMAGE_RUN, capabilities.RAG_RUN,
                capabilities.CUSTOM_UPLOAD):
        assert capabilities.can(Tier.Member, cap) is True


def test_member_cannot_write_settings_or_run_variance():
    """Lab-only stays Lab-only — Member is not a settings operator."""
    assert capabilities.can(Tier.Member, capabilities.SETTINGS_WRITE) is False
    assert capabilities.can(Tier.Member, capabilities.VARIANCE_RUN) is False
    assert capabilities.can(Tier.Member, capabilities.SETTINGS_READ_FULL) is False


def test_can_raises_on_unknown_capability():
    with pytest.raises(KeyError):
        capabilities.can(Tier.Lab, "totally_made_up")


# --- requires() factory -----------------------------------------------------

def test_requires_factory_validates_capability_at_creation():
    """Typos surface at app startup, not first-request time."""
    with pytest.raises(KeyError):
        capabilities.requires("nonsense_capability")


@pytest.mark.asyncio
async def test_requires_passes_for_lab_request():
    dep = capabilities.requires(capabilities.SETTINGS_WRITE)
    # Should not raise
    await dep(lab_request())


@pytest.mark.asyncio
async def test_requires_raises_403_for_anonymous_when_lab_required():
    dep = capabilities.requires(capabilities.SETTINGS_WRITE)
    with pytest.raises(HTTPException) as exc:
        await dep(anon_request())
    assert exc.value.status_code == 403
    assert "settings_write" in exc.value.detail


@pytest.mark.asyncio
async def test_requires_passes_for_anonymous_when_anonymous_required():
    dep = capabilities.requires(capabilities.VIDEO_RUN)
    await dep(anon_request())  # should not raise


@pytest.mark.asyncio
async def test_requires_raises_403_for_anonymous_when_member_required(monkeypatch):
    """The Member-tier 403 is the user-facing artefact of the locked rows in
    the capability matrix. Pin it: Anonymous → CUSTOM_PROMPT raises."""
    dep = capabilities.requires(capabilities.CUSTOM_PROMPT)
    with pytest.raises(HTTPException) as exc:
        await dep(anon_request())
    assert exc.value.status_code == 403
    assert "custom_prompt" in exc.value.detail


@pytest.mark.asyncio
async def test_requires_passes_for_member_when_member_required(monkeypatch):
    dep = capabilities.requires(capabilities.CUSTOM_PROMPT)
    await dep(member_request(monkeypatch))  # should not raise


@pytest.mark.asyncio
async def test_requires_raises_403_for_member_when_lab_required(monkeypatch):
    dep = capabilities.requires(capabilities.SETTINGS_WRITE)
    with pytest.raises(HTTPException) as exc:
        await dep(member_request(monkeypatch))
    assert exc.value.status_code == 403


# --- gate() helper for runtime capability dispatch -------------------------

def test_gate_passes_when_tier_satisfies():
    """Lab tier should pass gate() for any capability."""
    capabilities.gate(lab_request(), capabilities.BATCH_COMPARE,
                      capabilities.CUSTOM_PROMPT)  # should not raise


def test_gate_raises_403_with_capability_name_in_detail():
    """The 403 detail must name the failing capability so the front-end
    can map it to a "Members only · Join GoS" affordance."""
    with pytest.raises(HTTPException) as exc:
        capabilities.gate(anon_request(), capabilities.CUSTOM_PROMPT)
    assert exc.value.status_code == 403
    assert "custom_prompt" in exc.value.detail


def test_gate_raises_on_first_failing_cap():
    """When multiple caps are required and several fail, gate() reports the
    first one — keeps the error deterministic and the trace short."""
    with pytest.raises(HTTPException) as exc:
        capabilities.gate(anon_request(),
                          capabilities.BATCH_COMPARE,
                          capabilities.CUSTOM_PROMPT)
    assert "batch_compare" in exc.value.detail
    assert "custom_prompt" not in exc.value.detail


def test_gate_validates_capability_names_eagerly():
    """A typo in a gate() argument should fail fast with KeyError, not
    silently bypass the check."""
    with pytest.raises(KeyError):
        capabilities.gate(lab_request(), "nonsense_capability")


def test_gate_with_no_caps_is_a_noop():
    """Calling gate() with zero arguments should not raise — useful for
    routes that conditionally build the cap list and may end up empty."""
    capabilities.gate(anon_request())  # should not raise


# --- Policy snapshot --------------------------------------------------------

def test_required_tier_table_snapshot():
    """REGRESSION: This test pins the today's policy. A change to
    _REQUIRED_TIER is visible as a diff to this fixture, forcing the editor
    to acknowledge they're moving the security boundary.

    When CR-001 lands and adds Member-tier rows, update this fixture in the
    same commit that edits the table — the diff WILL be the security review.
    """
    expected = {
        # Anonymous — public surface + curated workloads
        "public_page":         Tier.Anonymous,
        "queue_view":          Tier.Anonymous,
        "results_download":    Tier.Anonymous,
        "live_telemetry":      Tier.Anonymous,
        "video_run":           Tier.Anonymous,
        "llm_run":             Tier.Anonymous,
        "image_run":           Tier.Anonymous,
        "rag_run":             Tier.Anonymous,
        # Member — "members shape inputs" (CR-001 part C1) +
        # custom_upload (CR-026 — anonymous-tier integrity pass) +
        # working_nav (CR-026 — home page nav grid for Member/Lab; Anonymous is redirected to /demo)
        "custom_upload":       Tier.Member,
        "working_nav":         Tier.Member,
        "custom_prompt":       Tier.Member,
        "batch_compare":       Tier.Member,
        "rag_corpus_upload":     Tier.Member,
        "rag_corpus_delete_own": Tier.Member,  # CR-051
        "results_export_csv":    Tier.Member,
        "benchmark_view":        Tier.Member,  # CR-061 — view runs/results; running stays Lab
        "enhance_run":           Tier.Member,  # S40 — partner transcode (Pixop) demo, off-LAN via magic-link
        # Lab — instrument operators
        "settings_read_full":  Tier.Lab,
        "settings_write":      Tier.Lab,
        "variance_run":        Tier.Lab,
        "benchmark_run":       Tier.Lab,   # CR-061
    }
    assert capabilities._REQUIRED_TIER == expected


# --- CR-026: regressions on the integrity-pass changes ----------------------


def test_anonymous_cannot_upload():
    """CR-026 step 1 — CUSTOM_UPLOAD moved Anonymous → Member."""
    assert capabilities.can(Tier.Anonymous, capabilities.CUSTOM_UPLOAD) is False
    assert capabilities.can(Tier.Member,    capabilities.CUSTOM_UPLOAD) is True
    assert capabilities.can(Tier.Lab,       capabilities.CUSTOM_UPLOAD) is True


def test_anonymous_does_not_get_working_nav():
    """CR-026 step 5 — home page splits on WORKING_NAV cap (not raw tier).
    Anonymous redirects to /demo; Member/Lab see the work nav grid."""
    assert capabilities.can(Tier.Anonymous, capabilities.WORKING_NAV) is False
    assert capabilities.can(Tier.Member,    capabilities.WORKING_NAV) is True
    assert capabilities.can(Tier.Lab,       capabilities.WORKING_NAV) is True


# --- CR-026 step 5 — every FastAPI route must declare a cap or be waived ----


# Routes that legitimately need no cap.
_ROUTE_WAIVERS = {
    # Sign-out: any tier can sign out.
    ("/auth/sign-out", "POST"),
    # FastAPI auto-injected schema docs. Not data; the OpenAPI surface is
    # internal-only on the GoS1 deployment via nginx (LAN only). If/when
    # we expose the public app at greeningofstreaming.org, consider
    # disabling these via FastAPI(docs_url=None, redoc_url=None,
    # openapi_url=None) for production.
    ("/docs",                 "GET"),
    ("/docs/oauth2-redirect", "GET"),
    ("/redoc",                "GET"),
    ("/openapi.json",         "GET"),
}


def _route_caps(route) -> list[str]:
    """Pull capability strings out of a route's `Depends(requires(...))`
    dependencies. Empty list if none declared."""
    caps = []
    for dep in getattr(route, "dependencies", []) or []:
        # `Depends(requires(X))` evaluates `requires(X)` at decorator time
        # and wraps it; the inner function's __closure__ holds X.
        call = getattr(dep, "dependency", None)
        if call is None:
            continue
        closure = getattr(call, "__closure__", None) or ()
        for cell in closure:
            v = cell.cell_contents
            if isinstance(v, str) and v in capabilities._REQUIRED_TIER:
                caps.append(v)
    return caps


def test_every_route_declares_capability_or_is_waived():
    """Walk every registered FastAPI route. Each must either declare a
    capability via Depends(requires(...)) or appear in _ROUTE_WAIVERS.

    This catches the class of mistake that landed CR-026 in the first
    place: a new endpoint shipped without a cap, silently exposing data
    to whichever tier could reach it.
    """
    # main.py mounts /static relative to cwd, so chdir into the package
    # dir before import. (conftest.py adds the dir to sys.path; cwd is
    # separate.)
    import os
    from pathlib import Path
    pkg_dir = Path(__file__).parent.parent
    prev_cwd = os.getcwd()
    os.chdir(pkg_dir)
    try:
        import main as _main  # imports the FastAPI app
    finally:
        os.chdir(prev_cwd)
    untagged = []
    for route in _main.app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None) or set()
        if not path or not methods:
            continue
        # Ignore the StaticFiles mount and other internal routes
        if path.startswith("/static"):
            continue
        for method in methods:
            if method == "HEAD":  # FastAPI auto-adds HEAD for GET routes
                continue
            if (path, method) in _ROUTE_WAIVERS:
                continue
            if not _route_caps(route):
                untagged.append(f"{method} {path}")
    assert not untagged, (
        f"Routes missing Depends(requires(...)) and not in _ROUTE_WAIVERS:\n"
        + "\n".join(sorted(untagged))
    )


# --- Gate-page presentation (central CapabilityError handler in main.py) -----
#
# The capability *policy* is unit-tested above. These pin the *presentation*:
# a browser navigation to a gated page gets a friendly HTML gate, while a
# fetch/API caller keeps the JSON contract the front-end JS already handles.
# Integration-level, so they use a TestClient (unlike the rest of this file).

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402

_gate_client = TestClient(main.app)
_BROWSER = {"x-real-ip": "8.8.8.8", "accept": "text/html"}   # anonymous browser
_FETCH   = {"x-real-ip": "8.8.8.8", "accept": "*/*"}         # anonymous fetch/API


def test_member_gate_renders_friendly_html_for_browser():
    """A browser hitting a Member-gated page (e.g. /enhance-run) gets a styled
    gate, not raw JSON — with the contact email and a sign-in path."""
    r = _gate_client.get("/enhance-run", headers=_BROWSER)
    assert r.status_code == 403
    assert "text/html" in r.headers["content-type"]
    assert "Members only" in r.text
    assert "owl@greeningofstreaming.org" in r.text
    assert "/auth/sign-in" in r.text
    # The cryptic capability string must NOT leak to the human-facing page.
    assert "requires enhance_run" not in r.text


def test_member_gate_keeps_json_for_fetch_callers():
    """Same gated page via fetch (Accept: */*) keeps {"detail":"requires …"}
    so existing front-end JS error handling is unchanged."""
    r = _gate_client.get("/enhance-run", headers=_FETCH)
    assert r.status_code == 403
    assert "application/json" in r.headers["content-type"]
    assert r.json() == {"detail": "requires enhance_run"}


def test_lab_gate_does_not_offer_sign_in():
    """Lab is granted by network origin, never by sign-in — the Lab gate page
    must not dangle a sign-in CTA that cannot help. (All Lab-gated routes are
    POST/DELETE; a browser form post still sends Accept: text/html.)"""
    r = _gate_client.post("/variance/run", headers=_BROWSER)
    assert r.status_code == 403
    assert "text/html" in r.headers["content-type"]
    assert "Lab access only" in r.text
    assert "owl@greeningofstreaming.org" in r.text
    assert "/auth/sign-in" not in r.text
