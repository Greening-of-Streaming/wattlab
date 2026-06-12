# OWL Anonymous Landing — UX Audit & Options for the Marketing Lab

**Date:** 2026-06-12 · **Author:** Ben (audit run by Claude) · **For:** Veronika / Marketing Lab
**Context:** We will point to OWL from the GoS website and talk about it on LinkedIn. Expected
anonymous traffic: (a) GoS members who haven't signed in, (b) people interested in sustainable
streaming + AI who do **not** know what GoS or OWL are. This audits what they actually get today
and lays out options for the lab to choose between.

**What anonymous visitors see today:** `https://wattlab.greeningofstreaming.org/` redirects to
`/demo`, a 7-step Guided Tour: Welcome → Video → LLM → Image → RAG → Confidence → Findings,
ending in a tier-comparison table with a "Join GoS" call to action.

---

## 1. What already works (keep)

- **Desktop first screen is strong.** Live wall-power readout ("79.0 W") as the hero is proof of
  life, not a brochure — exactly the right credibility signal for this audience. Value
  proposition is stated in two sentences. Single clear "Start Tour →" call to action.
- **Honesty is structural, on-brand.** The anonymous banner says up front "same numbers as
  members see". The tour explicitly downgrades the AI steps to "entering beta / exploratory"
  and invites people to stop if they only wanted the streaming story. Scope statements
  everywhere. No other site in this space does this.
- **The funnel exists.** Sign-in is visible top-right and in the banner; the tour ends on a
  capability matrix that doubles as the membership pitch, with "Join GoS" and "Sign in" buttons.
  Unlogged members have an obvious path back in.
- **Findings step is the best content on the page** — three real, confidence-flagged, citable
  results with dates. This is the most shareable asset we have.

## 2. Critical problems (launch-blocking for a LinkedIn campaign)

### 2.1 Mobile rendering is broken — and LinkedIn traffic is mostly mobile
The tour page (and most OWL pages) has **no `<meta name="viewport">` tag**. Phones therefore
render the page at desktop width scaled down: on an iPhone the text is roughly one-third size
and the visitor must pinch-zoom to read anything. The majority of LinkedIn referral clicks come
from the mobile app, so most campaign traffic would hit this first. (See
`owl_anon_mobile_fold.png`.) Three pages (findings, benchmark, methodology) already add the tag
ad hoc; the fix is one line in the shared page chrome so every page gets it.

### 2.2 Zero social-share metadata — LinkedIn posts will look broken
The page has **no meta tags at all**: no description, no OpenGraph, no Twitter card, no share
image. A LinkedIn post linking to OWL today renders as a bare link with the raw page title and
no image — it will look untrustworthy next to any normal post. Needed before the first post:
- `og:title`, `og:description`, `og:image` (PNG, ~1200×627 — the SVG owl won't be picked up),
  plus `<meta name="description">` for search.
- **Marketing input needed:** the one-sentence description and the share-card design (this is
  the single image most people will ever see of OWL).

### 2.3 The tour asserts things that are no longer true
For an organisation whose line is *"if it can't be measured, it shouldn't be asserted"*, the
tour currently misdescribes its own measurements. A technically sharp visitor — exactly our
audience — can catch every one of these:
- **LLM step says "Mistral 7B … via Ollama ROCm"; the button actually runs `qwen3:4b` on an
  NVIDIA/CUDA box.** Mistral 7B is no longer installed; ROCm is the old AMD stack (GPU swapped
  2026-05-29). A visitor who clicks "Run" is promised one model and shown a result for another.
- **The video step quotes the old confidence rule** ("ΔW > 5× noise and ≥ 9 polls") while step
  6 of the same tour teaches the current confidence-interval method. The page contradicts itself.
- "Full pipeline results pending first run" — stale; full-pipeline results have existed for weeks.
- The video step hardcodes "P110 sampled every second" while other steps correctly use the
  serve-time meter/cadence tokens (dual-meter copy).

These are engineering fixes, not marketing decisions, and should ship regardless of which
scenario the lab picks (see §4, Tier 0).

## 3. Significant gaps (fix-shape depends on marketing's choice)

### 3.1 Nobody explains who GoS is
The page assumes the visitor knows Greening of Streaming. The tagline is "Greening of Streaming
· Live energy measurement · GoS1" — "GoS1" is internal jargon, and "Greening of Streaming" is
never expanded anywhere on the page (NGO? vendor? lobby?). A visitor deciding whether to trust
these numbers needs one sentence of identity, e.g. *"Greening of Streaming is a member-funded
non-profit of streaming-industry engineers measuring the real energy cost of streaming."*
Trust in the source is the product here.

### 3.2 The best content is at step 7 of 7
A LinkedIn visitor gives us 30–90 seconds. The citable findings — the strongest hook — sit at
the end of a linear tour, behind an explicit "stop here if you only wanted the streaming story"
off-ramp at step 2. Almost nobody arriving from social will reach them. Conversely the tour is
*right* for the patient/professional visitor, so the answer is probably routing, not rewriting
(see scenarios).

### 3.3 Conversion goal is undefined
The page's only conversion is "Join GoS" at the tour's end. For cold LinkedIn traffic that's a
big ask as the *only* rung. Question for the lab: what do we actually want from an interested
stranger — membership lead? follow/newsletter? citation/bookmark of a finding? The hero CTA and
the share-card copy should be designed backwards from that answer.

### 3.4 Launch-readiness under a traffic spike (engineering, flagged here for completeness)
Anonymous visitors can trigger real measurements (3–10 min each, globally queued — by design,
it's the proof of liveness). A successful post means dozens of simultaneous "Run" clicks: most
will queue behind each other, and we have already seen nginx's per-IP connection cap produce a
429 on the homepage under *internal* load (S41). Before the first post we should decide queue
messaging for "you are #14 in line", and sanity-check the nginx caps against social-spike
patterns. Not a marketing decision, but it gates the campaign date.

## 4. Plan

### Tier 0 — ship regardless of scenario (engineering, ~1 session)
1. Viewport meta in the shared page chrome (fixes mobile everywhere at once).
2. Fix stale tour copy: model name routed through the live model registry, GPU wording through
   the backend helpers, one confidence story, remove "pending first run".
3. OG/description/share-image *plumbing* (the tags), with placeholder copy pending §Tier 1.
4. Spike sanity-check: nginx per-IP caps, queue-position wording for anonymous runners.

### Tier 1 — needs Marketing Lab input (the scenarios)

These are **two separate decisions**: A vs B are alternatives for the home page itself;
C is independent of that choice — it's about how LinkedIn posts enter the site, and it
combines with either A or B.

**Decision 1 — the home page (A vs B, or counter-propose):**

**Scenario A — "Polished tour" (minimum, ~0.5 session after Tier 0)**
Keep the tour as the anonymous landing. Add a one-line GoS identity sentence under the hero,
expand OWL once ("Online WattLab"), and let marketing supply the share-card image + description.
- *Pro:* cheapest; the tour is genuinely good for the patient visitor.
- *Con:* social traffic still enters a 7-step linear path with the findings last; weakest fit
  for the LinkedIn audience.

**Scenario B — "Findings-first landing" (~1–2 sessions)**
New lightweight anonymous landing: live-watts hero + GoS identity line + the 2–3 headline
findings as cards + three buttons: "Take the guided tour", "Run a live measurement", "Join GoS".
The tour stays intact one click away.
- *Pro:* leads with the most shareable, most credible asset; matches a 60-second visit; gives
  the GoS-website link and LinkedIn posts a landing that works for both audiences.
- *Con:* a new surface to maintain; needs marketing's call on hierarchy (findings vs. live demo
  vs. membership).

**Decision 2 — LinkedIn entry points (yes/no, independent of Decision 1):**

**Scenario C — "Per-finding campaign links" (no homepage change)**
Each LinkedIn post links **directly to one finding page** (`/findings/<slug>`), which gets a
small "What is OWL / who is GoS" header band + share metadata per finding + a "see it measured
live" CTA into the tour/demo.
- *Pro:* one finding = one post = a natural posting cadence for the lab; deep links outperform
  homepage links on social; findings pages already render well (they even have the viewport tag).
- *Cost:* each post needs a finding worth posting — the cadence is set by the bench, not the
  calendar.

**Recommendation:** decide A-vs-B for the front door (my lean: B for cold traffic), and say yes
to C regardless — it's the fastest path to a good-looking first post and doesn't depend on the
home-page choice.

### Questions for Veronika's lab
1. Conversion goal for an interested stranger: membership lead, follow/newsletter, or
   citation/credibility? (Drives the hero CTA everywhere.)
2. Who designs the share card (og:image), and does OWL's terminal-dark identity stay as-is or
   align with GoS-site branding? (Audience includes policymakers, not just engineers.)
3. Do LinkedIn posts link to the homepage or to individual findings (Scenario C)?
4. Public naming: "OWL", "Online WattLab", or always "OWL by Greening of Streaming"?
5. One approved sentence describing GoS for use on the page and in `og:description`.

---

*Artifacts: `owl_anon_desktop_fold.png` (current desktop first screen — good),
`owl_anon_mobile_fold.png` (current iPhone render — the viewport problem),
`owl_anon_desktop_full.png` (full Welcome step).*
