import re

import config

HTML = config.SPELLBOOK_PATH.read_text()


PRACTICE = (config.SPELLBOOK_PATH.parent / "practice.html").read_text()


def test_spellbook_loads_nothing_from_the_network():
    for html in (HTML, PRACTICE):
        assert not re.search(r"https?://|//fonts|@import|<link|src=", html)


def test_practice_page_measures_throughput_and_misses_with_three_target_sizes():
    assert "bits/s" in PRACTICE and "misses" in PRACTICE.lower()
    assert "SIZES = [120, 80, 50]" in PRACTICE
    assert 'href="practice.html"' in HTML or "practice.html" in HTML


def test_base_target_size_is_at_least_80px_and_buttons_use_it():
    target = int(re.search(r"--target:\s*(\d+)px", HTML).group(1))
    assert target >= 80
    assert re.search(r"button\s*\{[^}]*min-width:\s*var\(--target\);\s*min-height:\s*var\(--target\)", HTML)


def test_every_step_has_a_click_only_path():
    # Drag has click-to-pick/click-to-place; scroll has big Up/Down buttons (dwell-only mode).
    assert 'cauldron.addEventListener("click"' in HTML and 'stone.addEventListener("click"' in HTML
    assert "scroll-up" in HTML and "scroll-down" in HTML
    assert HTML.count('class="page"') == 7
