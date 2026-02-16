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

from functools import wraps

from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from .models import User, db


auth_bp = Blueprint("auth", __name__)


def bootstrap_required() -> bool:
    # check if any users exist - if not, we need the first-run setup
    # cached on g so we dont hit the db more than once per request
    if "bootstrap_required" not in g:
        g.bootstrap_required = db.session.scalar(
            db.select(func.count()).select_from(User)) == 0
    return g.bootstrap_required


def login_required(view):
    # decorator that redirects to setup if no users exist, or login if not authenticated
    @wraps(view)
    def wrapped(*args, **kwargs):
        if bootstrap_required():
            return redirect(url_for("auth.setup_admin"))
        if g.user is None:
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


def init_auth(app):
    @app.before_request
    def load_user():
        # pull the user id out of the session and fetch the full user object each request
        user_id = session.get("user_id")
        g.user = db.session.get(User, user_id) if user_id else None

    @app.context_processor
    def inject_auth_user():
        # makes current_user available in all templates without passing it manually
        return {"current_user": g.get("user")}


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    # redirect away if setup hasn't happened yet or user is already logged in
    if bootstrap_required():
        return redirect(url_for("auth.setup_admin"))

    if g.user is not None:
        return redirect(url_for("main.webui_list"))

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""

        user = db.session.scalar(
            db.select(User).where(User.username == username))
        if user and user.check_password(password):
            session.clear()
            session["user_id"] = user.id

            # respect the ?next= param but only allow relative paths to prevent open redirect
            next_url = request.args.get("next") or url_for("main.webui_list")
            if not next_url.startswith("/"):
                next_url = url_for("main.webui_list")
            return redirect(next_url)

        flash("Invalid username or password.", "error")

    return render_template("login.html")


@auth_bp.route("/setup-admin", methods=["GET", "POST"])
def setup_admin():
    # only accessible on first run when no users exist
    if not bootstrap_required():
        if g.user is not None:
            return redirect(url_for("main.webui_list"))
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        password_confirm = request.form.get("password_confirm") or ""

        if not username:
            flash("Username is required.", "error")
        elif not password:
            flash("Password is required.", "error")
        elif password != password_confirm:
            flash("Passwords do not match.", "error")
        else:
            user = User(username=username)
            user.set_password(password)
            db.session.add(user)
            try:
                db.session.commit()
            except IntegrityError:
                # shouldn't normally happen on first run but handle it cleanly
                db.session.rollback()
                flash("That username is already in use.", "error")
            else:
                session.clear()
                session["user_id"] = user.id
                flash("Admin account created.", "success")
                return redirect(url_for("main.webui_list"))

    return render_template("setup_admin.html")


@auth_bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("Logged out successfully.", "info")
    # if somehow no users exist after logout, go back to setup instead of login
    if bootstrap_required():
        return redirect(url_for("auth.setup_admin"))
    return redirect(url_for("auth.login"))
