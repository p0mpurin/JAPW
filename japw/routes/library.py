"""The local library: likes, collections, downloads, and backup / restore."""

import datetime
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from urllib.parse import urlsplit

import requests
from flask import Blueprint, Response, jsonify

import japw.x as xs
from japw.config import (
    load_collections, load_config, load_downloads, load_likes,
    save_collections, save_config, save_downloads, save_likes,
)
from japw.media import is_allowed_image_url
from japw.pinterest import canonical_key
from japw.routes.common import body, cfg_path, error

bp = Blueprint("library", __name__)

_downloads_lock = threading.Lock()
_library_lock = threading.Lock()


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _entry(urls: list, color=None, **extra) -> dict:
    e = {"key": canonical_key(urls[0]), "urls": [str(u) for u in urls], **extra}
    if isinstance(color, str) and color.startswith("#") and len(color) == 7:
        e["color"] = color.lower()
    return e


# ─── Likes ───

@bp.get("/api/likes")
def get_likes():
    return jsonify({"posts": load_likes(cfg_path()).get("posts", [])})


@bp.post("/api/likes/toggle")
def toggle_like():
    data = body()
    urls = data.get("urls") or []
    if not urls:
        return error("Missing urls")
    key = canonical_key(urls[0])
    with _library_lock:
        likes = load_likes(cfg_path())
        posts = likes.get("posts", [])
        before = len(posts)
        posts = [p for p in posts if p.get("key") != key]
        liked = len(posts) == before
        if liked:
            posts.insert(0, _entry(urls, data.get("color"), liked_at=_now()))
        likes["posts"] = posts
        save_likes(cfg_path(), likes)
    return jsonify({"liked": liked, "key": key})


# ─── Collections ───

def _find_collection(data: dict, col_id: str) -> dict | None:
    return next((c for c in data.get("collections", []) if c.get("id") == col_id), None)


@bp.get("/api/collections")
def get_collections():
    cols = load_collections(cfg_path()).get("collections", [])
    return jsonify({"collections": [{
        "id": c["id"],
        "name": c["name"],
        "count": len(c.get("posts", [])),
        "cover": c["posts"][0]["urls"][0] if c.get("posts") else None,
    } for c in cols]})


@bp.post("/api/collections")
def create_collection():
    name = (body().get("name") or "").strip()
    if not name:
        return error("Missing name")
    col = {"id": str(int(time.time() * 1000)), "name": name[:100], "created_at": _now(), "posts": []}
    with _library_lock:
        data = load_collections(cfg_path())
        data.setdefault("collections", []).append(col)
        save_collections(cfg_path(), data)
    return jsonify({"collection": {"id": col["id"], "name": col["name"], "count": 0, "cover": None}})


@bp.patch("/api/collections/<col_id>")
def rename_collection(col_id):
    name = (body().get("name") or "").strip()
    if not name:
        return error("Missing name")
    with _library_lock:
        data = load_collections(cfg_path())
        col = _find_collection(data, col_id)
        if not col:
            return error("Not found", 404)
        col["name"] = name[:100]
        save_collections(cfg_path(), data)
    return jsonify({"success": True})


@bp.delete("/api/collections/<col_id>")
def delete_collection(col_id):
    with _library_lock:
        data = load_collections(cfg_path())
        cols = data.get("collections", [])
        data["collections"] = [c for c in cols if c.get("id") != col_id]
        if len(data["collections"]) == len(cols):
            return error("Not found", 404)
        save_collections(cfg_path(), data)
    return jsonify({"success": True})


@bp.get("/api/collections/<col_id>/posts")
def get_collection_posts(col_id):
    col = _find_collection(load_collections(cfg_path()), col_id)
    if not col:
        return error("Not found", 404)
    return jsonify({"posts": col.get("posts", []), "name": col["name"]})


@bp.post("/api/collections/<col_id>/posts")
def add_to_collection(col_id):
    data = body()
    urls = data.get("urls") or []
    if not urls:
        return error("Missing urls")
    with _library_lock:
        cols = load_collections(cfg_path())
        col = _find_collection(cols, col_id)
        if not col:
            return error("Not found", 404)
        posts = col.setdefault("posts", [])
        key = canonical_key(urls[0])
        if not any(p.get("key") == key for p in posts):
            posts.insert(0, _entry(urls, data.get("color"), added_at=_now()))
            save_collections(cfg_path(), cols)
    return jsonify({"success": True})


@bp.delete("/api/collections/<col_id>/posts")
def remove_from_collection(col_id):
    key = (body().get("key") or "").strip()
    if not key:
        return error("Missing key")
    with _library_lock:
        cols = load_collections(cfg_path())
        col = _find_collection(cols, col_id)
        if not col:
            return error("Not found", 404)
        col["posts"] = [p for p in col.get("posts", []) if p.get("key") != key]
        save_collections(cfg_path(), cols)
    return jsonify({"success": True})


# ─── Downloads ───

_EXT_BY_TYPE = (("png", ".png"), ("gif", ".gif"), ("webp", ".webp"), ("mp4", ".mp4"), ("video", ".mp4"))


@bp.post("/api/download")
def download():
    data = body()
    url = (data.get("url") or "").strip()
    if not url:
        return error("Missing image URL")
    if not is_allowed_image_url(url):
        return error("Unsupported image host")

    folder = load_config(cfg_path())["download_folder"]
    os.makedirs(folder, exist_ok=True)
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as e:
        return error(str(e), 500)

    content_type = resp.headers.get("Content-Type", "")
    ext = next((e for marker, e in _EXT_BY_TYPE if marker in content_type), ".jpg")
    try:
        stem = Path(urlsplit(url).path).stem
        base_name = f"pin_{datetime.datetime.now():%Y%m%d}_{stem[:14]}"
    except Exception:
        base_name = "pin_" + hashlib.md5(url.encode()).hexdigest()[:12]

    key = (data.get("key") or "").strip() or canonical_key(url)
    with _downloads_lock:
        filepath = os.path.join(folder, base_name + ext)
        n = 2
        while os.path.exists(filepath):
            filepath = os.path.join(folder, f"{base_name}_{n}{ext}")
            n += 1
        with open(filepath, "wb") as f:
            f.write(resp.content)
        index = load_downloads(cfg_path())
        index["items"][key] = filepath
        save_downloads(cfg_path(), index)
    return jsonify({"success": True, "path": filepath, "key": key})


@bp.get("/api/downloads")
def downloaded_keys():
    return jsonify({"keys": list(load_downloads(cfg_path())["items"].keys())})


def _open_folder(path: str, select: bool = False) -> None:
    if sys.platform == "win32":
        if select:
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        else:
            os.startfile(path)
    else:
        webbrowser.open("file://" + (os.path.dirname(path) if select else path))


@bp.post("/api/reveal")
def reveal_download():
    """Show a downloaded file in Explorer, or open the download folder."""
    path = (body().get("path") or "").strip()
    known = set(load_downloads(cfg_path())["items"].values())
    if path and path in known and os.path.isfile(path):
        _open_folder(path, select=True)
        return jsonify({"opened": True})
    folder = load_config(cfg_path())["download_folder"]
    if not os.path.isdir(folder):
        return error("Download folder does not exist yet", 404)
    _open_folder(folder)
    return jsonify({"opened": True})


# ─── Backup / restore ───

@bp.get("/api/export")
def export_data():
    bundle = {
        "version": 1,
        "exported_at": _now(),
        "settings": load_config(cfg_path()),
        "likes": load_likes(cfg_path()),
        "collections": load_collections(cfg_path()),
        "x_artists": xs.load_artists(),
    }
    return Response(
        json.dumps(bundle, indent=2, ensure_ascii=False),
        mimetype="application/json",
        headers={"Content-Disposition": 'attachment; filename="japw_backup.json"'},
    )


@bp.post("/api/import")
def import_data():
    data = body()
    if not data:
        return error("Invalid backup file")
    if data.get("version") != 1:
        return error("Unsupported backup version")
    errors = []
    steps = (
        ("settings", dict, lambda v: save_config(cfg_path(), {**load_config(cfg_path()), **v})),
        ("likes", dict, lambda v: save_likes(cfg_path(), v)),
        ("collections", dict, lambda v: save_collections(cfg_path(), v)),
        ("x_artists", list, xs.save_artists),
    )
    for name, kind, save in steps:
        if isinstance(data.get(name), kind):
            try:
                save(data[name])
            except Exception as e:
                errors.append(f"{name}: {e}")
    if errors:
        return jsonify({"success": False, "errors": errors}), 207
    return jsonify({"success": True})
