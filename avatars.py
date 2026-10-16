import os
import secrets
from html import escape
from flask import (Blueprint, Response, abort, current_app, flash, g, redirect,
                   request, send_from_directory, url_for)
from PIL import Image, ImageOps, UnidentifiedImageError
from werkzeug.exceptions import NotFound
from auth import login_required
from db import get_db
from friends import are_friends

bp = Blueprint("avatars", __name__)

ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
AVATAR_SIZE = 256
MAX_PIXELS = 25_000_000   # refuse absurdly large images ("decompression bombs")
PALETTE = ["#7c3aed", "#0284c7", "#ea580c", "#15803d", "#e11d48", "#0f766e", "#b45309", "#6366f1"]


def can_view_avatar(db, viewer_id, owner_id):
    """You can see your own picture, your accepted friends' pictures,
    and pictures of people in a shared habit you've both joined."""
    if viewer_id == owner_id or are_friends(db, viewer_id, owner_id):
        return True
    row = db.execute(
        "SELECT 1 FROM shared_members a JOIN shared_members b ON a.shared_id = b.shared_id "
        "WHERE a.user_id = ? AND b.user_id = ? AND a.status = 'joined' AND b.status = 'joined' LIMIT 1",
        (viewer_id, owner_id),
    ).fetchone()
    return row is not None


def placeholder(letter, color):
    """A colored circle-ready square with an initial, drawn on the fly as an SVG."""
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        f'<rect width="100" height="100" fill="{color}"/>'
        '<text x="50" y="50" dy=".35em" text-anchor="middle" '
        'font-family="system-ui, sans-serif" font-size="48" font-weight="700" fill="#fff">'
        f'{escape(letter)}</text></svg>'
    )
    return Response(svg, mimetype="image/svg+xml", headers={
        "Cache-Control": "private, no-cache", "X-Content-Type-Options": "nosniff"})


def delete_file(filename):
    """Remove an old avatar file. basename() makes sure we can never leave the avatar folder."""
    if filename:
        try:
            os.remove(os.path.join(current_app.config["AVATAR_FOLDER"], os.path.basename(filename)))
        except FileNotFoundError:
            pass


@bp.route("/avatar/<int:user_id>")
@login_required
def avatar(user_id):
    """Every avatar image on the site comes through here, so the permission check
    happens on every single request."""
    db = get_db()
    owner = db.execute("SELECT username, avatar FROM users WHERE id = ?", (user_id,)).fetchone()

    # Same answer for "doesn't exist" and "not allowed", so this can't be used to probe for accounts
    if owner is None or not can_view_avatar(db, g.user["id"], user_id):
        return placeholder("?", "#9ca3af")

    if owner["avatar"]:
        try:
            response = send_from_directory(
                current_app.config["AVATAR_FOLDER"], owner["avatar"], mimetype="image/jpeg")
            response.headers["Cache-Control"] = "private, no-cache"  # always check for a newer picture
            response.headers["X-Content-Type-Options"] = "nosniff"
            return response
        except NotFound:
            pass  # file went missing: fall through to the initial

    return placeholder(owner["username"][:1].upper(), PALETTE[user_id % len(PALETTE)])


@bp.route("/settings/avatar", methods=("POST",))
@login_required
def upload():
    file = request.files.get("avatar")
    if file is None or file.filename == "":
        flash("Please choose a picture first.")
        return redirect(url_for("settings.settings"))

    # We never trust the file name or extension. We open the bytes and see what they really are.
    try:
        img = Image.open(file.stream)
        if img.format not in ALLOWED_FORMATS:
            raise ValueError("unsupported format")
        if img.width * img.height > MAX_PIXELS:
            raise ValueError("image too large")
        img.load()                              # fully decode it; broken or fake files fail here
        img = ImageOps.exif_transpose(img)      # respect the phone camera's rotation
        if img.mode in ("RGBA", "LA", "P"):     # transparency: flatten onto white
            img = img.convert("RGBA")
            flat = Image.new("RGB", img.size, "white")
            flat.paste(img, mask=img.getchannel("A"))
            img = flat
        else:
            img = img.convert("RGB")
        img = ImageOps.fit(img, (AVATAR_SIZE, AVATAR_SIZE), Image.LANCZOS)  # centered square crop
    except (UnidentifiedImageError, ValueError, OSError, Image.DecompressionBombError):
        flash("That file isn't a valid JPG, PNG or WebP picture.")
        return redirect(url_for("settings.settings"))

    # Save a brand-new JPEG under a random name. Re-encoding also strips EXIF/GPS data.
    folder = current_app.config["AVATAR_FOLDER"]
    os.makedirs(folder, exist_ok=True)
    filename = secrets.token_hex(16) + ".jpg"
    img.save(os.path.join(folder, filename), "JPEG", quality=88, optimize=True)

    db = get_db()
    old = g.user["avatar"]
    db.execute("UPDATE users SET avatar = ? WHERE id = ?", (filename, g.user["id"]))
    db.commit()
    delete_file(old)
    flash("Profile picture updated!")
    return redirect(url_for("settings.settings"))


@bp.route("/settings/avatar/remove", methods=("POST",))
@login_required
def remove():
    db = get_db()
    old = g.user["avatar"]
    db.execute("UPDATE users SET avatar = NULL WHERE id = ?", (g.user["id"],))
    db.commit()
    delete_file(old)
    flash("Profile picture removed.")
    return redirect(url_for("settings.settings"))