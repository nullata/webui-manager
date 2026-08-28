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

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from functools import wraps
from threading import Lock

from flask import Blueprint, flash, g, jsonify, redirect, render_template, request, session, url_for
from flask_wtf.csrf import generate_csrf
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from .models import User, db

_MAX_ATTEMPTS = 5
_LOCKOUT_DURATION = timedelta(minutes=5)

_failure_counts: dict[str, int] = defaultdict(int)
_lockout_until: dict[str, datetime] = {}
_attempts_lock = Lock()


def _client_ip() -> str:
    return request.remote_addr or "unknown"


def _check_lockout(ip: str) -> bool:
    """Return True if the IP is currently locked out."""
    until = _lockout_until.get(ip)
    if until and datetime.now(timezone.utc) < until:
        return True
    return False


def _record_failure(ip: str) -> None:
    with _attempts_lock:
        _failure_counts[ip] += 1
        if _failure_counts[ip] >= _MAX_ATTEMPTS:
            _lockout_until[ip] = datetime.now(timezone.utc) + _LOCKOUT_DURATION
            del _failure_counts[ip]


def _clear_failures(ip: str) -> None:
    with _attempts_lock:
        _failure_counts.pop(ip, None)
        _lockout_until.pop(ip, None)


auth_bp = Blueprint("auth", __name__)


def bootstrap_required() -> bool:
    # check if any users exist - if not, we need the first-run setup
    # cached on g so we dont hit the db more than once per request
    if "bootstrap_required" not in g:
        g.bootstrap_required = db.session.scalar(
            db.select(func.count()).select_from(User)) == 0
    return g.bootstrap_required


def get_user_by_username(username: str):
    """Look a user up by username, case-insensitively.

    PostgreSQL compares strings case-sensitively while MySQL's default
    collation does not, so plain ``User.username == username`` would let
    "admin" and "Admin" log in on one backend but not the other. Lower-casing
    both sides keeps the two backends behaving the same way.
    """
    return db.session.scalar(
        db.select(User).where(func.lower(User.username) == username.lower()))


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
        ip = _client_ip()

        if _check_lockout(ip):
            flash("Too many failed attempts. Try again in 5 minutes.", "error")
            return render_template("login.html")

        username = (request.form.get("username") or "").strip()
        password = (request.form.get("password") or "").strip()

        user = get_user_by_username(username)
        if user and user.check_password(password):
            _clear_failures(ip)
            session.clear()
            session["user_id"] = user.id

            # respect the ?next= param but only allow relative paths to prevent open redirect
            next_url = request.args.get("next") or url_for("main.webui_list")
            if not next_url.startswith("/"):
                next_url = url_for("main.webui_list")
            return redirect(next_url)

        _record_failure(ip)
        flash("Invalid username or password.", "error")

    return render_template("login.html")


@auth_bp.route("/csrf-token")
def csrf_token():
    # A login/setup page can outlive the session its embedded CSRF token was
    # bound to (browser restart drops the session cookie, another tab rotates
    # it). The form fetches this right before submitting so the POST always
    # carries a token matching the session cookie it is sent with; otherwise
    # the first attempt bounces through the CSRFError handler ("Your session
    # expired") and the user has to log in twice.
    response = jsonify({"csrf_token": generate_csrf()})
    # the global no-cache after_request hook only covers text/html responses
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return response


@auth_bp.route("/setup-admin", methods=["GET", "POST"])
def setup_admin():
    # only accessible on first run when no users exist
    if not bootstrap_required():
        if g.user is not None:
            return redirect(url_for("main.webui_list"))
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = (request.form.get("password") or "").strip()
        password_confirm = (request.form.get("password_confirm") or "").strip()

        if not username:
            flash("Username is required.", "error")
        elif not password:
            flash("Password is required.", "error")
        elif password != password_confirm:
            flash("Passwords do not match.", "error")
        else:
            if get_user_by_username(username) is not None:
                flash("That username is already in use.", "error")
                return render_template("setup_admin.html")
            user = User(username=username)
            user.set_password(password)
            db.session.add(user)
            try:
                db.session.commit()
            except IntegrityError:
                # Belt-and-braces race against the check above. Safe even
                # though PostgreSQL's unique index is case-sensitive: the
                # explicit check already used a case-insensitive comparison,
                # and only a concurrent first-run setup could hit this path.
                db.session.rollback()
                flash("That username is already in use.", "error")
                return render_template("setup_admin.html")
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
