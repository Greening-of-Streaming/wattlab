"""
routes_findings_feed.py — CR-087 — /findings.json, the findings feed the GoS
website (Wix) copies into its own database.

The website must keep working when OWL is offline, so Wix pulls this feed on a
schedule and keeps the last good copy (docs/wix_bridge/). OWL holds no Wix
credentials; this endpoint is read-only and public.

What crosses over: only findings at Lab-checked or above. Drafts and
not-reproduced findings never reach the website, so the Lab validation button
is the switch that publishes a finding there. Early signals (n below the bar)
carry no headline number or summary, as on the page. Validator names never
leave OWL.

Source: the CR-086 preview overlay, via routes_mockup_findings._entries. Phase B
moves those fields into frontmatter; this module then reads findings.py
directly and keeps the same output (schema_version 1).
"""
from datetime import datetime

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

import findings as findings_mod
import routes_mockup_findings as preview
import settings as cfg
from capabilities import requires, PUBLIC_PAGE

router = APIRouter()

SCHEMA_VERSION = 1
DEFAULT_PUBLIC_URL = "https://wattlab.greeningofstreaming.org"
_PUBLISHABLE = ("lab-checked", "group-validated")


def build_feed(base_url: str) -> dict:
    taxonomy = preview._load_yaml(preview._TAXONOMY_PATH)
    themes = taxonomy.get("theme", {}).get("values", {})
    stages = taxonomy.get("stage", {}).get("values", {})
    items = []
    for f, ov, early, is_draft in preview._entries(preview._DEFAULT_MIN_N):
        status = preview._review_status(ov, is_draft)
        if status not in _PUBLISHABLE:
            continue
        _, conf_label, conf_meaning = preview._CONF_PLAIN.get(f.confidence, ("", "", ""))
        theme = themes.get(ov.get("theme", ""), {})
        items.append({
            "slug": f.slug,
            "headline": ov.get("plain_headline") or f.headline,
            "why_it_matters": " ".join(str(ov.get("why_it_matters", "")).split()),
            "summary": "" if early else " ".join(str(ov.get("plain_summary", "")).split()),
            "key_number": "" if early else str(ov.get("key_number", "")),
            "early_signal": bool(early),
            "repeats": ov.get("n_runs"),
            "confidence": f.confidence,
            "confidence_label": conf_label,
            "confidence_meaning": conf_meaning,
            "review_status": status,
            "review_label": preview._REVIEW[status][0],
            "question": theme.get("question", ""),
            "question_label": theme.get("label", ""),
            "stages": [stages.get(s, {}).get("label", s) for s in ov.get("stages", [])],
            "first_measured": str(f.first_measured),
            "last_refined": str(f.last_refined),
            # Drafts have no public page yet; the website shows those cards without a link.
            "url": None if is_draft else f"{base_url}/findings/{f.slug}",
            "sort_order": len(items) + 1,
        })
    return {
        "schema_version": SCHEMA_VERSION,
        "source": "Open WattLab, the measurement lab of Greening of Streaming",
        "source_url": base_url,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "count": len(items),
        "findings": items,
    }


@router.get("/findings.json", dependencies=[Depends(requires(PUBLIC_PAGE))])
async def findings_feed():
    s = cfg.load()
    if not s.get("findings_enabled", False):
        return JSONResponse({"error": "Not found"}, status_code=404)
    feed = build_feed((s.get("public_base_url") or DEFAULT_PUBLIC_URL).rstrip("/"))
    return JSONResponse(feed, headers={"Cache-Control": "public, max-age=300",
                                       "Access-Control-Allow-Origin": "*"})
