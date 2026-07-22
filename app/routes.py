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
from urllib.parse import urlparse

from werkzeug.utils import secure_filename

_ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}
_MAX_BG_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MB

# magic byte signatures for each allowed image type
_IMAGE_MAGIC: list[tuple[int, bytes]] = [
    (0, b"\xff\xd8\xff"),           # JPEG
    (0, b"\x89PNG\r\n\x1a\n"),      # PNG
    (0, b"GIF87a"),                 # GIF87a
    (0, b"GIF89a"),                 # GIF89a
    (8, b"WEBP"),                   # WebP (RIFF....WEBP)
    (4, b"ftyp"),                   # AVIF / HEIF (ISO base media)
]


def _is_valid_image(stream) -> bool:
    header = stream.read(12)
    stream.seek(0)
    return any(header[offset:offset + len(sig)] == sig for offset, sig in _IMAGE_MAGIC)


def _uploads_dir() -> str:
    from flask import current_app
    path = os.path.join(current_app.static_folder, "uploads")
    os.makedirs(path, exist_ok=True)
    return path

from flask import Blueprint, current_app, flash, g, redirect, render_template, request, url_for, jsonify
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from .auth import login_required
from .favicons import trigger_favicon_refresh_async
from .healthchecks import get_app_settings, notify_settings_changed, trigger_healthcheck_pass_async
from .models import Category, HealthCheckLog, Host, User, WebUI, db

_SERVICE_TYPE_LABELS = {
    "web": "Web UI",
    "api": "API",
}
from .utils import decrypt_secret, encrypt_secret, normalize_url


main_bp = Blueprint("main", __name__)


@main_bp.before_request
def _load_settings() -> None:
    g.app_settings = get_app_settings()


@main_bp.route("/")
def index():
    # root just figures out where to send the user - setup, dashboard, or login
    if db.session.scalar(db.select(func.count()).select_from(User)) == 0:
        return redirect(url_for("auth.setup_admin"))
    if g.get("user"):
        return redirect(url_for("main.webui_list"))
    return redirect(url_for("auth.login"))


@main_bp.route("/dashboard")
@login_required
def webui_list():
    settings = g.app_settings
    q = (request.args.get("q") or "").strip()
    host_id = request.args.get("host_id", type=int)
    category_id = request.args.get("category_id", type=int)

    # eager load host and categories so we dont get n+1 queries when rendering cards
    stmt = db.select(WebUI).options(joinedload(
        WebUI.host), joinedload(WebUI.categories))
    # track whether we already joined categories so we dont do it twice
    categories_joined = False

    if q:
        like = f"%{q}%"
        # search across name, url, description, host name, and category name
        stmt = (
            stmt.outerjoin(WebUI.host)
            .outerjoin(WebUI.categories)
            .where(
                or_(
                    WebUI.name.ilike(like),
                    WebUI.url.ilike(like),
                    WebUI.description.ilike(like),
                    Host.name.ilike(like),
                    Category.name.ilike(like),
                )
            )
            .distinct()
        )
        categories_joined = True

    if host_id:
        stmt = stmt.where(WebUI.host_id == host_id)

    if category_id:
        # only join categories if the search didnt already do it
        if not categories_joined:
            stmt = stmt.join(WebUI.categories)
        stmt = stmt.where(Category.id == category_id)

    # unique is required when using joinedload with scalars - prevents duplicates from the join
    webuis = db.session.scalars(stmt.order_by(WebUI.name.asc())).unique().all()

    # group by host name, sort alpha, unassigned services go at the end
    grouped = {}
    for w in webuis:
        key = w.host.name if w.host else None
        grouped.setdefault(key, []).append(w)

    host_names = sorted(k for k in grouped if k is not None)
    groups = [(name, grouped[name]) for name in host_names]
    if None in grouped:
        groups.append((None, grouped[None]))

    hosts = db.session.scalars(db.select(Host).order_by(Host.name.asc())).all()
    categories = db.session.scalars(
        db.select(Category).order_by(Category.name.asc())).all()

    return render_template(
        "webui_list.html",
        groups=groups,
        hosts=hosts,
        categories=categories,
        q=q,
        host_id=host_id,
        category_id=category_id,
        healthchecks_enabled=settings.healthchecks_enabled,
    )


def _form_selection_defaults(webui: WebUI | None):
    # on a POST re-render (validation failure), use what the user submitted so values are preserved
    if request.method == "POST":
        return request.form.get("host_id", ""), request.form.getlist("category_ids")

    if webui is None:
        return "", []

    # on GET, pre-populate from the existing record
    host_id = str(webui.host_id) if webui.host_id else ""
    category_ids = [str(category.id) for category in webui.categories]
    return host_id, category_ids


def _hydrate_webui(webui: WebUI) -> bool:
    # fill in all fields from the submitted form - shared between create and edit
    name = (request.form.get("name") or "").strip()
    raw_url = (request.form.get("url") or "").strip()
    url = normalize_url(raw_url) if raw_url else None
    raw_healthcheck_url = (request.form.get("healthcheck_url") or "").strip()
    healthcheck_url = raw_healthcheck_url or ''
    description = (request.form.get("description") or "").strip() or ''

    service_type = (request.form.get("service_type") or "web").strip()
    if service_type not in WebUI.SERVICE_TYPES:
        service_type = "web"

    # web and api types require a URL; database/other can omit it
    url_required = service_type in ("web", "api")

    if not name:
        flash("Name is required.", "error")
        return False

    if url_required and not url:
        flash("URL is required for Web UI and API service types.", "error")
        return False

    if len(name) > 150:
        flash("Name must be 150 characters or fewer.", "error")
        return False

    if healthcheck_url and not healthcheck_url.startswith("/"):
        healthcheck_url = normalize_url(healthcheck_url)
        parsed_healthcheck = urlparse(healthcheck_url)
        if not parsed_healthcheck.netloc:
            flash("Healthcheck endpoint must be a full URL or a relative path starting with /.", "error")
            return False

    host_id_value = request.form.get("host_id")
    host = None
    if host_id_value:
        if not host_id_value.isdigit():
            flash("Invalid host selection.", "error")
            return False
        host = db.session.get(Host, int(host_id_value))
        if host is None:
            flash("Selected host does not exist.", "error")
            return False

    # collect submitted category ids, ignoring anything that isn't a valid integer
    category_ids = []
    for item in request.form.getlist("category_ids"):
        if item.isdigit():
            category_ids.append(int(item))

    selected_categories = []
    if category_ids:
        selected_categories = db.session.scalars(
            db.select(Category).where(Category.id.in_(category_ids))
        ).all()

    healthcheck_ignored = bool(request.form.get("healthcheck_ignored"))

    url_changed = url != webui.url
    healthcheck_changed = (healthcheck_url or '') != (webui.healthcheck_url or '')
    refresh_favicon = service_type == "web" and (url_changed or not webui.favicon_url) and bool(url)
    webui.name = name
    webui.service_type = service_type
    webui.url = url
    webui.description = description
    webui.healthcheck_url = healthcheck_url
    webui.healthcheck_ignored = healthcheck_ignored
    webui.host = host
    webui.categories = selected_categories
    if url_changed:
        webui.favicon_url = None

    username = (request.form.get("credential_username") or "").strip() or ''
    password = (request.form.get("credential_password") or "").strip()
    clear_credentials = bool(request.form.get("clear_credentials"))

    if clear_credentials:
        # wipe stored credentials entirely
        webui.credential_username = None
        webui.credential_password_encrypted = None
    else:
        old_username = webui.credential_username or ''
        if username != old_username and webui.credential_password_encrypted and not password:
            flash("Provide a new password when changing the username, or use 'Clear credentials' first.", "error")
            return False
        webui.credential_username = username
        # only re-encrypt if a new password was actually submitted - blank means leave existing alone
        if password:
            webui.credential_password_encrypted = encrypt_secret(password)

    # clear stale status on url/endpoint change, or when the service is now ignored
    # (so the dashboard doesn't keep showing an old up/down dot for it)
    if url_changed or healthcheck_changed or healthcheck_ignored:
        webui.last_healthcheck_at = None
        webui.last_healthcheck_ok = None
        webui.last_healthcheck_status = None

    webui._refresh_favicon = refresh_favicon

    return True


def _save_webui(webui: WebUI) -> tuple[int, str, bool]:
    """Flush + commit a hydrated WebUI, returning the data needed to queue a
    favicon refresh. Raises IntegrityError on a unique-URL collision.

    The favicon target is read *before* commit on purpose: commit expires every
    attribute on the instance (expire_on_commit), so reading webui.id/webui.url
    afterwards would trigger a reload that can raise ObjectDeletedError and 500
    the request even though the row was already persisted. Flushing first assigns
    the primary key and surfaces the unique-URL violation as IntegrityError."""
    db.session.add(webui)
    db.session.flush()
    favicon_target = (webui.id, webui.url, bool(getattr(webui, "_refresh_favicon", False)))
    db.session.commit()
    return favicon_target


def _queue_favicon_refresh(webui_id: int, site_url: str, refresh: bool) -> None:
    if not refresh:
        return

    trigger_favicon_refresh_async(
        current_app._get_current_object(),
        webui_id,
        site_url,
    )


@main_bp.route("/webuis/new", methods=["GET", "POST"])
@login_required
def new_webui():
    hosts = db.session.scalars(db.select(Host).order_by(Host.name.asc())).all()
    categories = db.session.scalars(
        db.select(Category).order_by(Category.name.asc())).all()

    selected_host_id, selected_category_ids = _form_selection_defaults(None)

    if request.method == "POST":
        webui = WebUI()
        if _hydrate_webui(webui):
            try:
                favicon_target = _save_webui(webui)
            except IntegrityError:
                # url collision - the unique constraint on url fired
                db.session.rollback()
                flash("A WebUI with that URL already exists.", "error")
            else:
                _queue_favicon_refresh(*favicon_target)
                flash("WebUI created.", "success")
                return redirect(url_for("main.webui_list"))

    return render_template(
        "webui_form.html",
        webui=None,
        hosts=hosts,
        categories=categories,
        selected_host_id=selected_host_id,
        selected_category_ids=selected_category_ids,
        service_types=_SERVICE_TYPE_LABELS,
    )


@main_bp.route("/webuis/<int:webui_id>/edit", methods=["GET", "POST"])
@login_required
def edit_webui(webui_id: int):
    # eager load categories so the form can pre-select them
    webui = db.get_or_404(WebUI, webui_id, options=[
                          joinedload(WebUI.categories)])
    hosts = db.session.scalars(db.select(Host).order_by(Host.name.asc())).all()
    categories = db.session.scalars(
        db.select(Category).order_by(Category.name.asc())).all()

    selected_host_id, selected_category_ids = _form_selection_defaults(webui)

    if request.method == "POST":
        if _hydrate_webui(webui):
            try:
                favicon_target = _save_webui(webui)
            except IntegrityError:
                db.session.rollback()
                flash("Could not save changes. URL may already exist.", "error")
            else:
                _queue_favicon_refresh(*favicon_target)
                flash("WebUI updated.", "success")
                return redirect(url_for("main.webui_list"))

    return render_template(
        "webui_form.html",
        webui=webui,
        hosts=hosts,
        categories=categories,
        selected_host_id=selected_host_id,
        selected_category_ids=selected_category_ids,
        service_types=_SERVICE_TYPE_LABELS,
    )


@main_bp.route("/settings", methods=["GET", "POST"])
@login_required
def settings_page():
    from .notifications import parse_recipients

    settings = g.app_settings
    last_run = db.session.scalar(db.select(func.max(HealthCheckLog.checked_at)))

    if request.method == "POST":
        interval_value = (request.form.get("healthcheck_interval_minutes") or "").strip()
        enabled = bool(request.form.get("healthchecks_enabled"))

        if not interval_value.isdigit():
            flash("Healthcheck interval must be a whole number of minutes.", "error")
            return render_template("settings.html", settings=settings, last_run=last_run)

        interval_minutes = int(interval_value)
        if interval_minutes < 1 or interval_minutes > 1440:
            flash("Healthcheck interval must be between 1 and 1440 minutes.", "error")
            return render_template("settings.html", settings=settings, last_run=last_run)

        settings.healthchecks_enabled = enabled
        settings.healthcheck_interval_minutes = interval_minutes

        # dashboard display preferences
        settings.show_host_service_counts = bool(request.form.get("show_host_service_counts"))

        # SMTP / email settings
        smtp_host = (request.form.get("smtp_host") or "").strip()[:255]
        smtp_port_raw = (request.form.get("smtp_port") or "587").strip()
        smtp_username = (request.form.get("smtp_username") or "").strip()[:255]
        smtp_password = (request.form.get("smtp_password") or "").strip()
        smtp_from = (request.form.get("smtp_from_address") or "").strip()[:255]
        smtp_to = (request.form.get("smtp_to_address") or "").strip()[:255]
        smtp_starttls = bool(request.form.get("smtp_use_starttls"))
        email_enabled = bool(request.form.get("email_notifications_enabled"))

        if not smtp_port_raw.isdigit() or not (1 <= int(smtp_port_raw) <= 65535):
            flash("SMTP port must be a number between 1 and 65535.", "error")
            return render_template("settings.html", settings=settings, last_run=last_run)

        if smtp_from and "@" not in smtp_from:
            flash("From address doesn't look like a valid email.", "error")
            return render_template("settings.html", settings=settings, last_run=last_run)

        # To may be a comma/semicolon-separated list of recipients - validate each
        to_recipients = parse_recipients(smtp_to)
        if any("@" not in addr for addr in to_recipients):
            flash("Each To address must be a valid email; separate multiple recipients with commas.", "error")
            return render_template("settings.html", settings=settings, last_run=last_run)

        settings.smtp_host = smtp_host or None
        settings.smtp_port = int(smtp_port_raw)
        settings.smtp_username = smtp_username or None
        settings.smtp_from_address = smtp_from or None
        settings.smtp_to_address = ", ".join(to_recipients) or None
        settings.smtp_use_starttls = smtp_starttls
        settings.email_notifications_enabled = email_enabled

        if smtp_password:
            settings.smtp_password_encrypted = encrypt_secret(smtp_password)

        # background image
        clear_bg = bool(request.form.get("clear_background"))
        bg_file = request.files.get("background_image")

        if clear_bg:
            if settings.background_image_filename:
                old = os.path.join(_uploads_dir(), settings.background_image_filename)
                if os.path.exists(old):
                    os.remove(old)
                settings.background_image_filename = None
        elif bg_file and bg_file.filename:
            ext = os.path.splitext(secure_filename(bg_file.filename))[1].lower()
            if ext not in _ALLOWED_IMAGE_EXTENSIONS:
                flash("Background image must be JPG, PNG, WebP, GIF, or AVIF.", "error")
                return render_template("settings.html", settings=settings, last_run=last_run)
            bg_file.stream.seek(0, 2)
            size = bg_file.stream.tell()
            bg_file.stream.seek(0)
            if size > _MAX_BG_IMAGE_BYTES:
                flash("Background image must be 10 MB or smaller.", "error")
                return render_template("settings.html", settings=settings, last_run=last_run)
            if not _is_valid_image(bg_file.stream):
                flash("File does not appear to be a valid image.", "error")
                return render_template("settings.html", settings=settings, last_run=last_run)
            if settings.background_image_filename:
                old = os.path.join(_uploads_dir(), settings.background_image_filename)
                if os.path.exists(old):
                    os.remove(old)
            filename = f"bg_image{ext}"
            bg_file.save(os.path.join(_uploads_dir(), filename))
            settings.background_image_filename = filename

        db.session.commit()
        notify_settings_changed(current_app._get_current_object())

        if enabled:
            trigger_healthcheck_pass_async(current_app._get_current_object())
            flash("Settings updated. Health checks will refresh shortly.", "success")
        else:
            flash("Settings updated.", "success")

        return redirect(url_for("main.settings_page"))

    return render_template("settings.html", settings=settings, last_run=last_run)


@main_bp.route("/settings/change-password", methods=["POST"])
@login_required
def change_password():
    current_password = (request.form.get("current_password") or "").strip()
    new_password = (request.form.get("new_password") or "").strip()
    confirm_password = (request.form.get("confirm_password") or "").strip()

    if not g.user.check_password(current_password):
        flash("Current password is incorrect.", "error")
        return redirect(url_for("main.settings_page"))

    if not new_password:
        flash("New password is required.", "error")
        return redirect(url_for("main.settings_page"))

    if new_password != confirm_password:
        flash("New passwords do not match.", "error")
        return redirect(url_for("main.settings_page"))

    g.user.set_password(new_password)
    db.session.commit()
    flash("Password updated.", "success")
    return redirect(url_for("main.settings_page"))


@main_bp.route("/settings/test-email", methods=["POST"])
@login_required
def test_email():
    from .notifications import send_test_email
    ok = send_test_email(g.app_settings)
    if ok:
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Failed to send. Check SMTP config and server logs."})


@main_bp.route("/webuis/<int:webui_id>/credentials", methods=["POST"])
@login_required
def webui_credentials(webui_id: int):
    # returns decrypted credentials as json - called by the js reveal button on the dashboard
    webui = db.get_or_404(WebUI, webui_id)
    return jsonify({
        "username": webui.credential_username or "",
        "password": decrypt_secret(webui.credential_password_encrypted) or "",
    })


@main_bp.route("/webuis/<int:webui_id>/history")
@login_required
def webui_history(webui_id: int):
    db.get_or_404(WebUI, webui_id)
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    logs = db.session.scalars(
        db.select(HealthCheckLog)
        .where(HealthCheckLog.webui_id == webui_id, HealthCheckLog.checked_at >= since)
        .order_by(HealthCheckLog.checked_at.asc())
    ).all()
    return jsonify([
        {
            "checked_at": log.checked_at.isoformat(),
            "is_ok": log.is_ok,
            "status_text": log.status_text,
        }
        for log in logs
    ])


@main_bp.route("/webuis/<int:webui_id>/history/clear", methods=["POST"])
@login_required
def clear_webui_history(webui_id: int):
    # wipes every stored check for this service, not just the last 24h the
    # modal displays - otherwise older rows would resurface as the window moves.
    # The service's current status (last_healthcheck_*) is live state, not
    # history, so it's left alone and the next worker pass refreshes it.
    db.get_or_404(WebUI, webui_id)
    result = db.session.execute(
        db.delete(HealthCheckLog).where(HealthCheckLog.webui_id == webui_id))
    db.session.commit()
    return jsonify({"ok": True, "deleted": result.rowcount})


@main_bp.route("/webuis/<int:webui_id>/delete", methods=["POST"])
@login_required
def delete_webui(webui_id: int):
    webui = db.get_or_404(WebUI, webui_id)
    db.session.delete(webui)
    db.session.commit()
    flash("WebUI removed.", "info")
    return redirect(url_for("main.webui_list"))


def _apply_named_record(instance, noun: str) -> bool:
    # shared validation + DB write for Host and Category create/edit
    # flashes on any failure and returns False; returns True on success
    name = (request.form.get("name") or "").strip()
    description = (request.form.get("description") or "").strip() or ''

    if not name:
        flash(f"{noun} name is required.", "error")
        return False
    if len(name) > 120:
        flash(f"{noun} name must be 120 characters or fewer.", "error")
        return False

    is_new = instance.id is None
    instance.name = name
    instance.description = description
    if is_new:
        db.session.add(instance)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash(f"{noun} name must be unique.", "error")
        return False

    flash(f"{noun} {'created' if is_new else 'updated'}.", "success")
    return True


@main_bp.route("/environments")
@login_required
def environments_page():
    hosts = db.session.scalars(db.select(Host).order_by(Host.name.asc())).all()
    categories = db.session.scalars(db.select(Category).order_by(Category.name.asc())).all()
    return render_template("environments.html", hosts=hosts, categories=categories)


@main_bp.route("/hosts", methods=["POST"])
@login_required
def hosts_page():
    if _apply_named_record(Host(), "Host"):
        return redirect(url_for("main.environments_page") + "#hosts")
    return redirect(url_for("main.environments_page") + "#hosts")


@main_bp.route("/hosts/<int:host_id>/delete", methods=["POST"])
@login_required
def delete_host(host_id: int):
    host = db.get_or_404(Host, host_id)
    linked_count = db.session.scalar(
        db.select(func.count()).select_from(
            WebUI).where(WebUI.host_id == host_id)
    )
    if linked_count:
        return jsonify({"error": f'"{host.name}" has {linked_count} WebUI(s) assigned and cannot be deleted.'}), 409

    db.session.delete(host)
    db.session.commit()
    flash("Host removed.", "info")
    return redirect(url_for("main.environments_page") + "#hosts")


@main_bp.route("/hosts/<int:host_id>/edit", methods=["POST"])
@login_required
def edit_host(host_id: int):
    host = db.get_or_404(Host, host_id)
    _apply_named_record(host, "Host")
    return redirect(url_for("main.environments_page") + "#hosts")


@main_bp.route("/categories", methods=["POST"])
@login_required
def categories_page():
    if _apply_named_record(Category(), "Category"):
        return redirect(url_for("main.environments_page") + "#categories")
    return redirect(url_for("main.environments_page") + "#categories")


@main_bp.route("/categories/<int:category_id>/delete", methods=["POST"])
@login_required
def delete_category(category_id: int):
    category = db.get_or_404(Category, category_id)
    from .models import webui_categories
    linked_count = db.session.scalar(
        db.select(func.count()).select_from(webui_categories).where(
            webui_categories.c.category_id == category_id
        )
    )
    if linked_count:
        return jsonify({"error": f'"{category.name}" is assigned to {linked_count} WebUI(s) and cannot be deleted.'}), 409
    db.session.delete(category)
    db.session.commit()
    flash("Category removed.", "info")
    return redirect(url_for("main.environments_page") + "#categories")


@main_bp.route("/categories/<int:category_id>/edit", methods=["POST"])
@login_required
def edit_category(category_id: int):
    category = db.get_or_404(Category, category_id)
    _apply_named_record(category, "Category")
    return redirect(url_for("main.environments_page") + "#categories")
