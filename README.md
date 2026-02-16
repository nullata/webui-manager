![webuiception](app/static/images/webuimuch.jpg "webuiception")

# WebUI Manager

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

# 4. Create the database
mysql -u root -p -e "CREATE DATABASE webui_manager CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"

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

## Project Structure

```
app/
├── __init__.py        # App factory, CLI commands
├── auth.py            # Login, logout, session auth, decorators
├── config.py          # Environment-based configuration
├── models.py          # SQLAlchemy models
├── routes.py          # CRUD routes
├── utils.py           # URL normalization, favicon resolution, encryption
├── static/
│   ├── css/
│   │   └── app.css            # Style overrides
│   ├── js/
│   │   └── app.js             # Client-side behaviour
│   └── images/
│       └── favicon.ico
└── templates/
    ├── base.html
    ├── partials/
    │   └── nav.html
    ├── login.html
    ├── setup_admin.html
    ├── webui_list.html
    ├── webui_form.html
    ├── hosts.html
    └── categories.html
run.py                 # Entry point
```

## Docker Hub

The image is published at [nullata/webui-manager](https://hub.docker.com/r/nullata/webui-manager).

```bash
docker pull nullata/webui-manager
```

Or use it directly in your `docker-compose.yml`:

```yaml
image: nullata/webui-manager
```

## Third-Party Licenses

[Font Awesome Free](https://fontawesome.com) 7.1.0 is bundled under CC BY 4.0 (icons), SIL OFL 1.1 (fonts), and MIT (code). See `app/static/fontawesome-free-7.1.0-web/LICENSE.txt`.

[IBM Plex Sans](https://fonts.google.com/specimen/IBM+Plex+Sans) and [Space Grotesk](https://fonts.google.com/specimen/Space+Grotesk) are bundled under the SIL Open Font License 1.1. See `app/static/fonts/IBM_Plex_Sans/OFL.txt` and `app/static/fonts/Space_Grotesk/OFL.txt`.

## Credits

The UI was generated with Gemini 2.5 and refined with many manual and agentic adjustments.

## License

Licensed under the [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0).
