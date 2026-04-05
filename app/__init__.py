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

from flask import Flask, render_template
from flask_wtf.csrf import CSRFProtect

from .config import Config
from .healthchecks import start_healthcheck_worker
from .models import db
from .routes import main_bp
from .auth import auth_bp, init_auth

csrf = CSRFProtect()


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    csrf.init_app(app)

    with app.app_context():
        db.create_all()

    init_auth(app)

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    start_healthcheck_worker(app)

    @app.cli.command("create-admin")
    def create_admin() -> None:
        # cli helper to create an admin user without going through the web ui
        from getpass import getpass

        from .models import User

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

################
# error handlers
################


    @app.errorhandler(404)
    def not_found(e):
        return render_template("error.html", error_code=404,
                               error_title="Not Found",
                               error_description="The page you're looking for doesn't exist."), 404

    @app.errorhandler(403)
    def forbidden(e):
        return render_template("error.html", error_code=403,
                               error_title="Forbidden",
                               error_description="You don't have permission to access this resource."), 403

    @app.errorhandler(405)
    def method_not_allowed(e):
        return render_template("error.html", error_code=405,
                               error_title="Method Not Allowed",
                               error_description="The request method is not supported for this endpoint."), 405

    @app.errorhandler(500)
    def internal_error(e):
        db.session.rollback()
        return render_template("error.html", error_code=500,
                               error_title="Internal Server Error",
                               error_description="Something went wrong on our end. Please try again later."), 500

    return app
