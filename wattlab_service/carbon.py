"""
carbon.py — Energy → CO2e conversion.

Single home for everything carbon-related. The rest of the service treats
Wh × g/kWh as a black box: it calls `walk_and_enrich(result_dict)` at save
time, and the resulting JSON carries a `co2e` block on every `energy`
sub-dict so audit trail + UI rendering both have the data they need.

Fallback ladder (no exception path; always returns a usable number):
  1. Live — ElectricityMaps API value, fresh (< LIVE_TTL_S)   → source="live"
  2. Static — annual mean for the zone (Ember 2025)            → source="static"

Live vs estimated is an explicit field in the returned dict — the UI shows
a badge based on this so visitors know which they're looking at.

The home zone (where the GoS1 server lives) gets a background poller; the
comparison zones use the static table only, so their numbers don't drift
between page loads.

CR-016 — both live and static numbers are on a **lifecycle** boundary
(includes nuclear fuel cycle, plant construction, methane upstream leaks,
etc.) so they are directly comparable. The live FR path used to trust
Eco2mix's `taux_co2` field (direct combustion only), which produced a
spurious ~4× live-vs-static gap during nuclear-heavy hours. We now derive
the live FR intensity from Eco2mix's production mix × IPCC AR6 lifecycle
factors instead — same method as the static annual means.
"""
import asyncio
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Read API token from .env at module import (siblings do the same).
try:
    from dotenv import dotenv_values
    _ENV = dotenv_values("/home/gos/wattlab/.env")
except Exception:
    _ENV = {}


# --- Config ---

# The zone the server actually runs in. Live polling targets this zone only.
HOME_ZONE = "FR"

# Cities shown in the comparison strip (in display order).
COMPARISON_ZONES = ["FR", "DK", "GB", "DE", "PL", "ES", "US", "CN"]

# Live cache freshness: values older than this are treated as stale and the
# fallback to the static annual mean kicks in. Applied to BOTH our cache hit
# time and the upstream source's own published timestamp (data_age_s).
LIVE_TTL_S = 30 * 60          # 30 minutes
POLL_INTERVAL_S = 5 * 60      # poll every 5 minutes
HTTP_TIMEOUT_S = 8.0

# Sources, in priority order for FR:
#   1. Eco2mix — RTE/Etalab official French TSO real-time data (no auth).
#      Already includes a precomputed `taux_co2` field, so we don't have to
#      compute carbon intensity from the production mix ourselves.
#   2. ElectricityMaps — third-party aggregator, requires token. Used as a
#      backup if Eco2mix is unreachable.
ECO2MIX_URL = (
    "https://odre.opendatasoft.com/api/explore/v2.1/catalog/datasets/"
    "eco2mix-national-tr/records"
)
ELECTRICITYMAPS_URL = "https://api.electricitymap.org/v3/carbon-intensity/latest"

# IPCC AR6 WGIII (2022) lifecycle median emission factors, gCO2eq/kWh.
# Used only as a sanity-check or fallback if `taux_co2` is missing from a
# given Eco2mix record. Eco2mix's own number is the authoritative output.
EMISSION_FACTORS = {
    "nucleaire":     12,
    "eolien":        11,
    "solaire":       45,
    "hydraulique":   24,
    "bioenergies":  230,
    "gaz":          490,
    "charbon":      820,
    "fioul":        650,
    "pompage":       24,   # pumped hydro storage — proxied with hydro factor
}
EMISSION_FACTORS_SOURCE = "IPCC AR6 WGIII (2022) lifecycle medians"


# Annual mean grid carbon intensity, gCO2eq/kWh — lifecycle basis (Ember
# generation mix × IPCC AR6 WGIII lifecycle factors), same basis as the
# live FR path. These are the fallback the UI shows as "estimated" (now
# badged 🟡 indicative per CR-036) and what the comparison cities always
# use, so they're directly comparable to the live FR number.
#
# Source: Ember Yearly Electricity Data, 2025 release (full-year 2025),
# via Our World in Data's "Lifecycle carbon intensity of electricity"
# grapher (ourworldindata.org/grapher/carbon-intensity-electricity).
# Refreshed 2026-05-12 from the raw CSV; rounded to whole g/kWh. To
# refresh again: pull the OWID CSV, take each entity's latest full year,
# update the values + `year` + STATIC_SOURCE + the "Ember <year> annual
# mean(s)" copy in main.py's _CARBON_JS and methodology section.
STATIC_INTENSITY = {
    "FR":    {"label": "Paris (France)",       "g_per_kwh": 41,  "year": 2025},
    "DK":    {"label": "Copenhagen (Denmark)", "g_per_kwh": 114, "year": 2025},
    "GB":    {"label": "London (UK)",          "g_per_kwh": 217, "year": 2025},
    "DE":    {"label": "Berlin (Germany)",     "g_per_kwh": 330, "year": 2025},
    "PL":    {"label": "Warsaw (Poland)",      "g_per_kwh": 589, "year": 2025},
    "ES":    {"label": "Madrid (Spain)",       "g_per_kwh": 154, "year": 2025},
    "NL":    {"label": "Amsterdam (NL)",       "g_per_kwh": 254, "year": 2025},
    "IE":    {"label": "Dublin (Ireland)",     "g_per_kwh": 257, "year": 2025},
    "IT":    {"label": "Rome (Italy)",         "g_per_kwh": 285, "year": 2025},
    "SE":    {"label": "Stockholm (Sweden)",   "g_per_kwh": 35,  "year": 2025},
    "NO":    {"label": "Oslo (Norway)",        "g_per_kwh": 28,  "year": 2025},
    "US":    {"label": "United States avg",    "g_per_kwh": 384, "year": 2025},
    "CN":    {"label": "China avg",            "g_per_kwh": 525, "year": 2025},
    "IN":    {"label": "India avg",            "g_per_kwh": 670, "year": 2025},
    "WORLD": {"label": "World average",        "g_per_kwh": 458, "year": 2025},
}
STATIC_SOURCE = "Ember 2025 annual mean"


# Curated historical France-grid data points (CR-018 Tier 1).
# Each value is the monthly mean lifecycle gCO2/kWh, computed from the
# Eco2mix consolidated production mix using `compute_intensity_from_mix`
# (the same IPCC AR6 factors as the live FR path — so live and historical
# are directly comparable).
#
# To regenerate or extend: `bin/fetch-historical-mix --year YYYY --month MM`
# and paste the printed value here.
#
# Five dates chosen to illustrate the range; not exhaustive. The full-
# history version (visitor-pickable any month) is captured as CR-018
# Tier 2.
HISTORICAL_INTENSITY = [
    {"key": "FR-2020-01", "zone": "FR", "year": 2020, "month": 1,
     "g_per_kwh": 65.8, "label": "France · Jan 2020",
     "note": "Pre-Covid winter."},
    {"key": "FR-2020-06", "zone": "FR", "year": 2020, "month": 6,
     "g_per_kwh": 54.6, "label": "France · Jun 2020",
     "note": "Covid-lockdown summer — industrial demand dipped."},
    {"key": "FR-2022-06", "zone": "FR", "year": 2022, "month": 6,
     "g_per_kwh": 59.5, "label": "France · Jun 2022",
     "note": "Energy-crisis-era summer (nuclear fleet partly offline)."},
    {"key": "FR-2024-01", "zone": "FR", "year": 2024, "month": 1,
     "g_per_kwh": 53.4, "label": "France · Jan 2024",
     "note": "Winter, post-recovery — cleaner than Jan 2020 despite the season."},
    {"key": "FR-2024-06", "zone": "FR", "year": 2024, "month": 6,
     "g_per_kwh": 26.9, "label": "France · Jun 2024",
     "note": "Recent summer — nuclear back, solar buildout reflected."},
]
HISTORICAL_SOURCE = (
    "Eco2mix consolidated dataset (RTE/Etalab) × IPCC AR6 lifecycle factors. "
    "Same methodology as the live path — directly comparable to today's number."
)


def historical_for_zone(zone: str) -> list:
    """All curated historical points for a given zone, ordered by date."""
    pts = [h for h in HISTORICAL_INTENSITY if h["zone"] == zone]
    pts.sort(key=lambda h: (h["year"], h["month"]))
    return pts


# Live cache: {zone: {"g_per_kwh": float, "fetched_at": epoch_s, "ok": bool}}
_LIVE: dict = {}


def _token() -> Optional[str]:
    return _ENV.get("ELECTRICITYMAPS_TOKEN") or None


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def compute_intensity_from_mix(mix_mw: dict) -> Optional[float]:
    """Sanity-check / fallback path: derive gCO2/kWh from a {source: MW} dict
    using EMISSION_FACTORS. Returns None if total positive production is 0
    or nothing maps to a known factor."""
    total = 0.0
    weighted = 0.0
    for source, mw in mix_mw.items():
        if mw is None:
            continue
        try:
            mw = float(mw)
        except (TypeError, ValueError):
            continue
        if mw <= 0:
            continue
        ef = EMISSION_FACTORS.get(source)
        if ef is None:
            continue
        total += mw
        weighted += mw * ef
    if total <= 0:
        return None
    return weighted / total


# --- Live fetchers ---

async def _fetch_eco2mix(client) -> Optional[dict]:
    """RTE/Etalab Eco2mix real-time — production mix in MW, converted to
    lifecycle gCO2eq/kWh using IPCC AR6 factors so live and static numbers
    sit on the same boundary (CR-016).

    Returns:
      {"g_per_kwh": float,            # lifecycle, derived from mix
       "g_per_kwh_direct": float,     # Eco2mix's own taux_co2 (direct
                                      # combustion only, kept for transparency)
       "mix_mw": {...},
       "source_datetime": str}
    or None on any failure.

    Why lifecycle over Eco2mix's `taux_co2`: `taux_co2` only counts direct
    combustion emissions (nuclear ~0, gas ~smokestack only). Our static
    table (Ember 2025 annual means) is on a lifecycle basis — including
    nuclear fuel cycle, plant construction, methane upstream leaks, etc.
    Mixing the two produced a ~4× live-vs-static gap that was almost
    entirely a methodology artefact (live 13 g/kWh vs static 53 g/kWh
    during a nuclear-heavy hour). With both on lifecycle, the gap reflects
    real diurnal grid variance (typically 1.0–1.5×).

    Filters `where=taux_co2 IS NOT NULL` because the dataset pre-populates
    rows for upcoming intervals as NULL placeholders — the latest *real*
    record is the one we want (also tells us the mix data is finalised).
    """
    try:
        r = await client.get(
            ECO2MIX_URL,
            params={
                "order_by": "date_heure desc",
                "where": "taux_co2 IS NOT NULL",
                "limit": 1,
            },
            timeout=HTTP_TIMEOUT_S,
        )
        if r.status_code != 200:
            return None
        data = r.json()
        records = data.get("results") or []
        if not records:
            return None
        rec = records[0]
        mix = {k: rec.get(k) for k in EMISSION_FACTORS.keys() if rec.get(k) is not None}
        lifecycle = compute_intensity_from_mix(mix)
        if lifecycle is None:
            # Mix unusable (all-zero or missing). No lifecycle number means
            # we can't honour our same-boundary contract — let the caller
            # fall through to ElectricityMaps or static.
            return None
        direct = rec.get("taux_co2")
        return {
            "g_per_kwh": round(lifecycle, 1),
            "g_per_kwh_direct": float(direct) if isinstance(direct, (int, float)) else None,
            "mix_mw": mix,
            "source_datetime": rec.get("date_heure"),
        }
    except Exception:
        return None


async def _fetch_electricitymaps(client, zone: str) -> Optional[float]:
    token = _token()
    if not token:
        return None
    try:
        r = await client.get(
            ELECTRICITYMAPS_URL,
            params={"zone": zone},
            headers={"auth-token": token},
            timeout=HTTP_TIMEOUT_S,
        )
        if r.status_code != 200:
            return None
        data = r.json()
        v = data.get("carbonIntensity")
        if not isinstance(v, (int, float)):
            return None
        return float(v)
    except Exception:
        return None


async def poller(zones=(HOME_ZONE,), interval_s: int = POLL_INTERVAL_S):
    """Background task — refreshes _LIVE for the given zones every interval_s.

    Source priority for FR:
      1. Eco2mix (RTE/Etalab — authoritative French TSO data, no auth)
      2. ElectricityMaps (if token configured)

    Other zones fall straight through to ElectricityMaps. Failures keep the
    previous good value (or leave the entry absent); the request path
    never blocks on this — if no live value is available, the static table
    is used.
    """
    try:
        import httpx
    except ImportError:
        # No httpx available — everything resolves to static. Service still works.
        return
    while True:
        try:
            async with httpx.AsyncClient() as client:
                for z in zones:
                    fetched = None

                    # 1. Eco2mix — only meaningful for FR.
                    if z == "FR":
                        eco = await _fetch_eco2mix(client)
                        if eco is not None:
                            fetched = {
                                "g_per_kwh": eco["g_per_kwh"],
                                "g_per_kwh_direct": eco.get("g_per_kwh_direct"),
                                "fetched_at": time.time(),
                                "ok": True,
                                "provider": "Eco2mix (RTE/Etalab)",
                                "provider_url": "https://www.rte-france.com/eco2mix",
                                "mix_mw": eco["mix_mw"],
                                "boundary": "lifecycle",
                                "source_datetime": eco["source_datetime"],
                            }

                    # 2. ElectricityMaps — backup for FR, primary for others.
                    if fetched is None:
                        v = await _fetch_electricitymaps(client, z)
                        if v is not None:
                            fetched = {
                                "g_per_kwh": v,
                                "fetched_at": time.time(),
                                "ok": True,
                                "provider": "ElectricityMaps",
                                "provider_url": "https://www.electricitymaps.com",
                            }

                    if fetched is not None:
                        _LIVE[z] = fetched
                    else:
                        # Mark unreachable but preserve any prior value.
                        existing = _LIVE.get(z, {})
                        _LIVE[z] = {**existing, "ok": False}
        except Exception:
            pass
        await asyncio.sleep(interval_s)


# --- Lookups ---

def intensity(zone: str = HOME_ZONE) -> dict:
    """Return current best-estimate intensity for `zone`. Always returns a
    usable value via the fallback ladder.

    For "live" results, `age_s` reflects the upstream source timestamp
    (`source_datetime`) when available, falling back to `fetched_at` —
    so the UI shows when RTE/ElectricityMaps actually published, not just
    when our cache was last refreshed."""
    z = zone.upper()
    live = _LIVE.get(z)
    if live and live.get("ok") and live.get("g_per_kwh") is not None:
        cache_age = time.time() - (live.get("fetched_at") or 0)
        # Compute data age from upstream timestamp if available.
        src_dt = _parse_iso(live.get("source_datetime"))
        if src_dt is not None:
            now = datetime.now(timezone.utc)
            data_age = (now - src_dt).total_seconds()
        else:
            data_age = cache_age
        # Fresh by both clocks.
        if cache_age < LIVE_TTL_S and data_age < LIVE_TTL_S:
            out = {
                "g_per_kwh": round(live["g_per_kwh"], 1),
                "source": "live",
                "fetched_at": live["fetched_at"],
                "age_s": int(data_age),
                "zone": z,
                "zone_label": STATIC_INTENSITY.get(z, {}).get("label", z),
                "provider": live.get("provider", "live"),
                "provider_url": live.get("provider_url"),
            }
            if live.get("mix_mw"):
                out["mix_mw"] = live["mix_mw"]
            if live.get("computed"):
                out["computed"] = True
            return out
    static = STATIC_INTENSITY.get(z) or STATIC_INTENSITY["WORLD"]
    return {
        "g_per_kwh": static["g_per_kwh"],
        "source": "static",
        "year": static.get("year"),
        "zone": z,
        "zone_label": static["label"],
        "provider": STATIC_SOURCE,
    }


def wh_to_co2e(wh: Optional[float], zone: str = HOME_ZONE) -> Optional[dict]:
    """Wh → gCO2e. Returns dict with `grams` and full intensity provenance."""
    if wh is None:
        return None
    try:
        wh_f = float(wh)
    except (TypeError, ValueError):
        return None
    i = intensity(zone)
    grams = (wh_f / 1000.0) * i["g_per_kwh"]
    # Clamp sub-baseline / negative readings to zero. ΔW < 0 happens on very
    # short tasks where the few polls during the encode happen to land below
    # baseline by chance (P110 1Hz × ~1W resolution). The honest read is
    # identical to ΔW ≈ 0 — the task is below the measurement floor — so we
    # surface the same "below measurement floor" treatment downstream rather
    # than display a numeric "negative footprint" that has no physical meaning.
    # The raw delta_w / delta_e_wh stay un-clamped in the result JSON so the
    # noise itself remains auditable; only the derived gCO2e is sanitised.
    if grams < 0:
        grams = 0
    # Round at nanogram precision — well below the P110 measurement floor.
    # Coarser rounding (3 decimals) silently truncates µg-scale values to 0,
    # which the UI then renders as "0 g". Display-layer formatting (fmtMass
    # in main.py) handles human-readable rounding from the full value.
    return {"grams": round(grams, 9), "intensity": i}


def enrich_energy(energy: dict, zone: str = HOME_ZONE) -> None:
    """Add a `co2e` block to an energy dict in place. Idempotent — overwrites
    any existing co2e block so re-enrichment picks up the latest intensity."""
    if not isinstance(energy, dict):
        return
    co2e = wh_to_co2e(energy.get("delta_e_wh"), zone)
    if co2e is not None:
        energy["co2e"] = co2e


def walk_and_enrich(obj, zone: str = HOME_ZONE) -> None:
    """Recursively walk a result dict, enriching every nested `energy` block.

    Single insertion point used by persist.save_result so every job type
    (video, llm, image, rag — single, both, all_codecs, all_both, batch,
    rag_compare, etc.) gets uniform CO2e enrichment without per-mode wiring.
    """
    if isinstance(obj, dict):
        if isinstance(obj.get("energy"), dict):
            enrich_energy(obj["energy"], zone)
        for v in obj.values():
            walk_and_enrich(v, zone)
    elif isinstance(obj, list):
        for v in obj:
            walk_and_enrich(v, zone)


def comparison_table(wh: Optional[float],
                     zones=COMPARISON_ZONES,
                     home_zone: str = HOME_ZONE) -> list:
    """Build comparison rows for a Wh figure. Home zone uses live (with
    static fallback); other zones always use static so values are stable
    across page loads."""
    if wh is None:
        return []
    rows = []
    for z in zones:
        if z == home_zone:
            i = intensity(z)  # may be live
        else:
            static = STATIC_INTENSITY.get(z) or STATIC_INTENSITY["WORLD"]
            i = {
                "g_per_kwh": static["g_per_kwh"],
                "source": "static",
                "year": static.get("year"),
                "zone": z,
                "zone_label": static["label"],
                "provider": STATIC_SOURCE,
            }
        grams = (float(wh) / 1000.0) * i["g_per_kwh"]
        row = {
            "zone": z,
            "label": i["zone_label"],
            "g_per_kwh": i["g_per_kwh"],
            "grams": round(grams, 9),
            "source": i["source"],
            "is_home": (z == home_zone),
        }
        if i.get("source") == "live":
            row["age_s"] = i.get("age_s")
        elif i.get("year"):
            row["year"] = i.get("year")
        rows.append(row)
    return rows


def status() -> dict:
    """Diagnostic snapshot for /carbon endpoint."""
    return {
        "home_zone": HOME_ZONE,
        "comparison_zones": COMPARISON_ZONES,
        "token_configured": bool(_token()),
        "home_intensity": intensity(HOME_ZONE),
        "live_cache": {
            z: {
                "g_per_kwh": v.get("g_per_kwh"),
                "ok": v.get("ok"),
                "age_s": int(time.time() - v["fetched_at"]) if v.get("fetched_at") else None,
            }
            for z, v in _LIVE.items()
        },
        "static_table": STATIC_INTENSITY,
        "static_source": STATIC_SOURCE,
        "historical_table": HISTORICAL_INTENSITY,
        "historical_source": HISTORICAL_SOURCE,
        "live_ttl_s": LIVE_TTL_S,
        "poll_interval_s": POLL_INTERVAL_S,
    }
