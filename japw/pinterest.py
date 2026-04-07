"""
Pinterest session: import cookies from the user's installed browsers (Chrome, Edge,
Firefox, …), save them, then call Pinterest's own internal JSON API for home/search
(same endpoints the web app uses — no browser needed, instant results).
Playwright is kept only for boards and related-pin pages which need DOM rendering.
"""

from __future__ import annotations

import collections
import concurrent.futures
import json
import os
import re
import threading
import time
from http.cookiejar import Cookie
from pathlib import Path
from urllib.parse import parse_qsl, quote_plus, urlencode, urlsplit, urlunsplit

from japw.config import get_app_data_dir

PINIMG_URL_RE = re.compile(r"https://i\.pinimg\.com/[^\"'\s<>\)]+", re.I)

HOMEFEED_URL = "https://www.pinterest.com/homefeed/"
SEARCH_URL_TEMPLATE = "https://www.pinterest.com/search/pins/?q={query}"

# Chromium: reduce stale feed from disk cache between runs.
_CHROMIUM_ARGS = ("--disable-http-cache",)


def playwright_effective_headless(requested: bool = True) -> bool:
    """
    Debug: set env JAPW_PLAYWRIGHT_HEADLESS=0 (or false/no/off) to run Chromium
    in a visible window. Default follows ``requested`` (normal headless=True).
    """
    v = os.environ.get("JAPW_PLAYWRIGHT_HEADLESS", "1").strip().lower()
    if v in ("0", "false", "no", "off"):
        return False
    return bool(requested)


def playwright_visible_fallback_allowed() -> bool:
    """
    When headless returns nothing, we used to retry with a visible browser.
    That caused surprise Chrome windows. Retries are disabled unless you set
    JAPW_PLAYWRIGHT_VISIBLE_FALLBACK=1 (or true/yes/on).
    """
    v = os.environ.get("JAPW_PLAYWRIGHT_VISIBLE_FALLBACK", "0").strip().lower()
    return v in ("1", "true", "yes", "on")

# Parallel Playwright runs per home/search/board batch. Default 1 keeps one browser
# and a single scroll sequence (lighter RAM/CPU). Set JAPW_SCRAPER_THREADS=2..8 to scale up.
try:
    _SCRAPER_PARALLEL_WORKERS = max(1, min(8, int(os.environ.get("JAPW_SCRAPER_THREADS", "1"))))
except ValueError:
    _SCRAPER_PARALLEL_WORKERS = 1

# Feed scrape: moderate scroll + generous waits so Pinterest XHR responses
# (typically 150-400 ms) complete before we read the DOM.
_SCRAPE_WHEEL_DELTA = 1800   # smaller step → fewer skipped pins per burst
_SCRAPE_BURST_WHEELS = 2     # two gentle nudges per step
_SCRAPE_PAUSE_HOME_MS = 200  # wait for XHR after each scroll step (was 300)
_SCRAPE_PAUSE_SEARCH_MS = 350  # search feed: longer wait for XHR pagination to respond
_SCRAPE_SETTLE_HOME_MS = 280  # final settle before last DOM read (was 400)
_SCRAPE_SETTLE_SEARCH_MS = 280  # (was 380)

# ─── Pinterest internal JSON API ─────────────────────────────────────────────
_PINTEREST_API_BASE = "https://www.pinterest.com/resource/"
_API_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# ─── Home pre-fetch buffer ────────────────────────────────────────────────────
# Background thread continuously fills a pool of ready posts.
# API calls pop from the pool (<100 ms) instead of waiting for a full scrape.

_home_buf: collections.deque[dict] = collections.deque()
_home_buf_lock = threading.Lock()
_home_buf_keys: set[str] = set()          # keys currently in buffer
_home_buf_served_keys: set[str] = set()   # keys already popped and sent to the UI
_home_buf_fill_active = False
_home_api_bookmark: str | None = None     # API pagination cursor
_HOME_BUF_LOW = 25       # start a refill when buffer drops below this
_HOME_BUF_TARGET = 90    # target size after each fill


def _home_buf_key(post: dict) -> str:
    urls = post.get("urls") or []
    return _pinimg_canonical_key(urls[0]) if urls else ""


def home_buf_warm_up() -> None:
    """Call once at startup (if a session exists) to begin filling the buffer."""
    _home_buf_start_fill()


def _home_buf_start_fill() -> None:
    """Schedule a background fill if not already running and buffer is low."""
    global _home_buf_fill_active
    if not has_session():
        return
    with _home_buf_lock:
        if _home_buf_fill_active or len(_home_buf) >= _HOME_BUF_TARGET:
            return
        _home_buf_fill_active = True
    threading.Thread(target=_home_buf_fill_worker, daemon=True).start()


def _home_buf_fill_worker() -> None:
    global _home_buf_fill_active, _home_api_bookmark
    try:
        with _home_buf_lock:
            need = _HOME_BUF_TARGET - len(_home_buf)
            ex = frozenset(_home_buf_served_keys) | frozenset(_home_buf_keys)
            bookmark = _home_api_bookmark
        if need <= 0:
            return

        def _home_fill_task(ctx):
            page = _apibr_make_home_page(ctx)
            try:
                local_collected: list[dict] = []
                local_keys: set[str] = set()
                pages_tried = 0
                bm = bookmark
                while len(local_collected) < need and pages_tried < 12:
                    page_posts, next_bm = _api_homefeed_page(page, bm, page_size=25)
                    pages_tried += 1
                    bm = next_bm
                    if not page_posts:
                        break
                    for post in page_posts:
                        k = _home_buf_key(post)
                        if k and k not in ex and k not in local_keys:
                            local_collected.append(post)
                            local_keys.add(k)
                return local_collected, bm
            finally:
                _apibr_close_page(page)

        collected, bookmark = _apibr_run(_home_fill_task)

        with _home_buf_lock:
            _home_api_bookmark = bookmark
            for post in collected:
                k = _home_buf_key(post)
                if not k or k in _home_buf_keys or k in _home_buf_served_keys:
                    continue
                _home_buf.append(post)
                _home_buf_keys.add(k)
    except Exception:
        pass
    finally:
        with _home_buf_lock:
            _home_buf_fill_active = False
        # Schedule another fill if still below watermark
        with _home_buf_lock:
            still_low = len(_home_buf) < _HOME_BUF_LOW
        if still_low and has_session():
            _home_buf_start_fill()


def _home_buf_pop(n: int) -> list[dict]:
    """Pop up to n posts from the buffer. Returns empty list if buffer is cold."""
    with _home_buf_lock:
        result: list[dict] = []
        while _home_buf and len(result) < n:
            post = _home_buf.popleft()
            k = _home_buf_key(post)
            _home_buf_keys.discard(k)
            _home_buf_served_keys.add(k)
            result.append(post)
        return result


def _home_buf_reset() -> None:
    """Clear buffer state (call when session is cleared or changed)."""
    global _home_api_bookmark
    with _home_buf_lock:
        _home_buf.clear()
        _home_buf_keys.clear()
        _home_buf_served_keys.clear()
        _home_api_bookmark = None
# ─────────────────────────────────────────────────────────────────────────────

# ─── Search pre-fetch buffer (per-query) ─────────────────────────────────────
# After the first search call returns, a background thread immediately starts
# fetching more results for the same query. Subsequent /search/more calls pop
# from this buffer in <100 ms instead of waiting for a new API round-trip.

_search_buf_lock = threading.Lock()
_search_buf_query: str = ""
_search_buf_posts: collections.deque[dict] = collections.deque()
_search_buf_keys: set[str] = set()    # keys currently in buffer
_search_buf_served: set[str] = set()  # keys already served for this query
_search_buf_filling: bool = False
_search_api_bookmark: str | None = None  # API pagination cursor for current query
_SEARCH_BUF_LOW = 20
_SEARCH_BUF_TARGET = 70


def _search_buf_reset(new_query: str = "") -> None:
    global _search_buf_query, _search_buf_filling, _search_api_bookmark
    with _search_buf_lock:
        _search_buf_query = new_query
        _search_buf_posts.clear()
        _search_buf_keys.clear()
        _search_buf_served.clear()
        _search_buf_filling = False
        _search_api_bookmark = None


def _search_buf_start_fill(query: str) -> None:
    global _search_buf_filling
    if not has_session() or not query:
        return
    with _search_buf_lock:
        if _search_buf_query != query:
            return
        if _search_buf_filling or len(_search_buf_posts) >= _SEARCH_BUF_TARGET:
            return
        _search_buf_filling = True
    threading.Thread(target=_search_buf_fill_worker, args=(query,), daemon=True).start()


def _search_buf_fill_worker(query: str) -> None:
    global _search_buf_filling, _search_api_bookmark
    try:
        with _search_buf_lock:
            if _search_buf_query != query:
                return
            need = _SEARCH_BUF_TARGET - len(_search_buf_posts)
            ex = frozenset(_search_buf_served) | frozenset(_search_buf_keys)
            bookmark = _search_api_bookmark
        if need <= 0:
            return

        def _search_fill_task(ctx):
            page = _apibr_make_home_page(ctx)
            try:
                local_collected: list[dict] = []
                local_keys: set[str] = set()
                pages_tried = 0
                bm = bookmark
                while len(local_collected) < need and pages_tried < 12:
                    page_posts, next_bm = _api_search_page(page, query, bm, page_size=25)
                    pages_tried += 1
                    bm = next_bm
                    if not page_posts:
                        break
                    page_posts = exclude_posts_seen_on_home(page_posts)
                    for post in page_posts:
                        k = _home_buf_key(post)
                        if k and k not in ex and k not in local_keys:
                            local_collected.append(post)
                            local_keys.add(k)
                return local_collected, bm
            finally:
                _apibr_close_page(page)

        collected, bookmark = _apibr_run(_search_fill_task)

        with _search_buf_lock:
            if _search_buf_query != query:
                return
            _search_api_bookmark = bookmark
            for post in collected:
                k = _home_buf_key(post)
                if not k or k in _search_buf_keys or k in _search_buf_served:
                    continue
                _search_buf_posts.append(post)
                _search_buf_keys.add(k)
    except Exception:
        pass
    finally:
        with _search_buf_lock:
            _search_buf_filling = False
        with _search_buf_lock:
            still_low = _search_buf_query == query and len(_search_buf_posts) < _SEARCH_BUF_LOW
        if still_low and has_session():
            _search_buf_start_fill(query)


def _search_buf_pop(query: str, n: int) -> list[dict]:
    """Pop up to n posts for this query. Returns [] if wrong query or buffer empty."""
    with _search_buf_lock:
        if _search_buf_query != query:
            return []
        result: list[dict] = []
        while _search_buf_posts and len(result) < n:
            post = _search_buf_posts.popleft()
            k = _home_buf_key(post)
            _search_buf_keys.discard(k)
            _search_buf_served.add(k)
            result.append(post)
        return result
# ─────────────────────────────────────────────────────────────────────────────

# Best-effort: map pinimg URL → Pinterest pin page URL by walking the live DOM.
# Carousel / multi-image pins often render extra images *outside* the main <a href="/pin/…">,
# so we also walk up from each img and use the innermost ancestor that contains exactly one
# distinct /pin/{id}/ link (same card). That lets merge_posts_same_pin group all slides.
_PIN_PAGE_URL_JS = """() => {
  const map = {};
  const normPinHref = (href) => {
    if (!href) return '';
    let path = '';
    try { path = new URL(href, 'https://www.pinterest.com').pathname; } catch (e) { return ''; }
    const m = /^\\/pin\\/(\\d+)\\/?$/.exec(path);
    return m ? ('https://www.pinterest.com/pin/' + m[1] + '/') : '';
  };
  try {
    document.querySelectorAll('img[src*="pinimg"], img[srcset*="pinimg"]').forEach((img) => {
      let pinUrl = '';
      const directA = img.closest('a[href*="/pin/"]');
      if (directA) pinUrl = normPinHref(directA.href);
      if (!pinUrl) {
        let el = img.parentElement;
        for (let d = 0; d < 42 && el && el !== document.body; d++, el = el.parentElement) {
          const ids = new Set();
          const links = el.querySelectorAll('a[href*="/pin/"]');
          for (let i = 0; i < links.length; i++) {
            const u = normPinHref(links[i].href);
            if (!u) continue;
            const mid = /\\/pin\\/(\\d+)\\//.exec(u);
            if (mid) ids.add(mid[1]);
          }
          if (ids.size === 1) {
            pinUrl = 'https://www.pinterest.com/pin/' + [...ids][0] + '/';
            break;
          }
        }
      }
      if (!pinUrl) return;
      const add = (raw) => {
        const s = (raw || '').split('?')[0];
        if (s && !map[s]) map[s] = pinUrl;
      };
      if (img.src) add(img.src);
      const ss = img.getAttribute('srcset') || '';
      ss.split(',').forEach((p) => add(p.trim().split(/\\s+/)[0]));
    });
  } catch (e) {}
  return map;
}"""


def _lookup_pin_url_in_dom_map(raw_map: dict, cover_norm: str) -> str | None:
    """
    Match a normalized pinimg URL to an entry from ``_PIN_PAGE_URL_JS`` (handles case,
    query strip, and different CDN size buckets vs. keys in the map).
    """
    if not raw_map or not cover_norm:
        return None
    cand = cover_norm.split("?")[0].strip()
    if cand in raw_map:
        return raw_map[cand]
    cl = cand.lower()
    for k, v in raw_map.items():
        if (k or "").split("?")[0].strip().lower() == cl:
            return v
    ck = _pinimg_canonical_key(cand)
    for k, v in raw_map.items():
        if _pinimg_canonical_key(k) == ck:
            return v
    return None


def _enrich_with_pin_urls(page, posts: list[dict]) -> None:
    """Attempt to add ``pin_url`` to each post by reading the live DOM."""
    try:
        raw_map: dict = page.evaluate(_PIN_PAGE_URL_JS) or {}
        if not raw_map:
            return
        for post in posts:
            if post.get("pin_url"):
                continue
            for img_url in (post.get("urls") or []):
                n = _normalize_pin_url(img_url)
                if not n:
                    continue
                pu = _lookup_pin_url_in_dom_map(raw_map, n)
                if pu:
                    post["pin_url"] = pu
                    break
    except Exception:
        pass


def _pin_id_from_pin_page_url(pin_page_url: str) -> str:
    """Return numeric pin id string, or empty if not a /pin/{id} URL."""
    u = (pin_page_url or "").split("?")[0].strip()
    m = re.search(r"/pin/(\d+)", u, re.I)
    return m.group(1) if m else ""


def is_pin_page_url(url: str) -> bool:
    """True if URL looks like a Pinterest pin page (any locale host)."""
    u = (url or "").strip()
    return bool(re.search(r"pinterest\.[^/]+/pin/\d+", u, re.I))


def normalize_pin_page_url(url: str) -> str:
    """https://www.pinterest.com/pin/123/ style URL."""
    u = (url or "").strip().split("?")[0].strip()
    m = re.search(r"(https?://(?:[\w-]+\.)?pinterest\.[^/]+/pin/(\d+))", u, re.I)
    if m:
        return f"https://www.pinterest.com/pin/{m.group(2)}/"
    return u.rstrip("/") + "/" if u.startswith("http") else ""


def _normalized_pin_page_url(pin_id: str) -> str:
    return f"https://www.pinterest.com/pin/{pin_id}/"


def merge_posts_same_pin(posts: list[dict]) -> list[dict]:
    """
    Merge items that belong to the same Pinterest pin (carousel / story / duplicate
    cards) into one ``{"urls": [...], "pin_url": ...}`` using ``pin_url`` from the DOM.
    Items without ``pin_url`` are left as separate entries.
    """
    by_key: dict[str, dict] = {}
    order_keys: list[str] = []
    orphan_i = 0

    for p in posts:
        urls_add = [u for u in (p.get("urls") or []) if u and str(u).strip()]
        if not urls_add:
            continue
        pin_raw = (p.get("pin_url") or "").strip()
        pid = _pin_id_from_pin_page_url(pin_raw) if pin_raw else ""

        if pid:
            if pid not in by_key:
                by_key[pid] = {"urls": [], "pin_url": _normalized_pin_page_url(pid)}
                order_keys.append(pid)
            by_key[pid]["urls"].extend(urls_add)
        else:
            k = f"__orphan:{orphan_i}"
            orphan_i += 1
            by_key[k] = {"urls": list(urls_add), "pin_url": None}
            order_keys.append(k)

    out: list[dict] = []
    for k in order_keys:
        m = by_key[k]
        urls = dedupe_pinimg_urls(m["urls"])
        if not urls:
            continue
        item: dict = {"urls": urls}
        if m.get("pin_url"):
            item["pin_url"] = m["pin_url"]
        out.append(item)
    return out


def filter_posts_excluding_image_keys(
    posts: list[dict], exc: set[str] | frozenset | None
) -> list[dict]:
    if not exc:
        return list(posts)
    out: list[dict] = []
    for p in posts:
        urls = [
            u
            for u in (p.get("urls") or [])
            if u and _pinimg_canonical_key(str(u)) not in exc
        ]
        urls = dedupe_pinimg_urls(urls)
        if not urls:
            continue
        item: dict = {"urls": urls}
        if p.get("pin_url"):
            item["pin_url"] = p["pin_url"]
        out.append(item)
    return out


def exclude_posts_matching_pin_id(posts: list[dict], pin_id: str) -> list[dict]:
    if not pin_id:
        return list(posts)
    out: list[dict] = []
    for p in posts:
        pu = (p.get("pin_url") or "").strip()
        if pu and _pin_id_from_pin_page_url(pu) == pin_id:
            continue
        out.append(p)
    return out


def _pin_page_url_busted(pin_page_url: str) -> str:
    u = normalize_pin_page_url(pin_page_url).rstrip("/")
    sep = "&" if "?" in u else "?"
    return f"{u}{sep}_JAPWcb={int(time.time() * 1000)}"


def _worth_reading_response_body(url: str, content_type: str | None) -> bool:
    """
    Avoid response.body() on huge HTML/JS payloads; pin data arrives in /resource/ JSON XHRs.
    """
    u = (url or "").lower()
    ct = (content_type or "").lower()
    if "pinimg.com" in u:
        return False
    if "pinterest.com" not in u:
        return False
    if "text/html" in ct or "text/javascript" in ct or "application/javascript" in ct:
        return False
    if "text/css" in ct or "font/" in ct or "image/" in ct:
        return False
    if "/resource/" in u or "graphql" in u:
        return True
    if "json" in ct:
        return True
    return False



# ─── Shared persistent API browser (worker-thread model) ────────────────────
# Playwright's sync API binds browser/context objects to the OS thread
# (greenlet) that created them.  Sharing them across threads causes:
#   "cannot switch to a different thread which happens to have exited"
# Solution: one long-lived daemon thread (_apibr_worker) owns all Playwright
# objects for its entire lifetime.  Other threads submit callables via
# _apibr_queue and block until the result is ready.

import queue as _queue

_apibr_queue: "_queue.Queue" = _queue.Queue()
_apibr_worker: "threading.Thread | None" = None
_apibr_worker_lock = threading.Lock()

# Sentinel objects for control commands (not data tasks).
_APIBR_SHUTDOWN       = object()
_APIBR_RELOAD_SESSION = object()


def _apibr_worker_main() -> None:
    import sys as _sys
    from playwright.sync_api import sync_playwright as _spw

    pw = br = ctx = None

    def _boot():
        nonlocal pw, br, ctx
        pw = _spw().__enter__()
        br = pw.chromium.launch(
            headless=playwright_effective_headless(True),
            args=list(_CHROMIUM_ARGS),
        )
        ctx = br.new_context(**_playwright_context_options())
        print("[JAPW] API browser started", file=_sys.stderr)

    def _close_all():
        nonlocal pw, br, ctx
        for obj, meth in ((ctx, "close"), (br, "close")):
            if obj is not None:
                try: getattr(obj, meth)()
                except Exception: pass
        if pw is not None:
            try: pw.__exit__(None, None, None)
            except Exception: pass
        pw = br = ctx = None

    try:
        _boot()
    except Exception as e:
        print(f"[JAPW] API browser failed to start: {e}", file=_sys.stderr)
        # Drain any pending tasks with an error so callers don't deadlock.
        while True:
            item = _apibr_queue.get()
            if item is _APIBR_SHUTDOWN or item is None:
                return
            if item is _APIBR_RELOAD_SESSION:
                continue
            _, result_q = item
            result_q.put(("err", RuntimeError(f"Browser failed to start: {e}")))
        return

    while True:
        item = _apibr_queue.get()

        if item is _APIBR_SHUTDOWN or item is None:
            _close_all()
            return

        if item is _APIBR_RELOAD_SESSION:
            # Close old context, open a fresh one with the newly-saved cookies.
            if ctx is not None:
                try: ctx.close()
                except Exception: pass
            try:
                ctx = br.new_context(**_playwright_context_options())
                print("[JAPW] API browser session reloaded", file=_sys.stderr)
            except Exception as e:
                print(f"[JAPW] session reload failed, restarting browser: {e}", file=_sys.stderr)
                _close_all()
                try: _boot()
                except Exception as e2:
                    print(f"[JAPW] browser restart failed: {e2}", file=_sys.stderr)
            continue

        fn, result_q = item
        try:
            result_q.put(("ok", fn(ctx)))
        except Exception as e:
            result_q.put(("err", e))


def _apibr_ensure_worker() -> None:
    """Start the Playwright worker thread if it is not already alive."""
    global _apibr_worker
    with _apibr_worker_lock:
        if _apibr_worker is not None and _apibr_worker.is_alive():
            return
        _apibr_worker = threading.Thread(
            target=_apibr_worker_main, daemon=True, name="JAPW-apibr"
        )
        _apibr_worker.start()


def _apibr_run(fn) -> object:
    """
    Run fn(ctx) on the dedicated Playwright worker thread and return its result.
    fn receives the live BrowserContext.  Raises whatever fn raises.
    Blocks the calling thread until done.
    """
    _apibr_ensure_worker()
    result_q: _queue.Queue = _queue.Queue(maxsize=1)
    _apibr_queue.put((fn, result_q))
    status, value = result_q.get()
    if status == "err":
        raise value
    return value


def _apibr_reload_session() -> None:
    """Signal the worker to discard the stale browser context and load fresh cookies."""
    _apibr_ensure_worker()
    _apibr_queue.put(_APIBR_RELOAD_SESSION)


def _apibr_teardown() -> None:
    """Shut down the Playwright worker thread (call on logout)."""
    _apibr_ensure_worker()
    _apibr_queue.put(_APIBR_SHUTDOWN)


def _apibr_make_home_page(ctx):
    """Create a fresh page navigated to pinterest.com. Must run on worker thread."""
    page = ctx.new_page()

    def _block_heavy(route):
        if route.request.resource_type in ("image", "media", "font", "stylesheet"):
            route.abort()
        else:
            route.fallback()

    page.route("**/*", _block_heavy)
    page.goto("https://www.pinterest.com/", wait_until="domcontentloaded", timeout=45_000)
    return page


def _apibr_close_page(page) -> None:
    """Close just the page — the browser stays alive for the next call."""
    try:
        page.close()
    except Exception:
        pass


# Legacy wrappers kept for Playwright DOM-scrape functions (boards / pin pages)
# which each manage their own browser lifecycle independently.
def _open_api_browser_page():
    """Deprecated helper — new code uses _apibr_lock + _apibr_get_page()."""
    from playwright.sync_api import sync_playwright as _spw
    pw = _spw().__enter__()
    browser = pw.chromium.launch(headless=playwright_effective_headless(True), args=list(_CHROMIUM_ARGS))
    context = browser.new_context(**_playwright_context_options())
    page = context.new_page()

    def _block_heavy(route):
        if route.request.resource_type in ("image", "media", "font", "stylesheet"):
            route.abort()
        else:
            route.fallback()

    page.route("**/*", _block_heavy)
    page.goto("https://www.pinterest.com/", wait_until="domcontentloaded", timeout=45_000)
    return pw, browser, context, page


def _close_api_browser_page(pw, browser, context, page) -> None:
    try:
        context.close()
    except Exception:
        pass
    try:
        browser.close()
    except Exception:
        pass
    try:
        pw.__exit__(None, None, None)
    except Exception:
        pass


def _best_pinimg_url(images: dict) -> str | None:
    """Pick the best available image URL from a Pinterest images dict."""
    if not isinstance(images, dict):
        return None
    for size in ("736x", "474x", "236x", "orig"):
        entry = images.get(size)
        if isinstance(entry, dict):
            u = entry.get("url") or ""
            if u and "pinimg.com" in u:
                return str(u)
    for entry in images.values():
        if isinstance(entry, dict):
            u = entry.get("url") or ""
            if u and "pinimg.com" in u:
                return str(u)
    return None


def _api_pin_to_post(pin: dict) -> dict | None:
    """Convert a Pinterest API pin object to ``{"urls": [...], "pin_url": ...}``."""
    if not isinstance(pin, dict):
        return None
    # UserHomefeedResource (hf_grid) includes is_promoted / promoted_is_removable on each pin.
    if _filter_promoted and _is_promoted_pin(pin):
        return None
    pin_id = str(pin.get("id") or "").strip()
    urls: list[str] = []

    # Carousel slides (cover image first)
    carousel = pin.get("carousel_data")
    if isinstance(carousel, dict):
        for slot in (carousel.get("carousel_slots") or []):
            u = _best_pinimg_url(slot.get("images") or {})
            if u:
                n = _normalize_pin_url(u)
                if n and n not in urls:
                    urls.append(n)

    # Main pin image — collect ALL size variants so dedupe_pinimg_urls can prefer
    # animated originals (.gif) over static thumbnails (.jpg).
    main_images = pin.get("images") or {}
    main_variants: list[str] = []
    for entry in main_images.values():
        if isinstance(entry, dict):
            u = (entry.get("url") or "").split("?")[0]
            if u and "pinimg.com" in u:
                n = _normalize_pin_url(u)
                if n and n not in main_variants:
                    main_variants.append(n)
    if main_variants:
        best_main = dedupe_pinimg_urls(main_variants)
        if best_main and best_main[0] not in urls:
            urls.insert(0, best_main[0])

    # Idea/story pin cover image
    if not urls:
        story = pin.get("story_pin_data") or {}
        ci = story.get("cover_images") or story.get("thumbnail_color_images") or {}
        u = _best_pinimg_url(ci)
        if u:
            n = _normalize_pin_url(u)
            if n:
                urls.append(n)

    if not urls:
        return None
    urls = dedupe_pinimg_urls(urls)
    if not urls:
        return None

    post: dict = {"urls": urls}
    if pin_id:
        post["pin_url"] = f"https://www.pinterest.com/pin/{pin_id}/"
    return post


def _page_fetch_json(page, url: str, timeout_ms: int = 15_000) -> dict | None:
    """Make an authenticated fetch() call from within the browser page. Returns parsed JSON or None."""
    js = f"""async () => {{
      try {{
        // Read values that Pinterest's own JS sends so Akamai accepts our request.
        const csrf = (document.cookie.split(';').find(c => c.trim().startsWith('csrftoken=')) || '').split('=').slice(1).join('=');
        const appVer = (window.__PWS_INITIAL_PROPS__ || {{}}).app_version || (document.head.querySelector('meta[name=app_version]') || {{}}).content || '';
        const r = await fetch({json.dumps(url)}, {{
          credentials: 'include',
          headers: {{
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'X-Requested-With': 'XMLHttpRequest',
            'X-Pinterest-AppState': 'active',
            'X-Pinterest-PWS-Handler': 'www/index.js',
            'X-Pinterest-Source-Url': '/',
            'X-App-Version': appVer,
            'X-CSRFToken': csrf,
            'Screen-Dpr': '1',
          }}
        }});
        if (!r.ok) {{
          console.error('[JAPW] fetch failed', r.status, r.statusText, {json.dumps(url)}.slice(0, 80));
          return null;
        }}
        return r.json();
      }} catch(e) {{
        console.error('[JAPW] fetch exception', String(e));
        return null;
      }}
    }}"""
    try:
        return page.evaluate(js)
    except Exception as exc:
        import sys
        print(f"[JAPW] _page_fetch_json evaluate error: {exc}", file=sys.stderr)
        return None


def _api_homefeed_page(
    page,
    bookmark: str | None = None,
    page_size: int = 25,
) -> tuple[list[dict], str | None]:
    """Call Pinterest UserHomefeedResource API via browser fetch(). Returns (posts, next_bookmark)."""
    opts: dict = {
        "field_set_key": "hf_grid",
        "in_nux": False,
        "in_news_hub": False,
        "static_feed": False,
    }
    if bookmark:
        opts["bookmarks"] = [bookmark]
    params = urlencode({
        "source_url": "/",
        "data": json.dumps({"options": opts, "context": {}}, separators=(",", ":")),
        "_": int(time.time() * 1000),
    })
    # Use a path-relative URL so the request goes to the same origin the browser
    # redirected to (e.g. it.pinterest.com for Italian locale users).
    url = f"/resource/UserHomefeedResource/get/?{params}"
    body = _page_fetch_json(page, url)
    if not body:
        return [], None

    rr = body.get("resource_response") or {}
    data = rr.get("data") or []
    next_bm = rr.get("bookmark")
    posts = []
    for item in (data if isinstance(data, list) else []):
        p = _api_pin_to_post(item)
        if p:
            posts.append(p)
    bm_out = next_bm if (isinstance(next_bm, str) and next_bm.strip()) else None
    return posts, bm_out


def _api_search_page(
    page,
    query: str,
    bookmark: str | None = None,
    page_size: int = 25,
) -> tuple[list[dict], str | None]:
    """Call Pinterest BaseSearchResource API via browser fetch(). Returns (posts, next_bookmark)."""
    opts: dict = {
        "query": query,
        "scope": "pins",
        "no_fetch_context_on_resource": False,
        "rs": "typed",
        "page_size": page_size,
    }
    if bookmark:
        opts["bookmarks"] = [bookmark]
    params = urlencode({
        "source_url": f"/search/pins/?q={quote_plus(query)}&rs=typed",
        "data": json.dumps({"options": opts, "context": {}}, separators=(",", ":")),
        "_": int(time.time() * 1000),
    })
    url = f"/resource/BaseSearchResource/get/?{params}"
    body = _page_fetch_json(page, url)
    if not body:
        return [], None

    rr = body.get("resource_response") or {}
    data = rr.get("data") or {}
    # Search: results live under data.results; fallback to data as list
    results = data.get("results") if isinstance(data, dict) else data
    next_bm = rr.get("bookmark")
    posts = []
    for item in (results or []):
        p = _api_pin_to_post(item)
        if p:
            posts.append(p)
    bm_out = next_bm if (isinstance(next_bm, str) and next_bm.strip()) else None
    return posts, bm_out


def _api_related_pins_page(
    page,
    pin_id: str,
    bookmark: str | None = None,
    page_size: int = 25,
) -> tuple[list[dict], str | None]:
    """
    Call Pinterest RelatedModulesResource to get "more like this" pins.
    The page must already be navigated to the pin's page (same-origin required).
    Returns (posts, next_bookmark).
    """
    opts: dict = {
        "pin_id": pin_id,
        "additional_fields": ["pin.gen_ai_topics"],
        "context_pin_ids": [],
        "page_size": page_size,
        "search_query": "",
        "source": "deep_linking",
        "top_level_source": "deep_linking",
        "top_level_source_depth": 1,
        "is_pdp": False,
    }
    if bookmark:
        opts["bookmarks"] = [bookmark]
    params = urlencode({
        "source_url": f"/pin/{pin_id}/",
        "data": json.dumps({"options": opts, "context": {}}, separators=(",", ":")),
        "_": int(time.time() * 1000),
    })
    url = f"/resource/RelatedModulesResource/get/?{params}"
    body = _page_fetch_json(page, url)
    if not body:
        return [], None

    rr = body.get("resource_response") or {}
    data = rr.get("data") or []
    next_bm = rr.get("bookmark")
    posts = []
    # data[0] is a header module (container_type=13); the rest are pin objects
    for item in (data if isinstance(data, list) else []):
        if item.get("container_type") == 13:
            continue  # skip header module
        if not item.get("id"):
            continue
        p = _api_pin_to_post(item)
        if p:
            posts.append(p)
    bm_out = next_bm if (isinstance(next_bm, str) and next_bm.strip()) else None
    return posts, bm_out


def _homefeed_url_busted() -> str:
    """Cache-bust so each scrape can see a fresher personalized feed."""
    b = HOMEFEED_URL.rstrip("/")
    sep = "&" if "?" in b else "?"
    return f"{b}{sep}_JAPWcb={int(time.time() * 1000)}"


_BOARDS_EXTRACT_JS = r"""() => {
  const out = [];
  const seen = new Set();
  const banFirst = new Set(['pin','pins','search','settings','notifications','messages','ideas','topics','today','videos','shopping','login','signup','password','invite','about','blog','help','business','creators','policy','videos','shop']);
  const add = (rawHref, title) => {
    if (!rawHref) return;
    let u = String(rawHref).split('?')[0].split('#')[0];
    if (u.startsWith('/')) u = window.location.origin + u;
    if (!/^https?:\/\/([\w-]+\.)?pinterest\.com\//i.test(u)) return;
    if (u.includes('/pin/') || u.toLowerCase().includes('/search')) return;
    const path = u.replace(/^https?:\/\/[^/]+\//i,'').split('/').filter(Boolean);
    if (path.length < 2) return;
    if (banFirst.has(path[0].toLowerCase())) return;
    let key = u.replace(/\/+$/, '');
    if (seen.has(key)) return;
    seen.add(key);
    let label = (title || path[path.length - 1] || 'Board').replace(/\s+/g,' ').trim().slice(0, 200);
    out.push({ url: key + '/', title: label || 'Board' });
  };
  document.querySelectorAll('[data-test-id="board-card"] a[href]').forEach(a => {
    add(a.href, a.getAttribute('aria-label') || a.textContent);
  });
  document.querySelectorAll('[data-test-id="board-row"] a[href], [data-testid="board-card"] a[href]').forEach(a => {
    add(a.href, a.getAttribute('aria-label') || a.textContent);
  });
  if (out.length < 4) {
    document.querySelectorAll('a[href*="pinterest.com/"]').forEach(a => {
      const h = a.href || '';
      const tail = h.split(/pinterest\.com\//i)[1];
      if (!tail) return;
      const parts = tail.split('?')[0].split('/').filter(Boolean);
      if (parts.length === 2 && !parts[0].toLowerCase().startsWith('pin')) add(h, a.textContent);
    });
  }
  return out;
}"""


def _board_url_busted(board_url: str) -> str:
    raw = (board_url or "").strip().split("#")[0].strip()
    if not raw.endswith("/"):
        raw += "/"
    parts = urlsplit(raw)
    q = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "_JAPWcb"]
    q.append(("_JAPWcb", str(int(time.time() * 1000))))
    path = parts.path if parts.path.endswith("/") else parts.path + "/"
    return urlunsplit((parts.scheme, parts.netloc, path, urlencode(q), ""))


def _pinterest_hostname_ok(host: str) -> bool:
    h = (host or "").lower()
    return h == "pinterest.com" or h.endswith(".pinterest.com")


def normalize_boards_listing_page_url(url: str) -> str:
    """Normalize stored user input: https, lowercase host, trailing slash on path."""
    u = (url or "").strip()
    if not u:
        return ""
    if u.startswith("http://"):
        u = "https://" + u[7:]
    u = u.split("#")[0].strip()
    try:
        p = urlsplit(u)
        if not p.scheme:
            return u
        path = p.path or "/"
        if path != "/" and not path.endswith("/"):
            path = path + "/"
        return urlunsplit((p.scheme, (p.hostname or "").lower(), path, "", ""))
    except Exception:
        return u


def is_valid_boards_listing_page_url(url: str) -> bool:
    """
    True for a profile-style or “all boards” page, not a single board.

    Examples: ``https://it.pinterest.com/username/``, ``https://www.pinterest.com/me/boards/``.
    Not: ``https://it.pinterest.com/username/character-art/`` (that is one board).
    """
    u = normalize_boards_listing_page_url(url)
    if not u.startswith("https://"):
        return False
    try:
        p = urlsplit(u)
        if not _pinterest_hostname_ok(p.hostname or ""):
            return False
        low = u.lower()
        if "/pin/" in low or "/search" in low or "/ideas/" in low:
            return False
        segs = [x for x in p.path.split("/") if x]
        if len(segs) == 0:
            return False
        if len(segs) == 1:
            bad = frozenset(
                {
                    "pin",
                    "pins",
                    "search",
                    "login",
                    "signup",
                    "ideas",
                    "videos",
                    "shopping",
                    "explore",
                }
            )
            return segs[0].lower() not in bad
        if len(segs) == 2:
            a, b = segs[0].lower(), segs[1].lower()
            if a == "me" and b == "boards":
                return True
            if b == "boards":
                return True
            return False
        return False
    except Exception:
        return False


def is_valid_user_board_url(url: str) -> bool:
    """Allow only pinterest.com user/board style URLs (not /pin/, search, etc.)."""
    u = (url or "").strip().lower()
    if not u.startswith("https://"):
        return False
    try:
        p = urlsplit(url.strip())
        if not _pinterest_hostname_ok(p.hostname or ""):
            return False
    except Exception:
        return False
    if "/pin/" in u or "/search" in u or "/ideas/" in u:
        return False
    try:
        p = urlsplit(url.strip())
        segs = [x for x in p.path.split("/") if x]
        return len(segs) >= 2
    except Exception:
        return False


def fetch_my_boards_list(
    listing_page_url: str,
    *,
    headless: bool = True,
    timeout_ms: int = 90_000,
) -> list[dict]:
    """Scrape board cards from the user's configured profile or saved-boards page."""
    if not has_session():
        raise PinterestSessionError("Not connected to Pinterest. Sync from browser first.")
    page_url = normalize_boards_listing_page_url(listing_page_url)
    if not is_valid_boards_listing_page_url(page_url):
        raise PinterestSessionError("Invalid boards listing page URL.")

    bust = page_url.rstrip("/")
    sep = "&" if "?" in bust else "?"
    boards_url = f"{bust}{sep}_JAPWcb={int(time.time() * 1000)}"

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=playwright_effective_headless(headless), args=list(_CHROMIUM_ARGS)
        )
        try:
            context = browser.new_context(**_playwright_context_options())
            page = context.new_page()

            def intercept(route):
                if route.request.resource_type in ("image", "media", "font"):
                    route.abort()
                else:
                    route.fallback()

            page.route("**/*", intercept)
            page.goto(boards_url, wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_timeout(500)
            for _ in range(6):
                for _w in range(_SCRAPE_BURST_WHEELS):
                    page.mouse.wheel(0, _SCRAPE_WHEEL_DELTA)
                page.wait_for_timeout(_SCRAPE_PAUSE_HOME_MS)
            raw = page.evaluate(_BOARDS_EXTRACT_JS)
            context.close()
        finally:
            browser.close()

    boards: list[dict] = []
    seen_u: set[str] = set()
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            u = (item.get("url") or "").strip()
            t = (item.get("title") or "Board").strip() or "Board"
            if not u or not is_valid_user_board_url(u):
                continue
            nu = u.rstrip("/") + "/"
            if nu in seen_u:
                continue
            seen_u.add(nu)
            boards.append({"title": t[:200], "url": nu})
    boards.sort(key=lambda b: (b.get("title") or "").lower())
    if not boards and playwright_effective_headless(headless) and playwright_visible_fallback_allowed():
        return fetch_my_boards_list(page_url, headless=False, timeout_ms=timeout_ms)
    return boards


def _run_board_pins_scrape(
    board_url: str,
    *,
    headless: bool,
    timeout_ms: int,
    exclude_canonical_keys: set[str] | frozenset | None,
    scroll_steps: int,
    max_urls: int,
) -> list[dict]:
    if not is_valid_user_board_url(board_url):
        raise PinterestSessionError("Invalid board URL.")

    from playwright.sync_api import sync_playwright

    target = _board_url_busted(board_url)
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=playwright_effective_headless(headless), args=list(_CHROMIUM_ARGS)
        )
        try:
            context = browser.new_context(**_playwright_context_options())
            page = context.new_page()

            def intercept(route):
                if route.request.resource_type in ("image", "media", "font"):
                    route.abort()
                else:
                    route.fallback()

            page.route("**/*", intercept)
            page.goto(target, wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_timeout(400)
            posts = collect_image_urls_from_page(
                page,
                scroll_steps=scroll_steps,
                scroll_pause_ms=_SCRAPE_PAUSE_HOME_MS,
                max_urls=max_urls,
                mode="home",
                exclude_canonical_keys=exclude_canonical_keys,
            )
            _enrich_with_pin_urls(page, posts)
            posts = merge_posts_same_pin(posts)
            context.close()
        finally:
            browser.close()
    return posts


def fetch_board_pins(
    board_url: str,
    *,
    headless: bool = True,
    timeout_ms: int = 90_000,
) -> list[dict]:
    if not has_session():
        raise PinterestSessionError("Not connected to Pinterest. Sync from browser first.")
    if not is_valid_user_board_url(board_url):
        raise PinterestSessionError("Invalid board URL.")

    posts = _run_board_pins_scrape(
        board_url,
        headless=headless,
        timeout_ms=timeout_ms,
        exclude_canonical_keys=None,
        scroll_steps=9,
        max_urls=48,
    )
    if not posts and headless and playwright_visible_fallback_allowed():
        posts = _run_board_pins_scrape(
            board_url,
            headless=False,
            timeout_ms=timeout_ms,
            exclude_canonical_keys=None,
            scroll_steps=9,
            max_urls=48,
        )
    return posts


def fetch_board_pins_more(
    board_url: str,
    seen_keys: set[str] | frozenset,
    *,
    headless: bool = True,
    timeout_ms: int = 90_000,
    batch_size: int = 40,
) -> list[dict]:
    if not has_session():
        raise PinterestSessionError("Not connected to Pinterest. Sync from browser first.")
    if not is_valid_user_board_url(board_url):
        raise PinterestSessionError("Invalid board URL.")

    sk = frozenset(seen_keys)
    posts = _run_board_pins_scrape(
        board_url,
        headless=headless,
        timeout_ms=timeout_ms,
        exclude_canonical_keys=sk,
        scroll_steps=14,
        max_urls=batch_size,
    )
    if not posts and headless and playwright_visible_fallback_allowed():
        posts = _run_board_pins_scrape(
            board_url,
            headless=False,
            timeout_ms=timeout_ms,
            exclude_canonical_keys=sk,
            scroll_steps=14,
            max_urls=batch_size,
        )
    return posts

_auth_lock = threading.Lock()
_auth_sync_in_progress = False
_last_login_error: str | None = None

# Canonical pin-image keys from the last successful home load (search omits these).
_last_home_canonical_keys: frozenset[str] = frozenset()


class PinterestSessionError(Exception):
    """No saved session or Playwright / cookie import failure."""


def get_storage_path() -> Path:
    return get_app_data_dir() / "pinterest_state.json"


def has_session() -> bool:
    p = get_storage_path()
    return p.is_file() and p.stat().st_size > 0


def _set_last_login_error(msg: str | None) -> None:
    global _last_login_error
    _last_login_error = msg


def clear_session() -> None:
    p = get_storage_path()
    if p.exists():
        p.unlink()
    _set_last_login_error(None)
    _home_buf_reset()
    _search_buf_reset()
    _apibr_teardown()


def is_login_in_progress() -> bool:
    return _auth_sync_in_progress


def get_last_login_error() -> str | None:
    return _last_login_error


def try_begin_sync() -> bool:
    """Return True if this caller should start the sync worker; False if already running."""
    global _auth_sync_in_progress
    with _auth_lock:
        if _auth_sync_in_progress:
            return False
        _auth_sync_in_progress = True
        return True


def finish_sync() -> None:
    global _auth_sync_in_progress
    with _auth_lock:
        _auth_sync_in_progress = False


def run_cookie_sync_thread_entry() -> None:
    """Run on a daemon thread after try_begin_sync() returned True."""
    _set_last_login_error(None)
    try:
        sync_session_from_installed_browsers()
        if has_session():
            # Reload the browser context so it picks up the newly-saved
            # session cookies.  Without this, the persistent BrowserContext
            # retains the cookies it was created with and all API calls return 401.
            _apibr_reload_session()
            _home_buf_reset()
            _home_buf_start_fill()
    except PinterestSessionError as e:
        _set_last_login_error(str(e))
    except Exception as e:
        _set_last_login_error(str(e))
    finally:
        finish_sync()


def _is_pinterest_domain(domain: str) -> bool:
    d = (domain or "").lstrip(".").lower()
    return d == "pinterest.com" or d.endswith(".pinterest.com")


def _firefox_fork_profile_roots() -> list[Path]:
    """
    Zen, Floorp, Waterfox, etc. keep profiles under their own AppData folder, not
    Mozilla/Firefox — browser_cookie3.firefox() only checks the latter by default.
    """
    appdata = Path(os.environ.get("APPDATA", ""))
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    roots: list[Path] = []
    vendors = (
        "zen",
        "Zen",
        "zen-browser",
        "Zen Browser",
        "floorp",
        "Floorp",
        "Waterfox",
    )
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


def _gather_pinterest_cookies() -> list[Cookie]:
    try:
        import browser_cookie3 as bc3
    except ImportError as e:
        raise PinterestSessionError(
            "Missing the browser-cookie3 package. Open a terminal in the JAPW folder and run: "
            "pip install browser-cookie3"
        ) from e

    by_key: dict[tuple[str, str, str], Cookie] = {}
    loader_names = (
        "chrome",
        "chromium",
        "edge",
        "brave",
        "opera",
        "opera_gx",
        "vivaldi",
        "firefox",
        "safari",
        "librewolf",
    )

    def add_from(iterator) -> None:
        try:
            for c in iterator:
                dom = getattr(c, "domain", "") or ""
                if not _is_pinterest_domain(dom):
                    continue
                key = (c.name, dom, getattr(c, "path", None) or "/")
                by_key[key] = c
        except Exception:
            pass

    for name in loader_names:
        loader = getattr(bc3, name, None)
        if not callable(loader):
            continue
        try:
            add_from(loader(domain_name="pinterest.com"))
        except Exception:
            pass

    # Zen Browser and other Firefox forks: explicit cookies.sqlite paths
    for sqlite_path in _iter_cookies_sqlite_files(_firefox_fork_profile_roots()):
        try:
            add_from(bc3.firefox(cookie_file=str(sqlite_path), domain_name="pinterest.com"))
        except Exception:
            try:
                add_from(bc3.firefox(cookie_file=str(sqlite_path)))
            except Exception:
                pass

    if not by_key:
        for name in loader_names:
            loader = getattr(bc3, name, None)
            if not callable(loader):
                continue
            try:
                for c in loader():
                    dom = getattr(c, "domain", "") or ""
                    if "pinterest" not in dom.lower():
                        continue
                    key = (c.name, dom, getattr(c, "path", None) or "/")
                    by_key[key] = c
            except Exception:
                pass

    return list(by_key.values())


def _playwright_cookie_expires(raw) -> int:
    """
    Playwright storage_state only allows expires: -1 (session) or a positive
    Unix timestamp in whole seconds. Firefox/Zen/SQLite sources may use 0,
    fractional seconds, milliseconds, or PRTime (microseconds).
    """
    if raw is None:
        return -1
    try:
        exp = float(raw)
    except (TypeError, ValueError):
        return -1
    if exp != exp:  # NaN
        return -1
    if exp <= 0:
        return -1
    # Reasonable Unix seconds are below ~4.1e9 (year 2100). Larger values are
    # almost certainly ms or µs since epoch (common in Firefox-family DBs).
    if exp > 4_102_441_920:
        if exp > 1e14:
            exp = exp / 1_000_000.0
        elif exp > 1e11:
            exp = exp / 1000.0
    exp_i = int(exp)
    if exp_i <= 0:
        return -1
    return exp_i


def _cookie_to_playwright_entry(c: Cookie) -> dict:
    domain = c.domain or ".pinterest.com"
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
        "secure": bool(c.secure),
        "sameSite": "Lax",
    }


def _sanitize_storage_state_for_playwright(state: dict) -> dict:
    """Ensure every cookie expires is -1 or a positive int (seconds)."""
    cookies = state.get("cookies") or []
    fixed: list[dict] = []
    for entry in cookies:
        if not isinstance(entry, dict):
            continue
        e = dict(entry)
        e["expires"] = _playwright_cookie_expires(e.get("expires"))
        fixed.append(e)
    return {"cookies": fixed, "origins": state.get("origins") or []}


def _cookies_to_storage_state(cookies: list[Cookie]) -> dict:
    by_key: dict[tuple[str, str, str], dict] = {}
    for c in cookies:
        if not _is_pinterest_domain(getattr(c, "domain", "") or ""):
            continue
        entry = _cookie_to_playwright_entry(c)
        k = (entry["name"], entry["domain"], entry["path"])
        by_key[k] = entry
    return _sanitize_storage_state_for_playwright(
        {"cookies": list(by_key.values()), "origins": []}
    )


def sync_session_from_installed_browsers() -> None:
    """
    Read Pinterest cookies from local browsers (Chrome, Edge, Firefox, …) and
    write Playwright-compatible storage_state JSON. No extra browser window.
    """
    cookies = _gather_pinterest_cookies()
    if not cookies:
        raise PinterestSessionError(
            "No Pinterest cookies found. Log in at pinterest.com (e.g. in Zen, Firefox, "
            "Chrome, or Edge), then use Sync from browser again. If sync still fails, "
            "close the browser completely so cookies.sqlite is not locked, then retry."
        )
    state = _cookies_to_storage_state(cookies)
    if not state["cookies"]:
        raise PinterestSessionError(
            "Found no usable Pinterest cookies. Log in on pinterest.com in a supported "
            "browser, then sync again."
        )
    path = get_storage_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f)


def _normalize_pin_url(url: str) -> str | None:
    url = url.split("?")[0].strip()
    u_lower = url.lower()
    if "i.pinimg.com" not in u_lower:
        return None
        
    # Filter out profile pictures, headers, and small UI thumbnails to keep feeds natural
    if any(skip in u_lower for skip in (
        "/75x75", "/150x150", "/140x140", "/200x200", 
        "_rs", "_t", "/avatars/", "/profile/"
    )):
        return None

    if url.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif")):
        return url
    if re.match(r"https://i\.pinimg\.com/[\w/]+", url, re.I):
        return url
    return None


def _pinimg_canonical_key(url: str) -> str:
    """
    Same pin image is often served as 236x, 474x, 736x, originals, etc.,
    sometimes in different formats (.jpg vs .gif).
    The path after the size bucket identifies one logical image.
    """
    u = url.split("?")[0].strip().lower()
    if "i.pinimg.com" not in u:
        return u.rsplit(".", 1)[0] if "." in u else u
        
    m = re.match(r"https?://i\.pinimg\.com/[^/]+/(.+)", u)
    if m:
        path = m.group(1)
        # Strip extension so .gif and .jpg variants of the same hash collide
        if "." in path:
            path = path.rsplit(".", 1)[0]
        return path
    
    if "." in u:
        return u.rsplit(".", 1)[0]
    return u


def _pinimg_quality_score(url: str) -> int:
    """Prefer larger / original assets when collapsing duplicates."""
    u = url.lower()
    score = 0
    
    # Massively prefer animated assets when resolving identical pins
    if u.endswith(".gif") or "/originals/" in u and ".gif" in u:
        score += 500_000

    if "/originals/" in u or re.search(r"pinimg\.com/originals/", u):
        score += 100_000
        return score
        
    m = re.search(r"pinimg\.com/(\d+)x(?:\d+)?/", u)
    if m:
        score += int(m.group(1))
    return score


def dedupe_pinimg_urls(urls: list[str]) -> list[str]:
    """One URL per logical Pinterest CDN image; keep the highest-quality variant."""
    order: list[str] = []
    best: dict[str, str] = {}
    for raw in urls:
        u = (raw or "").strip()
        if not u:
            continue
        key = _pinimg_canonical_key(u)
        if key not in best:
            best[key] = u
            order.append(key)
        elif _pinimg_quality_score(u) > _pinimg_quality_score(best[key]):
            best[key] = u
    return [best[k] for k in order]


def record_home_pins_for_search_filter(urls: list[str], *, merge: bool = False) -> None:
    """Remember images from the home feed so search can drop the same pins."""
    global _last_home_canonical_keys
    keys = {_pinimg_canonical_key(u) for u in urls if u and (u or "").strip()}
    if merge:
        _last_home_canonical_keys = frozenset(set(_last_home_canonical_keys) | keys)
    else:
        _last_home_canonical_keys = frozenset(keys)


def exclude_pins_seen_on_home(urls: list[str]) -> list[str]:
    """Remove URLs whose image was on the last home scrape (same pin, any size)."""
    if not _last_home_canonical_keys:
        return list(urls)
    return [u for u in urls if _pinimg_canonical_key(u) not in _last_home_canonical_keys]


def canonical_keys_from_urls(urls: list[str]) -> set[str]:
    """Build canonical pin keys for infinite-scroll / dedupe (matches _pinimg_canonical_key)."""
    return {_pinimg_canonical_key(str(u).strip()) for u in urls if u and str(u).strip()}


def _urls_from_text(text: str) -> set[str]:
    out: set[str] = set()
    for m in PINIMG_URL_RE.finditer(text):
        n = _normalize_pin_url(m.group(0))
        if n:
            out.add(n)
    return out


def _walk_json_for_urls(obj, out: set[str]) -> None:
    if isinstance(obj, dict):
        for v in obj.values():
            _walk_json_for_urls(v, out)
    elif isinstance(obj, list):
        for item in obj:
            _walk_json_for_urls(item, out)
    elif isinstance(obj, str):
        for u in _urls_from_text(obj):
            out.add(u)


def _walk_json_for_urls_from_bytes(body: bytes | str, out: set[str]) -> None:
    """Parse a response body and extract all pinimg URLs into *out*."""
    try:
        text = body.decode("utf-8", errors="ignore") if isinstance(body, bytes) else body
        data = json.loads(text)
        _walk_json_for_urls(data, out)
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    # Also pick up bare URLs from the raw text (not just JSON values).
    try:
        text = body.decode("utf-8", errors="ignore") if isinstance(body, bytes) else body
        out.update(_urls_from_text(text))
    except Exception:
        pass


def _promoted_truthy(v) -> bool:
    if v is True:
        return True
    if isinstance(v, (int, float)) and v != 0:
        return True
    if isinstance(v, str) and v.strip().lower() in ("true", "1", "yes"):
        return True
    return False


def _is_promoted_pin(obj: dict) -> bool:
    """Detect promoted / sponsored / shopping-ad pins from Pinterest API JSON."""
    if not isinstance(obj, dict):
        return False

    # ── Direct boolean / truthy flags ──
    for key in ("is_promoted", "isPromoted", "is_promoted_pin", "isPromotedPin"):
        if _promoted_truthy(obj.get(key)):
            return True

    # Homefeed pins include ad_match_reason: 0 for organic tiles; only a real reason counts as ad.
    amr = obj.get("ad_match_reason")
    if amr not in (None, "", 0, False, []):
        return True

    prom = obj.get("promoter")
    if isinstance(prom, dict) and len(prom) > 0:
        return True

    for key in ("promoted_by_advertiser", "promoted_by", "promotedByAdvertiser", "promotedBy"):
        v = obj.get(key)
        if v is not None and v != "" and v is not False:
            return True

    if obj.get("promoted_is_removable") is True:
        return True
    if _promoted_truthy(obj.get("is_quick_promotable")) and _promoted_truthy(obj.get("promoted_is_removable")):
        return True

    for key in ("promotion_id", "ad_creative_id", "ad_id", "campaign_id",
                "advertiser_id", "insertion_id", "ad_group_id"):
        v = obj.get(key)
        if v not in (None, "", 0, False):
            return True

    # ── Ad destination / click-through URLs ──
    for key in ("ad_destination_url", "ad_landing_page_url", "click_through_link",
                "adDestinationUrl", "adLandingPageUrl", "clickThroughLink"):
        v = obj.get(key)
        if isinstance(v, str) and v.strip():
            return True

    # ── __typename / type / entity_type ──
    tn = obj.get("__typename") or obj.get("type") or obj.get("entity_type")
    if isinstance(tn, str):
        tl = tn.lower()
        if "promot" in tl and "unpromot" not in tl:
            return True
        if "advertiser" in tl or "adpin" in tl.replace("_", ""):
            return True

    disc = obj.get("disclosure_type")
    if isinstance(disc, str) and "ad" in disc.lower():
        return True

    for key in ("is_sponsored", "show_sponsored_label", "isPaidPartnership", "is_paid_partnership"):
        if _promoted_truthy(obj.get(key)):
            return True

    # ── Module / layout wrappers ──
    for key in ("module_type", "moduleType", "feed_item_type", "layout_type"):
        v = obj.get(key)
        if isinstance(v, str):
            vl = v.lower().replace("-", "_")
            if "shopping_ad" in vl or "shoppable_ad" in vl or "ad_module" in vl or "adslot" in vl:
                return True
            if "sponsored" in vl and "unsponsored" not in vl:
                return True
            if vl.startswith("promoted") or "_promoted_" in vl or vl.endswith("_promoted"):
                return True
            if "dsa_" in vl or vl.startswith("dsa"):
                return True

    # ── Nested sub-objects that carry ad data ──
    # Pinterest often puts promoted flags in a child object like ad_data, ad_match_data,
    # or native_ad_data, while the images sit on the parent pin object.
    for key in ("ad_data", "adData", "ad_match_data", "adMatchData",
                "native_ad_data", "nativeAdData", "promoted_ad_data"):
        child = obj.get(key)
        if isinstance(child, dict) and len(child) > 0:
            # Any non-empty ad_data sub-object is a strong promoted signal.
            return True

    # ── tracking_params often encodes ad info as base64 JSON ──
    tp = obj.get("tracking_params") or obj.get("trackingParams")
    if isinstance(tp, str) and len(tp) > 20:
        try:
            import base64
            decoded = base64.b64decode(tp + "==", validate=False).decode("utf-8", errors="ignore")
            if '"is_promoted"' in decoded or '"promoted"' in decoded or '"ad_id"' in decoded:
                return True
        except Exception:
            pass

    # ── Catch-all: scan key names for obvious promo/sponsor substrings ──
    # Picks up fields like "promoted_pin_data", "sponsor_info", etc.
    for key, val in obj.items():
        if val in (None, "", False, 0, {}, []):
            continue
        kl = key.lower()
        if "promot" in kl and "unpromot" not in kl:
            return True
        if "sponsor" in kl and "unsponsor" not in kl:
            return True

    return False


def _is_ai_content_pin(obj: dict) -> bool:
    """Detect AI-generated or AI-modified pins from Pinterest API JSON."""
    if not isinstance(obj, dict):
        return False
    # Direct boolean flags Pinterest uses for AI attribution
    for key in ("is_ai_modified", "isAiModified", "has_ai_attribution", "hasAiAttribution",
                "is_ai_generated", "isAiGenerated"):
        v = obj.get(key)
        if v is True or (isinstance(v, str) and v.strip().lower() in ("true", "1")):
            return True
    # ai_content_type: non-null string means AI content
    act = obj.get("ai_content_type") or obj.get("aiContentType")
    if isinstance(act, str) and act.strip():
        return True
    # ai_creator_attribution or ai_tool_id present → AI content
    for key in ("ai_creator_attribution", "aiCreatorAttribution", "ai_tool_id", "aiToolId",
                "ai_attribution"):
        if obj.get(key) not in (None, "", {}, []):
            return True
    # __typename hints
    tn = obj.get("__typename") or ""
    if isinstance(tn, str) and "ai" in tn.lower().replace("_", ""):
        tl = tn.lower()
        if "aimodif" in tl or "aigenerat" in tl or "aicreated" in tl:
            return True
    return False


# ─── Module-level content filter flags (updated from settings) ────────────────

_filter_promoted: bool = True
_filter_ai_content: bool = False


def set_content_filters(filter_promoted: bool, filter_ai_content: bool) -> None:
    global _filter_promoted, _filter_ai_content
    _filter_promoted = filter_promoted
    _filter_ai_content = filter_ai_content


def _subtree_has_promoted_signal(obj, depth: int = 0) -> bool:
    """Recursively check whether *any* dict in *obj*'s subtree is promoted."""
    if depth > 12:
        return False
    if isinstance(obj, dict):
        if _is_promoted_pin(obj):
            return True
        for v in obj.values():
            if _subtree_has_promoted_signal(v, depth + 1):
                return True
    elif isinstance(obj, list):
        for item in obj:
            if _subtree_has_promoted_signal(item, depth + 1):
                return True
    return False


def _looks_like_pin_object(obj: dict) -> bool:
    """Heuristic: a dict that has a pin-like 'id' plus image data."""
    pid = obj.get("id")
    if not isinstance(pid, (str, int)):
        return False
    sid = str(pid).strip()
    if not sid:
        return False
    if obj.get("images") or obj.get("image_url") or obj.get("cover_images"):
        return True
    return False


def _extract_ad_urls_from_json(obj, ad_set: set[str], _parent=None) -> None:
    """Walk JSON and collect image URLs belonging to promoted pins.

    When a dict is identified as promoted, we collect URLs from it AND its
    parent, because Pinterest often puts the promoted marker on a child
    object while the images sit on a sibling or the parent.

    For pin-like objects (have ``id`` + ``images``), a deep subtree scan is
    performed so that promoted markers buried several levels deep still
    cause the pin's images to be flagged.
    """
    if isinstance(obj, dict):
        if _is_promoted_pin(obj):
            _walk_json_for_urls(obj, ad_set)
            if _parent is not None:
                _walk_json_for_urls(_parent, ad_set)
            return
        # Deep scan: if this looks like a pin object, check its entire
        # subtree for any promoted signal. This catches cases where the
        # promoted marker is 2+ levels below the images.
        if _looks_like_pin_object(obj) and _subtree_has_promoted_signal(obj):
            _walk_json_for_urls(obj, ad_set)
            if _parent is not None:
                _walk_json_for_urls(_parent, ad_set)
            return
        for v in obj.values():
            _extract_ad_urls_from_json(v, ad_set, _parent=obj)
    elif isinstance(obj, list):
        for item in obj:
            _extract_ad_urls_from_json(item, ad_set, _parent=_parent)


def _extract_ai_urls_from_json(obj, ai_set: set[str]) -> None:
    """Walk JSON and collect image URLs belonging to AI-content pins."""
    if isinstance(obj, dict):
        if _is_ai_content_pin(obj):
            _walk_json_for_urls(obj, ai_set)
            return
        for v in obj.values():
            _extract_ai_urls_from_json(v, ai_set)
    elif isinstance(obj, list):
        for item in obj:
            _extract_ai_urls_from_json(item, ai_set)


def _extract_pin_image_map(obj, out_map: dict[str, str]) -> None:
    """
    Walk Pinterest XHR JSON and populate out_map with {img_canonical_key: pin_id}.

    Pinterest API responses contain pin objects of the form:
        {"id": "123456789012345", "images": {"736x": {"url": "https://i.pinimg.com/..."}}}
    We collect every pinimg URL found inside such an object and map it to the pin ID,
    giving a reliable img → pin_url binding without touching the DOM.
    """
    if isinstance(obj, dict):
        pin_id_raw = obj.get("id")
        if isinstance(pin_id_raw, (str, int)):
            sid = str(pin_id_raw).strip()
            # Pinterest pin IDs are long numeric strings (8–19 digits).
            if sid.isdigit() and len(sid) >= 8:
                # Standard "images" dict: {"736x": {"url": "..."}, "originals": {...}}
                images = obj.get("images")
                if isinstance(images, dict):
                    for size_data in images.values():
                        if isinstance(size_data, dict):
                            url = (size_data.get("url") or "").split("?")[0]
                            if "pinimg.com" in url:
                                k = _pinimg_canonical_key(url)
                                if k:
                                    out_map.setdefault(k, sid)
                # Some responses use cover_images or image_url at top level
                for field in ("cover_images", "coverImages"):
                    cov = obj.get(field)
                    if isinstance(cov, dict):
                        for size_data in cov.values():
                            if isinstance(size_data, dict):
                                url = (size_data.get("url") or "").split("?")[0]
                                if "pinimg.com" in url:
                                    k = _pinimg_canonical_key(url)
                                    if k:
                                        out_map.setdefault(k, sid)
                for field in ("image_url", "thumbnail_url"):
                    url = (obj.get(field) or "").split("?")[0]
                    if "pinimg.com" in url:
                        k = _pinimg_canonical_key(url)
                        if k:
                            out_map.setdefault(k, sid)
        for v in obj.values():
            _extract_pin_image_map(v, out_map)
    elif isinstance(obj, list):
        for item in obj:
            _extract_pin_image_map(item, out_map)


def _collect_from_response_body(
    body: bytes | str,
    network_raw: list,
    carousel_map: dict,
    ad_urls: set[str],
    pin_image_map: dict[str, str],
    ai_urls: set[str] | None = None,
) -> None:
    if not body:
        return
    if isinstance(body, bytes):
        try:
            text = body.decode("utf-8", errors="ignore")
        except Exception:
            return
    else:
        text = body
    out = set()
    out |= _urls_from_text(text)
    try:
        data = json.loads(text)
        _walk_json_for_urls(data, out)
        _extract_carousels_from_json(data, carousel_map)
        _extract_ad_urls_from_json(data, ad_urls)
        if ai_urls is not None:
            _extract_ai_urls_from_json(data, ai_urls)
        _extract_pin_image_map(data, pin_image_map)
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    network_raw.extend(list(out))

def _register_carousel_slot_urls(slots: list, out_map: dict) -> None:
    """Append one best pinimg URL per carousel slot; register multi-image group in out_map."""
    urls: list[str] = []
    for slot in slots:
        found: set[str] = set()
        _walk_json_for_urls(slot, found)
        if found:
            best = dedupe_pinimg_urls(list(found))
            if best:
                urls.append(best[0])
    if len(urls) > 1:
        k = _pinimg_canonical_key(urls[0])
        if k not in out_map or len(urls) > len(out_map[k]):
            out_map[k] = urls


def _extract_carousels_from_json(obj, out_map: dict) -> None:
    if isinstance(obj, dict):
        cd = obj.get("carousel_data")
        if isinstance(cd, dict) and isinstance(cd.get("carousel_slots"), list):
            _register_carousel_slot_urls(cd.get("carousel_slots"), out_map)

        # Some XHR payloads expose carousel_slots without a carousel_data wrapper.
        if isinstance(obj.get("carousel_slots"), list) and not (
            isinstance(cd, dict) and isinstance(cd.get("carousel_slots"), list)
        ):
            _register_carousel_slot_urls(obj["carousel_slots"], out_map)

        sd = obj.get("story_pin_data")
        if isinstance(sd, dict) and isinstance(sd.get("pages"), list):
            _register_carousel_slot_urls(sd.get("pages"), out_map)

        for v in obj.values():
            _extract_carousels_from_json(v, out_map)
    elif isinstance(obj, list):
        for item in obj:
            _extract_carousels_from_json(item, out_map)


def _expand_carousel_map_all_keys(carousel_map: dict[str, list[str]]) -> dict[str, list[str]]:
    """
    Pinterest order in JSON may not match grid order. Map every slide's canonical key to the
    full URL list so whichever image appears first in the DOM still merges / suppresses siblings.
    """
    if not carousel_map:
        return carousel_map
    out: dict[str, list[str]] = dict(carousel_map)
    seen_lists: set[tuple[str, ...]] = set()
    for urls in list(carousel_map.values()):
        if not isinstance(urls, list) or len(urls) < 2:
            continue
        deduped = dedupe_pinimg_urls(urls)
        if len(deduped) < 2:
            continue
        sig = tuple(deduped)
        if sig in seen_lists:
            continue
        seen_lists.add(sig)
        for u in deduped:
            k = _pinimg_canonical_key(u)
            prev = out.get(k)
            if prev is None or len(deduped) > len(prev):
                out[k] = list(deduped)
    return out


def stream_image_urls_from_page(
    page,
    *,
    scroll_steps: int = 6,
    scroll_pause_ms: int = 250,
    max_urls: int = 80,
    mode: str = "home",
    exclude_canonical_keys: set[str] | frozenset | None = None,
):
    # Read filter flags at call time (module-level, updated from settings)
    do_filter_promoted = _filter_promoted
    do_filter_ai = _filter_ai_content

    network_raw: list[str] = []
    carousel_map: dict[str, list[str]] = {}
    ad_urls: set[str] = set()
    ai_urls: set[str] = set() if do_filter_ai else None  # type: ignore[assignment]
    pin_image_map: dict[str, str] = {}  # canonical_key → pin_id (from XHR JSON)
    promoted_pin_ids: set[str] = set()  # pin IDs confirmed promoted via URL signals

    _PROMOTED_URL_SIGNAL = re.compile(
        r'"is_promoted"\s*:\s*true|'
        r'"isPromoted"\s*:\s*true|'
        r'"promoted_is_removable"\s*:\s*true|'
        r'UserExperienceResource.*is_promoted',
        re.IGNORECASE,
    )
    _PIN_ID_FROM_URL = re.compile(r'"pin_id"\s*:\s*"([^"]+)"')

    def on_response(response) -> None:
        try:
            u = response.url
            ct = response.headers.get("content-type")
            if not _worth_reading_response_body(u, ct):
                # Even if the body isn't worth reading, the URL itself might
                # reveal a promoted pin ID (the UserExperienceResource URL
                # carries the pin_id in its query string).
                if do_filter_promoted and _PROMOTED_URL_SIGNAL.search(u):
                    m = _PIN_ID_FROM_URL.search(u)
                    if m:
                        promoted_pin_ids.add(m.group(1))
                return
            body = response.body()
            if do_filter_promoted and _PROMOTED_URL_SIGNAL.search(u):
                _collect_from_response_body(body, [], carousel_map, ad_urls, pin_image_map, ai_urls)
                found: set[str] = set()
                _walk_json_for_urls_from_bytes(body, found)
                ad_urls.update(found)
                m = _PIN_ID_FROM_URL.search(u)
                if m:
                    promoted_pin_ids.add(m.group(1))
                return
            _collect_from_response_body(body, network_raw, carousel_map, ad_urls, pin_image_map, ai_urls)
        except Exception:
            pass

    page.on("response", on_response)

    if mode == "search":
        steps = scroll_steps + 4
        pause = max(scroll_pause_ms, _SCRAPE_PAUSE_SEARCH_MS)
        settle_ms = _SCRAPE_SETTLE_SEARCH_MS
        wheel_delta = max(900, _SCRAPE_WHEEL_DELTA // 2)
        wheel_bursts = 1
    elif mode == "pin_related":
        steps = scroll_steps + 2
        pause = scroll_pause_ms
        settle_ms = _SCRAPE_SETTLE_HOME_MS
        wheel_delta = _SCRAPE_WHEEL_DELTA
        wheel_bursts = _SCRAPE_BURST_WHEELS
    else:
        steps = scroll_steps
        pause = scroll_pause_ms
        settle_ms = _SCRAPE_SETTLE_HOME_MS
        wheel_delta = _SCRAPE_WHEEL_DELTA
        wheel_bursts = _SCRAPE_BURST_WHEELS

    _mark_ai_js_extra = """
  // Mark AI-modified / AI-generated pin containers
  const markAiContainer = (el) => {
    let n = el.parentElement;
    for (let d = 0; d < 30 && n && n !== document.body; d++, n = n.parentElement) {
      if (n.querySelector('img[src*="pinimg"], img[srcset*="pinimg"]')) {
        n.setAttribute('data-JAPW-ai', '1');
        return;
      }
    }
  };
  document.querySelectorAll('[title]').forEach(el => {
    if (/^\\s*ai\\s*(modified|generated|created)\\s*$/i.test(el.getAttribute('title') || '')) markAiContainer(el);
  });
  document.querySelectorAll('div, span').forEach(el => {
    if (el.childElementCount === 0 && /^ai\\s*(modified|generated|created)$/i.test((el.textContent || '').trim())) markAiContainer(el);
  });
""" if do_filter_ai else ""

    _MARK_ADS_JS = """
  // Walk UP from a sponsored label to the nearest ancestor that contains a pinimg
  // (including inside shadow roots). Mark that subtree with data-JAPW-ad.
  const markAdContainer = (el) => {
    if (!el) return;
    let n = el.parentElement;
    for (let d = 0; d < 30 && n && n !== document.body; d++, n = n.parentElement) {
      if (subtreeHasPinImg(n)) {
        n.setAttribute('data-JAPW-ad', '1');
        return;
      }
    }
  };
  const titleLooksSponsored = (t) => {
    const s = (t || '').trim();
    if (!s) return false;
    if (/^promoted\\s+by\\b/i.test(s)) return true;
    if (/^(sponsored|promoted|promoted by)$/i.test(s)) return true;
    // e.g. "Sponsored · Brand" or localized strings that still contain the word
    if (/\\bsponsored\\b/i.test(s) && s.length < 80) return true;
    return false;
  };
  walkElementsDeep(document.documentElement, (el) => {
    if (!el.hasAttribute('title')) return;
    if (titleLooksSponsored(el.getAttribute('title'))) markAdContainer(el);
  });
  // Visible "Sponsored" / "Promoted" labels (home feed uses a div with title + text, sometimes nested)
  walkElementsDeep(document.documentElement, (el) => {
    if (el.tagName !== 'DIV' && el.tagName !== 'SPAN') return;
    const tx = (el.textContent || '').replace(/\\s+/g, ' ').trim();
    if (!tx || tx.length > 80) return;
    if (/^(sponsored|promoted|promoted by)$/i.test(tx)) markAdContainer(el);
    else if (/^promoted\\s+by\\b/i.test(tx)) markAdContainer(el);
  });
  walkElementsDeep(document.documentElement, (el) => {
    const al = el.getAttribute('aria-label') || '';
    const tid = el.getAttribute('data-test-id') || el.getAttribute('data-testid') || '';
    if (/\\bsponsored\\b|\\bpromoted\\b|paid\\s+partnership/i.test(al) ||
        /sponsored|promoted|shopping-ad|shoppable-ad|ad-badge|dsa-|paid-partnership/i.test(tid)) {
      markAdContainer(el);
    }
  });
""" + _mark_ai_js_extra

    dom_script = (
        """() => {
  const out = [];
  const seen = new Set();
  const normKey = (u) => (u || '').split('?')[0];
  const push = (raw) => {
    if (!raw || !raw.includes('pinimg')) return;
    const k = normKey(raw);
    if (seen.has(k)) return;
    seen.add(k);
    out.push(raw);
  };
  // Pinterest often renders the grid inside shadow roots; plain document.querySelectorAll misses it.
  const walkElementsDeep = (root, callback) => {
    const go = (node) => {
      if (!node || node.nodeType !== 1) return;
      callback(node);
      for (let c = node.firstElementChild; c; c = c.nextElementSibling) go(c);
      if (node.shadowRoot) go(node.shadowRoot);
    };
    go(root);
  };
  const subtreeHasPinImg = (root) => {
    let found = false;
    const walk = (node) => {
      if (!node || found || node.nodeType !== 1) return;
      if (node.matches && node.matches('img[src*="pinimg"], img[srcset*="pinimg"]')) {
        found = true;
        return;
      }
      for (let c = node.firstElementChild; c && !found; c = c.nextElementSibling) walk(c);
      if (node.shadowRoot && !found) walk(node.shadowRoot);
    };
    walk(root);
    return found;
  };
  const eachPinImgDeep = (root, fn) => {
    walkElementsDeep(root, (node) => {
      if (node.matches && node.matches('img[src*="pinimg"], img[srcset*="pinimg"]')) fn(node);
    });
  };
"""
        + _MARK_ADS_JS
        + (
            """
  const junk = (img) => !!img.closest(
    '[aria-label*="More ideas" i], [data-test-id="more-ideas"], ' +
    '[data-test-id="Homefeed"], [aria-label="Homefeed"], ' +
    '[data-test-id="today-tab"], [aria-label="Today"], ' +
    '[data-test-id="aggregated-comment"]'
  );
  const roots = [
    document.querySelector('[aria-label="Search results"]'),
    document.querySelector('[data-test-id="search-feed"]'),
    document.querySelector('[data-testid="search-results"]'),
    document.querySelector('[data-test-id="search-pin-grid"]'),
    document.querySelector('[data-testid="search-pin-grid"]'),
  ].filter(Boolean);
  const grab = (img) => {
    if (junk(img)) return;
    if (img.closest('[data-JAPW-ad]')) return;
    if (img.closest('[data-JAPW-ai]')) return;
    if (img.src) push(img.src);
    const ss = img.getAttribute('srcset');
    if (ss) ss.split(',').forEach(part => { push(part.trim().split(/\\s+/)[0]); });
  };
  if (roots.length) {
    roots.forEach(root => eachPinImgDeep(root, grab));
  } else {
    eachPinImgDeep(document.documentElement, grab);
  }
  return out;
}"""
            if mode == "search"
            else (
                """
  const junk = (img) => !!img.closest(
    '[aria-label*="More ideas" i], [data-test-id="aggregated-comment"], [data-test-id="Homefeed"]'
  );
  const roots = [];
  const seenRoot = new Set();
  const addRoot = (el) => {
    if (!el || seenRoot.has(el)) return;
    const n = el.querySelectorAll('img[src*="pinimg"]').length;
    if (n < 2) return;
    seenRoot.add(el);
    roots.push(el);
  };
  ['main', '[data-test-id="visual-content-container"]', '[data-test-id="closeup-bottom"]',
   '[data-test-id="related-repins"]', '[data-testid="related-repins"]', '[data-test-id="relatedPins"]',
   '[data-test-id="repinTray"]', 'div[role="list"]'].forEach(sel => {
    const e = document.querySelector(sel);
    if (e) addRoot(e);
  });
  document.querySelectorAll('[aria-label*="More like this" i], [aria-label*="more like this" i], [aria-label*="Similar" i]').forEach(h => {
    let n = h;
    for (let i = 0; i < 18 && n; i++, n = n.parentElement) {
      if (n.querySelectorAll && n.querySelectorAll('img[src*="pinimg"]').length >= 3) {
        addRoot(n);
        break;
      }
    }
  });
  const grab = (img) => {
    if (junk(img)) return;
    if (img.closest('[data-JAPW-ad]')) return;
    if (img.closest('[data-JAPW-ai]')) return;
    if (img.src) push(img.src);
    const ss = img.getAttribute('srcset');
    if (ss) ss.split(',').forEach(part => { push(part.trim().split(/\\s+/)[0]); });
  };
  if (roots.length) {
    roots.forEach(root => eachPinImgDeep(root, grab));
  } else {
    eachPinImgDeep(document.documentElement, grab);
  }
  return out;
}"""
                if mode == "pin_related"
                else """
  eachPinImgDeep(document.documentElement, (img) => {
    if (img.closest('[data-JAPW-ad]')) return;
    if (img.src) push(img.src);
    const ss = img.getAttribute('srcset');
    if (ss) ss.split(',').forEach(part => { push(part.trim().split(/\\s+/)[0]); });
  });
  return out;
}"""
            )
        )
    )

    seen_yielded = set(exclude_canonical_keys) if exclude_canonical_keys else set()
    total_yielded = 0

    ad_canonical_keys: set[str] = set()
    ai_canonical_keys: set[str] = set()

    _COLLECT_DOM_AD_URLS_JS = """() => {
  const urls = [];
  const walkElementsDeep = (root, callback) => {
    const go = (node) => {
      if (!node || node.nodeType !== 1) return;
      callback(node);
      for (let c = node.firstElementChild; c; c = c.nextElementSibling) go(c);
      if (node.shadowRoot) go(node.shadowRoot);
    };
    go(root);
  };
  walkElementsDeep(document.documentElement, (el) => {
    if (!el.hasAttribute('data-JAPW-ad')) return;
    walkElementsDeep(el, (node) => {
      if (!node.matches || !node.matches('img[src*="pinimg"], img[srcset*="pinimg"]')) return;
      if (node.src) urls.push(node.src);
      const ss = node.getAttribute('srcset');
      if (ss) ss.split(',').forEach(part => { urls.push(part.trim().split(/\\s+/)[0]); });
    });
  });
  return urls;
}"""

    _COLLECT_DOM_AI_URLS_JS = """() => {
  const urls = [];
  const walkElementsDeep = (root, callback) => {
    const go = (node) => {
      if (!node || node.nodeType !== 1) return;
      callback(node);
      for (let c = node.firstElementChild; c; c = c.nextElementSibling) go(c);
      if (node.shadowRoot) go(node.shadowRoot);
    };
    go(root);
  };
  walkElementsDeep(document.documentElement, (el) => {
    if (!el.hasAttribute('data-JAPW-ai')) return;
    walkElementsDeep(el, (node) => {
      if (!node.matches || !node.matches('img[src*="pinimg"], img[srcset*="pinimg"]')) return;
      if (node.src) urls.push(node.src);
      const ss = node.getAttribute('srcset');
      if (ss) ss.split(',').forEach(part => { urls.push(part.trim().split(/\\s+/)[0]); });
    });
  });
  return urls;
}"""

    def _get_new_items() -> list[dict]:
        nonlocal ad_canonical_keys, ai_canonical_keys
        # Build canonical keys for all ad URLs discovered so far (from JSON/XHR)
        if do_filter_promoted:
            for au in ad_urls:
                n = _normalize_pin_url(au)
                if n:
                    ad_canonical_keys.add(_pinimg_canonical_key(n))
            # Retroactively mark images whose pin_id was flagged via URL signals
            # (e.g. UserExperienceResource?…is_promoted=true).
            if promoted_pin_ids:
                for ck, pid in pin_image_map.items():
                    if pid in promoted_pin_ids:
                        ad_canonical_keys.add(ck)
        if do_filter_ai and ai_urls:
            for au in ai_urls:
                n = _normalize_pin_url(au)
                if n:
                    ai_canonical_keys.add(_pinimg_canonical_key(n))

        dom_urls: list[str] = []
        try:
            for s in (page.evaluate(dom_script) or []):
                n = _normalize_pin_url(s)
                if n:
                    dom_urls.append(n)
        except Exception:
            pass

        # Bridge DOM-detected ads/AI back to the canonical key sets so network
        # URLs from the same pins are also filtered. The DOM script marks
        # containers with data-JAPW-ad / data-JAPW-ai, but those markers only
        # affect DOM-scraped URLs. Network URLs bypass the DOM entirely, so we
        # collect image URLs from marked containers and add their keys here.
        if do_filter_promoted:
            try:
                for s in (page.evaluate(_COLLECT_DOM_AD_URLS_JS) or []):
                    n = _normalize_pin_url(s)
                    if n:
                        ad_canonical_keys.add(_pinimg_canonical_key(n))
            except Exception:
                pass
        if do_filter_ai:
            try:
                for s in (page.evaluate(_COLLECT_DOM_AI_URLS_JS) or []):
                    n = _normalize_pin_url(s)
                    if n:
                        ai_canonical_keys.add(_pinimg_canonical_key(n))
            except Exception:
                pass

        dom_keys = {_pinimg_canonical_key(u) for u in dom_urls}
        network_urls: list[str] = []
        upgrades: list[str] = []
        for s in network_raw:
            n = _normalize_pin_url(s)
            if not n:
                continue
            network_urls.append(n)
            if _pinimg_canonical_key(n) in dom_keys:
                upgrades.append(n)

        # Search/home JSON/XHR often contain many valid result pins before they are rendered
        # into the currently visible DOM. Trust those responses more aggressively so the feed
        # is not capped by only the handful of cards currently on-screen.
        if mode in ("search", "home"):
            ordered = dedupe_pinimg_urls(dom_urls + network_urls)
        else:
            ordered = dedupe_pinimg_urls(dom_urls + upgrades)

        cmap = _expand_carousel_map_all_keys(carousel_map)

        # Build a set of canonical keys that appear as non-cover slides in a known carousel.
        # These must be suppressed so they don't become standalone cards — the merged post
        # already carries the full urls list for that pin.
        carousel_non_cover_keys: set[str] = set()
        seen_carousels: set[tuple[str, ...]] = set()
        for _c_urls in cmap.values():
            if not isinstance(_c_urls, list) or len(_c_urls) < 2:
                continue
            sig = tuple(_c_urls)
            if sig in seen_carousels:
                continue
            seen_carousels.add(sig)
            for _c_url in _c_urls[1:]:
                carousel_non_cover_keys.add(_pinimg_canonical_key(_c_url))

        new_items = []
        for u in ordered:
            k = _pinimg_canonical_key(u)
            if k in seen_yielded:
                continue
            if do_filter_promoted and k in ad_canonical_keys:
                seen_yielded.add(k)
                continue
            if do_filter_ai and k in ai_canonical_keys:
                seen_yielded.add(k)
                continue
            # This image is a non-cover slide of a carousel we've already seen — skip it.
            # The cover post already has this URL in its urls list.
            if k in carousel_non_cover_keys:
                seen_yielded.add(k)
                continue
            seen_yielded.add(k)

            out = {"url": u, "carousel": None}
            if k in cmap:
                c_urls = cmap[k]
                if len(c_urls) > 1:
                    out["url"] = dedupe_pinimg_urls([u, c_urls[0]])[0]
                    out["carousel"] = c_urls
            # Attach pin_url from XHR JSON data (most reliable source).
            # Also check every key in the carousel group for a pin_id match.
            pin_id = pin_image_map.get(k)
            if not pin_id and out.get("carousel"):
                for _cu in (out["carousel"] or []):
                    pin_id = pin_image_map.get(_pinimg_canonical_key(_cu))
                    if pin_id:
                        break
            if pin_id:
                out["pin_url"] = _normalized_pin_page_url(pin_id)
            new_items.append(out)
        return new_items

    for _ in range(steps):
        for _w in range(wheel_bursts):
            page.mouse.wheel(0, wheel_delta)
        page.wait_for_timeout(pause)
        items = _get_new_items()
        if items:
            yield items
            total_yielded += len(items)
            if total_yielded >= max_urls:
                break

    page.wait_for_timeout(settle_ms)
    final_items = _get_new_items()
    if final_items and total_yielded < max_urls:
        yield final_items[:max_urls - total_yielded]


def _feed_post_from_stream_item(it: dict) -> dict | None:
    """One Pinterest card: ``{"urls": [...]}`` with carousel / story pages merged."""
    u = it.get("url")
    if not u:
        return None
    n = _normalize_pin_url(u)
    if not n:
        return None
    parts: list[str] = [n]
    car = it.get("carousel")
    if isinstance(car, list):
        for c in car:
            if not c:
                continue
            cn = _normalize_pin_url(c)
            if cn:
                parts.append(cn)
    urls = dedupe_pinimg_urls(parts)
    if not urls:
        return None
    post: dict = {"urls": urls}
    if it.get("pin_url"):
        post["pin_url"] = it["pin_url"]
    return post


def collect_image_urls_from_page(
    page,
    *,
    scroll_steps: int = 6,
    scroll_pause_ms: int = 80,
    max_urls: int = 80,
    mode: str = "home",
    exclude_canonical_keys: set[str] | frozenset | None = None,
) -> list[dict]:
    """
    Scroll the feed and return posts (one dict per pin).
    Each post is ``{"urls": [str, ...]}`` — multiple URLs for carousel / story pins.
    Deduplicates by canonical key of the cover image so the same pin is not returned twice.
    """
    posts: list[dict] = []
    seen_primary: set[str] = set()
    for batch in stream_image_urls_from_page(
        page,
        scroll_steps=scroll_steps,
        scroll_pause_ms=scroll_pause_ms,
        max_urls=max_urls,
        mode=mode,
        exclude_canonical_keys=exclude_canonical_keys,
    ):
        for it in batch:
            p = _feed_post_from_stream_item(it)
            if not p:
                continue
            urls = p.get("urls") or []
            if not urls:
                continue
            pk = _pinimg_canonical_key(urls[0])
            if pk in seen_primary:
                continue
            seen_primary.add(pk)
            posts.append(p)
            if len(posts) >= max_urls:
                return posts
    return posts


def record_home_pins_for_search_filter_posts(posts: list[dict], *, merge: bool = False) -> None:
    flat: list[str] = []
    for p in posts:
        flat.extend(p.get("urls") or [])
    record_home_pins_for_search_filter(flat, merge=merge)


def exclude_posts_seen_on_home(posts: list[dict]) -> list[dict]:
    """Drop image URLs that appeared on the last home scrape; drop empty posts."""
    if not _last_home_canonical_keys:
        return list(posts)
    out: list[dict] = []
    for p in posts:
        urls = [
            u
            for u in (p.get("urls") or [])
            if _pinimg_canonical_key(u) not in _last_home_canonical_keys
        ]
        urls = dedupe_pinimg_urls(urls)
        if urls:
            out.append({"urls": urls})
    return out


def _search_url_busted(query: str) -> str:
    q = quote_plus(query.strip())
    base = SEARCH_URL_TEMPLATE.format(query=q)
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}_JAPWcb={int(time.time() * 1000)}"


def _playwright_context_options() -> dict:
    return {
        "storage_state": str(get_storage_path()),
        "viewport": {"width": 1280, "height": 900},
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
    }


def _run_home_scrape(
    *,
    headless: bool,
    timeout_ms: int,
    exclude_canonical_keys: set[str] | frozenset | None,
    scroll_steps: int,
    max_urls: int,
) -> list[dict]:
    from playwright.sync_api import sync_playwright

    feed_url = _homefeed_url_busted()
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=playwright_effective_headless(headless), args=list(_CHROMIUM_ARGS)
        )
        try:
            context = browser.new_context(**_playwright_context_options())
            page = context.new_page()

            def intercept(route):
                if route.request.resource_type in ("image", "media", "font"):
                    route.abort()
                else:
                    route.fallback()
            page.route("**/*", intercept)

            page.goto(feed_url, wait_until="domcontentloaded", timeout=timeout_ms)
            posts = collect_image_urls_from_page(
                page,
                scroll_steps=scroll_steps,
                scroll_pause_ms=_SCRAPE_PAUSE_HOME_MS,
                max_urls=max_urls,
                mode="home",
                exclude_canonical_keys=exclude_canonical_keys,
            )
            _enrich_with_pin_urls(page, posts)
            context.close()
        finally:
            browser.close()
    return posts


def _parallel_scrape(scrape_fn, n_threads: int, exclude_canonical_keys, **kwargs) -> list[dict]:
    """
    Run scrape_fn n_threads times in parallel.  Results are merged and
    deduplicated so each logical pin appears at most once in the output.
    """
    exc = frozenset(exclude_canonical_keys) if exclude_canonical_keys else frozenset()
    # Pass exclude_canonical_keys through to each scrape call
    kwargs["exclude_canonical_keys"] = exc if exc else None
    all_posts: list[dict] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=n_threads) as pool:
        futs = [pool.submit(scrape_fn, **kwargs) for _ in range(n_threads)]
        for fut in concurrent.futures.as_completed(futs):
            try:
                all_posts.extend(fut.result())
            except Exception:
                pass

    merged = merge_posts_same_pin(all_posts)
    seen: set[str] = set()
    out: list[dict] = []
    for post in merged:
        urls = post.get("urls") or []
        if not urls:
            continue
        key = _pinimg_canonical_key(urls[0])
        if key not in seen and key not in exc:
            seen.add(key)
            item = {"urls": dedupe_pinimg_urls(urls)}
            if post.get("pin_url"):
                item["pin_url"] = post["pin_url"]
            out.append(item)
    return out


def fetch_home_image_urls(
    *,
    headless: bool = True,
    timeout_ms: int = 90_000,
    force_refresh: bool = False,
) -> list[dict]:
    global _home_api_bookmark
    if not has_session():
        raise PinterestSessionError("Not connected to Pinterest. Sync from browser first.")

    if force_refresh:
        # Reset everything so the next call gets the freshest feed from the top.
        _home_buf_reset()
    else:
        # Fast path: pop from pre-fetched buffer (<100 ms when warmed up).
        posts = _home_buf_pop(60)
        if posts:
            _home_buf_start_fill()
            record_home_pins_for_search_filter_posts(posts, merge=False)
            return posts

    # Cold path: buffer not ready — open browser and call API directly.
    try:
        def _home_cold_task(ctx):
            bpage = _apibr_make_home_page(ctx)
            try:
                local_collected: list[dict] = []
                seen_k: set[str] = set()
                bm: str | None = None
                while len(local_collected) < 60:
                    page_posts, bm = _api_homefeed_page(bpage, bm, page_size=25)
                    if not page_posts:
                        break
                    for p in page_posts:
                        k = _home_buf_key(p)
                        if k and k not in seen_k:
                            seen_k.add(k)
                            local_collected.append(p)
                return local_collected, bm
            finally:
                _apibr_close_page(bpage)

        posts, bookmark = _apibr_run(_home_cold_task)
        with _home_buf_lock:
            _home_api_bookmark = bookmark
            for p in posts:
                k = _home_buf_key(p)
                if k:
                    _home_buf_served_keys.add(k)
    except Exception as exc:
        raise PinterestSessionError(f"Home feed API error: {exc}") from exc

    if posts:
        record_home_pins_for_search_filter_posts(posts, merge=False)
    _home_buf_start_fill()
    return posts


def fetch_home_more_image_urls(
    seen_keys: set[str] | frozenset,
    *,
    headless: bool = True,
    timeout_ms: int = 90_000,
    batch_size: int = 120,
) -> list[dict]:
    global _home_api_bookmark
    if not has_session():
        raise PinterestSessionError("Not connected to Pinterest. Sync from browser first.")

    # Fast path: pop from pre-fetched buffer.
    posts = _home_buf_pop(batch_size // 2)
    if posts:
        _home_buf_start_fill()
        record_home_pins_for_search_filter_posts(posts, merge=True)
        return posts

    # Cold path: buffer not ready — open browser and call API directly.
    try:
        with _home_buf_lock:
            init_bookmark = _home_api_bookmark
        sk = frozenset(seen_keys)
        target = batch_size // 2

        def _home_more_task(ctx):
            bpage = _apibr_make_home_page(ctx)
            try:
                local_collected: list[dict] = []
                local_keys: set[str] = set()
                bm = init_bookmark
                pages_tried = 0
                while len(local_collected) < target and pages_tried < 8:
                    page_posts, next_bm = _api_homefeed_page(bpage, bm, page_size=25)
                    pages_tried += 1
                    bm = next_bm
                    if not page_posts:
                        break
                    for p in page_posts:
                        k = _home_buf_key(p)
                        if k and k not in sk and k not in local_keys:
                            local_collected.append(p)
                            local_keys.add(k)
                return local_collected, bm
            finally:
                _apibr_close_page(bpage)

        posts, bookmark = _apibr_run(_home_more_task)
        with _home_buf_lock:
            _home_api_bookmark = bookmark
    except Exception as exc:
        raise PinterestSessionError(f"Home feed API error: {exc}") from exc

    if posts:
        record_home_pins_for_search_filter_posts(posts, merge=True)
    _home_buf_start_fill()
    return posts


def _run_pin_related_scrape(
    pin_page_url: str,
    *,
    headless: bool,
    timeout_ms: int,
    exclude_canonical_keys: set[str] | frozenset | None,
    scroll_steps: int,
    max_urls: int,
) -> list[dict]:
    if not is_pin_page_url(pin_page_url):
        raise PinterestSessionError("Invalid pin page URL.")

    from playwright.sync_api import sync_playwright

    target = _pin_page_url_busted(pin_page_url)
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=playwright_effective_headless(headless), args=list(_CHROMIUM_ARGS)
        )
        try:
            context = browser.new_context(**_playwright_context_options())
            page = context.new_page()

            def intercept(route):
                if route.request.resource_type in ("image", "media", "font"):
                    route.abort()
                else:
                    route.fallback()

            page.route("**/*", intercept)
            page.goto(target, wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_timeout(700)
            try:
                page.wait_for_selector(
                    "main img[src*='pinimg'], [data-test-id='visual-content-container'] img[src*='pinimg']",
                    timeout=14_000,
                )
            except Exception:
                pass
            posts = collect_image_urls_from_page(
                page,
                scroll_steps=scroll_steps,
                scroll_pause_ms=_SCRAPE_PAUSE_HOME_MS,
                max_urls=max_urls,
                mode="pin_related",
                exclude_canonical_keys=exclude_canonical_keys,
            )
            _enrich_with_pin_urls(page, posts)
            posts = merge_posts_same_pin(posts)
            context.close()
        finally:
            browser.close()
    return posts


def resolve_pin_url_for_cover_image(
    cover_image_url: str,
    *,
    headless: bool = True,
    timeout_ms: int = 75_000,
) -> str | None:
    """
    When ``pin_url`` is missing on a feed card, open homefeed and map the cover image to a
    ``/pin/{id}/`` URL using the same DOM walk as feed enrichment. Best-effort: the pin
    must still appear on-screen after scrolling (recent home).
    """
    if not has_session():
        raise PinterestSessionError("Not connected to Pinterest. Sync from your browser first.")
    n = _normalize_pin_url(cover_image_url)
    if not n:
        return None

    from playwright.sync_api import sync_playwright

    feed_url = _homefeed_url_busted()
    found: str | None = None
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=playwright_effective_headless(headless), args=list(_CHROMIUM_ARGS)
        )
        try:
            context = browser.new_context(**_playwright_context_options())
            page = context.new_page()

            def intercept(route):
                if route.request.resource_type in ("image", "media", "font"):
                    route.abort()
                else:
                    route.fallback()

            page.route("**/*", intercept)
            page.goto(feed_url, wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_timeout(450)
            for _ in range(12):
                raw_map = page.evaluate(_PIN_PAGE_URL_JS) or {}
                found = _lookup_pin_url_in_dom_map(raw_map, n)
                if found:
                    break
                for _w in range(_SCRAPE_BURST_WHEELS):
                    page.mouse.wheel(0, _SCRAPE_WHEEL_DELTA)
                page.wait_for_timeout(_SCRAPE_PAUSE_HOME_MS)
            if not found:
                raw_map = page.evaluate(_PIN_PAGE_URL_JS) or {}
                found = _lookup_pin_url_in_dom_map(raw_map, n)
            context.close()
        finally:
            browser.close()

    if not found:
        return None
    norm = normalize_pin_page_url(found)
    return norm if is_pin_page_url(norm) else None


def fetch_pin_related_posts(
    pin_page_url: str,
    exclude_urls: list[str] | None = None,
    *,
    headless: bool = True,
    timeout_ms: int = 90_000,
    scroll_steps: int = 16,
    max_posts: int = 50,
) -> list[dict]:
    """
    Fetch "more like this" pins for a given pin via Pinterest's RelatedPinFeedResource API.
    Uses the shared persistent browser — results arrive in ~1-2 s instead of 15+ s.
    ``exclude_urls`` should include the open pin's image URLs so the hero is not in the list.
    """
    if not has_session():
        raise PinterestSessionError("Not connected to Pinterest. Sync from browser first.")
    norm = normalize_pin_page_url(pin_page_url)
    if not is_pin_page_url(norm):
        raise PinterestSessionError("Invalid pin page URL.")

    pin_id = _pin_id_from_pin_page_url(norm)
    if not pin_id:
        raise PinterestSessionError("Could not extract pin ID.")

    exc_list = [str(u) for u in (exclude_urls or []) if u]
    exc = canonical_keys_from_urls(exc_list) if exc_list else set()

    try:
        def _related_task(ctx):
            pin_page = ctx.new_page()
            try:
                def _block_heavy(route):
                    if route.request.resource_type in ("image", "media", "font", "stylesheet"):
                        route.abort()
                    else:
                        route.fallback()
                pin_page.route("**/*", _block_heavy)
                pin_page.goto(norm, wait_until="domcontentloaded", timeout=30_000)
                pin_page.wait_for_timeout(800)

                local_collected: list[dict] = []
                seen_k: set[str] = set()
                bm: str | None = None
                pages_tried = 0
                while len(local_collected) < max_posts and pages_tried < 4:
                    page_posts, bm = _api_related_pins_page(pin_page, pin_id, bm, page_size=25)
                    pages_tried += 1
                    for p in page_posts:
                        k = _home_buf_key(p)
                        if not k or k in seen_k or k in exc:
                            continue
                        seen_k.add(k)
                        local_collected.append(p)
                    if not page_posts or not bm:
                        break
                return local_collected
            finally:
                _apibr_close_page(pin_page)

        collected = _apibr_run(_related_task)
    except Exception as exc_e:
        raise PinterestSessionError(f"Related pins API error: {exc_e}") from exc_e

    posts = exclude_posts_matching_pin_id(collected, pin_id)
    posts = filter_posts_excluding_image_keys(posts, frozenset(exc) if exc else None)
    return posts


def _run_search_scrape(
    query: str,
    *,
    headless: bool,
    timeout_ms: int,
    exclude_canonical_keys: set[str] | frozenset | None,
    scroll_steps: int,
    max_urls: int,
    scroll_pause_ms: int | None = None,
) -> list[dict]:
    from playwright.sync_api import sync_playwright

    pause = scroll_pause_ms if scroll_pause_ms is not None else _SCRAPE_PAUSE_SEARCH_MS
    url = _search_url_busted(query)
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=playwright_effective_headless(headless), args=list(_CHROMIUM_ARGS)
        )
        try:
            context = browser.new_context(**_playwright_context_options())
            page = context.new_page()

            def intercept(route):
                if route.request.resource_type in ("image", "media", "font"):
                    route.abort()
                else:
                    route.fallback()
            page.route("**/*", intercept)

            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_timeout(200)
            try:
                page.wait_for_selector(
                    '[aria-label="Search results"], [data-test-id="search-feed"], '
                    '[data-testid="search-results"], [data-test-id="search-pin-grid"], '
                    '[data-testid="search-pin-grid"]',
                    timeout=14_000,
                )
            except Exception:
                pass
            page.wait_for_timeout(120)
            found = collect_image_urls_from_page(
                page,
                mode="search",
                scroll_steps=scroll_steps,
                scroll_pause_ms=pause,
                max_urls=max_urls,
                exclude_canonical_keys=exclude_canonical_keys,
            )
            _enrich_with_pin_urls(page, found)
            found = merge_posts_same_pin(found)
            context.close()
        finally:
            browser.close()
    return found


def fetch_search_image_urls(
    query: str,
    *,
    headless: bool = True,
    timeout_ms: int = 90_000,
) -> list[dict]:
    global _search_api_bookmark
    if not has_session():
        raise PinterestSessionError("Not connected to Pinterest. Sync from browser first.")

    # Reset buffer and bookmark for this new query.
    _search_buf_reset(query)

    try:
        def _search_cold_task(ctx):
            bpage = _apibr_make_home_page(ctx)
            try:
                local_collected: list[dict] = []
                seen_k: set[str] = set()
                bm: str | None = None
                while len(local_collected) < 60:
                    page_posts, bm = _api_search_page(bpage, query, bm, page_size=25)
                    if not page_posts:
                        break
                    page_posts = exclude_posts_seen_on_home(page_posts)
                    for p in page_posts:
                        k = _home_buf_key(p)
                        if k and k not in seen_k:
                            seen_k.add(k)
                            local_collected.append(p)
                return local_collected, bm
            finally:
                _apibr_close_page(bpage)

        posts, bookmark = _apibr_run(_search_cold_task)
        # Seed served set and store bookmark for background fill.
        with _search_buf_lock:
            _search_api_bookmark = bookmark
            if _search_buf_query == query:
                for p in posts:
                    k = _home_buf_key(p)
                    if k:
                        _search_buf_served.add(k)
    except Exception as exc:
        raise PinterestSessionError(f"Search API error: {exc}") from exc

    # Start pre-fetching next pages in background.
    _search_buf_start_fill(query)
    return posts


def fetch_search_more_image_urls(
    query: str,
    seen_keys: set[str] | frozenset,
    *,
    headless: bool = True,
    timeout_ms: int = 90_000,
    batch_size: int = 120,
) -> list[dict]:
    global _search_api_bookmark
    if not has_session():
        raise PinterestSessionError("Not connected to Pinterest. Sync from browser first.")

    # Fast path: pop from the pre-fetched buffer for this query.
    posts = _search_buf_pop(query, batch_size // 2)
    if posts:
        posts = exclude_posts_seen_on_home(posts)
        _search_buf_start_fill(query)
        return posts

    # Cold path: buffer not ready — open browser and call API directly.
    try:
        with _search_buf_lock:
            init_bookmark = _search_api_bookmark if _search_buf_query == query else None
        sk = frozenset(seen_keys)
        target = batch_size // 2

        def _search_more_task(ctx):
            bpage = _apibr_make_home_page(ctx)
            try:
                local_collected: list[dict] = []
                local_keys: set[str] = set()
                bm = init_bookmark
                pages_tried = 0
                while len(local_collected) < target and pages_tried < 8:
                    page_posts, next_bm = _api_search_page(bpage, query, bm, page_size=25)
                    pages_tried += 1
                    bm = next_bm
                    if not page_posts:
                        break
                    page_posts = exclude_posts_seen_on_home(page_posts)
                    for p in page_posts:
                        k = _home_buf_key(p)
                        if k and k not in sk and k not in local_keys:
                            local_collected.append(p)
                            local_keys.add(k)
                return local_collected, bm
            finally:
                _apibr_close_page(bpage)

        posts, bookmark = _apibr_run(_search_more_task)
        with _search_buf_lock:
            if _search_buf_query == query:
                _search_api_bookmark = bookmark
    except Exception as exc:
        raise PinterestSessionError(f"Search API error: {exc}") from exc

    _search_buf_start_fill(query)
    return posts
