import mimetypes
import os
import sys
import threading

from flask import Flask, send_from_directory

import japw.pinterest as ps
from japw.config import load_config
from japw.routes import library, media, pinterest, system, taste, x

# Windows' registry can map .js to text/plain, which browsers reject for ES modules.
mimetypes.add_type("text/javascript", ".js")


def get_base_path() -> str:
    """Base path for bundled resources (handles PyInstaller frozen mode)."""
    if getattr(sys, "frozen", False):
        return sys._MEIPASS
    return os.path.abspath(".")


def create_app(config_path: str | None = None, warm_up: bool = True) -> Flask:
    frontend_path = os.path.join(get_base_path(), "frontend")
    app = Flask(__name__, static_folder=frontend_path, static_url_path="")
    app.config["JAPW_CONFIG_PATH"] = config_path

    cfg = load_config(config_path)
    ps.set_content_filters(cfg.get("filter_promoted", True), cfg.get("filter_ai_content", False))
    if warm_up:
        threading.Thread(target=ps.warm_up, daemon=True).start()

    @app.route("/")
    def index():
        return send_from_directory(frontend_path, "index.html")

    for module in (pinterest, library, media, taste, x, system):
        app.register_blueprint(module.bp)
    return app
