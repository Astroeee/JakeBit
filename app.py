import os
from datetime import timedelta
from dotenv import load_dotenv
from flask import Flask, flash, g, redirect, url_for
from flask_wtf.csrf import CSRFProtect
import db

load_dotenv()  # reads SECRET_KEY etc. from your local .env file
csrf = CSRFProtect()

def create_app(test_config=None):
    app = Flask(__name__)
    # The secret key signs login cookies. It must come from the environment, never from the code.
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-only-change-me")
    app.config["DATABASE"] = os.path.join(app.root_path, "database", "database.db")
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)
    # Uploaded profile pictures live OUTSIDE the static folder, so they can't be fetched directly
    app.config["AVATAR_FOLDER"] = os.path.join(app.root_path, "uploads", "avatars")
    app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # reject any request over 5 MB
    # Cookie safety: scripts can't read it, and other sites can't send it along with their requests
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    # When we deploy over HTTPS, set PRODUCTION=1 so the cookie only travels over HTTPS
    app.config["SESSION_COOKIE_SECURE"] = os.environ.get("PRODUCTION") == "1"
    # In production we sit behind PythonAnywhere's load balancer, which puts the real
    # visitor address in the X-Real-IP header (used by rate limiting)
    app.config["TRUST_X_REAL_IP"] = os.environ.get("PRODUCTION") == "1"

    # Tests pass their own settings (temporary database, etc.), which replace the ones above
    if test_config:
        app.config.update(test_config)

    # In production, refuse to start with the built-in development key
    if os.environ.get("PRODUCTION") == "1" and app.config["SECRET_KEY"] == "dev-only-change-me":
        raise RuntimeError("Set a real SECRET_KEY in your .env file before running in production.")

    os.makedirs(os.path.dirname(app.config["DATABASE"]), exist_ok=True)

    db.init_app(app)
    csrf.init_app(app)

    from auth import bp as auth_bp
    from avatars import bp as avatars_bp
    from habits import bp as habits_bp
    from tracking import bp as tracking_bp
    from stats import bp as stats_bp
    from friends import bp as friends_bp
    from shared import bp as shared_bp
    from settings import bp as settings_bp, get_ui_settings
    from tracking import describe_schedule
    from recovery import bp as recovery_bp
    from pixelart import render_mascot
    from pixelscenes import render_scene
    app.register_blueprint(recovery_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(avatars_bp)
    app.register_blueprint(habits_bp)
    app.register_blueprint(tracking_bp)
    app.register_blueprint(stats_bp)
    app.register_blueprint(friends_bp)
    app.register_blueprint(shared_bp)
    app.register_blueprint(settings_bp)

    @app.context_processor
    def inject_ui():
        # Makes `ui` (theme, background, mascot...) available in every template
        return {"ui": get_ui_settings(), "schedule_label": describe_schedule}

    @app.context_processor
    def inject_notifications():
        """How many friend requests and shared-habit invitations are waiting for the
        logged-in user. The navigation shows these as little red badges."""
        user = getattr(g, "user", None)
        if user is None:
            return {"notify": {"friends": 0, "shared": 0}}
        conn = db.get_db()
        friends = conn.execute(
            "SELECT COUNT(*) FROM friendships WHERE addressee_id = ? AND status = 'pending'",
            (user["id"],),
        ).fetchone()[0]
        shared = conn.execute(
            "SELECT COUNT(*) FROM shared_members WHERE user_id = ? AND status = 'invited'",
            (user["id"],),
        ).fetchone()[0]
        return {"notify": {"friends": friends, "shared": shared}}

    @app.errorhandler(413)
    def file_too_large(error):
        flash("That file is too big. Please choose a picture under 5 MB.")
        return redirect(url_for("settings.settings"))

    app.jinja_env.globals["pixel_mascot"] = render_mascot
    app.jinja_env.globals["pixel_scene"] = render_scene
    
    return app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True)