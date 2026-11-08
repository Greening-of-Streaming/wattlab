"""
TEMPORARY — /findings redesign preview for the Marketing Lab (2026-10-16),
extended for the WattLab call of 2026-11-05 (CR-086).

Hidden preview of the redesigned findings catalog, built around what the
industry asks rather than how OWL is organised: a "where the watts go" chart up
front, plain-language headlines over the technical claim, search + filters, and
an "Early signals" shelf for findings below the n=3 bar. Served under the same
unguessable, noindexed prefix as routes_mockups.py.

CR-086 adds, from the 5 Nov call:
  - two layouts to compare and vote on (`?v=questions|workflow`): the
    reader-question menu, and the streaming workflow drawn as a diagram, gaps
    included (Tania). `?v=quiz` still works: Questions with the test open
  - a question on every finding (Barbara: gamify it), asked in a window that
    covers the finding, plus a "Test my knowledge" pop-down of the main-shelf
    questions (Dom, Tania). Answers are checked in the browser and never stored
  - "Why does this matter?" on every finding (Barbara)
  - a review status beside the measurement confidence: the two are separate axes
  - 👍 / ❓ on every finding, no thumbs-down (Dom) — stored by finding_feedback.py
  - a Lab-only review queue that ranks findings for the group review (Martin)
  - a "Data only" shelf with the raw measurements and no interpretation (Tania)

Reads:
  docs/findings/taxonomy.yaml             — controlled vocabulary (questions, facets, stages, synonyms)
  docs/findings_drafts/plain_overlay.yaml — per-slug plain headline, question, tags, n_runs, stages,
                                            review_status, why_it_matters, quiz;
                                            `draft: true` pulls a finding from docs/findings_drafts/
Writes only through finding_feedback.py (votes). Live finding files are
untouched; the overlay moves into frontmatter in CR-086 Phase B.

DELETE THIS MODULE (and its main.py registration) when the redesign ships.
"""
import hashlib
import html as html_lib
import io
import json
from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

import analytics
import audience
import capabilities
import finding_feedback as feedback
import findings as findings_mod
import ui
from capabilities import requires, PUBLIC_PAGE, FINDINGS_REVIEW
from persist import load_result
from routes_mockups import _PREFIX, _NOINDEX

router = APIRouter()

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TAXONOMY_PATH = _REPO_ROOT / "docs" / "findings" / "taxonomy.yaml"
_OVERLAY_PATH = _REPO_ROOT / "docs" / "findings_drafts" / "plain_overlay.yaml"

_DEFAULT_MIN_N = 3          # WattLab call 2026-09-03: n=3 to leave the room
_CHIP_FACETS = ("where", "lever", "hardware", "codec")

_CONF_PLAIN = {
    "green":  ("🟢", "Solid", "clear of measurement noise"),
    "yellow": ("🟡", "Indicative", "direction clear, size less certain"),
    "red":    ("🔴", "Unconfirmed", "within measurement noise"),
}

# Review status — a separate axis from the measurement confidence above, and
# deliberately not traffic-light coloured, so nobody reads "red" as "wrong".
# (label, tooltip, sort rank for the review queue)
_REVIEW = {
    "machine-draft":   ("Draft &middot; awaiting lab review",
                        "Written from the stored data; not yet checked by a lab member.", 0),
    "lab-checked":     ("Lab-checked",
                        "Checked against the stored data by a lab member; not yet reviewed by the group.", 1),
    "group-validated": ("Validated by the WattLab group",
                        "Reviewed and agreed at a WattLab meeting.", 2),
    "not-reproduced":  ("Not reproduced",
                        "An earlier result we could not repeat. Kept on record so the claim can be traced.", -1),
}

_VARIANTS = {
    "questions": ("Questions", "Browse by the question a reader brings"),
    "workflow":  ("Workflow", "Browse by stage of the streaming chain, gaps included"),
}
_DEFAULT_VARIANT = "questions"

# "Where the watts go" — every bar is a number from a finding's stored result,
# linked to that finding. Kept here (not computed) so the chart is reviewed
# like copy; the finding pages carry the CIs and provenance.
_WATTS = [
    ("What draws power while watching", [
        ("TV screen (55-inch OLED)", 52.80, "total", "tv-screen-draws-20x-the-streaming-box",
         "LG C2 panel, HD SDR, Filmmaker mode: 52.80 ±0.10 W, n=3"),
        ("Streaming box feeding it", 1.93, "total", "tv-screen-draws-20x-the-streaming-box",
         "Google TV Streamer, same rows: 1.93 ±0.01 W, n=3"),
    ]),
    ("What one choice adds", [
        ("Vivid picture mode instead of Standard", 20.36, "add", "tv-picture-mode-outweighs-streaming-choices",
         "Football: 73.05 W vs 52.69 W, 95 % CI +19.9 to +20.8 W, n=3"),
        ("HDR instead of SDR, at the screen", 3.92, "add", "hdr-costs-the-screen-4k-costs-the-box",
         "Panel +3.92 W (+7.4 %), HD Filmmaker, n=3; the box +0.01 W"),
        ("4K instead of HD, at the box", 0.41, "add", "hdr-costs-the-screen-4k-costs-the-box",
         "Google TV Streamer +0.41 W (+21 %), n=3; the screen +0.05 W"),
        ("128× the bitrate, at the box", 0.44, "add", "bitrate-barely-moves-box-playback-power",
         "Google TV Streamer, 0.25 → 32 Mb/s: +0.44 W (+26 %), n=3"),
    ]),
]

_STYLES = """
  body { font-family: system-ui, -apple-system, sans-serif; background: var(--bg); color: var(--text);
         max-width: 980px; margin: 0 auto; padding: 2rem; }
  h1 { font-family: monospace; color: var(--accent); font-size: 1.6rem; margin: 0 0 0.6rem; }
  h2 { font-family: monospace; color: var(--accent); font-size: 1.05rem; margin: 2.5rem 0 0.9rem; }
  .fx-preview { color: var(--text-4); font-family: monospace; font-size: 0.72rem; margin: 0 0 1.25rem;
    border-left: 2px solid var(--warn); padding-left: 0.6rem }
  .fx-preview b { color: var(--warn); font-weight: normal }
  .fx-variants { display: flex; flex-wrap: wrap; gap: 0.4rem 1rem; align-items: baseline; font-family: monospace;
    font-size: 0.78rem; color: var(--text-4); margin: -0.5rem 0 1.5rem }
  .fx-variants a { color: var(--text-2); text-decoration: none; border-bottom: 1px dotted var(--border-3) }
  .fx-variants a:hover { color: var(--accent) }
  .fx-variants a[aria-current="page"] { color: var(--accent); border-bottom: 2px solid var(--accent) }
  .fx-variants .fx-lab { margin-left: auto }
  .fx-lede { color: var(--text-2); line-height: 1.75; max-width: 680px; margin: 0 0 0.5rem; font-size: 1rem }
  .fx-proof { color: var(--text-3); font-size: 0.82rem; margin: 0 0 0.5rem }
  .fx-axes { color: var(--text-3); font-size: 0.8rem; line-height: 1.6; max-width: 680px; margin: 0 0 1.75rem }
  .fx-fig { border: 1px solid var(--border); background: var(--panel-2); padding: 1.2rem 1.25rem 1rem;
    display: flex; flex-direction: column; gap: 0.6rem }
  .fx-fig-title { font-size: 1.05rem; font-weight: 600; color: var(--text) }
  .fx-fig-sub { font-size: 0.8rem; color: var(--text-3) }
  .fx-legend { display: flex; gap: 1rem; flex-wrap: wrap; font-size: 0.75rem; color: var(--text-3) }
  .fx-legend i { display: inline-block; width: 11px; height: 11px; border-radius: 2px; margin-right: 0.35rem;
    vertical-align: -1px }
  .fx-chart { overflow-x: auto }
  .fx-chart svg { display: block; width: 100%; min-width: 640px; height: auto }
  .fx-chart text { fill: var(--text-2); font-size: 12.5px; font-family: system-ui, -apple-system, sans-serif }
  .fx-chart .grp { fill: var(--text-4); font-family: monospace; font-size: 10.5px; letter-spacing: 0.06em }
  .fx-chart .val { fill: var(--text); font-family: monospace; font-size: 12px; font-weight: bold }
  .fx-chart .axis { fill: var(--text-4); font-family: monospace; font-size: 10.5px }
  .fx-chart .grid { stroke: var(--border); stroke-width: 1 }
  .fx-chart .b-total { fill: var(--accent) }
  .fx-chart .b-add { fill: var(--text-4) }
  .fx-chart a:hover .bar, .fx-chart a:focus .bar { opacity: 0.75 }
  .fx-chart a:hover text.lbl { fill: var(--accent) }
  .fx-fig-note { font-size: 0.82rem; color: var(--text-2); line-height: 1.6; margin: 0.2rem 0 0 }
  .fx-fig-cap { font-size: 0.72rem; color: var(--text-4); line-height: 1.5; margin: 0 }
  .fx-themes { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 0.6rem }
  .fx-theme { text-align: left; background: var(--panel-2); border: 1px solid var(--border);
    border-left: 3px solid var(--border-3); color: var(--text); padding: 0.8rem 0.9rem; cursor: pointer;
    font: inherit; line-height: 1.4; display: flex; flex-direction: column; justify-content: flex-start; gap: 0.25rem }
  .fx-theme:hover { border-left-color: var(--accent) }
  .fx-theme:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px }
  .fx-theme[aria-pressed="true"] { border-color: var(--accent-soft); border-left-color: var(--accent);
    background: var(--panel) }
  .fx-theme b { font-size: 0.93rem }
  .fx-theme span { color: var(--text-4); font-family: monospace; font-size: 0.7rem; letter-spacing: 0.04em }
  .fx-theme .fx-n { color: var(--accent) }
  .fx-flow { overflow-x: auto; border: 1px solid var(--border); background: var(--panel-2); padding: 1rem 1rem 0.75rem }
  .fx-flow svg { display: block; width: 100%; min-width: 700px; height: auto }
  .fx-flow text { font-family: system-ui, -apple-system, sans-serif; font-size: 12.5px; fill: var(--text) }
  .fx-flow .st-n { font-family: monospace; font-size: 11px; fill: var(--accent) }
  .fx-flow .st-gap { font-family: monospace; font-size: 10.5px; fill: var(--text-4) }
  .fx-flow .st-box { fill: var(--panel); stroke: var(--border-3); stroke-width: 1.2 }
  .fx-flow .st-box.has { stroke: var(--accent) }
  .fx-flow .st-box.gap { fill: none; stroke-dasharray: 5 4 }
  .fx-flow .st-box.on { fill: var(--accent-soft); stroke-width: 2.4 }
  .fx-flow .arrow { stroke: var(--text-4); stroke-width: 1.2; fill: none }
  .fx-flow .side-lbl { font-family: monospace; font-size: 10.5px; fill: var(--text-4); letter-spacing: 0.06em }
  .fx-flow a:hover .st-box, .fx-flow a:focus .st-box { stroke: var(--accent); stroke-width: 2 }
  .fx-gaps { margin: 0.75rem 0 0; display: grid; grid-template-columns: max-content 1fr; gap: 0.35rem 0.9rem;
    font-size: 0.8rem; line-height: 1.55 }
  .fx-gaps dt { color: var(--text-3); font-family: monospace; font-size: 0.74rem }
  .fx-gaps dd { margin: 0; color: var(--text-3) }
  .fx-stage-note { color: var(--text-2); font-size: 0.85rem; line-height: 1.6; margin: 0.75rem 0 0 }
  .fx-quizzes { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 0.6rem }
  .fx-quiz { border: 1px solid var(--border); border-left: 3px solid var(--accent); background: var(--panel-2);
    padding: 0.9rem 1rem; display: flex; flex-direction: column; gap: 0.6rem }
  .fx-quiz p.q { margin: 0; font-weight: 600; line-height: 1.45; font-size: 0.95rem }
  .fx-opts { display: flex; flex-direction: column; gap: 0.35rem }
  .fx-opt { text-align: left; background: none; border: 1px solid var(--border-3); color: var(--text-2);
    padding: 0.4rem 0.7rem; font: inherit; font-size: 0.85rem; cursor: pointer }
  .fx-opt:hover { border-color: var(--accent) }
  .fx-opt.right { border-color: var(--accent); color: var(--accent) }
  .fx-opt.wrong { border-color: var(--warn); color: var(--warn); text-decoration: line-through }
  .fx-ans > summary[hidden] { display: none }
  .fx-verdict { margin: 0; font-weight: 600; font-size: 0.9rem; color: var(--accent) }
  .fx-verdict.no { color: var(--warn) }
  .fx-verdict:empty { display: none }
  .fx-test-open { background: none; border: 1px solid var(--accent); color: var(--accent); padding: 0.3rem 0.7rem;
    font: inherit; font-size: 0.8rem; cursor: pointer }
  .fx-test-open:hover { background: var(--panel-2) }
  dialog.fx-test { box-sizing: border-box; position: fixed; inset: 0; width: 100%; max-width: none; height: 100dvh; max-height: none; margin: 0;
    border: 0; padding: 1.25rem 1rem; background: var(--bg); color: var(--text); font-size: 1rem; overflow-y: auto }
  body:has(dialog.fx-test[open]) { overflow: hidden }
  .fx-test-in { max-width: 560px; margin: 0 auto; display: flex; flex-direction: column; gap: 1rem; padding-top: 8vh }
  .fx-test-top { display: flex; justify-content: space-between; align-items: center; color: var(--text-3);
    font-family: monospace; font-size: 0.78rem }
  .fx-test-close { background: none; border: 1px solid var(--border-3); color: var(--text-2); padding: 0.3rem 0.7rem;
    font: inherit; font-size: 0.8rem; cursor: pointer }
  .fx-test-back { align-self: flex-start; border-color: var(--accent); color: var(--accent) }
  .fx-ans > summary { cursor: pointer; color: var(--text-4); font-size: 0.75rem; font-family: monospace }
  .fx-ans p { margin: 0.4rem 0 0; color: var(--text-2); font-size: 0.85rem; line-height: 1.6 }
  .fx-ans a { color: var(--accent) }
  .fx-score { font-family: monospace; color: var(--accent); font-size: 0.85rem; margin: 0.6rem 0 0 }
  .fx-tools { display: flex; flex-direction: column; gap: 0.5rem; margin: 1.25rem 0 0.5rem }
  .fx-search { width: 100%; box-sizing: border-box; background: var(--panel-2); color: var(--text);
    border: 1px solid var(--border-3); padding: 0.65rem 0.8rem; font-size: 0.95rem; font-family: inherit }
  .fx-search:focus { outline: none; border-color: var(--accent) }
  details.fx-filters > summary { cursor: pointer; color: var(--text-3); font-size: 0.82rem; font-family: monospace }
  .fx-facets { display: flex; flex-direction: column; gap: 0.45rem; padding: 0.75rem 0 0.25rem }
  .fx-facet { display: flex; flex-wrap: wrap; gap: 0.35rem; align-items: baseline }
  .fx-facet-label { color: var(--text-4); font-family: monospace; font-size: 0.7rem; min-width: 10rem }
  .fx-chip { background: none; border: 1px solid var(--border-3); color: var(--text-2); padding: 0.15rem 0.6rem;
    font-size: 0.75rem; cursor: pointer; border-radius: 999px; font-family: inherit }
  .fx-chip:hover { border-color: var(--accent) }
  .fx-chip[aria-pressed="true"] { background: var(--accent-soft); border-color: var(--accent); color: var(--accent) }
  .fx-chip small { color: var(--text-4); margin-left: 0.25rem }
  .fx-status { color: var(--text-3); font-size: 0.8rem; margin: 0.25rem 0; font-family: monospace }
  .fx-status button { background: none; border: none; color: var(--accent); cursor: pointer; font: inherit;
    text-decoration: underline; padding: 0 }
  .fx-list { display: flex; flex-direction: column; gap: 0.6rem }
  .fx-card { border: 1px solid var(--border); border-left: 3px solid var(--accent); background: var(--panel-2);
    padding: 0.95rem 1.05rem; display: flex; flex-direction: column; gap: 0.5rem }
  .fx-card.early { border-left-color: var(--border-3) }
  .fx-q { color: var(--text-4); font-family: monospace; font-size: 0.68rem; letter-spacing: 0.05em;
    text-transform: uppercase }
  .fx-card h3 { margin: 0; font-size: 1.04rem; line-height: 1.45; font-weight: 600 }
  .fx-card h3 a { color: var(--text); text-decoration: none }
  .fx-card h3 a:hover { color: var(--accent) }
  .fx-meta { display: flex; flex-wrap: wrap; gap: 0.35rem 0.9rem; align-items: baseline; font-size: 0.78rem }
  .fx-pill { border: 1px solid var(--border-3); padding: 0.05rem 0.55rem; border-radius: 999px; color: var(--text-2);
    white-space: nowrap }
  .fx-draft { border-color: var(--warn); color: var(--warn) }
  .fx-rev { border-style: dashed }
  .fx-rev.validated { border-style: solid; border-color: var(--accent); color: var(--accent) }
  .fx-key { color: var(--accent); font-family: monospace; font-weight: bold; font-size: 0.88rem }
  .fx-nchip { color: var(--text-4); font-family: monospace; font-size: 0.74rem }
  .fx-why { margin: 0; color: var(--text); font-size: 0.88rem; line-height: 1.6; border-left: 2px solid var(--border-3);
    padding-left: 0.7rem }
  .fx-why b { color: var(--text-3); font-family: monospace; font-size: 0.68rem; letter-spacing: 0.05em;
    text-transform: uppercase; font-weight: normal; display: block }
  .fx-summary { color: var(--text-2); font-size: 0.88rem; line-height: 1.65; margin: 0 }
  .fx-foot { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 0.5rem;
    font-size: 0.75rem; color: var(--text-4) }
  .fx-foot a { color: var(--accent); text-decoration: none }
  .fx-vote { display: flex; flex-wrap: wrap; align-items: center; gap: 0.4rem }
  .fx-vbtn { background: none; border: 1px solid var(--border-3); color: var(--text-3); padding: 0.15rem 0.6rem;
    font: inherit; font-size: 0.75rem; cursor: pointer; border-radius: 999px }
  .fx-vbtn:hover { border-color: var(--accent); color: var(--text) }
  .fx-vbtn[aria-pressed="true"] { border-color: var(--accent); color: var(--accent); background: var(--accent-soft) }
  .fx-vbtn b { font-weight: normal; font-family: monospace; margin-left: 0.25rem }
  .fx-ask { display: flex; gap: 0.35rem; width: 100%; margin-top: 0.25rem }
  .fx-ask input { flex: 1; min-width: 0; background: var(--panel); color: var(--text); border: 1px solid var(--border-3);
    padding: 0.3rem 0.5rem; font: inherit; font-size: 0.8rem }
  .fx-vmsg { color: var(--text-4); font-size: 0.72rem }
  details.fx-early { margin-top: 2.25rem; border-top: 1px solid var(--border); padding-top: 1rem }
  details.fx-early > summary { cursor: pointer; color: var(--text-2); font-size: 0.95rem }
  details.fx-early > summary b { color: var(--text) }
  .fx-early-note { color: var(--text-3); font-size: 0.82rem; line-height: 1.6; max-width: 660px; margin: 0.6rem 0 0.9rem }
  .fx-empty { color: var(--text-3); font-size: 0.85rem; padding: 0.5rem 0 }
  .fx-data { width: 100%; border-collapse: collapse; font-size: 0.78rem }
  .fx-data th, .fx-data td { border-bottom: 1px solid var(--border); padding: 0.35rem 0.5rem; text-align: left;
    vertical-align: top }
  .fx-data th { color: var(--text-4); font-family: monospace; font-weight: normal }
  .fx-data td { color: var(--text-2); font-family: monospace }
  .fx-data a { color: var(--accent); text-decoration: none; margin-right: 0.6rem; white-space: nowrap }
  .fx-layout-vote { margin-top: 2.5rem; border: 1px dashed var(--border-3); padding: 0.9rem 1rem }
  .fx-layout-vote p { margin: 0 0 0.6rem; color: var(--text-2); font-size: 0.88rem }
  .fx-detail h1 { font-family: system-ui, -apple-system, sans-serif; color: var(--text); font-size: 1.5rem;
    line-height: 1.4; margin: 0.5rem 0 0.75rem }
  .fx-detail h2 { margin-top: 2rem }
  .fx-detail p, .fx-detail li { color: var(--text-2); line-height: 1.7; font-size: 0.9rem }
  .fx-detail table { border-collapse: collapse; font-size: 0.82rem; margin: 0.5rem 0 }
  .fx-detail th, .fx-detail td { border-bottom: 1px solid var(--border); padding: 0.35rem 0.6rem; text-align: left }
  .fx-detail .fx-why { margin: 1rem 0; font-size: 1rem; color: var(--text) }
  .fx-wide { overflow-x: auto }
  .fx-box { border: 1px solid var(--border); background: var(--panel-2); padding: 0.85rem 1rem; margin: 0.5rem 0 }
  .fx-box .fx-key { font-size: 1.1rem }
  .fx-mono { font-family: monospace; font-size: 0.78rem; color: var(--text-3); line-height: 1.6 }
  .fx-detail a { color: var(--accent) }
  .fx-check { margin: 1.25rem 0 }
  .fx-draft-banner { border: 1px solid var(--warn); color: var(--warn); padding: 0.55rem 0.85rem;
    font-size: 0.8rem; line-height: 1.5; margin: 0.5rem 0 1rem }
  .fx-review { width: 100%; border-collapse: collapse; font-size: 0.8rem }
  .fx-review th, .fx-review td { border-bottom: 1px solid var(--border); padding: 0.45rem 0.5rem; text-align: left;
    vertical-align: top }
  .fx-review th { color: var(--text-4); font-family: monospace; font-weight: normal; white-space: nowrap }
  .fx-review td { color: var(--text-2); line-height: 1.5 }
  .fx-review td.num { font-family: monospace; white-space: nowrap }
  .fx-review a { color: var(--text); text-decoration: none }
  .fx-review a:hover { color: var(--accent) }
  .fx-review .note { color: var(--warn); font-size: 0.74rem; display: block; margin-top: 0.2rem }
  .fx-review .cm { color: var(--text-3); font-size: 0.76rem; display: block }
  .fx-review tr.hot td:first-child { border-left: 3px solid var(--warn) }
  .fx-review tr.cand td:first-child { border-left: 3px solid var(--accent) }
  @media (max-width: 600px) {
    body { padding: 1rem; }
    .fx-facet-label { min-width: 100%; }
    .fx-variants .fx-lab { margin-left: 0 }
    .fx-gaps { grid-template-columns: 1fr }
  }
"""

# Live filtering. Plain string (not an f-string): braces are JS's. Reads the
# server-rendered cards' data-* attributes; the URL query mirrors the state so
# a filtered view can be shared. `stage` arrives from the workflow diagram's
# links (a real navigation, so it also works with JS off — the server hides
# non-matching cards).
_FILTER_JS = """
(function () {
  var params = new URLSearchParams(location.search);
  var state = {
    theme: params.get('theme') || '',
    tags: (params.get('tags') || '').split(',').filter(Boolean),
    q: params.get('q') || '',
    stage: params.get('stage') || ''
  };
  var cards = Array.prototype.slice.call(document.querySelectorAll('.fx-card'));
  var themeBtns = document.querySelectorAll('.fx-theme');
  var chips = document.querySelectorAll('.fx-chip');
  var search = document.getElementById('fx-q');
  var status = document.getElementById('fx-status');
  var statusText = document.getElementById('fx-status-text');
  var mainEmpty = document.getElementById('fx-main-empty');
  var earlyCount = document.getElementById('fx-early-count');
  var filters = document.getElementById('fx-filters');
  if (!search) return;
  search.value = state.q;
  if (state.tags.length) filters.open = true;

  function matches(card, ignoreTheme) {
    if (!ignoreTheme && state.theme && card.dataset.theme !== state.theme) return false;
    if (state.stage && card.dataset.stages.split(' ').indexOf(state.stage) < 0) return false;
    var tags = card.dataset.tags.split(' ');
    for (var i = 0; i < state.tags.length; i++) {
      if (tags.indexOf(state.tags[i]) < 0) return false;
    }
    var words = state.q.toLowerCase().split(/\\s+/).filter(Boolean);
    for (var j = 0; j < words.length; j++) {
      if (card.dataset.text.indexOf(words[j]) < 0) return false;
    }
    return true;
  }

  function apply() {
    var shownMain = 0, shownEarly = 0;
    cards.forEach(function (c) {
      var ok = matches(c, false);
      c.hidden = !ok;
      if (ok) { if (c.classList.contains('early')) shownEarly++; else shownMain++; }
    });
    themeBtns.forEach(function (b) {
      var t = b.dataset.theme;
      b.setAttribute('aria-pressed', String(t === state.theme));
      var n = cards.filter(function (c) { return c.dataset.theme === t && matches(c, true); }).length;
      var el = b.querySelector('.fx-n');
      if (el) el.textContent = n + (n === 1 ? ' finding' : ' findings');
    });
    chips.forEach(function (ch) {
      ch.setAttribute('aria-pressed', String(state.tags.indexOf(ch.dataset.tag) >= 0));
    });
    document.querySelectorAll('.fx-flow .st-box').forEach(function (b) {
      b.classList.toggle('on', !!state.stage && b.dataset.stage === state.stage);
    });
    mainEmpty.hidden = shownMain > 0;
    earlyCount.textContent = shownEarly;
    var filtered = state.theme || state.tags.length || state.q || state.stage;
    status.hidden = !filtered;
    if (filtered) {
      statusText.textContent = (shownMain + shownEarly) + ' of ' + cards.length + ' findings match \\u00b7 ';
    }
    var p = new URLSearchParams(location.search);
    ['theme', 'tags', 'q', 'stage'].forEach(function (k) { p.delete(k); });
    if (state.theme) p.set('theme', state.theme);
    if (state.tags.length) p.set('tags', state.tags.join(','));
    if (state.q) p.set('q', state.q);
    if (state.stage) p.set('stage', state.stage);
    var qs = p.toString();
    history.replaceState(null, '', location.pathname + (qs ? '?' + qs : '') + location.hash);
  }

  themeBtns.forEach(function (b) {
    b.addEventListener('click', function () {
      state.theme = (state.theme === b.dataset.theme) ? '' : b.dataset.theme;
      apply();
    });
  });
  chips.forEach(function (ch) {
    ch.addEventListener('click', function () {
      var i = state.tags.indexOf(ch.dataset.tag);
      if (i >= 0) state.tags.splice(i, 1); else state.tags.push(ch.dataset.tag);
      apply();
    });
  });
  search.addEventListener('input', function () { state.q = search.value.trim(); apply(); });
  document.getElementById('fx-clear').addEventListener('click', function () {
    state = { theme: '', tags: [], q: '', stage: '' }; search.value = ''; apply();
  });
  apply();
})();
"""

# Votes, quizzes and the layout vote — shared by the catalog and the detail
# page. The device id lives in localStorage and is created only on a first
# vote (see finding_feedback.py for why); localStorage also remembers which
# buttons this browser pressed, so the page can show them pressed again.
_INTERACT_JS = """
(function () {
  var PREFIX = document.body.dataset.fxPrefix || '';
  function store(k, v) { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { return null; } }
  function device() {
    var d = store('owl-fx-device');
    if (!d || !/^[0-9a-f]{32}$/.test(d)) {
      var a = new Uint8Array(16); (window.crypto || window.msCrypto).getRandomValues(a);
      d = Array.prototype.map.call(a, function (b) { return ('0' + b.toString(16)).slice(-2); }).join('');
      store('owl-fx-device', d);
    }
    return d;
  }
  function mine() { try { return JSON.parse(store('owl-fx-mine') || '{}'); } catch (e) { return {}; } }
  function remember(key, on) { var m = mine(); if (on) m[key] = 1; else delete m[key]; store('owl-fx-mine', JSON.stringify(m)); }
  function post(url, body) {
    body.device = device();
    return fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
      .then(function (r) { return r.json().then(function (d) { d._ok = r.ok; return d; }); });
  }

  var m = mine();
  document.querySelectorAll('.fx-vote[data-slug]').forEach(function (row) {
    var slug = row.dataset.slug, msg = row.querySelector('.fx-vmsg'), ask = row.querySelector('.fx-ask');
    row.querySelectorAll('.fx-vbtn').forEach(function (btn) {
      var key = slug + ':' + btn.dataset.kind;
      if (m[key]) btn.setAttribute('aria-pressed', 'true');
      btn.addEventListener('click', function () {
        send(btn.dataset.kind, '');
      });
    });
    function send(kind, comment) {
      post(PREFIX + '/findings/' + slug + '/feedback', { kind: kind, comment: comment }).then(function (d) {
        if (!d._ok) { msg.textContent = d.error || 'Could not record that, please try later.'; return; }
        remember(slug + ':' + kind, d.on);
        row.querySelectorAll('.fx-vbtn').forEach(function (b) {
          if (b.dataset.kind === kind) b.setAttribute('aria-pressed', String(d.on));
          var c = b.querySelector('b'); if (c) c.textContent = d.counts[b.dataset.kind] || '';
        });
        if (kind === 'question') {
          ask.hidden = !d.on || !!comment;
          msg.textContent = comment ? 'Thank you, the lab will look at this.' : '';
        } else {
          msg.textContent = d.on ? 'Thank you.' : '';
        }
      }).catch(function () { msg.textContent = 'Could not record that, please try later.'; });
    }
    if (ask) {
      ask.addEventListener('submit', function (ev) {
        ev.preventDefault();
        var t = ask.querySelector('input').value.trim();
        if (t) send('question', t);
      });
    }
  });

  // The score counts the pop-down only: a test on a card stands alone.
  var right = 0, done = 0, scoreEl = document.getElementById('fx-score'), popdown = document.getElementById('fx-test');
  document.querySelectorAll('.fx-quiz').forEach(function (qz) {
    var answered = false, inPopdown = !!popdown && popdown.contains(qz);
    var reveal = qz.querySelector('.fx-ans > summary'); if (reveal) reveal.hidden = true;
    qz.querySelectorAll('.fx-opt').forEach(function (opt) {
      opt.addEventListener('click', function () {
        if (answered) return; answered = true;
        var ok = opt.dataset.ok === '1';
        if (inPopdown) { done++; if (ok) right++; }
        opt.classList.add(ok ? 'right' : 'wrong');
        qz.querySelectorAll('.fx-opt').forEach(function (o) { if (o.dataset.ok === '1') o.classList.add('right'); });
        var verdict = qz.querySelector('.fx-verdict');
        if (verdict) { verdict.textContent = ok ? 'Correct.' : 'Not quite.'; if (!ok) verdict.classList.add('no'); }
        var ans = qz.querySelector('.fx-ans'); if (ans) ans.open = true;
        var dlg = qz.closest('dialog'), back = dlg && dlg.querySelector('.fx-test-back'); if (back) back.hidden = false;
        if (scoreEl && inPopdown) scoreEl.textContent = 'You got ' + right + ' of ' + done + ' right.';
      });
    });
  });

  // showModal() covers the page, makes it inert, and handles Esc and focus return.
  document.querySelectorAll('.fx-test-open').forEach(function (btn) {
    var dlg = btn.nextElementSibling;
    if (!dlg || !dlg.showModal) return;
    btn.hidden = false;
    btn.addEventListener('click', function () { dlg.showModal(); });
    dlg.querySelectorAll('.fx-test-close').forEach(function (c) {
      c.addEventListener('click', function () { dlg.close(); });
    });
  });

  var lv = document.querySelector('.fx-layout-vote');
  if (lv) {
    var picked = store('owl-fx-layout');
    lv.querySelectorAll('.fx-vbtn').forEach(function (btn) {
      if (picked === btn.dataset.variant) btn.setAttribute('aria-pressed', 'true');
      btn.addEventListener('click', function () {
        post(PREFIX + '/findings/variant-vote', { variant: btn.dataset.variant }).then(function (d) {
          var msg = lv.querySelector('.fx-vmsg');
          if (!d._ok) { msg.textContent = d.error || 'Could not record that, please try later.'; return; }
          store('owl-fx-layout', d.picked || '');
          lv.querySelectorAll('.fx-vbtn').forEach(function (b) {
            b.setAttribute('aria-pressed', String(b.dataset.variant === d.picked));
            var c = b.querySelector('b'); if (c) c.textContent = d.counts[b.dataset.variant] || '';
          });
          msg.textContent = d.picked ? 'Thank you.' : '';
        });
      });
    });
  }
})();
"""


def _load_yaml(path: Path) -> dict:
    try:
        return yaml.safe_load(path.read_text()) or {}
    except (OSError, yaml.YAMLError):
        return {}


def _tag_label(taxonomy: dict, tag: str) -> str:
    facet, _, key = tag.partition(":")
    return (taxonomy.get(facet, {}).get("values", {}).get(key, {}) or {}).get("label", key)


def _stages(taxonomy: dict) -> dict:
    return taxonomy.get("stage", {}).get("values", {}) or {}


def _search_text(f, ov: dict, taxonomy: dict) -> str:
    """Everything a visitor might type: plain + technical wording, tag labels
    and their synonyms (so "STB" finds "set-top box")."""
    parts = [f.slug, f.headline, f.claim_short, ov.get("plain_headline", ""),
             ov.get("plain_summary", ""), ov.get("key_number", ""), ov.get("why_it_matters", "")]
    theme = taxonomy.get("theme", {}).get("values", {}).get(ov.get("theme", ""), {})
    parts += [theme.get("label", ""), theme.get("question", "")] + list(theme.get("synonyms", []))
    for tag in ov.get("tags", []):
        facet, _, key = tag.partition(":")
        v = taxonomy.get(facet, {}).get("values", {}).get(key, {}) or {}
        parts += [v.get("label", key)] + list(v.get("synonyms", []))
    for st in ov.get("stages", []):
        v = _stages(taxonomy).get(st, {}) or {}
        parts += [v.get("label", st)] + list(v.get("synonyms", []))
    return " ".join(str(p) for p in parts).lower()


def _entries(min_n: int):
    """(finding, overlay, is_early, is_draft) — every published finding plus
    the drafts the overlay names, newest first. A published finding with no
    overlay entry falls back to its technical headline."""
    overlay = _load_yaml(_OVERLAY_PATH)
    items = [(f, False) for f in findings_mod.list_all()]
    for slug, ov in overlay.items():
        if (ov or {}).get("draft"):
            try:
                d = findings_mod.load_draft(slug)
            except findings_mod.FindingError:
                d = None
            if d is not None:
                items.append((d, True))
    items.sort(key=lambda x: x[0].last_refined, reverse=True)
    out = []
    for f, is_draft in items:
        ov = overlay.get(f.slug) or {}
        n = ov.get("n_runs")
        out.append((f, ov, n is None or int(n) < min_n, is_draft))
    return out


def _review_status(ov: dict, is_draft: bool) -> str | None:
    st = ov.get("review_status")
    if st in _REVIEW:
        return st
    return "machine-draft" if is_draft else None


def _review_pill(ov: dict, is_draft: bool) -> str:
    st = _review_status(ov, is_draft)
    if not st:
        return ""
    label, tip, _ = _REVIEW[st]
    cls = {"machine-draft": "fx-draft", "group-validated": "fx-rev validated"}.get(st, "fx-rev")
    return f'<span class="fx-pill {cls}" title="{html_lib.escape(tip)}">{label}</span>'


def _variant_qs(variant: str, min_n: int, **extra) -> str:
    parts = []
    if variant != _DEFAULT_VARIANT:
        parts.append(f"v={variant}")
    if min_n != _DEFAULT_MIN_N:
        parts.append(f"min_n={min_n}")
    parts += [f"{k}={html_lib.escape(str(v))}" for k, v in extra.items() if v]
    return ("?" + "&amp;".join(parts)) if parts else ""


def _detail_url(slug: str, min_n: int) -> str:
    q = "" if min_n == _DEFAULT_MIN_N else f"?min_n={min_n}"
    return f"{_PREFIX}/findings/{html_lib.escape(slug)}{q}"


def _vote_html(slug: str, counts: dict) -> str:
    """👍 / ❓ row. Counts come from the server at render time; with JS off
    the buttons do nothing, and the page still reads fully."""
    e = html_lib.escape
    up = sum((counts.get("up") or {}).values())
    qn = sum((counts.get("question") or {}).values())
    return (
        f'<div class="fx-vote" data-slug="{e(slug)}">'
        f'<button type="button" class="fx-vbtn" data-kind="up" aria-pressed="false" '
        f'title="This makes sense to me">👍 Makes sense<b>{up or ""}</b></button>'
        f'<button type="button" class="fx-vbtn" data-kind="question" aria-pressed="false" '
        f'title="I don\'t understand this, or it doesn\'t add up">❓ I don\'t get this<b>{qn or ""}</b></button>'
        f'<span class="fx-vmsg" aria-live="polite"></span>'
        f'<form class="fx-ask" hidden><input type="text" maxlength="{feedback.COMMENT_MAX}" '
        f'aria-label="What is unclear?" placeholder="What is unclear? (optional, one line)">'
        f'<button type="submit" class="fx-vbtn">Send</button></form>'
        f'</div>'
    )


def _card_html(f, ov: dict, early: bool, is_draft: bool, taxonomy: dict, min_n: int,
               counts: dict, stage: str = "") -> str:
    e = html_lib.escape
    dot, word, meaning = _CONF_PLAIN.get(f.confidence, ("·", "", ""))
    headline = ov.get("plain_headline") or f.headline
    n = ov.get("n_runs")
    n_txt = f"n={n}" if n is not None else "n not yet stated"
    detail = _detail_url(f.slug, min_n)
    theme = taxonomy.get("theme", {}).get("values", {}).get(ov.get("theme", ""), {})
    review = _review_pill(ov, is_draft)
    if early:
        meta = (f'{review}<span class="fx-pill">Early signal &middot; {e(n_txt)}</span>'
                f'<span class="fx-nchip">not yet repeated {min_n}&times;, so no headline number</span>')
    else:
        meta = (f'{review}<span class="fx-pill" title="{e(meaning)}">{dot} {e(word)}</span>'
                f'<span class="fx-key">{e(ov.get("key_number", ""))}</span>'
                f'<span class="fx-nchip">{e(ov.get("n_note") or n_txt)}</span>')
    summary = ov.get("plain_summary", "")
    why = ov.get("why_it_matters", "")
    stages = ov.get("stages", [])
    hidden = " hidden" if stage and stage not in stages else ""
    return (
        f'<article class="fx-card{" early" if early else ""}" data-theme="{e(ov.get("theme", ""))}" '
        f'data-stages="{e(" ".join(stages))}" '
        f'data-tags="{e(" ".join(ov.get("tags", [])))}" data-text="{e(_search_text(f, ov, taxonomy))}"{hidden}>'
        f'<span class="fx-q">{e(theme.get("label", ""))}</span>'
        f'<h3><a href="{detail}">{e(headline)}</a></h3>'
        + (f'<p class="fx-why"><b>Why does this matter?</b>{e(why)}</p>' if why else "")
        + f'<div class="fx-meta">{meta}</div>'
        + (f'<p class="fx-summary">{e(summary)}</p>' if summary and not early else "")
        + f'<div class="fx-foot">{_vote_html(f.slug, counts)}{_test_html(f, ov, min_n)}'
        f'<span>Measured {e(f.first_measured)}'
        f'{"" if f.last_refined == f.first_measured else " &middot; updated " + e(f.last_refined)}'
        f' &middot; <a href="{detail}">See the science &rarr;</a></span></div>'
        f'</article>'
    )


def _watts_chart_html(min_n: int) -> str:
    """Server-rendered horizontal bars on one linear watt scale, each row a
    link to the finding it comes from."""
    e = html_lib.escape
    W, label_w, right, row_h, top, vmax = 760, 300, 72, 34, 22, 80.0
    plot_w = W - label_w - right
    x = lambda v: label_w + v / vmax * plot_w
    parts, y = [], top
    for gi, (group, rows) in enumerate(_WATTS):
        if gi:
            y += 12
        parts.append(f'<text class="grp" x="0" y="{y + 12}">{e(group.upper())}</text>')
        y += 24
        for label, w, kind, slug, detail in rows:
            bh, by = 16, y + (row_h - 16) / 2 - 4
            bw = max(3.0, x(w) - label_w)
            val = f'{"+" if kind == "add" else ""}{w:.2f} W' if w < 1 else f'{"+" if kind == "add" else ""}{w:.1f} W'
            path = (f"M{label_w},{by:.1f} h{bw - 4:.1f} a4,4 0 0 1 4,4 v{bh - 8} a4,4 0 0 1 -4,4 "
                    f"h{-(bw - 4):.1f} z")
            parts.append(
                f'<a href="{_detail_url(slug, min_n)}"><title>{e(label)}: {e(val)}. {e(detail)}</title>'
                f'<rect x="0" y="{y - 4}" width="{W}" height="{row_h}" fill="transparent"/>'
                f'<text class="lbl" x="{label_w - 12}" y="{by + bh - 3.5:.1f}" text-anchor="end">{e(label)}</text>'
                f'<path class="bar {"b-total" if kind == "total" else "b-add"}" d="{path}"/>'
                f'<text class="val" x="{label_w + bw + 8:.1f}" y="{by + bh - 3.5:.1f}">{e(val)}</text></a>')
            y += row_h
    h = y + 26
    grid = "".join(
        f'<line class="grid" x1="{x(t):.1f}" x2="{x(t):.1f}" y1="{top - 4}" y2="{h - 22}"/>'
        f'<text class="axis" x="{x(t):.1f}" y="{h - 6}" text-anchor="middle">{t} W</text>'
        for t in (0, 20, 40, 60, 80))
    aria = ("Bar chart of watts while watching: TV screen 52.8 W, streaming box 1.9 W; "
            "Vivid picture mode adds 20.4 W, HDR adds 3.9 W at the screen, 4K adds 0.41 W at the box, "
            "128 times the bitrate adds 0.44 W at the box.")
    return (f'<svg viewBox="0 0 {W} {h}" role="img" aria-label="{e(aria)}">{grid}{"".join(parts)}</svg>')


def _split_label(label: str) -> list[str]:
    """Two lines for a stage box: break at the space nearest the middle."""
    if len(label) <= 9 or " " not in label:
        return [label]
    mid = len(label) / 2
    i = min((i for i, c in enumerate(label) if c == " "), key=lambda i: abs(i - mid))
    return [label[:i], label[i + 1:]]


def _stage_counts(entries, taxonomy: dict) -> dict[str, int]:
    counts = {k: 0 for k in _stages(taxonomy)}
    for _, ov, _, _ in entries:
        for st in ov.get("stages", []):
            if st in counts:
                counts[st] += 1
    return counts


def _workflow_html(entries, taxonomy: dict, min_n: int, stage: str) -> str:
    """The streaming chain as a left-to-right diagram. Each stage links to the
    findings that touch it; a stage with none is drawn dashed as a gap, and the
    list under the diagram says what would fill it."""
    e = html_lib.escape
    stages = _stages(taxonomy)
    counts = _stage_counts(entries, taxonomy)
    chain = sorted(((k, v) for k, v in stages.items() if v.get("pipeline")), key=lambda kv: kv[1]["pipeline"])
    side = [(k, v) for k, v in stages.items() if v.get("side")]
    W, bw, bh, top = 760, 92, 78, 30
    gap = (W - bw * len(chain)) / max(1, len(chain) - 1)

    def node(key, spec, x, y, w):
        n = counts.get(key, 0)
        cls = "st-box " + ("has" if n else "gap") + (" on" if key == stage else "")
        lines = _split_label(spec.get("label", key))
        ty = y + 28 - (len(lines) - 1) * 8
        label = "".join(f'<tspan x="{x + w / 2:.1f}" dy="{0 if i == 0 else 16}">{e(t)}</tspan>'
                        for i, t in enumerate(lines))
        sub = (f'<text class="st-n" x="{x + w / 2:.1f}" y="{y + bh - 12}" text-anchor="middle">'
               f'{n} finding{"" if n == 1 else "s"}</text>' if n else
               f'<text class="st-gap" x="{x + w / 2:.1f}" y="{y + bh - 12}" text-anchor="middle">Not measured yet</text>')
        title = f'{spec.get("label", key)}: {spec.get("definition", "")}'
        href = f'{_PREFIX}/findings{_variant_qs("workflow", min_n, stage=key)}#fx-list'
        return (f'<a href="{href}"><title>{e(title)}</title>'
                f'<rect class="{cls}" data-stage="{e(key)}" x="{x:.1f}" y="{y}" width="{w}" height="{bh}" rx="6"/>'
                f'<text x="{x + w / 2:.1f}" y="{ty}" text-anchor="middle">{label}</text>{sub}</a>')

    parts = [f'<text class="side-lbl" x="0" y="14">FROM PRODUCTION TO THE VIEWER&#8217;S SCREEN</text>']
    for i, (k, v) in enumerate(chain):
        x = i * (bw + gap)
        parts.append(node(k, v, x, top, bw))
        if i < len(chain) - 1:
            ax, ay = x + bw + 4, top + bh / 2
            parts.append(f'<path class="arrow" d="M{ax:.1f},{ay} h{gap - 8:.1f} m-5,-4 l5,4 l-5,4"/>')
    sy = top + bh + 34
    parts.append(f'<text class="side-lbl" x="0" y="{sy - 10}">BESIDE THE CHAIN</text>')
    sw = 2 * bw + gap
    for i, (k, v) in enumerate(side):
        parts.append(node(k, v, i * (sw + gap), sy, sw))
    h = sy + bh + 4
    measured = ", ".join(f'{v.get("label", k)} {counts.get(k, 0)}' for k, v in chain + side if counts.get(k))
    gaps_txt = ", ".join(v.get("label", k) for k, v in chain if not counts.get(k))
    aria = f"Streaming workflow diagram. Findings per stage: {measured}. Not measured yet: {gaps_txt}."
    svg = f'<svg viewBox="0 0 {W} {h}" role="img" aria-label="{e(aria)}">{"".join(parts)}</svg>'

    gap_rows = "".join(f'<dt>{e(v.get("label", k))}</dt><dd>{e(v.get("gap_note") or "Not measured yet.")}</dd>'
                       for k, v in chain if not counts.get(k))
    note = ""
    if stage in stages:
        spec = stages[stage]
        note = (f'<p class="fx-stage-note"><b>{e(spec.get("label", stage))}.</b> {e(spec.get("definition", ""))} '
                + (f'{e(spec.get("gap_note", ""))} ' if not counts.get(stage) else "")
                + f'<a href="{_PREFIX}/findings{_variant_qs("workflow", min_n)}">Show every stage</a></p>')
    return (f'<div class="fx-flow">{svg}</div>{note}'
            + (f'<dl class="fx-gaps" aria-label="Gaps in what we have measured">{gap_rows}</dl>' if gap_rows else ""))


def _quiz_card_html(f, ov: dict, min_n: int, with_link: bool = True) -> str:
    e = html_lib.escape
    q = ov.get("quiz") or {}
    # A stable shuffle, so the right answer isn't predictably in one position.
    shuffled = sorted(q.get("options", []), key=lambda o: hashlib.sha256(f"{f.slug}:{o}".encode()).hexdigest())
    opts = "".join(
        f'<button type="button" class="fx-opt" data-ok="{"1" if o == q.get("answer") else "0"}">{e(o)}</button>'
        for o in shuffled)
    link = (f' <a href="{_detail_url(f.slug, min_n)}">See the finding &rarr;</a>' if with_link else "")
    return (f'<div class="fx-quiz"><p class="q">{e(q.get("question", ""))}</p>'
            f'<div class="fx-opts">{opts}</div><p class="fx-verdict" aria-live="polite"></p>'
            f'<details class="fx-ans"><summary>Show the answer</summary>'
            f'<p><b>{e(q.get("answer", ""))}.</b> {e(q.get("explain", ""))}{link}</p></details></div>')


def _test_html(f, ov: dict, min_n: int) -> str:
    """The per-finding test: a button and a window that covers the page, so the
    finding can't be read while answering. Needs JS, so the button stays hidden
    until the script has wired it up."""
    if not (ov.get("quiz") or {}).get("options"):
        return ""
    return (f'<button type="button" class="fx-test-open" hidden>Test my understanding</button>'
            f'<dialog class="fx-test" aria-label="Test my understanding"><div class="fx-test-in">'
            f'<div class="fx-test-top"><span>Test my understanding</span>'
            f'<button type="button" class="fx-test-close">Close</button></div>'
            f'{_quiz_card_html(f, ov, min_n, with_link=False)}'
            f'<button type="button" class="fx-test-close fx-test-back" hidden>Back to the finding</button>'
            f'</div></dialog>')


def _quiz_html(entries, min_n: int, is_open: bool = False) -> str:
    """The "Test my knowledge" pop-down holds main-shelf findings only: early
    signals show no headline number, so their questions stay on their own card."""
    cards = [_quiz_card_html(f, ov, min_n) for f, ov, early, _ in entries if ov.get("quiz") and not early]
    if not cards:
        return ""
    return (f'<details class="fx-early" id="fx-test"{" open" if is_open else ""}>'
            f'<summary><b>Test my knowledge</b> &middot; {len(cards)} questions, each answered by one of our '
            f'measurements</summary><div class="fx-quizzes" style="margin-top:0.9rem">{"".join(cards)}</div>'
            f'<p id="fx-score" class="fx-score" aria-live="polite"></p></details>')


def _data_shelf_html(entries, min_n: int) -> str:
    """Tania, 5 Nov: researchers want the data without our interpretation.
    One row per finding, its stored results, nothing else."""
    e = html_lib.escape
    rows, n_results = [], 0
    for f, _, _, is_draft in sorted(entries, key=lambda x: x[0].slug):
        links = " ".join(f'<a href="{e(_source_url(r, is_draft))}">{e(r)}</a>' for r in f.source_result_ids)
        n_results += len(f.source_result_ids)
        rows.append(f'<tr><td>{e(f.slug)}</td><td>{e(f.first_measured)}</td><td>{links}</td></tr>')
    return (f'<details class="fx-early" id="fx-data"><summary><b>Data only</b> ({n_results} stored measurements): '
            f'the raw results behind every finding, without our interpretation</summary>'
            f'<p class="fx-early-note">Each link is the stored result as JSON, with every power sample, baseline and '
            f'setting we recorded. The method is on the <a href="/methodology" style="color:var(--accent)">Methodology</a> '
            f'page.</p><div class="fx-wide"><table class="fx-data"><thead><tr><th>Finding</th><th>Measured</th>'
            f'<th>Stored results (JSON)</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div></details>')


def _layout_vote_html(tally: dict) -> str:
    counts = tally.get("variants", {})
    btns = "".join(
        f'<button type="button" class="fx-vbtn" data-variant="{k}" aria-pressed="false" title="{html_lib.escape(desc)}">'
        f'{html_lib.escape(label)}<b>{sum(counts.get(k, {}).values()) or ""}</b></button>'
        for k, (label, desc) in _VARIANTS.items())
    return (f'<section class="fx-layout-vote" aria-label="Layout vote"><p>This page comes in two layouts for '
            f'the WattLab group to compare. <b>Which one should we keep?</b> Pick one; pick it again to withdraw.</p>'
            f'<div class="fx-vote">{btns}<span class="fx-vmsg" aria-live="polite"></span></div>'
            f'<p class="fx-mono" style="margin:0.6rem 0 0">Votes are stored without your IP address. '
            f'This browser keeps a random ID so a vote can be changed or withdrawn.</p></section>')


def _variant_nav_html(variant: str, min_n: int, is_lab: bool) -> str:
    links = " ".join(
        f'<a href="{_PREFIX}/findings{_variant_qs(k, min_n)}" title="{html_lib.escape(desc)}"'
        f'{" aria-current=&quot;page&quot;" if k == variant else ""}>{html_lib.escape(label)}</a>'
        for k, (label, desc) in _VARIANTS.items())
    lab = (f'<a class="fx-lab" href="{_PREFIX}/findings/review">Lab: review queue &rarr;</a>' if is_lab else "")
    return f'<nav class="fx-variants" aria-label="Layouts to compare">Layout: {links}{lab}</nav>'


def _catalog_html(min_n: int, variant: str = _DEFAULT_VARIANT, stage: str = "", is_lab: bool = False,
                  open_test: bool = False) -> str:
    e = html_lib.escape
    taxonomy = _load_yaml(_TAXONOMY_PATH)
    entries = _entries(min_n)
    tally = feedback.tally()
    votes = tally.get("findings", {})
    if stage not in _stages(taxonomy):
        stage = ""
    main = [x for x in entries if not x[2]]
    early = [x for x in entries if x[2]]

    themes = taxonomy.get("theme", {}).get("values", {})
    theme_btns = "".join(
        f'<button type="button" class="fx-theme" data-theme="{e(k)}" aria-pressed="false">'
        f'<b>{e(v.get("question", v.get("label", k)))}</b>'
        f'<span>{e(v.get("label", k).upper())} &middot; <span class="fx-n"></span></span></button>'
        for k, v in themes.items())

    used: dict[str, int] = {}
    for _, ov, _, _ in entries:
        for t in ov.get("tags", []):
            used[t] = used.get(t, 0) + 1
    facet_rows = []
    for facet in _CHIP_FACETS:
        spec = taxonomy.get(facet, {})
        chips = "".join(
            f'<button type="button" class="fx-chip" data-tag="{e(facet)}:{e(k)}" aria-pressed="false" '
            f'title="{e(v.get("definition", ""))}">{e(v.get("label", k))}'
            f'<small>{used[facet + ":" + k]}</small></button>'
            for k, v in spec.get("values", {}).items() if used.get(f"{facet}:{k}"))
        if chips:
            facet_rows.append(f'<div class="fx-facet"><span class="fx-facet-label">'
                              f'{e(spec.get("label", facet))}</span>{chips}</div>')

    cards = lambda xs: "".join(_card_html(f, ov, er, dr, taxonomy, min_n, votes.get(f.slug, {}), stage)
                               for f, ov, er, dr in xs)
    n_drafts = sum(1 for _, ov, _, dr in entries if _review_status(ov, dr) == "machine-draft")
    n_main_shown = sum(1 for _, ov, _, _ in main if not stage or stage in ov.get("stages", []))

    chart = f"""
<section class="fx-fig" aria-labelledby="fx-watts">
  <div class="fx-fig-title" id="fx-watts">Where the watts go when you watch</div>
  <div class="fx-fig-sub">Watts at the wall while playing video on one 55-inch OLED TV and the box feeding it.
     A watt drawn for an hour is a watt-hour, so each bar is also the energy per hour of viewing.</div>
  <div class="fx-legend" aria-hidden="true"><span><i style="background:var(--accent)"></i>Total draw</span>
     <span><i style="background:var(--text-4)"></i>Extra draw from one choice</span></div>
  <div class="fx-chart">{_watts_chart_html(min_n)}</div>
  <p class="fx-fig-note">The screen dominates, the TV's own picture setting outweighs every streaming choice, and
     4K, HDR and bitrate cost far less at the box than the debate suggests. Select a bar for the finding behind it.</p>
  <p class="fx-fig-cap">All values n=3, measured October 2026. One TV and one box: this shows the scale,
     not a market average. Network and data-centre energy are not included.</p>
</section>"""

    if variant == "workflow":
        browse = (f'<h2>Browse by stage of the streaming workflow</h2>'
                  f'{_workflow_html(entries, taxonomy, min_n, stage)}')
        top, after = chart, browse
    else:
        top, after = chart, f'<h2>Browse by question</h2><div class="fx-themes">{theme_btns}</div>'

    return f"""
<p class="fx-preview"><b>Preview</b> of the redesigned findings page, for discussion &middot;
   {n_drafts} findings marked Draft are awaiting lab review &middot; numbers link to the stored measurements</p>
{_variant_nav_html(variant, min_n, is_lab)}
<h1>What we've measured</h1>
<p class="fx-lede">OWL, the <strong>Open WattLab</strong>, is the measurement lab of <strong>Greening of
   Streaming</strong>, a member-funded non-profit. We measure real streaming hardware at the wall socket, repeat
   every test, and publish the confidence and the raw data behind each result.</p>
<p class="fx-proof">{len(main)} findings repeated at least {min_n}&times; &middot; {len(early)} early signals
   &middot; every one linked to its stored measurement</p>
<p class="fx-axes">Each finding carries two labels. One says how solid the measurement is: 🟢 Solid, 🟡 Indicative
   or 🔴 Unconfirmed. The other says how far it has been reviewed: Draft, Lab-checked, or Validated by the
   WattLab group. Tell us with 👍 when a finding makes sense to you, or ❓ when it doesn't.</p>
{_quiz_html(entries, min_n, open_test)}
{top}
{after}
<div class="fx-tools">
  <input id="fx-q" class="fx-search" type="search" aria-label="Search findings"
         placeholder="Search findings, e.g. 4K, set-top box, AV1, picture mode, AI">
  <details class="fx-filters" id="fx-filters"><summary>Filter by device, format or lever</summary>
    <div class="fx-facets">{"".join(facet_rows)}</div></details>
  <p id="fx-status" class="fx-status" hidden><span id="fx-status-text"></span><button type="button" id="fx-clear">clear filters</button></p>
</div>
<section class="fx-list" id="fx-list" aria-label="Findings">{cards(main)}
  <p id="fx-main-empty" class="fx-empty"{"" if not n_main_shown else " hidden"}>No repeated findings match. Try the early signals below.</p>
</section>
<details class="fx-early"{" open" if stage else ""}>
  <summary><b>Early signals</b> (<span id="fx-early-count">{len(early)}</span>): measured, but not yet repeated {min_n}&times;</summary>
  <p class="fx-early-note">These are real, published measurements, but each rests on fewer than {min_n} repeats.
     We show what we saw and why it matters, without a headline number, until the result is repeated.
     The numbers, limits and raw data are one click away.</p>
  <div class="fx-list">{cards(early)}</div>
</details>
{_data_shelf_html(entries, min_n)}
{_layout_vote_html(tally)}
<script>{_FILTER_JS}</script>
<script>{_INTERACT_JS}</script>
"""


def _source_url(rid: str, is_draft: bool) -> str:
    if not is_draft:
        return findings_mod.result_download_url(rid)
    type_, token = rid.split("/", 1)
    return f"{_PREFIX}/findings/source/{type_}/{token.split('_')[-1]}/download.json"


def _detail_html(slug: str, min_n: int) -> str | None:
    e = html_lib.escape
    taxonomy = _load_yaml(_TAXONOMY_PATH)
    entries = {f.slug: (f, ov, early, dr) for f, ov, early, dr in _entries(min_n)}
    if slug not in entries:
        return None
    f, ov, early, is_draft = entries[slug]
    dot, word, meaning = _CONF_PLAIN.get(f.confidence, ("·", "", ""))
    theme = taxonomy.get("theme", {}).get("values", {}).get(ov.get("theme", ""), {})
    n = ov.get("n_runs")
    back = f'{_PREFIX}/findings' + ("" if min_n == _DEFAULT_MIN_N else f"?min_n={min_n}")
    counts = feedback.tally().get("findings", {}).get(slug, {})

    review = _review_pill(ov, is_draft)
    if early:
        badge = (f'{review} <span class="fx-pill">Early signal &middot; n={e(str(n))}</span> '
                 f'<span class="fx-nchip">not yet repeated {min_n}&times;</span>')
    else:
        badge = (f'{review} <span class="fx-pill">{dot} {e(word)} &middot; {e(meaning)}</span> '
                 f'<span class="fx-key">{e(ov.get("key_number", ""))}</span>')
    draft_banner = ('<p class="fx-draft-banner">Draft finding, awaiting lab review. The measurements are '
                    'stored and linked below; the wording may still change before publication.</p>'
                    if is_draft else "")
    why = ov.get("why_it_matters", "")
    stage_labels = ", ".join(_stages(taxonomy).get(s, {}).get("label", s) for s in ov.get("stages", []))
    quiz = f'<div class="fx-check">{_test_html(f, ov, min_n)}</div>' if ov.get("quiz") else ""

    caveats = [c for c in f.caveats if not c.startswith("DRAFT pending")]
    caveats_html = "".join(f"<li>{findings_mod.md_to_html(c)}</li>" for c in caveats)
    sources = "".join(
        f'<li><a href="{e(_source_url(r, is_draft))}">{e(r)}</a> (JSON)</li>' for r in f.source_result_ids)
    related = ""
    for r in f.related_findings or []:
        if r in entries:
            rf, rov, _, _ = entries[r]
            related += f'<li><a href="{_detail_url(r, min_n)}">{e(rov.get("plain_headline") or rf.headline)}</a></li>'
    live = ("" if is_draft else
            f' &middot; Current live page: <a href="/findings/{e(f.slug)}">/findings/{e(f.slug)}</a>')

    return f"""
<p class="fx-preview"><b>Preview</b> of the redesigned findings page, for discussion</p>
<div class="fx-detail">
<p class="fx-mono"><a href="{back}">&larr; All findings</a> &middot; {e(theme.get("question", ""))}
   {f"&middot; Stage: {e(stage_labels)}" if stage_labels else ""}</p>
<h1>{e(ov.get("plain_headline") or f.headline)}</h1>
{draft_banner}<div class="fx-meta">{badge}</div>
{f'<p class="fx-why"><b>Why does this matter?</b>{e(why)}</p>' if why else ""}

<h2>What this means</h2>
<p>{e(ov.get("plain_summary", ""))}</p>
{quiz}
<div class="fx-box">{_vote_html(f.slug, counts)}
  <p class="fx-mono" style="margin:0.5rem 0 0">Does this make sense to you? Your 👍 or ❓ helps the lab decide
     what to publish and what to re-check. Votes are stored without your IP address.</p></div>

<h2>The numbers</h2>
<div class="fx-box">
  <p class="fx-mono" style="color:var(--text-2)">{e(f.claim_short)}</p>
  <p class="fx-mono">Repeats: {e(ov.get("n_note") or f"n={n}")} &middot; Confidence: {dot} {e(word)}
     &middot; Measured {e(f.first_measured)}, last refined {e(f.last_refined)} (v{f.version})</p>
</div>

<h2>Technical claim</h2>
<p>{e(f.headline)}</p>

<h2>What this covers, and what it doesn't</h2>
<p>{e(f.scope)}</p>
{f"<h2>Limitations</h2><ul>{caveats_html}</ul>" if caveats_html else ""}

<h2>Raw data</h2>
<ul>{sources}</ul>
<p class="fx-mono">How we measure and rate confidence: <a href="/methodology">Methodology</a>{live}</p>

<details><summary style="cursor:pointer;color:var(--text-2);margin-top:1.5rem">Full analysis</summary>
<div class="fx-wide">{findings_mod.md_to_html(f.body_md)}</div>
</details>

{f"<h2>Related findings</h2><ul>{related}</ul>" if related else ""}
</div>
<script>{_INTERACT_JS}</script>
"""


def _review_html(min_n: int) -> str:
    """Lab-only agenda for the group review (Martin, 5 Nov). Ranks findings;
    never changes a status — that is an overlay edit after a WattLab meeting."""
    e = html_lib.escape
    tally = feedback.tally()
    votes = tally.get("findings", {})
    rows = []
    for f, ov, early, is_draft in _entries(min_n):
        c = votes.get(f.slug, {})
        up, qn = c.get("up", {}), c.get("question", {})
        st = _review_status(ov, is_draft) or "machine-draft"
        rank = _REVIEW[st][2]
        q_total, up_total = sum(qn.values()), sum(up.values())
        rows.append(((-q_total, -(up_total if rank >= 1 else 0), -up_total, f.slug), f, ov, early, st, up, qn, c))
    rows.sort(key=lambda r: r[0])

    def split(d):
        total = sum(d.values())
        if not total:
            return "&ndash;"
        return f'{total} <span class="fx-nchip">(L{d.get("lab", 0)} M{d.get("member", 0)} A{d.get("anonymous", 0)})</span>'

    body = []
    for _, f, ov, early, st, up, qn, c in rows:
        dot = _CONF_PLAIN.get(f.confidence, ("·",))[0]
        notes = "".join(f'<span class="note">{e(ov[k])}</span>' for k in ("n_check", "review_note") if ov.get(k))
        comments = "".join(f'<span class="cm">{e(cm["ts"][:10])} {e(cm["tier"][0].upper())}: &ldquo;{e(cm["text"])}&rdquo;</span>'
                           for cm in c.get("comments", [])[:3])
        cls = "hot" if sum(qn.values()) else ("cand" if st == "lab-checked" and sum(up.values()) else "")
        body.append(
            f'<tr class="{cls}"><td><a href="{_detail_url(f.slug, min_n)}">{e(ov.get("plain_headline") or f.headline)}</a>'
            f'{notes}</td><td>{_REVIEW[st][0]}</td><td class="num">{dot} {"early" if early else "n≥" + str(min_n)}'
            f'<br><span class="fx-nchip">n={e(str(ov.get("n_runs", "?")))}</span></td>'
            f'<td class="num">{split(up)}</td><td class="num">{split(qn)}</td><td>{comments or "&ndash;"}</td>'
            f'<td class="num">{e(f.first_measured)}</td></tr>')
    variants = tally.get("variants", {})
    vrow = " &middot; ".join(f'{label}: {sum(variants.get(k, {}).values())}' for k, (label, _) in _VARIANTS.items())
    return f"""
<p class="fx-preview"><b>Lab only</b> &middot; review queue for the findings preview</p>
<p class="fx-mono"><a href="{_PREFIX}/findings">&larr; Findings preview</a></p>
<h1>Findings review queue</h1>
<p class="fx-lede">The agenda for the group review. Findings with ❓ come first: send them back to technical
   review. Lab-checked findings with 👍 come next: candidates for validation at a WattLab meeting.</p>
<p class="fx-axes"><b>Signals rank this list; they never change a status.</b> To change a status after a meeting,
   edit <code>review_status</code> in <code>docs/findings_drafts/plain_overlay.yaml</code> and add
   <code>validated_on</code>. Counts are split L(ab), M(ember), A(nonymous).</p>
<p class="fx-mono">Layout votes &middot; {vrow}</p>
<div class="fx-wide"><table class="fx-review">
<thead><tr><th>Finding</th><th>Review status</th><th>Measurement</th><th>👍</th><th>❓</th><th>Latest questions</th>
<th>Measured</th></tr></thead>
<tbody>{"".join(body)}</tbody></table></div>
"""


def _page(request: Request, title: str, body: str) -> HTMLResponse:
    page = ui.render_page(request, title, body, styles=_STYLES, head=_NOINDEX, back=False)
    # The interaction script reads the route prefix from the body element.
    page = page.replace("<body", f'<body data-fx-prefix="{_PREFIX}"', 1)
    return HTMLResponse(page)


def _min_n(request: Request) -> int:
    try:
        return max(1, int(request.query_params.get("min_n", _DEFAULT_MIN_N)))
    except ValueError:
        return _DEFAULT_MIN_N


def _visitor(request: Request) -> tuple[str, str]:
    """(hashed IP key, tier name) — the raw IP never leaves this function."""
    return (analytics.hash_ip(audience.client_ip(request)),
            audience.tier(request).name.lower())


async def _json_body(request: Request) -> dict | None:
    if not (request.headers.get("content-type") or "").startswith("application/json"):
        return None
    try:
        data = await request.json()
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


@router.get(_PREFIX + "/findings", response_class=HTMLResponse,
            dependencies=[Depends(requires(PUBLIC_PAGE))])
async def mockup_findings_catalog(request: Request):
    variant = request.query_params.get("v", _DEFAULT_VARIANT)
    open_test = variant == "quiz"     # the former quiz layout, kept as the MTS QR target
    if variant not in _VARIANTS:
        variant = _DEFAULT_VARIANT
    is_lab = capabilities.can(audience.tier(request), FINDINGS_REVIEW)
    body = _catalog_html(_min_n(request), variant, request.query_params.get("stage", ""), is_lab, open_test)
    return _page(request, "Findings (preview)", body)


@router.get(_PREFIX + "/findings/review", response_class=HTMLResponse,
            dependencies=[Depends(requires(FINDINGS_REVIEW))])
async def mockup_findings_review(request: Request):
    return _page(request, "Findings review queue", _review_html(_min_n(request)))


@router.post(_PREFIX + "/findings/variant-vote", dependencies=[Depends(requires(PUBLIC_PAGE))])
async def mockup_variant_vote(request: Request):
    data = await _json_body(request)
    if data is None:
        return JSONResponse({"error": "Send JSON."}, status_code=415)
    ip_key, tier = _visitor(request)
    try:
        out = feedback.pick_variant(str(data.get("variant", "")), tuple(_VARIANTS), ip_key=ip_key,
                                    device=data.get("device"), tier=tier)
    except feedback.FeedbackError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except feedback.RateLimited:
        return JSONResponse({"error": "Too many votes from this network. Please try again later."}, status_code=429)
    return JSONResponse(out)


@router.post(_PREFIX + "/findings/{slug}/feedback", dependencies=[Depends(requires(PUBLIC_PAGE))])
async def mockup_finding_feedback(request: Request, slug: str):
    if slug not in {f.slug for f, _, _, _ in _entries(_DEFAULT_MIN_N)}:
        return JSONResponse({"error": "Not a finding on this page."}, status_code=404)
    data = await _json_body(request)
    if data is None:
        return JSONResponse({"error": "Send JSON."}, status_code=415)
    ip_key, tier = _visitor(request)
    try:
        out = feedback.toggle_finding(slug, str(data.get("kind", "")), ip_key=ip_key,
                                      device=data.get("device"), tier=tier,
                                      comment=str(data.get("comment") or ""))
    except feedback.FeedbackError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except feedback.RateLimited:
        return JSONResponse({"error": "Too many votes from this network. Please try again later."}, status_code=429)
    return JSONResponse(out)


@router.get(_PREFIX + "/findings/source/{job_type}/{job_id}/download.json",
            dependencies=[Depends(requires(PUBLIC_PAGE))])
async def mockup_draft_source(job_type: str, job_id: str):
    """Raw data for the drafts this preview shows. Scoped like the live
    /findings/source carve-out: only results a previewed draft cites."""
    cited = set()
    for f, _, _, is_draft in _entries(_DEFAULT_MIN_N):
        if is_draft:
            for rid in f.source_result_ids:
                t, tail = rid.split("/", 1)
                cited.add((t, tail.split("_")[-1]))
    if (job_type, job_id.split("_")[-1]) not in cited:
        return JSONResponse({"error": "Not a cited draft source"}, status_code=404)
    data = load_result(job_type, job_id, visitor_key=None)
    if not data:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return StreamingResponse(io.BytesIO(json.dumps(data, indent=2).encode()), media_type="application/json")


@router.get(_PREFIX + "/findings/{slug}", response_class=HTMLResponse,
            dependencies=[Depends(requires(PUBLIC_PAGE))])
async def mockup_finding_detail(request: Request, slug: str):
    body = _detail_html(slug, _min_n(request))
    if body is None:
        return HTMLResponse("Not found", status_code=404)
    return _page(request, "Finding (preview)", body)
