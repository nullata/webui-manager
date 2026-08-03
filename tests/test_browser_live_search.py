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

"""Live search in a real browser.

The server half is covered in test_dashboard_search.py; this drives the client
filter itself - card visibility, host groups, counters, URL sync and the
interaction with collapsed groups.
"""

import pytest

expect = pytest.importorskip("playwright.sync_api").expect

pytestmark = pytest.mark.browser


@pytest.fixture(autouse=True)
def live(set_settings):
    set_settings(live_search_enabled=True)


def visible_cards(page):
    return page.locator(".service-card:visible")


def visible_names(page):
    return sorted(page.locator(".service-card:visible .font-display").all_inner_texts())


def group(page, host_key):
    return page.locator(f'.host-group[data-host-key="{host_key}"]')


# --------------------------------------------------------------------------
# Filtering
# --------------------------------------------------------------------------

def test_typing_filters_without_navigating(sample_catalog, dashboard):
    page = dashboard()
    expect(visible_cards(page)).to_have_count(6)

    navigations = []
    page.on("framenavigated", lambda frame: navigations.append(frame.url))

    page.fill('input[name="q"]', "plex")
    expect(visible_cards(page)).to_have_count(1)
    assert visible_names(page) == ["Plex"]
    assert not navigations, f"page navigated while filtering: {navigations}"


@pytest.mark.parametrize("term, expected", [
    ("plex", ["Plex"]),
    ("nas", ["Jellyfin", "Plex"]),                       # host name
    ("ops", ["Grafana", "Proxmox", "Uptime Kuma"]),      # category name
    ("MEDIA", ["Jellyfin", "Plex"]),                     # case-insensitive
    ("monitoring", ["Uptime Kuma"]),                     # description
    ("kuma.lan", ["Uptime Kuma"]),                       # url
])
def test_client_filter_matches_the_same_fields_as_the_server(
        sample_catalog, dashboard, term, expected):
    page = dashboard()
    page.fill('input[name="q"]', term)
    expect(visible_cards(page)).to_have_count(len(expected))
    assert visible_names(page) == expected


def test_groups_with_no_matches_are_hidden(sample_catalog, dashboard):
    page = dashboard()
    page.fill('input[name="q"]', "plex")
    expect(group(page, "nas")).to_be_visible()
    expect(group(page, "pi")).to_be_hidden()
    expect(group(page, "arrakis")).to_be_hidden()


def test_host_count_badges_track_visible_matches_and_restore(sample_catalog, dashboard):
    page = dashboard()
    badge = group(page, "nas").locator(".host-count")
    expect(badge).to_have_text("2")

    page.fill('input[name="q"]', "plex")
    expect(badge).to_have_text("1")

    page.fill('input[name="q"]', "")
    expect(badge).to_have_text("2")


def test_counter_appears_only_while_filtering(sample_catalog, dashboard):
    page = dashboard()
    counter = page.locator("#live-search-count")
    expect(counter).to_be_hidden()

    page.fill('input[name="q"]', "plex")
    expect(counter).to_be_visible()
    expect(counter).to_have_text("1 of 6 services")

    page.fill('input[name="q"]', "")
    expect(counter).to_be_hidden()


def test_empty_state_when_nothing_matches(sample_catalog, dashboard):
    page = dashboard()
    page.fill('input[name="q"]', "zzzzz")
    expect(visible_cards(page)).to_have_count(0)
    expect(page.locator("#live-search-empty")).to_be_visible()

    page.fill('input[name="q"]', "plex")
    expect(page.locator("#live-search-empty")).to_be_hidden()


def test_dropdowns_filter_and_combine_with_the_term(sample_catalog, dashboard):
    page = dashboard()

    page.select_option('select[name="host_id"]', label="pi")
    expect(visible_cards(page)).to_have_count(2)
    assert visible_names(page) == ["Grafana", "Uptime Kuma"]

    page.select_option('select[name="host_id"]', "")
    page.select_option('select[name="category_id"]', label="Media")
    assert visible_names(page) == ["Jellyfin", "Plex"]

    page.fill('input[name="q"]', "plex")
    expect(visible_cards(page)).to_have_count(1)
    assert visible_names(page) == ["Plex"]


def test_no_submit_button_and_enter_does_not_reload(sample_catalog, dashboard):
    page = dashboard()
    assert page.locator('#search-form button[type="submit"]').count() == 0

    page.fill('input[name="q"]', "plex")
    navigations = []
    page.on("framenavigated", lambda frame: navigations.append(frame.url))
    page.press('input[name="q"]', "Enter")
    page.wait_for_timeout(200)
    assert not navigations, f"Enter submitted the form: {navigations}"


def test_reset_clears_everything_in_place(sample_catalog, dashboard):
    page = dashboard()
    page.fill('input[name="q"]', "plex")
    page.select_option('select[name="category_id"]', label="Media")
    expect(visible_cards(page)).to_have_count(1)

    page.click("#search-reset-btn")
    expect(visible_cards(page)).to_have_count(6)
    assert page.input_value('input[name="q"]') == ""
    assert page.input_value('select[name="category_id"]') == ""


# --------------------------------------------------------------------------
# URL sync
# --------------------------------------------------------------------------

def test_filter_is_written_to_the_url(sample_catalog, dashboard, live_server):
    page = dashboard()
    page.fill('input[name="q"]', "grafana")
    page.wait_for_url(f"{live_server.base_url}/dashboard?q=grafana")


def test_reset_clears_the_url(sample_catalog, dashboard, live_server):
    page = dashboard()
    page.fill('input[name="q"]', "grafana")
    page.wait_for_url(f"{live_server.base_url}/dashboard?q=grafana")
    page.click("#search-reset-btn")
    page.wait_for_url(f"{live_server.base_url}/dashboard")


def test_reloading_a_filtered_url_keeps_every_card_available(sample_catalog, dashboard):
    """The regression that made the server stop filtering in live mode.

    A reload used to leave the browser holding only the previous result set, so
    widening the term returned *fewer* services instead of more.
    """
    page = dashboard("?q=kuma")
    expect(visible_cards(page)).to_have_count(1)
    assert page.input_value('input[name="q"]') == "kuma"
    # the counter proves all six are present client-side, not just the match
    expect(page.locator("#live-search-count")).to_have_text("1 of 6 services")

    page.fill('input[name="q"]', "media")
    expect(visible_cards(page)).to_have_count(2)
    assert visible_names(page) == ["Jellyfin", "Plex"]


# --------------------------------------------------------------------------
# Collapsed host groups
# --------------------------------------------------------------------------

def test_search_opens_a_collapsed_group_holding_a_match(sample_catalog, dashboard):
    page = dashboard()
    page.click('.host-group[data-host-key="nas"] .host-toggle')
    expect(visible_cards(page)).to_have_count(4)

    page.fill('input[name="q"]', "plex")
    expect(visible_cards(page)).to_have_count(1)
    assert visible_names(page) == ["Plex"]


def test_collapsing_mid_search_survives_the_next_keystroke(sample_catalog, dashboard):
    page = dashboard()
    page.fill('input[name="q"]', "plex")
    expect(visible_cards(page)).to_have_count(1)

    page.click('.host-group[data-host-key="nas"] .host-toggle')
    # 'server' matches only Plex's description, and nas is now collapsed
    page.fill('input[name="q"]', "server")
    expect(visible_cards(page)).to_have_count(0)


def test_group_that_gains_matches_later_opens(sample_catalog, dashboard):
    page = dashboard()
    page.click('.host-group[data-host-key="pi"] .host-toggle')

    page.fill('input[name="q"]', "plex")
    expect(visible_cards(page)).to_have_count(1)
    page.fill('input[name="q"]', "grafana")
    expect(visible_cards(page)).to_have_count(1)
    assert visible_names(page) == ["Grafana"]


def test_clearing_the_filter_restores_the_collapse_the_user_chose(sample_catalog, dashboard):
    page = dashboard()
    page.click('.host-group[data-host-key="pi"] .host-toggle')

    page.fill('input[name="q"]', "grafana")
    expect(visible_cards(page)).to_have_count(1)

    page.fill('input[name="q"]', "")
    # pi goes back to collapsed: 6 services minus the 2 on pi
    expect(visible_cards(page)).to_have_count(4)
