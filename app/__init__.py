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

from flask import Flask, flash, redirect, render_template, request, send_from_directory, url_for
from flask_wtf.csrf import CSRFError, CSRFProtect

from .config import Config
from .healthchecks import start_healthcheck_worker
from .models import db
from .routes import main_bp
from .auth import auth_bp, init_auth

csrf = CSRFProtect()


# Additive column migrations that db.create_all() can't apply to an existing
# table. Kept in sync with the scripts under migrations/. Each entry is
# (table, column, "ALTER TABLE ... ADD COLUMN ..."). The DDL must be valid on
# both MySQL/MariaDB and SQLite. Applied idempotently on startup when
# AUTO_MIGRATE is on (default), so upgrades don't require running SQL by hand.
_ADDITIVE_MIGRATIONS = [
    ("app_setting", "show_host_service_counts",
     "ALTER TABLE app_setting ADD COLUMN show_host_service_counts BOOLEAN NOT NULL DEFAULT 1"),
    ("web_ui", "healthcheck_ignored",
     "ALTER TABLE web_ui ADD COLUMN healthcheck_ignored BOOLEAN NOT NULL DEFAULT 0"),
]


def _apply_additive_migrations(app: Flask) -> None:
    from sqlalchemy import inspect, text

    inspector = inspect(db.engine)
    existing_tables = set(inspector.get_table_names())
    for table, column, ddl in _ADDITIVE_MIGRATIONS:
        # Fresh installs get the full schema from create_all(); only patch
        # tables that already exist but predate the column.
        if table not in existing_tables:
            continue
        columns = {c["name"] for c in inspector.get_columns(table)}
        if column in columns:
            continue
        db.session.execute(text(ddl))
        db.session.commit()
        app.logger.info("Auto-migrate: added column %s.%s", table, column)


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    csrf.init_app(app)

    with app.app_context():
        db.create_all()
        if app.config.get("AUTO_MIGRATE", True):
            _apply_additive_migrations(app)

    init_auth(app)

    @app.route("/favicon.ico")
    def favicon():
        # Browsers auto-request /favicon.ico at the site root regardless of the
        # <link rel="icon"> tags in <head>. Without this the request 404s (noisy
        # console error on every page). Serve the committed icon from static.
        return send_from_directory(app.static_folder, "favicon.ico", mimetype="image/x-icon")

    @app.after_request
    def add_no_cache_headers(response):
        # Never let the browser cache rendered HTML. A page restored from the
        # back/forward cache (bfcache) carries a CSRF token bound to a session
        # that may since have been cleared, so resubmitting it (e.g. logging in
        # after being logged out) fails with "CSRF token is missing". Static
        # assets are left cacheable.
        if request.endpoint != "static" and response.mimetype == "text/html":
            response.headers["Cache-Control"] = "no-store, max-age=0"
        return response

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    start_healthcheck_worker(app)

    @app.cli.command("create-admin")
    def create_admin() -> None:
        # cli helper to create an admin user without going through the web ui
        from getpass import getpass

        from .models import User

        username = input("Username: ").strip()
        if not username:
            print("Username is required.")
            return

        existing = db.session.scalar(
            db.select(User).where(User.username == username))
        if existing:
            print("User already exists.")
            return

        password = getpass("Password: ")
        if not password:
            print("Password is required.")
            return

        user = User(username=username)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        print(f"Admin user '{username}' created.")

################
# error handlers
################


    @app.errorhandler(CSRFError)
    def handle_csrf_error(e):
        # A stale/expired CSRF token (commonly a login form submitted after the
        # session was cleared) used to dump the user on a dead 400 page reading
        # "The CSRF token is missing", recoverable only by manually visiting the
        # root URL. Instead, flash a friendly message and redirect through the
        # root route, which re-issues a fresh token bound to the current session.
        flash("Your session expired. Please try again.", "error")
        return redirect(url_for("main.index"))

    @app.errorhandler(404)
    def not_found(e):
        return render_template("error.html", error_code=404,
                               error_title="Not Found",
                               error_description="The page you're looking for doesn't exist."), 404

    @app.errorhandler(403)
    def forbidden(e):
        return render_template("error.html", error_code=403,
                               error_title="Forbidden",
                               error_description="You don't have permission to access this resource."), 403

    @app.errorhandler(405)
    def method_not_allowed(e):
        return render_template("error.html", error_code=405,
                               error_title="Method Not Allowed",
                               error_description="The request method is not supported for this endpoint."), 405

    @app.errorhandler(500)
    def internal_error(e):
        db.session.rollback()
        return render_template("error.html", error_code=500,
                               error_title="Internal Server Error",
                               error_description="Something went wrong on our end. Please try again later."), 500

    return app
