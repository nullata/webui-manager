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

import re

from flask import Flask, flash, g, redirect, render_template, request, send_from_directory, url_for
from flask_wtf.csrf import CSRFError, CSRFProtect

from .config import Config
from .healthchecks import get_app_settings, start_healthcheck_worker
from .models import db
from .routes import main_bp
from .auth import auth_bp, init_auth

csrf = CSRFProtect()


# -----------------------------------------------------------------------
# Auto-migration: compares SQLAlchemy model metadata against the live DB
# and applies any differences.  Covers (MySQL/MariaDB):
#   1. Missing tables → db.create_all() (called before this function)
#   2. Missing columns → ALTER TABLE ... ADD COLUMN
#   3. Nullable changes → ALTER TABLE ... MODIFY COLUMN
#   4. Column type mismatches (e.g. VARCHAR length) → MODIFY COLUMN
#   5. Missing indexes → CREATE INDEX
#   6. Missing unique constraints → UNIQUE INDEX
#   7. Engine changes (MyISAM → InnoDB) → ALTER TABLE ... ENGINE
#
# For SQLite, only missing columns and indexes are applied since SQLite
# ALTER TABLE is limited (no MODIFY COLUMN, no ADD UNIQUE INDEX).
# -----------------------------------------------------------------------

def _is_sqlite() -> bool:
    return db.engine.dialect.name == "sqlite"


# Compile a model type to its DDL label for the active dialect,
# e.g. String(255) → "VARCHAR(255)"  /  Boolean → "BOOL" (MySQL)
def _type_label(col_type) -> str:
    return col_type.compile(dialect=db.engine.dialect)


_INT_DISPLAY_WIDTH = re.compile(r"^(tinyint|smallint|mediumint|int|integer|bigint)\(\d+\)$")


# Normalise a type label so the model side and the DB side compare equal
# when they mean the same storage type. The DB side arrives as a reflected
# TypeEngine object (stringify first); MySQL/MariaDB report booleans as
# tinyint(1) while the model compiles to BOOL, and MariaDB attaches display
# widths to integers (int(11)) that the model side lacks.
def _normalise_type(raw) -> str:
    label = str(raw).strip().lower()
    label = _INT_DISPLAY_WIDTH.sub(lambda m: m.group(1), label)
    # MySQL reports booleans as tinyint(1), MariaDB 11+ as bare tinyint
    # (display widths were removed) — both are the storage type of BOOL.
    if label in ("bool", "boolean", "tinyint"):
        return "bool"
    if label == "integer":
        label = "int"
    return label


def _execute_ddl(app: Flask, ddl: str) -> None:
    # One failed ALTER (bad legacy data, permissions) shouldn't abort the
    # remaining migrations or block app startup — log it and move on.
    from sqlalchemy import text

    try:
        db.session.execute(text(ddl))
        db.session.commit()
    except Exception:
        db.session.rollback()
        app.logger.exception("Auto-migrate: DDL failed: %s", ddl)


def _apply_auto_migrations(app: Flask) -> None:
    from sqlalchemy import inspect

    use_sqlite = _is_sqlite()
    mode = "SQLite (limited)" if use_sqlite else "MySQL"
    app.logger.info("Auto-migrate: starting schema sync (%s mode)", mode)

    inspector = inspect(db.engine)
    existing_tables = set(inspector.get_table_names())

    # db.metadata covers every model table plus plain join tables
    # (webui_categories), so nothing needs special-casing.
    for table in db.metadata.sorted_tables:
        table_name = table.name

        # Fresh tables were just created by db.create_all() with the full
        # schema — only tables that predate the current models need syncing.
        if table_name not in existing_tables:
            continue

        # --- reflect current DB state (one snapshot per table; the Inspector
        # caches per table, so re-reading after DDL would be stale anyway) ---
        db_columns = {c["name"]: c for c in inspector.get_columns(table_name)}
        # Build a set of cols that have indexes, and a set of unique cols.
        db_indexed_cols: set[str] = set()
        db_unique_cols: set[str] = set()
        for idx in inspector.get_indexes(table_name):
            # idx["column_names"] is a list; skip composite/pk indexes
            if idx["column_names"] and len(idx["column_names"]) == 1:
                col = idx["column_names"][0]
                db_indexed_cols.add(col)
                if idx.get("unique", False):
                    db_unique_cols.add(col)

        # --- 1. Missing columns ---
        for col_def in table.columns:
            col_name = col_def.name
            if col_name in db_columns:
                continue
            ddl = f"ALTER TABLE {table_name} ADD COLUMN {col_name} {_type_label(col_def.type)}"
            if not col_def.nullable:
                ddl += " NOT NULL"
            ddl += _sql_default_clause(col_def, use_sqlite)
            app.logger.info("Auto-migrate: adding column %s.%s — %s", table_name, col_name, ddl)
            _execute_ddl(app, ddl)

        # --- 2. Nullable changes / type mismatches (MySQL only — SQLite
        # can't MODIFY COLUMN). Columns added in step 1 aren't in db_columns
        # and are skipped: they already match the model. ---
        if not use_sqlite:
            for col_def in table.columns:
                col_name = col_def.name
                if col_name not in db_columns:
                    continue
                # Never MODIFY a primary key: a bare MODIFY COLUMN silently
                # drops AUTO_INCREMENT, breaking inserts.
                if col_def.primary_key:
                    continue
                existing = db_columns[col_name]
                nullable_differs = existing["nullable"] != col_def.nullable
                expected = _normalise_type(_type_label(col_def.type))
                actual = _normalise_type(existing["type"])
                type_differs = expected != actual
                if not (nullable_differs or type_differs):
                    continue
                # MODIFY COLUMN keeps existing indexes/uniques on the column;
                # only the type and nullability need restating.
                ddl = (
                    f"ALTER TABLE {table_name} MODIFY COLUMN {col_name} "
                    f"{_type_label(col_def.type)} "
                    + ("NOT NULL" if not col_def.nullable else "NULL")
                )
                if type_differs:
                    app.logger.warning(
                        "Auto-migrate: type mismatch on %s.%s — DB has %s, model wants %s. "
                        "Applying MODIFY COLUMN (data may be truncated).",
                        table_name, col_name, actual, expected,
                    )
                else:
                    app.logger.info("Auto-migrate: changing nullable on %s.%s — %s", table_name, col_name, ddl)
                _execute_ddl(app, ddl)

        # --- 3. Missing indexes ---
        for col_def in table.columns:
            col_name = col_def.name
            if not col_def.index or col_name in db_indexed_cols:
                continue
            idx_name = f"idx_{table_name}_{col_name}"
            ddl = f"CREATE INDEX {idx_name} ON {table_name} ({col_name})"
            app.logger.info("Auto-migrate: adding index %s.%s — %s", table_name, col_name, ddl)
            _execute_ddl(app, ddl)

        # --- 4. Missing unique constraints (MySQL only — SQLite can't add unique post-creation) ---
        if not use_sqlite:
            for col_def in table.columns:
                col_name = col_def.name
                if not col_def.unique or col_name in db_unique_cols:
                    continue
                uq_name = f"uq_{table_name}_{col_name}"
                ddl = f"ALTER TABLE {table_name} ADD UNIQUE INDEX {uq_name} ({col_name})"
                app.logger.info("Auto-migrate: adding unique constraint %s.%s — %s", table_name, col_name, ddl)
                _execute_ddl(app, ddl)

        # --- 5. Engine: ensure InnoDB (MySQL only) ---
        if not use_sqlite:
            wanted_engine = (table.kwargs.get("mysql_engine") or "").lower()
            current_engine = (inspector.get_table_options(table_name).get("mysql_engine") or "").lower()
            if wanted_engine and current_engine and wanted_engine != current_engine:
                ddl = f"ALTER TABLE {table_name} ENGINE={wanted_engine.upper()}"
                app.logger.info("Auto-migrate: converting %s engine %s → %s", table_name, current_engine, wanted_engine)
                _execute_ddl(app, ddl)

    app.logger.info("Auto-migrate: schema sync complete.")


def _sql_default_clause(col_def, use_sqlite: bool) -> str:
    """DEFAULT clause for ADD COLUMN, or "" when none is needed.

    Literal model defaults are emitted as-is. Python-side callable defaults
    (e.g. lambda: now()) and NOT NULL columns with no default at all get a
    type-appropriate fallback so the ALTER succeeds on tables that already
    contain rows.
    """
    from sqlalchemy.types import Boolean, DateTime, Integer, Numeric, String

    if col_def.default is not None:
        default_val = getattr(col_def.default, "arg", col_def.default)
        if not callable(default_val):
            if isinstance(default_val, bool):
                # MySQL and SQLite both store booleans as 0/1
                return f" DEFAULT {int(default_val)}"
            if isinstance(default_val, str):
                return " DEFAULT '{}'".format(default_val.replace("'", "''"))
            return f" DEFAULT {default_val}"

    if col_def.nullable:
        return ""  # existing rows get NULL; the app fills new rows

    col_type = col_def.type
    if isinstance(col_type, (Boolean, Integer, Numeric)):
        return " DEFAULT 0"
    if isinstance(col_type, DateTime):
        # SQLite only allows constant defaults in ADD COLUMN
        return " DEFAULT '1970-01-01 00:00:00'" if use_sqlite else " DEFAULT CURRENT_TIMESTAMP"
    if isinstance(col_type, String):  # includes Text
        return " DEFAULT ''"
    return ""


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    csrf.init_app(app)

    with app.app_context():
        db.create_all()
        if app.config.get("AUTO_MIGRATE", True):
            _apply_auto_migrations(app)

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

    @app.before_request
    def _load_app_settings():
        # App-level (not blueprint-level) so g.app_settings is also available
        # when an error handler renders a page — e.g. a 404 raised by an
        # unknown URL matches no blueprint, whose before_request hooks never
        # run, and base.html would otherwise skip the background image.
        g.app_settings = get_app_settings()

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
