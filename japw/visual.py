"""
Visual search: find pins that look like any image (a dropped / pasted file, or an image URL).

The image is sent to the endpoint Pinterest's own browser extension uses for "search this
image". Those ~15 matches come first; after that the feed continues with "more like this"
around the best matches (when logged in), so it scrolls like any other feed.
"""

from __future__ import annotations

import hashlib
import io

import requests

from japw import feeds
from japw.colors import bucket
from japw.pinterest import session
from japw.pinterest.feeds import _related_feed

_ENDPOINT = "https://api.pinterest.com/v3/visual_search/extension/image/"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
MAX_BYTES = 20 * 1024 * 1024
_SEEDS = 6


class VisualSearchError(RuntimeError):
    pass


def prepare_image(data: bytes) -> bytes:
    """Any image format → a JPEG of at most 1024 px (what the endpoint expects, and small to upload)."""
    from PIL import Image

    try:
        im = Image.open(io.BytesIO(data))
        im.seek(0)
        im = im.convert("RGB")
    except Exception as e:
        raise VisualSearchError("That file isn't an image JAPW can read.") from e
    im.thumbnail((1024, 1024))
    out = io.BytesIO()
    im.save(out, "JPEG", quality=90)
    return out.getvalue()


def fetch_image(url: str) -> bytes:
    if not url.lower().startswith("https://"):
        raise VisualSearchError("Only https image links are supported.")
    try:
        r = requests.get(url, headers={"User-Agent": _UA}, timeout=20, stream=True)
        r.raise_for_status()
        if not r.headers.get("Content-Type", "").startswith("image/"):
            raise VisualSearchError("That link isn't an image.")
        data = r.raw.read(MAX_BYTES + 1, decode_content=True)
    except requests.RequestException as e:
        raise VisualSearchError(f"Could not download the image: {e}") from e
    if len(data) > MAX_BYTES:
        raise VisualSearchError("That image is too large.")
    return data


def _to_post(item: dict) -> dict | None:
    url = item.get("image_large_url") or item.get("image_medium_url")
    if not url or "pinimg.com" not in url or item.get("promoter"):
        return None
    post: dict = {"urls": [url.split("?")[0]]}
    size = item.get("image_large_size_pixels") or {}
    if isinstance(size, dict) and size.get("width") and size.get("height"):
        post["width"], post["height"] = int(size["width"]), int(size["height"])
    color = item.get("dominant_color")
    if isinstance(color, str) and len(color) == 7:
        post["color"] = color.lower()
        post["bucket"] = bucket(color)
    pid = str(item.get("id") or "")
    if pid.isdigit():
        post["pin_url"] = f"https://www.pinterest.com/pin/{pid}/"
    title = (item.get("description") or "").strip()
    if title:
        post["title"] = title[:200]
    return post


def _matches(jpeg: bytes) -> list[dict]:
    try:
        r = requests.put(
            _ENDPOINT,
            files={"image": ("image.jpg", jpeg, "image/jpeg")},
            data={"x": "0", "y": "0", "w": "1", "h": "1", "base_scheme": "https"},
            headers={"User-Agent": _UA},
            timeout=(6, 30),
        )
    except requests.RequestException as e:
        raise VisualSearchError(f"Could not reach Pinterest: {e}") from e
    if r.status_code != 200:
        raise VisualSearchError(f"Pinterest visual search failed (HTTP {r.status_code}).")
    data = (r.json() or {}).get("data")
    return [p for p in (_to_post(i) for i in (data if isinstance(data, list) else [])) if p]


def start(data: bytes) -> str:
    """Run a visual search; returns an id for paging through the results with page()."""
    jpeg = prepare_image(data)
    search_id = hashlib.sha1(jpeg).hexdigest()[:16]
    key = ("visual", search_id)
    if feeds.cache.peek(key):
        return search_id
    matches = _matches(jpeg)
    if not matches:
        raise VisualSearchError("Pinterest found nothing similar to that image.")

    seeds = [p["pin_url"].rstrip("/").rsplit("/", 1)[-1] for p in matches if p.get("pin_url")][:_SEEDS]
    related = [_related_feed(pid) for pid in seeds] if session.has_session() else []
    more = feeds.merged_pages(related, per_source=8) if related else None

    def fetch(bookmark):
        if bookmark is None:
            return matches, "related" if more else None
        return more(bookmark)

    feeds.cache.get(key, lambda: feeds.Feed(fetch, f"visual:{search_id}", merged=True), ttl=30 * 60)
    return search_id


def page(search_id: str, offset: int, limit: int) -> tuple[list[dict], bool]:
    feed = feeds.cache.peek(("visual", search_id))
    if feed is None:
        raise VisualSearchError("This image search expired — run it again.")
    return feed.get(offset, limit)
