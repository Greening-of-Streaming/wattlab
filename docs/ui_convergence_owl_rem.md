# UI Convergence — OWL × REM

> **Purpose:** propose a common look-and-feel for OWL (public-facing 3-tier
> energy lab) and REM (member-only fleet meter that must demo well to mixed
> audiences). Audit-then-plan; no code changes in this pass.
>
> **Author:** Claude (overnight scratchpad for Ben). 2026-05-08.
> **Source files audited:**
> - OWL: `wattlab_service/main.py` (`_BASE_STYLES`, `_AUTH_CHIP_STYLES`,
>   `_LOCK_STYLES`, `_HEADER_STYLES`, `_LOGO`, `_BACK`, `_QUEUE_BADGE`,
>   `_LIVE_JS`, `_CARBON_JS`, `_PROGRESS_JS`, `_CONF_HELP_WIDGET`, home
>   route `/`, video route `/video`), `wattlab_service/static/owl.svg`,
>   `wattlab_service/static/wl-charts.js`
> - REM: `repo/admin/templates/{base,index,exploration,experiments,gallery,admin}.html`,
>   `repo/admin/static/{style,exploration}.css`
> - Pre-existing partial: `/home/gos/wattlab/rem-theme.css` (drop-in
>   re-skin for the legacy linksi page; never extended to the admin app).
> - Both services live and inspected: OWL `localhost:8000`, REM `localhost:7001`.

---

## TL;DR (read this if nothing else)

1. **OWL's aesthetic is already on a well-trodden design-language path** —
   "near-black palette, monospace numerics, single neon accent" — the same
   bucket as Bloomberg Terminal, Datadog dark, Grafana, Linear, Vercel,
   Raycast, JetBrains Mono. It pattern-matches "scientific instrument"
   the moment a stranger lands on it, which is exactly the framing GoS
   sells. Don't blow it up.
2. **REM is currently in a different bucket** — sage-green SaaS card
   layout, system sans, drop shadows, rounded 12 px corners. It looks
   like a non-profit's grant management tool, not an energy lab.
   That's a brand mismatch with both OWL *and* the GoS framing
   ("not eco-warriors, just people who dislike waste").
3. **Recommendation:** REM moves toward OWL, not the other way round.
   OWL has shipped the public face, conference-tested, on the docs
   site, and the credibility scaffolding (confidence flags, lock
   badges, carbon strip) is purpose-built for that visual register.
4. **Cheap wins available immediately** without redesigning anything —
   token file, header chrome, owl mark, charts theme — give roughly
   80 % of the family-resemblance for a half-day of work.
5. **Radical option (recommended) — "REM goes lab"** — full dark flip
   of REM's admin app. Half-week. Big payoff for demos.
6. **There is also a do-nothing answer** that's defensible — see §10.
   I do not recommend it but it's listed for completeness.

---

## 1. Audience scoping (changes the brief)

| | OWL | REM |
|---|---|---|
| Public URL | `wattlab.greeningofstreaming.org` (HTTPS) | `rem.greeningofstreaming.org` (HTTP Basic Auth) |
| Tier 1 — Anonymous | ✅ Guided Tour, locked controls, capability matrix as the GoS pitch | 🚫 (Basic Auth wall) |
| Tier 2 — GoS member | ✅ Magic-link sign-in, custom prompts, batch compare | 🚫 |
| Tier 3 — Wattlab member | ✅ Lab tier (LAN/loopback IP) — full settings, calibration | ✅ Operator UI |
| Demo audience | Conference / public web visitors / press | Wattlab members + **demoed to mixed audiences** (your brief) |
| Trust posture | Public credibility instrument | Internal but **must look cool** |

**Implication for the convergence brief:** REM doesn't need OWL's
locked-control + sign-in chip + capability-matrix scaffolding (Authelia /
Basic Auth handles tiering at a layer below the UI). But the *aesthetic*
half of OWL — owl mark, dark canvas, accent green, monospace numerics,
restrained iconography, confidence-flag colour vocabulary — should
absolutely land on REM. That's the half a stranger forms an opinion from
in 0.5 seconds at a conference booth.

---

## 2. OWL — UI inventory

### 2.1 What's already there
- **Tokens** (`_BASE_STYLES` at `wattlab_service/main.py:1123`):
  ```
  --bg #0a0a0a · --panel #111 · --panel-2 #0d0d0d
  --border #222 · --border-2 #1a1a1a · --border-3 #333
  --text #e0e0e0 · --text-2 #bbb · --text-3 #8a8a8a · --text-4 #707070 · --text-5 #5a5a5a
  --accent #00ff99 · --accent-hover #00dd88 · --accent-soft #00ff9922
  --warn #ffaa00 · --err #ff4400
  ```
  Every text colour passes WCAG AA on `--bg` (annotated in the source).
- **Typography:** `font-family: monospace` everywhere
  (`ui-monospace, "SF Mono", Monaco, Consolas, "Liberation Mono"` per the
  rem-theme partial). 14 px base, 15 px on mobile.
- **Page chrome:**
  - `_LOGO` (footer GoS round bug)
  - `_BACK` (top-left owl SVG + "WattLab ← Home")
  - `_AUTH_CHIP_STYLES` + `_auth_chip_html()` (top-right Lab/Member/CTA chip)
  - `_HEADER_STYLES` = `_AUTH_CHIP_STYLES` (factorisation seam already
    in place — `_header_html(request)` is the helper)
  - `_QUEUE_BADGE` (bottom-right floating live-power + temps + queue widget)
- **Live data poller** (`_LIVE_JS`): polls `/live` every 3 s, updates
  every `[data-live="<key>"]` element on the page. Single source of truth
  for live numbers across all 10+ pages.
- **Confidence-flag system** (`_CONF_HELP_WIDGET`): 🟢🟡🔴 popover with
  pre-injected current threshold values from settings.json. Pages that
  opt in just add `class="conf-badge"` to a flag element.
- **Lock affordance** (`_LOCK_STYLES`, `_lock_badge_html()`,
  `_lock_class()`, `_disabled_attr()`): "🔒 Members only · Join GoS ↗"
  for capability-locked controls. The lock IS the membership pitch.
- **Carbon strip** (`_CARBON_JS`): `wlCarbonRow()` inline, `wlCarbonStrip()`
  per-result section, `fmtMass` (auto t/kg/g/mg/µg), `fmtEnergy` (auto
  GWh/MWh/kWh/Wh), EV-equivalence comparator, LIVE/EST badges.
- **Progress widget** (`_PROGRESS_JS`): `wlRenderProgress()`,
  `wlStageList()`, stage labels per workload — used by `/video /llm
  /image /rag /demo`.
- **Charts** (`wattlab_service/static/wl-charts.js`): `WlCharts.line()`
  wrapper around Chart.js 4.4.0 with semantic colour names (`cpu`, `gpu`,
  `accent`, `warn`, `err`) resolved against the OWL palette. Drop-in
  swap point if Chart.js is later replaced with uPlot/ECharts.
- **Asset:** `wattlab_service/static/owl.svg` — 2.4 KB teal/green
  geometric owl, recognisable at 26 px (back link) and 72 px (hero).

### 2.2 Visual idioms a stranger would notice
- Narrow reading column on most pages (`max-width: 780 px`) — OWL
  reads more like documentation than a dashboard.
- Hero "live watts" reading at 6 rem accent green on the home page — the
  one place OWL goes loud.
- Restrained icon vocabulary: ASCII glyphs (◆ ▶ ▣ ⏱ ⚙ 📐 ⚿). Emoji used
  sparingly and only where they carry semantic content (🟢🟡🔴 🔒).
- Square or 2 px border-radius everywhere. No drop shadows. No transforms
  on hover. No gradients (one inline tile uses `linear-gradient` for
  Findings, otherwise flat).
- "Beta · exploratory" honesty band on AI workloads — sets expectations
  before users hit P110 floor weirdness. This is OWL's voice.

### 2.3 What OWL is missing that REM has
- **Wide operator dashboard** layout — 1400 px container with charts +
  controls side-by-side
- **Multi-chart compare** with split/overlay toggle (REM's `/exploration`)
- **Snapshot Gallery** (saved chart PNGs + metadata)
- **Modal-driven create flows** (Create Group / Create Experiment) — OWL
  has settings.json forms but no modal pattern
- **Inline stats header** (Total kWh · Avg W · Mean · Median) on each chart

---

## 3. REM — UI inventory

### 3.1 What's there
- **Tokens** (`repo/admin/static/style.css` + `exploration.css`):
  ```
  --gos-green #6B8E5A · --gos-green-dark #4A6B3A · --gos-green-light #8FA87A
  --gos-white #FFFFFF · --gos-gray #F5F5F5 · --gos-gray-dark #333333
  --gos-border #E0E0E0
  ```
  Two `:root` declarations, one per file — duplicated, drift risk.
  `exploration.css` and `admin.html` also reference `--gos-blue` and
  `--gos-green-dark, #2d6a4f` which are not declared anywhere — a stale
  rename that hasn't propagated.
- **Typography:** system sans
  (`-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto …`)
- **Header chrome** (`base.html`):
  - Linear-gradient sage-green bar, GoS PNG logo (3 KB),
    "GOS Remote Energy Measurement" wordmark
  - 5-tab nav: Exploration / Groups / Experiments / Gallery / Admin
  - Authelia 401 redirect inline `<script>`
- **Charts:** Chart.js 4.4.0 + chartjs-adapter-date-fns +
  chartjs-plugin-annotation + chartjs-plugin-zoom (already CDN-loaded;
  matches OWL's Chart.js version — convergence point).
- **Live status:** none of OWL's persistent floating telemetry widgets.
  Collector status is exposed via `collector_status.json` but not
  surfaced in the chrome.
- **Iconography:** emoji-heavy (📌 💾 🔄 ▶️ ⏹️ ⛶ 🔍 ⏸️). Stylistically
  loud relative to OWL.
- **Cards / sections:** white background, 12 px radius, drop shadows
  (`0 2px 8px rgba(0,0,0,0.1)`), 25–30 px padding.
- **Buttons:** rounded 6–8 px, hover lift (`transform: translateY(-2px)`,
  shadow grow). SaaS web-app idiom.
- **Modals:** centred with 12 px radius, dark scrim, full-screen variant
  for charts.

### 3.2 What works well already
- Chart-centric layout — charts at the top, controls below — is the right
  hierarchy for "what is the fleet drawing right now"
- Aggregation `<details>` explainer is genuinely good copy — exactly the
  kind of progressive-disclosure idiom OWL uses
- Tab nav scales (5 sections) better than OWL's home-page nav grid
  would for the same number of sections
- Snapshot Gallery + ZIP download is a real feature, not just chrome

### 3.3 Stale / cruft worth a pass
- Two `:root` declarations of the same tokens → one `tokens.css`
- `--gos-blue` / `--gos-green-dark, #2d6a4f` references with no
  declaration → broken-when-someone-removes-the-fallback bug
- Inline `<style>` blocks in `admin.html` (~120 lines) — should move to
  the CSS file
- `inline-css.html` template is empty (0 bytes — a leftover seam)
- `experiments.html` has an inline `<script>` block for
  `toggleEndTimeRequired()` mid-template — small, but the JS conventions
  drift between templates

---

## 4. Diff — where they actually disagree

| Dimension | OWL | REM | Disagreement |
|---|---|---|---|
| Canvas | dark `#0a0a0a` | light `#F5F5F5` | **Maximum** — opposite philosophies |
| Accent | electric green `#00ff99` | sage green `#6B8E5A` | High — same hue family, opposite saturations |
| Typography | monospace everywhere | system sans | High |
| Surface | flat panels, 1 px borders, square | rounded cards, drop shadows | High |
| Buttons | flat block / outline | rounded with hover lift | Medium |
| Iconography | ASCII glyphs (◆ ▶ ▣) | emoji (📌 💾 🔄) | Medium |
| Logo | owl SVG (2.4 KB, geometric) | GoS round bug PNG | Medium |
| Wordmark | "WattLab" (terse) | "GOS Remote Energy Measurement" (verbose) | Medium |
| Layout | narrow reading column (780 px) | wide dashboard (1400 px) | Medium-but-justified — different jobs |
| Live numbers | `[data-live="key"]` poller, persistent badges | none in chrome | Functional gap |
| Credibility scaffolding | confidence flags, lock badges, carbon strip | none | Functional gap (REM doesn't claim CO₂e) |
| Charts | shared `wl-charts.js` (Chart.js 4.4.0 wrapper) | inline Chart.js 4.4.0 calls | Same engine, different wrapper |

**Same engine, different wrapper** for charts is the single most
important convergence opportunity — both use Chart.js 4.4.0, both
already have the correct adapters loaded, and `wl-charts.js` is already
designed to be the cross-project seam.

---

## 5. Three convergence options

I've laid out three options in increasing radical-ness. The user-facing
pitch in your brief was "don't hesitate to suggest alternatives or
radical redesigns" — so option C is the one I'd actually ship, but A is
non-negotiable cheap wins and B is the "if option C scares you" middle.

### Option A — Token convergence (4 hours)

**No visual flip.** Just stop drift between projects.

- New file: `/home/gos/wattlab/gos-design-tokens.css` (one canonical
  `:root` block — OWL's palette, AA-annotated)
- OWL imports it via static (or inlines via `_BASE_STYLES` regenerated
  from it at build time — current setup is inline strings, so simplest
  is a stub-comment: "tokens canonical in `gos-design-tokens.css`,
  copy-and-paste here when changes happen")
- REM imports it directly from
  `repo/admin/static/gos-design-tokens.css`. Rest of REM's CSS keeps
  consuming `--gos-green` etc. (alias `--accent-sage: #6B8E5A` etc.)
- Fix REM's two stale token references (`--gos-blue`, ad-hoc
  `--gos-green-dark, #2d6a4f`)
- Add OWL palette tokens (`--accent`, `--bg`, `--panel`, `--text-3`)
  alongside REM's tokens so future cross-pollination just works

**Cost:** half-day. **Visual change:** none. **Demos still look
different.** Pure plumbing.

### Option B — Soft convergence (1.5 days)

A + bring the **identifying-as-a-sibling** pieces across without
flipping REM dark:

- Replace REM's GoS PNG logo + verbose wordmark with the OWL pattern:
  `<owl.svg + "REM" + " by Greening of Streaming">` — 26 px on every
  page, top-left, links home. Matches OWL's `_BACK`.
- Move REM's GoS round bug to the **footer** only (mirrors OWL's `_LOGO`).
- Adopt OWL's auth-chip slot top-right (REM doesn't have member/lab
  tiers, but it can show the basic-auth user + collector health pill —
  same component shape, different content).
- Replace emoji-heavy buttons with restrained ASCII glyphs:
  `📌 → ◆`, `💾 → ⤓`, `🔄 → ↻`, `▶️ → ▶`, `⏹️ → ■`, `⛶ → ⤢`. Keep traffic
  lights as emoji (🟢🟡🔴) when they ever land.
- Replace the gradient header bar with a flat dark-on-light strip
  (sage on near-white) — half-step toward OWL without fully flipping.
- Migrate inline Chart.js calls to `wl-charts.js` so palette &
  semantic colour names are shared. (Light-themed charts can still use
  the same wrapper; theme is a chart option.)

**Cost:** 1–1.5 days. **Visual change:** REM looks visibly related to
OWL — same logo grammar, same icon vocabulary, same chart styling — but
keeps its light dashboard feel. **Demos:** "from the same family" but
not interchangeable.

### Option C — REM goes lab (recommended) (3–5 days)

A + B + flip REM to OWL's dark lab aesthetic.

The substantive moves:
1. **Canvas flip** — REM body bg `#F5F5F5 → #0a0a0a`, cards
   `#FFFFFF → var(--panel) #111`, text `#333 → var(--text)`.
2. **Header** — gradient sage bar → flat dark with thin accent
   border-bottom. Same nav, restyled with OWL's `.nav-util` /
   `.nav-tour` patterns.
3. **Cards → panels** — 12 px radius → 4 px (or square). Drop shadows
   removed. Hover transforms removed.
4. **Forms** — native input/select/checkbox restyled for dark. Need
   actual care here (REM has more forms than OWL, especially in
   Groups + Experiments modals). Contrast-test all states.
5. **Charts** — `WlCharts.line()` already takes a theme; flip Chart.js
   defaults to dark colours, axis gridlines `#222`, ticks `--text-4`.
6. **Modals** — keep the modal pattern; restyle to flat dark panels.
7. **Buttons** — adopt OWL's two button shapes:
   `[primary] = solid var(--accent) on bg`,
   `[secondary] = outlined var(--accent) on transparent`,
   `[danger] = solid var(--err)`. Drop the rounded-with-lift
   web-app vibe.
8. **Type voice** — adopt monospace for labels, values, headers. Body
   copy in modals can stay system-sans (long-text in dark monospace
   is the one place OWL would benefit from softening too — this is a
   chance to standardise).
9. **Live status pill** — bring OWL's `_QUEUE_BADGE` pattern across:
   bottom-right floating widget showing collector health + last-poll
   age + active devices. Persistent across all REM pages, mirrors
   OWL's "watts · CPU · GPU · queue" pill.
10. **Wider container preserved** — 1400 px stays. OWL pages are
    documents, REM pages are dashboards. Same canvas, different
    layouts; that's fine.

**Cost:** 3–5 days incl. dark-form polish + chart re-themeing
(Chart.js dark needs explicit gridline + tick colour overrides;
chartjs-plugin-zoom + chartjs-plugin-annotation also need a quick
contrast pass).

**Visual outcome:** REM and OWL look **obviously the same product
family**. A demo audience seeing one then the other reads them as
"two views of the same lab". The narrow vs wide layouts code as
"reading vs watching the fleet" rather than "two different vendors".

**Risk:** Dom Robinson has been the project lead and has presumably
iterated on the current look. Don't ship this without his sign-off.

### Option D — Do nothing structurally; small polish only (0.5 day)

Defensible position. Argument: "OWL is public, REM is not; aesthetics
don't need to converge if audiences don't overlap." I list this for
completeness, but I argue against it:

- Your own brief notes REM **will be demoed to various audiences**.
- The two appear together in `/home/gos/wattlab/REM/CLAUDE.md`'s "OWL
  vs REM" comparison and in `TRAINING_REM_5MIN.md` — anyone reading
  GoS strategic material is told they're complementary.
- Inconsistent visual language between the two halves of GoS's
  measurement story actively undermines the "we measure rigorously"
  pitch in the same way that mismatched font sizes undermine a
  scientific paper.

I would not pick D, but the option is captured here.

---

## 6. Recommended path

**Ship Option A unconditionally** (token file, drift fix, and the lock
in for the next steps). It's a half-day with no aesthetic risk.

**Then choose** between Option B (soft, sibling) and Option C (radical,
twin):
- B if Dom prefers the current look and the convergence pitch is
  primarily for Ben's eye + occasional shared docs.
- **C if you want the demo "wow"** at the next conference and you can
  put 3–5 days of UI work on the calendar.

Concretely, I'd ask Dom's preference before C is implemented, but A and
B are both **drop-in changes that don't pre-commit you to C** — A is the
shared-tokens plumbing, B is the family-resemblance touchstones (logo,
icons, header chrome, charts wrapper). You can stop after either.

If C is selected, gate it on Dom's review on a feature branch — don't
push to `master` of `nebul2/REM` without him seeing it.

---

## 7. File-by-file migration map (Option A + B + start of C)

### New files (created by this work, would live in REM repo)
- `repo/admin/static/gos-design-tokens.css` — canonical OWL palette,
  AA-annotated. Copy of the `:root` block from
  `wattlab_service/main.py:1123` (with the same WCAG comments).
- `repo/admin/static/wl-charts.js` — verbatim copy of OWL's
  `wattlab_service/static/wl-charts.js`. Sync rule: when OWL ships a
  chart-helper change, copy across. (Or: serve OWL's via CDN later.)
- `repo/admin/static/owl.svg` — verbatim copy. (2.4 KB, no rebrand
  needed — REM is "owl meter on the building, OWL is owl on the bench"
  in your existing framing.)

### Edits (REM)
- `repo/admin/templates/base.html` — replace logo + header-text block
  with the OWL `_BACK`-shaped wordmark; restyle `.gos-header` from
  gradient to flat (B) or flat-dark (C); add a `.collector-pill` slot
  in the top-right for the auth-chip-shaped status widget.
- `repo/admin/static/style.css` — `@import "gos-design-tokens.css"`
  at top; tokens stay (alias path); fix stale `--gos-blue` /
  `--gos-green-dark, #2d6a4f` references; add component classes that
  read OWL tokens for new dark-aware components.
- `repo/admin/static/exploration.css` — same import; on C, dark
  inversion across `.controls-panel`, `.chart-container`,
  `.feature-controls`, `.modal-content`, `.btn` variants.
- `repo/admin/templates/index.html` (Groups) — emoji → ASCII glyph
  swap on the "Select All / Deselect All / Edit / Delete" buttons.
- `repo/admin/templates/experiments.html` — same emoji → glyph pass.
- `repo/admin/templates/gallery.html` — thumbnail backgrounds want a
  pass on dark (snapshots are light by default so they'll pop).
- `repo/admin/templates/admin.html` — move inline `<style>` to CSS
  file; same emoji → glyph pass.
- `repo/admin/static/exploration.js` — migrate Chart.js construction
  calls to `WlCharts.line()` / `.bar()` shapes. (B: just to share the
  palette. C: also to flip dark.)

### Edits (OWL)
- `wattlab_service/static/gos-design-tokens.css` — same canonical
  file, served from OWL's static/ as the source-of-truth copy.
- `wattlab_service/main.py` `_BASE_STYLES` — gain a header comment
  pointing to `gos-design-tokens.css`, "edit there first, then sync
  here." Or, longer term, generate `_BASE_STYLES` at startup from the
  CSS file. (Today they're an inline Python string; touching that
  is a separate refactor.)
- No visual change to OWL.

### Files NOT touched
- OWL's lock-affordance, confidence-flag, carbon-strip, progress-widget,
  auth-chip systems — they're tier-aware and live in OWL's policy layer.
  Don't propagate to REM until REM grows tiers.
- REM's `app/collector.py`, `repo/scripts/`, `docker-compose*.yml`,
  schema — none of this is UI.
- Existing `/home/gos/wattlab/rem-theme.css` — was scoped to a separate
  legacy linksi page, not REM's admin app. Leave it where it is. The
  new tokens file in REM's static/ supersedes it for the admin app.

---

## 8. Concrete design moves (Option C reference)

A target visual spec for REM under Option C, keyed off OWL's existing
patterns. Not prescriptive code — design intent for Dom + Ben to react to.

```
┌─────────────────────────────────────────────────────────────────┐
│ owl.svg  REM   by Greening of Streaming        [user@host · ▣]  │
│ ─────────────────────────────────────────────────────────────── │
│                                                                 │
│ Exploration · Groups · Experiments · Gallery · Admin            │
│                                                                 │
│ ┌─ Chart A — Power Consumption ──────────── Total 12.4 kWh ──┐ │
│ │                                                  Avg 47 W  │ │
│ │  ╱╲    ╱╲      ╱╲╱╲                            Mean 49 W  │ │
│ │ ╱  ╲__╱  ╲____╱     ╲____      ╲╱             Median 46  ⤢│ │
│ │                                                            │ │
│ │ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ │ │
│ └────────────────────────────────────────────────────────────┘ │
│                                                                 │
│ Chart A (Primary):       [select experiment ▾]                 │
│ Chart B (Comparison):    [select experiment ▾]                 │
│ Time Range: [1 hour ▾]   Aggregation: [1 minute ▾]            │
│                                                                 │
│ ☑ Show Devices  ☑ Mean  ☑ Median  ☑ Total  ☑ Average           │
│ ◆ Annotation  ⤓ Snapshot  ↻ Refresh  ▶ Start  ■ End            │
│                                                                 │
│                              ────────────                       │
│                          GoS · methodology                      │
│                                                                 │
│                                          [● coll · 47W · 32d]   │
└─────────────────────────────────────────────────────────────────┘
```

Bottom-right `[● coll · 47W · 32d]` is the new collector-health pill —
mirrors OWL's `_QUEUE_BADGE`. `●` colour: green = polling, amber =
backoff active, red = collector down. Live mean wall-power across the
fleet. Device count.

---

## 9. Cross-pollination opportunities (not in scope but worth flagging)

Things REM does well that OWL could borrow back:
- **Snapshot Gallery** as a UI pattern. OWL persists results (`results/`)
  but the catalog is a flat directory listing on `/queue-status`. A
  proper "previous runs gallery" with thumbnails + per-run metadata is
  exactly the affordance the deferred Findings-step redesign needs.
- **Aggregation `<details>` explainer** — REM's copy is genuinely
  good. OWL's `/methodology` could borrow the inline expander idiom
  for individual settings.
- **Chart fullscreen mode** with `position:fixed` zoom. OWL's
  `wl-charts.js` doesn't have it yet; would help the calibration
  history panel on `/settings`.

Things OWL does well that REM should borrow once it has the data:
- **Confidence flags on aggregated stats.** REM's "Mean 49 W" is just a
  mean. With variance + sample-count, a 🟢🟡🔴 flag tells operators
  whether a number is currently trustworthy.
- **Carbon strip on each chart.** `wlCarbonStrip()` already takes
  energy in Wh and renders the per-zone comparison. Drop in.
- **Live grid intensity.** `carbon.py`'s home-zone poller would make
  REM's "what is the fleet emitting *right now*" question answerable
  without a schema change.

Both these directions need the upstream data work first (REM doesn't
have CO₂e in `gos_rem`, by design — see REM/CLAUDE.md). Captured here
so they're on the radar after the visual convergence lands.

---

## 10. Why I don't recommend "do nothing"

Three reasons:

1. **GoS framing.** "Not eco-warriors. Just people who dislike waste."
   The voice is engineer-pragmatic, not non-profit-warm. OWL's lab
   register matches the voice; REM's SaaS-card register doesn't.
2. **Demo cost.** Switching from one to the other in a talk loses
   audience momentum. Visual continuity is free credibility.
3. **Drift compounds.** REM has two `:root` declarations with one
   stale token in 4 months of solo work. OWL has 11 inline `<style>`
   blocks (tracked the lock styles via grep). Neither will get worse
   if you stop touching them, but as both grow, the convergence cost
   grows monotonically. Pay it now, in a contained 3–5 day push, vs
   pay it across every future session you touch either UI.

---

## 11. Open questions for you

- **Is Dom OK with REM going dark?** This is the only blocker I can
  see for Option C. If he's iterated on the sage-green look
  intentionally, that should be respected and Option B is the right
  ceiling.
- **Where does the canonical tokens file live?** In OWL's repo
  (with REM consuming a copy), in REM's repo (with OWL consuming a
  copy), or in a third location (`/home/gos/wattlab/gos-design-tokens.css`,
  symlinked into both `static/` directories)? My weak preference is
  the third — neither owns it, both link.
- **Should REM "own" the OWL name on its UI**
  (`OWL — Online WattLab` is the public OWL framing per
  `MEMORY.md`)? My read: no. REM keeps its name, but borrows the
  wordmark grammar (`mark + name + by Greening of Streaming`).
- **Conference timing.** CLAUDE.md memory says "stop framing CRs as
  pre-conference" — so this is purely an aesthetic / strategic
  question, not a deadline one. Convergence work can land whenever
  there's a 3–5 day window, not gated on an event.

---

## 12. Sources / references

Design-language inspiration (Option C is in this bucket):
- Bloomberg Terminal — dense data, monospace numerics, amber/green accents
- Datadog dark mode — observability dark UI, late-2010s convention
- Grafana — green-on-near-black for status, restrained chrome
- Linear / Vercel / Raycast — modern dev-tool dark UI
- JetBrains IDE dark themes — monospace + accent semantics

Web search (this session, 2026-05-08):
- [Halo Lab — Dark UI Design Principles](https://www.halo-lab.com/blog/dark-ui-design-11-tips-for-dark-mode-design)
- [Datadog — Introducing Dark Mode](https://www.datadoghq.com/blog/introducing-datadog-darkmode/)
- [DesignRush — Dashboard Design Principles 2026](https://www.designrush.com/agency/ui-ux-design/dashboard/trends/dashboard-design-principles)
- [UXPin — Dashboard Design Principles 2025](https://www.uxpin.com/studio/blog/dashboard-design-principles/)
- [DEV — Grafana 12 dashboards](https://dev.to/dev_tips/grafana-12-just-leveled-up-observability-as-code-and-dashboards-that-think-nlh)

In-repo references already cited above:
- `wattlab_service/main.py:1123` (`_BASE_STYLES`)
- `wattlab_service/main.py:212` (`_AUTH_CHIP_STYLES`)
- `wattlab_service/main.py:287` (`_LOCK_STYLES`)
- `wattlab_service/main.py:266` (`_HEADER_STYLES`)
- `wattlab_service/main.py:382` (`_LOGO`, `_BACK`)
- `wattlab_service/static/wl-charts.js` (chart wrapper)
- `wattlab_service/static/owl.svg` (asset)
- `repo/admin/templates/base.html` (REM chrome)
- `repo/admin/static/style.css` (REM tokens, header)
- `repo/admin/static/exploration.css` (REM dashboard styling)
- `/home/gos/wattlab/rem-theme.css` (the existing partial drop-in)

---

## 13. Suggested next session's first 30 minutes

If you wake up agreeing with Option A + B + C-pending-Dom, the
sequencing I'd hand to a fresh session is:

1. Create `/home/gos/wattlab/gos-design-tokens.css` — copy of OWL's
   `_BASE_STYLES` `:root` block, preserve AA comments.
2. Symlink into `wattlab_service/static/gos-design-tokens.css` and
   `REM/repo/admin/static/gos-design-tokens.css`.
3. REM `style.css` `@import "gos-design-tokens.css";` at line 1; alias
   `--gos-green: var(--accent)` etc. (or keep separate; either is fine
   for Option A).
4. Fix REM's stale `--gos-blue` / orphan `#2d6a4f` references.
5. Copy `wl-charts.js` and `owl.svg` into REM static/.
6. REM `base.html` — replace header logo block with OWL wordmark
   pattern.
7. REM emoji → ASCII glyph pass on buttons (3 templates).
8. Stop. Show Dom. Take feedback.

Steps 1–7 are roughly half a day and reversible. Steps after that
(the dark flip + dark forms + dark chart theme + collector pill) are
the C-tier lift.

— end of scratchpad —
