"""
X (Twitter) artists for JAPW.

Login works like Pinterest: cookies are read from your installed browsers (Chrome, Edge,
Firefox, Zen, …) and saved locally. Media is then fetched straight from x.com's own GraphQL
API with those cookies — no browser — and paged through the shared read-ahead feeds.
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from http.cookiejar import Cookie
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter

from japw import feeds
from japw.config import get_app_data_dir

# ─── Storage ──────────────────────────────────────────────────────────────────

def get_x_storage_path() -> Path:
    return get_app_data_dir() / "x_state.json"


def _artists_path() -> Path:
    return get_app_data_dir() / "x_artists.json"


def _ops_cache_path() -> Path:
    return get_app_data_dir() / "x_ops.json"


def has_x_session() -> bool:
    p = get_x_storage_path()
    return p.is_file() and p.stat().st_size > 10


def clear_x_session() -> None:
    p = get_x_storage_path()
    if p.exists():
        p.unlink()
    reload_x_session()


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
    write them to a local storage-state JSON (same flow as Pinterest sync).
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


# ─── Direct GraphQL client ───────────────────────────────────────────────────
# x.com's web app talks to /i/api/graphql/<queryId>/<Operation>. Query ids, the public
# bearer token and the required feature flags all live in the site's main.js bundle, so we
# read them from there (cached for a few days) instead of hard-coding values that rotate.

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
_OPS_TTL = 3 * 86400
_TIMEOUT = (6, 25)
PAGE_SIZE = 40


class XSessionError(RuntimeError):
    pass


class XClient:
    def __init__(self, cookies: list[dict]) -> None:
        self._http = requests.Session()
        self._http.mount("https://", HTTPAdapter(pool_connections=4, pool_maxsize=16, max_retries=1))
        self._http.headers.update({"User-Agent": _UA, "Accept-Language": "en-US,en;q=0.9"})
        for c in cookies:
            if c.get("name") and c.get("value") is not None:
                self._http.cookies.set(c["name"], c["value"], domain=c.get("domain") or ".x.com", path=c.get("path") or "/")
        self._ops: dict | None = None
        self._ops_lock = threading.Lock()
        self._user_ids: dict[str, str] = {}

    def _ct0(self) -> str:
        return next((c.value for c in self._http.cookies if c.name == "ct0"), "")

    # ── bootstrap ──
    def _load_ops(self, force: bool = False) -> dict:
        with self._ops_lock:
            if self._ops and not force:
                return self._ops
            if not force:
                try:
                    with open(_ops_cache_path(), encoding="utf-8") as f:
                        cached = json.load(f)
                    if time.time() - cached.get("fetched_at", 0) < _OPS_TTL and cached.get("ops"):
                        self._ops = cached
                        return cached
                except (OSError, ValueError):
                    pass
            self._ops = self._discover_ops()
            try:
                with open(_ops_cache_path(), "w", encoding="utf-8") as f:
                    json.dump(self._ops, f)
            except OSError:
                pass
            return self._ops

    def _discover_ops(self) -> dict:
        try:
            html = self._http.get("https://x.com/", timeout=_TIMEOUT).text
            m = re.search(r'https://abs\.twimg\.com/responsive-web/client-web[^"]*/main\.[0-9a-f]+[a-z]?\.js', html)
            if not m:
                raise XSessionError("Could not find X's web client bundle.")
            js = self._http.get(m.group(0), timeout=_TIMEOUT).text
        except requests.RequestException as e:
            raise XSessionError(f"Could not reach x.com: {e}") from e
        bearer = re.search(r'"(AAAAAAAAAAAAAAAAAAAAA[A-Za-z0-9%]+)"', js)
        if not bearer:
            raise XSessionError("Could not find X's API token.")
        ops = {}
        for name in ("UserByScreenName", "UserMedia"):
            om = re.search(
                r'queryId:"([^"]+)",operationName:"' + name + r'",operationType:"query",'
                r'metadata:\{featureSwitches:\[([^\]]*)\],fieldToggles:\[([^\]]*)\]', js)
            if not om:
                raise XSessionError(f"Could not find X operation {name}.")
            ops[name] = {
                "id": om.group(1),
                "features": re.findall(r'"([^"]+)"', om.group(2)),
                "toggles": re.findall(r'"([^"]+)"', om.group(3)),
            }
        return {"fetched_at": time.time(), "bearer": bearer.group(1), "ops": ops}

    # ── calls ──
    def graphql(self, name: str, variables: dict, referer: str = "https://x.com/") -> dict:
        for attempt in range(2):
            boot = self._load_ops(force=attempt > 0)
            op = boot["ops"][name]
            params = {
                "variables": json.dumps(variables, separators=(",", ":")),
                "features": json.dumps({f: True for f in op["features"]}, separators=(",", ":")),
            }
            if op["toggles"]:
                params["fieldToggles"] = json.dumps({f: False for f in op["toggles"]}, separators=(",", ":"))
            try:
                r = self._http.get(
                    f"https://x.com/i/api/graphql/{op['id']}/{name}",
                    params=params,
                    headers={
                        "authorization": f"Bearer {boot['bearer']}",
                        "x-csrf-token": self._ct0(),
                        "x-twitter-auth-type": "OAuth2Session",
                        "x-twitter-active-user": "yes",
                        "x-twitter-client-language": "en",
                        "referer": referer,
                    },
                    timeout=_TIMEOUT,
                )
            except requests.RequestException as e:
                raise XSessionError(f"Could not reach x.com: {e}") from e
            if r.status_code in (401, 403):
                raise XSessionError("X rejected the session. Sync your X login again in the Artists panel.")
            if r.status_code == 429:
                raise XSessionError("X is rate-limiting requests. Try again in a few minutes.")
            # A rotated query id / new required feature → re-read the bundle once and retry.
            if r.status_code in (400, 404) and attempt == 0:
                continue
            try:
                body = r.json()
            except ValueError:
                raise XSessionError(f"X returned an unexpected response (HTTP {r.status_code}).")
            if r.status_code >= 400:
                raise XSessionError(f"X {name} failed (HTTP {r.status_code}).")
            return body
        raise XSessionError(f"X {name} failed.")

    def user(self, username: str) -> dict:
        body = self.graphql("UserByScreenName", {"screen_name": username}, f"https://x.com/{username}")
        result = ((body.get("data") or {}).get("user") or {}).get("result") or {}
        if not result.get("rest_id"):
            raise XSessionError(f"@{username} was not found (or is suspended).")
        legacy = result.get("legacy") or {}
        core = result.get("core") or {}
        avatar = ((result.get("avatar") or {}).get("image_url") or legacy.get("profile_image_url_https") or "")
        self._user_ids[username.lower()] = result["rest_id"]
        return {
            "id": result["rest_id"],
            "username": core.get("screen_name") or legacy.get("screen_name") or username,
            "display_name": core.get("name") or legacy.get("name") or username,
            "avatar_url": avatar.replace("_normal", "_400x400") or None,
            "protected": bool(legacy.get("protected") or (result.get("privacy") or {}).get("protected")),
        }

    def user_id(self, username: str) -> str:
        uid = self._user_ids.get(username.lower())
        return uid or self.user(username)["id"]

    def media_page(self, username: str, cursor: str | None) -> tuple[list[dict], str | None]:
        variables = {
            "userId": self.user_id(username), "count": PAGE_SIZE, "includePromotedContent": False,
            "withClientEventToken": False, "withBirdwatchNotes": False, "withVoice": True,
        }
        if cursor:
            variables["cursor"] = cursor
        body = self.graphql("UserMedia", variables, f"https://x.com/{username}/media")
        return parse_media(body, username)


# ─── Parsing ─────────────────────────────────────────────────────────────────

def _tweet_from_item_content(item_content: dict) -> dict | None:
    result = ((item_content or {}).get("tweet_results") or {}).get("result") or {}
    if result.get("__typename") == "TweetWithVisibilityResults":
        result = result.get("tweet") or {}
    return result if result.get("legacy") else None


def _tweet_to_post(tweet: dict, username: str) -> dict | None:
    legacy = tweet.get("legacy") or {}
    tweet_id = tweet.get("rest_id") or legacy.get("id_str")
    if not tweet_id:
        return None
    author = ((tweet.get("core") or {}).get("user_results") or {}).get("result") or {}
    screen = (author.get("core") or {}).get("screen_name") or (author.get("legacy") or {}).get("screen_name") or username
    media = (legacy.get("extended_entities") or {}).get("media") or (legacy.get("entities") or {}).get("media") or []
    urls: list[str] = []
    gif = None
    width = height = 0
    for m in media:
        base = (m.get("media_url_https") or "").split("?")[0]
        info = m.get("original_info") or {}
        if m.get("type") == "photo" and base:
            # Keep the extension in the path: likes / downloads key on it (see canonical_key).
            urls.append(f"{base}?name=orig")
        elif m.get("type") == "animated_gif":
            mp4s = [v for v in (m.get("video_info") or {}).get("variants", []) if v.get("content_type") == "video/mp4"]
            if mp4s:
                gif = max(mp4s, key=lambda v: v.get("bitrate") or 0)["url"]
                if base:
                    urls.append(base)
        else:
            continue
        if not width and info.get("width"):
            width, height = int(info["width"]), int(info.get("height") or 0)
    if not urls:
        return None
    post = {
        "urls": urls,
        "pin_url": f"https://x.com/{screen}/status/{tweet_id}",
        "artist": username,
        "source": "x",
        "title": (legacy.get("full_text") or "").split("https://t.co")[0].strip()[:200],
    }
    if width and height:
        post["width"], post["height"] = width, height
    if gif:
        post["gif_video_url"] = gif
    return post


def parse_media(body: dict, username: str) -> tuple[list[dict], str | None]:
    """UserMedia response → (posts, bottom cursor). Handles the first page (a grid module
    inside TimelineAddEntries) and later pages (TimelineAddToModule)."""
    result = ((body.get("data") or {}).get("user") or {}).get("result") or {}
    outer = result.get("timeline_v2") or result.get("timeline") or {}
    timeline = outer.get("timeline") or outer
    posts: list[dict] = []
    cursor = None

    def take(item_content):
        tweet = _tweet_from_item_content(item_content)
        post = tweet and _tweet_to_post(tweet, username)
        if post:
            posts.append(post)

    for instr in timeline.get("instructions") or []:
        for entry in instr.get("entries") or []:
            content = entry.get("content") or {}
            if content.get("cursorType") == "Bottom":
                cursor = content.get("value")
            elif content.get("items"):
                for it in content["items"]:
                    take((it.get("item") or {}).get("itemContent"))
            elif content.get("itemContent"):
                take(content["itemContent"])
        for it in instr.get("moduleItems") or []:
            take((it.get("item") or {}).get("itemContent"))
    # X keeps returning a cursor after the last page; stop when a page brings nothing new.
    return posts, (cursor if posts else None)


# ─── Public API ──────────────────────────────────────────────────────────────

_client: XClient | None = None
_client_lock = threading.Lock()


def get_client() -> XClient:
    global _client
    with _client_lock:
        if _client is None:
            if not has_x_session():
                raise XSessionError("Not connected to X. Sync your X login in the Artists panel.")
            with open(get_x_storage_path(), encoding="utf-8") as f:
                _client = XClient(json.load(f).get("cookies") or [])
        return _client


def reload_x_session() -> None:
    """Drop the client (and cached feeds) so the next call uses freshly synced cookies."""
    global _client
    with _client_lock:
        _client = None
    feeds.cache.drop(lambda key: key[0] == "x")


def fetch_user_info(username: str) -> dict[str, Any]:
    username = username.lstrip("@").strip()
    info = get_client().user(username)
    return {k: info[k] for k in ("username", "display_name", "avatar_url", "protected")}


def _artist_feed(username: str, fresh: bool = False) -> feeds.Feed:
    key = ("x", "artist", username.lower())
    return feeds.cache.get(key, lambda: feeds.Feed(lambda cur: get_client().media_page(username, cur), f"x:{username}"),
                           fresh=fresh, ttl=20 * 60)


def media(username: str | None = None, offset: int = 0, limit: int = 40, refresh: bool = False):
    """One artist's media, or (username=None) every artist interleaved. Returns (posts, has_more)."""
    if username:
        return _artist_feed(username, fresh=refresh and offset == 0).get(offset, limit)
    names = [a["username"] for a in load_artists() if a.get("username")]
    if not names:
        return [], False
    key = ("x", "all", tuple(n.lower() for n in names))
    fresh = refresh and offset == 0

    def factory():
        sources = [_artist_feed(n, fresh=fresh) for n in names]
        return feeds.Feed(feeds.merged_pages(sources, per_source=20), "x:all", merged=True)
    return feeds.cache.get(key, factory, fresh=fresh, ttl=20 * 60).get(offset, limit)


def shutdown(timeout: float = 0) -> None:
    """Nothing to stop any more (kept so main.py can treat both services alike)."""
