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
- Full-text search across name, URL, description, host, and category
- Filter by host or category
- Optional stored credentials (AES-encrypted at rest)
- CSRF protection on all forms and AJAX requests
- MySQL/MariaDB or self-contained SQLite backend, with automatic schema creation and migration on startup

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

## Upgrading

Schema migrations run automatically on startup (`AUTO_MIGRATE`, on by default): missing tables and columns are created, nullable and column-type changes are applied, and missing indexes, unique constraints, and MyISAM→InnoDB conversions are handled. Upgrading from any earlier version - including v0.6.4 and older - is just a matter of pulling the new image and restarting. Backing up your database before upgrading is still recommended.

## License

Licensed under the [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0).
