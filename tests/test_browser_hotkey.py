# Copyright 2026 nullata/webui-manager
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Ctrl+K search focus, the hint that advertises it, and Escape."""

import pytest

expect = pytest.importorskip("playwright.sync_api").expect

pytestmark = pytest.mark.browser


def focused_field(page):
    return page.evaluate("() => document.activeElement && document.activeElement.name")


def test_ctrl_k_focuses_the_search_box(sample_catalog, dashboard):
    page = dashboard()
    page.click("h1")                       # start with focus elsewhere
    assert focused_field(page) != "q"

    page.keyboard.press("Control+k")
    assert focused_field(page) == "q"


def test_ctrl_k_selects_existing_text_so_typing_replaces_it(sample_catalog, dashboard):
    page = dashboard()
    page.fill('input[name="q"]', "plex")
    page.click("h1")

    page.keyboard.press("Control+k")
    page.keyboard.type("grafana")
    assert page.input_value('input[name="q"]') == "grafana"


def test_ctrl_k_works_with_live_search_off(sample_catalog, dashboard, set_settings):
    set_settings(live_search_enabled=False)
    page = dashboard()
    page.click("h1")
    page.keyboard.press("Control+k")
    assert focused_field(page) == "q"


def test_hint_is_visible_and_sits_inside_the_input(sample_catalog, dashboard):
    page = dashboard()
    hint = page.locator("#search-hotkey-hint")
    expect(hint).to_be_visible()
    assert " ".join(hint.inner_text().split()) == "Ctrl K"

    field = page.locator('input[name="q"]').bounding_box()
    badge = hint.bounding_box()
    assert field["x"] < badge["x"]
    assert badge["x"] + badge["width"] <= field["x"] + field["width"] + 1


def test_hint_is_hidden_on_a_phone_sized_viewport(sample_catalog, dashboard):
    page = dashboard()
    page.set_viewport_size({"width": 390, "height": 844})
    expect(page.locator("#search-hotkey-hint")).to_be_hidden()
    # and the panel still fits
    assert page.evaluate(
        "() => document.documentElement.scrollWidth <= document.documentElement.clientWidth")


def test_escape_clears_the_filter_then_leaves_the_field(sample_catalog, dashboard, set_settings):
    set_settings(live_search_enabled=True)
    page = dashboard()

    page.keyboard.press("Control+k")
    page.keyboard.type("plex")
    expect(page.locator(".service-card:visible")).to_have_count(1)

    page.keyboard.press("Escape")
    assert page.input_value('input[name="q"]') == ""
    # clearing must re-run the filter, not just blank the box
    expect(page.locator(".service-card:visible")).to_have_count(6)
    assert focused_field(page) == "q"

    page.keyboard.press("Escape")
    assert focused_field(page) != "q"


def test_search_panel_layout_is_unchanged_by_the_hint(sample_catalog, dashboard):
    """The input was wrapped in a positioning div to hold the badge."""
    page = dashboard()
    field = page.locator('input[name="q"]').bounding_box()
    panel = page.locator(".search-panel").bounding_box()
    # still spans two of the four columns
    assert 0.4 < field["width"] / panel["width"] < 0.6
    assert page.evaluate(
        "() => document.documentElement.scrollWidth <= document.documentElement.clientWidth")
