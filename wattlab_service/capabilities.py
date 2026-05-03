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
RESULTS_DOWNLOAD   = "results_download"   # single-record fetch (per-job JSON / CSV used by /demo + recent-runs panels)
LIVE_TELEMETRY     = "live_telemetry"

# Workload runs — curated/pre-baked variants are Anonymous-allowed
VIDEO_RUN          = "video_run"          # codec preset run (Meridian or other curated source)
LLM_RUN            = "llm_run"            # curated task_key (T1/T2/T3) with the bundled prompt
IMAGE_RUN          = "image_run"          # curated seed prompt
RAG_RUN            = "rag_run"            # curated single-mode RAG question
CUSTOM_UPLOAD      = "custom_upload"      # video upload — Anonymous OK but quota-capped (see quotas module, CR-001 part D)

# Member-tier — the "members shape inputs" half of the CR-001 capability matrix
CUSTOM_PROMPT      = "custom_prompt"      # free-form LLM/image prompt OR custom ffmpeg args
BATCH_COMPARE      = "batch_compare"      # all-codecs sweep, LLM all-tasks, CPU-vs-GPU compare, RAG 3-mode compare
RAG_CORPUS_UPLOAD  = "rag_corpus_upload"  # PDF upload into the RAG corpus
RESULTS_EXPORT_CSV = "results_export_csv" # bulk CSV/JSON export of run history (≠ RESULTS_DOWNLOAD)

# Lab-only
SETTINGS_READ_FULL = "settings_read_full" # render-mode predicate (editable inputs vs read-only)
SETTINGS_WRITE     = "settings_write"
VARIANCE_RUN       = "variance_run"


# --- Capability → minimum tier ----------------------------------------------
#
# This is the policy. Edit here, not in route files.

_REQUIRED_TIER: dict[str, Tier] = {
    # Anonymous — public surface + curated/pre-baked workloads
    PUBLIC_PAGE:        Tier.Anonymous,
    QUEUE_VIEW:         Tier.Anonymous,
    RESULTS_DOWNLOAD:   Tier.Anonymous,
    LIVE_TELEMETRY:     Tier.Anonymous,
    VIDEO_RUN:          Tier.Anonymous,
    LLM_RUN:            Tier.Anonymous,
    IMAGE_RUN:          Tier.Anonymous,
    RAG_RUN:            Tier.Anonymous,
    CUSTOM_UPLOAD:      Tier.Anonymous,

    # Member — "members shape inputs"
    CUSTOM_PROMPT:      Tier.Member,
    BATCH_COMPARE:      Tier.Member,
    RAG_CORPUS_UPLOAD:  Tier.Member,
    RESULTS_EXPORT_CSV: Tier.Member,

    # Lab — instrument operators
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
