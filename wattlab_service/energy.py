"""
Energy arithmetic — the single definition of ΔE (Wh) from a mean power delta
and elapsed time.

Before CR-068 this one line was copy-pasted into eight measurement modules
(llm ×2, rag, image_gen, video, pixop, parity, rem_prep). The product's entire
output is energy numbers, so a sign or unit slip in any one copy would ship
green. Extracted here so it is defined and unit-tested exactly once.

Pure module: no imports, no I/O. The measurement modules import it; nothing
imports them back (keeps the layering rule intact).
"""


def energy_wh(delta_w: float, delta_t_s: float) -> float:
    """Energy in watt-hours from a mean power delta (W) over an interval (s).

    ΔE = ΔW × (Δt / 3600), rounded to 4 dp — the historical result-JSON
    precision (0.1 mWh). This reproduces the inline formula every measurement
    module used before CR-068 byte-for-byte; do NOT change the rounding without
    re-basing stored results (all cross-era comparisons assume it).
    """
    return round(delta_w * (delta_t_s / 3600), 4)
