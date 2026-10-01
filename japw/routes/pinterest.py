"""Pinterest feeds (home, search, boards, related) and the browser-cookie session."""

import threading
import webbrowser

from flask import Blueprint, jsonify, request

import japw.pinterest as ps
from japw.colors import BUCKETS
from japw.config import load_config
from japw.routes.common import body, cfg_path, error, int_arg, pinterest_error

bp = Blueprint("pinterest", __name__)

NOT_CONNECTED = "Not connected to Pinterest. Open Settings and sync from your browser."


def _page(posts: list[dict], offset: int, has_more: bool, **extra):
    return jsonify({"posts": posts, "next_offset": offset + len(posts), "has_more": has_more, **extra})


def _color_arg() -> str | None:
    c = (request.args.get("color") or "").strip().lower()
    return c if c in BUCKETS else None


def _refresh_arg() -> bool:
    return request.args.get("refresh", "").lower() in ("1", "true", "yes", "on")


@bp.get("/api/home")
def home():
    if not ps.has_session():
        return error(NOT_CONNECTED, 401)
    offset = int_arg("offset", 0, 0, 20000)
    limit = int_arg("limit", 50, 1, 200)
    try:
        posts, has_more = ps.home(offset, limit, refresh=_refresh_arg(), color=_color_arg())
    except Exception as e:
        return pinterest_error(e)
    return _page(posts, offset, has_more)


@bp.get("/api/foryou")
def for_you():
    if not ps.has_session():
        return error(NOT_CONNECTED, 401)
    offset = int_arg("offset", 0, 0, 20000)
    limit = int_arg("limit", 50, 1, 200)
    try:
        posts, has_more, personalised = ps.for_you(offset, limit, refresh=_refresh_arg(), color=_color_arg())
    except Exception as e:
        return pinterest_error(e)
    return _page(posts, offset, has_more, personalised=personalised)


def _search_logged_out(query: str):
    """Public search via pinscrape (no cookies, a single page). Imported lazily: it's slow to load."""
    from pinscrape import Pinterest

    results = Pinterest().search(query, page_size=50)
    urls = ps.dedupe_pinimg_urls([str(u) for u in results])
    return [{"urls": [u]} for u in urls]


@bp.get("/api/search")
def search():
    query = request.args.get("q", "").strip()
    if not query:
        return error("Missing search query")
    offset = int_arg("offset", 0, 0, 5000)
    limit = int_arg("limit", 50, 1, 200)
    use_pinscrape = bool(load_config(cfg_path()).get("search_use_pinscrape_when_logged_in"))
    if ps.has_session() and not use_pinscrape:
        try:
            posts, has_more = ps.search(query, offset, limit, color=_color_arg())
        except Exception as e:
            return pinterest_error(e)
        return _page(posts, offset, has_more, source="session")
    if offset:
        return _page([], offset, False, source="pinscrape")
    try:
        posts = _search_logged_out(query)
    except Exception as e:
        return error(str(e), 502)
    return _page(posts, 0, False, source="pinscrape")


@bp.post("/api/search/prefetch")
def search_prefetch():
    """Warm a query's first page while the user is still typing."""
    query = (body().get("q") or "").strip()
    if query and len(query) >= 2:
        threading.Thread(target=ps.prefetch_search, args=(query,), daemon=True).start()
    return jsonify({"ok": True})


@bp.get("/api/search/suggest")
def search_suggest():
    term = request.args.get("q", "").strip()
    try:
        return jsonify({"suggestions": ps.suggestions(term) if term else []})
    except Exception:
        return jsonify({"suggestions": []})


@bp.post("/api/pin/related")
def pin_related():
    if not ps.has_session():
        return error("Not connected to Pinterest.", 401)
    pin_url = (body().get("pin_url") or "").strip()
    pin_id = pin_url.rstrip("/").rsplit("/", 1)[-1]
    if not pin_url:
        return error("Missing pin_url")
    if "pinterest." not in pin_url or "/pin/" not in pin_url or not pin_id.isdigit():
        return error("Invalid pin_url")
    exclude = {ps.canonical_key(str(u)) for u in (body().get("exclude_urls") or [])}
    try:
        posts = ps.related(pin_id)
    except Exception as e:
        return pinterest_error(e)
    return jsonify({"posts": [p for p in posts if ps.canonical_key(p["urls"][0]) not in exclude]})


@bp.get("/api/boards")
def boards():
    if not ps.has_session():
        return error("Not connected to Pinterest.", 401)
    try:
        return jsonify({"boards": ps.my_boards(force=request.args.get("refresh") == "1")})
    except Exception as e:
        return pinterest_error(e)


@bp.get("/api/boards/<board_id>/pins")
def board_pins(board_id):
    if not ps.has_session():
        return error("Not connected to Pinterest.", 401)
    if not board_id.isdigit():
        return error("Invalid board id")
    offset = int_arg("offset", 0, 0, 20000)
    limit = int_arg("limit", 50, 1, 200)
    try:
        posts, has_more = ps.board_pins(board_id, request.args.get("url", ""), offset, limit)
    except Exception as e:
        return pinterest_error(e)
    return _page(posts, offset, has_more)


# ─── Visual search ───

@bp.post("/api/visual")
def visual_start():
    """Start a search by image: multipart field "image", or JSON {"url": "https://…"}."""
    from japw import visual

    try:
        if "image" in request.files:
            data = request.files["image"].read(visual.MAX_BYTES + 1)
            if len(data) > visual.MAX_BYTES:
                return error("That image is too large.")
        else:
            url = (body().get("url") or "").strip()
            if not url:
                return error("Send an image file or an image URL")
            data = visual.fetch_image(url)
        return jsonify({"id": visual.start(data)})
    except visual.VisualSearchError as e:
        return error(str(e), 422)
    except Exception as e:
        return error(str(e), 502)


@bp.get("/api/visual/<search_id>")
def visual_page(search_id):
    from japw import visual

    offset = int_arg("offset", 0, 0, 5000)
    limit = int_arg("limit", 50, 1, 200)
    try:
        posts, has_more = visual.page(search_id, offset, limit)
    except visual.VisualSearchError as e:
        return error(str(e), 404)
    except Exception as e:
        return pinterest_error(e)
    return _page(posts, offset, has_more)


# ─── Session ───

@bp.get("/api/auth/status")
def auth_status():
    return jsonify({
        "connected": ps.has_session(),
        "login_in_progress": ps.is_login_in_progress(),
        "last_error": ps.get_last_login_error(),
    })


@bp.post("/api/auth/login")
def auth_login():
    if not ps.try_begin_sync():
        return error("Sync already in progress", 409)
    threading.Thread(target=ps.run_cookie_sync_thread_entry, daemon=True).start()
    return jsonify({"started": True})


@bp.post("/api/auth/open-browser")
def auth_open_browser():
    webbrowser.open("https://www.pinterest.com/")
    return jsonify({"opened": True})


@bp.post("/api/auth/logout")
def auth_logout():
    ps.clear_session()
    return jsonify({"success": True})
