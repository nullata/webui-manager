"""PostgreSQL backend tests (opt-in).

These run against a real PostgreSQL instance, selected via:

    POSTGRES_TEST_URL=postgresql://user:pass@localhost:5432/webui_test \
        pytest -m postgres

They are excluded from the default run (see pytest.ini) and skip cleanly
when POSTGRES_TEST_URL is not set, so ``pytest -m postgres`` with no
database configured reports skips rather than errors.

Covers the two things that differ on Postgres vs SQLite/MySQL:

1. the auto-migrator's PostgreSQL dialect branch (DDL differences: real
   booleans, SERIAL PKs, ALTER COLUMN SET/DROP NOT NULL, constraint
   naming style), and
2. case-sensitive string comparison — usernames must match
   case-insensitively on Postgres the way they do on MySQL's default
   collation.
"""
import os

import pytest
from sqlalchemy import func, inspect

from app.models import User, db

pytestmark = pytest.mark.postgres


def _pg_configured() -> bool:
    return bool(os.environ.get("POSTGRES_TEST_URL"))


@pytest.fixture
def pg_engine(app):
    if not _pg_configured():
        pytest.skip("POSTGRES_TEST_URL not set; run with it to exercise the Postgres path")
    with app.app_context():
        yield db.engine


# --------------------------------------------------------------------------
# Auto-migrator on PostgreSQL
# --------------------------------------------------------------------------

def test_dialect_name_is_postgresql(pg_engine):
    """The conftest app must actually be talking to PostgreSQL here."""
    from app import _dialect_name

    assert _dialect_name() == "postgresql"


def test_fresh_boot_creates_schema_and_bootstrap(pg_engine, app):
    """A fresh database gets a full schema, and first-run setup works."""
    from app.auth import bootstrap_required

    with app.app_context():
        db.drop_all()
        db.create_all()

        # bootstrap_required() must be True on an empty DB...
        assert bootstrap_required()
        # ...and the user table must exist with the username column.
        inspector = inspect(db.engine)
        cols = [c["name"] for c in inspector.get_columns("user")]
        assert "username" in cols

    # Fresh context so the g-cached bootstrap check is re-evaluated.
    with app.app_context():
        # Seed an admin, then bootstrap_required() must flip to False.
        u = User(username="pgadmin")
        u.set_password("pw-12345")
        db.session.add(u)
        db.session.commit()
        db.session.remove()

    with app.app_context():
        assert not bootstrap_required()


def test_auto_migrator_adds_missing_column_on_postgres(pg_engine, app):
    """The Postgres dialect branch must ALTER TABLE ... ADD COLUMN."""
    from app import _apply_auto_migrations

    with app.app_context():
        db.drop_all()
        db.create_all()

        # Simulate a pre-migration schema by dropping columns the model
        # still declares, then let the migrator fill the gap.
        db.session.execute(db.text(
            "ALTER TABLE web_ui DROP COLUMN credential_password_encrypted"))
        db.session.execute(db.text("ALTER TABLE web_ui DROP COLUMN favicon_url"))
        db.session.commit()

        _apply_auto_migrations(app)

        inspector = inspect(db.engine)
        cols = {c["name"] for c in inspector.get_columns("web_ui")}
        assert "credential_password_encrypted" in cols
        assert "favicon_url" in cols
        # credential_password_encrypted is nullable with no default; the
        # migrator must have added it without a NOT NULL/DEFAULT that would
        # have failed on the (empty) table.
        col = next(c for c in inspector.get_columns("web_ui")
                   if c["name"] == "credential_password_encrypted")
        assert col["nullable"] is True


def test_auto_migrator_handles_not_null_boolean_column_on_postgres(pg_engine, app):
    """A missing NOT NULL boolean column gets DEFAULT FALSE on Postgres.

    (On MySQL/SQLite the same migration emits DEFAULT 0; PostgreSQL has
    real booleans and would reject 0 there.)
    """
    from app import _apply_auto_migrations

    with app.app_context():
        db.drop_all()
        db.create_all()

        db.session.execute(db.text("ALTER TABLE web_ui DROP COLUMN healthcheck_ignored"))
        db.session.commit()

        _apply_auto_migrations(app)  # must not raise

        inspector = inspect(db.engine)
        cols = {c["name"]: c for c in inspector.get_columns("web_ui")}
        assert "healthcheck_ignored" in cols
        col = cols["healthcheck_ignored"]
        assert col["nullable"] is False
        # Server-side default must be the boolean false, stored as a real
        # boolean on PostgreSQL.
        assert str(col.get("default") or "").upper() in ("FALSE", "0")


def test_auto_migrator_is_idempotent_on_postgres(pg_engine, app):
    """Running the migrator twice on a fresh schema must be a no-op the 2nd time."""
    from app import _apply_auto_migrations

    with app.app_context():
        db.drop_all()
        db.create_all()
        _apply_auto_migrations(app)  # 1st pass: no work
        _apply_auto_migrations(app)  # 2nd pass: must not raise

        inspector = inspect(db.engine)
        tables = set(inspect(db.engine).get_table_names())
        assert "user" in tables and "web_ui" in tables


# --------------------------------------------------------------------------
# Case-sensitive comparison (username lookups)
# --------------------------------------------------------------------------

def test_username_lookup_is_case_insensitive_on_postgres(pg_engine, app):
    """Login lookup must match across case, like MySQL's default collation."""
    from app.auth import get_user_by_username

    with app.app_context():
        db.drop_all()
        db.create_all()

        u = User(username="Admin")
        u.set_password("pw")
        db.session.add(u)
        db.session.commit()

        assert get_user_by_username("admin") is not None
        assert get_user_by_username("ADMIN") is not None
        assert get_user_by_username("admin").username == "Admin"


def test_setup_admin_is_closed_after_first_user(pg_engine, app):
    """Once any user exists, /setup-admin must not create another one —
    even one whose name is only a case variant of the existing user.
    (The in-route case-insensitive duplicate check is a belt-and-braces
    guard for concurrent first-run setup; the bootstrap gate above is what
    actually prevents duplicates.)"""
    with app.app_context():
        db.drop_all()
        db.create_all()

        u = User(username="Admin")
        u.set_password("pw")
        db.session.add(u)
        db.session.commit()

        client = app.test_client()
        resp = client.post(
            "/setup-admin",
            data={"username": "admin", "password": "pw2", "password_confirm": "pw2"},
        )
        # Setup is closed → redirect to /login, and no second user was made.
        assert resp.status_code == 302
        assert resp.headers["Location"] == "/login"

        count = db.session.scalar(db.select(func.count()).select_from(User))
        assert count == 1


def test_login_matches_case_insensitively(pg_engine, app):
    """A user created as 'Admin' can log in as 'admin'."""
    with app.app_context():
        db.drop_all()
        db.create_all()

        u = User(username="Admin")
        u.set_password("S3cret!")
        db.session.add(u)
        db.session.commit()

        client = app.test_client()
        resp = client.post(
            "/login",
            data={"username": "admin", "password": "S3cret!"},
        )
        # Success redirects to the dashboard; a failed login re-renders /login.
        assert resp.status_code == 302
        assert resp.headers["Location"] == "/dashboard"
