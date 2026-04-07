import hashlib
import json
import os
import sys
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path as _Path
from urllib.parse import urlsplit as _urlsplit

import requests
from flask import Flask, request, jsonify, send_from_directory

from japw.config import load_config, save_config, load_likes, save_likes, load_collections, save_collections


def _posts_from_flat_urls(urls: list[str]) -> list[dict]:
    return [{"urls": [str(u)]} for u in urls if u]


def _search_posts_via_pinscrape(query: str) -> tuple[list[dict], str]:
    """Public Pinterest search (pinscrape); no cookies."""
    import japw.pinterest as ps

    pinterest = Pinterest()
    results = pinterest.search(query, page_size=50)
    urls = ps.dedupe_pinimg_urls([str(url) for url in results])
    return _posts_from_flat_urls(urls), "pinscrape"


def get_base_path() -> str:
    """Return the base path for bundled resources (handles PyInstaller frozen mode)."""
    if getattr(sys, "frozen", False):
        return sys._MEIPASS
    return os.path.abspath(".")


def create_app(config_path: str | None = None) -> Flask:
    base_path = get_base_path()
    frontend_path = os.path.join(base_path, "frontend")

    app = Flask(__name__, static_folder=frontend_path, static_url_path="")
    app.config["JAPW_CONFIG_PATH"] = config_path

    # Apply saved content filter settings and warm up home feed
    try:
        import japw.pinterest as _ps
        _cfg = load_config(config_path)
        _ps.set_content_filters(
            bool(_cfg.get("filter_promoted", True)),
            bool(_cfg.get("filter_ai_content", False)),
        )
        if _ps.has_session():
            threading.Thread(target=_ps.home_buf_warm_up, daemon=True).start()
    except Exception:
        pass

    def cfg_path() -> str | None:
        return app.config.get("JAPW_CONFIG_PATH")

    @app.route("/")
    def index():
        return send_from_directory(frontend_path, "index.html")

    @app.route("/api/search")
    def search():
        query = request.args.get("q", "").strip()
        if not query:
            return jsonify({"error": "Missing search query"}), 400

        import japw.pinterest as ps

        config = load_config(cfg_path())
        use_pinscrape = bool(config.get("search_use_pinscrape_when_logged_in"))
        if ps.has_session() and not use_pinscrape:
            try:
                posts = ps.fetch_search_image_urls(query)
            except ps.PinterestSessionError as e:
                return jsonify({"error": str(e)}), 502
            except Exception as e:
                return jsonify({"error": str(e)}), 502
            return jsonify({"posts": posts, "source": "session"})
        try:
            posts, src = _search_posts_via_pinscrape(query)
        except Exception as e:
            return jsonify({"error": str(e)}), 502
        return jsonify({"posts": posts, "source": src})

    @app.route("/api/home")
    def home():
        import japw.pinterest as ps

        if not ps.has_session():
            return jsonify(
                {
                    "error": "Not connected to Pinterest. Open Settings and sync from your browser.",
                }
            ), 401
        refresh = (request.args.get("refresh") or "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        try:
            posts = ps.fetch_home_image_urls(force_refresh=refresh)
        except ps.PinterestSessionError as e:
            return jsonify({"error": str(e)}), 502
        except Exception as e:
            return jsonify({"error": str(e)}), 502
        return jsonify({"posts": posts})

    @app.route("/api/home/more", methods=["POST"])
    def home_more():
        import japw.pinterest as ps

        if not ps.has_session():
            return jsonify({"error": "Not connected to Pinterest."}), 401
        data = request.get_json() or {}
        seen = data.get("seen_urls")
        if not isinstance(seen, list):
            return jsonify({"error": "seen_urls must be a list"}), 400
        try:
            keys = ps.canonical_keys_from_urls([str(u) for u in seen])
            posts = ps.fetch_home_more_image_urls(keys)
        except ps.PinterestSessionError as e:
            return jsonify({"error": str(e)}), 502
        except Exception as e:
            return jsonify({"error": str(e)}), 502
        return jsonify({"posts": posts, "has_more": len(posts) > 0})

    @app.route("/api/search/more", methods=["POST"])
    def search_more():
        import japw.pinterest as ps

        if not ps.has_session():
            return jsonify({"error": "Not connected to Pinterest."}), 401
        data = request.get_json() or {}
        q = (data.get("q") or "").strip()
        if not q:
            return jsonify({"error": "Missing query"}), 400
        seen = data.get("seen_urls")
        if not isinstance(seen, list):
            return jsonify({"error": "seen_urls must be a list"}), 400
        try:
            keys = ps.canonical_keys_from_urls([str(u) for u in seen])
            posts = ps.fetch_search_more_image_urls(q, keys)
        except ps.PinterestSessionError as e:
            return jsonify({"error": str(e)}), 502
        except Exception as e:
            return jsonify({"error": str(e)}), 502
        return jsonify({"posts": posts, "has_more": len(posts) > 0})

    @app.route("/api/boards")
    def boards_list():
        import japw.pinterest as ps

        if not ps.has_session():
            return jsonify({"error": "Not connected to Pinterest."}), 401
        config = load_config(cfg_path())
        raw_listing = (config.get("pinterest_boards_page_url") or "").strip()
        if not raw_listing:
            return jsonify(
                {
                    "error": "Set your Pinterest boards page URL in Settings (your profile or Saved boards page, not a single board).",
                    "code": "missing_boards_page_url",
                }
            ), 400
        listing = ps.normalize_boards_listing_page_url(raw_listing)
        if not ps.is_valid_boards_listing_page_url(listing):
            return jsonify(
                {
                    "error": "The boards page URL in Settings is invalid. Use your profile link (e.g. https://it.pinterest.com/yourname/) or pinterest.com/me/boards/. Do not use a link to a single board.",
                    "code": "invalid_boards_page_url",
                }
            ), 400
        try:
            boards = ps.fetch_my_boards_list(listing)
        except ps.PinterestSessionError as e:
            return jsonify({"error": str(e)}), 502
        except Exception as e:
            return jsonify({"error": str(e)}), 502
        return jsonify({"boards": boards})

    @app.route("/api/board_pins")
    def board_pins():
        import japw.pinterest as ps

        if not ps.has_session():
            return jsonify({"error": "Not connected to Pinterest."}), 401
        url = (request.args.get("url") or "").strip()
        if not url:
            return jsonify({"error": "Missing board url"}), 400
        if not ps.is_valid_user_board_url(url):
            return jsonify({"error": "Invalid board URL"}), 400
        try:
            posts = ps.fetch_board_pins(url)
        except ps.PinterestSessionError as e:
            return jsonify({"error": str(e)}), 502
        except Exception as e:
            return jsonify({"error": str(e)}), 502
        return jsonify({"posts": posts})

    @app.route("/api/board_pins/more", methods=["POST"])
    def board_pins_more():
        import japw.pinterest as ps

        if not ps.has_session():
            return jsonify({"error": "Not connected to Pinterest."}), 401
        data = request.get_json() or {}
        board_url = (data.get("board_url") or "").strip()
        if not board_url:
            return jsonify({"error": "Missing board_url"}), 400
        if not ps.is_valid_user_board_url(board_url):
            return jsonify({"error": "Invalid board URL"}), 400
        seen = data.get("seen_urls")
        if not isinstance(seen, list):
            return jsonify({"error": "seen_urls must be a list"}), 400
        try:
            keys = ps.canonical_keys_from_urls([str(u) for u in seen])
            posts = ps.fetch_board_pins_more(board_url, keys)
        except ps.PinterestSessionError as e:
            return jsonify({"error": str(e)}), 502
        except Exception as e:
            return jsonify({"error": str(e)}), 502
        return jsonify({"posts": posts, "has_more": len(posts) > 0})

    @app.route("/api/pin/related", methods=["POST"])
    def pin_related():
        import japw.pinterest as ps

        if not ps.has_session():
            return jsonify({"error": "Not connected to Pinterest."}), 401
        data = request.get_json() or {}
        pin_url = (data.get("pin_url") or "").strip()
        if not pin_url:
            return jsonify({"error": "Missing pin_url"}), 400
        if not ps.is_pin_page_url(pin_url):
            return jsonify({"error": "Invalid pin_url"}), 400
        exclude = data.get("exclude_urls")
        if exclude is not None and not isinstance(exclude, list):
            return jsonify({"error": "exclude_urls must be a list"}), 400
        try:
            posts = ps.fetch_pin_related_posts(
                pin_url, [str(u) for u in exclude] if exclude else None
            )
        except ps.PinterestSessionError as e:
            return jsonify({"error": str(e)}), 502
        except Exception as e:
            return jsonify({"error": str(e)}), 502
        return jsonify({"posts": posts})

    @app.route("/api/pin/resolve", methods=["POST"])
    def pin_resolve():
        """Map a feed cover image URL to a Pinterest /pin/{id}/ URL (for similar pins)."""
        import japw.pinterest as ps

        if not ps.has_session():
            return jsonify({"error": "Not connected to Pinterest."}), 401
        data = request.get_json() or {}
        cover = (data.get("cover_url") or "").strip()
        if not cover:
            return jsonify({"error": "Missing cover_url"}), 400
        try:
            pin_url = ps.resolve_pin_url_for_cover_image(cover)
        except ps.PinterestSessionError as e:
            return jsonify({"error": str(e)}), 502
        except Exception as e:
            return jsonify({"error": str(e)}), 502
        if not pin_url:
            return jsonify(
                {
                    "error": "Pin link not found. The image may have scrolled off your home feed. Scroll it into view and try again, or use Open pin on the card.",
                }
            ), 404
        return jsonify({"pin_url": pin_url})

    @app.route("/api/auth/status", methods=["GET"])
    def auth_status():
        import japw.pinterest as ps

        return jsonify(
            {
                "connected": ps.has_session(),
                "login_in_progress": ps.is_login_in_progress(),
                "last_error": ps.get_last_login_error(),
            }
        )

    @app.route("/api/auth/login", methods=["POST"])
    def auth_login():
        import japw.pinterest as ps

        if not ps.try_begin_sync():
            return jsonify({"error": "Sync already in progress"}), 409
        threading.Thread(target=ps.run_cookie_sync_thread_entry, daemon=True).start()
        return jsonify({"started": True})

    @app.route("/api/auth/open-browser", methods=["POST"])
    def auth_open_browser():
        webbrowser.open("https://www.pinterest.com/")
        return jsonify({"opened": True})

    @app.route("/api/auth/logout", methods=["POST"])
    def auth_logout():
        import japw.pinterest as ps

        ps.clear_session()
        return jsonify({"success": True})

    @app.route("/api/download", methods=["POST"])
    def download():
        data = request.get_json()
        url = data.get("url", "").strip() if data else ""
        if not url:
            return jsonify({"error": "Missing image URL"}), 400

        config = load_config(cfg_path())
        folder = config["download_folder"]
        os.makedirs(folder, exist_ok=True)

        try:
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
        except requests.RequestException as e:
            return jsonify({"error": str(e)}), 500

        ext = ".jpg"
        content_type = resp.headers.get("Content-Type", "")
        if "png" in content_type:
            ext = ".png"
        elif "gif" in content_type:
            ext = ".gif"
        elif "webp" in content_type:
            ext = ".webp"
        elif "mp4" in content_type or "video" in content_type:
            ext = ".mp4"

        try:
            stem = _Path(_urlsplit(url).path).stem
            date_str = datetime.now().strftime("%Y%m%d")
            base_name = f"pin_{date_str}_{stem[:14]}"
        except Exception:
            base_name = "pin_" + hashlib.md5(url.encode()).hexdigest()[:12]
        filename = base_name + ext
        filepath = os.path.join(folder, filename)

        with open(filepath, "wb") as f:
            f.write(resp.content)

        return jsonify({"success": True, "path": filepath})

    @app.route("/api/settings", methods=["GET"])
    def get_settings():
        config = load_config(cfg_path())
        return jsonify(config)

    @app.route("/api/settings", methods=["POST"])
    def update_settings():
        data = request.get_json() or {}
        config = load_config(cfg_path())
        if "download_folder" in data:
            config["download_folder"] = data["download_folder"]
        if "resolution_filter_enabled" in data:
            config["resolution_filter_enabled"] = bool(data["resolution_filter_enabled"])
        if "resolution_target_width" in data:
            try:
                w = int(data["resolution_target_width"])
                if 1 <= w <= 16384:
                    config["resolution_target_width"] = w
            except (TypeError, ValueError):
                pass
        if "resolution_target_height" in data:
            try:
                h = int(data["resolution_target_height"])
                if 1 <= h <= 16384:
                    config["resolution_target_height"] = h
            except (TypeError, ValueError):
                pass
        if "resolution_match_mode" in data:
            m = str(data["resolution_match_mode"]).lower().strip()
            if m in ("min", "exact"):
                config["resolution_match_mode"] = m
        if "search_use_pinscrape_when_logged_in" in data:
            config["search_use_pinscrape_when_logged_in"] = bool(
                data["search_use_pinscrape_when_logged_in"]
            )
        if "pinterest_boards_page_url" in data:
            import japw.pinterest as ps

            v = (data.get("pinterest_boards_page_url") or "").strip()
            if not v:
                config["pinterest_boards_page_url"] = ""
            else:
                nv = ps.normalize_boards_listing_page_url(v)
                if not ps.is_valid_boards_listing_page_url(nv):
                    return jsonify(
                        {
                            "success": False,
                            "error": "Invalid boards page URL. Paste your profile URL (the page that lists your boards), e.g. https://it.pinterest.com/yourname/. Do not paste a single board URL (…/yourname/board-name/).",
                        }
                    ), 400
                config["pinterest_boards_page_url"] = nv
        if "filter_promoted" in data:
            config["filter_promoted"] = bool(data["filter_promoted"])
        if "filter_ai_content" in data:
            config["filter_ai_content"] = bool(data["filter_ai_content"])
        save_config(cfg_path(), config)
        # Apply content filters immediately to the running session
        try:
            import japw.pinterest as _ps
            _ps.set_content_filters(
                bool(config.get("filter_promoted", True)),
                bool(config.get("filter_ai_content", False)),
            )
        except Exception:
            pass
        return jsonify({"success": True})

    def _pin_key(url: str) -> str:
        import re as _re
        u = str(url or "").split("?")[0].strip().lower()
        if "i.pinimg.com" not in u:
            d = u.rfind(".")
            return u[:d] if d != -1 else u
        m = _re.match(r"^https?://i\.pinimg\.com/[^/]+/(.+)$", u)
        if not m:
            return u
        path = m.group(1)
        dot = path.rfind(".")
        return path[:dot] if dot != -1 else path

    @app.route("/api/likes", methods=["GET"])
    def get_likes():
        data = load_likes(cfg_path())
        return jsonify({"posts": data.get("posts", [])})

    @app.route("/api/likes/toggle", methods=["POST"])
    def toggle_like():
        body = request.get_json() or {}
        urls = body.get("urls") or []
        if not urls:
            return jsonify({"error": "Missing urls"}), 400
        key = _pin_key(urls[0])
        data = load_likes(cfg_path())
        posts = data.get("posts", [])
        existing = next((i for i, p in enumerate(posts) if p.get("key") == key), None)
        if existing is not None:
            posts.pop(existing)
            liked = False
        else:
            import datetime
            posts.insert(0, {"key": key, "urls": [str(u) for u in urls], "liked_at": datetime.datetime.utcnow().isoformat()})
            liked = True
        data["posts"] = posts
        save_likes(cfg_path(), data)
        return jsonify({"liked": liked, "key": key})

    @app.route("/api/collections", methods=["GET"])
    def get_collections():
        data = load_collections(cfg_path())
        cols = data.get("collections", [])
        summary = [{"id": c["id"], "name": c["name"], "count": len(c.get("posts", [])),
                    "cover": c["posts"][0]["urls"][0] if c.get("posts") else None}
                   for c in cols]
        return jsonify({"collections": summary})

    @app.route("/api/collections", methods=["POST"])
    def create_collection():
        body = request.get_json() or {}
        name = (body.get("name") or "").strip()
        if not name:
            return jsonify({"error": "Missing name"}), 400
        import time, datetime
        col_id = str(int(time.time() * 1000))
        col = {"id": col_id, "name": name[:100], "created_at": datetime.datetime.utcnow().isoformat(), "posts": []}
        data = load_collections(cfg_path())
        data.setdefault("collections", []).append(col)
        save_collections(cfg_path(), data)
        return jsonify({"collection": {"id": col_id, "name": col["name"], "count": 0, "cover": None}})

    @app.route("/api/collections/<col_id>", methods=["PATCH"])
    def rename_collection(col_id):
        body = request.get_json() or {}
        name = (body.get("name") or "").strip()
        if not name:
            return jsonify({"error": "Missing name"}), 400
        data = load_collections(cfg_path())
        for c in data.get("collections", []):
            if c["id"] == col_id:
                c["name"] = name[:100]
                save_collections(cfg_path(), data)
                return jsonify({"success": True})
        return jsonify({"error": "Not found"}), 404

    @app.route("/api/collections/<col_id>", methods=["DELETE"])
    def delete_collection(col_id):
        data = load_collections(cfg_path())
        before = len(data.get("collections", []))
        data["collections"] = [c for c in data.get("collections", []) if c["id"] != col_id]
        if len(data["collections"]) == before:
            return jsonify({"error": "Not found"}), 404
        save_collections(cfg_path(), data)
        return jsonify({"success": True})

    @app.route("/api/collections/<col_id>/posts", methods=["GET"])
    def get_collection_posts(col_id):
        data = load_collections(cfg_path())
        for c in data.get("collections", []):
            if c["id"] == col_id:
                return jsonify({"posts": c.get("posts", []), "name": c["name"]})
        return jsonify({"error": "Not found"}), 404

    @app.route("/api/collections/<col_id>/posts", methods=["POST"])
    def add_to_collection(col_id):
        import datetime
        body = request.get_json() or {}
        urls = body.get("urls") or []
        if not urls:
            return jsonify({"error": "Missing urls"}), 400
        key = _pin_key(urls[0])
        data = load_collections(cfg_path())
        for c in data.get("collections", []):
            if c["id"] == col_id:
                posts = c.setdefault("posts", [])
                if not any(p.get("key") == key for p in posts):
                    posts.insert(0, {"key": key, "urls": [str(u) for u in urls],
                                     "added_at": datetime.datetime.utcnow().isoformat()})
                    save_collections(cfg_path(), data)
                return jsonify({"success": True})
        return jsonify({"error": "Not found"}), 404

    @app.route("/api/collections/<col_id>/posts", methods=["DELETE"])
    def remove_from_collection(col_id):
        body = request.get_json() or {}
        key = (body.get("key") or "").strip()
        if not key:
            return jsonify({"error": "Missing key"}), 400
        data = load_collections(cfg_path())
        for c in data.get("collections", []):
            if c["id"] == col_id:
                c["posts"] = [p for p in c.get("posts", []) if p.get("key") != key]
                save_collections(cfg_path(), data)
                return jsonify({"success": True})
        return jsonify({"error": "Not found"}), 404

    @app.route("/api/open-url", methods=["POST"])
    def open_url():
        body = request.get_json() or {}
        url = (body.get("url") or "").strip()
        url_lower = url.lower()
        allowed = (
            url_lower.startswith("https://i.pinimg.com/")
            or url_lower.startswith("https://www.pinterest.com/pin/")
            or url_lower.startswith("https://x.com/")
            or url_lower.startswith("https://twitter.com/")
            or url_lower.startswith("https://pbs.twimg.com/")
        )
        if not url or not allowed:
            return jsonify({"error": "Invalid url"}), 400
        webbrowser.open(url)
        return jsonify({"opened": True})

    # ─── X / Artists ──────────────────────────────────────────────────────────

    @app.route("/x/auth/sync", methods=["POST"])
    def x_auth_sync():
        import japw.x as xs
        try:
            xs.sync_x_session_from_browsers()
            xs.reload_x_session()
            return jsonify({"connected": True})
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/x/auth/status", methods=["GET"])
    def x_auth_status():
        import japw.x as xs
        return jsonify({"connected": xs.has_x_session()})

    @app.route("/x/auth/logout", methods=["POST"])
    def x_auth_logout():
        import japw.x as xs
        xs.clear_x_session()
        return jsonify({"ok": True})

    @app.route("/x/artists", methods=["GET"])
    def x_artists_list():
        import japw.x as xs
        return jsonify(xs.load_artists())

    @app.route("/x/artists", methods=["POST"])
    def x_artists_add():
        import japw.x as xs
        body = request.get_json(force=True) or {}
        username = (body.get("username") or "").strip().lstrip("@")
        if not username:
            return jsonify({"error": "username required"}), 400
        if not username.replace("_", "").replace(".", "").isalnum():
            return jsonify({"error": "invalid username"}), 400
        if xs.artist_exists(username):
            return jsonify({"error": "already added"}), 409
        artist = {
            "username": username,
            "display_name": username,
            "avatar_url": None,
            "added_at": int(time.time()),
        }
        xs.add_artist(artist)
        # Enrich display name + avatar in background — don't block the response
        def _enrich():
            try:
                info = xs.fetch_user_info(username)
                if info.get("display_name") or info.get("avatar_url"):
                    artist.update({
                        "display_name": info.get("display_name", username),
                        "avatar_url": info.get("avatar_url"),
                    })
                    xs.add_artist(artist)
            except Exception as e:
                print(f"[JAPW/x] enrich failed for {username}: {e}", file=sys.stderr)
        threading.Thread(target=_enrich, daemon=True).start()
        return jsonify(artist), 201

    @app.route("/x/artists/<username>", methods=["DELETE"])
    def x_artists_remove(username):
        import japw.x as xs
        removed = xs.remove_artist(username)
        return jsonify({"ok": removed})

    # Track background refresh state (scoped to app instance)
    _x_refresh_in_progress: set = set()
    _x_refresh_lock = threading.Lock()

    def _x_bg_refresh(usernames: list, xs) -> None:
        for uname in usernames:
            with _x_refresh_lock:
                if uname in _x_refresh_in_progress:
                    continue
                _x_refresh_in_progress.add(uname)
            try:
                posts = xs.fetch_user_media(uname)
                xs.update_media_cache(uname, posts)
                print(f"[JAPW/x] cached {len(posts)} posts for @{uname}", file=sys.stderr)
            except Exception as e:
                print(f"[JAPW/x] bg refresh failed for @{uname}: {e}", file=sys.stderr)
            finally:
                with _x_refresh_lock:
                    _x_refresh_in_progress.discard(uname)

    @app.route("/x/media", methods=["GET"])
    def x_media():
        import japw.x as xs
        username = (request.args.get("username") or "").strip().lstrip("@")
        force_refresh = request.args.get("refresh", "0") in ("1", "true")

        artists = xs.load_artists()
        if not artists:
            return jsonify({"posts": [], "has_session": xs.has_x_session(), "refreshing": False})

        targets = (
            [a for a in artists if a.get("username", "").lower() == username.lower()]
            if username else artists
        )

        all_posts: list = []
        stale: list = []

        for artist in targets:
            uname = artist["username"]
            cached = xs.get_cached_artist_posts(uname)
            if cached is not None and not force_refresh:
                all_posts.extend(cached)
            else:
                # Return stale data immediately while refreshing in background
                all_posts.extend(xs.get_stale_cached_posts(uname))
                stale.append(uname)

        refreshing = False
        if stale and xs.has_x_session():
            with _x_refresh_lock:
                to_refresh = [u for u in stale if u not in _x_refresh_in_progress]
            if to_refresh:
                refreshing = True
                threading.Thread(
                    target=_x_bg_refresh, args=(to_refresh, xs), daemon=True
                ).start()
            else:
                refreshing = True  # already in progress from a prior request

        with _x_refresh_lock:
            in_prog = list(_x_refresh_in_progress)
        return jsonify({
            "posts": all_posts,
            "errors": [],
            "has_session": xs.has_x_session(),
            "refreshing": refreshing,
            "refreshing_usernames": in_prog,
        })

    @app.route("/x/media/refresh-status", methods=["GET"])
    def x_media_refresh_status():
        with _x_refresh_lock:
            in_progress = list(_x_refresh_in_progress)
        return jsonify({"refreshing": bool(in_progress), "usernames": in_progress})

    @app.route("/x/artists/<username>/info", methods=["GET"])
    def x_artist_info(username):
        """Fetch latest display name + avatar for an artist (called after enrich completes)."""
        import japw.x as xs
        artists = xs.load_artists()
        match = next((a for a in artists if a.get("username", "").lower() == username.lower()), None)
        if not match:
            return jsonify({"error": "not found"}), 404
        return jsonify(match)

    # ─── Export / Import ──────────────────────────────────────────────────────

    @app.route("/api/export", methods=["GET"])
    def export_data():
        import japw.x as xs
        bundle = {
            "version": 1,
            "exported_at": datetime.utcnow().isoformat() + "Z",
            "settings": load_config(cfg_path()),
            "likes": load_likes(cfg_path()),
            "collections": load_collections(cfg_path()),
            "x_artists": xs.load_artists(),
        }
        from flask import Response
        return Response(
            json.dumps(bundle, indent=2, ensure_ascii=False),
            mimetype="application/json",
            headers={"Content-Disposition": 'attachment; filename="japw_backup.json"'},
        )

    @app.route("/api/import", methods=["POST"])
    def import_data():
        import japw.x as xs
        body = request.get_json(silent=True)
        if not body or not isinstance(body, dict):
            return jsonify({"error": "Invalid backup file"}), 400
        if body.get("version") != 1:
            return jsonify({"error": "Unsupported backup version"}), 400

        errors = []

        if "settings" in body and isinstance(body["settings"], dict):
            try:
                existing = load_config(cfg_path())
                merged = {**existing, **body["settings"]}
                save_config(cfg_path(), merged)
            except Exception as e:
                errors.append(f"settings: {e}")

        if "likes" in body and isinstance(body["likes"], dict):
            try:
                save_likes(cfg_path(), body["likes"])
            except Exception as e:
                errors.append(f"likes: {e}")

        if "collections" in body and isinstance(body["collections"], dict):
            try:
                save_collections(cfg_path(), body["collections"])
            except Exception as e:
                errors.append(f"collections: {e}")

        if "x_artists" in body and isinstance(body["x_artists"], list):
            try:
                xs.save_artists(body["x_artists"])
            except Exception as e:
                errors.append(f"x_artists: {e}")

        if errors:
            return jsonify({"success": False, "errors": errors}), 207
        return jsonify({"success": True})

    return app
