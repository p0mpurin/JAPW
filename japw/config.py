import json
import os
import sys
from pathlib import Path


def get_app_data_dir() -> Path:
    """Return persistent config directory. Uses APPDATA on Windows."""
    if getattr(sys, "frozen", False):
        base = Path(os.environ.get("APPDATA", Path.home())) / "JAPW"
    else:
        base = Path(".")
    base.mkdir(parents=True, exist_ok=True)
    return base


def get_default_config() -> dict:
    return {
        "download_folder": str(Path.home() / "Pictures" / "JAPW"),
        "resolution_filter_enabled": False,
        "resolution_target_width": 1920,
        "resolution_target_height": 1080,
        "resolution_match_mode": "min",
        "pinterest_boards_page_url": "",
        "search_use_pinscrape_when_logged_in": False,
        "filter_promoted": True,
        "filter_ai_content": False,
    }


def _resolve_config_path(config_path: str | None = None) -> Path:
    if config_path:
        return Path(config_path)
    return get_app_data_dir() / "config.json"


def load_config(config_path: str | None = None) -> dict:
    path = _resolve_config_path(config_path)
    defaults = get_default_config()
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return {**defaults, **data}
        except (json.JSONDecodeError, IOError, OSError):
            pass
    config = dict(defaults)
    save_config(config_path, config)
    return config


def save_config(config_path: str | None = None, config: dict | None = None) -> None:
    if config is None:
        config = get_default_config()
    path = _resolve_config_path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)


# ─── Likes storage ───

def _likes_path(config_path=None):
    if config_path:
        return Path(config_path).parent / "likes.json"
    return get_app_data_dir() / "likes.json"


def load_likes(config_path=None):
    p = _likes_path(config_path)
    if p.exists():
        try:
            with open(p, "r", encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict):
                return d
        except Exception:
            pass
    return {"posts": []}


def save_likes(config_path=None, data=None):
    p = _likes_path(config_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data or {"posts": []}, f, indent=2)


# ─── Collections storage ───

def _collections_path(config_path=None):
    if config_path:
        return Path(config_path).parent / "collections.json"
    return get_app_data_dir() / "collections.json"


def load_collections(config_path=None):
    p = _collections_path(config_path)
    if p.exists():
        try:
            with open(p, "r", encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict):
                return d
        except Exception:
            pass
    return {"collections": []}


def save_collections(config_path=None, data=None):
    p = _collections_path(config_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data or {"collections": []}, f, indent=2)
