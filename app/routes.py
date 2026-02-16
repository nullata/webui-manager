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

from flask import Blueprint, flash, g, redirect, render_template, request, url_for
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from .auth import login_required
from .models import Category, Host, User, WebUI, db
from .utils import decrypt_secret, encrypt_secret, normalize_url, resolve_favicon


main_bp = Blueprint("main", __name__)


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
    raw_url = request.form.get("url") or ""
    url = normalize_url(raw_url)
    description = (request.form.get("description") or "").strip() or ''

    if not name or not url:
        flash("Name and URL are required.", "error")
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

    url_changed = url != webui.url
    webui.name = name
    webui.url = url
    webui.description = description
    webui.host = host
    webui.categories = selected_categories

    username = (request.form.get("credential_username") or "").strip() or ''
    password = request.form.get("credential_password") or ""
    clear_credentials = bool(request.form.get("clear_credentials"))

    if clear_credentials:
        # wipe stored credentials entirely
        webui.credential_username = None
        webui.credential_password_encrypted = None
    else:
        webui.credential_username = username
        # only re-encrypt if a new password was actually submitted - blank means leave existing alone
        if password:
            webui.credential_password_encrypted = encrypt_secret(password)

    # only re-resolve favicon if url changed or we dont have one yet
    if url_changed or not webui.favicon_url:
        resolved_favicon = resolve_favicon(url)
        if resolved_favicon:
            webui.favicon_url = resolved_favicon

    return True


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
            db.session.add(webui)
            try:
                db.session.commit()
            except IntegrityError:
                # url collision - the unique constraint on url fired
                db.session.rollback()
                flash("A WebUI with that URL already exists.", "error")
            else:
                flash("WebUI created.", "success")
                return redirect(url_for("main.webui_list"))

    return render_template(
        "webui_form.html",
        webui=None,
        hosts=hosts,
        categories=categories,
        selected_host_id=selected_host_id,
        selected_category_ids=selected_category_ids,
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
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                flash("Could not save changes. URL may already exist.", "error")
            else:
                flash("WebUI updated.", "success")
                return redirect(url_for("main.webui_list"))

    return render_template(
        "webui_form.html",
        webui=webui,
        hosts=hosts,
        categories=categories,
        selected_host_id=selected_host_id,
        selected_category_ids=selected_category_ids,
    )


@main_bp.route("/webuis/<int:webui_id>/credentials")
@login_required
def webui_credentials(webui_id: int):
    # returns decrypted credentials as json - called by the js reveal button on the dashboard
    from flask import jsonify
    webui = db.get_or_404(WebUI, webui_id)
    return jsonify({
        "username": webui.credential_username or "",
        "password": decrypt_secret(webui.credential_password_encrypted) or "",
    })


@main_bp.route("/webuis/<int:webui_id>/delete", methods=["POST"])
@login_required
def delete_webui(webui_id: int):
    webui = db.get_or_404(WebUI, webui_id)
    db.session.delete(webui)
    db.session.commit()
    flash("WebUI removed.", "info")
    return redirect(url_for("main.webui_list"))


@main_bp.route("/hosts", methods=["GET", "POST"])
@login_required
def hosts_page():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        description = (request.form.get("description") or "").strip() or ''

        if not name:
            flash("Host name is required.", "error")
        else:
            host = Host(name=name, description=description)
            db.session.add(host)
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                flash("Host name must be unique.", "error")
            else:
                flash("Host created.", "success")
                return redirect(url_for("main.hosts_page"))

    hosts = db.session.scalars(db.select(Host).order_by(Host.name.asc())).all()
    return render_template("hosts.html", hosts=hosts)


@main_bp.route("/hosts/<int:host_id>/delete", methods=["POST"])
@login_required
def delete_host(host_id: int):
    from flask import jsonify
    host = db.get_or_404(Host, host_id)
    linked_count = db.session.scalar(
        db.select(func.count()).select_from(WebUI).where(WebUI.host_id == host_id)
    )
    if linked_count:
        return jsonify({"error": f'"{host.name}" has {linked_count} WebUI(s) assigned and cannot be deleted.'}), 409

    db.session.delete(host)
    db.session.commit()
    flash("Host removed.", "info")
    return redirect(url_for("main.hosts_page"))


@main_bp.route("/categories", methods=["GET", "POST"])
@login_required
def categories_page():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        description = (request.form.get("description") or "").strip() or ''

        if not name:
            flash("Category name is required.", "error")
        else:
            category = Category(name=name, description=description)
            db.session.add(category)
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                flash("Category name must be unique.", "error")
            else:
                flash("Category created.", "success")
                return redirect(url_for("main.categories_page"))

    categories = db.session.scalars(
        db.select(Category).order_by(Category.name.asc())).all()
    return render_template("categories.html", categories=categories)


@main_bp.route("/categories/<int:category_id>/delete", methods=["POST"])
@login_required
def delete_category(category_id: int):
    from flask import jsonify
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
    return redirect(url_for("main.categories_page"))
