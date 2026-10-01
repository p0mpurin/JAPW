"""Settings and opening links in the user's browser."""

import webbrowser

from flask import Blueprint, jsonify

import japw.pinterest as ps
from japw.config import load_config, save_config
from japw.routes.common import body, cfg_path, error

bp = Blueprint("system", __name__)

_OPENABLE_PREFIXES = (
    "https://i.pinimg.com/",
    "https://www.pinterest.com/pin/",
    "https://x.com/",
    "https://twitter.com/",
    "https://pbs.twimg.com/",
)


@bp.get("/api/settings")
def get_settings():
    return jsonify(load_config(cfg_path()))


def _int_in_range(value, lo: int, hi: int) -> int | None:
    try:
        v = int(value)
    except (TypeError, ValueError):
        return None
    return v if lo <= v <= hi else None


@bp.post("/api/settings")
def update_settings():
    data = body()
    config = load_config(cfg_path())
    if "download_folder" in data:
        config["download_folder"] = str(data["download_folder"])
    for key in ("resolution_filter_enabled", "search_use_pinscrape_when_logged_in",
                "filter_promoted", "filter_ai_content"):
        if key in data:
            config[key] = bool(data[key])
    for key in ("resolution_target_width", "resolution_target_height"):
        if key in data:
            v = _int_in_range(data[key], 1, 16384)
            if v is not None:
                config[key] = v
    if str(data.get("resolution_match_mode", "")).lower().strip() in ("min", "exact"):
        config["resolution_match_mode"] = data["resolution_match_mode"].lower().strip()
    save_config(cfg_path(), config)
    ps.set_content_filters(config.get("filter_promoted", True), config.get("filter_ai_content", False))
    return jsonify({"success": True})


@bp.post("/api/open-url")
def open_url():
    url = (body().get("url") or "").strip()
    if not url.lower().startswith(_OPENABLE_PREFIXES):
        return error("Invalid url")
    webbrowser.open(url)
    return jsonify({"opened": True})
