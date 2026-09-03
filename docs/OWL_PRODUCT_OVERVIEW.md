# OWL — the Online WattLab

*A plain-language introduction. Boxes marked **🔧 For the technically curious** go deeper — skip them freely; you'll lose nothing of the story.*

---

## What is OWL?

OWL is a **live, public energy laboratory for streaming technology**, run by [Greening of Streaming](https://greeningofstreaming.org) (GoS). It answers a deceptively simple question:

> **How much electricity does it actually take to encode, enhance, and deliver video — and to run the AI tools creeping into that workflow?**

The industry is full of estimates, extrapolations, and marketing claims about streaming's energy footprint. OWL takes a different approach: **it measures**. A real server, plugged into a real power meter, runs real workloads — and publishes what the meter says, live, at [wattlab.greeningofstreaming.org](https://wattlab.greeningofstreaming.org).

If it can't be measured, OWL doesn't assert it.

---

## Why does it exist?

Greening of Streaming is a non-profit engineering community that believes the streaming industry's energy conversation should be grounded in evidence, not headlines. Big public numbers about streaming's footprint are often built from stacked assumptions; equally, "green" product claims often arrive without measurements attached.

OWL exists to put **a public, repeatable, inspectable measurement bench** in the middle of that conversation. Anyone — a CTO, a journalist, a policymaker, a sceptic — can visit the site, watch an experiment run, and see the energy numbers come straight off the meter.

Three principles shape everything on the site:

1. **Measure, don't model.** Every headline number traces back to a stored, timestamped measurement on named hardware.
2. **Say what's in scope.** OWL measures the *device* doing the work. Networks, data centres, and your TV at home are explicitly out of scope (server-side scope; since 2026-07 the separate decode rig measures client devices — see /decode) — and every result says so.
3. **Signal uncertainty honestly.** Every result carries a traffic-light confidence rating (🟢🟡🔴). When a measurement is too noisy to trust, OWL says so instead of publishing it anyway.

---

## What can you do on OWL?

### 🎬 Take the guided tour
A seven-stop walkthrough — from "what is this place?" through a live video encode, the energy budget of a stream, AI video enhancement with real before/after footage, how confidence ratings work, and finally the findings library. Visitors who want more can take an optional three-step AI detour (language models, image generation, retrieval-augmented search).

### ⚡ Watch video encoding cost real watts
The video page runs actual encodes on the lab machine and shows the power draw as it happens — comparing codecs, software vs. hardware encoding, and quality-vs-energy trade-offs.

### 💡 Explore the energy budget of a stream
How much energy does one minute of streamed video cost at the encoding stage, at different quality rungs? OWL's budget page is built from a full measured calibration sweep, not industry rules of thumb.

### ✨ See AI video enhancement measured
OWL runs professional AI upscaling/enhancement workloads and measures what that quality improvement costs in energy — including genuine before/after video comparisons.

### 🤖 Put AI itself on the meter
Local language models, image generators, and retrieval-augmented (RAG) pipelines run on the same bench, so their energy cost per task can be compared on equal terms — always tethered to streaming-relevant questions.

### 📚 Read the findings
The findings library is OWL's public output: short, plainly-written results, each citing the actual stored measurement behind it and carrying its own confidence rating. Highlights so far include:

- **Hardware video encoding used 2.0–4.4× (published finding abr-all-codecs-meridian-120s) less energy per minute than software encoding** on the lab machine — and the win comes from *speed*, not lower power draw.
- **AI upscaling has a "sweet spot"**: on degraded sources there's a point where extra enhancement effort stops buying visible quality but keeps costing energy.
- **"GPU encoding gives worse quality" is only true sometimes** — the gap appears on simple, low-bitrate content and vanishes (or reverses) on complex footage.

> **🔧 For the technically curious — the measurement protocol.**
> The bench is a single well-characterised workstation (AMD Ryzen 9 7900, NVIDIA RTX 5080) metered at the wall by smart plugs polled every second — two of them, interleaved, for finer effective resolution. Before each task the system quiets background services, takes a 5-poll idle baseline (live setting), runs the workload under a lock so nothing overlaps, then reports the *delta* above baseline as the task's energy (ΔE = ΔW × time). Video quality is scored with VMAF so energy can be traded off against measured quality, not eyeballed impressions. Every result JSON stores the raw power samples, so anyone can re-check the statistics.

> **🔧 For the technically curious — the confidence model.**
> The 🟢🟡🔴 rating isn't editorial judgement. It's a statistical test: given the noise in the baseline and task power samples, how confident are we that the measured power increase is real? 🟢 means ≥95% confidence with enough samples; 🟡 is suggestive; 🔴 means "we ran it, but don't quote this number."

---

## Who is it for?

- **Streaming CTOs and engineers** who need defensible numbers for infrastructure and codec decisions.
- **Operators and vendors** who want their efficiency claims tested — or challenged — on neutral ground.
- **Policymakers and analysts** who need a credible, independent reference point amid competing industry figures.
- **Anyone curious** about what their video habit actually costs at the machine level — the guided tour assumes no technical background.

OWL is also GoS's front door: it's the working demonstration of what the organisation does, and a natural entry point for companies considering membership.

---

## What OWL is *not*

- **Not a carbon calculator.** OWL reports energy (watts and watt-hours) — the thing it can actually stand behind. Carbon intensity varies by grid and by minute; where carbon context appears it's clearly labelled as indicative reference, never a headline.
- **Not a whole-internet model.** OWL measures one layer — the device doing the work — precisely and honestly, rather than estimating the entire chain loosely.
- **Not a vendor showcase.** Results are published whether they flatter a technology or not; several measured configurations have been publicly *rejected* because they cost more energy for less quality.

---

## The one-sentence version

> **OWL is a public laboratory where streaming and AI workloads run on a real, metered machine — so the industry's energy debate can start from measurements instead of claims.**

---

*Access tiers: everything above is publicly viewable. GoS members can additionally run their own jobs on the bench; lab operators have full control. OWL is operated by Greening of Streaming, a French non-profit (association loi 1901).*
