"""CR-051 — manifest + sanitisation helpers.

Security-relevant module; the sanitisation tests are the "no path traversal"
audit. The can_delete tests pin the tier×ownership matrix so a refactor to
the auth logic can't silently widen who can delete what.
"""
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

import corpus_manifest as cm


# --- Fixture: isolate manifest storage per-test ------------------------------

@pytest.fixture
def tmp_corpus(tmp_path, monkeypatch):
    """Re-point corpus_path to a clean tmp dir so the test never touches
    the real `corpus/papers/` or `corpus/manifest.json`. cfg.load() is
    patched at the module level for the duration of one test."""
    papers = tmp_path / "papers"
    papers.mkdir()
    fake_cfg = {"rag_corpus_path": str(papers)}
    monkeypatch.setattr(cm.cfg, "load", lambda: fake_cfg)
    return papers


# --- sanitise_filename + unique_filename ------------------------------------

def test_sanitise_strips_path_components():
    # Path traversal attempts (the only thing this absolutely MUST defend)
    assert cm.sanitise_filename("../../etc/passwd") == "passwd.pdf"
    assert cm.sanitise_filename("/etc/passwd.pdf") == "passwd.pdf"
    assert cm.sanitise_filename("../../root.pdf") == "root.pdf"

def test_sanitise_restricts_charset():
    assert cm.sanitise_filename("hello world.pdf") == "hello_world.pdf"
    assert cm.sanitise_filename("naïve résumé.pdf") == "na_ve_r_sum_.pdf"
    assert cm.sanitise_filename("a;b|c$.pdf") == "a_b_c_.pdf"

def test_sanitise_adds_pdf_extension():
    assert cm.sanitise_filename("notes").endswith(".pdf")
    assert cm.sanitise_filename("notes.pdf") == "notes.pdf"

def test_sanitise_handles_empty_or_dotty():
    # Hidden-file names and extension-only should not produce dot-files
    assert not cm.sanitise_filename(".").startswith(".")
    assert cm.sanitise_filename("").endswith(".pdf")
    assert cm.sanitise_filename(".pdf").endswith(".pdf")

def test_unique_filename_suffixes_on_collision(tmp_corpus):
    (tmp_corpus / "doc.pdf").write_bytes(b"%PDF-1.4\n")
    assert cm.unique_filename("doc.pdf") == "doc-2.pdf"
    (tmp_corpus / "doc-2.pdf").write_bytes(b"%PDF-1.4\n")
    assert cm.unique_filename("doc.pdf") == "doc-3.pdf"

def test_unique_filename_passthrough_when_free(tmp_corpus):
    assert cm.unique_filename("brand_new.pdf") == "brand_new.pdf"


# --- can_delete (tier × ownership matrix) -----------------------------------

def test_can_delete_anonymous_never(tmp_corpus):
    (tmp_corpus / "any.pdf").write_bytes(b"%PDF-1.4\n")
    assert cm.can_delete("any.pdf", "Anonymous", None) is False

def test_can_delete_lab_anything(tmp_corpus):
    (tmp_corpus / "lab_doc.pdf").write_bytes(b"%PDF-1.4\n")
    cm.record_upload("lab_doc.pdf", added_by="someone@else.com",
                      origin="Member", size_bytes=10)
    assert cm.can_delete("lab_doc.pdf", "Lab", None) is True
    # Lab doesn't even need an email
    assert cm.can_delete("lab_doc.pdf", "Lab", "any@thing.com") is True

def test_can_delete_member_own_only(tmp_corpus):
    (tmp_corpus / "alice_doc.pdf").write_bytes(b"%PDF-1.4\n")
    (tmp_corpus / "bob_doc.pdf").write_bytes(b"%PDF-1.4\n")
    cm.record_upload("alice_doc.pdf", added_by="alice@example.com",
                      origin="Member", size_bytes=10)
    cm.record_upload("bob_doc.pdf", added_by="bob@example.com",
                      origin="Member", size_bytes=10)
    assert cm.can_delete("alice_doc.pdf", "Member", "alice@example.com") is True
    assert cm.can_delete("bob_doc.pdf",   "Member", "alice@example.com") is False
    # Case-insensitive match (emails normalised when stored)
    assert cm.can_delete("alice_doc.pdf", "Member", "ALICE@example.COM") is True

def test_can_delete_member_lab_origin_blocked(tmp_corpus):
    """Members can't delete Lab-origin docs even though they have the cap."""
    (tmp_corpus / "seed_doc.pdf").write_bytes(b"%PDF-1.4\n")
    # ensure_entry stamps as Lab for files that exist without a manifest row
    cm.ensure_entry("seed_doc.pdf")
    assert cm.can_delete("seed_doc.pdf", "Member", "alice@example.com") is False


# --- manifest round-trip + ensure_entry self-healing ------------------------

def test_ensure_entry_creates_lab_entry_for_existing_file(tmp_corpus):
    (tmp_corpus / "dropped_in.pdf").write_bytes(b"%PDF-1.4\n" + b"x" * 100)
    entry = cm.ensure_entry("dropped_in.pdf")
    assert entry["origin"] == "Lab"
    assert entry["added_by"] == "Lab"
    assert entry["size_bytes"] > 0
    # Idempotent
    again = cm.ensure_entry("dropped_in.pdf")
    assert again == entry

def test_ensure_entry_returns_empty_when_file_missing(tmp_corpus):
    assert cm.ensure_entry("not_a_real_file.pdf") == {}

def test_record_upload_then_record_delete(tmp_corpus):
    cm.record_upload("paper.pdf", added_by="alice@example.com",
                      origin="Member", size_bytes=1234, title="Alice's paper")
    m = cm.load_manifest()
    assert m["paper.pdf"]["added_by"] == "alice@example.com"
    assert m["paper.pdf"]["size_bytes"] == 1234
    cm.record_delete("paper.pdf", actor="alice@example.com", tier="Member")
    assert "paper.pdf" not in cm.load_manifest()
    # Audit log keeps both events
    events = cm.read_audit()
    assert events[-2]["event"] == "upload"
    assert events[-1]["event"] == "delete"

def test_member_usage_aggregates_per_email(tmp_corpus):
    cm.record_upload("a1.pdf", added_by="alice@example.com",
                      origin="Member", size_bytes=100)
    cm.record_upload("a2.pdf", added_by="alice@example.com",
                      origin="Member", size_bytes=200)
    cm.record_upload("b1.pdf", added_by="bob@example.com",
                      origin="Member", size_bytes=300)
    u_alice = cm.member_usage("alice@example.com")
    assert u_alice["file_count"] == 2
    assert u_alice["total_bytes"] == 300
    u_bob = cm.member_usage("bob@example.com")
    assert u_bob == {"file_count": 1, "total_bytes": 300}
    assert cm.member_usage("nobody@example.com") == {"file_count": 0, "total_bytes": 0}


# --- migration idempotency --------------------------------------------------

def test_migrate_is_idempotent(tmp_corpus):
    for n in range(3):
        (tmp_corpus / f"doc{n}.pdf").write_bytes(b"%PDF-1.4\n")
    first = cm.migrate_existing_corpus()
    second = cm.migrate_existing_corpus()
    assert first == 3
    assert second == 0   # nothing new to stamp
    m = cm.load_manifest()
    assert all(m[f"doc{n}.pdf"]["origin"] == "Lab" for n in range(3))
