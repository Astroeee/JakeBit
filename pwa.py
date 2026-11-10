"""Makes Jakebit an installable app (a PWA): the manifest, the service worker and the offline page."""
from flask import Blueprint, Response, jsonify, render_template, send_from_directory, current_app, url_for

bp = Blueprint("pwa", __name__)


@bp.route("/manifest.webmanifest")
def manifest():
    def icon(name, size, purpose="any"):
        return {"src": url_for("static", filename=f"icons/{name}"), "sizes": f"{size}x{size}",
                "type": "image/png", "purpose": purpose}
    data = {
        "id": "/", "name": "Jakebit", "short_name": "Jakebit",
        "description": "Build habits, keep streaks and cheer on your friends.",
        "start_url": "/", "scope": "/", "display": "standalone", "orientation": "portrait-primary",
        "background_color": "#fbf5f4", "theme_color": "#c32f0c",
        "icons": [icon("icon-192.png", 192), icon("icon-512.png", 512), icon("icon-maskable-512.png", 512, "maskable")],
        "shortcuts": [
            {"name": "Today", "url": "/"},
            {"name": "Add a habit", "url": "/habits"},
            {"name": "Calendar", "url": "/calendar"},
        ],
    }
    response = jsonify(data)
    response.mimetype = "application/manifest+json"
    return response


@bp.route("/sw.js")
def service_worker():
    # Served from the site root so it can control every page; never cached, so updates arrive quickly
    response = send_from_directory(current_app.static_folder, "js/sw.js", mimetype="text/javascript")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["Service-Worker-Allowed"] = "/"
    return response


@bp.route("/offline")
def offline():
    return render_template("offline.html")
