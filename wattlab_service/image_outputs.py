"""
image_outputs.py — full-size images from warm-model image sessions (owner 2026-10-29).

A session measures many images but used to keep only a 256 px thumbnail of the
last one, so two machines' outputs could not be inspected or compared. Each
session runner now hands over the FIRST image of every prompt at full size,
after the measurement window has closed (no encoding inside the window). That
image's seed is the same on every stack, so two runs pair up image for image.

Files live beside the results: results/image_outputs/{job_id}/p{n}.png. A
result produced on a peer keeps its files there; this node fetches them over
the signed peer API on first view and caches them.

Pair score: ffmpeg SSIM + PSNR between same-seed images. Only meaningful when
both runs drew the SAME starting noise — the diffusers runner draws it on the
CPU (torch.Generator), identical on CUDA and MPS; mflux draws it with MLX's
RNG, so the same seed gives a different picture and the pair is reported as
not comparable rather than as a misleading low score.
"""
import base64
import hashlib
import re
import shutil
import subprocess
from pathlib import Path

import persist

DIR = persist.RESULTS_DIR / "image_outputs"
_JOB_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _job_dir(job_id: str) -> Path | None:
    return DIR / job_id if _JOB_RE.match(job_id or "") else None


def save(job_id: str, fulls: list) -> list:
    """Write the runner's {"ev": "full"} events; return the result's `outputs` list."""
    d = _job_dir(job_id)
    if d is None or not fulls:
        return []
    d.mkdir(parents=True, exist_ok=True)
    out = []
    for ev in sorted(fulls, key=lambda e: e["p"]):
        raw = base64.b64decode(ev["png_b64"])
        name = f"p{int(ev['p'])}.png"
        (d / name).write_bytes(raw)
        out.append({"p": int(ev["p"]), "seed": ev.get("seed"), "file": name,
                    "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
    return out


def local_path(job_id: str, p: int) -> Path | None:
    d = _job_dir(job_id)
    f = d / f"p{int(p)}.png" if d is not None else None
    return f if f is not None and f.is_file() else None


def fetch(result: dict, p: int) -> Path | None:
    """The file for prompt `p` of `result`: local copy, else pulled once from
    the peer that produced it (cached here)."""
    job_id = result.get("job_id") or ""
    f = local_path(job_id, p)
    if f is not None:
        return f
    if not any(o.get("p") == p for o in result.get("outputs") or []):
        return None
    import hosts
    import peer
    hid = (result.get("host") or {}).get("id")
    host = hosts.get(hid) if hid and hid != hosts.local_host().get("id") else None
    if not host or host.get("driver") != "peer":
        return None
    try:
        status, ctype, body = peer.forward(host, "GET", f"/peer/image-output/{job_id}/{int(p)}",
                                           timeout=30)
    except Exception:
        return None
    if status != 200 or not body:
        return None
    d = _job_dir(job_id)
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"p{int(p)}.png"
    f.write_bytes(body)
    return f


def _noise(r: dict) -> str | None:
    if (r.get("generation") or {}).get("noise"):
        return r["generation"]["noise"]
    rt = (r.get("engine") or {}).get("runtime") or ""
    return "mlx" if rt.startswith("mflux") else "torch-cpu" if rt.startswith("diffusers") else None


def _ssim_psnr(a: Path, b: Path) -> dict | None:
    ff = shutil.which("ffmpeg")
    if ff is None:
        return None
    cmd = [ff, "-hide_banner", "-nostats", "-i", str(a), "-i", str(b), "-lavfi",
           "[0:v]split[a0][a1];[1:v]split[b0][b1];[a0][b0]ssim;[a1][b1]psnr", "-f", "null", "-"]
    try:
        err = subprocess.run(cmd, capture_output=True, text=True, timeout=60).stderr
    except Exception:
        return None
    s = re.search(r"SSIM .*All:([0-9.]+)", err)
    p = re.search(r"PSNR .*average:([0-9.]+|inf)", err)
    if not s or not p:
        return None
    return {"ssim": round(float(s.group(1)), 4),
            "psnr_db": None if p.group(1) == "inf" else round(float(p.group(1)), 2)}


def pair(a: dict, b: dict) -> dict:
    """Compare two session results image for image."""
    why = []
    if a.get("model_key") != b.get("model_key"):
        why.append("different models")
    ga, gb = a.get("generation") or {}, b.get("generation") or {}
    if (ga.get("size"), ga.get("steps")) != (gb.get("size"), gb.get("steps")):
        why.append("different size or steps")
    na, nb = _noise(a), _noise(b)
    if na != nb:
        why.append("different starting noise (MLX vs PyTorch random generator): "
                   "the same seed draws a different picture, so pixels cannot be compared")
    oa = {o["p"]: o for o in a.get("outputs") or []}
    ob = {o["p"]: o for o in b.get("outputs") or []}
    if not oa or not ob:
        why.append("full-size images were not kept for one of the runs")
    if why:
        return {"comparable": False, "reasons": why}
    pa, pb = a.get("prompts") or [], b.get("prompts") or []
    pairs = []
    for p in sorted(set(oa) & set(ob)):
        if p >= len(pa) or p >= len(pb) or pa[p] != pb[p] or oa[p].get("seed") != ob[p].get("seed"):
            continue
        row = {"p": p, "prompt": pa[p], "seed": oa[p].get("seed"),
               "identical": oa[p].get("sha256") == ob[p].get("sha256")}
        fa, fb = fetch(a, p), fetch(b, p)
        if row["identical"]:
            row.update({"ssim": 1.0, "psnr_db": None})
        elif fa and fb:
            row.update(_ssim_psnr(fa, fb) or {"error": "ffmpeg comparison failed"})
        else:
            row["error"] = "image file unavailable"
        pairs.append(row)
    if not pairs:
        return {"comparable": False, "reasons": ["no prompt with the same text and seed in both runs"]}
    return {"comparable": True, "noise": na, "pairs": pairs}
