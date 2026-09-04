# SMPTE 4951 — Restructuring Notes for Editorial Pass

Prepared by Tania (with Claude) as a working companion to `SMPTE_4951_Dual_Track_restructured.docx`, which already applies everything below. This document exists so Ben (and his Claude) can see the reasoning, not just the diff — and can push back on any of it.

Starting point was the review-copy export (version `cdc17ac`) — comment-only, with Sections 1, 2, and 6 still carrying June 2026 placeholder text and Sections 3–5 written but, in Tania's read, dense to the point of unclear, especially Section 5.

---

## 1. Overall diagnosis

Three problems drove every change below:

1. **No stated argument.** The paper never explicitly says *why* two measurement platforms are needed instead of one. The closest it comes is three sentences in the old standalone Section 2 ("field measurement is realistic but confounded; lab measurement is clean but may not generalize; therefore both") — asserted, never demonstrated.
2. **Section 5 is chronology, not argument.** It reads as "here's what we did, in order" (Cycle 1, Cycle 2 field, Cycle 2 bench, encoder-flag pricing, fleet math) rather than "here's a claim, and here's how each piece of evidence supports it."
3. **No related-work grounding.** The paper cites exactly one prior study (Lasak et al., used only to motivate the field/lab tension) despite the companion paper already having sourced two more relevant citations (Begen et al. 2022, Zakaria et al. 2023), and despite known adjacent work (e.g. Fraunhofer device-power studies) not being cited at all. A reviewer's first question for a measurement-framework paper — "what's new here relative to existing device/codec energy work" — currently has no answer in the text.

Word count was explicitly *not* a constraint for this pass (Tania's instruction: "don't try to stick to 5000 words for now") — the restructured draft is longer than the source in places (Related Work and the Traffic Light explanation are new content), and still needs a real trim pass before submission. See §7.

---

## 2. Section-by-section changes

### Old Section 2 ("The Case for a Dual-Track Approach") → removed as a standalone section

It was three sentences making an unsupported claim. That claim now opens the Introduction (§1.1) instead, immediately followed by Related Work — its natural home, since "here's the field/lab tension, here's why nobody's solved it, here's our approach" is exactly what an introduction does, and a two-paragraph section arguably shouldn't survive next to five-page sections built to demonstrate that same argument.

### Section 1 (Introduction) → restructured into three subsections, `1.1–1.3`

- **1.1 Motivation.** Rewritten from the June placeholder to make the field/lab tension the central argument up front (this absorbs the old Section 2 content), ending on a direct pointer to Section 4 as where the argument gets demonstrated rather than just asserted.
- **1.2 Related Work — new.** Positions the paper against: Lasak et al. [1] (automated field measurement, no controlled counterpart), Begen et al. [2] and Zakaria et al. [3] (codec/distribution sustainability surveys — both already properly cited in Tania's companion abstract, reused here with matching citation info), and the companion paper itself [4]. **Flags a gap**: a citation for Fraunhofer's device-power measurement work is referenced conversationally but the actual paper/DOI was never sourced — this is left as an explicit `[TODO]` in the draft rather than invented. **Ben/whoever owns related work: this needs the real citation before submission**, and the paragraph is currently a placeholder shape rather than settled prose.
- **1.3 Contribution and Roadmap.** New, short, mechanical — one sentence per section so a reader knows what's coming.

### Section 3 (REM) — re-sequenced, not rewritten from scratch

Old order was 3.1 Polling architecture → 3.2 Cross-device time reference → 3.3 Test sequence design → 3.4 Removing the constraints (LEM). This mixed "what REM is," "why it's limited," and "how a specific limitation was fixed" in one undifferentiated run.

New order, chosen to make REM and OWL structurally parallel (see §3 rationale below):
- **2.1 Overview and Goals**
- **2.2 Architecture** (the plug/collector/SNMP setup, plus LEM introduced as an architectural component rather than a "fix" bolted on at the end)
- **2.3 Test Sequence Design and Cross-Device Alignment** — REM's own particular subsection: the embedded black/white/black marker technique, the alignment math, why sequence length is dictated by polling cadence rather than experiment design. This is REM's distinctive methodological contribution and now reads as one coherent technique rather than being split across two old subsections.
- **2.4 Challenges and Limitations** — the cloud-API truncation/lag findings, LEM's validation against a bench reader, and the two protocol requirements that came out of the 2026 campaigns (luminance-swing exclusion threshold, live-event timestamping).

No numbers were changed. Content was moved and re-framed, not re-measured.

### Section 4 (OWL) — same re-sequencing logic, plus one new subsection

Old order was 4.1 Instrument and protocol → 4.2 Comparison discipline → 4.3 Extending to client devices → 4.4 What the transfer taught / can't do.

New order:
- **3.1 Overview and Goals**
- **3.2 Architecture**, split into 3.2.1 Server Instrument, 3.2.2 Client Decode Bench, and **3.2.3 Instrument Commensurability — pulled out and elevated**. This is the paragraph (previously buried inside "extending to client devices") showing that OWL's bench reader and REM's LAN path (LEM) were validated against the *same plug hardware* and agree within 0.2%. This is arguably the single most important methodological fact in the whole paper — it's what licenses combining a REM number and an OWL number into one claim at all — and it was getting lost as an aside. It's now its own numbered subsection, and Section 4 (Findings) explicitly points back to it.
- **3.3 The Confidence Protocol (Traffic Light) — new subsection, and it surfaces a real gap.** Every finding in the paper carries a Repeatable / Early Insight / Need More Data label, but the label criteria are never actually defined anywhere in the paper itself (only in the *review-copy front matter*, which isn't part of the submitted text). This subsection states what the three labels mean in principle but is missing the model's actual numeric thresholds (what n, what confidence margin separates the tiers) — flagged as `[TODO]` in the draft. **Whoever owns the OWL confidence model needs to supply these numbers** — this was explicitly requested by Tania as an "educational" subsection (results should be interpretable, not just measured), so it can't stay a placeholder.
- **3.4 Comparison Discipline**, split into 3.4.1 Equivalence and 3.4.2 Two Traps and One Correction (pacing regime, encoder preset, and the "longer measurement window ≠ more confidence" correction, including the honest retraction of the earlier 5–20 minute guidance).
- **3.5 Challenges and Limitations** — the marginal-vs-attributional accounting choice, silicon-generation split, apportionment limits, "can decode ≠ can play."

### Section 5 (Findings) — the main rewrite

This was the actual subject of most of the discussion. Three changes:

**(a) It now opens with the necessity argument stated directly, before any chronology (new §4.1, "The Necessity Argument").** The logic, made explicit for the first time in the paper:
- REM alone gives an ambiguous result: a field null could mean "no effect" or could mean "effect exists but is below REM's resolution floor" — and Section 2 already showed that's a real risk (the cloud-path truncation issue), not hypothetical.
- OWL alone gives a clean mechanism, but only for the specific machines tested — it says nothing about whether that mechanism holds across a deployed fleet's diversity.
- Only the pairing — licensed by the 0.2%-agreement instrument calibration in §3.2.3 — converts an ambiguous field observation into an explained, generalizable one.

**(b) The phenomenon now has a name: "codec transparency under hardware decode."** Tania's objection to the term "null" is addressed — the paper previously never stated the finding as a positive claim, just as an absence. It's now stated once, explicitly, as: *codec's energy cost is close to zero under hardware decode, and becomes one of the largest single levers on device power the moment decode falls back to software.* Every subsequent subsection is now evidence for that stated claim rather than an item in a list of things that happened.

**(c) The old five subsections were reorganized around that argument rather than strict chronology**, and two placeholders were added for figures that don't exist yet:
- 4.2 Cycle 1 (variable ranking, then pricing) — largely unchanged, now framed as "why we started looking at codec at all."
- 4.3 Cycle 2, Field (was 5.2) — the REM finding, trimmed slightly, "null" language removed throughout.
- 4.4 Cycle 2, Bench (was 5.3) — the OWL explanation. **The Wi-Fi/pacing retraction narrative was compressed** from a full paragraph walking through the original wrong finding to two sentences stating the corrected result plus a citation — the retraction is honest and worth keeping in some form, but the paper doesn't need to re-derive a discarded result at length to be honest about it.
- **Old 5.4 (pricing individual encoder flags — grain synthesis, CABAC, ref frames) is cut down to one paragraph pointing at the companion paper**, rather than four independent flag-level mini-studies. Rationale: this is the section with the real overlap risk against Tania's paper (#4941) — it's encode-side, flag-level energy-vs-bits work, adjacent in genre to the companion paper's codec/implementation-level analysis. Cutting it here and citing forward is both the cleanest word-count win in the document (roughly 750 words down to ~100) and the safest move on overlap. **Ben should confirm he's fine losing this detail from this paper** — the underlying measurements aren't lost, they're just reported once, in the companion paper, rather than twice.
- 4.5 Fleet-scale close (was 5.5) — trimmed from a three-assumption hedge structure to a shorter closing paragraph, kept as the "why does a small device-level effect matter" payoff.
- **Two figures are now explicitly called for and captioned but not yet built**: a schematic of the REM-observes → OWL-explains → boundary-condition loop (this is the single highest-value diagram in the paper — nothing currently shows the argument as a picture), and the existing sequence-design figure carried over from Section 2.

### Section 6 (Conclusion) → repurposed as "Limitations, Future Work, and Conclusion"

Old version (June placeholder) asserted the dual-track combination as the contribution and closed with a generic openness/collaboration invitation, disconnected from anything specific Section 5 had shown.

New version: states the framework's actual limitation honestly (small panels on both sides — four REM TV panels, five OWL client devices, one operator set-top box — and the hardware-coverage claim, while now supported across three silicon vendors, isn't yet fleet-validated), carries forward the two narrower limitations from Sections 2–3 (LEM untested over Wi-Fi, OWL's mid-2026 GPU generation split), and **explicitly states the scope boundary against the companion paper** ("this paper answers where the energy lands... the companion paper answers what encoding choices cost to produce it") rather than leaving that relationship implicit across scattered mentions in the abstract, intro, and §3.4.2.

---

## 3. Why REM and OWL are now structurally parallel

Both platform sections follow the same shape — Overview/Goals → Architecture → [platform-specific method subsection] → Challenges/Limitations — rather than each having its own ad hoc structure. Two reasons: it makes the sections easier to read side by side, and it's what makes Section 4's argument work at all — the reader needs to be able to compare "what REM can and can't tell you" against "what OWL can and can't tell you" directly, and parallel structure is what makes that comparison legible rather than something the reader has to reconstruct.

---

## 4. Open questions for Ben / next editorial pass

1. **Fraunhofer citation** (§1.2) — needs the actual reference.
2. **Traffic Light numeric thresholds** (§3.3) — needs the real n / confidence-margin criteria from whoever owns the OWL confidence model.
3. **Cycle-1 OWL pricing reference** — the June text cited a reference [3] for "OWL priced the device-side ranking"; that specific source wasn't captured in this restructuring pass and needs to be re-confirmed and correctly numbered in the reference list.
4. **Confirm the 5.4 cut** — is Ben comfortable with the encoder-flag pricing material living only in the companion paper, or does he want at least one flag-level result kept in this paper as a bridge/teaser? Current draft assumes "cut and point forward."
5. **Two missing figures** — the necessity-loop schematic (Figure 3 in the new draft) is new and doesn't exist as a source diagram anywhere; the sequence-design figure (Figure 1) was already requested in the source doc and still isn't built.
6. **Format/template** — applied double-spacing, numbered sections, Times New Roman 12pt, US Letter, 1" margins based on the SMPTE style guide and the 2025/2026 Summit call-for-papers pages. The actual SMPTE `.dot` manuscript template couldn't be opened programmatically (binary file); worth checking the restructured docx against it directly before final formatting.
7. **Word count** — restructuring didn't shrink the paper; it added Related Work and the Traffic Light explanation while only partially trimming Section 5. A real cut pass is still needed against whatever the confirmed limit turns out to be (see the separate thread on Conference- vs Journal-track word limits — best evidence found points to 5,000 words max for the post-acceptance manuscript, but this should be confirmed against the actual SMPTE acceptance correspondence rather than taken from the public CFP page alone).

---

## 5. What was *not* changed

No measured number, confidence interval, n, or [Cx Fx] / [#4941] citation tag was altered anywhere in this pass — only prose framing, section order, and headings. Anything that looks like a number changed is either a transcription check worth doing, or (more likely) the same number appearing in a new sentence.
