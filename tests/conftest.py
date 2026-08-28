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

"""Shared fixtures.

app/config.py resolves the database URL from the environment at *import* time,
so DB_TYPE/DB_PATH must be set before anything imports the app. conftest is
loaded before any test module, and these assignments run at import, so this is
the one place it can be done - do not move them into a fixture.
"""

import os
import socket
import tempfile
import threading

import pytest

_TMP_DIR = tempfile.mkdtemp(prefix="webui-manager-tests-")

os.environ["DB_TYPE"] = "sqlite"
os.environ["DB_PATH"] = os.path.join(_TMP_DIR, "test.sqlite")
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ["AUTO_MIGRATE"] = "true"
# Keep a rotated SECRET_KEY from being a silent variable in credential tests.
os.environ.pop("APP_CREDENTIALS_KEY", None)

# Optional: point the suite at a real PostgreSQL. Setting POSTGRES_TEST_URL
# maps it onto DATABASE_URL, which the config honours ahead of the DB_* vars,
# so the engine (and therefore the auto-migrator's dialect) becomes Postgres.
# Select only these tests with `pytest -m postgres`.
_pg_url = os.environ.get("POSTGRES_TEST_URL")
if _pg_url:
    os.environ["DATABASE_URL"] = _pg_url

from app import create_app  # noqa: E402
from app.models import Category, Host, User, WebUI, db  # noqa: E402

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "test-password"


# --------------------------------------------------------------------------
# App / database
# --------------------------------------------------------------------------

@pytest.fixture(scope="session")
def app():
    """One app for the whole session; tables are reset per test below.

    TESTING keeps the healthcheck worker from starting, and CSRF is disabled so
    tests can post forms without scraping a token out of every page.
    """
    application = create_app()
    application.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    return application


@pytest.fixture(autouse=True)
def clean_db(app):
    """Give every test an empty schema, so ordering never matters."""
    with app.app_context():
        db.drop_all()
        db.create_all()
    yield
    with app.app_context():
        db.session.remove()


@pytest.fixture
def admin(app):
    with app.app_context():
        user = User(username=ADMIN_USERNAME)
        user.set_password(ADMIN_PASSWORD)
        db.session.add(user)
        db.session.commit()
        return user.id


@pytest.fixture
def client(app, admin):
    """Test client already logged in as the admin user."""
    test_client = app.test_client()
    response = test_client.post(
        "/login",
        data={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
        follow_redirects=True,
    )
    assert response.status_code == 200
    return test_client


@pytest.fixture
def anon_client(app):
    return app.test_client()


# --------------------------------------------------------------------------
# Seeding
# --------------------------------------------------------------------------

@pytest.fixture
def seed(app):
    """Create services (plus hosts/categories by name) and return their ids.

        seed(name="Plex", url="https://plex.example", host="nas",
             categories=["Media"], password="hunter2")
    """
    def _seed(name, url=None, host=None, categories=(), password=None, **fields):
        from app.utils import encrypt_secret

        with app.app_context():
            host_row = None
            if host:
                host_row = db.session.scalar(db.select(Host).where(Host.name == host))
                if host_row is None:
                    host_row = Host(name=host)
                    db.session.add(host_row)

            category_rows = []
            for category_name in categories:
                row = db.session.scalar(
                    db.select(Category).where(Category.name == category_name))
                if row is None:
                    row = Category(name=category_name)
                    db.session.add(row)
                category_rows.append(row)

            if password is not None:
                fields["credential_password_encrypted"] = encrypt_secret(password)

            webui = WebUI(name=name, url=url, host=host_row,
                          categories=category_rows, **fields)
            db.session.add(webui)
            db.session.commit()
            return webui.id

    return _seed


@pytest.fixture
def sample_catalog(seed):
    """A small, fixed catalog several tests share.

    Note the URLs: every host name, category name and description is chosen so
    no search term in the tests accidentally matches a different card. (An
    earlier version used *.example everywhere, and "ple" silently matched all
    six services via "example".)
    """
    return {
        "Plex": seed("Plex", "https://plex.lan", host="nas", categories=["Media"],
                     description="Media server"),
        "Jellyfin": seed("Jellyfin", "https://jelly.lan", host="nas", categories=["Media"],
                         description="Also media"),
        "Grafana": seed("Grafana", "https://grafana.lan", host="pi", categories=["Ops"],
                        description="Dashboards"),
        "Uptime Kuma": seed("Uptime Kuma", "https://kuma.lan", host="pi", categories=["Ops"],
                            description="Monitoring"),
        "Proxmox": seed("Proxmox", "https://pve.lan", host="arrakis", categories=["Ops"],
                        description="Hypervisor"),
        "Orphan Tool": seed("Orphan Tool", "https://orphan.lan", description="No host"),
    }


@pytest.fixture(autouse=True)
def no_background_favicons(monkeypatch, request):
    """Keep imports from firing real favicon fetches at made-up hostnames.

    The backfill thread outlives the test that started it: it would hit the
    network once per imported service and then write to tables clean_db has
    already dropped. Tests that want the real thing carry the
    `real_favicon_backfill` marker.
    """
    if "real_favicon_backfill" in request.keywords:
        return
    import app.routes

    monkeypatch.setattr(app.routes, "trigger_favicon_backfill_async",
                        lambda *args, **kwargs: None)


@pytest.fixture
def set_settings(app):
    """Flip AppSetting fields, e.g. set_settings(live_search_enabled=True)."""
    def _set(**values):
        from app.healthchecks import get_app_settings

        with app.app_context():
            settings = get_app_settings()
            for key, value in values.items():
                assert hasattr(settings, key), f"AppSetting has no field {key!r}"
                setattr(settings, key, value)
            db.session.commit()

    return _set


# --------------------------------------------------------------------------
# Live server + browser (only used by the browser tests)
# --------------------------------------------------------------------------

def _lan_address():
    """A non-loopback IPv4 address, or None.

    Browsers treat localhost/127.0.0.1 as a *potentially trustworthy* origin, so
    window.isSecureContext is true there and navigator.clipboard exists. Reaching
    the same server over a LAN address is the only way to exercise the plain-HTTP
    path that most self-hosted installs actually run on.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("10.255.255.255", 1))
        address = probe.getsockname()[0]
    except OSError:
        return None
    finally:
        probe.close()
    return None if address.startswith("127.") else address


@pytest.fixture(scope="session")
def live_server(app):
    """Serve the app on a real port for the browser tests.

    Bound to 0.0.0.0 rather than localhost so the same server is reachable over
    a LAN address - see _lan_address above.
    """
    from werkzeug.serving import make_server

    server = make_server("0.0.0.0", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    port = server.server_port
    lan = _lan_address()

    class LiveServer:
        base_url = f"http://127.0.0.1:{port}"
        lan_url = f"http://{lan}:{port}" if lan else None

    try:
        yield LiveServer()
    finally:
        server.shutdown()
        thread.join(timeout=5)


@pytest.fixture(scope="session")
def browser():
    playwright = pytest.importorskip(
        "playwright.sync_api", reason="playwright is not installed")
    with playwright.sync_playwright() as driver:
        instance = driver.chromium.launch()
        yield instance
        instance.close()


def login_page(browser, base_url, permissions=()):
    """New browser page, logged in, sitting on the dashboard."""
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    if permissions:
        context.grant_permissions(list(permissions), origin=base_url)
    page = context.new_page()
    page.goto(f"{base_url}/login")
    page.fill('input[name="username"]', ADMIN_USERNAME)
    page.fill('input[name="password"]', ADMIN_PASSWORD)
    page.click('button[type="submit"]')
    page.wait_for_url("**/dashboard")
    return context, page


def _watch_for_errors(page):
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console",
            lambda m: errors.append(f"console: {m.text}") if m.type == "error" else None)
    return errors


@pytest.fixture
def page(browser, live_server, admin):
    """Logged-in page on the loopback (secure-context) origin.

    Headless Chromium denies clipboard-write by default; a real browser
    auto-grants it on a user gesture, so granting it here removes a test-harness
    artefact rather than papering over anything. The insecure_page fixture
    deliberately grants nothing - navigator.clipboard doesn't exist there.
    """
    context, active_page = login_page(
        browser, live_server.base_url, permissions=["clipboard-write"])
    errors = _watch_for_errors(active_page)
    yield active_page
    context.close()
    assert not errors, f"JavaScript errors on the page: {errors}"


@pytest.fixture
def insecure_page(browser, live_server, admin):
    """Logged-in page reached over a LAN address, where isSecureContext is false.

    navigator.clipboard does not exist on such an origin, which is how most
    self-hosted installs are actually served, so this is the only way to prove
    the copy fallback works rather than assuming it.
    """
    if live_server.lan_url is None:
        pytest.skip("no non-loopback address available on this machine")

    context, active_page = login_page(browser, live_server.lan_url)
    errors = _watch_for_errors(active_page)
    yield active_page
    context.close()
    assert not errors, f"JavaScript errors on the page: {errors}"


@pytest.fixture
def dashboard(page, live_server):
    """Open the dashboard *after* the test's fixtures have seeded their data.

    Navigating inside the test body rather than at fixture setup keeps this
    independent of the order pytest happens to build fixtures in.
    """
    def _open(query=""):
        page.goto(f"{live_server.base_url}/dashboard{query}")
        return page

    return _open
