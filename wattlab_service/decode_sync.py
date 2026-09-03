"""decode_sync.py — pure helpers for synchronised multi-box playback with a
per-box CONTENT CLOCK (2026-09-03; intra-content decode power).

The measurement question: how does each box's draw move *within* a clip, and
does silicon A track the same content moments as silicon B? That needs every
power sample tagged with the content time the box was decoding. Two facts
fixed the design (JOURNAL S73):

  · The P110 refreshes every ~1.3-1.6 s and is polled at 1 s, so "sync" means
    a KNOWN content clock per box with launch skew minimised — never bin by
    wall time, bin by content time.
  · Android/Fire OS media sessions expose position/speed/updated but FREEZE
    them between state changes (Gen 2 read `position=0, updated=77188` 45 min
    into playback). The clock is `position + (uptime_now - updated) * speed`,
    both read in ONE adb shell so a poll is self-consistent.

Everything here is pure (no adb, no meters): bench.py wires it into the
per-device process, decode_run.py into the service, content_profile.py into
the analysis, and the tests exercise it directly.

Clock rows are `[t_epoch, pos_s | None, state | None, call_dt_s | None]`.
"""
from __future__ import annotations

import bisect
import os
import re
import statistics
import time
from pathlib import Path

MS_STATE_NAMES = {"0": "NONE", "1": "STOPPED", "2": "PAUSED", "3": "PLAYING",
                  "6": "BUFFERING", "7": "ERROR"}

# `[{,]` guards: "buffered position=" must never match as the position.
_POS_RE = re.compile(r"[{,]\s*position=(-?\d+)")
_SPEED_RE = re.compile(r"[{,]\s*speed=(-?[0-9.]+)")
_UPDATED_RE = re.compile(r"[{,]\s*updated=(\d+)")

UPTIME_MARK = "__UPTIME__"


# --- media session → position ------------------------------------------------

def parse_media_session(out: str, player: str) -> dict | None:
    """Parse `dumpsys media_session` for `player`'s PlaybackState. Same block
    logic as bench.py's AdbDevice.playback_state() (a `package=` line opens a
    block; the state line inside it is the one we want), but keeps the fields
    that parser discards. Handles Android 11 `state=3` and Android 14
    `state=PLAYING(3)`. Several blocks for the package (a stale session left
    by a rescue keypress): prefer PLAYING, else the most recently updated.
    Returns {state, position_ms (None if < 0/missing), speed, updated_ms} or
    None when the package has no session."""
    cands = []
    block = False
    for line in out.splitlines():
        if "package=" in line:
            block = player in line
        if block and "state=PlaybackState" in line and "{state=" in line:
            body = line.split("{state=", 1)[1]
            tok = body.split(",")[0].strip()
            num = tok.split("(")[-1].rstrip(")") if "(" in tok else tok
            st = MS_STATE_NAMES.get(num, tok)
            m = _POS_RE.search(body)
            pos = int(m.group(1)) if m else None
            if pos is not None and pos < 0:
                pos = None
            m = _SPEED_RE.search(body)
            speed = float(m.group(1)) if m else 0.0
            m = _UPDATED_RE.search(body)
            upd = int(m.group(1)) if m else None
            cands.append({"state": st, "position_ms": pos,
                          "speed": speed, "updated_ms": upd})
    if not cands:
        return None
    for c in cands:
        if c["state"] == "PLAYING":
            return c
    return max(cands, key=lambda c: c["updated_ms"] or -1)


def parse_uptime_ms(out: str) -> float | None:
    """`/proc/uptime` printed after a UPTIME_MARK line → ms since boot
    (CLOCK_BOOTTIME, the same base as media3's `updated`)."""
    lines = out.splitlines()
    for i, l in enumerate(lines):
        if l.strip() == UPTIME_MARK:
            for l2 in lines[i + 1:]:
                l2 = l2.strip()
                if l2:
                    try:
                        return float(l2.split()[0]) * 1000.0
                    except ValueError:
                        return None
    return None


def extrapolate_position_s(ps: dict, uptime_ms: float | None) -> float | None:
    """Current content position in seconds. media3 only rewrites `position`
    on state changes, so while PLAYING the truth is position + elapsed·speed.
    Falls back to the raw position when not playing, when speed ≤ 0, when the
    uptime is missing, or when the gap is implausible (negative or > 1 h —
    a stale session from a previous boot)."""
    pos = ps.get("position_ms")
    if pos is None:
        return None
    upd, speed = ps.get("updated_ms"), ps.get("speed") or 0.0
    if (ps.get("state") == "PLAYING" and speed > 0
            and upd is not None and uptime_ms is not None):
        gap = uptime_ms - upd
        if 0 <= gap <= 3_600_000:
            return (pos + gap * speed) / 1000.0
    return pos / 1000.0


# --- cross-process start rendezvous -------------------------------------------

def rendezvous(sync: dict, run_name: str, *, now=time.time, sleep=time.sleep,
               log=None) -> dict:
    """File-based start barrier between the per-device bench.py PROCESSES of
    one job (they share no memory). After its baseline each process writes
    `<dir>/<self>.<run>.ready` (atomic tmp+replace, epoch inside), polls until
    every peer has one (or an `<peer>.abort`), computes
    `start_at = max(ready epochs) + lead_s` — identical in every process
    because they all read the same files — and sleeps until then. A peer that
    never shows up is waited for at most `max_wait_s`; the row records it.
    Per-run-name files: a multi-clip template must not let row 2 see row 1's."""
    d = Path(sync["dir"])
    d.mkdir(parents=True, exist_ok=True)
    me = sync["self"]
    peers = [p for p in sync.get("peers", []) if p != me]
    lead = float(sync.get("lead_s", 3.0))
    max_wait = float(sync.get("max_wait_s", 120))
    poll = float(sync.get("poll_s", 0.25))
    ready_epoch = now()
    tmp = d / f"{me}.{run_name}.ready.tmp"
    tmp.write_text(f"{ready_epoch:.3f}")
    os.replace(tmp, d / f"{me}.{run_name}.ready")
    ready = {me: ready_epoch}
    gone: list = []
    deadline = ready_epoch + max_wait
    timed_out = False
    while True:
        for p in peers:
            if p in ready or p in gone:
                continue
            if (d / f"{p}.abort").exists():
                gone.append(p)
                continue
            f = d / f"{p}.{run_name}.ready"
            if f.exists():
                try:
                    ready[p] = float(f.read_text().strip())
                except (ValueError, OSError):
                    continue            # partial write — next poll
        if len(ready) + len(gone) >= len(peers) + 1:
            break
        if now() >= deadline:
            timed_out = True
            break
        sleep(poll)
    start_at = max(max(ready.values()) + lead, now())
    t = now()
    if start_at > t:
        sleep(start_at - t)
    if log:
        log(f"{run_name}: sync go at {start_at:.2f} (waited "
            f"{now() - ready_epoch:.1f}s, peers {sorted(ready)}, "
            f"gone {gone}, timed_out={timed_out})")
    return {"ready_epoch": round(ready_epoch, 3), "start_at": round(start_at, 3),
            "waited_s": round(now() - ready_epoch, 2),
            "peers_ready": sorted(ready), "peers_gone": gone,
            "timed_out": timed_out}


# --- clock → content time ------------------------------------------------------

def _rows(clock) -> list:
    out = []
    for r in clock or []:
        if isinstance(r, dict):
            out.append((r.get("t"), r.get("pos_s"), r.get("state")))
        else:
            t = r[0] if len(r) > 0 else None
            pos = r[1] if len(r) > 1 else None
            st = r[2] if len(r) > 2 else None
            out.append((t, pos, st))
    return out


def clock_segments(clock, *, max_rate_err: float = 0.1,
                   max_gap_s: float = 10.0) -> list:
    """Trusted stretches of the clock: consecutive PLAYING polls, gap ≤
    max_gap_s, implied playback rate within 1 ± max_rate_err. Rebuffers,
    pauses and rescue-seeks fall between segments and are never interpolated
    across. Returns [(t0, t1, pos0, pos1), ...] sorted by t0."""
    rows = [r for r in _rows(clock) if r[0] is not None and r[1] is not None]
    segs = []
    for (t0, p0, s0), (t1, p1, s1) in zip(rows, rows[1:]):
        if s0 != "PLAYING" or s1 != "PLAYING":
            continue
        dt = t1 - t0
        if dt <= 0 or dt > max_gap_s:
            continue
        rate = (p1 - p0) / dt
        if abs(rate - 1.0) > max_rate_err:
            continue
        segs.append((t0, t1, p0, p1))
    segs.sort()
    return segs


def content_time(t: float, segs: list, *, edge_s: float = 2.0) -> float | None:
    """Content position at wall time t: linear inside a segment, extrapolated
    at most edge_s past a segment's ends, else None (unaligned sample)."""
    if not segs:
        return None
    starts = [s[0] for s in segs]
    i = bisect.bisect_right(starts, t) - 1
    for j in (i, i + 1):
        if 0 <= j < len(segs):
            t0, t1, p0, p1 = segs[j]
            if t0 <= t <= t1:
                return p0 + (p1 - p0) * (t - t0) / (t1 - t0)
    # nearest end within edge_s
    best = None
    for j in (i, i + 1):
        if 0 <= j < len(segs):
            t0, t1, p0, p1 = segs[j]
            rate = (p1 - p0) / (t1 - t0)
            if t < t0 and t0 - t <= edge_s:
                cand = (t0 - t, p0 - (t0 - t) * rate)
            elif t > t1 and t - t1 <= edge_s:
                cand = (t - t1, p1 + (t - t1) * rate)
            else:
                continue
            if best is None or cand[0] < best[0]:
                best = cand
    return best[1] if best else None


def wall_time_of_pos(pos: float, segs: list) -> float | None:
    """Inverse of content_time over the trusted segments (positions are
    monotonic in wall time)."""
    for t0, t1, p0, p1 in segs:
        if p0 <= pos <= p1 and p1 > p0:
            return t0 + (t1 - t0) * (pos - p0) / (p1 - p0)
    return None


def bin_by_content(w: list, t: list, segs: list, loop_len_s: float,
                   bin_s: float, *, edge_s: float = 2.0):
    """Group power samples by (loop index, content bin). Returns
    ({(k, b): [w...]}, unaligned_count). k = floor(pos / loop_len),
    content_s = pos − k·loop_len, b = floor(content_s / bin_s)."""
    cells: dict = {}
    unaligned = 0
    for wi, ti in zip(w, t):
        pos = content_time(ti, segs, edge_s=edge_s)
        if pos is None or pos < 0:
            unaligned += 1
            continue
        k = int(pos // loop_len_s)
        c = pos - k * loop_len_s
        cells.setdefault((k, int(c // bin_s)), []).append(wi)
    return cells, unaligned


def clock_summary(clock) -> dict:
    rows = _rows(clock)
    ts = [r[0] for r in rows if r[0] is not None]
    pos = [r[1] for r in rows if r[1] is not None]
    gaps = [b - a for a, b in zip(ts, ts[1:])]
    return {"n_polls": len(rows),
            "n_playing": sum(1 for r in rows if r[2] == "PLAYING"),
            "pos_first_s": round(pos[0], 2) if pos else None,
            "pos_last_s": round(pos[-1], 2) if pos else None,
            "max_gap_s": round(max(gaps), 2) if gaps else None,
            "segments": len(clock_segments(clock))}


# --- screen-meter marker edges vs the clock ------------------------------------

def _sustained(head: list, candidates: list, tol: float, min_n: int):
    for v in candidates:
        if sum(1 for x in head if abs(x - v) <= tol) >= min_n:
            return v
    return None


def marker_edges_from_clock(ctx_w: list, ctx_t: list, clock, loop_len_s: float,
                            *, head_s: float = 15.0, black_s: float = 5.0,
                            win_before: float = 8.0, win_after: float = 15.0,
                            min_swing_w: float = 1.0, rail_tol_w: float = 0.6,
                            rail_min_n: int = 3, skip_loops=(0,)) -> dict:
    """Validate the media-session clock against the physical screen. For each
    loop k the clock predicts the wall time of the WHITE onset
    (pos = k·loop_len + black_s); the screen meter (Lab-E) should step up by
    the panel's white-field swing right there. Slices the context trace
    around the prediction, finds the rails with the same rule as
    decode_run.segment_marker_trace (≥3 samples within ±0.6 W, swing ≥ 1 W),
    and takes the rising midpoint crossing (interpolated) as the observed
    onset. residual_s = observed − predicted (render latency + clock error;
    ≈ the meter's own 1-1.5 s refresh is the noise floor).

    Loop 0 is reported but excluded from the median by default (`skip_loops`):
    its white onset sits ~1 s after launch, inside the player's start-up
    transient, and the panel trace there is the launcher→player switch rather
    than a clean black→white step — both 03 Sep runs put loop 0 at +11 s with
    every later loop at 1.0-1.3 s."""
    segs = clock_segments(clock)
    out: dict = {"loops": [], "n": 0, "median_residual_s": None, "mad_s": None}
    if not segs or not ctx_w or not ctx_t or loop_len_s <= 0:
        return out
    pos_max = max(s[3] for s in segs)
    k = 0
    residuals = []
    while k * loop_len_s + black_s <= pos_max and k < 1000:
        pos_white = k * loop_len_s + black_s
        T = wall_time_of_pos(pos_white, segs)
        k += 1
        if T is None:
            continue
        idx = [i for i, t in enumerate(ctx_t) if T - win_before <= t <= T + win_after]
        rec = {"k": k - 1, "predicted_t": round(T, 2), "observed_t": None,
               "residual_s": None, "swing_w": None}
        if len(idx) >= 6:
            vals = [ctx_w[i] for i in idx]
            ts = [ctx_t[i] for i in idx]
            lo = _sustained(vals, sorted(vals), rail_tol_w, rail_min_n)
            hi = _sustained(vals, sorted(vals, reverse=True), rail_tol_w, rail_min_n)
            if lo is not None and hi is not None and hi - lo >= min_swing_w:
                mid = (lo + hi) / 2
                for i in range(1, len(vals)):
                    if vals[i - 1] < mid <= vals[i]:
                        frac = (mid - vals[i - 1]) / (vals[i] - vals[i - 1])
                        t_obs = ts[i - 1] + frac * (ts[i] - ts[i - 1])
                        rec.update({"observed_t": round(t_obs, 2),
                                    "residual_s": round(t_obs - T, 2),
                                    "swing_w": round(hi - lo, 2)})
                        if rec["k"] not in (skip_loops or ()):
                            residuals.append(t_obs - T)
                        else:
                            rec["excluded"] = "launch transient"
                        break
        out["loops"].append(rec)
    out["n"] = len(residuals)
    if residuals:
        med = statistics.median(residuals)
        out["median_residual_s"] = round(med, 2)
        out["mad_s"] = round(statistics.median(abs(r - med) for r in residuals), 2)
    return out
