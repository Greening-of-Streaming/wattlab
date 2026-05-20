"""Guards for the centralised external-link registry.

Regression context: the carbon-strip block (`_CARBON_JS`) is JavaScript living
inside a plain Python string, so the registry URL constants CANNOT be referenced
via JS `+` — doing so injects an undefined JS variable that throws ReferenceError
at runtime (the carbon strip sticks on "loading grid intensity…"). py_compile and
the rest of the suite don't catch it because the Python is still valid.

These tests assert the rendered output carries real URLs, with no bare registry
identifier and no unsubstituted token left behind.
"""
import re
import main

REGISTRY = [
    "POSITION_PAPER_URL", "GOS_URL", "JOIN_GOS_URL", "GOS_LOGO_URL",
    "GITHUB_REPO_URL", "GITHUB_ISSUES_URL", "ECO2MIX_URL",
    "ELECTRICITYMAPS_URL", "EMBER_URL", "CHARTJS_URL",
]


def test_registry_constants_are_urls():
    for name in REGISTRY:
        assert getattr(main, name).startswith("https://")


def test_carbon_js_has_baked_urls_not_identifiers_or_tokens():
    js = main._CARBON_JS
    for name in REGISTRY:
        assert name not in js, f"{name} leaked into _CARBON_JS as a bare JS identifier"
    assert not re.findall(r"__[A-Z_]+__", js), "unsubstituted token left in _CARBON_JS"
    for url in (main.ECO2MIX_URL, main.ELECTRICITYMAPS_URL,
                main.EMBER_URL, main.POSITION_PAPER_URL):
        assert url in js


def test_demo_html_baked_urls_not_identifiers():
    html = main._DEMO_HTML
    assert main.JOIN_GOS_URL in html and main.GOS_URL in html
    for name in REGISTRY:
        assert name not in html, f"{name} leaked into _DEMO_HTML as a bare identifier"


def test_methodology_tokens_fully_resolve():
    # _METHODOLOGY_HTML is a plain template carrying {TOKEN}s baked in the route's
    # .replace() chain; simulate that and assert nothing is left dangling.
    html = main._METHODOLOGY_HTML
    for name in REGISTRY:
        html = html.replace("{" + name + "}", getattr(main, name))
    assert not re.findall(r"\{[A-Z_]+_URL\}", html), "unresolved URL token in methodology"
    assert main.POSITION_PAPER_URL in html
