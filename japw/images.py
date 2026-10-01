"""Image URL helpers (mostly the Pinterest CDN): normalisation, canonical keys, de-duplication."""

from __future__ import annotations

import re

_SIZE_BUCKET_RE = re.compile(r"pinimg\.com/(\d+)x(?:\d+)?/", re.I)


def normalize_pin_url(url: str) -> str | None:
    """Return a clean pinimg URL, or None for avatars / UI thumbnails / non-pinimg links."""
    url = (url or "").split("?")[0].strip()
    u_lower = url.lower()
    if "i.pinimg.com" not in u_lower:
        return None
    if any(skip in u_lower for skip in ("/75x75", "/150x150", "/140x140", "/200x200", "/avatars/", "/profile/")):
        return None
    return url if re.match(r"https://i\.pinimg\.com/[\w/.-]+", url, re.I) else None


def canonical_key(url: str) -> str:
    """
    The same image is served as 236x, 474x, 736x, originals, sometimes as .jpg and .gif.
    The path after the size bucket (minus extension) identifies one logical image.
    Must match canonicalKey() in frontend/js/core/pins.js.
    """
    u = (url or "").split("?")[0].strip().lower()
    m = re.match(r"https?://i\.pinimg\.com/[^/]+/(.+)", u)
    path = m.group(1) if m else u
    return path.rsplit(".", 1)[0] if "." in path else path


def quality_score(url: str) -> int:
    """Prefer animated, then original, then larger CDN buckets."""
    u = url.lower()
    score = 500_000 if u.endswith(".gif") else 0
    if "/originals/" in u:
        return score + 100_000
    m = _SIZE_BUCKET_RE.search(u)
    return score + (int(m.group(1)) if m else 0)


def dedupe_pinimg_urls(urls: list[str]) -> list[str]:
    """One URL per logical image, keeping the highest-quality variant, in first-seen order."""
    order: list[str] = []
    best: dict[str, str] = {}
    for raw in urls:
        u = (raw or "").strip()
        if not u:
            continue
        key = canonical_key(u)
        if key not in best:
            best[key] = u
            order.append(key)
        elif quality_score(u) > quality_score(best[key]):
            best[key] = u
    return [best[k] for k in order]
