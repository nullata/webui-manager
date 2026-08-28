![webuimanager-logo](docs/webuimanager-logo.png)

# <img src="app/static/images/logo.svg" alt="logo" width="24"> WebUI Manager

A self-hosted Flask app for organizing and launching your internal web services. Stores service URLs grouped by host with optional credentials, category tags, and auto-discovered favicons.

## Features

- Session-based login with first-run admin bootstrap
- Admin password change from the Settings page
- Login lockout after 5 failed attempts (5-minute cooldown, resets on restart)
- CSRF protection on all forms and AJAX requests
- Dashboard grouped by host with favicon auto-discovery
- Optional background health checks with per-app healthcheck endpoints
- Full-text search across name, URL, description, host, and category, with optional live (as-you-type) filtering
- Ctrl+K / Cmd+K to jump to the search box
- Filter by host or category
- Optional stored credentials (AES-encrypted at rest), copyable without revealing them
- Export and import the whole catalog as JSON, for backup or bulk-adding services
- Background image upload with MIME type validation and 10 MB size limit
- MySQL/MariaDB, PostgreSQL, or self-contained SQLite backend, with automatic schema creation and migration on startup

## Service Types

Each entry has a service type that controls how the dashboard renders it.

| Type | URL required | Favicon | Description |
|---|---|---|---|
| **Web UI** | Yes | Auto-discovered | A browser-accessible interface - Grafana, Portainer, Jellyfin, etc. |
| **API** | Yes | None | An HTTP API or backend service - REST APIs, internal endpoints, etc. |

## Requirements

- Python 3.12+
- **MySQL/MariaDB** (default), **PostgreSQL** — or use **SQLite** for self-contained deployments

## Setup

### MySQL / MariaDB (default)

```bash
# 1. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env with your DB credentials and a strong SECRET_KEY

# 4. Create the database and user
mysql -u root -p <<'SQL'
CREATE DATABASE IF NOT EXISTS webui_manager
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'webui'@'localhost' IDENTIFIED BY 'changeme';
GRANT ALL PRIVILEGES ON webui_manager.* TO 'webui'@'localhost';
FLUSH PRIVILEGES;
SQL
# Then set DB_USER=webui, DB_PASSWORD=changeme (or your chosen values) in .env

# 5. Run
flask --app run.py run
```

Tables are created automatically on startup. Navigate to `/` and follow the admin setup prompt.

### PostgreSQL

PostgreSQL 14+ works as a first-class backend. The same environment variables
are used as MySQL (`DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_NAME`) — only the
port and backend switch:

```bash
# 1-3. Virtual env, dependencies, .env as in the MySQL setup above

# 4. Set the backend in .env
#    DB_TYPE=postgres
#    DB_PORT=5432
#    DB_NAME=webui_manager
#    DB_HOST=127.0.0.1
#    (optionally DB_SSLMODE=require for an SSL-enabled server)

# 5. Create the database and user
psql -U postgres <<'SQL'
CREATE DATABASE webui_manager;
CREATE USER webui WITH PASSWORD 'changeme';
GRANT ALL PRIVILEGES ON DATABASE webui_manager TO webui;
SQL

# 6. Run
flask --app run.py run
```

Tables are created automatically on startup, and the startup auto-migration
handles schema sync the same way as on MySQL. Navigate to `/` and follow the
admin setup prompt.

> **Case sensitivity:** PostgreSQL compares strings case-sensitively where
> MySQL's default collation does not. Usernames are matched
> case-insensitively on all backends (storage keeps the case you entered), so
> `admin`, `Admin` and `ADMIN` all refer to the same account.

### SQLite (self-contained, no external database)

For single-user or simple deployments, set `DB_TYPE=sqlite` in your `.env` (or as an environment variable). The database file is stored at `DB_PATH` (default: `data/webui_manager.sqlite`).

```bash
# 1. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env — set SECRET_KEY and ensure DB_TYPE=sqlite

# 4. Run (database file created automatically)
flask --app run.py run
```

The SQLite file is created automatically under `data/webui_manager.sqlite` on startup. Tables and schema are managed the same way as MySQL — auto-created and auto-migrated.

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `SECRET_KEY` | Yes | Flask session signing key |
| `DB_TYPE` | No | Database backend: `mysql` (default), `sqlite`, or `postgres` |
| `DB_USER` | Conditional | Database username (required when `DB_TYPE=mysql` or `postgres`) |
| `DB_PASSWORD` | Conditional | Database password (required when `DB_TYPE=mysql` or `postgres`) |
| `DB_HOST` | No | Database host (default: `127.0.0.1`) |
| `DB_PORT` | No | Database port (default: `3306` for MySQL, `5432` for PostgreSQL) |
| `DB_NAME` | No | Database name (default: `webui_manager`) |
| `DB_SSLMODE` | No | PostgreSQL SSL mode (e.g. `require`; ignored by MySQL/SQLite) |
| `DB_PATH` | No | SQLite file path (default: `data/webui_manager.sqlite`) |
| `DATABASE_URL` | No | Full SQLAlchemy URL, overrides `DB_TYPE` and all `DB_*` fields (e.g. `postgresql+psycopg://webui:password@127.0.0.1:5432/webui_manager`) |
| `APP_CREDENTIALS_KEY` | No | Separate key for credential encryption (falls back to `SECRET_KEY`) |
| `AUTO_MIGRATE` | No | Sync existing tables to the current schema on startup (default: `true`). Missing tables are always created regardless |

## Docker Hub

The image is published at [nullata/webui-manager](https://hub.docker.com/r/nullata/webui-manager).

```bash
docker pull nullata/webui-manager
```

Or use it directly in your `docker-compose.yml`:

```yaml
image: nullata/webui-manager
```

## Docker Deployment

### 1. Configure environment

```bash
cp .env.example .env
# Edit .env - set SECRET_KEY, DB_PASSWORD, and any other values
```

### 2a. Docker Compose - build from source

The included `docker-compose.yml` builds the image locally. You will need an external MySQL/MariaDB instance reachable from the container; update `DB_HOST` in `.env` accordingly (or skip the external database entirely with SQLite — see 2d).

```bash
docker compose up --build -d
```

To use the pre-built Docker Hub image instead of building locally, edit `docker-compose.yml` and swap the `build` line for the two commented-out lines:

```yaml
# build: .                          # remove or comment out
image: nullata/webui-manager:latest  # uncomment
pull_policy: always                  # uncomment
```

Then:

```bash
docker compose up -d
```

### 2b. Docker Compose - full stack (app + database)

If you want Compose to manage the database as well, extend `docker-compose.yml` with a MariaDB service and update `DB_HOST` to match the service name:

```yaml
services:
  db:
    image: mariadb:11
    restart: unless-stopped
    environment:
      MARIADB_ROOT_PASSWORD: ${DB_ROOT_PASSWORD:-rootpassword}
      MARIADB_DATABASE: ${DB_NAME:-webui_manager}
      MARIADB_USER: ${DB_USER:-webui}
      MARIADB_PASSWORD: ${DB_PASSWORD}
    volumes:
      - db_data:/var/lib/mysql

  app:
    image: nullata/webui-manager:latest
    pull_policy: always
    restart: unless-stopped
    depends_on:
      - db
    ports:
      - "${APP_PORT:-5000}:5000"
    environment:
      SECRET_KEY: ${SECRET_KEY}
      APP_CREDENTIALS_KEY: ${APP_CREDENTIALS_KEY:-}
      DB_HOST: db
      DB_PORT: ${DB_PORT:-3306}
      DB_USER: ${DB_USER:-webui}
      DB_PASSWORD: ${DB_PASSWORD}
      DB_NAME: ${DB_NAME:-webui_manager}
      AUTO_MIGRATE: ${AUTO_MIGRATE:-true}

volumes:
  db_data:
```

```bash
docker compose up -d
```

### 2c. Plain Docker run

Build the image:

```bash
docker build -t webui-manager .
```

Run the container (supply env vars inline or via `--env-file`):

```bash
docker run -d \
  --name webui-manager \
  --restart unless-stopped \
  --env-file .env \
  -p 5000:5000 \
  webui-manager
```

Or pull the pre-built image from Docker Hub:

```bash
docker run -d \
  --name webui-manager \
  --restart unless-stopped \
  --env-file .env \
  -p 5000:5000 \
  nullata/webui-manager:latest
```

### 2d. Docker — self-contained with SQLite

No external database needed. Mount a volume for the SQLite file so it survives container restarts:

```bash
docker run -d \
  --name webui-manager \
  --restart unless-stopped \
  -p 5000:5000 \
  -e SECRET_KEY=change-this-secret \
  -e DB_TYPE=sqlite \
  -e DB_PATH=/data/webui_manager.sqlite \
  -v webui-data:/data \
  nullata/webui-manager:latest
```

Or with Compose: the included `docker-compose.yml` already contains the SQLite lines commented out — uncomment `DB_TYPE`, `DB_PATH`, and the two `volumes` sections. The result looks like this (the `DB_*` MySQL vars are ignored when `DB_TYPE=sqlite`, so they can stay or go):

```yaml
services:
  app:
    build: .    # or: image: nullata/webui-manager:latest
    restart: unless-stopped
    ports:
      - "${APP_PORT:-5000}:5000"
    environment:
      SECRET_KEY: ${SECRET_KEY}
      APP_CREDENTIALS_KEY: ${APP_CREDENTIALS_KEY:-}
      AUTO_MIGRATE: ${AUTO_MIGRATE:-true}
      DB_TYPE: sqlite
      DB_PATH: /data/webui_manager.sqlite
    volumes:
      - db_data:/data

volumes:
  db_data:
```

```bash
docker compose up -d
```

### 2e. Docker Compose — PostgreSQL backend

`docker-compose.postgres.yml` layers a `postgres:16` service (with a
persistent volume) onto the default compose file and points the app at it, so
the default `docker compose up` (MySQL) is untouched:

```bash
docker compose -f docker-compose.yml -f docker-compose.postgres.yml up --build -d
```

Set `DB_PORT`, `DB_NAME` and any SSL mode in `.env` if they differ from the
defaults; `DB_HOST` and `DB_TYPE` are set by the override file.

### First run

Once the container is running, navigate to `http://localhost:5000` (or your configured port). Tables are created automatically on startup - follow the on-screen admin setup prompt.

## Upgrading

Schema migrations run automatically on startup (`AUTO_MIGRATE`, on by default): missing tables and columns are created, nullable and column-type changes are applied, and missing indexes, unique constraints, and MyISAM→InnoDB conversions are handled. Upgrading from any earlier version - including pre-service-type deployments - is just a matter of deploying the new version and restarting. Backing up your database before upgrading is still recommended.

The plain SQL scripts in the `migrations/` directory are redundant with auto-migration and kept for reference; they are only needed if you run with `AUTO_MIGRATE=false` and want to apply schema changes by hand.

## Migrating to PostgreSQL

WebUI Manager can run on MySQL, PostgreSQL or SQLite — moving between any two
of them is a data export/import, not a schema migration. The JSON export in
**Settings → Backup & Restore** captures the catalog (services, hosts,
categories, favicons), and import rebuilds it on the new backend.

Two things the catalog export **does not** carry, so plan for them:

- **Users.** Accounts are not in the export. On the fresh install, create the
  admin via the first-run setup screen (`/` prompts automatically on an empty
  DB) or from the CLI: `flask --app run.py create-admin`.
- **App settings** (SMTP, dashboard options, healthcheck config) and healthcheck
  history are not exported either — re-enter settings on the new install.

Steps:

1. **Back up the old database first** (a raw dump of MySQL/SQLite is fine — you
   are *not* moving it across engines, but keep it until you've confirmed the
   import).
2. On the current install, export: **Settings → Backup & Restore → Export**.
   **Tick "include passwords"** — the export writes them as *plaintext* (the
   stored Fernet ciphertext is bound to this install's key and is never in the
   file), and a password-less export drops them entirely. They cannot be
   recovered afterwards. On import they are re-encrypted with the target
   install's key.
3. Stand up the app against PostgreSQL (`DB_TYPE=postgres` — see the setup
   section or `docker-compose.postgres.yml`) and let it boot once: on the empty
   database `db.create_all()` builds the full schema.
4. Create the admin (see above), then import the exported JSON:
   **Settings → Backup & Restore → Import**. Services, hosts, categories and
   favicons are recreated.

The database itself is never copied byte-for-byte between engines — the schema
is rebuilt from the models and the catalog flows through JSON.

> **Large installs:** the case-insensitive username lookup (`lower(username)`)
> can't use the plain unique index on PostgreSQL. That's a non-issue at
> homelab scale, but if an install ever grows past a handful of users, add a
> functional index: `CREATE INDEX ON "user" (lower(username));`

## Development

```bash
# Test suite (pytest + Playwright) - see tests/README.md
pip install -r requirements-dev.txt
playwright install chromium          # one-off, for the browser tests
pytest                               # everything
pytest -m "not browser"              # API and database only, no browser needed

# Rebuild the CSS after editing templates, JS, or tailwind-src.css.
# Output (app/static/css/tailwind.css) is committed, so rebuild before pushing.
./build-tailwind.sh
```

Tests run against a temporary SQLite database and never touch your `.env` or
real database. There is no JavaScript build step - `app/static/js/app.js` is
plain vanilla JS loaded directly.

## Third-Party Licenses

[Font Awesome Free](https://fontawesome.com) 7.1.0 is bundled under CC BY 4.0 (icons), SIL OFL 1.1 (fonts), and MIT (code). See `app/static/fontawesome-free-7.1.0-web/LICENSE.txt`.

[IBM Plex Sans](https://fonts.google.com/specimen/IBM+Plex+Sans) and [Space Grotesk](https://fonts.google.com/specimen/Space+Grotesk) are bundled under the SIL Open Font License 1.1. See `app/static/fonts/IBM_Plex_Sans/OFL.txt` and `app/static/fonts/Space_Grotesk/OFL.txt`.

## Credits

The UI was generated with Gemini 2.5 and refined with many manual and agentic adjustments.

## License

Licensed under the [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0).

![webuiception](app/static/images/dank.jpg "webuiception")
