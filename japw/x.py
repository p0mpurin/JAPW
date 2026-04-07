"""
X (Twitter) artist media scraper for JAPW.

Cookie loading mirrors pinterest_session exactly:
  - Individual per-browser loaders (no browser_cookie3.load() which trips on IE)
  - Explicit Zen / Firefox-fork profile paths via cookie_file= parameter
  - Storage-state JSON file so Playwright gets a full authenticated context
  - Same timestamp-normalisation logic for Firefox/Zen PRTime microseconds

Scraping mirrors pinterest_session:
  - Navigate to /media tab → intercept GraphQL JSON responses
  - Handles both UserMedia (logged-in) and UserTweets (fallback)
  - Handles timeline_v2.timeline (UserMedia) and timeline (UserTweets)
"""

from __future__ import annotations

import json
import os
import queue as _queue
import re
import sys
import threading
from http.cookiejar import Cookie
from pathlib import Path
from typing import Any

from japw.config import get_app_data_dir

# ─── Storage ──────────────────────────────────────────────────────────────────

def get_x_storage_path() -> Path:
    return get_app_data_dir() / "x_state.json"


def _artists_path() -> Path:
    return get_app_data_dir() / "x_artists.json"


def _media_cache_path() -> Path:
    return get_app_data_dir() / "x_media_cache.json"


def has_x_session() -> bool:
    p = get_x_storage_path()
    return p.is_file() and p.stat().st_size > 10


def clear_x_session() -> None:
    p = get_x_storage_path()
    if p.exists():
        p.unlink()


# ─── Artist persistence ───────────────────────────────────────────────────────

def load_artists() -> list[dict[str, Any]]:
    p = _artists_path()
    if not p.exists():
        return []
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_artists(artists: list[dict[str, Any]]) -> None:
    p = _artists_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(artists, f, ensure_ascii=False, indent=2)


def artist_exists(username: str) -> bool:
    ul = username.lower()
    return any(a.get("username", "").lower() == ul for a in load_artists())


def add_artist(artist: dict[str, Any]) -> None:
    artists = load_artists()
    ul = artist["username"].lower()
    for i, a in enumerate(artists):
        if a.get("username", "").lower() == ul:
            artists[i] = artist
            save_artists(artists)
            return
    artists.append(artist)
    save_artists(artists)


def remove_artist(username: str) -> bool:
    artists = load_artists()
    new = [a for a in artists if a.get("username", "").lower() != username.lower()]
    if len(new) == len(artists):
        return False
    save_artists(new)
    return True


# ─── Media cache ──────────────────────────────────────────────────────────────

_CACHE_TTL = 3600  # 1 hour


def _load_media_cache() -> dict:
    p = _media_cache_path()
    if p.is_file():
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_media_cache(cache: dict) -> None:
    p = _media_cache_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)


def get_cached_artist_posts(username: str) -> list[dict] | None:
    """Return cached posts if fresh, else None."""
    import time
    cache = _load_media_cache()
    entry = cache.get(username.lower())
    if not entry:
        return None
    if time.time() - entry.get("fetched_at", 0) > _CACHE_TTL:
        return None
    return entry.get("posts", [])


def get_stale_cached_posts(username: str) -> list[dict]:
    """Return cached posts regardless of age (used as instant fallback)."""
    cache = _load_media_cache()
    entry = cache.get(username.lower())
    return entry.get("posts", []) if entry else []


def update_media_cache(username: str, posts: list[dict]) -> None:
    import time
    cache = _load_media_cache()
    cache[username.lower()] = {"posts": posts, "fetched_at": int(time.time())}
    _save_media_cache(cache)


def invalidate_media_cache(username: str | None = None) -> None:
    if username is None:
        p = _media_cache_path()
        if p.exists():
            p.unlink()
    else:
        cache = _load_media_cache()
        cache.pop(username.lower(), None)
        _save_media_cache(cache)


# ─── Cookie gathering (mirrors _gather_pinterest_cookies) ─────────────────────

_X_DOMAINS = (".x.com", ".twitter.com", "x.com", "twitter.com")


def _is_x_domain(domain: str) -> bool:
    d = (domain or "").lower().lstrip(".")
    return d in ("x.com", "twitter.com")


def _firefox_fork_profile_roots() -> list[Path]:
    """Zen, Floorp, Waterfox, etc. — same list as pinterest_session."""
    appdata = Path(os.environ.get("APPDATA", ""))
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    roots: list[Path] = []
    vendors = ("zen", "Zen", "zen-browser", "Zen Browser", "floorp", "Floorp", "Waterfox")
    for vendor in vendors:
        for base in (appdata, local):
            profiles = base / vendor / "Profiles"
            if profiles.is_dir():
                roots.append(profiles)
    return roots


def _iter_cookies_sqlite_files(profile_roots: list[Path]) -> list[Path]:
    files: list[Path] = []
    for parent in profile_roots:
        try:
            for sub in parent.iterdir():
                if not sub.is_dir():
                    continue
                cf = sub / "cookies.sqlite"
                if cf.is_file():
                    files.append(cf)
        except OSError:
            pass
    return files


def _gather_x_cookies() -> list[Cookie]:
    try:
        import browser_cookie3 as bc3
    except ImportError as e:
        raise RuntimeError(
            "Missing browser-cookie3 package. Run: pip install browser-cookie3"
        ) from e

    by_key: dict[tuple[str, str, str], Cookie] = {}
    loader_names = (
        "chrome", "chromium", "edge", "brave",
        "opera", "opera_gx", "vivaldi", "firefox",
        "safari", "librewolf",
    )

    def add_from(iterator) -> None:
        try:
            for c in iterator:
                dom = getattr(c, "domain", "") or ""
                if not _is_x_domain(dom):
                    continue
                key = (c.name, dom, getattr(c, "path", None) or "/")
                by_key[key] = c
        except Exception:
            pass

    # Standard browser loaders
    for name in loader_names:
        loader = getattr(bc3, name, None)
        if not callable(loader):
            continue
        try:
            add_from(loader(domain_name="x.com"))
        except Exception:
            pass
        try:
            add_from(loader(domain_name="twitter.com"))
        except Exception:
            pass

    # Zen / Firefox forks — explicit cookies.sqlite paths
    for sqlite_path in _iter_cookies_sqlite_files(_firefox_fork_profile_roots()):
        try:
            add_from(bc3.firefox(cookie_file=str(sqlite_path), domain_name="x.com"))
        except Exception:
            try:
                add_from(bc3.firefox(cookie_file=str(sqlite_path)))
            except Exception:
                pass
        try:
            add_from(bc3.firefox(cookie_file=str(sqlite_path), domain_name="twitter.com"))
        except Exception:
            pass

    return list(by_key.values())


def _playwright_cookie_expires(raw) -> int:
    """Same normalisation as pinterest_session — handles ms/µs timestamps."""
    import math
    if raw is None:
        return -1
    try:
        exp = float(raw)
    except (TypeError, ValueError):
        return -1
    if not math.isfinite(exp) or exp <= 0:
        return -1
    # Reasonable Unix seconds < ~4.1e9 (year 2100).
    # Larger values are ms or µs from Firefox/Zen PRTime.
    if exp > 4_102_441_920:
        if exp > 1e14:
            exp = exp / 1_000_000.0   # µs → s
        elif exp > 1e11:
            exp = exp / 1000.0        # ms → s
    try:
        exp_i = int(exp)
    except (OverflowError, ValueError):
        return -1
    return exp_i if exp_i > 0 else -1


def _cookie_to_playwright_entry(c: Cookie) -> dict:
    domain = c.domain or ".x.com"
    if not domain.startswith("."):
        domain = "." + domain
    path = c.path or "/"
    expires = _playwright_cookie_expires(getattr(c, "expires", None))
    http_only = False
    rest = getattr(c, "_rest", None)
    if isinstance(rest, dict) and rest.get("HttpOnly"):
        http_only = True
    return {
        "name": c.name,
        "value": c.value,
        "domain": domain,
        "path": path,
        "expires": expires,
        "httpOnly": http_only,
        "secure": bool(getattr(c, "secure", False)),
        "sameSite": "None",
    }


def _cookies_to_storage_state(cookies: list[Cookie]) -> dict:
    by_key: dict[tuple, dict] = {}
    for c in cookies:
        entry = _cookie_to_playwright_entry(c)
        k = (entry["name"], entry["domain"], entry["path"])
        by_key[k] = entry
    # Fix any bad expires values
    fixed = []
    for e in by_key.values():
        ec = dict(e)
        ec["expires"] = _playwright_cookie_expires(ec.get("expires"))
        fixed.append(ec)
    return {"cookies": fixed, "origins": []}


def sync_x_session_from_browsers() -> None:
    """
    Read X/Twitter cookies from installed browsers (including Zen) and
    write a Playwright storage-state JSON. Same flow as Pinterest sync.
    """
    cookies = _gather_x_cookies()
    if not cookies:
        raise RuntimeError(
            "No X/Twitter cookies found. Make sure you are logged in to x.com "
            "in Zen (or another supported browser), close the browser completely "
            "so cookies.sqlite is not locked, then click Sync again."
        )
    state = _cookies_to_storage_state(cookies)
    if not state["cookies"]:
        raise RuntimeError(
            "Found cookies but none were usable. "
            "Log in to x.com in Zen Browser and retry."
        )
    path = get_x_storage_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f)
    auth_names = {c["name"] for c in state["cookies"]}
    print(
        f"[JAPW/x] Saved {len(state['cookies'])} cookies "
        f"(auth_token={'auth_token' in auth_names})",
        file=sys.stderr,
    )


# ─── Playwright worker ────────────────────────────────────────────────────────

_x_queue: "_queue.Queue" = _queue.Queue()
_x_worker_thread: threading.Thread | None = None
_x_worker_lock = threading.Lock()
_X_SHUTDOWN = object()
_X_RELOAD = object()


def _x_context_options() -> dict:
    opts: dict[str, Any] = {
        "viewport": {"width": 1280, "height": 900},
        "locale": "en-US",
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
    }
    p = get_x_storage_path()
    if p.is_file():
        opts["storage_state"] = str(p)
    return opts


def _x_worker_main() -> None:
    from playwright.sync_api import sync_playwright

    pw = br = ctx = None

    def _boot() -> None:
        nonlocal pw, br, ctx
        pw = sync_playwright().__enter__()
        br = pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"],
        )
        ctx = br.new_context(**_x_context_options())
        print("[JAPW/x] X browser worker started", file=sys.stderr)

    def _close_all() -> None:
        nonlocal pw, br, ctx
        for obj, meth in ((ctx, "close"), (br, "close")):
            if obj is not None:
                try:
                    getattr(obj, meth)()
                except Exception:
                    pass
        if pw is not None:
            try:
                pw.__exit__(None, None, None)
            except Exception:
                pass
        pw = br = ctx = None

    try:
        _boot()
    except Exception as boot_err:
        print(f"[JAPW/x] boot failed: {boot_err}", file=sys.stderr)
        while True:
            item = _x_queue.get()
            if item is _X_SHUTDOWN or item is None:
                return
            if item is _X_RELOAD:
                continue
            _, rq = item
            rq.put(("err", boot_err))
        return

    while True:
        item = _x_queue.get()
        if item is _X_SHUTDOWN or item is None:
            _close_all()
            return
        if item is _X_RELOAD:
            # Recreate context after a new session sync
            try:
                if ctx:
                    ctx.close()
            except Exception:
                pass
            try:
                ctx = br.new_context(**_x_context_options())
            except Exception as e:
                print(f"[JAPW/x] reload context error: {e}", file=sys.stderr)
            continue
        fn, result_q = item
        try:
            result_q.put(("ok", fn(ctx)))
        except Exception as e:
            result_q.put(("err", e))


def _x_ensure_worker() -> None:
    global _x_worker_thread
    with _x_worker_lock:
        if _x_worker_thread is None or not _x_worker_thread.is_alive():
            _x_worker_thread = threading.Thread(
                target=_x_worker_main, daemon=True, name="x-browser-worker"
            )
            _x_worker_thread.start()


def _x_run(fn) -> Any:
    _x_ensure_worker()
    rq: _queue.Queue = _queue.Queue(maxsize=1)
    _x_queue.put((fn, rq))
    status, value = rq.get()
    if status == "err":
        raise value
    return value


def reload_x_session() -> None:
    """Tell the worker to reload its browser context with fresh storage state."""
    _x_ensure_worker()
    _x_queue.put(_X_RELOAD)


# ─── GraphQL response matchers ────────────────────────────────────────────────

def _is_media_response(url: str, content_type: str | None) -> bool:
    """
    Match UserMedia (logged-in media tab) and UserTweets (unauthenticated
    fallback). Domain is now api.x.com — but /graphql/ is always present.
    """
    return (
        ("UserMedia" in url or "UserTweets" in url)
        and "/graphql/" in url
        and "application/json" in (content_type or "")
    )


def _is_user_response(url: str, content_type: str | None) -> bool:
    return (
        "UserByScreenName" in url
        and "/graphql/" in url
        and "application/json" in (content_type or "")
    )


# ─── GraphQL parsers ──────────────────────────────────────────────────────────

def _unwrap_tweet(tweet_result: dict) -> dict | None:
    """Unwrap TweetWithVisibilityResults and return the tweet if it has legacy data."""
    if not tweet_result:
        return None
    if tweet_result.get("__typename") == "TweetWithVisibilityResults":
        tweet_result = tweet_result.get("tweet", tweet_result)
    return tweet_result if tweet_result.get("legacy") else None


def _tweet_from_entry(entry: dict) -> dict | None:
    """Extract tweet from a TimelineAddEntries entry (regular timeline)."""
    content = entry.get("content") or {}
    item_content = content.get("itemContent", {})
    result = item_content.get("tweet_results", {}).get("result", {})
    return _unwrap_tweet(result)


def _tweet_from_module_item(mod_item: dict) -> dict | None:
    """Extract tweet from a TimelineAddToModule moduleItem (media grid)."""
    item_content = mod_item.get("item", {}).get("itemContent", {})
    result = item_content.get("tweet_results", {}).get("result", {})
    return _unwrap_tweet(result)


def _parse_media_response(
    body: dict,
    username: str,
    seen_ids: set[str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    posts: list[dict[str, Any]] = []
    user_info: dict[str, Any] = {}

    try:
        user_result = (
            body.get("data", {})
            .get("user", {})
            .get("result", {})
        )

        # User info — present on UserByScreenName; UserMedia only has __typename + timeline
        legacy_u = user_result.get("legacy", {})
        if legacy_u:
            user_info = {
                "username": legacy_u.get("screen_name", username),
                "display_name": legacy_u.get("name", username),
                "avatar_url": (
                    (legacy_u.get("profile_image_url_https") or "")
                    .replace("_normal", "_400x400") or None
                ),
            }

        # Path varies by endpoint:
        #   UserMedia  → result.timeline.timeline.instructions   (nested timeline)
        #   UserTweets → result.timeline.instructions            (single timeline)
        #   Old API    → result.timeline_v2.timeline.instructions
        outer = (
            user_result.get("timeline_v2")
            or user_result.get("timeline")
            or {}
        )
        tl = outer.get("timeline") or outer  # handle both nested and flat
        instructions = tl.get("instructions", [])

        for instr in instructions:
            instr_type = instr.get("type", "")

            if instr_type == "TimelineAddEntries":
                # Regular timeline — items live in entry.content.itemContent
                for entry in instr.get("entries", []):
                    tweet = _tweet_from_entry(entry)
                    _collect_tweet(tweet, username, seen_ids, posts, user_info)

            elif instr_type == "TimelineAddToModule":
                # Media grid — items live in moduleItem.item.itemContent
                for mod_item in instr.get("moduleItems", []):
                    tweet = _tweet_from_module_item(mod_item)
                    _collect_tweet(tweet, username, seen_ids, posts, user_info)

            else:
                # TimelineClearCache, TimelinePinEntry, etc. — skip
                pass

    except Exception as e:
        print(f"[JAPW/x] parse error: {e}", file=sys.stderr)

    return posts, user_info


def _collect_tweet(
    tweet: dict | None,
    username: str,
    seen_ids: set[str],
    posts: list,
    user_info: dict,
) -> None:
    """Extract image URLs from a tweet node and append to posts."""
    if not tweet:
        return

    legacy = tweet.get("legacy", {})
    tweet_id = tweet.get("rest_id") or legacy.get("id_str") or ""
    if not tweet_id or tweet_id in seen_ids:
        return

    # Grab screen name for the permalink (from tweet author's core)
    core_screen = (
        tweet.get("core", {})
        .get("user_results", {})
        .get("result", {})
        .get("legacy", {})
        .get("screen_name")
    ) or username

    # Backfill user_info from the first tweet we see
    if not user_info and core_screen:
        author_legacy = (
            tweet.get("core", {})
            .get("user_results", {})
            .get("result", {})
            .get("legacy", {})
        )
        if author_legacy:
            user_info.update({
                "username": author_legacy.get("screen_name", username),
                "display_name": author_legacy.get("name", username),
                "avatar_url": (
                    (author_legacy.get("profile_image_url_https") or "")
                    .replace("_normal", "_400x400") or None
                ),
            })

    media_list = (
        legacy.get("extended_entities", {}).get("media")
        or legacy.get("entities", {}).get("media")
        or []
    )

    urls: list[str] = []
    gif_video_url: str | None = None

    for m in media_list:
        mtype = m.get("type")
        if mtype == "photo":
            base = (m.get("media_url_https") or m.get("media_url") or "").split("?")[0]
            if base:
                urls.append(base + "?name=orig&format=jpg")
        elif mtype == "animated_gif":
            variants = m.get("video_info", {}).get("variants", [])
            mp4s = [v for v in variants if v.get("content_type") == "video/mp4"]
            if mp4s:
                gif_video_url = mp4s[0]["url"]
                thumb = (m.get("media_url_https") or m.get("media_url") or "").split("?")[0]
                if thumb:
                    urls.append(thumb)

    if not urls and not gif_video_url:
        return

    seen_ids.add(tweet_id)
    post: dict = {
        "urls": urls or [gif_video_url],
        "pin_url": f"https://x.com/{core_screen}/status/{tweet_id}",
        "artist": username,
        "source": "x",
    }
    if gif_video_url:
        post["gif_video_url"] = gif_video_url
    posts.append(post)


def _parse_user_by_screenname(body: dict, username: str) -> dict[str, Any]:
    try:
        result = body.get("data", {}).get("user", {}).get("result", {})
        legacy = result.get("legacy", {})
        if legacy:
            return {
                "username": legacy.get("screen_name", username),
                "display_name": legacy.get("name", username),
                "avatar_url": (
                    (legacy.get("profile_image_url_https") or "")
                    .replace("_normal", "_400x400") or None
                ),
            }
    except Exception:
        pass
    return {}


# ─── Public scraping API ──────────────────────────────────────────────────────

def fetch_user_info(username: str) -> dict[str, Any]:
    username = username.lstrip("@").strip()
    default = {"username": username, "display_name": username, "avatar_url": None}

    def _task(ctx):
        page = ctx.new_page()
        captured: list[dict] = []

        def on_response(response):
            try:
                ct = response.headers.get("content-type", "")
                if _is_user_response(response.url, ct) or _is_media_response(response.url, ct):
                    captured.append(response.json())
            except Exception:
                pass

        def intercept(route):
            if route.request.resource_type in ("image", "media", "font", "stylesheet"):
                route.abort()
            else:
                route.fallback()

        page.route("**/*", intercept)
        page.on("response", on_response)

        try:
            page.goto(f"https://x.com/{username}", wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(2500)
            for body in captured:
                info = _parse_user_by_screenname(body, username)
                if not info:
                    _, info = _parse_media_response(body, username, set())
                if info.get("display_name"):
                    return info
            return default
        finally:
            try:
                page.close()
            except Exception:
                pass

    try:
        return _x_run(_task)
    except Exception:
        return default


def fetch_user_media(username: str, count: int = 500) -> list[dict[str, Any]]:
    username = username.lstrip("@").strip()

    def _task(ctx):
        page = ctx.new_page()
        all_posts: list[dict[str, Any]] = []
        seen_ids: set[str] = set()

        def on_response(response):
            try:
                ct = response.headers.get("content-type", "")
                if not _is_media_response(response.url, ct):
                    return
                body = response.json()
                new_posts, _ = _parse_media_response(body, username, seen_ids)
                all_posts.extend(new_posts)
            except Exception as e:
                print(f"[JAPW/x] response parse: {e}", file=sys.stderr)

        def intercept(route):
            if route.request.resource_type in ("image", "media", "font", "stylesheet"):
                route.abort()
            else:
                route.fallback()

        page.route("**/*", intercept)
        page.on("response", on_response)

        try:
            page.goto(
                f"https://x.com/{username}/media",
                wait_until="domcontentloaded",
                timeout=25000,
            )
            page.wait_for_timeout(2500)

            stagnant = 0
            last_count = 0
            for _ in range(20):
                page.evaluate("window.scrollBy(0, 3000)")
                page.wait_for_timeout(1500)
                if len(all_posts) == last_count:
                    stagnant += 1
                    if stagnant >= 5:
                        break
                else:
                    stagnant = 0
                    last_count = len(all_posts)

            return all_posts[:count]
        finally:
            try:
                page.close()
            except Exception:
                pass

    return _x_run(_task)
