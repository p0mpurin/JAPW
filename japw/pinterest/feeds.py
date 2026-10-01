"""
Pinterest feeds (home, search, boards, related, colour, For You) on top of the shared
read-ahead Feed engine in japw.feeds.
"""

from __future__ import annotations

import sys
import time
from collections import OrderedDict
from urllib.parse import quote_plus

from japw import taste
from japw.colors import SEARCH_WORDS
from japw.feeds import Feed, cache as _feeds, merged_pages
from japw.pinterest.client import get_client
from japw.pinterest.errors import PinterestSessionError
from japw.images import canonical_key
from japw.pinterest.parse import pins_to_posts
from japw.pinterest import session

PAGE_SIZE = 50


def _clear_pinterest_feeds() -> None:
    _feeds.drop(lambda key: key[0] != "x")


session.on_session_changed(_clear_pinterest_feeds)


def _with_bookmark(options: dict, bookmark: str | None) -> dict:
    if bookmark:
        options["bookmarks"] = [bookmark]
    return options


def _next_bookmark(rr: dict) -> str | None:
    bm = rr.get("bookmark")
    return bm if isinstance(bm, str) and bm.strip() else None


# ─── Page fetchers ───────────────────────────────────────────────────────────

def _home_page(bookmark):
    rr = get_client().resource("UserHomefeedResource", _with_bookmark({
        "field_set_key": "hf_grid", "in_nux": False, "in_news_hub": False,
        "static_feed": False, "page_size": PAGE_SIZE,
    }, bookmark))
    data = rr.get("data")
    return pins_to_posts(data if isinstance(data, list) else []), _next_bookmark(rr)


def _search_page(query: str):
    source = f"/search/pins/?q={quote_plus(query)}&rs=typed"

    def fetch(bookmark):
        rr = get_client().resource("BaseSearchResource", _with_bookmark({
            "query": query, "scope": "pins", "rs": "typed", "page_size": PAGE_SIZE,
            "no_fetch_context_on_resource": False,
        }, bookmark), source)
        data = rr.get("data") or {}
        results = data.get("results") if isinstance(data, dict) else data
        return pins_to_posts(results or []), _next_bookmark(rr)
    return fetch


def _related_page(pin_id: str):
    def fetch(bookmark):
        rr = get_client().resource("RelatedModulesResource", _with_bookmark({
            "pin_id": pin_id, "context_pin_ids": [], "page_size": 25, "search_query": "",
            "source": "deep_linking", "top_level_source": "deep_linking",
            "top_level_source_depth": 1, "is_pdp": False,
        }, bookmark), f"/pin/{pin_id}/")
        items = [it for it in (rr.get("data") or []) if isinstance(it, dict)
                 and it.get("container_type") != 13 and str(it.get("id") or "") != pin_id]
        return pins_to_posts(items), _next_bookmark(rr)
    return fetch


def _board_page(board_id: str, board_url: str):
    def fetch(bookmark):
        rr = get_client().resource("BoardFeedResource", _with_bookmark({
            "board_id": board_id, "page_size": PAGE_SIZE, "field_set_key": "react_grid_pin",
        }, bookmark), board_url or "/")
        data = rr.get("data")
        return pins_to_posts(data if isinstance(data, list) else []), _next_bookmark(rr)
    return fetch


# ─── Public API ──────────────────────────────────────────────────────────────

def _require_session() -> None:
    if not session.has_session():
        raise PinterestSessionError("Not connected to Pinterest. Sync from browser first.")


def _home_feed(refresh: bool = False) -> Feed:
    return _feeds.get(("home",), lambda: Feed(_home_page, "home"), fresh=refresh)


def _search_feed(query: str) -> Feed:
    q = query.strip()
    return _feeds.get(("search", q.lower()), lambda: Feed(_search_page(q), f"search:{q}"))


def _related_feed(pin_id: str) -> Feed:
    return _feeds.get(("related", pin_id), lambda: Feed(_related_page(pin_id), f"related:{pin_id}"))


def _colored(base_key: tuple, base: Feed, color: str, queries: list[str], fresh: bool = False) -> Feed:
    """
    Only pins whose dominant colour falls in `color`. The base feed alone rarely has enough
    (≈1 in 10 pins match), so colour-targeted searches run alongside it in parallel.
    """
    def factory():
        sources = [_search_feed(q) for q in queries] + [base]
        keep = lambda p: p.get("bucket") == color  # noqa: E731
        return Feed(merged_pages(sources, keep, per_source=25), f"color:{color}", merged=True)
    return _feeds.get(base_key + ("color", color), factory, fresh=fresh)


def home(offset: int = 0, limit: int = PAGE_SIZE, refresh: bool = False, color: str | None = None):
    _require_session()
    base = _home_feed(refresh=refresh and offset == 0)
    if color in SEARCH_WORDS:
        word = SEARCH_WORDS[color]
        feed = _colored(("home",), base, color, [f"{word} aesthetic", f"{word} aesthetic wallpaper"],
                        fresh=refresh and offset == 0)
        return feed.get(offset, limit)
    return base.get(offset, limit)


def search(query: str, offset: int = 0, limit: int = PAGE_SIZE, color: str | None = None):
    _require_session()
    q = query.strip()
    base = _search_feed(q)
    if color in SEARCH_WORDS:
        word = SEARCH_WORDS[color]
        feed = _colored(("search", q.lower()), base, color, [f"{q} {word}"])
        return feed.get(offset, limit)
    return base.get(offset, limit)


def prefetch_search(query: str) -> None:
    """Start fetching a query's first page in the background (called while the user types)."""
    if query.strip() and session.has_session():
        _search_feed(query).prefetch()


def related(pin_id: str, limit: int = 50) -> list[dict]:
    _require_session()
    return _related_feed(pin_id).get(0, limit)[0]


def board_pins(board_id: str, board_url: str = "", offset: int = 0, limit: int = PAGE_SIZE):
    _require_session()
    feed = _feeds.get(("board", board_id), lambda: Feed(_board_page(board_id, board_url), f"board:{board_id}"))
    return feed.get(offset, limit)


def for_you(offset: int = 0, limit: int = PAGE_SIZE, refresh: bool = False, color: str | None = None):
    """
    Pins like the ones you engage with: "more like this" for your strongest recent pins,
    interleaved with your home feed. Returns (posts, has_more, personalised).
    """
    _require_session()
    seeds = taste.seeds(8)
    if not seeds:
        posts, more = home(offset, limit, refresh=refresh, color=color)
        return posts, more, False

    def factory():
        engaged = {canonical_key(e["url"]) for e in taste._load()}
        keep = lambda p: canonical_key(p["urls"][0]) not in engaged  # noqa: E731
        sources = [_related_feed(pid) for pid in seeds] + [_home_feed()]
        feed = Feed(merged_pages(sources, keep, per_source=10), "foryou", merged=True)
        feed.taste_version = taste.version()
        return feed

    current = _feeds.peek(("foryou",))
    # Rebuild from the top when asked, or when your taste changed since it was built.
    stale = current is not None and offset == 0 and getattr(current, "taste_version", None) != taste.version()         and time.monotonic() - current.created > 45
    base = _feeds.get(("foryou",), factory, fresh=(refresh and offset == 0) or stale, ttl=10 * 60)
    if color in SEARCH_WORDS:
        word = SEARCH_WORDS[color]
        feed = _colored(("foryou", id(base)), base, color, [f"{word} aesthetic"])
        posts, more = feed.get(offset, limit)
    else:
        posts, more = base.get(offset, limit)
    return posts, more, True


_typeahead_cache: OrderedDict[str, list[str]] = OrderedDict()


def suggestions(term: str) -> list[str]:
    term = term.strip().lower()
    if not term or not session.has_session():
        return []
    if term in _typeahead_cache:
        return _typeahead_cache[term]
    rr = get_client().resource("AdvancedTypeaheadResource", {
        "term": term, "pin_scope": "pins", "count": 8, "user_scope": "following",
        "no_fetch_context_on_resource": False,
    })
    data = rr.get("data") or {}
    items = data.get("items") if isinstance(data, dict) else data
    out = []
    for it in items or []:
        q = isinstance(it, dict) and (it.get("query") or "").strip()
        if q and q not in out:
            out.append(q)
    _typeahead_cache[term] = out
    while len(_typeahead_cache) > 200:
        _typeahead_cache.popitem(last=False)
    return out


_me: dict | None = None
_boards_cache: tuple[float, list[dict]] | None = None


def _username() -> str:
    global _me
    if _me is None:
        _me = get_client().resource("UserSettingsResource", {}).get("data") or {}
    name = _me.get("username")
    if not name:
        raise PinterestSessionError("Could not determine your Pinterest username.")
    return name


def my_boards(force: bool = False) -> list[dict]:
    """The signed-in user's boards: [{id, name, url, count, cover}]."""
    global _boards_cache
    _require_session()
    if not force and _boards_cache and time.monotonic() - _boards_cache[0] < 120:
        return _boards_cache[1]
    username = _username()
    out: list[dict] = []
    bookmark = None
    for _ in range(10):
        rr = get_client().resource("BoardsResource", _with_bookmark({
            "username": username, "page_size": 50, "privacy_filter": "all",
            "sort": "last_pinned_to", "field_set_key": "profile_grid_item",
        }, bookmark), f"/{username}/")
        for b in rr.get("data") or []:
            if not isinstance(b, dict) or not b.get("id"):
                continue
            covers = b.get("cover_images") or {}
            cover = b.get("image_cover_hd_url") or b.get("image_cover_url") or ""
            if not cover and isinstance(covers, dict):
                first = next(iter(covers.values()), {}) or {}
                cover = first.get("url") or ""
            out.append({
                "id": str(b["id"]),
                "name": b.get("name") or "Board",
                "url": b.get("url") or "",
                "count": int(b.get("pin_count") or 0),
                "cover": cover,
                "secret": b.get("privacy") == "secret",
            })
        bookmark = _next_bookmark(rr)
        if not bookmark or bookmark == "-end-":
            break
    _boards_cache = (time.monotonic(), out)
    return out


def _reset_user_cache() -> None:
    global _me, _boards_cache
    _me = None
    _boards_cache = None


session.on_session_changed(_reset_user_cache)


def warm_up() -> None:
    """Open the connection and start fetching the home feed at startup."""
    if not session.has_session():
        return
    try:
        get_client().warm()
        _home_feed().prefetch()
    except Exception as e:
        print(f"[JAPW] warm-up failed: {e}", file=sys.stderr)


def shutdown() -> None:
    from japw import feeds

    feeds.shutdown()
