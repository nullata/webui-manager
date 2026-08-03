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

"""Credentials panel: copy, reveal, and the decrypt-failure message."""

import pytest

expect = pytest.importorskip("playwright.sync_api").expect

pytestmark = pytest.mark.browser

MASK = "•" * 8
UNDECRYPTABLE = "gAAAAABm-this-is-not-a-valid-fernet-token"


@pytest.fixture
def catalog(seed):
    seed("Plex", "https://plex.lan", host="nas",
         credential_username="plexuser", password="hunter2")
    seed("Broken", "https://broken.lan", host="nas",
         credential_username="admin", credential_password_encrypted=UNDECRYPTABLE)
    seed("UserOnly", "https://useronly.lan", host="nas", credential_username="justme")


def card(page, name):
    return page.locator(".service-card", has=page.locator(f'.font-display:text-is("{name}")'))


def open_credentials(page, name):
    """Cards reveal their body on hover, so hold the pointer over it."""
    service = card(page, name)
    service.hover()
    service.locator(".credentials-btn").click()
    expect(service.locator(".credentials-panel")).to_be_visible()
    return service


def read_clipboard(page):
    """Paste into a scratch field - the only way to read the clipboard back
    without granting clipboard-read permission (which does not exist at all on
    an insecure origin)."""
    page.evaluate("""() => {
        const input = document.createElement('input');
        input.id = 'clipboard-probe';
        document.body.appendChild(input);
        input.focus();
    }""")
    page.keyboard.press("Control+v")
    value = page.input_value("#clipboard-probe")
    page.evaluate("() => document.getElementById('clipboard-probe').remove()")
    return value


# --------------------------------------------------------------------------
# Copy without revealing
# --------------------------------------------------------------------------

def test_copy_puts_the_password_on_the_clipboard_without_revealing_it(catalog, dashboard):
    page = dashboard()
    plex = open_credentials(page, "Plex")

    expect(plex.locator(".credentials-password")).to_have_text(MASK)
    plex.locator(".copy-password-btn").click()

    # the whole point: it never became visible on screen
    expect(plex.locator(".credentials-password")).to_have_text(MASK)
    expect(plex.locator(".copy-password-btn .fa-check")).to_have_count(1)
    assert read_clipboard(page) == "hunter2"


def test_copy_button_returns_to_its_normal_icon(catalog, dashboard):
    page = dashboard()
    plex = open_credentials(page, "Plex")
    plex.locator(".copy-password-btn").click()
    expect(plex.locator(".copy-password-btn .fa-check")).to_have_count(1)
    # the tick is temporary
    expect(plex.locator(".copy-password-btn .fa-copy")).to_have_count(1, timeout=3000)


def test_reveal_still_works_alongside_copy(catalog, dashboard):
    page = dashboard()
    plex = open_credentials(page, "Plex")
    password = plex.locator(".credentials-password")

    plex.locator(".toggle-password-btn").click()
    expect(password).to_have_text("hunter2")
    plex.locator(".toggle-password-btn").click()
    expect(password).to_have_text(MASK)


def test_username_is_shown(catalog, dashboard):
    page = dashboard()
    plex = open_credentials(page, "Plex")
    expect(plex.locator(".credentials-username")).to_have_text("plexuser")


def test_copy_works_before_the_fetch_has_resolved(catalog, dashboard):
    """Clicking copy the instant the panel opens must not race the request."""
    page = dashboard()
    service = card(page, "Plex")
    service.hover()
    service.locator(".credentials-btn").click()
    service.locator(".copy-password-btn").click()   # no wait in between
    expect(service.locator(".copy-password-btn .fa-check")).to_have_count(1)
    assert read_clipboard(page) == "hunter2"


# --------------------------------------------------------------------------
# The plain-HTTP origin most installs actually run on
# --------------------------------------------------------------------------

def test_copy_falls_back_on_an_insecure_origin(catalog, insecure_page, live_server):
    """navigator.clipboard does not exist off a secure context.

    Without the execCommand fallback the copy button is simply dead on a LAN
    address, which is where most of these dashboards live.
    """
    page = insecure_page
    page.goto(f"{live_server.lan_url}/dashboard")

    assert page.evaluate("() => window.isSecureContext") is False
    assert page.evaluate("() => !navigator.clipboard") is True

    plex = open_credentials(page, "Plex")
    plex.locator(".copy-password-btn").click()

    expect(plex.locator(".copy-password-btn .fa-check")).to_have_count(1)
    expect(plex.locator(".credentials-password")).to_have_text(MASK)
    assert read_clipboard(page) == "hunter2"


# --------------------------------------------------------------------------
# Decrypt failure
# --------------------------------------------------------------------------

def test_undecryptable_password_explains_itself(catalog, dashboard):
    page = dashboard()
    broken = open_credentials(page, "Broken")

    error = broken.locator(".credentials-error")
    expect(error).to_be_visible()
    assert "SECRET_KEY" in error.inner_text()
    # nothing to reveal or copy, so neither button is offered
    expect(broken.locator(".toggle-password-btn")).to_be_hidden()
    expect(broken.locator(".copy-password-btn")).to_be_hidden()
    expect(broken.locator(".credentials-username")).to_have_text("admin")


def test_service_with_no_stored_password_is_not_treated_as_an_error(catalog, dashboard):
    page = dashboard()
    user_only = open_credentials(page, "UserOnly")

    expect(user_only.locator(".credentials-error")).to_be_hidden()
    expect(user_only.locator(".toggle-password-btn")).to_be_hidden()
    expect(user_only.locator(".copy-password-btn")).to_be_hidden()
    expect(user_only.locator(".credentials-username")).to_have_text("justme")
