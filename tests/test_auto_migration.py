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

"""Startup auto-migration, exercised the way an upgrade hits it.

These run against SQLite, where only missing columns and indexes are applied -
see the schema-migrations section of CLAUDE.md for what MySQL additionally does.
"""

import sqlite3

import pytest

from app import _apply_auto_migrations


@pytest.fixture
def sqlite_path(app):
    url = app.config["SQLALCHEMY_DATABASE_URI"]
    assert url.startswith("sqlite:///"), f"these tests assume SQLite, got {url}"
    return url[len("sqlite:///"):]


def columns(path, table):
    connection = sqlite3.connect(path)
    try:
        return {row[1]: row for row in connection.execute(f"PRAGMA table_info({table})")}
    finally:
        connection.close()


def drop_column(path, table, column):
    connection = sqlite3.connect(path)
    try:
        connection.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
        connection.commit()
    finally:
        connection.close()


@pytest.mark.parametrize("table, column", [
    ("app_setting", "live_search_enabled"),
    ("app_setting", "show_host_service_counts"),
    ("web_ui", "healthcheck_ignored"),
])
def test_a_missing_column_is_added_on_startup(app, sqlite_path, table, column):
    """Simulates upgrading an install whose schema predates the column."""
    if sqlite3.sqlite_version_info < (3, 35):
        pytest.skip("ALTER TABLE DROP COLUMN needs SQLite 3.35+")

    drop_column(sqlite_path, table, column)
    assert column not in columns(sqlite_path, table)

    with app.app_context():
        _apply_auto_migrations(app)

    assert column in columns(sqlite_path, table)


def test_readded_boolean_column_is_not_null_with_a_usable_default(app, sqlite_path):
    """An existing row must survive the migration, not trip the NOT NULL."""
    from app.healthchecks import get_app_settings
    from app.models import db

    if sqlite3.sqlite_version_info < (3, 35):
        pytest.skip("ALTER TABLE DROP COLUMN needs SQLite 3.35+")

    with app.app_context():
        get_app_settings()          # materialise the singleton row
        db.session.commit()

    drop_column(sqlite_path, "app_setting", "live_search_enabled")
    with app.app_context():
        _apply_auto_migrations(app)

    _, _, col_type, not_null, default, _ = columns(
        sqlite_path, "app_setting")["live_search_enabled"]
    assert col_type.upper() == "BOOLEAN"
    assert not_null == 1
    assert default == "0"

    connection = sqlite3.connect(sqlite_path)
    try:
        rows = list(connection.execute("SELECT id, live_search_enabled FROM app_setting"))
    finally:
        connection.close()
    assert rows and rows[0][1] == 0

    with app.app_context():
        assert get_app_settings().live_search_enabled is False


def test_migration_is_idempotent(app, sqlite_path):
    before = columns(sqlite_path, "app_setting")
    with app.app_context():
        _apply_auto_migrations(app)
        _apply_auto_migrations(app)
    assert columns(sqlite_path, "app_setting").keys() == before.keys()
