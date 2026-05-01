"""
Capability table — what each audience tier is allowed to do.

This file IS the security policy. The `_REQUIRED_TIER` mapping below is the
canonical capability matrix; CR-001's product copy ("Members only · Join GoS"
locked rows) and the audit grep both ultimately resolve to this table.

Routes declare capabilities, not tiers, so a capability moving between tiers
("we now let Anonymous run all-codecs") is one row edited here, not 40 routes
changed. Routes use:

    @app.post("/foo", dependencies=[Depends(requires(SETTINGS_WRITE))])
    async def foo(...): ...

The grep target `Depends(requires(` is the audit anchor — count of route
decorators must equal count of `Depends(requires(` strings.

Today (Spine refactor commit B) only encodes the three Lab capabilities the
existing `_is_local()` checks already enforce. The richer CR-001 matrix
(Anonymous can upload ≤100 MB, Member can run all-codecs, etc.) edits this
file when CR-001 lands.
"""

from fastapi import HTTPException, Request

from audience import Tier, tier as resolve_tier


# --- Capability constants ---------------------------------------------------
#
# String-valued so test failures and 403 messages name the capability
# directly. One per row of the matrix in CHANGE_REQUESTS.md (CR-001).

# Public, no gating (anyone past today's gate password)
PUBLIC_PAGE        = "public_page"
QUEUE_VIEW         = "queue_view"
RESULTS_DOWNLOAD   = "results_download"
LIVE_TELEMETRY     = "live_telemetry"

# Workload runs — Anonymous today; CR-001 may add per-tier caps
VIDEO_RUN          = "video_run"
LLM_RUN            = "llm_run"
IMAGE_RUN          = "image_run"
RAG_RUN            = "rag_run"
CUSTOM_UPLOAD      = "custom_upload"

# Lab-only (currently behind _is_local() — to be replaced by capability check
# in commit C of the spine refactor)
SETTINGS_READ_FULL = "settings_read_full"   # render-mode predicate (editable inputs vs read-only)
SETTINGS_WRITE     = "settings_write"
VARIANCE_RUN       = "variance_run"


# --- Capability → minimum tier ----------------------------------------------
#
# This is the policy. Edit here, not in route files.

_REQUIRED_TIER: dict[str, Tier] = {
    # Anonymous-allowed (today: anyone past gate password)
    PUBLIC_PAGE:        Tier.Anonymous,
    QUEUE_VIEW:         Tier.Anonymous,
    RESULTS_DOWNLOAD:   Tier.Anonymous,
    LIVE_TELEMETRY:     Tier.Anonymous,
    VIDEO_RUN:          Tier.Anonymous,
    LLM_RUN:            Tier.Anonymous,
    IMAGE_RUN:          Tier.Anonymous,
    RAG_RUN:            Tier.Anonymous,
    CUSTOM_UPLOAD:      Tier.Anonymous,

    # Lab-only (today: _is_local())
    SETTINGS_READ_FULL: Tier.Lab,
    SETTINGS_WRITE:     Tier.Lab,
    VARIANCE_RUN:       Tier.Lab,
}


def can(audience_tier: Tier, capability: str) -> bool:
    """True if `audience_tier` is allowed to use `capability`.

    Tier ordering is `Anonymous < Member < Lab`, so a higher-tier audience
    can do everything a lower-tier audience can. Use this directly for
    render-mode predicates (e.g. `/settings` GET decides editable vs
    read-only based on `can(tier(request), SETTINGS_READ_FULL)`).
    """
    if capability not in _REQUIRED_TIER:
        raise KeyError(f"undefined capability: {capability!r}")
    return audience_tier >= _REQUIRED_TIER[capability]


def requires(capability: str):
    """FastAPI dependency factory.

    Usage:
        @app.post("/settings", dependencies=[Depends(requires(SETTINGS_WRITE))])
        async def settings_save(...): ...

    Raises 403 if the resolved tier doesn't satisfy the capability. Validates
    the capability name at factory-call time (not first-request time) so
    typos surface at app startup.
    """
    if capability not in _REQUIRED_TIER:
        raise KeyError(f"undefined capability: {capability!r}")

    async def _dep(request: Request):
        if not can(resolve_tier(request), capability):
            raise HTTPException(status_code=403, detail=f"requires {capability}")

    return _dep


def all_capabilities() -> list[str]:
    """Sorted list of every defined capability — for tests and introspection."""
    return sorted(_REQUIRED_TIER.keys())
