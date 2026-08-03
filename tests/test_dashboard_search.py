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

"""Server side of the dashboard search, in both modes.

The dashboard has two search implementations that must agree: an ILIKE query
when live search is off, and a browser-side substring filter when it is on.
These tests pin the server behaviour and the data the client filter runs on;
test_browser_live_search.py drives the client half.
"""

import html as html_lib
import re

import pytest


def card_attrs(response):
    """[{search, host_id, category_ids}] for each rendered card.

    data-search is unescaped here because that is what the browser hands the
    client filter via dataset.search - comparing against the raw HTML entities
    would test something no JavaScript ever sees.
    """
    page = response.get_data(as_text=True)
    out = []
    for tag in re.findall(r'<article class="service-card[^>]*>', page):
        attrs = {}
        for attribute in ("search", "host-id", "category-ids"):
            match = re.search(rf'data-{attribute}="([^"]*)"', tag)
            attrs[attribute.replace("-", "_")] = (
                html_lib.unescape(match.group(1)) if match else None)
        out.append(attrs)
    return out


def count_cards(response):
    return len(re.findall(r'<article class="service-card', response.get_data(as_text=True)))


# --------------------------------------------------------------------------
# Live search OFF (default): the server filters
# --------------------------------------------------------------------------

def test_search_is_off_by_default(app):
    from app.healthchecks import get_app_settings

    with app.app_context():
        assert get_app_settings().live_search_enabled is False


@pytest.mark.parametrize("term, expected", [
    ("plex", 1),            # name
    ("jelly.lan", 1),       # url
    ("hypervisor", 1),      # description
    ("nas", 2),             # host name
    ("ops", 3),             # category name
    ("lan", 6),             # substring, not word match
    ("PLEX", 1),            # case-insensitive
    ("zzzz", 0),
])
def test_server_side_search_covers_all_five_fields(client, sample_catalog, term, expected):
    assert count_cards(client.get(f"/dashboard?q={term}")) == expected


def test_server_side_host_and_category_filters(client, sample_catalog, app):
    from app.models import Category, Host, db

    with app.app_context():
        nas = db.session.scalar(db.select(Host).where(Host.name == "nas")).id
        ops = db.session.scalar(db.select(Category).where(Category.name == "Ops")).id

    assert count_cards(client.get(f"/dashboard?host_id={nas}")) == 2
    assert count_cards(client.get(f"/dashboard?category_id={ops}")) == 3
    # combined, and combined with a term
    assert count_cards(client.get(f"/dashboard?category_id={ops}&q=grafana")) == 1
    assert count_cards(client.get(f"/dashboard?host_id={nas}&category_id={ops}")) == 0


def test_search_button_rendered_when_live_search_off(client, sample_catalog):
    html = client.get("/dashboard").get_data(as_text=True)
    form = html.split("</form>")[0]
    assert 'type="submit"' in form
    assert "data-live-search" not in html


# --------------------------------------------------------------------------
# Live search ON: the server must stop filtering
# --------------------------------------------------------------------------

@pytest.fixture
def live(set_settings):
    set_settings(live_search_enabled=True)


@pytest.mark.parametrize("query", [
    "q=plex", "q=zzzz", "q=nas", "host_id=1", "category_id=1", "q=plex&host_id=1",
])
def test_live_mode_returns_every_service_whatever_the_query(client, sample_catalog, live, query):
    """The client filters what it was sent, so it has to be sent everything.

    If the server also filtered, reloading a filtered URL would leave the browser
    holding only that result set - and widening the term would then return fewer
    services instead of more.
    """
    assert count_cards(client.get(f"/dashboard?{query}")) == 6


def test_live_mode_still_primes_the_form_from_the_query_string(client, sample_catalog, live, app):
    from app.models import Host, db

    with app.app_context():
        nas = db.session.scalar(db.select(Host).where(Host.name == "nas")).id

    html = client.get(f"/dashboard?q=plex&host_id={nas}").get_data(as_text=True)
    assert 'value="plex"' in html
    assert re.search(rf'<option value="{nas}" selected', html)


def test_live_mode_drops_the_search_button(client, sample_catalog, live):
    html = client.get("/dashboard").get_data(as_text=True)
    assert 'data-live-search="1"' in html
    assert 'type="submit"' not in html.split("</form>")[0]
    assert 'id="live-search-empty"' in html
    assert 'id="live-search-count"' in html


def test_toggling_the_setting_back_off_removes_the_markup(client, sample_catalog, set_settings):
    set_settings(live_search_enabled=True)
    assert "data-live-search" in client.get("/dashboard").get_data(as_text=True)
    set_settings(live_search_enabled=False)
    html = client.get("/dashboard").get_data(as_text=True)
    assert "data-live-search" not in html
    assert 'id="live-search-empty"' not in html


# --------------------------------------------------------------------------
# The two implementations must agree
# --------------------------------------------------------------------------

def test_card_haystack_holds_the_same_five_fields_the_query_searches(client, sample_catalog, live):
    attrs = card_attrs(client.get("/dashboard"))
    plex = next(a for a in attrs if "plex" in a["search"])
    for token in ("plex", "https://plex.lan", "media server", "nas", "media"):
        assert token in plex["search"], (token, plex["search"])
    assert plex["search"] == plex["search"].lower()


@pytest.mark.parametrize("term", ["plex", "nas", "ops", "lan", "hypervisor", "zzzz"])
def test_client_filter_would_match_exactly_what_the_server_returns(
        client, sample_catalog, set_settings, term):
    """Same term, same services, whichever mode is on."""
    set_settings(live_search_enabled=False)
    server_side = count_cards(client.get(f"/dashboard?q={term}"))

    set_settings(live_search_enabled=True)
    haystacks = [a["search"] for a in card_attrs(client.get("/dashboard"))]
    client_side = sum(1 for hay in haystacks if term.lower() in hay)

    assert server_side == client_side


def test_haystack_is_escaped_so_it_cannot_break_out_of_the_attribute(client, seed, live):
    seed("Quoted", "https://quoted.lan", description='say "hi" & <b>bye</b>')
    html = client.get("/dashboard").get_data(as_text=True)
    assert "&#34;hi&#34;" in html and "&lt;b&gt;" in html
    # the raw quote would have terminated data-search early
    assert 'data-search="quoted https://quoted.lan say "hi"' not in html


def test_unassigned_service_has_empty_host_and_category_attributes(client, sample_catalog, live):
    attrs = card_attrs(client.get("/dashboard"))
    orphan = next(a for a in attrs if "orphan" in a["search"])
    assert orphan["host_id"] == ""
    assert orphan["category_ids"] == ""


def test_host_count_badge_carries_its_untouched_total(client, sample_catalog, live):
    html = client.get("/dashboard").get_data(as_text=True)
    # the client rewrites the badge while filtering and restores from data-total
    assert re.search(r'class="host-count[^"]*"\s+data-total="2"', html)


def test_empty_dashboard_wording_depends_on_the_mode(client, set_settings):
    def text(response):
        # the template wraps the sentence across lines
        return " ".join(response.get_data(as_text=True).split())

    set_settings(live_search_enabled=False)
    assert "No services found for the current filters" in text(client.get("/dashboard?q=nothing"))

    # in live mode the server applied no filter, so empty means genuinely empty
    set_settings(live_search_enabled=True)
    assert "No services yet" in text(client.get("/dashboard?q=nothing"))
