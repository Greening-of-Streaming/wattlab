"""CR-073 — decode campaigns = batches: collator, routes, list_batch,
envelope_version, and the backfill script."""
import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import decode_batch
import main
import persist

_LAB = {"x-real-ip": "127.0.0.1"}
_ANON = {"x-real-ip": "8.8.8.8"}
client = TestClient(main.app)


def _row(device, delta, flag="🟢", **kw):
    r = {"run": "clip_loop", "device": device, "delta_w": delta, "w_base": 1.4,
         "w_task": 1.4 + delta, "n_task": 1100, "window_s": 1100,
         "alive_at_window_end": True,
         "confidence": {"flag": flag, "ci_delta_w_95": [delta - 0.1, delta + 0.1],
                        "confidence_positive": 0.99},
         "provenance": {"playback_state_midwindow": "PLAYING",
                        "screenshot": "x.png", "play_presses_after_launch": 0,
                        "keep_awake": {"secure.sleep_timeout": "-1"}},
         "raw_task_w": [1.0] * 3, "raw_task_t": [1.0, 2.0, 3.0]}
    r.update(kw)
    return r


def _env(job_id, template, runs, batch_id="abc123def456", mode="ui_headless",
         devices=None, saved_at="2026-08-17T01:00:00"):
    return {"job_id": job_id, "saved_at": saved_at, "batch_id": batch_id,
            "mode": mode, "template": template, "template_label": template,
            "devices": devices if devices is not None else
                       {r["device"]: {"rows": [dict(r)]} for r in runs},
            "runs": runs,
            "protocol": {"protocol_version": 3, "window_s": 1100, "cadence_s": 1.0},
            "owl_version": {"sha": "abc1234"}}


# --- collator ------------------------------------------------------------

def test_parse_template_shapes():
    assert decode_batch.parse_template("loop_bbb_h264") == ("BBB", "H.264")
    assert decode_batch.parse_template("loop_kranjska_av1") == ("Kranjska", "AV1")
    assert decode_batch.parse_template("bbb_h264_hw_rt") == ("BBB", "H.264")
    assert decode_batch.parse_template("upload", "uploaded clip — promo.mp4") == \
        ("upload/promo.mp4", "?")
    assert decode_batch.parse_template("weird_thing") == ("weird_thing", "?")


def test_matrix_builds_device_by_content_codec():
    envs = [_env("j1", "loop_bbb_h264", [_row("gtv", 0.6), _row("firestick", 0.59)]),
            _env("j2", "loop_bbb_av1", [_row("gtv", 0.6), _row("firestick", 0.52)]),
            _env("j3", "loop_meridian_h264", [_row("gtv", 0.38)])]
    m = decode_batch.matrix(envs, "abc123def456")
    assert m["devices"] == ["gtv", "firestick"]
    assert [(c["content"], c["codec"]) for c in m["columns"]] == \
        [("BBB", "AV1"), ("BBB", "H.264"), ("Meridian", "H.264")]
    cell = m["cells"]["gtv|Meridian|H.264|"][0]
    assert cell["delta_w"] == 0.38 and cell["flag"] == "🟢" and cell["job_id"] == "j3"
    assert cell["mid_state"] == "PLAYING" and cell["screenshot"] == "x.png"
    assert m["n_cells"] == 5 and m["n_errors"] == 0
    assert m["cells"].get("firestick|Meridian|H.264|") is None   # empty cell, not fabricated
    assert any("pinned OFF" in n for n in m["notes"])            # keep_awake disclosure


def test_matrix_keeps_errored_rows_and_failed_sections():
    envs = [_env("j1", "loop_bbb_h264",
                 [_row("gtv", 0.6)],
                 devices={"gtv": {"rows": [_row("gtv", 0.6)]},
                          "c2": {"rows": [{"run": "clip_loop", "error": "TimeoutError()",
                                           "error_where": ["start:210"]}]},
                          "bbox": {"error": "not ready after 90s"}})]
    m = decode_batch.matrix(envs)
    assert m["n_errors"] == 2
    assert m["cells"]["c2|BBB|H.264|"][0]["error"] == "TimeoutError()"
    assert m["cells"]["bbox|BBB|H.264|"][0]["error"] == "not ready after 90s"
    assert "bbox" in m["devices"] and "c2" in m["devices"]


def test_matrix_screen_mode_is_its_own_column_and_repeats_stack():
    envs = [_env("j1", "loop_bbb_h264", [_row("gtv", 0.6)]),
            _env("j2", "loop_bbb_h264", [_row("gtv", 0.65)]),                # repeat
            _env("j3", "loop_bbb_h264", [_row("gtv", 0.52, context_delta_w=27.6)],
                 mode="ui_screen")]
    m = decode_batch.matrix(envs)
    assert [c["mode"] for c in m["columns"]] == ["headless", "screen"]
    assert len(m["cells"]["gtv|BBB|H.264|"]) == 2                    # n=2, both kept
    assert m["cells"]["gtv|BBB|H.264|screen"][0]["context_delta_w"] == 27.6
    assert any("Screen-mode" in n for n in m["notes"])


def test_csv_rows_flatten_every_cell():
    envs = [_env("j1", "loop_bbb_h264", [_row("gtv", 0.6), _row("firestick", 0.59)])]
    rows = decode_batch.to_csv_rows(decode_batch.matrix(envs, "b"))
    assert len(rows) == 2 and set(rows[0]) >= set(decode_batch.CSV_FIELDS)
    assert rows[0]["ci_low"] == pytest.approx(0.49) or rows[1]["ci_low"] == pytest.approx(0.49)


# --- persist: list_batch + envelope_version ------------------------------

def test_list_batch_scans_type_dir_without_visitor_scoping(tmp_path, monkeypatch):
    monkeypatch.setattr(persist, "RESULTS_DIR", tmp_path)
    d = tmp_path / "decode"; d.mkdir()
    (d / "2026-08-17_a1.json").write_text(json.dumps(
        {"job_id": "a1", "batch_id": "b1b1b1", "visitor_key": None, "saved_at": "2"}))
    (d / "2026-08-17_a2.json").write_text(json.dumps(
        {"job_id": "a2", "batch_id": "b1b1b1", "visitor_key": "a:someone", "saved_at": "1"}))
    (d / "2026-08-17_a3.json").write_text(json.dumps({"job_id": "a3", "saved_at": "3"}))
    (d / "junk.json").write_text("{not json")
    got = persist.list_batch("decode", "b1b1b1")
    assert [g["job_id"] for g in got] == ["a2", "a1"]        # saved_at order, both visitors
    assert persist.list_batch("decode", "nope") == []
    assert persist.list_batch("decode", "") == []


def test_rem_batch_csv_still_works_via_list_batch(tmp_path, monkeypatch):
    monkeypatch.setattr(persist, "RESULTS_DIR", tmp_path)
    d = tmp_path / "rem"; d.mkdir()
    (d / "2026-08-17_r1.json").write_text(json.dumps(
        {"job_id": "r1", "batch_id": "cafe01", "saved_at": "1", "codec": "h264"}))
    out = persist.rem_batch_csv("cafe01")
    assert out.splitlines()[0].startswith("job_id") or "r1" in out


def test_save_result_stamps_envelope_version(tmp_path, monkeypatch):
    monkeypatch.setattr(persist, "RESULTS_DIR", tmp_path)
    persist.save_result("decode", "zz9", {"mode": "ui_headless", "runs": []},
                        visitor_key=None)
    f = next((tmp_path / "decode").glob("*_zz9.json"))
    assert json.loads(f.read_text())["envelope_version"] == persist.ENVELOPE_VERSION == 1


# --- routes ---------------------------------------------------------------

@pytest.fixture
def _batch_on_disk(tmp_path, monkeypatch):
    monkeypatch.setattr(persist, "RESULTS_DIR", tmp_path)
    d = tmp_path / "decode"; d.mkdir()
    for e in [_env("j1", "loop_bbb_h264", [_row("gtv", 0.6), _row("firestick", 0.59)]),
              _env("j2", "loop_bbb_av1", [_row("gtv", 0.6)])]:
        (d / f"2026-08-17_{e['job_id']}.json").write_text(json.dumps(e))
    return "abc123def456"


def test_batch_page_json_csv_public(_batch_on_disk):
    bid = _batch_on_disk
    for hdrs in (_LAB, _ANON):                       # public by link
        r = client.get(f"/decode/batch/{bid}", headers=hdrs)
        assert r.status_code == 200
        assert "Decode campaign" in r.text and "+0.60" in r.text and "BBB" in r.text
        assert "/decode?job=j1" in r.text and f"/decode/batch/{bid}.csv" in r.text
    j = client.get(f"/decode/batch/{bid}.json", headers=_ANON).json()
    assert j["batch_id"] == bid and j["n_cells"] == 3 and j["devices"] == ["gtv", "firestick"]
    c = client.get(f"/decode/batch/{bid}.csv", headers=_ANON)
    assert c.status_code == 200 and c.text.startswith("batch_id,job_id,device")
    assert c.text.count("\n") >= 4                     # header + 3 rows + disclaimer


def test_batch_routes_reject_bad_and_unknown_ids(_batch_on_disk):
    assert client.get("/decode/batch/ZZ", headers=_LAB).status_code == 400
    assert client.get("/decode/batch/deadbeef00", headers=_LAB).status_code == 404
    assert client.get("/decode/batch/deadbeef00.json", headers=_LAB).status_code == 404


def test_decode_run_accepts_and_validates_batch_id(monkeypatch):
    import queue_control
    import routes_decode
    seen = {}
    monkeypatch.setattr(queue_control, "enqueue",
                        lambda job_id, kind, label, coro, **kw: seen.setdefault("q", 1))
    monkeypatch.setattr(routes_decode.decode_run, "resolve_template",
                        lambda k, u: {"label": "x", "clips": {}, "bench": {"window_s": 90}})
    monkeypatch.setattr(routes_decode.decode_run, "TEMPLATES",
                        {"bbb_h264_smoke": {"label": "x", "clips": {},
                                            "bench": {"window_s": 90}}})
    body = {"template": "bbb_h264_smoke", "mode": "headless", "devices": ["gtv"],
            "batch_id": "ZZZ"}
    assert client.post("/decode/run", json=body, headers=_LAB).status_code == 400
    body["batch_id"] = "abc123def456"
    r = client.post("/decode/run", json=body, headers=_LAB)
    assert r.status_code == 200 and r.json()["batch_id"] == "abc123def456"
    del body["batch_id"]
    r = client.post("/decode/run", json=body, headers=_LAB)
    assert r.status_code == 200 and r.json()["batch_id"] is None


def test_recent_runs_carry_batch_id_and_default_25(_batch_on_disk):
    j = client.get("/decode/runs.json", headers=_LAB).json()
    assert {r["batch_id"] for r in j["runs"]} == {_batch_on_disk}
    assert len(j["runs"]) == 2


def test_lem_csv_reads_runs_single_store(_batch_on_disk):
    r = client.get("/decode/result/j1/lem.csv", headers=_LAB)
    assert r.status_code == 200 and ",gtv,1.0" in r.text and ",firestick,1.0" in r.text


# --- stamp_batch (shared by the script and the UI) + list_batches -----------

def test_stamp_batch_idempotent_refusing_and_labels(tmp_path, monkeypatch):
    monkeypatch.setattr(persist, "RESULTS_DIR", tmp_path)
    d = tmp_path / "decode"; d.mkdir()
    (d / "2026-08-17_j1.json").write_text(json.dumps({"job_id": "j1", "saved_at": "1"}))
    (d / "2026-08-17_j2.json").write_text(json.dumps({"job_id": "j2", "batch_id": "other1",
                                                       "saved_at": "2"}))
    # dry-run writes nothing
    r = persist.stamp_batch("decode", "abc123", ["j1"], apply=False)
    assert r["stamped"] == ["j1"] and "batch_id" not in json.loads((d / "2026-08-17_j1.json").read_text())
    # apply + label; second apply skips but refreshes label
    r = persist.stamp_batch("decode", "abc123", ["j1"], label="Night one")
    assert r["stamped"] == ["j1"]
    f = json.loads((d / "2026-08-17_j1.json").read_text())
    assert f["batch_id"] == "abc123" and f["batch_label"] == "Night one"
    r = persist.stamp_batch("decode", "abc123", ["j1"], label="Night ONE")
    assert r["skipped"] == ["j1"] and r["stamped"] == []
    assert json.loads((d / "2026-08-17_j1.json").read_text())["batch_label"] == "Night ONE"
    # refuse: different batch / unknown id → nothing written at all
    r = persist.stamp_batch("decode", "abc123", ["j1", "j2"])
    assert r["refused"] == {"j2": "already in batch other1"} and r["stamped"] == []
    r = persist.stamp_batch("decode", "abc123", ["nope"])
    assert "nope" in r["refused"]
    # inventory
    inv = persist.list_batches("decode")
    assert [b["batch_id"] for b in inv] == ["other1", "abc123"]      # newest last-activity first
    a = [b for b in inv if b["batch_id"] == "abc123"][0]
    assert a["label"] == "Night ONE" and a["n_jobs"] == 1 and a["job_ids"] == ["j1"]


def test_stamp_script_delegates_to_persist(tmp_path, monkeypatch):
    """bin/stamp-decode-batch is a thin CLI over persist.stamp_batch."""
    monkeypatch.setattr(persist, "RESULTS_DIR", tmp_path)
    d = tmp_path / "decode"; d.mkdir()
    (d / "2026-08-17_j1.json").write_text(json.dumps({"job_id": "j1"}))
    src = _SCRIPT.read_text()
    assert "persist.stamp_batch" in src and "--label" in src
    r = subprocess.run([sys.executable, str(_SCRIPT), "XYZ", "j1"], capture_output=True, text=True)
    assert r.returncode == 2                                        # bad id, before any IO


_SCRIPT = Path(__file__).resolve().parents[2] / "bin" / "stamp-decode-batch"


# --- list page + stamp route -----------------------------------------------

def test_batches_list_page_and_json_public(_batch_on_disk):
    bid = _batch_on_disk
    for hdrs in (_LAB, _ANON):
        r = client.get("/decode/batches", headers=hdrs)
        assert r.status_code == 200 and bid in r.text and "Decode campaigns" in r.text
    j = client.get("/decode/batches.json", headers=_ANON).json()
    assert j["batches"][0]["batch_id"] == bid and j["batches"][0]["n_jobs"] == 2
    assert j["batches"][0]["devices"] == ["firestick", "gtv"]


def test_stamp_route_lab_only_labels_and_refuses(_batch_on_disk, tmp_path):
    bid = _batch_on_disk
    d = tmp_path / "decode"
    (d / "2026-08-17_solo.json").write_text(json.dumps(_env("solo", "loop_bbb_h265",
                                                             [_row("gtv", 0.3)], batch_id=None)))
    (d / "2026-08-17_elsewhere.json").write_text(json.dumps(_env("elsewhere", "loop_bbb_h265",
                                                                  [_row("gtv", 0.3)], batch_id="ffffff")))
    # Anonymous cannot stamp
    assert client.post(f"/decode/batch/{bid}/stamp", json={"job_ids": ["solo"]},
                       headers=_ANON).status_code == 403
    # add + label
    r = client.post(f"/decode/batch/{bid}/stamp", json={"job_ids": ["solo"], "label": "Test night"},
                    headers=_LAB)
    assert r.status_code == 200 and r.json()["stamped"] == ["solo"]
    m = client.get(f"/decode/batch/{bid}.json", headers=_ANON).json()
    assert m["label"] == "Test night" and len(m["jobs"]) == 3
    assert "Test night" in client.get(f"/decode/batch/{bid}", headers=_ANON).text
    # label-only relabels every file in the batch
    r = client.post(f"/decode/batch/{bid}/stamp", json={"label": "Renamed"}, headers=_LAB)
    assert r.status_code == 200
    assert client.get(f"/decode/batch/{bid}.json", headers=_ANON).json()["label"] == "Renamed"
    # refuse cross-batch move; nothing changes
    r = client.post(f"/decode/batch/{bid}/stamp", json={"job_ids": ["elsewhere"]}, headers=_LAB)
    assert r.status_code == 409 and "elsewhere" in r.json()["refused"]
    assert json.loads((d / "2026-08-17_elsewhere.json").read_text())["batch_id"] == "ffffff"
    # bad / empty
    assert client.post("/decode/batch/ZZ/stamp", json={"job_ids": ["solo"]}, headers=_LAB).status_code == 400
    assert client.post(f"/decode/batch/{bid}/stamp", json={}, headers=_LAB).status_code == 400
    assert client.post("/decode/batch/abcdef012345/stamp", json={"label": "x"}, headers=_LAB).status_code == 404
