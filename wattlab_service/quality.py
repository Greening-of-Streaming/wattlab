"""quality.py — the single home for terminal-pass quality metrics.

One source of truth for BOTH quality-scoring families (the read_sensors
pattern — per-module wrappers in video.py / pixop.py delegate here):

  - Full-reference:  compute_vmaf (+ optional compute_psnr_ssim) — needs a
    pristine reference; model + binary are settings-selected so a VMAF model
    upgrade (v0.6.1 → v1.0.16) or rollback is a settings flip, not a code hunt.
  - No-reference:    probe_vqa_nr (CompressedVQA-HDR) — scores one file
    independently; the only option for uploads/enhancement with no reference.

Shared contract, inherited from CR-044 and enforced on every function here:
  * TERMINAL PASS ONLY — callers invoke these after a job's measurement
    window has closed (lock released, focus exited). Their CPU draw is never
    polled, so it cannot enter a reported energy figure.
  * FAIL-SOFT — any failure returns None (or {}), never an exception that
    could kill a measured run's persistence.

Model / binary selection (VMAF):
  * `vmaf_model` setting: "v0" (libvmaf built-in vmaf_v0.6.1), "v1"
    (vmaf_v1.0.16 file models under `vmaf_model_dir`), or an absolute path
    to any libvmaf model json.
  * `vmaf_ffmpeg_bin` setting: scoring-only ffmpeg. v1 models need libvmaf
    >= 3.2.0 (the Speed_chroma extractor), newer than the pinned encode
    binary — and the encode binary (`ffmpeg_bin`) must NEVER be bumped just
    for scoring: binary changes confound energy results. Empty/missing →
    falls back to `ffmpeg_bin` (fine for v0).
  * Every score's model identity is returned by `vmaf_model_id()`; callers
    stamp it into results as `vmaf_model`. Stored results WITHOUT the field
    predate provenance and are all vmaf_v0.6.1 (the only model OWL ever ran
    before 2026-07-17).
"""
import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional

import settings as cfg


# --- binary + model resolution ----------------------------------------------

def _encode_bin(s: dict) -> str:
    return s.get("ffmpeg_bin", "ffmpeg")


def _scoring_bin(s: dict) -> str:
    """The ffmpeg used for scoring. Falls back to the encode binary when no
    dedicated scoring binary is configured (or it vanished from disk)."""
    b = s.get("vmaf_ffmpeg_bin") or ""
    if b:
        if Path(b).exists():
            return b
        print(f"WARN: vmaf_ffmpeg_bin {b} missing — scoring via ffmpeg_bin")
    return _encode_bin(s)


def _ffprobe_bin(s: dict) -> str:
    """ffprobe sibling of the ENCODE ffmpeg (probing is metadata-only, and the
    scoring-binary tree ships no ffprobe), else PATH `ffprobe`."""
    bin_path = _encode_bin(s)
    candidate = Path(bin_path).with_name("ffprobe") if "/" in bin_path else Path("ffprobe")
    return str(candidate) if (candidate.exists() or "/" not in bin_path) else "ffprobe"


# variant → (v1 model filename, v0 libvmaf `version=` token or None=builtin)
_VARIANTS = {
    "hd":  ("vmaf_v1.0.16_3d0h.json", None),             # 1080p, 3H viewing
    "uhd": ("vmaf_v1.0.16_1d5h_2160.json", "vmaf_4k_v0.6.1"),  # 4K, 1.5H
}


def _resolve_model(s: dict, variant: str = "hd"):
    """→ (libvmaf model option or None-for-builtin-default, provenance id).

    A configured-but-missing v1 model file falls back to v0 WITH a warning —
    the stamped provenance stays honest either way (never mislabel a score;
    a silently wrong model id would corrupt the score currency)."""
    v1_file, v0_version = _VARIANTS.get(variant, _VARIANTS["hd"])
    tok = str(s.get("vmaf_model", "v0") or "v0").strip()
    if tok.endswith(".json"):
        p = Path(tok)
        if p.exists():
            return f"path={p}", p.stem
        print(f"WARN: vmaf_model {tok} missing — falling back to v0")
        tok = "v0"
    if tok == "v1":
        p = Path(s.get("vmaf_model_dir", "/srv/data/owl/vmaf/model")) / v1_file
        if p.exists():
            return f"path={p}", p.stem
        print(f"WARN: v1 model {p} missing — falling back to v0")
    # v0: built-in default for HD; explicit version token for the 4K model
    if v0_version:
        return f"version={v0_version}", v0_version
    return None, "vmaf_v0.6.1"


def vmaf_model_id(s: Optional[dict] = None, variant: str = "hd") -> str:
    """Provenance id of the model compute_vmaf would use right now — callers
    persist this next to the score as `vmaf_model`."""
    if s is None:
        s = cfg.load()
    return _resolve_model(s, variant)[1]


# --- full-reference: VMAF ----------------------------------------------------

def _probe_dims(path) -> Optional[tuple]:
    """(width, height) of the first video stream's display frame, or None."""
    try:
        out = subprocess.run(
            [_ffprobe_bin(cfg.load()), "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0",
             str(path)],
            capture_output=True, text=True, timeout=10,
        )
        parts = out.stdout.strip().split("x")
        if out.returncode == 0 and len(parts) >= 2:
            return int(parts[0]), int(parts[1])
    except Exception:
        pass
    return None


def _parse_vmaf_log(log_path) -> Optional[float]:
    """Pull the pooled-mean VMAF from a libvmaf json log; None if unparseable."""
    try:
        data = json.loads(Path(log_path).read_text())
        mean = data.get("pooled_metrics", {}).get("vmaf", {}).get("mean")
        if mean is not None:
            return round(float(mean), 2)
        scores = [f.get("metrics", {}).get("vmaf") for f in data.get("frames", [])]
        scores = [x for x in scores if x is not None]
        if scores:
            return round(sum(scores) / len(scores), 2)
    except Exception:
        pass
    return None


def _fr_prep(tw: int, th: int) -> str:
    """Shared [d][r] prep for all FR metrics. The distorted is *cropped* (not
    scaled) to its own delivered WxH and the reference is scaled to match.
    Cropping strips VAAPI macroblock padding — the GPU HEVC path decodes
    1080->1088, which otherwise trips libvmaf with "input height must match"
    — without resampling the signal we're measuring. Verified on a real
    CPU-vs-GPU H.265 run 2026-05-22 (CPU 91.48 / GPU 91.31)."""
    return (
        f"[0:v]crop={tw}:{th}:0:0,setpts=PTS-STARTPTS[d];"
        f"[1:v]scale={tw}:{th}:flags=bicubic,setpts=PTS-STARTPTS[r];"
    )


def compute_vmaf(distorted, reference, s: Optional[dict] = None,
                 variant: str = "hd") -> Optional[float]:
    """Pooled-mean VMAF of `distorted` vs `reference`, or None on any failure.

    QA only — terminal pass, see the module contract. The model (v0/v1) and
    scoring binary come from settings; persist `vmaf_model_id()` alongside
    any score you store. `variant="uhd"` selects the 4K model family."""
    if s is None:
        s = cfg.load()
    if not s.get("vmaf_enabled", True):
        return None
    distorted, reference = Path(distorted), Path(reference)
    if not (distorted.exists() and reference.exists()):
        return None

    dims = _probe_dims(distorted)   # display dims (1920x1080 for every preset)
    if dims is None:
        return None
    tw, th = dims

    sub = int(s.get("vmaf_n_subsample", 1) or 1)
    nt = int(s.get("vmaf_n_threads", 12) or 12)
    sub_opt = f":n_subsample={sub}" if sub > 1 else ""
    model_opt, _ = _resolve_model(s, variant)
    model_arg = f":model={model_opt}" if model_opt else ""

    fd, log = tempfile.mkstemp(prefix="owl_vmaf_", suffix=".json")
    os.close(fd)
    log = Path(log)
    lavfi = (
        _fr_prep(tw, th)
        + f"[d][r]libvmaf=n_threads={nt}{sub_opt}{model_arg}"
          f":log_fmt=json:log_path={log}"
    )
    cmd = [_scoring_bin(s), "-y", "-i", str(distorted), "-i", str(reference),
           "-lavfi", lavfi, "-f", "null", "-"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        score = _parse_vmaf_log(log)
        if score is None and proc.stderr and "VMAF score:" in proc.stderr:
            try:
                score = round(float(proc.stderr.split("VMAF score:")[-1].split()[0]), 2)
            except Exception:
                score = None
        return score
    except Exception:
        return None
    finally:
        log.unlink(missing_ok=True)


# --- full-reference: PSNR / SSIM (model-free cross-checks) -------------------

def compute_psnr_ssim(distorted, reference, s: Optional[dict] = None) -> dict:
    """{"psnr_db": float|None, "ssim": float} — subset on partial failure, {}
    on total failure. Model-free FR cross-checks (ported from the S48 offline
    fr_score.py so ground-truth scoring shares the one funnel). psnr_db is
    None when the clips are identical (ffmpeg reports `inf`)."""
    if s is None:
        s = cfg.load()
    distorted, reference = Path(distorted), Path(reference)
    if not (distorted.exists() and reference.exists()):
        return {}
    dims = _probe_dims(distorted)
    if dims is None:
        return {}
    tw, th = dims
    out: dict = {}

    def _run(graph: str) -> str:
        r = subprocess.run(
            [_scoring_bin(s), "-i", str(distorted), "-i", str(reference),
             "-lavfi", _fr_prep(tw, th) + graph, "-f", "null", "-"],
            capture_output=True, text=True, timeout=600)
        return r.stderr or ""

    try:
        m = re.search(r"average:([\d.]+|inf)", _run("[d][r]psnr"))
        if m:
            out["psnr_db"] = None if m.group(1) == "inf" else round(float(m.group(1)), 2)
        m = re.search(r"All:([\d.]+)", _run("[d][r]ssim"))
        if m:
            out["ssim"] = round(float(m.group(1)), 4)
    except Exception:
        pass
    return out


# --- no-reference: CompressedVQA-HDR -----------------------------------------
# Credit: CompressedVQA-HDR — Sun et al., arXiv:2507.11900, Apache 2.0. A
# learned NR model (HDR10 + SDR capable) scoring each file INDEPENDENTLY — the
# within-run relative indicator for enhancement runs, which have no ground-truth
# reference (VMAF N/A). Runs via subprocess to the sandboxed venv at vqa_dir
# (never loaded into the service process: VRAM released on exit, crash-isolated,
# vendor-portable — the script itself does cuda-if-available, which ROCm also
# satisfies). Fail-soft everywhere: no sandbox → no score.

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
    if c is None:
        import pixop  # lazy: pixop imports quality at module load
        c = pixop.config()
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
