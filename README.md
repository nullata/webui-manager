![webuiception](app/static/images/dank.jpg "webuiception")

# <img src="app/static/images/logo.svg" alt="logo" width="24"> WebUI Manager

A self-hosted Flask app for organizing and launching your internal web services. Stores service URLs grouped by host with optional credentials, category tags, and auto-discovered favicons.

## Features

- Session-based login with first-run admin bootstrap
- Dashboard grouped by host with favicon auto-discovery
- Full-text search across name, URL, description, host, and category
- Filter by host or category
- Optional stored credentials (AES-encrypted at rest)
- MySQL/MariaDB backend with automatic schema creation on first request

## Requirements

- Python 3.12+
- MySQL or MariaDB

## Setup

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

Tables are created automatically on the first request. Navigate to `/` and follow the admin setup prompt.

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

The included `docker-compose.yml` builds the image locally. You will need an external MySQL/MariaDB instance reachable from the container; update `DB_HOST` in `.env` accordingly.

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

### First run

Once the container is running, navigate to `http://localhost:5000` (or your configured port). Tables are created automatically on the first request - follow the on-screen admin setup prompt.

## Third-Party Licenses

[Font Awesome Free](https://fontawesome.com) 7.1.0 is bundled under CC BY 4.0 (icons), SIL OFL 1.1 (fonts), and MIT (code). See `app/static/fontawesome-free-7.1.0-web/LICENSE.txt`.

[IBM Plex Sans](https://fonts.google.com/specimen/IBM+Plex+Sans) and [Space Grotesk](https://fonts.google.com/specimen/Space+Grotesk) are bundled under the SIL Open Font License 1.1. See `app/static/fonts/IBM_Plex_Sans/OFL.txt` and `app/static/fonts/Space_Grotesk/OFL.txt`.

## Credits

The UI was generated with Gemini 2.5 and refined with many manual and agentic adjustments.

## License

Licensed under the [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0).
