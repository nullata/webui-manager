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
- MySQL/MariaDB backend with automatic schema creation on first request

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

Then run:

```bash
docker compose up -d
```

Navigate to `http://localhost:5000` and follow the admin setup prompt.

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `SECRET_KEY` | Yes | Flask session signing key |
| `DB_USER` | Yes | MySQL username |
| `DB_PASSWORD` | Yes | MySQL password |
| `DB_HOST` | No | MySQL host (default: `127.0.0.1`) |
| `DB_PORT` | No | MySQL port (default: `3306`) |
| `DB_NAME` | No | Database name (default: `webui_manager`) |
| `DATABASE_URL` | No | Full SQLAlchemy URL, overrides all `DB_*` fields |
| `APP_CREDENTIALS_KEY` | No | Separate key for credential encryption (falls back to `SECRET_KEY`) |
| `AUTO_MIGRATE` | No | Auto-create tables on first request (default: `true`) |

## Upgrading

### v0.7.5 - Breaking DB Schema Change

v0.7.5 introduces schema changes that are **not backwards-compatible** with v0.6.4.

If you are upgrading from v0.6.4 or earlier, you must either:

- **Reinitialize the database** (drop and recreate) - all data will be lost, or
- **Run the migration SQL** - see the [v0.7.5 release notes](https://github.com/nullata/webui-manager/releases/tag/0.7.5) for the required statements

Fresh installs are unaffected; the schema is created automatically on first request.

## License

Licensed under the [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0).
