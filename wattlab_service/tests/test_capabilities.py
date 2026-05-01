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


# --- Policy snapshot --------------------------------------------------------

def test_required_tier_table_snapshot():
    """REGRESSION: This test pins the today's policy. A change to
    _REQUIRED_TIER is visible as a diff to this fixture, forcing the editor
    to acknowledge they're moving the security boundary.

    When CR-001 lands and adds Member-tier rows, update this fixture in the
    same commit that edits the table — the diff WILL be the security review.
    """
    expected = {
        "public_page":         Tier.Anonymous,
        "queue_view":          Tier.Anonymous,
        "results_download":    Tier.Anonymous,
        "live_telemetry":      Tier.Anonymous,
        "video_run":           Tier.Anonymous,
        "llm_run":             Tier.Anonymous,
        "image_run":           Tier.Anonymous,
        "rag_run":             Tier.Anonymous,
        "custom_upload":       Tier.Anonymous,
        "settings_read_full":  Tier.Lab,
        "settings_write":      Tier.Lab,
        "variance_run":        Tier.Lab,
    }
    assert capabilities._REQUIRED_TIER == expected
