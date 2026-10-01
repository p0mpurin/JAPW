"""
Direct client for Pinterest's internal resource API (/resource/<Name>/get/) — the same
JSON endpoints the web app calls. Uses the synced cookies over plain HTTPS, so no
browser is needed and a page of pins arrives in roughly one round trip.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from urllib.parse import urlencode

import requests
from requests.adapters import HTTPAdapter

from japw.pinterest import session
from japw.pinterest.errors import PinterestAuthExpired, PinterestSessionError

BASE = "https://www.pinterest.com"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_TIMEOUT = (6, 25)
# Pinterest rotates session cookies; write them back at most this often so the session lasts.
_PERSIST_EVERY_S = 30


class PinterestClient:
    def __init__(self, cookies: list[dict]) -> None:
        self._http = requests.Session()
        adapter = HTTPAdapter(pool_connections=4, pool_maxsize=16, max_retries=1)
        self._http.mount("https://", adapter)
        self._http.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "en-US,en;q=0.9",
            "X-Requested-With": "XMLHttpRequest",
            "X-Pinterest-AppState": "active",
            "X-Pinterest-PWS-Handler": "www/index.js",
            "Referer": f"{BASE}/",
        })
        for c in cookies:
            if c.get("name") and c.get("value") is not None:
                self._http.cookies.set(c["name"], c["value"], domain=c.get("domain") or ".pinterest.com",
                                       path=c.get("path") or "/")
        self._snapshot = self._cookie_values()
        self._last_persist = time.monotonic()
        self._persist_lock = threading.Lock()

    def _cookie_values(self) -> dict[str, str]:
        return {c.name: c.value for c in self._http.cookies}

    def _csrf(self) -> str:
        for c in self._http.cookies:
            if c.name == "csrftoken":
                return c.value
        return ""

    def warm(self) -> None:
        """Open the TLS connection early so the first real request skips the handshake."""
        try:
            self._http.head(f"{BASE}/robots.txt", timeout=_TIMEOUT)
        except requests.RequestException:
            pass

    def resource(self, name: str, options: dict, source_url: str = "/") -> dict:
        """GET a resource and return its resource_response. Raises on auth / API errors."""
        params = urlencode({
            "source_url": source_url,
            "data": json.dumps({"options": options, "context": {}}, separators=(",", ":")),
            "_": int(time.time() * 1000),
        })
        try:
            r = self._http.get(
                f"{BASE}/resource/{name}/get/?{params}",
                headers={"X-CSRFToken": self._csrf(), "X-Pinterest-Source-Url": source_url},
                timeout=_TIMEOUT,
            )
        except requests.RequestException as e:
            raise PinterestSessionError(f"Could not reach Pinterest: {e}") from e

        if r.status_code in (401, 403):
            raise PinterestAuthExpired()
        try:
            body = r.json()
        except ValueError:
            raise PinterestSessionError(f"Pinterest returned an unexpected response (HTTP {r.status_code}).")
        rr = body.get("resource_response") or {}
        err = rr.get("error")
        if err or r.status_code >= 400:
            code = (err or {}).get("http_status") or r.status_code
            if code in (401, 403):
                raise PinterestAuthExpired()
            msg = (err or {}).get("message") or f"HTTP {r.status_code}"
            raise PinterestSessionError(f"Pinterest {name} failed: {msg}")
        self._maybe_persist_cookies()
        return rr

    def _maybe_persist_cookies(self) -> None:
        now = time.monotonic()
        if now - self._last_persist < _PERSIST_EVERY_S:
            return
        with self._persist_lock:
            self._last_persist = now
            current = self._cookie_values()
            if current == self._snapshot:
                return
            self._snapshot = current
            stored = {(c["name"], c.get("domain"), c.get("path")): c for c in session.load_cookies()}
            for c in self._http.cookies:
                key = (c.name, c.domain, c.path)
                entry = stored.get(key) or {"name": c.name, "domain": c.domain, "path": c.path,
                                            "httpOnly": False, "secure": bool(c.secure), "sameSite": "Lax"}
                entry["value"] = c.value
                entry["expires"] = int(c.expires) if c.expires else -1
                stored[key] = entry
            try:
                session.save_cookies(list(stored.values()))
            except OSError as e:
                print(f"[JAPW] could not persist refreshed cookies: {e}", file=sys.stderr)


_client: PinterestClient | None = None
_client_lock = threading.Lock()


def get_client() -> PinterestClient:
    """The shared client for the current session; raises if not connected."""
    global _client
    with _client_lock:
        if _client is None:
            if not session.has_session():
                raise PinterestSessionError("Not connected to Pinterest. Sync from browser first.")
            _client = PinterestClient(session.load_cookies())
        return _client


def reset_client() -> None:
    global _client
    with _client_lock:
        _client = None


session.on_session_changed(reset_client)
