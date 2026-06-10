# OWL Change Requests

Active design / change requests. Each entry has a status, a problem statement, the agreed direction, and any open questions. Implementation lives in JOURNAL.md once it lands.

**Closed CRs live in `CHANGE_REQUESTS_CLOSED.md`** — once a CR's headline scope ships, it moves there with the original problem statement preserved and a Status line naming the closing commit.

---

## Design principle (standing): preserve the lab look & feel

OWL was designed as a **lab tool first** — dense, fast, neutral, no marketing chrome. Every CR that adds UI elements (badges, headers, comparison rows, advisory copy, charts) must consciously preserve that: keep elements compact, default-collapsed when supplementary, monospace where it earns it, no decorative animation. The risk is real and stated by the owner (2026-05-11): *"as we add more and more info on the UI, it loses its LAB look & feel that must always allow for quick use."* Each UI-touching CR carries a "Lab look & feel constraint" line — when in doubt, hide it behind a `<details>` block, push it to `/methodology`, or cut it. Density audits are a hard gate at PR review; CR-034 (unified results card) is the natural place to enforce them across surfaces.

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

### Cross-references (added 2026-05-27)

- **CR-054** (findings catalog): the deliverable line above offered "methodology sub-section, separate `/grid-variance` page, or one-off white paper" — once CR-054 ships, the natural answer is **a finding** (`docs/findings/grid-variance-fr-2026.md`). The `/grid-variance` page option dissolves into the finding page; the white paper becomes the finding's analysis prose.

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

**Status:** **Low priority (downgraded 2026-05-28 — owner: "we won't be going there for a while").** Originally captured 2026-05-04 (Session 21) as exploratory; upgraded to confirmed direction by team meeting 2026-05-04 (item 30). Tagged "maybe" because the wins are bounded by the current P110 API resolution; the meeting agreed to pursue regardless because "Ubuntu focus mode may not suppress background activity enough" and the RT investigation creates a path to higher-resolution sensor work later. **Must not interleave with the CR-060 GPU swap** — RT + a card swap together would confound the AMD↔Nvidia comparison, and PREEMPT_RT independently risks ROCm/VAAPI. Revisit well after the swap.
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

## CR-029 · Encoding rigor pass (apples-to-apples credibility)

**Status:** captured 2026-05-04 (post-meeting). High priority. **Now the immediate priority (2026-05-28):** §2's encode-parameter decisions gate the CR-060 AMD baseline — a video benchmark captured on parameters §2 is about to rewrite would be stale, so §2 must be settled *before* the night-time AMD baseline run. Bundles items 18, 19, 20, 21, 22, 23 — Tania's video credibility workstream. Coherent because each item is a step in the same chain: *what is each encoder actually doing → are CPU and GPU comparable → can we present it cleanly*.
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
   - **Progress (2026-05-28):** partially shipped — `/methodology` already carries the ABR apples-to-apples framing + two explicit GOP/profile-equivalence open-items (`main.py:11368`, `:11406`). `WATTLAB_SPEC.md` §2.4 was **stale** (listed CRF/QP + `libaom-av1`; code has run ABR + `libsvtav1` since S13) and was **corrected 2026-05-28**. Remaining: the full per-codec pipeline subsection.
2. **Validate CPU vs GPU encode parameters** (Tania-led). For each codec, compare what the CPU and GPU encoders actually produce: profile, level, B-frames, GOP, refs, slices. Write findings to `WATTLAB_SPEC.md` and adjust commands as needed to bring them into apples-to-apples shape (or document explicitly where they can't be).
   - **VMAF already exposes a concrete instance to chase down (2026-05-22, clean 🟢 run `e18a9d57`):** at the same 1500 kbps AV1 target, `av1_vaapi` (hw) hit the target (20.34 MB) while `libsvtav1` (sw) undershot to ~967 kbps (14.51 MB) yet scored *higher* VMAF (92.74 vs 90.79). So "same bitrate target" is not being honoured equally across encoders, and the hw encoder is less bit-efficient. This is exactly the apples-to-apples gap this item is meant to characterise — the VMAF axis (CR-044) now makes it measurable. See CLAUDE.md Key Findings (AV1 hardware vs software).
   - **Measured audit (2026-05-28 — ffprobe on 12s `meridian_120s` encodes, ABR ladder 4000/2000/1500).** The presets are bare (codec + bitrate + scale + audio; **no `-g` / `-bf` / `-profile` / `-level` / `-refs` anywhere in `video.PRESETS`**), so GOP and B-frame structure are encoder-defaulted and diverge systematically:

     | Preset | Profile | Level | GOP (keyint) | B-frames |
     |---|---|---|---|---|
     | libx264 (CPU) | High | 4.2 | **249** | max 3 (has_b 2) |
     | h264_vaapi (GPU) | High | 4.2 | **120** | max 2 (has_b 1) |
     | libx265 (CPU) | Main | 4.1 | ~250 | uses B (has_b 2) |
     | hevc_vaapi (GPU) | Main | 4.0 | **120** | **none (has_b 0)** |
     | libsvtav1 (CPU) | Main | 4.0 | **321** | none (AV1 alt-ref) |
     | av1_vaapi (GPU) | Main | 4.0 | **120** | none (AV1 alt-ref) |

     Headline gaps: **(a)** every VAAPI encoder defaults to **GOP 120**; every CPU encoder runs 2–2.7× longer (x264 249 / svtav1 321 / x265 ~250) — a driver-vs-library default split consistent across all three codecs. **(b)** `hevc_vaapi` uses **zero B-frames** while `libx265` uses them; H.264 B-depth differs (CPU 3 / GPU 2). **(c)** profiles align across the board; H.265 level differs slightly (4.1 vs 4.0). **(d)** scalers differ (`scale` libswscale on CPU vs `scale_vaapi` on GPU). These explain the cross-CPU/GPU VMAF gaps — e.g. AV1 **92.29 (CPU) vs 81.48 (GPU)** at near-equal file size on BBB (run `a4332530`), an 11-point gap driven by encoder internals + content, not bitrate. **The fix: pin `-g` / `-bf` / `-profile` / `-level` (and force B-frames on `hevc_vaapi`) across all six presets, or document each residual gap.** This doubles as a **CR-060 requirement** — NVENC's defaults differ again, so bare presets would float the AMD↔Nvidia comparison on three different driver defaults.
     - *Method caveat:* per-frame `pict_type` is reliable for H.264 but not populated for HEVC/AV1 via ffprobe's CSV path, so the H.265/AV1 B-frame/GOP figures lean on `has_b_frames` + packet-keyframe counting. §3's ffprobe-on-output (now wired) makes GOP codec-agnostic by deriving it from packet keyframe flags.
   - **Decision taken (2026-05-28 — provisional, pending Tania's review).** We can't gate the GPU-swap baseline on Tania's availability, so a defensible normalization was chosen now, validated on real encoders, with a one-line update path:
     - **GOP — pinned & normalized (the big win).** Settings key `encode_gop_frames` (default **120** = 2 s on the 59.94 fps Meridian, a streaming-standard segment length), applied identically to all six presets; CPU encoders also get **closed GOP + scene-cut disabled** (`scenecut=0:open_gop=0` / `open-gop=0` / SVT `scd=0`) so the cadence is *exactly* the setting. Validation: all six now produce GOP avg=max=120 (was 249/250/321 CPU vs 120 GPU). Pure win, low risk.
     - **Profiles — pinned explicit** (H.264 High, H.265/AV1 Main). Already aligned by default; pinning locks them against driver/lib drift. Zero behaviour change.
     - **B-frames — documented as a hardware limit, not normalized.** `-bf 2` is *requested* on H.264/H.265, but AMD VAAPI caps it (validation: `h264_vaapi` reorder depth **1**, `hevc_vaapi` **0**) while the CPU encoders honour 2. This is a VAAPI pipeline limitation the flag can't beat — so the CPU encoders retain a B-frame compression advantage the GPU paths *structurally cannot match*. This is itself a finding (part of why VAAPI is less bit-efficient), surfaced per-result in `stream.has_b_frames`. Not a settings choice; flagged for Tania to confirm she's happy treating it as a documented residual rather than dropping the GPU B-frame request entirely.
     - **Level — left as-is.** The H.265 4.1 (CPU) / 4.0 (GPU) split is cosmetic at 1080p and forcing `-level` on VAAPI is fragile. Documented residual.
     - **Update path:** GOP → `settings.json` `encode_gop_frames`; everything else → **one function, `video._norm_args`**. When Tania revises any value: change there, **re-run variance calibration** (the calibration workload is `video.PRESETS`, so the existing `variance_*_pct` are now stale and must be re-measured), then re-capture the AMD baseline. This re-bases all video numbers vs pre-2026-05-28 results — intended (that's the point of §2).
     - **Implemented:** `video._norm_args` + `encode_gop_frames` setting; tests in `tests/test_encode_norm.py`; full suite green.
3. **Verify sample output files.** Pick at least two recent encodes per codec. Inspect with `ffprobe -show_format -show_streams` and `mediainfo`. Confirm: bitrate matches target, codec matches command, profile/level reasonable, file size in expected range. Once-off audit; capture findings.
   - **Progress (2026-05-28): ✅ wired as a standing pass, not a once-off.** `video.probe_output_stream()` runs as a terminal ffprobe after each encode's measurement window closes (alongside `output_size_mb`, so its draw never enters an energy figure); result JSON now carries a `stream` block per encode — actual codec / profile / level / pix_fmt / bit_rate / `has_b_frames` + GOP (avg/max, from packet keyframe flags, codec-agnostic).
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

### Cross-references (added 2026-05-27)

- **CR-054** (findings catalog): §1's `/methodology` documentation becomes the `methodology_ref` target for video findings. §2's CPU-vs-GPU validation work, if it changes the AV1 numbers, ships as a new finding version (`av1-hw-sw-vmaf-tradeoff-v2.md` with `supersedes: av1-hw-sw-vmaf-tradeoff`) — CR-054's versioning primitive is designed for exactly this case.
- **CR-060** (added 2026-05-28): §2 is the load-bearing gate on the CR-060 AMD baseline. The cross-card (AMD↔Nvidia) comparison freezes the video encode commands; if §2 rewrites them after the baseline, the night's run is stale. Lock §2's parameters into the suite before capturing the AMD baseline. See CR-060's baseline-integrity gate.

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

### Update 2026-05-11 (board meeting context)

Board reinforced sub-section 3 (containerisation) as the path to data-centre hosting on a friendly partner's rack (Linode, or Mike's Akamai offer of an open-rack slot in Virginia with 100% renewable cover). Two constraints surfaced that grow sub-section 2:

- **1 s power-measurement granularity is a hard portability constraint.** Many PDUs poll at 1 min or coarser — they can't replace the Tapo P110 without losing measurement fidelity. Sub-section 2 must include a *meter-resolution declaration* on every backend, and the confidence flag must visibly degrade when the backend's resolution is coarser than the task's duration ("you cannot be 🟢 on a 4 s encode measured by a 60 s meter"). This is **resolution-aware confidence**, a required behaviour of the abstraction, not a watch-out.
- **Utility-grade meter + PDU per-plug meters in series** (Mike). A contained-rack deployment is one utility-grade meter on top of the rack plus PDU meters per plug for component attribution. The backend interface should be expressive enough to represent that stack — one primary reading plus N attributable sub-readings — not just `get_power_watts() -> float`.

Net: sub-section 2 grows from ~half day to ~1 day. Sub-section 3 lands on Mike's facility if/when the offer materialises; nothing about CR-031 changes in shape, but the timeline becomes externally-driven.

---

## CR-039 · Energy-vs-quality axis for AI jobs (frontier-model-as-judge — exploratory)

**Status:** captured 2026-05-11 (board meeting). **Exploratory** — owner's idea, mixed reception; ship behind a Member/Lab gate, frame explicitly as a snapshot not a leaderboard. **Easy to drop** if the answer to the CR-029 §6 tension below is "don't."
**Triggered by:** GoS board meeting 2026-05-11. Ben: *"use a frontier model. We'd have to have a teeny weeny budget for some tokens to ask really cheap local models simple questions, then send them to a frontier model and have a frontier model score them. So you could say, OK, you're using ten times less energy for a ten times smaller model, but the answer is only ten percent less good."* Mike: standardise on a model and evolve. Tania (cautionary): *"I would seriously hesitate getting into measuring the energy consumption and sustainability of AI… we're going to be really out of our depth really quickly."* Tania's concern is energy-of-AI; this CR is **quality-of-AI** — the orthogonal axis the paper itself calls out as missing (*"what constitutes useful work?"*).

### Problem

OWL's LLM/RAG Compare views report energy and duration cleanly but say nothing about answer quality. So a visitor sees *"TinyLlama: 0.061 mWh/token, 15× less than Mistral"* — and walks away thinking small models are obviously the answer. CLAUDE.md Key Findings already flags the counter-evidence: *"TinyLlama hallucinated 'REM is a framework provided by the European Commission'… Gemma and Phi-4 stayed faithful."* The energy story without the quality story is misleading. The board explicitly raised this gap.

### Agreed direction (exploratory)

A frontier-model judge that scores cheap-local-model answers so the Compare views show **energy × quality** rather than energy alone. Ship behind capabilities (Member + Lab — needs API budget); frame as a *snapshot of the ratio today*, never a leaderboard.

1. **Capability + settings:** new `AI_QUALITY_JUDGE` capability (Member-tier by default), `judge_provider` and `judge_model` settings (default to a single named frontier model — Mike's "standardise and evolve" point), `judge_token_budget_per_day_usd` cap enforced server-side per visitor key.
2. **Judge protocol:** for each candidate answer, send the prompt + the answer + a fixed rubric to the judge with low temperature; parse a 1–5 quality score + a one-line rationale. Same rubric across all judged runs in a comparison; rubric pinned in source so it's auditable and versioned.
3. **Surfacing:** Compare result rows gain a "Quality (judged)" column showing score + rationale-on-hover. Verdict line (CR-038) gains an optional second clause: *"…and answers scored 4.6/5 vs Mistral's 4.8/5 — ~4% quality loss for ~15× energy savings."* Hidden entirely when judging is off.
4. **Provenance preserved.** Result JSON gains `quality.judge_model`, `quality.judge_score`, `quality.judge_rationale`, `quality.judge_run_at`, `quality.rubric_version`. The score is always paired with which judge produced it, on what date, against which rubric — so nobody can quote *"OWL scored TinyLlama 4.6"* a year later without that context.
5. **Snapshot, not leaderboard.** Header copy on the Compare views: *"Quality snapshot — frontier-model judgement as of [date]. Models drift; this is one ratio, one judge. See `/methodology` for the rubric."* No persistent rankings page.

### Lab look & feel constraint

One column added to the compare table; one optional clause on the verdict line; hidden entirely without judge access. No dashboard, no leaderboard page.

### Cost / leverage

~2 days:
- ~3h: capability + settings + budget cap + rubric source-pinning.
- ~4h: judge call wired into LLM and RAG compare flows (gated path).
- ~3h: result-card surfacing + JSON provenance fields + tests.
- ~2h: methodology subsection on the rubric + the "snapshot not leaderboard" framing.
- ~2h: a small CLI to retroactively judge stored historical results (one-shot, useful for backfilling without re-running them).
- ~2h: visual + look & feel review.

Leverage: turns the LLM and RAG Compare views from "small is cheap" into the actual story — *"small is cheap, here's how much quality you trade for it."* Partially answers the paper's "what constitutes useful work?" open question.

### Watch-outs

- **Tension with CR-029 §6 ("External PQA, not internal").** That principle was about *video* PQA, where industry has external benchmarks (Netflix VMAF). Internalising video quality scoring would be a credibility liability. **AI quality scoring has no equivalent external authority OWL can point at** — University of Michigan's `ml.energy/leaderboard` measures energy only; LMSYS and Hugging Face quality leaderboards are general-purpose, not streaming-anchored. So CR-039 doesn't *violate* CR-029's spirit, but it sits adjacent to it and the carve-out must be explicit on `/methodology`: *"we don't do PQA on video output because Netflix-class references exist; we do a quality snapshot on LLM output because no equivalent external authority exists for the streaming-adjacent AI workloads we measure."* **If owner disagrees with the carve-out, drop CR-039 entirely** — the principle of leaning on external authorities is more important than the column.
- **Judge bias.** A frontier model judging smaller models inherits the judge's own training-data bias. Document this on `/methodology`; pick a judge from a different provider than the candidates where possible (avoid "OpenAI judges OpenAI"). Periodic sanity check with a second judge family; surface divergence if scores diverge meaningfully.
- **Cost spiral.** The budget cap is non-optional. Without it, an enthusiastic Member could rack up real money. Cap enforced server-side per visitor key per day.
- **Staleness.** Models update on weeks-months cadence. The "snapshot date" in the header copy is the single most important framing; don't let it get stale. A periodic refresh of canonical snapshots (same judge, same rubric) keeps the displayed ratios fresh.
- **The cautious voice on the board is on record.** Tania's hesitation was about AI *energy*, not AI quality; CR-039 doesn't trip that exact wire — but the framing must distinguish them crisply or visitors conflate them.

### Cross-references

- **CR-029 §6:** principle-tension noted above; resolved (or rejected) by owner judgment.
- **CR-037:** the streaming-tethered framing for LLM/RAG. Quality scoring lives on those tethered pages, not a generic `/ai-judge`.
- **CR-038:** the verdict line is the natural surface for the quality clause.

### Priority: medium (exploratory) — sequence after CR-037 and CR-038, or drop.

If CR-037 and CR-038 land first, CR-039 reads as natural continuation. If they don't, it risks reading as a quality leaderboard out of nowhere.

---

## CR-041 · New-vs-aged silicon benchmark (chip-instance comparison)

**Status:** captured 2026-05-11 (board meeting). Low priority — opportunistic research finding.
**Triggered by:** GoS board meeting 2026-05-11. Dom: *"from what I understand, CPUs and GPUs — their thermal performance changes with age, and it might be interesting if we could get a comparable chip, a new comparable chip, and maybe Mike could pull one out of one of their recycled bins at the back of Akamai. But it might be worth comparing a brand new chip and one that's been absolutely hammered in a data centre at some point — just because it's yet another interesting statistic that you could benchmark in there."* Mike was warm to the idea.

### Problem

OWL's canonical findings are all from one chip instance (GoS1's Ryzen 9 7900 + RX 7800 XT, ~18 months old, sitting-room ambient). Whether those numbers generalise to a *data-centre-aged* chip — same SKU, same kernel, but hammered for years — is unknown. CLAUDE.md memory already flags the *ffmpeg* version analogue ("software-aging energy comparison"); this is the hardware analogue. Both speak to the same generalisable insight: *small changes to the run environment shift energy meaningfully, and the streaming industry tends to forget that.*

### Agreed direction

When a comparable chip becomes available (Mike's offer; or any donated/decommissioned matching SKU), tag results by `chip_instance` and publish the new-vs-aged delta as a one-off finding. The only code change ahead of chip access is a new `chip_instance_id` field on the result JSON + hardware-fingerprint surfacing on the result card.

1. **Settings:** `chip_instance_id` string in `settings.json` (free-form: `"gos1-original-2024"` / `"akamai-recycled-2026-05"`). Defaults to a generated UUID with a friendly suffix.
2. **Result JSON:** `hardware.chip_instance_id` written into every result alongside the existing `cpu` / `gpu` fields.
3. **Comparison helper:** a small `/findings/chip-aging` page (Lab-only) that walks results across `chip_instance_id` values and renders the delta on the canonical Meridian benchmark.
4. **Discoverability:** when a new chip_instance appears in stored results, a one-line "chip change detected" note on `/queue-status` so the operator confirms before publishing comparison numbers.

### Lab look & feel constraint

One field on result JSON (invisible to most visitors), one Lab-only findings page. Public visitors see no new UI unless the canonical Key Findings table is later updated with a "new vs aged" row.

### Cost / leverage

~half a day for instrumentation; the experiment itself depends on chip availability. Without chip access, this CR is captured-only.

- ~1h: settings field + result JSON wiring + tests.
- ~2h: `/findings/chip-aging` page (Lab-only, simple table — graph deferred to CR-004 territory).
- ~1h: documentation on `/methodology` once the first finding lands.

Leverage: low until a chip exists. When one does, the finding is a sharper version of CLAUDE.md's existing "software changes shift energy" story. Pair with the ffmpeg-version energy test (existing memory note) for a running theme: *"the lab numbers are good; here are the things that move them."*

### Watch-outs

- **Without chip access, don't ship the instrumentation prematurely.** The result-JSON field is fine to add (forward-compatible), but the `/findings` page should land *with* the first comparison data, not as a placeholder. Empty findings pages erode credibility.
- **Confound: thermal environment.** A chip in a data centre runs cooler and steadier than one in a sitting room. If we compare "aged data-centre chip vs new sitting-room chip", the delta is *aging + thermal environment*, not aging alone. Document the confound; ideally test both chips in the same environment.
- **Confound: power supply.** PSU age also matters. If the aged chip arrives in its original chassis, the PSU is part of the comparison.

### Cross-references

- **CLAUDE.md memory `ffmpeg_version_energy_test.md`:** the software analogue. Land both as a single "things that move the numbers" finding.
- **CR-031:** if OWL is portable, the chip-instance field is the natural multi-deployment merge key.
- **CR-008:** REM ↔ OWL — REM already runs across a fleet; cross-fleet chip-aging data could come from REM rather than from a one-off OWL experiment.
- **CR-054** (added 2026-05-27): when this ships, the output lands as a CR-054 finding (`docs/findings/chip-aging.md` with two `source_result_ids` — original GoS1 + donated chip), **not** a bespoke `/findings/chip-aging` page. The "walks across instances" comparison lives in the finding's analysis prose, not a separate route. Keeps the catalog's "one renderer for all finding pages" invariant intact.

### Priority: low (opportunistic). Stays captured until a chip arrives.

---

## CR-043 · Input/output video preview in the result card (defer until CR-039 lands quality plumbing)

**Status:** captured 2026-05-14. Deferred — re-evaluate once CR-039 (energy-vs-quality axis) lands its retention plumbing.
**Triggered by:** owner question — "what's the feasibility of a video display in the results card? optional, input and output side by side in a dropdown — the 4K→HD downscale might be visible."

### Problem

The result card today is metrics + carbon strip + scope notes — no media. A visitor reading "GPU used 81% less energy than CPU on H.265" has to trust that the two encodes produced equivalent output. Showing the actual transcoded video (or at least the input) would make the energy claim visceral and answer the implicit "is this still good enough to ship?" question that comes up around every codec-comparison number.

### Why this was deferred, not built

The pushback that landed it here:

1. **The "4K→1080p downscale" intuition doesn't survive contact with the presets.** Every preset already runs `-vf scale=-2:1080` on both CPU and GPU paths. A side-by-side player would not reveal that downscale — both sides are downscaled identically. What it *would* reveal is the codec-engine delta (libx264 vs h264_vaapi at the same ABR), which at 1080p in a browser tab is usually too subtle to see without still-frame zoom or a proper PSNR/VMAF treatment.
2. **Retention is a lifecycle flip.** Today `run_job(..., delete_after=True)` clears outputs the moment metrics are computed. Keeping them needs (a) a scoped-by-`visitor_key` serving route (CR-026 just tightened this), (b) a janitor for disk pressure — a Member `all_codecs` sweep retains six files at ~4 Mbps × N min = multi-GB per run, (c) per-tier retention policy. None of this is hard individually, but it's a small system, not a one-file change.
3. **The "quality" question already has a home.** CR-039 (frontier-model-as-judge / energy-vs-quality axis) is the right place for a structured quality treatment of all the comparison results, and it will need its own output-retention plumbing anyway. Building a generic dual-player here forks the retention machinery before CR-039 has set its shape.

### Cheap-fallback option (~15 lines, if owner ever wants the visceral beat sooner)

**Input-only preview, preloaded sources only.** Three fixed known files in `test_content/`, served via the existing `/video-enhance/asset/` allowlist pattern (extend the allowlist). A `<details>` block on the result card lazy-mounts a single `<video>` element when opened. No retention changes, no per-job scoping, no janitor — because nothing new is stored. The visitor sees what went into the encoder, which is the lesser half of the comparison but the *only* half that scales without a retention rebuild.

### Agreed direction (when picked back up)

Ride on CR-039's plumbing once it lands:

1. Reuse CR-039's per-job output retention (it needs the encoded artefact for any quality-judge pass anyway — PSNR/VMAF/LLM-judge all consume the actual encoded file).
2. Reuse its serving route (visitor_key-scoped) and its janitor.
3. The dual-player UI then becomes a thin add: a `<details>` on the card, two `<video>` elements with synchronised seek, lazy-mounted on open. Audio off by default. Add a "freeze frame at t=" picker to make codec-engine artefacts visible — that's where the eye actually sees the delta.
4. Gate behind a per-result `keep_output` flag so most runs still default to `delete_after=True` and don't pay the disk cost.

### Watch-outs

- **Don't ship retention without a janitor.** Even with the Member `queue_member_cap=4` and Anonymous `queue_anonymous_cap=1`, a busy day stacks GB-scale residue fast. Hours-old auto-purge is fine; the visitor's window for "still useful preview" is short.
- **Don't serve outputs via a guessable URL.** Per-`visitor_key` scoping + token in URL, not just job_id.
- **The 4K→1080p framing was misleading** — see above. If the eventual UI ships, name and frame it as "codec-engine comparison preview," not "see the downscale."
- **Mobile-data viewer concern:** if a visitor opens the result card on a phone and the dual-player auto-loads, that's tens of MB streamed without consent. Lazy-mount on `<details>` open, and label the disclosure.

### Cross-references

- **CR-039** — owns the retention plumbing this CR rides on. Don't build before CR-039 sets its shape.
- **CR-029** — encoding rigor / apples-to-apples GOP+profile work. A dual-player without CR-029's validation is just two videos that *look* similar; the rigor pass is what makes the comparison meaningful.
- **CR-026** — anon-integrity pass that explicitly scopes own-jobs by `visitor_key`. Any output-serving route must honour this.

### Priority: deferred. Re-evaluate when CR-039 picks up.

---

## CR-045 · "Same Bitrate / Same Quality" toggle on the all-codecs comparison

**Status:** captured 2026-05-22 (owner idea). Rides on the VMAF axis (CR-044, shipped). Sequence after / alongside CR-029.
**Triggered by:** owner — *"the compare-all-codecs button could have a toggle: Same Bitrate OR Same Quality."*

### Problem / opportunity

The all-codecs comparison runs **ABR at a fixed per-codec bitrate** ("Same Bitrate"): it answers *"at this bitrate, which codec/device is most efficient, and what quality results?"* That's one of the two questions operators ask. The other — the one that actually drives codec adoption — is the inverse: *"to deliver **this** perceptual quality, which codec/device uses least energy?"* Modern codecs (H.265, AV1) earn their keep precisely here: same VMAF at lower bitrate. Now that VMAF ships on every comparison (CR-044), OWL has the missing half of the picture and can offer an iso-quality mode. This is the iso-quality sibling of CR-003 (iso-energy), surfaced as a clean UX toggle on the existing button.

**Already visible (motivating data, 2026-05-22 clean 🟢 run `e18a9d57`):** at the same 1500 kbps target, `av1_vaapi` (hw) scored VMAF 90.79 in a 20.34 MB file while `libsvtav1` (sw) scored 92.74 in 14.51 MB — VMAF already exposes that the cross-codec/-device comparison is happening at different *effective* quality. A "same quality" mode is what turns that into a fair, operator-facing answer. See CLAUDE.md Key Findings (AV1 hardware vs software).

### The rigor gotcha (must be designed in, not bolted on)

**"Same Quality" is harder than it looks, and the label has to be honest** — straight into GoS's own "if it can't be measured, it shouldn't be asserted":

- The cheap implementation is to swap ABR for **CRF / CQP constant-quality** rate control. But CRF values are **not comparable across codecs** — libx264 CRF 23 ≠ libx265 CRF 23 ≠ SVT-AV1 CRF 23 ≠ VAAPI `qp`/`global_quality`. "Same CRF" is **not** "same quality." A button labelled "Same Quality" that just sets equal CRF asserts something untrue.
- **True** same-quality = **same VMAF**, which ffmpeg cannot target directly. It needs a per-codec **bitrate search** (encode → measure VMAF → adjust → re-encode, ~3–5 passes), i.e. N× the encodes (and N× the energy/time). VMAF (CR-044) is exactly the instrument that makes the search possible.

### Agreed direction — two honest designs, not one mislabelled button

1. **V1 — "Constant quality (per-codec)".** Native CQ rate control per encoder (CRF for libx264/libx265/SVT-AV1, `qp` / `global_quality` for the VAAPI encoders). The VMAF column (CR-044) is shown prominently so the visitor *sees* the resulting quality is close-but-not-identical across codecs — the honesty is in surfacing the real VMAF, not in claiming equality. This is essentially the long-deferred **"Benchmark 2 — codec-natural rate control (CRF/QP)"** from the roadmap. Cheap: same number of encodes as today.
2. **V2 — "Match quality (target VMAF)".** The rigorous iso-VMAF version: binary-search each codec's bitrate to hit a target VMAF ± tolerance, then report the energy to deliver it. Bigger build (N× encodes, search loop, abort/convergence guards, much longer wall-time — keep VMAF scoring as the terminal pass per CR-044 so the search encodes don't pollute energy readings of the *final* accepted encode).

UX: a two-state toggle on the all-codecs control — `Same bitrate` (today's ABR, default) / `Constant quality` (V1) — with V2 as a later third state once it exists. The result card's framing line and the carbon/energy headline must state which mode produced the numbers.

### Cost / leverage

V1 ~1 day (new preset variants with CRF/QP + a mode flag through `run_all_measurement` + result framing). V2 ~2–4 days (search loop + convergence handling + longer-run UX). Leverage: high — answers the codec-adoption question directly and showcases the VMAF axis. The energy-vs-quality story becomes "AV1 delivers VMAF 93 at X Wh vs H.264 at Y Wh," which is the headline operators care about.

### Cross-references

- **CR-044** (VMAF) — the enabling measurement; V2's search loop consumes it.
- **CR-029** (encoding rigor) — overlaps heavily: defining "equivalent quality" (GOP/profile, the CRF-isn't-comparable point) is Tania's apples-to-apples territory. **Sequence CR-045 after/with CR-029** so encode-parameter changes aren't re-validated against a moving target.
- **CR-003** (iso-energy bitrate sweep) — the mirror-image axis (fix energy, vary quality).
- **"Benchmark 2 — codec-natural rate control (CRF/QP)"** (CLAUDE.md deferred / WATTLAB_SPEC) — V1 *is* this, surfaced as a toggle.

### Watch-outs

- **Never label CRF-equal as "Same Quality."** Call V1 "Constant quality (per-codec)" and let VMAF show the spread.
- **VMAF stays a terminal pass** (CR-044) even inside V2's search, so the accepted encode's reported energy excludes all the search re-encodes' draw.
- VAAPI CQ rate control differs by driver/codec — verify `qp` vs `global_quality` behaviour per `*_vaapi` encoder during V1.

### Priority: captured; gate V1 behind (or run alongside) CR-029. V2 is a later, larger follow-up.

---

## CR-057 · Home page repositioning — findings-first landing

**Status:** **Captured 2026-05-27 (S32 close-out).** Drafted as the last remaining flow change in the findings chain. Code untouched. **Awaiting lab UX review before implementation** — touches the most-visited surface, so the design risk is higher than the mechanical lift. Depends on CR-055 + CR-056 (both ✅ shipped). Will ride the existing `findings_enabled` flag for byte-identical rollback.
**Triggered by:** S32 UX-strategy thread (2026-05-27) — *"an Anonymous visitor reading a finding card and quoting its number in a Slack thread is exactly what GoS wants from OWL — credibility flywheel + member-recruitment loss-leader. Running a job is bonus, not core. Today the UX inverts this: workbench front and centre, findings buried."* Once the catalog exists (CR-055) and has more than one entry (CR-056), the home page is the natural surface to express the inversion.

**Lab look & feel constraint:** central, and the design risk this CR carries. "Findings-first" must not read as a marketing pivot. The page must remain dense, monospace, telemetry-anchored, with zero decorative animation and zero hero copy. The live watts + thermals hero stays — telemetry IS the lab vibe, and removing it would lose what makes OWL credible in the first 200 ms a visitor sees the page. The risk to manage is "more sections + more rows" sneaking density loss into a high-traffic page — see also the standing design principle at the top of this file.

### Problem

Today's `/` for Member/Lab visitors is a *bench launchpad*: live watts hero, then "◆ Guided Tour / ▶ Video transcode / Beta cards (image / llm / rag / video-enhance) / utility links" (`wattlab_service/main.py:~2657-2680`). Anonymous visitors don't even reach this page — they're redirected to `/demo` (CR-001 / CR-026, gated on `WORKING_NAV`).

Neither path surfaces the findings catalog. Per the S32 strategic thread, OWL's stated audience (CTOs / operators / policymakers — see CLAUDE.md "GoS Framing") reads findings rather than runs benches; the front door inverts that intent. CLAUDE.md also flags this implicitly: the "Findings step" of the guided tour was redesigned in CR-058 specifically because echoing the session run wasn't what visitors needed at that point in the flow — the same logic applies one level up.

The mechanical lift is small (the catalog row component already exists, the data is already on disk, the renderer is JSON-pure). The hard work is the UX decision tree below.

### Agreed direction (subject to lab approval — see Open questions)

Single `/` template, capability-conditional blocks, repositioned around findings. Live telemetry stays at the top; bench-launchpad moves below findings. Flag-gated for clean rollback.

1. **Telemetry hero unchanged.** Live watts + thermals stay exactly as today. This is the credibility primitive; reordering it would be the wrong density loss.
2. **Findings catalog preview** as the next block. Top N findings (N TBD, see Open questions) rendered by the shared `_findings_catalog_rows_html` from CR-055; "See all findings →" link to `/findings`; honest empty-state copy (matching CR-055's empty-catalog contract) if the catalog is empty.
3. **Bench launchpad demoted to a secondary section** below findings. Framing flips from "the bench IS the page" to "▶ Run the bench yourself" — same links, lower visual weight. Beta-card grid stays; utility links stay.
4. **Anonymous visitors see the same `/`**, with the working-nav block capability-gated off rather than redirected away. Findings + a clear "◆ Guided Tour" CTA serve the recruitment role `/demo` carried. The `/demo` page stays accessible; only the redirect retires. **(This is the load-bearing UX call — see Open questions; the CR-001 anonymous-redirect contract may be load-bearing in ways not obvious from CHANGE_REQUESTS_CLOSED.md.)**
5. **`findings_enabled` flag controls the swap.** Flag off → the current home page renders byte-identical (regression test pinned). Flag on → repositioned page. Same rollback contract as CR-054 / CR-055 / CR-056 / CR-058.
6. **One template, never two.** Capability-gated blocks are conditional renders inside one HTML string; never an `if/else` over two near-duplicate pages. The dual-renderer drift bug class is the lesson CR-034 → CR-036 → CR-038 taught — the home page must not reintroduce it.

### Maintainability invariants (extends CR-054 / CR-055 / CR-056 / CR-058 contract)

20. **One `/` template, capability-conditional blocks.** No parallel rendering paths for Anonymous vs Member/Lab. Capability checks gate sub-blocks within the single template.
21. **Findings preview reuses the shared row component.** Same `_findings_catalog_rows_html` as `/findings` and `/demo` step 7. Layout drift between the three preview surfaces is impossible by construction.
22. **Telemetry is non-negotiable on `/`.** Live watts + thermals stay at the top regardless of any future reordering. They are the credibility primitive, not a removable component.
23. **`findings_enabled: false` restores the pre-CR-057 page exactly.** Byte-identical regression test pinned in the suite; no copy drift, no class-name drift, no nav-link drift in the off state.
24. **No new persistence, no new schema.** Same pure-view-over-`findings.list_all()` contract as CR-055.

### Open questions (require lab discussion before coding)

- **How many findings to preview on `/`?** 3 (forces curation, matches the /demo step), 5 (a round catalog feel), or all (turns `/` into the catalog itself and makes the dedicated `/findings` page redundant). Recommendation: 3, mirroring CR-058's `/demo` step.
- **Does the anonymous `/demo` redirect retire?** CR-001 (closed) wired the redirect deliberately, gating on `WORKING_NAV`. The contract memory ([access_tier_bundle](file: /home/gos/.claude/projects/-home-gos-wattlab/memory/access_tier_bundle.md)) says *"routes never compare tiers; business modules stay tier-blind"* — the redirect itself is the only tier-aware route in the codebase. Retiring it pushes the gating into the template (sub-blocks rendered conditionally on `WORKING_NAV`), which is consistent with that contract, **but the recruitment role `/demo` plays for first-time anonymous visitors is real and shouldn't be lost in the refactor.** Lab decides.
- **Where does the Guided Tour CTA live on the new `/`?** Top of the page (lead with the call-to-action, matches the current `◆ Guided Tour` button position) or below findings (lead with substance, then offer the walk-through). Recommendation: top, beside the telemetry hero — same visual weight as today.
- **Does the bench-launchpad nav stay full-width** (current shape, one card per bench) **or collapse** to a single "▶ Run a measurement" link that expands? Recommendation: stay full-width. Collapsing it would lose the Beta-card framing that surfaces image / llm / rag / video-enhance.
- **Methodology link promotion?** The `/methodology` link is currently a small utility tile. If `/` becomes the publication face, methodology arguably deserves visual parity with findings. Lab call.
- **`/findings` vs `/` overlap.** If the home page previews 3 findings and a "See all findings →" link points at `/findings`, the two pages are close cousins. Are they distinct enough to both exist, or does the home preview eventually subsume `/findings`? Recommendation: keep both — `/findings` stays the deep-link target for citations (stable URL, no telemetry chrome), `/` stays the discovery surface (telemetry-anchored).

### Ship criteria (target — for the implementation session)

- `/` with `findings_enabled: true` renders: telemetry hero, Guided Tour CTA, N findings rows via `_findings_catalog_rows_html`, "See all findings →" → `/findings`, bench-launchpad section below, utility links at the bottom.
- `/` with `findings_enabled: false` renders byte-identical to today (regression test).
- Anonymous visitors see `/` (no `/demo` redirect) if the lab approves the redirect retirement; otherwise the redirect stays and only Member/Lab see the new shape.
- Tests: page renders for Anonymous / Member / Lab without 500; findings preview ordering matches `/findings`; capability-gated blocks render exactly when their cap is held.
- No new persistence files; no new module beyond what CR-054 / CR-055 / CR-058 already added.
- VERSION bumped (one decimal — UI-only change, no methodology shift).

### Cross-references

- **CR-001 (closed):** the anonymous-redirect-to-`/demo` contract lives here. Read before deciding on Open question #2.
- **CR-026 (closed):** the `WORKING_NAV` capability that gates the redirect. The repositioning either pushes the gate into the template or removes the redirect outright — either way `WORKING_NAV` stays the policy primitive.
- **CR-027 (closed):** the capability matrix (Public / Member / Lab) was the original member-recruitment surface; CR-058 preserved it untouched on `/demo` step 7. CR-057 must similarly not collide with it — the matrix stays on `/demo`, not promoted to `/`.
- **CR-058:** the `/demo` Findings step uses the same `_findings_catalog_rows_html` preview pattern this CR proposes for `/`. If the previews diverge in shape, the shared component is the place to update.

### Lab look & feel constraint (restated, because it's the load-bearing risk)

When implementing, the density audit at PR review is non-optional. Concrete tests: open `/` on a 1366×768 laptop screen (typical visitor display); the telemetry hero + Guided Tour CTA + 3 findings rows + bench-launchpad section + utility links must all be visible without scrolling, or the density has slipped. If they don't fit, cut findings preview to 2, or collapse the beta-card row, or both — don't compromise the telemetry hero.

### Priority: **awaiting lab review.**

Smallest-footprint flow change in the findings chain that touches the *most-visited* surface — so the design risk is highest. The mechanical work is ~half a day; the design discussion is the bottleneck. **Not blocking** — CR-057 staying captured lets the rest of the backlog progress; the findings chain still pays off (catalog + worked example + bulk import + /demo rewire shipped) even if `/` never moves.

---

## CR-060 · GPU-backend abstraction (AMD VAAPI/ROCm ↔ Nvidia NVENC/CUDA)

**Status:** **abstraction SHIPPED 2026-05-29 (S35), pre-swap — AMD validated, Nvidia path awaiting the physical RTX 5080.** The software layer is done, tested, and stamping provenance; what remains is hardware validation + the env prereqs (torch wheel, driver) on the actual card. Keep open until the 5080 is in and a re-run confirms NVENC.
**Triggered by:** Pixop conversion (CUDA-only) → planned RX 7800 XT → RTX 5080 swap. Full hardware/strategy context in memory `gpu-swap-nvidia-initiative` + board lazy-consensus email 2026-05-28.

### What shipped (S35)

New `wattlab_service/gpu.py` — `AmdBackend` / `NvidiaBackend` / `NoGpuBackend`, resolved **once at import** into `gpu.BACKEND` (so a card swap + reboot is picked up with zero code edits). Each backend supplies: GPU sensor read (`{gpu_junction, gpu_ppt_w}`), ffmpeg GPU encode pieces (hwaccel args / scale filter / encoder / codec norm args), torch env setup, device label, and a provenance `stamp()`. Refactored consumers: `power.read_sensors_dict` (GPU half → backend; `amdgpu_chip` kept as a back-compat alias), `video.py` (3 GPU presets → `_gpu_cmd()`), `image_gen.py` (env + label), `persist.save_result` (stamps `gpu_hardware`). Methodology Hardware-Disclosure table now dynamic via the `gpu_display_name` setting (curated default preserved). 339 → 385 tests; new `tests/test_gpu_backend.py`.

**Three deliberate departures from the locked design below — flagged, not silent:**
1. **Module named `gpu.py`, not `gpu_backend.py`** (cosmetic).
2. **Auto-detect, NOT explicit config (reverses decision #2).** Owner's S35 instruction was *"swapping a new GPU just requires a reboot"* — explicit config can't satisfy that (needs a settings edit), auto-detect can. Detection order: `nvidia-smi` → sensors amdgpu → none. The explicit-config *intent* is preserved via an `OWL_GPU_VENDOR` env override **and** the per-result `gpu_hardware` stamp. Owner okayed auto-detect 2026-05-29 ("let's go for autodetect… we'll see if it works or whether we were too ambitious").
3. **AMD path proven by a byte-identical-command test (as planned)** — no ΔWh re-baseline (a pure software abstraction's energy effect is imperceptible per owner; see memory `software-abstraction-energy-imperceptible`).

**Open-Q resolved:** `scale_cuda` + `h264/hevc/av1_nvenc` are **already present** in the `ffmpeg-master` build — no ffmpeg rebuild needed. `-rc cbr` valid; `av1_nvenc` has no `-profile` knob (handled). Still pending: torch `+cu12x` wheel + Nvidia driver/CUDA. NVENC commands are a best-effort first cut to validate on the 5080.

**Label pass — partially done:** the authoritative methodology Hardware table is now dynamic. The remaining ~13 scattered "RX 7800 XT"/"ROCm" UI copy strings in `main.py` + `reproduce.py:29` `_HARDWARE["gpu"]` are still static (several also list retired models — fold into a copy refresh, not this CR).

**AMD pre-swap energy baseline frozen:** `docs/gpu_swap_amd_baseline.md` (overnight benchmark `e29ccef7`, n=10 × 6 presets × 2 sources; variance 3.07% warm-ambient; no VMAF that run). This is the reference the 5080's NVENC numbers compare against.

### Problem

Every GPU-touching path in OWL assumes AMD: `video.py` hardcodes VAAPI encoders/filters/device in the `PRESETS` lambdas (~280–365); `power.py` reads AMD lm-sensors keys (`amdgpu_chip()`, `junction`, `PPT`, ~36–71); `image_gen.py` sets the ROCm `HSA_OVERRIDE_GFX_VERSION` env + hardcodes "RX 7800 XT, ROCm" labels. To swap in an Nvidia card — and keep AMD runnable as a future GoS2 reference — the codebase must run on **both**, selectable by config. Because GoS1 is one box with a single P110, an in-place swap makes the card the only variable, so an identical benchmark suite before/after yields the AMD-vs-Nvidia energy comparison for free.

`llm.py` / `rag.py` are already GPU-agnostic (all GPU work is behind Ollama); their only coupling is thermal reads via `power.py`, so fixing `power.py` fixes them.

### Agreed direction

Full design doc: `~/.claude/plans/i-want-to-discuss-cosmic-beacon.md`. Headline decisions (locked 2026-05-28):

1. **Long-term dual-card** — a real polymorphic backend abstraction (new `gpu_backend.py` with a frozen dataclass per card + `current()` resolving the config), not a throwaway migration.
2. **Explicit config** — a `gpu_backend` setting (`amd_vaapi` | `nvidia_nvenc`) in `settings.json` DEFAULTS, **stamped onto every result** beside `owl_version` (`persist.py:51` + `append_history_line` `:75`).
3. **AMD-baseline-first sequencing** — capture the AMD benchmark baseline while the AMD card is still installed, then physically swap and re-run. The abstraction is a pure refactor; its correctness is proven by a cheap **byte-identical-command test** (assembled ffmpeg arg lists match today's literals — no hardware, no measurement re-run) rather than a ΔWh re-validation. Per owner (2026-05-28), a software abstraction layer's effect on measured energy is imperceptible, so this is a correctness check, not a confounder gate.

Seam covers: video encoder/filter/hwaccel/device (VAAPI↔NVENC), torch env + device (ROCm `HSA_OVERRIDE`↔none; device string stays `"cuda"` for both), and GPU sensor resolution (lm-sensors `amdgpu`↔`nvidia-smi`), keeping the returned keys `gpu_junction`/`gpu_ppt_w` stable so `main.py` telemetry + AI modules need no change. Benchmark suite = thin orchestration over the existing `/llm/compare` `/rag/compare` `/image/compare` (CR-048/049/050) + video `all_codecs`; no new measurement code.

Environment prerequisites (not code): rebuild ffmpeg with `--enable-nvenc` (keep libvmaf); swap torch `+rocm6.2`→`+cu12x`; install Nvidia driver/CUDA. Plan two saved driver/venv states for the swap-iterate cycle.

### Baseline-integrity gate (sequencing vs other CRs — folded in 2026-05-28)

The cross-card comparison is only valid if the GPU is the sole variable, so the AMD baseline and the Nvidia re-run must bracket a frozen measurement environment. Constraints found in the 2026-05-28 open-CR sweep, by severity:

- **CR-029 (fix first — the active blocker).** Its §2 encode-parameter audit (GOP / profile / B-frames) rewrites the very ffmpeg commands the suite freezes. Lock §2's parameter decisions *into* the baseline before the night run — don't benchmark a night on params CR-029 is about to change.
- **CR-025 (shelved — now low priority).** RT kernel + CPU isolation + `taskset` in the ffmpeg chain would change measured energy/variance and risks ROCm/VAAPI. Must land well before the baseline or well after the swap, never during.
- **CR-031 §2 (co-design).** Refactors `power.py` into a dispatcher — the same file as this CR's GPU-sensor seam. Design the power-source and GPU-backend abstractions together, or sequence them; don't let two `power.py` refactors collide. Its resolution-aware confidence also changes result labels.
- **CR-024 (verify-neutral).** Shares the measurement spine (`transcode` / `focus_mode` / `LOCK_FILE`). Claims behaviour-neutral; confirm the probe CSVs are unchanged before trusting a baseline captured around it.
- **CR-045 (downstream).** Its V1 CQ presets use VAAPI-specific `qp` / `global_quality`, so they are GPU-backend-coupled and ride on this CR's abstraction to go cross-card (NVENC uses `-cq` / `-rc`). Also entangled with CR-029.
- **CR-041 (reuse).** Its `chip_instance_id` is the sibling provenance pattern to `gpu_backend`; the "compare results across a hardware field" machinery is shared — reuse, don't reinvent.

Two non-CR freezes:
- **Variance calibration:** capture the AMD baseline calibration under normal ambient — NOT during the current Paris heat wave (inflates the floor 2–6×; memory `variance-calibration-ambient-sensitive`). Same constraint as the post-swap Nvidia calibration.
- **`ffmpeg_bin`:** the suite runs on `/usr/local/bin/ffmpeg-master`. The NVENC rebuild (this CR) and the deferred ffmpeg old-vs-new energy test both change that binary — keep them out of the comparison window.

**Not a confounder: this abstraction itself.** Per owner, a pure software abstraction layer's energy impact is imperceptible (see decision #3) — it does not need a re-baseline.

### Open questions

- **`scale_cuda` availability** — needs a cuda-filters ffmpeg build. If absent, the Nvidia scale step diverges (hwupload_cuda or CPU scale) and the pipeline is no longer directly comparable. Decide the Nvidia filter chain explicitly before benchmarking.
- **Sampling semantics** — nvidia-smi `power.draw` (instantaneous) vs AMD `power1_average` (averaged). Document; consider an averaging window for parity.
- **Post-swap obligations** — re-run variance calibration (**not during the Paris heat wave** — memory `variance-calibration-ambient-sensitive`) and supersede AMD-measured findings via the `/findings` `supersedes:` machinery.

### Out of scope (track separately)

- Label-only pass: ~15 hardcoded "RX 7800 XT"/"ROCm" UI strings in `main.py` + `reproduce.py:29` `_HARDWARE["gpu"]` will misreport on Nvidia.
- 7800 XT disposition (sell vs shelve as AMD reference) — see memory.

### Lab look & feel constraint

No new UI surface; the backend chip on a result card (if surfaced at all) is a single token in the existing provenance line. Don't add a card.

---

## CR-064 · /enhance-run revamp — upload, format/resolution controls, generated presets

**Status:** logged 2026-06-10, implementation started same day.
**Triggered by:** June 10 call with Jon (Pixop) + Tania. Jon is decision-maker; HDR stays (over Tania's objection to drop it).

### Problem

`/enhance-run` exposes raw `.args` preset files and fixed staged clips. The call agreed a user-facing flow: upload or pick a clip, choose output format (SDR/HDR) + Super Resolution target (SD/HD/4K), bitrate auto-coupled — preset selected silently. Only 3 hand-written presets exist; the 2×3 combo matrix needs 6, generated rather than hand-authored.

### Agreed direction

1. **No input probe driving the UI** (Jon's simplification): six static combos work on any input — pixop-live auto-downscales when the target is below source. Probe results (w/h/duration/colour-transfer) are stamped on the result JSON as provenance only.
2. **Preset generation:** two colour templates (SDR-out / HDR-out) × `--output-res` (854×480 / 1920×1080 / 3840×2160) × `--cbr` (5000 / 20000 / 35000 — CBR, never user-chosen) → `presets/generated/*.args`. Interim templates derived from Jon's `fhd_709` / `fhd_pq` files (correct for SDR input); swap in his blessed input-agnostic templates when they arrive. Generated presets stamp `preset_origin: generated`.
3. **UI:** Output Format radio (SDR default; HDR + viewing-environment footnote) + "Super Resolution" dropdown (SD / HD default / 4K), bitrate read-only. Flow: select/upload → format → resolution → Run. `<details>` keeps full generated args for transparency. Page label stays "Video Enhancement".
4. **Upload:** Member 1 GB + clip duration ≤ 60 s (ffprobe-enforced; reading of the call's "60 s processing time" — runs are 1×-paced so duration ≈ processing time); Lab uncapped; limits shown pre-upload; Anonymous already excluded by the page gate. Member upload inputs deleted after the run (outputs kept).
5. **ffmpeg comparison side** matched to preset output (4:2:2 10-bit HEVC, `p210le` verified in ffmpeg-master's hevc_nvenc) to stay apples-to-apples.
6. NR-quality footnote gains "subject to further refinement pending validation" (call note). Quality metric itself shipped pre-CR (`8b561ea`, CompressedVQA-HDR).
7. **Past runs** (owner add, 2026-06-10): enhance results become first-class — `persist._SUMMARISERS` entries for `enhance`/`enhance_compare` (kills the `unrecognised_mode` gap), `/results/enhance/*` list/JSON/CSV/delete endpoints, a "Previous runs" section on the page (own-jobs scoped), and the exact expanded `preset_args` + `preset_origin` + `input_stream` stamped on every result.
8. **Complexity table collapsed** (owner add): the SI/TI "Resulting-file complexity" block renders inside a default-collapsed `<details>` marked "under discussion" — deep-analysis readers opt in.

### Open questions (all on Jon)

- Input-agnostic **HDR-out** colour template: auto-detect `input_mat`? does `sdr_to_hdr=on` no-op on PQ input? (Current `fhd_pq` flags would inverse-tone-map already-HDR content.)
- Blessed **HDR→SDR** tone-map flags for the SDR-out template on HDR input (no `hdr_to_sdr` visible in `--vpp-pixop-live` options).
- `dnn_scaling` behaviour at ~×4.5 (480p → 4K).
- Tania: statistical-significance thresholds for confidence badges (global `confidence.py` follow-up, not this CR).

### Lab look & feel constraint

Two compact controls replace the preset `<select>`; no new cards. Limits line is one muted sentence. Follow-up review with Jon/Tania planned before the page sheds its "UNDER DEVELOPMENT" banner.

---

## Caught during the session but **not** new CRs

For the record, several items came up that don't warrant new CR entries:

- **Bug: `/settings` page rendered empty mid-run** (~T+338s) — owner observed this when trying to demo settings during a queued calibration. Filed as a bug to investigate, not a CR. May be related to job-state machine showing the page in a transient state. Repro: start a calibration, immediately reload `/settings`.
- **Confidence multipliers (5× / 2×) statistical grounding** — ✅ resolved by **CR-028 Phase 2** (shipped 2026-05-22): the multipliers are replaced by the Φ(z) CI model. Full body in `CHANGE_REQUESTS_CLOSED.md`.
- **Codec apples-to-apples equivalence (GOP, profile)** — see **CR-029** sub-item 2 (Tania's CPU-vs-GPU encode-parameter validation).
- **Long-term mash-up of REM + OWL data for 100s of homes** — covered as the post-conference phase of CR-008. No separate CR.
- **"Counter for OWL's own compute footprint"** (Dom, ~T+3319s, in passing) — fun meta-toy, not load-bearing. Skip.
- **The 5-minute training narrative was generated mid-meeting** — captured separately if needed. No CR; deliverable not infrastructure.

**From team meeting 2026-05-04:**

- **GPU variance broken at calibration time** (item 10, originally tagged Bug Medium) — turned out to be a settings tweak, not a bug: `gpu_encode_max_s` was set too short for the variance calibration's sampling window. Bumped from 30 to 90 inline. Not a CR. *Resolved 2026-05-05: overnight n=24 calibration confirmed GPU CV at 4.77% (clean, statistically real); idle 2.41%, cpu 1.33%. CR-028 open question closed; Phase 2 design session with Tania has a clean number as input.*
- **Carbon philosophy / scoping board agenda** (item 25) — strategic discussion item, not engineering work. Belongs on a board agenda, not in CRs.
- **GosOne → OWL name pass** (item 33) — doc/comment audit. Trivial sweep across stale references; do inline whenever convenient. Not a CR.

**From board meeting 2026-05-11:**

- **Bug: live energy-mix breakdown row missing from some result tables.** Owner observed mid-demo: *"it doesn't show the energy mix here, a little bug here… it's supposed to have a little thing just on this table, it's not here."* Filed as bug; check the `wlCarbonStrip` mode-detection branch that conditionally renders the mix row.
- **Bug: `/image` previous-results panel not rendering.** Owner: *"there's a bug, it's not showing the previous results."* Likely the same drift-bug class as the original /demo↔main-page renderer split; check first whether CR-034 Phase A would absorb the fix automatically rather than patching `/image` in isolation.
- **Methodology page status:** as of 2026-05-11 the page is mostly aligned with board feedback already — CO₂e section reduced and reframed *"for reference only"*; recovery-curve graphic added under *Thermal-recovery probe* (uses the shared `WlCharts.line` helper from S21). Owner waiting on Tania's review before publishing the page externally.
- **OWL/WattLab UI rename** done 2026-05-11 across all pages (`<title>`s, headers, hero name, methodology copy); repo URLs and module names stay lowercase `wattlab`. Not a CR — naming hygiene only.
- **Marketing Lab workshop on OWL usage** (Barbara): action for Marketing Lab, not a CR. Pair with CR-040 — the reproducibility kit is the natural artefact for that workshop.
- **OWL containerised + data-centre hosting** (Mike's Akamai-Virginia open-rack offer; Linode option): folds into the 2026-05-11 addendum on CR-031 sub-section 3. New constraint surfaced: 1 s power-measurement granularity as a hard portability gate.
- **Recruitment brainstorm meeting (~10 days out)**: action item from the meeting, not a CR. Stan / Marisol / Veronika / Ben / probably Mike participating.

---

## Groupings & dependencies (added 2026-05-08, S23 close-out review; updated 2026-05-11 after board meeting; 2026-05-12 close-out sweep — CR-032 / CR-034 / CR-036 / CR-038 / CR-042 moved to closed; S26 close-out 2026-05-20 — CR-037 / CR-040 / CR-027 moved to closed; S32 close-out 2026-05-27 — CR-054 / CR-055 / CR-056 / CR-058 findings-chain + CR-012 history-journal moved to closed)

The 15 active CRs cluster into a few loose tracks. Each CR remains its own entry — these notes are about where the *next* design session should look first when picking up two adjacent items.

### Track A — Storage / persistence (Tania-elevated 2026-05-07)

Tania's S22 meeting line — *"if we save them somewhere reusable, we can do a lot of really interesting statistics on that"* — turned storage from quality-of-life into the gating decision for the analytics layer. Remaining CRs on this track:

- **CR-031** sub-section 1 (DB choice with REM coherence — "I don't want five different databases")
- **CR-003** iso-energy bitrate sweep *(downstream — the analytics use-case)*
- **CR-007** carbon variance over time-of-day / season / location *(downstream — also analytics)*

*(CR-012 calibration + probe history journal shipped S32 — JSONL files under `results/variance/` and `results/diagnostics/`. Append-only; first feed for the analytics layer. In `CHANGE_REQUESTS_CLOSED.md`.)*

**Recommendation:** the storage-family decision (CR-031 §1) is the remaining bottleneck. CR-012's JSONL shape works standalone; whether the analytics layer reads it as-is or migrates onto whatever DB the §1 pass picks is a CR-031 decision. CR-003 and CR-007 still inherit the eventual storage shape automatically.

### Track B — Confidence model (CR-028 Phase 2 ✅ SHIPPED 2026-05-22)

- **CR-028 Phase 2 shipped** — the CI model (`confidence.py`) per Tania's §9 v2 is on `main`; raw `baseline_samples_w` + `task_samples_w` are persisted; all four modules share it; legacy fallback retained. Full body in `CHANGE_REQUESTS_CLOSED.md`. Absorbed CR-020 (per-run baseline-CV gate) and the 5×/2× threshold grounding.
- **CR-029** encoding rigor benefits from the shipped model but, per the 2026-05-22 decision, stays a **separate, deferred** issue (Tania-led; the §9 v2 gate is lifted but CR-029 isn't being pushed now).
- *Open follow-up:* the **aggregate / repeated-run confidence layer** that consumes `variance_cpu_pct` / `variance_gpu_pct` (reserved by Phase 2's option-C choice) is not yet built — capture as a new CR if/when it's wanted.

**Recommendation:** track complete for now. The natural next step is the **Track A storage decision** (sample persistence already lands raw arrays per result — CR-012 + the analytics layer can build on that shape).

### Track C — Widget / progress extensions (post-CR-019)

All three touch `wlRenderProgress` but the work is independent:

- **CR-035 encode progress bar — ✅ SHIPPED S23** (`b2204b4`): `ffmpeg -progress pipe:1` parsing + `progress_pct` / `eta_s` surfaced through `wlRenderProgress`. In `CHANGE_REQUESTS_CLOSED.md`.
- **CR-024** re-run probe button — server-side endpoint promotion (`bin/probe-thermal-recovery` → `precalibration.py`) routed through `queue_control.enqueue`.
- **CR-019 deferred (resume-job hook)** — client-side lifecycle, URL `?job=<id>`, browser history.

**Recommendation:** CR-035 shipped. Remaining: CR-024 next (operator quality-of-life), resume-job last (lifecycle is the hardest to design for cleanly without spilling).

### Track D — Result-rendering / framing coherence

**Track D is now fully shipped.** The 2026-05-12 sweep closed CR-034 / CR-032 / CR-036 / CR-038; the S26 credibility bundle (2026-05-20) closed the last two — **CR-037** (AI workloads tethered to streaming: per-page streaming-context bands + the paper's framing principles + a per-result "≈ N× a 120 s video encode" multiplier) and **CR-027** (tier copy: three-column Public/Member/Lab matrix + first-step tier indicator). All in `CHANGE_REQUESTS_CLOSED.md`.

### Track E — Polish (small, independent)

- **CR-007** carbon variance study *(also Track A downstream)*

*(CR-005 software fan control — resolved S24 by investigation, not feasible on GoS1's hardware; moved to `CHANGE_REQUESTS_CLOSED.md`.)*

**Recommendation:** CR-007 has no dependencies; slot whenever Track A–D are blocked.

### Track F — Strategic / exploratory (longer horizon, captured-but-not-active)

- **CR-008** REM ↔ OWL integration
- **CR-009** cross-platform web client test bay
- **CR-018 Tier 2/3** historical CO₂e visitor-pickable any-month *(Tier 1 shipped; T2/T3 are gold-plating)*
- **CR-025** real-time Linux kernel migration *(team meeting upgraded direction but not yet started)*
- **CR-039** *(new, 2026-05-11)* energy-vs-quality axis for AI (frontier-model judge) — explicit tension with CR-029 §6 to resolve; easy to drop.
- **CR-041** *(new, 2026-05-11)* new-vs-aged silicon comparison — opportunistic, awaiting chip availability.

**Recommendation:** keep captured. CR-039 is the one most likely to mature quickly now that CR-037 has shipped (it lives on the tethered AI pages, and CR-038's verdict line is its natural surface). Others remain idle until the active tracks resolve.

### Track G — Member trust & verification *(new, 2026-05-11)*

- **CR-040** "Reproduce this result" downloadable bundle — ✅ **shipped S26 (2026-05-20)**, video-only V1 (`cmd.sh` + `expected.json` k=3σ envelope + stdlib `compare.py` + README; "↓ Reproduce this" on video cards). `POST /reproduce/contribute` deferred. In `CHANGE_REQUESTS_CLOSED.md`.

**Follow-up:** pair with the Marketing Lab workshop Barbara proposed — the bundle is the natural artefact for that conversation. The deferred member-side `POST /reproduce/contribute` can become its own CR if a member asks for it.

### Cross-track dependencies summary

```
CR-031 storage decision  ─┬─→  CR-012  (calibration history persistence)
                         └─→  Track A analytics: CR-003, CR-007

CR-028 Phase 2 ✅ SHIPPED ──→  CR-029 (encoding rigor — deferred by decision 2026-05-22)
(2026-05-22)              ──→  CR-020 retired (absorbed into SE_per_run)
                         ──→  aggregate-confidence layer (cpu/gpu CVs) = future CR

CR-037 ✅ (shipped S26)  ──→  CR-039  (quality scoring lives on the now-tethered AI pages)
CR-029 §6 "external PQA"  ─?→  CR-039  (carve-out needed, or drop CR-039)

CR-044 (VMAF ✅ shipped)  ──→  CR-029  (VMAF proves CPU/GPU do comparable work)
                         ──→  CR-039  (VMAF is the video sibling of the AI quality judge)
                         ──→  CR-043  (cheaper, rigorous half of "make the claim visceral")
                         ──→  CR-045  (enables the iso-VMAF "Match quality" search)

CR-045 (Same Bitrate /   ──→  CR-029  (defining "equivalent quality" is Tania's territory)
        Same Quality)    ──→  CR-003  (mirror axis: fix energy, vary quality)
                         ↳ V1 = the deferred "Benchmark 2" (CRF/QP) surfaced as a toggle

CR-026 ✅  ─→  CR-027 ✅  (tier explanation — both shipped)

CR-054 ✅ (findings catalog, shipped S32) ──→  CR-055 ✅ (catalog index — shipped S32)
                                         ──→  CR-056 ✅ (bulk import Key Findings — shipped S32)
                                         ──→  CR-058 ✅ (guided tour terminus — shipped S32)
                                         ──→  CR-057  (home-page repositioning — DRAFTED S32, awaiting lab UX review)
CR-029 §1 + §2  ─?→  CR-054   (methodology_ref source; potential AV1 finding v2 via supersedes)
CR-041 (chip)   ─?→  CR-054   (output is a finding, not a bespoke /findings/chip-aging page)
CR-007 (grid)   ─?→  CR-054   (deliverable becomes a finding, not a separate page)
```

(Track D's internal chain — CR-034 → CR-036 → CR-038 → CR-032 — has fully resolved; all four are closed. CR-037 now lands on that finished surface.)

### Suggested order (updated S32 close-out, 2026-05-27 — findings chain shipped except CR-057)

S26 shipped the credibility three (CR-037, CR-040, CR-027); S28 (2026-05-22) shipped CR-044 (VMAF) + CR-028 Phase 2 (CI confidence); S29 (2026-05-26) shipped CR-046 Phase 1 (BBB preloaded) + CR-047 (variants schema for `/video` Source picker); S30 (2026-05-27) closed CR-033 + CR-046 Phase 2; S30/S31 (2026-05-26 → 2026-05-27, parallel sessions) shipped the AI-comparison trilogy CR-048 (`/llm/compare`) + CR-049 (`/rag/compare`) + CR-050 (dynamic model catalog + active-probe thermal floor + N-way `/image/compare`); S32 (2026-05-27) shipped CR-051 (RAG corpus self-service: Member upload + delete) and the findings-chain bundle CR-054 / CR-055 / CR-056 / CR-058.

**The S32 UX-strategy thread (2026-05-27) re-prioritised the order** — most visitors browse without running jobs; the strategic role of OWL per the board is credibility/recruitment, not interactivity; the S32 architecture audit established that rich replay of past results is essentially free because the renderers are already JSON-pure. The findings chain shipped behind a feature flag (`findings_enabled`) for safe lab-colleague review. **CR-057 (home page repositioning) is the one remaining flow change in the chain**, drafted and awaiting lab UX review.

Remaining order:

1. **CR-057** home page repositioning to findings-first — **DRAFTED, awaiting lab UX review.** Mechanical work ~half day; design discussion is the bottleneck. Behind same `findings_enabled` flag for byte-identical rollback. Non-blocking — the rest of the backlog can progress without it.
2. **Track A storage decision** — CR-031 §1 (REM coherence); unblocks the analytics layer (CR-003, CR-007). CR-012's JSONL journals are the first feed; the §1 decision is whether to consume them as-is or migrate onto a shared DB with REM. Can run in parallel with CR-057.
3. **CR-045 (with/after CR-029)** — Tania-led; "Same Bitrate / Same Quality" toggle.
4. **Track C — CR-024** re-run-probe button (CR-035 progress bar already shipped S23).
5. **CR-039 / CR-041** as exploratory follow-ups (CR-039 lands on the shipped tethered AI pages; VMAF is its video sibling; CR-041 awaits chip arrival, output lands as a CR-054 finding).
6. **CR-007** carbon variance (output lands as a CR-054 finding) · **CR-004** graphing · longer-horizon Track F (CR-008 / 009 / 018 T2-3 / 025) as capacity allows.

CR-029 stays Tania-led and deferred; CR-045 rides with it. CR-029's eventual encoding-rigor work may refine the AV1 finding (v2 via `supersedes`) — designed-for in CR-054's versioning primitive.
