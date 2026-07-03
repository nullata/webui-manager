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

import os
from datetime import datetime, timedelta, timezone
from threading import Event, Lock, Thread
from typing import Iterable
from urllib.parse import urljoin

import requests
import urllib3
from sqlalchemy.exc import IntegrityError

from .models import AppSetting, HealthCheckLog, WebUI, db
from .utils import normalize_url, run_with_app_context


urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

HEALTHCHECK_TIMEOUT_SECONDS = 5
DISABLED_POLL_INTERVAL_SECONDS = 15
SUCCESS_STATUS_CODES = {401, 403}

_healthcheck_lock = Lock()


def get_app_settings() -> AppSetting:
    settings = db.session.get(AppSetting, 1)
    if settings is not None:
        return settings

    settings = AppSetting(id=1)
    db.session.add(settings)
    try:
        db.session.commit()
        return settings
    except IntegrityError:
        db.session.rollback()
        return db.session.get(AppSetting, 1)


def run_healthcheck_pass(webui_ids: Iterable[int] | None = None) -> int:
    with _healthcheck_lock:
        settings = get_app_settings()
        if not settings.healthchecks_enabled:
            return 0

        # services flagged as ignored are never checked, even if explicitly requested
        stmt = db.select(WebUI).where(WebUI.healthcheck_ignored.is_(False)).order_by(WebUI.name.asc())
        selected_ids = list(webui_ids) if webui_ids is not None else []
        if selected_ids:
            stmt = stmt.where(WebUI.id.in_(selected_ids))

        webuis = db.session.scalars(stmt).all()
        if not webuis:
            return 0

        down_webuis = []
        with requests.Session() as session:
            session.headers.update({"User-Agent": "webui-manager-healthcheck/1.0"})
            for webui in webuis:
                if _check_webui(session, webui):
                    down_webuis.append(webui)

        db.session.commit()

        if down_webuis and settings.email_notifications_enabled:
            from .notifications import send_down_alert
            send_down_alert(settings, down_webuis)

        return len(webuis)


def start_healthcheck_worker(app) -> None:
    if app.testing or app.extensions.get("healthcheck_worker_started"):
        return

    debug_enabled = app.debug or app.config.get("DEBUG") or os.environ.get("FLASK_DEBUG") == "1"
    if debug_enabled and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        return

    stop_event = Event()
    wake_event = Event()
    thread = Thread(
        target=_healthcheck_worker,
        args=(app, stop_event, wake_event),
        name="webui-healthchecks",
        daemon=True,
    )
    thread.start()

    app.extensions["healthcheck_worker_started"] = True
    app.extensions["healthcheck_worker_stop"] = stop_event
    app.extensions["healthcheck_worker_wake"] = wake_event
    app.extensions["healthcheck_worker_thread"] = thread


def notify_settings_changed(app) -> None:
    """Wake the healthcheck worker so it picks up the new interval immediately."""
    wake_event = app.extensions.get("healthcheck_worker_wake")
    if wake_event is not None:
        wake_event.set()


def trigger_healthcheck_pass_async(app) -> None:
    thread = Thread(
        target=_run_healthcheck_pass_task,
        args=(app,),
        name="webui-healthchecks-now",
        daemon=True,
    )
    thread.start()


def _healthcheck_worker(app, stop_event: Event, wake_event: Event) -> None:
    while not stop_event.is_set():
        sleep_seconds = DISABLED_POLL_INTERVAL_SECONDS

        def _work():
            nonlocal sleep_seconds
            _purge_old_logs()
            settings = get_app_settings()
            if settings.healthchecks_enabled:
                run_healthcheck_pass()
                sleep_seconds = max(60, settings.healthcheck_interval_minutes * 60)

        run_with_app_context(app, _work, "Healthcheck worker iteration failed.")
        wake_event.wait(timeout=sleep_seconds)
        wake_event.clear()


def _run_healthcheck_pass_task(app) -> None:
    run_with_app_context(app, run_healthcheck_pass, "Background healthcheck pass failed.")


def _purge_old_logs() -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    db.session.execute(db.delete(HealthCheckLog).where(HealthCheckLog.checked_at < cutoff))
    db.session.commit()


def _check_webui(session: requests.Session, webui: WebUI) -> bool:
    """Check a single WebUI and log the result. Returns True if the service newly went DOWN."""
    target_url = _healthcheck_target(webui)
    checked_at = datetime.now(timezone.utc)

    if not target_url:
        webui.last_healthcheck_at = checked_at
        webui.last_healthcheck_ok = False
        webui.last_healthcheck_status = "No URL configured"
        db.session.add(HealthCheckLog(
            webui_id=webui.id,
            checked_at=checked_at,
            is_ok=False,
            status_text="No URL configured",
        ))
        return False

    response = None
    try:
        response = session.get(
            target_url,
            timeout=HEALTHCHECK_TIMEOUT_SECONDS,
            allow_redirects=True,
            verify=False,
            stream=True,
        )
        is_ok = response.status_code < 400 or response.status_code in SUCCESS_STATUS_CODES
        webui.last_healthcheck_at = checked_at
        webui.last_healthcheck_ok = is_ok
        webui.last_healthcheck_status = f"HTTP {response.status_code}"
    except requests.RequestException as exc:
        webui.last_healthcheck_at = checked_at
        webui.last_healthcheck_ok = False
        webui.last_healthcheck_status = str(exc)[:255]
    finally:
        if response is not None:
            response.close()

    db.session.add(HealthCheckLog(
        webui_id=webui.id,
        checked_at=checked_at,
        is_ok=webui.last_healthcheck_ok,
        status_text=webui.last_healthcheck_status,
    ))

    return not webui.last_healthcheck_ok


def _healthcheck_target(webui: WebUI) -> str:
    base_url = normalize_url(webui.url)
    if webui.healthcheck_url and webui.healthcheck_url.startswith("/"):
        return urljoin(base_url, webui.healthcheck_url)
    return normalize_url(webui.healthcheck_url or base_url)
