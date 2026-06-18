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

from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash


db = SQLAlchemy()


# many-to-many join table between webuis and categories
webui_categories = db.Table(
    "webui_categories",
    db.Column("webui_id", db.Integer, db.ForeignKey(
        "web_ui.id"), primary_key=True),
    db.Column("category_id", db.Integer, db.ForeignKey(
        "category.id"), primary_key=True),
    # Force InnoDB: MyISAM ignores transactions and FKs, and raises error 1020
    # ("Record has changed since last read") under the app's concurrent writes.
    mysql_engine="InnoDB",
)


class User(db.Model):
    __table_args__ = {"mysql_engine": "InnoDB"}

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True,
                         nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(
        timezone.utc), nullable=False)

    def set_password(self, password: str) -> None:
        # hashes and stores the password - never store plaintext
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        # compare a plaintext attempt against the stored hash
        return check_password_hash(self.password_hash, password)


class Host(db.Model):
    __table_args__ = {"mysql_engine": "InnoDB"}

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False, index=True)
    description = db.Column(db.Text)

    # back-ref so we can do host.webuis to get all linked services
    webuis = db.relationship("WebUI", back_populates="host")


class Category(db.Model):
    __table_args__ = {"mysql_engine": "InnoDB"}

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False, index=True)
    description = db.Column(db.Text)


class AppSetting(db.Model):
    __tablename__ = "app_setting"
    __table_args__ = {"mysql_engine": "InnoDB"}

    id = db.Column(db.Integer, primary_key=True, default=1)
    healthchecks_enabled = db.Column(db.Boolean, default=False, nullable=False)
    healthcheck_interval_minutes = db.Column(
        db.Integer, default=5, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False
    )

    # SMTP / email notification settings
    smtp_host = db.Column(db.String(255))
    smtp_port = db.Column(db.Integer, default=587, nullable=False)
    smtp_username = db.Column(db.String(255))
    smtp_password_encrypted = db.Column(db.Text)
    smtp_from_address = db.Column(db.String(255))
    smtp_to_address = db.Column(db.String(255))
    smtp_use_starttls = db.Column(db.Boolean, default=True, nullable=False)
    email_notifications_enabled = db.Column(db.Boolean, default=False, nullable=False)
    background_image_filename = db.Column(db.String(255))


class WebUI(db.Model):
    __tablename__ = "web_ui"
    __table_args__ = {"mysql_engine": "InnoDB"}

    SERVICE_TYPES = ("web", "api")

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False, index=True)
    service_type = db.Column(db.String(20), nullable=False, default="web")
    # capped at 768 chars - utf8mb4 is 4 bytes per char, 768*4 = 3072 which is the mysql index limit
    # nullable because non-web service types (database, other) may not have an HTTP URL
    url = db.Column(db.String(768), nullable=True, unique=True)
    description = db.Column(db.Text)
    favicon_url = db.Column(db.Text)
    healthcheck_url = db.Column(db.String(768))
    last_healthcheck_at = db.Column(db.DateTime)
    last_healthcheck_ok = db.Column(db.Boolean)
    last_healthcheck_status = db.Column(db.String(255))

    host_id = db.Column(db.Integer, db.ForeignKey(
        "host.id"), nullable=True, index=True)
    host = db.relationship("Host", back_populates="webuis")

    # stored credentials - password is encrypted at rest via fernet
    credential_username = db.Column(db.String(255))
    credential_password_encrypted = db.Column(db.Text)

    # use lambdas here so the timestamp is evaluated at insert/update time, not at class definition time
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(
        timezone.utc), nullable=False)
    updated_at = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False
    )

    # lazy=subquery loads categories in the same query to avoid n+1 on the dashboard
    categories = db.relationship(
        "Category", secondary=webui_categories, lazy="subquery")

    healthcheck_logs = db.relationship(
        "HealthCheckLog", back_populates="webui", cascade="all, delete-orphan", lazy="dynamic"
    )


class HealthCheckLog(db.Model):
    __tablename__ = "healthcheck_log"
    __table_args__ = {"mysql_engine": "InnoDB"}

    id = db.Column(db.Integer, primary_key=True)
    webui_id = db.Column(db.Integer, db.ForeignKey(
        "web_ui.id"), nullable=False, index=True)
    checked_at = db.Column(db.DateTime, nullable=False, index=True)
    is_ok = db.Column(db.Boolean, nullable=False)
    status_text = db.Column(db.String(255), nullable=False, default="")

    webui = db.relationship("WebUI", back_populates="healthcheck_logs")
