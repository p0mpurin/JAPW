"""The local library: likes, collections, downloads, and backup / restore."""

import datetime
import json
import os
import subprocess
import sys
import webbrowser

from flask import Blueprint, Response, jsonify

import japw.x as xs
from japw import library as lib
from japw.config import (
    load_collections, load_config, load_downloads, load_likes,
    save_collections, save_config, save_likes,
)
from japw.routes.common import body, cfg_path, error

bp = Blueprint("library", __name__)


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _fail(e: lib.LibraryError):
    return error(str(e), e.status)


# ─── Likes ───

@bp.get("/api/likes")
def get_likes():
    return jsonify({"posts": lib.list_likes(cfg_path())})


@bp.post("/api/likes/toggle")
def toggle_like():
    data = body()
    try:
        liked, key = lib.set_like(data.get("urls") or [], None, data.get("color"), data.get("pin_url"), cfg_path())
    except lib.LibraryError as e:
        return _fail(e)
    return jsonify({"liked": liked, "key": key})


# ─── Collections ───

@bp.get("/api/collections")
def get_collections():
    return jsonify({"collections": lib.list_collections(cfg_path())})


@bp.post("/api/collections")
def create_collection():
    try:
        return jsonify({"collection": lib.create_collection(body().get("name") or "", cfg_path())})
    except lib.LibraryError as e:
        return _fail(e)


@bp.patch("/api/collections/<col_id>")
def rename_collection(col_id):
    try:
        lib.rename_collection(col_id, body().get("name") or "", cfg_path())
    except lib.LibraryError as e:
        return _fail(e)
    return jsonify({"success": True})


@bp.delete("/api/collections/<col_id>")
def delete_collection(col_id):
    try:
        lib.delete_collection(col_id, cfg_path())
    except lib.LibraryError as e:
        return _fail(e)
    return jsonify({"success": True})


@bp.get("/api/collections/<col_id>/posts")
def get_collection_posts(col_id):
    try:
        name, posts = lib.collection_posts(col_id, cfg_path())
    except lib.LibraryError as e:
        return _fail(e)
    return jsonify({"posts": posts, "name": name})


@bp.post("/api/collections/<col_id>/posts")
def add_to_collection(col_id):
    data = body()
    try:
        lib.add_to_collection(col_id, data.get("urls") or [], data.get("color"), data.get("pin_url"), cfg_path())
    except lib.LibraryError as e:
        return _fail(e)
    return jsonify({"success": True})


@bp.delete("/api/collections/<col_id>/posts")
def remove_from_collection(col_id):
    try:
        lib.remove_from_collection(col_id, (body().get("key") or "").strip(), cfg_path())
    except lib.LibraryError as e:
        return _fail(e)
    return jsonify({"success": True})


# ─── Downloads ───

@bp.post("/api/download")
def download():
    data = body()
    try:
        path = lib.download(data.get("url") or "", data.get("key"), cfg_path(),
                            subfolder=data.get("subfolder") or None, name=data.get("name") or None)
    except lib.LibraryError as e:
        return _fail(e)
    key = (data.get("key") or "").strip() or lib.canonical_key(data["url"].strip())
    return jsonify({"success": True, "path": path, "key": key})


@bp.get("/api/downloads")
def downloaded_keys():
    return jsonify({"keys": list(lib.downloaded(cfg_path()).keys())})


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
