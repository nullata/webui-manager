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
- Full-text search across name, URL, description, host, and category
- Filter by host or category
- Optional stored credentials (AES-encrypted at rest)
- Background image upload with MIME type validation and 10 MB size limit
- MySQL/MariaDB or self-contained SQLite backend, with automatic schema creation and migration on startup

## Service Types

Each entry has a service type that controls how the dashboard renders it.

| Type | URL required | Favicon | Description |
|---|---|---|---|
| **Web UI** | Yes | Auto-discovered | A browser-accessible interface - Grafana, Portainer, Jellyfin, etc. |
| **API** | Yes | None | An HTTP API or backend service - REST APIs, internal endpoints, etc. |

## Requirements

- Python 3.12+
- **MySQL/MariaDB** (default) — or use **SQLite** for self-contained deployments

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
| `DB_TYPE` | No | Database backend: `mysql` (default) or `sqlite` |
| `DB_USER` | Conditional | MySQL username (required when `DB_TYPE=mysql`) |
| `DB_PASSWORD` | Conditional | MySQL password (required when `DB_TYPE=mysql`) |
| `DB_HOST` | No | MySQL host (default: `127.0.0.1`) |
| `DB_PORT` | No | MySQL port (default: `3306`) |
| `DB_NAME` | No | Database name (default: `webui_manager`) |
| `DB_PATH` | No | SQLite file path (default: `data/webui_manager.sqlite`) |
| `DATABASE_URL` | No | Full SQLAlchemy URL, overrides `DB_TYPE` and all `DB_*` fields |
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

### First run

Once the container is running, navigate to `http://localhost:5000` (or your configured port). Tables are created automatically on startup - follow the on-screen admin setup prompt.

## Upgrading

Schema migrations run automatically on startup (`AUTO_MIGRATE`, on by default): missing tables and columns are created, nullable and column-type changes are applied, and missing indexes, unique constraints, and MyISAM→InnoDB conversions are handled. Upgrading from any earlier version - including pre-service-type deployments - is just a matter of deploying the new version and restarting. Backing up your database before upgrading is still recommended.

The plain SQL scripts in the `migrations/` directory are redundant with auto-migration and kept for reference; they are only needed if you run with `AUTO_MIGRATE=false` and want to apply schema changes by hand.

## Third-Party Licenses

[Font Awesome Free](https://fontawesome.com) 7.1.0 is bundled under CC BY 4.0 (icons), SIL OFL 1.1 (fonts), and MIT (code). See `app/static/fontawesome-free-7.1.0-web/LICENSE.txt`.

[IBM Plex Sans](https://fonts.google.com/specimen/IBM+Plex+Sans) and [Space Grotesk](https://fonts.google.com/specimen/Space+Grotesk) are bundled under the SIL Open Font License 1.1. See `app/static/fonts/IBM_Plex_Sans/OFL.txt` and `app/static/fonts/Space_Grotesk/OFL.txt`.

## Credits

The UI was generated with Gemini 2.5 and refined with many manual and agentic adjustments.

## License

Licensed under the [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0).

![webuiception](app/static/images/dank.jpg "webuiception")
