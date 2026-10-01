from flask import current_app, jsonify, request

from japw.pinterest import PinterestAuthExpired


def cfg_path() -> str | None:
    return current_app.config.get("JAPW_CONFIG_PATH")


def body() -> dict:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def int_arg(name: str, default: int, lo: int = 0, hi: int = 500) -> int:
    try:
        return max(lo, min(hi, int(request.args.get(name, default))))
    except (TypeError, ValueError):
        return default


def error(msg: str, status: int = 400, **extra):
    return jsonify({"error": msg, **extra}), status


def pinterest_error(e: Exception):
    """401 + code=session_expired when Pinterest rejected the cookies, else 502."""
    if isinstance(e, PinterestAuthExpired):
        return error(str(e), 401, code="session_expired")
    return error(str(e) or e.__class__.__name__, 502)
