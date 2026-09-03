"""decode_sync — media-session content clock, the cross-process start barrier,
content-time binning, and marker-edge validation against the screen meter.

The dumpsys fixtures below are LITERAL lines captured from the rig on
2026-09-02 (Xiaomi Gen 2 on Android 11, Google TV on Android 14) — the two
formats the parser has to survive, including the `buffered position=` field
that must never be mistaken for the position.
"""
import decode_sync
import pytest

PLAYER = "com.brouken.player"

# Android 11 (Xiaomi Gen 2, MiTV_AFKR0): bare numeric state, and a SECOND
# session (Spotify) that must be ignored.
DUMP_A11 = """  Sessions Stack - have 3 sessions:
    androidx.media3.session.id. com.brouken.player/androidx.media3.session.id. (userId=0)
      ownerPid=7243, ownerUid=10089, userId=0
      package=com.brouken.player
      active=true
      state=PlaybackState {state=3, position=2887, buffered position=42005, speed=1.0, updated=801803, actions=7339995, custom actions=[], active item id=0, error=null}
      metadata: size=4, description=bbb_h264_60min, null, null
    spotify-android-tv-media-session com.spotify.tv.android/spotify (userId=0)
      package=com.spotify.tv.android
      state=PlaybackState {state=0, position=0, buffered position=0, speed=1.0, updated=37231, actions=2368383, custom actions=[], active item id=-1, error=null}
__UPTIME__
2748.60 7606.84
"""

# Android 14 (Google TV Streamer): named state form.
DUMP_A14 = DUMP_A11.replace("state=3, position=2887", "state=PLAYING(3), position=16384")


def test_parses_android_11_and_14_state_forms():
    a11 = decode_sync.parse_media_session(DUMP_A11, PLAYER)
    assert a11 == {"state": "PLAYING", "position_ms": 2887,
                   "speed": 1.0, "updated_ms": 801803}
    a14 = decode_sync.parse_media_session(DUMP_A14, PLAYER)
    assert a14["state"] == "PLAYING" and a14["position_ms"] == 16384


def test_buffered_position_is_never_the_position():
    # The regex guard: 42005 is the buffered position, 2887 is the position.
    assert decode_sync.parse_media_session(DUMP_A11, PLAYER)["position_ms"] == 2887


def test_other_packages_and_missing_session():
    assert decode_sync.parse_media_session(DUMP_A11, "com.nope") is None
    assert decode_sync.parse_media_session("", PLAYER) is None


def test_playing_session_wins_over_a_stale_one():
    # A rescue keypress can leave a second session for the same package.
    stale = DUMP_A11.replace(
        "      metadata: size=4",
        "      state=PlaybackState {state=2, position=999, buffered position=0,"
        " speed=0.0, updated=999999, actions=0, custom actions=[], active item"
        " id=0, error=null}\n      metadata: size=4")
    assert decode_sync.parse_media_session(stale, PLAYER)["state"] == "PLAYING"


def test_uptime_parse_and_extrapolation():
    up = decode_sync.parse_uptime_ms(DUMP_A11)
    assert up == pytest.approx(2748600.0)
    ps = decode_sync.parse_media_session(DUMP_A11, PLAYER)
    # position frozen at 2.887 s, updated 801.803 s after boot, now 2748.6 s:
    # the box is really 1949.7 s into the clip.
    assert decode_sync.extrapolate_position_s(ps, up) == pytest.approx(1949.684, abs=1e-3)


def test_paused_and_zero_speed_are_not_extrapolated():
    paused = DUMP_A11.replace("state=3, position=2887", "state=2, position=62928") \
                     .replace("speed=1.0, updated=801803", "speed=0.0, updated=419322")
    ps = decode_sync.parse_media_session(paused, PLAYER)
    assert ps["state"] == "PAUSED"
    assert decode_sync.extrapolate_position_s(ps, 2748600.0) == pytest.approx(62.928)


def test_negative_position_and_stale_boot_are_rejected():
    neg = DUMP_A11.replace("position=2887", "position=-1")
    assert decode_sync.parse_media_session(neg, PLAYER)["position_ms"] is None
    assert decode_sync.extrapolate_position_s(
        decode_sync.parse_media_session(neg, PLAYER), 2748600.0) is None
    ps = decode_sync.parse_media_session(DUMP_A11, PLAYER)
    # uptime BEFORE `updated` (box rebooted, session dump stale) → raw position
    assert decode_sync.extrapolate_position_s(ps, 1000.0) == pytest.approx(2.887)


# --- rendezvous ---------------------------------------------------------------

class _Clock:
    def __init__(self, t0=1000.0):
        self.t = t0
        self.slept = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


def _sync(tmp_path, me, peers, **kw):
    return {"dir": str(tmp_path), "self": me, "peers": peers,
            "lead_s": 3.0, "max_wait_s": 120, "poll_s": 0.25, **kw}


def test_rendezvous_all_peers_ready_agree_on_start_at(tmp_path):
    # Peer readied 5 s ago; we ready now → both compute max(epochs) + lead.
    (tmp_path / "gtv.row1.ready").write_text("1000.0")
    c = _Clock(1005.0)
    out = decode_sync.rendezvous(_sync(tmp_path, "xiaomi", ["xiaomi", "gtv"]),
                                 "row1", now=c.now, sleep=c.sleep)
    assert out["start_at"] == pytest.approx(1008.0)   # max(1000,1005)+3
    assert out["timed_out"] is False
    assert out["peers_ready"] == ["gtv", "xiaomi"]
    assert c.slept == [pytest.approx(3.0)]            # slept until start_at


def test_rendezvous_is_per_run_name(tmp_path):
    # A previous row's file must not satisfy this row's barrier.
    (tmp_path / "gtv.row1.ready").write_text("1000.0")
    c = _Clock(1000.0)
    out = decode_sync.rendezvous(
        _sync(tmp_path, "xiaomi", ["xiaomi", "gtv"], max_wait_s=1.0),
        "row2", now=c.now, sleep=c.sleep)
    assert out["timed_out"] is True


def test_rendezvous_aborted_peer_is_not_waited_for(tmp_path):
    (tmp_path / "gtv.abort").touch()
    c = _Clock()
    out = decode_sync.rendezvous(_sync(tmp_path, "xiaomi", ["xiaomi", "gtv"]),
                                 "row1", now=c.now, sleep=c.sleep)
    assert out["timed_out"] is False and out["peers_gone"] == ["gtv"]


def test_rendezvous_ignores_a_partial_ready_file(tmp_path):
    (tmp_path / "gtv.row1.ready").write_text("")      # mid-write
    c = _Clock()
    out = decode_sync.rendezvous(
        _sync(tmp_path, "xiaomi", ["xiaomi", "gtv"], max_wait_s=1.0),
        "row1", now=c.now, sleep=c.sleep)
    assert out["timed_out"] is True


def test_rendezvous_writes_its_own_ready_atomically(tmp_path):
    c = _Clock()
    decode_sync.rendezvous(_sync(tmp_path, "xiaomi", ["xiaomi"]), "row1",
                           now=c.now, sleep=c.sleep)
    assert (tmp_path / "xiaomi.row1.ready").read_text().startswith("1000")
    assert not list(tmp_path.glob("*.tmp"))


# --- clock → content time ------------------------------------------------------

def _clock(pairs, state="PLAYING"):
    return [[t, p, state, 0.1] for t, p in pairs]


def test_segments_reject_rebuffers_gaps_and_wrong_rate():
    ck = (_clock([(100.0, 10.0), (102.0, 12.0)])                    # good
          + [[104.0, 12.0, "BUFFERING", 0.1]]                       # stalled
          + _clock([(106.0, 12.0), (108.0, 14.0)])                  # good again
          + _clock([(130.0, 36.0)]))                                # 22 s gap
    segs = decode_sync.clock_segments(ck)
    assert [(s[0], s[1]) for s in segs] == [(100.0, 102.0), (106.0, 108.0)]


def test_content_time_interpolates_and_refuses_wide_gaps():
    segs = decode_sync.clock_segments(_clock([(100.0, 10.0), (102.0, 12.0)]))
    assert decode_sync.content_time(101.0, segs) == pytest.approx(11.0)
    assert decode_sync.content_time(103.0, segs) == pytest.approx(13.0)   # ≤ edge_s
    assert decode_sync.content_time(120.0, segs) is None                  # too far


def test_bin_by_content_maps_loops_and_bins():
    """Loop boundary is exclusive-left: content 374.5 s is loop 0's last bin,
    375.0 s is already loop 1's first (marker) bin. Getting this off by one
    loop would put every head bin in the wrong repetition."""
    segs = decode_sync.clock_segments(_clock([(100.0, 374.0), (110.0, 384.0)]))
    cells, unaligned = decode_sync.bin_by_content(
        [1.0, 2.0, 3.0], [100.5, 101.0, 107.0], segs, 375.0, 5.0)
    assert unaligned == 0
    assert cells[(0, 74)] == [1.0]           # 374.5 s → loop 0, last bin
    assert cells[(1, 0)] == [2.0]            # 375.0 s → loop 1, first (black) bin
    assert cells[(1, 1)] == [3.0]            # 381.0 s → loop 1, 5-10 s (white) bin


def test_bin_by_content_counts_unaligned_samples():
    segs = decode_sync.clock_segments(_clock([(100.0, 10.0), (102.0, 12.0)]))
    _, unaligned = decode_sync.bin_by_content([1.0], [500.0], segs, 375.0, 5.0)
    assert unaligned == 1


def test_clock_summary_reports_coverage():
    ck = _clock([(100.0, 10.0), (102.0, 12.0)]) + [[112.0, 22.0, "PAUSED", 0.1]]
    s = decode_sync.clock_summary(ck)
    assert s == {"n_polls": 3, "n_playing": 2, "pos_first_s": 10.0,
                 "pos_last_s": 22.0, "max_gap_s": 10.0, "segments": 1}


# --- marker edges vs the screen meter ------------------------------------------

def test_marker_edges_recover_the_white_onset_per_loop():
    """Panel trace: ~30 W black, ~50 W white. Each loop's white field starts
    5 s into the head; the clock says when that content position was reached,
    and the meter should show the step there."""
    loop_len, black_s = 100.0, 5.0
    ctx_t = [1000.0 + i for i in range(240)]
    clock, ctx_w = [], []
    for i, t in enumerate(ctx_t):
        pos = float(i)                       # content advances 1 s per second
        in_loop = pos % loop_len
        ctx_w.append(50.0 if black_s <= in_loop < 10.0 else 30.0)
        if i % 2 == 0:
            clock.append([t, pos, "PLAYING", 0.1])
    out = decode_sync.marker_edges_from_clock(ctx_w, ctx_t, clock, loop_len)
    assert out["n"] >= 2
    assert abs(out["median_residual_s"]) <= 1.0
    assert all(r["swing_w"] == pytest.approx(20.0)
               for r in out["loops"] if r["swing_w"])


def test_marker_edges_report_nothing_on_a_flat_trace():
    ctx_t = [1000.0 + i for i in range(120)]
    clock = [[t, float(i), "PLAYING", 0.1] for i, t in enumerate(ctx_t)]
    out = decode_sync.marker_edges_from_clock([30.0] * 120, ctx_t, clock, 100.0)
    assert out["n"] == 0 and out["median_residual_s"] is None


def test_marker_edges_need_a_clock():
    assert decode_sync.marker_edges_from_clock([1.0], [1.0], [], 100.0)["n"] == 0
