# OWL — 15-Minute Demo Guide

**Framing (say once, up front):** *"If it can't be measured, it shouldn't be asserted."*

Audience lens: CTOs / operators / infra players. OWL = a **bench** that measures real device-layer energy of streaming & AI workloads.

---

## Flow & timing

| # | Segment | Time | Where to click |
|---|---|---|---|
| 1 | Open & framing | 1m | Home / `/demo` |
| 2 | The measurement spine | 2m | any result + confidence popover |
| 3 | Video codec compare | 3m | `/video` → Compare codecs |
| 4 | AI tethered to streaming | 3m | `/llm/compare` + `/image/compare` |
| 5 | Findings = body of evidence | 2m | `/findings` |
| 6 | Partner integration (Pixop) | 2m | `/enhance-run` |
| 7 | Field ↔ Bench (REM flash) | 1m | REM UI screenshot |
| 8 | Close | 1m | — |

---

## 1 · Open (1m)
- GoS = neutral, technically credible French NGO
- OWL measures **real watts**, not models / estimates
- Scope honesty: **device layer only** — network / CDN / datacenter explicitly excluded

## 2 · Measurement spine (2m)
- Real hardware: smart plug (full mW precision) + CPU/GPU thermal sensors
- Protocol: baseline → locked task → poll → ΔW, ΔE
- **Traffic Light Confidence** — every claim 🟢/🟡/🔴: *"can this be told apart from idle?"*
- Hook: *"the number comes with its own uncertainty"*

## 3 · Video codec compare (3m) — **the meat**
- Same clip, multiple codecs / encoders head-to-head
- Energy **and** quality (VMAF) side by side
- ⭐ Key finding: **AV1 hardware vs software at same bitrate** — energy↔quality tradeoff is real and measurable
- Hook: *"hardware encode saves energy — but does it cost quality? Now we can answer."*

## 4 · AI tethered to streaming (3m)
- Why AI here: it's the new load on the same infrastructure
- `/llm/compare` — tiny → 20B models, energy per token, CPU vs GPU
- `/image/compare` — N models side by side, first-run cost
- Hook: *"same rigor, applied to the AI workloads now sharing the pipe"*

## 5 · Findings catalog (2m)
- `/findings` — not one-off demos; a **growing evidence base**
- Each finding cites a real stored measurement on disk
- Hook: *"reproducible, sourced, no hand-waving"*

## 6 · Partner integration (2m) — *don't name the vendor*
- `/enhance-run` — a **commercial enhancement / transcode partner** wrapped in OWL's measurement harness
- Their product runs; OWL measures its energy honestly, same protocol
- Hook: *"vendors can prove efficiency claims on neutral ground"*

## 7 · Field ↔ Bench (1m) — **REM flash**
- *REM context (one line):* GoS's sibling project — real power meters on real sites reporting continuously, where OWL's bench findings get checked against the wild.
- Show REM UI screenshot
- OWL = **controlled bench**; REM = **fleet in the field** (real meters on real buildings)
- Hook: *"bench tells you why, field tells you what's actually happening — two halves of one story"*

## 8 · Close (1m)
- OWL turns "streaming is wasteful" from assertion → **measurement**
- Open, reproducible, vendor-neutral
- Ask / CTA: members, partners, contributors

---

## Safety rails
- **Don't** say the partner's name (use "enhancement partner")
- **Don't** over-claim n — several findings are n=1, flagged as such; let the rigor be the story
- If asked "how accurate?" → point to the confidence flag, not a hand-wave
- Keep carbon talk minimal — **energy (W/Wh) is what GoS stands behind**; CO₂e is reference-only

---

## Pre-demo checklist
- [ ] `/enhance-run` actually enabled (`ENHANCE_RUN` flag + Lab tier) and rendering — no mid-demo 404
- [ ] Service restarted if showing `/image` or `/llm` compare progress strips live (S39 cooldown-label fix is stale until restart)
- [ ] REM screenshot ready to flash
- [ ] On LAN / Lab tier so all pages are reachable
