"""
S41 regression guard — pages must not hardcode a default model key.

The /llm and /rag model panels render from live views (catalog ∩
*_enabled_models setting ∩ `ollama list`), so any key can vanish between
sessions. The pages used to hardcode `tinyllama` as the JS default; when it
dropped out of llm_enabled_models the dead getElementById killed /llm's whole
init block (empty prompt box, no selection, stale key submitted → "Invalid
model"). These tests pin the fix: the served default must be the first model
card actually rendered.
"""
import re

import pytest
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)
LAB = {"x-real-ip": "127.0.0.1"}

CASES = [
    ("/llm", r"id=\"model-([^\"]+)\"", r"let selectedModel = '([^']*)'"),
    ("/rag", r"id=\"rmodel-([^\"]+)\"", r"let selectedRModel = '([^']*)'"),
]


@pytest.mark.parametrize("path,card_re,default_re", CASES)
def test_default_model_is_first_rendered_card(path, card_re, default_re):
    html = client.get(path, headers=LAB).text
    cards = re.findall(card_re, html)
    assert cards, f"{path} rendered no model cards (is ollama down?)"
    m = re.search(default_re, html)
    assert m, f"{path} no longer declares a JS default model"
    assert m.group(1) == cards[0], (
        f"{path} JS default {m.group(1)!r} != first rendered card {cards[0]!r} "
        "— a hardcoded/stale default key is how the S41 empty-prompt/'Invalid "
        "model' regression happened")


@pytest.mark.parametrize("path,card_re,default_re", CASES)
def test_default_model_exists_as_card(path, card_re, default_re):
    html = client.get(path, headers=LAB).text
    cards = set(re.findall(card_re, html))
    key = re.search(default_re, html).group(1)
    assert key in cards, f"{path} default {key!r} has no rendered card"
