"""CR-047 — parent + variants schema in sources.py. These pin both the
new accessors (get_grouped_sources, get_variant, get_parent_for) and the
back-compat surface (PRELOADED dict, get_source_info, get_all_sources)
so anything that touched the picker pre-CR-047 keeps working.
"""
from pathlib import Path

import pytest

import sources


# --- shape of the new schema ---

def test_sources_parents_in_canonical_order():
    ids = [s["id"] for s in sources.SOURCES]
    assert ids == ["gos", "meridian", "bbb", "kranjska"]


def test_every_parent_has_name_credit_variants():
    for s in sources.SOURCES:
        assert s["name"]
        assert s["credit"]
        assert isinstance(s["variants"], list) and len(s["variants"]) >= 1


def test_variant_keys_globally_unique():
    keys = [v["key"] for s in sources.SOURCES for v in s["variants"]]
    assert len(keys) == len(set(keys))


def test_each_variant_has_required_fields():
    for s in sources.SOURCES:
        for v in s["variants"]:
            assert v["key"]
            assert v["label"]
            assert v["description"]
            assert v["length"] in {"full", "extract"}
            assert isinstance(v["path"], Path)


def test_each_parent_has_one_full_variant():
    """The 'full' length is the canonical reference per source — the
    picker should always offer it. (Extracts can be skipped, e.g. the
    GoS-50s parent has no 2-min extract because it's already short.)"""
    for s in sources.SOURCES:
        lengths = {v["length"] for v in s["variants"]}
        assert "full" in lengths, f"{s['id']} missing a 'full' variant"


# --- accessors ---

def test_get_variant_resolves_known_key():
    v = sources.get_variant("meridian_120s")
    assert v is not None
    assert v["key"] == "meridian_120s"
    assert v["length"] == "extract"


def test_get_variant_returns_none_for_unknown():
    assert sources.get_variant("not_a_real_key") is None


def test_get_parent_for_resolves():
    p = sources.get_parent_for("bbb_4k")
    assert p is not None
    assert p["id"] == "bbb"


def test_get_parent_for_unknown_returns_none():
    assert sources.get_parent_for("not_a_real_key") is None


# --- back-compat: PRELOADED dict ---

def test_preloaded_has_every_variant_key():
    expected = {v["key"] for s in sources.SOURCES for v in s["variants"]}
    assert set(sources.PRELOADED.keys()) == expected


def test_preloaded_entries_keep_legacy_shape():
    """main.py:/video/use-source still reads .label, .path, .credit,
    .description off the PRELOADED entry — don't break that contract."""
    for key, entry in sources.PRELOADED.items():
        assert "label" in entry
        assert "path" in entry and isinstance(entry["path"], Path)
        assert "credit" in entry
        assert "description" in entry


def test_preloaded_label_is_parent_prefixed():
    """Queue labels read this, so the parent-prefixed form is the contract."""
    e = sources.PRELOADED["meridian_120s"]
    assert e["label"].startswith("Meridian 4K")


# --- back-compat: get_source_info / get_all_sources ---

def test_get_source_info_known_key_shape():
    info = sources.get_source_info("bbb_120s")
    assert info is not None
    # legacy fields (pre-CR-047)
    assert info["key"] == "bbb_120s"
    assert info["label"].startswith("Big Buck Bunny 4K")
    assert info["description"]
    assert info["credit"]
    assert info["path"]
    # ffprobe-filled (file is on disk)
    assert info["resolution"] == "3840x2160"
    assert info["codec"] == "h264"
    # CR-047 additions
    assert info["variant_label"] == "2 min extract"
    assert info["parent"] == "bbb"
    assert info["parent_name"] == "Big Buck Bunny 4K"
    assert info["length"] == "extract"


def test_get_all_sources_returns_flat_list_of_all_variants():
    flat = sources.get_all_sources()
    keys = {s["key"] for s in flat}
    assert keys == set(sources.PRELOADED.keys())


def test_get_all_sources_preserves_parent_then_variant_order():
    """Anything iterating /video/sources expects the canonical order:
    GoS → Meridian (extract, full) → BBB (extract, full)."""
    flat = sources.get_all_sources()
    keys = [s["key"] for s in flat]
    assert keys == ["gos_in_50s", "meridian_120s", "meridian_4k",
                    "bbb_120s", "bbb_4k", "kranjska_120s", "kranjska_full"]


# --- get_grouped_sources (new accessor for the picker) ---

def test_get_grouped_sources_returns_parent_blocks():
    g = sources.get_grouped_sources()
    assert [p["id"] for p in g] == ["gos", "meridian", "bbb", "kranjska"]


def test_get_grouped_sources_each_parent_has_variants_field():
    for p in sources.get_grouped_sources():
        assert "variants" in p
        assert isinstance(p["variants"], list)
        assert len(p["variants"]) >= 1


def test_get_grouped_sources_variant_shape_matches_get_source_info():
    """Picker template reads one schema for both flat + grouped views.
    The per-variant dict in get_grouped_sources()[*].variants[*] is the
    same shape as get_source_info() returns."""
    g = sources.get_grouped_sources()
    bbb = next(p for p in g if p["id"] == "bbb")
    bbb_120s_grouped = next(v for v in bbb["variants"] if v["key"] == "bbb_120s")
    bbb_120s_flat = sources.get_source_info("bbb_120s")
    assert bbb_120s_grouped == bbb_120s_flat
