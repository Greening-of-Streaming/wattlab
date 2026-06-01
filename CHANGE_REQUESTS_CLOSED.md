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

## CR-005 · Software fan-speed control during tests

**Status:** captured 2026-05-01; **resolved 2026-05-13 (S24) by investigation — not feasible as conceived on GoS1's hardware; no code shipped.** Closing commit `54e724a` (CR entry rewritten with the findings); moved here in the S24 doc-tidy pass.
**Triggered by:** Dom + owner (transcript ~T+1796s, ~T+1840s) + owner notes.

### Original problem & direction (kept for the record)

GoS1 lives in the owner's sitting room with fans set conservatively low for noise. Some of the baseline drift seen in calibration runs is thermal — the chassis warms over a session. The proposed fix: programmatic fan control around tests — raise to an aggressive profile before a job, restore quiet after; `focus_mode_fan_profile: "aggressive" | "default" | "off"` in `settings.json` (default `"off"`); fan profile recorded in the result JSON. Open question at capture time: *exact mechanism on this hardware (Ryzen 9 7900 / RX 7800 XT / the chassis fans) — needs investigation.*

### Investigation (S24, 2026-05-13) — what's actually controllable on this box

`hwmon` enumeration + `lsmod` on GoS1:

- **GPU fans (RX 7800 XT)** — *controllable.* The `amdgpu` hwmon exposes `pwm1`, `pwm1_enable`, `fan1_input`, `fan1_target`: write `pwm1_enable=1` (manual), then `pwm1=0..255`; restore with `pwm1_enable=2` (firmware curve). Sysfs is root-owned → would need a sudoers entry like the focus-mode one. Currently `pwm1_enable=2`, fans at 0 RPM (zero-RPM idle).
- **CPU fan + the 5 case fans** — *NOT controllable from Linux.* No super-I/O sensor driver is present (`nct6775` / `it87` / Nuvoton / ITE — none loaded, no matching hwmon device). The only platform hwmon is `asus` (via `asus_wmi`) and it's empty — no temp/fan/pwm files. `sensors -j` reports zero chassis fan RPMs. The motherboard fan controller runs its BIOS curve and Linux can't touch it. Reaching it would mean booting with `acpi_enforce_resources=lax` and hoping a super-I/O chip probes cleanly — the kernel warns that can corrupt the EC; not worth it on a headless server in a living room.

### BIOS fan curve (owner note, 2026-05-13)

The case fans are configured in BIOS to stay quiet until ~70 °C, then ramp. Across all OWL testing to date the owner has never heard them spin up — the chassis never reaches the ramp threshold during a job, so the case fans sit at an effectively fixed low speed throughout. **Decision: leave the BIOS curve as-is.** Useful side effect: airflow during a calibration is a known constant, so a calibration stays valid as long as the BIOS curve isn't re-tuned (re-tuning it later → re-calibrate).

### Conclusion

The version of CR-005 that would help the baseline-drift problem — driving the *case* fans — isn't implementable in software on this hardware. GPU PWM control *is* possible but low-value: VAAPI encodes are ~15 s and barely warm the GPU (S21 thermal-recovery probe: post-GPU baselines converged by d≈5 s), and pinning GPU fans to max during a CPU job just adds a couple of watts of fan power to the measurement — worse for cleanliness, not better. The genuinely useful action — a fixed, documented BIOS fan state — is already in place (quiet-below-70 °C, never observed ramping) and is a BIOS setting, not OWL code.

**No code planned.** If a future chassis/cooling change reopens this, GPU PWM is the only software lever and the BIOS-curve constant is the calibration precondition to re-check. Separately, CR-005's drift concern is partly addressed by the S24 re-enable of the 5th case fan via a Y-splitter (a fixed hardware change — see JOURNAL S24); the S24 thermal-recovery probe showed it did *not* move within-session drift (mean within-window CV ~2.0%, essentially the S21 ~2.14%) — expected, since the BIOS curve never ramps the fans.

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

---

## CR-027 · Tier explanation pass

**Status:** ✅ CLOSED S26 (2026-05-20) — found already-implemented; verified + closed. Captured 2026-05-04 (post-meeting). Medium priority. Bundles items 8 + 9 — both are tier-explanation copy/UX on the same surface.
**Triggered by:** team meeting 2026-05-04 — current "Why this matters" / tier explanation is too buried at the end of the demo, partly outdated, and the public/member/lab text still describes anonymous upload as allowed and shows the wrong member upload cap. Lab column is missing entirely.

### Problem

The demo's Findings step has the capability matrix as product copy (CR-001 part B/2) — it's the right *content*, in roughly the right *place*, but the meeting confirmed it underperforms in two ways:

1. **Buried.** Visitors complete most of the tour before reaching the explanation, so the "what tier am I?" question is asked silently throughout the earlier steps without an answer.
2. **Stale.** The current copy was written before CR-001 part D shipped (per-tier upload caps) and before the meeting decision to remove anonymous upload entirely. So:
   - It still says anonymous upload is allowed.
   - Member upload cap is shown incorrectly (probably the pre-CR-001-D placeholder).
   - Lab tier isn't mentioned, even though every screenshot a team member shows has the Lab chip in the corner.

### Agreed direction

**Three small changes.**

1. **Refresh the capability matrix copy.** Walk every row of the table currently rendered on `/demo` Findings step against the canonical policy table in CR-026, and the per-tier caps in `settings.json`. Wire the upload cap numbers to live settings via the same placeholder-injection pattern `/methodology` uses, so the table never silently drifts again.
2. **Add the Lab column.** The matrix is currently two columns (Public / Member). Add Lab. Even though no public visitor *is* Lab, presenting all three tiers makes the model visible and helps members understand that a recognisable subset of the team has stricter access.
3. **Surface tier framing earlier.** Add a one-line tier indicator to the demo's first step (something like *"You're browsing as: Anonymous · [sign in to do more]"* / *"You're a Member · here's what that means →"*). The full matrix stays at Findings; the early-step indicator just sets expectations and links forward. Server-rendered, no JS state.

### Cost / leverage

~3-4 hours: copy walk + placeholder injection + add column + first-step indicator. Leverage is conversion-funnel for member sign-up (anonymous visitors who recognise they could unlock more) and reducing post-demo confusion ("can I do X?" should be answered before they try, not after).

### Watch-outs

- **Don't double up with CR-021.** The "Sign in" chip prominence is a separate CR; this one shouldn't grow to include it. The first-step tier indicator is *content* (text in the page), not a CTA chip — different surface.
- **Member upload cap reads from settings.** That means if the operator changes `upload_size_member_mb` in settings.json, the demo copy updates on next page render. Verify this works on /settings round-trip.
- **Don't promise unimplemented capabilities.** Match the matrix to what CR-026 actually ships, not what the meeting wishes had shipped. If a row is conditional on CR-026 landing, sequence the merge so this CR ships *after* CR-026.

### Not in scope

- The bigger demo flow rework (Findings step aggregation across stored results) — captured separately in the CLAUDE.md "Open Questions / Deferred" list.
- The sign-in chip styling (CR-021).

### Open questions

- **Should the early-step indicator be on every page, not just the demo first step?** Probably yes for consistency, but it competes with the auth chip in the corner on small screens. Decide during implementation; default to demo-only and revisit.

---

## CR-037 · Tether the AI jobs to streaming workflows (anchor to the Language Lab AI position paper)

**Status:** ✅ CLOSED S26 (2026-05-20) — shipped. Captured 2026-05-11 (board meeting + AI position paper review). High priority — board-endorsed quick-win.
**Triggered by:** GoS board meeting 2026-05-11. Tania: *"we did publish a paper about the uses of AI in the context of video… maybe the inclusion of AI in our [tool] should be kind of in that context. We can take some of those applications, at least the simpler ones, link it and maybe compare — encoding in the bad standard way takes that, compares to a prompt of that length or complexity — rather than just 'here's the AI tab which has nothing to do with streaming.'"* Dom seconded with the "25 fps × 15 min" personalisation-energy framing. Cross-references the Language Lab Jan-2026 position paper *"Artificial Intelligence in Streaming Media Sustainability: Distinguishing Impact from Innovation"* (v1.4 final).

### Problem

CR-006 (closed) reframed `/llm`, `/image`, `/rag` as "AI workloads — beta · exploratory" — the right step, but a *negative* framing (what they're not). The AI tabs still read as generic AI demos with no connection to streaming. That's the failure mode Tania flagged and Dom warned against: *"I don't think greening and streaming should be going and just doing energy measurement of AI, because then the greening of AI will lose our identity and will lose our focus."*

The paper provides the positive framing that's currently missing. Central claims OWL can express:

- AI in streaming is **neither inherently a sustainability solution nor a threat**; the type, size, and deployment context determine net impact.
- **The type of AI matters enormously.** Small specialised CNNs (per-title encoding, scene classification, super-resolution) are orders of magnitude cheaper than general-purpose LLMs and diffusion models. **Streaming primarily uses the former.**
- **Data volume ≠ energy consumption.**
- **Efficiency must be measured against useful work, not assumed.** Critically: measuring the energy AI *adds* is only half the equation — the other half is the energy AI *avoids* through better compression / caching / routing.
- **Training vs inference** are distinct cost categories; OWL measures only inference.
- **The Personalisation Risk:** AI-generated personalised content streams break the multicast / cached-edge model and return delivery to expensive unicast.

Today none of those framings appear on `/llm`, `/image`, `/rag`. Visitors leave with a fuzzy "AI uses lots of watts" impression but no map of where the numbers fit in streaming sustainability.

### Agreed direction

**Each AI page gets a streaming-anchored header band, a video-relative comparison readout, and adopts the paper's framing principles as standing copy.** No new measurements — reframing only.

#### Per-page reframes

- **`/image` → "AI-generated content / video-frame synthesis."** The Personalisation Risk anchor. Every result also shows per-image energy *scaled to a video*: *"× 25 fps × 1 min = X Wh per minute of personalised content"* and *"the same 1-minute clip encoded H.265 GPU = Y Wh (≈ N× less)."* Makes the personalised-unicast cost concrete; lands Dom's "25 fps × 15 min" comment directly. Use the canonical H.265 GPU on Meridian-120 s as the video baseline (already in CLAUDE.md Key Findings).
- **`/llm` → "the 'what about AI?' upper bound."** Honest framing per the paper: chat-style LLMs have **limited direct application in traditional streaming workflows**; streaming itself uses small specialised CNNs. OWL's LLM tab measures the *expensive end* of the spectrum as an upper bound, not the streaming-typical case. Each result also shown as a multiple of the canonical H.265 GPU encode of Meridian-120 s ("≈ N× a 120 s 1080p hardware encode") — Ben's "ratios stay stable even as models go stale" thesis from the board.
- **`/rag` → "the energy cost of a retrieval/context layer."** Less directly streaming-shaped, so framed as a controlled study of a *variable that recurs in streaming AI* (context-aware encoding decisions, retrieval-augmented QoE models). The corpus being GoS's own ~100 white papers makes it self-referential — label it explicitly as a meta-demo, not generic Q&A. Same video-relative comparison line.

#### Standing copy adoption

A small "About this measurement" expander on each AI page lists, in 4–5 lines drawn verbatim/near-verbatim from the paper:

1. *Type of AI matters enormously — small specialised CNNs vs general-purpose LLMs are orders of magnitude apart.*
2. *Data volume ≠ energy consumption.*
3. *OWL measures the energy AI **adds**; we do not measure the infrastructure energy AI **avoids** through optimisation. Both halves are needed for net impact; OWL has the first.*
4. *Inference cost only — no amortised training cost included.*
5. *Watch for rebound effects: efficiency gains can be offset by expanded use (more variations, more personalisation).*

Mirror text lives on `/methodology` under a new "AI workloads — framing" subsection; the on-page expanders summarise.

#### Cross-links

Each AI page header gets a one-line link to the position paper PDF (publish location TBD with Language Lab; failing that, link the closed-doc copy under `/static/papers/` with a "GoS member access" note). The methodology page's "AI workloads" subsection gets the same link as the primary anchor.

### Lab look & feel constraint

Three header bands, three comparison readouts, three about-expanders — this is the most copy-heavy CR in the batch and the most exposed to the design risk. Mitigations: the header band is one line + an inline link, not a banner; the video-relative comparison is one extra row in the result KPI block (no new card); the "About this measurement" copy lives behind a `<details>` summary collapsed by default. Total visual addition per page must be *one line* unless the visitor opens an expander.

### Cost / leverage

~1.5–2 days:
- ~3h: copy draft (header bands + video-relative readouts + about-expanders) — heavily reuses paper text.
- ~4h: per-page wiring (`/llm`, `/image`, `/rag`) + the methodology subsection.
- ~2h: the video-relative comparison number — a small helper that pulls a *pinned* canonical H.265 GPU Meridian-120 s result from disk as the reference, then formats "≈ N× a 120 s 1080p hardware encode" against the current result's energy. Caches the reference at startup; falls back gracefully if the canonical result is missing.
- ~1h: visual verification, dense-page check, lab look & feel review.
- ~1h: tests for the multiplier helper.

Leverage: the board's explicit "AI must stay tethered to streaming" deliverable. Without it, the AI tabs remain the strongest argument *against* OWL's coherence; with it, they become the strongest argument *for* GoS's measurement-first stance on AI.

### Watch-outs

- **The canonical reference is a moving target.** When the canonical Meridian H.265 GPU benchmark is re-run (e.g. after CR-029 lands), the multiplier "≈ N×" shifts. Pin the reference to a specific *commit-tagged* result file under `results/canonical/`, not "whatever's latest." When the canonical is intentionally updated, do the multiplier review as part of that work.
- **Position-paper publication state.** As of 2026-05-11 the paper is final v1.4 but not yet on the public site. If it lands behind member access, the AI tabs' link copy needs to say "GoS member document" — not a dead URL.
- **Don't quietly convert the multipliers into a leaderboard.** "AI is N× a video encode" is a framing helper, not a competition. Avoid bar charts ranking everything against the H.265 baseline; one inline line per result is the right dose.
- **RAG's streaming connection is the weakest of the three.** The "retrieval layer as a recurring streaming-AI variable" framing is honest but more abstract than the image/LLM ones. Don't oversell the connection; if the framing reads forced, leave RAG as the meta-demo and skip the streaming-relative readout for it.
- **The "About this measurement" copy must match the paper exactly on contested phrasing.** *"AI is neither inherently sustainable nor unsustainable"* is the paper's headline; don't paraphrase it in OWL or the two voices diverge.

### Cross-references

- **CR-006 (closed):** the "beta · exploratory" framing. CR-037 adds the positive framing on top.
- **CR-029:** the canonical Meridian H.265 GPU result is the reference. CR-029 may shift the canonical bitrates; if so, the multiplier needs a refresh.
- **CR-034:** if the unified result card lands first, the video-relative comparison row drops into the shared renderer cleanly.
- **CR-036:** carbon hardening sets the energy/carbon visual contrast that the AI tabs inherit.
- **CR-042:** the Pixop placeholder is exactly the paper's "small specialised CNN" pattern; if Pixop joins, CR-037's framing extends to whatever measurement module replaces CR-042's placeholder.

### Priority: high

Board explicitly endorsed this. Highest-value framing change for OWL's public AI narrative.

---

## CR-040 · "Reproduce this result" downloadable bundle

**Status:** ✅ CLOSED S26 (2026-05-20) — shipped (video-only V1). Captured 2026-05-11 (board meeting). Medium priority — addresses the explicit trust / buy-in concern from Marisol and Barbara.
**Triggered by:** GoS board meeting 2026-05-11. Marisol: *"verification and trust of those data — it would be really good to have some of the members buy in and see if we can do some tests. We were talking to Telefónica — probably just verify and demonstrate that you can trust those data is something that can be worked out."* Stan: OWL is the recruitment loss-leader; reproducibility is what makes it convincing to a sceptical operator. The AI position paper itself says GoS has *"our own early proof-of-concept working models that we are encouraging the wider community to experiment with."* Reproducibility is what makes that invitation real.

### Problem

OWL logs the exact ffmpeg command in each result JSON (CR-002 closed) and pins ffmpeg via `ffmpeg_bin` (S23). Everything needed to reproduce a video result is technically present on disk — but spread across files, with no member-friendly path from *"I see this result in the UI"* to *"I'm running the same workload on my own GoS1-class server and comparing my numbers to OWL's."* When Marisol talks to Telefónica about "verifying the data", today's only honest answer is *"clone the repo, set up a Tapo plug, calibrate."* Friction → no verification.

### Agreed direction

A per-result **"Reproduce this" download** bundling everything needed to re-run on the visitor's hardware and compare:

1. **Bundle contents (one zip per video result):**
   - `cmd.sh` — the exact ffmpeg command (already in result JSON), wrapped in a minimal shell script that prints the command, runs it, prints elapsed wall time.
   - `expected.json` — OWL's measured numbers for this run: `delta_w_mean`, `delta_e_wh`, `duration_s`, `confidence_flag`, hardware fingerprint (`cpu`, `gpu`, `kernel`, `ffmpeg_version`), `variance_pct_at_time_of_run`. Plus a "compare bounds" block: 3σ envelope on `delta_e_wh` from OWL's variance, so the reproducer has a numeric pass/fail.
   - `source/` — the input asset reference (URL to Meridian under its CC BY 4.0 license; for uploaded inputs a "you'll need to provide your own; the OWL-side SHA was X" note).
   - `README.md` — three sections: *prerequisites* (ffmpeg version, sensible OS, a power meter — any of: Tapo P110, a PDU with ≥1 s granularity, a Kill-A-Watt with manual logging), *running the script*, *interpreting the comparison*. Reads as an invitation, not a barrier.
   - `compare.py` — reads `expected.json` and a user-supplied `your_run.json` (same shape), prints per-metric diff and green/yellow/red verdict against the bounds. Stdlib only.

2. **Surfacing:**
   - "↓ Reproduce this" button on every video result card (next to the existing CSV/JSON download).
   - Hidden on AI results in V1 — LLM/image/RAG are *less* reproducible across hardware (model is sensitive to driver/cuDNN/ROCm versions in ways video isn't); capture as a follow-up.

3. **Receiving comparisons:**
   - `POST /reproduce/contribute` (Member-tier) accepts `your_run.json` and records under `results/contributed/`. *Optional* — useful if a member wants OWL to track their reproduction; not required for the verification loop to work.

### Lab look & feel constraint

One new button per result card, same compact treatment as the existing download links. No new page.

### Cost / leverage

~1 day:
- ~3h: bundle generator (server-side, builds the zip on demand from result JSON + canonical assets).
- ~2h: `compare.py` (~80 lines, stdlib only).
- ~2h: README copy.
- ~1h: `POST /reproduce/contribute` endpoint + tests.
- ~1h: UI button + visual.

Leverage: Marisol said it directly — *"trust those data is something that can be worked out."* This is the worked-out version. Doubles as the paper's *"open proof-of-concept the wider community can experiment with"* claim made real. Recruitment angle (Stan + Barbara): a member who runs the script and sees their numbers within OWL's bounds *is* the conversation Barbara wants when she asks *"how would you envision using this?"*

### Watch-outs

- **Don't promise cross-hardware identicality.** A Ryzen 9 7900 won't produce the same ΔW as a different chip — the bound is "within OWL's variance envelope on equivalent hardware", not absolute. The README must explain this *before* the visitor runs the script and is surprised.
- **Confidence-of-confidence problem.** If the reproducer hits a wide envelope on their hardware, that's actually informative (their lab has more variance than OWL's) — render the comparison as "your variance + OWL's variance" rather than "you matched / didn't match."
- **License the Meridian asset reference explicitly.** Netflix's CC BY 4.0 is permissive; the README carries the attribution. Don't ship the asset in the bundle (812 MB); link it.
- **Don't blow the "OWL is a lab tool" framing.** The bundle is a serious-but-friendly addition; don't market it as a product. *"Reproduce this"* button copy beats *"Verify OWL's claims"* copy.
- **Mike's data-centre rack offer.** If that materialises, the bundle becomes the natural validation harness for "is OWL's result reproducible on a colocated GoS1-class machine in a real data centre?" — sequence with CR-031 sub-section 3.

### Cross-references

- **CR-002 (closed):** ffmpeg cmd already logged. CR-040 makes it actionable.
- **CR-031:** when OWL is portable, the reproducer works against any OWL deployment; the bundle format becomes the interchange layer.
- **CR-008:** REM ↔ OWL — contributed reproductions eventually merge into the cross-deployment data model.
- **AI position paper:** the *"proof-of-concept the wider community can experiment with"* claim. CR-040 is what makes it true.

### Priority: medium-high (scoped tight, video-only V1).

A working "reproduce this" button is the single most convincing artefact for a sceptical member or stakeholder. Don't gold-plate it.

---

## CR-044 · VMAF quality score on video comparison cards

**Status:** ✅ **SHIPPED 2026-05-22** — `feature/cr-044-vmaf`, merged to `main` (`07e03ad`); CSV column + methodology follow-ups in `298097c` / `d208758`. Feasibility was proven by a live trial on GoS1 the same day (see below).
**Triggered by:** owner request — "for any video job involving more than one video (CPU vs GPU, or comparing codecs), show a VMAF score, just below output file size in the comparison result cards."

### Problem

OWL's video comparisons report energy, speed, and output size — but never *quality*. A visitor reading "H.265 GPU used 81% less energy than CPU" can't tell whether the two encodes are perceptually equivalent. Output-size parity (today's implicit proxy) only confirms the bitrate target was hit; it says nothing about how well each encoder spent those bits. VMAF (Netflix's perceptual quality metric, 0–100) is the industry-standard answer and turns every comparison into a defensible energy-vs-quality statement — squarely the GoS framing ("if it can't be measured, it shouldn't be asserted").

### Scope

**Comparison modes only** — `mode: "both"` (CPU vs GPU) and `mode: "all_codecs"`. Single-encode runs (`run_single` / `renderSingle`) get no VMAF: there is no second encode and the value is the *delta*. Per owner.

### Feasibility — proven by live trial 2026-05-22 (not theory)

Ran the real filtergraph on two retained outputs from an actual CPU-vs-GPU H.265 run (`GoS-in-50s.mp4`, 1080p30):

- **Embedded model works with no model file** — `/usr/local/bin/ffmpeg-master` is built `--enable-libvmaf` with `vmaf_v0.6.1` compiled in; bare `libvmaf` scores without a `model=` arg. System `/usr/bin/ffmpeg` 6.1.1 lacks libvmaf, so this **must** route through `_ffmpeg_bin()`.
- **Result: CPU 91.48 / GPU 91.31** — within 0.17 VMAF (JND ≈ 6 points), i.e. visually identical. Paired with the known ~81% GPU energy saving, that *is* the headline.
- **Cost: ~7 s per 50 s/1080p30 clip** at `n_threads=12` (~215 fps). ≈17 s for a 120 s clip; ≈100 s for a 6-file all-codecs sweep.
- **Bug caught before building (the reason to trial first):** the naive "scale the reference only" graph **failed on the GPU/VAAPI output** with `input height must match`. The hardware HEVC encoder pads the decoded surface (CTB alignment, 1080→1088) in a way ffprobe does *not* surface (it reports 1080). It breaks precisely the GPU half of every comparison. **Fix (verified):** `crop` the distorted to the exact target dims — removes padding **without resampling the measured signal** — then `libvmaf`. The sensible 91.31 confirms the crop alignment is correct (a misaligned crop would tank the score).

Proven filtergraph (crop dims derived from the reference, not hardcoded, so it survives non-16:9 sources):
```
[0:v]crop=<refW>:<refH>:0:0,setpts=PTS-STARTPTS[d];
[1:v]scale=-2:<refH>:flags=bicubic,setpts=PTS-STARTPTS[r];
[d][r]libvmaf=n_threads=N[:n_subsample=K]:log_fmt=json:log_path=<tmp>
```

### Energy integrity (the load-bearing constraint)

VMAF is CPU-heavy and **must never enter the reported energy number.** It runs as a **terminal pass after the whole job's measurement is over** — after `stop_event.set()` stops polling, after `LOCK_FILE` is released and `focus_mode_exit` runs in each compare function's `finally`. No P110 poll is taken while VMAF runs, so its draw is excluded by construction. It must run *after the job's last baseline*, never interleaved between encodes — otherwise VMAF heat biases the next encode's baseline (second-order leak). The measured workload is the encode; VMAF is offline QA, legitimately out of scope, same as OWL's own web-serving overhead.

### Subsampling: temporal, not spatial

If wall-time ever bites, subsample **temporally** (`libvmaf n_subsample=K` — every Kth frame, each at full resolution). **Never spatially** — downscaling frames before scoring corrupts the metric (VMAF is trained for a presentation resolution) and breaks comparability, the same reason we crop rather than scale the distorted. Ship `vmaf_n_subsample` defaulting to 1 (full); raise only if needed, and identically across all sides of a comparison.

### Design / implementation

1. `video.compute_vmaf(distorted, reference, s) -> float | None` — fail-soft (None on any error, like other optional metrics), uses `_ffmpeg_bin()` + the proven graph, parses pooled mean from the JSON log.
2. Terminal VMAF pass in `run_both_measurement` + `run_all_measurement` (after the `finally`); attach `vmaf` to each side's result dict. Flows automatically into persisted JSON, reproduce bundles, and the `owl_version` stamp — no schema change.
3. Settings: `vmaf_enabled` (default true), `vmaf_n_subsample` (default 1). Lab can disable/tune.
4. UI — VMAF just below output size in all four compare-card sites: `renderBoth` (`main.py:3186`), `renderAllCodecs` matrix (`3281`/`3284`) + miniCol detail (`3306`), stored all-codecs prev-run table (`1949`). (CR-037 lesson: update live *and* stored renderers.)
5. Optional but recommended: a quality note in `analyse()` / `analyse_all()` — e.g. "GPU within 0.2 VMAF of CPU at 81 % less energy." It *is* the GoS story.
6. Tests: parse-from-captured-JSON unit + fail-soft path + renderer smoke (TestClient).

### Cost / leverage

~half a day. Adds wall-time *after* measurement (queue occupancy, not energy). Disk: outputs are already retained by `run_single`; VMAF doesn't change that (latent cleanup concern noted separately under CR-043 watch-outs). Leverage: high — turns every comparison into an energy-vs-quality statement, the missing third axis.

### Cross-references

- **CR-029** (encoding rigor) — VMAF is how you *prove* CPU and GPU are doing comparable work; this CR delivers the measurement, CR-029 the parameter validation. Natural pair.
- **CR-039** (energy-vs-quality axis for AI) — this is the video sibling: VMAF is for video what the frontier-model judge is for AI.
- **CR-043** (video preview in card) — both make the energy claim visceral; VMAF is the cheaper, more rigorous half (a number, not a player) and needs no retention rebuild.

### Watch-outs

- Crop, don't scale, the distorted (resampling the measured signal corrupts the score).
- VMAF only on `ffmpeg_bin` (master), never system ffmpeg.
- Keep it a terminal pass after the last baseline — never interleaved.
- Methodology note: VMAF measured at the delivered 1080p against the source downscaled to 1080p.

### Priority: ✅ shipped. Residual: per-mode VMAF inside V2 of CR-045; CSV/JSON already carry the column.

---

---

## CR-028 · Confidence model evolution (interim re-weighting + Tania's unified redesign)

**Status:** ✅ **Phase 2 SHIPPED 2026-05-22** (`feature/cr-028-confidence`, merged to `main` `713bf3a`; hardening `cc792db` + `044fc68`) — `confidence.py` CI model per Tania §9 v2, all four modules, raw samples persisted, legacy fallback, docs + tests. Phase 1 (interim re-weighting) was overtaken by Phase 2. Absorbed CR-020 + the 5×/2× threshold grounding. Two-phase history kept below for the design record.
**Triggered by:** team meeting 2026-05-04 — items 11 (statistical redesign — Tania) and 14 (variance composite weighting decision: 60/20/20 instead of mean of three).

### Problem

The current `variance_pct = mean(idle_cv, cpu_cv, gpu_cv)` mixes two different things:

- `idle_cv` is the noise floor — CV of raw idle watts during baselines.
- `cpu_cv` / `gpu_cv` are run-to-run reproducibility — CV of *ΔW values across runs*. Already a "noise of a noise" measurement.

Averaging them gives equal weight to a noise-floor measurement and a reproducibility measurement, which has no statistical defence. The S21 calibration data made this concrete: with 4.4% idle, 2.11% CPU, 17.22% GPU, mean = 7.91% — but the relevant noise for the confidence formula `noise_w = variance_pct/100 × W_base` is *idle*, not the average.

The meeting also identified a deeper problem: the entire confidence model relies on **three independent thresholds** (poll count + ΔW vs noise + the unstated "is the baseline itself behaving") that aren't unified into a single statistical claim. Tania proposed redesigning to a unified confidence calculation.

### Agreed direction

**Phase 1 — interim re-weighting (no working session needed).**

1. Change the composite formula:
   ```
   variance_pct = 0.6 × idle_cv + 0.2 × cpu_cv + 0.2 × gpu_cv
   ```
   in `wattlab_service/video.py:run_variance_calibration` (the line that currently does `mean_cv = round(sum(available)/len(available), 2)`).
2. Update the `/methodology` page's "Calibration integrity" prose to document the new weighting + why (idle is the noise floor; CPU/GPU contribute reproducibility signal but shouldn't dominate).
3. Update the `/settings` page's "Variance %" hint text similarly.
4. **Test**: a unit test that asserts the weighted formula on known inputs returns the expected composite, so future drift gets caught.

Effect on current settings: with idle 4.4%, CPU 2.11%, GPU 17.22%, the new composite is `0.6×4.4 + 0.2×2.11 + 0.2×17.22 = 2.64 + 0.42 + 3.44 = 6.51%` (vs current 7.91%). Once GPU CV recovers (after the `gpu_encode_max_s` tweak — see "Caught during the session"), the GPU contribution shrinks proportionally and the composite settles in the 3-4% range, very close to the probe's 2.96% pooled CV.

**Phase 2 — Tania's unified statistical redesign — SHIPPED 2026-05-22 (`feature/cr-028-confidence`).** `confidence.py` implements the §9 CI model exactly as specced below; `baseline_samples_w` + `task_samples_w` now persisted in every result energy dict; all four modules call the shared function; popover + `/methodology` + `/llm` band + `/settings` copy updated; legacy variance flag retained as fallback for pre-change results; `confidence.py` test suite added (268 tests total). Decisions captured below were implemented verbatim.

Tania's §9 v2 (`docs/wattlab_traffic_light_confidence.md` §9.1–9.7) is now on `main` (commit `d3d78e9`, cherry-picked 2026-05-22). It specifies a **CI-based single-run confidence**, scoped to *single-run measurability* ("can this one run be distinguished from idle?"), not run-to-run repeatability:

- **Inputs (option C, confirmed):** build the flag from persisted `baseline_samples_w` + `task_samples_w` plus `variance_idle_pct` as the calibrated idle noise floor. **Do not** use `variance_cpu_pct` / `variance_gpu_pct` in the single-run formula — they're run-level repeatability CVs, reserved for a later aggregate-confidence layer.
- **Uncertainty (§9.3):** `SE_calibrated = (variance_idle_pct/100·w_base)·√(1/n_base + 1/n_task)`; `SE_per_run = √(std_base²/n_base + std_task²/n_task)`; take the conservative one.
- **Score (§9.4):** `z = delta_w / SE_final`; `confidence_positive = Φ(z)` — one continuous score replacing the three-flag patchwork.
- **Thresholds (§9.5):** 🟢 `confidence_positive ≥ 0.95 ∧ n_task ≥ 10`; 🟡 `≥ 0.80 ∧ n_task ≥ 5`; 🔴 otherwise. Retires `variance_yellow_x` / `variance_green_x` from the single-run path.
- **Store (§9.6):** persist `confidence_method`, the raw sample arrays, the SE breakdown, `confidence_positive`, and 95% CI on ΔW + ΔE so old results can be reflagged.

**Decisions taken 2026-05-22 (Ben, with Tania present on-screen):**
1. **Baseline↔task drift → worst-case / safest.** §9.3's `SE_final = max(SE_calibrated, SE_per_run)` is extended to also carry an inter-window drift term: `SE_drift = variance_idle_drift_pct/100 · w_base` (the S25 drift CV, currently 1.10%), combined **additively** (most conservative): `SE_final = max(SE_calibrated, SE_per_run) + SE_drift`. Closes the original Phase-2 concern that drift between the time-separated baseline and task windows was ignored. (Tania may swap additive→quadrature if she prefers; default is additive = safest.)
2. **Autocorrelation → first pass uses raw `n` + 1.96.** Ship the simple version; `n_effective = floor(duration_s/5)` and the Student-t critical value remain documented future refinements (§9.5/§9.6).
3. **Apply to all four modules, not video-only.** §9 is written for video, but the same CI logic is applied to LLM, image_gen, and RAG. `confidence()` is shared by all four; the detection question ("above idle?") is ΔW-based in every module (LLM's mWh/token is downstream of the same ΔW).
4. Factor the four per-module `confidence(...)` copies into a shared `confidence.py` as the new model lands (as previously agreed).

**Implementation prerequisite (our work):** raw `baseline_samples_w` / `task_samples_w` are **not persisted today** — `confidence()` currently receives only `(delta_w, poll_count, w_base)`. Phase 2 therefore starts by adding that persistence (ties into Track A storage), then the shared `confidence.py`, then re-validating every result page renders the new flag.

This phase was **a design exercise first, code second** — the design is now agreed, so implementation can proceed.

### Cost / leverage

Phase 1: ~30 min code + 30 min docs + 30 min tests = **~1.5 hours**. No-regret quick win. Leverage: variance composite stops over-weighting reproducibility; meeting decision honoured immediately.

Phase 2: half-week minimum — design session, then implementation, then re-validating every existing result page renders the new confidence correctly. High leverage but requires Tania.

### Cross-references

- **CR-020** (per-run baseline CV gate): the in-run baseline-noise check Tania discussed is exactly what CR-020 captured. Phase 2 here probably *supersedes* CR-020 by absorbing it into the unified model, but Phase 1 + CR-020 are independent.
- **CLAUDE.md deferred** (5×/2× threshold grounding): same Tania session covers this. Phase 2 likely changes whether `variance_green_x` / `variance_yellow_x` even survive as parameters.
- **CR-022 + CR-023** (CR-022 cap + calibration gating): both shipped; Phase 1 sits on top of those fixes.

### Watch-outs

- **Don't ship Phase 1 without re-running calibration.** The composite formula change interacts with the current GPU CV anomaly (17.22% from too-short encodes). Land the `gpu_encode_max_s: 30 → 90` settings tweak first, re-calibrate, *then* ship Phase 1 — otherwise the team sees one number change and can't tell which fix moved it.
- **Phase 2 is a science problem disguised as a UI change.** Don't prototype implementation before the model is on paper. The danger pattern is "let's just try X and see if it looks right" — that produces a model nobody can defend.

### Not in scope

- Multi-machine / cross-platform confidence (different hardware, different P110 baseline) — separate problem.
- Carbon-side confidence (uncertainty bounds on gCO₂e) — separate again.

### Open questions (added 2026-05-04 after multiple calibrations; updated 2026-05-05)

- **GPU CV at `gpu_encode_max_s = 90`: ~~4.77% (n=3) or 24.5% (n=10)?~~** **Resolved 2026-05-05.** Overnight calibration at `variance_runs=24, variance_cooldown_s=90` produced **idle 2.41% / cpu 1.33% / gpu 4.77%** (`variance_pct=2.84`). At n=24, SE on the CV figure is ~14% of value — statistically real, not sampling luck. GPU lives near the bottom of Tania's 3–5% expectation; the n=10 24.5% reading was a small-sample artefact. Settings.json staged at the new runs/cooldown values; CV fields written by the calibration. Clean GPU figure available as Phase 2 design-session input.
- **Idle and CPU CV settling?** Across the 2026-05-04 calibrations, idle CV ranged 1.92–7.42% and CPU 0.71–5.28%. The morning's clean baseline (idle ~2%, CPU ~1%) is what we'd expect on a quiet box; the higher numbers correlated with active work elsewhere. The 2026-05-05 overnight n=24 calibration landed at idle 2.41% / cpu 1.33% — clean-baseline range, consistent with "no other active work on the box." ~~Open question for Phase 2: should the confidence model account for *time-of-day* idle baseline drift, or treat it as out-of-scope and rely on a fresh per-run baseline?~~ **Resolved 2026-05-22 (worst-case / safest):** the model carries an additive inter-window drift term (`SE_drift = variance_idle_drift_pct/100 · w_base`) on top of the per-run/calibrated `max()`, so drift between the time-separated baseline and task windows is accounted for rather than assumed away. See Phase 2 decisions above.

---

---

## CR-035 · Encode progress bar for long video jobs

**Status:** ✅ **SHIPPED 2026-05-08** (S23, `b2204b4`). `-progress pipe:1` parser in `video.py` (`_make_progress_cb` → `progress_pct` / `eta_s`), the % bar renders via `wlRenderProgress` (main.py), `tests/test_video_progress.py` (17 tests). Sibling CR-019 (resume-job) stays deferred.
**Triggered by:** owner — uploaded a 650 MB / ~1 hr video via Member-tier `/video/upload`. The widget shows stage + elapsed + live watts, but no "% through the encode" indicator. For an hour-long input the "Encoding" stage stays active for tens of minutes with nothing to look at except the watts ticking. Visitors on `/demo` never hit this scope (predetermined 2-min clip), but Lab and Member operators routinely do.

### Problem

`wlRenderProgress` displays the right *categorical* state — which stage, how many seconds elapsed, current power draw — but not the *progress through the active stage*. ffmpeg already knows: it logs `frame=…`, `time=HH:MM:SS.cc`, `speed=2.5x` to stderr on every frame. With ffprobe knowing the input duration up front, the percent-complete is one division. Today none of that flows out of `transcode()`.

The same widget is the natural surface for the bar — same target, same render call, just one extra optional field.

### Agreed direction (rough)

**Server side — `video.py`:**

1. **Read input duration once** via `ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 <input>`. Cache on `jobs[job_id]["input_duration_s"]` so the UI can format the "X of Y" label without a second probe.
2. **Switch `transcode()` from `subprocess.run` to `Popen`** with `-progress pipe:1 -nostats` appended to the cmd. ffmpeg writes structured key=value progress lines to stdout (`out_time_ms=`, `total_size=`, `speed=2.5x`, `progress=continue|end`). Read line-by-line in a worker thread.
3. **Update job state on every progress line.** Compute:
   - `progress_pct = (out_time_ms / 1000) / input_duration_s × 100`
   - `encode_speed = "2.5x"` (verbatim from ffmpeg)
   - `eta_s = (input_duration_s - out_time_ms / 1000) / float(speed)` — moving-average smoothed over the last ~30 s of samples to dampen jitter
   Write all three to `jobs[job_id]`.
4. **`_job_status()` already passes the full job dict to clients** (CR-019 helper), so `data.progress_pct`, `data.eta_s`, `data.encode_speed` flow through automatically — no endpoint changes needed.

**Client side — `_PROGRESS_JS`:**

1. **`wlRenderProgress` gains `opts.progressPct`, `opts.etaS`, `opts.encodeSpeed`.** Pure CSS thin coloured bar above the stage list when `progressPct != null`. Optional ETA + speed line below the watts readout.
2. **The four poll loops** (main pages + `/demo`'s `pollVideo`) thread the new fields through. One-line addition per call site.

### Setting shape

No new settings — the parsing is operational. Optional later: a `progress_smoothing_window_s` if jitter complaints come in (default 30 s).

### Cost / leverage

Half-day:
- ~1h: `transcode()` Popen rewrite + stdout/stderr split + worker thread for the progress reader.
- ~30m: ffprobe duration helper + cache.
- ~1h: widget progress-bar CSS + `opts.progressPct/etaS/encodeSpeed` plumbing.
- ~30m: parse-tests (unit-test the `out_time_ms=` parser against a recorded ffmpeg progress fixture).
- ~30m: ETA computation + smoothing.
- ~30m: visual verification across `/video` and `/demo`.

Leverage: removes the dead-end feel of long encodes on the Member surface. Especially valuable for `/video/upload` Members hitting the 1024 MB cap with hour-scale inputs (CR-001 part D's whole point).

### Watch-outs

- **Compare modes (CPU+GPU `*_both`) need two progress contexts.** Cleanest: one bar at a time, with a "1 of 2" label in the header. Two side-by-side bars is more polish than the v1 needs.
- **Encode `speed=` is wall-clock-relative; jittery on a busy machine.** ETA based on a single sample will be unstable — moving average is essential, not optional.
- **`-progress pipe:1` requires ffmpeg ≥ 3.x.** ffmpeg-master (CR-022 closure) is fine. The system `/usr/bin/ffmpeg` 6.1.1 also fine. Worth asserting `_ffmpeg_version()` is recent enough at startup; fall back to the existing no-progress path if not.
- **all_codecs sweep runs 6 encodes back-to-back.** The bar should reset cleanly between encodes (ffmpeg writes `progress=end` then re-opens for the next).
- **Don't lose stderr.** Today `transcode()` captures stderr for the failure-detection message. With Popen, capture both streams; only display stderr on failure.

### Open questions

- **Progress bar on non-video workloads?** LLM has its own per-token streaming; image gen typically completes in seconds. Probably no — but the `opts.progressPct` field is workload-agnostic so future modules could opt in.
- **What happens on `kill -9` mid-encode?** The progress reader thread should join on Popen exit and not block the worker. Unit-test the cancellation path.
- **ETA display threshold.** Show ETA only when `progress_pct > 5%` to avoid wildly wrong early estimates? Or always show with a wide error bar early?

### Pre-conference: medium priority

Not strictly blocking but a real polish item for Members operating long encodes during the launch window. Pair with CR-034 (unified results card) — the result card lands at progress=100% and benefits from the same widget context. CR-019's deferred resume-job piece is its sibling on the lifecycle side; CR-035 lives on the information side.

---

## CR-047 · Parent source + variants schema for `/video` Source picker

**Status:** Phase 1 shipped 2026-05-26 on `main` — schema + picker rewrite done, 272 → 290 tests. Phase 2 (vignette UI, source identifier on result JSON, parent+variant card framing) deferred to follow-ups.
**Triggered by:** owner, 2026-05-26 — *"moving forward we're going to have more variation for a given source (not just length as with Meridian full vs extract, but also different level of compression or even codec of the origin file), the UI needs to support that evolution. The vignettes idea is just for better demo experiences."*

### Problem (original capture)

`sources.PRELOADED` was a flat dict — each entry a peer, even when several entries were logically the same source. `meridian_4k` (full) and `meridian_120s` (extract) were siblings of the same Netflix master but rendered as unrelated picks; `bbb_4k` (CR-046) was about to gain a vignette and likely more variants over time. With the flat list, every new variant added a top-level row and `/video` Source would have hit the *"loses its LAB look & feel that must always allow for quick use"* failure mode the standing design principle calls out.

The owner had named three candidate axes of variation: length / scope, codec of the origin master, and compression level of the origin master. The pre-implementation tests (`docs/input_sensitivity_findings.md`, 2026-05-26) showed that **only the length axis carried enough energy signal to earn a picker slot**:

- Input bitrate spread (CRF span, same codec): 1.7 % CPU, 4.9 % GPU — at the noise floor.
- Codec-of-origin spread (industry-typical H.264 / H.265 / AV1 bitrates): 3.4 % CPU, 10.3 % GPU — borderline, AV1 carries the jump, but not enough to justify the matrix explosion.

So the picker landed at **2 variants per parent** (full + 2-min extract), not the 5-variant sketch. The vignette (a parent-level still image for UI friendliness, no measurement purpose — owner clarified mid-design) is plumbed as an optional field on the parent dict, orthogonal to the variant list. Codec-of-origin is documented as a Key Finding rather than a picker variant.

### Surface audit (2026-05-26, while adding CR-046 BBB)

Grep across `wattlab_service/` for hardcoded source keys turned up exactly two places:

- `sources.py` — the PRELOADED dict (correct home).
- `main.py:~2807–2845` — the `/video` Source picker, **hardcoded as four sibling `<input type="radio" name="source" value="…">` blocks** rather than driven by `sources.get_all_sources()` / `/video/sources`. This was why adding `bbb_4k` to `sources.py` alone didn't make it appear on `/video` — the radio list had to be touched too. **This duplication was the immediate target of CR-047** and is what shipped first.

`/demo` step 1's video job is a separate hardcode (`source_key=meridian_120s` at `main.py:~6955`), but it's a *selection* (curated demo deliberately runs one job) — not a *picker*. That's CR-033's territory.

### What shipped (Phase 1 — 2026-05-26)

**`sources.py` rewrite.** New top-level `SOURCES` list — parent-grouped, with `{id, name, credit, license, vignette, variants: [...]}` per parent. Each variant carries `{key, label, description, length, path}`. The `vignette` field on the parent is plumbed but unused by the UI today (hook for CR-046 Phase 2). New accessors:
- `get_variant(key)` / `get_parent_for(key)` — direct lookups.
- `get_grouped_sources()` — parent-grouped list with full per-variant ffprobe info, the schema the picker speaks.
- `get_source_info()` / `get_all_sources()` / `PRELOADED` — preserved exactly as pre-CR-047 callers expect. `PRELOADED` is now a derived view over `SOURCES` (built at module load).

The per-variant info dict gained `variant_label` (short form, "2 min extract"), `parent` (id), `parent_name`, and `length` (`"full"` or `"extract"`). The legacy `label` keeps the parent-prefixed form ("Big Buck Bunny 4K — 2 min extract") so the queue label string and any historical JSON consumer stay valid.

**`main.py` picker.** Added `_video_source_picker_html()` helper that renders the entire grouped radio block from `get_grouped_sources()` — small dim parent header ("Big Buck Bunny 4K · CC BY 3.0") then variants underneath as radios in the same density / border style as the upload row. The hardcoded radio block in `video_page()`'s f-string template was replaced with a single `{source_picker_html}` interpolation. Same selectors / `selectSource(key)` JS contract → no client-side changes needed.

**Tests.** New `tests/test_sources.py`, 18 tests pinning both the new schema shape and the back-compat surface: PRELOADED has every variant key, legacy field names preserved, `get_all_sources()` order unchanged (`gos_in_50s, meridian_120s, meridian_4k, bbb_120s, bbb_4k`), `get_grouped_sources()` returns the expected three-parent structure with variant dicts shape-equivalent to `get_source_info()`. 272 → **290 passing**.

Render verified end-to-end via `TestClient` — parent headers ("GoS promo", "Meridian 4K · CC BY 4.0", "Big Buck Bunny 4K · CC BY 3.0") appear in order; all five variant radios resolve with their value attributes intact; the variant labels use the short form ("2 min extract") in the row, with the parent name in the header.

### Deferred to follow-ups

- **Vignette UI.** The parent `vignette` field exists; rendering still images / thumbnails in the picker is its own polish pass. Becomes load-bearing when CR-046 Phase 2 (FOKUS-scene vignette) ships. Owner deferred the collapsible-picker UI to "after this is all working" — same pass.
- **Source identifier on result JSON.** `result["source"] = {key, parent}` would let historical results stay filterable as the variant schema evolves further. Cheap, additive — capture as a Track A storage follow-up once that track moves.
- **Result-card parent+variant framing.** The renderers still surface the legacy `label` (parent-prefixed). When result cards get the next polish pass, splitting parent vs variant into a two-row title block is straightforward — but not required for CR-047 itself.

### Cross-references

- **CR-046** Phase 2 (FOKUS vignette) — direct downstream; the vignette field on the `bbb` parent is now ready to receive a still image taken from the FOKUS-matched frame.
- **CR-033** (curated demo video job selection) — secondary beneficiary: `/demo` step 1's chip-row can now resolve to a variant key when implemented.
- **docs/input_sensitivity_findings.md** — empirical justification for the 3-slot matrix (length-axis only).

---

## CR-046 · Big Buck Bunny preloaded for FOKUS Berlin demo

**Status:** Shipped 2026-05-27 (S30). Phase 1 (4K master + 2-min extract, 2026-05-26) + a generic `bbb.jpg` vignette (BBB at t=180 s, 2026-05-26 alongside Meridian + GoS thumbnails). The originally-sketched "FOKUS-matched vignette" Phase 2 was explored and dropped: the FOKUS event header is a *modified* BBB still (added laser-eye effects), so a literal frame-match isn't possible, and the generic BBB vignette already satisfies the underlying picker-friendliness goal.
**Triggered by:** owner, 2026-05-26 — Fraunhofer FOKUS Media Web Symposium 2026 (Berlin) uses a Big Buck Bunny scene in their promo material. Having BBB preselectable on `/video` lets the OWL demo at the event use the same source the audience already associates with FOKUS.

### Problem / opportunity

OWL's preloaded test content was Meridian (Netflix Open Content) + the in-house GoS-in-50s promo. Both useful but neither lands the "this is the clip you've been looking at all morning" reaction at the FOKUS booth. BBB is the canonical Blender Foundation demo asset, CC BY 3.0, and what FOKUS picked for their event branding — running the live energy comparison on it closes the loop visually for the visitor.

### What shipped

- **Full 4K master** — 60 fps H.264 from archive.org (`big-buck-bunny-4k-60fps/BigBuckBunny4k60fps.mp4`, 642 MB) at `/srv/data/owl/test_content/bbb_4k.mp4`. Sibling to Meridian 4K's 59.94 fps so cross-source comparison stays apples-to-apples.
- **2-min extract** — stream-copy of the first 120 s (`bbb_120s.mp4`, 102 MB) for the fast-demo slot, mirroring `meridian_120s`. Created via `ffmpeg-master -i bbb_4k.mp4 -t 120 -c copy …`.
- Both variants live under the `bbb` parent in `sources.py` (CR-047 schema). Picker renders them grouped under "Big Buck Bunny 4K · CC BY 3.0".
- **Generic vignette** — `wattlab_service/static/source_vignettes/bbb.jpg` (t=180 s, ~3 KB) wired into the `bbb` parent. Rendered by `_video_source_picker_html()` as a 32 px-high thumbnail left of the parent header. (Same pass added `gos.jpg` t=25 s + `meridian.jpg` t=60 s for the other two parents.)

### FOKUS-matched-frame investigation (closed-as-not-needed)

A dHash perceptual-hash matcher (PIL-only, no external dep) was built to find the BBB frame closest to the FOKUS event header still:
<https://www.fokus.fraunhofer.de/en/fame/events/mws26/jcr:content/stage/stageParsys/stage_slide/image.img.png/1764765211663/FAME-FOKUSMWS-2026-Header-2100x700.png>

Sampling every 2 s across the 634 s master gave a best Hamming distance of 18/64 (top 3: t=136 s, t=146 s, t=216 s). The match was visibly weak. Visual side-by-side confirmed why: the FOKUS image has been **post-processed with added laser-eye effects on BBB** — it isn't a literal frame at all, just a stylised header with a BBB scene as the base. So no automatic match is meaningful and a literal frame-extract would only approximately resemble the FOKUS header.

Decision: drop the FOKUS-match angle, keep the generic `bbb.jpg`. The picker's identifying-thumbnail goal is satisfied without coupling to FOKUS's stylised header.

If a FOKUS-keyed visual ever becomes load-bearing (e.g. a literal "this is what you saw at the entrance" callout next to the BBB radio), the natural path is a hand-curated lookalike frame, not an algorithmic match. Capture as a new CR at that point.

### Cross-references

- **CR-047** (variants schema, shipped same day) — the `vignette` field on the parent dict that bbb.jpg uses.
- **docs/input_sensitivity_findings.md** — the parallel measurement work justifying the 2-variant picker shape.

---

## CR-033 · Curated demo video job selection (1–2 options)

**Status:** Shipped 2026-05-27 (S30) — codec chip-row on `/demo` step 1, H.265 default, AV1 alternate, both on `meridian_120s`. Captured 2026-05-08 (S23).
**Triggered by:** owner observation during anonymous-tier testing — `/demo` step 1's video job was hardcoded to `source=meridian_4k` + `preset=both` (full 12-minute Meridian + H.264 CPU+GPU compare = ~10–15 min wall time). For the guided tour that's a flow-breaker: visitors can't realistically wait that long, and the result card lands long after the demo session is fresh in their head. Quick-fix in S23 changed it to `source=meridian_120s` + `preset=h265_both` (~2–3 min, shows GPU advantage cleanly). CR-033 was the curated-options follow-up.

### Problem

A single hardcoded demo job was a UX compromise: the guided tour either picked one codec family (H.265) and silently skipped the others, or grew toward the long-job problem the S23 quick-fix had retired. Visitors who care about codec-family comparisons (H.264 vs H.265 vs AV1 — exactly the population to hook for membership) got less information than the canonical Key Findings table on the methodology page.

### What shipped

A two-chip row above the run button on `/demo` step 1:

1. **H.265 (CPU vs GPU)** — default. Maps to `source=meridian_120s` + `preset=h265_both`.
2. **AV1 (CPU vs GPU)** — alternate. Maps to `source=meridian_120s` + `preset=av1_both`.

Implementation:
- HTML: two `<button class="demo-chip" data-codec="…">` elements with inline styles so /demo's existing CSS scope doesn't need a new class (lab look & feel — inline ok at this surface size).
- JS: `selectedDemoCodec` state variable (default `'h265'`) + `selectDemoCodec(codec)` updates the chip styling + the run-button label. `runDemoVideo()` reads it and posts the right `preset` to `/video/use-source`. Source key stays `meridian_120s` regardless of codec choice (consistent fast-demo timing).
- Result-card rendering needed zero changes — both `h265_both` and `av1_both` share the codec-agnostic `renderBoth` path.

Out of scope (deferred): AV1 GPU vs H.265 GPU side-by-side, all_codecs sweep on `/demo`, custom source selection. Those are CR-029 / CR-031 territory.

### Open question resolved

- **Default selection** → H.265 (safer, more familiar codec to most operators). AV1 sits behind the chip-click; visitors who notice the chip find the better story underneath.
- **Chip persistence** → reset on each load (demo is a fresh first-impression each time, no localStorage).

### Lab look & feel

Two chips inline above the run button; no decorative animation, no extra row of explanatory copy. Selected state = filled accent background; deselected = transparent + dim text. Matches the visual vocabulary of the `/video` preset chips without sharing their selected-state logic (which is /video-specific).

---

## CR-048 · /llm compare-across-models · energy per correct answer

**Status:** Shipped 2026-05-26 (Session 30, parallel session) — new page `/llm/compare`, new endpoint `POST /llm/compare-models` (BATCH_COMPARE gated), grader helper in `llm.py`. Cooldown + noise UX hardened in Session 31 alongside CR-050 (active-probe thermal floor + 🔴 filtering + N-way size-vs-energy charts).
**Triggered by:** owner, 2026-05-26 — *"make these LLM/RAG stuff more relevant to GoS by focussing on measurable energy aspects. The UI must be designed for that to stand out."*

### Problem

Existing `/llm` reports energy per inference and surfaces **mWh per output token** as the headline. That's a process metric and it actively misleads: a model that "thinks out loud" for 100 tokens to reach a 1-token answer looks more efficient per token than a model that answers in 1 token, even though it burned 100× the energy. For a GoS-framed efficiency story the right axis is the **energy cost of getting the right answer**, not the energy cost of producing more text. The existing page also runs only one model per session, so visitors never see the cross-model comparison that makes the energy story land.

### What shipped

New `/llm/compare` page implementing the hybrid showcase + member-only "Try your own" pattern:

1. **Anonymous showcase (3 demo cards).** Tab between three prompts picked by a 2026-05-26 probe (5 models × 8 candidate prompts × 3 reps, `/tmp/llm_probe/results_20260526_174852.jsonl`): Strawberry (the meme; "R's in strawberry?" — size ≠ smarts), Logic (Carol; clean Type 1), Addition (50; arithmetic ceiling test).
2. **Member "Try your own"** (BATCH_COMPARE gated). Prompt textarea + expected-answer text field + one button. Runs the prompt sequentially across every model in `llm.MODELS` (now 7 per CR-050) on GPU with a clean P110 baseline before each model. Graded with a tolerant substring + leading-integer rule (also punctuation-stripped retry). Result rendered into the same comparison card as the showcase.

- `llm.py`: added `grade()` helper (tolerant: substring or leading-integer, case-insensitive; punctuation-stripped retry for list-style answers).
- `main.py`: added `run_llm_compare_models_job`, `POST /llm/compare-models` endpoint, `GET /llm/compare` page, "NEW" banner on `/llm`. Result `mode: "compare_models"` joins the standard results stream → CSV/JSON export + carbon enrichment for free.
- Headline = **Wh per correct answer**. mWh/token stays in the table as a supporting column because the perverse incentive of optimising for it is visible right next to total Wh (the verbose-but-low-mWh/tok inversion).
- "Cheapest correct" winner highlighted with `--accent-soft` + ⭐. Bust card fires the "smaller model right, bigger model wrong" narrative when present; falls back to "same answer, N× more energy" otherwise.
- Side-by-side charts (Wh vs params, mWh/tok vs params) gated at ≥3 trusted-correct rows.
- 🔴 rows greyed in the table but excluded from cheapest pick, bust card, and chart (CR-050 follow-up).

### Phase 2 — open work (after Session 31 backfill, only #3 remains)

1. ✅ **P110 backfill of the showcase cards** — done Session 31. Hardcoded `_LLM_COMPARE_SHOWCASE` now carries real P110 measurements on the post-CR-050 7-model panel.
2. ✅ **Mirror for `/rag`** — done CR-049 (Session 30).
3. **Aggregate "Findings" surface.** Showcase tabs should pull from a small library of stored canonical results rather than a hardcoded constant, so adding a new showcase prompt is a one-run-of-the-feature operation, not a code edit. Deferred.

### Lab look & feel constraint

Same monospace + `--accent` palette as the rest of OWL; no decorative animation. Showcase tabs are buttons; methodology is in a `<details>` fold-down; opinionated visual elements are the green winner-row + ⭐ and the warn-coloured bust card.

---

## CR-049 · /rag compare-across-models · energy per correct answer (sibling of CR-048)

**Status:** Shipped 2026-05-26 (Session 30, parallel session) — new page `/rag/compare`, new endpoint `POST /rag/compare-models` (BATCH_COMPARE gated), uses the existing `run_rag_measurement` per-model primitive. Showcase P110 backfilled Session 31.
**Triggered by:** owner, 2026-05-26 — *"implement the /rag energy-first demo page with the bbc data as dry run."*

### Problem

Existing `/rag` runs one model in one mode at a time. To make the RAG energy story land for a GoS audience, the page needs the same cross-model comparison shape that CR-048 added for `/llm`: one corpus-grounded question, ranked by energy of the *correct* answer across the panel. The RAG twist is that "wrong" can mean two different things — the model was wrong, or retrieval gave it the wrong chunks — and the energy data makes the cost of bad retrieval visible (you can burn Wh generating wrong answers from off-target chunks).

### Showcase data — sourced from a real probe

A 2026-05-26 prompt-selection probe (`/tmp/rag_probe/results_20260526_223406.jsonl`) ran 3 corpus-grounded prompts × 4 models × 1 mode (rag, top-3 retrieval) through the production `/rag/run` endpoint. Real P110 measurement, ~5 min wall. Only one prompt passed all four models:

- **BBC Radio 2018 energy total** ("325 GWh") — 4/4 ✓. Energy spread TinyLlama 0.003 Wh → Gemma3 0.443 Wh, ~143× for the same correct answer.

The two IEA prompts (415 TWh / 945 TWh) failed across the panel for a retrieval reason: top-3 retrieval correctly surfaced the 250-page IEA report but missed the page containing the headline numbers. Kept in the probe data as a deliberately negative example for a future "retrieval-precision matters" demo, but not a clean showcase.

### What shipped

- `rag.py`: added `COMPARE_PROMPTS` registry (BBC only initially; expanded Session 31 backfill).
- `main.py`: added `run_rag_compare_models_job` (sequential N-model loop with active-probe thermal-floor cooldown between models, same as /llm/compare), `POST /rag/compare-models` endpoint, `GET /rag/compare` page, 1-line "NEW" banner on `/rag`. Grading reuses `llm_grade`. Result `mode: "rag_compare_models"` joins the standard results stream.
- Showcase row Wh comes from the probe's real P110 measurements via a `wh_measured` parallel array, so showcase doesn't have to fall back to the `wall_s × 25 W` estimate /llm/compare's showcase originally used.
- Same charts and bust-card semantics as /llm/compare. The bust card has a RAG-specific tagline: when a bigger model is wrong and a smaller one is right, that often means the smaller model trusted the retrieved chunk while the larger one hallucinated past it.

### Phase 2 — open work (after Session 31 backfill, #1 remains)

1. **Document upload to corpus.** Page surfaces a one-paragraph "ask the GoS team" note in the "Try your own" section. Real upload needs: `POST /rag/upload` endpoint, file validation (PDF only, size cap, no executables), append to `corpus/papers/`, trigger `build-index`. Adds a publicly-reachable file upload — a real security surface. Estimated 250 lines + a careful hardening pass.
2. ✅ **More showcase prompts** — addressed Session 31 backfill (more candidate prompts re-probed on the 7-model panel).
3. **Retrieval inspection.** The compare card shows the model's answer but not which chunks retrieval picked. Surfacing the top-3 chunk sources per row would make the "wrong because of bad retrieval" story explicit. Cheap addition (data is already in the result JSON via `chunk_sources`).

### Lab look & feel constraint

Page mirrors `/llm/compare` styling exactly. Upload note is a dashed-border block (not solid) to signal "not interactive yet" without screaming.

---

## CR-051 · RAG corpus self-service: Member upload + delete, manifest + audit

**Status:** Shipped 2026-05-27 (Session 32). New `corpus_manifest.py` module + `POST /rag/upload` + `DELETE /rag/doc/{filename}` + `GET /rag/audit` (Lab) + UI on `/rag` corpus browser. New `RAG_CORPUS_DELETE_OWN` capability (Member). 15 new tests in `tests/test_corpus_manifest.py`. Existing 101 PDFs migrated to `origin=Lab` via `corpus_manifest.migrate_existing_corpus()`.
**Triggered by:** owner, 2026-05-27 — *"I want to implement the possibility to add documets to the corpus."*

### Problem

Phase 2 #1 carry-over from CR-049: the `/rag` corpus was seeded once and only growable by dropping PDFs into `corpus/papers/` on the server, then triggering `/rag/build-index`. No tiered self-service; no audit trail; no way for a Member to contribute (or to undo a contribution). Owner explicitly raised the trust/audit angle — *"to protect against any (unlikely) bad intentions, we need to be able to remove documents too, but also track when a doc was added and who by."*

### Agreed tier model

- **Anonymous:** read-only view of the corpus list (origin tag visible, uploader email **not** shown — aggregate label only, "Member" or "Lab", protects member privacy).
- **Member (RAG_CORPUS_UPLOAD + RAG_CORPUS_DELETE_OWN):** upload PDFs; delete their own uploads; cannot delete Lab-origin docs.
- **Lab:** all of the above, plus delete any doc and read the audit log.
- **Delete semantics:** hard delete (file unlinked, ChromaDB chunks dropped, manifest entry removed). The append-only audit log preserves the upload/delete history.
- **Existing 101 PDFs:** migrated as `origin=Lab` via a one-shot `migrate_existing_corpus()` call from the manifest module. Self-healing for any PDF added out-of-band: `ensure_entry()` stamps it as Lab using the file's mtime.

### What shipped

**`corpus_manifest.py`** (new) — single source of truth:
- `corpus/manifest.json` keyed by filename, each entry `{origin, added_by, added_at, size_bytes, title}`.
- `corpus/audit.log` append-only NDJSON, one event per add/delete.
- `can_delete(filename, tier, email)` — the tier × ownership matrix in one place. 15 tests pin it.
- `sanitise_filename()` strips path components, restricts to `[A-Za-z0-9._-]`, ensures `.pdf`. Defends against `../../etc/passwd` style attempts even if the upload endpoint trusts Content-Disposition.
- `unique_filename()` auto-suffixes `-2`, `-3`, … on collision so an upload can never silently overwrite an existing doc.
- `member_usage(email)` → `{file_count, total_bytes}` for quota enforcement.
- `migrate_existing_corpus()` idempotent one-shot to seed manifest entries for the existing 101 PDFs.

**`rag.py`** — incremental index helpers (no more full rebuild per upload):
- `add_doc_to_index(filename)` — load one PDF, chunk, embed, `collection.add()` with globally-unique ids (`<filename>#<i>`). ~3–8 s per typical doc.
- `remove_doc_from_index(filename)` — `collection.delete(where={"source": filename})`. Idempotent.

**`main.py`** — endpoints + UI:
- `GET /rag/corpus-list` enriched with origin, added_at, per-row `can_delete`, member usage counters, caps.
- `POST /rag/upload` (RAG_CORPUS_UPLOAD-gated): size cap, %PDF-magic-byte sniff, per-Member quota, sanitised + unique filename, manifest record, incremental index, audit log.
- `DELETE /rag/doc/{filename:path}` (RAG_CORPUS_DELETE_OWN-gated, in-handler ownership check): defensive basename + traversal guards, unlink file, drop chunks, audit log.
- `GET /rag/audit` (SETTINGS_READ_FULL = Lab) returns last 200 events.
- `/rag` page corpus browser: per-row origin chip (green Member / muted Lab), added-on date, `×` delete button (only shown when `can_delete`), upload form (Member-only, with live quota display) above the list. Member-uploaded docs sort to the top so users find their own first.

**`settings.json`** — three new caps (Lab uncapped):
- `rag_upload_max_mb`: 50 (per-file)
- `rag_member_doc_count_cap`: 10 (per Member email)
- `rag_member_total_mb_cap`: 200 (per Member email)

**`capabilities.py`** — new `RAG_CORPUS_DELETE_OWN` (Tier.Member). Snapshot test updated.

### Hardening notes (worth re-reviewing if the public URL is ever opened beyond OWL_AUTH_SECRET-gated access)

1. **Path traversal** — sanitise_filename + os.basename + traversal-guard in the DELETE handler. Test pinned.
2. **Magic bytes** — first 5 bytes must be `%PDF-`; renamed-binary attempts rejected at the gateway.
3. **Size cap** — per-file enforced before write (50 MB default).
4. **Per-Member quota** — 10 files / 200 MB total per Member email. Lab uncapped.
5. **Filename collision** — auto-suffix `-2`, `-3`. Never overwrites.
6. **No executable indexing** — pypdf is the parser; we never `exec` content. The largest residual risk is a malicious PDF exploiting pypdf or ChromaDB parsers — both are widely-used libs but worth tracking for CVEs.

### Phase 2 — open work

1. **Optional title field on upload.** Manifest already has the slot; UI just doesn't expose it yet. Cheap.
2. **Lab audit-log viewer page.** Endpoint exists (`/rag/audit`); no UI. A small `/rag/audit` page rendering the events as a table is a half-hour add.
3. **Background re-index on disk drift.** Today `ensure_entry()` self-heals manifest gaps for out-of-band file drops, but the chunks aren't auto-added until someone hits `/rag/build-index`. A periodic check that compares disk contents to ChromaDB sources and incrementally adds the missing ones would close the loop.

### Lab look & feel constraint

Corpus browser sits inside the existing `<details>` block; no new top-level surface. Origin chip is one of two colours (green = Member, muted = Lab), 0.65 rem font, single-line per row. Delete button is a tiny `×` — only renders for rows the visitor can act on, so visitors don't see clickable targets they're not authorised for. Upload form sits behind a dashed border above the list (signals "not the main content, but here when you want it").

---

## CR-050 · Dynamic model catalog · adding / removing a model is no longer a code change

**Status:** Shipped 2026-05-27 (Session 31). New `model_catalog.py` module; LLM/RAG/Image `MODELS` dicts replaced with live views; Models section added to `/settings`. Subsequent follow-ups (active-probe thermal floor, Ollama keep_alive eviction, asymmetric settle, ±3 W tolerance, 4 Hz UI ticker, N-way `/image/compare`) all landed under this CR.
**Triggered by:** owner, 2026-05-27 — *"Moving forward, removing or adding a model must be a simple process, not requiring code changes."*

### Problem

Every surface kept its own hand-maintained `MODELS` dict (`llm.MODELS`, `rag.MODELS`, `image_gen.IMAGE_MODELS`). Each update meant a code edit + service restart, and the dicts drifted apart — `/llm` and `/rag` had 5 models but `/llm/compare-models` hardcoded a 5-model panel referencing keys (`mistral`, `gemma3:12b`) that had been removed; `/image` was missing two models present in the HF cache. Stale state was a recurring source of bugs.

### What shipped

**Single source of truth.** New `model_catalog.py` auto-discovers what's installed:

- `available_llm_models()` shells `ollama list`, parses, filters image-only entries (`x/flux*`, `x/z-image*`), normalises keys (`phi4:latest` → `phi4`), sorts by parsed parameter count ascending (so `/llm` selector cards + `/llm/compare` panel + charts all read 1.1B → 1.7B → 4B → 8B → 12B → 14B → 20B by default). 60 s cache.
- `available_image_models()` scans `~/.cache/huggingface/hub/`, mapping known families (sd-turbo, sdxl-turbo, sdxl-lightning, sana-600m) to full operational metadata; unknown families get safe defaults. Slugs are kept short (`sd-turbo`, not `stabilityai/sd-turbo`) for backwards-compat. 60 s cache.
- Per-surface enable lists live in `settings.json` as `llm_enabled_models` / `rag_enabled_models` / `image_enabled_models`. Empty list / absent key = "all available enabled" so a fresh server with no settings file works out of the box.
- `llm.MODELS`, `rag.MODELS`, `image_gen.IMAGE_MODELS` are now thin `_ModelsView` classes that proxy `__getitem__` / `keys()` / `items()` / etc to `model_catalog.enabled_*_models()`. Drop-in interface; every existing caller works unchanged.

**Settings UI.** New "Models (CR-050)" section on `/settings`. Three checkbox panels (LLM, RAG, Image), each model row showing label, params, size, and the monospace key. Save (Lab tier) writes the enabled lists and calls `model_catalog.refresh_all()` so changes are visible on the next render. Anonymous viewers see the panels read-only.

To add a new LLM: `ollama pull <name>` on the server, reload `/settings`, tick the new entry. No code edits, no restart.

**Active-probe thermal floor wait (replaces the fixed `llm_rest_s` sleep between models).** New `power.wait_for_thermal_floor(reference_w, tolerance_w=3.0, poll_interval_s=1.0, settle_polls=3, max_wait_s=120)`. Called between every pair of models in `/llm/compare`, `/rag/compare`, and `/image/compare`. Reference = first model's baseline (captured cold, after explicit VRAM eviction). The asymmetric settle condition (`w ≤ reference + tolerance`) treats "at or below floor" as goal-achieved — there's no reason to wait for power to climb *back up* to a match if the system has continued cooling.

**Ollama keep_alive eviction.** Original symptom: 7-model compare runs showed baselines climbing from ~60 W to 130 W mid-run because Ollama's default 5-minute `keep_alive` kept every previously-run model resident in VRAM (~60 W of permanent draw per resident model). New `llm.unload_all_loaded_models()` queries `/api/ps` and sends `keep_alive=0` to every resident model. Called at the start of every compare run (to clear pre-existing VRAM from prior `/llm` interactive use) and between every pair of models (so the thermal-floor wait can actually reach the cold reference).

**🔴 noise handling.** `cheapest_correct` pick, the bust card, the "vs best" ratio column, and the size-vs-energy charts all now filter out 🔴 rows (CR-028 confidence flag). 🔴 rows still appear in the comparison table greyed + italic — visible but explicitly disregarded for rankings. Confidence column added to the table.

**Size-vs-energy charts.** Side-by-side line charts (Wh vs params, mWh/tok vs params) under the headline on both `/llm/compare` and `/rag/compare`, gated at ≥3 trusted-correct rows. Uses the existing `WlCharts.line` helper.

**N-way `/image/compare`.** `run_image_compare_models_measurement` no longer hardcodes SD-Turbo + SDXL-Turbo — iterates every enabled image model with the same thermal-floor cooldown. Result returns a `models` list (with `small`/`large` legacy aliases set to cheapest/priciest by Wh/image, so old prev-runs rendering still works). The compare button is enabled whenever ≥2 image models are ticked; label says *"Compare all N models (GPU) ⚡"*. Page-side: `STAGE_LABELS` + `COMPARE_STAGES` are now built server-side from `IMAGE_MODELS.items()` and injected; `wlRenderImageCard` compare branch iterates `r.models` — N image columns, N KPI cards, N confidence flags.

**UI cooldown ticker.** 4 Hz local ticker in the compare-page JS interpolates `cooldown_waited_s` between server polls (server polls P110 every 1 s; UI polls `/job/{id}` every 2 s), so the displayed wait counter advances smoothly. Resets on each server update; stops on done / error / new run.

### Backwards-compat notes

- Ollama returns `phi4:latest` and `tinyllama:latest`; the catalog strips `:latest` so existing code paths using bare `phi4` / `tinyllama` keep working. Tags that *encode* a variant (`qwen3:1.7b`, `gpt-oss:20b`) are preserved.
- Image keys are short slugs so existing image code paths and stored result JSONs stay valid. The full HF repo string lives in the `repo` field.
- Result schemas: `compare_models` and `rag_compare_models` results gain `floor_reference_w` + `cooldowns` (list of per-gap diagnostics: `waited_s`, `settled`, `final_w`, `evicted_before_wait`); image `compare_models` results gain `models` list alongside legacy `small`/`large`.

### Phase 2 — open work

1. **`ollama pull` from the Models panel.** Right now the panel only enables/disables what's already installed. A "+ Add model" affordance that runs `ollama pull <name>` (async, with progress) would close the loop entirely — the catalog would then auto-discover the new entry. Adds a backend endpoint + capability + progress UX.
2. **Image-model defaults editor.** Unknown image families get safe defaults that may not match the model. A small "edit defaults" expander per image model (steps, native_px, cpu_ok, batch sizes) writes to an `image_overrides.json` the catalog merges in.
3. **N-way image compare progress UX polish.** Current cooldown stage uses a single `cooldown` key in `COMPARE_STAGES`; the progress dot strip shows it indexed at the first occurrence, so subsequent cooldowns map to the same dot. The status text (`Model N/T · cooldown · waiting Xs for floor`) shows the right thing — only the dot strip cosmetic. Distinct `cooldown_after_m1` / `cooldown_after_m2` stage keys would fix.

### Lab look & feel constraint

Models section sits at the bottom of `/settings` next to Tier limits, same vertical layout as the rest of the page. Checkbox rows are compact (single line per model: tick + label + meta + monospace key). No decorative animation; muted secondary colour for auto-discovered metadata.

---

## CR-054 · Findings catalog — data model + one worked example

**Status:** **shipped behind `findings_enabled` flag 2026-05-27 (S32 evening).** Code on `main`; route `/findings/av1-hw-sw-vmaf-tradeoff` reachable by direct URL. **One discreet beta link added on `/video`** (owner approval same session, 2026-05-27) — `[beta] Some initial findings: AV1 hardware vs software — the energy↔quality tradeoff →`, gated on the same `findings_enabled` flag. Other surfaces (`/llm`, `/image`, `/rag`, `/`) still nav-silent. Awaiting lab-colleague review before broader nav promotion / CR-055 catalog. **Tests:** 315 → 324 (+9). **Rollback:** set `findings_enabled: false` in `settings.json` — one bool flip removes both the route AND the `/video` beta link.
**Triggered by:** Owner observation that the vast majority of visitors browse OWL without ever running a measurement, combined with the S32 architecture audit which established that the existing live-run renderers (`wlRenderVideoCard` / `wlRenderLLMCard` / `wlRenderImageCard` / `wlRenderRAGCard`) are already JSON-pure and shared between live and past results.

**Lab look & feel constraint:** the finding page is a *publication*, not a marketing landing — same dark palette, same monospace numerics, same density as a fresh result card. Citation block is one small monospace box. No hero imagery, no decorative animation. The embedded measurement uses the unmodified existing renderer.

### Problem

OWL produces credible measurements but exposes them as workbench surfaces (run-a-thing pages) rather than citable artefacts. Key Findings live in CLAUDE.md prose and as scattered showcase rows on bench pages; the audience (CTOs / operators / policymakers) can't deep-link to a finding, can't quote it stably in a board deck or RFP, and can't verify the underlying measurement at the same fidelity as a live run.

The S32 audit established that the rendering substrate is already capable: the four live-run renderer functions are JSON-pure, already used for both live and past results via the `expand-row` UI on `/results/{type}/list`, and identical-shape input (`{result, isPrev, savedAt}`) produces identical-fidelity output. The gap is curation + presentation, not rendering.

Strategic framing (S32 thread): an Anonymous visitor reading a finding card and quoting its number in a Slack thread is *exactly* what GoS wants from OWL — the credibility flywheel + the member-recruitment loss-leader. Running a job is bonus, not core. Today the UX inverts this: workbench front and centre, findings buried.

### Agreed direction

Ship the smallest end-to-end slice that proves the pattern: **one finding, fully rendered at live-run fidelity, with a stable URL and a copy-paste citation block.**

#### Scope (in)

1. **Finding data model** — markdown-with-frontmatter at `docs/findings/<slug>.md`. Frontmatter holds structured fields; body holds analysis prose. Chosen over pure YAML because `docs/` already uses markdown and the analysis prose has a place to live next to the structured data.
2. **Loader module** — `wattlab_service/findings.py` (flat, alongside `sources.py` / `curated.py`): `load(slug) -> Finding`, `list_all() -> list[Finding]`, `validate(finding)`. In-memory cache after first load.
3. **One generic page renderer** — `GET /findings/<slug>`: loads a finding, renders one common page layout. **Same template for every finding, forever** — adding a finding never adds Python.
4. **One worked example** — `docs/findings/av1-hw-sw-vmaf-tradeoff.md`, backed by result `video/2026-05-22_e18a9d57.json` (the S28 CR-044 finding ⭐ already in CLAUDE.md).
5. **Citation block** — copy-paste citation rendered on every finding page; contains stable URL + `first_measured` + `last_refined` dates. One small monospace box, lab-look-preserving.
6. **Source-measurement embed** — the finding page calls the existing renderer (`wlRenderVideoCard({result, isPrev: true, savedAt})`) against the linked result JSON. Visitor sees the underlying measurement at live-run fidelity, no fork.

#### Data model (frontmatter contract)

```yaml
---
slug: av1-hw-sw-vmaf-tradeoff
version: 1
first_measured: 2026-05-22
last_refined: 2026-05-22
headline: "AV1 hardware uses ~55% less energy than software at 1500 kbps, but loses ~2 VMAF and produces ~40% larger files"
claim_short: "1500 kbps ABR — SVT-AV1: 0.71 Wh / VMAF 92.74 / 14.5 MB · av1_vaapi: 0.32 Wh / VMAF 90.79 / 20.3 MB"
confidence: green                       # green | yellow | red
scope: "Device layer only (GoS1). Network, CDN, and CPE excluded."
methodology_ref: docs/wattlab_traffic_light_confidence.md
source_result_ids:
  - video/2026-05-22_e18a9d57
related_findings: []
supersedes: null
tags: [video, av1, vmaf, hw-vs-sw, cr-044]
caveats:
  - "Cross-codec VMAF is NOT apples-to-apples (different per-codec bitrate targets); only the within-AV1 CPU-vs-GPU comparison at 1500 kbps is a fair quality read."
  - "Tiny clips (≤~4 s) are unreliable for this — flag 🔴."
---

# Free-form analysis prose below the frontmatter…
```

#### Maintainability invariants (this CR's contract for future work)

These hold for every future findings-related CR. The owner's explicit concern (2026-05-27): *don't let UI churn weaken the codebase.* These are the locks.

1. **One renderer for all finding pages.** A single `_render_finding_page(finding)`. Never per-finding HTML. New finding = new `.md` file, never new Python.
2. **One loader.** `findings.load(slug)` is the only path. Cached in-memory. No ad-hoc parsing elsewhere.
3. **Validate-on-load with clear errors.** Schema mismatch → loud failure naming file + offending field. Broken `source_result_ids` → same.
4. **`source_result_ids` always exist on disk.** Enforced by test; a finding with a dangling reference cannot ship.
5. **Findings are editorial markdown, not code.** Adding / refining a finding requires zero Python changes. Editors don't touch code; code reviewers don't gate editorial content.
6. **Reuse existing measurement renderers verbatim.** The finding page embeds `wlRenderVideoCard` / `wlRenderLLMCard` / etc. unmodified. No fork, no parallel rendering path.
7. **No new persistence layer.** Findings live in version-controlled markdown alongside `docs/`. Git is the audit log.
8. **No new JS framework, build step, or template engine.** Server-side render + existing JS renderer invocation, same pattern as the rest of OWL.
9. **`supersedes` is the versioning primitive.** Refinement = new finding file with new slug + `supersedes: <old-slug>`. Old finding stays citable, marked superseded on render. No URL trickery in v1; defer the `@date` pin URL form.
10. **Page layout is locked in this CR.** Future CRs can extend the data model with optional fields, but the page layout (sections, order, citation block placement) does not churn per-finding. Layout redesign = one CR touching one renderer, affecting all findings consistently.

#### Test plan (~+5 tests, 307 → 312)

- `test_findings_schema.py` — parses the AV1 example, asserts required fields, `confidence ∈ {green, yellow, red}`, dates parse.
- `test_findings_references.py` — for every `docs/findings/*.md`, every `source_result_id` resolves to a file in `results/`.
- `test_findings_route.py` — `GET /findings/av1-hw-sw-vmaf-tradeoff` → 200, body contains headline + claim_short + citation block + scope + embedded measurement card.
- `test_findings_404.py` — `GET /findings/<nonexistent>` → 404.
- `test_findings_citation.py` — citation block contains stable URL, `first_measured`, `last_refined` — well-formed for copy-paste into a board deck.

#### Why this won't weaken the codebase

- **Net code:** small — ~150 lines for loader + renderer + route, ~80 lines for tests. The bulk of future "catalog growth" is editorial markdown, not Python.
- **No new patterns introduced.** Uses existing FastAPI routing, existing string templating, existing shared JS renderers, existing flat-file storage convention.
- **Single point of change.** Layout in one template; schema in one validator. UI churn is bounded to those two files, not spread across handlers.
- **Hardens editorial-vs-code separation** — strengthens, doesn't weaken, separation of concerns.
- **Defers everything that would weaken it.** Home repositioning, catalog UI, versioning URL form, guided tour rewire — each is a separate CR with its own scope review.

#### Out of scope (explicitly deferred — each is a follow-up CR)

- `/findings` index/catalog page → **CR-055**
- Bulk import of existing Key Findings from CLAUDE.md → **CR-056** (editorial, after pattern proven by CR-054)
- Versioning URL pin (`/findings/<slug>@<date>`) → defer; v1 uses `supersedes` which is enough for honest revisioning
- Home page repositioning to findings-first → **CR-057** (UX design needed; depends on CR-055)
- Guided tour terminus rewire (long-deferred — see CLAUDE.md "Guided Tour Findings step") → **CR-058** (depends on CR-055)
- Social share buttons / OG meta tags → **CR-059**
- "Verify the bench" sanity-check run (Anonymous-tier trust gesture from the S32 thread) → separate CR (not findings-coupled)
- Member-tier "methodology deep-dive" expanders → separate

### Ship criteria

- Tests pass (307 → 312)
- AV1 finding page renders with the embedded video result card identical to what a fresh `/video/all-codecs` run on Meridian-120s produces
- Citation block copy-pastes cleanly into Slack / a Google Doc / a board slide
- One internal review confirms the page reads as a credible publication, not as a UI tab

### Rollback path (lab-colleague-disapproval insurance)

The whole feature lands behind a single setting; rolling back is one boolean flip, not a code revert.

1. **Feature flag.** `settings.json` gains `findings_enabled: true` (default). The `GET /findings/<slug>` route checks the flag at request time; when `false`, returns 404 (route is undiscoverable). One-line flip via `/settings` UI or direct JSON edit.
2. **No nav promotion in this CR.** `/findings/<slug>` is only reachable by direct URL. No links from `/`, `/video`, `/llm`, `/image`, `/rag`, `/methodology`, or any nav. Lab colleagues can preview by typing the URL; visitors who don't know it exists won't stumble onto it.
3. **Single revertable commit.** All code lands in one logical commit (`findings.py` + route + template + tests). `git revert <sha>` removes the code cleanly. Editorial markdown under `docs/findings/` is safe to keep even after a code revert — they're just docs.
4. **No data-model lock-in.** No DB changes, no result-JSON schema changes, no changes to existing renderer signatures. Findings live in their own corner of the tree.
5. **Decision point:** lab review at the end of this CR. If approved, CR-055 (catalog) follows with nav promotion. If rejected, flip flag to `false`, file `git revert`, and the bench is exactly where it was at the start of the session.

### Priority: ship soon — small effort, unblocks CR-055 → CR-058 (the strategic findings-first repositioning chain).

---

## CR-055 · `/findings` catalog index page

**Status:** **shipped behind same `findings_enabled` flag 2026-05-27 (S32 evening).** Code on `main`; route `/findings` lists every finding under `docs/findings/`. **The `/video` beta link from CR-054 was re-pointed at the catalog** (was the specific AV1 finding URL) — catalog is the right discovery surface. **Tests:** 326 → 331 (+5). Same rollback: `findings_enabled: false` removes catalog + beta link + falls /demo step back.
**Triggered by:** Owner direction 2026-05-27: *"I think we need a catalogue of findings (even if there's only one there for now)"* — once the data model + worked example exist (CR-054), the catalog index is the natural next step and turns the publishing surface from "deep links only" into a browsable layer.

**Lab look & feel constraint:** dense list of rows, one per finding. Each row: confidence dot · headline · `v<n> · <date>` on the right · `claim_short` snippet underneath. Dark theme, monospace where it earns. No filtering UI (premature with 1 finding; revisit at CR-056 bulk import). Empty-catalog state is honest copy ("No findings published yet"), no scaffolding for a state that may never arrive.

### Problem

CR-054 shipped one finding page (`/findings/<slug>`) but visitors could only land on it via a direct URL. A catalog is the natural index that lets the credibility surface scale beyond one entry — and is the prerequisite for the `/video` beta link, the `/demo` Findings step (CR-058), and any future home-page repositioning (CR-057).

### Agreed direction

`GET /findings` route, same `findings_enabled` flag as `/findings/<slug>`. Renders `findings.list_all()` sorted by `last_refined` desc. Shared row component (`_findings_catalog_rows_html`) so the catalog page and the /demo Findings step preview never diverge on layout. CSS lives in `_FINDINGS_CATALOG_CSS` — a single source of truth for finding-row styling.

The `/video` beta link from CR-054 was re-pointed at `/findings` instead of `/findings/av1-hw-sw-vmaf-tradeoff` so the catalog is the entry point.

### Maintainability invariants (extends CR-054's contract)

11. **One catalog renderer.** `_findings_catalog_rows_html` renders rows; both the `/findings` page and the /demo step use it. New layout decisions = one place to change.
12. **No new persistence or schema for the catalog.** It's a pure view over `findings.list_all()`.
13. **Empty-catalog state is first-class.** The "no findings yet" copy is part of the renderer, not scaffolding-shaped placeholder.

### Ship criteria — met

- Tests pass (326 → 331)
- `/findings` lists the AV1 finding row, links to `/findings/av1-hw-sw-vmaf-tradeoff`
- `/video` beta link points at `/findings`
- `findings_enabled: false` → 404 + link disappears (test pinned)

### Priority: shipped same session as CR-054 (small lift, tightly coupled).

---

## CR-056 · Bulk import of CLAUDE.md Key Findings into the catalog

**Status:** **shipped 2026-05-27 (S32 evening).** Five new findings under `docs/findings/`; catalog grows from 1 → 6 entries. Editorial markdown only — zero Python changes per the CR-054 invariant. **Tests:** 331 → 334 (+3). Same rollback as CR-054 (`findings_enabled: false` removes the whole feature; the markdown files stay safe).
**Triggered by:** Owner direction 2026-05-27: *"Go for CR-056. Keep it factual, avoid superlatives, flag uncertainty, ask for confirmations on anything unclear."*

**Lab look & feel constraint:** the new findings sit in the same shared row renderer + page template from CR-054 / CR-055. No new layout, no new components.

### Problem

After CR-054 + CR-055 the catalog renders one finding (AV1 hw-vs-sw VMAF) and the index page lists it. The catalog as a discovery surface starts to earn its keep only once it has more than one entry — and CLAUDE.md already documents a handful of measured findings that have stored result files behind them.

### Agreed direction

Import five additional findings as editorial markdown files. Each cites a real on-disk `source_result_id`; numbers in each finding are taken verbatim from the stored result file rather than from CLAUDE.md prose (which in some cases diverges by a few percent). Owner-approved confirmations (2026-05-27) for the design choices below.

### Imported findings

| Slug | Source result(s) | Confidence | Notes |
|---|---|---|---|
| `abr-all-codecs-meridian-120s` | `video/e18a9d57` | green | n=1 on full-length Meridian-120s. CLAUDE.md's "n=3" claim isn't supported by the current on-disk dataset — flagged in the finding's caveats. A future n=3 re-measurement would create v2 via `supersedes`. |
| `sd-turbo-cpu-image-first-run` | `image/c40acdc1` | green | Disk says 0.2099 Wh (CLAUDE.md prose cited 0.2063) — finding uses disk number, caveat notes the discrepancy. |
| `llm-cold-inference-mwh-per-token` | `llm/2d79c99c`, `llm/163c6442` | **yellow** | Pre-S30 panel. Mistral 7B retired in the S30 ladder refresh. Confidence downgraded because TinyLlama returned 🟡 (n=2 polls, near noise floor). |
| `rag-faithfulness-rem-question` | `llm/5efb2079` | **yellow** | Pre-S30 panel. Gemma 3 12B retired in the S30 ladder refresh. n=1 — single observed hallucination, not a statistical claim. |
| `input-master-sensitivity` | 6 result_ids (`video/2328a8ab`, `2c112a4d`, `97ec1c07`, `883b15b0`, `dc0679b2`, `683d3a30`) | green | Summary of the existing `docs/input_sensitivity_findings.md` analysis, restructured as a finding. Original doc kept as the source for the long-form bench log. |

### Explicitly NOT imported

Two CLAUDE.md findings do not fit the CR-054 schema (which requires `source_result_ids` to be a non-empty list pointing at stored measurement files):

- **French grid evolution (S18, Jan 2020 → Jun 2024).** Derived from `carbon.HISTORICAL_INTENSITY` static data, not a measurement run. Belongs on `/methodology`, not `/findings`. Owner confirmed (2026-05-27) the schema stays strict.
- **Methodology insight: lifecycle vs combustion CO₂ (CR-016).** Methodology change, not a measurement. Same disposition.

### Maintainability invariants (extends CR-054 + CR-055)

17. **Findings cite disk numbers verbatim.** If a finding's frontmatter or analysis prose disagrees with the stored result file it cites, the result file wins. Discrepancies with prose elsewhere (e.g. CLAUDE.md) are documented in the finding's caveats, not by editing the finding's numbers.
18. **Retired-model findings carry a `pre-s30-panel` tag and an explicit caveat.** Future ladder refreshes follow the same pattern: tag with the panel name + add a caveat. A re-measurement creates a v2 via `supersedes`.
19. **Findings without a single measurement source are excluded.** Methodology essays, derived/static-data analyses, and aggregate stories live on `/methodology`. The catalog stays strictly measurement-anchored.

### Ship criteria — met

- All 5 new finding files parse, validate, and resolve their source_result_ids (`test_cr056_imported_findings_all_loadable`)
- All 5 appear in the catalog listing (`test_cr056_imported_findings_all_in_catalog`)
- SD-Turbo image finding renders with `wlRenderImageCard` (Q5 sanity check, `test_cr056_image_finding_renders_with_image_dispatcher`)
- 331 → 334 tests, full suite green

### Open follow-ups (not in this CR)

- ABR all-codecs canonical at n=3 — currently n=1 on Meridian-120s. A future probe run produces v2.
- LLM cold inference on the post-S30 panel (`qwen3:1.7b`, `qwen3:4b`, `mistral-nemo:12b`, `phi4`, `gpt-oss:20b`) — would produce v2 of the cold-inference finding.
- RAG faithfulness on the post-S30 panel — same.
- Image GPU vs CPU comparison finding — there's a `both`-mode result on disk but no finding yet; could be CR-056b or later.

### Priority: shipped same session as CR-054 / CR-055 / CR-058. Editorial work, no UI flow change beyond the catalog growing from 1 → 6 rows.

---

## CR-058 · `/demo` Findings step rewire — catalog preview replaces session echo

**Status:** **shipped behind same `findings_enabled` flag 2026-05-27 (S32 evening).** Code on `main`; the /demo Findings step (step 7) shows a curated catalog preview + "See all findings" link instead of the session-echo. **Rollback identical:** flip flag → original `buildSummary()` session echo restored, capability matrix below stays put. **Tests:** part of the 326 → 331 (+5) bundle.
**Triggered by:** Owner direction 2026-05-27: *"maybe replace the guided tour's findings with the new findings page"* — finally addresses the long-standing CLAUDE.md note *"Guided Tour Findings step — currently echoes session run; redesign to aggregate across all stored results to surface body-of-evidence learnings"*.

**Lab look & feel constraint:** changes only the top half of step 7 (was: `<div id="summary-content">` populated by JS `buildSummary()`). The "Want to dig deeper?" capability matrix (Public / Member / Lab) from CR-027 stays exactly as-is — it's the Member-recruitment lever and not a findings concern.

### Problem

The `/demo` guided tour's last step is titled "Findings" but currently shows two things stacked:
1. A JS-populated session echo (`buildSummary()`) that lists what the visitor ran during the tour — *not* findings in OWL's measurement-evidence sense.
2. A capability matrix (Public / Member / Lab, from CR-027) — valuable but unrelated to findings.

The step's name + behaviour have drifted. With the catalog now existing (CR-055), the step can deliver on its name: surface the body of evidence rather than echo the session.

### Agreed direction

Replace the inner content of `<div id="summary-content">` with a server-rendered catalog preview (top 3 findings via the shared `_findings_catalog_rows_html`, plus a "See all findings →" link to `/findings`). Set `window.OWL_FINDINGS_CATALOG_ENABLED = true` in the same injection. `buildSummary()` JS now early-returns when that global is set — so flipping `findings_enabled: false` removes the server-side injection AND restores the original session-echo behaviour.

The capability matrix below the divider stays untouched. (It's a separate, working artefact — CR-027 closed, Member recruitment is its job, not findings.)

### Maintainability invariants

14. **Reuse the catalog row component.** The /demo preview uses the same `_findings_catalog_rows_html` as the catalog page. Layout drift between the two surfaces is impossible by construction.
15. **Original behaviour is recoverable via the flag.** `buildSummary()` JS stays in place; its early-return is gated on `window.OWL_FINDINGS_CATALOG_ENABLED`. Flag false → JS runs → session echo restored. (Test pinned.)
16. **The capability matrix is not touched.** Future findings-related changes must not modify the "Want to dig deeper?" matrix; that's CR-027 territory.

### Ship criteria — met

- Tests pass (326 → 331 with CR-055)
- /demo step 7 with flag=true shows: "From OWL's body of evidence — citable findings…" framing, the AV1 finding row, "See all findings →" link to `/findings`
- /demo step 7 with flag=false reverts to "Loading results…" placeholder + buildSummary() session echo (test pinned)
- Capability matrix below unchanged in both states

### Priority: shipped same commit as CR-055. Tightly coupled to the catalog (step 7 needs the catalog to link to).

---

## CR-012 · Persist variance calibration history (and thermal-recovery probe history)

**Status:** **shipped 2026-05-27 (S32 close-out, commit pending).** Both halves landed: variance calibration appends to `results/variance/history.jsonl` from `video.run_variance_calibration` (post-`cfg.save`); thermal-recovery probe appends a summary line to `results/diagnostics/history.jsonl` from `bin/probe-thermal-recovery` (post-CSV-write). New `persist.append_history_line()` helper holds the journal contract — append-only, `ts` + `owl_version` stamped on every line. CLI failure is non-fatal (try/except with stderr log). Probe rollups (`mean_within_window_cv_pct` across d≥5s, `settled_floor_w` at max distance) computed by reading the probe summary CSV back after it's written. **Tests:** 334 → 339 (+5). **CR-024 follow-up:** when the in-process probe endpoint ships, the same `_append_probe_history` rollup can be lifted into `precalibration.py` and the CLI becomes a thin wrapper.
**Triggered by:** owner notes during Session 17 wrap — every variance calibration overwrites the previous values in `settings.json`, so there's no record of how variance has drifted across kernel updates, room-temperature changes, GPU driver bumps, or thermal-paste age. **Team meeting 2026-05-04 (#16)** confirmed the same need for the thermal-recovery probe — useful for system drift and portability checks across deployments.

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

### Thermal-recovery probe history (folded in 2026-05-04)

Same persistence shape, second JSONL file: `results/diagnostics/probe_history.jsonl`. Each line carries the probe's summary metrics (mean within-window CV across d≥5s, settled-idle floor, kernel + git_sha + ts) so the same trend page can render both calibration and probe drift over time.

The probe already writes per-run CSVs under `results/diagnostics/recovery_<ts>{,_summary}.csv`; the new history file is a *summary index* so trend rendering doesn't have to walk every CSV. Append on probe completion (currently CLI; once CR-024 ships the in-process endpoint, the same hook fires).

### Where it lives

`video.py:651–658` — the block that writes back to `settings.json` is the natural place to also write the calibration history line. For the probe, the equivalent line in `bin/probe-thermal-recovery` (and later in `precalibration.py` once CR-024 lands).

### Pre-conference: no, but cheap (~30 min). Could slot into any session as a low-priority filler. The data starts being valuable from the moment we start logging — every missed calibration is one more datapoint that's gone forever.

---

## CR-062 · S38 omnibus — unified cooldown/wait-for-idle + compare-flow & Lab-tooling fixes

**Status:** ✅ shipped 2026-06-02 (S38) on `feature/cr-062-cooldown-and-lab-ux`. Umbrella CR retro-created to record a multi-theme session (agreed: one umbrella rather than splitting). 391 → 427 tests passing (the lone `test_encode_norm` failure is pre-existing and unrelated). **Known issue deferred** (see end). settings.json deliberately held out of the commit (live calibration state).

**Triggered by:** a day of iterative work that shipped without a CR; created+closed for traceability before committing.

### Theme 1 — Unified cooldown / wait-for-idle (the headline)
- New settings: `cooldown_wait_for_idle` (master toggle, default ON) + `cooldown_idle_{tolerance_w,settle_polls,max_wait_s}` + `cooldown_dialog_watchdog_s`.
- `power.cooldown_between_runs(...)` is now the **single code path** for every inter-pass cooldown (video/llm/rag/image compares + batch + variance). Toggle ON → active-probe `wait_for_thermal_floor`; OFF → fixed `*_cooldown_s` sleep. `respect_toggle=False` keeps variance on its fixed protocol.
- Idle-wait **timeout dialog** (Wait again ≤3 / Run anyway / Cancel) for attended Lab compare runs (`allow_dialog` + `interactive_eligible` set at enqueue); `cooldown_dialog_watchdog_s` auto-applies the non-interactive fallback (one fixed sleep → proceed, `settled:false`). `power.CooldownCancelled` + `POST /job/{id}/cooldown-decision`.
- Per-result `cooldowns:[{method,waited_s,settled,final_w,timed_out}]` stamping; result-card summary (`wlCooldownSummary`) + persistent live "Cooldowns done" log on /llm/compare & /rag/compare; honest `Rest (→ idle)` stage labels (toggle-aware `_bake_durations`); `/video` adaptive 1s-during-cooldown polling.
- /settings: toggle greys the fixed rest fields + advanced idle tunables. Tests: `test_cooldown.py`.

### Theme 2 — /video codec split
"Compare all codecs" → three boxes: **Compare codecs · CPU**, **· GPU**, **Compare all (CPU vs GPU)**. New `video.run_codecs_single_measurement(side)`, shared `wlRenderCodecsSingle` card (fresh + expand), per-mode Previous-Runs labels, `persist._summarise` widened. Tests: `test_codecs_split.py`.

### Theme 3 — Image compare 2-of-3 fix
`_summarise` now carries the full `models` list; the **fresh** compare card was routed to the shared N-aware `wlRenderImageCard` (legacy 2-model `renderCompareModels` retired to a shim) so 3-model runs show 3 cards in both fresh and Previous-Runs views.

### Theme 4 — Lab test-data cleanup
`persist.delete_result` + Lab-gated `DELETE /results/{type}/{id}` (SETTINGS_WRITE) + a collapsed "Test data cleanup (Lab)" dropdown on /settings (dropdown is the guard; no per-delete confirm). Tests: `test_delete_result.py`.

### Theme 5 — Queue resume routing
`queue_control.enqueue(page=...)` stores `resume_page`; `snapshot` exposes it; `resumeLink` uses it (falls back to `/<type>`). Compare endpoints pass `/llm/compare` / `/rag/compare`, and those pages gained the `?job=` resume handler they lacked. Tests updated + `test_snapshot_carries_resume_page`.

### Theme 6 — JS bundling fix
Moved the cooldown dialog helpers + `wlCooldownSummary` into `_CARBON_JS` (bundled on every page) — they had been in `_PROGRESS_JS`, which the compare pages don't load, causing a `ReferenceError` in the poll loop that froze compare-page progress on the submit message. Regression guard: `test_js_bundling.py`.

### Known issue (deferred — promote to active CR if it lingers)
- **/video `Rest (→ idle)` live counter doesn't tick.** The readout line renders and the label is correct, but the seconds counter doesn't visibly increment during the GPU codec-sweep rest (adaptive 1s polling is in place; suspect the readout isn't re-rendering per poll or the rest settles within ~1 poll). Authoritative per-rest `waited_s` is still in the result JSON + card summary. To fix later.

### Infra note (not code; logged here for the record)
- GoS1 `eno2` (Realtek RTL8125 2.5GbE, r8169) link **flaps** caused intermittent loss of all remote access (DuckDNS + tailscale die together, recover together). Suspect EEE (802.3az, "enabled-active") and/or 2.5G autoneg with the firmware-updated Bbox. Mitigations to try: `ethtool --set-eee eno2 eee off`, reseat/swap cable + different Bbox port, or pin 1G. Not yet a CR.

---
