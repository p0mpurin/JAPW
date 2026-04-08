import os
import sys
import threading

# PyInstaller + Playwright: browsers live inside the collected package
if getattr(sys, "frozen", False):
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "0")

import webview

from japw.api import create_app


class Api:
    def __init__(self, window: webview.Window) -> None:
        self._window = window

    def pick_folder(self) -> str | None:
        result = self._window.create_file_dialog(webview.FOLDER_DIALOG)
        if result and len(result) > 0:
            return result[0]
        return None

    def save_file(self, content: str, filename: str) -> str | None:
        result = self._window.create_file_dialog(
            webview.SAVE_DIALOG,
            directory=os.path.expanduser("~"),
            save_filename=filename,
            file_types=("JSON files (*.json)", "All files (*.*)")
        )
        if not result:
            return None
        path = result[0] if isinstance(result, (list, tuple)) else str(result)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path


def start_flask(app, port: int) -> None:
    app.run(host="127.0.0.1", port=port, threaded=True, use_reloader=False)


def main() -> None:
    if getattr(sys, "frozen", False):
        import logging
        log = logging.getLogger("werkzeug")
        log.setLevel(logging.ERROR)

    app = create_app()
    port = 52741

    flask_thread = threading.Thread(
        target=start_flask,
        args=(app, port),
        daemon=True,
    )
    flask_thread.start()

    window = webview.create_window(
        "JAPW",
        url=f"http://127.0.0.1:{port}",
        width=1100,
        height=750,
        min_size=(800, 500),
        resizable=True,
        background_color="#050505",
        frameless=False,
    )

    api = Api(window)
    window.expose(api.pick_folder)
    window.expose(api.save_file)

    webview.start()


if __name__ == "__main__":
    main()
