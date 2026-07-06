"""
CR-068 · unit coverage for the extracted energy_wh() helper.

The eight inline copies this replaced had zero direct tests — the only
assertion on delta_e_wh anywhere was `is not None`. These pin the contract:
the formula, the 4-dp rounding, and the sign.
"""
import energy


def test_basic_conversion():
    # 3600 W for 1 s = 1 Wh.
    assert energy.energy_wh(3600, 1) == 1.0
    # 100 W for 3600 s (1 h) = 100 Wh.
    assert energy.energy_wh(100, 3600) == 100.0


def test_matches_legacy_inline_formula():
    # The exact expression the measurement modules used before extraction.
    for dw, dt in [(12.3, 47.0), (0.0031, 15.0), (250.7, 612.4), (1.0, 1.0)]:
        assert energy.energy_wh(dw, dt) == round(dw * (dt / 3600), 4)


def test_rounds_to_four_dp():
    # 1 W for 1 s = 1/3600 Wh = 0.000277... → 0.0003 at 4 dp.
    assert energy.energy_wh(1, 1) == 0.0003


def test_zero_power_or_time_is_zero():
    assert energy.energy_wh(0, 5000) == 0.0
    assert energy.energy_wh(500, 0) == 0.0


def test_negative_delta_w_preserved():
    # A below-baseline task (rare, but real noise) must not be silently clamped.
    assert energy.energy_wh(-3600, 1) == -1.0
