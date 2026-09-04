"""CR-083 · Lab-session reservations — the courtesy calendar on /queue-status.

The immediate toggle keeps its semantics (test_lab_session.py); these tests
pin the calendar: persistence, overlap refusal, the tick state machine's
ownership rules (a reservation raises the flag once, lowers only what it
raised, and never re-raises after a hand end), the routes, and the surfaces
(queue page block, site banner, /decode notice).
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import lab_reservations as lr
import main
import queue_control

client = TestClient(main.app)
_LAB = {"x-real-ip": "127.0.0.1"}
_ANON = {"x-real-ip": "8.8.8.8"}

TZ = timezone(timedelta(hours=2))
T0 = datetime(2026, 9, 7, 18, 0, tzinfo=TZ)
DAY_BEFORE = T0 - timedelta(days=1)


@pytest.fixture(autouse=True)
def _fixed_zone(monkeypatch):
    """Labels are asserted in a fixed +02:00 zone, whatever the host runs."""
    monkeypatch.setattr(lr, "_local_tz", lambda: TZ)


def _flag():
    return queue_control.LAB_SESSION_FLAG


def _idle():
    return {"raised": [], "lowered": [], "finished": []}


# --- model ------------------------------------------------------------------

def test_add_persists_sorted_and_returns_record():
    b = lr.add(T0 + timedelta(hours=5), 60, "Ben — decode", now=DAY_BEFORE)
    a = lr.add(T0, 180, "Tania — encode sweep re-run", now=DAY_BEFORE)
    items = lr.load()
    assert [r["id"] for r in items] == [a["id"], b["id"]]
    assert items[0]["duration_min"] == 180
    assert items[0]["comment"] == "Tania — encode sweep re-run"
    assert items[0]["started"] is None and items[0]["owns_flag"] is False
    assert lr.RESERVATIONS_FILE.exists()


def test_overlap_refused_with_existing_shown():
    lr.add(T0, 180, "Tania — encode sweep", now=DAY_BEFORE)
    with pytest.raises(lr.ReservationOverlap) as ei:
        lr.add(T0 + timedelta(hours=2), 60, "Ben — decode", now=DAY_BEFORE)
    assert ei.value.existing["comment"] == "Tania — encode sweep"
    assert "Tania — encode sweep" in str(ei.value)
    assert len(lr.load()) == 1
    # Back-to-back is not an overlap.
    lr.add(T0 + timedelta(hours=3), 60, "Ben — decode", now=DAY_BEFORE)
    assert len(lr.load()) == 2


@pytest.mark.parametrize("start,dur,comment,msg", [
    (T0, 2, "x", "duration"),
    (T0, 25 * 60, "x", "duration"),
    (T0, "lots", "x", "whole number"),
    (T0, 60, "   ", "comment"),
    (T0, 60, "y" * 41, "characters"),
    (T0 - timedelta(hours=1), 60, "x", "past"),
    (T0 + timedelta(days=61), 60, "x", "ahead"),
])
def test_validation(start, dur, comment, msg):
    with pytest.raises(lr.ReservationError) as ei:
        lr.add(start, dur, comment, now=T0)
    assert msg in str(ei.value).lower()
    assert lr.load() == []


def test_parse_start_reads_form_value_as_local_time():
    dt = lr.parse_start("2026-09-07T18:00")
    assert dt.tzinfo is not None and dt == T0
    assert lr.parse_start(T0.isoformat()) == T0
    with pytest.raises(lr.ReservationError):
        lr.parse_start("next tuesday")
    with pytest.raises(lr.ReservationError):
        lr.parse_start("")


def test_tick_raises_flag_at_start_and_owns_it():
    r = lr.add(T0, 60, "Tania — sweep", now=T0 - timedelta(hours=1))
    assert lr.tick(now=T0 - timedelta(minutes=1)) == _idle()
    assert not _flag().exists()
    out = lr.tick(now=T0)
    assert out["raised"] == [r["id"]]
    assert _flag().exists() and lr.flag_owner() == r["id"]
    assert queue_control.lab_session_active()
    rec = lr.load()[0]
    assert rec["started"] and rec["owns_flag"] is True
    assert lr.active(now=T0 + timedelta(minutes=30))["id"] == r["id"]
    # Idempotent while active.
    assert lr.tick(now=T0 + timedelta(minutes=30)) == _idle()


def test_tick_lowers_owned_flag_at_end_and_prunes():
    r = lr.add(T0, 60, "Tania — sweep", now=T0 - timedelta(hours=1))
    lr.tick(now=T0)
    out = lr.tick(now=T0 + timedelta(minutes=60))
    assert out["lowered"] == [r["id"]] and out["finished"] == [r["id"]]
    assert not _flag().exists()
    assert lr.load() == []


def test_hand_started_session_is_never_lowered():
    _flag().touch()                       # bin/lab-session-on, empty file
    r = lr.add(T0, 60, "Tania — sweep", now=T0 - timedelta(hours=1))
    out = lr.tick(now=T0)
    assert out["raised"] == []
    rec = lr.load()[0]
    assert rec["started"] and rec["owns_flag"] is False
    assert lr.flag_owner() is None
    out = lr.tick(now=T0 + timedelta(minutes=61))
    assert out["lowered"] == [] and out["finished"] == [r["id"]]
    assert _flag().exists()               # the hand session outlives the slot


def test_hand_ended_session_finishes_reservation_without_re_raise():
    r = lr.add(T0, 60, "Tania — sweep", now=T0 - timedelta(hours=1))
    lr.tick(now=T0)
    _flag().unlink()                      # bin/lab-session-off mid-slot
    out = lr.tick(now=T0 + timedelta(minutes=10))
    assert out["finished"] == [r["id"]] and out["raised"] == []
    assert not _flag().exists() and lr.load() == []


def test_missed_slot_is_dropped_without_touching_flag():
    lr.add(T0, 60, "Tania — sweep", now=T0 - timedelta(hours=1))
    out = lr.tick(now=T0 + timedelta(hours=3))   # service down for the whole slot
    assert out["finished"] and out["raised"] == []
    assert not _flag().exists() and lr.load() == []


def test_flag_rewritten_by_hand_is_not_lowered():
    r = lr.add(T0, 60, "Tania — sweep", now=T0 - timedelta(hours=1))
    lr.tick(now=T0)
    _flag().unlink()
    _flag().touch()                       # lowered and re-raised by hand between ticks
    out = lr.tick(now=T0 + timedelta(minutes=60))
    assert out["finished"] == [r["id"]] and out["lowered"] == []
    assert _flag().exists()


def test_extend_pushes_end_and_respects_neighbour():
    a = lr.add(T0, 60, "Tania — sweep", now=T0 - timedelta(hours=1))
    lr.add(T0 + timedelta(hours=2), 60, "Ben — decode", now=T0 - timedelta(hours=1))
    lr.tick(now=T0)
    lr.extend(a["id"], 30, now=T0 + timedelta(minutes=50))
    assert lr.load()[0]["duration_min"] == 90
    assert lr.tick(now=T0 + timedelta(minutes=80))["lowered"] == []
    with pytest.raises(lr.ReservationOverlap):
        lr.extend(a["id"], 60, now=T0 + timedelta(minutes=50))   # into Ben's slot
    with pytest.raises(lr.ReservationError):
        lr.extend(a["id"], 0)
    with pytest.raises(lr.ReservationError):
        lr.extend(a["id"], "soon")
    with pytest.raises(lr.ReservationError):
        lr.extend("nope", 30)
    assert lr.load()[0]["duration_min"] == 90


def test_remove_active_owner_ends_session():
    r = lr.add(T0, 60, "Tania — sweep", now=T0 - timedelta(hours=1))
    lr.tick(now=T0)
    assert lr.remove(r["id"]) is True
    assert not _flag().exists() and lr.load() == []
    assert lr.remove(r["id"]) is False


def test_remove_upcoming_leaves_hand_session_alone():
    _flag().touch()
    r = lr.add(T0, 60, "Tania — sweep", now=T0 - timedelta(hours=1))
    assert lr.remove(r["id"]) is True
    assert _flag().exists()


def test_corrupt_or_odd_file_reads_as_empty():
    lr.RESERVATIONS_FILE.write_text("{not json")
    assert lr.load() == []
    lr.RESERVATIONS_FILE.write_text('{"reservations": [{"id": "x"}, 3]}')
    assert lr.load() == []
    lr.add(T0, 60, "x", now=T0)          # recovers by rewriting
    assert len(lr.load()) == 1


def test_snapshot_shape_and_labels():
    a = lr.add(T0, 90, "Tania — sweep", now=T0 - timedelta(hours=1))
    b = lr.add(T0 + timedelta(days=1), 45, "Ben — decode", now=T0 - timedelta(hours=1))
    lr.tick(now=T0)
    s = lr.snapshot(now=T0 + timedelta(minutes=10))
    assert s["flag_up"] and s["flag_owner"] == a["id"]
    assert s["active"]["id"] == a["id"] and s["active"]["end_label"] == "19:30"
    assert s["active"]["duration_label"] == "1 h 30"
    assert s["active"]["remaining_s"] == 80 * 60
    assert [u["id"] for u in s["upcoming"]] == [b["id"]]
    assert s["upcoming"][0]["start_label"] == "tomorrow 18:00"
    assert s["upcoming"][0]["duration_label"] == "45 min"
    assert s["limits"]["max_comment_chars"] == lr.MAX_COMMENT_CHARS
    assert lr.duration_label(120) == "2 h"
    assert lr.start_label(T0 + timedelta(days=3), now=T0) == "Thu 10 Sep 18:00"
    assert lr.active_summary(now=T0 + timedelta(minutes=10))["id"] == a["id"]
    assert lr.active_summary(now=T0 + timedelta(hours=2)) is None


# --- routes -----------------------------------------------------------------

def _form_time(dt):
    return dt.strftime("%Y-%m-%dT%H:%M")


def test_reserve_form_creates_record_and_redirects():
    r = client.post("/lab-session/reserve", headers=_LAB, follow_redirects=False,
                    data={"start": _form_time(lr.now_local() + timedelta(hours=2)),
                          "duration_min": "90", "comment": "Tania — encode sweep"})
    assert r.status_code == 303 and r.headers["location"] == "/queue-status"
    assert lr.load()[0]["comment"] == "Tania — encode sweep"
    assert not _flag().exists()


def test_reserve_now_activates_immediately():
    r = client.post("/lab-session/reserve", headers=_LAB, follow_redirects=False,
                    data={"start": _form_time(lr.now_local()),
                          "duration_min": "30", "comment": "Ben — quick check"})
    assert r.status_code == 303
    assert _flag().exists() and lr.flag_owner() == lr.load()[0]["id"]


def test_reserve_refusal_travels_as_note():
    start = _form_time(lr.now_local() + timedelta(hours=2))
    client.post("/lab-session/reserve", headers=_LAB, follow_redirects=False,
                data={"start": start, "duration_min": "60", "comment": "Tania — sweep"})
    r = client.post("/lab-session/reserve", headers=_LAB, follow_redirects=False,
                    data={"start": start, "duration_min": "60", "comment": "Ben — decode"})
    assert r.status_code == 303 and r.headers["location"].startswith("/queue-status?note=")
    page = client.get(r.headers["location"], headers=_LAB).text
    assert "Overlaps an existing reservation" in page and "Tania" in page
    assert len(lr.load()) == 1


def test_reservation_routes_are_lab_only():
    assert client.post("/lab-session/reserve", headers=_ANON, follow_redirects=False,
                       data={"start": "2030-01-01T10:00", "duration_min": "60",
                             "comment": "x"}).status_code == 403
    assert client.get("/lab-session/reservations.json", headers=_ANON).status_code == 403
    assert client.post("/lab-session/reservation/r1/delete", headers=_ANON,
                       follow_redirects=False).status_code == 403
    assert client.post("/lab-session/reservation/r1/extend", headers=_ANON,
                       follow_redirects=False, data={"minutes": "30"}).status_code == 403
    assert lr.load() == []


def test_delete_and_extend_routes():
    rec = lr.add(lr.now_local() + timedelta(hours=2), 60, "Tania — sweep")
    r = client.post(f"/lab-session/reservation/{rec['id']}/extend", headers=_LAB,
                    follow_redirects=False, data={"minutes": "30"})
    assert r.status_code == 303 and lr.load()[0]["duration_min"] == 90
    r = client.post(f"/lab-session/reservation/{rec['id']}/extend", headers=_LAB,
                    follow_redirects=False, data={"minutes": "-5"})
    assert "note=" in r.headers["location"] and lr.load()[0]["duration_min"] == 90
    r = client.post(f"/lab-session/reservation/{rec['id']}/delete", headers=_LAB,
                    follow_redirects=False)
    assert r.status_code == 303 and lr.load() == []
    r = client.post(f"/lab-session/reservation/{rec['id']}/delete", headers=_LAB,
                    follow_redirects=False)
    assert "note=" in r.headers["location"]


def test_reservations_json_ticks_and_describes():
    rec = lr.add(lr.now_local(), 30, "Ben — quick check")
    s = client.get("/lab-session/reservations.json", headers=_LAB).json()
    assert s["active"]["id"] == rec["id"] and s["flag_up"] is True
    assert s["upcoming"] == [] and "limits" in s


def test_hand_toggle_off_finishes_active_reservation():
    lr.add(lr.now_local(), 30, "Ben — quick check")
    lr.tick()
    assert _flag().exists()
    r = client.post("/lab-session/toggle", headers=_LAB, data={"on": "0"},
                    follow_redirects=False)
    assert r.status_code == 303
    assert not _flag().exists() and lr.load() == []


# --- surfaces ---------------------------------------------------------------

def test_queue_page_has_reservation_form_and_polls_instead_of_reloading():
    page = client.get("/queue-status", headers=_LAB).text
    assert 'action="/lab-session/reserve"' in page
    assert 'name="duration_min"' in page and 'id="lab-res-list"' in page
    assert 'http-equiv="refresh"' not in page
    assert "setInterval(load, 4000)" in page and "window.CAN_LAB=true" in page
    anon = client.get("/queue-status", headers=_ANON).text
    assert "/lab-session/reserve" not in anon and "window.CAN_LAB=false" in anon


def test_queue_page_state_line_names_the_active_reservation():
    lr.add(lr.now_local(), 30, "Tania — encode sweep")
    lr.tick()
    page = client.get("/queue-status", headers=_LAB).text
    assert "ACTIVE" in page and "reserved until" in page
    assert "Tania — encode sweep" in page


def test_banner_shows_until_for_all_and_comment_for_lab_only():
    lr.add(lr.now_local(), 30, "Tania — encode sweep")
    lr.tick()
    anon = client.get("/demo", headers=_ANON).text
    assert "Lab session in progress" in anon and "Reserved until" in anon
    assert "Tania" not in anon
    lab = client.get("/demo", headers=_LAB).text
    assert "Reserved until" in lab and "Tania — encode sweep" in lab


def test_banner_plain_for_hand_started_session():
    _flag().touch()
    page = client.get("/demo", headers=_LAB).text
    assert "Lab session in progress" in page and "Reserved until" not in page


def test_decode_page_carries_calendar_notice():
    page = client.get("/decode", headers=_LAB).text
    assert 'id="lab-res"' in page and "labTick" in page
