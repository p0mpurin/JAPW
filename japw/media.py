"""Image helpers: host allow-list, PNG conversion (for clipboard copy), and dominant colours."""

from __future__ import annotations

import colorsys
import concurrent.futures
import io
import json
import re
import threading
from urllib.parse import urlsplit

import requests

from japw.config import get_app_data_dir

ALLOWED_HOSTS = ("i.pinimg.com", "v.pinimg.com", "pbs.twimg.com", "video.twimg.com")

_http = requests.Session()
_http.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) JAPW"


def is_allowed_image_url(url: str) -> bool:
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return parts.scheme == "https" and parts.hostname in ALLOWED_HOSTS


def small_variant(url: str) -> str:
    """A small rendition of the same image — enough to measure its colour."""
    if "i.pinimg.com" in url:
        return re.sub(r"i\.pinimg\.com/(?:originals|\d+x(?:\d+)?)/", "i.pinimg.com/236x/", url, flags=re.I)
    if "pbs.twimg.com" in url:
        base = url.split("?")[0]
        return f"{base}?name=small" if "format=" not in url else re.sub(r"name=\w+", "name=small", url)
    return url


def fetch_png(url: str, max_side: int = 4096) -> bytes:
    """Download an image and re-encode it as PNG (the only image type browsers can put on the clipboard)."""
    from PIL import Image

    r = _http.get(url, timeout=20)
    r.raise_for_status()
    im = Image.open(io.BytesIO(r.content))
    im.seek(0)
    im = im.convert("RGBA")
    if max(im.size) > max_side:
        im.thumbnail((max_side, max_side))
    out = io.BytesIO()
    im.save(out, "PNG", optimize=False)
    return out.getvalue()


# ─── Dominant colours ───

_colors: dict[str, str] | None = None
_colors_lock = threading.Lock()
_pool = concurrent.futures.ThreadPoolExecutor(max_workers=8, thread_name_prefix="JAPW-color")


def _cache_path():
    return get_app_data_dir() / "colors.json"


def _load_cache() -> dict[str, str]:
    global _colors
    if _colors is None:
        try:
            with open(_cache_path(), encoding="utf-8") as f:
                _colors = dict(json.load(f))
        except (OSError, ValueError):
            _colors = {}
    return _colors


def _save_cache() -> None:
    try:
        with open(_cache_path(), "w", encoding="utf-8") as f:
            json.dump(_colors, f)
    except OSError:
        pass


def _measure(url: str) -> str | None:
    """Most saturated common colour of a 24×24 thumbnail, as #rrggbb."""
    from PIL import Image

    try:
        r = _http.get(small_variant(url), timeout=12)
        r.raise_for_status()
        im = Image.open(io.BytesIO(r.content)).convert("RGB").resize((24, 24))
    except Exception:
        return None
    # Quantise, then prefer frequent colours with some saturation over flat grey backgrounds.
    q = im.quantize(colors=6, method=Image.Quantize.MEDIANCUT)
    palette = q.getpalette() or []
    best, best_score = None, -1.0
    for count, idx in q.getcolors() or []:
        rgb = palette[idx * 3: idx * 3 + 3]
        if len(rgb) < 3:
            continue
        h, l, s = colorsys.rgb_to_hls(*(c / 255 for c in rgb))
        score = count * (0.35 + s) * (1 - abs(l - 0.5))
        if score > best_score:
            best, best_score = rgb, score
    return "#%02x%02x%02x" % tuple(best) if best else None


def dominant_colors(items: list[tuple[str, str]]) -> dict[str, str]:
    """items = [(key, url)] → {key: "#rrggbb"}, cached on disk by key."""
    with _colors_lock:
        cache = _load_cache()
        known = {k: cache[k] for k, _ in items if k in cache}
    todo = [(k, u) for k, u in items if k not in known and is_allowed_image_url(u)]
    if todo:
        results = list(_pool.map(lambda ku: (ku[0], _measure(ku[1])), todo[:200]))
        with _colors_lock:
            for k, c in results:
                if c:
                    cache[k] = c
                    known[k] = c
            _save_cache()
    return known
