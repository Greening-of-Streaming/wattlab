# OWL Change Requests — Closed

Archive of fully-shipped CRs. Active work lives in `CHANGE_REQUESTS.md`.

Each entry preserves the original problem statement and agreed direction; the **Status** line records when it landed and which commit closed it. Where a CR's headline scope shipped but a follow-up step was deferred, the Status line names the residual item — promote to a new active CR if/when it becomes urgent.

Ordered by CR number.

---

## CR-001 · Two-tier OWL: anonymous public + authenticated members

**Status:** ✅ shipped 2026-05-03 on `feature/cr-001-two-tier`. All parts (A, B/1, B/2, C1, C2a, C2b, C2c, D, task #10) landed across S19 + S20. Closed in commit `11ecbd0` (S20 part 4 — docs tidy). Ready to merge to `main`.
**Triggered by:** demo on 2026-05-01 — discussion of opening OWL to the wider streaming community.
**Refined 2026-05-01:** anonymous tier explicitly *can* upload (capped at 100 MB, 1 concurrent job per visitor); LAN/SSH-tunnel auto-detection already implements the Lab tier today; quotas restated below.

### Shipped in S19 (commits on `feature/cr-001-two-tier`)

- **Part A** (3b05152) — magic-link auth: `auth.py`, `email_send.py`, `/auth/sign-in /verify /sign-out`. Member allowlist `data/members.json`. `audience.tier()` returns Member from cookie. Gate middleware bypasses `/auth/*` and any valid session cookie.
- **Part B/1** (e8bc5f0) — tier-aware routing on `/`. Anonymous → 302 `/demo`; Member/Lab → nav grid. Sign-in/Sign-out/Lab chip top-right.
- **Part B/2** (b187c92) — capability matrix on `/demo` Findings step. 7-row Public-vs-GoS-member table + Join-GoS CTA + sign-in CTA. The locks are the membership pitch.
- **Part C1** (8e9fe56) — Member-tier capability constants in `capabilities.py`: `CUSTOM_PROMPT`, `BATCH_COMPARE`, `RAG_CORPUS_UPLOAD`, `RESULTS_EXPORT_CSV`. Snapshot test pinned. 21 new tests.
- **Part C2a** (d6d3482) — `capabilities.gate(request, *caps)` imperative helper. Retag `/llm/run-all` → BATCH_COMPARE; `/rag/build-index` → RAG_CORPUS_UPLOAD. Inline `gate()` on `/llm/run` (prompt set, repeats>1, device='both'), `/video/use-source` + `/video/upload` (preset='all_codecs', custom_cmd*), `/image/start` (device in {both, compare_models}).
- **Part C2b** (680e4ac) — `curated.py` (CANONICAL_IMAGE_PROMPT, CANONICAL_RAG_QUESTION, CANONICAL_RAG_MODEL). `/image/start`, `/rag/run`, `/rag/run-compare` made `prompt`/`question` optional; absent → server uses curated; present → gate(CUSTOM_PROMPT or BATCH_COMPARE). `/demo` JS dropped the hardcoded prompt/question params on image and RAG.

### Shipped in S20

- **Part C2c** (8bdc4cb) — `_LOCK_STYLES` + `_lock_badge_html()` + `_lock_class()` + `_disabled_attr()` helpers. Applied across `/llm` (prompt editor, Both, repeats>1, Run All), `/video` (all-codecs preset, custom-cmd textarea now keys on CUSTOM_PROMPT so Members get edit too), `/image` (prompt textarea, Both, Compare Models), `/rag` (question, 3-mode compare, Build/Rebuild). JS on each page reads `CAN_CUSTOM_PROMPT` / `CAN_BATCH_COMPARE` flags from server and skips the corresponding form params for Anonymous so the runtime gate doesn't trip on pre-filled defaults.
- **Part D** (1d15857) — per-tier concurrent-job caps and per-tier upload size caps. `queue_control._visitor_key()` resolves Anonymous to `a:<ip>`, Member to `m:<email>`, Lab to None (uncapped). `enqueue()` rejects (returns None → 429) when at cap; the worker publishes `current_visitor_key`. Settings keys: `queue_anonymous_cap=1`, `queue_member_cap=4`, `upload_size_anonymous_mb=100`, `upload_size_member_mb=1024`. `/video/upload` Content-Length pre-check returns 413 before reading the body. 12 new queue_control tests. `/settings` page renders a "Tier limits" section.
- **Task #10** (5d7897c) — `WATTLAB_GATE_PASSWORD` and the gate middleware fully removed. The shared-password gate was the wrong shape once magic-link + per-tier caps shipped: it gated everyone equally and conflated Anonymous identity with password possession. CLAUDE.md, TESTING.md, bin/README.md, bin/stage-on, bin/stage-off all updated to drop the cookie. 77 lines removed from main.py; loopback `/live` now resolves Lab tier directly.

180 tests passing.

### Factorisation contract (held throughout S19, must keep holding)

- **Capability table is the policy.** `capabilities._REQUIRED_TIER` is the single source of truth. New rule = one row edit.
- **Routes only declare or call the helpers.** `Depends(requires(CAP))` (decorator) or `gate(request, CAP)` (imperative). Grep `audience.tier(request) ==` in route files = 0.
- **Business modules know nothing about auth.** Grep `import audience` / `import capabilities` in `video.py`/`llm.py`/`image_gen.py`/`rag.py` = 0.
- **No runtime "is this default?" detection.** Capability is decided by *presence/absence of free-form input* (curated wrapper pattern in C2b) or by *enum value* (preset='all_codecs' in C2a).
- **Curated content lives in `curated.py`.** Adding pre-baked content to the Anonymous path = one row edit there; no policy change.

### Problem

OWL is currently single-tier: one shared password (`WATTLAB_GATE_PASSWORD`) gates everything. Two pressures:

1. **Conference / public visitors** may not have the technical background for the full UI's depth (settings, calibration, custom ffmpeg commands, CSV export, etc.). The first public showing should be approachable.
2. **GoS membership needs a value proposition.** If the public version is identical to what members get, there's no incentive to join. Membership should unlock real benefits.
3. **Security posture differs.** A public-facing version needs much harder limits (rate-limit, no uploads, no custom commands) than the trusted-member version.

But also:
- We do *not* want to fork the codebase (double maintenance, guaranteed drift).
- We do *not* want to gate the *measurement* itself behind auth — the whole GoS mission is making energy / CO₂e visible. If a casual visitor can't run a workload, the project fails its mission.
- A GoS member showing OWL to a colleague at a conference booth shouldn't have to "find the password" — auth should be optional, additive, low-friction.

### Strategic intent — OWL as a GoS membership funnel

OWL has a **dual purpose**, and the two reinforce each other:

1. **Technical mission (always was):** make the energy and CO₂e cost of streaming workloads visible, on real hardware, against real grid data — earning streaming-industry credibility for GoS. *"Not eco-warriors. Just people who dislike waste."*
2. **Recruitment mission (now explicit with two-tier):** OWL is **a sales tool for GoS itself.** Every public visitor sees not only what OWL measures but also — through the locked rows in the capability matrix — what becomes possible if they join GoS. The capability matrix is **product copy first, security model second.** The locks are the pitch, not the punishment.

**Implications that flow from "OWL is a sales channel":**

- **Conversion design matters.** "Want to Join GoS" CTA copy, placement, and click-through destination (presumably `greeningofstreaming.org/join` or equivalent) is a deliberate design decision, not an afterthought.
- **Friction on the public side is strategic, not regrettable.** The point of locking custom-upload, calibration, etc. behind membership is not "to keep visitors out" — it's to give them a reason to join. Public capabilities should be **genuinely useful** (measurements are credible, results citable) so visitors form a positive impression *before* they hit a lock.
- **Public usefulness is the recruitment funnel's top-of-funnel.** A weak public version means fewer visitors → fewer membership clicks. This argues for keeping pre-baked content rich enough to demonstrate real insight (Meridian transcode + LLM tasks + image gen + RAG, all the same workloads members get), and never gating *measurement quality* — only inputs and bookkeeping.
- **Worth instrumenting.** The change request should include a basic conversion metric: count "Members only · Join GoS" CTA clicks per week. That's the lagging indicator of whether OWL is actually working as a funnel.

The line that holds against feature creep — *public sees results, members shape inputs* — is also the line that keeps the membership pitch credible. If everything's available publicly, "join GoS" has no answer to "why?".

### Agreed direction

**One deployment, one hostname, three capability tiers** gated at the route layer:

| Tier | How identified | Default landing |
|---|---|---|
| **Anonymous** | No auth cookie | Public landing page (= today's `/demo` Guided Tour, promoted) |
| **Member** | Signed in via magic-link email or GitHub OAuth | Same landing page; "Sign in" affordance flips to member view |
| **Lab** | Request from LAN IP (existing `_is_local()` check) | Full settings + calibration access |

**Key UX framing — a single landing page everyone sees:**
- Anonymous and members arrive at the same page.
- Locked features are *visible* with a "Members only · Join GoS" affordance — the capability matrix becomes the GoS sales pitch.
- Members don't *have* to sign in to demo OWL to a colleague — they get the public experience by default, sign in only when they want a member-only feature.
- Conference / booth demos: zero auth friction.

### Capability matrix (locked = sales pitch for joining GoS)

Measurement quality is identical across tiers — only inputs and bookkeeping differ.

| Capability | Anonymous | Member | Lab |
|---|---|---|---|
| Pre-baked workloads (Meridian, fixed prompts, sample image gens) | ✓ | ✓ | ✓ |
| Live wall-power, CO₂e, comparison strip | ✓ | ✓ | ✓ |
| Guided tour, methodology, Eco2mix mix breakdown | ✓ | ✓ | ✓ |
| Browse public recent runs (anonymised) | ✓ | ✓ | ✓ |
| Custom video upload | ✓ (≤100 MB, 1 concurrent job) | ✓ (no size cap, programmatic / scheduled allowed) | ✓ |
| Custom prompts / custom ffmpeg commands | — | ✓ | ✓ |
| All-codecs / batch / compare-modes | — | ✓ | ✓ |
| RAG corpus upload | — | ✓ | ✓ |
| CSV / JSON export of own runs | — | ✓ | ✓ |
| Per-user run history, named presets | — | ✓ | ✓ |
| `/settings`, variance calibration | — | — | ✓ |

**Anonymous upload rationale:** 10 MB was floated and rejected — too small, jobs run too fast to lift power above the P110 measurement floor and produce a usable green-light reading. 100 MB sized to give a 1080p clip ~30 s+ of transcode wall-time, comparable to the bundled `meridian_120s` test asset (~123 MB).

The line that holds against feature creep: **public sees results, members shape inputs.**

### Architecture

- **One systemd unit, one nginx vhost, one cert.** Don't fork.
- **`audience.py` module** — single source of truth. `audience.tier(request)` returns one of `Anonymous | Member | Lab`. Every route declares the tier it needs (`@requires(Member)` or similar). The grep target `requires(` is the security audit.
- **Auth: magic-link email** (libraries like `mailauth`, `magic-link-auth`) preferred over GitHub OAuth — no "create account" step, single click from email. Member email allowlist is a small JSON file (~tens of GoS members, no DB needed).
- **Replace `WATTLAB_GATE_PASSWORD`** entirely. The shared-password gate is the wrong shape for this model.
- **Per-tier rate limiting and queue caps** (must, since same hostname):
  - **Anonymous:** 1 concurrent job per visitor (single slot in the queue at a time — no parallel anonymous runs from the same browser session). 100 MB upload cap. nginx-level backstop ~1 measurement/5min per IP.
  - **Member:** relaxed per-user pool — programmatic / scripted / scheduled-weekend runs explicitly allowed (this is part of the membership pitch).
  - **Lab:** uncapped. **Already implemented today** via `_is_local()` — a member SSH-tunneling from outside back to localhost is auto-detected as Lab tier. CR-001 just generalises the existing carve-out into a named tier.
  - Conference-day spike from anonymous can't drain the queue and starve members.
- **Public-side hardening:**
  - Upload route reachable for Anonymous, but capped at 100 MB and gated through `queue_control.enqueue_for(request, …)` so the 1-concurrent-job-per-visitor limit is enforced at the single chokepoint.
  - Length caps on any free-text input (RAG question, prompt).
  - Strict CSP, no `eval`, etc.
  - Aggressive nginx rate limits as a backstop to in-app caps.

---

## CR-001b · Demo lock (sub-feature of CR-001)

**Status:** ✅ resolved 2026-05-03 by CR-011 + CR-015. No code shipped under this CR's name. Marked resolved in commit `d5867c4` (S19 part 1).
**Triggered by:** owner running important demos and needing exclusive control of the queue.

### How CR-011 covers the intent

- `bin/stage-on` raises `/tmp/owl-maintenance`, which nginx honours with a static maintenance page (HTTP 503) for everyone hitting the public hostname.
- The owner accesses OWL via LAN (`http://192.168.1.62:8000`) or SSH tunnel (`localhost:8000`) — both bypass nginx, so the owner has full, exclusive use of the queue while the maintenance flag is up.
- This delivers the headline guarantee CR-001b was capturing ("only the owner can run jobs during a demo") without a new flag, new banner, or new auth concept.
- The "I forgot to unlock" failure mode is handled by CR-015 (auto-lower the maintenance flag on Lab-tier inactivity), captured 2026-05-03 as a CR-011 follow-up.

### What this loses vs. the original CR-001b design

- No "demo in progress, ends 13:42" friendly UI for blocked users — public sees the generic maintenance page instead. Acceptable: the maintenance page is already on-brand and the messaging is clear.
- No `🔒 demo` pill on the floating telemetry badge for the owner — owner already knows because they ran `stage-on`.
- No fixed expiry timer with `[extend]/[end now]` controls — replaced by the activity-driven CR-015 watchdog, which is a better fit (extends when the owner is using the system, lowers when they walk away).

If a future demo format genuinely needs the in-app banner / extend-button UX, re-open this CR. For now the cheaper path covers the use case.

### Original problem statement (preserved for context)

For high-stakes live demos (conference stage, sponsor pitch, press), the owner needs **exclusive write access** to the OWL queue — only they can run jobs. Anyone else hitting "Run" sees a clear "demo in progress" message. The risk we wanted to avoid: forgetting to turn the lock off after the demo. Q&A or hallway conversation can stretch an hour, and by the time the owner remembers, the system has been silently unusable for users in the meantime.

The original design (now superseded) was a `/tmp/owl-demo-lock` flag mirroring the existing pause-flag idiom, with auto-expiry and an in-app banner for blocked users. CR-011's maintenance-page swap covers the same use case more cheaply.

---

## CR-002 · Methodology page accuracy pass

**Status:** ✅ done 2026-05-02 (Session 17 follow-up). Original three issues shipped in S16 (`994e380`); extended scope (popover + Guided Tour drift) shipped in `6bb80c2` (S17 part 5).
**Triggered by:** training-prep walkthrough of the methodology page (transcript ~T+790s) + owner notes.

### Problem

Three inaccuracies on `/methodology` need fixing before the page is shown to a public audience:

1. **P110 power resolution stated as "1 W" — incomplete and misleading.** The Tapo P110 reports power at **1 W resolution via its public API** (which is what we currently poll), but **1 mW resolution via direct device read** (the underlying instrument is far better than the API exposes). The page should state both numbers and be explicit about which one this deployment uses.
2. **`baseline_polls` hard-coded as `10` in the prose, but `settings.json` defaults to `5`** — disconnect between docs and behaviour. Either render the setting at request time (preferred — single source of truth) or at minimum drop the hard number and refer the reader to `/settings`.
3. **"From energy to CO₂e" section names ElectricityMaps as the only live source** — Eco2mix was added later as the primary live source for France, with ElectricityMaps now a backup. Section needs updating to reflect the actual fallback ladder: **Eco2mix (RTE/Etalab) → ElectricityMaps → Ember 2024 static**. (The result-card formula footer was updated; the methodology page copy was missed.)

### Done

- **S16 (994e380):** `/methodology` page rewritten — P110 1W/1mW resolution stated correctly, Eco2mix → ElectricityMaps → Ember fallback ladder named, `baseline_polls` / `video_cooldown_s` / confidence-multiplier / poll-count placeholders injected at request time from `settings.json`.
- **S17 follow-up (6bb80c2):** extended scope — verified that the *spirit* of CR-002 (no copy contradicting running config) was leaking outside the methodology page. Fixed:
  - **Popover content (`_CONF_HELP_WIDGET`)** — was still using the **pre-S11 fixed-watt framework** ("ΔW > 5W and ≥ 10 polls"), directly contradicting the methodology page. Rewritten to qualitative, framework-correct copy + link to `/methodology` for the formal numbers. Avoids plumbing live settings into 5 frozen page templates.
  - **Guided Tour video step + confidence step** — same pattern as `/methodology`: placeholder tokens (`{BASELINE_POLLS}`, `{VIDEO_COOLDOWN_S}`, `{CONF_GREEN_X}`, `{CONF_GREEN_POLLS}`, `{CONF_YELLOW_X}`, `{CONF_YELLOW_POLLS}`) replaced at request time in `demo_page()`. Tour now agrees with `/methodology` on every threshold.
  - **Popover positioning bug** (root cause of "click does nothing" reports) — widget script set `pop.style.top = r.bottom + 6 + window.scrollY`, but the popover is `position:fixed` (viewport-relative). The `+window.scrollY` pushed it offscreen below the visible area whenever the user had scrolled to see the badge. Fixed: drop the scroll offset.
  - **Missing `class="conf-badge"` on fresh-run badges** — ~13 badge sites across `/video`, `/llm`, `/image`, plus a few shared helpers, rendered the flag in plain `<div>`/`<td>`/inline interpolation without the class. Click handler's `e.target.closest(".conf-badge")` returned null → handler silently skipped. Class added in batch via Python script with strict-count assertions.
  - **Prev-run badges wrapped in `<span class="conf-badge">`** — the "Previous runs" panels on `/video`, `/llm`, `/rag`, `/image` flattened the confidence flag into a one-line summary string with no wrapping element. Wrapped the flag emoji (and label where present) so prev-run badges fire the popover too. `/image`'s prev-rendering is server-side Python f-string and got the same treatment. Made CR-013 visible (rows themselves should drill into stored detail).
  - **Net effect:** popover now fires uniformly across `/video`, `/llm`, `/rag`, `/image`, `/demo` on both fresh-run and prev-run badges, with framework-correct copy that matches `/methodology` exactly.

---

## CR-006 · Move AI workloads (LLM, RAG, image-gen) to a "beta / skunkworks" area

**Status:** ✅ done 2026-05-03 (Session 18 part 2 — `4c0b496`). Landing nav re-framed, h1 chips on `/llm` `/rag` `/image`, Demo Tour entering-beta band on steps 2/3/4. `_BETA_CHIP` constant introduced as single source of truth so the framing copy stays consistent.
**Triggered by:** Dom (transcript ~T+2516s; owner agreed).

### Problem

OWL's home page presented Video / Image / LLM / RAG as equal first-class workloads. The video work is mature, repeatable, and on-mission for GoS (streaming impact). The AI workloads are exploratory, sometimes below the P110 measurement floor (TinyLlama short-task), and at risk of diluting GoS's streaming focus when shown to a streaming-industry audience.

### Direction taken

Restructured the navigation so:
- **Primary, prominent:** Video (transcoding) — the main GoS story.
- **Beta / Skunkworks (visually de-emphasised, separate section):** LLM, RAG, Image generation. Still fully accessible, but framed as "exploratory work, energy/quality/faithfulness tradeoffs we're investigating" rather than "here's our authoritative answer."

Affected:
- Home page nav structure (AI links moved into a labelled "Beta · exploratory" group with a short explainer).
- Each AI-workload nav button gets a small BETA tag.
- `/llm` `/rag` `/image`: BETA chip next to the h1.
- Guided Tour: new "Entering beta · exploratory" framing band at the bottom of step 1 (after the video result), warning visitors that the next three steps are exploratory and inviting them to stop here if they only wanted the streaming-impact story. Steps 2/3/4 (LLM, image, RAG) get BETA chips on their h1s via a `{BETA_CHIP}` placeholder substitution at render time.

No measurement code touched; pure framing/copy work.

---

## CR-010 · France historical reference in "how this is calculated" comparison strip

**Status:** ✅ done 2026-05-03 (Session 18 part 1 — `63d38fc`). Adds a pinned reference row inside the carbon comparison `<details>` on every result page: same home zone as the live headline, but its Ember 2024 annual mean alongside today's live value. Side fix carried in the same hunks: zone-aware live-source explainer (was hard-coded to France/Eco2mix; now dispatches on HOME_ZONE so the copy stays correct if the server ever moves zones).
**Triggered by:** owner notes during spine-refactor session — concern that LIVE French intensity (~11 g/kWh, dominated by nuclear) can read very differently from the long-run average, leading viewers to draw the wrong conclusion when they compare FR-LIVE against UK/DE/PL annual means.

### Problem

The "If this had run elsewhere · how this is calculated" dropdown showed:
- Home zone (France) at the **live** intensity (Eco2mix or ElectricityMaps, badged LIVE).
- Comparison cities (Warsaw / London / Berlin / …) at **annual mean** intensity (Ember 2024, badged EST).

This is internally consistent but visually misleading: France looks unusually clean simply because it's currently low-carbon, and viewers can't see how *typical* that is. A visitor doing a back-of-envelope comparison may conclude "France beats Germany by 10×" when in fact the live snapshot is at the cleanest end of France's own distribution.

### Direction taken

Added **France 2024 annual mean** as an extra row in the comparison strip dropdown, badged distinctly so viewers can do an apples-to-apples comparison both ways:
- France LIVE (today's grid right now) — badged **LIVE**, accent colour.
- France HISTORICAL (2024 annual mean) — badged **EST · REF**, muted, with a small note like *"Historical reference — France's 2024 annual mean. Compare against this for a like-for-like view of the other countries below."*
- Other zones at annual mean — badged **EST**, unchanged.

When the live intensity diverges ≥25% from the static mean, a one-line note flags whether today's grid is "cleaner than" or "dirtier than" the year's mean. Suppressed when the headline itself is EST (no value duplicating the same number). Sharpens CR-007's "live grid varies" thesis without code complexity — visitors see three numbers in the same widget: live now, annual mean for this zone, and the divergence between them.

Implementation lived in `_CARBON_JS` in `main.py` — the comparison-strip rendering block.

---

## CR-011 · Staging environment via maintenance-page swap

**Status:** ✅ done 2026-05-03 (Session 18 part 4 — `d622505`; system-side nginx config + `www-data` group applied + smoke-tested same day). Follow-up captured as **CR-015** (auto-lower the maintenance flag on inactivity).
**Triggered by:** spine-refactor session — every restart-and-test loop currently takes the public service down with no friendly intermediate state, and there's no path for the owner to test a feature branch live before merging.

### Problem

OWL is a single systemd unit on a single port, behind nginx + cert at `wattlab.greeningofstreaming.org`. Testing any change required either (a) testing locally without the production wiring (misses real-world behaviour), or (b) restarting prod and hoping no public visitor hits a connection error during the window. Neither was acceptable for the conference runway, when visitors may arrive at any time.

### Constraint that shaped the design

GoS1 has **one Tapo P110 plug measuring the whole machine** and **one GPU**. Two OWL processes running measurement workloads simultaneously corrupt each other's readings — they both see each other's energy as part of their own ΔW. So a "staging" environment that runs measurements alongside prod is not a real option without buying a second plug + isolating GPU access; a side-by-side instance would only be safe for UI / route / docs work.

### Direction taken — single-service swap with maintenance page

The owner's actual workflow is short manual test windows (5–15 min) on a feature branch, not parallel staging. So:

1. **One service, swap branches in place.** No second systemd unit, no second port, no env-var split, no worktree. `git checkout <feature-branch> && sudo systemctl restart wattlab`, manually test, `git checkout main && sudo systemctl restart wattlab`.
2. **Maintenance page at the nginx layer** during the swap window. Triggered by a flag file (`/tmp/owl-maintenance`); when the file exists, nginx returns a static `maintenance.html` instead of proxying to FastAPI. Works even while wattlab is stopped — that's the whole point.
3. **Staging access bypasses nginx.** Owner accesses `http://192.168.1.62:8000` (LAN) or `localhost:8000` via SSH tunnel — both routes don't traverse nginx, so the maintenance flag has no effect on them.

### Mechanism

- **`maintenance.html`** (static, lives at `/var/www/maintenance.html` or similar): re-uses `_BASE_STYLES` palette, owl mark, GoS bug, link to greeningofstreaming.org. Reusable for any planned downtime (cert renewal, reboots, demo prep).
- **nginx config** for `wattlab.greeningofstreaming.org`: `if (-f /tmp/owl-maintenance)` block returns the static page with HTTP 503. ~10 lines.
- **`bin/stage-on`** shell script: optionally drains the queue (checks `queue_control.depth()` via `/queue` JSON; waits up to N seconds), touches `/tmp/owl-maintenance`, restarts wattlab. Optionally takes a branch name and does the checkout.
- **`bin/stage-off`** shell script: opposite — checkout main, restart, remove flag.

### Why not the alternatives

- **Two systemd units on different ports:** ~half-day to build, requires env-driven config split (results dirs, DBs, ports), still has P110/GPU contention for measurement work. Pays off only if staging runs for hours-days at a time, which is not the workflow.
- **Docker-isolated staging:** same P110/GPU contention; ROCm-in-container is non-trivial; only earns its keep when GoS1 hosts other projects. Tracked separately under CR-031 (deployment portability).
- **Different machine entirely:** can't validate measurement code paths since hardware differs. Misses the point.

---

## CR-014 · RAG compare-3-modes missing carbon strip

**Status:** ✅ done 2026-05-02 (Session 17 follow-up — fixed inline alongside CR-002 closure in commit `6bb80c2`).
**Triggered by:** owner notes during CR-002 verification — `/rag` single-mode results show the "If this had run elsewhere · how this is calculated" comparison strip, but the compare-3-modes report was missing it entirely. Visitors using compare-3-modes (the more interesting view) saw no cross-grid comparison and no live French production-mix breakdown.

### Root cause

`/llm` CPU-vs-GPU calls `wlCarbonStrip(_stripWh, _stripLbl)` at the top of the comparison report (main.py:2177). `/rag` single-mode does the equivalent at line 2899. The compare-3-modes path (`renderCompareResult` around line 3024) was built later and never wired up the strip — it only renders per-mode KPI cards.

### Fix

Added the strip at the top of the compare-3-modes report:

```javascript
const _stripWhArr = MODES
    .map(m => (r.results||{})[m] && r.results[m].energy ? r.results[m].energy.delta_e_wh : null)
    .filter(v => v != null);
const _stripWh = _stripWhArr.length ? Math.min.apply(null, _stripWhArr) : null;
const _stripLbl = r.model_label + ' · 3-mode RAG comparison (best of)';
```

Uses `Math.min` across the three modes (most efficient mode) — same idiom as `/llm` CPU-vs-GPU which uses the lower of CPU/GPU energy. Inserted between the question line and the per-mode cards.

---

## CR-015 · Auto-lower maintenance flag on inactivity (CR-011 follow-up)

**Status:** ✅ shipped 2026-05-07 (Session 23 part 4). Activity-driven, not wall-clock. Three pieces: middleware in `main.py` that touches `/tmp/owl-maintenance` on every Lab-tier request, new `bin/owl-maintenance-watchdog` one-shot script, and `systemd/owl-maintenance-watchdog.{service,timer}` units that fire the script every minute. Settings field `max_idle_mins` (default 30) tunable from `/settings`. systemd install is owner-only — see `systemd/README.md`.
**Originally captured:** 2026-05-03 (Session 18) right after CR-011 shipped — owner observation that the maintenance flag persists indefinitely until `stage-off` is run, leaving public visitors on the maintenance page if the operator walks away.

### What shipped

- **Lab-tier middleware** (`main.py`) bumps `/tmp/owl-maintenance` mtime on every Lab request. Cap-table-only contract: gates on `SETTINGS_WRITE` rather than a raw tier compare. Wrapped in try/except so a touch failure can never crash the request.
- **`bin/owl-maintenance-watchdog`** — one-shot bash script. Exits immediately if the flag isn't raised; reads `max_idle_mins` from `settings.json` (default 30 if missing or `jq` unavailable); compares against the flag's mtime; `exec`s `bin/stage-off` (no `--main` — preserves the staged branch) when the threshold is exceeded.
- **systemd timer + service** (`systemd/owl-maintenance-watchdog.{service,timer}`) fire the script every minute starting 2 min after boot. Output captured in `journalctl -u owl-maintenance-watchdog.service`.
- **Settings UI** — `max_idle_mins` shown in the `/settings` "Staging" section (Lab tier).
- **Docs** — `bin/README.md` gains a `## owl-maintenance-watchdog` section; `systemd/README.md` documents the install; `STAGING.md` cross-refs the auto-lower behaviour.

### Why activity-driven, not wall-clock

A naive "auto-off after N hours from `stage-on`" timer doesn't serve the two real use cases: 5-minute conference demo (short — wall-clock that's safe for it fires mid-test in the second case) vs 1-hour testing session (intermittent activity, owner is around but not poking the system every minute). Activity-driven via mtime + middleware-touch covers both — the operator extends the window simply by *using* the system.

### Watch-outs

- **systemd install is owner-only.** Files are in the repo but `sudo cp + daemon-reload + enable --now` has to happen on GoS1 by hand (one-time).
- **Don't auto-`stage-off --main`.** The watchdog deliberately preserves the currently-checked-out branch; surprising the operator with a checkout they didn't ask for is worse than letting them stay on the staged branch.
- **Cron alternative works.** A `* * * * * /home/gos/wattlab/bin/owl-maintenance-watchdog` cron entry is functionally identical; systemd is preferred only for `journalctl` integration.

---

## CR-016 · Live + static CO₂e on the same lifecycle boundary

**Status:** ✅ done 2026-05-03 (Session 18 part 10 — `c8c2316`; methodology copy follow-up in `6d06a81`). Was never given its own CR section in `CHANGE_REQUESTS.md` — captured and closed within the same session as a credibility fix.
**Triggered by:** owner — investigating a spurious ~4× live-vs-static gap on nuclear-heavy hours that didn't match physical reality. Turned out to be a methodology artefact, not real grid variance.

### Problem

Live FR carbon intensity was driven by Eco2mix's pre-computed `taux_co2` field, which is **direct combustion only** (nuclear ~0, gas counts only the smokestack). The Ember 2024 static reference table is **lifecycle** (nuclear fuel cycle, plant construction, methane upstream leaks, etc.). Mixing the two on the same UI surface produced a ~4× gap during nuclear-heavy hours that read as real diurnal variance — but was almost entirely a boundary mismatch.

### Direction taken

Live FR intensity now derives from Eco2mix's **production mix** (MW per source) × IPCC AR6 lifecycle factors, the same lifecycle math the static path already used. Live and static now sit on the same boundary and are directly comparable.

The infrastructure was already mostly there: `compute_intensity_from_mix` existed as a fallback for missing `taux_co2`, and Eco2mix already returned the production mix in MW. The fix was one path-flip in `_fetch_eco2mix` plus dropping the `computed` flag (every value is now derived from mix; the distinction is gone). Eco2mix's own `taux_co2` is preserved as `g_per_kwh_direct` in the response for transparency in the JSON audit trail, just no longer driving the UI.

After the fix, the live-vs-static gap is in the 1.0–1.5× range and reflects real diurnal variation (nuclear-heavy weekend afternoons cleaner than coal-heavy winter evenings). Two regression tests added (`test_eco2mix_response_returns_lifecycle_not_taux_co2`, `test_eco2mix_returns_none_when_mix_unusable`) so the boundary contract can't silently regress later.

### Why this matters more than it looks

This was a credibility fix masquerading as a small bug. Publishing carbon numbers where the live and reference values use different boundaries means every cross-grid comparison on every result page is silently wrong. CR-016 puts both on the same boundary; everything downstream (CR-010's home-zone reference row, CR-018's historical comparison) only works because of this fix.

---

## CR-017 · 24/7 continuous-service projection on the carbon strip

**Status:** ✅ shipped 2026-05-05 (Session 22 part 2 — Bundle 2). Toggle-only V1 per the captured plan; workload-aware defaults (V2) deferred to a future session if real visitor demand emerges.
**Originally captured:** 2026-05-03 (Session 18) as a sibling to the EV-distance equivalence shipped same session. Owner request: make CO2e more meaningful by showing not just "this single job's footprint" but also "what happens if this workload runs continuously."

### Problem (preserved for context)

CO2e numbers for individual jobs are honestly tiny — a single image gen is mm-scale of EV driving. The magnitude only starts to matter for streaming when you multiply by time × volume. A "if this ran 24/7" line in the carbon strip makes the scale leap visible without arithmetic, particularly for naturally-continuous workloads (live-stream encoding, model serving, embedding pipeline, RAG retrieval).

### Direction shipped — V1 toggle

`wlCarbonStrip(wh, label, durationS, savedIntensityG)` gained two optional args. When `durationS > 0`, an opt-in toggle inside the strip multiplies the displayed energy + every grams figure by `windowSeconds / durationS`:

- **as-measured** (default) — ×1.
- **1 hour / 1 day / 1 month / 1 year** — projected continuous service.

Multiplier wires through:
- Headline mass + Wh subtitle (+ projection prefix when on)
- EV-distance equivalence
- Pinned home-zone reference row + divergence note
- Comparison-zone rows
- Historical-zone rows
- "Same X on other grids" caption + "Through history — same X" caption

State persists in the URL hash (`#continuous=1d`) via `history.replaceState` so a shared link reproduces the projection without scrolling the page on hash-change. Toggle hidden when no `durationS` is passed (compare-mode strips that compute Math.min over multiple sub-runs — picking one mode's duration is ambiguous, V1 just doesn't offer the projection there). Single-run video, LLM, RAG, image all pass `e.delta_t_s`.

Energy and mass formatters extended for sane projections — `fmtEnergy(wh)` auto-switches Wh / kWh / MWh / GWh; `fmtMass(g)` extends upward to kg / t. So "1 year continuous" of even a tiny image gen lands at "131 kWh · 2.6 kg" rather than "131400 Wh · 2628000 mg".

### Watch-outs (still relevant)

- **Don't lose the projected framing.** When toggle is on, the headline subtitle is prefixed with "Projected over <window> continuous · " so visitors can't read the projected number as the measured number.
- **The projection is hypothetical.** "If this ran continuously" makes physical sense for some workloads (model serving, RAG service, live-stream encoder) and is silly for others (one-off transcode, single image prompt). V1 doesn't classify; visitors opt in. V2 (workload-aware defaults + auto-suggest the toggle on continuous workloads) is captured as a deferred CR-017 V2 if usage warrants.

---

## CR-019 · Unify the in-progress widget across `/demo` and the main pages

**Status:** ✅ shipped 2026-05-07 (Session 23 part 5). Headline scope (widget unification) done. **Resume-job progress fix deferred** — captured as a follow-up CR; the widget-unification work was the 80% of the user-visible win, the resume-job hook is a separate lifecycle problem worth its own design pass.
**Originally captured:** 2026-05-03 (Session 19), scope extended 2026-05-04 to fold in resume-job. Triggered by owner running 3-mode RAG from `/demo` step 4 on mobile and noticing the in-progress UI was much less informative than `/rag`'s for the same workload (no stage list, no live watts, no extras slot).

### What shipped

- **`wlRenderProgress(opts)` and `wlRenderQueued(pos, opts)`** accept `opts.target` (default `'status'` for back-compat). `/demo`'s four poll loops pass `'video-status'` / `'llm-status'` / `'image-status'` / `'rag-status'` and reuse the same widget the main pages have used since CR-001.
- **Shared stage arrays** in `_PROGRESS_JS`: `WL_VIDEO_STAGES`, `WL_LLM_STAGES`, `WL_IMAGE_STAGES`, `WL_RAG_STAGES`. Stages can't drift between `/demo` and the main pages because they reference the same source.
- **`_PROGRESS_JS` injected into `_DEMO_HTML`.** Previously the demo template assembled `_FOOTER` only; now it appends `_PROGRESS_JS` so `wlRenderProgress` is in scope.
- **Live wall-power threading.** New `_job_status(job_id)` helper injects `_power_cache["watts"]` into every job-status response. All four endpoints (`/llm/job/{id}`, `/video/job/{id}`, `/image/job/{id}`, `/rag/job/{id}`) now return `data.watts`, which flows through to the 2.5 rem live readout on the widget — the proof-of-reality moment that `/demo` was previously missing.
- **/demo poll loops migrated**: `pollVideo`, `pollLLM`, `pollDemoRAG`, `pollDemoImage` all dropped their bespoke `<p class="progress-note">` markup. LLM keeps its stream-box partial output via `opts.extraHtml`; RAG shows the active sub-mode (e.g. "inference of rag_large") in the extras slot.

### Resume-job progress fix — deferred

Out of scope for this PR; captured as a follow-up CR. The agreed direction (per the original CR-019 doc): a `?job=<id>` query-param hook that re-attaches `wlRenderProgress` to an in-flight job on page load. Needs a small design pass on URL state and browser history — too much surface to fold into a "widget unification" PR without spilling.

### Why this matters

`/demo` is the conference narrative and the highest-traffic public surface. The big live wall-power readout *is* the proof-of-reality moment ("there's a real power meter, this isn't a slideshow"). Hiding it during the in-progress phase was exactly the wrong moment to drop it.

### Watch-outs (still relevant)

- **Stages drift.** If a workload module gains a new stage (e.g. RAG cooldown), update `WL_*_STAGES` in `_PROGRESS_JS` rather than redefining inline somewhere.
- **`data.watts` consumers must tolerate `null`.** The live cache initialises to `None` before the first poll cycle; `wlRenderProgress` already handles that branch (only renders the watts block when non-null).
- **Resume-job follow-up CR will need to fold in URL state.** When it lands, `?job=<id>` becomes the canonical pattern; current `pollX(jobId)` callers should become `pollX(jobId, {resume: true})` or similar so the widget knows whether it's re-attaching or starting fresh.

---

## CR-020 · Baseline-variance gate on confidence

**Status:** ✅ closed 2026-05-07 — **superseded by CR-028 Phase 2.** The per-run baseline-CV gate described here is absorbed into Tania's unified statistical model: §9 of `docs/wattlab_traffic_light_confidence.md` computes `SE_per_run` from the actual baseline + task samples on each run, replacing the static `variance_pct × w_base` denominator that CR-020 was designed to retrofit. Once CR-028 Phase 2 ships, the per-run noise check is in the math by default — no separate gate needed. Storage piece (persist raw `baseline_samples_w` / `task_samples_w` per result) folded into CR-028 Phase 2 scope.
**Originally captured:** 2026-05-03 (Session 20). Marked "likely superseded" on capture day; confirmed superseded after Tania's §9 doc landed 2026-05-07.

### Problem (preserved for context)

`confidence(delta_w, poll_count, w_base)` in all four modules compares `delta_w` against `(variance_pct/100) × w_base`. The denominator was *yesterday's* idle CV from calibration, not *this run's* baseline noise. If today's baseline polls themselves swung far more than calibrated variance suggests, every downstream confidence label was built on sand — and the existing 🟢/🟡/🔴 logic didn't notice. CR-020's plan was a single-purpose `variance_gate_x` setting that would force 🔴 when in-run baseline CV diverged materially from `variance_idle_pct`. CR-028 Phase 2's combined-CI approach achieves the same outcome with a single statistical claim instead of an ad-hoc gate, so the gate doesn't need to ship as a separate piece.

---

## CR-021 · Sign-in chip more prominent on large screens

**Status:** ✅ shipped 2026-05-07 (Session 23 part 4). Anonymous chip gets a CTA variant (`.auth-chip.cta`): filled accent background, 0.85 rem font, `⚿` glyph next to "Sign in", inverted text colour. Member/Lab keep the recessive status-pill look. Renders on every page including `/queue-status` and `/methodology` after the `_HEADER` factorisation that landed alongside.
**Originally captured:** 2026-05-03 (Session 20). Tagged "trivial."

### What shipped

Single CSS rule + one-line variant in `_auth_chip_html()`. New `.auth-chip.cta` block in `_AUTH_CHIP_STYLES`. Plus a tiny refactor — `_header_html(request)` returns chip + back link as one helper, used by `/queue-status` and `/methodology` so they render the same chrome as standard pages (also closes the "Factorise `_HEADER` constant" deferred item from CLAUDE.md).

### Why this matters

CR-001 made all member-tier features visible-but-locked on the public surface ("the locks ARE the membership pitch"). The Sign-in chip is the affordance that turns those locks into unlocked features. At 0.72 rem in the corner it under-converted; the CTA variant pulls the eye on wide displays without crowding the page.

---

## CR-022 · `scale_vaapi` surface-pool leak corrupts long GPU encodes

**Status:** ✅ fully shipped 2026-05-07 (Session 23 part 1 — `9e1d076`). Closed in two steps. **Step 1** (Session 21, `aae9af4`): `_maybe_cap_vaapi()` workaround injected `-t 30` before `-i` on any VAAPI cmd; new `gpu_encode_max_s` setting. **Step 2** (Session 23 part 1): upgraded to ffmpeg master build at `/usr/local/bin/ffmpeg-master`, which fixes the `scale_vaapi` leak at source. The `-t` cap was deleted (`_maybe_cap_vaapi` removed; `gpu_encode_max_s` removed; result dict no longer reports `gpu_capped_at_s`). New `ffmpeg_bin` setting routes every preset, custom command, and calibration template through the upgraded binary. First post-resolution n=24 calibration confirmed full encodes complete cleanly: idle 2.41% → 2.26%, gpu 4.77% → 0.95%.
**Originally captured:** 2026-05-04 (Session 21). Real bug, reproducible in standalone ffmpeg, root cause upstream.
**Triggered by:** owner — surfaced while building `bin/probe-thermal-recovery` (Session 21 thermal-recovery diagnostic). The probe's GPU encode failed deterministically on the first smoke test. Standalone ffmpeg reproduction confirmed the bug isn't probe-specific — it's in the production VAAPI pipeline.

### Problem

The VAAPI filter chain `-vf scale_vaapi=w=-2:h=1080:format=nv12` leaks surfaces over time and exhausts the pool around frame ~7000-43000 (variable, but always near end-of-stream on long inputs). Symptom on the standalone command:

```
[vf#0:0 @ 0x...] Error while filtering: Cannot allocate memory
Failed to inject frame into filter network: Cannot allocate memory
Conversion failed!
```

ffmpeg returncode=1, but only after most of the stream has already been processed.

**Affected commands** (all use the same filter chain):
- `settings.variance_gpu_cmd` — H.265 GPU calibration encode
- `PRESETS["h265_gpu"]` — production /video preset
- `PRESETS["av1_gpu"]` — production /video preset
- `PRESETS["gpu"]` (H.264 GPU) — production /video preset

Reproduces on both `meridian_4k.mp4` (12 min, fails ~frame 43076) and `meridian_120s.mp4` (2 min, fails ~frame 7178). Adding `-extra_hw_frames 64` was tried previously (S12 fix) and is no longer sufficient — the leak rate just outruns whatever pool size you set.

### Why it mattered more than it looked

1. The headline finding **"H.265 GPU 14.5s / 0.29 Wh"** in CLAUDE.md was measured on the 120s asset where the encode runs *most* of the way before crashing — but `transcode()` returns `success=False` on the failed encodes and downstream consumers don't all check that field (see CR-023). So the reported figure may include partial-encode data depending on which path produced it.
2. CR-023 was the much bigger consequence: variance calibration silently treats failed encodes as successful, polluting `variance_gpu_pct` with partial-encode ΔW.

### Workarounds tried

- `-t 30` cap on the encode → completes cleanly, ~5s wall time. **Now used by `transcode()` automatically via `_maybe_cap_vaapi()`.**
- `-extra_hw_frames 64` / `128` → delays the crash but doesn't prevent it on long streams.
- Pipeline restructure (no `scale_vaapi`, swap to CPU scaling then re-upload) — not tested; would change the energy profile and defeat the "full VAAPI pipeline" framing. Captured as Step 2.

### Direction shipped

**Two-step fix; Step 1 done.**

1. **(Done)** Short-term workaround in PRESETS + variance_gpu_cmd. `gpu_encode_max_s` setting (default 30, bumped to 90 inline post-S21 once it became the variance-calibration sample window). Result JSON tagged with `gpu_capped_at_s` so we can audit which results were affected.
2. **(Deferred)** Long-term: investigate filter alternatives. Test whether a different filter graph (e.g. `hwupload`/`hwdownload` round-trip, or `scale=` on CPU before VAAPI encode) avoids the leak while keeping the energy profile honest. Document findings in METHODOLOGY.md regardless of outcome.

### Watch-outs (still relevant)

- **Capping changes the energy profile** — a 30s GPU encode draws less total energy than a 12-min encode. The cap means our "GPU energy per encode" headline figures will be smaller than they would be uncapped. The mWh-per-frame and ΔW figures stay valid; the per-encode totals scale with duration.
- **The canonical ABR all-codecs benchmark** in CLAUDE.md was run on the (failing) full-length GPU command before the cap shipped. Re-running it under the cap will produce different absolute numbers. Re-run + headline update is open work captured under CR-029.

---

## CR-023 · Variance calibration silently uses partial-encode data on ffmpeg failure

**Status:** ✅ calibration-loop fix shipped 2026-05-04 (Session 21 — `aae9af4`). `run_variance_calibration` now captures `transcode_result`, only appends ΔW from successful encodes, tracks `cpu_failed`/`gpu_failed` counters with stderr tails, and aborts the settings update if ≥50% of either side fails. Result JSON gains `cpu_failed`, `gpu_failed`, `failure_stderr`, `abort_reason` fields. **Residual scope:** Step 2 (tag failures on single-run paths in `run_single`/`run_both`/`run_all`) deferred — not urgent now that the calibration spine is gated. Promote to a fresh CR if/when a confused operator demands UI badges on partial-encode results.
**Originally captured:** 2026-05-04 (Session 21). Confirmed bug — overnight calibration produced bogus `variance_gpu_pct` because of this.
**Triggered by:** owner — investigating why the latest variance calibration jumped `variance_idle_pct` 6.66 → 11.03 and `variance_gpu_pct` 0.49 → 3.00. Root cause for the GPU number turned out to be CR-022 (scale_vaapi leak) crashing every GPU encode near end-of-stream — but the calibration didn't *notice* the crashes, and persisted ΔW figures computed over the partial encode duration.

### Problem

`run_variance_calibration` (`wattlab_service/video.py:537`) ran each encode like this:

```python
await asyncio.get_event_loop().run_in_executor(None, transcode, cmd_gpu)
stop_gpu.set()
readings_gpu = await poll_gpu
out_gpu.unlink(missing_ok=True)
if readings_gpu:
    w_task2 = sum(r["watts"] for r in readings_gpu) / len(readings_gpu)
    gpu_delta_w.append(round(w_task2 - w_base_gpu, 3))
```

`transcode()` *did* return `{"success": False, ...}` when ffmpeg exited non-zero, but the calibration loop never checked it. As long as `readings_gpu` had any polls in it (which it always will — power polling runs in parallel with the encode), the run was treated as a successful data point. The ΔW got averaged over however long the encode ran before crashing — which for the historical `variance_gpu_cmd` + `meridian_4k.mp4` was ~84s of partial encode every time (frame=43076 of ~43200).

**Confirmed concrete impact:** the polluted calibration's `variance_gpu_pct = 3.00` was computed from 30 partial-encode runs that all crashed near end-of-stream. The figure was not measurement variance — it was a mixture of that plus encoder-failure-state variance. Same applies to any prior calibration where `variance_gpu_cmd` ran on a long input.

The same pattern existed in the production single-encode path (`run_single`, `video.py:235`) and `run_both_measurement` / `run_all_measurement` — none of them gated their result on `transcode_result["success"]`. CR-022 was what made this dangerous in practice; CR-023 was the failure of the surrounding code to *notice*.

### Direction shipped

**Two changes — small, surgical.**

1. **(Done)** Calibration loop gates on `success`. In `run_variance_calibration`, capture the `transcode_result` from the executor call and skip the ΔW append if `success=False`. Increment a `failed_runs` counter that lands on the result JSON. If `failed_runs >= n_runs / 2`, refuse to update settings — abort with an error explaining which command failed and pointing at the result JSON for forensics.
2. **(Deferred)** Single-run path tags failures. `run_single`, `run_both_measurement`, `run_all_measurement` all need to record `encode_success: bool` and `encode_stderr_tail: str` on the result JSON, and the result detail UI needs to badge failed-encode runs distinctly so they can't be confused with clean measurements. Don't drop the result entirely — the partial readings are still informative for some questions (e.g. CR-022's leak rate) — just label them.

### Why this mattered

Two compounding effects:

- The variance framework is built on the assumption that `variance_pct` (specifically `variance_idle_pct`) reflects measurement-noise reality. CR-023 meant the GPU contribution to that figure was *partially encoder-failure noise*, not measurement noise. Every confidence label on every GPU result inherited that distortion via `noise_w = variance_pct/100 × w_base`.
- Combined with CR-022 (leak in scale_vaapi) it meant **we hadn't had a clean GPU calibration since the leak emerged**, and didn't know.

### Watch-outs (sequencing notes preserved for posterity)

- **Don't ship CR-023 alone** — if we'd started refusing to persist calibrations with failed GPU encodes *before* fixing CR-022, no calibration could ever complete. They shipped together in S21.
- **Audit historical results.** Worth a one-off scan of `results/video/*.json` for any GPU result where the encode duration is suspiciously close to the input duration but the file size doesn't add up. That's CR-022 + CR-023 in the wild. Not in scope for the fix itself; flag in a separate audit task if/when a published headline is questioned.
- **Don't auto-delete partial results.** Annotate them, don't remove them — they may have post-hoc diagnostic value (as CR-023 itself just demonstrated).

---

## CR-026 · Anonymous-tier integrity pass

**Status:** ✅ shipped 2026-05-07 (Session 23 part 2 — `caa025b`). Five coordinated changes from the team meeting 2026-05-04 leak. Phase E (curated content expansion — add more pre-loaded videos) deferred to a follow-up CR; the existing `meridian_4k` + `meridian_120s` already cover the demo, so it's variety not coverage.
**Originally captured:** 2026-05-04 (post-meeting). Tania surfaced the leak (logged-out, she could see other visitors' jobs and parameters on the public site).

### Problem (preserved for context)

CR-001 introduced the three-tier model and gated the *workload* spine through `capabilities.requires(...)` / `gate(...)`. The 2026-05-04 meeting found gaps in surfaces that aren't workload routes: result-history endpoints, JSON downloads, the upload form, and at least some HTML pages were rendering content for tiers that shouldn't see it. The pattern was: when a route was "read a result" or "list jobs", it didn't get the cap-table treatment that workload routes did.

### What shipped

**Phase A — Persistence + visitor scope:** `save_result()` records `visitor_key` on every result JSON; reads `queue_control.current_visitor_key` as ambient fallback so workload modules pick it up without per-call-site changes. `list_results()` / `load_result()` accept a `visitor_key` filter (None = unfiltered, for Lab). Pre-CR-026 records have no key and are invisible to non-Lab callers — own-jobs scope inherited automatically. `/results/{type}/list` and `/results/{type}/{id}/download.{json,csv}` resolve `visitor_key` from the request. The `/image` page's server-side `list_results()` does the same.

**Phase B — Disable Anonymous upload:** `CUSTOM_UPLOAD: Tier.Anonymous → Tier.Member` in `capabilities.py`. The `/video` upload form gets a "Members only" lock badge + disabled attr via the existing `_lock_class` / `_disabled_attr` predicates.

**Phase C — Anti-pattern cleanup (cap-table-only contract):** New `WORKING_NAV` cap (Member+) replaces the raw tier compare on the home redirect (Anonymous → `/demo`, Member/Lab → work nav). `/video/upload` size cap simplified to `s["upload_size_member_mb"]` since the route now requires Member+ (Anonymous can't reach it).

**Phase D — Defence in depth:** New test walks every registered FastAPI route and asserts each has `Depends(requires(...))` or appears in `_ROUTE_WAIVERS` (auto-injected `/docs`, `/redoc`, `/openapi.json`, plus `/auth/sign-out`). Catches "shipped a new endpoint without a gate" — the class of mistake that landed CR-026 in the first place. 10 visitor-scope persistence tests + 3 cap-table regressions. Renames `_visitor_key` → `visitor_key` in `queue_control` (now public, since `main.py` needs it for request scoping; test stubs updated).

### Watch-outs (still relevant)

- **Pre-CR-026 historical records are invisible to non-Lab callers.** Intended — they have no `visitor_key` field, so `_visitor_match` rejects them for any non-Lab visitor. Lab still sees everything. If a visitor reports "I can't see my old runs," they pre-date the cap.
- **Member onboarding has no visible-edit-mode confirmation today.** Tania noticed at the meeting — she'd SSH'd in but didn't see edit mode in the browser without an explicit walkthrough. CR-027 territory.

### Not in scope (deferred to follow-ups)

- **Phase E (curated content expansion).** Add a head-and-shoulders 1080p clip + a high-motion sports clip to `sources.PRELOADED` for Anonymous demo variety. Existing two assets already cover the demo functionally; the new clips are variety, not coverage. Captured for a follow-up CR.
- **FastAPI `/docs` / `/redoc` / `/openapi.json` policy.** Currently waived (internal-only on GoS1 via nginx). If/when the public surface at greeningofstreaming.org should hide these, set `FastAPI(docs_url=None, redoc_url=None, openapi_url=None)` in production.

---

## CR-030 · Carbon UI calibration pass

**Status:** ✅ shipped 2026-05-05 (Session 22 part 2 — Bundle 2). All four sub-changes landed; #4 was added during Bundle 2 visual verification when the owner spotted a related divergence.
**Originally captured:** 2026-05-04 (post-meeting). Bundles items 24 + 26 + 27 — three small UI/copy items on the carbon strip widget. Sub-#4 added 2026-05-05 to address a saved-vs-live divergence surfaced by visual review of #1.

### Problem

The carbon strip lived at the bottom of every result with explicit "HIGH-LEVEL CO₂e ESTIMATE" framing (S18 work), but the visual weight + the EV-equivalence wording still pulled focus from the energy figures. The team's framing is: *OWL measures energy; carbon is a derived view. The hierarchy should reflect that.* µg vs mg was a separate but adjacent issue — `fmtMass` auto-switches but the unit symbols can blur in spoken / printed contexts. After the typography shrink visual review surfaced a fourth issue: the strip headline (recomputed from live `/carbon` at page load) can read 1–10% different from the per-column inline rows (frozen in the result JSON at save time). Both correct for their respective timestamps; reading them on the same page without explanation is confusing.

### Direction shipped — four changes; one pass through `_CARBON_JS`

1. **Typography shrunk + colour weight reduced.** Headline mass: `1rem → 0.85rem`, `var(--accent) → var(--text-3)`. The "HIGH-LEVEL CO₂e ESTIMATE" caption stays as-is for framing; the headline now reads as a footnote to the energy block rather than a peer. "in <zone>" subtitle moved from text-3/0.78rem to text-4/0.72rem to maintain the visual hierarchy.

2. **EV-equivalence floor.** `fmtEvDistance` now suppresses the row below `EV_FLOOR_GRAMS = 0.0005 g` (≈ 10 mm of EV driving). Below threshold the comparator reads as too cute and undermines credibility — visitors who care about µg-scale carbon read the µg figure directly.

3. **µg/mg disambiguation.** New `massTitle(g)` helper returns a tooltip string like *"CO₂e mass · 1 mg = 1000 µg = 1e-3 g · this value: 1.234e-3 g"*. Wired into `wlCarbonRow` and every mass cell in the strip — reference row, historical rows, comparison rows. µ glyph (U+00B5) audited for consistency.

4. **Drift note for saved-vs-live home intensity.** `wlCarbonStrip` signature gained an optional 4th arg `savedIntensityG`. When the home-zone live intensity at page-load time differs ≥1% from the result's saved intensity, the strip renders a small italic note explaining the divergence: *"Grid moved X.X% up/down since this run was saved · saved at A g/kWh, current B g/kWh · rows above show the saved snapshot, headline shows live now"*. Tooltip on the note re-explains: per-column rows are an audit trail, strip headline is "right now". Wired into 4 single-run sites (video, LLM, RAG, image) and 5 compare-mode sites (video CPU/GPU + all_codecs, LLM CPU/GPU, image CPU/GPU + small/large, RAG 3-mode); LLM batch-mean and T3-long pass null since aggregates have no single saved intensity.

### Bonus shipped (related credibility fix)

Two video compare-mode strips (CPU/GPU and all_codecs) had labels that read like single-result labels ("H.264 GPU"). Updated to "best of CPU vs GPU" / "most efficient codec across all comparisons" — same convention the LLM, image, and RAG compare strips already used. Closes a "this looks like the only result" misreading the owner spotted during Bundle 2 visual review.

### Why this matters

Getting the visual hierarchy right means OWL reads as an energy-measurement tool that *also* shows carbon, rather than a carbon calculator. The drift note is the harder credibility lift: visitors comparing a strip headline to a column inline row would otherwise quietly conclude one is wrong. Both are correct; the note teaches the visitor that carbon estimates are time-stamped.

### Not shipped (captured for follow-up)

- **CSV export µg/mg disambiguation.** ✅ Resolved (differently) by **CR-036** — the CSV now carries a leading comment marking the `co2e_*` columns 🟡 indicative, which subsumes the unit-clarification intent.
- **Per-mode CO₂e expansion in the strip's details block.** ✅ Shipped as **CR-032** (see below) — promoted from this note during Bundle 2, landed alongside the CR-034 result-card lift.

---

## CR-032 · Per-mode CO₂e rows inside the carbon strip details

**Status:** ✅ shipped — `wlCarbonStrip`'s `subRuns` parameter + the per-mode breakdown inside the strip's `<details>` block are in `_CARBON_JS` and wired into every compare-mode result renderer. The implementation went beyond the original "one row per sub-mode" spec: N=2 comparisons (CPU vs GPU, small vs large) render two narrow side columns + shared two-mass rows; N≥3 (all_codecs) renders a per-mode ladder ("Per-mode breakdown — N sub-runs sorted by CO₂e") + a winner-anchored comparison block. Captured 2026-05-05 (Session 22 part 2); landed alongside the CR-034 result-card lift; closed in the 2026-05-12 close-out sweep.
**Triggered by:** owner observation during Bundle 2 visual verification — for compare-mode results the strip headline showed the most-efficient mode's mass with "best of N" framing, but the other modes' CO₂e footprints weren't visible inside the strip itself; visitors had to scroll up to the per-column inline rows.

### Problem

Compare-mode strips (video CPU/GPU, video all_codecs, LLM CPU/GPU, image CPU/GPU, image small/large, RAG 3-mode) all use `Math.min` to pick the most-efficient sub-run's energy and label that mode as the headline. The strip's `<details>` block showed comparison rows for *other zones / other dates / live mix / formula* — but never the *other sub-runs of this same comparison*. The data existed (each sub-run has its own `energy.co2e.grams`), it just wasn't surfaced in the strip.

### Direction shipped

`wlCarbonStrip` signature gained an optional `subRuns` array — `[{label, grams, deltaWh, durationS}, ...]`. When present (compare mode), the strip renders per-mode CO₂e inside `<details>`, computing each row from the sub-run's saved-snapshot `energy.co2e.grams` (so the rows agree with the per-column inline rows above). Single-run call sites pass `null` and behave unchanged. The 24/7 projection multiplier scales each sub-run by its own duration. Headline stays "best of N" — per-mode rows live inside the dropdown, not above it.

### Resolved / not in scope (from the original capture)

- Per-mode rows do honour the 24/7 projection toggle (the page-wide hash multiplier applies to all rows). No further work.
- No analogue for single-run strips — out of scope; `wlCarbonRow` already shows per-run CO₂e for single results.

---

## CR-034 · Unified results card (lift renderers + click-to-expand prev rows)

**Status:** ✅ shipped — both phases landed. **Phase A:** `_RESULT_JS` carries shared `window.wlRenderVideoCard / wlRenderLLMCard / wlRenderRAGCard / wlRenderImageCard` helpers (the compact-result-card lift); `/demo`'s `renderVideoResult` etc. are thin wrappers calling them. **Phase B:** `window.wlExpandPrevRow(jobType, jobId, savedAt, cardKind)` lazy-loads `/results/{type}/{job_id}/download.json` and renders through the matching helper; wired into the prev-run rows on `/video`, `/llm`, `/rag` (with `cardKind='rag'` since RAG persists under `llm/`), and `/image` — each with `chev-<jobId>` / `expand-<jobId>` element IDs, multiple rows expandable at once. **Absorbs CR-013** ("previous-result rows clickable for full stored detail", captured 2026-05-02) — CR-013 never got a standalone entry; it shipped as CR-034's Phase B. Captured 2026-05-08 (Session 23 part 6); closed in the 2026-05-12 close-out sweep.
**Triggered by:** two converging observations — (i) `/demo`'s bespoke compact result cards lacked the polished elements the main pages ship (carbon strip, EV-distance equivalence, 24/7 projection toggle, drift note, scope clarifier), so guided-tour visitors saw substantively different framing than direct-URL visitors; (ii) prev-run rows on the main pages showed only a one-line summary with no path to the rich detail short of downloading the JSON.

### Problem

Two parallel result-rendering paths existed (mirror of the situation CR-019 fixed for the in-progress phase): main pages assembled a rich card with `wlCarbonStrip` + scope clarifier + the full `<details>` block; `/demo` rendered a compact card with energy + confidence + scope-note only. Same drift-bug class — when CR-030's drift note shipped it landed on the main pages but not `/demo`. Independently, prev-row drilldown gave JSON/CSV download links rather than an inline expansion to the rich card visitors saw the first time.

### Direction shipped

**Phase A** — per-page render functions lifted into a sibling `_RESULT_JS` block as `wlRenderXxxCard({result, isPrev, savedAt})` helpers that *return* HTML strings (no DOM mutation; callers decide where to render). Cards include headline KPI row + prompt/question blockquote + confidence badge + carbon strip (full `<details>`: comparison rows, historical rows, drift note, EV equivalence, projection toggle) + scope clarifier. `/demo`'s renderers became thin wrappers. **Phase B** — prev-run rows became click-to-expand: collapsed by default, click fetches the full result and renders it through the Phase A helper, second click collapses, multiple rows open at once. Image previews still inline-render server-side thumbnails; the row stays as-is and the expand opens the full result.

### Deferred

- **"Expand all" toggle for Lab tier** — the original capture marked it "optionally"; not shipped. Capture if it surfaces as real friction in repetitive Lab work.
- **Resume-job lifecycle hook** — still the deferred CR-019 follow-up; the unified result card is its natural landing point, so pair the two if/when resume-job ships.

---

## CR-036 · Carbon "indicative only" — hard delineation across the UI

**Status:** ✅ shipped 2026-05-12 (Session 24). Captured 2026-05-11 from the board meeting. Commit-hash TBD — bundled into the next commit on `main`.
**Triggered by:** GoS board meeting 2026-05-11. Dom: *"all those carbon calculators… picking made-up numbers… we're doing really good primary empirical research and then sticking some random numbers on them and saying carbon. So I think it's just really important that they're all badged orange and they're all clearly not supposed to be interpreted as anything other than indicative."* Barbara: *"it could be a little bit more obvious… colour it… it should be very clear that this is a disclaimer."* Dom: *"make sure that's not someone reading it and quoting greening of streaming on someone else's carbon data — that would be appalling."*

### Problem

CR-030 shrank the carbon-block typography and added the drift note; the methodology "From energy to CO₂e" section was reframed "for reference only" (2026-05-11). But on the result-card carbon strips themselves, CO₂e was still visually peer to the energy headline — same palette, no consistent "third-party data, not a GoS measurement" treatment, no traffic-light data-quality badge. A screenshot of any carbon number could be lifted out of context and re-shared as GoS data. The Jan-2026 Language Lab AI position paper defines a 🟢 direct / 🟡 estimation / 🔴 speculation data-quality framework and rates IEA top-down energy figures 🟡 Amber — by that framework OWL's energy figures are 🟢 and its CO₂e figures are 🟡, and OWL didn't express that asymmetry visually.

### Direction shipped

- **Amber chrome on every `wlCarbonStrip`** — `rgba(255,170,0,0.30)` border + a 2 px warn-tone top edge, so the block reads as indicative third-party data before any number inside it is read. Energy results above keep the accent-green chrome; the contrast is the signal.
- **Persistent 🟡 INDICATIVE chip** at the top of every strip (single line, monospace, amber) with a tooltip naming both halves of the framework (🟢 direct = the energy figure; 🟡 indicative = this block, Wh × third-party grid intensity, IPCC AR6 lifecycle factors × live/recent mix, not a GoS primary measurement, see /methodology). Replaced the prior "High-level CO₂e estimate" caption.
- **Headline mass colour** swapped `--text-3` → `--warn`.
- **`wlCarbonRow`** (inline CO₂e row under each ΔE) — `(est.)` replaced by an inline `🟡 indicative` chip; mass cell `--warn`.
- **Strip `<details>` formula block** names the 🟢/🟡 framework explicitly and anchors to the position paper — single source of truth for the framing.
- **`estBadge()` tooltip** and the section-heading copy updated; "estimate" → "indicative" in carbon contexts (kept the existing LIVE/EST badges, which signal *source freshness* — a distinct axis).
- **CSV export** — leading comment row: `# OWL CSV export — energy columns (w_*, delta_*) are 🟢 direct measurements; co2e_* columns are 🟡 indicative (Wh × third-party grid intensity, not measured). See /methodology.` Survives `pandas.read_csv(comment='#')`; visible even to consumers who don't strip it. (Supersedes CR-030's "CSV µg/mg disambiguation" follow-up — this clearer framing replaces a unit-clarification note.)
- **Methodology page** "From energy to CO₂e" gained an amber call-out paragraph defining 🟢 Direct / 🟡 Indicative anchored to the position paper.

### Not shipped (deliberately)

- **Per-result-card 🟢 DIRECT chip next to the energy KPI** — the CR's "(or on hover)" escape hatch was taken: the 🟢 framing now lives once inside the strip header copy, communicating the asymmetry without N edits across every workload's energy display. No decision lost; a visible green chip on every result is a small follow-up if ever wanted.

---

## CR-038 · Efficiency-winner headline across all compare modes

**Status:** ✅ shipped 2026-05-12 (Session 24). Captured 2026-05-11 from the board meeting. Commit-hash TBD — bundled into the next commit on `main`.
**Triggered by:** GoS board meeting 2026-05-11. Marisol: *"if we could focus on sustainable AI… you have three models, one will be more sustainable than the other — highlight that on your screen as well, just make the focus on what is sustainable."* The data was in wattage but sat in a table, not a verdict.

### Problem

CR-030 gave the video compare-mode result a "best of CPU vs GPU" / "most efficient codec" label — but only on video, and only on the strip label. LLM Compare Models, Image Compare Models, and RAG compare-3-modes showed a results table with energy per mode and no headline verdict; visitors had to read row-by-row to find the winner.

### Direction shipped

- **`window.wlEfficiencyVerdict(subRuns, opts)`** in `_RESULT_JS` — sorts by `energy`, emits `⚡ Most efficient: <winner> · <value> <unit> · <ratio>× less than <other>` for N=2; `· best of N · spread <X>× across all sub-runs` for N≥3; `Tied within noise · A and B both ≈ <value> <unit>` when the margin is <5%. Returns empty string for fewer than 2 valid sub-runs. Optional `qualityNote` passes through verbatim — the helper does **not** invent quality scoring (that's CR-039). Single compact line, monospace, accent-green winner, soft-green background (a 🟢-direct framing, in deliberate contrast to the amber carbon strip below it).
- **Wired in:** the shared `_RESULT_JS` helpers (prev-row expansion + /demo) — `wlRenderLLMCard` both-mode, `wlRenderRAGCard` 3-mode, `wlRenderImageCard` both + compare_models; and the page-local fresh-run renderers — `/llm` `renderLLMBoth`, `/rag` `renderCompareResult`, `/image` `renderImageBoth` + `renderCompareModels`. So the verdict shows on a fresh main-page run, not just /demo and prev-rows. mWh/token for LLM/RAG, Wh/image for image (the units visitors see in the cells).

### Not shipped (deliberately)

- **Video `renderBoth` / `renderAllCodecs`** keep their own richer "⚡ Most efficient + 🏁 Fastest + finding-prose" highlights block — adding `wlEfficiencyVerdict` would duplicate. The CR's "refactor video to use the helper" is partial: the helper exists, video stays on its richer block.
- **LLM `renderLLMAllBoth`** (Run-All × Both — 6 sub-runs grouped by task) — a single verdict over all 6 doesn't map cleanly; deferred.

---

## CR-042 · Pixop placeholder — ML video enhancement demo tile

**Status:** ✅ shipped 2026-05-12 (Session 24). Captured 2026-05-11 from the board meeting; implemented same week ahead of the owner's Wednesday 2026-05-13 meeting with Pixop. Commit-hash TBD — bundled into the next commit on `main` alongside the board-meeting CR drafts.
**Triggered by:** owner — meeting with Pixop (startup using specialised ML models for video enhancement). Goal: show them concretely *"where ML-based video enhancement would slot in"* if Pixop joined GoS, opening a real conversation rather than a hypothetical one. Aligns with the position paper's "small specialised CNNs" framing and the board's "AI must stay tethered to streaming" steer (CR-037 captured the same week).

### Problem

OWL had no surface where a Pixop-class workload (specialised CNN super-resolution / denoise / interpolation) would live. The home page listed Video Transcode + the three "beta · exploratory" AI tabs; none would make Pixop's eyes light up. They needed to see a slot shaped like their product to imagine joining. A short, honest *placeholder* tile does that work without overcommitting OWL to a measurement we can't yet do.

Reversibility was a hard constraint: must revert in a single commit if Pixop doesn't sign.

### Direction shipped

A new home-page tile **"Video Enhancement (placeholder)"** immediately below the Video Transcode tile — peer-shape, but amber (`--warn`) so it visibly reads as placeholder. Sub-label *"Demo · illustrative · awaiting partner integration"*. Clicking opens `/video-enhance`.

#### `/video-enhance` page

- **Amber `placeholder-band` at the top** — *"⚠ This page is a placeholder."* + one sentence explaining the slot.
- **"Before" video viewer** — newly-generated `meridian_120s_lowq.mp4` (720p × 1.5 Mbps H.264, 22 MB) served via a small allowlisted `FileResponse` route.
- **Three enhancement chip-buttons** — Denoise (~5M params), Super-resolution (~25M, 720p→1080p), Frame interpolation (25→50 fps).
- **Fake progress** via the existing `wlRenderProgress` widget — 4 / 5 / 7 second simulated runs with a sin-shaped peak watts curve on a 53.5 W baseline.
- **Result card wrapped in amber chrome** with every KPI tagged `· illustrative`: duration / ΔW mean / ΔE. Illustrative energies per option (denoise 0.03 Wh, super-res 0.18 Wh, interp 0.45 Wh on a 120 s clip — inside the position paper's small-specialised-CNN envelope). Carbon strip rendered via `wlCarbonStrip` so the gCO₂e tracks live grid intensity but lives inside the amber result card.
- **"After" video viewer** — reveals on result, replays the full-quality `meridian_120s.mp4` with a caption that names the enhancement and says *"illustrative — full-quality master shown for comparison."*
- **Methodology note** at the bottom linking `/methodology`.

#### Three "placeholder" signals (per the lab look & feel hard constraint)

1. Home-tile sub-label *"Demo · illustrative · awaiting partner integration"*.
2. Amber `placeholder-band` at the top of the page.
3. `· illustrative` clause on every result-card KPI label + an explicit *"illustrative values, not measured"* sub-line on the result-card header.

#### Reversibility — held

Everything additive:

- One `FileResponse` import addition.
- One `_VIDEO_ENHANCE_HTML` constant + two route handlers (`/video-enhance` and `/video-enhance/asset/{name}` — both `PUBLIC_PAGE`-gated; the asset route has a dict-key allowlist of two filenames so path-traversal attempts 404 by definition).
- One `.nav-enhance` CSS block + one tile HTML stanza on the home page.
- One degraded video asset (`test_content/meridian_120s_lowq.mp4`, gitignored).

**No new module, no new route on the runtime measurement spine, no new capability, no settings change, no schema change, no persistence change.** Revert = one `git restore` on the four touched files; the asset stays in the gitignored directory.

#### Verification at ship time

213 tests passing throughout. Page renders 200 OK; asset endpoint returns 206 Partial Content for range requests (video seeking works) and 404 on misses / traversal attempts. Home page tile appears for Lab/Member tier in the correct order (Video Transcode → Video Enhancement → Beta · exploratory); Anonymous tier still redirects to `/demo` (no regression).

### Visibility caveat (recorded for the post-meeting decision)

The home tile lives at `/` which redirects Anonymous → `/demo`. So Pixop sees the tile only when the owner is signed in (Lab or Member) and drives the demo from the home page — the canonical Wednesday-meeting path. For anonymous post-meeting browsing, Pixop needs the direct URL `/video-enhance`. If broader discoverability is needed, a small link on `/demo` is a ~5-minute follow-up.

### Two decision points wait on the Pixop meeting outcome

- **If Pixop joins:** the placeholder is retired and a real `video_enhance.py`-style measurement module replaces it (tethered per CR-037; reproducibility kit per CR-040 from day one). New CR captured at that point.
- **If Pixop doesn't join:** revert. Don't leave an empty placeholder live "in case someone else fits."

### Cross-references

- **CR-006 (closed) + CR-037 (captured):** AI as "beta · exploratory" / streaming-tethered. CR-042's placeholder inherits both framings.
- **CR-036 (captured):** carbon "indicative only" hardening — when it lands, the amber `--warn` palette used here becomes the site-wide indicative vocabulary, and the placeholder fits the standard.
- **CR-040 (captured):** reproducibility kit — if/when CR-042 becomes a real measurement, the kit covers it from day one.
- **AI position paper (Jan 2026 Language Lab):** specialised CNNs (denoise, super-resolution) are the paper's headline efficient-AI category. The placeholder is shaped to that exactly.
