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

from threading import Thread

from .models import WebUI, db
from .utils import normalize_url, resolve_favicon, run_with_app_context


def trigger_favicon_refresh_async(app, webui_id: int, site_url: str) -> None:
    thread = Thread(
        target=_refresh_favicon_task,
        args=(app, webui_id, site_url),
        name=f"webui-favicon-{webui_id}",
        daemon=True,
    )
    thread.start()


def trigger_favicon_backfill_async(app, webui_ids: list[int]) -> None:
    """Resolve favicons for a batch of services on a single background thread.

    An import can create dozens of services at once; calling
    trigger_favicon_refresh_async per service would start that many threads and
    fire the same number of simultaneous outbound requests. This walks the list
    in order instead, one request at a time."""
    if not webui_ids:
        return

    thread = Thread(
        target=_backfill_favicons_task,
        args=(app, list(webui_ids)),
        name="webui-favicon-backfill",
        daemon=True,
    )
    thread.start()


def _backfill_favicons_task(app, webui_ids: list[int]) -> None:
    def _work():
        for webui_id in webui_ids:
            webui = db.session.get(WebUI, webui_id)
            # Skip anything deleted, re-pointed or already resolved since the
            # import - and keep going if one service is unreachable, so a single
            # bad URL can't abandon the rest of the batch.
            if webui is None or not webui.url or webui.favicon_url:
                continue
            try:
                favicon_url = resolve_favicon(webui.url)
            except Exception:
                app.logger.exception("Favicon backfill failed for webui %s", webui_id)
                continue
            if favicon_url:
                webui.favicon_url = favicon_url
                db.session.commit()

    run_with_app_context(app, _work, "Background favicon backfill failed.")


def _refresh_favicon_task(app, webui_id: int, site_url: str) -> None:
    def _work():
        favicon_url = resolve_favicon(site_url)
        webui = db.session.get(WebUI, webui_id)
        if webui is None:
            return

        # Don't overwrite if the record changed after this task was queued.
        if normalize_url(webui.url) != normalize_url(site_url):
            return

        webui.favicon_url = favicon_url
        db.session.commit()

    run_with_app_context(app, _work, "Background favicon refresh failed.")
