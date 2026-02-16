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

from threading import Lock

from flask import Flask, request

from .config import Config
from .models import db
from .routes import main_bp
from .auth import auth_bp, init_auth


# lock to prevent multiple threads from running create_all at the same time on startup
_schema_lock = Lock()


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    # flag so we only run schema creation once per process lifetime
    app.extensions["schema_ready"] = False

    @app.before_request
    def auto_migrate_schema() -> None:
        # skip if auto migrate is disabled or schema is already set up
        if not app.config.get("AUTO_MIGRATE", True):
            return
        # skip static file requests - no point acquiring the lock for those
        if request.path.startswith("/static/"):
            return
        if app.extensions.get("schema_ready"):
            return
        with _schema_lock:
            # double-check inside the lock in case another thread just finished
            if app.extensions.get("schema_ready"):
                return
            db.create_all()
            app.extensions["schema_ready"] = True

    init_auth(app)

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)

    @app.cli.command("init-db")
    def init_db() -> None:
        # manually trigger schema creation - useful if AUTO_MIGRATE is off
        with app.app_context():
            db.create_all()
        print("Database tables created.")

    @app.cli.command("create-admin")
    def create_admin() -> None:
        # cli helper to create an admin user without going through the web ui
        from getpass import getpass

        from .models import User

        with app.app_context():
            db.create_all()

        username = input("Username: ").strip()
        if not username:
            print("Username is required.")
            return

        existing = db.session.scalar(
            db.select(User).where(User.username == username))
        if existing:
            print("User already exists.")
            return

        password = getpass("Password: ")
        if not password:
            print("Password is required.")
            return

        user = User(username=username)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        print(f"Admin user '{username}' created.")

    return app
