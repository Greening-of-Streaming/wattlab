"""
Shared page chrome — Phase 2 of the 2026-06 refactor (ARCHITECTURE.md).

Everything a page shell needs that isn't page-specific: the design-token
stylesheet (_BASE_STYLES), header/auth chip, footer (logo + version stamp +
queue badge + shared JS bundle tags), capability lock badges, and the
<script src> tags for the static/wl-*.js bundles. main.py (and, from Phase 3,
the per-feature route modules) imports these by name; no behaviour lives here.
"""
from fastapi import Request

import audience
import auth
import version
from capabilities import can

# ── External links — single source of truth ─────────────────────────────────
# Every externally-hosted URL the UI points at lives here, so a changed link is
# a one-line edit. Referenced three ways, depending on the template mechanism:
#   • HTML f-strings (_LOGO, _DEMO_HTML, auth body)              → {CONST}
#   • JS string builders (carbon strip, chart_js)               → ' + CONST + '
#   • plain templates rendered via .replace() (_METHODOLOGY_HTML) → {TOKEN}, baked
#     in the route's .replace() chain
# The Language Lab AI position paper is a filesusr.com asset that can move —
# keep it here, never inline.
POSITION_PAPER_URL  = "https://555e2619-4a3d-4f25-8303-8fb567f350a1.filesusr.com/ugd/ecf0e7_a46203016e4e40c7aa638232bce16486.pdf"
GOS_URL             = "https://greeningofstreaming.org"
JOIN_GOS_URL        = "https://www.greeningofstreaming.org/membership"
OWL_CONTACT_EMAIL   = "owl@greeningofstreaming.org"
GOS_LOGO_URL        = "https://static.wixstatic.com/media/b1006e_f5e9aff607cf4133abf7089207dc3cab~mv2.png"
GITHUB_REPO_URL     = "https://github.com/greeningofstreaming/wattlab"
GITHUB_ISSUES_URL   = "https://github.com/greeningofstreaming/wattlab/issues"
ECO2MIX_URL         = "https://www.rte-france.com/eco2mix"
ELECTRICITYMAPS_URL = "https://www.electricitymaps.com"
EMBER_URL           = "https://ember-energy.org"
CHARTJS_URL         = "https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"



# --- Auth chip (tier-aware top-right widget) -------------------------------
#
# Rendered on every page the visitor can land on (today: `/` and `/demo`,
# more pages in CR-001 part C). Three states:
#
#   Anonymous → "Sign in" link → /auth/sign-in
#   Member    → "<email> · Sign out" form
#   Lab       → "▣ Lab" pill (auth is by IP, no sign-out makes sense)
#
# CSS lives in a string constant so any page that wants the chip just
# concatenates _AUTH_CHIP_STYLES into its own <style> block. (Could move
# to _BASE_STYLES later when more pages opt in.)

_AUTH_CHIP_STYLES = (
    ".auth-chip{position:fixed;top:0.6rem;right:0.75rem;z-index:100;"
    "font-family:monospace;font-size:0.72rem;color:var(--text-4);"
    "background:rgba(15,15,15,0.92);border:1px solid var(--border-2);"
    "padding:0.3rem 0.7rem;border-radius:2px;display:flex;gap:0.45rem;"
    "align-items:center}"
    ".auth-chip a,.auth-chip button{color:var(--accent);background:none;"
    "border:none;padding:0;font-family:monospace;font-size:inherit;"
    "cursor:pointer;text-decoration:none}"
    ".auth-chip a:hover,.auth-chip button:hover{text-decoration:underline}"
    ".auth-chip .auth-email{color:var(--text-3)}"
    ".auth-chip.lab{border-color:var(--accent);color:var(--accent)}"
    # CR-021 — Anonymous CTA variant. The chip is a status indicator for
    # Member/Lab but a sign-up *call to action* for Anonymous. On wide
    # displays (conference booths) the recessive 0.72 rem chip was easy
    # to miss; this variant reads as a button: filled accent background,
    # 0.85 rem font, key glyph for affordance. Member/Lab keep the
    # recessive look. The link inside inherits the inverted colour so
    # it doesn't double-style.
    ".auth-chip.cta{background:var(--accent);border-color:var(--accent);"
    "color:var(--bg);font-size:0.85rem;padding:0.4rem 0.85rem}"
    ".auth-chip.cta a{color:var(--bg);font-weight:bold}"
    ".auth-chip.cta a:hover{text-decoration:underline}"
)


def _auth_chip_html(request: Request) -> str:
    """Tier-aware sign-in widget. Pure HTML, no script — safe to inject
    into any page template via .replace('{AUTH_CHIP}', ...)."""
    t = audience.tier(request)
    if t == audience.Tier.Lab:
        return '<div class="auth-chip lab" title="Authenticated by LAN/loopback IP">▣ Lab</div>'
    if t == audience.Tier.Member:
        email = auth.member_email_from_request(request) or ""
        return (
            '<div class="auth-chip">'
            f'<span class="auth-email">{email}</span>'
            '<span style="color:var(--text-5)">·</span>'
            '<form method="post" action="/auth/sign-out" style="display:inline">'
            '<button type="submit">Sign out</button>'
            '</form>'
            '</div>'
        )
    # Anonymous — CR-021 prominent CTA variant. Members-only features
    # are visible-but-locked across the surface; the chip is the entry
    # point that turns those locks into unlocked features.
    return '<div class="auth-chip cta"><a href="/auth/sign-in">⚿ Sign in</a></div>'


# Page chrome — auth chip + back link. Mirrors `_FOOTER` so any page can
# concatenate `_HEADER_STYLES` into its <style> block and call
# `_header_html(request)` near the top of <body>. Standard pages already
# inline the chip and back link individually; `/queue-status` and
# `/methodology` use this helper directly.
_HEADER_STYLES = _AUTH_CHIP_STYLES


def _header_html(request: Request) -> str:
    return _auth_chip_html(request) + _BACK


# CR-027 — early tier framing on /demo Welcome step.
#
# The /demo Findings step already shows the full Public/Member/Lab matrix
# (capability table, CR-001 part B/2 + this CR's three-column refresh), but
# visitors complete most of the tour before they get there. This indicator
# answers "what tier am I?" up front, in plain language, with a link to
# either upgrade (Anonymous) or read the full matrix (Member/Lab).
#
# Server-rendered, no JS. Different surface from the corner auth chip:
# the chip is a status indicator + sign-in button; this is a one-line
# explanation embedded inline in the Welcome step's reading flow.
def _tier_indicator_html(request: Request) -> str:
    t = audience.tier(request)
    base_style = (
        'display:inline-block;font-family:monospace;font-size:0.78rem;'
        'padding:0.4rem 0.85rem;margin-bottom:1.25rem;'
        'border:1px solid var(--border-2);background:var(--panel-2);'
        'color:var(--text-3);line-height:1.5'
    )
    if t == audience.Tier.Lab:
        return (
            f'<div style="{base_style};border-color:var(--accent);color:var(--accent)">'
            "▣ You're on the GoS1 lab network — "
            '<span style="color:var(--text-3)">'
            'Lab tier · all access (settings, calibration, custom inputs)</span>'
            '</div>'
        )
    if t == audience.Tier.Member:
        return (
            f'<div style="{base_style}">'
            '◆ <span style="color:var(--accent)">Signed in as a GoS member</span> · '
            'you can drive the engine with custom prompts, custom ffmpeg commands, '
            'all-codecs sweeps, your own corpus and uploads. '
            '<a href="#step-6" onclick="goStep(6);return false;" '
            'style="color:var(--text-3);border-bottom:1px solid var(--border)">'
            'See the full capability matrix &rarr;</a></div>'
        )
    # Anonymous — frame the tour as the public surface, with a clear path
    # to unlock the rest.
    return (
        f'<div style="{base_style}">'
        '○ <span style="color:var(--text-2)">You\'re browsing as Anonymous</span> · '
        'curated demo runs, live measurement, full methodology — same numbers '
        'as members see. '
        '<a href="/auth/sign-in" style="color:var(--accent);'
        'border-bottom:1px solid var(--accent)">Sign in</a> '
        'to unlock custom inputs and uploads, or '
        '<a href="#step-6" onclick="goStep(6);return false;" '
        'style="color:var(--text-3);border-bottom:1px solid var(--border)">'
        'see what changes &rarr;</a></div>'
    )


# CR-001 part C2c — capability lock badge + dim treatment.
#
# Member-tier inputs (custom prompts, custom ffmpeg, all-codecs sweeps,
# batch / compare modes, RAG corpus upload) render visible-but-disabled
# for Anonymous, with the badge above as the GoS membership pitch.
# The locks ARE the pitch — see `/demo` capability matrix for the same
# product copy.
#
# Pure HTML / CSS, no script. Pages that opt in concatenate `_LOCK_STYLES`
# into their <style> block, then call `_lock_badge_html()` per locked
# control and add the `_lock_class()` to the parent block.

_LOCK_STYLES = (
    ".lock-badge{display:inline-flex;align-items:center;gap:0.35rem;"
    "border:1px solid var(--border-3);background:rgba(255,170,0,0.05);"
    "color:var(--warn);font-family:monospace;font-size:0.7rem;"
    "padding:0.2rem 0.55rem;text-decoration:none;border-radius:2px;"
    "margin-bottom:0.5rem}"
    ".lock-badge:hover{border-color:var(--warn);text-decoration:none}"
    ".lock-block{opacity:0.55;filter:saturate(0.5)}"
    ".lock-block input,.lock-block textarea,.lock-block button,"
    ".lock-block select,.lock-block label{cursor:not-allowed!important}"
)


def _lock_badge_html(request: Request, capability: str,
                      label: str = "Members only") -> str:
    """Return a 🔒 Members only · Join GoS pitch badge if `request` lacks
    `capability`; '' if the tier already has it. Pair with `_lock_class()`
    on the parent block so the dim/disabled treatment lands in the same
    place. The badge links to greeningofstreaming.org/membership."""
    if can(audience.tier(request), capability):
        return ""
    return (
        f'<a href="{JOIN_GOS_URL}" target="_blank" rel="noopener noreferrer" '
        f'class="lock-badge" title="{label} — join GoS to unlock">'
        f'🔒 {label} · Join GoS ↗</a>'
    )


def _lock_class(request: Request, capability: str) -> str:
    """Returns 'lock-block' (dim + not-allowed cursor) when the request
    lacks `capability`; '' when it has it. Drop into a class= attribute
    next to the lock badge."""
    return "" if can(audience.tier(request), capability) else "lock-block"


def _disabled_attr(request: Request, capability: str) -> str:
    """Returns ' disabled' when `request` lacks `capability`, else ''.
    Use on inputs/buttons inside a lock-block so they can't be focused
    or clicked. The runtime gate (`gate(request, ...)`) is the actual
    enforcement — this is just the polite UX layer."""
    return "" if can(audience.tier(request), capability) else " disabled"


_LOGO = (
    f'<a href="{GOS_URL}" target="_blank"'
    f' style="display:inline-flex;align-items:center;gap:0.6rem;'
    f'text-decoration:none;margin-bottom:1.5rem;opacity:0.75;'
    f'transition:opacity 0.2s" onmouseover="this.style.opacity=1"'
    f' onmouseout="this.style.opacity=0.75">'
    f'<img src="{GOS_LOGO_URL}" alt="Greening of Streaming"'
    f' height="32" style="display:block">'
    f'<span style="color:var(--text-4);font-size:0.72rem;font-family:monospace">'
    f'greeningofstreaming.org</span></a>'
)


_BACK = (
    '<a href="/" style="display:inline-flex;align-items:center;gap:0.55rem;'
    'color:var(--text-3);text-decoration:none;font-size:0.82rem;margin-bottom:1.5rem;'
    'transition:color 0.2s" onmouseover="this.style.color=\'#00ff99\'"'
    ' onmouseout="this.style.color=\'#777\'">'
    '<img src="/static/owl.svg" alt="OWL" '
    'style="height:26px;width:26px;display:block;flex-shrink:0">'
    '<span style="font-weight:bold;letter-spacing:0.02em">OWL</span>'
    '<span style="color:var(--text-5);margin-left:0.35rem">&nbsp;&nbsp;&larr; Home</span>'
    '</a>'
)


# Floating badge: shows watts + CPU + GPU temps + queue depth on every page.
# Values are filled in by the shared _LIVE_JS poller below via data-live hooks.
_QUEUE_BADGE = (
    '<div id="gos-qbadge" style="position:fixed;bottom:1rem;right:1rem;'
    'font-family:monospace;font-size:0.72rem;background:var(--panel);border:1px solid var(--border-2);'
    'padding:0.3rem 0.6rem;max-width:calc(100vw - 2rem)">'
    '<a href="/queue-status" style="color:var(--text-3);text-decoration:none;white-space:nowrap">'
    '<span data-live="watts">—</span>'
    ' · CPU <span data-live="cpu_tctl">—</span>'
    ' · GPU <span data-live="gpu_junction">—</span>'
    '<span data-live="queue_depth"></span>'
    '<span data-live="paused"></span>'
    '</a></div>'
)


# Phase 1 (2026-06-10): the shared JS bundles are real files under static/ —
# lintable, diffable, cacheable (version-sha cache-buster). Settings/meter
# copy reaches them per request via /ui-config.js (window.WL_CFG), so copy
# changes no longer need a service restart. See ARCHITECTURE.md.
_WL_ASSET_V = version.version_dict().get("sha") or "dev"


_UI_CFG_TAG = '<script src="/ui-config.js"></script>'


# Shared live-telemetry poller (static/wl-live.js): one /live fetch every 3s
# updates every element carrying a data-live="<key>" attribute; formatters
# live in the FMT table in that file.
_LIVE_JS = f'<script src="/static/wl-live.js?v={_WL_ASSET_V}"></script>'


# Shared carbon UI helpers. Two globals defined: `wlCarbonRow(energy)` for
# the inline CO2e line under any Energy (ΔE) row; `wlCarbonStrip(wh, label)`
# for the per-report "if this had run elsewhere" comparison strip. Both
# render explicit "live" / "estimated" badges so visitors know which data
# source they're looking at — single source of truth for that distinction.
# All carbon logic (fallback ladder, intensity table, polling) lives in
# carbon.py; this is the UI projection only.
# static/wl-carbon.js needs WL_CFG (the source URLs), so the config tag rides
# along. A page that includes /ui-config.js twice (here + _PROGRESS_JS) is
# harmless — same idempotent assignment, one cached fetch.
_CARBON_JS = (_UI_CFG_TAG
              + f'<script src="/static/wl-carbon.js?v={_WL_ASSET_V}"></script>')


# Small "BETA" chip used next to h1 on AI-workload pages and Guided Tour
# steps 2/3/4 (LLM, image, RAG). Single source of truth so the framing copy
# stays consistent: video is production-grade, AI workloads are exploratory.
_BETA_CHIP = (
    '<span style="font-size:0.55rem;letter-spacing:0.08em;'
    'color:var(--text-5);border:1px solid var(--border-3);padding:0.1rem 0.35rem;'
    'border-radius:2px;vertical-align:middle;margin-left:0.5rem;'
    'font-family:monospace">BETA</span>'
)


# Footer links — methodology + GitHub issue tracker. Methodology added 2026-05-08
# for universal access from every page; was previously only reachable via the
# /demo Confidence step or by typing /methodology directly.
_METHODOLOGY_LINK = (
    '<div style="margin-top:0.75rem;font-family:monospace;font-size:0.72rem;color:var(--text-5)">'
    'Full measurement protocol &middot; confidence framework &middot; scope statements: '
    '<a href="/methodology" '
    'style="color:var(--text-3);text-decoration:none;border-bottom:1px solid var(--border)">'
    'Methodology &rarr;</a></div>'
)


_ISSUES_LINK = (
    '<div style="margin-top:0.75rem;font-family:monospace;font-size:0.72rem;color:var(--text-5)">'
    'Spotted a bug or have a feature request? '
    f'<a href="{GITHUB_ISSUES_URL}" target="_blank" rel="noopener" '
    'style="color:var(--text-3);text-decoration:none;border-bottom:1px solid var(--border)">'
    'Open an issue on GitHub &rarr;</a></div>'
)


# Single source of truth for content colors, panel/border tones, and base
# readability rules. CSS variables defined in :root cascade globally, so any
# inline `style="color:var(--text-3)"` resolves correctly regardless of where
# this <style> block sits in the document. Injected via _FOOTER (every page
# that uses the standard footer) and via the gate page directly.
_BASE_STYLES = (
    '<style>'
    ':root{'
    # backgrounds
    '--bg:#0a0a0a;'
    '--panel:#111;'
    '--panel-2:#0d0d0d;'
    # borders (light → dark)
    '--border:#222;'
    '--border-2:#1a1a1a;'
    '--border-3:#333;'
    # text — text-3 is the new "secondary" default. All values were chosen
    # for WCAG AA contrast on --bg (≥4.5:1) except --text-5 which is for
    # purely decorative non-content (separators, faint hints).
    '--text:#e0e0e0;'      # primary body         (~13:1, AAA)
    '--text-2:#bbb;'       # bright secondary     (~9.7:1, AAA)
    '--text-3:#8a8a8a;'    # default secondary    (~6.6:1, AA)
    '--text-4:#707070;'    # tertiary / muted     (~4.7:1, AA)
    '--text-5:#5a5a5a;'    # faint decorative     (~3.5:1)
    # accents — already pass, just consolidated
    '--accent:#00ff99;'
    '--accent-hover:#00dd88;'
    '--accent-soft:#00ff9922;'
    '--warn:#ffaa00;'
    '--err:#ff4400;'
    '}'
    # global readability
    'body{font-size:14px;line-height:1.55}'
    '@media(max-width:600px){'
    'body{font-size:15px;line-height:1.6}'
    # bump the smallest fonts on mobile so muted text stays above ~12px
    '.sub,.subtitle,.scope,.label,.elapsed,.t-lbl{font-size:0.85rem!important}'
    '}'
    '</style>'
)


_FOOTER = (
    f'{_BASE_STYLES}'
    f'<footer style="margin-top:3rem;padding-top:1rem;border-top:1px solid var(--panel)">'
    f'{_LOGO}{_METHODOLOGY_LINK}{_ISSUES_LINK}'
    f'<div style="margin-top:0.75rem;color:var(--text-5);font-size:0.68rem;'
    f'font-family:monospace">{version.version_string()}</div>'
    f'</footer>'
    f'{_QUEUE_BADGE}{_LIVE_JS}{_CARBON_JS}'
)


# Confidence flag popover — inject into any page that shows .conf-badge elements.
# Plain string (not f-string) so JS curly braces need no escaping.
_CONF_HELP_WIDGET = (
    '<div id="conf-pop" style="display:none;position:fixed;z-index:9999;background:var(--panel);'
    'border:1px solid var(--border);padding:1rem 1.25rem;max-width:300px;font-size:0.8rem;'
    'line-height:1.7;box-shadow:0 4px 24px #000a">'
    '<div style="font-family:monospace;color:var(--text-5);font-size:0.65rem;text-transform:uppercase;'
    'letter-spacing:0.06em;margin-bottom:0.75rem">Confidence flag</div>'
    '<div style="margin-bottom:0.5rem">'
    '<span style="font-family:monospace">🟢 Repeatable</span>'
    '<span style="color:var(--text-3);display:block;font-size:0.75rem;padding-left:1.4rem">'
    '≥95% confident the task draws above idle, with enough task polls to confirm. '
    'Reliable enough to cite.</span></div>'
    '<div style="margin-bottom:0.5rem">'
    '<span style="font-family:monospace">🟡 Early insight</span>'
    '<span style="color:var(--text-3);display:block;font-size:0.75rem;padding-left:1.4rem">'
    '≥80% confident above idle, or too few polls for green. Directional, needs a longer run.</span></div>'
    '<div>'
    '<span style="font-family:monospace">🔴 Need more data</span>'
    '<span style="color:var(--text-3);display:block;font-size:0.75rem;padding-left:1.4rem">'
    'Not yet distinguishable from idle. Don\'t cite yet.</span></div>'
    '<div style="color:var(--text-5);font-size:0.7rem;margin-top:0.75rem;font-family:monospace">'
    'confidence = Φ(ΔW / SE), SE from this run\'s noise + the calibrated idle floor · '
    '<a href="/methodology" style="color:var(--text-3)">methodology</a></div>'
    '</div>'
    '<script>(function(){'
    'var s=document.createElement("style");'
    's.textContent=".conf-badge{cursor:pointer}";'
    'document.head.appendChild(s);'
    'var pop=document.getElementById("conf-pop");'
    'document.addEventListener("click",function(e){'
    'var b=e.target.closest(".conf-badge");'
    'if(b){e.stopPropagation();'
    'var r=b.getBoundingClientRect();'
    'pop.style.left=Math.min(r.left,window.innerWidth-320)+"px";'
    'pop.style.top=(r.bottom+6)+"px";'
    'pop.style.display=pop.style.display==="none"?"block":"none";'
    '}else if(!pop.contains(e.target)){pop.style.display="none";}'
    '});'
    '})();</script>'
)


# Shared progress utilities + WL_*_STAGES stage labels — injected into every
# test page (static/wl-progress.js). Stage wording (toggle-aware cooldown
# labels, meter name) is built in the browser from WL_CFG, resolved per
# request — the old import-time bake (and its restart-to-refresh constraint)
# is gone.
_PROGRESS_JS = (_UI_CFG_TAG
                + f'<script src="/static/wl-progress.js?v={_WL_ASSET_V}"></script>')


# CR-034 Phase A \u2014 shared compact-result-card helpers.
#
# Lifted from /demo's bespoke renderers so the four workload result cards
# (video, llm, rag, image) live in a single source of truth. /demo's
# wrappers call into these; CR-034 Phase B (prev-row click-to-expand on
# /video /llm /rag /image) reuses the same helpers to render expanded
# rows. Future drift-bug class \u2014 when a polish item ships on the main
# pages but not /demo (CR-019 lifecycle, CR-030 drift note) \u2014 is closed
# at the architectural level.
#
# Contract: every helper takes `{result, isPrev, savedAt}` and RETURNS an
# HTML string. No DOM mutation inside \u2014 callers decide where to render.
# Confidence flag, prompt blockquote, carbon strip (with sub-runs +
# drift note + projection toggle + EV equivalence), scope clarifier are
# all standard surface; pages can't accidentally drop one when they
# render through these helpers.
_RESULT_JS = f'<script src="/static/wl-result.js?v={_WL_ASSET_V}"></script>'


# Hydrate each step embed via the same /results/.../download.json + card
# renderer pattern the /findings embeds use. Dispatch on `kind` (so rag→RAG
# card) but fetch by the result_ref `type` (rag persists under results/llm/).
_BENCH_HYDRATE_JS = f'<script src="/static/wl-bench-hydrate.js?v={_WL_ASSET_V}"></script>'
