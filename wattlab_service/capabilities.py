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

# Public, no gating — every audience tier sees these
PUBLIC_PAGE        = "public_page"
QUEUE_VIEW         = "queue_view"
RESULTS_DOWNLOAD   = "results_download"   # single-record fetch (per-job JSON / CSV used by /demo + recent-runs panels)
LIVE_TELEMETRY     = "live_telemetry"

# Workload runs — curated/pre-baked variants are Anonymous-allowed
VIDEO_RUN          = "video_run"          # codec preset run (Meridian or other curated source)
LLM_RUN            = "llm_run"            # curated task_key (T1/T2/T3) with the bundled prompt
IMAGE_RUN          = "image_run"          # curated seed prompt
RAG_RUN            = "rag_run"            # curated single-mode RAG question
WORKING_NAV        = "working_nav"        # member home page (work nav grid) — Anonymous gets the guided tour at /demo instead
CUSTOM_UPLOAD      = "custom_upload"      # video upload — Member+ (CR-026); pre-CR-026 was Anonymous-with-quota

# Member-tier — the "members shape inputs" half of the CR-001 capability matrix
CUSTOM_PROMPT      = "custom_prompt"      # free-form LLM/image prompt OR custom ffmpeg args
BATCH_COMPARE      = "batch_compare"      # all-codecs sweep, LLM all-tasks, CPU-vs-GPU compare, RAG 3-mode compare
RAG_CORPUS_UPLOAD     = "rag_corpus_upload"      # PDF upload into the RAG corpus
RAG_CORPUS_DELETE_OWN = "rag_corpus_delete_own"  # CR-051 — delete a corpus PDF you uploaded (Lab can delete any via tier override)
RESULTS_EXPORT_CSV = "results_export_csv" # bulk CSV/JSON export of run history (≠ RESULTS_DOWNLOAD)
BENCHMARK_VIEW     = "benchmark_view"     # CR-061 — view benchmark runs + results pages (Member); running stays Lab (BENCHMARK_RUN)
ENHANCE_RUN        = "enhance_run"         # partner GPU transcode/upscale (Pixop) — hidden /enhance-run page (S40: Lab→Member so Jon/Tania can run the demo via magic-link off-LAN)

# Lab-only
SETTINGS_READ_FULL = "settings_read_full" # render-mode predicate (editable inputs vs read-only)
SETTINGS_WRITE     = "settings_write"
VARIANCE_RUN       = "variance_run"
BENCHMARK_RUN      = "benchmark_run"       # CR-061 — launch/cancel the in-app overnight benchmark
PREPARE_REM        = "prepare_rem"         # REM↔OWL integration — /prepare-rem hidden Lab page: encode a
                                           # source to a target VMAF + wrap it in timer/marker structure for
                                           # REM device-playback experiments (the generated file's SHARE link
                                           # is intentionally un-gated, PUBLIC_PAGE, so a remote collaborator
                                           # can download it without LAN/SSH — security by unguessable token).
RIG_CONTROL        = "rig_control"         # /decode — client-decode rig power console (Pi 5 / Pi 400 /
                                           # Google TV + monitor + optional Shelly master). Whole page is
                                           # Lab-only like /settings: it switches real mains relays.


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

    # Member — "members shape inputs"
    # CR-026: CUSTOM_UPLOAD moved from Anonymous to Member as part of the
    # anonymous-tier integrity pass (team meeting 2026-05-04). Anonymous
    # visitors run curated sources only; uploads require sign-in.
    CUSTOM_UPLOAD:      Tier.Member,
    WORKING_NAV:        Tier.Member,
    CUSTOM_PROMPT:      Tier.Member,
    BATCH_COMPARE:      Tier.Member,
    RAG_CORPUS_UPLOAD:     Tier.Member,
    RAG_CORPUS_DELETE_OWN: Tier.Member,
    RESULTS_EXPORT_CSV:    Tier.Member,
    BENCHMARK_VIEW:        Tier.Member,
    ENHANCE_RUN:           Tier.Member,   # S40 — partner-transcode demo, off-LAN via magic-link

    # Lab — instrument operators
    SETTINGS_READ_FULL: Tier.Lab,
    SETTINGS_WRITE:     Tier.Lab,
    VARIANCE_RUN:       Tier.Lab,
    BENCHMARK_RUN:      Tier.Lab,
    PREPARE_REM:        Tier.Lab,
    RIG_CONTROL:        Tier.Lab,
}


class CapabilityError(HTTPException):
    """403 raised by requires()/gate() when the resolved tier is too low.

    Subclasses HTTPException so every existing consumer is unchanged — the
    status is still 403 and `.detail` still names the capability ("requires
    <cap>"), which tests and fetch-based front-end code rely on. The extra
    `capability` / `required_tier` attributes let a single central exception
    handler (main.py) render a friendly HTML gate page for browser
    navigations instead of leaking raw JSON like {"detail":"requires …"}.
    """

    def __init__(self, capability: str):
        super().__init__(status_code=403, detail=f"requires {capability}")
        self.capability = capability
        self.required_tier = _REQUIRED_TIER[capability]


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
            raise CapabilityError(capability)

    return _dep


def gate(request: Request, *capabilities_required: str) -> None:
    """Imperative capability check inside a route body.

    Use when the *required capability depends on runtime input* — e.g. a
    single endpoint that accepts both a curated preset and a free-form
    custom command, where the cap is decided after the form is parsed.
    Raises 403 with the first failing capability named.

    Routes still never compare tiers directly:
        if preset == "all_codecs":
            capabilities.gate(request, BATCH_COMPARE)   # OK
        if request_tier == Tier.Member: ...             # NOT OK

    The factorisation contract: capability names are the only thing routes
    speak. If the policy moves BATCH_COMPARE between tiers tomorrow,
    this call site doesn't change.

    Validates capability names eagerly so typos blow up at the call, not
    at audit time.
    """
    t = resolve_tier(request)
    for cap in capabilities_required:
        if cap not in _REQUIRED_TIER:
            raise KeyError(f"undefined capability: {cap!r}")
        if not can(t, cap):
            raise CapabilityError(cap)


def all_capabilities() -> list[str]:
    """Sorted list of every defined capability — for tests and introspection."""
    return sorted(_REQUIRED_TIER.keys())
