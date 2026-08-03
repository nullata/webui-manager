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

"""JSON export and import of the service catalog."""

import html as html_lib
import io
import json
import re

import pytest


def flashes(response):
    return [html_lib.unescape(message) for message in re.findall(
        r'<span class="flex-1">([^<]*)</span>', response.get_data(as_text=True))]


def do_import(client, payload, filename="import.json"):
    if isinstance(payload, bytes):
        body = payload
    else:
        body = json.dumps(payload).encode()
    return client.post(
        "/services/import",
        data={"import_file": (io.BytesIO(body), filename)},
        content_type="multipart/form-data",
        follow_redirects=True,
    )


def export(client, include_passwords=False):
    data = {"include_passwords": "1"} if include_passwords else {}
    response = client.post("/services/export", data=data)
    assert response.status_code == 200
    return response


@pytest.fixture
def catalog(seed):
    seed("Plex", "https://plex.lan", host="nas", categories=["Media"],
         description="Media server", credential_username="admin", password="s3cret",
         favicon_url="data:image/png;base64,AAAA", healthcheck_url="/health")
    seed("Grafana", "https://grafana.lan", host="pi", categories=["Ops"])


# --------------------------------------------------------------------------
# Export
# --------------------------------------------------------------------------

def test_export_is_a_json_download(client, catalog):
    response = export(client)
    assert response.mimetype == "application/json"
    disposition = response.headers["Content-Disposition"]
    assert disposition.startswith('attachment; filename="webui-manager-export-')
    assert disposition.endswith('.json"')


def test_export_carries_services_hosts_categories_and_favicons(client, catalog):
    payload = export(client).get_json()
    assert payload["version"] == 1
    assert {h["name"] for h in payload["hosts"]} == {"nas", "pi"}
    assert {c["name"] for c in payload["categories"]} == {"Media", "Ops"}

    plex = next(s for s in payload["services"] if s["name"] == "Plex")
    assert plex["host"] == "nas"
    assert plex["categories"] == ["Media"]
    assert plex["url"] == "https://plex.lan"
    assert plex["healthcheck_url"] == "/health"
    # favicons are self-contained data: URIs, so a restore looks right at once
    assert plex["favicon_url"] == "data:image/png;base64,AAAA"


def test_export_omits_passwords_by_default(client, catalog):
    payload = export(client).get_json()
    assert payload["includes_passwords"] is False
    for service in payload["services"]:
        assert "credential_password" not in service
    # the username is not a secret and is still exported
    plex = next(s for s in payload["services"] if s["name"] == "Plex")
    assert plex["credential_username"] == "admin"


def test_export_includes_plaintext_passwords_only_when_asked(client, catalog):
    payload = export(client, include_passwords=True).get_json()
    assert payload["includes_passwords"] is True
    plex = next(s for s in payload["services"] if s["name"] == "Plex")
    # the stored ciphertext is keyed to this install, so it is plaintext or nothing
    assert plex["credential_password"] == "s3cret"


def test_export_blanks_passwords_it_cannot_decrypt(client, seed):
    seed("Broken", "https://broken.lan", credential_username="admin",
         credential_password_encrypted="gAAAAABm-not-valid")
    payload = export(client, include_passwords=True).get_json()
    assert payload["services"][0]["credential_password"] == ""


def test_export_requires_a_session(anon_client):
    response = anon_client.post("/services/export")
    assert response.status_code in (301, 302)


# --------------------------------------------------------------------------
# Import
# --------------------------------------------------------------------------

def test_reimporting_an_export_changes_nothing(client, catalog, app):
    from app.models import WebUI, db

    payload = export(client).get_json()
    messages = flashes(do_import(client, payload))
    assert any("0 imported" in m and "2 skipped" in m for m in messages), messages
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count()).select_from(WebUI)) == 2


def test_import_creates_services_with_missing_hosts_and_categories(client, app):
    from app.models import Category, Host, WebUI, db
    from app.utils import decrypt_secret

    response = do_import(client, {
        "hosts": [{"name": "pi", "description": "little one"}],
        "services": [{
            "name": "Sonarr", "url": "https://sonarr.lan", "host": "pi",
            "categories": ["Media", "Arr"], "description": "tv",
            "credential_username": "u", "credential_password": "p",
        }],
    })
    assert any("1 imported" in m for m in flashes(response)), flashes(response)

    with app.app_context():
        sonarr = db.session.scalar(db.select(WebUI).where(WebUI.name == "Sonarr"))
        assert sonarr.host.name == "pi"
        assert sorted(c.name for c in sonarr.categories) == ["Arr", "Media"]
        assert decrypt_secret(sonarr.credential_password_encrypted) == "p"
        # description comes from the envelope, not the bare name reference
        assert db.session.scalar(
            db.select(Host).where(Host.name == "pi")).description == "little one"
        assert db.session.scalar(db.select(Category).where(Category.name == "Arr")) is not None


def test_import_normalizes_urls_the_same_way_the_form_does(client, app):
    from app.models import WebUI, db

    do_import(client, [{"name": "Radarr", "url": "radarr.lan"}])
    with app.app_context():
        assert db.session.scalar(
            db.select(WebUI).where(WebUI.name == "Radarr")).url == "http://radarr.lan"


def test_import_accepts_a_bare_list(client):
    response = do_import(client, [{"name": "Bare", "url": "https://bare.lan"}])
    assert any("1 imported" in m for m in flashes(response)), flashes(response)


def test_import_skips_urls_that_already_exist(client, seed):
    seed("Existing", "https://dup.lan")
    response = do_import(client, [
        {"name": "Different name, same url", "url": "https://dup.lan"},
        {"name": "New", "url": "https://new.lan"},
    ])
    messages = flashes(response)
    assert any("1 imported" in m and "1 skipped" in m for m in messages), messages


def test_duplicate_urls_within_one_file_collapse(client, app):
    from app.models import WebUI, db

    response = do_import(client, [
        {"name": "Dup A", "url": "https://dup.lan"},
        {"name": "Dup B", "url": "https://dup.lan"},
    ])
    assert any("1 imported" in m and "1 skipped" in m for m in flashes(response))
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count()).select_from(WebUI)
                                 .where(WebUI.url == "https://dup.lan")) == 1


def test_unusable_rows_are_counted_not_fatal(client, app):
    from app.models import WebUI, db

    response = do_import(client, [
        {"name": "", "url": "https://noname.lan"},   # no name
        {"name": "NoUrl"},                            # no url
        "not an object",                              # wrong type
        {"name": "Fine", "url": "https://fine.lan"},
    ])
    messages = flashes(response)
    assert any("1 imported" in m and "3 unusable" in m for m in messages), messages
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count()).select_from(WebUI)) == 1


def test_import_defaults_an_unknown_service_type_to_web(client, app):
    from app.models import WebUI, db

    do_import(client, [{"name": "Odd", "url": "https://odd.lan", "service_type": "banana"}])
    with app.app_context():
        assert db.session.scalar(db.select(WebUI).where(WebUI.name == "Odd")).service_type == "web"


@pytest.mark.parametrize("payload, expected", [
    (b"not json at all", "isn't valid JSON"),
    ({"nope": 1}, "No services found"),
    ([], "no services to import"),
])
def test_import_rejects_junk_with_a_readable_message(client, payload, expected):
    assert any(expected in m for m in flashes(do_import(client, payload)))


def test_import_without_a_file(client):
    response = client.post("/services/import", data={}, follow_redirects=True)
    assert any("Choose a JSON file" in m for m in flashes(response))


def test_import_rejects_oversize_files(client):
    response = do_import(client, b"x" * (5 * 1024 * 1024 + 10))
    assert any("5 MB or smaller" in m for m in flashes(response))


def test_import_requires_a_session(anon_client):
    response = anon_client.post("/services/import", data={})
    assert response.status_code in (301, 302)


def test_full_round_trip_preserves_the_catalog(client, catalog, app):
    """Export everything, wipe, import it back, and compare."""
    from app.models import WebUI, db

    payload = export(client, include_passwords=True).get_json()

    with app.app_context():
        # Delete through the ORM, not db.delete(WebUI): a bulk delete skips the
        # cascade and strands rows in webui_categories, which the re-imported
        # services then inherit through recycled SQLite rowids.
        for webui in db.session.scalars(db.select(WebUI)).all():
            db.session.delete(webui)
        db.session.commit()

    do_import(client, payload)

    with app.app_context():
        restored = {
            w.name: (w.url, w.host.name if w.host else None,
                     sorted(c.name for c in w.categories), w.favicon_url,
                     w.credential_username)
            for w in db.session.scalars(db.select(WebUI)).all()
        }
    assert restored == {
        "Plex": ("https://plex.lan", "nas", ["Media"], "data:image/png;base64,AAAA", "admin"),
        "Grafana": ("https://grafana.lan", "pi", ["Ops"], None, ""),
    }
