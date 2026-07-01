"""
finding_draft.py — LLM-assisted, human-gated finding drafter (Lab-only).

This is OWL's FIRST non-measurement use of a local LLM. Everywhere else the
models are measurement *targets*; here a capable local model (gpt-oss:20b by
default) DRAFTS a `docs/findings/<slug>.md` from one or more stored results, for
an operator to edit and approve. Nothing is published without a human save.

Design rules (see docs/finding_draft_method.md and CLAUDE.md §GoS Framing):
  - The LLM NEVER detects signals. Deterministic code reads the result JSON,
    pulls the confidence flags, and qualifies cross-run signals; the LLM only
    *verbalises* facts it is handed. "If it can't be measured, don't assert it."
  - The LLM never sets confidence / scope / source_result_ids — those are
    derived from the cited results. The LLM writes headline, claim_short,
    body prose, caveats, tags only.
  - A guardrail layer (validate_draft) enforces the GoS framing ban on
    bandwidth→network-energy claims, scope/confidence honesty, schema
    completeness, and flags numbers in the prose that don't trace to the data.
  - The drafting model competes for the GPU, so drafting refuses to run while a
    measurement holds /tmp/gos-measure.lock.
"""

from __future__ import annotations

import datetime
import json
import re
from pathlib import Path

import findings as findings_mod

_REPO_ROOT    = Path(__file__).resolve().parent.parent
_FINDINGS_DIR = _REPO_ROOT / "docs" / "findings"
_MEASURE_LOCK = Path("/tmp/gos-measure.lock")

DEFAULT_MODEL    = "gpt-oss:20b"
DEFAULT_METHODOLOGY_REF = "docs/wattlab_traffic_light_confidence.md"

_FLAG_RANK  = {"red": 0, "yellow": 1, "green": 2}
_EMOJI_FLAG = {"🟢": "green", "🟡": "yellow", "🔴": "red"}


class DraftError(Exception):
    """Drafting could not start (locked, no resolvable sources, model down)."""


# --- measurement-integrity guard -------------------------------------------

def measurement_in_progress() -> bool:
    """True while a measurement holds the lock — drafting must not run then, it
    would contend for the GPU and contaminate the in-flight energy reading."""
    return _MEASURE_LOCK.exists()


# --- context assembly: the only numeric facts the LLM may use --------------

def _walk_flags(obj) -> list[str]:
    """Every confidence flag in a result, normalised to green/yellow/red."""
    out: list[str] = []
    if isinstance(obj, dict):
        flag = obj.get("flag")
        if isinstance(flag, str) and flag in _EMOJI_FLAG and "label" in obj:
            out.append(_EMOJI_FLAG[flag])
        for v in obj.values():
            out.extend(_walk_flags(v))
    elif isinstance(obj, list):
        for v in obj:
            out.extend(_walk_flags(v))
    return out


def _collect_numbers(obj) -> set[float]:
    """All numeric values anywhere in the result — used to check the LLM didn't
    invent figures. Bools are excluded (isinstance(True, int) is True)."""
    out: set[float] = set()
    if isinstance(obj, bool):
        return out
    if isinstance(obj, (int, float)):
        out.add(float(obj))
    elif isinstance(obj, str):
        for m in re.findall(r"-?\d+(?:\.\d+)?", obj):
            try:
                out.add(float(m))
            except ValueError:
                pass
    elif isinstance(obj, dict):
        for v in obj.values():
            out |= _collect_numbers(v)
    elif isinstance(obj, list):
        for v in obj:
            out |= _collect_numbers(v)
    return out


# Metric keys worth handing the LLM verbatim, with their unit. Without these
# the model has no real figures to write with — it placeholder-fills or
# hallucinates (an end-to-end test showed exactly that).
_METRIC_UNITS = {
    "delta_e_wh": "Wh", "delta_w": "W", "delta_t_s": "s", "w_base": "W",
    "vmaf": "VMAF", "tokens_per_sec": "tok/s", "mwh_per_token": "mWh/tok",
    "output_size_mb": "MB", "duration_s": "s", "total_s": "s", "gen_s": "s",
    "load_s": "s", "vqa_score": "VQA", "co2e_g": "g",
}


def _key_metrics(obj, prefix: str = "") -> list[str]:
    """Flatten the result to side-labeled 'path = value unit' facts (e.g.
    'gpu.energy.delta_e_wh = 0.32 Wh') so the LLM writes with real numbers.

    NR-VQA quality is the point of /enhance-run findings, but it's nested as
    `<side>.vqa.score` (not a flat key) — handle it explicitly and surface the
    score, while skipping the vqa dict's internals (its duration_s is scoring
    overhead, not part of the finding)."""
    out: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            path = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict) and "vqa" in k.lower() and isinstance(
                    v.get("score"), (int, float)) and not isinstance(v.get("score"), bool):
                out.append(f"{path}.score = {v['score']} NR-VQA (higher = better quality)")
                continue
            if k in _METRIC_UNITS and isinstance(v, (int, float)) and not isinstance(v, bool):
                out.append(f"{path} = {v} {_METRIC_UNITS[k]}")
            elif isinstance(v, (dict, list)):
                out.extend(_key_metrics(v, path))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.extend(_key_metrics(v, f"{prefix}[{i}]"))
    return out


_RESULTS_DIR = _REPO_ROOT / "results"


def normalize_rid(rid: str) -> str:
    """Return `<type>/<token>` resolved to a real stored result.

    Tolerates the common slip of using the page name as the type prefix
    (e.g. `enhance-run/8675abb9` → `enhance/8675abb9`): if the given type
    doesn't resolve, search every results/<type>/ dir for the bare token and,
    when exactly one type matches, correct it. Left unchanged if ambiguous or
    not found (gather_context then raises a helpful error)."""
    rid = rid.strip()
    if findings_mod.resolve_result_path(rid) is not None:
        return rid
    token = (rid.split("/", 1)[1] if "/" in rid else rid).split("_")[-1]
    if not token:
        return rid
    hits = []
    if _RESULTS_DIR.exists():
        for type_dir in _RESULTS_DIR.iterdir():
            if type_dir.is_dir() and list(type_dir.glob(f"*{token}*.json")):
                hits.append(type_dir.name)
    return f"{hits[0]}/{token}" if len(hits) == 1 else rid


def gather_context(source_result_ids: list[str]) -> dict:
    """Load and distil the cited results into structured facts.

    Returns {results:[{id,type,scope,flag,finding,...}], scope, confidence,
    numbers:set[float]}. Raises DraftError if no id resolves to a file."""
    if not source_result_ids:
        raise DraftError("no source_result_ids given")

    results: list[dict] = []
    numbers: set[float] = set()
    allowed: set[float] = set()      # analysis/finding numbers the LLM may quote
    salient: set[float] = set()      # the metric values fed to the LLM (small set)
    scopes: list[str] = []
    flags: list[str] = []
    normalized: list[str] = []
    unresolved: list[str] = []

    for raw in source_result_ids:
        rid = normalize_rid(raw)
        path = findings_mod.resolve_result_path(rid)
        if path is None:
            unresolved.append(raw)
            continue
        try:
            data = json.loads(path.read_text())
        except Exception:
            unresolved.append(raw)
            continue
        normalized.append(rid)
        rflags = _walk_flags(data)
        flags.extend(rflags)
        worst = min(rflags, key=lambda f: _FLAG_RANK[f]) if rflags else None
        scope = data.get("scope")
        if isinstance(scope, str) and scope:
            scopes.append(scope)
        numbers |= _collect_numbers(data)
        analysis = data.get("analysis") or {}
        # Allowed-number basis for the prose check = the figures the LLM was
        # actually handed: the salient metrics + the rule-based analysis/finding
        # numbers (percentages, deltas it may quote). NOT the full JSON dump,
        # which is so dense (~hundreds of values) that every figure spuriously
        # "matches" — making the check both noisy and falsely reassuring.
        allowed |= _collect_numbers(analysis)
        metrics = _key_metrics(data)
        for m in metrics:
            mm = re.search(r"=\s*(-?\d+(?:\.\d+)?)", m)
            if mm:
                salient.add(float(mm.group(1)))
        results.append({
            "id": rid,
            "type": rid.split("/", 1)[0],
            "mode": data.get("mode"),
            "scope": scope,
            "flag": worst,
            "flags": rflags,
            "finding": analysis.get("finding") if isinstance(analysis, dict) else None,
            "metrics": metrics,
            "data": data,
        })

    if not results:
        types = sorted(p.name for p in _RESULTS_DIR.iterdir()
                       if p.is_dir() and not p.name.startswith("_")) \
            if _RESULTS_DIR.exists() else []
        raise DraftError(
            f"none of {source_result_ids!r} resolves to a stored result. "
            f"Use the result TYPE as the prefix, not the page name "
            f"(e.g. 'enhance/<id>', not 'enhance-run/<id>'). "
            f"Known types: {', '.join(types) or '(none)'}."
        )

    # Confidence honesty: a finding can be no greener than its weakest source.
    overall = min(flags, key=lambda f: _FLAG_RANK[f]) if flags else "red"
    # Scope: use the cited results' as-measured scope verbatim (don't invent).
    scope = scopes[0] if scopes else ""
    return {
        "results": results,
        "source_result_ids": normalized,   # corrected ids, for the finding frontmatter
        "unresolved": unresolved,
        "scope": scope,
        "scopes": scopes,
        "confidence": overall,
        "numbers": numbers,                 # every number in the JSON (broad)
        "allowed": allowed | salient,       # the figures the LLM was handed (tight)
        "salient": salient,
    }


# --- deterministic signal detectors (the real "weak signal" layer) ---------

def _summary_delta_e(summary: dict) -> float | None:
    """Pull a representative energy delta (Wh) from a list_results summary,
    tolerating the per-mode shape differences. None if absent."""
    for k in ("delta_e_wh", "cpu_delta_e_wh", "gpu_delta_e_wh"):
        v = summary.get(k)
        if isinstance(v, (int, float)):
            return float(v)
    return None


def detect_signals(ctx: dict, recent_limit: int = 20) -> list[dict]:
    """Qualify candidate signals from the cited results vs recent history.

    Each signal carries a confidence so the prompt can be honest. The LLM is
    handed these as text — it never re-derives them. Defensive throughout:
    missing/odd history just yields fewer signals, never an error."""
    import persist

    signals: list[dict] = []

    # 1. Confidence floor — always emitted; it bounds what may be asserted.
    floor = ctx["confidence"]
    signals.append({
        "kind": "confidence_floor",
        "confidence": floor,
        "text": {
            "green": "All cited measurements are 🟢 repeatable — the headline claim is assertable.",
            "yellow": "Weakest cited measurement is 🟡 indicative — frame the claim as early/indicative, not settled.",
            "red": "A cited measurement is 🔴 below the noise floor — this is NOT yet an assertable finding; needs more data.",
        }[floor],
    })

    # 2. Consistency with recent runs of the same type — outlier vs in-family.
    by_type: dict[str, list[str]] = {}
    for r in ctx["results"]:
        by_type.setdefault(r["type"], []).append(r["id"])
    for jtype, ids in by_type.items():
        try:
            recent = persist.list_results(jtype, limit=recent_limit, visitor_key=None)
        except Exception:
            continue
        deltas = [d for d in (_summary_delta_e(s) for s in recent) if d is not None]
        if len(deltas) < 3:
            continue
        mean = sum(deltas) / len(deltas)
        var = sum((d - mean) ** 2 for d in deltas) / len(deltas)
        sd = var ** 0.5
        signals.append({
            "kind": "recent_distribution",
            "type": jtype,
            "n": len(deltas),
            "mean_wh": round(mean, 4),
            "sd_wh": round(sd, 4),
            "text": (
                f"Context: the last {len(deltas)} stored {jtype} results average "
                f"{mean:.4f} Wh (sd {sd:.4f}). Use only to judge whether a "
                f"difference is robust or within run-to-run scatter — do not cite "
                f"these as part of the finding."
            ),
        })
    return signals


# --- prompt -----------------------------------------------------------------

_SYSTEM_RULES = """\
You are drafting a research FINDING for OWL (Online WattLab), run by Greening of
Streaming — a neutral, technically credible NGO that measures the energy of
streaming and AI. You write a DRAFT for a human lab operator to edit; you do not
publish.

Hard rules — a violation makes the draft unusable:
1. Assert ONLY what the supplied measurements and qualified signals support. If a
   signal says a measurement is below the noise floor, do not claim an effect.
2. NEVER claim that more data, bitrate, or bandwidth causes more *network*
   energy. OWL measures device-layer energy only; the network is excluded, not
   modelled. You may report a delivery-side difference as a DATA/storage
   requirement (bytes, kbps) — never as network Wh.
3. Do not invent numbers. Every figure in your prose must come from the supplied
   facts. Quote the exact values given; NEVER write a placeholder like
   "[energy_value]" or "X Wh" — if a number is not supplied, do not state it.
4. Separate device / network / data-centre impacts explicitly. State scope and
   uncertainty.
5. Do not use the phrase "not eco-warriors" or any slogan.

Write in OWL's house style: precise, sober, quantified, with the trade-off made
visible. Sections like "The result, in one sentence", "Why this matters", "How
it was measured", "What this finding does not measure" work well.

Framing: when the measurements include a QUALITY axis (VMAF, VQA score, output
resolution, file size), LEAD with what changed in quality — what the viewer or
operator actually gets — and present energy as the BUDGET that bought that
quality ("what you get for your energy budget"), not as a standalone cost. The
energy-for-quality trade-off is the spine of the finding, not an afterthought.
"""


def _exemplars(job_type: str, k: int = 2) -> list[findings_mod.Finding]:
    """A couple of existing findings as style/schema exemplars, preferring the
    same result type. This is the useful 'RAG' here — exemplar retrieval, not
    vector search over the papers corpus."""
    allf = findings_mod.list_all()
    same = [f for f in allf if any(r.split("/", 1)[0] == job_type
                                   for r in f.source_result_ids)]
    rest = [f for f in allf if f not in same]
    return (same + rest)[:k]


def build_prompt(ctx: dict, signals: list[dict], angle: str = "") -> str:
    facts = []
    for r in ctx["results"]:
        facts.append(f"- {r['id']} (type={r['type']}, mode={r['mode']}, "
                     f"confidence={r['flag']})")
        for m in r.get("metrics", []):
            facts.append(f"    {m}")
        if r["finding"]:
            facts.append(f"    rule-based finding: {r['finding']}")
        if r["scope"]:
            facts.append(f"    scope: {r['scope']}")
    sig_lines = [f"- {s['text']}" for s in signals]

    job_type = ctx["results"][0]["type"]
    ex_lines = []
    for f in _exemplars(job_type):
        ex_lines.append(f"### Exemplar: {f.headline}\n{f.body_md[:900]}")

    angle_block = ""
    if angle.strip():
        angle_block = (
            "## Operator's requested angle (HIGHEST-PRIORITY framing)\n"
            f"Frame the finding around this lens: {angle.strip()}\n"
            "Honour it as the primary shape of the write-up, within the hard "
            "rules above (never fabricate, never claim network energy).\n\n"
        )

    return (
        f"{_SYSTEM_RULES}\n\n"
        f"{angle_block}"
        f"## Cited measurements (the ONLY numeric facts you may use)\n"
        + "\n".join(facts) + "\n\n"
        f"## Qualified signals (deterministically derived — do not re-derive)\n"
        + "\n".join(sig_lines) + "\n\n"
        f"## Style exemplars (do NOT copy their numbers)\n"
        + "\n\n".join(ex_lines) + "\n\n"
        "## Your task\n"
        "Return STRICT JSON (no markdown fences) with keys: "
        '"headline" (one sentence, quantified), "claim_short" (one compact line '
        'of the key numbers), "tags" (list of short keywords), "caveats" (list '
        'of honest limitations), "body_md" (the finding prose in OWL house '
        "style). Do not include confidence, scope, dates, or source ids — those "
        "are filled in for you.\n"
    )


# --- generation -------------------------------------------------------------

def _default_generate(prompt: str, model: str) -> str:
    import llm
    out = llm.run_inference_streaming(model, prompt, num_gpu=-1)
    return out.get("response", "")


def _extract_json(text: str) -> dict:
    """Pull the first JSON object out of an LLM response (tolerates fences /
    prose / <think> preamble that reasoning models emit)."""
    s = text.strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s, flags=re.MULTILINE)
    start = s.find("{")
    if start == -1:
        raise DraftError("LLM returned no JSON object")
    depth, in_str, esc = 0, False, False
    for i in range(start, len(s)):
        c = s[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        # strict=False: reasoning models often emit raw newlines
                        # inside string values (technically invalid JSON).
                        return json.loads(s[start:i + 1], strict=False)
                    except json.JSONDecodeError as e:
                        raise DraftError(f"LLM JSON parse failed: {e}")
    raise DraftError("LLM JSON object not closed")


def slugify(headline: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", headline.lower()).strip("-")
    return s[:60].strip("-") or "untitled-finding"


def draft_finding(source_result_ids: list[str], model: str = DEFAULT_MODEL,
                  generate=None, today: str | None = None,
                  angle: str = "") -> dict:
    """Produce a draft finding (frontmatter + body) — does NOT write to disk.

    `angle` is optional operator steering ("lead with the quality gain and what
    the energy budget buys"). `generate(prompt, model)->str` and `today` are
    injectable for tests."""
    if measurement_in_progress():
        raise DraftError(
            "a measurement is in progress (/tmp/gos-measure.lock held) — "
            "drafting would contend for the GPU; try again when it clears"
        )
    ctx = gather_context(source_result_ids)
    signals = detect_signals(ctx)
    prompt = build_prompt(ctx, signals, angle=angle)
    gen = generate or _default_generate
    raw = gen(prompt, model)
    parsed = _extract_json(raw)

    today = today or datetime.date.today().isoformat()
    headline = str(parsed.get("headline", "")).strip()
    meta = {
        "slug": slugify(headline),
        "version": 1,
        "first_measured": today,
        "last_refined": today,
        "headline": headline,
        "claim_short": str(parsed.get("claim_short", "")).strip(),
        # Derived, NOT from the LLM:
        "confidence": ctx["confidence"],
        "scope": ctx["scope"],
        "methodology_ref": DEFAULT_METHODOLOGY_REF,
        "source_result_ids": ctx["source_result_ids"],   # normalized to real types
        "related_findings": [],
        "supersedes": None,
        "tags": [str(t) for t in (parsed.get("tags") or [])],
        "caveats": [str(c) for c in (parsed.get("caveats") or [])],
    }
    body = str(parsed.get("body_md", "")).strip()
    validation = validate_draft(meta, body, ctx=ctx)
    return {
        "ok": not any(v["severity"] == "error" for v in validation),
        "draft": {**meta, "body_md": body},
        "facts": {
            "confidence": ctx["confidence"],
            "scope": ctx["scope"],
            "signals": [s["text"] for s in signals],
            "sources": [{"id": r["id"], "flag": r["flag"]} for r in ctx["results"]],
        },
        "validation": validation,
        "raw_llm": raw,
        "model": model,
    }


# --- guardrail / validation -------------------------------------------------

# The forbidden construct (CLAUDE.md §GoS Framing): a data/bitrate term and a
# network-energy term asserted together. "Networks use energy" alone is fine;
# "more bits ⇒ more network energy" is not.
_DATA_TERMS = re.compile(
    r"\b(bitrate|bandwidth|kbps|mbps|gbps|throughput|bits?|bytes?|data\s+rate)\b",
    re.IGNORECASE)
_NET_ENERGY = re.compile(
    r"\bnetwork[- ]?(energy|power|wh|kwh|watt|consum\w*|draw|footprint)\b",
    re.IGNORECASE)
_MOTTO = re.compile(r"not\s+eco[- ]?warriors", re.IGNORECASE)

# Numbers in prose that carry a unit — the substantive claims worth checking.
_NUM_WITH_UNIT = re.compile(
    r"(\d+(?:\.\d+)?)\s*(wh|kwh|w\b|%|mb|gb|kbps|mbps|fps|×|x\b|s\b|vmaf|tok)",
    re.IGNORECASE)


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]


def validate_draft(meta: dict, body: str, ctx: dict | None = None) -> list[dict]:
    """Structured validation report. severity 'error' blocks save; 'warning' is
    surfaced for the operator but does not block."""
    issues: list[dict] = []

    def err(code, msg):
        issues.append({"severity": "error", "code": code, "message": msg})

    def warn(code, msg):
        issues.append({"severity": "warning", "code": code, "message": msg})

    # 1. Schema completeness (same required set as the loader).
    missing = findings_mod._REQUIRED_FIELDS - meta.keys()
    if missing:
        err("schema_missing", f"missing required fields: {sorted(missing)}")
    if not meta.get("headline"):
        err("empty_headline", "headline is empty")
    if not meta.get("source_result_ids"):
        err("no_sources", "source_result_ids must be a non-empty list")
    if not findings_mod._SLUG_RE.match(str(meta.get("slug", ""))):
        err("bad_slug", f"slug {meta.get('slug')!r} is not a valid slug")
    if (_FINDINGS_DIR / f"{meta.get('slug')}.md").exists():
        warn("slug_exists", f"a finding {meta.get('slug')!r} already exists — "
                            f"saving will overwrite it (bump version first)")

    # 2. Confidence honesty.
    conf = meta.get("confidence")
    if conf not in findings_mod._VALID_CONFIDENCE:
        err("bad_confidence", f"confidence {conf!r} not in green/yellow/red")
    elif ctx is not None and conf != ctx["confidence"]:
        if _FLAG_RANK.get(conf, 0) > _FLAG_RANK.get(ctx["confidence"], 0):
            err("confidence_inflated",
                f"finding confidence {conf!r} is greener than the weakest cited "
                f"measurement ({ctx['confidence']!r}) supports")
    if conf == "red":
        err("red_source", "a cited measurement is below the noise floor — this "
                          "is not an assertable finding yet")

    # 3. Scope integrity — must match an as-measured scope from a cited result.
    if ctx is not None and ctx.get("scopes"):
        if meta.get("scope") not in ctx["scopes"]:
            err("scope_mismatch", "scope does not match any cited result's "
                                 "as-measured scope")

    # 4. Sources resolve on disk.
    for rid in meta.get("source_result_ids", []):
        if findings_mod.resolve_result_path(str(rid)) is None:
            err("dangling_source", f"source_result_id {rid!r} resolves to no file")

    # 5. GoS framing lint — bandwidth→network-energy ban + motto.
    haystacks = [str(meta.get("headline", "")), str(meta.get("claim_short", "")),
                 body] + [str(c) for c in meta.get("caveats", [])]
    blob = "\n".join(haystacks)
    for sent in _sentences(blob):
        if _DATA_TERMS.search(sent) and _NET_ENERGY.search(sent):
            err("bandwidth_network_energy",
                f"forbidden bandwidth→network-energy claim: {sent!r}")
    if _MOTTO.search(blob):
        warn("motto", "drop the 'not eco-warriors' slogan")

    # 6. Number-consistency — figures in prose should trace to the data, either
    #    directly or as a simple derivation (a difference/sum of two measured
    #    metrics — e.g. an ML-vs-ffmpeg energy delta). Report each distinct
    #    untraceable figure ONCE; duplicates across headline/claim/body are noise.
    if ctx is not None:
        # Tight basis (figures handed to the LLM); fall back to the broad set
        # for contexts built without it (e.g. older callers/tests).
        known = ctx.get("allowed") or ctx["numbers"]
        salient = ctx.get("salient") or set()
        seen: set[float] = set()
        for m in _NUM_WITH_UNIT.finditer(blob):
            try:
                val = float(m.group(1))
            except ValueError:
                continue
            if any(abs(val - s) <= max(abs(val), abs(s)) * 0.01 for s in seen):
                continue                      # already reported this figure
            if _value_known(val, known) or _derived_value(val, salient):
                continue
            seen.add(val)
            figure = re.sub(r"\s+", " ", m.group(0)).strip()   # normalise   etc.
            warn("unverified_number",
                 f"figure '{figure}' is not a measured value or a simple "
                 f"difference/sum of two — verify before publishing")

    return issues


def _value_known(val: float, known: set[float], rel: float = 0.01) -> bool:
    """True if `val` matches a known value within 1% (or matches a rounding of
    one). Tolerates the LLM quoting 0.71 for a stored 0.7123."""
    for k in known:
        if k == val:
            return True
        tol = max(abs(k), abs(val)) * rel
        if abs(k - val) <= tol:
            return True
        # rounding: stored 0.7123 quoted as 0.71 / 0.712
        for nd in (0, 1, 2, 3):
            if round(k, nd) == val:
                return True
    return False


def _derived_value(val: float, salient: set[float], rel: float = 0.01) -> bool:
    """True if `val` is a pairwise difference or sum of two salient metric
    values (within 1%). Covers the honest deltas a finding naturally states
    (ML−ffmpeg energy, before/after file size) without inflating the accept-set
    to the point of waving through hallucinations — `salient` is the ~dozen
    metric values fed to the LLM, not every number in the JSON."""
    if val < 0:
        val = abs(val)
    vals = list(salient)
    for i, a in enumerate(vals):
        for b in vals[i:]:
            for cand in (abs(a - b), a + b):
                if cand and abs(cand - val) <= max(cand, val) * rel:
                    return True
    return False


# --- save -------------------------------------------------------------------

def render_markdown(meta: dict, body: str) -> str:
    """Serialise a draft to the `---`-fenced markdown a finding file needs."""
    import yaml
    front = {k: meta[k] for k in (
        "slug", "version", "first_measured", "last_refined", "headline",
        "claim_short", "confidence", "scope", "methodology_ref",
        "source_result_ids", "related_findings", "supersedes", "tags", "caveats")
        if k in meta}
    fm = yaml.safe_dump(front, sort_keys=False, allow_unicode=True,
                        default_flow_style=False).strip()
    return f"---\n{fm}\n---\n\n{body.strip()}\n"


def save_draft(meta: dict, body: str) -> Path:
    """Write the (operator-edited) draft to docs/findings/<slug>.md.

    Re-validates first: refuses to write if any error remains, and confirms the
    written file loads cleanly through the canonical findings loader."""
    ctx = gather_context([str(x) for x in meta.get("source_result_ids", [])])
    issues = validate_draft(meta, body, ctx=ctx)
    blocking = [i for i in issues if i["severity"] == "error"]
    if blocking:
        raise DraftError("cannot save — unresolved errors: "
                         + "; ".join(i["message"] for i in blocking))
    slug = str(meta["slug"])
    path = _FINDINGS_DIR / f"{slug}.md"
    path.write_text(render_markdown(meta, body), encoding="utf-8")
    findings_mod._CACHE.pop(slug, None)
    # Confirm it round-trips through the real loader; roll back on failure.
    try:
        findings_mod.load(slug)
    except findings_mod.FindingError as e:
        path.unlink(missing_ok=True)
        raise DraftError(f"written finding failed validation, rolled back: {e}")
    return path
