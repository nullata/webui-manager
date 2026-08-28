<p align="center"><img src="https://raw.githubusercontent.com/nullata/webui-manager/main/docs/webuimanager-logo.png" alt="logo" width="600"> </p>

# <img src="https://raw.githubusercontent.com/nullata/containers/refs/heads/main/images/logo.png" alt="Logo" width="24"> WebUI Manager

Self-hosted dashboard for organizing and launching your internal web services.

Stores service URLs grouped by host with optional credentials, category tags, and auto-discovered favicons.

For full documentation and source code visit [github.com/nullata/webui-manager](https://github.com/nullata/webui-manager).

## Features

- Session-based login with first-run admin bootstrap and in-app password change
- Login rate limiting (5 failed attempts triggers a 5-minute IP lockout)
- Dashboard grouped by host with favicon auto-discovery
- Custom background image support
- Full-text search across name, URL, description, host, and category, with optional live (as-you-type) filtering
- Ctrl+K / Cmd+K to jump to the search box
- Filter by host or category
- Optional stored credentials (AES-encrypted at rest), copyable without revealing them
- Export and import the whole catalog as JSON, for backup or bulk-adding services
- CSRF protection on all forms and AJAX requests
- MySQL/MariaDB, PostgreSQL, or self-contained SQLite backend, with automatic schema creation and migration on startup

## Quick Start

Create a `docker-compose.yml`:

```yaml
services:
  webui-manager:
    image: nullata/webui-manager
    restart: unless-stopped
    ports:
      - "5000:5000"
    environment:
      SECRET_KEY: your-secret-key
      DB_HOST: 192.168.1.100
      DB_PORT: 3306
      DB_USER: webui
      DB_PASSWORD: your-db-password
      DB_NAME: webui_manager
```

Or against PostgreSQL - a `postgres:16` service with a persistent volume, same variables as MySQL, only the port and backend switch:

```yaml
services:
  webui-manager:
    image: nullata/webui-manager
    restart: unless-stopped
    ports:
      - "5000:5000"
    environment:
      SECRET_KEY: your-secret-key
      DB_TYPE: postgres
      DB_HOST: db
      DB_PORT: 5432
      DB_USER: webui
      DB_PASSWORD: your-db-password
      DB_NAME: webui_manager
      # DB_SSLMODE: require   # uncomment for an SSL-enabled server
    depends_on:
      db:
        condition: service_healthy
  db:
    image: postgres:16-alpine
    restart: unless-stopped
    environment:
      POSTGRES_DB: webui_manager
      POSTGRES_USER: webui
      POSTGRES_PASSWORD: your-db-password
    volumes:
      - pg_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U webui -d webui_manager"]
      interval: 5s
      timeout: 3s
      retries: 10

volumes:
  pg_data:
```

> **Case sensitivity:** PostgreSQL compares strings case-sensitively where
> MySQL's default collation does not. Usernames are matched
> case-insensitively on all backends, so `admin`, `Admin` and `ADMIN` all
> refer to the same account.

Or fully self-contained with SQLite - no external database, just a volume for the data file:

```yaml
services:
  webui-manager:
    image: nullata/webui-manager
    restart: unless-stopped
    ports:
      - "5000:5000"
    environment:
      SECRET_KEY: your-secret-key
      DB_TYPE: sqlite
      DB_PATH: /data/webui_manager.sqlite
    volumes:
      - db_data:/data

volumes:
  db_data:
```

Then run:

```bash
docker compose up -d
```

Navigate to `http://localhost:5000` and follow the admin setup prompt.

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

## Upgrading

Schema migrations run automatically on startup (`AUTO_MIGRATE`, on by default): missing tables and columns are created, nullable and column-type changes are applied, and missing indexes, unique constraints, and MyISAM→InnoDB conversions are handled. Upgrading from any earlier version - including v0.6.4 and older - is just a matter of pulling the new image and restarting. Backing up your database before upgrading is still recommended.

## Migrating to PostgreSQL (or any other backend)

Moving between MySQL, PostgreSQL and SQLite is a data export/import, not a schema migration: use **Settings → Backup & Restore → Export** on the old install (tick "include passwords" - the export writes them as plaintext so they can be re-encrypted for the target install), point the new install at the other backend (`DB_TYPE=postgres` with the compose file above), and **Import** the JSON. Accounts and app settings are not in the export - create the admin via the first-run setup screen and re-enter settings on the new install. Full steps are in the [GitHub README](https://github.com/nullata/webui-manager#migrating-to-postgresql).

## License

Licensed under the [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0).
