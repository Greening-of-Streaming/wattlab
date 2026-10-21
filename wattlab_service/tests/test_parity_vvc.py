"""parity.build_cmd — VVC (libvvenc) codec and the opt-in 10-bit chain."""
import shlex

import pytest

import parity


def _argv(codec, bit_depth=8, profile="cpu", bps=1000):
    return shlex.split(parity.build_cmd(codec, profile, bps, 1080, bit_depth=bit_depth))


def test_default_8bit_cpu_cmd_unchanged():
    a = _argv("h265")
    assert a[a.index("-vf") + 1] == "scale=-2:1080"
    assert a[a.index("-profile:v") + 1] == "main"


def test_10bit_shared_chain_for_all_three_cpu_codecs():
    for codec in ("h265", "av1", "vvc"):
        a = _argv(codec, bit_depth=10)
        assert a[a.index("-vf") + 1] == "scale=-2:1080,format=yuv420p10le"
        assert a[a.index("-c:v") + 1] == parity.CPU_ENCODER[codec]
        assert a[a.index("-c:a") + 1] == "aac"


def test_10bit_h265_is_main10():
    a = _argv("h265", bit_depth=10)
    assert a[a.index("-profile:v") + 1] == "main10"


def test_vvc_pins_gop_via_intra_period_not_g():
    a = _argv("vvc", bit_depth=10)
    assert "-g" not in a                      # libvvenc ignores -g
    params = a[a.index("-vvenc-params") + 1]
    assert params == "IntraPeriod=120:DecodingRefreshType=idr"


@pytest.mark.parametrize("kw", [dict(bit_depth=8), dict(bit_depth=10, profile="gpu_baseline")])
def test_vvc_rejects_8bit_and_gpu(kw):
    with pytest.raises(ValueError):
        _argv("vvc", **kw)


def test_10bit_rejected_on_gpu_profiles():
    with pytest.raises(ValueError):
        _argv("h265", bit_depth=10, profile="gpu_baseline")
