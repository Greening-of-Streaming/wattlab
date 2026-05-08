"""
CR-035 — unit tests for the ffmpeg `-progress pipe:1` parser and the
progress callback factory.

Why these matter: the parser is the load-bearing piece between ffmpeg's
stdout (a sequence of `key=value\\n` lines, blocked by a sentinel
`progress=continue|end` line) and the live progress bar. A regression
here is silent — the bar just stops moving — so we pin the contract.
"""

import video


# ─── _consume_progress_line ───────────────────────────────────────────────

def test_consume_progress_line_accumulates_until_sentinel():
    """A normal progress block: several key=value lines, closed by
    `progress=continue`. The function returns the whole block on the
    sentinel, and only on the sentinel."""
    block = {}
    assert video._consume_progress_line("frame=42", block) is None
    assert video._consume_progress_line("fps=23.97", block) is None
    assert video._consume_progress_line("out_time_us=1750000", block) is None
    assert video._consume_progress_line("speed=2.1x", block) is None
    completed = video._consume_progress_line("progress=continue", block)
    assert completed == {
        "frame": "42",
        "fps": "23.97",
        "out_time_us": "1750000",
        "speed": "2.1x",
        "progress": "continue",
    }


def test_consume_progress_line_end_sentinel_returns_block():
    """The terminal `progress=end` block is returned identically to a
    `progress=continue` block — caller decides whether to treat it
    specially."""
    block = {}
    video._consume_progress_line("out_time_us=120000000", block)
    completed = video._consume_progress_line("progress=end", block)
    assert completed["progress"] == "end"
    assert completed["out_time_us"] == "120000000"


def test_consume_progress_line_ignores_blank_and_malformed():
    """Blank lines, missing `=`, and stray whitespace must not poison
    the accumulator."""
    block = {}
    assert video._consume_progress_line("", block) is None
    assert video._consume_progress_line("   ", block) is None
    assert video._consume_progress_line("not-a-key-value", block) is None
    assert video._consume_progress_line("frame=10", block) is None
    # Whitespace around values is preserved — ffmpeg never emits any,
    # but we don't strip.
    assert block == {"frame": "10"}


def test_consume_progress_line_handles_multiple_blocks_via_reset():
    """Caller resets the dict between blocks; we verify the function
    doesn't leak state across resets (it shouldn't — it's pure)."""
    block = {}
    video._consume_progress_line("frame=1", block)
    completed = video._consume_progress_line("progress=continue", block)
    assert completed["frame"] == "1"
    # Caller resets:
    block = {}
    completed = video._consume_progress_line("progress=continue", block)
    # Empty block was completed — frame from previous round must NOT appear
    assert "frame" not in completed
    assert completed == {"progress": "continue"}


# ─── _make_progress_cb ─────────────────────────────────────────────────────

def test_progress_cb_writes_pct_speed_eta_to_jobs():
    """Standard happy path — a progress block with out_time and speed
    yields all three fields on jobs[job_id]."""
    jobs = {"job1": {}}
    cb = video._make_progress_cb(jobs, "job1", duration_s=120.0)
    cb({"out_time_us": "30000000", "speed": "2.0x", "progress": "continue"})
    assert jobs["job1"]["progress_pct"] == 25.0  # 30s / 120s
    assert jobs["job1"]["encode_speed"] == "2.0x"
    # ETA: remaining 90s / speed 2.0 = 45s
    assert jobs["job1"]["eta_s"] == 45.0


def test_progress_cb_eta_smoothing_averages_recent_speeds():
    """Speed jitters frame-to-frame; the ETA should reflect a moving
    average over the last N samples, not the latest single sample."""
    jobs = {"job1": {}}
    cb = video._make_progress_cb(jobs, "job1", duration_s=100.0, smoothing_n=4)
    # Four samples at varying speeds — mean = 2.0
    for sec, sp in [(10, "1.5x"), (20, "2.5x"), (30, "1.5x"), (40, "2.5x")]:
        cb({"out_time_us": str(sec * 1_000_000), "speed": sp, "progress": "continue"})
    # Last sample at 40s: remaining = 60s, mean speed = 2.0, ETA = 30s
    assert jobs["job1"]["eta_s"] == 30.0


def test_progress_cb_clamps_pct_to_0_100():
    """If ffmpeg overshoots duration (clip with cut/seek edges, or a
    bad probe), pct should clamp to 100 — no negative or >100 values
    flowing to the UI."""
    jobs = {"job1": {}}
    cb = video._make_progress_cb(jobs, "job1", duration_s=10.0)
    cb({"out_time_us": "15000000", "speed": "1.0x", "progress": "continue"})
    assert jobs["job1"]["progress_pct"] == 100.0


def test_progress_cb_end_sentinel_clamps_pct_to_100():
    """`progress=end` is the final block; clamp pct to 100 so the bar
    closes even if the last reported out_time_us undershoots."""
    jobs = {"job1": {}}
    cb = video._make_progress_cb(jobs, "job1", duration_s=120.0)
    cb({"out_time_us": "119500000", "speed": "1.0x", "progress": "end"})
    assert jobs["job1"]["progress_pct"] == 100.0
    assert jobs["job1"]["eta_s"] == 0.0


def test_progress_cb_no_duration_skips_pct_and_eta():
    """When ffprobe failed to read duration, the cb should still write
    speed (visitor still sees encode rate) but leave pct/eta as None."""
    jobs = {"job1": {}}
    cb = video._make_progress_cb(jobs, "job1", duration_s=None)
    cb({"out_time_us": "30000000", "speed": "2.0x", "progress": "continue"})
    assert jobs["job1"]["progress_pct"] is None
    assert jobs["job1"]["eta_s"] is None
    assert jobs["job1"]["encode_speed"] == "2.0x"


def test_progress_cb_handles_na_out_time():
    """Very early in an encode ffmpeg sometimes emits `out_time_us=N/A`.
    Don't crash, don't write nonsense — just leave fields untouched."""
    jobs = {"job1": {}}
    cb = video._make_progress_cb(jobs, "job1", duration_s=120.0)
    cb({"out_time_us": "N/A", "speed": "0x", "progress": "continue"})
    assert "progress_pct" not in jobs["job1"]


def test_progress_cb_handles_malformed_speed():
    """Speed strings can be `0x`, `N/A`, or absent. None of these
    should throw — pct should still update from out_time, just no ETA."""
    jobs = {"job1": {}}
    cb = video._make_progress_cb(jobs, "job1", duration_s=120.0)
    cb({"out_time_us": "60000000", "speed": "N/A", "progress": "continue"})
    assert jobs["job1"]["progress_pct"] == 50.0
    assert jobs["job1"]["eta_s"] is None


def test_progress_cb_no_jobs_dict_is_safe():
    """Encoders run without a job dict (variance calibration template
    runs through transcode() too); cb should be a no-op."""
    cb = video._make_progress_cb(None, "ignored", duration_s=120.0)
    # Must not raise.
    cb({"out_time_us": "30000000", "speed": "2.0x", "progress": "continue"})


def test_progress_cb_unknown_job_id_is_safe():
    """If the job was cancelled / popped before the encode finishes,
    a stray callback shouldn't recreate the entry."""
    jobs = {"other_job": {}}
    cb = video._make_progress_cb(jobs, "missing", duration_s=120.0)
    cb({"out_time_us": "30000000", "speed": "2.0x", "progress": "continue"})
    assert "missing" not in jobs


# ─── _clear_progress ───────────────────────────────────────────────────────

def test_clear_progress_removes_only_progress_fields():
    """Compare-mode sweeps clear progress between sub-encodes so the
    next encode's bar doesn't start at the previous encode's value.
    Other job fields (stage, watts, etc.) must survive."""
    jobs = {"job1": {
        "stage": "cpu_encode",
        "progress_pct": 75.0,
        "eta_s": 15.0,
        "encode_speed": "2.1x",
        "input_duration_s": 120.0,
    }}
    video._clear_progress(jobs, "job1")
    assert "progress_pct" not in jobs["job1"]
    assert "eta_s" not in jobs["job1"]
    assert "encode_speed" not in jobs["job1"]
    # input_duration_s + stage are NOT progress fields — preserved.
    assert jobs["job1"]["stage"] == "cpu_encode"
    assert jobs["job1"]["input_duration_s"] == 120.0


def test_clear_progress_idempotent_when_fields_absent():
    """Clearing a job with no progress fields set is a no-op, not an
    error (called unconditionally in run_single)."""
    jobs = {"job1": {"stage": "cpu_encode"}}
    video._clear_progress(jobs, "job1")
    assert jobs["job1"] == {"stage": "cpu_encode"}


def test_clear_progress_safe_for_missing_jobs_dict_or_id():
    """Defensive: callers may invoke after the job dict is gone."""
    video._clear_progress(None, "anything")
    video._clear_progress({}, "missing")  # must not raise


# ─── Integration: parser + callback simulating a full encode ───────────────

def test_full_progress_stream_drives_bar_to_completion():
    """Simulate ffmpeg's stdout for a 120s clip encoding at ~2x: a
    sequence of `progress=continue` blocks plus a final `progress=end`
    block. After processing every line, pct should be at 100%."""
    jobs = {"job1": {}}
    cb = video._make_progress_cb(jobs, "job1", duration_s=120.0)
    block = {}

    # Sample ffmpeg stream — abbreviated to the keys our parser cares about.
    lines = []
    for sec in [10, 30, 60, 90, 110]:
        lines += [
            f"frame={sec * 24}",
            f"fps=24.0",
            f"out_time_us={sec * 1_000_000}",
            f"speed=2.0x",
            "progress=continue",
        ]
    lines += [
        "frame=2880",
        "out_time_us=120000000",
        "speed=2.0x",
        "progress=end",
    ]

    completed_blocks = 0
    for line in lines:
        completed = video._consume_progress_line(line, block)
        if completed is not None:
            cb(completed)
            block = {}
            completed_blocks += 1

    # 5 continue + 1 end = 6 blocks
    assert completed_blocks == 6
    assert jobs["job1"]["progress_pct"] == 100.0
    assert jobs["job1"]["eta_s"] == 0.0
