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

import os
from pathlib import Path

from dotenv import load_dotenv

# resolve the project root and load .env from there
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _env_bool(name: str, default: bool) -> bool:
    # parses common bool string values from env vars
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production")
    APP_CREDENTIALS_KEY = os.getenv("APP_CREDENTIALS_KEY")  # optional separate key for credential encryption
    AUTO_MIGRATE = _env_bool("AUTO_MIGRATE", True)
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # db conn vars
    _db_user = os.getenv("DB_USER", "root")
    _db_password = os.getenv("DB_PASSWORD", "password")
    _db_host = os.getenv("DB_HOST", "127.0.0.1")
    _db_port = os.getenv("DB_PORT", "3306")
    _db_name = os.getenv("DB_NAME", "webui_manager")

    # DATABASE_URL takes priority over the individual db vars
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        f"mysql+pymysql://{_db_user}:{_db_password}@{_db_host}:{_db_port}/{_db_name}?charset=utf8mb4",
    )

    # Connection-pool hardening. MySQL closes idle connections after wait_timeout
    # (and proxies/load balancers often much sooner), which surfaces as
    # "Lost connection to MySQL server during query" (2013) or "MySQL server has
    # gone away" (2006) on the next request that reuses a stale pooled connection.
    #   - pool_pre_ping issues a lightweight liveness check before handing out a
    #     connection and transparently reconnects if it's dead.
    #   - pool_recycle proactively discards connections older than the interval so
    #     we never reuse one the server has already timed out. Must stay below the
    #     server's wait_timeout; 280s sits safely under both the MySQL default and
    #     the common ~300s idle timeout on proxies.
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": int(os.getenv("DB_POOL_RECYCLE", "280")),
    }
