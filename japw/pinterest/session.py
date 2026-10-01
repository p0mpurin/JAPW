"""
Pinterest login: import cookies from the user's installed browsers (Chrome, Edge, Firefox,
Zen, …) and keep them in a storage file. JAPW never sees the password.

The file uses Playwright's storage_state format ({"cookies": [...], "origins": []}) so
sessions synced by older versions keep working.
"""

from __future__ import annotations

import json
import os
import threading
from http.cookiejar import Cookie
from pathlib import Path
from typing import Callable

from japw.config import get_app_data_dir
from japw.pinterest.errors import PinterestSessionError

_auth_lock = threading.Lock()
_auth_sync_in_progress = False
_last_login_error: str | None = None
_listeners: list[Callable[[], None]] = []


def on_session_changed(fn: Callable[[], None]) -> None:
    """Register a callback that runs after a sync or logout (to drop cached clients / feeds)."""
    _listeners.append(fn)


def _notify() -> None:
    for fn in _listeners:
        try:
            fn()
        except Exception:
            pass


def get_storage_path() -> Path:
    return get_app_data_dir() / "pinterest_state.json"


def has_session() -> bool:
    p = get_storage_path()
    return p.is_file() and p.stat().st_size > 0


def load_cookies() -> list[dict]:
    try:
        with open(get_storage_path(), encoding="utf-8") as f:
            return list(json.load(f).get("cookies") or [])
    except (OSError, ValueError):
        return []


def save_cookies(cookies: list[dict]) -> None:
    path = get_storage_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"cookies": cookies, "origins": []}, f)
    os.replace(tmp, path)


def clear_session() -> None:
    p = get_storage_path()
    if p.exists():
        p.unlink()
    _set_last_login_error(None)
    _notify()


def _set_last_login_error(msg: str | None) -> None:
    global _last_login_error
    _last_login_error = msg


def get_last_login_error() -> str | None:
    return _last_login_error


def is_login_in_progress() -> bool:
    return _auth_sync_in_progress


def try_begin_sync() -> bool:
    """True if this caller should start the sync worker; False if one is already running."""
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
        _notify()
    except Exception as e:
        _set_last_login_error(str(e))
    finally:
        finish_sync()


# ─── Reading cookies from installed browsers ─────────────────────────────────

def _is_pinterest_domain(domain: str) -> bool:
    d = (domain or "").lstrip(".").lower()
    return d == "pinterest.com" or d.endswith(".pinterest.com")


def _firefox_fork_profile_roots() -> list[Path]:
    """Zen, Floorp, Waterfox keep profiles outside Mozilla/Firefox, which browser_cookie3 misses."""
    appdata = Path(os.environ.get("APPDATA", ""))
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    roots: list[Path] = []
    for vendor in ("zen", "Zen", "zen-browser", "Zen Browser", "floorp", "Floorp", "Waterfox"):
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
                cf = sub / "cookies.sqlite"
                if sub.is_dir() and cf.is_file():
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
    loader_names = ("chrome", "chromium", "edge", "brave", "opera", "opera_gx", "vivaldi",
                    "firefox", "safari", "librewolf")

    def add_from(iterator, domain_filter=_is_pinterest_domain) -> None:
        try:
            for c in iterator:
                dom = getattr(c, "domain", "") or ""
                if domain_filter(dom):
                    by_key[(c.name, dom, getattr(c, "path", None) or "/")] = c
        except Exception:
            pass

    for name in loader_names:
        loader = getattr(bc3, name, None)
        if callable(loader):
            try:
                add_from(loader(domain_name="pinterest.com"))
            except Exception:
                pass

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
            if callable(loader):
                try:
                    add_from(loader(), lambda d: "pinterest" in d.lower())
                except Exception:
                    pass
    return list(by_key.values())


def _cookie_expires(raw) -> int:
    """-1 (session) or whole Unix seconds; Firefox-family DBs may store ms or µs."""
    try:
        exp = float(raw)
    except (TypeError, ValueError):
        return -1
    if exp != exp or exp <= 0:
        return -1
    if exp > 4_102_441_920:
        exp = exp / 1_000_000.0 if exp > 1e14 else exp / 1000.0 if exp > 1e11 else exp
    return int(exp) if int(exp) > 0 else -1


def _cookie_to_entry(c: Cookie) -> dict:
    rest = getattr(c, "_rest", None)
    return {
        "name": c.name,
        "value": c.value,
        "domain": c.domain or ".pinterest.com",
        "path": c.path or "/",
        "expires": _cookie_expires(getattr(c, "expires", None)),
        "httpOnly": bool(isinstance(rest, dict) and rest.get("HttpOnly")),
        "secure": bool(c.secure),
        "sameSite": "Lax",
    }


def sync_session_from_installed_browsers() -> None:
    cookies = _gather_pinterest_cookies()
    if not cookies:
        raise PinterestSessionError(
            "No Pinterest cookies found. Log in at pinterest.com (e.g. in Zen, Firefox, "
            "Chrome, or Edge), then use Sync from browser again. If sync still fails, "
            "close the browser completely so cookies.sqlite is not locked, then retry."
        )
    by_key: dict[tuple[str, str, str], dict] = {}
    for c in cookies:
        if _is_pinterest_domain(getattr(c, "domain", "") or ""):
            e = _cookie_to_entry(c)
            by_key[(e["name"], e["domain"], e["path"])] = e
    if not by_key:
        raise PinterestSessionError(
            "Found no usable Pinterest cookies. Log in on pinterest.com in a supported browser, then sync again."
        )
    save_cookies(list(by_key.values()))
