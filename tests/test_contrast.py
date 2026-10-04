"""WCAG contrast audit for every color pair Conjure draws: text at 4.5:1 or better (AA), component
borders at 3:1 or better (1.4.11), in the Tk windows, the overlay, and the web pages."""

import re

import pytest

import config
from pipeline import palette as P
from pipeline.overlay import NAIVE_RED, STATUS


def luminance(h):
    r, g, b = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def contrast(a, b):
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


TEXT_PAIRS = {
    "body text": (P.WHITE, P.NAVY), "accent text": (P.SKY_LIGHT, P.NAVY), "muted text": (P.MUTED, P.NAVY),
    "button text": (P.WHITE, P.NAVY_3), "selected button text": (P.NAVY, P.SKY), "pill text": (P.SKY_LIGHT, P.NAVY_2),
    "warning banner text": (P.WHITE, P.RED_DEEP), "naive click label": (NAIVE_RED, P.NAVY_2),
    "muted on card": (P.MUTED, P.NAVY_3), "accent on card": (P.SKY_LIGHT, P.NAVY_3),
    "web button text (gradient start)": (P.NAVY, P.SKY), "web button text (gradient end)": (P.NAVY, P.SKY_LIGHT),
}
BORDER_PAIRS = {"button border": (P.BORDER, P.NAVY_3), "pill border": (P.BORDER, P.NAVY_2),
                "window border": (P.BORDER, P.NAVY)}


@pytest.mark.parametrize("name", sorted(TEXT_PAIRS))
def test_text_contrast_meets_aa(name):
    fg, bg = TEXT_PAIRS[name]
    assert contrast(fg, bg) >= 4.5, f"{name}: {contrast(fg, bg):.2f}"


@pytest.mark.parametrize("name", sorted(BORDER_PAIRS))
def test_component_borders_meet_3_to_1(name):
    fg, bg = BORDER_PAIRS[name]
    assert contrast(fg, bg) >= 3.0, f"{name}: {contrast(fg, bg):.2f}"


@pytest.mark.parametrize("key", sorted(STATUS))
def test_status_dot_colors_read_on_the_pill(key):
    assert contrast(STATUS[key][0], P.NAVY_2) >= 4.5


@pytest.mark.parametrize("page", ["index.html", "practice.html"])
def test_web_pages_use_the_audited_palette_for_borders(page):
    html = (config.SPELLBOOK_PATH.parent / page).read_text()
    root = dict(re.findall(r"--([a-z0-9-]+): (#[0-9a-f]{6})", html))
    assert root["navy"] == P.NAVY and root["sky"] == P.SKY and root["sky-light"] == P.SKY_LIGHT
    assert root["border"] == P.BORDER
    # No component border still uses the too-dark sky-deep (gradients may).
    for m in re.finditer(r"border(?:-color)?: [^;]*var\(--sky-deep\)", html):
        pytest.fail(f"{page}: {m.group(0)}")
    assert contrast(root["white"], root["navy"]) >= 7 and contrast(root["muted"], root["navy-3"]) >= 4.5
