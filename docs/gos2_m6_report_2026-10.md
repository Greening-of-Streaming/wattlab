# Apple M6 (Mac mini) vs GoS1 — encode, LLM and image energy (first look, 2026-10-05)

**Status: DRAFT — measured overnight 2026-10-04/05 by Claude (owner asleep); not reviewed. Nothing here is
published. Tania checks before anything leaves the room (publication rule 2026-08-17; n=3 bar 2026-09-03).**
CR-085 Part 2/3. Machines: GoS1 (AMD Ryzen 9 7900 + NVIDIA RTX 5080, Ubuntu 24.04, ~78 W idle) and GoS2
(Apple M6 Mac mini `Mac18,5`, 12-core CPU 2S+4P+6E, 12-core GPU, 24 GB unified memory, macOS 27.0.1,
~1.35 W idle — `docs/gos2_design.md` §13). Same OWL code path for both (GoS1 drives GoS2 over SSH and reads
GoS2's own P110 pair; envelope v2 stamps host + engine on every result).

## What is already public about the M6 (desk research, 2026-10-05)

| Claim | Source | Notes |
|---|---|---|
| 2 nm (TSMC N2), 12-core CPU (2 super + 4 performance + 6 efficiency), 12-core GPU, dual 16-core Neural Engine, up to 32 GB unified memory at up to 170 GB/s | [Apple Newsroom, Aug 2026](https://www.apple.com/newsroom/2026/08/apple-introduces-m6-and-m5-ultra-for-a-big-leap-in-performance-and-ai-compute/) | 153.6 GB/s on 16 GB configs, 170 GB/s on 24/32 GB ([Wikipedia](https://en.wikipedia.org/wiki/Apple_M6), [MindStudio](https://www.mindstudio.ai/blog/m6-mac-mini-benchmarks-review)). Our unit is 24 GB → 170 GB/s rated. |
| Media engine: H.264, HEVC, ProRes, ProRes RAW encode/decode; **AV1 decode only** | [Wikipedia (Apple M6)](https://en.wikipedia.org/wiki/Apple_M6) | Confirmed independently on our unit: Homebrew ffmpeg 9.0.2 exposes `h264/hevc/prores_videotoolbox`, no AV1 encoder. |
| Mac mini (M6) power: 4 W idle, 70 W max (Apple's test conditions: Finder open, default power settings) | [Apple Support 103253](https://support.apple.com/en-us/103253) | |
| Idle 0.9–1.0 W with nothing attached; 2.1–2.2 W with keyboard/mouse/monitor via KVM; smart-plug measurement | [note.com (重藤 六)](https://note.com/heavywisteriasix/n/ne8f28ffbc85f?hl=en) | Our 1.352 W ± 0.008 (Ethernet, logged-in session, services on) sits between their two configurations. |
| ~48 W full-CPU, ~38 W full-GPU (vs 40 W / 44 W on M4); STREAM ~143–145 GB/s measured | [MindStudio](https://www.mindstudio.ai/blog/m6-mac-mini-benchmarks-review) (own tests) | Whole-machine figures; no encode-energy numbers. |
| LLM: 9B Q4 prompt processing ~740 tok/s, generation ~27 tok/s; FLUX.1-schnell image ~35 s (M4 94 s) | [Wccftech](https://wccftech.com/apple-m6-vs-m4-ai-performance-benchmarks/), [MindStudio](https://www.mindstudio.ai/blog/m6-mac-mini-local-ai-performance) (citing Alex Ziskind's tests) | Speed, not energy per token/image. |
| CPU efficiency ~13–15 % better than M4/M5 (points per watt) | [Notebookcheck SoC analysis](https://www.notebookcheck.net/Apple-M6-SoC-Analysis-Apple-s-2-nm-chip-crushes-AMD-Intel-Qualcomm.1404057.0.html) (via search summary; page not fetchable by our tooling — verify before citing) | |

**The gap OWL fills:** nothing found reports *energy per encode / per token / per image* for the M6, nor a
like-for-like comparison against a discrete-GPU workstation running identical software and identical inputs.
Everything published is speed or whole-machine peak power.

### Earlier Apple silicon and related work on video energy (desk research, 2026-10-05, second pass)

All **secondary**; none reports energy per encode at a stated quality, with a stated method and repeats. Listed
for context and for the "what's already public" claim — not as validation of our numbers.

| Source | What it reports | Relevance / quality |
|---|---|---|
| [thescurvydawg.com — Mac mini M2 Pro encode/decode](https://thescurvydawg.com/2025/06/21/mac-mini-m2-pro-video-decoding-encoding/) | M2 Pro HEVC encode: ~18 W average via VideoToolbox (media engine) vs ~52 W software; media engine ~70 % faster | Single blog, method unstated. Same *pattern* as ours on M6 (media engine ~23 W vs x264 ~48 W above idle). |
| [Hostbor — Mac mini M4 home server](https://hostbor.com/mac-mini-m4-home-server/) | M4 Mac mini 4K HEVC encode peak 11.8 W | Peak power only, method unclear. |
| [singhkays.com — Apple Silicon M1 power deep dive, local playback](https://singhkays.com/blog/apple-silicon-m1-video-power-consumption-pt-2/) | M1 power during local video playback, per codec | Most rigorous Apple video-power write-up found — but playback, not encode. |
| [Apple Developer Forums — VideoToolbox quality on M1](https://developer.apple.com/forums/thread/678210) | Hardware encoding trades compression quality for speed vs good software encoders | Qualitative; nobody quantifies the CBR-vs-VBR effect we measured (report §1). |
| [arXiv 2212.12842 — edge server built from massive mobile SoCs](https://arxiv.org/pdf/2212.12842) | Mobile-SoC transcoding 2.58–3.21× more energy-efficient than an Intel CPU and 1.83–4.53× than an NVIDIA A40 | Closest published analogue to M6 vs RTX; peer-reviewed-style method; not Apple silicon. |
| [arXiv 2511.18687 — NVENC split-frame encoding, UHD](https://arxiv.org/pdf/2511.18687) | NVENC board power ~38.5–43 W (HEVC), ~42–48 W (AV1); software encoders up to ~150 W | NVIDIA-side reference (board power, not wall). |
| [arXiv 2405.17866 — Rate-Energy-Distortion codec evaluation](https://arxiv.org/pdf/2405.17866) | Proposes evaluating codecs on rate × energy × distortion jointly | The right frame for our CBR/VBR iso-quality result. |
| [arXiv 2401.09854 — survey: energy and environmental impact of video streaming](https://arxiv.org/pdf/2401.09854) | Literature survey | Context; no Apple silicon encode data. |

Excluded: several search hits were AI-generated or retail "wiki" pages (AliExpress / Alibaba) with unsourced
Mac mini wattages — not cited.

**Conclusion of both passes:** no published energy-per-job data for the M6 (encode, token or image), and for
M1–M4 only blog-grade peak-power figures for encoding. The direction of the M2 Pro blog and of the mobile-SoC
transcoding paper matches ours.

## Unified memory — what it can and cannot explain (conjecture section, not claims)

- **Encode (media engine):** frames decoded, scaled and encoded on the M6 never cross a bus — the decoder,
  scaler (GPU) and media engine all read the same physical memory. GoS1's NVENC path is *also* all-on-device
  (CUDA decode → `scale_cuda` → NVENC, frames stay in VRAM), so unified memory is **not** the obvious source of
  any encode difference here. The large whole-machine gap is mostly the **idle floor** (~78 W vs ~1.4 W: discrete
  GPU at idle, desktop platform, PSU at low load), which no per-task metric captures.
- **Software encode (same x264/x265/SVT-AV1 binary family on both):** identical bit-exact output (VMAF equal to
  2 decimals) at ~26–40 % lower marginal energy on M6. Plausible contributors: 2 nm vs 5 nm-class silicon,
  wide P-cores at lower clocks, memory controller on-package. We cannot attribute among these with a wall meter.
- **LLM token generation** is memory-bandwidth bound: per output token the whole active weight set is read.
  RTX 5080 GDDR7 ≈ 960 GB/s vs M6 ≈ 170 GB/s → expect GoS1 several × faster per token; energy per token then
  depends on whether the 5080's higher power is offset by its speed. Unified memory's real advantage is
  **capacity**: a 24 GB M6 can hold a ~18 GB model entirely in GPU-addressable memory, where the 16 GB RTX 5080
  must spill layers to system RAM over PCIe — a test we did *not* run tonight (needs a >16 GB model on both).
- **MLX vs llama.cpp on the same Mac:** MLX is designed around unified memory (lazy evaluation, no host↔device
  copies, Metal kernels tuned for Apple GPUs); llama.cpp/Ollama's Metal backend is a port. Any MLX advantage
  measured on GoS2 is a *software stack* effect on the same silicon — reported as a separate engine.

## Results

*(filled from stored results below; every number cites a job id)*

### 1. Video encode — Meridian 120 s → 1080p, n = 3 per engine, all 🟢

Campaign manifest: `/srv/data/owl/campaign_2026-10-05_gos2_m6/manifest.jsonl` (12 jobs, 33 sides),
VBR set `vbr_manifest.jsonl` + `isoq_manifest.jsonl`. Draft finding:
`docs/findings_drafts/apple-m6-encode-energy-vs-ryzen-rtx5080.md` (all job ids, full table, caveats).

| | Marginal ΔE (energy above own idle) | Whole machine (wall × time) | Speed | Quality |
|---|---|---|---|---|
| Same software encoder (x264 / x265 / SVT-AV1) | M6 **−26 % / −40 % / −40 %** vs Ryzen 9 7900 | M6 **2.8× / 3.3× / 3.4×** cheaper | equal (±8 %) | bit-identical output |
| Hardware, VBR (H.264 4 Mb/s / H.265 2 Mb/s) | M6 media engine **−15 % / −22 %** vs RTX 5080 NVENC | M6 ~2.3–2.5× cheaper | NVENC ~1.5× faster | H.264: VMAF 88.6 vs 89.6 · H.265: 88.0 vs 87.4 (M6 file 20 % smaller) |
| Hardware, CBR (OWL preset parity) | M6 −1 % / −12 % | M6 2.3× / 2.5× cheaper | NVENC 2.4× / 2.2× faster | M6 **5 VMAF lower** (83.3 vs 88.7) |

**Practical finding (rate control):** on the M6 media engine, CBR (`-constant_bit_rate 1`) at the same file
size is 50 % slower, uses 15 % more energy and loses 5 VMAF vs VBR; raising the CBR target to 12 Mb/s only
reaches VMAF 86.3 (bits go to filler: 6 and 8 Mb/s give identical VMAF 84.26). NVENC loses ~0.9 VMAF in CBR.
**On Apple silicon, the rate-control setting matters more than the silicon comparison.**

AV1: the M6 has no AV1 hardware encoder — SVT-AV1 on the M6 CPU (0.379 Wh) uses 78 % *more* marginal energy
than NVENC AV1 (0.212 Wh) at equal VMAF (87.8 vs 87.1); whole-machine the M6 is still cheaper (0.39 vs 0.50 Wh).

### 2. LLM inference — qwen3:4b, task T2 (medium reasoning), cold start, n = 3, all 🟢

| Engine | mWh / output token (marginal) | Whole machine mWh/token | tokens/s |
|---|---|---|---|
| GoS1 — RTX 5080, Ollama 0.20.2 (CUDA) | 0.294 ± 0.010 | 0.412 | 185 |
| GoS2 — M6 GPU, Ollama 0.35.1 (Metal, **byte-identical GGUF**, digest 359d7dd4bcda) | 0.160 ± 0.008 (**−46 %**) | 0.168 | 47 |
| GoS2 — M6 GPU, **MLX** (mlx-lm 0.32.0, mlx-community/Qwen3-4B-4bit) | 0.105 ± 0.001 (**−64 %**) | 0.112 | 55 |

Jobs: GoS1 dcfe2bf7, 0d5a2c2c, 18ff7f0e · GoS2 Ollama gos2-f079b955, gos2-2020644d, gos2-ae79f829 ·
GoS2 MLX gos2-154efd8e, gos2-092d00ab, gos2-877b51c2 (`ai_manifest.jsonl`).

Reading: the RTX 5080 is **~4× faster** (GDDR7 bandwidth ≈ 960 GB/s vs 170 GB/s unified memory — token
generation is bandwidth-bound), but at ~196 W marginal vs ~27 W (Ollama) / ~21 W (MLX) — measured means, qwen3:4b — its energy per token is ~2× higher. On the
same Mac, **MLX beats llama.cpp/Ollama by 34 % per token** — the owner's hypothesis (2026-10-05) holds on this
model/task. Caveats: (a) MLX decodes greedily by default (3046 tokens, identical every run) while Ollama
samples at its default temperature (3799–4743 tokens) — per-token normalisation absorbs most of this, but
longer outputs carry longer contexts; (b) MLX's 4-bit conversion is not the same file as the GGUF Q4_K_M;
(c) Ollama versions differ (0.20.2 vs 0.35.1 — GoS1 upgrade needs owner sudo).

### 3. Image generation — 512 px, GPU path, batch 50, n = 3, all 🟢

Same model files (copied from GoS1's HF cache), same steps/size/guidance, diffusers 0.37.1 on both
(GoS1 CUDA fp16, torch 2.11; GoS2 Metal/MPS fp16, torch 2.14.1). Lab route `/image/bench` (`bench_manifest.jsonl`).

| Model | Machine | Wh / image (marginal) | s / image | ΔW | Whole machine Wh / image |
|---|---|---|---|---|---|
| SD-Turbo (20 steps) | RTX 5080 | 0.0216 ± 0.0050 | 0.40 | 194 W | 0.0303 |
| SD-Turbo (20 steps) | Apple M6 | **0.0172 ± 0.0002 (−20 %)** | 2.06 | 30 W | 0.0180 |
| SDXL-Turbo (4 steps) | RTX 5080 | 0.0105 ± 0.0001 | 0.22 | 172 W | 0.0150 |
| SDXL-Turbo (4 steps) | Apple M6 | **0.0085 ± 0.0004 (−19 %)** | 1.03 | 30 W | 0.0089 |

Jobs: sd-turbo GoS1 5018ce34, 92297a48, 3bfc4234 · GoS2 gos2-798b85e9, gos2-f2ea1345, gos2-5ae563c5 ·
sdxl-turbo GoS1 f9bdb51a, 4d4f872f, 2c8eee89 · GoS2 gos2-f10fccbb, gos2-9038f5c6, gos2-fc85b49c.

**Method note that changed the answer (keep this):** OWL's image convention averages wall power over model
load + generation but multiplies by generation time only. With GoS1's default 5-image GPU batch the generation
window is ~2 s, so the load phase dominates the mean and the comparison *inverts* — at default batch the RTX
looked ~2× more efficient per image (0.0056 vs 0.0118 Wh, 🟡 on GoS1). Recomputing from the generation-window
samples only already pointed the other way; batch 50 settles it (both 🟢, tight CIs). **Any cross-host image
comparison must use a run long enough that load is negligible.** The public `/image` default batch is fine for
its own demo purpose but its per-image figures carry this bias on fast GPUs.

Reading: the RTX 5080 is ~5× faster per image; the M6 uses ~20 % less energy per image at the margin and
~1.7× less counting the whole machine. Diffusion is compute-bound, unlike LLM token generation — the M6's
per-image advantage is much smaller than its per-token advantage (−20 % vs −46/−64 %), which is the pattern
you would expect if memory bandwidth is what the RTX is "wasting" power on during token generation.

**The efficient model — SANA-Sprint 0.6B (1024 px, 2 steps, bf16), batch 50, n = 3, all 🟢:**

| Machine | Wh / image (marginal) | s / image | Whole machine Wh / image |
|---|---|---|---|
| RTX 5080 | **0.0140 ± 0.0004** | 0.27 | 0.0198 |
| Apple M6 | 0.0146 ± 0.0005 (+4 %, ≈ tie) | 1.79 | **0.0153** |

Jobs: GoS1 3b671420, 4b306d84, b156d048 · GoS2 gos2-d90790a4, gos2-82a3de95, gos2-ee130afb.
A 1024 px SANA-Sprint image costs about what a 512 px SD-Turbo image does — the model choice moves energy per
image far more than the machine does. On this modern bf16 DiT the RTX closes the per-image gap entirely.
Added to the public `/image` panel (owner-approved), public smoke test 🟢 (89307e04).

**Candidate post line (needs Tania's check, operating point named):** *"This 1024-pixel image took 0.014 Wh to
generate on an NVIDIA RTX 5080 and 0.015 Wh on an Apple M6 Mac mini (SANA-Sprint 0.6B, 2 steps; energy above
idle; n = 3). Counting the whole machine, 0.020 vs 0.015 Wh — and the RTX was 6.6× faster."*

### 2b. LLM — three model sizes (qwen3 1.7B / 4B / 8B), task T2, cold start, n = 3

mWh per output token (marginal, mean ± 95 % CI) · tokens/s · whole-machine mWh/token:

| Model | RTX 5080 (Ollama 0.20.2) | M6 · Ollama 0.35.1 (same GGUF) | M6 · MLX (4-bit) |
|---|---|---|---|
| qwen3:1.7b | 0.130 ± 0.009 · 308 tok/s · 0.196 — **🟡** (runs ~7 s) | 0.073 ± 0.028 · 91 · 0.077 | **0.039 ± 0.003** · 120 · 0.042 |
| qwen3:4b | 0.294 ± 0.010 · 185 · 0.412 | 0.160 ± 0.008 · 47 · 0.168 | **0.105 ± 0.001** · 55 · 0.112 |
| qwen3:8b | 0.496 ± 0.006 · 127 · 0.661 | 0.245 ± 0.010 · 27 · 0.259 | **0.182 ± 0.004** · 32 · 0.195 |

Jobs (ai_manifest.jsonl): 8b GoS1 e3c40ec3, 8423e5dd, 213a6c8f · Ollama gos2-b29364f3, gos2-efb92bf2,
gos2-61914d6d · MLX gos2-b3c5f2da, gos2-a9d833e5, gos2-bd841599 · 1.7b GoS1 515904d1, 5f5e8d12, 0575b37f ·
Ollama gos2-afae8350, gos2-4eb06e95, gos2-aee6aeff · MLX gos2-8db534da, gos2-58b8ba54, gos2-117e7169.
Ollama digests identical on both hosts (qwen3:8b 500a1f067a9f).

**Pattern, consistent across sizes:** same model file, the M6 (Ollama) spends **44–51 % less marginal energy
per token** than the RTX 5080 while running **3.4–4.7× slower**; MLX on the same Mac takes a further
**26–47 % off**. Whole-machine, the M6+MLX is **3.4–4.7× cheaper per token**. Every engine scales roughly
with parameter count.


### 3b. Image re-test — warm-model sessions (owner challenge, 2026-10-05) — **supersedes §3's per-image claims**

Owner: "Are we sure we're not confounding model load times?" — yes, we were. New method (`POST /image/session`,
same runner script on both hosts): load + 2 warm-up images outside the window, 30 s settle, warm baseline, then
4 prompts × 25 images, window = generation only. n = 3, all 🟢 (`session_manifest.jsonl`).

| Wh / image | Bench (§3, old) | Session, whole window | Session, steady state (blocks 2–4) | s / image |
|---|---|---|---|---|
| SANA-Sprint 1024 px — RTX 5080 | 0.0140 | 0.0163 ± 0.0001 (+16 %) | **0.0175 ± 0.0002** | 0.269 |
| SANA-Sprint 1024 px — M6 | 0.0146 | 0.0154 ± 0.0004 (+5 %) | **0.0157 ± 0.0005 (−10 % vs RTX)** | 1.798 |
| SDXL-Turbo 512 px — RTX 5080 | 0.0105 | 0.0125 ± 0.0001 (+19 %) | **0.0136 ± 0.0001** | 0.225 |
| SDXL-Turbo 512 px — M6 | 0.0085 | 0.0091 ± 0.0001 (+7 %) | **0.0093 ± 0.0001 (−31 % vs RTX)** | 1.026 |

Jobs: SANA GoS1 89f7ba16, b87d1d53, 939e5e29 · GoS2 gos2-7b4209cf, gos2-b17ab828, gos2-b376d791 ·
SDXL GoS1 3cc0f76c, 3e8c9114, 521de028 · GoS2 gos2-131eebb1, gos2-c0d07b7e, gos2-f928b53f.

What we learned:
1. **Load dilution was material and biased toward the RTX** (+16–19 % on GoS1 vs +5–7 % on GoS2 once removed).
   The SANA-Sprint "tie" becomes **M6 −10 %**; SDXL-Turbo **M6 −31 %**. Whole machine: M6 1.4× / 1.8× cheaper.
2. **Warm vs cold idle: no difference after a 30 s settle** (GoS1 74.5 vs 75.6 W, GoS2 1.3 vs 1.5 W). The +34 W
   seen in a 10 s-settle smoke test was GPU clocks still decaying after warm-up — settle ≥ 30 s.
3. **Prompt complexity is a non-factor** (control confirmed): identical time per prompt block on both machines,
   including a prompt longer than CLIP's 77-token window and a text-rendering prompt.
4. **Meter ramp:** the first prompt block reads 9–27 % low (RTX 22–27 %, M6 9–12 %) with identical time — the P110 lags the power step.
   Steady state (blocks 2–4) is the better estimate; it matters more for short windows (RTX).

Candidate post line, revised: *"Same model, same script, model already loaded: a 1024-pixel SANA-Sprint image
took 0.0175 Wh on an NVIDIA RTX 5080 and 0.0157 Wh on an Apple M6 Mac mini (energy above idle, n = 3) — 10 %
less on the Mac, which took 1.8 s per image against the RTX's 0.27 s."*
