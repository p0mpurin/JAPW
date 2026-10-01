"""X / Twitter artists: session, artist list, and paged media (direct GraphQL, no browser)."""

import time

from flask import Blueprint, jsonify, request

import japw.x as xs
from japw.routes.common import body, error, int_arg

bp = Blueprint("x", __name__)


def _x_error(e: Exception):
    if isinstance(e, xs.XSessionError):
        return error(str(e), 401 if "session" in str(e).lower() or "connected" in str(e).lower() else 502)
    return error(str(e) or e.__class__.__name__, 502)


@bp.post("/x/auth/sync")
def x_auth_sync():
    try:
        xs.sync_x_session_from_browsers()
        xs.reload_x_session()
        return jsonify({"connected": True})
    except Exception as e:
        return error(str(e))


@bp.get("/x/auth/status")
def x_auth_status():
    return jsonify({"connected": xs.has_x_session()})


@bp.post("/x/auth/logout")
def x_auth_logout():
    xs.clear_x_session()
    return jsonify({"ok": True})


@bp.get("/x/artists")
def x_artists_list():
    return jsonify(xs.load_artists())


@bp.post("/x/artists")
def x_artists_add():
    username = (body().get("username") or "").strip().lstrip("@")
    if "x.com/" in username or "twitter.com/" in username:
        username = username.split(".com/", 1)[1].split("/")[0].split("?")[0]
    if not username or not username.replace("_", "").isalnum() or len(username) > 15:
        return error("That doesn't look like an X username")
    if xs.artist_exists(username):
        return error("already added", 409)
    artist = {"username": username, "display_name": username, "avatar_url": None, "added_at": int(time.time())}
    if xs.has_x_session():
        try:
            info = xs.fetch_user_info(username)
        except Exception as e:
            return _x_error(e)
        artist.update(username=info["username"], display_name=info["display_name"], avatar_url=info["avatar_url"])
    xs.add_artist(artist)
    return jsonify(artist), 201


@bp.delete("/x/artists/<username>")
def x_artists_remove(username):
    return jsonify({"ok": xs.remove_artist(username)})


@bp.get("/x/media")
def x_media():
    if not xs.has_x_session():
        return error("Not connected to X. Sync your X login in the Artists panel.", 401, code="x_not_connected")
    username = (request.args.get("username") or "").strip().lstrip("@") or None
    offset = int_arg("offset", 0, 0, 20000)
    limit = int_arg("limit", 40, 1, 200)
    refresh = request.args.get("refresh", "") in ("1", "true")
    try:
        posts, has_more = xs.media(username, offset, limit, refresh=refresh)
    except Exception as e:
        return _x_error(e)
    return jsonify({"posts": posts, "next_offset": offset + len(posts), "has_more": has_more})
