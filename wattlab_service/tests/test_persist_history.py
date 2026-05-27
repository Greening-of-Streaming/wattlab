"""CR-012 — persist.append_history_line tests.

Covers the drift-tracking JSONL journal used by variance calibration
(`results/variance/history.jsonl`) and the thermal-recovery probe
(`results/diagnostics/history.jsonl`). Append-only, no overwrites.
"""
import json
from pathlib import Path

import pytest

import persist


@pytest.fixture
def tmp_results(monkeypatch, tmp_path):
    monkeypatch.setattr(persist, "RESULTS_DIR", tmp_path)
    return tmp_path


def _read_lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_creates_subdir_and_writes_one_line(tmp_results):
    path = persist.append_history_line("variance", {"variance_pct": 1.29})
    assert path == tmp_results / "variance" / "history.jsonl"
    assert path.exists()
    [line] = _read_lines(path)
    assert line["variance_pct"] == 1.29


def test_appends_does_not_overwrite(tmp_results):
    persist.append_history_line("variance", {"variance_pct": 1.29})
    persist.append_history_line("variance", {"variance_pct": 1.34})
    persist.append_history_line("variance", {"variance_pct": 1.28})
    lines = _read_lines(tmp_results / "variance" / "history.jsonl")
    assert [l["variance_pct"] for l in lines] == [1.29, 1.34, 1.28]


def test_stamps_ts_and_owl_version(tmp_results):
    persist.append_history_line("variance", {"variance_pct": 1.29})
    [line] = _read_lines(tmp_results / "variance" / "history.jsonl")
    # ts is ISO-formatted
    assert "T" in line["ts"]
    # owl_version is the same shape persist.save_result stamps
    assert "version" in line["owl_version"]
    assert "sha" in line["owl_version"]


def test_diagnostics_category_separates_from_variance(tmp_results):
    persist.append_history_line("variance", {"variance_pct": 1.29})
    persist.append_history_line("diagnostics", {"kind": "probe", "n_pairs": 12})
    assert (tmp_results / "variance" / "history.jsonl").exists()
    assert (tmp_results / "diagnostics" / "history.jsonl").exists()
    var_lines = _read_lines(tmp_results / "variance" / "history.jsonl")
    diag_lines = _read_lines(tmp_results / "diagnostics" / "history.jsonl")
    assert len(var_lines) == 1 and len(diag_lines) == 1
    assert "variance_pct" in var_lines[0]
    assert diag_lines[0]["kind"] == "probe"


def test_payload_fields_preserved_verbatim(tmp_results):
    payload = {
        "variance_pct": 1.29,
        "variance_idle_pct": 2.3,
        "variance_cpu_pct": 0.95,
        "variance_gpu_pct": 0.63,
        "w_base_mean": 56.4,
        "runs": 10,
        "kernel": "6.17.0-23-generic",
    }
    persist.append_history_line("variance", payload)
    [line] = _read_lines(tmp_results / "variance" / "history.jsonl")
    for k, v in payload.items():
        assert line[k] == v
