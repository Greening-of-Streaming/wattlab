# OWL Change Requests

Active design / change requests. Each entry has a status, a problem statement, the agreed direction, and any open questions. Implementation lives in JOURNAL.md once it lands.

**Closed CRs live in `CHANGE_REQUESTS_CLOSED.md`** — once a CR's headline scope ships, it moves there with the original problem statement preserved and a Status line naming the closing commit.

---

## Design principle (standing): preserve the lab look & feel

OWL was designed as a **lab tool first** — dense, fast, neutral, no marketing chrome. Every CR that adds UI elements (badges, headers, comparison rows, advisory copy, charts) must consciously preserve that: keep elements compact, default-collapsed when supplementary, monospace where it earns it, no decorative animation. The risk is real and stated by the owner (2026-05-11): *"as we add more and more info on the UI, it loses its LAB look & feel that must always allow for quick use."* Each UI-touching CR carries a "Lab look & feel constraint" line — when in doubt, hide it behind a `<details>` block, push it to `/methodology`, or cut it. Density audits are a hard gate at PR review; CR-034 (unified results card) is the natural place to enforce them across surfaces.

---

## Design principle (standing): quality assessment by external authority

*(Promoted 2026-06-11 from CR-029 §6 — a stance, not a closable feature.)* OWL measures **energy**; it does not develop or internalise perceptual-quality assessment for video. Where a quality axis is needed, point at external authorities (Netflix VMAF, industry references) and document the scoping on `/methodology`. Origin: team meeting 2026-05-04 (CR-029 §6); reinforced by Tania's caution at the 2026-05-11 board.

**One open tension carried here verbatim:** CR-039 proposes a frontier-model-as-judge quality axis for AI jobs (LLM/RAG/image), where no external authority exists. That is an *exception to this principle* the owner must explicitly ratify — or reject, in which case **drop CR-039**. (Video PQA remains out of scope either way; shipped quality columns — VMAF for codec comparisons, CompressedVQA-HDR as a relative NR indicator for enhancement — are external models consumed as-is, consistent with this principle.)

---

## CR-003 · Iso-energy bitrate sweep ("I want to spend X Wh, what are my options?")

**Status:** captured 2026-05-01 — longer horizon (long test runs needed).
**Triggered by:** Dom (transcript ~T+1126s and ~T+2398s).

### Problem

OWL currently fixes the bitrate per codec (4 Mbps H.264, 2 Mbps H.265, 1.5 Mbps AV1 — chosen to match real-world ABR ladders) and reports the energy that produces. The inverse question is more interesting for an industry audience: **"given a fixed energy budget, what bitrate / quality options do I have across codecs?"**

Inverts the typical framing — instead of "this codec at this bitrate uses N Wh", asks "if I have N Wh to spend on a one-minute encode, here are my codec/bitrate options". Dom flagged this as IBC white-paper material; owner called it press-worthy.

### Agreed direction

New video-test mode (`video_iso_energy` or similar). Iterates a bitrate range across H.264 / H.265 / AV1 — long-running, intended for overnight or weekend execution — finds the bitrates per codec that produce equivalent energy. Output: chart/table of "for X Wh budget, your options are H.264@Y kbps / H.265@Z kbps / AV1@W kbps."

Possibly pair with a quality metric (mean PSNR / SSIM / VMAF) so the result is "for X Wh, here's your bitrate AND quality across codecs" — Simon flagged in transcript that quality scoring should accompany this.

### Open questions

- Quality metric: VMAF **shipped since (CR-044)** — the dependency objection is gone; reuse it.
- Bitrate sweep granularity? Logarithmic vs linear?
- White-paper scope: just CPU? Just GPU? Both? Cross-grid?

### Cross-reference

CR-045 is the mirror axis (fix quality/bitrate, compare energy); this CR fixes energy and sweeps the rest. Sequence independently.

### Priority: strong candidate when capacity allows — long (overnight/weekend) test runs needed; natural IBC-submission material.

---

## CR-004 · Visual graphing in OWL

**Status:** captured 2026-05-01 — nice-to-have. **Partially overtaken by incidental shipping** (2026-06-11 audit): Chart.js 4.4 is the de facto house library (`ui.CHARTJS_URL`), the thermal-recovery curve renders on `/settings`, and `/llm/compare` + `/rag/compare` ship energy bar charts. Remaining scope below.
**Triggered by:** Dom (transcript ~T+1657s) + owner notes.

### Problem

Single-run results and the home page are still metric tables only; trend, variance, and shape are visible only by reading numbers row-by-row.

### Remaining deliverables

1. **Per-run power trace** — line chart of the P110 polls (raw samples are persisted on every result since the CI confidence work) showing baseline → ramp-up → workload → cooldown. Makes the ΔW computation visually obvious. Single canvas per result card.
2. **Comparison-mode side-by-side on the result card** — bar chart for both/all-codecs results (the LLM/RAG compare pages already have one; video doesn't).
3. **Historical trend** — small chart of last N runs' energy over time. Coordinate the surface with CR-057's findings-first home redesign rather than landing on today's home page.

### Priority: nice-to-have. Would visibly improve demo impact.

---

## CR-007 · Carbon-intensity history & variance study (absorbs CR-018 Tier 2/3)

**Status:** captured 2026-05-01; **merged 2026-06-11 with CR-018's Tiers 2/3** (CR-018's shipped Tier 1 — the curated "Through history" block — is recorded in CHANGE_REQUESTS_CLOSED.md). The variance study needs exactly the historical dataset Tier 2 specified: one infrastructure, two outputs.
**Triggered by:** Simon + Dom (transcript ~T+2029s onwards); CR-018 owner question on "what would this job have emitted in 2020".

### Problem

OWL now reports gCO₂e against live grid intensity, but **the variance of that intensity itself** isn't characterised. Dom raised the right framing: if the carbon intensity of the grid varies by 1000% across the day, optimising your code by 1% is noise. If the grid varies by 1% and your code variation drives 50%, your code matters more. Without knowing which regime you're in, optimisation effort is mis-targeted.

### Agreed direction — Stage 1: historical-data infrastructure (ex-CR-018 Tier 2)

- `bin/refresh-historical-carbon` (replaces the one-shot `bin/fetch-historical-mix`): fetch monthly Eco2mix aggregates for every (zone, year, month) tuple in scope → `data/eco2mix_history.json` (~50 KB for FR, ~150 monthly aggregates). Run on demand; re-run quarterly. Budget a half-hour first fetch (API pagination).
- `carbon.py` loads the cache at startup; new `historical_intensity(zone, year, month)`.
- `/carbon/historical?zone=FR&year=2020&month=6` → `{g_per_kwh, label}`.
- Comparison strip gains a small year-month picker (2012 → last completed month).
- Cost ~1 day. Same lifecycle method as the live path (`compute_intensity_from_mix`).

### Agreed direction — Stage 2: the variance study

1. Take a **standard fixed-energy reference workload** (e.g. exactly 1 Wh of compute — a calibrated transcode or synthetic CPU hold).
2. Compute its gCO₂e variance over Stage 1's dataset as a function of hour of day / day of week / season / comparison zone.
3. Render: a chart plus a punchy summary line ("your 1 Wh workload, run in France, swung from X g to Y g over the last 6 months — Z× spread").
4. **Deliverable is a finding** (`docs/findings/grid-variance-fr-2026.md`) via the shipped CR-054 machinery — the old "/grid-variance page or white paper" options dissolve into the finding.

### Output value

Strong industry talking point — speaks directly to Simon's "schedule your work to carbon-efficient times" thesis: if grid intensity varies 1000% across the day, optimising code by 1% is noise; if it varies 1%, your code dominates. Knowing the regime targets the optimisation effort.

### Later (one line each)

- Ex-Tier 3 interactive timeline scrubber — only if Stage 1's picker proves popular.
- Non-FR zones — the same Stage 1 infrastructure pointed at ElectricityMaps (paid) or Ember (free, lagged, cleaner European provenance).

### Caveat

Lifecycle factors (IPCC AR6) are static — applied to historical mixes. Defensible; footnote on `/methodology` when Stage 1 ships.

### Priority: low / half-day spike to assess. Gated on the CR-031 §1 storage decision only if results need persisting beyond the findings file.

---

## CR-008 · REM ↔ OWL integration

**Status:** captured 2026-05-01. **Steps 1–2 ✅ shipped** (REM source in-repo under `REM/`; OWL branding pass — `rem-theme.css` re-skin, 2026-05-27). Steps 3–4 (data interop, OWL-as-encoder) remain — longer horizon.
**Triggered by:** Dom + owner across the transcript (~T+486s, ~T+2160s, ~T+3151s, ~T+1014s).

### Problem

GoS now has two measurement tools that were built independently:
- **OWL** — single-server, fine-grained, encoder-side energy + CO₂e.
- **REM** — multi-machine, end-to-end streaming workflow, less granular.

They're **complementary, not competing**, but currently they look like separate projects. For a GoS audience, the right framing is "REM = end-to-end at scale; OWL = deep dive at the encoder; together they cover the streaming pipeline."

### Agreed direction (multi-step)

1. ✅ **(Shipped)** Pull REM source code into the Claude project context so cross-understanding is possible (`REM/` + `REM/CLAUDE.md`).
2. ✅ **(Shipped)** Update REM with **OWL branding and visual style** — `rem-theme.css` drop-in re-skin, same owl mark / `#00ff99` accent / dark theme. Dom's request.
3. **(Later)** Genuine data interoperability — OWL exporting in a format REM can ingest, or vice versa. Mash-up view where 100s of homes report from REM and 1-2 contribute high-resolution OWL-style local measurements; visualised together.
4. **(Long-term, exploratory)** OWL acting as the encoder in a REM-orchestrated end-to-end test (encoder → intermediary server [Linode / TNO / Bristol] → client). Auto-hackathon workflow (see CR-009).

### Priority: the branding pass is the feasible near-term step; data integration comes later.

---

## CR-009 · Cross-platform web client test bay

**Status:** captured 2026-05-01 — longer horizon.
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

### Priority: longer horizon, high leverage — turns OWL into a contribution-driven RUM platform, not just a single-server lab.

---

## CR-024 · Re-run thermal-recovery probe from the "More calibration details" panel

**Status:** captured 2026-05-04 (S21). The panel *display* shipped (S21: recovery chart from `GET /precalibration/data`, served from `routes_settings.py` post-S42-refactor) — but the deliverable here, **`POST /precalibration/run` + a "▶ Re-run probe" button, was never built**; the deferral is documented in code at `routes_settings.py:573`. Half-day estimate stands.
**Triggered by:** owner — refresh the curve without dropping to the shell.

### Problem

The probe is a CLI script (`bin/probe-thermal-recovery`, ~65 min) that holds `/tmp/owl-paused` + `/tmp/gos-measure.lock` directly and writes CSVs under `results/diagnostics/`. Every other long-running measurement goes through `queue_control.enqueue` so visitor-vs-operator collision is handled by the spine; the probe predates being a first-class server feature.

### Agreed direction

**Promote the probe into `wattlab_service/precalibration.py` + `POST /precalibration/run`, mirroring `/variance/run`.**

1. Extract the probe loop into `precalibration.py:run_thermal_recovery_probe(job_id, jobs)` — same shape as the variance calibration (encoder pieces now route through `gpu.BACKEND`). Also lift `_append_probe_history` from the CLI so runs keep journaling to `results/diagnostics/history.jsonl` (the hook CR-012's closed entry pre-named).
2. New endpoint gated on `VARIANCE_RUN` (or a sibling capability), routed through `queue_control.enqueue`.
3. CLI script becomes a thin client (or stays standalone — the module is what matters).
4. Panel UI: "▶ Re-run probe" button + job polling + chart refresh on completion; ETA badge (≈65 min); disabled while in-flight.

### Setting shape

```jsonc
{
  "precal_distances":      "0,2,5,8,12,18,25,35,50,70,95,120",
  "precal_pre_cool_s":     30,
  "precal_baseline_polls": null   // null → baseline_polls
}
```
Defaults match the CLI so behaviour is unchanged.

**Cost:** ~half a day (mechanical extract + button + tests + docs).

### Watch-outs

- Keep the CLI script (diagnostic/pdb value) as a thin wrapper around the module.
- `results/diagnostics/` keeps its CSV shape — the reader doesn't care which path produced it.
- Don't auto-chain probe → variance; separate buttons, recommended sequence documented on `/methodology`.

### Open question

Naming only: `/precalibration/*` URL space for symmetry with `/variance/run`; the panel header may read "Thermal recovery probe".

---

## CR-025 · Migrate to a real-time Linux kernel for tighter measurement determinism

**Status:** **Parked, low priority** (owner 2026-05-28: "we won't be going there for a while"). Captured 2026-05-04 (S21); confirmed by team meeting same day (item 30). **Body compressed 2026-06-11** — the original AMD-era analysis (ROCm-on-RT risk, per-number win estimates from pre-normalization CVs) is in this file's git history; any future validation targets the **Nvidia/CUDA/NVENC** stack (RTX 5080 since 2026-05-29).
**Triggered by:** owner — does focus mode become more effective on RT? Honest answer: RT and focus mode address orthogonal noise sources and stack.

### Problem

Focus mode addresses the *power side* of background noise (timers that wake cores and draw watts). Nothing addresses *temporal* jitter: poll-spacing variance, ffmpeg startup transients, scheduler quanta. A slice of the unexplained variance residual is real per-run timing variance.

### What RT does / doesn't

- **Does:** deterministic kernel-thread latency, prioritised IRQs, `SCHED_FIFO`, CPU isolation (`isolcpus`/`nohz_full`/`rcu_nocbs`), exact sleep granularity (1 Hz polls actually at 1.000 s).
- **Doesn't:** stop background draw (the P110 measures the whole box — focus mode still required); improve P110 resolution; make encoders deterministic.

### Direction if picked up

1. Install `linux-image-rt-generic`; **validate the full stack on RT — the proprietary Nvidia driver + CUDA + NVENC + Ollama + diffusers is the single biggest unknown.**
2. Core split via cmdline (`isolcpus`/`nohz_full`/`rcu_nocbs`, split TBD empirically) + systemd `CPUAffinity` + `taskset` on measurement spawns; focus mode unchanged (composes).
3. `cyclictest` harness gating calibrations.
4. `/methodology` + Hardware Disclosure update; result JSON gains `kernel_flavour`/`isolated_cpus` tags.
5. Reversibility: GRUB-selectable, one reboot back — verify nothing hard-codes against RT first.

~Half a week of careful work. Run the thermal probe + variance calibration before/after; the empirical delta is the only honest justification.

### Decision frame (the honest core)

The P110 cloud-API quantisation bounds RT's likely win to **≲1 percentage point of variance** — marginal alone, *necessary* if a higher-resolution power path ever lands. **The power-measurement landscape is in motion under CR-065 (dual P110) — re-read this calculus after it settles; don't predict it here.** Worth a 30-minute team discussion before any work.

---

## CR-029 · Encoding rigor pass (apples-to-apples credibility)

**Status:** captured 2026-05-04 (post-meeting). High priority, Tania-led. **Remaining scope: §1** (finish the per-codec pipeline doc on `/methodology` — now describing the **NVENC** paths), **Tania's review of the §2 normalization decisions** (made on the AMD card; review is against current NVENC reality), **§5** (philosophy doc). Shipped: §2 (S34, `88a2696` — provisional pending that review), §3 (standing pass). Restructured 2026-06-11: **§4 extracted into CR-045** as its "Typical use" mode; **§6 promoted to the standing External-PQA principle** at the top of this file.
**Triggered by:** team meeting 2026-05-04 — for the canonical ABR all-codecs benchmark to be cited externally, the pipeline has to be auditable and the comparison's semantics explicit.

### Problem

For the canonical ABR all-codecs benchmark to be cited externally: (1) the exact per-codec pipeline isn't documented anywhere readers can audit; (2) CPU and GPU encoder parameters were encoder-defaulted and diverged (addressed by §2, pending review); (3) the comparison philosophy needs explicit documentation so the headline isn't misread.

### §1 — Document the pipeline on /methodology (REMAINING)

New subsection under "Video transcoding": input read, decode path, pixel-format handling, encoder defaults this deployment relies on, output container — one pass per codec/path, **describing the current NVENC pipeline** (`-hwaccel cuda` + `scale_cuda` + `*_nvenc`). Source from the actual command, not memory. Partial progress 2026-05-28: ABR framing + GOP/profile open-items already on the page; `WATTLAB_SPEC.md` §2.4 corrected.

### §2 — Encode normalization (SHIPPED S34 `88a2696`; Tania's review REMAINING)

The 2026-05-28 ffprobe audit found systematic driver-vs-library default splits across all six presets (VAAPI GOP 120 vs CPU 249–321; `hevc_vaapi` zero B-frames vs libx265 using them; full table in this file's git history / JOURNAL S34). The decisions taken — **the object of Tania's review**:

- **GOP pinned** via `encode_gop_frames` (default 120 ≈ 2 s segments), identical across all six presets; CPU encoders get closed GOP + scenecut-off so cadence is exactly the setting. Validated: all six at avg=max=120.
- **Profiles pinned explicit** (H.264 High, H.265/AV1 Main).
- **B-frames documented as a hardware limit, not normalized** — `-bf 2` requested; the AMD card capped it (reorder depth 1/0). Surfaced per-result in `stream.has_b_frames`.
- **Level left as-is** (cosmetic 4.1/4.0 split).
- **Update path:** GOP → settings; everything else → ONE function `video._norm_args`; any revision **re-runs variance calibration** (re-bases all video numbers — intended).
- **Honesty note for the review (2026-06-11):** these decisions were validated on the AMD/VAAPI card. NVENC defaults differ (B-frame behaviour; `av1_nvenc` has no `-profile` knob — see CR-060's closed record). **Tania reviews against current NVENC reality, not the archived VAAPI numbers.** The motivating VMAF instance stands: same-target AV1 hw vs sw split bitrate honouring AND quality (run `e18a9d57`, hw 90.79 @ target vs sw 92.74 @ undershoot).

### §3 — Output verification (✅ SHIPPED, standing pass)

`video.probe_output_stream()` stamps a `stream` block (codec/profile/level/pix_fmt/bitrate/`has_b_frames`/GOP) on every encode, after the measurement window closes.

### §5 — Comparison-philosophy doc (REMAINING)

Which mode is the headline finding measured under (currently same-bitrate apples-to-apples)? Document explicitly on `/methodology` + home page. An hour of writing once §1 and the review settle.

*(§4 "typical use" mode → CR-045. §6 external-PQA → standing principle, top of file.)*

**Cost:** ~1–2 days remaining, gated on Tania's availability.

### Watch-outs

- **Don't quietly change bitrates mid-experiment** — a §2 revision re-bases the canonical finding; that's deliberate and announced, never silent.

### Open question

Spec-doc ownership: Tania the encoding-spec subsection of `WATTLAB_SPEC.md`, owner the methodology page.

### Cross-references

- **CR-054**: §1's doc becomes the `methodology_ref` for video findings; a §2 revision ships as a versioned finding (`supersedes:` primitive).
- **CR-060 (closed)**: the old baseline-integrity gate was satisfied (S34 → S35 → S36); future §2 revisions no longer affect the captured AMD↔Nvidia comparison.

---

## CR-031 · Deployment portability (DB / power source / containerisation)

**Status:** captured 2026-05-04 (post-meeting). Medium priority. One CR, three sub-sections (they share the question *what does it take to run OWL somewhere other than GoS1?*) — each with its own state: **§1 open decision (the Track A gate) · §2 cheap wins shipped, full backend parked behind CR-065 · §3 nothing built, externally driven.**
**Triggered by:** team meeting 2026-05-04; board 2026-05-11 reinforced §3 (rack hosting — Linode, or Mike's Akamai open-rack offer in Virginia).

#### §1 Persistence — STATUS: open decision, and the gate for Track A (CR-003, CR-007 analytics)

Flat JSON per result (`results/{type}/{date}_{job_id}.json`): fast, debuggable, version-controllable — but no indexing for time-series queries, no atomic transactions, no growth story. Two options:

- **JSON + thin index** — `persist.py` maintains a small SQLite mirror for queries; raw JSON stays source of truth. Cheap, preserves `jq` workflows.
- **Real DB migration** (SQLite → maybe Postgres). Better for history charts, time-of-day carbon UI, multi-deployment merge. Bigger lift.

Decision criteria: if the historical-carbon work (now CR-007 Stage 1) and the calibration-history journals (CR-012, shipped — `results/diagnostics/history.jsonl`; their query friction is live evidence) show real flat-file pain, migrate; else index. Don't pre-decide the engine; REM coherence matters (owner: "I don't want five different databases").

#### §2 Power source — STATUS: cheap wins shipped 2026-06-09 (`power.stamp()` provenance + `meter_display_name`); full backend NOT built

The deferred full shape: `power.py` becomes a dispatcher (`POWER_SOURCE` = tapo | pdu | synthetic) over `power_tapo.py` / `power_pdu.py` / `power_synthetic.py`. Board-added requirements (2026-05-11): every backend declares its **meter resolution**, and confidence must visibly degrade when resolution is coarser than the task ("you cannot be 🟢 on a 4 s encode measured by a 60 s meter" — *resolution-aware confidence is required behaviour, not a watch-out*); the interface must express **one primary reading plus N attributable sub-readings** (utility-grade meter + per-plug PDU stack, Mike's rack model).

**⚠ CR-065 (in flight, owned by a parallel session) is rewriting `power.py`** — meter registry, cached KLAP handles, a shared baseline/task sampler. That registry is a step *toward* this backend (CR-065 says so itself) but is not the protocol. **Do not design or build §2 until CR-065 lands; re-scope this section against the post-CR-065 `power.py`.**

#### §3 Containerisation — STATUS: nothing built; timeline externally driven (Mike's rack / Linode)

`Dockerfile` + `compose.yml`, with explicit acknowledgement of what can't containerise cleanly: focus mode's `systemctl stop` (drop it and document the quality loss, or privileged + /run/systemd — both ugly); GPU passthrough (now `--gpus` + nvidia-container-toolkit for NVENC/CUDA, not the old VAAPI `--device /dev/dri`); settings/calibration are host-specific — **first run on a new host MUST trigger a fresh variance calibration as a startup check**, never a manual step.

### Watch-outs

- Don't migrate the DB silently — migration script + rollback + render-identical test.
- Don't lose calibration when moving hosts — confident-looking readings on an uncalibrated box are worse than none.
- Don't break the bench dev loop — optimise for fast restart, not pristine reproducibility.

### Not in scope

Multi-tenancy / multi-deployment merge; cloud-native rewrite; REM↔OWL data merge (CR-008).

---

## CR-039 · Energy-vs-quality axis for AI jobs (frontier-model-as-judge — exploratory)

**Status:** captured 2026-05-11 (board meeting). **Exploratory, zero implementation** — owner's idea, mixed reception; ship behind a Member/Lab gate, frame explicitly as a snapshot not a leaderboard. **Gated on the standing External-PQA principle's carve-out (top of file): owner ratifies the LLM-judge exception or this CR is dropped.**
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

- **The External-PQA carve-out** (see the standing principle at the top of this file, which carries the full argument): no external authority exists for streaming-adjacent AI quality, so this is an explicit *exception* to the principle, documented on `/methodology` — or the CR is dropped. The principle outranks the column.
- **Judge bias.** A frontier model judging smaller models inherits the judge's own training-data bias. Document this on `/methodology`; pick a judge from a different provider than the candidates where possible (avoid "OpenAI judges OpenAI"). Periodic sanity check with a second judge family; surface divergence if scores diverge meaningfully.
- **Cost spiral.** The budget cap is non-optional. Without it, an enthusiastic Member could rack up real money. Cap enforced server-side per visitor key per day.
- **Staleness.** Models update on weeks-months cadence. The "snapshot date" in the header copy is the single most important framing; don't let it get stale. A periodic refresh of canonical snapshots (same judge, same rubric) keeps the displayed ratios fresh.
- **The cautious voice on the board is on record.** Tania's hesitation was about AI *energy*, not AI quality; CR-039 doesn't trip that exact wire — but the framing must distinguish them crisply or visitors conflate them.

### Cross-references

- **Standing External-PQA principle (top of file):** carries the carve-out tension; resolved (or rejected) by owner judgment.
- **CR-037 (✅ closed):** the streaming-tethered framing for LLM/RAG — quality scoring lives on those tethered pages, not a generic `/ai-judge`.
- **CR-038 (✅ closed):** the verdict line is the natural surface for the quality clause.
- **Retention:** judging stored runs needs retained outputs — CR-064's enhance retention pattern (keep flag, TTL sweep, scoped serving) is the in-repo precedent.

### Priority: medium (exploratory). CR-037 and CR-038 both shipped — the surfaces this rides on exist, so it reads as natural continuation. Decide the carve-out, then build or drop.

---

## CR-041 · New-vs-aged silicon benchmark (chip-instance comparison)

**Status:** captured 2026-05-11 (board meeting). Low priority — opportunistic research finding.
**Triggered by:** GoS board meeting 2026-05-11. Dom: *"from what I understand, CPUs and GPUs — their thermal performance changes with age, and it might be interesting if we could get a comparable chip, a new comparable chip, and maybe Mike could pull one out of one of their recycled bins at the back of Akamai. But it might be worth comparing a brand new chip and one that's been absolutely hammered in a data centre at some point — just because it's yet another interesting statistic that you could benchmark in there."* Mike was warm to the idea.

### Problem

OWL's canonical findings are all from one chip instance (GoS1's Ryzen 9 7900 — paired with the RX 7800 XT pre-2026-05-29, the RTX 5080 since — sitting-room ambient). Whether those numbers generalise to a *data-centre-aged* chip — same SKU, same kernel, but hammered for years — is unknown. CLAUDE.md memory already flags the *ffmpeg* version analogue ("software-aging energy comparison"); this is the hardware analogue. Both speak to the same generalisable insight: *small changes to the run environment shift energy meaningfully, and the streaming industry tends to forget that.*

### Agreed direction

When a comparable chip becomes available (Mike's offer; or any donated/decommissioned matching SKU), tag results by `chip_instance` and publish the new-vs-aged delta as a one-off finding. The only code change ahead of chip access is a new `chip_instance_id` field on the result JSON + hardware-fingerprint surfacing on the result card.

1. **Settings:** `chip_instance_id` string in `settings.json` (free-form: `"gos1-original-2024"` / `"akamai-recycled-2026-05"`). Defaults to a generated UUID with a friendly suffix.
2. **Result JSON:** `hardware.chip_instance_id` written into every result alongside the existing `cpu` / `gpu` fields.
3. **Output is a finding:** `docs/findings/chip-aging.md` with two `source_result_ids` (original GoS1 + donated chip) via the shipped CR-054 machinery; the cross-instance comparison lives in the finding's analysis prose — no bespoke route (keeps the catalog's one-renderer invariant).
4. **Discoverability:** when a new chip_instance appears in stored results, a one-line "chip change detected" note on `/queue-status` so the operator confirms before publishing comparison numbers.

### Lab look & feel constraint

One field on result JSON (invisible to most visitors), one Lab-only findings page. Public visitors see no new UI unless the canonical Key Findings table is later updated with a "new vs aged" row.

### Cost / leverage

~half a day for instrumentation; the experiment itself depends on chip availability. Without chip access, this CR is captured-only.

- ~1h: settings field + result JSON wiring + tests.
- ~2h: the finding markdown + analysis once comparison data exists.
- ~1h: documentation on `/methodology` once the first finding lands.

Leverage: low until a chip exists. When one does, the finding is a sharper version of CLAUDE.md's existing "software changes shift energy" story. Pair with the ffmpeg-version energy test (existing memory note) for a running theme: *"the lab numbers are good; here are the things that move them."*

### Watch-outs

- **The result-JSON field is fine to add ahead of chip access** (forward-compatible); the finding lands *with* the first comparison data, never as a placeholder.
- **Confound: thermal environment.** A chip in a data centre runs cooler and steadier than one in a sitting room. If we compare "aged data-centre chip vs new sitting-room chip", the delta is *aging + thermal environment*, not aging alone. Document the confound; ideally test both chips in the same environment.
- **Confound: power supply.** PSU age also matters. If the aged chip arrives in its original chassis, the PSU is part of the comparison.

### Cross-references

- **CLAUDE.md memory `ffmpeg_version_energy_test.md`:** the software analogue. Land both as a single "things that move the numbers" finding.
- **CR-031:** if OWL is portable, the chip-instance field is the natural multi-deployment merge key.
- **CR-008:** REM ↔ OWL — REM already runs across a fleet; cross-fleet chip-aging data could come from REM rather than from a one-off OWL experiment.

### Priority: low (opportunistic). Stays captured until a chip arrives.

---

## CR-043 · Input/output video preview on the `/video` result card

**Status:** captured 2026-05-14; **premise updated 2026-06-11** — `/enhance-run` result cards now DO show input + output video (CR-064: kept outputs, TTL orphan sweep, browser-playable normalized-stream proxy, visitor-scoped serving). The generic `/video` card remains media-less. **No longer gated on CR-039**: CR-064 solved retention locally and is the pattern to port.
**Triggered by:** owner question — feasibility of input/output side-by-side in a dropdown on the result card.

### Problem

The `/video` result card is metrics + carbon strip + scope notes — no media. A visitor reading "GPU used 81% less energy than CPU on H.265" has to trust that the two encodes produced equivalent output.

### Honesty point (kept — it renames the feature)

Every preset scales to 1080p on both paths, so a side-by-side would NOT reveal the downscale — it reveals the **codec-engine delta** (libx264 vs NVENC at the same ABR), which at 1080p in a browser tab is subtle without still-frame zoom. Name and frame the eventual UI "codec-engine comparison preview", never "see the downscale".

### Cheap fallback (~15 lines, anytime)

Input-only preview of the fixed `test_content/` sources via an allowlist route; `<details>`-lazy single `<video>`. Nothing new stored — no retention, no janitor.

### Agreed direction (when picked up)

Port CR-064's enhance retention pattern to `/video`:

1. Per-result `keep_output` flag, defaulting off (most runs keep `delete_after=True`).
2. Generalise the enhance TTL janitor; visitor_key-scoped serving route (CR-026 scoping honoured).
3. Dual `<video>` in a `<details>`, synchronised seek, lazy-mounted, audio off, "freeze frame at t=" picker — that's where the eye actually sees the codec delta.
4. CR-029's rigor pass is what makes the side-by-side meaningful; CR-039, if built, consumes the same retained artefacts — **converging consumers, not a gate**.

### Watch-outs

- No retention without a janitor (an all-codecs sweep retains six multi-MB files per run).
- No guessable output URLs — visitor_key scoping + token.
- Mobile data: lazy-mount on `<details>` open, label the disclosure.

### Priority: deferred, but unblocked. Natural follow-on whenever `/video` gets attention post-CR-029.

---

## CR-045 · Comparison-mode toggle on the all-codecs comparison (Same bitrate / Typical use / Constant quality)

**Status:** captured 2026-05-22 (owner idea). Rides on the VMAF axis (CR-044, ✅ shipped). **Absorbs CR-029 §4 ("typical use" mode, 2026-06-11)** — same control, same result-framing rule. Sequence after / alongside CR-029's remaining review.
**Triggered by:** owner — *"the compare-all-codecs button could have a toggle: Same Bitrate OR Same Quality"* + team meeting 2026-05-04 (typical-use mode).

### Problem / opportunity

The all-codecs comparison runs **ABR at a fixed per-codec bitrate** ("Same Bitrate"): it answers *"at this bitrate, which codec/device is most efficient, and what quality results?"* That's one of the two questions operators ask. The other — the one that actually drives codec adoption — is the inverse: *"to deliver **this** perceptual quality, which codec/device uses least energy?"* Modern codecs (H.265, AV1) earn their keep precisely here: same VMAF at lower bitrate. Now that VMAF ships on every comparison (CR-044), OWL has the missing half of the picture and can offer an iso-quality mode. This is the iso-quality sibling of CR-003 (iso-energy), surfaced as a clean UX toggle on the existing button.

**Already visible (motivating data, 2026-05-22 clean 🟢 run `e18a9d57`):** at the same 1500 kbps target, `av1_vaapi` (hw) scored VMAF 90.79 in a 20.34 MB file while `libsvtav1` (sw) scored 92.74 in 14.51 MB — VMAF already exposes that the cross-codec/-device comparison is happening at different *effective* quality. A "same quality" mode is what turns that into a fair, operator-facing answer. See CLAUDE.md Key Findings (AV1 hardware vs software).

### The rigor gotcha (must be designed in, not bolted on)

**"Same Quality" is harder than it looks, and the label has to be honest** — straight into GoS's own "if it can't be measured, it shouldn't be asserted":

- The cheap implementation is to swap ABR for **CRF / CQP constant-quality** rate control. But CRF values are **not comparable across codecs** — libx264 CRF 23 ≠ libx265 CRF 23 ≠ SVT-AV1 CRF 23 ≠ VAAPI `qp`/`global_quality`. "Same CRF" is **not** "same quality." A button labelled "Same Quality" that just sets equal CRF asserts something untrue.
- **True** same-quality = **same VMAF**, which ffmpeg cannot target directly. It needs a per-codec **bitrate search** (encode → measure VMAF → adjust → re-encode, ~3–5 passes), i.e. N× the encodes (and N× the energy/time). VMAF (CR-044) is exactly the instrument that makes the search possible.

### Agreed direction — three honest modes, not one mislabelled button

1. **"Same bitrate"** — today's ABR at identical per-codec targets (default; unchanged).
2. **"Typical use"** (ex-CR-029 §4) — each codec at its real-world operating point: provisionally H.264 6000 / H.265 3500 / AV1 2500 kbps (streaming-platform mid-tier; **Tania to confirm against Bitmovin/Netflix tier guidance**). Different question, different honest answer.
3. **"Constant quality (per-codec)"** (V1) — native CQ rate control per encoder. The VMAF column is shown prominently so the visitor *sees* the resulting quality is close-but-not-identical — the honesty is in surfacing the real VMAF, not claiming equality. This is the long-deferred "Benchmark 2 — codec-natural rate control". Cheap: same number of encodes as today.

**V2 — "Match quality (target VMAF)"** as a later fourth state: binary-search each codec's bitrate to a target VMAF ± tolerance, report the energy to deliver it (N× encodes; keep VMAF terminal per CR-044 so search re-encodes never pollute the accepted encode's energy).

UX: one radio control on the all-codecs preset. **The result card's framing line and energy headline must state which mode produced the numbers** — mode names are visitor-facing ("Same bitrate" / "Typical use" / "Constant quality"), not engineer jargon.

### Cost / leverage

Typical-use mode ~half a day (a second bitrate set + mode flag + framing). V1 ~1 day. V2 ~2–4 days. Leverage: high — answers the codec-adoption question directly; "AV1 delivers VMAF 93 at X Wh vs H.264 at Y Wh" is the headline operators care about.

### Cross-references

- **CR-044 (✅ shipped)** — the enabling measurement; V2's search loop consumes it.
- **CR-029** (encoding rigor) — defining "equivalent quality" is Tania's territory; sequence after/with her review so encode-parameter changes aren't validated against a moving target.
- **CR-003** (iso-energy bitrate sweep) — the mirror-image axis (fix energy, vary quality).

### Watch-outs

- **Never label CRF-equal as "Same Quality."** Call V1 "Constant quality (per-codec)" and let VMAF show the spread.
- **VMAF stays a terminal pass** even inside V2's search, so the accepted encode's reported energy excludes all search re-encodes.
- **TODO at V1 build time:** verify NVENC CQ rate-control flags (`-cq` / `-rc`) per codec — replaces the obsolete VAAPI `qp`/`global_quality` analysis; **nothing verified yet**.

### Priority: captured; typical-use + V1 gate behind (or run alongside) CR-029's review. V2 is a later, larger follow-up.

---

## CR-057 · Home page repositioning — findings-first landing

**Status:** **Captured 2026-05-27 (S32 close-out).** Drafted as the last remaining flow change in the findings chain. Code untouched. **Awaiting lab UX review before implementation** — touches the most-visited surface, so the design risk is higher than the mechanical lift. Depends on CR-055 + CR-056 (both ✅ shipped). Will ride the existing `findings_enabled` flag for byte-identical rollback.
**Triggered by:** S32 UX-strategy thread (2026-05-27) — *"an Anonymous visitor reading a finding card and quoting its number in a Slack thread is exactly what GoS wants from OWL — credibility flywheel + member-recruitment loss-leader. Running a job is bonus, not core. Today the UX inverts this: workbench front and centre, findings buried."* Once the catalog exists (CR-055) and has more than one entry (CR-056), the home page is the natural surface to express the inversion.

**Lab look & feel constraint:** central, and the design risk this CR carries. "Findings-first" must not read as a marketing pivot. The page must remain dense, monospace, telemetry-anchored, with zero decorative animation and zero hero copy. The live watts + thermals hero stays — telemetry IS the lab vibe, and removing it would lose what makes OWL credible in the first 200 ms a visitor sees the page. The risk to manage is "more sections + more rows" sneaking density loss into a high-traffic page — see also the standing design principle at the top of this file.

### Problem

Today's `/` for Member/Lab visitors is a *bench launchpad*: live watts hero, then "◆ Guided Tour / ▶ Video transcode / Beta cards (image / llm / rag / video-enhance) / utility links" (`main.py` home route). Anonymous visitors don't even reach this page — they're redirected to `/demo` (CR-001 / CR-026, gated on `WORKING_NAV`).

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

## CR-065 · Dual daisy-chained P110 — staggered polling for ~2× fresh samples

**Status:** logged 2026-06-11; Phase 1 pre-test PASSED same day (2.5× fresh-sample gain — `bin/probe-dual-meter`, `docs/dual_meter_pretest_findings.md`); Phase 2 integration shipped same evening (meter registry + cached KLAP handles, shared sampler in power.py, ci2 combine, `energy.meters` block, `{METER_CADENCE}` token; live-verified against both plugs). **Remaining to close: service restart + variance recalibration under normal ambient (owner).**
**Triggered by:** owner idea 2026-06-11 — daisy-chain a second P110 and alternate polls to halve the effective sampling interval, with a side benefit of hedging single-meter calibration risk.

### Problem

Analysis of the 30 most recent stored results shows 22.5% of consecutive 1s power samples are byte-identical at 10 mW resolution — the P110's local-API `current_power` only refreshes every ~1.3–1.6s, so OWL's 1s polling already loses ~⅕ of polls to stale reads. Short tasks (e.g. 12-poll GPU encodes) pay the price in confidence: n_task is small and a fifth of it is duplicates.

### Agreed direction

1. **Topology:** wall → outer plug → inner plug → GoS1. Inner measures the server alone and is the primary/absolute-W meter (`TAPO_P110_IP`); outer (`TAPO_P110_IP_2`, optional — absent = exact single-meter behavior) sees server + inner-plug self-draw, which cancels in per-meter ΔW.
2. **Phase 1 (done):** `bin/probe-dual-meter` pre-test — fresh-sample gain, inner-plug self-draw stability, cross-meter ΔW agreement, latency/jitter. Gate: ≥~1.5× fresh gain, stable offset, ΔW agreement, latency p95 ≪ stagger slot.
3. **Phase 2 (gated):** meter registry + cached KLAP handles in power.py (side win: kills the per-poll handshake); ONE shared baseline/task sampler the four measurement modules delegate to; per-meter ΔW combined (mean, `SE = √(SE_a²+SE_b²)/2`, `method: "ci2"`); `baseline_samples_w`/`task_samples_w` keep their exact current meaning (inner meter) with a new optional `energy.meters` block; honest cadence copy via a `{METER_CADENCE}` token (claim "fresh samples/s", never "0.5-second intervals"); recal after. Full step list in the approved plan + pre-test findings doc.
4. **KLAP sessions are exclusive per device** (pre-test discovery): every fresh handshake invalidates other sessions on that plug — the registry's cached handles must rebuild on 403/SessionTimeout, and nothing else may poll a registered meter out-of-band.

### Relationship to CR-031 §2

The meter registry is a step *toward* the deferred PowerBackend abstraction, not the protocol itself — PDU/IPMI/synthetic backends stay out of scope here.

### Lab look & feel constraint

No new UI elements; only serve-time wording (meter name already tokenized, cadence token added). Result-card layout unchanged.

---

## Unverified reports (compressed 2026-06-11; re-checked same day — the GosOne→OWL sweep item closed by S43's doc pass)

The old "caught during the session but **not** new CRs" lists (2026-05-01 demo, team meeting 2026-05-04, board meeting 2026-05-11) were compressed 2026-06-11: every item that was marked resolved, absorbed into a CR, or is a meeting note recorded elsewhere (JOURNAL.md / board notes / CR cross-refs) was deleted. The genuinely unresolved residue — **all three possibly mooted by the S42 routes refactor; verify with the named 5–15 min spike before deleting**:

- **Bug (2026-05-01, never reproduced): `/settings` rendered empty mid-run** — suspect the job-state machine showing the page in a transient state. *Spike: start a calibration, immediately reload `/settings`.*
- **Bug (2026-05-11 board demo, unverified): live energy-mix breakdown row missing** from some result tables. *Spike: check the `wlCarbonStrip` mode-detection branch against a recent result card (the S37 guard fix may already cover it).*
- **Bug (2026-05-11 board demo, unverified): `/image` previous-results panel not rendering** — the renderer-drift class. *Spike: load `/image` previous results against the S42-unified shared renderers.*

---

## Groupings & dependencies (rewritten 2026-06-11 — restructure pass: CR-018 merged into CR-007, CR-064 closed, CR-029 §4/§6 extracted)

The **15 active CRs** cluster into a few loose tracks. Each CR remains its own entry — these notes are about where the *next* design session should look first when picking up two adjacent items.

### Track A — Storage / analytics (Tania-elevated 2026-05-07)

Tania's S22 meeting line — *"if we save them somewhere reusable, we can do a lot of really interesting statistics on that"* — made the storage-family decision the gate for the analytics layer; the flat-file-blocker memory says decide before extending `persist.py` again.

- **CR-031 §1** (DB choice with REM coherence — "I don't want five different databases") — the bottleneck/gate.
- **CR-003** iso-energy bitrate sweep + **CR-007** carbon history & variance (merged entry) *(downstream analytics; both outputs land as `/findings` entries via the shipped CR-054 machinery)*.

### Track B — Encoding rigor / quality (Tania-led)

- **CR-029** remainder — §1 pipeline doc (NVENC paths), Tania's §2 review against NVENC reality, §5 philosophy doc.
- **CR-045** comparison-mode toggle (now 3-mode: Same bitrate / Typical use (ex-§4) / Constant quality) — rides with/after CR-029's review. NVENC CQ flags to be verified at V1 build time (replaces the old VAAPI notes — nothing verified yet).
- **CR-043** `/video` result-card video preview — **de-gated** from CR-039; ports CR-064's shipped retention pattern; CR-029's rigor is what makes the side-by-side meaningful.

### Track C — In flight / awaiting review

- **CR-065** dual daisy-chained P110 — **in flight, owned by a parallel session; hands off from this backlog.** Its `power.py` rewrite gates any CR-031 §2 design.
- **CR-057** home-page findings-first repositioning — drafted, **awaiting lab UX review**; ~half a day of mechanical work behind `findings_enabled`; non-blocking.

### Track D — Operator quality-of-life (small, independent)

- **CR-024** re-run thermal-recovery probe from `/settings` (the display shipped; the run endpoint + button didn't).
- **CR-004** visual graphing remainder — no dependencies; CR-007 + the CR-012 history journals are its first consumers.

### Track E — Strategic / exploratory (captured, idle)

- **CR-008** REM ↔ OWL (steps 3–4; branding shipped) · **CR-009** cross-platform web client test bay · **CR-025** RT kernel (parked; re-read its decision frame after CR-065 settles) · **CR-039** AI quality judge (ratify the standing External-PQA carve-out, or drop) · **CR-041** new-vs-aged silicon (awaits a chip).

### Cross-track dependencies summary

```
CR-031 §1 storage decision ──→ CR-003, CR-007 (analytics layer)
CR-065 (in flight)         ──→ CR-031 §2 re-scope (power.py rewrite lands first)
CR-029 (rigor review)      ──→ CR-045 (defining "equivalent quality" is the shared territory)
Standing External-PQA rule ─?→ CR-039 (carve-out: ratify or drop)
CR-064 retention pattern   ──→ CR-043 (port to /video; CR-039 a converging consumer)
CR-041 / CR-007 outputs    ──→ /findings entries (CR-054 machinery, shipped)
CR-057                     ──→ gated only on the lab UX review (flag-protected rollback)
```

### Suggested order (2026-06-11)

1. **CR-065** close-out — the parallel session's to drive, not this backlog's.
2. **CR-057** — schedule the lab UX review; the implementation itself is ~half a day.
3. **CR-031 §1** storage decision — unblocks the analytics layer (CR-003, CR-007).
4. **CR-029 remainder + CR-045** — Tania-led, as her availability allows; a §2 revision re-bases video numbers (re-run variance calibration), designed-for via `video._norm_args`.
5. **CR-024**, then **CR-039 / CR-041 / CR-004 / CR-007 / CR-043** opportunistically; Track E as capacity allows.
