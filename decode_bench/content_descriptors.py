#!/usr/bin/env python3
"""content_descriptors.py — per-second "how hard is this content" descriptors
for a source clip, so a box's intra-content power profile can be correlated
against WHAT the content is doing at that moment (2026-09-03).

Descriptors, all per second of content, cached as JSON in
streams/_descriptors/<clip>.json:

  bits_mbps   — encoded bitrate actually delivered to the decoder (video
                packets only), from ffprobe packet sizes. Entropy/bitstream load.
  i_frames    — intra frames in the second (I-frame / scene-cut driven work).
  motion      — mean absolute luma difference between consecutive frames
                (tblend=difference → signalstats YAVG). Motion-compensation /
                temporal-prediction load proxy.
  edge        — mean Sobel edge energy (spatial detail). Residual/texture proxy.
  luma        — mean luma. Panel-side (OLED) driver; also a sanity check that two
                clips really are the same content.
  frames      — frames counted in that second (drops/duplicates show here).

Motion/edge/luma are measured on the DECODED frames after a 640-wide downscale
(the proxies survive downscaling; the pass runs in a couple of minutes for a
6-min 60 fps clip on GoS1). They describe the content, not the encode — so two
encodes of the same source (H.264 vs HEVC, 1080p vs 4K) should give matching
motion/edge/luma and differing bits — which is itself the check that a
cross-codec or cross-resolution comparison is comparing like with like.

Usage: python3 content_descriptors.py <clip> [<clip> ...]   (names under streams/)
"""
import json
import re
import statistics
import subprocess
import sys
from pathlib import Path

STREAMS = Path("/srv/data/owl/decode-bench/streams")
OUT_DIR = STREAMS / "_descriptors"
FFMPEG = "/usr/local/bin/ffmpeg-master"


def _per_second_yavg(path: Path) -> dict:
    """Parse a metadata=print file → {second: mean YAVG}."""
    t, acc = None, {}
    for line in path.open():
        m = re.search(r"pts_time:([0-9.]+)", line)
        if m:
            t = float(m.group(1))
            continue
        m = re.search(r"YAVG=([0-9.]+)", line)
        if m and t is not None:
            acc.setdefault(int(t), []).append(float(m.group(1)))
    return {k: statistics.mean(v) for k, v in acc.items()}


def _bitstream_per_second(src: Path) -> tuple:
    """(bits, i_frames, frames) per second from ffprobe's frame list. Parsed as
    key=value (`compact=nk=0`), never positionally: ffprobe orders CSV fields by
    its own struct, not by the -show_entries request — the first version of
    this read pict_type where pkt_size was and silently recorded 0 bits
    everywhere (2026-09-03, caught by the range check in __main__)."""
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_frames",
         "-show_entries", "frame=pts_time,pict_type,pkt_size",
         "-of", "compact=nk=0:p=0", str(src)],
        capture_output=True, text=True, check=True, timeout=900).stdout
    bits, iframes, frames = {}, {}, {}
    for line in probe.splitlines():
        kv = dict(part.split("=", 1) for part in line.split("|") if "=" in part)
        try:
            sec = int(float(kv.get("pts_time", "")))
            size = int(kv.get("pkt_size", "0") or 0)
        except ValueError:
            continue
        bits[sec] = bits.get(sec, 0) + size * 8
        frames[sec] = frames.get(sec, 0) + 1
        if kv.get("pict_type") == "I":
            iframes[sec] = iframes.get(sec, 0) + 1
    return bits, iframes, frames


def refresh_bitstream(clip: str) -> dict:
    """Recompute only the cheap bitstream columns of a cached descriptor file
    (the picture pass is the expensive part and is left alone)."""
    out = OUT_DIR / f"{Path(clip).stem}.json"
    doc = json.loads(out.read_text())
    bits, iframes, frames = _bitstream_per_second(STREAMS / clip)
    for r in doc["descriptors"]:
        s = r["t"]
        r["bits_mbps"] = round(bits.get(s, 0) / 1e6, 3)
        r["frames"] = frames.get(s, 0)
        r["i_frames"] = iframes.get(s, 0)
    out.write_text(json.dumps(doc))
    return doc


def extract(clip: str, force: bool = False) -> dict:
    src = STREAMS / clip
    OUT_DIR.mkdir(exist_ok=True)
    out = OUT_DIR / f"{Path(clip).stem}.json"
    if out.exists() and not force:
        doc = json.loads(out.read_text())
        if all(r.get("bits_mbps", 0) == 0 for r in doc["descriptors"]):
            doc = refresh_bitstream(clip)      # cached by the buggy first cut
        return doc
    ff = FFMPEG if Path(FFMPEG).exists() else "ffmpeg"
    tmp = OUT_DIR / f".{Path(clip).stem}"
    tmp.mkdir(exist_ok=True)

    bits, iframes, frames = _bitstream_per_second(src)

    # 2. picture: one decode pass, three measurements (luma, motion, edge)
    luma_f, mot_f, edge_f = (tmp / "luma.txt", tmp / "motion.txt", tmp / "edge.txt")
    graph = (
        "scale=640:-2,split=3[a][b][c];"
        f"[a]signalstats,metadata=print:key=lavfi.signalstats.YAVG:file={luma_f}[a1];"
        f"[b]tblend=all_mode=difference,signalstats,"
        f"metadata=print:key=lavfi.signalstats.YAVG:file={mot_f}[b1];"
        f"[c]sobel,signalstats,metadata=print:key=lavfi.signalstats.YAVG:file={edge_f}[c1]"
    )
    subprocess.run(
        [ff, "-v", "error", "-threads", "8", "-i", str(src), "-filter_complex", graph,
         "-map", "[a1]", "-f", "null", "-", "-map", "[b1]", "-f", "null", "-",
         "-map", "[c1]", "-f", "null", "-"],
        check=True, timeout=3600)
    luma, mot, edge = (_per_second_yavg(luma_f), _per_second_yavg(mot_f),
                       _per_second_yavg(edge_f))

    secs = sorted(set(bits) | set(luma))
    rows = [{"t": s, "bits_mbps": round(bits.get(s, 0) / 1e6, 3),
             "frames": frames.get(s, 0), "i_frames": iframes.get(s, 0),
             "luma": round(luma.get(s, float("nan")), 3),
             "motion": round(mot.get(s, float("nan")), 4),
             "edge": round(edge.get(s, float("nan")), 3)} for s in secs]
    doc = {"clip": clip, "seconds": len(rows), "downscale": "640:-2",
           "descriptors": rows}
    out.write_text(json.dumps(doc))
    for f in (luma_f, mot_f, edge_f):
        f.unlink(missing_ok=True)
    tmp.rmdir()
    return doc


def bin_descriptors(doc: dict, bin_s: float, head_s: float = 0.0) -> dict:
    """{bin_index: {descriptor: mean}} on the SAME content-bin grid the power
    profile uses: content bins start after the marker head, so content second
    s maps to bin floor((s + head_s) / bin_s)."""
    bins: dict = {}
    for r in doc["descriptors"]:
        b = int((r["t"] + head_s) // bin_s)
        bins.setdefault(b, []).append(r)
    out = {}
    for b, rows in bins.items():
        out[b] = {k: statistics.mean(x[k] for x in rows if x[k] == x[k])
                  for k in ("bits_mbps", "i_frames", "luma", "motion", "edge")
                  if any(x[k] == x[k] for x in rows)}
    return out


if __name__ == "__main__":
    for clip in sys.argv[1:]:
        d = extract(clip, force="--force" in sys.argv)
        rows = d["descriptors"]
        def rng(k):
            v = [r[k] for r in rows if r[k] == r[k]]
            return f"{min(v):.2f}–{max(v):.2f} (mean {statistics.mean(v):.2f})"
        print(f"{clip}: {d['seconds']} s | bits {rng('bits_mbps')} Mbps | "
              f"motion {rng('motion')} | edge {rng('edge')} | luma {rng('luma')}")
