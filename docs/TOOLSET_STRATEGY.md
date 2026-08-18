# The GoS Measurement Toolset: Strategic Appraisal & Future Scenarios

**Internal working document — fully candid. Not for distribution.**
**Date:** 2026-07-29 · **Author:** prepared for Ben Schwarz, feeding the SMPTE 2026 paper
*"A Dual-Track Measurement Framework for Streaming Energy" (Schwarz et al.; companion: Pouli et al. #4941)*
**Sources:** owl repo @ `e87fdf5`, rem repo @ `f625f85`, LAN-reader (LEM) @ v0.2.0, the five GoS publications, the accepted SMPTE abstract, `rem/docs/audit-2026-07/` (REM_AUDIT, OWL_AUDIT, CONVERGENCE), and the July 2026 client-decode reports (`owl/docs/pi_decode_energy_2026-07.md`, `owl/docs/stb_decode_energy_2026-07.md`).

---

## 1. Grounding: why these tools exist at all

GoS's raison d'être is a refusal: the refusal to let streaming's environmental story be told
by models, averages, and marketing. Its publications repeat one commitment — **measured,
verifiable, boundary-explicit data over estimation** — and codify it in the Language Lab's
🟢 measured / 🟡 indicative / 🔴 speculative framework and the LESS Accord's challenge to
quality-obsessed defaults. Every public GoS claim is supposed to survive the question
*"what exactly did you measure, and how would I reproduce it?"*

The toolset is that commitment made executable:

| Tool | Identity | One-line role |
|---|---|---|
| **OWL** (Online WattLab) | Single instrumented server (GoS1), FastAPI, ~33.5k LOC, 1027 tests (2026-08-19) | The calibrated bench: marginal-over-baseline energy of encode/LLM/RAG/image workloads, per-run confidence flags, result envelopes |
| **REM** (Remote Energy Measurement) | Collector + TimescaleDB + admin UI, live on Linode, ~34-plug fleet | The field network: distributed real-world power over time, experiments, hackathons |
| **LEM** (Local Energy Measurement) | CLI + GUI, Tapo/Shelly plugins, CI-published .app/.exe | The hand-held probe: local-API, milliwatt, 1–2 s readings anywhere a volunteer stands |

Current integration topology — two thin, one-way bridges:

```
OWL ──(/prepare-rem: marker-wrapped, target-VMAF clips)──▶ REM ◀──(field-sync: join code,
                                                                     batch upload, collector
                                                                     pauses cloud polling)── LEM
```

The SMPTE abstract's thesis maps cleanly onto this: **REM identifies *where* effects exist;
OWL quantifies *why*.** Note what the abstract does *not* mention: LEM. That is a framing
decision to make deliberately (see §4, S2): LEM is best positioned not as a third track but as
**the instrument that upgrades REM's track** — local-API milliwatt sampling at 1–2 s where
REM's cloud polling manages ~30 s at ~1 W class resolution. The July decode work (§3) is the
proof that this framing is right: it used LEM's principle, OWL's method, on REM's territory.

## 2. Honest appraisal: is the 3-tool set fit for purpose?

**Short answer: the *method* is fit for purpose and genuinely differentiated; the *platform*
is not yet a platform.** Three tools, two thin bridges, three copies of the same meter-polling
problem, and one of the three (REM) currently fails GoS's own anti-greenwashing standard if we
applied it to ourselves.

### 2.1 What is genuinely strong

- **OWL's measurement discipline is the crown jewel.** Per-run idle baselines, focus mode,
  cooldown guards (CR-070), dual-meter CI (CR-065), the traffic-light confidence model, a
  documented result-envelope contract, and a findings catalog with measured-vs-conjecture
  separation. 1027 tests (2026-08-19). This is the credibility engine — the thing SMPTE reviewers will
  actually be buying.
- **REM's federation contract is the right shape.** The field-ingest API (bearer token, batch
  upload, idempotent batches, 90 s sessions, collector hand-off that pauses cloud polling per
  alias) is a genuinely good design for volunteer-operated fleets, and it's live in production.
- **LEM's engineering hygiene is the best of the three** — CI on every push, tagged releases,
  cross-platform binaries, offline-first journaled sync — and its pluggable `BaseDevice`
  abstraction is the natural seed for a shared meter-driver layer.
- **The hackathon lineage is real methodological capital**: marker/energy-signature sync
  proven (Feb 2024), a repeatable 6-minute signature sequence, and the Nov 2025 campaign's
  quantitative results (resolution = 55% of server-side encoding variance; device-side power
  dominated by luminance r²≈0.47, not bitrate/resolution). Thirteen researchers, multi-site.
  No other industry body has this.

### 2.2 What is weak — stated bluntly

1. **REM would fail a GoS audit of a member's claims.** Its own July 2026 audit
   (`rem/docs/audit-2026-07/REM_AUDIT.md`): TP-Link OAuth client secret, API key, and a
   `.env.bak` with a live refresh token committed to history; admin UI on host port 7001 and
   TimescaleDB on 0.0.0.0:5432 around the proxy; Traefik password in git; **zero automated
   tests** while the README documents a phantom pytest suite; ~60 of ~77 docs frozen snapshots;
   90-day *destructive* retention with no archive — we delete our own research data on a timer.
   The abstract says "both platforms are openly available for replication." For REM today that
   sentence is aspiration, not fact — and publishing it unqualified is exactly the kind of
   claim GoS exists to challenge.
2. **OWL's rigour stops at the measurement boundary.** No CI (pytest isn't even in
   requirements); ~5–7% of tests only pass on GoS1; flat-file persistence at its acknowledged
   ceiling (CR-031); VERSION frozen 111+ commits back; and the convergence audit scored a
   **critical** reflected-XSS in the magic-link pages plus a spoofable `X-Real-IP` Lab-tier
   bypass while uvicorn binds 0.0.0.0:8000. The bench is trustworthy; the service around it is
   a lab prototype.
3. **The "toolset" is three implementations of one problem.** OWL's `power.py`, REM's
   1,466-LOC collector, and LEM's `devices/` all speak Tapo independently, with different
   credential conventions (`TAPO_*` vs `TPLINK_*`), different sampling assumptions, and no
   shared result schema. Every meter-firmware quirk (fw 1.4.0 local-API lockout, 1.5 s refresh)
   must be discovered three times.
4. **The bridges are one-way and unclosed.** OWL→REM ships clips out; nothing brings REM's
   device measurements *back* into OWL for encode-vs-decode synthesis — today that loop closes
   through a human with a spreadsheet. LEM→REM uploads rows; REM cannot push experiment
   orchestration down to LEM beyond a cadence hint.
5. **Scale claims have outrun scale reality.** The REM overview paper promises "hundreds of
   measurement points, expandable to thousands." Reality: ~34 plugs on one account, 4 TV models
   in the Nov 2025 testbed, multi-LEM ingest confirmed working but never load-tested, and the
   known hard blockers from 2024 — universal stream access across device diversity, volunteer
   logistics — still open.
6. **No CDN, no ISP, no display nuance.** The Nov 2025 coverage table's red cells are
   unchanged: CDN, ISP, codec-at-scale, dynamic HDR. The toolset measures the two ends of the
   chain well and the middle not at all.

### 2.3 The one-sentence verdict

GoS has built a **methodology** the industry lacks and wrapped it in **infrastructure it
couldn't yet recommend to a member** — the strategy question is how to close that gap while
spending the credibility the methodology has earned.

## 3. The July 2026 client-decode work: the loop closes for the first time

The Google TV Streamer + Raspberry Pi 5 + Pi 400 campaign (canonical:
`owl/docs/pi_decode_energy_2026-07.md`, `owl/docs/stb_decode_energy_2026-07.md`; envelopes
`results/decode/2026-07-29_dec0de{04,05,06}.json`; harnesses on GoS1 under
`/srv/data/owl/decode-bench/` and `/srv/data/owl/stb-decode-2026-07/`) is strategically the
most important thing the toolset has produced this year, for three reasons.

**It is the first actual close of the OWL↔REM loop.** OWL's bench method (settle → baseline →
sampled window → `confidence.py`, all rows 🟢) applied to *client devices* — REM's territory —
using LEM's local-API principle (P110 mW path at 1.5 s) as the instrument. One protocol,
three devices, ADB-orchestrated playback. This is the "connect OWL and REM into a more
complete end-to-end measurement system" slide made real, before any UI exists.

**The findings are paper-grade and non-obvious:**
- A hardware decoder is worth **3.6× while playing, 4.1× saturated** on the same board, same
  file (Pi 400 hw +0.35 W vs sw +1.25 W realtime).
- On fixed-function silicon codec choice moves **≤0.08 W (~4%)**; on software-decoding clients
  it moves decode power by **up to ~60%** — the codec-energy debate is really a silicon debate.
- **Delivery mode outweighs codec by 5–14×** (sustained streaming +0.42 W over burst-buffered;
  network delivery alone decomposed to +0.21 W) — an *end-to-end* finding no single-layer rig
  could produce.
- **Measurement regime changes codec ranking** (AV1 cheapest saturated, H.264 cheapest paced) —
  a methodology finding that belongs in the SMPTE paper's "lessons" section almost verbatim.

**It exposes exactly what "productizing" requires.** The work lives as harnesses and reports,
not as a tool: `bench.py` has no baseline-floor guard (the hot-baseline failure mode OWL
already closed on the bench with CR-070); the STB used device-total W because the box's
baseline drifts 0.9–1.4 W; the ad-hoc `:8123` file server's Range-request defect corrupted
HTTP arms; nothing is surfaced in OWL's UI or findings pages; two superseded partial write-ups
sit next to the raw data. The gap between "we did it" and "a member could do it" is the
S3/S4 work program in miniature.

## 4. Scenarios

Each scenario: what it is → what it unlocks → effort/risk → what it lends the paper.
They are cumulative, not alternatives; S5 is the governing decision.

### S1 — Consolidate the spine (shared envelope + shared meter layer)
Adopt one **GoS result envelope** (OWL's `docs/result_envelope.md` as the base: energy block,
confidence block, provenance stamps) readable by all three tools, and one **meter-driver
library** grown from LEM's `BaseDevice` plugins (Tapo local, Shelly, fake; later PDU/IPMI —
the Nov 2025 server side already used SNMP PDUs ad hoc). REM ingests OWL envelopes as
first-class experiment artifacts. CONVERGENCE.md Phases 1–3 (shared CLAUDE.md skeleton, CI
pattern, `/health` contract) are the substrate for this.
**Unlocks:** every future meter quirk solved once; cross-tool results become composable data
instead of PDFs. **Effort:** M (weeks, mostly extraction not invention). **Risk:** low —
it's refactoring toward contracts that already exist in one tool each.
**Paper:** lets "a common framework" mean a *data* framework, not just a narrative one.

### S2 — REM–LEM deepening: LEM as REM's universal field probe
Resolve the abstract's silent question — where does LEM sit? — by making it explicit: **LEM is
how REM escapes the cloud API.** The cloud path's ~30 s / rate-limited cadence is the abstract's
own named REM limitation; LEM's local path is the fix (1–2 s, mW, any meter type, offline-safe).
Work items: the planned multi-LEM non-regression/stress test (CR-004 is confirmed working but
untested at scale — validate the 90 s session and batch ingest under load *before* SMPTE
claims); REM→LEM downlink so an experiment can push sequence timing/markers to field probes,
not just cadence; hackathon kits (a Pi + LEM + join code) as the volunteer on-ramp, directly
attacking the 2024 "volunteer logistics" blocker.
**Unlocks:** the promised "hundreds of points" becomes credible via federation rather than one
cloud account; citizen-science scaling for hackathons. **Effort:** M. **Risk:** low-medium
(the untested-at-scale part is the risk — which is why it's the work).
**Paper:** honest resolution of the rate-limit limitation, with LEM one paragraph as REM's
instrument-grade mode.

### S3 — OWL–REM closing the loop (results flow back)
The reverse bridge: REM device/decode measurements ingested into OWL so encode energy and
decode energy of the *same clip* render in one view. The decode envelopes (`dec0de{04,05,06}`)
already sit in OWL's results tree — the mash-up is unbuilt UI plus an ingest contract, not new
science. Includes CR-008 step 4 (OWL as encoder inside a REM-orchestrated end-to-end test) and
promoting the decode bench to a first-class OWL module (baseline-floor guard in `bench.py`,
device registry, findings publication of the two drafts).
**Unlocks:** the encode-once/decode-per-viewer economics made visible — the STB report's
encode:decode ratios (GPU encode = 1.9–4.0× one device decode; CPU = 6.2–22.7×) become a live,
citable tool output. **Effort:** M–L. **Risk:** medium (touches OWL's persistence ceiling;
do after or with CR-031's storage decision).
**Paper:** §5's dual-track synthesis gets a concrete mechanism, not just a claim.

### S4 — The end-to-end reference streaming service (minus CDN and ISP)
Formalize what the July campaign improvised: **OWL encodes and originates → an instrumented
delivery path → OWL-orchestrated devices (ADB/SSH: STB, Pis, next a TV panel) → REM/LEM meters
every hop → one experiment identity end to end.** The hackathons proved the multi-site,
multi-layer version at 1 W/20 s resolution; the decode bench proved the single-site version at
mW/1.5 s; S4 is their product. Near-term additions that need no partners: a *proper*
instrumented origin (the `:8123` Range defect showed the delivery layer must be real —
nginx/Caddy with byte-range correctness and TCP counters), a home-gateway meter (Nov 2025
already touched this), the player-with-display arm, and GStreamer 1.24 hw-HEVC on the Pis.
Then the honest externalization: CDN and ISP cells stay red until a member CDN node or ISP
CPE sits inside the loop — this is a concrete, costed membership ask ("bring a cache node,
get your layer measured"), which is a better recruitment pitch than any deck.
**Unlocks:** GoS operates the only measurable reference streaming chain in the industry;
LESS Accord profiles become empirically testable end to end. **Effort:** L (staged; the
minus-CDN/ISP core is weeks given S1–S3, the partner cells are quarters).
**Risk:** medium — scope creep is the killer; the mitigations are the experiment-identity
contract and refusing to claim layers we don't meter.
**Paper:** the future-work section stops being hand-waving — it's "here is the loop closed
once, at bench grade; here is the chain we are assembling," with the decode findings as
evidence.

### S5 — Merge vs federate (the governing decision)
**Recommendation: federate hard; do not merge.** The convergence audit is right that the
products differ (fleet telemetry vs bench measurement vs hand probe) and that the storage
engines should not converge. What must be *shared* is: the result envelope, the meter layer,
the CR/journal/testing process, the CI shape, the security floor, and a name — market the
federation as one thing (working title: **the GoS Measurement Suite**: OWL the bench, REM the
field, LEM the probe) so members and SMPTE readers see a platform, while engineering keeps
three small, honest codebases. A merged codebase would weld OWL's host-coupled hardware layer
to REM's cloud fleet for cosmetic unity — all cost, no measurement gain.
**Effort:** S (it's a decision plus naming/docs). **Risk:** the real risk is *not* deciding —
drift continues and every scenario above gets built bespoke.

## 5. Sequencing against the paper deadline (~4–6 weeks)

**Feed the paper (do in the next 2–3 weeks):**
1. **Publish the two decode findings** (`hw-decoder-cuts-client-energy-4x`,
   `codec-decode-energy-depends-on-silicon-and-regime`) through OWL's findings process after
   lab review — the paper can then cite stable URLs, not drafts.
2. **Make "openly available for replication" true enough to print.** Minimum bar = REM
   Phase 0 from CONVERGENCE.md: rotate the TP-Link creds and Traefik password, close 7001/5432,
   plus OWL's XSS/X-Real-IP fixes. Cheap (days), and it converts the abstract's boldest claim
   from exposure into fact. If not done, soften the sentence in the paper — GoS rules apply to
   GoS.
3. **Write §5 of the paper around the decode campaign** as the first dual-track closure:
   regime-changes-ranking as a methodology lesson, delivery-mode-beats-codec as the
   dual-track-only finding, encode:decode ratios as the synthesis. Keep the Pi conjecture list
   out of the claims (the reports' own measured/conjecture discipline shows how).
4. **One paragraph positioning LEM** as REM's instrument-grade field mode (resolves its absence
   from the abstract without re-scoping the paper).

**Don't feed the paper (12-month roadmap, in order):** S5 decision → S1 spine → S2 stress test
+ downlink → S3 loop closure + decode-bench productization → S4 staged chain, with the CDN/ISP
membership ask launched once the minus-CDN/ISP core runs unattended.

**Standing precondition for all public claims:** every number GoS publishes about its own
tools must carry the same 🟢🟡🔴 honesty it demands of members — including "multi-LEM tested
to N probes" (🔴 until the stress test runs) and "hundreds of measurement points" (🟡 at best
today).

---

## Appendix: claim-to-source map (spot-check trail)

| Claim in this doc | Source |
|---|---|
| REM committed secrets, exposed ports, zero tests, 90-day destructive retention | `rem/docs/audit-2026-07/REM_AUDIT.md`; CONVERGENCE.md §2.3, §2.4, §2.6, Phase 0 |
| OWL critical XSS, X-Real-IP bypass, no CI, GoS1-bound tests, VERSION drift | CONVERGENCE.md header note, §2.6, §2.9; `owl/CHANGE_REQUESTS.md` CR-031/CR-068 |
| `/prepare-rem` shipped, one-way, undocumented arc | CONVERGENCE.md §4; `owl/wattlab_service/{rem_prep,routes_rem}.py` |
| LEM field-sync contract, join codes, journaled upload | `LAN-reader/src/lem/{rem_client,uploader}.py`; `rem/admin/field_api.py`; `rem/docs/FIELD_API.md` |
| Decode findings (3.6–4.1×, ≤0.08 W vs ~60%, 5–14×, regime ranking, +0.21 W network) | `owl/docs/pi_decode_energy_2026-07.md`; `owl/docs/stb_decode_energy_2026-07.md` |
| Resolution 55% of server variance; luminance r²≈0.47; 4 TV models | Hackathon Data Analysis (Feb 2026 PDF), results & coverage table |
| Marker sync proven; universal stream access & volunteer logistics open | Feb 2024 Hackathon Review PDF |
| "Hundreds of points, expandable to thousands" | REM overview PDF |
| Abstract thesis, rate-limit & baseline-noise limitations, "openly available" sentence | 2026 SMPTE Abstract (Drive doc `127ZTC8J…`) |
| Multi-LEM untested at scale; CR-004 confirmed 2026-07-24 | `rem/CHANGE_REQUESTS.md`; REM_AUDIT |

> **Status note (2026-08-19):** the three future-work items named above — a baseline-floor guard in `bench.py`, a device registry, and publication of the two draft decode findings — have all shipped (`decode_idle_guard` protocol v3, `rig.RIG`, `ff7fd9f` de-DRAFT). This document is a decision record; the live state is CLAUDE.md + JOURNAL.
