"""
Pixop partner GPU transcode/upscale — energy measurement wrapper.

Backs the hidden, Lab-only `/enhance-run` page. Pixop's `pixop/live` image is a
thin wrapper around NVEncC (NVIDIA HW encoder); its entrypoint forwards CLI args
straight to `nvencc`. A real enhance run (480p H.264 → 1080p HEVC 10-bit, ×2
super-resolution + HDR passthrough) already works bare-metal on GoS1's RTX 5080.
This module wraps that `docker run` in OWL's existing measurement harness so the
ENERGY cost of the enhancement is a P110-polled ΔWh with a confidence flag, just
like every other workload.

Design decisions (verified ground truth, 2026-06-03):
  - The license is baked INTO the image (`/opt/pixop/license.jwt`, customer gos).
    OWL supplies NO license — do not mount `PIXOP_LICENSE_JWT` or a host file.
  - Container contract: host dirs mount to `/mnt/host/input` + `/mnt/host/output`;
    presets are passed to nvencc via `--option-file <file.args>` (NOT `-p`).
  - OWL owns its workdir under `/srv/data/owl` (gos-owned), so it can create
    input/output/presets itself with no root chown. Jon's `/home/jon/...` is
    permission-locked and must NOT be referenced.

Single-sourcing: baseline / 1 Hz polling / focus mode / cooldown / output probe
are all REUSED from video.py + power.py — never reimplemented here. Cooldown goes
through `power.cooldown_between_runs` (no raw asyncio.sleep), keeping the
cooldown-dispatcher audit clean.
"""
import asyncio
import json
import math
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Optional

import gpu
import settings as cfg
from confidence import confidence
from power import cooldown_between_runs
from video import (
    measure_baseline, poll_during_task, focus_mode_enter, focus_mode_exit,
    probe_output_stream, _probe_duration, _ffprobe_bin, LOCK_FILE,
)

SCOPE = "Device layer only (GoS1 server). Network, CDN, CPE excluded."
_TAIL = 2000  # chars of stdout/stderr retained on the result


# --- Config -----------------------------------------------------------------

def config() -> dict:
    """Effective pixop config: settings.json overlaid with OWL_PIXOP_* env vars
    (env wins, for ops flexibility without a settings write)."""
    s = cfg.load()
    workdir = os.environ.get("OWL_PIXOP_WORKDIR", s.get("pixop_workdir", "/srv/data/owl/pixop"))
    return {
        "image_tag":     os.environ.get("OWL_PIXOP_IMAGE_TAG", s.get("pixop_image_tag", "pixop/live:2026.06.03")),
        "workdir":       workdir,
        # Pixop license is mounted in at runtime (NOT baked into the image, despite
        # earlier notes) — Jon's run_pixop_nvencc.sh mounts ./license.jwt to
        # /opt/pixop/license.jwt:ro. Default to <workdir>/license.jwt; env overrides.
        "license_path":  os.environ.get("OWL_PIXOP_LICENSE_FILE", str(Path(workdir) / "license.jwt")),
        "presets":       s.get("pixop_presets", []) or [],
        "cooldown_s":    s.get("pixop_cooldown_s", 60),
        "docker_timeout_s": s.get("pixop_docker_timeout_s", 1800),
        "baseline_polls":   s.get("baseline_polls", 10),
        "vqa_enabled":   s.get("vqa_enabled", True),
        "vqa_dir":       os.environ.get("OWL_VQA_DIR", s.get("vqa_dir", "/srv/data/owl/vqa-eval")),
        "vqa_timeout_s": s.get("vqa_timeout_s", 600),
        # CR-064 — colour templates the generated combo matrix derives from.
        # Interim: Jon's staged FHD presets (correct for SDR input); swap for
        # his blessed input-agnostic templates when they arrive.
        "template_sdr":  s.get("enhance_template_sdr", "nvencc_fhd_709_20mbps.args"),
        "template_hdr":  s.get("enhance_template_hdr", "nvencc_fhd_pq_20mbps.args"),
    }


def _workdir_paths(c: dict) -> tuple[Path, Path, Path]:
    base = Path(c["workdir"])
    return base / "input", base / "output", base / "presets"


def ensure_workdir(c: Optional[dict] = None) -> None:
    """mkdir -p the three subdirs. OWL owns /srv/data/owl, so no root needed.
    Fails soft — preflight surfaces an unwritable workdir as a reason."""
    c = c or config()
    for p in _workdir_paths(c):
        try:
            p.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass


def list_presets(c: Optional[dict] = None) -> list[str]:
    """Configured preset list, else auto-listed *.args basenames in presets/."""
    c = c or config()
    if c["presets"]:
        return list(c["presets"])
    _, _, pre = _workdir_paths(c)
    try:
        return sorted(p.name for p in pre.glob("*.args"))
    except Exception:
        return []


def describe_preset(preset_name: str, c: Optional[dict] = None) -> str:
    """Human-friendly one-liner derived from the preset's ACTUAL flags (so it
    stays truthful if Jon tweaks a preset). E.g. 'AI restore + upscale to 1080p ·
    SDR→HDR · 20 Mbps'. Empty string on any parse miss (fail-soft)."""
    c = c or config()
    _, _, pre = _workdir_paths(c)
    try:
        args = " ".join(read_preset_args(pre / preset_name))
    except Exception:
        return ""
    if not args:
        return ""
    bits = []
    # Resolution / scaling
    scale = None
    m = re.search(r"--output-res\s+(\S+)", args)
    if m:
        res = m.group(1)
        if "scale=2" in res:
            scale = "×2 super-res"
        else:
            wxh = res.split(",")[0]
            if "x" in wxh and wxh != "0x0":
                scale = f"upscale to {wxh.split('x')[1]}p"
    if scale:
        bits.append(scale)
    # Colour / HDR
    if "sdr_to_hdr=on" in args:
        bits.append("SDR→HDR")
    elif "smpte2084" in args:
        bits.append("HDR passthrough")
    elif "transfer bt709" in args:
        bits.append("stays SDR")
    # Bitrate
    mb = re.search(r"--cbr\s+(\d+)", args)
    if mb:
        bits.append(f"{round(int(mb.group(1)) / 1000)} Mbps")
    return " · ".join(bits)


def parse_preset_spec(preset_name: str, c: Optional[dict] = None) -> dict:
    """Structured view of a preset's flags, for the ffmpeg apples-to-apples
    baseline: target resolution / scale factor, target bitrate (kbps), and
    whether it does an SDR→HDR colour conversion. Fail-soft to a dict of Nones.

    `hdr_convert` is the gate for the ffmpeg comparison — libswscale can't
    replicate a real SDR→HDR tone-map apples-to-apples (the Tania call), so
    only upscale-only presets qualify for a fair plain-ffmpeg baseline."""
    c = c or config()
    _, _, pre = _workdir_paths(c)
    spec = {"width": None, "height": None, "scale_factor": None,
            "bitrate_kbps": None, "hdr_convert": False, "stays_sdr": False,
            "output_csp": None, "output_depth": None}
    try:
        args = " ".join(read_preset_args(pre / preset_name))
    except Exception:
        return spec
    if not args:
        return spec
    m = re.search(r"--output-res\s+(\S+)", args)
    if m:
        res = m.group(1)
        sm = re.search(r"scale=(\d+(?:\.\d+)?)", res)
        if sm:
            spec["scale_factor"] = float(sm.group(1))
        wxh = res.split(",")[0]
        if "x" in wxh.lower() and wxh != "0x0":
            try:
                w, h = wxh.lower().split("x")
                spec["width"], spec["height"] = int(w), int(h)
            except ValueError:
                pass
    mb = re.search(r"--cbr\s+(\d+)", args)
    if mb:
        spec["bitrate_kbps"] = int(mb.group(1))
    if "sdr_to_hdr=on" in args:
        spec["hdr_convert"] = True
    elif "transfer bt709" in args:
        spec["stays_sdr"] = True
    # CR-064 — output chroma subsampling + bit depth, so the ffmpeg baseline
    # can match the preset's actual output format (apples-to-apples).
    mc = re.search(r"--output-csp\s+(\S+)", args)
    if mc:
        spec["output_csp"] = mc.group(1)
    md = re.search(r"--output-depth\s+(\d+)", args)
    if md:
        spec["output_depth"] = int(md.group(1))
    return spec


def ffmpeg_comparable(preset_name: str, c: Optional[dict] = None) -> bool:
    """True if a preset is a fair target for a plain-ffmpeg upscale baseline —
    i.e. it does NOT do an SDR→HDR conversion. Upscale-only presets qualify."""
    return not parse_preset_spec(preset_name, c).get("hdr_convert")


def list_inputs(c: Optional[dict] = None) -> list[str]:
    """Files staged in input/ (video containers only)."""
    c = c or config()
    inp, _, _ = _workdir_paths(c)
    exts = {".mov", ".mp4", ".mkv", ".m4v", ".y4m", ".webm"}
    try:
        return sorted(p.name for p in inp.iterdir()
                      if p.is_file() and p.suffix.lower() in exts)
    except Exception:
        return []


# --- CR-064: generated preset matrix (Output Format × Super Resolution) -----
# Six combos (sdr|hdr × sd|hd|4k) generated from two Jon-authored colour
# templates by substituting ONLY `--output-res` and `--cbr` — OWL never
# authors encoder flags. Bitrate is COUPLED to the target (June-10 call),
# never user-chosen. Written under presets/generated/ so every file-based
# mechanism (read_preset_args / describe_preset / parse_preset_spec /
# preset_key provenance) works unchanged; list_presets' non-recursive glob
# keeps them out of the raw staged-preset listing.

_SR_TARGETS = {  # key → (label, "WxH", CBR kbps)
    "sd": ("SD", "854x480", 5000),
    "hd": ("HD", "1920x1080", 20000),
    "4k": ("4K", "3840x2160", 35000),
}
_OUTPUT_FORMATS = ("sdr", "hdr")
_GENERATED_DIR = "generated"

# Known-bad combos, excluded from generation until Jon's input-agnostic HDR
# template lands. 2026-06-10 bisect (1080p SDR input, GoS promo):
# `sdr_to_hdr=on` aborts pixop-live (rc 134, std::runtime_error immediately
# after the ×2 AOTI model loads) ONLY at a 4K target — SDR→4K, HDR→SD and
# HDR→HD all pass. An excluded combo simply doesn't generate, so the UI shows
# it as "not available yet" and Run disables. CR-064 open question #1.
_COMBO_EXCLUSIONS = {"hdr_4k"}


def _combo_preset_name(fmt: str, target: str, kbps: int) -> str:
    return f"{_GENERATED_DIR}/owl_{fmt}_{target}_{kbps // 1000}mbps.args"


def preset_origin(preset_name: str) -> str:
    return "generated" if str(preset_name).startswith(f"{_GENERATED_DIR}/") else "staged"


def _generate_preset_text(template_path: Path, res: str, kbps: int) -> str:
    """Template body with only the `--output-res` / `--cbr` lines replaced —
    everything else (incl. Jon's comments) byte-identical, so a diff against
    the template shows exactly the two substitutions."""
    out = []
    for raw in template_path.read_text().splitlines():
        s = raw.strip()
        if s.startswith("--output-res"):
            out.append(f"--output-res {res}")
        elif s.startswith("--cbr"):
            out.append(f"--cbr {kbps}")
        else:
            out.append(raw)
    return "\n".join(out) + "\n"


def generate_presets(c: Optional[dict] = None) -> dict:
    """(Re)generate the combo matrix into presets/generated/. Returns
    {"<fmt>_<target>": {preset, format, target, res, mbps, template}} for every
    combo whose colour template exists. Write-if-changed (no mtime churn);
    fail-soft per format — a missing template just drops that format's combos."""
    c = c or config()
    _, _, pre = _workdir_paths(c)
    combos: dict = {}
    for fmt in _OUTPUT_FORMATS:
        tpl = pre / c[f"template_{fmt}"]
        if not tpl.is_file():
            continue
        for tkey, (tlabel, res, kbps) in _SR_TARGETS.items():
            if f"{fmt}_{tkey}" in _COMBO_EXCLUSIONS:
                continue
            name = _combo_preset_name(fmt, tkey, kbps)
            try:
                text = _generate_preset_text(tpl, res, kbps)
                path = pre / name
                path.parent.mkdir(parents=True, exist_ok=True)
                if not path.exists() or path.read_text() != text:
                    path.write_text(text)
                combos[f"{fmt}_{tkey}"] = {
                    "preset": name,
                    "format": fmt.upper(),
                    "target": tlabel,
                    "res": res,
                    "mbps": kbps // 1000,
                    "template": c[f"template_{fmt}"],
                }
            except Exception:
                continue
    return combos


def resolve_combo(output_format: str, sr_target: str,
                  c: Optional[dict] = None) -> Optional[dict]:
    """Combo dict for a (format, target) pair, or None if not generatable."""
    fmt = str(output_format).lower()
    tgt = str(sr_target).lower()
    if fmt not in _OUTPUT_FORMATS or tgt not in _SR_TARGETS:
        return None
    return generate_presets(c).get(f"{fmt}_{tgt}")


# --- Preflight --------------------------------------------------------------

def _image_present(c: dict) -> bool:
    try:
        r = subprocess.run(["docker", "image", "inspect", c["image_tag"]],
                           capture_output=True, text=True, timeout=10)
        return r.returncode == 0
    except Exception:
        return False


def preflight(c: Optional[dict] = None) -> dict:
    """What's configured / runnable. Drives the page's graceful state.

    `ok_selftest` needs only the image (the `--check-device` probe). `ok_transcode`
    additionally needs a writable workdir + ≥1 preset + ≥1 input. NO license gate —
    the license is baked into the image.
    """
    c = c or config()
    ensure_workdir(c)
    inp, out, pre = _workdir_paths(c)

    image_present = _image_present(c)
    workdir_ok = (inp.is_dir() and out.is_dir() and pre.is_dir()
                  and os.access(inp, os.R_OK) and os.access(out, os.W_OK))
    license_present = Path(c["license_path"]).exists()
    presets = list_presets(c)
    inputs = list_inputs(c)
    combos = generate_presets(c)  # CR-064 — format×resolution matrix

    reasons = []
    if not image_present:
        reasons.append(f"docker image '{c['image_tag']}' not found")
    if not workdir_ok:
        reasons.append(f"workdir {c['workdir']} missing input/output/presets (or not writable)")
    if not license_present:
        reasons.append(f"no Pixop license.jwt at {c['license_path']}")
    if not presets:
        reasons.append(f"no *.args preset staged in {pre}")
    if not inputs:
        reasons.append(f"no input clip staged in {inp}")

    return {
        "image_tag": c["image_tag"],
        "image_present": image_present,
        "workdir_ok": workdir_ok,
        "license_present": license_present,
        "presets": presets,
        "inputs": inputs,
        "combos": combos,
        "ok_selftest": image_present,
        "ok_transcode": bool(image_present and workdir_ok and license_present and presets and inputs),
        # Informational only — a missing VQA sandbox must never block runs
        # (the score just goes absent), so this is NOT a reason and gates nothing.
        "vqa_ok": bool(c["vqa_enabled"] and _vqa_paths(c)),
        "reasons": reasons,
    }


# --- Self-test (plumbing only, no measurement, no license needed) -----------

def self_test(c: Optional[dict] = None) -> dict:
    """`docker run --rm --gpus all <tag> --check-device` — proves docker + GPU +
    image without a license and without measuring energy. The baked license is
    `max 1 instance`, so refuse if a measured run holds the lock."""
    c = c or config()
    if LOCK_FILE.exists():
        return {"ok": False, "returncode": None, "image_tag": c["image_tag"],
                "stdout_tail": "", "stderr_tail": "", "duration_s": 0.0,
                "error": "a measurement is in progress — try again when idle"}
    cmd = ["docker", "run", "--rm", "--gpus", "all", c["image_tag"], "--check-device"]
    t0 = time.time()
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except Exception as e:
        return {"ok": False, "returncode": None, "image_tag": c["image_tag"],
                "stdout_tail": "", "stderr_tail": str(e)[-_TAIL:],
                "duration_s": round(time.time() - t0, 1), "error": str(e)}
    return {
        "ok": r.returncode == 0,
        "returncode": r.returncode,
        "image_tag": c["image_tag"],
        "stdout_tail": (r.stdout or "")[-_TAIL:],
        "stderr_tail": (r.stderr or "")[-_TAIL:],
        "duration_s": round(time.time() - t0, 1),
    }


# --- Docker command + subprocess --------------------------------------------

def _output_name(input_name: str, preset_name: str) -> str:
    return f"{Path(input_name).stem}__{Path(preset_name).stem}.mp4"


def read_preset_args(preset_path) -> list[str]:
    """Parse an nvencc `.args` preset into a token list, mirroring Jon's
    run_pixop_nvencc.sh exactly: strip CR, trim, skip blank + full-line `#`
    comments, drop a trailing ` #...` comment, then whitespace-tokenize. The
    preset is expanded host-side into argv (NOT passed via `--option-file`),
    matching the verified working invocation."""
    args: list[str] = []
    for raw in Path(preset_path).read_text().splitlines():
        line = raw.rstrip("\r").strip()
        if not line or line.startswith("#"):
            continue
        if " #" in line:            # trailing inline comment
            line = line.split(" #", 1)[0].strip()
        if line:
            args.extend(line.split())
    return args


def build_pacer_cmd(input_name: str, c: Optional[dict] = None) -> list[str]:
    """Host-side 1x "faucet" for live mode: ffmpeg -re stream-copies the input's
    compressed packets to stdout at native frame rate. `-c copy` means NO decode,
    so it adds <0.5 W over idle (measured 0.1-0.2 W, below the noise floor) and is
    input-independent — nvencc still does its own decode, identical to batch."""
    c = c or config()
    inp, _, _ = _workdir_paths(c)
    ff = cfg.load().get("ffmpeg_bin", "ffmpeg")
    return [ff, "-re", "-i", str(inp / input_name), "-c", "copy", "-f", "mpegts", "-"]


def build_docker_cmd(input_name: str, preset_name: str, output_name: str,
                     c: Optional[dict] = None, live: bool = False) -> list[str]:
    """The verified container contract (from Jon's run_pixop_nvencc.sh):
      - the license is MOUNTED in at /opt/pixop/license.jwt:ro (not baked, not env),
      - the host workdir is a single mount at /mnt/host (so input/output/presets
        live under /mnt/host/{input,output,presets}),
      - the preset `.args` is expanded host-side into argv (NOT `--option-file`),
      - runtime flags: --network host, --init, --user <uid>:<gid> (outputs owned by
        the OWL service user), + the NVIDIA/UCX/log env. The PIXOP_LIVE_PULSE_*
        telemetry env in Jon's script is NOT required (verified) and is omitted.

    live=True: keep docker stdin open (`-i`) and read a piped mpegts stream
    (`--input-format mpegts -i -`) from the host pacer instead of the input file,
    so the encode runs at 1x realtime (the Pixop Live profile)."""
    c = c or config()
    base = Path(c["workdir"])
    _, _, pre = _workdir_paths(c)
    preset_args = read_preset_args(pre / preset_name)
    cmd = [
        "docker", "run", "--rm", "--gpus", "all", "--network", "host",
        "-v", f"{c['license_path']}:/opt/pixop/license.jwt:ro",
        "-v", f"{base}:/mnt/host",
        "--init",
    ]
    if live:
        cmd.append("-i")          # keep stdin open for the piped TS
    cmd += [
        "--user", f"{os.getuid()}:{os.getgid()}",
        "-e", "NVIDIA_DRIVER_CAPABILITIES=all",
        "-e", "UCX_ERROR_SIGNALS=SIGILL,SIGBUS,SIGFPE",
        "-e", "PIXOP_LOG_MODE=TERMINAL",
        c["image_tag"],
        *preset_args,
    ]
    cmd += (["--input-format", "mpegts", "-i", "-"] if live
            else ["-i", f"/mnt/host/input/{input_name}"])
    cmd += ["-o", f"/mnt/host/output/{output_name}"]
    return cmd


_DEFAULT_FF_BITRATE_KBPS = 10000   # fallback when a preset carries no --cbr

# CR-064 — (output_csp, output_depth) → NVENC input pixel format, so the ffmpeg
# baseline encodes at the SAME chroma subsampling + bit depth as the partner
# preset (4:2:2 10-bit needs the Blackwell NVENC; verified present in
# ffmpeg-master's hevc_nvenc). Unmapped combos fall back to the encoder
# default — the result card's probed pix_fmt shows the truth either way.
_NVENC_PIX_FMT = {
    ("yuv422", 10): "p210le",
    ("yuv420", 10): "p010le",
    ("yuv422", 8):  "nv16",
    ("yuv444", 10): "yuv444p10msble",
}


def _ffmpeg_pix_fmt(spec: dict) -> Optional[str]:
    """NVENC pixel format matching the preset's output, or None (encoder
    default). Nvidia-only — other vendors keep their default path."""
    if gpu.BACKEND.vendor != "nvidia":
        return None
    return _NVENC_PIX_FMT.get((spec.get("output_csp"), spec.get("output_depth")))


def _ffmpeg_output_name(input_name: str, preset_name: str, ff_filter: str) -> str:
    return f"{Path(input_name).stem}__{Path(preset_name).stem}__ff-{ff_filter}.mp4"


def build_ffmpeg_upscale_cmd(input_name: str, output_name: str,
                             target_w: int, target_h: int,
                             bitrate_kbps: Optional[int], ff_filter: str,
                             c: Optional[dict] = None, live: bool = False,
                             pix_fmt: Optional[str] = None) -> list[str]:
    """A traditional (non-ML) upscale baseline: ffmpeg's `scale` filter at the
    SAME target resolution + bitrate as the partner preset, encoded with HEVC
    (NVENC) so the ONLY variable vs the AI pass is the scaling algorithm
    (Lanczos / Bicubic interpolation vs learned super-resolution). Runs
    bare-metal on the host (no container), writing straight into the OWL output
    dir.  This is NOT an apples-to-apples for SDR→HDR presets — callers must gate
    on `ffmpeg_comparable` first (see the Tania call).

    live=True adds `-re` so the input is read at native frame rate (1× realtime),
    matching the partner Live profile for a paced comparison."""
    c = c or config()
    inp, out, _ = _workdir_paths(c)
    ff = cfg.load().get("ffmpeg_bin", "ffmpeg")
    flag = ff_filter if ff_filter in ("lanczos", "bicubic") else "lanczos"
    kbps = bitrate_kbps or _DEFAULT_FF_BITRATE_KBPS
    cmd = [ff, "-y"]
    if live:
        cmd.append("-re")
    # HEVC GPU encode, vendor-resolved via gpu.BACKEND so the baseline tracks
    # the installed card rather than hardcoding NVENC. -rc cbr is NVENC-specific
    # (VAAPI takes -b:v alone), so gate it on vendor; the bitrate target is
    # identical either way, keeping the scaling algorithm the only variable.
    enc = gpu.BACKEND.ffmpeg_encoder("h265")
    cmd += [
        "-i", str(inp / input_name),
        "-vf", f"scale={target_w}:{target_h}:flags={flag}",
        "-c:v", enc,
    ]
    if pix_fmt:
        # CR-064 — match the partner preset's chroma/depth (see _ffmpeg_pix_fmt)
        cmd += ["-pix_fmt", pix_fmt]
    if gpu.BACKEND.vendor == "nvidia":
        cmd += ["-rc", "cbr"]
    cmd += [
        "-b:v", f"{kbps}k",
        "-c:a", "copy",
        "-f", "mp4", str(out / output_name),
    ]
    return cmd


def _probe_dims(path) -> tuple[Optional[int], Optional[int]]:
    """(width, height) of a clip's first video stream, or (None, None)."""
    try:
        out = subprocess.run(
            [_ffprobe_bin(), "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height",
             "-of", "csv=p=0:s=x", str(path)],
            capture_output=True, text=True, timeout=10)
        val = out.stdout.strip()
        if "x" in val:
            w, h = val.split("x")[:2]
            return int(w), int(h)
    except Exception:
        pass
    return None, None


# --- Terminal complexity probes (post-measurement; NO energy impact) --------
# How "busy"/detailed the resulting file is — SI/TI (ITU-T P.910 spatial &
# temporal information, via ffmpeg's `siti` filter) + per-frame-type size stats
# (ffprobe). Run AFTER the measurement window closes (like probe_output_stream /
# compute_vmaf), so their decode draw never enters a reported energy figure.
# Parsing is split into pure helpers so it's unit-testable without ffmpeg.

_SITI_COMPLEXITY_TIMEOUT_S = 600


def _parse_siti_summary(text: str) -> Optional[dict]:
    """Pull {si_mean, si_max, ti_mean, ti_max} from `siti=print_summary=1`
    stderr. The summary is emitted twice (an empty init pass with `Total
    frames: 0` then the real one) — take the LAST block with a positive frame
    count. nan/unparseable → None per field; all-None → None."""
    best = None
    for m in re.finditer(r"Total frames:\s*(\d+)(.*?)(?=Total frames:|\Z)", text, re.S):
        if int(m.group(1)) > 0:
            best = m.group(2)
    if not best:
        return None
    parts = re.split(r"Temporal Information", best, maxsplit=1)
    si_seg, ti_seg = parts[0], (parts[1] if len(parts) > 1 else "")

    def _f(label, seg):
        m = re.search(label + r":\s*(\S+)", seg)
        if not m:
            return None
        try:
            v = float(m.group(1))
        except ValueError:
            return None
        return None if math.isnan(v) else round(v, 2)

    out = {"si_mean": _f("Average", si_seg), "si_max": _f("Max", si_seg),
           "ti_mean": _f("Average", ti_seg), "ti_max": _f("Max", ti_seg)}
    return out if any(v is not None for v in out.values()) else None


def _aggregate_frame_sizes(frames: list) -> Optional[dict]:
    """Per-frame-type size stats from a list of ffprobe frame dicts
    (pict_type + pkt_size). Bigger / denser frames ⇒ more complexity."""
    by = {"I": [], "P": [], "B": []}
    sizes = []
    for f in frames or []:
        s = f.get("pkt_size")
        if s is None:
            continue
        try:
            s = int(s)
        except (TypeError, ValueError):
            continue
        sizes.append(s)
        t = f.get("pict_type")
        if t in by:
            by[t].append(s)
    if not sizes:
        return None
    kb = lambda lst: round(sum(lst) / len(lst) / 1024, 1) if lst else None
    return {
        "frames": len(sizes),
        "keyframes": len(by["I"]),
        "mean_kb": round(sum(sizes) / len(sizes) / 1024, 1),
        "max_kb": round(max(sizes) / 1024, 1),
        "i_mean_kb": kb(by["I"]),
        "p_mean_kb": kb(by["P"]),
        "b_mean_kb": kb(by["B"]),
    }


def probe_siti(path, c: Optional[dict] = None) -> Optional[dict]:
    """SI/TI of a clip via ffmpeg's `siti` filter. Fail-soft to None."""
    ff = cfg.load().get("ffmpeg_bin", "ffmpeg")
    try:
        r = subprocess.run([ff, "-i", str(path), "-vf", "siti=print_summary=1",
                            "-f", "null", "-"], capture_output=True, text=True,
                           timeout=_SITI_COMPLEXITY_TIMEOUT_S)
    except Exception:
        return None
    return _parse_siti_summary(r.stderr or "")


def probe_frame_stats(path) -> Optional[dict]:
    """Per-frame-type size stats via ffprobe -show_frames. Fail-soft to None."""
    try:
        r = subprocess.run(
            [_ffprobe_bin(), "-v", "error", "-select_streams", "v:0",
             "-show_entries", "frame=pict_type,pkt_size", "-of", "json", str(path)],
            capture_output=True, text=True, timeout=_SITI_COMPLEXITY_TIMEOUT_S)
        frames = json.loads(r.stdout).get("frames", [])
    except Exception:
        return None
    return _aggregate_frame_sizes(frames)


def probe_complexity(path, c: Optional[dict] = None) -> Optional[dict]:
    """Resulting-file complexity: SI/TI + frame-size stats merged. Terminal,
    fail-soft — returns a partial dict, or None if both probes miss."""
    out = {}
    siti = probe_siti(path, c)
    if siti:
        out.update(siti)
    fr = probe_frame_stats(path)
    if fr:
        out.update(fr)
    return out or None


# --- A↔B differential quality (NOT vs ground truth — VMAF is wrong here) -----
# The two outputs are the SAME resolution, so PSNR/SSIM between them is a clean
# reference comparison: "how different is the AI output from the plain resize?"
# High PSNR (>~45 dB) / SSIM (~1.0) ⇒ near-identical; lower ⇒ the AI added detail
# the resize didn't. No quality VERDICT (we don't rank upscalers) — just a delta.

def _parse_psnr(text: str) -> Optional[float]:
    m = re.search(r"average:\s*(inf|[\d.]+)", text or "")
    if not m:
        return None
    if m.group(1) == "inf":
        return float("inf")
    try:
        return round(float(m.group(1)), 2)
    except ValueError:
        return None


def _parse_ssim(text: str) -> Optional[float]:
    m = re.search(r"SSIM .*?All:\s*([\d.]+)", text or "")
    if not m:
        return None
    try:
        return round(float(m.group(1)), 4)
    except ValueError:
        return None


def _run_ab_metric(path_a, path_b, metric: str) -> str:
    """One ffmpeg pass computing `metric` (psnr|ssim) between two equal-size
    clips, normalised to a common format/SAR first. Returns stderr (or '')."""
    ff = cfg.load().get("ffmpeg_bin", "ffmpeg")
    fc = ("[0:v]format=yuv420p,setsar=1[a];"
          "[1:v]format=yuv420p,setsar=1[b];[a][b]" + metric)
    try:
        r = subprocess.run([ff, "-i", str(path_a), "-i", str(path_b),
                            "-filter_complex", fc, "-f", "null", "-"],
                           capture_output=True, text=True,
                           timeout=_SITI_COMPLEXITY_TIMEOUT_S)
        return r.stderr or ""
    except Exception:
        return ""


def probe_ab_quality(path_a, path_b) -> Optional[dict]:
    """PSNR + SSIM between two equal-resolution outputs. `identical` flags the
    PSNR=inf (bit-identical) case so it stays JSON-safe. Fail-soft to None."""
    out = {}
    psnr = _parse_psnr(_run_ab_metric(path_a, path_b, "psnr"))
    if psnr is not None:
        if psnr == float("inf"):
            out["psnr_db"] = None
            out["identical"] = True
        else:
            out["psnr_db"] = psnr
    ssim = _parse_ssim(_run_ab_metric(path_a, path_b, "ssim"))
    if ssim is not None:
        out["ssim"] = ssim
    return out or None


# --- No-reference VQA (CompressedVQA-HDR) ------------------------------------
# Credit: CompressedVQA-HDR — Sun et al., arXiv:2507.11900, Apache 2.0. A
# learned NR model (HDR10 + SDR capable) scoring each file INDEPENDENTLY — the
# within-run relative indicator for enhancement runs, which have no ground-truth
# reference (VMAF N/A). Runs as a TERMINAL pass via subprocess to the sandboxed
# venv at vqa_dir (never loaded into the service process: VRAM released on exit,
# crash-isolated, vendor-portable — the script itself does cuda-if-available,
# which ROCm also satisfies). Fail-soft everywhere: no sandbox → no score.

_VQA_SCORE_RE = re.compile(r"Quality score:\s*(-?[\d.]+)")
_VQA_MODEL_LABEL = "CompressedVQA-HDR (NR)"


def _parse_vqa_score(text) -> Optional[float]:
    """Pull the score from VQA_NR.py stdout (warning noise may precede it)."""
    m = _VQA_SCORE_RE.search(text or "")
    if not m:
        return None
    try:
        return round(float(m.group(1)), 2)
    except ValueError:
        return None


def _vqa_paths(c: dict) -> Optional[tuple[Path, Path]]:
    """(venv_python, NR_dir) if the sandbox is complete, else None. The NR dir
    must be the cwd of the run (VQA_NR.py imports NR_model from cwd; ckpt paths
    are relative)."""
    root = Path(c["vqa_dir"])
    venv_python = root / "venv" / "bin" / "python"
    nr_dir = root / "CompressedVQA-HDR" / "NR"
    needed = [venv_python, nr_dir / "VQA_NR.py",
              nr_dir / "ckpts" / "NR_HDR_VQA.pth",
              nr_dir / "ckpts" / "NR_HDR_VQA.npy"]
    if all(p.exists() for p in needed):
        return venv_python, nr_dir
    return None


def probe_vqa_nr(path, c: Optional[dict] = None) -> Optional[dict]:
    """NR quality score for one clip, or None (disabled / sandbox missing /
    file missing / timeout / parse failure — the run must never fail on this)."""
    c = c or config()
    if not c.get("vqa_enabled"):
        return None
    paths = _vqa_paths(c)
    if paths is None or not Path(path).exists():
        return None
    venv_python, nr_dir = paths
    t0 = time.time()
    try:
        r = subprocess.run(
            [str(venv_python), "VQA_NR.py", "--distorted", str(path),
             "--model_path", "ckpts/NR_HDR_VQA.pth",
             "--profile_path", "ckpts/NR_HDR_VQA.npy"],
            cwd=str(nr_dir), capture_output=True, text=True,
            timeout=c["vqa_timeout_s"])
        score = _parse_vqa_score(r.stdout)
        if score is None:
            # Sandbox drift (unpatched VQA_NR.py, missing HF cache, …) shows up
            # here — log the tail so it's diagnosable, but stay fail-soft.
            print(f"WARN: vqa score parse failed for {path}: "
                  f"{(r.stderr or r.stdout or '')[-500:]}")
            return None
        return {"score": score, "model": _VQA_MODEL_LABEL,
                "duration_s": round(time.time() - t0, 1)}
    except Exception as e:
        print(f"WARN: vqa probe failed for {path}: {e}")
        return None


# NVEncC prints a summary line like
#   "encoded 705 frames, 51.91 fps, 18067.47 kbps, 63.27 MB"
# when the encode completes. That fps is the steady-state throughput (excludes
# container/cuDNN cold-start), which is what the realtime/Live verdict uses.
_ENCODE_STATS_RE = re.compile(r"encoded\s+(\d+)\s+frames?,\s*([\d.]+)\s*fps", re.IGNORECASE)


def parse_encode_stats(text: Optional[str]) -> Optional[dict]:
    """Pull {frames, fps} from NVEncC's completion summary, or None."""
    if not text:
        return None
    m = _ENCODE_STATS_RE.search(text)
    if not m:
        return None
    try:
        return {"frames": int(m.group(1)), "fps": round(float(m.group(2)), 2)}
    except ValueError:
        return None


def run_transcode_subprocess(cmd: list[str], timeout_s: int,
                             pacer_cmd: Optional[list[str]] = None) -> dict:
    """Run the docker transcode, capturing returncode + tails + NVEncC's encode
    fps. Batch mode (pacer_cmd=None) runs docker directly. Live mode pipes a
    host-side `ffmpeg -re -c copy` pacer into docker's stdin so the encode runs
    at 1x realtime (the pacer's draw is negligible — see build_pacer_cmd)."""
    t0 = time.time()
    out = err = ""
    rc: Optional[int] = None
    if pacer_cmd is None:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
            out, err, rc = r.stdout or "", r.stderr or "", r.returncode
        except subprocess.TimeoutExpired:
            err, rc = f"timed out after {timeout_s}s", None
    else:
        pacer = subprocess.Popen(pacer_cmd, stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL)
        proc = subprocess.Popen(cmd, stdin=pacer.stdout, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)
        pacer.stdout.close()   # let the pacer get SIGPIPE if docker exits first
        try:
            out, err = proc.communicate(timeout=timeout_s)
            rc = proc.returncode
        except subprocess.TimeoutExpired:
            proc.kill()
            out, err = proc.communicate()
            err = (err or "") + f"\ntimed out after {timeout_s}s"
            rc = None
        finally:
            pacer.terminate()
            try:
                pacer.wait(timeout=5)
            except Exception:
                pacer.kill()
    combined = (out or "") + "\n" + (err or "")
    return {
        "success": rc == 0,
        "returncode": rc,
        "duration_s": round(time.time() - t0, 1),
        "docker_cmd": " ".join(cmd),
        "live": pacer_cmd is not None,
        "stdout_tail": (out or "")[-_TAIL:] if rc != 0 else "",
        "stderr_tail": (err or "")[-_TAIL:] if rc != 0 else "",
        "encode_stats": parse_encode_stats(combined),
    }


# --- Realtime / Live feasibility --------------------------------------------

def probe_input_stream(path) -> Optional[dict]:
    """Input provenance (CR-064): codec / resolution / pix_fmt / colour
    transfer / duration of the source clip. Stamped on every result so "what
    actually went in" is recorded — it NEVER drives the UI (the six combos
    work on any input by design, the June-10 call). Terminal, fail-soft."""
    try:
        r = subprocess.run(
            [_ffprobe_bin(), "-v", "error", "-select_streams", "v:0",
             "-show_entries",
             "stream=codec_name,width,height,pix_fmt,color_transfer",
             "-show_entries", "format=duration", "-of", "json", str(path)],
            capture_output=True, text=True, timeout=15)
        j = json.loads(r.stdout)
        s = (j.get("streams") or [{}])[0]
        if not s:
            return None
        dur = (j.get("format") or {}).get("duration")
        transfer = s.get("color_transfer")
        return {
            "codec": s.get("codec_name"),
            "width": s.get("width"),
            "height": s.get("height"),
            "pix_fmt": s.get("pix_fmt"),
            "color_transfer": transfer,
            "duration_s": round(float(dur), 2) if dur else None,
            # PQ / HLG transfers = HDR; None when ffprobe doesn't say.
            "hdr": (transfer in ("smpte2084", "arib-std-b67")) if transfer else None,
        }
    except Exception:
        return None


def _probe_input(path) -> tuple[Optional[float], Optional[float]]:
    """(duration_s, source_fps) of an input clip, or (None, None). fps from the
    stream's r_frame_rate; reuses video._probe_duration for the duration."""
    duration = _probe_duration(path)
    fps = None
    try:
        out = subprocess.run(
            [_ffprobe_bin(), "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=r_frame_rate",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=10,
        )
        val = out.stdout.strip()
        if "/" in val:
            num, den = val.split("/", 1)
            fps = round(float(num) / float(den), 3) if float(den) else None
        elif val:
            fps = round(float(val), 3)
    except Exception:
        fps = None
    return duration, fps


def realtime_verdict(rtf: Optional[float]) -> str:
    """Live-feasibility verdict from the steady-state realtime factor."""
    if rtf is None:
        return "unknown"
    if rtf >= 1.15:
        return "live"        # keeps up with realtime + headroom
    if rtf >= 1.0:
        return "marginal"    # realtime, no headroom
    return "file"            # sub-realtime — batch/File only on this hardware


def build_realtime(content_s: Optional[float], source_fps: Optional[float],
                   encode_stats: Optional[dict], encode_wall_s: Optional[float],
                   live: bool = False) -> dict:
    """Realtime block.

    Batch: steady-state RTF (encode_fps / source_fps) is the headline feasibility
    metric (verdict live/marginal/file); wall-clock RTF is the cold-start caveat.

    Live (1x-paced): encode fps is pinned to the source rate, so headroom is
    meaningless — the question is whether the box SUSTAINED 1x (no back-pressure),
    i.e. wall ≈ content duration. verdict = live_sustained | live_behind."""
    fps = (encode_stats or {}).get("fps")
    frames = (encode_stats or {}).get("frames")
    rtf_steady = round(fps / source_fps, 2) if (fps and source_fps) else None
    rtf_wall = round(content_s / encode_wall_s, 2) if (content_s and encode_wall_s) else None
    if live:
        if rtf_wall is None:
            verdict = "unknown"
        else:
            verdict = "live_sustained" if rtf_wall >= 0.9 else "live_behind"
    else:
        primary = rtf_steady if rtf_steady is not None else rtf_wall
        verdict = realtime_verdict(primary)
    return {
        "live": live,
        "content_s": content_s,
        "source_fps": source_fps,
        "encode_fps": fps,
        "frame_count": frames,
        "rtf_steady": rtf_steady,
        "rtf_wall": rtf_wall,
        "verdict": verdict,
    }


# --- Measured run -----------------------------------------------------------

def _preset_known(preset_name: str, pf: dict) -> bool:
    """A runnable preset is either a staged .args file or one of the CR-064
    generated combo presets (which live under presets/generated/)."""
    if preset_name in pf["presets"]:
        return True
    return preset_name in {v["preset"] for v in (pf.get("combos") or {}).values()}


def _preset_args_soft(path) -> Optional[list]:
    """read_preset_args, fail-soft — provenance stamping must never kill a run."""
    try:
        return read_preset_args(path)
    except Exception:
        return None


async def _measured_pass(*, c: dict, job_id: str, jobs: Optional[dict],
                         input_name: str, input_path, output_name: str,
                         output_path, cmd: list[str], pacer_cmd, live: bool,
                         preset_key: str, preset_label: str, preset_detail: str,
                         update_stage: bool = True,
                         cooldown_stage: str = "cooldown",
                         do_cooldown: bool = True) -> dict:
    """One measured transcode/upscale pass through the standard harness (focus →
    baseline → 1 Hz poll → cooldown → ΔW/ΔE + confidence → terminal probe),
    returning the single-run result dict shape. Shared by the partner-GPU run
    AND the ffmpeg baseline so both go through the identical harness; the only
    difference between them is the command they wrap.

    update_stage=False lets a multi-pass caller (the compare runner) own the
    coarse jobs[*]['stage'] while this still reports its fine step via
    jobs[*]['substage']; `cooldown_stage` is the stage label the cooldown writes
    (so the coarse stage stays stable for the compare progress).
    do_cooldown=False skips the trailing cooldown — pointless after the LAST
    measured pass, since no measurement follows it (result['cooldown'] = None)."""
    def _stage(name):
        if jobs is not None:
            jobs[job_id]["substage"] = name
            if update_stage:
                jobs[job_id]["stage"] = name

    _stage("baseline")
    stopped = focus_mode_enter()
    baseline = await measure_baseline(polls=c["baseline_polls"])
    LOCK_FILE.write_text(job_id)
    try:
        _stage("transcoding")
        stop_event = asyncio.Event()
        poll_task = asyncio.create_task(poll_during_task(stop_event))
        t_start = time.time()
        transcode_result = await asyncio.get_event_loop().run_in_executor(
            None, lambda: run_transcode_subprocess(cmd, c["docker_timeout_s"],
                                                   pacer_cmd=pacer_cmd))
        t_end = time.time()
        stop_event.set()
        readings = await poll_task

        cd = None
        if do_cooldown:
            _stage("cooldown")
            cd = await cooldown_between_runs(
                fixed_seconds=c["cooldown_s"], reference_w=baseline["w_base"],
                stage=cooldown_stage, jobs=jobs, job_id=job_id,
            )
    finally:
        LOCK_FILE.unlink(missing_ok=True)
        asyncio.get_event_loop().run_in_executor(None, focus_mode_exit, stopped)

    # --- Energy (identical formula to video.run_single) ---
    delta_t = round(t_end - t_start, 1)
    w_base = baseline["w_base"]
    task_samples_w = [round(r["watts"], 2) for r in readings]
    baseline_samples_w = baseline.get("baseline_samples_w")
    w_task = sum(r["watts"] for r in readings) / len(readings) if readings else w_base
    delta_w = round(w_task - w_base, 2)
    delta_e_wh = round(delta_w * (delta_t / 3600), 4)
    conf = confidence(delta_w, len(readings), w_base,
                      baseline_samples_w=baseline_samples_w,
                      task_samples_w=task_samples_w)

    cpu_temps = [r["cpu_tctl"] for r in readings if r.get("cpu_tctl")]
    gpu_temps = [r["gpu_junction"] for r in readings if r.get("gpu_junction")]
    gpu_ppts = [r["gpu_ppt_w"] for r in readings if r.get("gpu_ppt_w")]

    # --- Terminal probe (after lock released — never polled) ---
    _stage("probe")
    out_size_mb = round(output_path.stat().st_size / 1024 / 1024, 2) \
        if output_path.exists() and output_path.stat().st_size > 0 else None
    stream = probe_output_stream(output_path)
    # Realtime / Live feasibility — encode throughput vs the source frame rate.
    # ffprobe of the input runs here (post-measurement), so it never enters energy.
    content_s, source_fps = _probe_input(input_path)
    realtime = build_realtime(content_s, source_fps,
                              transcode_result.get("encode_stats"),
                              transcode_result.get("duration_s"), live=live)
    # NB: no VMAF here. For super-resolution there is no ground-truth reference —
    # VMAF vs a bicubic-upscaled source would penalise the AI detail the
    # enhancement adds, so it would be a misleading quality number. Energy is the
    # headline; output stream params are the provenance. (Honest-metric call.)

    if update_stage:
        _stage("done")

    return {
        "mode": "enhance",
        "job_id": job_id,
        "baseline": baseline,
        "cooldown": cd,
        "result": {
            "preset_key": preset_key,
            "preset_label": preset_label,
            "preset_detail": preset_detail,
            "live": live,
            "input_name": input_name,
            "output_name": output_name,
            "transcode": transcode_result,
            "output_size_mb": out_size_mb,
            "stream": stream,
            "realtime": realtime,
            "energy": {
                "w_base": round(w_base, 2),
                "w_task": round(w_task, 2),
                "delta_w": round(delta_w, 2),
                "delta_t_s": delta_t,
                "delta_e_wh": delta_e_wh,
                "poll_count": len(readings),
                "baseline_samples_w": baseline_samples_w,
                "task_samples_w": task_samples_w,
                "confidence": conf,
            },
            "thermals": {
                "cpu_base": baseline["cpu_temp_base"],
                "cpu_peak": round(max(cpu_temps), 1) if cpu_temps else None,
                "cpu_mean": round(sum(cpu_temps) / len(cpu_temps), 1) if cpu_temps else None,
                "gpu_base": baseline["gpu_temp_base"],
                "gpu_peak": round(max(gpu_temps), 1) if gpu_temps else None,
                "gpu_mean": round(sum(gpu_temps) / len(gpu_temps), 1) if gpu_temps else None,
                "gpu_ppt_mean_w": round(sum(gpu_ppts) / len(gpu_ppts), 1) if gpu_ppts else None,
                "gpu_ppt_peak_w": round(max(gpu_ppts), 1) if gpu_ppts else None,
            },
        },
        "scope": SCOPE,
    }


async def run_enhance_measurement(input_name: str, preset_name: str,
                                  job_id: str, jobs: Optional[dict] = None,
                                  live: bool = False) -> dict:
    """Measure the energy of one partner GPU transcode/upscale.

    Validates input/preset, builds the verified docker command, then delegates to
    the shared `_measured_pass` harness. Returns a dict shaped like the video
    single result so the page's render helpers + persist's CO2e/gpu_hardware
    stamping work unchanged.
    """
    c = config()
    pf = preflight(c)
    if not pf["ok_transcode"]:
        raise RuntimeError("partner transcode not configured: " + "; ".join(pf["reasons"]))
    if input_name not in pf["inputs"]:
        raise RuntimeError(f"unknown input: {input_name!r}")
    if not _preset_known(preset_name, pf):
        raise RuntimeError(f"unknown preset: {preset_name!r}")

    inp, out, pre = _workdir_paths(c)
    output_name = _output_name(input_name, preset_name)
    cmd = build_docker_cmd(input_name, preset_name, output_name, c, live=live)
    pacer_cmd = build_pacer_cmd(input_name, c) if live else None

    # do_cooldown=False — same rule as the compare's last pass and video's
    # all-codecs loop: no trailing cooldown after the LAST measured pass,
    # since nothing is measured after it (probe + VQA are terminal/decode-only;
    # the next job protects itself via its own baseline / wait-for-idle).
    res = await _measured_pass(
        c=c, job_id=job_id, jobs=jobs, input_name=input_name,
        input_path=inp / input_name, output_name=output_name,
        output_path=out / output_name, cmd=cmd, pacer_cmd=pacer_cmd, live=live,
        preset_key=preset_name,
        preset_label=("Partner GPU transcode / upscale"
                      + (" · Live (1× paced)" if live else "")),
        preset_detail=preset_name, update_stage=True, do_cooldown=False)

    # NR quality (CompressedVQA-HDR) on input + output — terminal, post-lock,
    # fail-soft (fields nullable). Reuses the existing "probe" stage index.
    if jobs is not None:
        jobs[job_id]["stage"] = "probe"
        jobs[job_id]["substage"] = "vqa"
    res["result"]["source_vqa"] = probe_vqa_nr(inp / input_name, c)
    output_path = out / output_name
    tc_ok = bool((res["result"].get("transcode") or {}).get("success")
                 and output_path.exists())
    res["result"]["vqa"] = probe_vqa_nr(output_path, c) if tc_ok else None
    # CR-064 provenance — the exact args used + where the preset came from +
    # what the input actually was (never drives behaviour; record-keeping).
    res["result"]["preset_args"] = _preset_args_soft(pre / preset_name)
    res["result"]["preset_origin"] = preset_origin(preset_name)
    res["result"]["input_stream"] = probe_input_stream(inp / input_name)
    if jobs is not None:
        jobs[job_id]["stage"] = "done"
    return res


# --- Compare: ML / partner upscale vs traditional ffmpeg upscale ------------

def _resolve_target_dims(spec: dict, ml: dict, input_path) -> tuple[int, int]:
    """Target W×H for the ffmpeg baseline. Prefer the partner output's ACTUAL
    dims (guarantees both outputs land at identical resolution); else the
    preset's explicit --output-res; else source dims × scale_factor (even)."""
    s = (ml.get("result") or {}).get("stream") or {}
    if s.get("width") and s.get("height"):
        return int(s["width"]), int(s["height"])
    if spec.get("width") and spec.get("height"):
        return int(spec["width"]), int(spec["height"])
    sw, sh = _probe_dims(input_path)
    f = spec.get("scale_factor") or 2.0
    if sw and sh:
        return int(sw * f) // 2 * 2, int(sh * f) // 2 * 2
    return 1920, 1080


def _build_comparison(ml: dict, ff: dict) -> dict:
    """The head-to-head summary: energy, file size, duration — plus a quality
    slot deliberately left TBD (no native ground-truth reference for upscaling;
    VMAF N/A — the Tania call). Ratios are ML ÷ traditional."""
    mr = ml.get("result") or {}
    fr = ff.get("result") or {}
    me = mr.get("energy") or {}
    fe = fr.get("energy") or {}
    ml_wh, ff_wh = me.get("delta_e_wh"), fe.get("delta_e_wh")
    ml_mb, ff_mb = mr.get("output_size_mb"), fr.get("output_size_mb")
    return {
        "ml_delta_e_wh": ml_wh,
        "ff_delta_e_wh": ff_wh,
        "energy_ratio": round(ml_wh / ff_wh, 2) if (ml_wh and ff_wh) else None,
        "ml_size_mb": ml_mb,
        "ff_size_mb": ff_mb,
        "size_ratio": round(ml_mb / ff_mb, 2) if (ml_mb and ff_mb) else None,
        "ml_delta_t_s": me.get("delta_t_s"),
        "ff_delta_t_s": fe.get("delta_t_s"),
        "quality": "TBD",
        "quality_note": ("No native ground-truth reference for upscaling — "
                         "perceptual quality is for the viewer to judge (VMAF N/A)."),
    }


async def run_enhance_compare_measurement(input_name: str, preset_name: str,
                                          job_id: str, jobs: Optional[dict] = None,
                                          live: bool = False,
                                          ff_filter: str = "lanczos") -> dict:
    """Single comparison run: the partner ML/GPU upscale vs a traditional
    ffmpeg `scale` (Lanczos/Bicubic) at the SAME resolution + bitrate. Two
    sequential measured passes (each with its own baseline + cooldown so they're
    cleanly separated), then a head-to-head summary. Gated to upscale-only
    presets — SDR→HDR presets aren't apples-to-apples for plain ffmpeg.
    """
    c = config()
    pf = preflight(c)
    if not pf["ok_transcode"]:
        raise RuntimeError("partner transcode not configured: " + "; ".join(pf["reasons"]))
    if input_name not in pf["inputs"]:
        raise RuntimeError(f"unknown input: {input_name!r}")
    if not _preset_known(preset_name, pf):
        raise RuntimeError(f"unknown preset: {preset_name!r}")
    spec = parse_preset_spec(preset_name, c)
    if spec.get("hdr_convert"):
        raise RuntimeError("ffmpeg comparison supports upscale-only presets — "
                           "this preset does an SDR→HDR conversion")
    if ff_filter not in ("lanczos", "bicubic"):
        ff_filter = "lanczos"

    inp, out, pre = _workdir_paths(c)
    input_path = inp / input_name

    # --- pass 1: ML / partner GPU upscale ---
    if jobs is not None:
        jobs[job_id]["stage"] = "ml"
    ml_output = _output_name(input_name, preset_name)
    ml_cmd = build_docker_cmd(input_name, preset_name, ml_output, c, live=live)
    ml_pacer = build_pacer_cmd(input_name, c) if live else None
    ml = await _measured_pass(
        c=c, job_id=job_id, jobs=jobs, input_name=input_name,
        input_path=input_path, output_name=ml_output,
        output_path=out / ml_output, cmd=ml_cmd, pacer_cmd=ml_pacer, live=live,
        preset_key=preset_name,
        preset_label="AI / ML enhance" + (" · Live 1×" if live else ""),
        preset_detail=preset_name, update_stage=False, cooldown_stage="ml")

    # --- pass 2: traditional ffmpeg upscale (same res + bitrate) ---
    if jobs is not None:
        jobs[job_id]["stage"] = "ffmpeg"
    tgt_w, tgt_h = _resolve_target_dims(spec, ml, input_path)
    ff_output = _ffmpeg_output_name(input_name, preset_name, ff_filter)
    ff_cmd = build_ffmpeg_upscale_cmd(input_name, ff_output, tgt_w, tgt_h,
                                      spec.get("bitrate_kbps"), ff_filter, c, live=live,
                                      pix_fmt=_ffmpeg_pix_fmt(spec))
    ff = await _measured_pass(
        c=c, job_id=job_id, jobs=jobs, input_name=input_name,
        input_path=input_path, output_name=ff_output,
        output_path=out / ff_output, cmd=ff_cmd, pacer_cmd=None, live=live,
        preset_key=f"ffmpeg:{ff_filter}",
        preset_label=f"Traditional upscale (ffmpeg {ff_filter})"
                     + (" · Live 1×" if live else ""),
        preset_detail=f"scale={tgt_w}:{tgt_h}:flags={ff_filter}",
        update_stage=False, cooldown_stage="ffmpeg", do_cooldown=False)

    # --- terminal analysis (post-measurement; no energy impact) ---
    # Complexity (SI/TI + frame-size) of source + both outputs, and an A↔B
    # differential (PSNR/SSIM) so the energy gap can be read against how much
    # the outputs actually differ. All decode-only; runs after the lock is gone.
    if jobs is not None:
        jobs[job_id]["stage"] = "analyse"
    ml_ok = bool((ml["result"].get("transcode") or {}).get("success") and ml["result"].get("output_name"))
    ff_ok = bool((ff["result"].get("transcode") or {}).get("success") and ff["result"].get("output_name"))
    if ml_ok:
        ml["result"]["complexity"] = probe_complexity(out / ml_output, c)
    if ff_ok:
        ff["result"]["complexity"] = probe_complexity(out / ff_output, c)
    source_complexity = probe_complexity(input_path, c)
    ab_quality = probe_ab_quality(out / ml_output, out / ff_output) if (ml_ok and ff_ok) else None

    # NR quality (CompressedVQA-HDR) — scores source + both outputs
    # independently. Terminal like the probes above; all fields nullable.
    if jobs is not None:
        jobs[job_id]["substage"] = "vqa"
    source_vqa = probe_vqa_nr(input_path, c)
    ml["result"]["vqa"] = probe_vqa_nr(out / ml_output, c) if ml_ok else None
    ff["result"]["vqa"] = probe_vqa_nr(out / ff_output, c) if ff_ok else None

    # CR-064 provenance — exact AI-side args + preset origin + what the input
    # actually was. The ffmpeg side's full command is already in its
    # transcode.docker_cmd.
    ml["result"]["preset_args"] = _preset_args_soft(pre / preset_name)
    ml["result"]["preset_origin"] = preset_origin(preset_name)
    input_stream = probe_input_stream(input_path)

    if jobs is not None:
        jobs[job_id]["stage"] = "done"

    comparison = _build_comparison(ml, ff)
    comparison["ab_quality"] = ab_quality
    return {
        "mode": "enhance_compare",
        "job_id": job_id,
        "live": live,
        "input_name": input_name,
        "preset_key": preset_name,
        "ff_filter": ff_filter,
        "target_res": f"{tgt_w}x{tgt_h}",
        "source_complexity": source_complexity,
        "source_vqa": source_vqa,
        "input_stream": input_stream,
        "ml": ml,
        "ffmpeg": ff,
        "comparison": comparison,
        "scope": SCOPE,
    }
