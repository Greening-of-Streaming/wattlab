# OWL Change Requests

Active design / change requests. Each entry has a status, a problem statement, the agreed direction, and any open questions. Implementation lives in JOURNAL.md once it lands.

**Closed CRs live in `CHANGE_REQUESTS_CLOSED.md`** — once a CR's headline scope ships, it moves there with the original problem statement preserved and a Status line naming the closing commit.

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

## CR-012 · Persist variance calibration history (and thermal-recovery probe history)

**Status:** captured 2026-05-01 — nice-to-have. **Scope extended 2026-05-04 (post-meeting)** to cover the thermal-recovery probe's history too; both diagnostics share the same persistence shape.
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

## CR-018 · Historical CO₂e comparison — full coverage upgrade (Tier 2 + Tier 3)

**Status:** Tier 1 ✅ done 2026-05-03 (Session 18 part 14 — `bf462c3`); Tier 2 + Tier 3 captured for later.
**Triggered by:** owner question on whether OWL could show "if this job had run in Paris in January 2020" as a feel for grid evolution. Tier 1 (curated five dates) shipped same session because the methodology was already in place after CR-016 — same `compute_intensity_from_mix` for live and historical.

### What Tier 1 delivered (already shipped)

Five hard-coded France monthly lifecycle intensities in `carbon.HISTORICAL_INTENSITY`, surfaced as a "Through history" block in the carbon comparison strip and documented on `/methodology`. Generated by a one-shot `bin/fetch-historical-mix --year YYYY --month MM` helper that fetches Eco2mix consolidated data and runs each record through the same lifecycle calculation as the live path. Curated, narrative-driven, FR-only.

### Tier 2 — full historical coverage with cached JSON

The next step up: instead of cherry-picking five dates, pull every month from 2012 to last month, cache it locally, and let the visitor pick any date.

**Mechanism:**
- `bin/refresh-historical-carbon` — Python, replaces the one-shot helper. Fetches monthly aggregates for every (zone, year, month) tuple in scope. Writes to `data/eco2mix_history.json` (~50KB for FR alone, ~150 monthly aggregates).
- Run on demand (no cron); re-run quarterly to extend the dataset by ~3 months.
- `carbon.py` loads the cache at startup; new function `historical_intensity(zone, year, month)`.
- New endpoint `/carbon/historical?zone=FR&year=2020&month=6` returns `{g_per_kwh: …, label: …}`.
- Comparison strip gains a small year-month picker (2012 → last completed month). When the visitor picks a date, the historical row updates inline.

**Cost estimate:** ~1 day. The script is the slowest part because of API pagination across 150 months × ~1500 records each — manageable but not instant; budget a half-hour fetch the first time.

**Why not now:** Tier 1 covers the conference narrative (a small, well-chosen set of dates makes a sharper story than a slider that lets visitors "shop around"). Tier 2 earns its keep when there's a specific user demand for a date that's not in the curated five.

### Tier 3 — interactive timeline

Visitor scrubs across years; the headline number, the EV equivalence, and the comparison rows all animate in response.

**Mechanism:** Tier 2's data + a simple range slider + smooth transitions on the carbon-strip values. Optionally a sparkline of intensity-over-time for the home zone.

**Cost estimate:** ~2 days. UX work is the bulk — the data is already cached by Tier 2.

**Why not now:** scope creep risk. The animation is engaging but adds maintenance for marginal pedagogical gain over Tier 2's picker. Lands well after the conference if at all.

### Other zones

All three tiers are FR-only out of the box. Eco2mix is RTE's data; it doesn't cover Germany, UK, etc. Other zones could get historical coverage via:

- ElectricityMaps' historical API (paid; their token already in scope per CR for the live path).
- Ember's monthly data (free; published with a few months' lag; cleaner provenance for European zones).

Adding non-FR historical is essentially "the same Tier 2 infrastructure pointing at a second data source." Captured here as a follow-up consideration; not in scope for the FR-focused conference launch.

### Caveat across all tiers

Lifecycle factors (IPCC AR6 WGIII 2022) are static, so we're applying current factors to historical mixes. Defensible (the factors are physics/process estimates, not annual statistics that drift), but worth a footnote on `/methodology` if Tier 2 ships. Already noted in passing in the Tier 1 doc.

### Pre-conference: no

Tier 1 is enough for the conference. Tier 2 lands post-launch if visitors ask for it; Tier 3 only if Tier 2 itself proves popular.

---

## CR-019 · Unify the in-progress widget across `/demo` and the main pages (+ resume-job progress fix)

**Status:** captured 2026-05-03 (Session 19). **Scope extended 2026-05-04 (post-meeting)** to cover the resume-job progress bug — same widget surface, same fix surface, no point splitting.
**Triggered by:** owner running the 3-mode RAG comparison from `/demo` step 4 on mobile and noticing the in-progress UI is *much* less informative than what `/rag` shows for the same workload — no multi-stage breakdown ("Baseline poll → Inference running → Complete"), no big live wall-power readout, no carbon strip preview. Suspected to apply to all four `/demo` workload steps (video, LLM, image, RAG), since they all share the same simpler-than-main-page polling pattern. **Team meeting 2026-05-04 (#6)** added a related concern: after a job is queued and then resumes, the visitor may lose the progress bar entirely or be taken to the wrong page — same widget, different failure mode (visibility / lifecycle rather than feature-completeness).

### Problem

Two parallel progress UIs exist today:

- **Main pages** (`/video`, `/llm`, `/image`, `/rag`) use the shared widget `wlRenderProgress(opts)` (defined in `_PROGRESS_JS` around `main.py:1005`). It renders a single bordered card with: yellow "Measuring — do not close this tab" header, multi-stage list with ✓/▶/· icons (via `wlStageList(stages, cur)`), big 2.5rem live watts ("live wall power · Tapo P110"), elapsed timer, and extra HTML slot for stage-specific detail (e.g. partial RAG results between modes). Each page has its own STAGES array (`VIDEO_STAGES`, `LLM_STAGES`, `RAG_STAGES`, `IMAGE_STAGES`) and threads `data.watts` from the job-status payload through `opts.watts`.
- **`/demo`** rolls its own per-step progress in `pollLLM`, `pollDemoImage`, `pollDemoRAG`, `pollVideo` — just a single line `<p class="progress-note">▶ stage label</p>` plus an elapsed line. No stages list, no live watts, no extras slot.

Result: the visitor running the canonical guided tour gets a *worse* experience than the same visitor clicking through to a main page directly, even though `/demo` is supposed to be the polished public surface.

### Agreed direction

**One widget, one signature, all five surfaces.** `/demo`'s four poll loops drop their bespoke HTML and call `wlRenderProgress` with the same STAGES arrays the main pages already define. No new module — `wlStageList` and `wlRenderProgress` are already in `_PROGRESS_JS`, which `/demo` includes (it ships under `_DEMO_BASE_STYLES` / `_PROGRESS_JS` indirectly via the main.py page assembly).

Required mechanical changes:

1. **`wlRenderProgress` writes to `#status` today.** `/demo` already has per-step status divs (`#video-status`, `#llm-status`, `#image-status`, `#rag-status`). Either:
   - Add an `opts.target` field; default to `#status` for back-compat. `/demo` passes the per-step ID. Smallest change.
   - Or refactor `/demo` to use a shared `#status` per active step. Bigger change, no real benefit.
   The `opts.target` route is cleaner.
2. **Live watts threading.** Main pages get `data.watts` from the job-status JSON (the worker writes the live P110 reading into the job state on each poll). `/demo`'s poll endpoints (`/llm/job/{id}`, `/image/job/{id}`, `/rag/job/{id}`, `/video/job/{id}`) likely already include this — verify, fix if not.
3. **Stages reuse.** Pull `RAG_STAGES`, `VIDEO_STAGES`, `LLM_STAGES`, `IMAGE_STAGES` out of their per-page f-strings into `_PROGRESS_JS` (or a sibling shared block) so `/demo` references the same arrays the main pages do. Without this, the stages drift and the unification rots.
4. **Extras slot.** `/demo`'s RAG step today shows nothing during the cooldown between modes; the equivalent on `/rag` shows partial-results-so-far. Same widget, same `opts.extraHtml`, same render — comes for free once the call shape is unified.

### Why this matters

`/demo` is the conference narrative — the visitor's first 60-second impression of OWL. The big live wall-power readout *is* the proof-of-reality moment ("there's a real power meter, this isn't a slideshow"). Hiding it during the in-progress phase is exactly the wrong moment to drop it.

Refactor also collapses ~80 LOC of duplicated progress markup spread across five poll functions, which removes a class of "fixed it on `/rag` but forgot the same fix on `/demo`" drift bugs (we already had one of these — the carbon-strip on RAG compare-3-modes was missing from `/demo` for weeks before being noticed).

### Cost / leverage

Small refactor (~½ day). Large UX impact: `/demo` is the highest-traffic surface, and the live wall-power readout *is* the proof-of-reality moment, so dropping it during the in-progress phase is exactly the wrong moment to drop it. Also collapses ~80 LOC of duplicated progress markup, which removes a class of "fixed it on `/rag` but forgot the same fix on `/demo`" drift bugs (we already had one of these — the carbon-strip was missing from `/demo` for weeks).

### Resume-job progress fix (folded in 2026-05-04)

After a job is queued (visitor enters the queue while another job is in flight) and then dispatched, the visitor's progress UI doesn't always re-attach cleanly. Symptoms reported in the meeting:

- Progress bar disappears entirely after queue → run transition.
- Visitor is sometimes taken to a different page (probably the home redirect rather than a stable per-job URL).
- The job is actually running and completing fine on the server — this is purely a client-side widget lifecycle bug.

Likely causes (to verify during implementation):

- The `/demo` poll loops re-instantiate from scratch on every visit; if the visitor navigates away during the queued state, the on-return polling doesn't pick up the in-flight job.
- The `wlRenderProgress` widget has no resume-by-job-id pattern — it's started by the click that submitted the job, not by the page that wants to display it.

Right fix lives in the same place as the main unification: every page that surfaces in-progress UI should be able to *re-attach* to a job by its ID, not just the page that originally submitted it. Add a query-param hook (`?job=abc123`) that resumes the widget on page load if a matching active job exists. `wlRenderProgress` becomes resumable rather than session-bound.

### Open questions

- Does `data.watts` already flow through every job's poll payload, or only some? Verify on `/llm`, `/image`, `/video`, `/rag`. If not, write it once in `queue_control.py` so all workloads inherit.
- During the cooldown phase between RAG modes, the stages list shows "Inference running" but the system is actually idle. Does the active-stage indicator need a fourth state ("cooldown") or does the existing logic handle it? The `RAG_STAGES` array on `/rag` doesn't include cooldown explicitly; live-watts dipping back to baseline is the actual signal.
- For the resume-job case: should the URL change to `/<page>?job=<id>` when a job is queued, so a back/forward navigation or a link-share preserves the in-flight state? Probably yes; needs a careful design pass to not break browser history.

---

## CR-024 · Re-run thermal-recovery probe from the "More calibration details" panel

**Status:** captured 2026-05-04 (Session 21). Half-day of work — not lightweight enough to fold into the panel that currently just renders the chart.
**Triggered by:** owner — the "More calibration details" dropdown on `/settings` (shipped Session 21) renders the recovery curve from `bin/probe-thermal-recovery` output. The CLI script is fine for owner-on-keyboard runs, but the natural next step is a "▶ Re-run probe" button next to the chart so the operator can refresh the curve without dropping to the shell.

### Problem

Currently the probe is a CLI script (`bin/probe-thermal-recovery`) that takes ~65 min, holds `/tmp/owl-paused` and `/tmp/gos-measure.lock` directly, and writes CSVs under `results/diagnostics/`. The settings panel reads the latest CSV via `GET /precalibration/data`. There is no in-process trigger; the operator has to SSH in and run the script.

The mismatch: every other long-running measurement on OWL (variance, video, llm, image, rag) goes through `queue_control.enqueue` so visitor-vs-operator collision is handled by the spine. The probe doesn't, because it predates being a first-class server feature.

### Agreed direction

**Promote `bin/probe-thermal-recovery` into a `wattlab_service/precalibration.py` module + `POST /precalibration/run` endpoint that mirrors `/variance/run`.**

1. **Extract the probe loop** from the CLI into `precalibration.py:run_thermal_recovery_probe(job_id, jobs)` — same shape as `video.run_variance_calibration`. Reuses `focus_mode_enter/exit`, `LOCK_FILE`, `transcode`, `_maybe_cap_vaapi` (CR-022).
2. **New endpoint** `POST /precalibration/run`, gated on `VARIANCE_RUN` capability (or a sibling `PRECALIBRATION_RUN` if we want to differentiate). Routes through `queue_control.enqueue(...)` so visitor jobs queue behind it just like a variance calibration.
3. **CLI script becomes a thin client** that POSTs to the endpoint and tails progress. Or stays as a stand-alone — the module is what matters.
4. **Panel UI**: a "▶ Re-run probe" button next to the chart, plus a status line that polls `/jobs/{id}` (existing pattern). On completion, refetch `/precalibration/data` and replace the chart. ETA badge ("≈65 min"). Disabled while a probe is in-flight.

### Setting shape

Add the existing probe parameters to settings.json so they're operator-tunable from `/settings`:
```jsonc
{
  "precal_distances":     "0,2,5,8,12,18,25,35,50,70,95,120",  // comma-separated seconds
  "precal_pre_cool_s":    30,                                   // pre-encode wait
  "precal_baseline_polls": null  // null → fall back to baseline_polls
}
```

Default values match the CLI defaults so behaviour is unchanged.

### Cost / leverage

Estimate ~half a day:
- ~2h to extract `precalibration.py` and the route (mostly mechanical — copy from `bin/probe-thermal-recovery`, adapt to `jobs[job_id]["stage"]` reporting, integrate with `queue_control.enqueue`).
- ~1h for the panel UI button + status polling + auto-refresh of the chart.
- ~1h for tests covering the module-level pure functions (cap injection already covered by CR-022 changes).
- ~1h for docs + checking the visitor-protection story matches `/variance/run` exactly.

Leverage: the panel becomes self-contained — operator clicks a button, walks away for an hour, comes back to a refreshed curve. Also: every future hardware change (new GPU, new ambient temp, swapped fan) can be re-validated in one click instead of "remember to run the script". The diagnostic stops being tribal knowledge.

### Watch-outs

- **Don't drop the CLI script.** It still has value for diagnostic-during-development work where you want pdb/raw logs. Keep `bin/probe-thermal-recovery` as a thin wrapper around the module — it's already structured that way.
- **`results/diagnostics/` should keep its current shape.** Same CSV format, same naming. The endpoint just produces them via a different code path. The reader (`/precalibration/data`) doesn't care.
- **Don't auto-fold this into variance calibration.** Tempting to chain "probe → variance" as a single workflow, but they answer different questions and operators may want one without the other. Keep them separate buttons; document the recommended sequence on `/methodology`.

### Open questions

- **Sub-CR or independent?** Could ship as a follow-up to the Session-21 panel (CR-001 style sub-letter), but it's substantial enough to deserve its own number. Going with CR-024 as primary.
- **Naming:** `/precalibration/run` mirrors `/variance/run` symmetrically, which is the priority. The word "precalibration" is clunky; "thermal recovery" is more accurate but operators are already used to "pre-calibration" framing. Stick with `/precalibration/*` for the URL space, but the panel header could say "Thermal recovery probe" if that reads better in context.

---

## CR-025 · Migrate to a real-time Linux kernel for tighter measurement determinism

**Status:** captured 2026-05-04 (Session 21) as exploratory; **upgraded to confirmed direction by team meeting 2026-05-04** (item 30). Originally tagged "maybe" because the wins are bounded by the current P110 API resolution; the meeting agreed to pursue regardless because "Ubuntu focus mode may not suppress background activity enough" and the RT investigation creates a path to higher-resolution sensor work later.
**Triggered by:** owner — meeting question on whether `systemctl stop` (focus mode) becomes more effective on a real-time Linux. Honest answer surfaced a different framing: RT and focus mode address orthogonal noise sources, and there's a coherent story where they stack rather than overlap.

### Problem (what we're trying to improve)

The current variance-control setup has two layers:
- **Focus mode** stops 8 background timer units (cron, fwupd, apt-daily, …) so they don't fire during measurement and contribute to ΔW noise. This addresses the *power-side* of background work — things that wake a core and draw watts.
- **The 1 Hz P110 polling cadence** is on a vanilla preemptive kernel and is therefore subject to whatever scheduling jitter the kernel sees from itself, IRQ handlers, kernel threads, and any non-suppressed userspace.

We have no layer addressing *temporal* jitter: variance in poll spacing, variance in ffmpeg startup transient, variance in encode runtime caused by scheduler quanta or kernel housekeeping. On the probe data this manifests as the few-percent residual we can't easily explain — most of the floor is P110 quantisation, but a slice is real per-run timing variance.

### What RT Linux actually does (and doesn't)

A PREEMPT_RT kernel + CPU isolation gives:

1. **Preemptable kernel threads** with deterministic latency bounds (microseconds vs. tens of ms on stock).
2. **Prioritised IRQ handling** — interrupts handled at known priority instead of competing with kernel housekeeping.
3. **`SCHED_FIFO` / `SCHED_RR`** strict priority for designated tasks.
4. **CPU isolation** (`isolcpus`, `nohz_full`, `rcu_nocbs`) — dedicate cores to measurement; all other system activity runs on a smaller "housekeeping" core set.
5. **More consistent sleep granularity** — `asyncio.sleep(1.0)` actually wakes at 1.000 s rather than 1.000 ± a few ms.

What it does **not** do:
- It does not stop scheduled jobs from running. A cron job pinned to housekeeping cores still draws power, and the **P110 measures the whole box** — so isolated measurement cores don't isolate W_base from background load. Focus mode still required.
- It does not improve P110 resolution. Today's ~1 W floor via the cloud API is unaffected.
- It does not magically make ffmpeg deterministic — VAAPI driver behaviour, hardware thermals, and surface-pool warm-up dynamics are unchanged.

### Where the wins land (concretely)

If we ship CR-025 *as-is, with focus mode still in place*, expect:

- **Tighter `variance_cpu_pct` / `variance_gpu_pct`** — encode runtime variance shrinks. Today's CPU 2.11% / GPU 17.22% have a real timing-variance slice; RT compresses it.
- **More predictable short-task measurement.** This morning's 17.22% GPU CV from 2-poll encodes is partly because polling cadence has jitter; on RT, exact 1 Hz with deterministic ffmpeg startup pushes that figure down regardless of `gpu_encode_max_s` tuning.
- **Sub-1 W signal investigations become tractable.** If we ever swap to the P110's direct device read (~1 mW resolution) or a PDU / IPMI, kernel jitter goes from "noise floor << instrument floor" to "noise floor ≈ instrument floor" — and RT becomes the difference between credible mW measurements and not.

### Agreed direction (if shipped)

**Stack RT + focus mode + CPU isolation** so the three layers solve different problems instead of overlapping:

1. **Install `linux-image-rt-generic`** (Ubuntu 24 ships PREEMPT_RT in the generic-rt flavour). Validate boot + GPU drivers + ROCm + VAAPI on the RT kernel before changing anything else. Some out-of-tree drivers don't love PREEMPT_RT — known risk.
2. **Kernel cmdline:** `isolcpus=8-23 nohz_full=8-23 rcu_nocbs=8-23` (dedicate 16 of 24 cores to measurement, leave 0-7 for housekeeping). Tunable; the split is a knob to test.
3. **Pin OWL service + measurement spawns to the isolated set.** systemd unit override: `CPUAffinity=8-23`. ffmpeg is already invoked through `nice -n -5`; add `taskset -c 8-23` to the chain. Power polling stays on isolated cores too.
4. **Focus mode unchanged** — it still suppresses the cron-side noise on the housekeeping cores. The two layers compose.
5. **Verification harness.** Use `cyclictest -p 99 -t -m -n -i 1000 -l 100000` to prove latency stays in the µs range during a calibration run. Add a smoke test in `bin/` that fires before each calibration and aborts if max latency exceeds a threshold.
6. **Document on `/methodology`.** New subsection under "Diagnostics" explaining the kernel layer; bumps the "Hardware Disclosure" table to include kernel flavour + isolation config.

### Setting shape

No new runtime settings. Two operator-facing knobs are kernel-level (cmdline) rather than `settings.json`:

```
# /etc/default/grub
GRUB_CMDLINE_LINUX_DEFAULT="quiet splash isolcpus=8-23 nohz_full=8-23 rcu_nocbs=8-23"

# /etc/systemd/system/wattlab.service.d/affinity.conf
[Service]
CPUAffinity=8-23
```

### Cost / leverage

Estimate **~half a week of careful work**, not a quick patch:

- ~1 day: install RT kernel, validate full stack (FastAPI + ffmpeg + Ollama + ROCm + diffusers + ChromaDB) survives the migration. ROCm on RT is the single biggest unknown.
- ~1 day: cmdline tuning, CPU isolation, systemd affinity overrides, taskset wrappers in `transcode()` / measurement spawns.
- ~1 day: cyclictest harness + a re-run of variance calibration + the thermal-recovery probe, comparing pre/post numbers honestly.
- ~½ day: methodology page update + journal entry.

Leverage depends entirely on whether RT moves the needle for OWL specifically. **Run the probe before and after; the empirical delta on `variance_*_pct` and on probe within-window CV is the only honest justification.**

### Watch-outs

- **Can lose ROCm or VAAPI.** AMD's driver stack on PREEMPT_RT isn't a tested combination. If it breaks, the workload modules (image_gen, video GPU presets) lose their primary path. Validate on a snapshot before committing.
- **Power-measurement boundary unchanged.** P110 still sees the whole box. Visitors and team members must understand isolation is *for jitter*, not *for excluding cores from energy accounting* — easy to confuse.
- **System feels different to operate.** Background commands run on 8 cores instead of 24; non-measurement work (apt update, git operations, an SSH session) feels slower. Worth a heads-up to anyone who SSHes in.
- **Diminishing returns ceiling.** With the P110's 1 W cloud-API quantisation, RT's likely contribution to `variance_idle_pct` is ≤1 percentage point. The probe data will tell us whether that's worth the complexity.
- **Reversibility.** The RT kernel is selectable from GRUB at boot, so falling back is one reboot — *if* nothing in the stack has hard-coded behaviour against the RT kernel. Verify before shipping.

### Open questions

- **Does ROCm work on Ubuntu 24's `linux-image-rt-generic`?** First thing to test; everything downstream depends on it.
- **What's the right isolated/housekeeping split?** 16/8 is a guess; 12/12 might be cleaner for parallelism on the housekeeping side. Empirical.
- **Does this make `variance_cooldown_s` shorter feasible?** Less jitter could mean less safety margin needed. Not a primary motivation but a possible side-benefit.
- **Should the probe + calibration auto-detect RT and tag results?** I.e. result JSON gains `kernel_flavour` and `isolated_cpus` so historical comparisons can attribute differences. Probably yes; small change.
- **Companion CR for power-sensor upgrade?** RT's full value lands when paired with a higher-resolution sensor. If the team is interested, capture a sibling CR for evaluating P110 direct-read or a proper PDU. RT alone is partial value; together they're transformative.

### Why "maybe"

Two questions tip the decision:

1. **Is jitter the limiting factor?** Probe says noise floor is ~2% within-window. P110 quantisation alone explains ~1.5-1.8% on a ~55 W idle (1 W / 55 W ≈ 1.8%). Margin for kernel jitter is small. RT might shave 0.5 percentage points; might shave none.
2. **Are we planning a sensor upgrade?** If yes, RT moves from "marginal win" to "necessary precondition" and the calculus flips entirely.

Worth a 30-minute discussion with the measurement team rather than a unilateral decision. The CR is here so that conversation has something concrete to push against.

---

## CR-027 · Tier explanation pass

**Status:** captured 2026-05-04 (post-meeting). Medium priority. Bundles items 8 + 9 — both are tier-explanation copy/UX on the same surface.
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

## CR-028 · Confidence model evolution (interim re-weighting + Tania's unified redesign)

**Status:** captured 2026-05-04 (post-meeting). Two-phase. **Phase 1** is small and shippable now; **Phase 2** needs a working session with Tania. One CR with both phases keeps the design conversation in one place.
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

**Phase 2 — Tania's unified statistical redesign (working session required).**

The shape isn't decided yet, but candidate ingredients:
- Replace `noise_w = variance_pct × W_base` with a per-run uncertainty bound derived from observed baseline CV *during this run* (overlaps with CR-020).
- Replace the three-flag traffic light with a single confidence number (e.g. effective signal-to-noise ratio) and a continuous mapping to badge colours, so adjacent runs aren't artificially binned.
- Properly account for the dependence between baseline and task readings — they're separated in time, so drift between them is a real noise contributor that the current formula ignores.

This phase is **a design exercise first, code second**. Working session with Tania to align on the model before any implementation. Once the model is agreed, factor the existing `confidence(...)` function in each measurement module into a shared `confidence.py` module so the new model lives in one place.

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
- **Idle and CPU CV settling?** Across the 2026-05-04 calibrations, idle CV ranged 1.92–7.42% and CPU 0.71–5.28%. The morning's clean baseline (idle ~2%, CPU ~1%) is what we'd expect on a quiet box; the higher numbers correlated with active work elsewhere. The 2026-05-05 overnight n=24 calibration landed at idle 2.41% / cpu 1.33% — clean-baseline range, consistent with "no other active work on the box." Open question for Phase 2: should the confidence model account for *time-of-day* idle baseline drift, or treat it as out-of-scope and rely on a fresh per-run baseline?

---

## CR-029 · Encoding rigor pass (apples-to-apples credibility)

**Status:** captured 2026-05-04 (post-meeting). High priority. Bundles items 18, 19, 20, 21, 22, 23 — Tania's video credibility workstream. Coherent because each item is a step in the same chain: *what is each encoder actually doing → are CPU and GPU comparable → can we present it cleanly*.
**Triggered by:** team meeting 2026-05-04 — for the canonical ABR all-codecs benchmark to be cited externally, the pipeline has to be auditable and the comparison's semantics explicit (apples-to-apples vs. typical use).

### Problem

The current `/video` flow runs presets that look comparable but haven't been formally checked at the level needed for citation. Specifically:

1. **The exact pipeline isn't documented** anywhere readers can audit. The ffmpeg command is logged in result JSON (per CR-002) but the surrounding choices (input format, intermediate buffer formats, output container, profile/level defaults, GOP defaults per encoder) aren't.
2. **CPU and GPU may not be running comparable work.** Same bitrate target, yes, but profile level, B-frame structure, GOP cadence, refs, and preset are all encoder-defaulted and may differ. Tania to verify by reading the encoded outputs.
3. **Sample outputs aren't routinely verified.** We trust ffmpeg; we don't routinely confirm the output file's actual encoding matches what we intended.
4. **There's only one comparison philosophy.** Same bitrate across codecs ("apples-to-apples") is one valid frame; same *typical operating point per codec* (different bitrates representing real-world use) is another. The team agreed both should exist; currently we only have the first.

### Agreed direction

**Six items, sequenced:**

1. **Document the pipeline** on `/methodology` — new subsection under "Video transcoding". Cover: input read, decode (CPU vs `hwaccel vaapi`), pixel-format handling (`scale_vaapi` + `format=nv12`), encoder defaults this deployment relies on, output container. One pass per codec/path. Source from the actual command, not from memory.
2. **Validate CPU vs GPU encode parameters** (Tania-led). For each codec, compare what the CPU and GPU encoders actually produce: profile, level, B-frames, GOP, refs, slices. Write findings to `WATTLAB_SPEC.md` and adjust commands as needed to bring them into apples-to-apples shape (or document explicitly where they can't be).
3. **Verify sample output files.** Pick at least two recent encodes per codec. Inspect with `ffprobe -show_format -show_streams` and `mediainfo`. Confirm: bitrate matches target, codec matches command, profile/level reasonable, file size in expected range. Once-off audit; capture findings.
4. **Add two comparison modes to `/video`.**
   - **"Compare all codecs · apples-to-apples"** — current behaviour, identical bitrate per codec from settings.
   - **"Compare all codecs · typical use"** — each codec at its real-world operating point. Bitrates per codec to be agreed but provisionally H.264 6000 kbps, H.265 3500 kbps, AV1 2500 kbps (representative of streaming-platform mid-tier; needs Tania confirm).
   Mode is a UI radio button on the compare-all preset, not a separate preset. Result page label includes the mode so post-hoc comparison is unambiguous.
5. **Define and document the default comparison philosophy.** Which mode is the headline finding measured under? Currently apples-to-apples. Document this explicitly on `/methodology` and the home page so the headline isn't accidentally misread.
6. **External PQA, not internal.** When quality-targeted comparison comes up (visitors asking "is the AV1 output as good as H.264 at the same bitrate?"), the answer is to point at Netflix / industry references — not to do PQA inside OWL. Document this scoping decision on `/methodology` so the question has a written answer.

### Cost / leverage

Sub-items differ wildly:
- #1 (document): half a day if the audit is clean, more if it surfaces issues.
- #2 (validate CPU/GPU): Tania session + iteration. ~half a day to a day depending on what the audit finds.
- #3 (verify samples): 1-2 hours, mostly mechanical.
- #4 (two modes): ~half a day for the UI + the new bitrate set.
- #5 (philosophy): an hour of writing once #1-#4 are settled.
- #6 (external PQA scoping): an hour.

Total ~2-3 days, gated on Tania's availability for #2.

Leverage is high: this is the work that turns OWL's video numbers from "interesting" into "citable". Until this is done, the headline benchmark sits in the canonical-finding section with an asterisk.

### Watch-outs

- **Don't quietly change bitrates mid-experiment.** If #2's audit finds CPU and GPU need different settings to align, the previous benchmark numbers no longer apply and the canonical finding gets re-run. The headline-findings audit (already in CLAUDE.md deferred) is upstream of this.
- **Don't internalise PQA.** Visual quality assessment is a deep field with established methodology and large tooling; OWL trying to do it lightly is a credibility liability, not an asset. Hold the line on #6.
- **Mode names matter.** "Apples-to-apples" and "typical use" are good for engineers but might confuse public visitors. Consider "Same bitrate" / "Real-world bitrate" or similar in UI copy. Decide during implementation.

### Not in scope

- Benchmark 2 (CRF/QP codec-natural rate control) — already on the CLAUDE.md roadmap, separate workstream.
- LLM / image / RAG equivalent rigor passes — out of scope for *this* CR even though the same principles apply. Capture follow-ups if the team wants.

### Open questions

- **Who owns the spec doc?** `WATTLAB_SPEC.md` exists but is sparse. This CR could grow it substantially; Tania probably owns the encoding-spec subsection and bs/owner owns the methodology page.
- **Per-codec "typical use" bitrate values** — provisional numbers above; Tania to confirm against Bitmovin / Netflix tier guidance.

---

## CR-031 · Deployment portability (DB / power source / containerisation)

**Status:** captured 2026-05-04 (post-meeting). Medium priority. Bundles items 29, 31, 32 because all three answer the same underlying question: *what does it take to run OWL somewhere other than GoS1?* Three sub-sections rather than three CRs because they share a single decision frame and will be designed together.
**Triggered by:** team meeting 2026-05-04 — sketches of OWL running on Linode, on a different bench server, or in a container; concerns that today's design (one JSON per job, `power.py` only has the Tapo path, no container story) makes that harder than it needs to be.

### Problem

OWL was built for one server (GoS1) and the assumptions show:

1. **Persistence** — flat JSON files keyed by date+job_id under `results/{type}/`. Fast, debuggable, version-controllable. But: no indexing for time-series queries (history charts, drift over runs), no atomic transactions (CR-023 abort path writes settings.json directly), no portability story when the data volume grows.
2. **Power source** — `power.py` is `get_power_watts() → float` from the Tapo P110 via the `tapo` lib. The abstraction is the right shape but the implementation is single-source. Other deployments (different bench, hosted environment, no Tapo plug available) need a swap path: PDU read, IPMI sensor, BMC API, or a synthetic source for development.
3. **Containerisation** — there's no container story. OWL is a systemd service + sudoers config + nginx vhost + a venv. Reproducing this on another machine is a half-day of imperative steps. The Tapo cloud path, the focus-mode sudoers rules, and the GPU drivers (VAAPI, ROCm) all need careful staging.

### Agreed direction

**Three sub-sections; one CR because the decisions interact.**

#### 1. Persistence: decision required, not implementation yet.

Two options:

- **Stay with JSON files**, add a thin index layer (`persist.py` gains `list_results_indexed()` that maintains a small SQLite mirror for time-series queries; raw JSON stays the source of truth). Cheap, preserves all existing tooling.
- **Migrate to a real DB** (SQLite or Postgres). Better story for history charts, time-of-day carbon UI, multi-deployment data merge. Bigger lift, breaks current `cat results/video/2026-05-04_*.json | jq` workflows.

Decision criteria: if the time-of-day / historical UI work (CR-018 T2/T3) plus the variance + thermal-recovery history work (CR-012) show real friction with flat-file storage, migrate. If they don't, stay with JSON + a small index.

#### 2. Power source abstraction.

`power.py` already has the right shape (one function, one return type). Make it explicit:
- Move the Tapo implementation to `power_tapo.py`.
- Add `power_pdu.py` (stub for SNMP-based PDU reading) and `power_synthetic.py` (returns a configurable noise pattern around a configurable mean — for tests / dev without hardware).
- `power.py` becomes a dispatcher reading `POWER_SOURCE` env var (`tapo` | `pdu` | `synthetic`) and importing the right backend.
- Existing tests stay green via `synthetic`.

This is small (~half a day) and unblocks anyone else in the GoS network running OWL on a non-Tapo environment.

#### 3. Containerisation readiness.

A `Dockerfile` + `compose.yml` that boot OWL with all needed runtime, with explicit acknowledgement of what *can't* be containerised cleanly:
- **Sudoers + focus mode** — focus mode `systemctl stop` calls don't work inside a container. Either drop focus mode in containerised mode (and document the loss of measurement quality) or run privileged + bind-mount /run/systemd. Both are ugly.
- **VAAPI / ROCm** — passing GPU into a container needs `--device /dev/dri/...` for VAAPI and the ROCm runtime image for AI workloads. The CLAUDE.md long-term plan mentions a two-stage container plan (FastAPI+VAAPI first, ROCm later); this CR formalises it.
- **Settings + calibration** — settings.json must be system-dependent and recalculable when moved. The container's first run on a new host MUST run a fresh variance calibration before trusting confidence labels. Bake this as a startup check, not a manual step.

### Cost / leverage

- **Sub 1 (persistence decision):** half a day to write up the criteria, talk to the team, decide. Implementation cost depends on the decision (small for "JSON + SQLite index", several days for DB migration).
- **Sub 2 (power source abstraction):** ~half a day. Zero coupling to other CRs.
- **Sub 3 (containerisation):** ~3-5 days for stage 1 (FastAPI + VAAPI). Stage 2 (ROCm) is its own follow-up.

Total: depends on Sub 1's decision. If "JSON + SQLite index" + Sub 2 + Stage 1 container, ~1 week. If "DB migration" + Sub 2 + Stage 1, ~2 weeks.

Leverage: Sub 2 is pure win, ship anytime. Sub 1 is a strategic decision that other CRs (CR-012, CR-018 T2/T3) depend on. Sub 3 is the long-term vision, currently CLAUDE.md "Deferred / open".

### Watch-outs

- **Don't migrate the DB silently.** If we go DB, ship a migration script + rollback path + test that historical results render identically before and after.
- **Don't lose the calibration when moving hosts.** A container that starts on a new machine and serves results without a fresh calibration is worse than no container — it produces confident-looking readings that are physically meaningless.
- **Don't break the bench dev loop.** Today's loop is "edit, restart wattlab, refresh page". Anything that adds 5 minutes to that loop (slow container build, DB migrate steps) reduces iteration speed dramatically. Optimise for fast restart, not pristine reproducibility.

### Not in scope

- Multi-tenancy / multi-deployment data merge — separate CR if/when needed.
- Cloud-native rewrite — out of scope by orders of magnitude.
- REM ↔ OWL data merge — already CR-008.

### Open questions

- **DB choice if we migrate.** SQLite is the obvious starting point (file-based, no extra service). Postgres if multi-deployment merge becomes near-term. Don't pre-decide; the answer falls out of Sub 1's criteria.
- **Synthetic power source as a first-class testing tool?** Cleanly written, it'd let us run integration tests with deterministic measurement responses — useful far beyond this CR. Capture as a follow-up if Sub 2 ships.

---

## CR-032 · Per-mode CO₂e rows inside the carbon strip details

**Status:** captured 2026-05-05 (Session 22 part 2). Medium priority — UX clarification, not a credibility blocker. CR-030's bonus label fix ("best of CPU vs GPU" / "most efficient codec") is the V1 patch that stops the strip from misleading on its own; CR-032 is the next step that makes the strip *self-contained* for compare results.
**Triggered by:** owner observation during Bundle 2 visual verification — for compare-mode results the strip headline shows the most-efficient mode's mass with explicit "best of N" framing, but the other modes' CO₂e footprints aren't visible inside the strip itself. Visitors who want to compare per-mode CO₂e have to scroll up to the per-column inline rows. The strip should answer "where does this number come from" without forcing the eye elsewhere.

### Problem

Today's compare-mode strips (video CPU/GPU, video all_codecs, LLM CPU/GPU, image CPU/GPU, image small/large, RAG 3-mode) all use `Math.min` to pick the most-efficient sub-run's energy and label that mode as the headline. The strip's `<details>` block then shows comparison rows for *other zones / other dates / live mix / formula* — but never the *other sub-runs of this same comparison*. The data exists (each sub-run has its own `energy.co2e.grams`), it's just not surfaced in the strip.

### Agreed direction

Inside the strip's `<details>` block, when the result is a compare mode, render one row per sub-mode showing each mode's individual CO₂e at the saved home intensity (consistent with the per-column inline rows that visitors see above). Sits alongside the existing reference row, comparison rows, historical rows, and live-mix breakdown. Gated on the strip being passed enough context to know it's a compare result.

Mechanically: extend `wlCarbonStrip` signature with an optional `subRuns` array — `[{label, grams, deltaWh}, ...]` — and have the strip render a "Per-mode breakdown" sub-section in the details block when present. Existing single-run call sites pass `null` and behave unchanged. Compare-mode call sites construct the array from their per-mode energy blocks. Keeps single-run scope unchanged; opt-in for compare modes.

### Cost / leverage

~half a day:
- Extend strip signature (~10 min)
- Render the new sub-section inside `<details>` (~30 min)
- Update 5 compare-mode call sites to construct the array (~1 hour)
- Visual verification on each (~1 hour)
- Tests / sanity checks (~30 min)

Leverage: closes the "what about the others?" gap on every compare-mode result page. Especially valuable for `all_codecs` (6 sub-runs) where the strip currently elides 5/6 of the work the visitor just ran.

### Watch-outs

- **Don't bloat the headline.** Per-mode rows live inside the dropdown, not above. The headline stays "best of N" with the most-efficient mass — that's the right takeaway number.
- **Use saved intensity for consistency.** Per-mode rows should compute mass from each sub-run's `energy.co2e.grams` (already saved at /carbon snapshot time), so they agree with the per-column inline rows above. Don't recompute from current live intensity — that diverges, and CR-030's drift-note already covers that case for the headline.
- **Sort order.** Most-efficient first (matches the headline framing) or stable-by-mode (matches the page order above)? Lean: most-efficient first, since the strip is the carbon-perspective rendering — sorting by carbon footprint is internally consistent.

### Open questions

- Should the per-mode rows also show the projected (24/7 toggle) values when the toggle is on? Probably yes — the projection multiplier is page-wide via the URL hash, so applying it consistently across all rows is the least-surprise behaviour.
- Should non-compare strips (single-run) get any analogue? Not in scope; the inline `wlCarbonRow` above already shows the per-run CO₂e for single results.

---

## Caught during the session but **not** new CRs

For the record, several items came up that don't warrant new CR entries:

- **Bug: `/settings` page rendered empty mid-run** (~T+338s) — owner observed this when trying to demo settings during a queued calibration. Filed as a bug to investigate, not a CR. May be related to job-state machine showing the page in a transient state. Repro: start a calibration, immediately reload `/settings`.
- **Confidence multipliers (5× / 2×) need statistical grounding from Tanya** — see **CR-028 Phase 2** (the unified statistical model is where this lands).
- **Codec apples-to-apples equivalence (GOP, profile)** — see **CR-029** sub-item 2 (Tania's CPU-vs-GPU encode-parameter validation).
- **Long-term mash-up of REM + OWL data for 100s of homes** — covered as the post-conference phase of CR-008. No separate CR.
- **"Counter for OWL's own compute footprint"** (Dom, ~T+3319s, in passing) — fun meta-toy, not load-bearing. Skip.
- **The 5-minute training narrative was generated mid-meeting** — captured separately if needed. No CR; deliverable not infrastructure.

**From team meeting 2026-05-04:**

- **GPU variance broken at calibration time** (item 10, originally tagged Bug Medium) — turned out to be a settings tweak, not a bug: `gpu_encode_max_s` was set too short for the variance calibration's sampling window. Bumped from 30 to 90 inline. Not a CR. *Resolved 2026-05-05: overnight n=24 calibration confirmed GPU CV at 4.77% (clean, statistically real); idle 2.41%, cpu 1.33%. CR-028 open question closed; Phase 2 design session with Tania has a clean number as input.*
- **Carbon philosophy / scoping board agenda** (item 25) — strategic discussion item, not engineering work. Belongs on a board agenda, not in CRs.
- **GosOne → OWL name pass** (item 33) — doc/comment audit. Trivial sweep across stale references; do inline whenever convenient. Not a CR.
