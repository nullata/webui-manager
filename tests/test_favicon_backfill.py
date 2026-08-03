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

"""The post-import favicon backfill.

Everywhere else the backfill is stubbed out (see no_background_favicons in
conftest); these tests let the real thing run and point it at the live server,
which serves its own /favicon.ico.
"""

import io
import json
import time

import pytest

pytestmark = pytest.mark.real_favicon_backfill


def wait_for_favicons(app, timeout=20):
    """The backfill is a daemon thread, so poll rather than guess a sleep."""
    from app.models import WebUI, db

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with app.app_context():
            found = {w.name: w.favicon_url
                     for w in db.session.scalars(db.select(WebUI)).all()}
        if all(value is not None for value in found.values()):
            return found
        time.sleep(0.25)
    return found


def test_import_backfills_favicons_and_survives_an_unreachable_service(
        client, app, live_server):
    """One bad URL must not abandon the rest of the batch.

    The whole batch shares a single thread, so an unhandled error on any one
    service would take the others with it.
    """
    from app.models import WebUI, db

    payload = json.dumps([
        {"name": "Reachable", "url": live_server.base_url},
        # nothing listens on port 1
        {"name": "Unreachable", "url": "http://127.0.0.1:1/nope"},
    ]).encode()

    response = client.post(
        "/services/import",
        data={"import_file": (io.BytesIO(payload), "import.json")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert response.status_code == 200

    deadline = time.monotonic() + 20
    reachable = None
    while time.monotonic() < deadline:
        with app.app_context():
            reachable = db.session.scalar(
                db.select(WebUI).where(WebUI.name == "Reachable")).favicon_url
        if reachable:
            break
        time.sleep(0.25)

    assert reachable and reachable.startswith("data:image/"), reachable

    with app.app_context():
        unreachable = db.session.scalar(
            db.select(WebUI).where(WebUI.name == "Unreachable"))
        assert unreachable.favicon_url is None


def test_backfill_leaves_an_existing_favicon_alone(app, seed, live_server):
    """Imported records that already carry a favicon are skipped."""
    from app.favicons import trigger_favicon_backfill_async
    from app.models import WebUI, db

    webui_id = seed("HasIcon", live_server.base_url,
                    favicon_url="data:image/png;base64,ALREADYHERE")

    trigger_favicon_backfill_async(app, [webui_id])
    time.sleep(1.5)

    with app.app_context():
        assert db.session.get(WebUI, webui_id).favicon_url == \
            "data:image/png;base64,ALREADYHERE"


def test_backfill_with_an_empty_list_does_nothing(app):
    from app.favicons import trigger_favicon_backfill_async

    trigger_favicon_backfill_async(app, [])   # must not raise or start a thread
