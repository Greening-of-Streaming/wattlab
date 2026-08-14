"""
parity.py — encode-parity / energy-quality calibration harness (CR-003 × CR-045 V2).

Standalone, RE-RUNNABLE measurement harness. For a fixed source clip it sweeps an
ABR-bitrate axis across {CPU, GPU} encoders and {h264, h265, av1} codecs, measuring
wall-plug energy (through the SAME measured path /video uses — video.run_single) and
VMAF (terminal pass, video.compute_vmaf, after the measurement window closes). It
writes one versioned JSON artifact keyed by a HARDWARE FINGERPRINT, so a hardware
change (e.g. the NetInt ASIC cards landing) produces a new dataset rather than
silently overwriting the old one.

WHY THIS EXISTS (the two questions it answers)
  1. PARITY: NVENC currently runs a bare config (gpu.py: "best-effort first cut").
     For each codec we measure the GPU at its current ("baseline") args AND with a
     quality-knob bundle ("tuned") — at the SAME bitrate — so the VMAF lift, and its
     energy cost, are measured rather than asserted. If tuned NVENC still ceilings
     below the CPU encoder, that is a genuine finding, not something to massage.
  2. BUDGET: the resulting VMAF-vs-bitrate and Wh-per-minute curves seed the
     /video/budget calculator (replacing its hand-authored illustrative fixture).

INTEGRITY NOTES
  - The live /video gpu.py defaults are NOT modified. "baseline" reuses
    gpu.BACKEND.ffmpeg_gpu_norm_args() verbatim; "tuned" appends CBR-compatible
    quality knobs. The arg sets are injected here via run_single(custom_cmd=...).
  - The tuned knobs (-preset p7 -tune hq -multipass 2 -spatial-aq/-temporal-aq
    -aq-strength -rc-lookahead, + B-frame refs) raise VMAF at a FIXED bitrate, so
    the apples-to-apples ABR comparison /video relies on is preserved.
  - Energy is the encode's measured ΔE for `clip_duration_s` of video; we report
    wh_per_min_video = ΔE / (clip_duration_s/60) — energy per MINUTE OF CONTENT,
    independent of how fast the encode ran. That is the unit the budget page needs.

OPERATIONAL CONTRACT (real runs)
  - The P110 KLAP session is exclusive per device. While the wattlab service runs
    it polls the meter every 5s (runtime.power_poller). A real metered run therefore
    needs the service's poller backed off — pause via /tmp/owl-paused (the existing
    queue pause) once runtime.power_poller honours the pause guard. We also hold
    /tmp/gos-measure.lock for the campaign so no in-service job overlaps.
  - Dry mode (`dry=True`) does NOT touch the real meter: it monkeypatches
    video.get_power_watts to a synthetic source so the FULL run_single path (energy
    math, confidence, stream probe, thermals) + real encodes + real VMAF are
    exercised without contending with a running service. Use it to validate the
    harness end-to-end; the energy numbers it produces are synthetic and flagged.

Core logic is importable: bin/run-encode-parity drives it now; a future
/video/budget/reconfigure route will call run_campaign() the same way.
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import shlex
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import gpu
import power
import energy
import quality
import settings as cfg
import video
from confidence import confidence

# Artifacts live alongside results (symlinked to /srv/data/owl). One file per run.
ARTIFACT_DIR = Path(__file__).resolve().parent.parent / "results" / "calibration"
TRIM_DIR = Path("/tmp/wattlab_parity_clips")
SCHEMA = "encode-parity/v1"

# Canonical reference clips, by MEASURED ITU-T P.910 SI/TI (2026-06-19), NOT by
# their loose reputations: Meridian is LOW complexity (SI~13 / TI~2, soft
# cinematic), BBB is HIGH spatial (SI~33 / TI~6, sharp 3D animation), and the
# Kranjska downhill-MTB clip is the SPORT tier — high spatial AND high temporal
# (SI~101 / TI~45). Higher complexity correctly needs more bitrate to hit a VMAF
# target (sport ~12 Mbps h264 for VMAF 92 vs Meridian's ~3 Mbps).
CLIPS = {
    "meridian_120s": Path("/home/gos/wattlab/test_content/meridian_120s.mp4"),  # low
    "bbb_120s":      Path("/home/gos/wattlab/test_content/bbb_120s.mp4"),        # high
    "kranjska_120s": Path("/home/gos/wattlab/test_content/kranjska_dh_120s.mp4"),  # sport
}

CPU_ENCODER = {"h264": "libx264", "h265": "libx265", "av1": "libsvtav1"}
CPU_NORM_KEY = {"h264": "cpu", "h265": "h265_cpu", "av1": "av1_cpu"}
PRESET_KEY = {
    ("h264", "cpu"): "cpu",  ("h265", "cpu"): "h265_cpu", ("av1", "cpu"): "av1_cpu",
    ("h264", "gpu"): "gpu",  ("h265", "gpu"): "h265_gpu", ("av1", "gpu"): "av1_gpu",
}

# Validated CBR-compatible NVENC quality bundle (smoke-tested on ffmpeg N-124403,
# RTX 5080 Blackwell — all three encoders accept it). Appended for the "tuned"
# profile only; absent for "baseline".
TUNED_KNOBS = ["-preset", "p7", "-tune", "hq", "-multipass", "2",
               "-spatial-aq", "1", "-temporal-aq", "1", "-aq-strength", "8",
               "-rc-lookahead", "32"]


def _tuned_extra(codec: str) -> list:
    # h264/h265 baseline already carries -bf 2; add B-frame referencing. av1
    # baseline carries no -bf, so add both.
    return (["-bf", "2", "-b_ref_mode", "middle"] if codec == "av1"
            else ["-b_ref_mode", "middle"])


# ---------------------------------------------------------------------------
# Command builders — mirror the live /video pipeline (1080p, AAC 128k, pinned GOP),
# varying ONLY the encoder/quality args so the comparison stays apples-to-apples.
# ---------------------------------------------------------------------------
def build_cmd(codec: str, profile: str, bitrate_kbps: int, height: int = 1080) -> str:
    """Return a custom_cmd template string (with {input}/{output}) for one recipe.
    profile ∈ {"cpu", "gpu_baseline", "gpu_tuned"}. `height` is the output rung."""
    gop = str(int(cfg.load().get("encode_gop_frames", 120)))
    if profile == "cpu":
        norm = video._norm_args(CPU_NORM_KEY[codec])
        parts = ["ffmpeg", "-y", "-i", "{input}",
                 "-c:v", CPU_ENCODER[codec], "-b:v", f"{bitrate_kbps}k", *norm,
                 "-vf", f"scale=-2:{height}", "-c:a", "aac", "-b:a", "128k", "{output}"]
    else:
        b = gpu.BACKEND
        quality = list(b.ffmpeg_gpu_norm_args(codec, gop))     # live baseline args
        if profile == "gpu_tuned":
            quality += TUNED_KNOBS + _tuned_extra(codec)
        parts = ["ffmpeg", "-y", *b.ffmpeg_hwaccel_args(), "-i", "{input}",
                 "-vf", b.ffmpeg_scale_filter(height),
                 "-c:v", b.ffmpeg_encoder(codec), "-b:v", f"{bitrate_kbps}k", *quality,
                 "-c:a", "aac", "-b:a", "128k", "{output}"]
    return " ".join(parts)


def _encoder_kind(profile: str) -> str:
    return "cpu" if profile == "cpu" else "gpu"


# ABR ladder lower rungs (the 1080p top rung is the VMAF-target-driven sweep, not
# here). (height, H.264 kbps); H.265/AV1 scale per _CODEC_BR_SCALE. Lower rungs are
# fixed-bitrate and measured on cpu + gpu_baseline only (gpu_tuned was rejected S53).
_LADDER_LOWER = [(720, 2800), (540, 1600), (480, 1100), (360, 800)]
_CODEC_BR_SCALE = {"h264": 1.0, "h265": 0.6, "av1": 0.5}


def _rung_bitrate(codec: str, h264_kbps: int) -> int:
    return round(h264_kbps * _CODEC_BR_SCALE.get(codec, 1.0) / 50) * 50


# ---------------------------------------------------------------------------
# Hardware fingerprint — so a card/CPU/ffmpeg change is an obvious new dataset.
# ---------------------------------------------------------------------------
def _cpu_info() -> dict:
    model = "unknown"
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                model = line.split(":", 1)[1].strip()
                break
    except Exception:
        pass
    return {"model": model, "logical_cores": os.cpu_count()}


def fingerprint() -> dict:
    fp = {
        "gpu": gpu.stamp(),
        "cpu": _cpu_info(),
        "ffmpeg_version": video._ffmpeg_version(),
        "power_meter": power.stamp(),
    }
    try:
        import version
        fp["owl_version"] = version.version_dict()
    except Exception:
        fp["owl_version"] = None
    return fp


def fingerprint_slug(fp: dict) -> str:
    """Short, filesystem-safe key from the parts that matter for comparability."""
    gpu_enc = (fp.get("gpu") or {}).get("encode") or "nogpu"
    cores = (fp.get("cpu") or {}).get("logical_cores") or "x"
    return f"{gpu_enc}_{cores}c"


# ---------------------------------------------------------------------------
# Reference-clip trimming — VMAF needs distorted & reference to share frames, so
# we encode FROM a trimmed clip and score AGAINST the same trimmed clip. Stream-copy
# trim is exact for our purposes (both sides derive from one file).
# ---------------------------------------------------------------------------
def ensure_clip(src: Path, duration_s: Optional[int]) -> Path:
    if not duration_s:
        return src
    TRIM_DIR.mkdir(parents=True, exist_ok=True)
    out = TRIM_DIR / f"{src.stem}_{duration_s}s{src.suffix}"
    if not out.exists():
        subprocess.run(
            [video._ffmpeg_bin(), "-y", "-i", str(src), "-t", str(duration_s),
             "-c", "copy", str(out)],
            capture_output=True, text=True, check=True,
        )
    return out


# ---------------------------------------------------------------------------
# Campaign definition.
# ---------------------------------------------------------------------------
@dataclass
class Campaign:
    clips: list                      # list of clip keys (into CLIPS)
    codecs: list                     # ["h264","h265","av1"]
    profiles: list                   # ["cpu","gpu_baseline","gpu_tuned"]
    bitrates: dict                   # {codec: [kbps,...]}
    duration_s: Optional[int]        # trim length; None = full clip
    baseline_polls: int
    cooldown_s: int
    reps: int = 1
    min_task_s: float = 20.0         # repeat the encode until the measured window
                                     # reaches this many wall-clock seconds, so fast
                                     # encoders (NVENC) get enough 1 Hz power samples.
                                     # 0 = single encode (dry/plumbing).
    ladder_rungs: list = field(default_factory=list)  # lower ABR rungs [(height, h264_kbps)]
                                     # measured fixed-bitrate on cpu + gpu_baseline only.
    clip_bitrates: dict = field(default_factory=dict)  # {clip_key: {codec: [kbps]}} per-clip
                                     # sweep override (e.g. sport's taller ladder); clips not
                                     # listed fall back to self.bitrates.

    def _bitrates_for(self, clip_key: str) -> dict:
        return self.clip_bitrates.get(clip_key, self.bitrates)

    def recipes(self):
        """Yield recipe dicts in a stable order: first the 1080p VMAF-target SWEEP
        (all profiles), then the fixed-bitrate LADDER lower rungs (cpu + gpu_baseline)."""
        for clip_key in self.clips:
            for codec in self.codecs:
                for bps in self._bitrates_for(clip_key).get(codec, []):
                    for profile in self.profiles:
                        for rep in range(self.reps):
                            yield {"clip": clip_key, "codec": codec, "profile": profile,
                                   "bps": bps, "height": 1080, "rep": rep, "kind": "sweep"}
        for clip_key in self.clips:
            for codec in self.codecs:
                for height, h264_kbps in self.ladder_rungs:
                    for profile in ("cpu", "gpu_baseline"):
                        for rep in range(self.reps):
                            yield {"clip": clip_key, "codec": codec, "profile": profile,
                                   "bps": _rung_bitrate(codec, h264_kbps), "height": height,
                                   "rep": rep, "kind": "ladder"}

    def count(self) -> int:
        return sum(1 for _ in self.recipes())


# Per-codec 1080p ABR ladders spanning roughly VMAF 86–97 on typical content.
FULL_BITRATES = {
    "h264": [3000, 4500, 6000, 8000, 11000],
    "h265": [1500, 2500, 3500, 5000, 7000],
    "av1":  [1000, 1800, 2800, 4000, 6000],
}

# Sport (high SI/TI) needs ~3–4× the bitrate to reach the same VMAF, so the normal
# ladder tops out BELOW the VMAF-92 target for it. Measured h264 curve on Kranjska:
# 4 Mbps→70, 8→86, 12→~92, 16→96.5. These taller ladders keep the target interior
# to the measured range for all three codecs (h265 ~0.6×, av1 ~0.5× of h264).
SPORTS_BITRATES = {
    "h264": [4000, 8000, 12000, 16000, 20000],
    "h265": [2500, 5000, 7500, 10000, 13000],
    "av1":  [2000, 4000, 6000, 8000, 11000],
}


def dry_campaign() -> Campaign:
    """Tiny plumbing test: one codec, all three profiles, one bitrate, short clip."""
    return Campaign(
        clips=["bbb_120s"], codecs=["h264"],
        profiles=["cpu", "gpu_baseline", "gpu_tuned"],
        bitrates={"h264": [4500]}, duration_s=8,
        baseline_polls=4, cooldown_s=4, reps=1, min_task_s=0,
    )


def full_campaign(duration_s: Optional[int]) -> Campaign:
    """Full matrix: 1080p VMAF-target sweep (parity) + the lower ABR-ladder rungs."""
    s = cfg.load()
    return Campaign(
        clips=["meridian_120s", "bbb_120s", "kranjska_120s"],
        codecs=["h264", "h265", "av1"],
        profiles=["cpu", "gpu_baseline", "gpu_tuned"],
        bitrates=FULL_BITRATES,
        clip_bitrates={"kranjska_120s": SPORTS_BITRATES},
        duration_s=duration_s,
        baseline_polls=int(s.get("baseline_polls", 10)),
        cooldown_s=int(s.get("video_cooldown_s", 60)), reps=1,
        min_task_s=20.0, ladder_rungs=list(_LADDER_LOWER),
    )


def ladder_campaign(duration_s: Optional[int]) -> Campaign:
    """ONLY the lower ABR-ladder rungs (no 1080p sweep) — to add ladder data to an
    existing parity run without re-measuring the 90 sweep encodes."""
    s = cfg.load()
    return Campaign(
        clips=["meridian_120s", "bbb_120s", "kranjska_120s"],
        codecs=["h264", "h265", "av1"],
        profiles=[],                      # no 1080p sweep
        bitrates={}, duration_s=duration_s,
        baseline_polls=int(s.get("baseline_polls", 10)),
        cooldown_s=int(s.get("video_cooldown_s", 60)), reps=1,
        min_task_s=20.0, ladder_rungs=list(_LADDER_LOWER),
    )


# ---------------------------------------------------------------------------
# Synthetic meter for dry mode (no contention with a running service).
# ---------------------------------------------------------------------------
def _install_synthetic_meter():
    """Replace video.get_power_watts with a deterministic-ish synthetic source so
    run_single executes fully without touching the real P110. Returns the original
    for restoration."""
    orig = video.get_power_watts
    base = 80.0
    state = {"n": 0}

    async def fake():
        state["n"] += 1
        # idle ~80 W; once an encode is running the task poller will see a lift —
        # but we cannot know that here, so add a mild deterministic ripple. Dry
        # energy numbers are synthetic and flagged in the artifact.
        return base + 25.0 + 3.0 * math.sin(state["n"] / 2.0)

    video.get_power_watts = fake
    return orig


# ---------------------------------------------------------------------------
# Single-recipe measurement. Mirrors video.run_single's energy math, but repeats
# the encode back-to-back inside ONE baseline+task window until min_task_s of
# wall-clock has elapsed — so a fast encoder (NVENC finishes a 30s clip in a few
# seconds) still yields enough 1 Hz power samples for a tight CI. Energy is
# normalised by TOTAL content encoded (clip_seconds × n_encodes).
# ---------------------------------------------------------------------------
async def _measure_recipe(ref: Path, job_id: str, codec: str, profile: str,
                          bps: int, clip_dur_s: float, baseline_polls: int,
                          min_task_s: float, height: int = 1080) -> dict:
    cmd_str = build_cmd(codec, profile, bps, height)
    out_path = video.UPLOAD_DIR / f"{job_id}_out.mp4"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd_list = video.apply_custom_cmd(cmd_str, ref, out_path)
    loop = asyncio.get_event_loop()

    baseline = await video.measure_baseline(polls=baseline_polls)

    stop_event = asyncio.Event()
    poll_task = asyncio.create_task(video.poll_during_task(stop_event))
    t0 = time.time()
    n_enc = 0
    last_tx = None
    while True:
        last_tx = await loop.run_in_executor(None, lambda: video.transcode(cmd_list))
        n_enc += 1
        if time.time() - t0 >= min_task_s:
            break
    t1 = time.time()
    stop_event.set()
    readings = await poll_task

    delta_t = round(t1 - t0, 1)
    w_base = baseline["w_base"]
    task_samples_w = [round(r["watts"], 2) for r in readings]
    baseline_samples_w = baseline.get("baseline_samples_w")
    w_task = sum(r["watts"] for r in readings) / len(readings) if readings else w_base
    delta_w = round(w_task - w_base, 2)
    meters = power.meters_summary(baseline, readings, task_samples_w)
    if meters and "delta_w_combined" in meters:
        delta_w = meters["delta_w_combined"]
    delta_e_wh = energy.energy_wh(delta_w, delta_t)
    conf = confidence(delta_w, len(readings), w_base,
                      baseline_samples_w=baseline_samples_w,
                      task_samples_w=task_samples_w, meters=meters)

    content_s = clip_dur_s * n_enc
    wh_per_min = round(delta_e_wh / (content_s / 60), 4) if content_s else None
    # Attributional companion figure: charges the row for occupying the machine
    # ((W_base + ΔW) × Δt) rather than only the marginal ΔW above idle. Derived
    # from the same samples, not separately measured — see /methodology#energy.
    attr_wh = energy.energy_wh(w_base + delta_w, delta_t)
    wh_per_min_attr = round(attr_wh / (content_s / 60), 4) if content_s else None
    out_size_mb = round(out_path.stat().st_size / 1024 / 1024, 2) \
        if out_path.exists() and out_path.stat().st_size > 0 else None
    stream = video.probe_output_stream(out_path)
    vmaf = video.compute_vmaf(out_path, ref)          # terminal pass
    try:
        out_path.unlink()
    except FileNotFoundError:
        pass

    return {
        "vmaf": vmaf,
        "vmaf_model": quality.vmaf_model_id() if vmaf is not None else None,
        "ffmpeg_cmd": (last_tx or {}).get("ffmpeg_cmd"),
        "transcode_ok": (last_tx or {}).get("success"),
        "n_encodes": n_enc, "content_s": round(content_s, 1),
        "w_base": round(w_base, 2),
        "delta_w": delta_w, "delta_e_wh_total": delta_e_wh, "delta_t_s": delta_t,
        "wh_per_min_video": wh_per_min,
        "wh_per_min_video_attributional": wh_per_min_attr,
        "poll_count": len(readings),
        "achieved_bitrate_bps": (stream or {}).get("bit_rate_bps"),
        "output_size_mb": out_size_mb,
        "confidence_flag": (conf or {}).get("flag"),
        "confidence": conf, "stream": stream or {},
    }


# ---------------------------------------------------------------------------
# The measurement loop.
# ---------------------------------------------------------------------------
async def run_campaign(campaign: Campaign, *, dry: bool = False,
                       merge_into: Optional[Path] = None, log=print) -> dict:
    """Execute the campaign, returning the artifact dict (also written to disk).
    merge_into: append rows into an existing artifact (e.g. ladder rungs) rather
    than starting a fresh one."""
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    total = campaign.count()
    log(f"[parity] {'DRY ' if dry else ''}campaign: {total} encodes "
        f"({len(campaign.clips)} clip(s) × {len(campaign.codecs)} codec(s) × "
        f"{len(campaign.profiles)} profile(s)), duration={campaign.duration_s or 'full'}s")

    # Fingerprint + artifact skeleton up front, so we can CHECKPOINT after every
    # recipe — an unattended overnight run that dies at recipe 85 leaves a valid
    # partial artifact rather than nothing.
    started = time.time()
    if merge_into is not None:
        # Append (e.g. ladder rungs) into an existing artifact without re-measuring
        # its rows. Keeps the original fingerprint / generated_at / sweep rows.
        artifact = json.loads(Path(merge_into).read_text())
        rows = artifact["rows"]
        fp = artifact.get("fingerprint", fingerprint())
        artifact["protocol"]["ladder_rungs"] = campaign.ladder_rungs
        artifact["protocol"]["ladder_expected_rows"] = total
        out = Path(merge_into)
        log(f"[parity] merging {total} ladder rows into {out.name} ({len(rows)} existing)")
    else:
        fp = fingerprint()
        rows = []
        artifact = {
            "schema": SCHEMA,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "dry_run": dry, "synthetic_energy": dry, "complete": False,
            "fingerprint": fp,
            "protocol": {
                "clips": campaign.clips, "duration_s": campaign.duration_s,
                "scale": "1080p (scale=-2:1080)", "audio": "aac 128k",
                "gop_frames": int(cfg.load().get("encode_gop_frames", 120)),
                "baseline_polls": campaign.baseline_polls,
                "cooldown_s": campaign.cooldown_s, "reps": campaign.reps,
                "min_task_s": campaign.min_task_s, "tuned_knobs": TUNED_KNOBS,
                "ladder_rungs": campaign.ladder_rungs,
                "expected_rows": total, "elapsed_s": 0,
            },
            "rows": rows,
        }
        date = artifact["generated_at"][:10]
        suffix = "_DRY" if dry else ""
        out = ARTIFACT_DIR / f"encode_parity_{fingerprint_slug(fp)}_{date}{suffix}.json"

    def checkpoint():
        artifact["protocol"]["elapsed_s"] = round(time.time() - started, 1)
        out.write_text(json.dumps(artifact, indent=2))

    orig_watts = _install_synthetic_meter() if dry else None
    stopped = [] if dry else video.focus_mode_enter()
    if not dry:
        video.LOCK_FILE.write_text("encode-parity campaign\n")

    try:
        for idx, rc in enumerate(campaign.recipes()):
            clip_key, codec, profile = rc["clip"], rc["codec"], rc["profile"]
            bps, height, rep, rkind = rc["bps"], rc["height"], rc["rep"], rc["kind"]
            ref = ensure_clip(CLIPS[clip_key], campaign.duration_s)
            clip_dur_s = campaign.duration_s or video._probe_duration(ref) or 0
            job_id = f"parity_{idx:03d}_{clip_key}_{codec}_{profile}_{height}p_{bps}_r{rep}"
            log(f"[parity] {idx + 1}/{total}  {codec:5s} {profile:12s} {height:>4}p {bps:>6}k  "
                f"{clip_key} [{rkind}]")

            try:
                m = await _measure_recipe(ref, job_id, codec, profile, bps, clip_dur_s,
                                          campaign.baseline_polls, campaign.min_task_s, height)
            except Exception as exc:                       # never lose the run to one bad recipe
                log(f"[parity]      ! recipe failed: {exc!r}")
                m = {"error": repr(exc), "vmaf": None}
            log(f"[parity]      → vmaf={m.get('vmaf')} dW={m.get('delta_w')}W "
                f"wh/min={m.get('wh_per_min_video')} n_enc={m.get('n_encodes')} "
                f"polls={m.get('poll_count')} {m.get('confidence_flag')}")
            rows.append({
                "clip": clip_key, "codec": codec, "profile": profile,
                "encoder_kind": _encoder_kind(profile), "target_bitrate_kbps": bps,
                "height": height, "rung": rkind, "rep": rep,
                **m,
            })
            checkpoint()
            if idx + 1 < total:
                await asyncio.sleep(campaign.cooldown_s)
        artifact["complete"] = True
        if merge_into is not None or campaign.ladder_rungs:
            artifact["has_ladder"] = True
    finally:
        if not dry:
            try:
                video.LOCK_FILE.unlink()
            except FileNotFoundError:
                pass
            video.focus_mode_exit(stopped)
        if orig_watts is not None:
            video.get_power_watts = orig_watts
        checkpoint()

    log(f"[parity] wrote {out}  ({len(rows)} rows, complete={artifact['complete']}, "
        f"{artifact['protocol']['elapsed_s']}s)")
    return artifact


# ---------------------------------------------------------------------------
# CLI entry (driven by bin/run-encode-parity).
# ---------------------------------------------------------------------------
async def main(argv: list) -> int:
    import argparse
    p = argparse.ArgumentParser(description="Encode-parity / calibration harness")
    p.add_argument("--dry", action="store_true",
                   help="plumbing test: real encodes + VMAF, SYNTHETIC energy, no meter, no focus mode")
    p.add_argument("--full", action="store_true", help="run the full matrix (sweep + ladder)")
    p.add_argument("--ladder", action="store_true",
                   help="run ONLY the lower ABR-ladder rungs and merge into the latest artifact")
    p.add_argument("--duration", type=int, default=None,
                   help="trim clips to N seconds (full-run length; default full clip)")
    p.add_argument("--print-only", action="store_true",
                   help="just print the recipe commands and exit (no encoding)")
    args = p.parse_args(argv)

    merge_into = None
    if args.dry:
        camp = dry_campaign()
    elif args.ladder:
        import budget_data
        merge_into = budget_data.latest_artifact_path()
        if not merge_into:
            print("--ladder needs an existing complete parity artifact to merge into")
            return 2
        camp = ladder_campaign(args.duration or 30)
    elif args.full:
        # 30s default — clip-length literature sweet spot (>15s energy floor,
        # >=10s quality convention, ~30 1Hz power samples). Override with --duration.
        camp = full_campaign(args.duration or 30)
    else:
        print("specify --dry, --full or --ladder")
        return 2

    if args.print_only:
        for idx, rc in enumerate(camp.recipes()):
            print(f"# {idx}: {rc['clip']} {rc['codec']} {rc['profile']} {rc['height']}p {rc['bps']}k [{rc['kind']}]")
            print("  " + build_cmd(rc["codec"], rc["profile"], rc["bps"], rc["height"]))
        return 0

    if (args.full or args.ladder) and not Path("/tmp/owl-paused").exists():
        print("WARNING: /tmp/owl-paused not present — the service poller may contend "
              "for the P110. Pause the queue (/queue-status toggle) before a real run.")

    await run_campaign(camp, dry=args.dry, merge_into=Path(merge_into) if merge_into else None)
    return 0
