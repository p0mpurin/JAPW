"""
The local library — likes, collections and downloads — as plain functions shared by the
Flask routes (the app UI) and the MCP server (AI assistants).
"""

from __future__ import annotations

import datetime
import hashlib
import os
import re
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

import requests

from japw.config import (
    load_collections, load_config, load_downloads, load_likes,
    save_collections, save_downloads, save_likes,
)
from japw.images import canonical_key
from japw.media import is_allowed_image_url

_library_lock = threading.Lock()
_downloads_lock = threading.Lock()
_EXT_BY_TYPE = (("png", ".png"), ("gif", ".gif"), ("webp", ".webp"), ("mp4", ".mp4"), ("video", ".mp4"))


class LibraryError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _entry(urls: list, color=None, pin_url=None, **extra) -> dict:
    e = {"key": canonical_key(urls[0]), "urls": [str(u) for u in urls], **extra}
    if isinstance(color, str) and color.startswith("#") and len(color) == 7:
        e["color"] = color.lower()
    if isinstance(pin_url, str) and pin_url.startswith("https://"):
        e["pin_url"] = pin_url
    return e


# ─── Likes ───

def list_likes(cfg: str | None = None) -> list[dict]:
    return load_likes(cfg).get("posts", [])


def is_liked(urls: list, cfg: str | None = None) -> bool:
    key = canonical_key(urls[0])
    return any(p.get("key") == key for p in list_likes(cfg))


def set_like(urls: list, liked: bool | None = None, color=None, pin_url=None, cfg: str | None = None) -> tuple[bool, str]:
    """Like / unlike (liked=None toggles). Returns (liked_now, key)."""
    if not urls:
        raise LibraryError("Missing urls")
    key = canonical_key(urls[0])
    with _library_lock:
        likes = load_likes(cfg)
        posts = likes.get("posts", [])
        present = any(p.get("key") == key for p in posts)
        want = (not present) if liked is None else liked
        posts = [p for p in posts if p.get("key") != key]
        if want:
            posts.insert(0, _entry(urls, color, pin_url, liked_at=_now()))
        likes["posts"] = posts
        save_likes(cfg, likes)
    return want, key


# ─── Collections ───

def _find(data: dict, col_id: str) -> dict | None:
    return next((c for c in data.get("collections", []) if c.get("id") == col_id), None)


def find_collection(name_or_id: str, cfg: str | None = None) -> dict | None:
    """Look a collection up by id, or by name (case-insensitive)."""
    cols = load_collections(cfg).get("collections", [])
    needle = (name_or_id or "").strip().lower()
    return next((c for c in cols if c.get("id") == name_or_id), None) or \
        next((c for c in cols if c.get("name", "").strip().lower() == needle), None)


def list_collections(cfg: str | None = None) -> list[dict]:
    return [{
        "id": c["id"],
        "name": c["name"],
        "count": len(c.get("posts", [])),
        "cover": c["posts"][0]["urls"][0] if c.get("posts") else None,
    } for c in load_collections(cfg).get("collections", [])]


def create_collection(name: str, cfg: str | None = None) -> dict:
    name = (name or "").strip()
    if not name:
        raise LibraryError("Missing name")
    col = {"id": str(int(time.time() * 1000)), "name": name[:100], "created_at": _now(), "posts": []}
    with _library_lock:
        data = load_collections(cfg)
        # ids are millisecond timestamps; avoid a clash when two are created in the same ms
        while _find(data, col["id"]):
            col["id"] = str(int(col["id"]) + 1)
        data.setdefault("collections", []).append(col)
        save_collections(cfg, data)
    return {"id": col["id"], "name": col["name"], "count": 0, "cover": None}


def rename_collection(col_id: str, name: str, cfg: str | None = None) -> None:
    name = (name or "").strip()
    if not name:
        raise LibraryError("Missing name")
    with _library_lock:
        data = load_collections(cfg)
        col = _find(data, col_id)
        if not col:
            raise LibraryError("Collection not found", 404)
        col["name"] = name[:100]
        save_collections(cfg, data)


def delete_collection(col_id: str, cfg: str | None = None) -> None:
    with _library_lock:
        data = load_collections(cfg)
        cols = data.get("collections", [])
        data["collections"] = [c for c in cols if c.get("id") != col_id]
        if len(data["collections"]) == len(cols):
            raise LibraryError("Collection not found", 404)
        save_collections(cfg, data)


def collection_posts(col_id: str, cfg: str | None = None) -> tuple[str, list[dict]]:
    col = _find(load_collections(cfg), col_id)
    if not col:
        raise LibraryError("Collection not found", 404)
    return col["name"], col.get("posts", [])


def add_to_collection(col_id: str, urls: list, color=None, pin_url=None, cfg: str | None = None) -> bool:
    """Returns False when the pin was already in the collection."""
    if not urls:
        raise LibraryError("Missing urls")
    with _library_lock:
        data = load_collections(cfg)
        col = _find(data, col_id)
        if not col:
            raise LibraryError("Collection not found", 404)
        posts = col.setdefault("posts", [])
        key = canonical_key(urls[0])
        if any(p.get("key") == key for p in posts):
            return False
        posts.insert(0, _entry(urls, color, pin_url, added_at=_now()))
        save_collections(cfg, data)
    return True


def remove_from_collection(col_id: str, key: str, cfg: str | None = None) -> bool:
    if not key:
        raise LibraryError("Missing key")
    with _library_lock:
        data = load_collections(cfg)
        col = _find(data, col_id)
        if not col:
            raise LibraryError("Collection not found", 404)
        before = len(col.get("posts", []))
        col["posts"] = [p for p in col.get("posts", []) if p.get("key") != key]
        save_collections(cfg, data)
        return len(col["posts"]) < before


# ─── Downloads ───

def download_folder(cfg: str | None = None) -> str:
    return load_config(cfg)["download_folder"]


def _safe_part(text: str, limit: int = 60) -> str:
    """A string usable as a file or folder name on Windows."""
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', " ", text or "").strip(" .")
    return re.sub(r"\s+", " ", text)[:limit].strip(" .")


def download(url: str, key: str | None = None, cfg: str | None = None,
             subfolder: str | None = None, name: str | None = None) -> str:
    """Save an image (or GIF video) to the download folder; returns the file path. Never overwrites."""
    url = (url or "").strip()
    if not url:
        raise LibraryError("Missing image URL")
    if not is_allowed_image_url(url):
        raise LibraryError("Unsupported image host")

    folder = download_folder(cfg)
    if subfolder:
        part = _safe_part(subfolder)
        if part:
            folder = os.path.join(folder, part)
    os.makedirs(folder, exist_ok=True)
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise LibraryError(str(e), 502) from e

    content_type = resp.headers.get("Content-Type", "")
    ext = next((e for marker, e in _EXT_BY_TYPE if marker in content_type), ".jpg")
    base_name = _safe_part(name or "")
    if not base_name:
        try:
            stem = Path(urlsplit(url).path).stem
            base_name = f"pin_{datetime.datetime.now():%Y%m%d}_{stem[:14]}"
        except Exception:
            base_name = "pin_" + hashlib.md5(url.encode()).hexdigest()[:12]

    key = (key or "").strip() or canonical_key(url)
    with _downloads_lock:
        filepath = os.path.join(folder, base_name + ext)
        n = 2
        while os.path.exists(filepath):
            filepath = os.path.join(folder, f"{base_name}_{n}{ext}")
            n += 1
        with open(filepath, "wb") as f:
            f.write(resp.content)
        index = load_downloads(cfg)
        index["items"][key] = filepath
        save_downloads(cfg, index)
    return filepath


def downloaded(cfg: str | None = None) -> dict[str, str]:
    """canonical key → saved file path."""
    return dict(load_downloads(cfg)["items"])
