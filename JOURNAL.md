# WattLab — Project Journal

## About
WattLab is GoS's live energy measurement platform. It makes the energy cost of real-world content generation and manipulation visible, credible, and reproducible — using primary measurement data, not estimates. Not a dashboard. Not a calculator. A lab.

Scope: device layer only (GoS1). Network, CDN, and CPE explicitly excluded.

---

## Session 53 — 2026-06-18/19

**Encode-parity & energy-quality calibration — built the harness, ran the first full
campaign, wired the budget page to real data.** Operators fix a VMAF target (commonly
92) and minimise energy to hit it. Two questions: (1) can the GPU encoder reach the
CPU's VMAF — operators say no, "especially AV1"; (2) given an energy budget, how much
video can I push at target VMAF (the `/video/budget` page). Both need one measured
table: per (hardware, codec, quality) → bitrate that hits the target, VMAF, Wh/min.

**New harness `parity.py` + `bin/run-encode-parity`** (importable so the bin driver
and the new `/reconfigure` route share it). Sweeps codec × {CPU, GPU baseline, GPU
tuned} × bitrate ladder × {BBB, Meridian}, 1080p, through the real measured path
(`run_single`-style energy + terminal VMAF). Live `/video` gpu.py args UNTOUCHED —
"tuned" is injected via custom args. Key build decisions:
- **30s clips** (clip-length literature: >15s energy floor, 10s quality convention,
  30s sweet spot). But NVENC is so fast a 30s encode finishes in seconds → too few
  1 Hz power samples. Fix: **repeat the encode back-to-back until ≥20s wall-clock**,
  normalise energy by total content. Result: all 90 rows 🟢 (20–27 samples each).
- **Per-row checkpointing** + `complete` flag (a crash mid-run leaves a valid partial).
- **Operational model: pause, don't stop.** Added a guard so `runtime.power_poller`
  backs off the 5s meter poll while `/tmp/owl-paused` is set — UI stays up, harness
  owns the P110. Needed one service restart to deploy (done this session).

**First full run (90 encodes, 79 min, all 🟢)** —
`results/calibration/encode_parity_nvenc_24c_2026-06-18.json`:
- **Energy:** NVENC **2.5–4.4× less Wh/min** than CPU (h265 biggest: 0.16 vs 0.71) —
  the win is SPEED not lower draw (ΔW ~70W for both; GPU just finishes sooner).
- **Parity:** the "GPU worse, especially AV1" effect is real but ONLY on
  low-complexity content at low bitrate (AV1/BBB gap up to −8.9 VMAF). On Meridian the
  gap vanishes and **NVENC AV1 beats libsvtav1** (default preset) at mid-high bitrate.
- **Tuned NVENC bundle measured and REJECTED for live:** costs 1.6–2.8× energy AND
  lowers VMAF for h264/av1 (AQ trades metric fidelity for perceptual distribution);
  only helps h265 at low bitrate. **Recommendation: do NOT flip the live GPU args.**

**`/video/budget` now measured.** `budget_data.py` loads the artifact, interpolates
the VMAF-vs-achieved-bitrate curves, picks the better GPU profile per codec
(all → baseline), and the page auto-flips illustrative→measured once a *complete*
artifact exists (honest banner: 1080p single-rendition, projected ASIC). Null-safe JS.

**`target_vmaf` (default 92) added to `/settings`** (Encoding section). **Method note
`docs/encode_parity_calibration_2026-06.md`** (Tania-readable, with the literature +
results). **`/video/budget/reconfigure`** (Lab-only) — status + one-button re-cal that
launches the proven harness (pause→run→un-pause); built for when the NetInt cards land.

**Budget-page polish + ABR ladder (same session, cont.):** codec pulled out of the
constraints group into its own **"compare codecs"** axis (it's a comparison dimension,
not a constraint — Ben). **5-rung ABR ladder** defined and built end-to-end: 1080p
(VMAF-target, swept) + fixed 720p@2800 / 540p@1600 / 480p@1100 / 360p@800 (H.264 kbps;
H.265 ×0.6, AV1 ×0.5). Ladder Wh/min = top-rung@target + Σ lower rungs; lower rungs
measured on cpu + gpu_baseline only (tuned rejected), so `--ladder` adds just 48 encodes
and MERGES into the existing artifact (no re-running the 90). `budget_data.py` computes
`ladder_add`; the "Full ABR ladder" toggle is additive on measured data and auto-disables
until ladder data exists. New **`/methodology#energy-budget`** section (operator question,
parity findings, ladder definition, fast-encoder caveat); the budget page links straight
to it. ARCHITECTURE.md updated (parity.py, budget_data.py).

Tests 704. Committed + pushed (e124bf1). The 48-encode ladder pass then ran (all 🟢,
merged → 138-row artifact, has_ladder set, page auto-shows the 5-rung ladder). Full-
ladder VMAF-92 low-complexity Wh/min: H.264 cpu 1.03 / gpu 0.73, H.265 1.91 / 0.79,
AV1 1.37 / 0.74 — the GPU advantage NARROWS across the ladder (~4× at 1080p-only →
~1.4–2.4× full ladder; lower rungs are cheap on both). System back online (un-paused).
⚠ ONE service restart still pending to load the budget/methodology/reconfigure code.
Formal `/findings` entry deferred (lab-review gated). settings.json excluded (live state).

## Session 52 — 2026-06-16

**HDR→4K enhancement unblocked (CR-064 residual #2 closed).** Jon's 2026-06-15
email answered the open question on the `hdr_4k` combo — excluded since
2026-06-10 because `sdr_to_hdr=on` aborted pixop-live (rc 134) at a 4K target,
a GPU-VRAM ceiling (~94% peak, one allocation from the crash). He prescribed two
pipeline env vars: `PIXOP_ASYNC_CAPACITY_SCALE=0.5` (input-buffer scale, default
1.5) + `PIXOP_SR_PROCESSING_THREADS=2` (concurrent SR threads, default 5),
warning throughput would drop.

**Measured them first (no OWL edits, `/tmp/owl_envvar_test.py` + `owl_sd4k_test.py`,
OWL's own baseline/poll/confidence harness, image `2026.06.10`, all arms 🟢):**
- `bbb_hd_clean` 1080p→4K (×2 SR): HDR→4K default peaked **94.0%** VRAM, throttled
  **84.9%** (−1.45 GB); SDR→4K 57.9%→51.0%. fps/wall/ΔW/ΔE all within run-to-run
  noise (≤1%) — **Jon's perf warning did NOT materialise** on single-stream 4K SR
  (compute-bound, not buffer/thread-bound).
- `meridian_sd_dirty` 480p→4K (×4.5 SR), batch AND Live: default **89.9%**,
  throttled **79.7%**, all rc=0. **Could not reproduce a reported hard failure**
  (input needs no normalization, so the test matched the page path exactly).
- **VRAM insight (corrects an earlier assumption):** peak VRAM tracks OUTPUT
  resolution + model footprint, NOT the scale ratio — the ×4.5 480p case (90%)
  uses *less* than the ×2 1080p case (94%). So 1080p→4K is the VRAM-worst combo.
- **Live == batch** for VRAM (the `-re` pacer blocks on the pipe, bounding the
  input buffer — backpressure-OOM hypothesis disproved).
- **Image `2026.06.12` == `2026.06.10`** to the megabyte on VRAM (no ceiling
  shift). Jon's 2026-06-15 FFmpeg-8.1 build is NOT pulled to the box; OWL still
  runs `2026.06.10`.

**Decision (owner): un-block coupled with the throttle, not bare** — the combo
borderline-passes at default but ~90–94% is one unlucky allocation from rc 134;
the throttle (→~80–85%) is what makes it dependable, and it's free on energy.

**Shipped (`pixop.py` / `routes_enhance.py` / `routes_methodology.py`):**
- `_COMBO_EXCLUSIONS` now empty; `_COMBO_ENV` maps `hdr_4k` → the two env vars;
  `preset_combo_key`/`combo_env` helpers; `build_docker_cmd` injects them for
  `hdr_4k` ONLY (every other combo runs bare — energy stays comparable to
  history); result stamps `pixop_env`; combos carry a `throttled` flag.
- `/methodology` "4K HDR — reduced-capacity note" (94%→85%, sub-noise A/B,
  settings recorded in JSON, applies only to this combo).
- Page combo-line "mild throttle applied (hardware memory limit) — energy
  unaffected" note + a hover tooltip on the compare button explaining why
  compare-vs-ffmpeg is HDR-disabled (no apples-to-apples SDR→HDR baseline).
- **Progress-bar parity fix:** `/enhance-run` used the shared `wlRenderProgress`
  but never fed it `elapsed` in the real poll loops (only the placeholder
  teaser did) — so the bar showed stages but no clock unlike `/video`. Added
  `enhRunStart` (set at submit in `startRun`/`startCompare`), passed
  `elapsed: Date.now() - enhRunStart` into both real renders.

Tests: 702 → **704** (`test_combo_env_throttle`,
`test_build_docker_cmd_injects_hdr4k_throttle`; three exclusion assertions
updated). Full record in CHANGE_REQUESTS_CLOSED CR-064 residual #2.

**Exit condition:** if Jon's new FFmpeg-8.1 build (or a later one) lowers the
default-env VRAM ceiling, drop the `hdr_4k` entry from `_COMBO_ENV` to run it
bare (re-test first).

---

## Session 51 — 2026-06-15

**Conference-demo pre-flight (Ben demoing OWL live, remote):** verified server
health (services active, queue idle ~78W, all pages 200), confirmed the Guided
Tour (/demo) and /methodology are operational + current (S49 truth-pass holding;
only nit = methodology footer date 2026-06-09, left as-is). Reminder captured:
the "demo lock" is CR-011 staging mode (`bin/stage-on` → nginx 503 for public,
owner via LAN/SSH tunnel) — there is no separate demo-lock flag (CR-001b was
folded into CR-011). Critical gotcha for a remote demo: must reach OWL via the
SSH tunnel (`ssh -L 8000:localhost:8000 … -p 2222`), not the public hostname.

**GDPR anonymous-analytics bundle (ccb77a9)** — make OWL safe to invite external
traffic to. Audit first found the real gap: anonymous `visitor_key` was persisted
as `a:<raw IP>` (CR-026), and 2 external IPs were already on disk across 7 result
files — personal data, no notice. Fixed end-to-end:
- `analytics.py`: cookie-less aggregate visit counter (day → tier → path), no
  IP/cookie/UA → anonymous statistics outside GDPR (Recital 26). Recorded by an
  HTML-GET middleware in main.py; kill switch `analytics_enabled` (default on).
- `analytics.hash_ip`: truncate IP to /24 (v4) / /48 (v6) then HMAC-SHA256 under
  the server secret, 16 hex. `queue_control.visitor_key` now emits `a:<token>` so
  CR-026 own-results scoping survives without a raw address touching disk.
  `bin/anonymise-visitor-ips.py` (idempotent) migrated the 7 legacy files — 0 raw
  IPs remaining.
- `/privacy` (routes_privacy.py, public, footer-linked): GDPR Art. 13 notice.
- `/audience` (routes_audience.py, hidden Lab-only): visit dashboard, external
  (anonymous) vs member vs lab broken out — the traction view.
- Tests: +test_analytics.py (12); updated the 2 test_queue_control cases that
  pinned raw-IP visitor_key. **702 pass.** Goes live on next restart (tomorrow's
  stage-on); stored-IP migration already applied independently.

---

## Session 50 — 2026-06-13

**Marketing email finalised + scenario framing sharpened** (with Ben, several passes):
mockup index now presents TWO decisions — Decision 1 "do we even need a dedicated
landing page?" (A = today's tour, polished / B = findings-first front page) and
Decision 2 (C = per-finding LinkedIn deep-links, explicitly "not a home-page
alternative", combines with either). Audit doc reframed to match. Service restarted
by Ben → S48/S49 stack live; email links verified live before send.

**Findings embed bug (owner report):** the S48 sweet-spot finding's 16 enhance-type
source embeds all errored ("no renderer for type=enhance") — embed dispatch knew only
video/llm/image/rag AND /findings/source rejected the type. Shipped `wlRenderEnhanceCard`
(single + enhance_compare shapes), registered in both dispatch maps (also fixes /results
expand on enhance rows), allowed the type on the source endpoint, and added the card CSS
findings pages never had (embeds rendered unstyled for every type since the feature
shipped). Guard test: every type cited by the published catalog must be fetchable AND
renderable — fails at publish time, not on the live page. (001cb1e)

**Compare-panel sort** (owner ask): LLM/RAG compare tables now sort small → large by
parameter count at render time (covers stored results). (fd493de)

**Confidence question answered (no code change):** qwen3:1.7b's 🔴 in the last
/llm/compare is NOT a meter problem — ci2 dual-meter was active, p(above idle)=0.90;
it failed the ≥4-task-polls gate (2.9 s generation ≈ 3 polls). Poll gates deliberately
stay on the primary meter (task-duration proxy, S46). Real lever: longer generation for
small models. Also surfaced: mistral-nemo + phi4 answered the compare quiz in 2 tokens —
their mWh/token in that run is meaningless; a minimum-generation floor for compare mode
is the candidate fix (offered, not yet asked).

**PCE-AAC paced-path workaround (Jon's reply: container ffmpeg upgrade has no timeline;
he prescribed ingest-side audio transcode):** new audio-only pre-remux in pixop —
`-c:v copy` (video bit-identical, md5-verified on a real fixture) + AAC re-encode to a
standard channel config, pre-baseline so energy stays clean. 6-ch sources keep 5.1 via
explicit channelmap (PCE streams have NO defined layout — ffmpeg's aac encoder refused
the real fixture; mocks alone would have shipped that bug), others downmix to stereo.
Live 1× runs on 5.1-AAC content work again (audio remux ≠ the FFV1 live-claim guard,
which stands); compares keep their pacing instead of falling back un-paced; upload
notice gains a paced-audio line. (fa6cfda) **687 tests. Pending: one paced container
verification run (Ben budgets it); Ben to Slack Jon re hdr_4k memory-tuning env vars.**

---

## Session 49 — 2026-06-12 (afternoon)

**Anonymous-landing audit** (Ben prepping GoS-website + LinkedIn pointers; audience =
unlogged members + interested strangers who don't know GoS/OWL). Deliverable for
Veronika's Marketing Lab: `docs/anon_landing_audit_2026-06.md` + screenshots. Verdict:
desktop Welcome fold is strong; three launch-blockers — (1) no viewport meta anywhere
(phones rendered desktop-width at ~1/3 scale; LinkedIn traffic is mostly mobile);
(2) zero meta/OG tags (shared links render bare — share-card design/wording needs
Marketing input, still open); (3) tour copy asserted things that stopped being true:
"Mistral 7B via Ollama ROCm" while the button runs qwen3:4b on CUDA, old variance-rule
confidence sentence contradicting the CI step, "full pipeline results pending first
run", hardcoded P110/`812 MB` facts.

**Truth pass shipped (890b712):** tour copy now bakes from live sources at request
time — LLM/RAG model name+size from `llm.MODELS` (new `DEMO_LLM_MODEL` const +
`curated.CANONICAL_RAG_MODEL`; the JS form fields bake from the SAME constants, so
copy and button can't diverge again), GPU encoders/runtime via `_gpu_enc`/`_gpu_runtime`,
video-source facts from `sources.PRELOADED`, image detail from the model catalog,
meter wording via cadence tokens. Hand-typed "previous result" numbers removed — the
Result panels already hydrate the latest stored run. `ui.render_page` now ships
charset+viewport on every page (ad-hoc benchmark tags dropped); image_gen
compare-models scope string routes through `gpu.BACKEND.device_label()` (was
"RX 7800 XT, ROCm"). Guard: `tests/test_demo_copy.py` (model-copy/button agreement,
vendor-flip wording, unreplaced-token leak). **682 tests. Restart pending** (stacks on
S48's: tour fixes + /preview routes go live together).

**Marketing mockups (TEMPORARY):** `routes_mockups.py` — three watermarked, noindexed,
zero-JS scenario pages at the unguessable `/preview-c5d9b3be` prefix (index +
A polished-tour, B findings-first landing, C per-finding campaign page with mock
LinkedIn share card). Real live findings/power data, nothing runnable. Delete the
module + main.py registration once the lab picks a direction. Open for Marketing:
conversion goal, share-card design, homepage-vs-deep-link posting, GoS identity
sentence (draft-marked on the mockups).

---

## Session 48 — 2026-06-12 (overnight, autonomous)

**Upscale sweet-spot sweep executed end-to-end** on the fresh dual-P110 instrument
(recal'd same evening; GPU variance 0.91%): 12 frozen ladder fixtures + 2 real-UGC
anchors → SDR/4K singles + 2 Lanczos compares, **all 🟢**, driven through the live
queue by a resumable orchestrator (survived one death from the service's
VQA-stage event-loop blocking — poll retries added). ~330 Wh total.

**Finding shipped:** `docs/findings/upscale-sweetspot-degraded-sources.md` (16 cited
results). Headlines: (1) energy is set by INPUT resolution (~45 Wh per 45 s 4K-in
clip, ~12–15 Wh HD/SD-in) — predictable before running; (2) quality gain is set by
source badness — >100× ΔVQA-per-Wh spread, sweet spot = worst content, pristine-4K
re-processing buys nothing at max cost; (3) synthetic (BBB) vs cinematic (Meridian)
identical on NR axis, cinematic restores ~20 VMAF points more faithfully on the worst
rung; (4) "looking better ≠ being restored" — NR-near-pristine outputs round-trip at
VMAF 47–81 (FR vs masters possible uniquely because rungs descend from known refs;
doubles as the first CompressedVQA-HDR validation data). Anchors land ON the synthetic
curve — the degradation recipes are validated against reality. AI vs Lanczos: 2–5×
the quality gain at ~23× the energy; Lanczos helped synthetic rungs slightly but
HURT the real 2005 UGC — artifact-character dependent.

**Subpage shipped:** `/enhance-run/ladder` — finding band, Chart.js ΔVQA-vs-source-VQA
curve (3 series incl. anchors), full recipes/results table, view/download grid for all
12 fixtures; data-driven from `manifest.json` + `sweep_summary.json` (graceful while
absent). Linked from /enhance-run's subtitle. **Restart needed to expose the route.**

**Ops notes:** compare runs on the fixtures initially ran 1×-paced and FAILED in the
container's mp4 mux (`aac_adtstoasc`: PCE-based AAC channel config — the fixtures'
5.1 native-AAC audio breaks the paced mpegts path; one for Jon's list), clobbering two
single-run outputs to 0 bytes (same output name); redone un-paced, artifacts
regenerated, FR re-scored. Demo findings-preview test un-brittled (asserts newest-3
contract instead of a hardcoded slug). Tests **668**.

---

## Session 47 — 2026-06-12 (after midnight)

The CR-065 firmware hypothesis, settled by experiment — plus the member email.

**fw refresh-rate hypothesis CONFIRMED (`bin/probe-p110-fw`, new).** A sacrificial
third P110 (shipped on the fast fw 1.3.1, metering Ben's screen + MacBook at
~69 W): 0.0% duplicates in 600 polls at 1 Hz. Updated to fw 1.4.0 — same plug,
same load, half an hour apart: 33.44% duplicates, plateaus {1: 199, 2: 200},
latency unchanged. The 1.5 s refresh is the firmware, full stop; matches the
production outer plug byte-for-byte. Two side discoveries: (1) fw 1.4.0 403-locks
the local API until the app's Third-Party-Compatibility toggle is cycled — an
unattended auto-update on the primary meter would have STOPPED measurements,
not degraded them (auto-update now off on the meters; firmware is formally part
of the measurement setup); (2) "P110" is two distinct EU hardware variants
(owner-spotted by the missing earth prong; distinct `hw_id`/`oem_id` under
identical model/hw_ver strings) on separate firmware tracks — and the latest
fw 1.4.6 (Mar 2026, measured on the second variant) is equally slow at 1.5 s.
Every firmware measured from mid-2024 on is slow; the inner meter's 1.3.1 is
effectively irreplaceable. Plan: acquire + bench-verify 1.3.1 spares (cold spare
for the inner first; outer upgrade opportunistically at a natural power-down —
worth ~10% tighter CIs). Data: `results/diagnostics/p110_fw_*`; findings doc
updated; closed CR-065 record updated to final state.

**WattLab-group email** drafted/iterated with Ben (the half-day-manual vs
10-minute-harness framing is his). Vendor naming policy applied repo-wide:
facts about firmware versions stay, vendor name out of anything critical.

---

## Session 46 — 2026-06-11 (evening)

CR-065 logged and Phase 1 executed in one session: the owner's dual-meter idea
(daisy-chain a second P110, stagger the polls) pre-tested and **gate PASSED — 2.5×
fresh-sample gain**. Spanned the GoS1 rewire reboot (session handoff via plan file +
WIP memory). No service code touched; restart still pending from S44/S45.

**Why it works (disk evidence first).** Before any hardware: 30 recent results showed
22.5% of consecutive 1s samples byte-identical at 10 mW resolution → the P110's
local-API value refreshes only every ~1.3–1.6s; 1s polling already loses ~⅕ of polls
to staleness. So a second independently-clocked meter ≈ doubles fresh information
(it is NOT a 0.5s grid — copy must say "fresh samples/s").

**`bin/probe-dual-meter` (new).** Staggered per-meter asyncio polling, raw mW, cached
KLAP handles with rebuild-on-error, idle/load/idle2 protocol, plain-subprocess ffmpeg
load, gate-metric analysis to `results/diagnostics/dual_meter_*` + history.jsonl.
Deliberately bypasses `power.get_power_watts()`.

**Pre-test results (`docs/dual_meter_pretest_findings.md`).** Gain 2.50× (gate ≥1.5×);
ΔW agreement 78.79 vs 79.63 W (~1%); latency p95 40 ms, 0 overruns. Discoveries:
(1) the plugs are unequal samplers — existing unit refreshes exactly 1.5s (perfect
1,2,1,2 plateau pattern), the NEW unit had **zero dups in 601 polls** (≥1 Hz refresh);
(2) **KLAP sessions are exclusive per device** — the service's 5s poller killed the
probe's cached session on the shared plug within seconds (service stopped for the run);
(3) topology came up reversed vs plan (owner-confirmed: wall → existing → new → GoS1).

**Decisions.** Primary meter swapped to the new plug in `.env` (`TAPO_P110_IP=.91` =
inner, measures GoS1 alone, 1.5× better sampler even single-meter; ~1% cross-unit
epoch note in findings). `TAPO_P110_IP_2=.159` = outer. Phase 2 integration (meter
registry + cached handles, shared sampler, per-meter ΔW `ci2` combine, cadence token,
recal) is specced in CR-065 and the approved plan; next session.

**Phase 2 shipped (same session, post-approval).** power.py grew the meter
registry (`_meter_ips`, index 0 = inner/primary), per-meter CACHED device
handles with rebuild-on-403 (side win: kills the per-poll KLAP handshake the
old `get_power_watts()` paid at 1 Hz), and ONE shared sampler pair
(`sample_baseline`/`sample_task`) that all five modules' legacy-shaped
wrappers now delegate to (video/llm/image_gen/rag; pixop borrows video's).
Secondary meter polls staggered 0.5 s on a parallel task; failure mid-run
fail-softs to flagged single-meter data (`meters: {degraded: true}`), never
aborts. Energy blocks gain an optional `energy.meters` block (per-meter
w_base/w_task/ΔW + outer raw samples + `delta_w_combined`); headline
`delta_w`/`delta_e_wh` become the per-meter mean combine while
w_base/w_task/sample arrays keep their exact historical (inner-meter)
meaning. confidence() gained the `meters` kwarg → method "ci2"
(SE = √(SE₁²+SE₂²)/2, per-meter ΔW against own baseline so the daisy-chain
offset cancels; n_task gates stay on primary poll count — duration proxy).
Copy via new `{METER_CADENCE}`/`{METER_TOPOLOGY_ROW}` tokens (methodology,
demo, ui-config) — claims "1-second intervals on each of two staggered
meters", never "0.5-second intervals". Registered the schema delta in
docs/result_envelope.md; ARCHITECTURE/GOS1_INFRA one-liners. 14 new tests
(parity, stagger, fail-soft, combine maths, ci2 gates, handle rebuild,
ui-config token) → **662**. Live-verified end-to-end against both plugs
(outer−inner ≈ +0.8 W as the pre-test predicted; method ci2 on real data).
**To close CR-065: Ben restarts wattlab, then one variance recalibration
from /settings under normal ambient.** (Both done same evening — recal
20:22, idle 2.18% n=20 — the honest floor: the old meter's stale dups had
compressed measured variance to 1.84%.)

**Late fix — /enhance-run input preview.** After a compare run the page-level
input preview sat dead below the card (the element is created at page load and
never refreshed; the hygiene pause at run-start plus the evening's service
restart left it in MEDIA_ERR_NETWORK with nothing re-setting src) — while the
card's own three fresh players played the same URLs fine. Fix: renderCompare()
hides the page-level preview (the compare card carries its own Source cell —
redundant, Ben's observation); single-run completion revives it via
updateInputPreview() (the single card has no source player); updateInputPreview()
adds vid.load() so a dead element always recovers on selection change.
Verified via headless Chromium with the stored 76b45c71 result.

Continuation of the S44 day. Four threads: Pixop naming, queue toggle, the first
energy-vs-quality learnings from real UGC runs, and the degradation-ladder fixture
library for the upscale sweet-spot experiment. **648 tests.** Service restart pending
(naming + queue toggle).

**Pixop named on /enhance-run (088c249).** Pixop agreed to be named; framed as
member-contributed technology under independent measurement (never promotion). Four
placements (lead-band sentence, symmetric result-card labels, "Contributed technology"
footer block with independence statement + members-can-contribute recruitment line,
one /methodology paragraph), all from a single serve-time source
(`enhance_partner_name/org/url` settings). Old vendor-neutral guard test replaced.

**Queue enable/disable toggle (36aa8ae).** The worker's PAUSE_FLAG (`/tmp/owl-paused`)
predated the UI; /queue-status now has a Lab toggle (`POST /queue/pause`,
`queue_control.set_paused`) sharing the same flag file with external tools.

**First UGC energy-vs-quality learnings (from today's 🟢 runs).** (1) Enhance energy
tracks OUTPUT pixel rate almost linearly (~5.1–5.3 Wh per content-minute at 4K, ~1.4 at
HD, on 15–21 fps sources) regardless of input. (2) Quality gain (NR-VQA) tracks INPUT
badness: 2005 clip +1.83 at 4K vs night clip +0.64 — worst content = best Wh-per-quality.
(3) The compare run's sharpest result: ffmpeg Lanczos to 4K cost 8× less energy and
LOWERED the NR score below source (5.20 vs 5.37) — cheap upscale pays energy to magnify
defects. All within-run NR caveats apply.

**Degradation-ladder fixture library — built, calibrated, FROZEN**
(`/srv/data/owl/test_content/degraded/` + manifest.json, scripts in-dir). For the
SD→4K sweet-spot experiment (energy vs NR-quality gain across source quality).
6 files per source (ref_4k CRF14 / 4k_dirty / hd_clean / hd_dirty / sd_clean /
sd_dirty), 45 s windows (BBB 360 s action; Meridian 100 s office — 480 s/420 s windows
rejected as too dark on eyeball review), dirty rungs = light temporal noise into a
2-pass x264 starved encode (single-pass ABR undershot 2–10× from its high initial-QP
estimate — diagnosed, hence 2-pass). Final NR ladder: BBB 9.58/8.63/9.30/8.10/7.83/5.45,
Meridian 9.86/9.16/9.49/7.95/7.63/6.04 — sd_dirty lands within 0.1 VQA of the real 2005
UGC clip (5.37), sd_clean at the night clip's level (7.89); real clips ride along as
ecological anchors. Source check: held `bbb_4k.mp4` IS the best practical public copy
(Sunflower distribution), held `meridian_4k.mp4` is md5-identical to the official
Netflix Open Content mp4; true Meridian masters are 769 GB IMF / ~2 TB TIFFs — declined,
flagged (a 45 s TIFF window ≈ 135 GB is the affordable true-master fallback). Next:
owner eyeballs the two ref windows, then the measured sweep → /findings entry (+ TBD
subpage off /enhance-run).

---

## Session 44 — 2026-06-11

Jon's (Pixop) reply to the CR-064 questions landed and resolved most of the open list; this
session implemented his prescriptions and gathered the evidence he asked for. **628 tests.**
Service restart pending (new normalize stage + log capture need a reload).

**Input normalization (Jon's fix for both UGC failure classes).** One mechanism kills both
2026-06-10 upload failures: a lossless local pre-conversion to `yuv444p10le` + the `fps`
filter at the detected average rate (VFR→CFR, so `--avsync forcecfr` stays valid), FFV1 in
NUT. OWL improves on Jon's "slight energy skew" trade-off by running the pass BEFORE the
baseline window — the ffmpeg CPU cost never enters a reported figure (the stdin-pipe
variant he offered would have put a full decode inside the window; cf. the +2.6 W
decode-pacing data point). Conditional, not always-on: probe-driven (VFR = declared-vs-
average frame-rate disagreement >0.5%; pixel format outside the verified
{yuv420p, yuv420p10le} set), so the staged clips and every result to date run untouched.
Audio copies when mp4-safe, else AAC (video stays lossless; audio isn't the measurand).
Live 1× mode refuses inputs needing normalization (the mpegts pacer can't carry FFV1, and
a hidden pre-conversion wouldn't be the live scenario it claims to measure). The bulky
intermediate is deleted at run end + swept on TTL if a crash orphans it. Provenance
stamped on every result (`input_normalization`, + `normalized_stream` when performed).
**Post-normalize idle wait (owner ask, same session):** the normalization burst is CPU
work right before the measured pass's baseline, so it ends with the SAME
`cooldown_between_runs` idle-wait the compare flow runs between its passes — floored at a
3-poll power snapshot taken before normalization starts (the dispatcher needs a settle
reference and no baseline exists yet; the snapshot is the pre-baseline equivalent of
pass 1's `w_base`). Wait result stamped at `input_normalization.cooldown`.
**Verified on the real failures:** the VFR night clip (declared 24.83 / average 21.08 fps,
previously rc 1 at frame 427) → rc 0, 914 frames; a synthesized `yuvj422p` MJPEG clip
(the swept 2005-camera file's failure mode) → flagged, normalized, rc 0. NVEncC decodes
FFV1-in-NUT without complaint.

**Per-job log capture.** `run_transcode_subprocess` now writes the FULL command +
stdout/stderr to `<workdir>/logs/<job>_{partner,ffmpeg,normalize}.log` (the result keeps
only 2000-char tails) — what a partner debug request actually needs.

**hdr_4k abort: Jon's VRAM theory now has a number.** Reproduced the 2026-06-10 bisect
conditions (1080p SDR → 4K, `sdr_to_hdr=on`, same `sm120_x2_rs1p0_1920_1080.so` AOTI
model) with 1 Hz `nvidia-smi` sampling: the run PASSED this time at **15,774 / 16,303 MiB
peak (96.8%, ~530 MiB headroom)** with the desktop holding ~389 MiB. A heavier desktop
session on the bisect evening plausibly was the margin — consistent with Jon's
couldn't-reproduce and the intermittent rc 134. `_COMBO_EXCLUSIONS` keeps `hdr_4k` out
until the desktop moves off the 5080 (the Ryzen 7900's Raphael iGPU is present at
`0c:00.0`) and/or Jon's memory-tuning env vars land — at 3% headroom it would be flaky in
production. Log at `/srv/data/owl/pixop/logs/repro_hdr4k.log` for Jon.

**UI:** `/enhance-run` stage strip gains a leading "Normalize" stage (conditional stages
pass straight through for clean inputs); compare strip unchanged (normalize maps to the
first bucket).

**Same-day follow-ups (owner feedback after first live runs):** (1) the post-normalize
idle wait was invisible — it ran under the "Normalize" strip stage and fast settles outran
the page's 2 s poll ("maybe it's there silently" — correct). Now its own stage key
(`normalize-idle`) with the toggle-aware idle label as an explicit strip position, same as
the compare flow. (2) The re-uploaded 2005 MJPEG clip previewed audio-only (browsers don't
decode MJPEG `<video>`); normalization now also writes a browser-playable H.264 proxy OF
THE NORMALIZED STREAM (`preview_<stem>.mp4`, kept past the run, orphan-swept with its
source) — the input picker and the compare card's Source cell prefer it with an honest
"showing the normalized stream" caption. Owner's framing adopted: what we measure against
is the normalized stream, so that's what the preview should show. 633 tests.

**Still open on Jon:** blessed HDR→SDR tone-map (explicitly deferred to Pixop's own
dynamic tone-mapper; `--vpp-colorspace` exists but isn't in the presets), `dnn_scaling`
at ~×4.5, memory-tuning env vars (Slack). Owner ops queued: desktop→iGPU move (changes
idle baseline → variance recalibration required), service restart.

---

## Session 43 — 2026-06-11

Two threads: a `/video` regression report run to ground, and a documentation cleanup pass
(executed overnight on owner instruction). Service restarted twice (01:59 post-S42/CR-064,
and again after the `/video` fix).

**/video "compare-codecs boxes non-selectable" — an affordance bug, not a refactor
casualty.** Owner reported the three batch boxes (Compare codecs CPU / GPU / all) couldn't
be selected. Root-caused via server-log forensics + real-browser reproduction (Playwright
Chromium through the public HTTPS path): the clicks were in fact firing — preview-cmd hits
visible in the journal log — but the boxes had zero selection affordance: no pointer
cursor, no hover state, "selected" was only a 1px border-brightness change, and clicking
one visibly *deselected* the default H.264 Both card, so the control read as dead. Fix:
shared `.batch-box` class (cursor + hover + the same selected border+tint the `.preset`
cards get), `selectPreset` simplified to one class-based selection mechanism; locked boxes
keep the lock-block dimming + `not-allowed` cursor. Guard test added in
`test_codecs_split.py`; commit `47aa150`; **615 tests passing**. The affordance gap dates
back to the S38 codec split — the markup/JS were byte-identical to `v0.8.7`, so the S42
refactor was not the cause.

**Documentation cleanup (overnight, owner instruction).** CLAUDE.md pruned + fact-fixed;
CR-060 moved to closed + CR-052/053/061 back-filled; the groupings appendix rewritten;
README + TESTING.md rewritten to current reality; `wattlab_service_overview.md` stubbed as
superseded; status headers added to the architecture-review / traffic-light /
gpu-swap-checklist docs; GOS1_INFRA.md facts pass + CGNAT/DuckDNS records; this journal's
tail repaired (dead "Phase 6 resumption" runbook deleted, the Sessions 1–5 era reordered
newest-first) + back-filled S38/S40 stubs so the session sequence has no holes.

---

## Session 42 — 2026-06-10/11 (overnight, autonomous)

Refactor **Phases 2–4 complete** — the code restructuring the 2026-06 review planned is
done. Owner went to bed with the goal "complete the code restructuring"; tests were green
(560 → 566) after every one of ~20 incremental commits, and the measurement modules are
byte-identical throughout (energy-imperceptibility rule — no re-baselining needed).

**Phase 2 — page-shell unification.** Every standard page now renders through
`ui.render_page()` (one shell owning doctype, title, auth chip + back link, footer, design
tokens, bundle tags; `back=False` for home, `head=` for chart.js pages). Pages that stay
chrome-less are now an explicit, documented list: `/findings` + single-finding pages (S41
decision), `/methodology` (bespoke topbar + own design tokens — converting it would
visually regress a polished page), the auth/gate family (one deliberate mini-shell,
`_auth_page_shell` — no telemetry chrome on a sign-in page), and the video-enhance asset
404 mini-page.

**Phase 3 — per-feature route modules.** `main.py` went 10,976 → ~430 lines and now holds
*only* app assembly: middleware, the CapabilityError gate handler, startup, home,
`/live` `/power` `/carbon`, `/ui-config.js`, `/queue`(+`-status`), cooldown-decision.
Twelve flat `routes_*.py` APIRouter modules (enhance, benchmark, findings, image, llm,
rag, video, settings, results, demo, methodology, auth) each own their routes, page
template, and `run_*_job` orchestration. New `runtime.py` owns the `jobs` dict + live
telemetry cache + pollers, so feature modules never import main; `ui.py` gained the
serve-time wording config (`_ui_cfg`/`_bake_durations`), the CR-037 AI bands, the CR-060
GPU copy helpers, and `_model_date_line`. `main.py` keeps one commented compat-alias block
(benchmark.py reaches `run_job`/`run_llm_compare_models_job`/`run_rag_compare_models_job`;
tests reach templates + handlers). Testing gotcha worth remembering: monkeypatch the
`routes_*` module that *binds* a name, not main — `test_codecs_split`/`test_delete_result`
updated accordingly. Second gotcha: Python ≥3.12.4 counts TEST-NET `203.0.113.x` as
`is_private` → Lab tier; probe Anonymous with a genuinely public IP (8.8.8.8).

**Phase 4 — result-render contract.** `docs/result_envelope.md` is the new single
catalogue of every `job_type × mode`, its shape, its summariser, its JS renderer, and the
ordered consumer (blast-radius) list. `persist._summarise` is now a per-family
`mode → summariser` dispatch (`_SUMMARISERS`), differential-tested against all 274 stored
results on disk — zero summary diffs. Unregistered modes still summarise (listings never
break) but stamp `"unrecognised_mode"`; the `wlRender*Card` soft-fails now echo the
offending mode (`_wlBadRecord`). `wlCooldownSummary` accepts both cooldown stamp shapes
(`cooldowns` list + the measurement modules' legacy singular `cooldown` dict). New
`test_result_envelope.py` machine-checks that every writer mode is registered. Deferred,
documented: a formal `JobRecord` shape (fix when next touched) and cooldown writer
unification (the singular writers live inside measurement modules — out of bounds here).

ARCHITECTURE.md rewritten to describe the current (post-refactor) state. Rollback anchor
remains tag `v0.8.7`. **Service restart needed** to run the new module layout.

---

## Session 41 — 2026-06-10

Architecture review + start of the 2026-06 refactor (Phases 0–1 of 4). Owner asked for a
critical evaluation of four observations from an external architecture review before any
code moved; full verdicts + the phased plan live in `docs/architecture_review_2026-06.md`
(the deliverable), with a 1–2 page orientation doc at `ARCHITECTURE.md`.

**Review verdicts (measured, not vibes):** main.py = 13,276 lines (60% of the service),
112/191 commits since March touch it, and it *doubled* in the five weeks since the 2026-05-01
access-spine audit — gravity-well TRUE. Blast radius diagnosis AGREED but sharpened: the
bottleneck is the presentation layer (untyped result shapes consumed by string-assembled
renderers — the S37/S38/S39 regressions all lived there). `features/` tree = right direction,
wrong first move (would relocate the mud, and the string-assembly mechanism is exactly what
breaks when code moves — see S38). Rendering extraction FIRST — which was already the
2026-05-01 audit's own post-CR-001 recommendation, never executed. Owner constraint folded
in: containerisation + P110→PDU power backends is a mid-term priority — verified the metering
surface is already one module (`power.get_power_watts()` is the only read path), so the
PowerBackend protocol (mirroring `gpu.BACKEND`) is an independent parallel track; Phase 1's
kill-import-time-baking is itself a container prerequisite (runtime-injectable config).

**Phase 0:** CR-063 branch merged to main (fast-forward); previously-untracked deliberate
files committed (DEMO_GUIDE, data_exports/, ForTania static CSV); `VERSION` → 0.8.7 and an
annotated **v0.8.7 pre-refactor checkpoint tag** pushed to GitHub as the rollback anchor
(505 tests passing at the tag). Stale `main.py.bak` / `*.session15*` clutter deleted.

**Phase 1 — front-end extraction (the S37/38/39 regression class, structurally removed):**
- The five shared JS bundles left their Python strings for real files:
  `static/wl-live.js` (0.7K), `wl-carbon.js` (56K), `wl-progress.js` (6.7K),
  `wl-result.js` (44K), `wl-bench-hydrate.js` (1K). Extraction was AST-based
  (byte-exact values out of main.py, no retyping). The module constants
  (`_CARBON_JS` etc.) now hold `<script src="/static/wl-*.js?v={sha}">` tags, so
  all ~20 inclusion sites were untouched.
- **Import-time baking is gone.** New `_ui_cfg()` resolves the settings-driven copy
  (toggle-aware cooldown labels, baseline polls, meter name, registry URLs) per request;
  it feeds both `_bake_durations()` (page HTML, serve-time as before) and a new
  `/ui-config.js` route serving `window.WL_CFG` (`Cache-Control: no-store`).
  `wl-progress.js` builds `WL_*_STAGES` from `WL_CFG` in the browser; `wl-carbon.js`
  reads the source URLs from `WL_CFG.urls`. Consequence: cooldown-label / meter copy
  changes now apply on the next request — the "restart needed for the label fix"
  constraint (S38, S39) is structurally dead.
- main.py: 13,276 → **11,356 lines** (−1,920).
- Tests 505 → **555**: new `tests/test_ui_config.py` (settings flip visible in the next
  /ui-config.js response without reload; no leftover `{TOKEN}`/`__TOKEN__` in bundles;
  every referenced bundle exists + serves; **`node --check` syntax-gates every static/*.js**
  — the check the in-string era never had). `test_js_bundling.py` reworked to assert over a
  page's *effective* JS corpus (HTML + referenced bundles), same ReferenceError class
  guarded. `test_external_links.py` repointed at wl-carbon.js + WL_CFG.urls.
- Deployment check: live nginx already serves `/static/` directly from disk (CR-011 work),
  **exempt from `limit_conn 3`** — so the new parallel bundle fetches can't 429 like the
  S33 findings embeds did. The repo's `infra/wattlab.nginx.conf` had drifted from live
  (missing the maintenance + static-from-disk + certbot blocks) — synced from
  `/etc/nginx/sites-available/wattlab`.
- One extraction bug caught by the new guards themselves: the script wrote the unconverted
  carbon JS (URL `__TOKEN__`s intact); `test_external_links` + the token guard flagged it,
  fixed in place. The guards earn their keep on day one.

**Service restart needed** for pages to ship the new `<script src>` tags (old process still
serves the inline-JS HTML; no broken intermediate state either way).

NB: S40 (2026-06-08, CR-063 `/enhance-run` Pixop integration, 505 tests) shipped without a
full journal entry — see git log `CR-063` and CHANGE_REQUESTS_CLOSED.md.

---

## Session 40 — 2026-06-08

*(back-filled stub, 2026-06-11)* CR-063 — Pixop partner-transcode integration: hidden
`/enhance-run` page (AI-vs-ffmpeg upscale comparison) behind the `ENHANCE_RUN` capability,
new `pixop.py`, 73 new tests → 505. Recorded in git log under `CR-063`; no full journal
entry was written at the time.

---

## Session 39 — 2026-06-03

CR-062 follow-up: three reported bugs in the `/image` "compare 4 models" run, plus a
factoring audit of the whole cooldown surface (owner asked to confirm cooldown logic is
single-sourced so future tweaks apply everywhere). Diagnosed against the actual stored
result `results/image/2026-06-03_13a5b4c3.json` before touching code.

- **"Cooldown displayed as fixed 10s" despite wait-for-idle ON — the real bug.** The
  per-page *inline* progress-strip labels hardcoded `{COOLDOWN_S}` (image `STAGE_LABELS`
  `main.py:~11124`; `/llm` CPU-vs-GPU strip `~4843`), which `_bake_durations` substitutes to
  `"10"` **regardless of the toggle**. CR-062 (S38) only made the *shared* `WL_*_STAGES`
  toggle-aware via the `{COOLDOWN_LABEL}` token — it missed these inline compare-page labels,
  so they kept claiming a fixed "(10s)" after the switch. Fix: added a single toggle-aware
  `{COOLDOWN_PAREN}` token to `_bake_durations` (`"(→ idle)"` vs `"(10s)"`) as the one place
  the parenthetical is decided, and repointed both labels (and the new per-gap labels below)
  at it. `{COOLDOWN_LABEL}` is now defined as `"Cooldown {COOLDOWN_PAREN}"` so there's one
  decision. The "20s / 21s" the owner saw at the foot of the result was never wrong — that's
  `wlCooldownSummary(r.cooldowns)` rendering the *real* measured idle-waits (both
  `method=idle, settled=true`); only the strip label lied. They now agree.
- **Only 3 of 4 models shown — NOT a render bug.** `sdxl-lightning` genuinely fails to load
  (UNet-only checkpoint, no `model_index.json`) and is **first** in the panel, so the runner
  caught it (`image_gen.py:469`), recorded it in `model_errors`, and continued with the 3
  survivors — which the stored result faithfully holds. Because `floor_reference_w` is only
  set after a *successful* run (`image_gen.py:451,483`), model #1's failure also caused the
  first inter-model cooldown to be skipped — which is exactly why the owner saw **2**
  cooldowns, not 3. The real defect was that `wlRenderImageCard` **silently dropped the
  failure** (unlike `wlRenderComparePanel:2353`, which surfaces `model_errors`). Fix: render a
  `⚠ <model>: <error>` note in the image compare card. (`sdxl-lightning` cannot run on this
  box at all — it's the cached-but-unwired model from the S30 audit; owner to uncheck it in
  `/settings` if they want a clean 3-up. Not auto-disabled — settings is live state.)
- **Progress strip misaligned (nice-to-have).** `COMPARE_STAGES` carried the literal string
  `"cooldown"` once per gap (3× for 4 models); JS `indexOf(stage)` always resolves to the
  *first* match, so every later cooldown snapped the indicator back to the m1→m2 position —
  compounded this run by the skipped first cooldown. Fix: unique per-gap keys
  `cooldown_<i>` in the strip + label `"Cooldown before <model> {COOLDOWN_PAREN}"`; `pollJob`
  maps the runner's generic `"cooldown"` stage to `cooldown_<current_model_idx>` (the idx the
  strip key was built with). The runner's *emitted* stage string is unchanged, so every
  substring `indexOf('cooldown')` detection path (live idle-floor display, etc.) is untouched.
- **Factoring audit — cooldown logic is single-sourced for behaviour + wording, per-caller for
  orchestration.** Centralized (tweak once → applies to `/video /llm /image /rag` + compare
  pages + any future page): strategy/mechanism `power.cooldown_between_runs` +
  `_await_cooldown_decision` (all ~14 call sites route through it; no inline `asyncio.sleep`
  cooldown remains — the residual sleeps are poll intervals + LLM VRAM-unload settles, a
  distinct concept); tunables in `settings.py`; wording in `_bake_durations`
  `{COOLDOWN_PAREN}`/`{COOLDOWN_LABEL}`; result-footer in `wlCooldownSummary`; live "waiting
  for idle" via the job-dict fields the dispatcher stamps. NOT centralized (per-workload by
  necessity): which baseline is `reference_w`, when to cool, and how the result is stamped.
  Noted wart: the stamped key is inconsistent — N-way compares use a `"cooldowns"` list,
  CPU-vs-GPU "both" runs a singular `"cooldown"` dict, and the per-entry label varies
  (`before` / `before_codec` / `before_model` / `before_mode`); the `cd` payload inside is
  always the dispatcher's identical dict. A consumer reading result JSON must handle both shapes.
- **Tests: +4 in `test_cooldown.py` → 432 passing.** Three pin `_bake_durations`' toggle
  behaviour (`{COOLDOWN_PAREN}`/`{COOLDOWN_LABEL}` flip with `cooldown_wait_for_idle`); one is
  a source guard — `test_no_page_hardcodes_a_fixed_second_cooldown_label` fails CI if any page
  reintroduces a raw `{{COOLDOWN_S}}`, forcing future pages onto the toggle-aware token. No
  enforcement that a future page calls the dispatcher rather than an inline sleep — that stays
  convention (dispatcher docstring + memory note).
- **Not committed** at session end: the `main.py` + `test_cooldown.py` edits (awaiting owner's
  go), plus the usual uncommitted `settings.json` (live calibration state) and untracked
  `data_exports/` + `static/dl-…` ForTania export. **Service restart required** for the label
  fix to show (owner runs `sudo systemctl restart wattlab` — not in my sudoers).
- **NB:** JOURNAL has no Session 38 full entry — CR-062 shipped (commit `c430217`) with only
  its CLAUDE.md one-liner written, never a JOURNAL block. Left as-is (not reconstructing it
  from git); flagged here so the S37→S39 gap isn't read as a lost session.

---

## Session 38 — 2026-06-02

*(back-filled stub, 2026-06-11)* CR-062 omnibus: unified cooldown / wait-for-idle
(`cooldown_wait_for_idle` toggle + `power.cooldown_between_runs` as the single execution
path), `/video` codec split, queue resume routing, JS bundling fix; 392 → 427 tests. Full
record lives in the CR-062 closed entry in CHANGE_REQUESTS_CLOSED.md.

---

## Session 37 — 2026-06-01

Two long-standing `/demo` guided-tour bugs fixed at the root (owner: *"You've fixed both
these problems several times, but it keeps coming back. Might need a deeper fix than the
last times."*), plus `/findings` chrome polish.

- **Tour no longer trappable on the LLM / Image steps.** Symptom: stepping to LLM (or
  Image) offered only "run a standard generation" with no way to advance until you actually
  ran one; Video and RAG were fine. Root cause: `/demo/last/{llm,image}` returns the
  *newest* persisted result, which is frequently a `compare_models` / `rag_compare_models`
  record (their `task` is `None`, so the old `"RAG"`-prefix filter never excluded them).
  Those carry no top-level `.energy`, so `renderLLMResult` / `renderDemoImageResult` hit an
  early-return guard that re-shows the run buttons and **never called `revealNext`** —
  `renderVideoResult` / `renderRAGResult` have no such guard, which is exactly why Video and
  RAG worked and LLM/Image didn't. Fixes: (1) `goStep` now reveals the step's Next button
  **on entry** for steps 1–4 unconditionally — tour navigation is never gated on a renderer
  recognising the pre-loaded shape (kills the whole class); (2) defensive `revealNext` added
  to both guarded renderers' early-return branch; (3) `/demo/last/{llm,image}` now filters on
  `mode` (single inference / single cpu-gpu image) rather than the unreliable `task` text, so
  the single-run card never receives a compare record and shows "format not recognised".
  Added `summary["mode"]` to the llm summariser to support the filter.
- **Findings embeds no longer 404 for non-Lab visitors — the *real* root cause found.**
  Symptom: every finding page showed "could not load video/<id> (HTTP 404)" for its source
  measurements. Cited finding sources are lab-measured (`visitor_key=None`); the embed JS
  fetched `/results/<type>/<id>/download.json`, which applies **CR-026 visitor scoping**, so a
  non-Lab visitor (`a:<ip>` / `m:<email>`) never matched the lab record → 404, every time.
  Prior fixes chased the job_id parsing and the markdown ids; the visitor filter was the wall.
  **Why it kept coming back: the test suite runs as Lab (TestClient = loopback), so the scoped
  404 was invisible to every test.** Fix: new endpoint
  `/findings/source/{type}/{job_id}/download.json` — a *scoped* CR-026 carve-out (same pattern
  as `/demo/last`): loads with `visitor_key=None`, but only for a result a published finding
  actually cites (gate built from `findings.list_all()` source ids — not a general bypass).
  Pointed both the embed-hydration JS and `findings.result_download_url` (the "raw measurement"
  link) at it. Added 3 regression tests pinning the carve-out's content + gate, deliberately
  visitor-independent.
- **/findings chrome.** Index gets a "Beta · under development" badge beside the H1 + a
  `← Home` back link (and `<title>` → "OWL — Findings (Beta)"); each finding page gets an
  `OWL / ← All findings` breadcrumb so it's no longer a dead-end. Kept the bespoke finding
  footer (carries permalink + version + citation metadata) rather than swapping in the full
  `_FOOTER` with its floating queue badge / live-telemetry poller on what is a static
  publication page.
- **Tests 389 → 392** (391 passing). The lone failure `test_encode_norm` is pre-existing and
  unrelated — fails identically with this session's changes stashed, tied to the uncommitted
  `settings.json`.
- **Not committed:** `settings.json` (live calibration/bench state, per convention) and the
  untracked `data_exports/` + `static/dl-…` ForTania export.

---

## Session 36 — 2026-05-29 (GPU swap — first light, RTX 5080)

The RTX 5080 is **in the box and detected**. `gpu.BACKEND` auto-resolved to `NvidiaBackend` with zero code edits (CR-060 working as designed): card at PCI `02:00.0` (GB203), driver `610.43.02`, CUDA UMD 13.3, `OWL_GPU_VENDOR` unset. iGPU (Raphael) correctly did *not* false-detect. First investigation was the owner's question: **why is idle power so much higher with the new card.**

- **Idle is higher, and it's real — but smaller than the GPU sensor suggests.** Vendor-neutral **wall idle rose ~57–59 W (AMD frozen baseline) → ~79 W (5080) ≈ +20 W / +34%** (P110, n=8, genuinely idle: GPU-util 0%, only Xorg resident). This +20 W is the honest, defensible number.
- **The GPU-sensor "4 W → 18 W" jump is mostly a sensor-scope artifact, NOT a hardware finding.** AMD `power1_average` reports a partial/core power domain; Nvidia `power.draw` reports *total board* power — exactly the CR-060 open Q. Third-party board measurements put both cards close at idle (5080 ~18 W, 7800 XT ~19–23 W), so the true GPU-level idle gap is small. **Do not report 4→18 W as a real +14 W.** Confirmed: `read_sensors_dict()` now returns `gpu_ppt_w: 17.9` from the Nvidia path.
- **The card is idling correctly — not a pathology.** P8 perf state, 180 MHz core / 405 MHz mem (floored), nothing pinning clocks high. Web consensus: **17–18 W in P8 is textbook-normal for a 5080** on Linux open-kernel drivers (healthy range 13–25 W). The scary "140 W stuck idle" reports are a *different* misconfig, not us. So the higher idle is the architectural floor of a 360 W Blackwell card with 16 GB GDDR7, not something "broken."
- **Both cheap levers measured = non-levers; +20 W is intrinsic.** Persistence OFF: 78.6 W (vs 79.0 ON — inside noise). Headless (`isolate multi-user.target`): 80.8 W — **no saving**, because the monitor stayed physically connected so the kernel kept scanning out a text console; the GPU sat at P8/19 W regardless. The real lever is **"no connected display," not "no GNOME"** — confirmed by inspection (card0 = the 5080, HDMI-A-2 connected). Reverted to `graphical.target`; boot default never changed, so all of this was runtime-only and fully reversible.
- **5080 idle is strongly display-state-sensitive (new methodology note for the A/B).** Settled/blanked desktop → P8, 180/405 MHz, ~17–19 W GPU → **~79 W wall**. *Active* (non-idle) desktop → P3, 1500/7001 MHz, 16 % util, ~40 W GPU → **~101 W wall** — a ~22 W wall swing purely from screen-on vs blanked. GNOME `idle-delay = 900 s`, so it returns to the blanked floor 15 min after the last input. **Implication: the AMD↔Nvidia A/B must compare matched display states** (the overnight AMD baseline ran display-connected and screen-blanked, so the like-for-like 5080 figure is the ~79 W blanked one). Decided **not** to unplug HDMI / go headless for the A/B — it would shave watts but break comparability (same reason headless is out) and remove the physical-console fallback (mitigation if ever wanted: move the cable to the motherboard iGPU port — frees dGPU scanout, keeps a console — but that's a separate "true headless server" baseline, not the A/B).
- **Ruled out the multi-display idle pathology + confirmed matched cabling.** Owner noted a short DP-to-motherboard cable that was present for the AMD card and reconnected for the 5080. Checked: the 5080 reports **only one connected output (HDMI-A-2, the monitor)**; all three DP ports read `disconnected`, so that cable is inert to the GPU's display engine (no second framebuffer → no "stuck at max mem clock" multi-display penalty — the card does fall to P8/405 MHz mem when blanked). Net: cabling is **matched across both baselines** and not a contributor — the +20 W is the card itself, not a topology artifact.
- **HDMI-unplug diagnostic (someone on-site, fully reversible) — a blanked-but-connected monitor costs ≈0 W.** 6-min rolling monitor across an unplug/replug from the *settled* P8 state: GPU dead flat at P8/405 MHz/0%/~18 W throughout; wall drifted ~79→72 W (≤5 W, inside noise — possible display-link power the GPU PPT sensor misses, inconclusive). The proprietary Nvidia driver never updated the `/sys/class/drm` connector status on hotplug (holds it via Xorg), so power was the only reliable signal. Conclusion: the idle penalty is the **active desktop (P3, +22 W)**, not the cable being plugged in — and it self-clears via the 15-min blank. Owner's separate observation — **AMD drops to idle in ~seconds, the 5080 lingers** — is the *active→idle ramp-down*, not measurable from an already-idle start; flagged for a dedicated load→decay timing test (run server-side, no on-site help needed).
- **Load A/B still pending.** Only the pre-swap AMD benchmark (`e29ccef7`) exists on disk; the post-swap NVENC CR-061 re-run hasn't happened. Under-load energy comparison (does NVENC's ~4× VAAPI energy win hold? does the +20 W idle floor eat into it on short jobs?) is the next benchmark.
- **Post-swap A/B — full n=10 benchmark (`benchmark/2026-05-29_f56dfa77`, 24 steps, overnight 23:27→03:52).** Matches the AMD baseline scale (n=10, both 120 s sources). Supersedes the earlier quick n=2 run (`46772ea7`), which gave the same directional read. **GPU transcode (NVENC vs VAAPI), meridian:** H.264 0.376→0.218 Wh (−42 %, 19.4→12.3 s, VMAF +1.2); H.265 0.315→0.247 Wh (−22 %, −16 %, VMAF −2.0); AV1 0.312→0.233 Wh (−25 %, −22 %, **VMAF +1.9**). bbb similar; **NVENC AV1 the standout — +4.3 VMAF on animated content** where VAAPI AV1 had collapsed (81.5→85.8). NVENC quality equal-or-better in 5 of 6 cases (H.265 the only give-up, −2 VMAF). Energy CV now 1.8–4.5 %. **CPU-path contamination resolved at n=10:** CPU energy matches AMD (H.264-CPU 0.40 vs 0.40, H.265-CPU 1.24 vs 1.28, AV1-CPU 0.62 vs 0.64 Wh) — same encoder + silicon, validates the bench. Residual: the first step per rep (H.264-CPU) still captures an elevated ~108 W baseline from the GPU's P3 linger, but it inflates baseline *and* task equally so deltas stay clean.
- **AMD baseline VMAF correction.** The frozen `docs/gpu_swap_amd_baseline.md` had claimed "no VMAF this run" — **wrong**: all 120 cells of `e29ccef7` have VMAF populated. Added the VMAF column to both AMD tables + corrected the caveat. CPU-path VMAF is byte-identical across the AMD and Nvidia runs (same libx264/x265/SVT-AV1), which validates the A/B. (Doc-drift hazard again — see memory `claude-md-prose-can-drift-from-disk`.)
- **Idle↔load crossover computed.** Total-energy model `E = W_idle·T + Σ ΔE_encode`; the 5080's +20 W idle = **480 Wh/day** that its per-encode NVENC savings must repay. Break-even GPU duty cycle (120 s clips, meridian): **H.264 ≈ 43 %** (saving 0.158 Wh/encode), **AV1 ≈ 90 %** (0.079 Wh), **H.265 never** (0.068 Wh × max throughput 6128/day = 417 Wh < 480). So the swap is **energy-positive only for H.264-heavy, near-saturated** workloads; for H.265 the idle penalty is never repaid by transcode alone. Reframes the swap as a **capability / quality / speed upgrade, not a same-workload energy win.** (Caveat from the n=2 run — CPU baseline contamination — is resolved at n=10; CPU figures now match AMD, see above.)

---

## Session 35 — 2026-05-29

GPU-backend abstraction (CR-060) shipped **pre-swap**, and the first overnight benchmark analysed into a frozen AMD baseline. Sequencing was deliberate: capture the AMD numbers and lock the abstraction while the AMD card is still in the box, so the upcoming RTX 5080 swap (hopefully later today) yields the AMD↔Nvidia comparison for free.

- **AMD pre-swap baseline frozen — `docs/gpu_swap_amd_baseline.md`.** Analysed the overnight orchestrated benchmark `e29ccef7` (24 steps, 0 errors, 6h31m): variance calibration + 20 video reps (3 codecs × CPU/GPU × 2 sources, n=10) + LLM/RAG/image panels. Headline: VAAPI GPU beats CPU ~4–4.5× on energy and ~4× on time for H.265/AV1; ~a wash on H.264 energy but ~2× faster. GPU PPT under load ~46–52 W (idle ~4 W). Caveats recorded: variance ran at **3.07%** (warm-ambient, not the clean 1.29%), **no VMAF** that batch (energy-only), AV1-CPU/bbb cv≈40.6% (one outlier), and the LLM panel's "capital of France" prompt gave 2 models a 2-token denominator (mWh/tok artifacts). Full provenance (all 21 result IDs) in the doc.
- **CR-060 abstraction shipped.** New `wattlab_service/gpu.py` resolves `AmdBackend` / `NvidiaBackend` / `NoGpuBackend` once at import into `gpu.BACKEND` — a card swap + reboot is picked up with zero code edits. Each backend supplies GPU sensor read, ffmpeg GPU encode pieces (hwaccel / scale filter / encoder / norm args), torch env setup, device label, and a provenance `stamp()`. Refactored: `power.read_sensors_dict` (GPU half delegates; `amdgpu_chip` kept as alias), `video.py` (3 GPU presets → `_gpu_cmd()`), `image_gen.py` (HSA env + device label), `persist.save_result` (stamps `gpu_hardware = {vendor, name, encode}` — key is `gpu_hardware` not `gpu`, since video both-mode already uses a top-level `gpu`). Methodology Hardware table dynamic via new `gpu_display_name` setting (curated default kept). **AMD output proven byte-identical to the pre-refactor literals by `tests/test_gpu_backend.py`** → no ΔWh re-baseline. 339 → 385 tests.
- **Deliberate reversal: auto-detect, not explicit config.** CR-060's locked decision #2 was an explicit `gpu_backend` setting. Owner's instruction this session — *"swapping a new GPU just requires a reboot"* — explicit config can't satisfy (needs a settings edit). Shipped auto-detect (nvidia-smi → sensors amdgpu → none) as default, keeping the explicit intent via an `OWL_GPU_VENDOR` override + the per-result stamp. Owner okayed: *"let's go for autodetect, then when I get back with the new card we'll see if it works or whether we were too ambitious."*
- **Env open-question resolved.** The existing `/usr/local/bin/ffmpeg-master` **already ships** `h264_nvenc` / `hevc_nvenc` / `av1_nvenc` + the `scale_cuda` filter — no ffmpeg rebuild needed for the swap. Confirmed `-rc cbr` valid (ABR-equivalent); `av1_nvenc` has no `-profile` knob (omitted). Still pending on the physical swap: torch `+rocm6.2`→`+cu12x` wheel + Nvidia driver/CUDA.
- **Not committed:** `settings.json` — its working-tree diff is the warm-ambient 3.07% recalibration (which we agreed not to bake into git, see memory `variance-calibration-ambient-sensitive`) plus unrelated CR-061 bench config. Left as live state per convention; the `gpu_display_name` default lives in `settings.py` DEFAULTS, not `settings.json`.

---

## Session 34 — 2026-05-28

CR-061 in-app benchmark orchestrator + CR-029 §2 encode normalization (commit `88a2696`). `benchmark.py` + `results/benchmark/` — a multi-step run (variance → video all-codecs reps → llm/rag/image compare panels) driven from the app, each step referencing the individual result files it produced. This is the orchestration that produced the S35 overnight baseline. (Brief entry — backfilled S35; see commit for detail.)

---

## Session 33 — 2026-05-28

S32 close-out + md tidy + overnight calibration. The S32 evening shipped the findings-chain (CR-054 / 055 / 056 / 058) and CR-012 (variance + thermal-probe history journals); this session migrated all five to `CHANGE_REQUESTS_CLOSED.md`, drafted CR-057, fixed two `/findings` bugs surfaced by the lab review, pruned the repo's `.md` files, and kicked off an overnight variance calibration to refresh the idle/cpu/gpu numbers.

- **Findings chain shipped (S32 evening, commits `5f9a53b` / `fc58816` / `10d68c9`).** CR-054 data model + AV1 worked example (`docs/findings/av1-hw-sw-vmaf-tradeoff.md`, backed by result `video/2026-05-22_e18a9d57.json`); `findings.py` loader; `GET /findings/<slug>` route gated by `findings_enabled` flag. CR-055 `/findings` catalog index page + shared `_findings_catalog_rows_html` row renderer. CR-056 bulk import of 5 more findings (ABR all-codecs, SD-Turbo, LLM cold, RAG faithfulness, input-master sensitivity) — editorial markdown only, zero Python per CR-054's invariant. CR-058 `/demo` step 7 rewire (catalog preview replaces the session-echo; capability matrix below untouched). 315 → 334 tests over the chain.
- **CR-012 shipped (commit `ec583ef`).** `persist.append_history_line(category, data)` helper; variance calibration appends to `results/variance/history.jsonl` (post-`cfg.save`, only on success — aborted runs don't pollute); `bin/probe-thermal-recovery` appends a summary line to `results/diagnostics/history.jsonl` after CSVs close (`mean_within_window_cv_pct` across d≥5s, `settled_floor_w` at max distance, computed by re-reading the summary CSV). Both append paths non-fatal (try/except + stderr log) so a journal write can't break a measurement. Migrated to `CHANGE_REQUESTS_CLOSED.md`. 334 → 339 tests.
- **CR-057 drafted (commit `bc3909d`).** Home-page repositioning to findings-first — touches the most-visited surface so the design risk > mechanical lift. Captured with open questions (anonymous redirect retire? findings count on `/`? bench-launchpad collapse?) for lab UX review. Not blocking — `/` stays as the bench launchpad until the lab decides. Same `findings_enabled` rollback flag.
- **`/findings` bugs surfaced + fixed.** Lab review caught (a) `wlCarbonStrip is not defined` console errors on every finding page — the page injected `_RESULT_JS` (card renderers) but not `_CARBON_JS` (defines `window.wlCarbonStrip`); fix is one extra include in `_finding_page_html`. (b) HTTP 429s on findings with multiple embedded measurements — nginx caps concurrent connections at 3 per IP (`limit_conn wattlab_conn 3` on `location /`), and the hydration JS fired all embeds in parallel via `forEach(async ...)`; rewrote to a sequential `for…of` loop with awaited fetches. The "Loading measurement X…" placeholders progress visibly rather than 429-ing.
- **MD tidy.** CLAUDE.md "Recent sessions" trimmed (S26–S28 collapsed to one-liners), "Key Findings to Date" replaced by pointers at `/findings` + `docs/findings/` (the catalog is now canonical; prose duplication here was a known drift hazard, see memory). README.md stale references fixed — version `v1.2.0` → `v0.8.6`, LLM model list updated to the S30 post-refresh panel (Qwen3 / Mistral-Nemo / Phi-4 / GPT-OSS instead of Mistral 7B / Gemma 3 12B), Key Findings section collapsed to catalog pointers. Active CR appendix: count corrected (`17` → `15` after the 5-CR migration), cross-track diagram + Suggested order re-flowed with CR-057 as the one remaining flow change in the findings chain.
- **Overnight variance calibration.** Snapshot `settings.json`, set `variance_runs=32, variance_cooldown_s=60`, kicked off via `POST /variance/run`. Up to 4 attempts allowed before giving up — on each fail, the cooldown / runs combination bumps (60→90→60 with n=48→both maxed). "Decent" = no abort AND `variance_idle_pct < 5%`. Pass → keep auto-saved settings.json + the new history.jsonl line. Fail → restore snapshot. Results land in the morning summary.

---

## Session 32 — 2026-05-27

CR-051 RAG corpus self-service shipped end-to-end. Owner asked to enable Member-tier doc upload with audit trail (*"to protect against any (unlikely) bad intentions, we need to be able to remove documents too, but also track when a doc was added and who by"*); design + implement + tests + close all in one session.

- **`corpus_manifest.py`** (new) — single-file source of truth for corpus provenance. `corpus/manifest.json` keyed by filename, `corpus/audit.log` append-only NDJSON. Helpers for `can_delete(tier, email)` (the security boundary in one place — 8 tests pin it), `sanitise_filename()` (strips `../`, restricts to `[A-Za-z0-9._-]`, `.pdf` extension), `unique_filename()` (auto-suffix on collision), `member_usage()` (for quota enforcement), `ensure_entry()` (self-heals manifest gaps for files dropped in out-of-band), `migrate_existing_corpus()` (idempotent one-shot — ran once, stamped 101 existing PDFs as `origin=Lab`).
- **`rag.py`** — incremental index helpers: `add_doc_to_index(filename)` chunks + embeds + `collection.add()` with globally-unique ids (`<filename>#<i>`) so a single upload re-indexes in 3–8 s instead of the full 60+ s rebuild. `remove_doc_from_index(filename)` is one `collection.delete(where={"source": filename})` call.
- **Three new endpoints in `main.py`:** `POST /rag/upload` (RAG_CORPUS_UPLOAD-gated; size cap, %PDF magic-byte sniff, per-Member quota check, sanitised filename, manifest record, background incremental index, audit log entry); `DELETE /rag/doc/{filename:path}` (RAG_CORPUS_DELETE_OWN-gated; in-handler tier×ownership check because the rule mixes tier with per-row ownership; defensive basename + traversal guards; unlink + chunk drop + audit); `GET /rag/audit` (Lab-only; last 200 events).
- **`/rag/corpus-list` enriched** with `origin` ("Lab" | "Member" — aggregate label only, no email exposure to non-Lab callers), `added_at`, per-row `can_delete` tailored to the visitor, member usage counters, and caps.
- **`/rag` page UI** — corpus browser inside the existing `<details>` block: per-row origin chip (green Member / muted Lab), added-on date, `×` delete button (only rendered for rows the visitor can act on), upload form (Member-only, with live quota display, dashed-border block above the list). Member-uploaded docs sort to the top so users find their own first.
- **`capabilities.py`** — new `RAG_CORPUS_DELETE_OWN` (Tier.Member). Snapshot test updated.
- **`settings.json`** — three new caps (Lab uncapped): `rag_upload_max_mb=50`, `rag_member_doc_count_cap=10`, `rag_member_total_mb_cap=200`.
- **15 new tests** in `tests/test_corpus_manifest.py` pinning the sanitisation defences (path traversal, charset restriction, extension enforcement, empty-name handling), the collision-suffix logic, the can_delete tier×ownership matrix (Anonymous never; Lab anything; Member own only; Member blocked from Lab-origin docs even though they have the cap), manifest round-trip, `ensure_entry()` self-healing, `member_usage()` per-email aggregation, and migration idempotency. **Tests: 292 → 307.**
- **CR housekeeping.** CR-051 shipped one-session so went straight to `CHANGE_REQUESTS_CLOSED.md` with full writeup including hardening notes (the 6 security musts) + Phase 2 follow-ups (title field UI, audit-log viewer page, background re-index on disk drift). Active CRs: 15. CLAUDE.md header updated. VERSION 0.7.2 → 0.8.0.

---

## Session 31 — 2026-05-27 (overnight autonomous run)

AI-comparison trilogy close-out — CR-048 / CR-049 / CR-050 all landed and shipped under one umbrella session, running parallel to S30's picker UX work. The conversation arc was: define the energy-per-correct-answer framing for LLM (CR-048), mirror it on RAG (CR-049), then notice that the per-surface model dicts are drifting and refactor everything to a dynamic catalog (CR-050). The thermal-floor + Ollama-eviction + 🔴-filter follow-ups all rolled into CR-050 once it became clear they were one coherent measurement-quality story.

- **CR-048 `/llm/compare`.** Hybrid landing: anonymous showcase (3 tabs — Strawberry / Carol / Addition — from the 2026-05-26 probe), member "Try your own" prompt + expected-answer + run-on-all-models. Headline metric is **Wh per correct answer** — mWh/token is kept as a supporting column on the comparison table because the inversion (a verbose model can have the lowest mWh/tok but the highest total Wh) is the perverse incentive worth showing visitors. New `POST /llm/compare-models` endpoint (BATCH_COMPARE gated), new `grade()` helper in `llm.py` (substring or leading-integer, case-insensitive, punctuation-stripped retry for list-style answers). 2-chart strip (Wh vs params, mWh/tok vs params) under the headline, gated at ≥3 trusted-correct rows.
- **CR-049 `/rag/compare`.** Same shape as CR-048, calls existing `run_rag_measurement` per-model in a sequential loop. Showcase BBC prompt ("325 GWh", 4/4 ✓ from the RAG probe). Bust-card tagline tuned for the RAG-specific failure mode (a wrong bigger model probably hallucinated past the retrieved chunk; a right smaller one trusted it). "Try your own question" surfaces a graceful "ask the GoS team to add documents" note since corpus upload is deferred Phase 2.
- **CR-050 dynamic model catalog.** `model_catalog.py` shells `ollama list` (filters image-only entries, normalises `:latest` away, sorts by parsed param count) and scans `~/.cache/huggingface/hub/` for image models (slugs short, full HF repo in `repo` field). `llm.MODELS` / `rag.MODELS` / `image_gen.IMAGE_MODELS` are now `_ModelsView` proxies — drop-in dict interface, source of truth is the catalog ∩ per-surface enable list. New `/settings` Models section with 3 checkbox panels (LLM / RAG / Image) that write to `llm_enabled_models` / `rag_enabled_models` / `image_enabled_models` and call `model_catalog.refresh_all()` on save. Adding a model is `ollama pull <name>` + tick + save — no code, no restart.
- **Active-probe thermal floor (started as a CR-050 follow-up, became core).** New `power.wait_for_thermal_floor(reference_w, tolerance_w=3.0, poll_interval_s=1.0, settle_polls=3, max_wait_s=120)`. Replaces the fixed `llm_rest_s` sleep between models in all three compare flows. Reference = first model's baseline (cold). Asymmetric settle: `w ≤ reference + tolerance` counts as settled (i.e. "at or below floor"), because if the system cools *further* than the reference there's no reason to wait for power to climb back up. Several iterations to get right — initial ±5 W → ±3 W; symmetric `abs()` → asymmetric `≤`; 2 s poll → 1 s poll for tighter UI feedback.
- **Ollama keep_alive eviction (the silent bug behind "cooldown never reaches floor").** Observed mid-run: 7-model compare baselines were climbing 60 W → 130 W after just three small models because Ollama's default 5-min keep_alive left every previously-run model resident in VRAM (~60 W of permanent draw each). The thermal-floor wait was correctly waiting — the "floor" just couldn't be reached because the VRAM-resident models inflated it. Fix: new `llm.unload_all_loaded_models()` queries `/api/ps` and sends `keep_alive=0` to every resident model; called at the start of every compare run AND before every thermal-floor wait. The compare runner records the eviction list as `cooldowns[].evicted_before_wait` for diagnostics.
- **🔴 noise handling.** "Cheapest correct" pick, bust card, "vs best" ratio column, and the size-vs-energy charts all filter out 🔴 rows (CR-028 confidence flag). 🔴 rows still display in the table (greyed + italic via a `.noisy` class) so visitors see what each model said — they're just explicitly disregarded for rankings. Confidence column added to the table.
- **N-way `/image/compare`.** `run_image_compare_models_measurement` no longer hardcodes SD-Turbo + SDXL-Turbo — iterates every enabled image model. Result returns a `models` list (legacy `small`/`large` aliases set to cheapest/priciest by Wh/image for backwards-compat). `wlRenderImageCard` compare branch iterates `r.models` — N image columns, N KPI cards, N confidence flags, with the legacy 2-model path preserved as fallback for old stored results. `COMPARE_STAGES` + `STAGE_LABELS` built server-side from `IMAGE_MODELS.items()` and injected.
- **4 Hz UI cooldown ticker.** Server polls P110 every 1 s; UI polls `/job/{id}` every 2 s; the displayed `cooldown_waited_s` could otherwise tick in 1-2 s jumps. Local `setInterval(renderRunStatus, 250)` interpolates between server values for a smooth counter. Resets on each server update; stops on done / error / new run.
- **Banner counts dynamic.** `/llm` and `/rag` banner text now derives "Compare N models" from `len(MODELS)` instead of a hardcoded number that always lags reality.
- **Tests:** 290 → 290 passing. No new test files this session — work was an architectural refactor (catalog) + measurement-quality plumbing (thermal floor, eviction, 🔴 filter) + JS UX (ticker, charts, N-way render), all on paths the existing suite + `TestClient` page-render checks cover.
- **CR housekeeping.** CR-048 + CR-049 + CR-050 all migrated to `CHANGE_REQUESTS_CLOSED.md` with full writeups including follow-up notes (Phase 2 items, backwards-compat). Active CRs: 18 → 15. `Suggested order` preamble bumped to S31 close-out. VERSION 0.4.0 → 0.7.1 over the arc of the session.
- **Showcase data regenerated (overnight).** Showcase tabs on `/llm/compare` and `/rag/compare` re-baselined on the new 7-model panel using the active-probe thermal floor, replacing the older 5-model probe data and the Wh estimates (the showcase now carries real P110 measurements). See the autonomous-run summary at the end of the chat transcript for the per-prompt headline numbers.

---

## Session 30 — 2026-05-27

Picker UX polish package — three small items riding on the S29 variants schema. Closed two CRs (CR-033, CR-046), filled in one CR-047 follow-up, and noticed a parallel-session CR-048 had landed in the docs (`/llm/compare`).

- **Source vignettes — thumbnails extracted + rendered in the `/video` picker.** Three small JPEGs (`gos.jpg` t=25 s · `meridian.jpg` t=60 s · `bbb.jpg` t=180 s) extracted via `ffmpeg -ss <t> -frames:v 1 -vf scale=160:-1 -q:v 3`, ~3–6 KB each, stored under `wattlab_service/static/source_vignettes/`. Wired into each parent's `vignette` field in `sources.py`. `_video_source_picker_html()` extended to render a 32 px-high `<img>` left of the parent header (gracefully no-op when the field is `None`), preserving the lab-look density.
- **CR-046 closed — BBB Phase 2 FOKUS-match dropped.** Built a PIL-only dHash matcher to find the BBB frame closest to the FOKUS event header still. Best Hamming distance was 18/64 (top 3: t=136 s, t=146 s, t=216 s) — weak match. Visual confirmation revealed why: the **FOKUS image is post-processed BBB content with added laser-eye effects**, not a literal frame, so no automatic match is meaningful and a literal extract would only approximately resemble the stylised header. Closed the CR with the generic `bbb.jpg` (t=180 s) already satisfying the identifying-thumbnail goal. Investigation artefacts cleaned up from `/tmp`.
- **CR-033 closed — codec chip-row on `/demo` step 1.** Two `<button class="demo-chip">` elements above the run button, H.265 (default, mapped to `h265_both`) + AV1 (mapped to `av1_both`), both on `meridian_120s`. `selectedDemoCodec` JS state variable + `selectDemoCodec(codec)` updates chip styling + run-button label; `runDemoVideo()` reads the choice for the form-post. Chips use inline styles in the OWL accent vocabulary (no new CSS class needed), reset on each page load (no localStorage — demo is a fresh first impression). Result-card rendering needed zero changes (codec-agnostic `renderBoth`). Open questions from the CR resolved: H.265 is the default (more familiar), chip choice doesn't persist.
- **CR-047 follow-up — source identifier on result JSON.** `run_job()` gained a `source_key: str = None` kwarg; `/video/use-source` passes the variant key through; after the result is built (`run_all_measurement` / `run_both_measurement` / `run_video_measurement`) and before `save_result`, the code stamps `result["source"] = {"key": …, "parent": PRELOADED[key]["_parent"]}` when a source key is set. `/video/upload` (custom file) leaves it unset. Cheap, additive, unlocks future filtering / analytics on the variant schema as Track A (storage) work eventually moves.
- **Parallel-session CR-048 noticed in active CRs.** While auditing the doc state for this session's package, a CR-048 entry was found in `CHANGE_REQUESTS.md` that wasn't from this conversation — a separate session shipped Phase 1 of `/llm/compare` (energy per correct answer, BATCH_COMPARE-gated, 3-prompt showcase + Member "Try your own"). New page, new endpoint, grader helper in `llm.py`. Not touched by S30 — flagged in CLAUDE.md as the latest active capture.
- **CR housekeeping.** CR-033 + CR-046 migrated to `CHANGE_REQUESTS_CLOSED.md` (both with full closure writeups + the FOKUS-image-is-stylised investigation captured under CR-046). Active CR count: 16. CLAUDE.md "Last updated" header + Recent sessions list bumped.
- **Tests:** 290 → **290 passing** (no new test files this session; the work was code refactor + UI + persistence plumbing, all on paths the existing suite + `TestClient` render checks already cover).

---

## Session 29 — 2026-05-26

FOKUS Berlin prep + the variants-schema refactor. Mostly two CRs (CR-046, CR-047) plus a UX bug surfaced by the first, plus pre-design measurement work that meaningfully narrowed the second's scope.

- **CLAUDE.md pruning pass (early session).** Network topology updated — Nighthawk RAX120 retired (the Bbox got a Wi-Fi 7 upgrade, so the wireless AP is gone); shipped `[x]` items in "Deferred / open" dropped (CR-022, CR-026, `_HEADER` factorisation, etc. — all in `CHANGE_REQUESTS_CLOSED.md`); S10–S25 session log trimmed to one-liners with the full detail living here in JOURNAL.md; "See also" header collapsed. Active count line was already stale by one (S28 said 17 but the count was actually 16 after `a0bba8c` migrated CR-035 to closed).
- **CR-046 — Big Buck Bunny preloaded for FOKUS Berlin demo.** FOKUS MWS 2026 uses a BBB scene in their event header, so having BBB as a one-click `/video` source closes the loop visually for booth visitors. **Phase 1 shipped:** the canonical 4K 60 fps H.264 master from archive.org (`big-buck-bunny-4k-60fps`, 642 MB) placed at `/srv/data/owl/test_content/bbb_4k.mp4`, plus a stream-copy first-120 s extract (`bbb_120s.mp4`, 102 MB) for the fast-demo slot. Both wired into `sources.py`. **Phase 2 deferred** — a vignette (still image taken from the FOKUS-matched frame, used as the `bbb` parent's UI thumbnail — no measurement purpose); URL of the FOKUS header preserved in the CR body; revisit closer to the event.
- **The hardcoded-radio gap.** Adding `bbb_4k` to `sources.py` didn't make it appear on `/video` — the picker was a hardcoded radio block in `main.py:~2807-2845`, not driven by `sources.get_all_sources()`. Patched short-term by adding two more radios; surfaced as the immediate target of CR-047.
- **VMAF stage in the progress widget.** Owner reported the BBB-full `h265_both` run "looked like it restarted" after the encodes finished. Root cause: `_attach_vmaf` set `stage="vmaf"` on the job dict but neither `_BOTH_MAP` nor `_ALL_MAP` had a `'vmaf'` key, so `stageMap[serverStage]` returned `undefined` → the widget defaulted to stage 0 (Baseline). Fixed: added `'VMAF (quality)'` to `_BOTH_STAGES` / `_ALL_STAGES` between `GPU encode` and `Done`; mapped `'vmaf'` → new index; bumped `'done'` index by one. Server side `_attach_vmaf` now also clears stale encode-progress fields on entry (so the bar doesn't sit at 100 % through VMAF) and surfaces `vmaf_total` / `vmaf_done` so the widget can render "VMAF · 1 of 2 encodes scored". `renderProgress` reads those fields and emits an extra line below the bar during the VMAF stage. Warning text on the two full-length radios bumped to reflect VMAF cost: Meridian-full `~6-8 min` → `~14-18 min incl. VMAF`; BBB-full `~5-7 min` → `~12-16 min incl. VMAF` (user observed >15 min real-world).
- **Pre-CR-047 design tests — input sensitivity.** Owner sketched a 5-per-source variant matrix (original + 2-min mid + 2-min high-complexity + 2-min low-complexity, plus a vignette slot that was later clarified to be just a parent-level still image for UI friendliness, *not* a measurement variant) and asked to *measure* whether complexity matters before committing to the picker complexity. Two tests ran end-to-end through `/video/upload` from loopback (Lab tier), each three 2-min variants × `h265_both` ≈ 30 min wall.
  - **Test 1 — input bitrate (CRF span, same codec).** Three `bbb_120s` siblings re-encoded H.264 at 15 / 5 / 1 Mbps (`light` / `mid` / `aggro`). Spread: **CPU ΔE 1.7 %, GPU ΔE 4.9 %** — at noise floor (`variance_pct` = 1.29 %). Verdict: input bitrate doesn't move re-encode energy. (Quality side did: aggro source lost ~2.3 VMAF on the GPU output — the hardware encoder can't recover what the source threw away; software encoder absorbed it.)
  - **Test 2 — codec-of-origin (industry-typical bitrates).** Three 1080p siblings at H.264 5 Mbps / H.265 3 Mbps / AV1 2 Mbps. Spread: **CPU ΔE 3.4 %, GPU ΔE 10.3 %** — borderline. AV1 carries the entire jump (H.264↔H.265 is +1.3 %; H.265↔AV1 is +8.8 %). Why GPU shows it more sharply: OWL doesn't apply `-hwaccel vaapi`, so software decode runs on CPU even on the GPU encode path — on the fast GPU path it's a proportionally bigger chunk. Bonus VMAF finding: higher-quality source codec → higher output VMAF even at lower bitrate (AV1 2.3 Mbps gives VMAF 88.2 GPU vs H.264 5.1 Mbps giving 87.0).
  - Both findings + 6 result JSON IDs + bench harness paths captured in `docs/input_sensitivity_findings.md`. Variants kept at `/tmp/bbb_120s_*.mp4` until the next prune.
- **CR-047 — parent + variants schema for `/video` Source picker (shipped same day).** Schema rewrite in `sources.py`: new top-level `SOURCES` list (parent dicts with nested `variants`); each parent has `{id, name, credit, license, vignette, variants: [...]}`, each variant has `{key, label, description, length: full|extract, path}`. New accessors: `get_grouped_sources()`, `get_variant(key)`, `get_parent_for(key)`. Legacy surface (`PRELOADED`, `get_source_info()`, `get_all_sources()`) preserved as derived views over `SOURCES` — every existing call site stays valid. Per-variant info now also carries `variant_label` (short form, "2 min extract"), `parent`, `parent_name`, `length`. Picker rewrite in `main.py`: new `_video_source_picker_html()` helper renders the entire radio block from `get_grouped_sources()` (small dim parent header + radios in the same density / border style as before); the hardcoded ~60-line block in `video_page()`'s f-string collapsed to `{source_picker_html}`. Radio order preserved exactly (`gos_in_50s, meridian_120s, meridian_4k, bbb_120s, bbb_4k`). The empirical pre-test collapsed the candidate 5-variant matrix to **2 variants per parent** (full + 2-min extract); the vignette stays plumbed as an optional parent-level still field (no UI rendering yet). **Deferred to follow-ups:** vignette rendering in the picker (CR-046 Phase 2 territory), source identifier on result JSON (`result["source"] = {key, parent}`), parent+variant card framing.
- **CR housekeeping.** CR-046 stays active (Phase 2 vignette still open); CR-047 migrated to `CHANGE_REQUESTS_CLOSED.md` with full Phase-1-shipped writeup. CR-046's body updated to reflect both Phase 1 components shipped + CR-047 unblocking Phase 2. Suggested-order preamble bumped to S29 close-out. Active CRs: 17 (down from 18 mid-session). `docs/input_sensitivity_findings.md` is the new empirical reference for any future "should this be a picker variant?" decisions.
- **All-member-meeting bullet list drafted.** Owner asked for a punchy findings summary for this week's all-member meeting email; produced one grouped by Video / AI / Carbon / Measurement integrity, ~10 bullets with ⭐ on the genuinely surprising findings (RAG faithfulness divergence; French grid 65.8→26.9 in two years; AV1 hw-vs-sw energy↔quality tradeoff). Lives in the chat transcript; not committed to docs.
- **Tests:** 272 → **290 passing** (added `tests/test_sources.py`, 18 tests pinning both the new schema shape and the back-compat surface — PRELOADED keys, `get_all_sources()` order, `get_grouped_sources()` structure).

---

## Session 28 — 2026-05-22

Big session: the measurement-quality axis (VMAF) and the confidence-model rebuild, plus member comms and a doc/CR cleanup.

- **CR-044 — VMAF perceptual quality on comparison cards.** Added `video.compute_vmaf()` (fail-soft, routes through `ffmpeg_bin`'s libvmaf — the embedded `vmaf_v0.6.1` model, no model file needed). Runs as a **terminal pass after measurement closes** (in `run_both` / `run_all`, after lock release + focus exit) so its CPU draw is never polled — energy numbers stay clean. A live trial caught the key gotcha: `av1_vaapi`/VAAPI outputs decode to 1088px (macroblock padding ffprobe hides), so the distorted is **cropped** (not scaled) to the reference dims before scoring. Surfaced below output size in `renderBoth`, the all-codecs matrix + per-codec detail, and the shared `wlRenderVideoCard` (prev-rows/`/demo`). Settings `vmaf_enabled` / `vmaf_n_subsample` (temporal only) / `vmaf_n_threads`. `analyse()` gains a `quality_note`. Verified CPU 91.48 / GPU 91.31 on a real H.265 run.
- **CR-028 Phase 2 — unified CI confidence (Tania §9 v2).** New shared `confidence.py` replacing the four near-identical variance-threshold copies: `SE_final = max(SE_calibrated, SE_per_run) + SE_drift` (additive worst-case drift — Ben's call), `confidence_positive = Φ(ΔW/SE_final)`, 🟢 ≥0.95 & ≥`conf_green_polls` / 🟡 ≥0.80 & ≥`conf_yellow_polls`. Raw `baseline_samples_w` + `task_samples_w` now persisted in every result energy dict (all four modules; `measure_baseline` returns a dict). Option C: only `variance_idle_pct` feeds the single-run flag; cpu/gpu CVs reserved for a future aggregate layer. **Legacy fallback** keeps old results' badges (`method` = `ci` | `variance`). Absorbed CR-020 + the 5×/2× grounding. Copy rewritten: popover, `/methodology` Confidence Framework, `/llm` band, `/settings` (CI vs legacy split + calibration blurb). Two follow-up fixes: short runs (1 task poll) now use the CI model → 🔴 instead of leaking to legacy-🟡; null positive-thresholds coalesce to defaults so a config typo can't crash a run.
- **Key Finding ⭐ — AV1 hardware vs software.** Clean ≥10s all-🟢 run `e18a9d57`: at the same 1500 kbps target, `libsvtav1` (sw) 14.51 MB / VMAF 92.74 / 0.71 Wh vs `av1_vaapi` (hw) 20.34 MB / VMAF 90.79 / 0.32 Wh. Hardware AV1 uses ~55% less energy but ~2 VMAF lower + ~40% larger — SVT-AV1 is markedly more bit-efficient. First OWL result pairing energy with a measured quality axis. Recorded in CLAUDE.md Key Findings; cross-ref'd in CR-045 + CR-029.
- **CSV export fixes.** Numbers was collapsing the export to ~2 columns: it sniffs the whole file for a delimiter and the leading `#` disclaimer carried a semicolon. Moved the disclaimer to a trailing `#` line and removed the semicolon entirely (comma is now the only delimiter-like char); added the `vmaf` column.
- **CR-045 captured** — "Same Bitrate / Same Quality" toggle on all-codecs compare. Framed as two honest designs: V1 "Constant quality (per-codec)" (CRF/QP = the deferred Benchmark 2; VMAF shows the real spread) and V2 "Match quality (target VMAF)" (iso-VMAF bitrate search). Caveat front-and-centre: CRF is not comparable across codecs, so never label CRF-equal as "Same Quality." Gate with/after CR-029.
- **Housekeeping.** Versioning footer + reproduce bundle already in place from S26/S27. Member email drafted (covering VMAF, AV1 finding, CI confidence, carbon, AI-tethering, and the magic-link sign-in change). CR-028 + CR-044 migrated to `CHANGE_REQUESTS_CLOSED.md` (active CRs 17); appendix re-based; CLAUDE.md / WATTLAB_SPEC.md confidence copy brought current; deferred list pruned. `settings.json` now carries the new `vmaf_*` + `conf_positive_*` keys with `conf_green/yellow_polls` back at the documented 10/5.
- **Tests:** 237 → **272 passing** (new `test_vmaf.py`, `test_confidence.py`).

---

## Session 27 — 2026-05-21

### What we did

A short follow-up session: a versioning / build-stamp feature, the CR-037 readout bug, and the deferred CR close-out migration.

**CR-037 readout bug fixed.** The S26 per-result *"This run ≈ N× a 120 s 1080p H.265 GPU encode"* line wasn't appearing on the live `/llm` and `/image` cards. Root cause: enrichment was always correct (the field is on disk — `result.energy.video_relative`), but the readout had only been wired into the *shared* CR-034 renderers (`wlRenderLLMCard` / `wlRenderImageCard`, which drive `/demo` + prev-row click-to-expand), while the **live** cards on the main pages use separate bespoke renderers (`renderLLMSingle`, `renderLLMAll`, the `/image` `renderResult`). Added the one-liner to those three too — now shows on every surface.

**Versioning + build stamp.** `VERSION` (0.4.0) + `version.py`, resolved once at startup: prefers a committed `version.json` (container-friendly, CR-031), falls back to live git (short SHA + commit date + dirty flag), then a `"dev"` fallback — all fail-soft. The footer on every page now carries `OWL v0.4.0 · <sha> · <date>`, with a `-local` marker when the running tree is dirty (OWL runs straight from the working tree, so uncommitted edits go live on restart — the flag keeps the stamp honest). `persist.save_result()` stamps every result with `owl_version = {version, sha, dirty, built_at}` — code provenance for CR-040 reproduce bundles and Track A analytics (re-flagging after a formula change); the reproduce `expected.json` carries it too. Methodology version (0.4) deliberately kept separate (citable measurement-protocol version vs. code provenance). `tests/test_version.py` (3). 234 → **237 tests**.

**CR close-out migration.** Moved the full **CR-027 / CR-037 / CR-040** bodies from `CHANGE_REQUESTS.md` to `CHANGE_REQUESTS_CLOSED.md` (S26 marked them closed but left the bodies in active for a sweep). `CHANGE_REQUESTS.md` is back to active-only — **17 entries**. The Groupings & dependencies appendix was re-based: Track D and Track G are now fully shipped, and the cross-track diagram + Suggested order point at the remaining work (next up: CR-029 prep + the Track A storage/DB decision, then Track C).

**Process note.** The `session-close` skill (added S26) isn't registered with the harness until a Claude Code restart, so this entry was produced by running its procedure directly.

---

## Session 26 — 2026-05-20

### What we did

The "credibility & recruitment" CR bundle (the documented top-3 Tania-independent priorities), plus an external-links cleanup and a session-close skill — work picked deliberately while CR-028/CR-029 stay blocked on Tania's §9 v2.

**External-links registry + a carbon-strip regression caught and fixed.** Fixed a stale link first (the carbon strip's "Framework: Language Lab AI position paper" pointed at `/methodology`, not the paper PDF), then centralised every external URL in `main.py` into one registry (`POSITION_PAPER_URL`, `GOS_URL`, `JOIN_GOS_URL`, `GOS_LOGO_URL`, `GITHUB_REPO_URL`, `GITHUB_ISSUES_URL`, `ECO2MIX_URL`, `ELECTRICITYMAPS_URL`, `EMBER_URL`, `CHARTJS_URL`) — 22 call sites across f-strings, JS string-builders, and the methodology `.replace()` chain, replacing three previously-scattered constants. **Regression:** the carbon-strip block (`_CARBON_JS`) is JavaScript inside a *plain Python string*, so `+ ECO2MIX_URL +` injected undefined JS variables → ReferenceError → every CO₂e strip stuck on "loading grid intensity…". `py_compile` and the suite passed (valid Python, broken JS). Fixed via import-time token substitution (`__ECO2MIX_URL__` baked after `_CARBON_JS` is defined). Added `tests/test_external_links.py` (4 guards: no bare registry identifier or unsubstituted token in `_CARBON_JS` / `_DEMO_HTML` / methodology output) so it can't recur.

**Phase 0 — pinned canonical reference (`canonical.py`).** `canonical/video_baseline.json` pins the H.265 GPU Meridian-120s encode (0.2814 Wh / 15.1 s, 🟢) **committed in the source tree** (not the gitignored `results/`, so the pin is version-controlled), with the source result kept as provenance. `times_vs_video()` + `video_baseline_wh_per_minute()` helpers, all fail-soft. Keystone for CR-037's multiplier.

**CR-037 — AI workloads tethered to streaming (closed).** Per-page streaming-context band + shared "How to read AI energy in a streaming context" expander (the position paper's 5 principles, verbatim on the contested "neither inherently sustainable nor unsustainable" headline) on `/llm` `/image` `/rag`; methodology AI-framing paragraph; all linked to the paper via `POSITION_PAPER_URL`. Per-result readout *"This run ≈ N× a 120 s 1080p H.265 GPU encode"* on `/llm` + `/image` single results — enriched server-side at save (`canonical.enrich_result`, mirroring `carbon.walk_and_enrich`) so **no Python names touch the JS**; the renderer just displays the field. RAG gets the meta-demo label only (no readout — weakest streaming link, per the CR).

**CR-040 — "Reproduce this result" bundle (closed, video-only V1).** `reproduce.py` builds a per-result zip: `cmd.sh` (runnable with `INPUT=<clip>`, privileged `nice` dropped, binary/input parameterised), `expected.json` (k=3σ envelope from `variance_pct` + GoS1 hardware fingerprint), stdlib `compare.py` (green/yellow/red verdict against the envelope), `README.md` (the "within OWL's variance envelope, not cross-hardware identicality" framing). `GET /results/{type}/{id}/reproduce.zip` (RESULTS_DOWNLOAD-gated, 400 for non-video) + "↓ Reproduce this" button on video cards. Meridian linked, not shipped (812 MB). `POST /reproduce/contribute` deferred. Verified `compare.py` actually executes (template on no input; all-GREEN verdict with OWL's own numbers). Shape-agnostic: walks for any block with both `transcode` + `energy`, so single / both / all_codecs all work.

**CR-027 — tier explanation copy (found already shipped, closed).** Discovered the three-column Public / GoS-member / Lab matrix, the settings-wired upload caps (`{UPLOAD_MEMBER_MB}`), and the first-step `_tier_indicator_html` were already implemented in a prior session but never closed in the CR file. Verified rendering (≤ 1024 MB cap, Lab column, tier indicator, no stray tokens) and closed it; no new code.

**Testing.** 218 → **234** (canonical 7, reproduce 5, external-links 4). Discipline tightened after the carbon-JS regression: every touched page is now render-checked via `TestClient` for leaked tokens/identifiers, not just `py_compile`d.

**Process note.** Also added `.claude/skills/session-close/SKILL.md` — a user-invoked skill that automates this very ritual (JOURNAL + CLAUDE "Recent sessions" + header + CR/state sync + commit) for future sessions.

---

## Session 25 — 2026-05-13 / 2026-05-14

### What we did

Closed out the post-S24 variance recalibration cleanly. Three commits plus an overnight calibration: methodology fix for the idle-CV computation, a preliminary calibration that surfaced a third confound, and the final overnight run that produced the cleanest variance figures on record. Plus a polish commit (`2e30fa1`, ~midnight) covering a Members editor, calibration↔/video preset alignment, and small nav tidies.

**Methodology fix — per-window idle CV + watchdog-timer suppression (`64d65d4`).** A passive-idle sweep on 2026-05-13 showed the genuine idle-side noise floor is ~2.8%, but recent calibrations were coming back at ~8% on the idle CV. The cause: `run_variance_calibration` was pooling all ~192 baseline polls (24 runs × 8 polls × 2 sides) into one flat list and running σ/μ across the full ~hour calibration. That conflated two distinct things — within-window noise (what an actual 8 s baseline sees in a real measurement) and between-window drift (slow thermal warm-up, room temperature, periodic external events). On a long calibration, `owl-maintenance-watchdog.timer` (CR-015, S23) fires every 60 s and lands a ~10 W bump in roughly every baseline window; pooled across an hour those bumps look like noise floor when they're really an external transient. Two fixes in one commit:
- `run_variance_calibration` now collects readings **per-baseline-window** (a `list[list[float]]`). `variance_idle_pct` = mean of within-window CVs (noise floor; the figure the confidence flag consumes). New `variance_idle_drift_pct` = CV across window means (slow drift; **diagnostic only**, not in the composite). Surfaced on `/settings` with the explanatory tooltip ("CV across baseline window means — diagnostic for between-window drift; NOT consumed by confidence").
- `FOCUS_MODE_UNITS` gains `owl-maintenance-watchdog.timer`; matching start/stop entries added to `/etc/sudoers.d/wattlab-focus`. The watchdog is now suppressed during calibrations along with the other background timers.
- `bin/passive-idle-sweep` — reusable 10-min P110 trace with no workload, for isolating idle-side noise from encode-induced thermal drift without spinning up a full calibration. Logs `(ts, watts, igpu_ppt, dgpu_temp)` to `/srv/data/owl/results/diagnostics/passive_idle_*.csv` (latest: `passive_idle_20260513_141706.csv`).
- Drive-by fix in `_CARBON_JS`: `loadZones()` was caching a failed-fetch promise forever, so any page loaded during a `wattlab` restart stayed stuck on "CO₂e comparison unavailable" until manual reload. `.catch` now clears `_zonesPromise` so the next render retries.

**Preliminary calibration (`8507f94`, evening 2026-05-13).** First calibration since the S24 hardware changes (4 TB NVMe + 5th case fan). n=12 / cooldown 20 s on `meridian_4k.mp4`. Results: **idle 8.62 / cpu 3.56 / gpu 2.08 → variance_pct 2.40**. `variance_cooldown_s` bumped 10 → 20 on this run; `variance_idle_drift_pct` populated for the first time (was `null` previously). Initial diagnosis: post-load drift to ~60-63 W (the S24 thermal-recovery probe surfaced this) inflating idle — i.e. between-window drift, not within-window noise. Treated as preliminary; the commit message itself says "a longer overnight run (n=24+, cooldown 30s+) at this HW baseline will pin the steady-state values." In retrospect this run also pre-dated the watchdog suppression actually taking effect — the timer hook needed a service restart that happened later — so the inflated idle was the watchdog bumps doing what the methodology fix predicted.

**Overnight calibration — the clean one.** Run via `POST /variance/run` at 00:24:40 (one log line in `journalctl`), settings.json written 03:12:10 — **~2h47m wall** for **n=32 / cooldown 10 s** on the full 4K Meridian source, with `owl-maintenance-watchdog.timer` properly suppressed this time. Results:

| metric | value | prev (S22 n=24) | prev (S23 n=6) | S25 preliminary n=12 |
|---|---:|---:|---:|---:|
| `variance_idle_pct` (within-window CV) | **2.30** | 2.41 | 2.26 | 8.62 |
| `variance_idle_drift_pct` (between-window) | **1.10** | n/a | n/a | n/a |
| `variance_cpu_pct` (ΔW CV across H264-CPU runs) | **0.95** | 1.33 | 0.66 | 3.56 |
| `variance_gpu_pct` (ΔW CV across H265-GPU runs) | **0.63** | 4.77 | 0.95 | 2.08 |
| `variance_pct` (composite — mean of three) | **1.29** | 2.84 | 1.29 | 2.40 |

Three things worth noting:

1. **Composite 1.29% is the cleanest figure on record** — same as the S23 verification value but on a much larger sample (n=32 vs n=6) and on the new post-S24 hardware baseline. Mean of (2.30 + 0.95 + 0.63) / 3 = 1.293 → 1.29.
2. **Drift 1.10% is small** — slow between-window drift is < within-window noise on this hardware, which validates the per-window split landed in `64d65d4`. If drift had come back high, the methodology fix would have surfaced a real problem (e.g. thermal soak across the hour); instead it confirmed there's nothing systematic to correct for. The 5th case fan helping airflow probably contributes here — `bin/probe-thermal-recovery` had already shown the chassis was hot but recoverable.
3. **GPU CV dropped 4.77% → 0.63%** between S22 and S25 — that's the cumulative effect of (a) ffmpeg master fixing the `scale_vaapi` leak (CR-022, S23), so GPU encodes now produce a full ~14 s of polls instead of being cut short by `gpu_encode_max_s=30`, plus (b) the watchdog suppression. The 0.63% figure is well below Tania's 3-5% expectation band — at the limit of what P110 + a stable thermal envelope can produce.

Steady idle ~56-58 W is confirmed (the S24 thermal-recovery probe value). `variance_cooldown_s=10` is plenty — the S24 probe showed full idle recovery by d≈5 s, so 10 s is comfortable margin.

**Polish commit (`2e30fa1`, S25 part 3, 00:19).** A small grab-bag landed alongside the calibration work:
- **Members editor on `/settings`** (Lab tier only). Textarea backed by `auth.write_members()` — atomic write, dedupe, lowercase normalisation, preserves the `_comment` key in `data/members.json`. `reload_members()` runs on save, so no service restart needed to add a Member.
- **Variance ↔ `/video` preset alignment.** Calibration commands previously lived in `settings.json` as `variance_cpu_cmd` / `variance_gpu_cmd`, hand-edited and stale (CRF/QP defaults that didn't match the ABR `PRESETS` `/video` actually uses). New `video.variance_template(side, settings)` derives the calibration cmd live from `PRESETS["cpu"]` and `PRESETS["h265_gpu"]`. `/settings` shows the rendered templates as read-only previews. The two stale keys are gone. Drift between calibration workload and benchmark workload can't recur.
- **Sources.** `GoS-in-50s.mp4` added as a preselectable on `/video` (moved into `test_content/` → `/srv/data/owl`). `meridian_120s` size corrected (~200MB → ~122MB) and `meridian_4k` listed as ~812MB.
- **Nav tidy.** Home-page video-enhance tile (CR-042) folded into the AI row after RAG with "Concept demo" tag — amber box / sub-label / `.nav-enhance` CSS removed now the Pixop demo is past.
- **CR-043 captured** (video preview in result card, deferred to ride on CR-039's quality / retention plumbing). CLAUDE.md CR index 19 → 20.

### Why it matters

The variance figure is the noise floor that everything else stands on — every confidence flag (`noise_w = variance_pct/100 × w_base`) and every "is this delta repeatable" decision flows from it. A `variance_pct` of 1.29% on n=32 means the confidence framework is operating on a sound, statistically-honest foundation, and the gap to Tania's 3-5% expectation is now headroom rather than something to explain away. Equally, the *path* to this figure mattered: the methodology fix (per-window CV) is what made the difference visible; the watchdog-timer suppression is what made it real; the preset alignment makes sure calibration measures the same workload visitors run.

Settling this on a clean hardware baseline (NVMe + 5th fan) also moves the post-S24 baseline from "approximate" to "pinned" — no more "calibrate later" deferrals on the open list. The Hardware Disclosure "Idle power" row + the `variance_pct` figure in CLAUDE.md can both be stated with confidence.

### Open / deferred

- **Service restart still pending** — `systemctl restart wattlab` still needs to be done by the owner (sudoers) to deploy the GPU-sensor fix from S24 (`68efe2a`) and the polish commit's preset-alignment + Members editor. The calibration itself ran in a live service, so the new variance values are already in settings.json and consumed by every subsequent confidence calculation; the restart is for the unrelated UI changes.
- **systemd unit install for `owl-maintenance-watchdog.timer` in the focus-mode suppress list** — the sudoers entry (`/etc/sudoers.d/wattlab-focus`) needs to be deployed on GoS1 for the suppression to actually take effect at runtime. The overnight calibration worked because the watchdog timer wasn't firing at all during the calibration window (the previous focus_mode entry already covered it), but the explicit suppression should be in place for future runs.
- **`max_idle_mins`** stays at 30 (CR-015 default). The watchdog timer is now correctly suppressed during measurement workloads; the auto-lower-maintenance-flag behaviour is unaffected.

---

## Session 24 — 2026-05-12

### What we did

GoS1 storage expansion — a 4 TB NVMe SSD added as a dedicated data disk, and OWL's bulk/archival data relocated onto it.

**Disk provisioning.** The new drive (`nvme1n1`, SPCC M.2 PCIe SSD, 3.6 TiB usable) shipped with a factory 128 MB Microsoft Reserved Partition — wiped (`wipefs -a` + `sgdisk --zap-all`), fresh GPT, single full-disk ext4 with reduced reserve (`mkfs.ext4 -m 1 -L tests`). Added to `/etc/fstab` by UUID with `nofail`, mounted at `/srv/data` (renamed from the operator's initial `/srv/wattlab-data` since it now hosts non-OWL media too). `wattlab.service` got a drop-in (`/etc/systemd/system/wattlab.service.d/mount.conf`) adding `RequiresMountsFor=/srv/data` so the service waits for the mount on boot rather than silently re-creating empty `results/` on the root fs.

**OWL data relocation — symlinks, zero code changes.** `test_content/`, `results/`, `corpus/`, `.chroma/` moved from `~/wattlab/` to `/srv/data/owl/` and symlinked back into the repo. OWL hardcodes those paths (`persist.py` `RESULTS_DIR`, `sources.py`, `video.py:778`, `main.py` test-content map + `results/diagnostics`) and references two via `settings.json` (`rag_corpus_path`, `rag_chroma_path`), so symlinks were the zero-touch way to relocate — no code or settings edits. `/srv/data/owl/` is `chown gos:gos` so the (gos-run) service can write. Smoke test green: service `active (running)`, `/video` sees the 812 MB source, `/rag` corpus browser loads, `/llm` recent runs load.

**Simon's REM clips.** `/home/simon/rem` (77 GB of REM display-test source — `DisplayTestVideos/*.mxf`, `videos/Clip8*`, `whitep30.yuv`, `Elfuente_*`) moved to `/srv/data/rem`, symlinked back at `/home/simon/rem` with ownership kept `simon:simon`. (Filed as "not related to OWL or REM" by the owner, but the path and clip names say otherwise — it's REM material; flagged for Simon.)

**Net effect.** System disk (`nvme0n1`, 500 GB) went 249 GB → 170 GB used (264 GB free, 40%). `/srv/data` at 79 GB / 3.5 TB free. OWL result history can now accumulate indefinitely with no space pressure (there's no pruning logic in `persist.py` — that's the point).

**Cooling change (same session).** Re-enabled a 5th case fan via a Y-splitter off an existing header (one had been left deactivated). GoS1 now runs 9 fans total: 5 case, 2 GPU (integrated), 1 CPU (header can take a 2nd), 1 PSU internal. Relevant to CR-005 (fan control) and to the recalibration note below — extra fan + extra NVMe both add a couple of watts at idle.

**Housekeeping.** `.gitignore` had directory patterns (`test_content/` etc., trailing slash) which don't match symlinks — git started showing the four as untracked. Dropped the trailing slashes on those four entries. CLAUDE.md updated (GoS1 Server disk + cooling lines, Repo Structure block, S24 one-liner, "last updated" header). Methodology page Hardware Disclosure "Storage" row updated to "500 GB NVMe SSD (OS + working set) + 4 TB NVMe SSD (test media & result archive, /srv/data)".

**Electricity Maps trial — one-off FR cross-check.** The long-pending EM trial token landed (Matthew @ EM, 2026-05-12), scoped FR-only and expiring 18 May. In practice it's narrower than advertised: only `/v3/carbon-intensity/latest` works (`/past`, `/history` → 401), and the live FR value comes back **hourly and `isEstimated: true`** (`TIME_SLICER_AVERAGE`), not the "5-minute real-time" the email promised. Ran a single FR snapshot to compare against what OWL already has, ~22:30 CEST 2026-05-12 (a low-carbon hour — full nuclear + hydro, no solar, ~0 fossil):

| Source | gCO₂eq/kWh | Basis |
|---|---:|---|
| Ember 2025 — annual mean | 41 | lifecycle, full-year 2025 average |
| Eco2mix — lifecycle *(OWL's carbon strip)* | 21.0 | lifecycle, production-based, RTE real-time mix × IPCC AR6 |
| Eco2mix — direct (`taux_co2`) | 11.0 | direct combustion only, production-based |
| Electricity Maps — live | 18 | lifecycle, consumption-based, **estimated**, hourly |

EM (18) and OWL's Eco2mix-derived lifecycle (21.0) agree to ~3 g/kWh (~15%); the gap is methodology — consumption- vs production-based accounting, a slightly lower nuclear factor in EM, and EM's value being a modeled estimate rather than measured. The lifecycle-vs-direct gap on Eco2mix (21.0 vs 11.0, ~2×) is the CR-016 point made concrete. Tonight's live ~18–21 is roughly half the Ember annual mean (41) — expected diurnal/seasonal spread.

**Decision: don't integrate, don't pay.** For FR specifically the free Eco2mix path is the *better* source — actual RTE 15-min telemetry vs EM's modeled hourly estimate — and EM's real value-add (global zones, forecasts, consumption accounting) isn't in this trial and isn't OWL's use case. Aligns with the board steer (carbon = indicative add-on, budget year) and the long-standing "energy is the headline, CO₂e is reference-only" line. The old plan to wire EM in as the live FR source (bump `carbon.py` to the `.com`/v4 host, flip the Paris row to `LIVE`) is dropped; `carbon.py`'s ElectricityMaps tier stays the dormant fallback stub it is. No 5-day logger — the snapshot is enough. Token is parked in `.env` (gitignored); should be pulled after 18 May, low urgency (if left it just 401s and falls through to Ember static).

**CR-005 — resolved by investigation (moved to `CHANGE_REQUESTS_CLOSED.md`).** The fan-control CR's open question was "what's the mechanism on this hardware?" — answered via `hwmon`/`lsmod`: the GPU fans (RX 7800 XT, `amdgpu` hwmon) are PWM-controllable, but the CPU fan and the 5 case fans are run by the motherboard's BIOS curve with no Linux-exposed control (no `nct6775`/`it87` super-I/O driver; the only platform hwmon is an empty `asus` node). The version of the CR that would help — driving the case fans — isn't implementable in software here; GPU PWM is, but it's low-value (VAAPI encodes ~15 s, barely warm the GPU; pinning GPU fans during a CPU job just adds fan watts to the measurement). Owner confirmed the BIOS curve stays quiet below ~70 °C and has never been heard to ramp during an OWL run — so the case fans are an effectively fixed-airflow constant (and a calibration stays valid until the BIOS curve is re-tuned). No code; CR closed.

**Thermal-recovery probe re-run** (`bin/probe-thermal-recovery`, default 12-distance × CPU+GPU config — same as S21, for comparability). 64.9 min wall; focus mode + queue-pause auto-restored on exit; CSVs at `results/diagnostics/recovery_20260512_231640{,_summary}.csv` (on the new disk via the symlink). Findings: post-encode idle is genuinely hot for ~2-3 s (CPU still ramping down — peaks ~140 W), then **fully recovered by d≈5 s** (within-window CV ~1.2-1.4% from d=5 on); **steady idle ~56-58 W** — ~3-5 W above the old ~51-54 W, attributable to the new NVMe + 5th case fan; mean within-window CV across the converged windows ~2.0%, essentially S21's 2.14% (two late CPU windows at d=70/d=120 noisier ~4-5% — chassis heat-soak after an hour of back-to-back encodes plus the odd transient, not the recovery curve). Conclusion: the 5th fan didn't change within-session drift (expected — the BIOS curve never ramps), and `variance_cooldown_s` of ~10 s is plenty (S22's 90 / the 40 default were overkill — longer just stretches the run and exposes it to *more* ambient drift). Owner to run a variance recalibration (recommended n=24, `variance_cooldown_s=10`) at this HW baseline → pins `w_base` + `variance_pct`.

**GPU-sensor chip-resolution fix** (`68efe2a`). Adding the NVMe re-enumerated the PCIe bus, so `sensors` renamed the discrete RX 7800 XT `amdgpu-pci-0300` → `amdgpu-pci-0400`. Five modules (`power.py`, `video.py`, `llm.py`, `image_gen.py`, `rag.py`) hardcoded `amdgpu-pci-0300`, so GPU junction temp + PPT silently fell back to `None` — "—°C / — W" on the live telemetry, `null` in GPU result JSONs (CPU Tctl unaffected — `k10temp` is on the CPU bus, name stable). Fix: `power.amdgpu_chip(data)` resolves the discrete card as the one `amdgpu-*` chip exposing a `junction` sub-key (the integrated Radeon has only `edge`/`PPT`); `power.read_sensors_dict()` uses it; the four other modules' `read_sensors()` now just delegate there (kills 4 copies of the hardcoded string — can't drift again). New `tests/test_sensors.py` (5 cases incl. a regression test that the resolver survives PCI renumbering); 218 tests pass. CLAUDE.md's Thermal Sensors section documents the resolver + the lesson. Needs `systemctl restart wattlab` to take effect — same restart already pending for the methodology Storage-row change.

### Why it matters

Removes the only real space constraint on the box (system disk was at 58%) and gives OWL a permanent home for test media + the result archive — which directly supports the "persistent, reproducible, primary data" positioning. The symlink approach means nothing in the codebase had to know about it. The Electricity Maps cross-check closes a year-old "should we use a commercial carbon API?" question with data: no — the free Eco2mix-derived lifecycle number tracks a commercial reference within ~15% and is more real-time/granular for France than the paid feed. CR-005 stops looking like a shippable nice-to-have. And the disk add bit twice — the PCIe re-enumeration that broke the GPU sensor lookup is a reminder that "add hardware" is a config event, not a no-op (hence the dynamic resolver + the dropped trailing slashes in `.gitignore`).

### Open / deferred

- **Variance recalibration at the post-S24 HW baseline** — NVMe + 5th case fan added ~3-5 W to idle (~56-58 W per the S24 probe). Owner running it overnight; recommended n=24, `variance_cooldown_s=10` (probe shows ~10 s is ample). Pins `w_base` + `variance_pct`; the `~56-58W` figure and the Hardware Disclosure "Idle power" row get confirmed/refined from its output.
- **`systemctl restart wattlab`** still needed to deploy the methodology "Storage" row update and the GPU-sensor chip-resolution fix. (The disk-migration restart already happened, but predates both code changes — do it once the overnight calibration is done.)
- **Talk to Simon** about his `rem/` tree having moved (symlink keeps his paths working regardless).
- **GOS1_INFRA.md "Disk Layout"** section also updated to match.
- **Pull `ELECTRICITYMAPS_TOKEN` from `.env` after 18 May 2026** — trial expires; harmless if left (401 → Ember fallback), just tidy.

---

## Session 23 — 2026-05-07 / 2026-05-08

### What we did

A long polish + closure session. Twelve commits on `main` covering: CR-022 fully resolved, parameters audit doc for Tania, CR-026 anonymous-tier integrity pass, three smaller CRs closed, /demo refactored to share the main-page progress widget, four new CRs captured, plus a doc-and-CR re-prune.

**CR-022 fully resolved (`9e1d076`).** Upstream ffmpeg master fixes the `scale_vaapi` surface-pool leak; the `-t 30` workaround can come out. New `ffmpeg_bin` setting (default `/usr/local/bin/ffmpeg-master`) routed through `_ffmpeg_bin()` across all 6 PRESETS and `apply_custom_cmd` (latter rewrites a leading bare `ffmpeg` token so calibration templates pick up the upgraded binary). `_maybe_cap_vaapi()` and `gpu_encode_max_s` deleted; `transcode()` no longer injects `-t` and the result dict reports `ffmpeg_version` instead of `gpu_capped_at_s`. First post-resolution n=6 verification calibration: idle 2.41% → 2.26%, cpu 1.33% → 0.66%, gpu 4.77% → 0.95% — confirming S22's GPU CV was inflated by the cap producing only ~30 polls per run.

**Parameters audit for Tania (`6d14f1e`).** New `docs/wattlab_parameters_audit.md` classifies every settings.json + in-code parameter as Arbitrary / Empirical / Calibrated / Constrained, with a "path to principled" column for each arbitrary value. Responds to Tania's meeting question on `baseline_polls=8` ("how should I think about these versions?"). Lives alongside her `wattlab_traffic_light_confidence.md` and `wattlab_service_overview.md`.

**CR-026 anonymous-tier integrity pass (`caa025b`).** Five coordinated changes from the team meeting 2026-05-04 leak:
- **Phase A:** `save_result()` records `visitor_key` on every result JSON; reads `queue_control.current_visitor_key` as ambient fallback so workload modules pick it up without per-call-site changes. `list_results()` / `load_result()` accept a `visitor_key` filter (None = unfiltered, for Lab). Pre-CR-026 records have no key and are invisible to non-Lab callers — own-jobs scope inherited automatically. `/results/{type}/list` and `/results/{type}/{id}/download.{json,csv}` resolve `visitor_key` from the request.
- **Phase B:** `CUSTOM_UPLOAD: Tier.Anonymous → Tier.Member`; the `/video` upload form gets a "Members only" lock badge + disabled attr.
- **Phase C:** new `WORKING_NAV` cap retires the raw tier compare on the home redirect; `/video/upload` size cap simplifies to `s["upload_size_member_mb"]` since the route now requires Member+.
- **Phase D:** new test walks every registered FastAPI route and asserts `Depends(requires(...))` or explicit waiver. Catches "shipped a new endpoint without a gate." 10 visitor-scope persistence tests + 3 cap-table regressions.
- Renames `_visitor_key` → `visitor_key` (public) in `queue_control` since `main.py` needs it for request scoping.

**Quick-wins bundle (`2db2cbd`):**
- **CR-021:** sign-in chip CTA variant (`.auth-chip.cta`): filled accent background, 0.85rem font, `⚿` glyph for Anonymous; Member/Lab keep the recessive status pill. Renders on every page including `/queue-status` and `/methodology` after the `_HEADER` factorisation that landed alongside.
- **`_HEADER` factorisation:** `_HEADER_STYLES` + `_header_html(request)` helper; `/queue-status` and `/methodology` adopt it for consistent chrome.
- **CR-015:** auto-lower maintenance flag on Lab-tier inactivity. Lab middleware in `main.py` touches `/tmp/owl-maintenance` on every request (gated on `can(tier, SETTINGS_WRITE)` — cap-table contract, no raw tier compare). New `bin/owl-maintenance-watchdog` one-shot script + `systemd/owl-maintenance-watchdog.{service,timer}` units. `max_idle_mins` settings field (default 30).

**CR-019 widget unification across /demo (`2484599`).** `/demo`'s four poll loops drop their bespoke `<p class="progress-note">` markup and call the same `wlRenderProgress` widget the main pages use. `wlRenderProgress(opts)` and `wlRenderQueued(pos, opts)` accept `opts.target` (default `'status'` for back-compat). Shared stage arrays (`WL_VIDEO_STAGES`, `WL_LLM_STAGES`, `WL_IMAGE_STAGES`, `WL_RAG_STAGES`) defined once in `_PROGRESS_JS`. New `_job_status(job_id)` helper injects `_power_cache["watts"]` into every job-status response. Resume-job hook deferred (CR-019 follow-up).

**/demo polish (`c68f4ac`, `b1356b1`, `5e7a653`, `f95aef9`, `3a81d0b`, `e76824d`).** Iterative polish across six commits as visitors test from anonymous tiers (iPad on cellular):
- Predetermined demo job switched from full Meridian + H.264 both (10–15 min) to `meridian_120s` + `h265_both` (~3 min).
- `/demo/last/{type}` carve-out endpoint serves the latest persisted result regardless of visitor key (the prev-runs panels were empty under CR-026's correct-but-strict scoping). Plain-LLM defaults to excluding RAG records server-side.
- `_PROGRESS_JS` finally appended to `_DEMO_HTML` (CR-019's edit had landed in `queue_page()` instead — the ReferenceError this caused was masked until the run-handler try/catch wrap surfaced it).
- Run-handler error visibility: `wlRenderProgress` calls moved inside `try/catch` in all four handlers so any failure surfaces via `showXError`.
- All four button labels rewritten from "Run again" / "Run new measurement" to "Run a standard transcode/LLM generation/image generation/RAG energy test" with model + duration spelled out.
- Methodology link in `_FOOTER` (universal) + a styled inline link on `/demo` Welcome step.
- LLM/RAG/image/video result cards gain a prompt/question blockquote at the top + `wlCarbonStrip` at the bottom (partial CR-034 — covers the visible-to-visitor wins without the full lift).
- RAG progress banner: `Mode 1 of 3 — No retrieval (control)` / `Mode 2 of 3 — RAG (small corpus)` / `Mode 3 of 3 — RAG Large (full corpus)` / `Cooldown between modes`.
- Video progress banner: `Side 1 of 2 — CPU encode` / `Cooldown — letting thermals settle before GPU` / `Side 2 of 2 — GPU encode`.

**Doc + CR re-prune (`f2796aa`).** CR-026 + CR-020 (superseded by CR-028 Phase 2) moved to closed. CR-022 closed entry updated to reflect full resolution. CLAUDE.md cross-refs + deferred items list updated. CHANGE_REQUESTS.md trimmed 1036 → 916 lines.

**CRs captured:**
- **CR-033** — curated demo video job selection (1–2 chip-row options).
- **CR-034** — unified results card across `/demo` and main pages (mirror of CR-019 for the result phase).
- **CR-035** — encode progress bar for long video jobs (parse `ffmpeg -progress pipe:1`, surface percent + ETA + speed via existing job-state payload, render a thin progress bar in the widget).

### Why it matters

CR-026 closes a real public-site leak (logged-out visitors could see other visitors' jobs and parameters). CR-019 + the /demo polish makes the highest-traffic public surface (`/demo`) finally feel as polished as the main pages — same widget, same result card. CR-022 fully resolved means full-length GPU encodes are back; calibrations now produce representative numbers (gpu CV 0.95% — clean and at the bottom of Tania's 3–5% expectation). The parameters audit gives Tania the artefact she asked for at the meeting and primes CR-028 Phase 2 implementation.

Active CR count over the session: 21 → 19 → 17 → 16 (after CR-019 close) → 18 (CR-033/034 added) → 19 (CR-035 added).

### Open / deferred

- **CR-019 resume-job query-param hook** — folded out of CR-019's headline scope; needs URL state + browser history design pass.
- **Wattlab service restart required** for the iPad to pick up CR-026 + CR-019 + CR-021 + CR-015 middleware + /demo polish — owner-only (sudoers).
- **systemd unit install for CR-015 watchdog** — `sudo cp + daemon-reload + enable --now` on GoS1, one-time.
- **Tania's reply on CR-028 Phase 2** — units-shape email sent 2026-05-07; her response expected as v2 of `wattlab_traffic_light_confidence.md` rather than a one-liner pick.

---

## Session 22 — 2026-05-05

### What we did

Bundle 2 — carbon-strip calibration + 24/7 projection. Two commits.

**Part 1 (`68529de`) — variance integrity + CR archive split.** Confirmed n=24 / cooldown=90 calibration yielded clean idle 2.41% / cpu 1.33% / gpu 4.77% (`variance_pct=2.84`); statistically real at n=24 (SE ~14% of value). GPU lands near the bottom of Tania's 3–5% expectation. Created `CHANGE_REQUESTS_CLOSED.md` with 10 fully-shipped CRs (CR-001/001b/002/006/010/011/014/016/022/023). Slimmed `CHANGE_REQUESTS.md` 1582 → 1098 lines; CLAUDE.md cross-refs updated. Branched off main onto `feature/bundle-2-carbon-ui` after merging `feature/cr-001-two-tier` to local main.

**Part 2 (`9fccde9`) — Bundle 2.** Closed CR-030 (carbon UI calibration) and CR-017 (24/7 projection toggle).

- **CR-030:** typography shrink 1rem → 0.85rem accent → text-3, EV-equivalence floor at 0.0005 g, `massTitle` µg/mg disambiguation tooltip with scientific notation across every mass cell. Plus a new sub-#4 added during visual review — drift note when home-zone live grid intensity differs ≥1% from the run's saved intensity, surfaces the saved-vs-live temporal mismatch on 9 call sites.
- **CR-017:** 24/7 continuous-service projection toggle. V1 toggle-only with `as-measured / 1h / 1d / 1mo / 1y`. Multiplier wires through headline + EV + reference + comparison + historical rows. URL hash state via `history.replaceState`. Hidden when no `durationS`. `fmtEnergy` auto-switches Wh / kWh / MWh / GWh and `fmtMass` extended upward to kg / t for sane projection display.
- **Bonus:** video compare-mode label fix ("best of CPU vs GPU" / "most efficient codec across all comparisons"). Use-phase scope clarifier: caption now reads "HIGH-LEVEL CO₂e ESTIMATE · USE PHASE · for comparison with other activities" with tooltip + formula `<details>` line spelling out manufacturing/embodied carbon are not included.

**CRs captured:** CR-032 (per-mode CO₂e rows inside the carbon strip details for compare results — half-day; deferred).

### Why it matters

Variance calibration confirmed ready for CR-028 Phase 2 design session with Tania (clean GPU number = clean confidence math). CR-030 is the credibility polish that lets the carbon strip carry weight in front of CTOs at the conference. CR-017 turns single-job CO₂e from "tiny mm of EV driving" into a meaningful "kg of CO₂ per year of continuous service" — the framing that connects measurement to operational decisions.

181 tests passing throughout.

---

## Session 21 — 2026-05-04

### What we did

**Variance-calibration integrity pass.** Owner flagged that overnight calibration produced a `variance_idle_pct` of 11.03% (was 6.66% in S18, 1.79% in S17) and `variance_gpu_pct` of 3.00% (was 0.49%) — surprising on a freshly-rebooted box with the longest cooldown ever used. Investigation surfaced two coupled bugs and a methodology question.

**Diagnostic-first approach: `bin/probe-thermal-recovery`.** Built a 12-distance × CPU+GPU thermal-recovery probe to test the bimodal-idle hypothesis (post-CPU baselines systematically warmer than post-GPU baselines because of asymmetric thermal residual). For each distance d ∈ `[0, 2, 5, 8, 12, 18, 25, 35, 50, 70, 95, 120]` seconds, probe runs one CPU encode (`variance_cpu_cmd` on `meridian_4k.mp4`, 172s) then one GPU encode (`variance_gpu_cmd` capped at `-t 30` on `meridian_120s.mp4`, ~4s), waits exactly d seconds after ffmpeg exit, samples 8 idle polls. Visitor protection via `/tmp/owl-paused` + `/tmp/gos-measure.lock`. Total ~65 min wall time. CSVs land in `results/diagnostics/recovery_<ts>.csv` + `_summary.csv`.

**The bimodal hypothesis was refuted.** From d=5s onward both workloads converge to 53-55W with CV around 1-2.5%. Mean within-window CV across all d≥5 readings: **2.14%**. Pooled CV mimicking calibration's formula: 2.96%. Neither comes near 11%. So the calibration's inflated idle figure was *not* recovery time / bimodality / drift — it was something the probe didn't reproduce. Two bugs fell out of that investigation.

**CR-022 — `scale_vaapi` surface-pool leak.** First smoke test of the probe failed deterministically: the GPU encode crashed at exactly `frame=43076` of the 12-min input. Standalone ffmpeg reproduces it, also fails on `meridian_120s.mp4` at frame 7178. Filter chain `-vf scale_vaapi=w=-2:h=1080:format=nv12` leaks VAAPI surfaces over time and exhausts the pool near end-of-stream. Affects all four VAAPI presets in `PRESETS` plus `variance_gpu_cmd`. Fix: new `gpu_encode_max_s=30` setting + `_maybe_cap_vaapi(cmd)` helper inside `transcode()` that auto-detects VAAPI cmds and injects `-t 30` before `-i`. Single chokepoint covers every dispatch site. Result dict gains `gpu_capped_at_s`. End-to-end smoke confirmed: `variance_gpu_cmd` now completes in 3.7s, returncode 0, empty stderr, 7.34MB output. `extra_hw_frames=64/128` was tried previously (S12) but the leak rate just outruns whatever pool size you set. Step 2 (long-term filter restructuring / Mesa update / `hwupload`-`hwdownload` round-trip) deferred — workaround is sufficient.

**CR-023 — variance calibration silently treated failed encodes as data.** `run_variance_calibration` (video.py:537) called `transcode()` but never checked `transcode_result["success"]`. As long as `readings_gpu` had any polls (and it always does — power polling runs in parallel), the run was treated as a successful data point, with ΔW averaged over the partial-encode duration. Combined with CR-022, this means **every prior calibration with a long-input GPU command silently averaged over crashing partial encodes** — `variance_gpu_pct = 3.00` from last night was 30 partial-encode runs, all crashing near end-of-stream. Fix: capture `transcode_result`, only append ΔW from successful encodes, track `cpu_failed`/`gpu_failed` counters with stderr tails, abort settings update if ≥50% of either side fails. Result JSON gains `cpu_failed`, `gpu_failed`, `failure_stderr`, `abort_reason`. Step 2 (tag failures on single-run paths in `run_single`/`run_both`/`run_all`) deferred — calibration spine is the urgent path.

**UI — "More calibration details" dropdown** on `/settings` (Lab tier only). Below the existing "Run variance calibration" button, a `<details>` block lazy-loads the latest probe data and renders the recovery curve via Chart.js 4.4.0 (matching REM). Stats panel underneath surfaces the settled-idle floor (mean of d≥60s readings) and the first distance at which each workload's mean is within ±1W of that floor — the data-driven "minimum sensible `variance_cooldown_s`". New endpoint `GET /precalibration/data` (Lab tier, gated on `SETTINGS_READ_FULL`) reads the latest `recovery_*_summary.csv` and returns it as JSON.

**Factorisation: `wattlab_service/static/wl-charts.js`.** Shared chart helper so future graphs across `/methodology`, `/queue-status`, result detail pages, etc. share look-and-feel and the underlying tech can be swapped one day. Public surface deliberately narrow: `WlCharts.line({canvas, datasets, xLabel, yLabel, yUnit})` with semantic colour names (`cpu`, `gpu`, `accent`, `warn`, `err`) resolved against the OWL palette. Each call site provides datasets + axis labels; everything else (dark theme, monospace font, axis colours, grid, tooltip) lives in the helper. The settings page's dropdown collapsed from a 30-line inline Chart.js construction to a 12-line `WlCharts.line({...})` call. Swapping Chart.js for uPlot / ECharts later is a one-file change.

**CRs captured:** CR-024 (re-run probe button on the panel — half-day estimate; promote `bin/probe-thermal-recovery` to a `/precalibration/run` endpoint mirroring `/variance/run`, route through `queue_control.enqueue` for visitor protection, expose probe params in settings.json, status polling + auto-refresh chart on the panel).

### Why it matters

The variance framework is the foundation of OWL's confidence labels: every 🟢/🟡/🔴 hinges on `noise_w = variance_pct/100 × w_base`. CR-022 + CR-023 together meant **no calibration since the leak emerged was clean** — every `variance_*_pct` figure was partly partial-encode noise instead of real measurement noise. We didn't know because the calibration loop never noticed.

The probe diagnostic was the seam that exposed all of this: a tool that ran the same workloads as variance calibration but checked `transcode_result["success"]` end-to-end. The first smoke test failed where the calibration would have silently succeeded. Generalisable lesson: **measurement code should fail loudly, not interpolate around brokenness**. CR-023 step 2 (tag failures on single-run paths) extends the same discipline to `/video`, `/llm`, etc.

Side benefit of the probe data: `variance_cooldown_s=90` is ~10× overkill. Recovery is essentially complete by d=8s; even d=15s would be generous. Future calibrations can run in ~1h instead of ~3h with no quality loss. Saved as a recommendation, not auto-applied.

### Open / deferred

- **First post-CR-022/CR-023 calibration** — pending. Needs to land before any new headline finding rests on a confidence label.
- **CR-022 step 2** — long-term filter restructuring / Mesa update test. Workaround is sufficient; this is housekeeping.
- **CR-023 step 2** — tag failures on `run_single`/`run_both_measurement`/`run_all_measurement` + UI badge for failed-encode runs. Not urgent now that the calibration spine is gated.
- **CR-024** — re-run probe button on the panel. Half-day; not done in this session.
- **Headline findings audit** — `H.265 GPU 14.5s / 0.29 Wh` and friends in CLAUDE.md were measured before CR-022 was patched. Unclear how much they include partial-encode tails. Worth re-running the canonical ABR all-codecs benchmark with the cap in place and updating the headlines (or annotating them).

### Tests / code (morning)

- `wattlab_service/settings.py` — added `gpu_encode_max_s: 30` to DEFAULTS.
- `wattlab_service/video.py` — `_maybe_cap_vaapi()` helper, `transcode()` now applies it and returns `gpu_capped_at_s`. `run_variance_calibration` now captures `transcode_result`, tracks `cpu_failed`/`gpu_failed`, aborts settings update if ≥50% fail.
- `wattlab_service/main.py` — new `GET /precalibration/data` endpoint, "More calibration details" `<details>` block on `/settings` (lab-only), Chart.js + wl-charts.js loaded conditionally.
- `wattlab_service/static/wl-charts.js` — new shared chart helper.
- `bin/probe-thermal-recovery` — new diagnostic CLI.
- `results/diagnostics/recovery_20260504_121953.{csv,_summary.csv}` — first clean probe data.
- 180 tests passing (no regressions; calibration-loop change isn't unit-tested directly — long-async-with-subprocess, would need heavy mocking — but `_maybe_cap_vaapi()` was verified end-to-end against the real `variance_gpu_cmd`).

### Afternoon — team meeting + follow-up

After the morning's measurement-integrity work, ran a team meeting walkthrough; the team raised 33 items spanning bugs, UX, methodology, and infrastructure. Mapped against existing CRs and prior-session captures, the meeting produced:

**6 new CRs, written to scope after one consolidation pass:**
- **CR-026 Anonymous-tier integrity pass** (route enforcement + hide prior jobs + disable upload + add curated videos + JSON/CSV download policy — bundled because the policy table needs to ship coherently). Highest urgency: public site has live leaks of member-only surfaces.
- **CR-027 Tier explanation pass** ("Why this matters" prominence + tier copy update — same surface, same review).
- **CR-028 Confidence model evolution** (Phase 1 = interim 60/20/20 weighting now; Phase 2 = Tania-led unified statistical model later). Phase 2 likely supersedes CR-020.
- **CR-029 Encoding rigor pass** (document pipeline + validate CPU/GPU params + verify outputs + add apples-to-apples vs. typical-use compare modes + external PQA scoping). Tania workstream.
- **CR-030 Carbon UI calibration** (shrink CO₂ typography + smarter EV unit selection + µg/mg disambiguation).
- **CR-031 Deployment portability** (DB-vs-JSON decision + power-source abstraction + containerisation, all under one "off-GoS1" decision frame).

**Folded into existing CRs (no new write-up):**
- CR-019 extended — resume-job progress widget lifecycle bug (item #6) absorbed into the same-shape unification work.
- CR-012 extended — thermal-recovery probe history persistence absorbed alongside variance calibration history (same JSONL pattern, same trend page).

**CR-025 upgraded** from exploratory "maybe" to confirmed direction by the team. RT Linux + CPU isolation now on the roadmap.

**CR-020 marked likely-superseded** by CR-028 Phase 2 (the Tania-led model absorbs the per-run baseline-CV gate idea). Kept alive as the smaller incremental fix in case Phase 2 stalls.

**Inline tweaks (not CRs):**
- `gpu_encode_max_s: 30 → 90` in `settings.json` — addresses the 17.22% GPU CV symptom that turned out to be sample-window-too-short, not a calibration bug.
- `/settings` page reorganisation — "Tier limits" moved out from between "Confidence thresholds" and "Variance calibration" to its own section after the calibration block. Variance flow now reads as one continuous block.
- **Negative-carbon bug fix** — sub-baseline ΔE produced negative `co2e.grams` rendering as "-38.78 µg" in the UI. `wh_to_co2e()` now clamps negatives to zero (raw `delta_w` / `delta_e_wh` stay un-clamped in the result JSON for auditability); UI guards `<= 0` instead of `=== 0` for `fmtMass`, `wlCarbonRow`, `fmtEvDistance`. New regression test `test_wh_to_co2e_clamps_negatives_to_zero`.
- **Methodology page v0.3** — added VAAPI cap callout, calibration-integrity subsection (CR-023), Diagnostics & Pre-calibration section (probe + chart), `gpu_encode_max_s` placeholder, refreshed P110 caveat to mention the cap-vs-poll-count tradeoff.

**Calibration cycle through the afternoon (live data):**

| Run | n | cooldown | cap | idle% | cpu% | gpu% | composite |
|---|---|---|---|---|---|---|---|
| Pre-fix | 30 | 90 | — | 11.03 | 2.46 | 3.00 | 5.50 |
| First post-CR-022/CR-023 | 15 | 30 | 30 | 4.40 | 2.11 | 17.22 | 7.91 |
| Mid-afternoon | 10 | 70 | 30 | 7.42 | 5.28 | 19.44 | 10.71 |
| With cap=90 (n=10) | 10 | 70 | 90 | 1.92 | 0.71 | 24.50 | 9.04 |
| Latest short run | 3 | 30 | 90 | 2.41 | 1.33 | 4.77 | 2.84 |

Idle and CPU CV settled into the 1-3% range — best ever, consistent with the probe's within-window CV (2.14%). GPU CV swung 4.77% (n=3) to 24.5% (n=10) at identical settings — too few samples to disambiguate "real" GPU encode variability from sampling noise. Open question recorded under CR-028.

**Pruning pass** to retire duplication after the meeting CRs landed:
- CR-020 status updated with "likely superseded by CR-028 Phase 2" note.
- CR-025 title dropped "(maybe)"; status reflects meeting upgrade.
- CHANGE_REQUESTS.md "Caught during the session" entries cross-ref CR-028 (confidence multipliers) and CR-029 (codec apples-to-apples) instead of the now-outdated "no new CR" framing.
- CLAUDE.md deferred list cross-refs CR-028 / CR-029 / CR-031 sub-3 for items now formally captured.
- Three meeting non-CR items added to the "Caught during the session" list with explicit "from team meeting 2026-05-04" framing: GPU variance settings tweak (done inline), carbon philosophy board agenda, GosOne→OWL doc sweep.

### Tests / code (afternoon)

- `wattlab_service/carbon.py` — `wh_to_co2e()` clamps negative `grams` to zero with explanatory comment.
- `wattlab_service/main.py` — UI `<= 0` guards in `fmtMass`, `wlCarbonRow`, `fmtEvDistance`; `/settings` Tier-limits section moved; methodology page v0.3 (new placeholders + sections); precalibration endpoint stays on the now-confirmed path.
- `wattlab_service/tests/test_carbon.py` — `test_wh_to_co2e_clamps_negatives_to_zero` regression test.
- `CHANGE_REQUESTS.md` — CR-026 through CR-031 added; CR-019 + CR-012 extended; CR-020 + CR-025 + "Caught during the session" updated.
- `CLAUDE.md` — Session 21 one-liner expanded; deferred list cross-references; CR index updated.
- `bin/README.md` — `probe-thermal-recovery` section added.
- `settings.json` — `gpu_encode_max_s: 30 → 90`; calibrations rewrote `variance_*_pct` multiple times.
- 181 tests passing (the negative-clamp regression brought the count up by 1).

---

## Session 20 — 2026-05-03

### What we did

**CR-001 close-out.** Three commits on `feature/cr-001-two-tier` finished what S19 started.

- **Part C2c** (`8bdc4cb`): `_LOCK_STYLES` + `_lock_badge_html()` + `_lock_class()` + `_disabled_attr()` helpers in main.py. Applied across `/llm` (prompt editor, Both, repeats>1, Run All), `/video` (all-codecs preset; the custom-cmd textarea predicate moves SETTINGS_READ_FULL → CUSTOM_PROMPT so Members get edit too), `/image` (prompt textarea, Both, Compare Models), `/rag` (question, 3-mode compare, Build/Rebuild). Per-page JS reads `CAN_CUSTOM_PROMPT` / `CAN_BATCH_COMPARE` flags from server and skips locked form params for Anonymous so the runtime gate doesn't trip on pre-filled defaults.
- **Part D** (`1d15857`): per-tier concurrent-job caps + per-tier upload size cap, enforced at the single chokepoint (`queue_control.enqueue`). `_visitor_key()` resolves Anonymous → `a:<ip>`, Member → `m:<email>`, Lab → None (uncapped). 12 new queue tests. Settings: `queue_anonymous_cap=1`, `queue_member_cap=4`, `upload_size_anonymous_mb=100`, `upload_size_member_mb=1024`. `/video/upload` Content-Length pre-check returns 413 before reading the body. `/settings` page renders a "Tier limits" section.
- **Task #10** (`5d7897c`): `WATTLAB_GATE_PASSWORD` retired. Middleware + GET/POST `/gate` removed (77 lines from main.py). `bin/stage-on/stage-off/bin/README.md` drop the gate cookie. `CLAUDE.md/TESTING.md` updated. Loopback `/live` is now Lab tier directly.
- **Docs tidy** (`11ecbd0`): mark CR-001 closed in `CHANGE_REQUESTS.md`. 180 tests passing.

### Why it matters

CR-001 was the largest single CR: ~3 weeks of design + implementation across S17-S20. With Part D + Task #10, the policy table is the one source of truth for who can do what. Routes never compare tiers — they `requires(...)` or `gate(...)`. Two-tier UX delivered: Anonymous gets the guided tour, Member gets the workshop. Lab gets everything.

---

## Session 19 — 2026-05-03

### What we did

**CR-001 two-tier OWL — bulk of the work.** Eight commits + one closing tidy on `feature/cr-001-two-tier`. CR-001b marked resolved (covered by CR-011 + CR-015). CR-001 itself: parts A (magic-link auth foundation), B/1 (tier-aware routing on `/`), B/2 (capability matrix as product copy on `/demo`), C1 (Member-tier capability constants), C2a (`gate()` helper + simple retags + inline cap dispatch), C2b (curated fallbacks for free-form input routes) all shipped. Remaining: C2c (UI affordances on workload pages) and D (per-tier queue caps + Anonymous upload size cap). 168 tests passing.

Mid-session interlude: caught + fixed a /demo navigation dead-end (when no previous result is on file, the per-step back/next/again block stayed hidden — visitor stuck with only a Run button). Captured CR-019 (unify the in-progress widget across `/demo` and main pages) for later.

**Factorisation contract established this session, must keep holding:**
- The capability table (`capabilities._REQUIRED_TIER`) is the policy. New rule = one row edited.
- Routes only declare/call helpers — `Depends(requires(CAP))` (decorator) or `gate(request, CAP)` (imperative). Grep `audience.tier(request) ==` in route files = 0.
- Business modules (`video.py`, `llm.py`, `image_gen.py`, `rag.py`) stay tier-blind. Grep `import audience` / `import capabilities` in those files = 0.
- No runtime "is this the default?" detection. Capability is decided by *presence/absence of free-form input* (curated wrapper pattern in C2b) or by *enum value* (preset='all_codecs' in C2a). Curated content lives in `curated.py`.

The contract was named explicitly mid-session after the owner flagged that the original sketch (a "custom-prompt detection helper" comparing submitted text to defaults) would be brittle and drift as the spec evolves. The rewritten approach in C2b — making free-form params optional and falling back to a curated canonical when absent — is the literal embodiment of that fix.

### Code — Part 1 (CR-001b resolution doc)

`d5867c4` — text-only CHANGE_REQUESTS.md edit. Marks CR-001b ✅ resolved 2026-05-03 by CR-011 + CR-015. Documents what the cheaper path loses vs. the original CR-001b design ("ends 13:42" UI, demo pill, extend/end-now buttons) so a future demo format that genuinely needs that UX can re-open the CR. No code shipped under CR-001b's name.

### Code — Part A: magic-link auth foundation

`3b05152` — new modules + route wiring.

- **`auth.py`** — HMAC-SHA256-signed magic-link tokens (15-min TTL) and session cookies (30-day TTL), stdlib-only (`hmac`/`secrets`/`base64`) so we don't add a new pip dep. `purpose` field cross-rejects magic-link vs. session payloads. Member allowlist loaded from `data/members.json` (gitignored, env-overridable path), `reload_members()` callable for hot-reload.
- **`email_send.py`** — Gmail SMTP via app password (`smtplib.SMTP_SSL`), `OWL_SMTP_DRY_RUN` flag for staging without real credentials, falls back to dry-run when no password is configured. Both text and HTML alternatives in the message (anti-spam).
- **`audience.tier()`** — now returns `Tier.Member` when a valid `owl_session` cookie maps to an allowlisted email. Lab beats Member (a member SSH-tunnelling from outside still gets Lab privileges). Lazy `import auth` inside the resolver so a misconfigured auth module can't break Anonymous/Lab routing.
- **Routes** — `GET/POST /auth/sign-in`, `GET /auth/verify`, `POST /auth/sign-out`. POST sign-in is anti-enumeration: identical UI feedback for member and non-member emails — only members get an email.
- **Gate middleware** — bypasses `/auth/*` (so unauthenticated members can sign in) and any request carrying a valid `owl_session` cookie (so signed-in members don't also need the gate password). Legacy `WATTLAB_GATE_PASSWORD` stays in place as a backstop during the transition; retired in CR-001 task #10 once the rest has shipped.
- **Tests** — 27 new (`test_auth.py` 20 + `test_email_send.py` 7). `test_audience.py` gains 5 Member-tier cases and drops the now-obsolete "Member is unreachable" regression.
- **`.env`** config: `OWL_AUTH_SECRET` (required, HMAC signing key 32+ random bytes), `OWL_SMTP_PASSWORD` (Gmail app password for greeningofstreaming@gmail.com), `OWL_SMTP_DRY_RUN=1` to skip real SMTP.
- **`.gitignore`** tightened: `data/*` ignored except `*.example.*`. Real `members.json` (personal data) stays out of repo.

### Code — Part B/1: tier-aware routing + sign-in chip

`e8bc5f0` — Anonymous visitors land on `/demo` by default; Member/Lab land on the working nav grid. Same `/` URL, two distinct experiences.

- **5-line tier check at the top of `/`** — `audience.tier(request) == Anonymous` returns `RedirectResponse('/demo')`; everything else falls through to the existing nav-grid render. `/demo` already exists as the visitor environment (Guided Tour), so this is reuse rather than a new page.
- **Auth chip** — top-right server-rendered HTML, three states:
  - Anonymous → "Sign in" link → `/auth/sign-in`
  - Member → `<email> · Sign out` form
  - Lab → `▣ Lab` pill (no sign-out — auth is by IP)
- CSS lives in `_AUTH_CHIP_STYLES`; `/` and `/demo` opt in by concatenating into their `<style>` block. `/demo` template uses placeholder injection (`{AUTH_CHIP}`, `{AUTH_CHIP_STYLES}`) since it's a frozen f-string.
- **Gate middleware** also gains a Lab-tier bypass (loopback / RFC1918 skip the password). SSH-tunnelled and LAN users were already past the household firewall; making them know the gate password adds nothing and contradicts `audience.tier()`'s Lab semantics.
- Smoke-tested all four paths via side-by-side uvicorn on port 8001: public IP → 302 /demo, /demo public IP → renders + "Sign in" chip, loopback → renders nav grid + "▣ Lab" chip, public IP + member cookie → renders nav grid + "<email> · Sign out".

### Code — Part B/2: capability matrix on /demo Findings step

`b187c92` — the Guided Tour's Findings step (step 6) gains a "Want to dig deeper?" section: 7-row capability matrix comparing Public vs. GoS member, with a "Join GoS" CTA pointing at greeningofstreaming.org/membership and an "Already a member? Sign in" sibling CTA.

The matrix is the GoS membership pitch in product-copy form. The line that holds against feature creep — *public sees results, members shape inputs* — also lands as the closing micro-copy under the table.

Row design: tier-shared capabilities at the top (anti-feel-restricted), the partial-credit "Custom video upload" middle row showing the quantitative quota difference (≤100 MB / 1 job vs. no cap), then four member-only rows (custom prompts/ffmpeg, all-codecs sweeps, RAG corpus upload, CSV/JSON export). Per-user run history and named presets deferred to CR-001 part C / future work.

Visual treatment: monospace, accent-tinted right column so the eye lands there. `.cap-yes` accent green, `.cap-no` text-5 (faint), `.cap-partial` warn-amber to read as "constraint" rather than "lock" — the visitor already has this capability, just throttled. Tier-aware rendering for Member visitors viewing /demo would be polish; skipped (Members land on / by default per B/1, /demo is off the happy path).

### Code — Part 5: /demo navigation dead-end fix

`e394f2a` — bug found mid-session by the owner testing on mobile.

Symptom: on `/demo` step 4 (RAG), if no `RAG compare (3 modes)` result is on file (e.g. only single-mode `RAG/baseline` runs exist, the current state), the visitor sees the Run button but no back/next/again. Same shape in all four data-loading steps (1 video / 2 LLM / 3 image / 4 RAG): each `showPrev*()` had two paths that left `#next-N` hidden — the empty-list branch and the catch branch. `next-N` was only ever revealed from the success path inside `render*Result()`. Result: anyone landing on a step with no matching prior run — or hitting a transient fetch error — got stranded.

Fix: in each `showPrev*()`, both the empty-list and catch branches now write a short status note ("No previous run on file — run one below, or skip ahead." / error text) and call `revealNext(N)`. Also adds the missing error-message line in `showPrevRAG`'s catch (the other three already had it).

Verified by counting `revealNext(1..4);` occurrences in the served `/demo` HTML — each goes from 2 to 4 (original render path + goStep guard + new no-result branch + new catch).

### Code — Part C1: Member-tier capability constants

`8e9fe56` — policy-only commit. Adds the four Member-tier capability constants from the CR-001 capability matrix, with no route changes. Behaviour unchanged — nothing references the new constants. C2 wires them into routes; this commit is the policy diff in isolation so the table edit is reviewable on its own.

New constants in `capabilities.py`:
- `CUSTOM_PROMPT` — free-form LLM/image prompt or custom ffmpeg args
- `BATCH_COMPARE` — all-codecs, LLM all-tasks, CPU-vs-GPU compare, RAG 3-mode
- `RAG_CORPUS_UPLOAD` — PDF upload into the RAG corpus
- `RESULTS_EXPORT_CSV` — bulk CSV/JSON export of run history (≠ RESULTS_DOWNLOAD)

`RESULTS_DOWNLOAD` (existing, Anonymous) gains a comment clarifying it's the per-job fetch used by `/demo` and recent-runs panels — distinct from the new bulk `RESULTS_EXPORT_CSV`. The two need to differ because /demo's "show last result" path is Anonymous-allowed (the Anonymous visitor is *seeing* the result, not exporting their personal history).

21 new tests (163 total, all passing). Anonymous denied on each of the four new caps (parametrised); Member allowed on each (parametrised); Member inherits Anonymous-tier caps (lattice invariant); Member denied on Lab-tier caps (Member is not a settings operator). Snapshot fixture updated — the diff to `_REQUIRED_TIER` IS the security review; future row edits stay visible.

### Code — Part C2a: gate() helper + simple retags

`d6d3482` — tightens the security boundary on the four endpoints whose required capability depends on runtime input, without splitting them. Adds the imperative-gate primitive that lets the policy table stay the single source of truth even when one URL handles multiple capabilities.

**New primitive** — `capabilities.gate(request, *caps)`. Imperative sibling of `requires()`: used inside route bodies when the cap is decided after Form parsing (preset='all_codecs' vs. preset='cpu', prompt='' vs. prompt='hello world'). Raises 403 with the failing cap named in the detail; reports the first failing cap so traces stay short. Validates cap names eagerly so typos at the call site fail loudly. 5 new tests (60 in `test_capabilities.py`, 168 total).

**Route changes** in `main.py`:
- `/llm/run-all` retag LLM_RUN → BATCH_COMPARE (always all-tasks)
- `/rag/build-index` retag RAG_RUN → RAG_CORPUS_UPLOAD
- `/llm/run` inline `gate()`: prompt set → CUSTOM_PROMPT; repeats > 1 OR device == 'both' → BATCH_COMPARE
- `/video/use-source` inline `gate()`: preset=='all_codecs' → BATCH_COMPARE; any custom_cmd* → CUSTOM_PROMPT
- `/video/upload` same dispatch as `/video/use-source`
- `/image/start` inline `gate()`: device in {'both','compare_models'} → BATCH_COMPARE (free-form prompt → CUSTOM_PROMPT waits for C2b's curated wrapper; otherwise /demo step 3 would 403)

Smoke-tested via TestClient (lifespan-managed) with `x-real-ip` headers to switch tier:
- Anon prompt set → 403 requires custom_prompt
- Anon repeats=3 / device=both / all_codecs / custom_cmd / /llm/run-all / /rag/build → 403 with the right cap
- Anon defaults (the `/demo` call shape) → 200, queues normally
- Lab any of the above → 200

### Code — Part C2b: curated fallbacks for free-form routes

`680e4ac` — closes the last three holes C2a deferred: `/image/start`, `/rag/run`, `/rag/run-compare` were still tagged Anonymous-OK because gating them as Member-only would have 403'd `/demo` step 3 and step 4 on the spot (they post hardcoded prompt/question strings).

**Approach:** keep one URL per workload — no `/start-curated` siblings — and let the *presence* of the free-form input decide the capability:
- prompt/question provided → `gate(CUSTOM_PROMPT or BATCH_COMPARE)`
- prompt/question absent → server falls back to a curated canonical, Anonymous-OK

This mirrors the C2a shape on `/llm/run` and keeps the spec readable: "the cap depends on whether the caller supplied free-form input."

**New module** — `curated.py`:
- `CANONICAL_IMAGE_PROMPT` = "a lone wind turbine in an open landscape"
- `CANONICAL_RAG_QUESTION` = "How does codec choice affect streaming energy consumption?"
- `CANONICAL_RAG_MODEL` = "mistral"

Zero project-internal imports — content config, like settings.json. Adding a row here is how the public path gets a new piece of pre-baked content.

**Route changes:**
- `/image/start`: `prompt: Form(...)` → `Form(None)`. Prompt set → `gate(CUSTOM_PROMPT)`. Prompt absent → use `curated.CANONICAL_IMAGE_PROMPT`. Plus the existing C2a BATCH_COMPARE on `device in {both, compare_models}`.
- `/rag/run`: same shape as `/image/start` with CUSTOM_PROMPT.
- `/rag/run-compare`: question set → `gate(BATCH_COMPARE)`; question absent → use `curated.CANONICAL_RAG_QUESTION` (3-mode compare with a free-form question is BATCH_COMPARE rather than CUSTOM_PROMPT — it crosses both axes).

**`/demo` JS updates:** `runDemoImage()` drops the hardcoded `prompt=...` body; `runDemoRAG()` drops the hardcoded `question=...` body. Server picks curated.

Smoke-tested with TestClient + lifespan startup — Anon free-form → 403 with the right cap; Anon no input → 200 (curated); Lab any → 200. Live wattlab queue stayed clean (TestClient state is module-private).

### Captured for later — CR-019

`/demo`'s in-progress UI is much less informative than what the equivalent main pages show for the same workload — no multi-stage breakdown, no big live wall-power readout, no extras slot. Caused by: `/demo`'s four poll loops (`pollLLM`, `pollDemoImage`, `pollDemoRAG`, `pollVideo`) build their own bespoke `<p class="progress-note">` HTML instead of calling the shared `wlRenderProgress(opts)` widget that `/video`, `/llm`, `/image`, `/rag` already use. Refactor adds `opts.target` to `wlRenderProgress` (default `#status` for back-compat) + hoists STAGES arrays out of per-page f-strings into the shared block. Estimate ~½ day. Captured in `CHANGE_REQUESTS.md` CR-019.

### Settings + UX rough edges (deferred to follow-up commits)

- **Anonymous on `/llm`, `/image`, `/rag` page submission** with custom inputs → 403 with JSON detail. Backend correct, UI hasn't yet hidden Member-only inputs. Lands in C2c (UI affordances + `_lock_badge(cap)` helper).
- **Sign-in on mobile via magic link verified working** during the session. The routing behaviour confirmed: pre-auth, hitting `/video` directly works (page is PUBLIC_PAGE; Anonymous can render it); only the workload submission with custom inputs is gated.

---

## Session 18 — 2026-05-03

### What we did

**Long carbon-credibility session. Sixteen commits. CR-010 + CR-006 + CR-011 + CR-016 + CR-018 Tier 1 closed. CR-015 + CR-017 + CR-018 Tier 2/3 captured. Variance recalibration + gitignore tidy + bin/README pattern established.**

Started as a tidy-up: working tree from S17 had ~155 lines of uncommitted main.py work that turned out to be CR-010 and CR-006 already implemented and live (the `__pycache__` mtimes told the tale). Plus drafted but uncommitted CR-011 OWL-side artifacts. First half of the session: split the main.py diff into clean per-CR commits, ship CR-011, fix gitignore, and hand the CR-011 system-side config off as a sudo runbook (which the owner ran + smoke-tested green same day).

Second half pivoted into carbon-credibility work after the owner spotted that the live FR carbon intensity (13 g/kWh) and the 2024 annual mean (53 g/kWh) differed by ~4× — which would be alarming if it were real. Investigation found a methodology mismatch: live used Eco2mix's `taux_co2` (direct combustion only, ~0 for nuclear), static used Ember 2024 (lifecycle, includes nuclear fuel cycle + plant construction etc.). Fixed by always deriving live from the production mix × IPCC AR6 lifecycle factors (CR-016). Then a sequence of UI-credibility improvements: de-emphasise the carbon block (move to bottom of every result, smaller font), frame it as "high-level estimate" everywhere, add EV-distance equivalence as a relatable comparator, then add curated historical France data (CR-018 Tier 1) so visitors can see how the grid has actually evolved.

### Code — CR-010 (carbon comparison strip)

- **`_CARBON_JS` reference row** (main.py:~394–~575) — every result page's carbon comparison `<details>` now opens with a pinned **home-zone reference row**: same zone as the live headline, but its Ember 2024 annual mean. When live and reference diverge by ≥25%, a one-line note flags whether today's grid is "cleaner than" or "dirtier than" the year's mean (smaller deltas suppressed as noise). Reference row suppressed when the headline itself is EST — no value duplicating the same number.
- **Live-source explainer dispatch on `HOME_ZONE`** — formerly hard-coded to France/Eco2mix wording. Now dispatches: FR gets the Eco2mix→ElectricityMaps→Ember ladder copy; any other home zone gets ElectricityMaps→Ember. Full live-source ladder for non-FR zones is a deferred CR; this just stops the wording from lying if the server moves zones.
- **Live mix subheading dispatch** — `mixZone` and `mixProvider` now come from the live response (`zone_label`, `provider`) rather than the hard-coded "French grid right now (live, via Eco2mix)" string.

### Code — CR-006 (BETA framing for AI workloads)

- **`_BETA_CHIP` constant** (main.py:~575) — single source of truth: small monospace `BETA` chip with the project's border + text-5 colour tokens. Used everywhere the framing copy needs to land.
- **Landing-page nav** (main.py:~773 + ~819) — `nav-label` "AI workloads" → "Beta · exploratory" with a short explainer below ("Energy / quality / faithfulness tradeoffs we're investigating. Less mature than video — signal can be below the P110 floor; interpret with care."). Each AI-workload nav button picks up an inline `<span class="beta-tag">BETA</span>`. CSS additions for `.nav-beta-note` and `.beta-tag`.
- **Page h1s** — `/llm` (main.py:1900), `/rag` (main.py:2708), `/image` (main.py:4938) all gain `{_BETA_CHIP}` next to their h1 text. Streaming `/video` deliberately untouched — that's the headline.
- **Demo Tour entering-beta band** (main.py:~3805) — after step 1 (the production-grade video result), a dashed-border framing band appears: "Entering beta · exploratory" header + body text inviting visitors to stop here if they only wanted the streaming-impact story. Steps 2/3/4 (LLM, image, RAG) gain `{{BETA_CHIP}}` placeholders next to their h1s, substituted at render time by `demo_page()` (main.py:~5453).

### Code — CR-011 staging via maintenance-page swap (fully shipped)

- **`bin/stage-on`** — drain queue (60s timeout, polls `/live` for `queue_depth`), touch `/tmp/owl-maintenance`, optional `git checkout <branch>`, `sudo systemctl restart wattlab`. Sources `.env` for the gate cookie so loopback `/live` calls can authenticate.
- **`bin/stage-off`** — optional `git checkout main`, `sudo systemctl restart`, **wait for `/live` to respond OK (30s budget)**, then remove the flag. If the service fails to come back up the flag stays raised and the script exits non-zero — visitors keep seeing the maintenance page until a successful `stage-off`.
- **`wattlab_service/static/maintenance.html`** — owl mark + GoS framing + "5–15 minutes" expectation, no JS. Served by nginx directly so no FastAPI dependency during restart.
- **`STAGING.md`** — workflow doc + nginx vhost edits + rollback notes. Captures the queue-drain trade-off (didn't implement snapshot+restore for pending jobs because that would require refactoring every `enqueue()` call site to serialise (type, params) tuples plus a coroutine factory registry — ~half a day touching four modules; drain-with-timeout is ~10 lines of bash and acceptable given GoS1's typical idle queue depth ≈ 0).
- **System-side config applied + smoke-tested same day** — `usermod -a -G gos www-data`, nginx vhost edits installed via `/tmp/wattlab.nginx.new` → `/etc/nginx/sites-available/wattlab` (added `error_page 503 @maintenance` block, `/static/` direct location, and `if (-f /tmp/owl-maintenance) { return 503; }` in both proxy `location` blocks), `nginx -t && systemctl reload nginx`. Smoke test: flag raised → public returned 503 + maintenance.html, LAN returned 302 (owner bypass intact); flag lowered → public returned 302 (back to live); `/static/owl.svg` direct-served by nginx returned 200.
- **`bin/README.md` established** — the canonical home for operator-script docs. Pattern: each script gets a section with description, usage block, options table, examples, and a "Things to know" list. Future scripts in `bin/` add a section here. Root `README.md` gets a one-line pointer.

### Code — CO2e UI hierarchy (de-emphasis pass)

GoS works in Watts primarily; CO2e is secondary. Two changes to reflect the hierarchy:

- **Strip moved from top to bottom** — `wlCarbonStrip(...)` was rendering immediately under each result `<h2>`, competing visually with the energy figures. Moved to just before the scope-note in every result block. Mechanical edit across 12 sites: video single/both/all_codecs, LLM single/batch/both/all, RAG single/compare-3-modes, image single/cpu-vs-gpu/compare-models. The inline `wlCarbonRow` line stays where it is — already small and low-weight under each Energy ΔE.
- **Headline number shrunk** 1.5rem → 1rem in `wlCarbonStrip` (and the matching "below P110 measurement floor" placeholder branch). The strip no longer competes with the energy figures above it.

### Code — CR-016 (live and static CO2e on the same lifecycle boundary)

- **`carbon._fetch_eco2mix` flipped** — was: prefer Eco2mix's precomputed `taux_co2`, fall back to `compute_intensity_from_mix(mix)` if missing. Now: always derive lifecycle intensity from the production mix × IPCC AR6 factors. The infrastructure was already there (`compute_intensity_from_mix` existed as a fallback path; mix already extracted from the record); the fix was a path-flip plus dropping the `computed` flag (every value is now derived; the distinction is gone). Eco2mix's own `taux_co2` is preserved as `g_per_kwh_direct` in the response for transparency in the JSON audit trail, but no longer drives the displayed UI.
- **Module docstring + comments updated** to call out: live and static both lifecycle, comparable, gap reflects real diurnal variance.
- **Two regression tests added** (`test_eco2mix_response_returns_lifecycle_not_taux_co2`, `test_eco2mix_returns_none_when_mix_unusable`) so the boundary contract can't silently regress later. 30 carbon tests passing.
- **Sanity check after restart**: live FR moved from 13 g/kWh (direct, nuclear-heavy hour) to 26 g/kWh (lifecycle from a 66% nuclear / 17% solar / 9% hydro / 6% wind / 0.5% gas mix). Math confirmed: 0.66×12 + 0.17×45 + 0.09×24 + 0.06×11 + 0.005×490 ≈ 26 g/kWh. Live-vs-static gap dropped from ~4× to ~2× — within the genuine diurnal range for France.

### Code — CO2e framing + EV equivalence

- **`_BETA_CHIP`-style "HIGH-LEVEL CO₂e ESTIMATE" caption** at the top of every carbon strip. Frames the whole block as derived/estimated context, distinct from the measured energy above. Tooltip explains the basis (Wh × grid intensity, energy is measured at the wall).
- **Inline row label** `wlCarbonRow` changes "CO₂e" to "CO₂e (est.)" so the framing carries through.
- **EV-distance equivalence line** in the strip headline: `≈ X mm/m/km driving a typical EV` using `EV_G_PER_KM = 50` (Transport & Environment 2024 European fleet average lifecycle operational intensity). New `fmtEvDistance()` helper auto-switches units so tiny digital workloads still read meaningfully (e.g., `≈ 3 mm` for an image gen). The "this is genuinely tiny in EV-terms" reading IS the message — streaming-at-scale is about volume × frequency, not single-job footprint.
- **Methodology page + carbon-strip explainer text updated** for CR-016: now describes the lifecycle calculation (production mix × IPCC AR6 factors) instead of "trust Eco2mix's precomputed value." New trailing italic line: "Live and reference are on the same lifecycle boundary, so the two numbers are directly comparable. The gap reflects real diurnal grid variance, not a methodology mismatch." That line is the credibility insurance — it pre-empts the "wait, this doesn't add up" reaction.

### Code — CR-018 Tier 1 (historical France carbon rows)

- **`bin/fetch-historical-mix`** — one-shot Python helper. Hits the Eco2mix consolidated dataset (`eco2mix-national-cons-def`, FR national, 2012–present, 30-min resolution) for a given `--year YYYY --month MM`, runs each record through `carbon.compute_intensity_from_mix` (same code path as live), prints monthly mean lifecycle g/kWh. Reusable for adding more dates: `--quiet` for pipeline use, otherwise prints per-page progress on stderr.
- **Five curated FR historical entries** added to `carbon.HISTORICAL_INTENSITY`:

  | Date | g/kWh | Story |
  |---|---|---|
  | Jan 2020 | 65.8 | Pre-Covid winter |
  | Jun 2020 | 54.6 | Covid-lockdown summer |
  | Jun 2022 | 59.5 | Energy-crisis-era summer |
  | Jan 2024 | 53.4 | Post-recovery winter — cleaner than Jan 2020 despite the season |
  | Jun 2024 | 26.9 | Recent summer — nuclear back, solar buildout reflected |

- **Notable finding from the data**: the French nuclear corrosion crisis (popularly framed as a huge carbon spike in 2022/early 2023) shows up much less dramatically in monthly lifecycle averages than the news made it sound — Jan 2023 was 63.2 g/kWh, only marginally higher than Jan 2020's 65.8 and Jan 2024's 53.4. The bigger story the data tells is the long-term cleaning trend, especially in summer (Jun 2022 → Jun 2024 = 55% reduction in two years). Captions revised to reflect what the data actually shows, not the popular narrative.
- **`historical_for_zone(zone)` helper + `historical_table` / `historical_source` fields on `/carbon`** so the JS can render without a separate fetch.
- **"Through history" rows in the carbon strip** between comparison cities and the formula explainer. FR-only (suppressed for other home zones until those have curated history). Each row shows label + grams + ratio-vs-now + monthly mean intensity, with the narrative note as a small italic sub-line. Closing italic disclaimer: "Same lifecycle methodology as the live number above … Curated dates illustrate the range of grid evolution; not exhaustive."
- **Methodology page** picks up a new "Through history (France)" subsection documenting source, methodology consistency with live, the curated-vs-exhaustive choice, and the ops command for adding more dates.

### Variance recalibration

Settings.json picked up runtime updates from a calibration run during S17/S18 testing: `variance_pct` 1.08 → 3.62 (idle 1.79→6.66, CPU 0.82→3.72, GPU 0.64→0.49), `variance_runs` 10→15, `variance_cooldown_s` 90→60. Confidence multipliers (`variance_green_x=5`, `variance_yellow_x=2`) unchanged — 🟢/🟡/🔴 boundaries automatically widen. `baseline_polls` 7→8, `video_cooldown_s` 30→60 to match the recalibrated noise envelope. Three new `*_bitrate_kbps` fields (4000/2000/1500) added so the canonical ABR all-codecs benchmark values live in settings.

### Tidy

- **`.gitignore`** expanded for `.chroma/`, `corpus/` (RAG runtime data + source PDFs), `*.bak`, `*.session*`, `amdgpu-install_*.deb`, plus `REM/` and `TRAINING_REM_5MIN.md` (sibling project — REM has its own repo at `dom-robinson/stats`; the in-repo dir is just a working copy for cross-project context).
- **`__pycache__/*.pyc`** — four files (`llm`, `main`, `sources`, `video`) had slipped into the index before `*.pyc` was in `.gitignore`. `git rm --cached`'d so they stop appearing as modified noise on every restart.

### CRs captured (for later)

- **CR-015** — Auto-lower the maintenance flag on inactivity. CR-011's flag persists indefinitely until explicit `stage-off`; walking away leaves public on the maintenance page. Design: piggyback on the S17 access spine — Lab-tier middleware bumps the flag's mtime on every request; systemd watchdog lowers it if mtime exceeds `max_idle_mins` (default 30, settings-tunable). Owner does nothing extra.
- **CR-017** — 24/7 projection toggle on the carbon strip. Owner asked about adding "if this workload ran continuously" to make CO2e at scale visible. Not shipped because it only makes physical sense for naturally-continuous workloads (LLM serving, live-stream encoding, RAG service); projecting onto a one-off image gen reads as silly. Design: simplest first version is a multiplier toggle (1h / 1d / 1mo / 1yr) the visitor opts into, with per-workload-type defaults layered on later.
- **CR-018 Tier 2 + Tier 3** — full historical coverage. Tier 2: bin/refresh-historical-carbon fetches every month from 2012, caches to JSON, comparison strip gains a year-month picker. Tier 3: interactive timeline scrubber. Both post-launch — Tier 1's curated five-date story actually lands sharper for conference than a slider would.

### What's next

Next session opens cleanly on **CR-001b — demo lock**:

- Plugs into the seam shipped in S17 spine commit A — `queue_control.enqueue(request=None)` takes the request specifically so CR-001b's owner-identity check has somewhere to attach.
- Stopgap owner identity: gate password (`WATTLAB_GATE_PASSWORD` cookie). Magic-link auth lands with CR-001 proper.
- Iteration cycle is now amplified by CR-011 staging — use `bin/stage-on --branch cr-001b` to test live without bouncing the public site.
- Estimated effort: ~½ day. Full design context in `CHANGE_REQUESTS.md` lines 115–166.

After CR-001b: **CR-001** (two-tier OWL — magic-link auth + capability-tier UI + conference launch, mid-June 2026).

### Commits

- `63d38fc` part 1: close CR-010 (carbon comparison strip — home-zone reference row)
- `4c0b496` part 2: close CR-006 (BETA framing for AI workloads)
- `13ba8af` part 3: settings.json — variance recalibration + bitrate fields
- `d622505` part 4: CR-011 OWL-side — staging via maintenance-page swap
- `8dcad5e` part 5: tidy gitignore + untrack .pyc files
- `3f39288` part 6: update CLAUDE.md + JOURNAL.md for S18 (interim)
- `e0b3b2f` part 7: document operator scripts in bin/README.md
- `2ab739c` part 8: capture CR-015 + mark CR-011 done
- `c8791e2` part 9: de-emphasise CO2e in result reports
- `c8c2316` part 10: close CR-016 (live + static CO2e on the same boundary)
- `4875ba5` part 11: CO2e UI framing + EV-distance equivalence
- `dcbadbb` part 12: capture CR-017 (24/7 projection on the carbon strip)
- `6d06a81` part 13: update CO2e explanation text for CR-016 methodology
- `bf462c3` part 14: CR-018 Tier 1 — historical France carbon rows
- `34c9d5e` part 15: capture CR-018 Tier 2 + Tier 3 (full historical)
- `2da3b23` part 16: document fetch-historical-mix in bin/README.md

---

## Session 17 — 2026-05-01 / 2026-05-02

### What we did

**Access spine refactor (audit's #1 recommendation, A/3 + B/3 + C/3) · CR-002 closure · CR-014 RAG carbon strip · CRs 010/011/012/013 captured**

Two-day session. Day one extracted the access spine the audit called out as the prerequisite for CR-001. Day two closed CR-002 properly — the original methodology fix shipped in S16, but the popover and Guided Tour were still drifting (and the popover had a silent positioning bug nobody had noticed because the *content* was technically present, just rendered offscreen). Followed by a small RAG carbon-strip gap discovered during verification.

### Code — Spine refactor (parts A/3 + B/3 + C/3, day one)

- **`queue_control.py`** (new module, extracted from `main.py`) — single chokepoint for queue mutation. Public API: `depth()`, `paused()`, `pause(reason)`, `unpause()`, `enqueue(request=None)`. The `request=None` parameter is the CR-001b demo-lock seam — when a request is supplied, `enqueue` can consult `audience.tier(request)` and a future demo-lock owner check before honouring the call. No behaviour change today; the seam is for next session.
- **`audience.py`** (new module) — single source of truth for "who is this request from". `tier(request)` returns `Anonymous | Member | Lab`. Today it implements only the Anonymous-vs-Lab split (LAN IP detection, replacing the old `_is_local()` helper); Member tier is stubbed for CR-001. Tests assert that `127.0.0.1`, `192.168.x`, and `10.x` private blocks return `Lab`; everything else returns `Anonymous`.
- **`capabilities.py`** (new module) — declarative capability constants (`PUBLIC_PAGE`, `SETTINGS_READ_FULL`, `QUEUE_VIEW`, etc.) plus `requires(cap)` FastAPI dependency factory and `can(tier, cap)` helper. Every existing endpoint now declares its required capability; the grep target `requires(` becomes the security audit. No-op for end users today (every cap is satisfied by Anonymous), but CR-001 just tightens the table without touching routes.
- **Route tagging pass** — every `@app.get` / `@app.post` in `main.py` gained `dependencies=[Depends(requires(...))]`. ~30 endpoints touched. `_is_local()` removed; callers use `can(audience.tier(request), SETTINGS_READ_FULL)`.
- **Settings.save partial-update fix** (`settings.py`) — POST to `/settings` was overwriting the on-disk file with only the form-submitted keys, dropping anything the form doesn't render (e.g. variance values written at calibration time). Fix: load → merge → save. Caught by hand-testing CR-002's variance threshold rendering.

### Code — CR-002 closure + CR-014 (day two)

- **`_CONF_HELP_WIDGET` rewritten** (main.py:555) — the popover content was still using the **pre-S11 fixed-watt framework** (`ΔW > 5W and ≥ 10 polls`), directly contradicting `/methodology`. Made qualitative + framework-correct (`ΔW well above measured noise, with enough polls to confirm`) with a footer link to `/methodology` for formal numbers. Avoided plumbing live settings into 5 frozen page templates.
- **Popover positioning bug** — script set `pop.style.top = r.bottom + 6 + window.scrollY`. Popover is `position:fixed` (viewport-relative). The `+window.scrollY` pushed it offscreen below the viewport whenever the user had scrolled to see the badge. **Removed the scroll offset.** This was the root cause of every "click does nothing" report — the popover *was* opening, just not where the user could see it. Subtle bug because the cursor:pointer rule and event handler were both wired correctly; only the final positioning was wrong.
- **Missing `class="conf-badge"` batch fix** — ~13 badge-rendering sites across `/video`, `/llm`, `/image` (and a few shared helpers) emitted the flag in plain `<div>`/`<td>`/inline interpolations without the class. Click handler's `e.target.closest(".conf-badge")` returned null → silently skipped. Added via Python script with strict-count assertions per pattern. Total class hits in source: 22.
- **Prev-run badges wrapped** (main.py:1514, 1517, 1520, 2384, 3097, 4765) — Previous-runs panels flattened the confidence flag into a one-line summary string with no wrapping element. Wrapped the flag emoji in `<span class="conf-badge">` so prev-run rows fire the popover too. `/image`'s prev-rendering is server-side Python f-string and got the same treatment.
- **Guided Tour placeholder injection** (main.py:5319) — `demo_page()` route now calls `cfg.load()` and `.replace(...)` on `_DEMO_HTML` for `{BASELINE_POLLS}`, `{VIDEO_COOLDOWN_S}`, `{CONF_GREEN_X}`, `{CONF_GREEN_POLLS}`, `{CONF_YELLOW_X}`, `{CONF_YELLOW_POLLS}`. Same idiom as `methodology_page()`. Tour now agrees with `/methodology` on every threshold.
- **CR-014 — RAG compare-3-modes carbon strip** (main.py:3066) — single-mode RAG already called `wlCarbonStrip` at line 2899. Compare-3-modes was missing it entirely (visitors using the more interesting view saw no cross-grid comparison). Added at the top of the report using `Math.min` of the three modes' energies — same idiom as `/llm` CPU-vs-GPU at line 2177.

### CRs captured (day one)

- **CR-010** — France historical reference row in the comparison strip dropdown. Live FR (~11 g/kWh, nuclear-dominated) reads very differently from the 2024 annual mean; without the historical row, viewers could conclude "France beats Germany 10×" when in fact the live snapshot is at the cleanest end of France's own distribution. Add `France HISTORICAL · EST · REF` row in `_CARBON_JS` comparison strip.
- **CR-011** — Staging environment via maintenance-page swap. Single-service swap with nginx-level static maintenance page triggered by `/tmp/owl-maintenance` flag file. ~1 hour of work; high leverage for CR-001 testing because the spine refactor's restart-and-test cycle was painful enough to make this worth doing before CR-001 lands.
- **CR-012** — Persist variance calibration history. `settings.json` only keeps the latest `variance_pct`/`variance_idle_pct`/etc.; previous values vanish. Append-only `results/variance/history.jsonl` with kernel + git_sha context for "did variance jump after kernel 6.17?" type questions. ~30 min, cheap filler.
- **CR-013** (day two) — Previous-result rows clickable for full stored detail. The popover wrapping made the prev-runs panel's information density gap obvious: rows show date + summary + JSON download, but no inline detail. Click-to-expand-inline pattern, re-using each page's existing render function. Medium priority.

### What's NOT done

- Service restarted on day two; popover + RAG strip live and verified working across `/video` `/llm` `/rag` `/image` `/demo`.
- Spine refactor is wired but no Member tier yet — CR-001 will define and add Member identity (magic-link auth).
- ElectricityMaps API trial still pending (token requested 2026-04-30).
- No tests added for the spine modules yet — they were extracted from working code, but the audit recommendation was "tests-with-spine." Test suite for `audience.py` / `capabilities.py` / `queue_control.py` is technical debt going into CR-001b/CR-001.

### What's next

Order locked in during day-two scope conversation:
1. **CR-010** France historical row — small, high pedagogical value.
2. **CR-006** AI workloads → beta/skunkworks framing — small, shapes what conference visitors see first.
3. **CR-011** staging environment — ~1 hour, lands right before CR-001 to amplify the upcoming restart-and-test churn.
4. **CR-001b** demo lock — uses the `enqueue(request=None)` seam from S17 spine refactor.
5. **CR-001** two-tier OWL — magic-link auth, capability-tier UI, conference launch (mid-June 2026).

---

## Session 16 — 2026-04-30 / 2026-05-01

### What we did

**CO₂e measurement + Eco2mix integration · CR-002 methodology accuracy · first automated test suite · conference-prep strategy package**

The session split across two days but reads as one block of conference-prep work (training course is May 18 dry-run, mid-June stage).

### Code

- **`carbon.py`** (new module, ~290 lines) — single home for Wh→gCO₂e conversion. Three-tier fallback ladder: **Eco2mix (RTE/Etalab official French TSO data, 15-min cadence, no auth)** → **ElectricityMaps (paid backup, requires token)** → **Ember 2024 static annual means** (always-floor + comparison cities). Background poller refreshes home-zone live cache every 5 minutes. `walk_and_enrich(payload)` walks the result tree and injects a `co2e` block on every nested `energy` dict — single insertion point covers every job mode (single, both, all_codecs, batch, all, all_both, rag, rag_compare, compare_models). IPCC AR6 emission factors documented as a fallback if Eco2mix ever drops `taux_co2`.
- **`persist.py`** — calls `carbon.walk_and_enrich(payload)` at save time. CSV exports gain `co2e_g`, `co2e_intensity_g_per_kwh`, `co2e_source`, `co2e_zone` columns across video/image/llm/rag.
- **`main.py` `_CARBON_JS`** (~150 lines of JS injected via `_FOOTER`) — defines `wlCarbonRow(e)` (inline CO₂e row under any Energy ΔE) and `wlCarbonStrip(wh, label)` (per-result "if this had run elsewhere" block, with collapsed `<details>` showing comparison cities + live French production mix breakdown + formula provenance). Headline up top with big LIVE/EST badge. `fmtMass` auto-switches g/mg/µg by magnitude (~2 sig figs across 6 orders). When ΔE rounds to 0 (below P110 floor), renders `—` with a "below measurement floor" tooltip rather than misleading "0 g".
- **CR-002 methodology accuracy pass** — `/methodology` now uses placeholders for `baseline_polls`, `video_cooldown_s`, and the four confidence thresholds (`variance_green_x`/`variance_yellow_x`/`conf_green_polls`/`conf_yellow_polls`); `methodology_page()` route handler injects values from `cfg.load()` at request time. Drift is structurally impossible. P110 quantisation copy fixed to state both 1 W via API (current path) and 1 mW via direct device read (instrument capability). "From energy to CO₂e" section rewritten to reflect the actual three-tier ladder with sources cited.
- **Result-card template insertions** — `${{wlCarbonRow(e)}}` after every Energy row across ~10 render templates (video single/both/all_codecs, LLM single/both/all/batch, RAG single, image single/both/compare-models). `${{wlCarbonStrip(...)}}` once per report at the top, using a sensible headline Wh per mode.
- **Round-precision regression fix** — was `round(grams, 3)` in `wh_to_co2e`; changed to `round(grams, 9)` (nanogram precision). Caught when a tiny LLM task (~0.001 Wh on French grid) was rendering as `0 g` because 5.3e-5 truncated to 0.0 in persist. Lesson logged as a regression test.

### Tests (first automated test suite in the repo)

- `wattlab_service/tests/conftest.py` — pytest path setup so tests run with `pytest wattlab_service/tests/` from any cwd.
- `wattlab_service/tests/test_carbon.py` — 28 tests covering: static fallback (3), the round-precision regression (named after the bug), live cache freshness (4 — fresh / stale-by-clock / stale-by-source-datetime / failed fetch), `walk_and_enrich` on every real result shape (10 — single, both, all_codecs, all, rag_compare, batch-with-list, idempotency, defensive non-dict handling), `comparison_table` (5), `compute_intensity_from_mix` IPCC AR6 fallback math (4). All 28 pass in 0.04s.
- Pattern documented in the test file's docstring so the upcoming access-spine modules (audience.py / capabilities.py / queue_control.py) follow the same shape: pure logic, regression tests named after bugs, fixtures for module-state reset, no live HTTP.

### Strategy / docs

- **`CHANGE_REQUESTS.md`** (new doc) — captures architectural decisions:
  - **CR-001 Two-tier OWL** — anonymous public + authenticated members + LAN/lab tier, single deployment with `audience.py` capability gating, magic-link email auth, OWL framed as a deliberate GoS membership funnel ("public sees results, members shape inputs"). Refined mid-session per training-prep transcript: anonymous tier *can* upload (capped at 100 MB, 1 concurrent job per visitor — 10 MB initially proposed and rejected for being below the P110 measurement floor).
  - **CR-001b Demo lock** — `/tmp/owl-demo-lock` flag, owner-only enqueue access, auto-expire after `demo_lock_minutes` (default 60) so a forgotten lock during conference Q&A doesn't silently brick the system. Can ship before CR-001 with a `demo_lock_owner` stopgap.
  - **CR-002 through CR-009** — methodology accuracy (CR-002, shipped this session); iso-energy bitrate sweep ("I want to spend X Wh, what are my options?", IBC white-paper material); visual graphing in result cards; software fan-speed control during tests; AI workloads → beta/skunkworks area; carbon variance over time-of-day/season/location study; REM ↔ OWL integration (branding step + long-term data interop); cross-platform web client test bay.
- **`AUDIT_BRIEF.md`** + **`AUDIT_RESPONSE.md`** — pre-CR-001 architecture audit: brief sent to ChatGPT, ChatGPT's response captured. Both agreed: the issue isn't `main.py` size, it's coupling. Recommendation: build an access spine (`audience.py` / `capabilities.py` / `queue_control.py`) with tests *before* CR-001 lands. Estimate: 2–4 days. Tests should land *with* the spine — the carbon test suite this session is the warm-up.
- **`TRAINING_OWL_5MIN.md`** — 5-minute spoken narrative of OWL for the GoS training course. Sibling deliverable `TRAINING_REM_5MIN.md` to be produced in a separate session (prompt drafted, REM repo at github.com/dom-robinson/stats).
- **`rem-theme.css`** — ~220-line drop-in stylesheet that re-skins the REM Linksi page (`test.greeningofstreaming.org`) to match OWL's visual identity. CSS variables identical to OWL's `_BASE_STYLES`. Two minimal HTML edits required at REM's end (link tag + optional logo wordmark snippet, included as a comment).
- **CLAUDE.md prune** — 383 → 189 lines, ~16.8k → ~5.1k tokens (~70% reduction). Dropped: stale Network/Tailscale temporary sections (Bouygues was restored long ago), session 11–15 implementation prose (one-line summaries kept), completed Phase 1–8 checklists, completed `[x]` items in Deferred, superseded findings. Kept: load-bearing context (server config, framing, protocol, traffic-light, current canonical findings, RAG faithfulness story).
- **OWL public name confirmed** — project is publicly **OWL (Online WattLab)**; "WattLab" stays internal/repo. Captured in MEMORY.md so future sessions don't relearn.

### What's NOT done

- Service has not been restarted; the CR-002 methodology fixes are on disk but not yet visible on the live `/methodology` page. `sudo systemctl restart wattlab` to apply.
- ElectricityMaps API trial submitted 2026-04-30, awaiting response (~24h). Once it arrives: paste token into `.env`, bump `carbon.py` `ELECTRICITYMAPS_URL` from v3/`.org` to v4/`.com` (one-line edit per current docs), restart.
- `settings.json` has uncommitted drift unrelated to today's session (variance values nulled, baseline_polls 7→5, video_cooldown_s 30→15, llm_rest_s 10→8, bitrate fields propagated from DEFAULTS). Investigate before committing — cleared variance values may be deliberate (about to recalibrate) or an accidental flush.

### Decisions / open questions surfaced

- **OWL is a deliberate GoS membership funnel** (not just a tool with tiers). The capability matrix is product copy first, security model second. Locks are the pitch, not the punishment. Worth instrumenting CTA clicks weekly as funnel performance signal. Open question: CTA copy + click-through destination needs decision before conference launch.
- **Magic-link email > OAuth** for member auth at this scale (~tens of GoS members). Avoids "create account" friction.
- **Public usefulness is top-of-funnel.** Never gate measurement quality; only inputs (custom upload, custom prompts) and bookkeeping (CSV export, history) are member-only.
- **Anonymous upload allowed at 100 MB cap, 1 concurrent job per visitor** — supports demonstrable measurement on the public side without abuse vectors.
- **Tests-with-spine pattern** confirmed: every new module ships with its tests; no separate "testing sprint."

### What's next

1. Restart service to apply CR-002 fixes; verify on `/methodology`.
2. ElectricityMaps token integration (when trial response arrives).
3. **Access spine refactor** — `audience.py` + `capabilities.py` + `queue_control.py` with tests, in a branch with manual smoke checklist. Audit's #1 recommendation, prerequisite for CR-001. ~2–4 days.
4. CR-001 implementation (auth, public landing page, locked-feature affordances) on top of the spine.
5. CR-001b demo lock — can ship before/alongside CR-001 with `demo_lock_owner` stopgap.
6. CR-006 AI → beta/skunkworks area (~half-day, affects visitor first-impression).

### Files touched

- New: `wattlab_service/carbon.py`, `wattlab_service/tests/conftest.py`, `wattlab_service/tests/test_carbon.py`, `CHANGE_REQUESTS.md`, `AUDIT_BRIEF.md`, `AUDIT_RESPONSE.md`, `TRAINING_OWL_5MIN.md`, `rem-theme.css`.
- Modified: `wattlab_service/main.py`, `wattlab_service/persist.py`, `CLAUDE.md` (pruned), `JOURNAL.md` (this entry).
- Memory: `~/.claude/projects/-home-gos-wattlab/memory/electricitymaps_trial.md`, `project_name.md`.

---

## Session 15 — 2026-04-29

### What we did

**Readability + visual consistency pass · RAG bug fixes · RAG polish · Corpus doc browser · Demo prep for 2026-04-30**

#### `_BASE_STYLES` — single source of truth for content colours
The site shipped with 396 inline `color:#xxx` declarations across `main.py`, dominated by `#555` (used 112×, ~3.3:1 contrast on `#0a0a0a` — fails WCAG AA). User feedback flagged grey-on-black as hard to read on mobile. Fixed in two passes:

1. Added `_BASE_STYLES` constant (`main.py:~276`) — a single `<style>` block defining `:root` CSS variables for all content colours (`--text` / `--text-2..5`), accents (`--accent` / `--warn` / `--err`), backgrounds (`--bg` / `--panel`), and borders. Plus base body sizing and a `@media (max-width:600px)` block that bumps the smallest sub-label fonts on phones. Injected via `_FOOTER` (covers all standard pages) and directly into the `/gate` page.
2. Bulk migration via Python regex script: 620 mechanical replacements of `color:#xxx`, `background:#xxx`, `border-color:#xxx`, and `1px solid #xxx` literals → `var(--*)`. Worst offender `#555` → `--text-3` = `#8a8a8a` (~6.6:1, AA). Alpha-channel variants like `#00ff99XX` intentionally left as literals — they're translucent overlays semantically distinct from `--accent`.

Future readability tweaks are now one place: edit `--text-3` / `--text-4` / `--text-5` and the whole site shifts together.

#### Visual consistency — owl logo + Guided Tour findings
- Replaced the inline `← Home` link on `/queue-status` with the shared `_BACK` snippet (now uses `""" + _BACK + """` concat pattern, matching how `_FOOTER` is wired in the same page).
- Added the owl SVG before the existing GoS logo in the `/methodology` topbar — project mark + org credit visible together. (User flagged that the methodology topbar layout still differs from other pages — recorded as a deferred "factorise headers/footers" item; the symptom is left-justified logo + title + bespoke `.topbar` div predates the `_BACK`/`_FOOTER` consolidation.)
- Refactored `buildSummary` (`main.py:~4223`) on the Guided Tour final step: video transcoding now leads as the headline (`<h2>` + scope sentence + flat table), with LLM / Image / RAG demoted to collapsible `<details>` blocks under an "OTHER WORKLOADS MEASURED" subhead. Reflects the GoS thesis that video is the streaming-impact story; AI workloads are interesting but secondary.

#### RAG Compare 3 Modes — bug fixes
User reported `-0.0133 mWh/tok` for TinyLlama on rag_large in a Compare 3 Modes run. Investigation surfaced three bugs in `run_rag_compare_job` (`main.py:~2846`):

1. **No cooldown between modes.** Loop ran `run_rag_measurement()` back-to-back. With TinyLlama's sub-2s inference, the rag_large baseline was contaminated by residual heat from the rag run (w_base inflated from 53 W cold → 64 W after rag), making `delta_w` go negative. Fixed: added `await asyncio.sleep(s["llm_rest_s"])` between iterations (skipped after the last). Reused existing `llm_rest_s` setting (default 10s) — no new settings field.
2. **Stage-name collision.** Outer loop set `jobs[job_id]["stage"] = rag_mode` ("baseline"/"rag"/"rag_large"), then the inner `run_rag_measurement` immediately overwrote with its own "baseline"/"inference"/"done" stages. The JS `RAG_STAGE_IDX` map only knew the inner three, so it silently fell back to index 0 for "rag"/"rag_large" — the progress bar appeared to reset between modes. Fixed: outer loop no longer touches `stage`, only `current_mode` and a new `mode_index`.
3. **Stage list undersized for the 9-phase flow.** Deferred — current 3-stage display works for single mode, and compare-mode renderer (`renderCompareProgress`) shows mode-level progress with the new "⏱ Cooling down" row, which is sufficient.

#### RAG polish for tomorrow's demo
- Renamed "Baseline" → "Without RAG" in the RAG section UI only (display labels: mode card, single-mode `ragModeLabels`, compare-mode `MODE_LABELS` ×2, Guided Tour `buildSummary` ragRows). Internal `baseline` mode key kept — renaming would break stored result files and CSV schemas.
- Pre-populated `/rag` question textarea with **"What is REM (Remote Energy Measurement)?"**. Corpus-grounded (the GoS REM whitepaper is in the index), and surfaces a strong demo finding: all three model sizes retrieved the same correct chunks for this question, but TinyLlama hallucinated "REM is a framework provided by the European Commission" (blending the GoS source with an adjacent JRC sustainability framework chunk), while Gemma 3 12B and Phi-4 14B stayed faithful. Headline insight: **RAG retrieval ≠ RAG quality. Hallucination is a third axis on the energy/quality tradeoff.**
- Added an inline `<details>` callout under the question textarea explaining (1) why this question, (2) what visitors will see, and (3) the headline insight. Visible inline rather than buried in methodology.
- Replaced the previous "What year did your training data end?" demo question — it was a meta-question about the model's own state, but RAG floods context with dated corpus documents, causing models to conflate "this PDF is dated 2025" with "my training cutoff is 2025". Misleading demo of RAG capability.
- Dropped the hardcoded `(10s)` from the RAG progress bar label — actual baseline duration honours `s["baseline_polls"]` (now 7s in user's settings). Label is now just `'Baseline poll'` so it can never go stale regardless of settings.

#### LLM CSV — response column
JSON files already include `inference.response` (full LLM output) but CSV export at `persist.py:71-76` excluded it. Added `response` to fieldnames and to the `_row` helper inside `_llm_rows`. CSV-quoting handled by `csv.DictWriter` defaults — newlines preserved inside quoted fields. Applies to single, batch, both, all, all_both, rag, and rag_compare modes.

For `mode: rag_compare`, also confirmed structure: there's no top-level `inference.response` (no top-level `inference` dict at all) — each mode result lives under `results.<mode>.inference.response` (and also `results.<mode>.answer`). Both contain the full LLM output. No normalisation needed.

#### RAG corpus document browser
New `corpus_list()` in `rag.py` returns `[{name, rel_path, size_kb, indexed}]` — cross-referenced against the ChromaDB collection's source-filename metadata to show indexed vs pending. New `GET /rag/corpus-list` endpoint wraps it with totals. Collapsed `<details>` panel on `/rag` (between index bar and Model section); on first open it sorts pending first, renders a scrollable list with green ● / amber ○ status dots, per-doc size and tag, and a footer note explaining how to add docs.

Demo angle this unlocks: "the GoS REM whitepaper is right here in the index, alongside 92 other PDFs — anyone can drop a paper in and rebuild." Concrete, visible, anti-slideware.

#### Stale-box audit
Tidied three Phase 6 boxes (`CLAUDE.md:173-175`) that were marked `[ ]` despite being completed in session 13: DNS A record, Let's Encrypt SSL, HTTP→HTTPS redirect. Same fix in memory: removed `project_phase6.md` and `project_deferred.md` (the latter pointed to "image elapsed time" which had been silently fixed before being ticked).

#### Testing strategy — `TESTING.md`
Wrote a three-tier testing strategy doc as the project's first quality plan. Sweet-spot principle: tests get *run* (not avoided), so we deliberately keep the bar low. Tier 1 is a 30-second bash smoke (imports + page 200s + JSON shapes + two pure-function checks); Tier 2 is a 2–5 min integration check (persistence + CSV round-trip, RAG `corpus_list` metadata sync, no full RAG rebuild); Tier 3 is a 5 min manual UI checklist with concrete click-paths for video / LLM / RAG / Guided Tour. Includes a decision matrix ("typo → Tier 1 only; pre-demo → all three") and an explicit "what we're NOT testing and why" section so the bar stays sustainable. Bash skeletons for `scripts/smoke.sh` and `scripts/integration.sh` are embedded inline — implementation deferred until first time we feel friction.

### Files touched
- `wattlab_service/main.py` — `_BASE_STYLES` constant + injection via `_FOOTER` and `/gate`; bulk hex → `var(--*)` migration; `_BACK` swap on `/queue-status`; owl logo on `/methodology` topbar; Guided Tour findings refactor (per-section row strings + collapsible AI workloads); RAG `/rag` page polish (Without RAG labels, REM question pre-fill, faithfulness `<details>` callout, dropped `(10s)`); `run_rag_compare_job` cooldown + stage-collision fix; `MODE_LABELS` cooldown row; corpus browser `<details>` panel + `loadCorpus()` JS; `GET /rag/corpus-list` endpoint
- `wattlab_service/persist.py` — `response` added to LLM CSV fieldnames + `_row` helper
- `wattlab_service/rag.py` — `corpus_list()` function (cross-references ChromaDB metadata for indexed status)
- `TESTING.md` — new file, three-tier testing strategy with bash skeletons
- `CLAUDE.md` — Session 15 entry; 8 Deferred items ticked; 4 new Deferred items added with `[LOW]`/`[MID]` priority tags on the two RAG follow-ups; stale Phase 6 trio cleared; `TESTING.md` added to See also + Repo Structure
- `JOURNAL.md` — this entry
- Memory (`~/.claude/projects/-home-gos-wattlab/memory/`) — removed `project_deferred.md` and `project_phase6.md` (stale)

### Open items coming out of this session
- Restart `wattlab` systemd service after pulling these changes (sudo required)
- Demo on 2026-04-30 — pre-warm Video Compare All Codecs (3 min) and RAG Compare 3 Modes with Phi-4 (~80s) before going live, so Previous Runs are populated as backup
- Watch the new readable-on-mobile breakpoint after demo — `@media (max-width:600px)` block bumps base + sub-label fonts; if it overshoots on tablets we can narrow the breakpoint
- After demo: see Deferred section for sized-and-prioritised follow-ups (RAG visitor upload `[MID]`, individual PDF view `[LOW]`, Findings step redesign, header factorisation)

---

## Session 14 — 2026-04-24

### What we did

**Larger LLM tier · SDXL-Turbo + Compare Models · VRAM leak fix · Progressive-disclosure UX pilot · Methodology refresh**

#### LLM tiers — adding a "large" option
Previous tiers: TinyLlama 1.1B (small), Mistral 7B (mid). Added **Gemma 3 12B** as the large tier via `ollama pull gemma3:12b` (8.1GB Q4_0). Choice rationale: same distillation family story (Google alongside Meta/Mistral), fits cleanly in 12GB VRAM without offload, knowledge cutoff ~Aug 2024. SDK knowledge cutoff is past the model's actual cutoff — when asked to write a dated report it filled in 2023-10-26 (a notorious pretraining-corpus default), which is an LLM artefact not a WattLab bug.

Also confirmed `phi4:latest` (14B) was already pulled but missing from `llm.py` — it's in `rag.py` already, so added there too. No HTML changes to `/llm` or `/rag`: both pages iterate `MODELS` so new entries auto-render as selector cards.

#### SDXL-Turbo + Compare Models
Added `stabilityai/sdxl-turbo` (~3.5B params) as a second diffusion model. `image_gen.py` gained an `IMAGE_MODELS` registry and `generate_image()` now takes a `model_key` parameter; entry points `run_image_measurement` and `run_image_both_measurement` were extended accordingly.

New `run_image_compare_models_measurement()` runs both models on GPU with same prompt + seed, both at 512×512 and both at their native 4-step operating point (SD-Turbo batch 30, SDXL-Turbo batch 15). Result is rendered side-by-side on `/image` — image quality is subjective (no single metric), energy per image is measured for each.

#### SDXL-Turbo on Navi31 — investigation
Three issues surfaced:

1. **Black images with fp16 VAE.** SDXL's VAE overflows in fp16 on our RX 7800 XT (known issue). Diffusers auto-detects this and upcasts the VAE to fp32 for decode (via deprecated `upcast_vae`). We leave `force_upcast=True`.
2. **VRAM OOM at 1024×1024.** The fp32 VAE decode allocates 4.5 GB for a single conv, exceeding our 12 GB budget when UNet + text encoders are resident. We tried `enable_vae_tiling()` but the default SDXL `tile_latent_min_size=128` uses a strict `>` check, so a 1024-output latent (exactly 128×128) fails to trigger tiling. Forced `tile_latent_min_size=64` triggers tiling but makes decode 100× slower (~115s per image).
3. **Resolution.** Picked 512×512 as the operating point — fp32 VAE decode fits comfortably, no tiling needed. Bonus: 512 is native for SD-Turbo, so Compare Models becomes apples-to-apples at same resolution with model size as the only variable.

#### VRAM leak in `generate_image`
Observed the uvicorn worker holding 9.67 GB of VRAM with no active jobs. Root cause: pipelines created in `generate_image()` weren't being released between calls — Python GC isn't timely, and ROCm's HIP allocator holds cached memory. Added `try/finally` with `del pipe`, `gc.collect()`, `torch.cuda.empty_cache()`. Latent bug, present since the image module was added; now fixed.

#### Compare Models — step parity correction
Initial Compare Models implementation ran SD-Turbo at its solo-mode 20 steps and SDXL-Turbo at 4 steps. Caught mid-conversation: this is not apples-to-apples. SD-Turbo at 20 steps is 5× over-sampled relative to its native 1–4 range (it's set high in solo mode to give P110 enough runtime). In a model comparison, SD-Turbo was being charged for over-sampling that doesn't improve its distilled output.

Fix: added `compare_steps`/`compare_batch` fields to `IMAGE_MODELS`, and `generate_image()` accepts optional `steps_override`/`batch_override`. Compare Models now runs both at 4 steps; SD-Turbo batch 30 to keep wall time ≈ 10s for P110 reliability. Solo mode unchanged for historical continuity.

#### Progressive-disclosure UX pilot
Question raised: should WattLab have two UI modes (power-user vs visitor)? Considered, rejected. Two full modes means 2× HTML to maintain, 2× copy that drifts, and `/demo` (Guided Tour) + `/methodology` already serve the visitor audience. Instead:

- Replaced verbose `.info` blocks on `/image`, `/video`, `/llm`, `/rag` with collapsed `<details>` ("ⓘ About this test") — default collapsed for lab use, expands for first-time visitors.
- Added a subtle "First time here? Try the Guided Tour →" link near the top of each test page.
- Subtitle (one-line hardware/scope summary) stays always visible.
- All control rows (model picker, preset cards, prompt editor, buttons) untouched — lab workflow unaffected.

Worth revisiting if visitor feedback says the collapsed default is too hidden.

#### Methodology page refresh
`/methodology` bumped to version 0.2 (last updated 2026-04-24):
- **Video section** rewritten for ABR rate control + full VAAPI pipeline + `all_codecs` preset.
- **Image section** rewritten for SD-Turbo + SDXL-Turbo + Compare Models, with step-count rationale.
- **LLM section** updated to list the three size tiers (TinyLlama / Mistral / Gemma 3).
- **Hardware table** updated for new codecs, models.
- **Removed** stale "CPU thermal cross-talk" limitation (resolved by full GPU pipeline in session 12).
- **Removed** stale "GPU energy crossover" open question (superseded by session 13 ABR findings — GPU is now 43–81% less energy across codecs).
- **Rewrote** "Transcoding quality equivalence" open question to reflect ABR progress (bitrate now controlled; GOP/profile still TBD).
- Added matching `← Home` links top and bottom of content (`.home-link` class — same style as the `_BACK` link on other pages).

#### Live telemetry — modular refactor
Demo feedback surfaced a request: CPU + GPU temperatures alongside the P110 wattage, updated live. Done in a way that makes adding future live metrics a one-line change.

- `power.py` gained `read_sensors_dict()` — single subprocess read of `sensors -j`, returns `{cpu_tctl, gpu_junction, gpu_ppt_w}`.
- `main.py` extended `_power_cache` with the sensor keys + queue depth. Two background tasks populate it: `power_poller` at 5s (P110 rate-limit) and `sensors_poller` at 2s (subprocess is cheap, temp changes matter during workloads).
- New `/live` endpoint bundles everything into one JSON fetch. `/power` kept for backwards compatibility — multiple pages still read it during active measurements.
- `_LIVE_JS` shared JS block polls `/live` every 3s and updates any DOM element carrying `data-live="<key>"`. Formatters live in a single `FMT` table: adding a new metric is one cache key + one FMT entry.
- Floating badge (bottom-right, every page) now shows `watts · CPU °C · GPU °C · queue depth`. Home page gets a 3-cell row under the big watts display: CPU Tctl / GPU junction / GPU PPT. Both use the same declarative `data-live` hooks — no bespoke JS per page.

#### "Report an issue" link
- `_FOOTER` gained a subtle "Spotted a bug or have a feature request? Open an issue on GitHub →" line — visible on every page that includes the footer.
- `/methodology` gained a visible "Source on GitHub" + "Report an issue" pair of links near the top of the content, in addition to the existing footer mention. GitHub repo is the canonical feedback channel.

#### Queue pause flag for external tools
A companion experiment at `/home/gos/claude-local-router/` runs Ollama-backed local models (`qwen2.5-coder:14b` now, was `gemma3:12b` originally) that compete with WattLab's SDXL-Turbo image jobs for the 12 GB VRAM. Per the spec at `OWL_INTEGRATION_PROPOSAL.md` in that repo: a coarse file-flag `/tmp/owl-paused` gates the queue worker between jobs without killing the service.

- `queue_worker` checks `Path(PAUSE_FLAG).exists()` before each `pop(0)`. In-flight jobs are untouched — only between-jobs transitions are gated. `queue_event` semantics unchanged so enqueues-during-pause wake the worker correctly when the flag clears.
- `/queue` JSON grew a `"paused"` key; `/queue-status` renders an amber banner when paused.
- Mitigation for the "forgotten flag → silent wedge" failure mode: `/live` also surfaces `paused`, and `_LIVE_JS`'s FMT table renders a `⏸ paused` pill in the floating badge on *every* page. So a user who runs a video job while paused sees the reason immediately without having to navigate to `/queue-status`.
- Router side already handles flag lifecycle (`touch` on launch, `trap EXIT rm -f` on exit).

#### WattLab owl logo
Commissioned a project mark (geometric owl, teal/green palette adjacent to the GoS `#00ff99` accent but not identical — the org mark and project mark coexist rather than compete).

- SVG at `wattlab_service/static/owl.svg` (2.4 KB).
- FastAPI `StaticFiles` mount at `/static`; gate middleware whitelists `/static/*` so the favicon loads on the `/gate` login page before the user has authenticated.
- Favicon swapped on all 10 pages from the Wix-hosted GoS PNG to the local owl SVG. Browser tabs now read as WattLab.
- `_BACK` upgraded from a bare "← Home" text link to `[owl] WattLab ← Home` — one change, propagates to every test / settings / methodology page.
- Home page gets a 72 px owl + wordmark block above the big live watts display.
- Footer `_LOGO` retains the GoS mark. Org credit stays on every page.

### Files touched
- `wattlab_service/power.py` — `read_sensors_dict()` helper
- `wattlab_service/llm.py` — Gemma 3 12B added to `MODELS`
- `wattlab_service/rag.py` — Gemma 3 12B added to `MODELS`; pre-existing Phi-4 entry kept
- `wattlab_service/image_gen.py` — `IMAGE_MODELS` registry; `model_key`, `steps_override`, `batch_override` params; `run_image_compare_models_measurement`; `_analyse_models`; VRAM cleanup in `finally`
- `wattlab_service/main.py` — `/image/start` accepts `model_key` + `compare_models` device; model picker + Compare Models button + `renderCompareModels()` on `/image`; progressive-disclosure collapsibles on `/image`, `/video`, `/llm`, `/rag`; methodology rewrite + home links; `/live` endpoint + `sensors_poller`; `_LIVE_JS` shared poller; badge + home page live hooks; `_ISSUES_LINK` in `_FOOTER`; methodology GitHub links; `PAUSE_FLAG` queue gate + banner + live pill; `StaticFiles` mount + owl favicon + `_BACK` wordmark + home hero
- `wattlab_service/static/owl.svg` — new project mark (2.4 KB)
- `wattlab_service/persist.py` — `compare_models` branch in `_summarise`
- `CLAUDE.md` — session 14 entry, deferred list tidied
- `JOURNAL.md` — this entry

### Open items coming out of this session
- Restart `wattlab` systemd service to pick up changes (sudo required — can't do from this agent)
- Once restarted, validate Compare Models end-to-end with a real measurement (can't test from the agent's process because the running uvicorn worker still holds leaked VRAM from pre-fix state)
- Watch whether the progressive-disclosure default is too hidden for visitors — if so, revisit with a visible density toggle or make the "ⓘ About this test" open by default on first visit via `localStorage`

---

## Session 13 — 2026-04-10

### What we did

**ABR benchmark · Compare all codecs · HTTPS · CSV/output fixes · Deferred roadmap tidy**

#### ABR rate control — methodology fix
All six video presets (H.264/H.265/AV1 × CPU/GPU) previously used different rate-control modes: CRF for software encoders, QP for hardware. These are not equivalent — CRF is adaptive (targets quality), QP is fixed (targets quantisation). Output file sizes differed, meaning CPU and GPU were not being given the same task.

Fixed by switching all presets to ABR (`-b:v Nk`) with a shared bitrate target per codec:
- H.264: 4000 kbps · H.265: 2000 kbps · AV1: 1500 kbps

Targets are stored in settings (`h264_bitrate_kbps`, `h265_bitrate_kbps`, `av1_bitrate_kbps`) and editable in the Settings page. CPU and GPU now produce near-identical output file sizes, displayed in results as confirmation.

PRESETS refactored: `cmd(i,o)` → `cmd_fn(i,o,bps)` + `detail_fn(bps)` + `bitrate_key`. Helper `_preset_bps(preset_key, s)` resolves the correct setting at runtime.

#### Compare all codecs
New `all_codecs` preset mode runs all six presets sequentially in three codec pairs (H.264 CPU→GPU, H.265 CPU→GPU, AV1 CPU→GPU) with cooldown between each pair.

Backend:
- `run_all_measurement()` in `video.py`: queues 3 pairs, collects per-codec results
- `analyse_all(codecs)`: cross-codec summary — most energy-efficient preset, fastest preset, per-codec winner
- `persist.py`: `_summarise` and `_video_rows` updated for `all_codecs` mode
- Stage map: 12-stage `_ALL_STAGES` + `_ALL_MAP` wired into STAGES/STAGE_MAP

UI result card (`renderAllCodecs()`):
- Matrix table: Codec × (CPU time / CPU energy / CPU out / GPU time / GPU energy / GPU out / Conf)
- Output size in separate per-side columns (not a combined column) — confirms bitrate parity
- Highlights: most efficient preset + fastest preset
- Collapsible per-codec detail cards with full thermal breakdown
- Footnote: "CPU out / GPU out should match — confirms same bitrate target"

#### HTTPS
DNS A record for `wattlab.greeningofstreaming.org → 176.148.88.254` restored (was wiped during Wix domain transfer). Certbot provisioned: `sudo certbot --nginx -d wattlab.greeningofstreaming.org` + `sudo systemctl restart nginx`. Service now live at https://wattlab.greeningofstreaming.org.

#### CSV and output size fixes
- `output_size_mb` added to video CSV (`_video_result_row` + fieldnames)
- Full thermals now in CSV: added `cpu_mean`, `gpu_mean`, `gpu_ppt_peak_w` alongside existing `cpu_base/peak`, `gpu_base/peak`, `gpu_ppt_mean_w`
- All-codecs matrix: output size split into separate "CPU out" / "GPU out" columns (previously a single combined column appearing after GPU energy)

#### Results — ABR all-codecs benchmark (3 runs, all 🟢)
Meridian 120s extract (4K → 1080p), ABR targets as above, full GPU pipeline:

| Codec | CPU | GPU | GPU energy saving | GPU speed gain |
|---|---|---|---|---|
| H.264 | 37.3s / 0.83 Wh | 17.5s / 0.37 Wh | ~55% | ~53% |
| H.265 | 70.3s / 1.58 Wh | 14.5s / 0.29 Wh | ~81% | ~79% |
| AV1   | 30.8s / 0.65 Wh | 14.5s / 0.30 Wh | ~55% | ~53% |

Notable observations:
- H.265 and AV1 GPU both encode in exactly 14.5s — VAAPI hardware clock is the ceiling on the GPU path
- AV1 CPU outperforms H.265 CPU on both speed and energy (SVT-AV1 multi-core optimisation)
- Most energy-efficient preset: AV1 GPU and H.265 GPU (~0.29 Wh) — gap within noise, more runs needed
- Results reproduced across 3 runs to within 1%

#### Deferred roadmap updates
- CPU temp under GPU load: **closed** — full pipeline (session 12) resolved this
- DNS + SSL: **closed** — done this session
- Added: Benchmark 2 (representative real-world CRF/QP presets), main.py refactor, Docker containerisation

#### Cron jobs
Two cron jobs added to `/etc/cron.d/`:

**wattlab-tmp-cleanup** — daily at 03:00, removes transcode output files older than 180 minutes from `/tmp/wattlab_uploads/`. The age filter ensures no in-flight or queued job input files are touched. (4.2 GB had accumulated at time of writing.)
```
0 3 * * * gos find /tmp/wattlab_uploads -type f -mmin +180 -delete
```

**wattlab-results-backup** — daily at 03:30, rsyncs `results/` to Nextcloud (`GoS1-backup/wattlab-results/`). Results are gitignored and were previously unbacked — this is the only copy outside GoS1. Logs to `/var/log/wattlab-backup.log`.
```
30 3 * * * gos /usr/bin/rclone sync /home/gos/wattlab/results/ nextcloud:GoS1-backup/wattlab-results/ --log-file=/var/log/wattlab-backup.log 2>&1
```

#### power.py — pluggable power measurement module
`get_power_watts()` was duplicated identically in all five files: `video.py`, `llm.py`, `image_gen.py`, `rag.py`, `main.py` (the comment in llm.py even said "same as video.py"). Extracted into a new `wattlab_service/power.py` module.

All five files now import `from power import get_power_watts`. The `tapo` and `dotenv_values` imports were removed from the four measurement modules entirely; `main.py` retains `dotenv_values` for the gate password.

`power.py` includes an explicit comment marking the swap point for future PDU/IPMI/alternative sources — the only file that needs changing for a DC deployment.

Net result: −89 lines across the codebase.

### Deferred (carried forward)
- Image page elapsed time in progress bar
- GPU image generation: first clean measurement run
- phi4: `ollama pull phi4`
- Confidence multiplier grounding with Tanya (5×/2× thresholds still by judgement)
- Transcoding profile documentation: GOP structure and profile level (bitrate now standardised)
- Benchmark 2: representative real-world presets (CRF/QP, codec-natural rate control)
- main.py refactor (routes/, Jinja templates, typed models, tests)
- Docker containerisation (two-stage plan; see CLAUDE.md)

---

## Session 12 — 2026-04-10

### What we did

**Preset overhaul · Full GPU pipeline · VAAPI fix · meridian_120s · Confidence hints · Guided tour RAG step · Queue badge · Bug fixes**

#### Video preset UI restructure
- Three codec rows (H.264 / H.265 / AV1), each with CPU / GPU / Both cards
- Preset details now collapsible via `<details class="pdesc">` — arrow toggles `▸/▾`, muted grey text
- `.pspec` class for codec spec line (was inline style); `DEFAULT` badge removed from H.264 Both
- Source picker: meridian_120s added between upload and full meridian

#### Full GPU pipeline — significant methodology change
Previously all GPU presets used a **partial pipeline**: ffmpeg CPU software-decoded the 4K input, then GPU-encoded the result. This meant the CPU was working hard during "GPU" jobs — and appeared hotter during GPU runs than CPU runs (counterintuitive but correct: software decode + PCIe DMA heats the IOD).

Now all three GPU codecs use a **full pipeline**:
```
-hwaccel vaapi -hwaccel_output_format vaapi -extra_hw_frames 32 -vaapi_device /dev/dri/renderD128
```
Frames stay GPU-resident from decode through scale through encode. This represents real live-encoding workflows (Harmonic, Ateme) and cuts CPU thermal load during GPU jobs.

**Impact on energy results** — dramatic:
| Mode | Duration | Energy | ΔW |
|---|---|---|---|
| H.264 CPU | 30.6s | 0.664 Wh 🟢 | 78.2W |
| H.264 GPU (full) | 17.6s | 0.376 Wh 🟢 | 76.8W |
| AV1 CPU | 28.2s | 0.586 Wh 🟢 | 74.8W |
| AV1 GPU (full) | 14.5s | 0.284 Wh 🟢 | 70.5W |

GPU is now faster **and** more energy efficient (H.264: 43% less energy; AV1: 51% less). Old partial-pipeline result (GPU 9.7% more energy) is superseded.

#### VAAPI surface pool fix
GPU encodes were failing with `Cannot allocate memory` at frame ~7178/7193 (99.8% through a 2-min 4K clip). Root cause: Mesa VA-API exhausts the DMA surface pool when `scale_vaapi` flushes at end-of-stream. The error is in teardown — the muxer had already written the full output file (confirmed: `Lsize=11188kB` in stderr before "Conversion failed!").

Two fixes:
1. `scale_vaapi=w=-2:h=1080:format=nv12` — explicit pixel format prevents EOS format-renegotiation failure
2. `out_size_mb` now checks `file.exists() and size > 0` instead of `success=True` — output is valid even when ffmpeg exits non-zero from the EOS teardown error

#### meridian_120s — 2-minute demo extract
Generated with `ffmpeg -y -ss 0 -i meridian_4k.mp4 -t 120 -c copy meridian_120s.mp4` (123MB). Full Meridian 4K gave only ~8 polls on short GPU jobs (🟡). The 120s extract gives 14–30 polls per job, all 🟢. Added to source picker and `sources.py`.

#### Confidence hint
`confidence()` now returns an optional `hint` string when signal is strong (ΔW > green threshold) but the task ran too briefly for enough polls (poll count < `conf_green_polls`). Example: *"Strong signal (49× noise floor) — task too short for 🟢. Use a longer clip or batch mode."* Rendered in single and both result cards beneath the flag.

#### Guided tour update
- 7 steps (was 5): RAG step inserted as step 4 before the Confidence step
- Page X/Y counter on all steps
- Previous buttons on steps 1–6
- Confidence step updated to variance-relative language with formula `noise = (variance%/100) × W_base`
- RAG result card shows model size, input/output tokens, retrieval_ms, mWh/token, tok/s, confidence per mode

#### Queue badge
Always-visible fixed bottom-right badge on all pages: polls `/power` + `/queue` every 5s, shows e.g. "52.3 W · ⏱ 2 jobs". Shows watts even when queue is empty.

#### Bug fixes
- `h265_both`/`av1_both`/`av1_gpu` missing from `STAGES`/`STAGE_MAP` → "Cannot read properties of undefined (reading 'starting')" crash on any new preset. Fixed by adding all new types to both tables.
- Variance calibration save-before-run: `runVarianceCalibration()` now calls `await saveSettings()` before queuing — previously the live value wasn't saved and the old settings.json value was used.
- Queue page resume link 404 for variance jobs: `resumeLink()` now skips variance-type jobs.
- Previous runs: codec displayed (e.g. "H.264 CPU vs H.264 GPU"); `persist.py` both-mode summary includes `cpu_preset`/`gpu_preset`.

### Technical notes
- Full GPU pipeline: add `-extra_hw_frames 32 -vaapi_device /dev/dri/renderD128` before `-i`; use `scale_vaapi=w=-2:h=1080:format=nv12` (not `scale_vaapi=-2:1080`)
- `variance_cooldown_s` serves double duty: CPU→GPU gap within a pair AND GPU→next pair gap. 10s is too short (CPU reaches 60°C during H264). Recommended: 60s minimum.
- Variance calibration uses full `meridian_4k.mp4` (not the 120s extract). With 10 runs + 60s cooldown: ~68 min total.
- VAAPI "Cannot allocate memory" is an EOS bug in Mesa VA-API, not actual VRAM exhaustion. Output file is valid.

### Deferred (carried forward)
- DNS + SSL (blocked on DNS rebuild)
- GPU image generation: first clean measurement run
- Image page elapsed time in progress bar
- phi4 (14B): `ollama pull phi4`
- Transcoding profile documentation (apples-to-apples bitrate/GOP/profile)
- Confidence multiplier grounding with Tanya

---

## Session 11 — 2026-04-09

### What we did

**Methodology page · Variance-based confidence · ffmpeg command preview + edit · Variance calibration tool · CLAUDE.md updates**

#### /methodology page
- New standalone page at `/methodology` with full measurement methodology documentation
- Covers: scope, measurement principle, protocol (8 steps), energy formulas, confidence framework, hardware disclosure, test type descriptions, known limitations, open questions
- Linked from home nav utility row (alongside Queue and Settings)
- Static HTML embedded in `main.py` as `_METHODOLOGY_HTML` string constant (no f-string — avoids CSS brace escaping)
- HTML written externally on MacBook, transferred via `scp -P 2222` and embedded

#### Variance-based confidence framework (major change)
**Old:** Fixed absolute ΔW thresholds — 🟢 >5W, 🟡 ≥2W. Problem: does not reflect actual measurement system noise; arbitrary and not grounded in empirical data.

**New:** Variance-relative thresholds anchored to empirically measured system noise.
- `noise_w = (variance_pct / 100) × w_base` — noise in watts, computed at measurement time from baseline power
- 🟢 ΔW > `variance_green_x × noise_w` AND polls ≥ `conf_green_polls`
- 🟡 ΔW ≥ `variance_yellow_x × noise_w` OR polls ≥ `conf_yellow_polls`
- 🔴 below yellow threshold
- Defaults: `variance_pct=2.0%`, `variance_green_x=5.0×`, `variance_yellow_x=2.0×`
- At 55W idle: noise_w ≈ 1.1W, green threshold ≈ 5.5W, yellow ≈ 2.2W — similar to old values but now scale correctly with idle power and adapt as variance is calibrated
- Variance captures total system noise: P110 quantisation + OS background processes + Wi-Fi polling jitter + thermal drift combined
- `confidence()` function updated in all four modules: `video.py`, `llm.py`, `image_gen.py`, `rag.py` — new signature: `confidence(delta_w, poll_count, w_base)`
- Old settings keys `conf_green_delta_w` and `conf_yellow_delta_w` removed from `settings.py`

#### New settings keys (settings.py + settings page)
Added to `DEFAULTS` and Settings page Confidence section:
- `variance_pct` — measured system variance as % of baseline; auto-updated by calibration
- `variance_green_x`, `variance_yellow_x` — multiplier thresholds (default 5×, 2×)

Three read-only calibration output fields shown in the Confidence thresholds section (above the editable `variance_pct`):
- `variance_idle_pct`, `variance_cpu_pct`, `variance_gpu_pct` — display "—" until first calibration run
- Visually distinct (dimmer label, no input control); `calib_field()` helper in settings_page()
- These are always read-only (even on LAN) — only updated by a calibration run

New Settings page section **Variance calibration** with:
- `variance_runs` slider (5–100, step 5) — number of H264-CPU + H265-GPU run pairs
- `variance_cooldown_s` slider (10–300, step 10) — cooldown between each pair
- `variance_cpu_cmd` textarea — editable ffmpeg command template (H.264 CPU, `{input}`/`{output}` substituted at runtime)
- `variance_gpu_cmd` textarea — editable ffmpeg command template (H.265 GPU)
- **▶ Run variance calibration** button (LAN only) — queues the calibration job
- Settings page gains `slider_field()` and `textarea_field()` helpers alongside existing `field()`

#### Variance calibration job (`/variance/run`)
- POST endpoint, LAN-only (403 on public)
- Queues a job labelled "Variance calibration — system offline"
- `run_variance_calibration()` in `video.py`: runs N × (H264-CPU baseline→encode + cooldown + H265-GPU baseline→encode) on Meridian
- **Three separate CVs** (revised after first run showed 24.62% — root cause: original code pooled H264 ΔW ~30W and H265 ΔW ~70W together, so CV was measuring workload difference not instrument noise):
  - `variance_idle_pct` — CV of raw P110 readings across all inline baseline polls
  - `variance_cpu_pct` — CV of ΔW across all H264-CPU encode runs
  - `variance_gpu_pct` — CV of ΔW across all H265-GPU encode runs
  - `variance_pct` — mean of the three (the operative noise estimate used for confidence thresholds)
- All four values written to `settings.json`; three read-only calibration fields shown in Settings page above the editable `variance_pct` field
- Stage labels visible in queue status: `run_1/N_cpu_encode`, `run_1/N_cooldown`, `run_1/N_gpu_encode`, etc.

#### ffmpeg command preview + edit on video page
- Before clicking Run, the ffmpeg command that would be executed is shown below the preset selector
- `/video/preview-cmd?preset=<key>` endpoint returns command template(s) with `{input}` and `{output}` placeholders
- On LAN: editable `<textarea>` (single preset: one box; "both" mode: CPU and GPU boxes stacked)
- On public: read-only `<pre>`-style code block
- Preset selection triggers `fetchCmdPreview()` JS; initial preview loads on page load
- Edited command sent as `custom_cmd` (single) or `custom_cmd_cpu`/`custom_cmd_gpu` (both) in form POST
- Server substitutes `{input}`/`{output}` at run time via `apply_custom_cmd()` in `video.py`
- `run_single()`, `run_video_measurement()`, `run_both_measurement()` all accept optional custom cmd params, threaded through `run_job()`, `/video/upload`, `/video/use-source`
- `IS_LAN` constant injected server-side into page JS so render is request-aware

#### CSV export updated
- `persist.py` `_video_result_row()` now includes `ffmpeg_cmd` column
- Fieldnames updated to match

#### /methodology confidence section updated
- Rewrote to explain variance-relative thresholds with formula block (`noise_w = variance_pct/100 × W_base`)
- Added explanation of why variance-relative is better than fixed thresholds
- Updated P110 noise floor callout to describe total system noise (not just P110 hardware)
- Open question updated: confidence multipliers (5×/2×) acknowledged as judgement-based pending statistical grounding session with Tanya

#### CLAUDE.md / SSH tunnel note
- Added "See also: GOS1_INFRA.md" reference line after Last updated
- Updated disk free: 221GB (April 2026)
- Clarified SSH tunnel: access via `http://localhost:8000/` not `http://192.168.1.62:8000/` — LAN IP is unreachable from outside the home network

### Technical notes
- `confidence()` now takes `w_base` as third argument in all modules — any future module must pass this
- `variance_pct` in settings.json is the live calibration value; change it manually or via calibration run
- `{input}` and `{output}` placeholders are substituted by `apply_custom_cmd()` (shlex-split after substitution)
- Calibration output files are written to `/tmp/wattlab_uploads/` and deleted after each pass

### Deferred (carried forward)
- DNS + SSL (blocked on DNS rebuild)
- GPU image generation: first clean measurement run
- Image page elapsed time in progress bar
- phi4 (14B): `ollama pull phi4`
- Transcoding profile documentation (apples-to-apples)
- CPU temp under GPU load: investigation
- Confidence multiplier grounding: working session with Tanya (thresholds now variance-relative but multipliers still by judgement)

---

## Session 10 — 2026-04-07

### What we did

**Video upload fix · Centralized power cache · FFmpeg audit · Home nav restructure · Meeting debrief**

#### Video upload 413 fix
- nginx `client_max_body_size` was defaulting to 1MB — any upload over that returned a 413 HTML error page, which the JS tried to parse as JSON → `SyntaxError: Unexpected token '<'`
- Added `client_max_body_size 2g` to the HTTP server block in `infra/wattlab.nginx.conf` (and to the commented HTTPS block for when SSL goes live)
- Root cause of "fix didn't work first time": `systemctl reload nginx` does a graceful restart — old workers (from Apr 05) kept running with the old 1MB config. Required `systemctl restart nginx` to kill all workers and spawn fresh ones with the new config.
- JS error message improved: now context-aware — only shows "file too large (nginx limit)" when it was actually an upload AND actually a 413. Other failures show `Failed (HTTP NNN)` without the misleading hint.

#### Centralized power cache
- Previously every browser session independently polled the P110 every 10s on page load and every 3–5s during measurement display. Multiple simultaneous users saw different wattage values and the P110 was hammered concurrently.
- Added `_power_cache: dict` global and `power_poller()` background coroutine (started at app startup alongside `queue_worker()`). Polls P110 every 5s, updates cache. On transient errors, stale value is kept.
- `/power` endpoint now returns from cache (dict read, no I/O). Home page reads from cache on page load — no direct P110 call on HTTP request path.
- Measurement workers (`video.py`, `llm.py`, etc.) still poll P110 directly at 1s intervals — measurement accuracy unchanged.
- Result: all browser sessions see the same value; P110 is polled at a steady 5s cadence regardless of how many users are connected.

#### FFmpeg command in result JSON and UI
- `transcode()` in `video.py` now returns `ffmpeg_cmd` (the full command string including `nice -n -5`) in the result dict.
- Surfaced in the result card (single and both modes) as a collapsible `▶ ffmpeg command` disclosure element under the Encode section.
- Addresses the Stan/meeting question: "what exactly is happening to the input file?" — the exact command is now visible and saved in the result JSON for auditability and reproducibility.
- Note: only new runs (post this session) will have the field. Old saved results show nothing for the ffmpeg section.

#### GPU PPT explanatory note
- GPU self-reported power (PPT from `amdgpu PPT power1_average`) was already captured and shown in result cards, but the discrepancy with P110 ΔW was confusing (meeting: "GPU reported 44W but P110 delta showed 85W — why?").
- Added a one-line note beneath the PPT row in single and both-mode result cards: *"GPU self-reported power (PPT). P110 ΔW above is the full system delta — includes CPU, RAM, drives."*

#### Home nav restructure
- Video promoted to its own full-width row beneath Guided Tour.
- Image / LLM / RAG grouped under a dim "AI WORKLOADS" label in a secondary row.
- Queue / Settings demoted to a utility row (smallest, dimmest).
- Reflects meeting consensus: GoS's core story is video transcoding; AI workloads are secondary.

#### DNS situation
- DNS table was wiped during Wix ownership transfer from Dom to Ben.
- `wattlab.greeningofstreaming.org` A record needs to be re-added once DNS is rebuilt.
- In the meantime, `http://176.148.88.254` (public IP, no DNS needed) is working and was used for the dry run.
- SSL cert deferred until DNS is restored.

#### Meeting debrief (WattLab Monthly, Apr 07)
Attendees: Ben, Stan (IABM), Barbara Lange, Carl (Akamai). Key feedback:

**Methodology gaps raised by Stan:**
- FFmpeg pipeline: does it decode to baseband? What intermediate format? → Fixed (ffmpeg command now logged).
- Apples-to-apples: all presets must use comparable profiles (same bitrate target, GOP, profile level). Currently undocumented beyond the command string. To follow up with Tanya/Simon.

**GPU PPT vs P110 delta (~18min):**
- GPU self-reported ~44W, P110 system delta ~85W during GPU encode. Explained: CPU also active during GPU encode (loading/sending data). Added explanatory note to UI.

**CPU heats more under GPU load than CPU load:**
- Unexplained observation from the demo. Hypothesis: CPU handles memory transfers for GPU. To investigate.

**Audio measurement question:**
- Can we measure the energy impact of audio volume? Ben tested informally (TV plug, full vs min volume) — delta within P110 noise floor (~1W on a 50–200W device). Stan will contact an audio expert (AES Canada chapter).

**Image gen and LLM scope:**
- Stan and Ben agreed these are off-brand as primary features. Moved to "AI workloads" secondary section in nav.

**Public access:**
- Upload worked for all testers once the 413 fix was deployed.
- Barbara confirmed settings page was read-only (by design).
- Queue worked correctly under concurrent load.

**Confidence flags:**
- Ben wants a working session with Tanya to make the thresholds more statistically rigorous.

**Deferred / action items from meeting:**
- CPU temp under GPU load: investigate and document
- Transcoding profile documentation (apples-to-apples): work with Simon/Tanya
- Audio measurement: Stan to contact audio expert
- DNS rebuild: whenever Dom/Ben can access DNS panel
- SSL cert: after DNS
- Akamai meeting rescheduled: Apr 23, 3pm UK, Simon to be invited

### Deferred (carried forward)
- DNS + SSL (blocked on DNS rebuild)
- GPU image generation: first clean measurement run
- Image page elapsed time in progress bar
- phi4 (14B): `ollama pull phi4` — for RAG quality comparison
- Confidence threshold refinement: working session with Tanya
- Transcoding profile documentation (apples-to-apples across H.264/H.265/AV1)
- CPU temp under GPU load: investigation

---

## Session 9 — 2026-04-06

### What we did

**RAG energy test · Compare 3 modes · Shared progress component · Home nav restructure**

#### RAG energy test page (`/rag`)
New test type measuring the energy cost of Retrieval-Augmented Generation vs plain LLM inference:
- Three modes: **baseline** (cold LLM, no retrieval), **rag** (top_k=3 chunks), **rag_large** (top_k=8)
- Backend: ChromaDB + `all-MiniLM-L6-v2` sentence-transformer embeddings (singletons, loaded once)
- Corpus: PDF files from `settings.rag_corpus_path`, chunked at ~512 tokens with 64-token overlap
- Index build: `/rag/build-index` endpoint + status polling; index persists in `.chroma/` across restarts
- Same P110 measurement protocol as other tests (baseline → task → ΔW/ΔE/mWh/token)
- New module `rag.py`, new `persist.py` branches for RAG result summary and CSV export
- Supports TinyLlama, Mistral 7B, Phi-4 model selection

#### RAG — Compare 3 modes
**▶▶ Compare 3 modes** button runs baseline → rag → rag_large sequentially in one job:
- Single baseline measurement shared across all three modes (unload + re-baseline between each)
- Live progress: shows current mode, stage (baseline/inference), live wall power, elapsed time
- Result: three side-by-side cards (or stacked on mobile) with energy, tokens/sec, confidence badge per mode
- Answer text collapsible per card (toggle button); answers saved in result JSON for quality comparison
- Backend: `run_rag_compare_job()` coroutine, `/rag/run-compare` endpoint

#### Shared `_PROGRESS_JS` component
Progress display factorized out of all 4 test pages into a single `_PROGRESS_JS` plain-string constant:
- `wlRenderProgress({header, stagesHtml, watts, elapsed, extraHtml})` — renders 2.5rem live wall power, stage list, elapsed timer into `#status` div
- `wlStageList(stages, currentStage)` — renders coloured pip list
- `wlRenderQueued(position)` — renders queue position banner
- `wlFormatElapsed(ms)` — formats elapsed time as `Ns` or `Nm Ns`
- All 4 pages (video, LLM, image, RAG) inject `{_PROGRESS_JS}` and call shared functions

#### Home nav restructure
New three-tier layout (mobile-friendly, `flex-wrap` on all rows):
1. **◆ Guided Tour** — solid green filled button, most prominent
2. **Primary row** — Video · Image · LLM (outlined green, ordered by visual weight)
3. **Secondary row** — RAG · Queue · Settings (muted grey, smaller text)

#### Bug fixes
- **RAG JS syntax error** (page unresponsive after first implementation): `\'` in Python triple-double-quoted f-strings outputs `'` not `\'`, causing `getElementById('' + answerId + '')` — adjacent JS string literals → SyntaxError. Fixed by using `data-id` attribute pattern (`data-id="..." onclick="toggleAns(this.dataset.id)"`) — no nested quote escaping needed.
- **RAG Internal Server Error** (prior session): `{{}}` double-brace escaping used in plain Python functions (not f-strings) → `unhashable type: dict`. Fixed by removing double-braces from all endpoint functions.

### Deferred
- DNS: table lost during Wix ownership transfer (Dom → Ben). A record `wattlab.greeningofstreaming.org → 176.148.88.254` needs to be re-added once DNS is rebuilt. SSL cert follows after that.
- GPU image generation: first clean measurement run still needed
- Image page elapsed time in progress bar
- phi4 (14B): `ollama pull phi4` (9.1GB) — for RAG quality comparison

---

## Session 8 — 2026-04-05

### What we did

**Peer review response · README · Confidence flags · Guided Tour polish · Password gate · Queue resume**

#### External code audit (another AI)
Received a structured review of the codebase. Agreed findings acted on this session:
- Missing README (fixed)
- Confidence flag description too buried (fixed — popover + Guided Tour step)
- Guided Tour felt like a repackaged lab screen (fixed — three-band structure)
- `confidence()` flag values flagged as potentially empty — confirmed clean (🟢/🟡/🔴 correct in all three modules), no fix needed

Deferred (valid but not pre-demo priority): main.py refactor into routes/, Jinja templates, typed models, tests.

#### README added
- What WattLab measures and explicitly doesn't (network, CDN, training cost)
- Hardware spec, key findings table, access instructions (public vs SSH tunnel)
- Links to WATTLAB_SPEC.md and JOURNAL.md
- How to run locally

#### Guided Tour: three-band structure per step
Each measurement step (Video, LLM, Image) restructured into three explicit bands:
1. **What this shows** — the insight, 1–2 sentences
2. **What we're doing** — concrete action + methodology in collapsible drawer
3. **Result** — action button / result card + limitation note (scope + what the figure does not mean)
Added `.band`, `.band-label`, `.limitation` CSS classes. Fixed step 3 which used undefined `.step-intro` / `.method-box` classes.

#### Guided Tour: confidence flag step
New step 4 "How We Flag Confidence" — explains P110 noise floor (~1W), the three-level system with thresholds, and why those specific values (5:1 SNR reasoning, batch mode as correct response to yellow/red). Findings promoted to step 5. Nav updated to 6 dots.

#### Confidence flag popover on all result pages
`_CONF_HELP_WIDGET` — a plain-string constant (not f-string) injected into video, LLM, image, and tour pages. Clicking any 🟢 🟡 🔴 badge opens a fixed popover with all three thresholds and ΔW definition. Event delegation so it works on dynamically rendered badges. `.conf-badge` gets `cursor:pointer` via injected `<style>` tag.

#### Password gate
Cookie-based gate for private preview period:
- First visit → password form ("WattLab · Private preview")
- Correct password → 30-day httponly cookie, full access
- Password stored in `.env` as `WATTLAB_GATE_PASSWORD` (gitignored)
- FastAPI middleware, exempts `/gate` paths only

#### `_is_local()` security fix
Previous check (`"greeningofstreaming.org" not in host`) allowed direct public IP access (e.g. phone over 5G to raw IP:8000) — treated as local. Replaced with IP-based check: uses `X-Real-IP` (set by nginx) when present, otherwise `request.client.host`. Returns True only if loopback or RFC-1918 private address.

#### Navigation cleanup
- `_BACK` renamed: "← Dashboard" → "← Home" across all pages
- "← Lab mode" button removed from Guided Tour welcome step (redundant with ← Home)
- "Lab mode" link removed from Guided Tour Findings step (same reason)

#### Queue resume
- `enqueue()` now stores `type` and `label` in `jobs` dict (previously lost when job was popped from `pending_queue` to start running)
- `/queue` endpoint exposes `type` and `label` on running job
- Queue page: "↩ Resume" link on each card → `/video?job=id`, `/llm?job=id`, `/image?job=id`
- Video / LLM / Image pages: check `?job=` param on load, call existing poll function — handles in-progress and already-done cases without extra logic

### Tags
- `v1.0.0` — first public-ready commit (Session 7 + security fix)
- `v1.1.0` — README + Guided Tour three-band + confidence popover (Session 8)

### Deferred
- DNS A record + SSL cert (after Easter, pending Wix admin access)
- GPU image generation measurement figures (next clean run)
- Image page elapsed time in progress bar
- RAG experiment — prototype on MacBook first (corpus there, faster iteration), then port to GoS1 as new test type if energy trade-off is measurable

---

## Session 7 — 2026-04-05

### What we did

**Demo renamed to Guided Tour · Settings read-only on public internet · nginx rate limiting · Queue cap**

#### Demo mode → Guided Tour
- Nav link on home page: "◆ Demo mode" → "◆ Guided Tour"
- Page `<title>` updated: "WattLab — Guided Tour · Greening of Streaming"
- Welcome step button changed: "Start Tour →"
- URL unchanged: `/demo`

#### Settings: graceful read-only from public internet
Previous approach was a hard 403. Replaced with a friendlier read-only view:
- Public visitors (Host header contains `greeningofstreaming.org`) see all values as plain-text spans, no inputs, no Save button
- Banner: "🔒 Read-only — settings can only be modified from the lab network or SSH tunnel."
- Subtitle: "WattLab · GoS1 · Read-only" (vs "WattLab · GoS1 · Lab mode" on LAN/SSH tunnel)
- POST `/settings` still returns 403 if not local — belt and suspenders
- `_is_local(request)` remains the single gating function for both GET and POST

#### nginx: removed /settings 403, added rate limiting
- Removed `location /settings { return 403; }` — no longer needed since FastAPI degrades gracefully
- Added `limit_req_zone` (4 job submissions/min per IP, burst 2) and `limit_conn_zone` (3 simultaneous per IP)
- New rate-limited location block for job submission endpoints: `/video/use-source`, `/video/upload`, `/llm/run`, `/llm/run-all`, `/image/start`
- HTTPS server block moved to commented-out section (uncomment after cert is issued)

#### Queue: hard cap added
- `MAX_QUEUE_DEPTH = 8` (total queued + running)
- `enqueue()` now returns `None` when full instead of always returning a position
- All 4 submit endpoints check for `None` and return HTTP 429 "Queue full — try again later."

#### UI navigation cleanup
- Added `_BACK` global: "← Dashboard" link used on all sub-pages
- Added `_FOOTER` global: GoS logo in a footer `<footer>` element, consistent across pages
- Home: removed fixed-position logo div, logo now in footer
- Video + LLM pages: replaced inline `{_LOGO}` with `{_BACK}` at top, old "← Back to power monitor" anchor removed, `{_FOOTER}` added at bottom

### Deferred (unchanged from Session 6)
- DNS A record + SSL cert (after Easter, pending Wix admin access)
- GPU image generation measurement figures (next clean run)
- Image page elapsed time in progress bar

---

## Session 6 — 2026-04-05

### What we did

**Phase 6 progress + GPU image gen confirmed + bug fixes**

#### Phase 6 — Public access progress
- nginx setup script run on GoS1 (Step 1 complete)
- BouyguesBox port forwarding configured: TCP 80 + 443 → 192.168.1.62 (named `wattlab-http` / `wattlab-https`)
  - Pre-existing rules `apache` (port 80) and `ssh` (port 22) deleted first — both pointed to 192.168.1.1 and were left over from the owner's son's personal projects. Port 80 conflict would have silently broken nginx.
- DNS A record blocked until after Easter — requires Wix domain admin access not yet granted
- Confirmed: GoS1 auto-starts correctly after reboot (wattlab + ollama both `systemctl enabled`)
- Confirmed: uploaded test videos are deleted after transcoding (`delete_after=True` in `run_job`)

#### GPU image generation — first confirmed run
- SD-Turbo float16, ROCm, batch of 5 images, 20 steps, 512×512 — works correctly
- Image displays in result, prompt variation working
- (Measurement figures to be added once a clean run is recorded)

#### Image Previous Runs — bug fixes
- **Missing thumbnails for "both" mode:** `_summarise` was looking for `generation.b64_png` at top level; for "both" mode results it's nested under `cpu.generation` / `gpu.generation`. Fixed.
- **No CPU/GPU label:** mode not included in summary or template. Fixed — now shows CPU / GPU / CPU+GPU.
- **"both" mode showed only one row:** template rendered a single entry regardless of mode. Fixed — "both" runs now render two rows (CPU and GPU) each with their own thumbnail, confidence badge, Wh, and time.
- **Ordering:** `list_results` was sorting by filename (date + UUID), so runs within the same day appeared in arbitrary order. Fixed — now sorts by `saved_at` ISO timestamp, newest first. Date display also upgraded to `YYYY-MM-DD HH:MM` for disambiguation.

### Deferred
- DNS A record + SSL cert (after Easter, pending Wix admin access)
- GPU image generation measurement figures (next clean run)
- Image page elapsed time in progress bar (still outstanding from session 5)

---

*(Sessions 1–5, April 2026 — bootstrap era; entries below predate the current format.)*

## Session 5 — 2026-04-05

### What we built

**Deferred items catchup + Phase 6 prep**

#### LLM — prompt textarea visibility
- Label changed from dim `#555` to `#aaa` with `✎ Edit prompt` text
- Textarea border brightened to `#444` with green left accent (`#00ff9966`)
- Reset button relabelled "Reset to default"

#### LLM — batch result card response text (bug fix)
- `renderLLMBatch` was missing the generated text from the last run
- Added "Response preview (last run)" section: `r.runs[r.runs.length-1].inference.response`

#### LLM — Run All Tasks (T1+T2+T3) feature
- New "Run All Tasks (T1+T2+T3)" button alongside the existing Run Measurement button
- New backend: `run_llm_all_job()` runs T1 → T2 → T3 sequentially, each with cold baseline
- Supports CPU / GPU / Both ⚡ (via the existing device selector)
  - **Both mode** (`mode: "all_both"`): runs all 3 tasks on CPU, then all 3 on GPU
  - Produces a comparison table: T1/T2/T3 rows × CPU tok/s / GPU tok/s / CPU mWh/tok / GPU mWh/tok, green = winner
- New `/llm/run-all` endpoint (POST, accepts `model_key`, `warm`, `device`)
- New JS: `runAllTasks()`, `pollLLMAll()`, `renderLLMAll()`, `renderLLMAllBoth()`
- Progress display shows T1/T2/T3 pips + current device badge + live wall power

#### Previous runs null record fix (bug fix)
- `persist.py _summarise()` only handled `mode: "single"` — returned null for batch/both/all/all_both
- Fixed to handle all LLM modes:
  - `single`: top-level energy/inference (unchanged)
  - `batch`: uses aggregate mean stats
  - `both`: uses GPU side energy/inference
  - `all`: uses T3 as representative, shows "T1+T2+T3" as task label
  - `all_both`: uses GPU T3, shows "T1+T2+T3 · CPU vs GPU"
- `_llm_rows()` also fixed for all modes — CSV export now correct for batch/both/all/all_both

#### Live wall power — generalised across all test pages
- Video page (`pollJob` + `renderProgress`): now fetches `/power` in parallel with job status, displays live W during measurement
- LLM page (`pollLLM`, `pollLLMAll`, `renderProgress`): same
- Image page already had this; video and LLM now match

#### Tapo P110 SessionTimeout fix
- Root cause: browser-side `/power` polling (new, every 3s) ran concurrently with internal 1s measurement polling, overwhelming the P110's single-session limit
- Fix: 3-attempt retry with 1s sleep in all four `get_power_watts()` implementations (`main.py`, `video.py`, `llm.py`, `image_gen.py`)
- Transient session conflicts recover silently within one retry

#### Phase 6 — Public access (GoS1 side complete, pending router + DNS)

**Architecture:**
```
Internet → BouyguesBox (forward 80+443) → nginx on GoS1
  :80  → ACME challenge passthrough + proxy (or redirect to HTTPS once cert live)
  :443 → reverse proxy to WattLab :8000, /settings blocked 403
Nextcloud snap → moved to :8080 (off :80)
```

**GoS1 public IP:** `176.148.88.254`

**Files written:**
- `infra/wattlab.nginx.conf` — nginx vhost config (HTTP + HTTPS blocks, /settings 403, proxy_pass to :8000, ACME challenge dir)
- `infra/setup-nginx.sh` — one-shot setup script (run as sudo)

**`/settings` double-blocked:**
- nginx: `location /settings { return 403; }`
- FastAPI: `_is_local(request)` checks `Host` header — returns 403 if `greeningofstreaming.org` in host, on both GET and POST

**What's already done (GoS1):**
- nginx config written and ready at `infra/wattlab.nginx.conf`
- Setup script ready at `infra/setup-nginx.sh`
- FastAPI `/settings` block implemented and deployed

### Deferred (noted for next session)
- **Image page progress bar:** missing elapsed time (video + LLM pages both show it). Standardise elapsed time + live wall power across all three test pages.
- **GPU image generation:** code is complete and should work (SD-Turbo float16 needs ~2-3 GB VRAM, well within the 11.1 GB available). Just needs a first run to confirm and record the measurement.

---

## Session 4 — 2026-04-04

### What we built

**LLM CPU vs GPU comparison**
- Added Backend selector to `/llm` page: CPU / GPU / Both ⚡
- GPU mode: standard Ollama inference (ROCm, default)
- CPU mode: `"options": {"num_gpu": 0}` forces Ollama to use CPU only
- Both mode: CPU pass → cooldown → re-baseline → GPU pass → side-by-side result card with winner highlighting
- New `run_llm_both_measurement()` in `llm.py`, new `_analyse_llm()` for comparison
- New `renderLLMBoth()` JS function: speed winner (green) vs loser (grey), energy winner highlighted

**Image generation CPU vs GPU**
- `HSA_OVERRIDE_GFX_VERSION=11.0.0` set at module level and in systemd service — required for RX 7800 XT (gfx1101) with PyTorch ROCm 2.5.1
- GPU strategy: batch of 5 images × 20 steps (~10s total) → `wh_per_image = total_energy / 5`
  (GPU generates in ~2s/image — too fast for reliable P110 measurement at 1s polling interval)
- CPU strategy unchanged: 8 steps, ~12s per image, single image
- Added `device` param to `generate_image()`, `run_image_measurement()`, new `run_image_both_measurement()`
- Added `_analyse_image()` for comparison: energy_winner, speed_winner, speed/energy diff %
- Added CPU / GPU / Both radio selector to `/image` page
- New `renderImageBoth()` JS: side-by-side CPU/GPU cards, winner badge, batch note
- Both pages now fully symmetric: same UI pattern as LLM page

### Key GPU Image Finding (first run — to be measured)
- GPU JIT compilation: ~74s one-time cost on first PyTorch ROCm call (kernels cached to disk)
- Expected GPU: ~2s/image × 5 batch = ~10s measurement window, ≥10 P110 polls
- Expected CPU: ~12s/image, ≥10 P110 polls

### Architecture notes
- `IMAGE_STEPS_CPU = 8`, `IMAGE_STEPS_GPU = 20`, `GPU_BATCH_SIZE = 5`
- `_run_single_image()`: shared internal helper for both-mode passes
- `_calc_energy()`: shared energy calculation, handles batch normalisation
- Energy measurement uses `gen_s` (generation only), not `total_s` (excludes model load)

---

## Session 3 — 2026-04-04

### What we built (Phase 4 + Phase 5)

**Phase 4 — Demo Mode**
- `/demo` guided 4-step journey (Video → LLM → Summary → Findings)
- GoS visual identity on every page: logo, `#00ff99` accent, monospace data / system-ui narrative
- Inline methodology explanations, anti-slideware proof points
- "Previous run" instant-result option in demo flow

**Phase 5 — Image Generation**
- Upgraded Ollama 0.18.3 → 0.20.2 (native image generation support)
- Pulled `x/z-image-turbo` (12GB, 10.3B FP8) and `x/flux2-klein` (5.7GB, MLX)
- **VRAM constraint:** z-image-turbo requires 11.9 GiB; RX 7800 XT has 12 GiB total but only 11.1 GiB available after driver + Ollama overhead — 800 MB short. flux2-klein uses MLX runner which requires CUDA (AMD incompatible). Both blocked on GPU.
- **Solution:** CPU diffusion via Python `diffusers` + `stabilityai/sd-turbo`, 8 inference steps, 512×512
- **Measurement result:** 0.2063 Wh/image, ~12s generation, 🟢 Repeatable
- New module `image_gen.py` with same measurement protocol as video/LLM (P110 polling, baseline, focus mode, thermals, confidence)
- New `/image` page: prompt input, random colour/mood modifier appended per run (anti-slideware proof), live wall power during generation, result card with generated image + energy metrics
- Results saved to `results/image/` with base64 PNG embedded in JSON
- Previous runs browser with 80×80 thumbnail previews
- New module `persist.py` for flat-file result persistence (all types), `settings.py` for configurable parameters

### Key Image Generation Finding

**SD-Turbo CPU, 8 steps, 512×512 (first run) — 🟢 Repeatable**

| Metric | Value |
|---|---|
| Energy / image | 0.2063 Wh |
| Generation time | 12.15s |
| Delta above idle | ~30W |
| Backend | CPU (Ryzen 9 7900, 24 cores) |
| Model | stabilityai/sd-turbo |

GPU image generation deferred: z-image-turbo needs 11.9 GiB VRAM, card has 12 GiB but only 11.1 GiB available after overhead. GPU measurement possible if overhead reduced or larger card added.

### Bugs fixed this session
- `/power` endpoint had `{{...}}` double-brace escaping (leftover from f-string edit) → `TypeError: unhashable type: 'dict'` crashing JS poll loop
- Image page used `r["date"]` (doesn't exist) and `r["data"]` (doesn't exist) from `list_results` summaries — fixed to use `r["saved_at"]` and direct summary fields; added `"image"` branch to `persist._summarise`
- Image JS polled `/job/{id}` — endpoint doesn't exist; correct path is `/image/job/{id}` — added endpoint and fixed JS

### Also built this session
- **FIFO queue system:** central `pending_queue` + `queue_event` + `queue_worker` coroutine (startup task). All three test endpoints enqueue instead of returning 409. Job status includes `queue_position`. Each test page shows "⏱ Queued — position N" while waiting, auto-transitions when slot opens. `/queue-status` HTML page (auto-refresh 4s) shows running job + queue depth. `/queue` JSON endpoint for programmatic access.
- **Fixes to prior gaps:** image_gen.py now calls `focus_mode_enter/exit`; image results export (JSON + CSV) enabled; image step added to `/demo` as step 3 (before summary); CLAUDE.md roadmap checkboxes corrected; `queue-status` link added to home nav.

### Deferred (carried forward)
- GPU image generation (needs VRAM headroom or larger card)
- LLM result text display in result card (last batch iteration)
- All-tasks batch launch (T1+T2+T3 in one click)
- Prompt textarea visibility improvement
- UI polish / visual design pass (flagged for next session)

---

## Session 2 — 2026-04-04

### What we built (Phases 1–3)
- **Phase 1 — Research Integrity:** JSON result persistence (`results/video/`, `results/llm/`), CSV + JSON export endpoints, previous-runs browser (last 10 per type, inline on each page)
- **Phase 2 — Measurement Quality:** LLM streaming inference (token-by-token via Ollama stream API), warm/cold toggle, editable prompts with reset-to-default, batch mode (1×/3×/5×, 10s rest, aggregate + stddev), H.265 CPU/GPU + AV1 CPU video presets
- **Phase 3 — Settings:** `/settings` page with 8 configurable parameters (baseline polls, video cooldown, LLM rest, unload settle, confidence thresholds), `settings.json` persistence

### Bug noted mid-session
LLM response was truncated at 500 chars (leftover from original non-streaming `run_inference`). Fixed: `run_inference_streaming` now stores full response; response box height raised to 500px with `white-space:pre-wrap`.

### Deferred change requests
**Prompt visibility:** The editable prompt textarea was not obvious to first-time users — it only appeared after the service was restarted, and its styling (dark background, subtle border) may make it easy to miss. Consider making the prompt section more prominent or adding a visual label like "Edit prompt ↓" to draw attention to it.

**LLM result text display:** The generated text from inference should be displayed in the result — at minimum the last iteration in batch mode. Currently the response preview may not be prominent enough or may not always render.

**All-tasks batch launch:** Add a single "Run all tasks" button that fires T1 + T2 + T3 sequentially for the selected model, producing a combined report. Useful for a complete per-model benchmark in one click.

---

## Product Planning — 2026-04-04

### Two-mode architecture agreed

**Lab mode** (Simon, Tania, Dom, internal): full controls, editable prompts, export, settings, SSH tunnel access.

**Demo mode** (partners, CTOs, public): guided journey, curated, no settings exposed, proof-of-reality mechanisms, GoS visual identity.

### Data persistence decision
**Flat JSON files, not SQLite.** Each completed job writes `results/{type}/{date}_{job_id}.json`. Survives restarts, directly loadable by pandas/clean_measures.py, no schema migrations, stays agile. SQLite deferred indefinitely.

### Prioritised roadmap

**Phase 1 — Research Integrity** (next session)
- JSON result persistence
- CSV + JSON export
- Previous results browser (last 10 runs, expandable inline)

**Phase 2 — Measurement Quality**
- LLM batched mode: load once, rest, run N times, measure aggregate
- LLM warm vs cold toggle
- LLM editable prompts + streaming word-by-word output display
- Video H.265/HEVC + AV1 presets

**Phase 3 — Settings & Lab Config**
- `/settings` page (lab only)
- Configurable: baseline duration, cooldown, repeats, rest time, confidence thresholds
- `settings.json` persistence

**Phase 4 — Demo Mode**
- `/demo` guided journey with Next flow
- GoS visual identity (logo on every page, link to greeningofstreaming.org)
- Inline methodology explanations, "more info" expanders
- "See previous run" instant result option
- Anti-slideware proof points: streaming LLM output, varied image prompts per run

**Phase 5 — Image Generation**
- Diffusion model via Ollama or ComfyUI
- Energy per image metric
- Live display as generated, varied prompt per run

**Phase 6 — Public Access**
- nginx + Let's Encrypt
- `wattlab.greeningofstreaming.org` domain (preferred)
- `/settings` blocked from public URL

### Open questions
- Confirm domain with GoS — `wattlab.greeningofstreaming.org` or `gos1.duckdns.org`?
- Which image generation runtime to install?
- Should video crossover point (GPU vs CPU efficiency) be a published GoS finding?
- Results directory — add to `.gitignore` or commit selected runs to repo as reference data?

---

## Session 1 — 2026-04-03/04

### What we built
1. **Live power display** — P110 via local API, auto-refresh 10s, systemd service
2. **Video transcode test** — CPU vs GPU H.264 comparison, P110 + thermals, side-by-side report, server-reported progress stages, Meridian 4K pre-loaded
3. **LLM inference test** — Ollama, TinyLlama + Mistral 7B, fixed prompts, cold inference protocol, energy per token
4. **Focus mode** — 8 background timers suppressed during measurement
5. **Infrastructure** — Git/GitHub, SSH keys, Nighthawk AP mode, Claude Code on GoS1

### Key Video Findings

**H.264 1080p from 4K source (Meridian, 4 runs) — 🟢 Repeatable**

| | CPU (libx264) | GPU (h264_vaapi) |
|---|---|---|
| Duration (mean) | 174.3s 🏁 | 114.0s |
| Energy (mean) | 4.06 Wh ✓ | 4.42 Wh |
| Peak delta | ~85W | ~139W |
| Variance | 7.3% (3.4% ex. outlier) | 0.2% |

GPU 34.5% faster, 9.7% more energy. CPU wins on energy efficiency.

Crossover exists: GPU wins on short clips (<10s transcode), CPU wins on long. The crossover point is between 10-60s transcode duration for this workload.

**Methodology note:** CPU baseline drifts 51-58W between runs (OS thermal state). GPU baseline stable (~54W). Focus mode and 60s cooldown reduce but don't eliminate CPU variance.

### Key LLM Findings

**Cold inference (model unloaded before each run)**

| Model | Task | Tok/s | mWh/token | Confidence |
|---|---|---|---|---|
| Mistral 7B | T2 Medium | 59.3 | 1.028 | 🟢 |
| Mistral 7B | T3 Long | 47.6 | 0.943 | 🟢 |
| TinyLlama | T3 Long | 209.3 | 0.061 | 🟡 |

TinyLlama ~15x more energy efficient per token than Mistral. TinyLlama too fast (1-4s) for reliable P110 measurement — batching needed.

**Warm vs cold:** A contaminated warm run showed 161W delta vs 219W cold — 26% lower. Cold measurement (first-request cost) is more honest for real-world scenarios.

---

## What's Running (end of Session 1)

| Service | URL | Notes |
|---|---|---|
| Live power + nav | `http://192.168.1.62:8000` | LAN / SSH tunnel |
| Video test | `http://192.168.1.62:8000/video` | CPU/GPU/Both + Meridian 4K |
| LLM test | `http://192.168.1.62:8000/llm` | TinyLlama + Mistral, 3 tasks |
| Ollama | `localhost:11434` | systemd, ROCm GPU |
| Remote tunnel | `ssh -p 2222 -L 8000:localhost:8000 user@gos1.duckdns.org` | Simon, Tania, Dom |
