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

**Phase 2 — Tania's unified statistical redesign — SPEC LANDED + DECISIONS AGREED 2026-05-22.**

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

### Update 2026-05-11 (board meeting context)

Board reinforced sub-section 3 (containerisation) as the path to data-centre hosting on a friendly partner's rack (Linode, or Mike's Akamai offer of an open-rack slot in Virginia with 100% renewable cover). Two constraints surfaced that grow sub-section 2:

- **1 s power-measurement granularity is a hard portability constraint.** Many PDUs poll at 1 min or coarser — they can't replace the Tapo P110 without losing measurement fidelity. Sub-section 2 must include a *meter-resolution declaration* on every backend, and the confidence flag must visibly degrade when the backend's resolution is coarser than the task's duration ("you cannot be 🟢 on a 4 s encode measured by a 60 s meter"). This is **resolution-aware confidence**, a required behaviour of the abstraction, not a watch-out.
- **Utility-grade meter + PDU per-plug meters in series** (Mike). A contained-rack deployment is one utility-grade meter on top of the rack plus PDU meters per plug for component attribution. The backend interface should be expressive enough to represent that stack — one primary reading plus N attributable sub-readings — not just `get_power_watts() -> float`.

Net: sub-section 2 grows from ~half day to ~1 day. Sub-section 3 lands on Mike's facility if/when the offer materialises; nothing about CR-031 changes in shape, but the timeline becomes externally-driven.

---

## CR-033 · Curated demo video job selection (1–2 options)

**Status:** captured 2026-05-08 (Session 23 part 6). Follow-up to today's `/demo` video step quick-fix.
**Triggered by:** owner observation during anonymous-tier testing — `/demo` step 1's video job was hardcoded to `source=meridian_4k` + `preset=both` (full 12-minute Meridian + H.264 CPU+GPU compare = ~10–15 min wall time). For the guided tour that's a flow-breaker: visitors can't realistically wait that long, and the result card lands long after the demo session is fresh in their head. Quick-fix in Session 23 part 6 changed it to `source=meridian_120s` + `preset=h265_both` (~2–3 min, shows GPU advantage cleanly). CR-033 is the next step.

### Problem

A single hardcoded demo job is a UX compromise: the guided tour either picks one codec family (today: H.265) and silently skips the others, or grows toward the long-job problem we just retired. Visitors who care about codec-family comparisons (H.264 vs H.265 vs AV1 — exactly the population we want to hook for membership) get less information than the canonical Key Findings table on the methodology page.

### Agreed direction (rough)

Two curated demo jobs, selectable via a small chip row on `/demo` step 1:

1. **H.265 CPU vs GPU on `meridian_120s`** — current default. Demonstrates the GPU advantage on a modern codec.
2. **AV1 CPU vs GPU on `meridian_120s`** — sibling option. AV1 is the most efficient codec in the canonical findings; the demo should show it.

Each runs the same `*_both` shape so renderVideoResult can stay codec-agnostic. Two chips above the run button, the second one disabled-with-lock-badge for now if we want to phase it in (or both available from day one).

Out of scope for V1: AV1 GPU vs H.265 GPU side-by-side, all_codecs sweep on `/demo`, custom source selection. Those are CR-029 / CR-031 territory.

### Cost / leverage

Tiny — a chip-row UI on `/demo` step 1, two `runDemoVideo()` variants (or one parametrised), plus a one-line label change. Half-day including visual verification. Leverage: the demo shows a *family* of comparisons rather than a single codec, which is more useful framing for the conference visitor.

### Open questions

- **Default selection.** If we ship two chips, which one is on by default? H.265 (current) is safer (more familiar codec to most operators) but AV1 makes the GoS environmental story better (most efficient).
- **Chip persistence.** Should the choice persist across the visitor's session (localStorage) or reset each load? Lean: reset — the demo is meant to be a fresh first-impression each time.

---

## CR-035 · Encode progress bar for long video jobs

**Status:** captured 2026-05-08 (Session 23 part 6). Sibling to the deferred CR-019 resume-job piece — both touch `wlRenderProgress`, both are widget extensions, but the work is genuinely separable so they ship independently.
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

## CR-044 · VMAF quality score on video comparison cards

**Status:** captured 2026-05-22. **Feasibility proven same day** by a live trial on GoS1 (see below); owner-directed to implement.
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

### Priority: ready to implement (owner-directed, feasibility proven 2026-05-22).

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

**From board meeting 2026-05-11:**

- **Bug: live energy-mix breakdown row missing from some result tables.** Owner observed mid-demo: *"it doesn't show the energy mix here, a little bug here… it's supposed to have a little thing just on this table, it's not here."* Filed as bug; check the `wlCarbonStrip` mode-detection branch that conditionally renders the mix row.
- **Bug: `/image` previous-results panel not rendering.** Owner: *"there's a bug, it's not showing the previous results."* Likely the same drift-bug class as the original /demo↔main-page renderer split; check first whether CR-034 Phase A would absorb the fix automatically rather than patching `/image` in isolation.
- **Methodology page status:** as of 2026-05-11 the page is mostly aligned with board feedback already — CO₂e section reduced and reframed *"for reference only"*; recovery-curve graphic added under *Thermal-recovery probe* (uses the shared `WlCharts.line` helper from S21). Owner waiting on Tania's review before publishing the page externally.
- **OWL/WattLab UI rename** done 2026-05-11 across all pages (`<title>`s, headers, hero name, methodology copy); repo URLs and module names stay lowercase `wattlab`. Not a CR — naming hygiene only.
- **Marketing Lab workshop on OWL usage** (Barbara): action for Marketing Lab, not a CR. Pair with CR-040 — the reproducibility kit is the natural artefact for that workshop.
- **OWL containerised + data-centre hosting** (Mike's Akamai-Virginia open-rack offer; Linode option): folds into the 2026-05-11 addendum on CR-031 sub-section 3. New constraint surfaced: 1 s power-measurement granularity as a hard portability gate.
- **Recruitment brainstorm meeting (~10 days out)**: action item from the meeting, not a CR. Stan / Marisol / Veronika / Ben / probably Mike participating.

---

## Groupings & dependencies (added 2026-05-08, S23 close-out review; updated 2026-05-11 after board meeting; 2026-05-12 close-out sweep — CR-032 / CR-034 / CR-036 / CR-038 / CR-042 moved to closed; S26 close-out 2026-05-20 — CR-037 / CR-040 / CR-027 moved to closed)

The 17 active CRs cluster into a few loose tracks. Each CR remains its own entry — these notes are about where the *next* design session should look first when picking up two adjacent items.

### Track A — Storage / persistence (Tania-elevated 2026-05-07)

Tania's S22 meeting line — *"if we save them somewhere reusable, we can do a lot of really interesting statistics on that"* — turned storage from quality-of-life into the gating decision for the analytics layer. Three CRs sit on this track:

- **CR-012** persist variance calibration + thermal-recovery probe history *(small, well-scoped)*
- **CR-031** sub-section 1 (DB choice with REM coherence — "I don't want five different databases")
- **CR-003** iso-energy bitrate sweep *(downstream — the analytics use-case)*
- **CR-007** carbon variance over time-of-day / season / location *(downstream — also analytics)*

**Recommendation:** before implementing CR-012 in isolation, hold a brief design pass that decides the DB family for both OWL and REM. CR-012's persistence shape should drop into whatever container that pass chooses, not invent a third format. CR-003 and CR-007 inherit the same shape automatically.

### Track B — Confidence model (CR-028 Phase 2)

- **CR-028 Phase 2** spec is now **landed and agreed** — Tania's `wattlab_traffic_light_confidence.md` §9 v2 is on `main` (`d3d78e9`) and the units question is resolved (option C). Design done; implementation can proceed (see Phase 2 decisions in the CR-028 entry above). The implementation-prereq is persisting raw `baseline_samples_w` + `task_samples_w`, which ties back into the Track A storage decision.
- **CR-029** encoding rigor *partially* depends on Phase 2: apples-to-apples encode comparisons get more credible once confidence flags rest on a unified statistical model. Per 2026-05-22 decision, CR-029 stays a **separate, deferred** issue — not kicked off now even though the §9 v2 gate is lifted.
- The CR-020 retirement absorbed the per-run baseline-CV gate into Phase 2's `SE_per_run`. Storage of raw `baseline_samples_w` + `task_samples_w` is folded into Phase 2 scope so historical results can be re-flagged after the formula change.

**Recommendation:** Phase 2's spec gate is cleared. The longest-pole work is now the implementation — start with sample persistence (Track A) + shared `confidence.py`, then re-validate every result page. CR-029 remains intentionally deferred.

### Track C — Widget / progress extensions (post-CR-019)

All three touch `wlRenderProgress` but the work is independent:

- **CR-019 deferred (resume-job hook)** — client-side lifecycle, URL `?job=<id>`, browser history.
- **CR-024** re-run probe button — server-side endpoint promotion (`bin/probe-thermal-recovery` → `precalibration.py`) routed through `queue_control.enqueue`.
- **CR-035** encode progress bar — `ffmpeg -progress pipe:1` parsing + new `progress_pct` / `eta_s` fields surfaced through `_job_status()`.

**Recommendation:** ship in this order — CR-035 first (highest visitor value, especially Member-tier long uploads), CR-024 next (operator quality-of-life), resume-job last (lifecycle is the hardest to design for cleanly without spilling).

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

Tania §9 v2 ✅ landed     CR-028 Phase 2  ─→  CR-029 (encoding rigor — deferred by decision 2026-05-22)
(spec agreed 2026-05-22) ─→ (impl ready)  ─→  retire CR-020 fully

CR-037 ✅ (shipped S26)  ──→  CR-039  (quality scoring lives on the now-tethered AI pages)
CR-029 §6 "external PQA"  ─?→  CR-039  (carve-out needed, or drop CR-039)

CR-044 (VMAF, in build)  ──→  CR-029  (VMAF proves CPU/GPU do comparable work)
                         ──→  CR-039  (VMAF is the video sibling of the AI quality judge)
                         ──→  CR-043  (cheaper, rigorous half of "make the claim visceral")

CR-026 ✅  ─→  CR-027 ✅  (tier explanation — both shipped)
```

(Track D's internal chain — CR-034 → CR-036 → CR-038 → CR-032 — has fully resolved; all four are closed. CR-037 now lands on that finished surface.)

### Suggested order (updated S26 close-out, 2026-05-20)

The S26 credibility bundle shipped what were the top three (CR-037, CR-040, CR-027). Remaining order:

1. **CR-028 Phase 2 implementation + Track A storage decision** — §9 v2 spec is landed and agreed (2026-05-22), so the confidence track is unblocked. Start with sample persistence (`baseline_samples_w` / `task_samples_w`) which shares the storage/DB-family decision (CR-031 §1, REM coherence) that also unblocks CR-012 + the Track A analytics layer (CR-003, CR-007); then the shared `confidence.py`; then re-validate every result page. **CR-029** stays deferred by decision — separate issue to look into later, not part of this push.
2. **Track C (CR-035 → CR-024)** — encode progress bar, then re-run-probe button.
3. **CR-039 / CR-041** as exploratory follow-ups (CR-039 now lands on the shipped tethered AI pages).
4. **CR-007** carbon variance · **CR-004** graphing · longer-horizon Track F (CR-008 / 009 / 018 T2-3 / 025) as capacity allows.

If only one thing per week: in the order above. The confidence track's spec gate cleared 2026-05-22; CR-028 Phase 2 is now implementation, and CR-029 is intentionally held as a later, separate issue.
