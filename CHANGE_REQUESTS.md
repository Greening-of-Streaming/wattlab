# OWL Change Requests

Design / change requests captured for later implementation. Each entry has a status, a problem statement, the agreed direction, and any open questions. Implementation lives in JOURNAL.md once it lands.

---

## CR-001 · Two-tier OWL: anonymous public + authenticated members

**Status:** captured 2026-05-01 — awaiting implementation slot.
**Triggered by:** demo today (2026-05-01) — discussion of opening OWL to the wider streaming community at the sustainable-streaming conference (mid-June 2026, OWL's first public showing).
**Refined 2026-05-01 (training-prep transcript):** anonymous tier explicitly *can* upload (capped at 100 MB, 1 concurrent job per visitor); LAN/SSH-tunnel auto-detection already implements the Lab tier today; quotas restated below.

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

- **Conversion design matters.** "Want to Join GoS" CTA copy, placement, and click-through destination (presumably `greeningofstreaming.org/join` or equivalent) is a deliberate design decision, not an afterthought. Decide before the conference launch.
- **Friction on the public side is strategic, not regrettable.** The point of locking custom-upload, calibration, etc. behind membership is not "to keep visitors out" — it's to give them a reason to join. Public capabilities should be **genuinely useful** (measurements are credible, results citable) so visitors form a positive impression *before* they hit a lock.
- **Public usefulness is the recruitment funnel's top-of-funnel.** A weak public version means fewer visitors → fewer membership clicks. This argues for keeping pre-baked content rich enough to demonstrate real insight (Meridian transcode + LLM tasks + image gen + RAG, all the same workloads members get), and never gating *measurement quality* — only inputs and bookkeeping.
- **Worth instrumenting.** The change request should include a basic conversion metric: count "Members only · Join GoS" CTA clicks per week. That's the lagging indicator of whether OWL is actually working as a funnel — and it tells GoS leadership whether to invest more in OWL's public surface.
- **Conference launch (mid-June 2026) is positioned as the funnel's first real test.** First public showing → first wave of streaming-industry visitors → first measurable membership clicks. Worth treating the conference as a launch event for the funnel, not just a demo.

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

### Implementation order (deliverable before mid-June 2026)

1. **`audience.py` + capability tags** (~1 day). Promote `_is_local()` to the richer tier helper. Tag every existing endpoint. No behaviour change yet — this is just the audit harness.
2. **Magic-link auth + member allowlist JSON** (~1 day with library, ~3 if rolling). Replace `WATTLAB_GATE_PASSWORD` cookie with per-user identity. Default state = Anonymous (no redirect to login).
3. **Public landing page + locked-feature UI** (~½–1 day). The capability matrix above, rendered as visible product copy. "Members only · Join GoS" affordances on locked rows. Promote `/demo` content to `/`.
4. **Per-tier rate limits + queue caps** (~½ day). Configured in `settings.json` (`rate_anonymous_per_5min`, `queue_anonymous_cap`, etc.).

### Open questions

- Magic-link email vs. GitHub OAuth — pick by GoS member technical fluency. Default lean: magic-link.
- "Anonymised public runs" feed — is that a feature day-1, or post-conference? Risk of cluttering with low-quality/test runs.
- Member allowlist mechanism: pure JSON file vs. self-serve "request access" flow? Manual approval is fine at this scale (~tens).
- **CTA copy + destination for "Join GoS"** — what does the button actually say, and where does it send the visitor? Coordinate with whoever runs greeningofstreaming.org membership flow.
- **Conversion instrumentation** — count CTA clicks at minimum; do we also want to capture which locked feature triggered the click (e.g. did they click on "custom upload" vs "calibration"), so GoS knows which pitch is landing?

---

## CR-001b · Demo lock (sub-feature of CR-001)

**Status:** captured 2026-05-01 — must ship with or before CR-001.
**Triggered by:** owner running important demos and needing exclusive control of the queue.

### Problem

For high-stakes live demos (conference stage, sponsor pitch, press), the owner needs **exclusive write access** to the OWL queue — only they can run jobs. Anyone else hitting "Run" sees a clear "demo in progress" message.

The risk we want to avoid: forgetting to turn the lock off after the demo. Q&A or hallway conversation can stretch an hour, and by the time the owner remembers, the system has been silently unusable for users in the meantime.

### Agreed direction

**Demo-lock flag with an auto-expire timeout**, modelled on the existing `/tmp/owl-paused` queue-pause flag (introduced session 14 for the local-model router) — same shape, different semantics:

- **Pause flag (`/tmp/owl-paused`):** existing, halts the entire queue. External tool sets/clears.
- **Demo lock (new):** restricts the queue to a single owner identity. Auto-expires.

### Mechanic

- **Flag file:** `/tmp/owl-demo-lock` (parallel to `/tmp/owl-paused`).
  - Contents: JSON `{"owner": "<member_id_or_email>", "started_at": <epoch_s>, "expires_at": <epoch_s>}`.
  - Presence of file = lock active.
  - Absence (or `expires_at` in the past) = lock inactive.
- **Auto-expire:** the lock expires `demo_lock_minutes` after `started_at` (default 60 min, configurable in `settings.json`). The `queue_worker` checks `time.time() < expires_at` before honouring the lock; once past, it ignores the file (and a janitor sweep deletes it).
- **Enforcement point:** in `enqueue()` (single-place). If lock active and `request.user != lock.owner`, return HTTP 423 (Locked) with a friendly "Demo in progress · ends ~13:42 (in 18 min)" message. Already-running jobs continue uninterrupted.
- **UI affordances:**
  - Owner sees a prominent "DEMO LOCK · ACTIVE · expires 13:42 [extend] [end now]" banner on every page (sibling of the existing pause-flag banner on `/queue-status`).
  - Other users see "Demo in progress · jobs queued for you will start at ~13:42" instead of the normal "Run" button — keeps page browsable, only blocks `enqueue`.
  - Floating telemetry badge (`_QUEUE_BADGE`) gains a `🔒 demo` pill (alongside `⏸ paused`).
- **Trigger UI:** owner-only button on `/queue-status` (or `/settings`) — "Start demo lock" → POST `/demo-lock/start`. Sets the flag with current time + `demo_lock_minutes`. "End demo lock now" — DELETE the flag.

### Settings (added to `settings.json`)

- `demo_lock_minutes` (default `60`) — auto-expire window in minutes.
- `demo_lock_owner` — optional fixed owner identity if not deriving from auth (e.g. while CR-001 isn't shipped yet, a hardcoded value works as a stopgap).

### Why this shape

- Same idiom as the existing pause flag (filesystem flag, queue_worker checks on each tick) — no new infrastructure, no new auth model.
- Auto-expire is the safety mechanism for the "I forgot to unlock" failure mode — owner explicitly named this risk, the system handles it without their attention.
- Configurable expiry from `settings.json` so different demo formats (5-min flash demo vs. 90-min workshop) work without code changes.

### Implementation order

Can ship **before** CR-001 — uses today's auth model (the gate password = the implicit owner). When CR-001 lands, the `lock.owner` field becomes a real member identity instead of a stopgap.

### Open questions

- "Extend" button — by `demo_lock_minutes` again, or by 15 min? Probably 15 min — extending in big chunks defeats the auto-expire safety.
- Notification on auto-expire? Probably no — it's intended as a silent safety net. If owner needed to know, they wouldn't have left it on.

---

## CR-002 · Methodology page accuracy pass

**Status:** ✅ done 2026-05-02 (Session 17 follow-up). Original three issues shipped in S16 (994e380); extended scope (popover + Guided Tour drift) shipped today.
**Triggered by:** training-prep walkthrough of the methodology page (transcript ~T+790s) + owner notes.

### Problem

Three inaccuracies on `/methodology` need fixing before the page is shown to a public audience:

1. **P110 power resolution stated as "1 W" — incomplete and misleading.** The Tapo P110 reports power at **1 W resolution via its public API** (which is what we currently poll), but **1 mW resolution via direct device read** (the underlying instrument is far better than the API exposes). The page should state both numbers and be explicit about which one this deployment uses.
2. **`baseline_polls` hard-coded as `10` in the prose, but `settings.json` defaults to `5`** — disconnect between docs and behaviour. Either render the setting at request time (preferred — single source of truth) or at minimum drop the hard number and refer the reader to `/settings`.
3. **"From energy to CO₂e" section names ElectricityMaps as the only live source** — Eco2mix was added later as the primary live source for France, with ElectricityMaps now a backup. Section needs updating to reflect the actual fallback ladder: **Eco2mix (RTE/Etalab) → ElectricityMaps → Ember 2024 static**. (The result-card formula footer was updated; the methodology page copy was missed.)

### Agreed direction

Single editing pass on the `_METHODOLOGY_HTML` block in `main.py`. No new features — accuracy patch only. Where possible, render values from settings/code at request time so future drift is impossible.

### Pre-conference: must.

### Done

- **S16 (994e380):** `/methodology` page rewritten — P110 1W/1mW resolution stated correctly, Eco2mix → ElectricityMaps → Ember fallback ladder named, `baseline_polls` / `video_cooldown_s` / confidence-multiplier / poll-count placeholders injected at request time from `settings.json`.
- **S17 follow-up (2026-05-02):** extended scope — verified that the *spirit* of CR-002 (no copy contradicting running config) was leaking outside the methodology page. Fixed:
  - **Popover content (`_CONF_HELP_WIDGET`)** — was still using the **pre-S11 fixed-watt framework** ("ΔW > 5W and ≥ 10 polls"), directly contradicting the methodology page. Rewritten to qualitative, framework-correct copy + link to `/methodology` for the formal numbers. Avoids plumbing live settings into 5 frozen page templates.
  - **Guided Tour video step + confidence step** — same pattern as `/methodology`: placeholder tokens (`{BASELINE_POLLS}`, `{VIDEO_COOLDOWN_S}`, `{CONF_GREEN_X}`, `{CONF_GREEN_POLLS}`, `{CONF_YELLOW_X}`, `{CONF_YELLOW_POLLS}`) replaced at request time in `demo_page()`. Tour now agrees with `/methodology` on every threshold.
  - **Popover positioning bug** (root cause of "click does nothing" reports) — widget script set `pop.style.top = r.bottom + 6 + window.scrollY`, but the popover is `position:fixed` (viewport-relative). The `+window.scrollY` pushed it offscreen below the visible area whenever the user had scrolled to see the badge. Fixed: drop the scroll offset.
  - **Missing `class="conf-badge"` on fresh-run badges** — ~13 badge sites across `/video`, `/llm`, `/image`, plus a few shared helpers, rendered the flag in plain `<div>`/`<td>`/inline interpolation without the class. Click handler's `e.target.closest(".conf-badge")` returned null → handler silently skipped. Class added in batch via Python script with strict-count assertions.
  - **Prev-run badges wrapped in `<span class="conf-badge">`** — the "Previous runs" panels on `/video`, `/llm`, `/rag`, `/image` flattened the confidence flag into a one-line summary string with no wrapping element. Wrapped the flag emoji (and label where present) so prev-run badges fire the popover too. `/image`'s prev-rendering is server-side Python f-string and got the same treatment. Made CR-013 visible (rows themselves should drill into stored detail).
  - **Net effect:** popover now fires uniformly across `/video`, `/llm`, `/rag`, `/image`, `/demo` on both fresh-run and prev-run badges, with framework-correct copy that matches `/methodology` exactly.

---

## CR-003 · Iso-energy bitrate sweep ("I want to spend X Wh, what are my options?")

**Status:** captured 2026-05-01 — likely post-conference.
**Triggered by:** Dom (transcript ~T+1126s and ~T+2398s).

### Problem

OWL currently fixes the bitrate per codec (4 Mbps H.264, 2 Mbps H.265, 1.5 Mbps AV1 — chosen to match real-world ABR ladders) and reports the energy that produces. The inverse question is more interesting for an industry audience: **"given a fixed energy budget, what bitrate / quality options do I have across codecs?"**

Inverts the typical framing — instead of "this codec at this bitrate uses N Wh", asks "if I have N Wh to spend on a one-minute encode, here are my codec/bitrate options". Dom flagged this as IBC white-paper material; owner called it press-worthy.

### Agreed direction

New video-test mode (`video_iso_energy` or similar). Iterates a bitrate range across H.264 / H.265 / AV1 — long-running, intended for overnight or weekend execution — finds the bitrates per codec that produce equivalent energy. Output: chart/table of "for X Wh budget, your options are H.264@Y kbps / H.265@Z kbps / AV1@W kbps."

Possibly pair with a quality metric (mean PSNR / SSIM / VMAF) so the result is "for X Wh, here's your bitrate AND quality across codecs" — Simon flagged in transcript that quality scoring should accompany this.

### Open questions

- Quality metric to use? VMAF is the streaming-industry standard but adds dependency.
- Bitrate sweep granularity? Logarithmic vs linear?
- White-paper scope: just CPU? Just GPU? Both? Cross-grid?

### Pre-conference: unrealistic (long test runs needed). Post-conference: strong candidate, especially as IBC submission.

---

## CR-004 · Visual graphing in OWL

**Status:** captured 2026-05-01 — pre-conference nice-to-have.
**Triggered by:** Dom (transcript ~T+1657s) + owner notes.

### Problem

OWL currently renders all results as metric tables. Trend, variance, and shape are visible only by reading numbers row-by-row. Visitors are visual thinkers; demos land harder with a chart than a table.

### Agreed direction

Add chart rendering to result pages. Three candidates in priority order:

1. **Per-run power trace** — line chart of P110 polls (1s cadence) across the run, showing baseline → ramp-up → workload → cooldown. Makes the ΔW computation visually obvious. Single canvas per result card.
2. **Comparison-mode side-by-side** — bar chart for both/all-codecs/compare-models results, energy + CO₂e + duration on the same axis or stacked. Replaces or supplements the existing summary table.
3. **Historical trend** — small chart on the home page or `/queue-status` showing last N runs' energy across run timestamp. Gives a feel for how stable the lab is over time.

Library choice is open: chart.js (small, easy), uPlot (faster, smaller, ugly defaults), pure SVG (no dep, more code). Probably chart.js.

### Pre-conference: nice-to-have. Would visibly improve demo impact.

---

## CR-005 · Software fan-speed control during tests

**Status:** captured 2026-05-01 — pre-conference nice-to-have.
**Triggered by:** Dom + owner (transcript ~T+1796s, ~T+1840s) + owner notes.

### Problem

The GoS1 server lives in the owner's sitting room with fans set conservatively low for noise reasons. The 2% baseline drift currently visible in calibration runs is partly thermal (the chassis runs warmer over a session). Manually pre-cooling with a desk fan would help but isn't scientific or repeatable.

### Agreed direction

Programmatic fan-speed control around tests:
1. **Before a test starts:** raise fan speed to an aggressive profile (e.g. AMD `pp_dpm_fclk` / `fancontrol` / `nbfc`-style sysfs writes — exact mechanism TBD on AMD/Linux).
2. **After the test ends:** restore the default quiet profile.
3. **Configurable in `settings.json`** — `focus_mode_fan_profile: "aggressive" | "default" | "off"`. Default `"off"` so users who don't want their server howling aren't surprised.
4. **Bonus:** capture the fan-profile-used in the result JSON for reproducibility.

### Open questions

- Exact mechanism on this hardware (Ryzen 9 7900 + RX 7800 XT + the chassis fans) — needs investigation. Likely a combination of GPU PWM (via `/sys/class/drm/card0/device/hwmon/`) and chassis fans (motherboard EC, possibly out of reach without IPMI/BMC).
- Should this be exposed as part of focus mode (sudoers-gated stop-timers script) or as a separate sub-feature? Probably bundled into focus mode for cohesion.

### Pre-conference: nice-to-have, improves measurement quality (lower baseline drift = tighter green-light thresholds).

---

## CR-006 · Move AI workloads (LLM, RAG, image-gen) to a "beta / skunkworks" area

**Status:** captured 2026-05-01 — pre-conference, important for visitor framing.
**Triggered by:** Dom (transcript ~T+2516s; owner agreed).

### Problem

OWL's home page currently presents Video / Image / LLM / RAG as equal first-class workloads. The video work is mature, repeatable, and on-mission for GoS (streaming impact). The AI workloads are exploratory, sometimes below the P110 measurement floor (TinyLlama short-task), and at risk of diluting GoS's streaming focus when shown to a streaming-industry audience.

### Agreed direction

Restructure the navigation so:
- **Primary, prominent:** Video (transcoding) — the main GoS story.
- **Beta / Skunkworks (visually de-emphasised, separate section):** LLM, RAG, Image generation. Still fully accessible, but framed as "exploratory work, energy/quality/faithfulness tradeoffs we're investigating" rather than "here's our authoritative answer."

Affects:
- Home page nav structure (move AI links into a labelled "Beta" or "Exploratory" group).
- Guided Tour ordering — video stays as the headline; AI workloads may move later or to a separate skunkworks tour.
- Possibly methodology page sectioning (clearer "production vs. exploratory" framing).

### Pre-conference: important — shapes what conference visitors see first.

---

## CR-007 · Carbon variance study over time-of-day / season / location

**Status:** captured 2026-05-01 — possible pre-conference talking point if scoped tight.
**Triggered by:** Simon + Dom (transcript ~T+2029s onwards).

### Problem

OWL now reports gCO₂e against live grid intensity, but **the variance of that intensity itself** isn't characterised. Dom raised the right framing: if the carbon intensity of the grid varies by 1000% across the day, optimising your code by 1% is noise. If the grid varies by 1% and your code variation drives 50%, your code matters more. Without knowing which regime you're in, optimisation effort is mis-targeted.

### Agreed direction

Background or one-shot job:
1. Take a **standard fixed-energy reference workload** (e.g. exactly 1 Wh of compute — could be a calibrated transcode or a synthetic CPU hold).
2. Pull historical Eco2mix data for the last N months.
3. Compute the resulting gCO₂e variance for that 1 Wh workload as a function of:
   - Hour of day
   - Day of week
   - Season
   - Comparison location (UK / Germany / Poland — using their available historical data)
4. Render: a chart (CR-004 territory) plus a punchy summary line ("your 1 Wh workload, run in France, swung from X g to Y g over the last 6 months — Z× spread").

Possible deliverable: a methodology-page sub-section, a separate `/grid-variance` page, or a one-off white paper.

### Output value

Strong conference talking point — speaks directly to Simon's "schedule your work to carbon-efficient times" thesis. Could become guidance for operators / regulators on workload scheduling. *"Move your workload to this time slot for X% lower carbon."*

### Pre-conference: candidate if scoped tight. Worth a half-day spike to assess.

---

## CR-008 · REM ↔ OWL integration

**Status:** captured 2026-05-01 — branding step pre-conference, full integration is post.
**Triggered by:** Dom + owner across the transcript (~T+486s, ~T+2160s, ~T+3151s, ~T+1014s).

### Problem

GoS now has two measurement tools that were built independently:
- **OWL** — single-server, fine-grained, encoder-side energy + CO₂e.
- **REM** — multi-machine, end-to-end streaming workflow, less granular.

They're **complementary, not competing**, but currently they look like separate projects. For a GoS audience, the right framing is "REM = end-to-end at scale; OWL = deep dive at the encoder; together they cover the streaming pipeline."

### Agreed direction (multi-step)

1. **(Pre-conference)** Pull REM source code into the Claude project context so cross-understanding is possible. Owner action item from transcript.
2. **(Pre-conference)** Update REM with **OWL branding and visual style** — same owl mark, same `#00ff99` accent, same dark theme — so they read as one coherent GoS system. Dom's request.
3. **(Post-conference)** Genuine data interoperability — OWL exporting in a format REM can ingest, or vice versa. Mash-up view where 100s of homes report from REM and 1-2 contribute high-resolution OWL-style local measurements; visualised together.
4. **(Long-term, exploratory)** OWL acting as the encoder in a REM-orchestrated end-to-end test (encoder → intermediary server [Linode / TNO / Bristol] → client). Auto-hackathon workflow (see CR-009).

### Pre-conference: branding pass is feasible; data integration is post.

---

## CR-009 · Cross-platform web client test bay

**Status:** captured 2026-05-01 — post-conference.
**Triggered by:** Dom (transcript ~T+1431s, ~T+2940s); Simon flagged the long-standing problem this solves (~T+1394s).

### Problem

Real-user-measurement (RUM) at the client side is the missing piece in GoS's measurement coverage. Hackathons have done it manually with TVs. Simon's prior attempts at automation hit a wall: when the encoder switches codecs/bitrates mid-stream, **media players have to be restarted**, which can't easily be done on a TV remotely. So every hackathon needs a human pressing play between tests.

### Agreed direction

Web-based test client that uses page-reload as the "restart media player" mechanism:
- **Server side:** runs a 9-minute test sequence inside a 10-minute slot.
- **Client side:** a thin web app that auto-refreshes the page every 10 minutes (using AJAX / `setTimeout` / page reload). Each refresh loads a fresh `<video>` element with the next stream's URL. Synchronised by clock, not by event.
- **Cross-platform:** runs in any browser — iOS, Android, Roku, Apple TV, Samsung. No native app needed.
- **Anonymous contribution flow:** "Test your device now" button on OWL's public landing — visitor leaves their browser open for an hour or two, contributes data, sees their result.
- **Booking model (Dom):** since you can only have one active client tester at a time (to keep variance bounded), a slot-booking page lets contributors pick a 2-3 hour window over the weekend.

### Action items from transcript

- Dom to share his prior auto-refresh / autoplay code with Ben.
- Simon to dig out his earlier server-side automation work (he had Cron-based scheduling on the server but never the client).

### Effort estimate

Dom guessed five days of Claude Code work. Probably correct order of magnitude. Cross-platform browser quirks (autoplay policies on iOS especially) will eat real time.

### Pre-conference: unrealistic.
### Post-conference: high leverage — turns OWL into a contribution-driven RUM platform, not just a single-server lab.

---

## CR-010 · France historical reference in "how this is calculated" comparison strip

**Status:** captured 2026-05-01.
**Triggered by:** owner notes during spine-refactor session — concern that LIVE French intensity (~11 g/kWh, dominated by nuclear) can read very differently from the long-run average, leading viewers to draw the wrong conclusion when they compare FR-LIVE against UK/DE/PL annual means.

### Problem

The "If this had run elsewhere · how this is calculated" dropdown today shows:
- Home zone (France) at the **live** intensity (Eco2mix or ElectricityMaps, badged LIVE).
- Comparison cities (Warsaw / London / Berlin / …) at **annual mean** intensity (Ember 2024, badged EST).

This is internally consistent but visually misleading: France looks unusually clean simply because it's currently low-carbon, and viewers can't see how *typical* that is. A visitor doing a back-of-envelope comparison may conclude "France beats Germany by 10×" when in fact the live snapshot is at the cleanest end of France's own distribution.

### Agreed direction

Add **France 2024 annual mean** as an extra row in the comparison strip dropdown, badged distinctly so viewers can do an apples-to-apples comparison both ways:
- France LIVE (today's grid right now) — badged **LIVE**, accent colour.
- France HISTORICAL (2024 annual mean) — badged **EST · REF**, muted, with a small note like *"Historical reference — France's 2024 annual mean. Compare against this for a like-for-like view of the other countries below."*
- Other zones at annual mean — badged **EST**, unchanged.

Implementation note: this is the same Ember 2024 number the existing comparison strip already uses — `carbon.STATIC_INTENSITY["FR"]["g_per_kwh"]`. Today the home zone goes straight to the live path; CR-010 just exposes the static value alongside, with a tag clarifying it's a reference, not the live reading.

### Where it lives

`_CARBON_JS` in `main.py` — the comparison-strip rendering block. Probably one extra row in the table builder; one line of CSS for the muted REF badge.

### Pre-conference: yes — small change, high pedagogical value, sharpens the "live grid varies" story (which is already the core CR-007 thesis).

---

## CR-011 · Staging environment via maintenance-page swap

**Status:** ✅ done 2026-05-03 (Session 18 part 4 — `d622505`; system-side nginx config + `www-data` group applied + smoke-tested same day). Follow-up captured as **CR-015** (auto-lower the maintenance flag on inactivity).
**Triggered by:** spine-refactor session — every restart-and-test loop currently takes the public service down with no friendly intermediate state, and there's no path for the owner to test a feature branch live before merging.

### Problem

OWL is a single systemd unit on a single port, behind nginx + cert at `wattlab.greeningofstreaming.org`. Today, testing any change requires either (a) testing locally without the production wiring (misses real-world behaviour), or (b) restarting prod and hoping no public visitor hits a connection error during the window. Neither is acceptable for the conference runway, when visitors may arrive at any time.

### Constraint that shapes the design

GoS1 has **one Tapo P110 plug measuring the whole machine** and **one GPU**. Two OWL processes running measurement workloads simultaneously corrupt each other's readings — they both see each other's energy as part of their own ΔW. So a "staging" environment that runs measurements alongside prod is not a real option without buying a second plug + isolating GPU access; a side-by-side instance would only be safe for UI / route / docs work.

### Agreed direction — single-service swap with maintenance page

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

- **Two systemd units on different ports** (Option A in the discussion): ~half-day to build, requires env-driven config split (results dirs, DBs, ports), still has P110/GPU contention for measurement work. Pays off only if staging runs for hours-days at a time, which is not the workflow.
- **Docker-isolated staging** (Option B): same P110/GPU contention; ROCm-in-container is non-trivial; only earns its keep when GoS1 hosts other projects. Tracked separately in CLAUDE.md "Dockerize OWL" deferred item.
- **Different machine entirely** (Option C): can't validate measurement code paths since hardware differs. Misses the point.

### Open questions

- **Queue drain on `stage-on`** — block until queue empties, with a timeout, or just accept the dropped-job risk? Lean: short timeout (60s), then warn-and-proceed.
- **Where the maintenance HTML lives** — `/var/www/owl-maintenance.html` is conventional; could also live inside the repo at `wattlab_service/static/maintenance.html` and be served via nginx alias. Slight preference for the repo location so the page evolves with the brand without a separate deploy step.
- **Auth on staging** — staging runs the same gate password as prod (since it's the same `.env`). For testing CR-001's auth flow, staging may need its own gate password override. Defer until CR-001 lands.

### Implementation order

Single afternoon, ~1 hour of actual work:
1. Write `maintenance.html` (5 min).
2. nginx vhost edit + reload (15 min, including syntax debugging).
3. `bin/stage-on` and `bin/stage-off` (20 min).
4. Document the workflow in CLAUDE.md or a `STAGING.md` (10 min).

### Pre-conference: yes — unblocks every other CR's restart-and-test loop. Probably the second-most-leveraged conference-runway change after the access-spine refactor itself.

---

## CR-012 · Persist variance calibration history

**Status:** captured 2026-05-01 — nice-to-have.
**Triggered by:** owner notes during Session 17 wrap — every variance calibration overwrites the previous values in `settings.json`, so there's no record of how variance has drifted across kernel updates, room-temperature changes, GPU driver bumps, or thermal-paste age.

### Problem

`settings.json` keeps only the **latest** `variance_pct`, `variance_idle_pct`, `variance_cpu_pct`, `variance_gpu_pct` — the four numbers written by `video.py:657` at the end of a calibration run. The previous run's numbers vanish on the next save. This makes it impossible to ask:
- "Has the system become noisier over the last quarter?"
- "Did the kernel 6.17 update change our baseline?"
- "What was variance the day we ran the canonical Meridian benchmark?"

For a measurement project that publishes confidence figures, that history is genuinely useful — and trivially cheap to keep.

### Agreed direction

Append every completed calibration to `results/variance/history.jsonl` (or similar). One JSON object per line, append-only:

```json
{"ts": "2026-05-01T18:42:11Z", "variance_pct": 1.08, "variance_idle_pct": 1.79,
 "variance_cpu_pct": 0.82, "variance_gpu_pct": 0.64,
 "w_base_mean": 53.2, "cpu_tctl_at_start": 41.2, "gpu_junction_at_start": 36.0,
 "runs": 10, "kernel": "6.17.0-22-generic", "git_sha": "880825c"}
```

Captures enough context that a future spike about "why did variance jump" is answerable. Use the existing `persist.py` save machinery if it fits (write a sibling helper or a `save_calibration` function), or a small append in `video.py` near line 657.

Bonus: a small `/variance/history` page or JSON endpoint surfaces the trend (CR-004 graphing territory — could share that work).

### Where it lives

`video.py:651–658` — the block that writes back to `settings.json` is the natural place to also write the history line.

### Pre-conference: no, but cheap (~30 min). Could slot into any session as a low-priority filler. The data starts being valuable from the moment we start logging — every missed calibration is one more datapoint that's gone forever.

---

## CR-013 · Previous-result rows clickable for full stored detail

**Status:** captured 2026-05-02 — medium priority.
**Triggered by:** owner notes during CR-002 verification — once the confidence popover started firing on prev-run badges, it became obvious that the rows themselves carry only a one-line summary (date, model, mWh/tok, confidence flag). All the rich detail sits in the stored result JSON, but the only path to it today is downloading the JSON and reading raw fields.

### Problem

Today, "Previous runs" panels on `/video`, `/llm`, `/rag`, `/image`, and `/queue-status` show one terse line per run plus JSON / CSV download links. Anything beyond the summary line — the actual ΔW trace, thermals, ffmpeg command, response text, retrieval sources, generated image, full CO₂e block — is invisible without downloading. For a visitor giving OWL a serious look, that's a dead end. For Lab repetitive work, it's also a friction point (can't quickly re-inspect yesterday's run without round-tripping through JSON).

### Agreed direction (rough)

Make each prev-run row click-to-expand-or-load-full-card. Two competing design constraints:

1. **Public visitors:** want everything visible — the same rich result card they'd see for a fresh run, just labelled "↩ Previous run · 2 hours ago" (the `prevNote` line that already exists in `/image`'s `renderImageBoth` etc.).
2. **Lab repetitive work:** dozens of runs in a session; expanding inline would clutter the page; collapse-by-default with a click-to-expand affordance is right.

Default lean: **collapsed by default, click row to expand inline below the row**, fetching the full result via the existing `/results/{type}/{job_id}` GET path and rendering through the same per-page render function used for fresh runs (`renderResult`, `renderLLMSingle`, etc.). A second click collapses. Multiple rows can be open at once for side-by-side compare. Lab tier could optionally get an "expand all" toggle.

### Where it lives

Each page's `renderPrevRuns` JS function (one per route — see line numbers in main.py: `/video` ~1504, `/llm` ~2377, `/rag` ~3090, `/image` server-side ~4700, `/queue-status` similar). Render functions for fresh runs are already structured to take a result object and produce a card — re-use them.

### Open questions

- Lazy-load JSON on click vs. preload all when prev-runs list renders? Lazy-load is right at scale (tens to hundreds of runs in `results/`).
- Image previews on `/image` already inline-render thumbnails server-side — interaction with the click-to-expand pattern needs thought (probably: click thumbnail → open full result; the row stays as-is).
- Prev-run cards should reuse the corrected confidence popover (which now fires on the wrapped flag spans — landed today as part of CR-002 follow-up).

### Pre-conference: medium priority. Worth doing if there's a quiet half-day; the popover work today made the gap visible.

---

## CR-014 · RAG compare-3-modes missing carbon strip

**Status:** ✅ done 2026-05-02 (Session 17 follow-up — fixed inline alongside CR-002 closure).
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

**Status:** captured 2026-05-03 — quality-of-life follow-up to CR-011.
**Triggered by:** owner observation right after CR-011 shipped: the maintenance flag persists indefinitely until `stage-off` is run. Walking away from the desk leaves public visitors on the maintenance page until the owner remembers to come back. Two real use cases shape the design:

1. **5-minute conference demo** — short, well-defined window. If the owner forgets to lower the flag, public visitors see "Brief maintenance" for hours.
2. **1-hour testing session** — longer, intermittent activity (read code, fix bug, re-test). The owner is around but not necessarily poking the system every minute.

A naive "auto-lower after N hours" timer doesn't serve both: short enough to protect case 1 will fire mid-test in case 2; long enough to be safe for case 2 leaves a long gap for case 1.

### Design — lower on **inactivity**, not wall-clock

A small watchdog cron (every 1 min) checks: "is the flag file's mtime older than `MAX_IDLE_MINS`?" If yes, run `stage-off`. The owner extends the window simply by **using the staging system** — every Lab-tier request through FastAPI touches `/tmp/owl-maintenance` to bump its mtime.

This piggybacks on the access spine shipped in S17. `audience.tier(request)` already classifies requests as `Anonymous | Member | Lab`. A tiny middleware in `main.py`: when `tier == Lab` AND `/tmp/owl-maintenance` exists, `os.utime(flag, None)`. Zero owner burden — just keep using the LAN URL or SSH tunnel like normal, and the flag stays raised. Stop using it for `MAX_IDLE_MINS`, the watchdog lowers it.

### Mechanism

- **Middleware in `main.py`** (~5 lines): on every request, if `audience.tier(request) == Lab` and the flag file exists, `Path("/tmp/owl-maintenance").touch()`. Cheap (single stat + utime call); inert when the flag isn't raised, so zero cost in normal operation.
- **`bin/owl-maintenance-watchdog`** (new script): one-shot — checks mtime, runs `stage-off --main` if older than the threshold. Exits cleanly otherwise.
- **systemd timer** (`/etc/systemd/system/owl-maintenance-watchdog.timer` + `.service`) running the watchdog every minute. Enable/disable via `systemctl enable --now owl-maintenance-watchdog.timer`. Could be a cron entry instead, but systemd timers integrate with `journalctl` for free.
- **Settings**: `max_idle_mins` (default `30`) — tunable via `settings.json` so the owner can dial it for a known-long testing session without editing code.

### Why 30 minutes as default

- Short enough that a 5-min conference demo + ~20 min of distraction afterwards still recovers automatically before lunch.
- Long enough that a normal testing session (poke, read logs, think, re-test) doesn't trigger mid-task — most "I'm working on this" gaps are well under 30 min.
- The owner can lower it to `5` for "I'm definitely doing a quick demo" or raise it to `120` for "I'm head-down on CR-001b for the afternoon." Settings page exposes the dial.

### Open questions

- **Should manual touch suffice as a heartbeat?** I.e. the owner can also just run `touch /tmp/owl-maintenance` to extend without making a request. Probably yes — costs nothing to support and gives a CLI escape hatch. Document in `bin/README.md`.
- **What counts as Lab-tier activity?** Today: any request from a private-IP source (`audience.tier()` returns `Lab` for 192.168/10/127). When CR-001 lands proper auth, switch to "authenticated owner" or stay with IP. Loose IP detection is fine for CR-015 — it errs on the side of "owner is around."
- **Shutdown behaviour on `stage-off` from watchdog**: should the auto-`stage-off` use `--main` or stay on the staged branch? Lean toward staying on the current branch (don't surprise the owner with a checkout they didn't ask for); the maintenance page comes down but they're still on the feature branch when they return. Document clearly.
- **Recovery if the watchdog races with active testing**: if the watchdog fires the moment the owner returns, the public site swings back live mid-keystroke. Acceptable cost — they can `stage-on` again. Not worth a debounce.

### Why not the alternatives

- **Wall-clock timer (auto-off after N hours from `stage-on`):** doesn't differentiate the two use cases above. Fails one or the other.
- **Manual heartbeat command (e.g. `stage-keepalive`):** owner has to remember it, which defeats the "I forgot" motivation. Activity-driven is the point.
- **Blocking `stage-on` shell session that lowers the flag on Ctrl-C:** binds staging to a specific terminal session; bad fit for SSH-tunnel testing where the owner might close the laptop. Watchdog is decoupled from any session.

### Implementation order

Half a session, ~1.5 hours:

1. Middleware in `main.py` — ~5 lines, one new import, behind a `flag.exists()` check (10 min).
2. `bin/owl-maintenance-watchdog` shell script — mtime check + `stage-off` invocation (15 min).
3. systemd timer + service unit (15 min).
4. Settings field `max_idle_mins` (10 min).
5. Test plan: raise flag, verify watchdog leaves it alone while you curl LAN every few seconds; stop curling, verify it lowers after `max_idle_mins`. ~30 min.
6. Update `bin/README.md` "Things to know" section to reflect the auto-lower behaviour and the manual-touch heartbeat (10 min).

### Pre-conference: nice-to-have, not must-have

The conference is the strongest argument *for* this CR (forgetting to lower the flag during a busy event is the realistic scenario). But CR-001 / CR-001b are higher-leverage for the launch itself. Land CR-015 if there's slack between CR-001b and CR-001 closing, or right after CR-001 ships if not.

---

## CR-017 · 24/7 projection on the carbon strip (workload-aware "if this ran continuously")

**Status:** captured 2026-05-03 — sibling to the EV-distance equivalence (shipped in Session 18 part 11). Owner request: make CO2e more meaningful by showing not just "this single job's footprint" but also "what happens if this workload runs continuously."
**Triggered by:** CO2e numbers for individual jobs are honestly tiny (a single image gen is mm-scale of EV driving). The magnitude only starts to matter for streaming when you multiply by time × volume. A "if this ran 24/7" line in the carbon strip would make the scale leap visible without arithmetic.

### The opportunity

For a long-running or always-on workload — live-stream encoding, an LLM model serving requests, an image-generation API — the natural framing is rate × time:

```
This image generation: 156 µg CO2e (≈ 3 mm EV)
Continuous (24h × 365): ~75 g CO2e/year (≈ 1.5 km EV)
```

That's the thinking the EV equivalence line *almost* gets to but stops short of.

### Why this is more nuanced than EV equivalence

The EV line works on every workload because every workload has a known total energy. The 24/7 projection only makes physical sense for workloads that could plausibly run continuously:

- **Yes:** live-stream encoding, LLM model serving, embedding generation pipeline, image generation API endpoint, RAG retrieval service.
- **No, or only with framing:** a single one-off video transcode (no one runs the same transcode in a loop), a one-shot image prompt (creative workflow, not a service), a single batch run (it's a measurement, not a service).

If we project 24/7 on every result, "if this image gen ran 24/7 = X" reads as silly because no one does that. If we project only on certain workloads, we need either a workload classifier or a UI toggle.

### Design candidates

1. **Always-on toggle on the result page** ("Show as continuous service: [off / 1h / 1day / 1month / 1year]"). Visitor opts in. Multiplies the displayed CO2e (and EV-distance) by the chosen multiplier. Universally applicable, no per-workload heuristics needed. Probably the cleanest first version.
2. **Workload-aware projection** — only show 24/7 on jobs that pass a "naturally continuous" filter (LLM serving, RAG, live-stream encode benchmarks). Cleaner UX (no toggle to discover) but requires the classifier and is harder to extend.
3. **Both** — workload-aware projection appears by default on continuous-natured workloads, but the toggle is always present so visitors can override. Best UX, most code.

Lean: ship #1 first. Add #2 layered on top later if visitors are hitting it. #3 is the eventual right answer but earns its keep only after #1 has been used in anger.

### Open questions

- **Where does the toggle live in the UI?** Inside the carbon strip's collapsed `<details>`? As a sibling control above the strip? On the top-of-page "results filter" if we ever add one? Lean: inside the carbon strip, just above the EV line, since that's the section the projection modifies.
- **What multipliers?** 1h / 1day / 1month / 1year is the obvious set. Could also include "1B requests" for serving workloads — but that's a different framing (volume not time). Defer.
- **Should the 24/7 default state be "off" or "on" for naturally-continuous workloads?** "On" is more impactful for LLM serving demos; "off" is safer (visitor sees the as-measured value first). Lean: off, but auto-suggest the toggle on continuous workloads.
- **Pricing the projection in a different currency** (e.g. "≈ X round-trip flights LON–PAR" alongside or instead of EV-km) — separate CR, not bundled here. EV is the universal-comparator default; flights / homes / etc. are bigger framings worth their own design.

### Implementation order

Half a session, ~2 hours for the toggle-only version (#1):

1. Add a small toggle UI inside the carbon strip — radio or compact dropdown (15 min).
2. Wire the multiplier into the headline + EV line + reference row + comparison rows. Every grams display gets `× multiplier` (45 min).
3. State persistence in the URL hash (`#continuous=1d`) so visitors can share a "look at this serving footprint" link (20 min).
4. Tooltip explaining "this is the same workload assumed to run continuously" (10 min).
5. Capture per-workload-type defaults as a follow-up if usage warrants (#2 later).

### Pre-conference: nice-to-have

CR-017 strengthens the streaming-impact story (which is the conference headline) by making "single job × volume = real impact" tangible without forcing the visitor to do the arithmetic. But it's not on the critical path for CR-001 / CR-001b (auth + demo lock are launch blockers). Land it after CR-001b if there's time, or post-launch if not.

---

## Caught during the session but **not** new CRs

For the record, several items came up that don't warrant new CR entries:

- **Bug: `/settings` page rendered empty mid-run** (~T+338s) — owner observed this when trying to demo settings during a queued calibration. Filed as a bug to investigate, not a CR. May be related to job-state machine showing the page in a transient state. Repro: start a calibration, immediately reload `/settings`.
- **Confidence multipliers (5× / 2×) need statistical grounding from Tanya** — already in CLAUDE.md "Open Questions" / Deferred. No new CR.
- **Codec apples-to-apples equivalence (GOP, profile)** — already in CLAUDE.md Deferred. No new CR.
- **Long-term mash-up of REM + OWL data for 100s of homes** — covered as the post-conference phase of CR-008. No separate CR.
- **"Counter for OWL's own compute footprint"** (Dom, ~T+3319s, in passing) — fun meta-toy, not load-bearing. Skip.
- **The 5-minute training narrative was generated mid-meeting** — captured separately if needed. No CR; deliverable not infrastructure.
