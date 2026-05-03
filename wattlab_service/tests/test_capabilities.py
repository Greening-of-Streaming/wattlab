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
])
def test_anonymous_cannot_use_member_capabilities(cap):
    """The four Member-tier capabilities are the public/private boundary the
    capability matrix calls out. Anonymous must be denied."""
    assert capabilities.can(Tier.Anonymous, cap) is False


@pytest.mark.parametrize("cap", [
    "custom_prompt",
    "batch_compare",
    "rag_corpus_upload",
    "results_export_csv",
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
        "custom_upload":       Tier.Anonymous,
        # Member — "members shape inputs" (CR-001 part C1)
        "custom_prompt":       Tier.Member,
        "batch_compare":       Tier.Member,
        "rag_corpus_upload":   Tier.Member,
        "results_export_csv":  Tier.Member,
        # Lab — instrument operators
        "settings_read_full":  Tier.Lab,
        "settings_write":      Tier.Lab,
        "variance_run":        Tier.Lab,
    }
    assert capabilities._REQUIRED_TIER == expected
