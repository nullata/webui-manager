# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

WebUI Manager is a self-hosted Flask dashboard for cataloging and launching internal web services (homelab/internal tools). Services are grouped by host, tagged with categories, optionally store encrypted credentials, and can be background health-checked. Backend is **MySQL/MariaDB** (default) or **SQLite** (self-contained). There is no JS build step — only a CSS (Tailwind) build. Tests are pytest + Playwright under `tests/` (see `tests/README.md`).

## Commands

```bash
# Tests (pytest + Playwright). See tests/README.md.
pip install -r requirements-dev.txt && playwright install chromium
pytest                    # all
pytest -m "not browser"   # no browser needed, ~20s

# Dev server (auto-reload, debug on) — uses app.run(debug=True)
python run.py

# Dev server via Flask CLI (no debug)
flask --app run.py run

# Create an admin user from the CLI instead of the web bootstrap flow
flask --app run.py create-admin

# Rebuild Tailwind CSS after editing templates/JS or tailwind-src.css.
# Uses the committed standalone binary; output is app/static/css/tailwind.css (committed).
./build-tailwind.sh

# Docker (builds from source by default)
docker compose up --build -d

# Build & tag the Docker Hub image from VERSION
./docker-image-build.sh
```

Requires Python 3.12+. Copy `.env.example` to `.env` and set at minimum `SECRET_KEY`. For MySQL, also set `DB_USER`/`DB_PASSWORD` (or `DB_TYPE=sqlite` for self-contained). Tables are created automatically on startup (`db.create_all()` in `create_app`).

## Architecture

Flask app-factory (`app/__init__.py: create_app`) wiring two blueprints: `auth` (`app/auth.py`) and `main` (`app/routes.py`). Config comes from env vars via `app/config.py` (loads `.env` from project root). Models are SQLAlchemy via Flask-SQLAlchemy in `app/models.py`.

**Database backend** — Controlled by `DB_TYPE` env var (`mysql` default, or `sqlite`). When `DB_TYPE=sqlite`, the DB file is at `DB_PATH` (default: `data/webui_manager.sqlite`). SQLite uses `check_same_thread=False` since healthcheck/favicon workers run in daemon threads. `DATABASE_URL` overrides everything. MySQL connection pooling (`pool_pre_ping`, `pool_recycle`) is only enabled for MySQL.

**Request/auth model** — Session-based, no Flask-Login. `init_auth` registers a `before_request` that loads `g.user` from `session["user_id"]`; `current_user` is injected into all templates. Protect views with the `@login_required` decorator (`app/auth.py`), which redirects to the first-run setup if no users exist (`bootstrap_required`), else to `/login`. Login lockout is **in-memory per-IP** (`_failure_counts`/`_lockout_until` dicts) — it resets on process restart and is not shared across workers/replicas. All forms and AJAX are CSRF-protected (Flask-WTF `CSRFProtect`).

**Models** — `User`, `Host`, `Category`, `WebUI`, `HealthCheckLog`, and `AppSetting`. Notable points:
- `AppSetting` is a **singleton row pinned to `id=1`**. Always read/create it via `get_app_settings()` (`app/healthchecks.py`), never instantiate directly. It holds healthcheck + SMTP + background-image settings, plus dashboard display prefs (`show_host_service_counts`, `live_search_enabled`).
- `WebUI.SERVICE_TYPES = ("web", "api")`. `url` is unique and nullable. Categories are many-to-many via the `webui_categories` join table.
- Dashboard queries eager-load `host` and `categories` (`joinedload`/`lazy="subquery"`) specifically to avoid N+1 — preserve this when modifying queries.

**Dashboard search** — Two modes, switched by `AppSetting.live_search_enabled`. Off (default): `webui_list` filters server-side with `ILIKE` over name, URL, description, host name and category name, and the form submits normally. On: the route deliberately **applies no filter and returns every service**, and `initLiveSearch` (`app/static/js/app.js`) filters the rendered cards against each card's `data-search` haystack (the same five fields, lowercased, built in `webui_list.html`). Keep the two in sync — the substring semantics are meant to be identical either way. The server must keep returning everything in live mode, or reloading a filtered URL would strand the client with only the previous result set.

**Backup & restore** — `export_services`/`import_services` (`app/routes.py`) move the catalog as JSON; the UI is the "Backup & Restore" block on the settings page (two sibling forms, deliberately outside the main settings form). Export **omits passwords unless `include_passwords` is ticked**, in which case they are written as plaintext — the stored Fernet ciphertext is keyed to the install and useless elsewhere. Favicons travel in the export because they are already self-contained `data:` URIs. Import accepts the export envelope or a bare list, resolves-or-creates hosts/categories by name, and skips services whose URL is already taken (`url` is unique), so it is idempotent; malformed rows are counted, not fatal.

**Background work** — Four things run on daemon threads, all wrapped by `run_with_app_context` (`app/utils.py`) which pushes an app context and rolls back/cleans the session on failure:
1. Healthcheck worker (`start_healthcheck_worker`) — a long-lived loop. It **does not start under the Flask debug reloader's parent process** (only when `WERKZEUG_RUN_MAIN == "true"`) and not when `app.testing`. It self-paces: polls every 15s while disabled, else sleeps `interval_minutes`. Wake it early after settings changes via `notify_settings_changed`.
2. Favicon refresh (`app/favicons.py: trigger_favicon_refresh_async`) — queued from the WebUI create/edit flow when the URL changes or a web service has no favicon.
3. One-off healthcheck pass (`trigger_healthcheck_pass_async`) — fired when settings are saved with healthchecks enabled.
4. Favicon backfill (`app/favicons.py: trigger_favicon_backfill_async`) — fired after an import. Deliberately **one thread for the whole batch**, walking services in order: an import can create dozens at once, and the per-service `trigger_favicon_refresh_async` would start that many threads and outbound requests at the same time. A failure on one service is logged and skipped so it can't abandon the rest.

**Favicons** — `resolve_favicon` (`app/utils.py`) fetches the page server-side, parses `<link rel="icon">`, falls back to `/favicon.ico`, and stores the image **as a base64 `data:` URI** in `WebUI.favicon_url`. This is deliberate: the browser never connects directly to the service, so self-signed certs don't break icons. TLS verification is disabled throughout for the same homelab reason.

**Healthchecks** — `_check_webui` treats HTTP `<400` plus `401`/`403` as "up" (auth-gated services count as reachable). A relative `healthcheck_url` (starting with `/`) is joined onto the service URL; an absolute one is used as-is. Logs older than 7 days are purged each worker iteration; the dashboard/history view shows the last 24h.

**Email alerts** — When a worker pass finds newly-down services and `email_notifications_enabled` is set, it calls `send_down_alert` (`app/notifications.py`). `send_email` picks implicit SSL (`SMTP_SSL`) when port is 465 and STARTTLS is off, else plain/STARTTLS; certificate verification is disabled (homelab self-signed certs). Failures are logged and swallowed, never raised into the worker loop.

**Secret encryption** — Stored service credentials and the SMTP password are encrypted with Fernet (`encrypt_secret`/`decrypt_secret` in `app/utils.py`). The key is derived as `base64(sha256(APP_CREDENTIALS_KEY or SECRET_KEY))`. **Consequence: changing `SECRET_KEY` (when `APP_CREDENTIALS_KEY` is unset) silently makes all previously stored secrets undecryptable** — `decrypt_secret` returns `None` rather than raising. Set `APP_CREDENTIALS_KEY` separately to decouple session signing from credential encryption. Because `None` is ambiguous, `webui_credentials` compares it against whether ciphertext was stored at all and returns a `decrypt_failed` flag, which the dashboard turns into an explanation — don't collapse that back into a bare `or ""`. The SMTP password still fails silently this way (`send_email` just can't authenticate); worth the same treatment if it comes up.

**Frontend** — Server-rendered Jinja templates in `app/templates/` (`base.html` + `partials/nav.html`). Styling is Tailwind built from `app/static/css/tailwind-src.css` into the committed `tailwind.css`; additional hand-written styles live in `app/static/css/app.css`. All interactivity is one vanilla-JS file, `app/static/js/app.js` (credential reveal, healthcheck history, AJAX deletes) — no framework, no bundler. Fonts and Font Awesome are vendored under `app/static/` for fully offline use.

## Schema migrations

Auto-migration runs on startup (controlled by `AUTO_MIGRATE`, default `true`).
`_apply_auto_migrations()` in `app/__init__.py` compares SQLAlchemy model
metadata against the live DB via SQLAlchemy's Inspector and applies differences.

**MySQL mode** (full):

1. **Missing tables** — handled by `db.create_all()` before the migration runs.
2. **Missing columns** — `ALTER TABLE ... ADD COLUMN` with correct type,
   nullable, and DEFAULT. Python-side callable defaults (e.g. `lambda: now()`)
   get sensible fallbacks (`CURRENT_TIMESTAMP`, `0`, `''`).
3. **Nullable changes** — `ALTER TABLE ... MODIFY COLUMN` (preserves UNIQUE).
4. **Column type mismatches** — `MODIFY COLUMN` for e.g. `VARCHAR(20)` → `VARCHAR(50)`.
5. **Missing indexes** — `CREATE INDEX`.
6. **Missing unique constraints** — `ADD UNIQUE INDEX`.
7. **Engine changes** — MyISAM → InnoDB.
8. **Join table** — `webui_categories` engine conversion.

**SQLite mode** (limited — SQLite ALTER TABLE is restricted):

1. **Missing tables** — handled by `db.create_all()`.
2. **Missing columns** — `ALTER TABLE ... ADD COLUMN` (same as MySQL).
3. **Missing indexes** — `CREATE INDEX`.
4. Nullable changes, type mismatches, unique constraints, and engine changes
   are skipped since SQLite cannot `MODIFY COLUMN` or `ADD UNIQUE INDEX` on
   existing tables. These only matter when upgrading an existing SQLite DB.
   Fresh SQLite installs get the full schema from `db.create_all()`.

Models use `mysql_engine="InnoDB"` which is a MySQL-only DDL option silently
ignored by SQLite (safe).

The old `migrations/` SQL scripts are now redundant — the auto-migration handles
everything they did and more. Keep them in the repo for historical reference but
new schema changes only need model edits + restarting the app.
