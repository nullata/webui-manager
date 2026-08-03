# Tests

```bash
pip install -r requirements-dev.txt
playwright install chromium          # one-off, for the browser tests

pytest                               # everything
pytest -m "not browser"              # API/DB only, no browser needed (~20s)
pytest -m browser                    # browser tests only
```

Tests run against a temporary SQLite database created per session; every test
gets an empty schema (`clean_db` in `conftest.py`). Nothing touches your `.env`
or real database — `conftest.py` sets `DB_TYPE`/`DB_PATH`/`SECRET_KEY` at import
time, which it must do *before* anything imports the app, since `app/config.py`
resolves the database URL at import.

| File | Covers |
|---|---|
| `test_dashboard_search.py` | Server-side search in both modes, and that the two implementations agree |
| `test_credentials.py` | Credentials endpoint, including the decrypt-failure signal |
| `test_backup_restore.py` | JSON export/import, round trip, malformed input |
| `test_auto_migration.py` | Startup schema migration (SQLite subset) |
| `test_favicon_backfill.py` | Post-import favicon thread |
| `test_browser_*.py` | Live search UI, Ctrl+K, credential copy/reveal |

## Two things worth knowing

**The favicon backfill is stubbed by default.** It is a daemon thread that
outlives the test that started it, so it would hit the network for every
imported service and then write to tables `clean_db` has already dropped. Tests
that want the real thing carry `@pytest.mark.real_favicon_backfill`.

**One browser test runs over a LAN address, not localhost.** Browsers treat
`127.0.0.1` as a *potentially trustworthy* origin, so `isSecureContext` is true
there and `navigator.clipboard` exists. Most self-hosted installs are served
over plain HTTP on a LAN IP, where it does not — and the copy button falls back
to `execCommand`. `test_copy_falls_back_on_an_insecure_origin` is the only test
that exercises that path; it skips if the machine has no non-loopback address.
