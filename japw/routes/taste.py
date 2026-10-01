"""Local taste profile: interaction signals that drive the For You feed."""

from flask import Blueprint, jsonify

from japw import taste
from japw.routes.common import body, error

bp = Blueprint("taste", __name__)


@bp.post("/api/taste/signal")
def signal():
    data = body()
    if not taste.record(str(data.get("kind") or ""), data.get("post") or {}):
        return error("Unknown signal")
    return jsonify({"ok": True})


@bp.get("/api/taste")
def profile():
    return jsonify(taste.summary())


@bp.post("/api/taste/reset")
def reset():
    taste.reset()
    return jsonify({"ok": True})
