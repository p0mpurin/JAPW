import os
import sys
import threading

import webview

from japw.api import create_app
from japw.config import get_app_data_dir, load_window_state, save_window_state

DEFAULT_SIZE = (1100, 750)
MIN_SIZE = (800, 500)


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


def _position_on_screen(x, y, width: int) -> bool:
    """False when the saved position belongs to a monitor that is no longer connected."""
    if x is None or y is None:
        return False
    try:
        for s in webview.screens:
            if s.x - width // 2 <= x < s.x + s.width and s.y <= y < s.y + s.height:
                return True
        return False
    except Exception:
        return True


class WindowStateTracker:
    """Remembers the last normal (non-maximized) geometry so the next launch reopens there."""

    def __init__(self, window: webview.Window, initial: dict) -> None:
        self._state = dict(initial)
        window.events.resized += self._on_resized
        window.events.moved += self._on_moved
        window.events.maximized += lambda: self._state.update(maximized=True)
        window.events.restored += lambda: self._state.update(maximized=False)
        window.events.closing += self.save

    def _on_resized(self, width, height) -> None:
        if not self._state.get("maximized"):
            self._state.update(width=int(width), height=int(height))

    def _on_moved(self, x, y) -> None:
        if not self._state.get("maximized"):
            self._state.update(x=int(x), y=int(y))

    def save(self) -> None:
        try:
            save_window_state(self._state)
        except OSError:
            pass


def _shutdown_background_work() -> None:
    """Cancel in-flight feed fetches so the process exits promptly."""
    from japw import feeds

    feeds.shutdown()


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

    saved = load_window_state()
    width = max(MIN_SIZE[0], int(saved.get("width") or DEFAULT_SIZE[0]))
    height = max(MIN_SIZE[1], int(saved.get("height") or DEFAULT_SIZE[1]))
    x, y = saved.get("x"), saved.get("y")
    if not _position_on_screen(x, y, width):
        x = y = None

    window = webview.create_window(
        "JAPW",
        url=f"http://127.0.0.1:{port}",
        width=width,
        height=height,
        x=x,
        y=y,
        min_size=MIN_SIZE,
        resizable=True,
        maximized=bool(saved.get("maximized")),
        background_color="#050505",
        frameless=False,
    )
    WindowStateTracker(window, {"width": width, "height": height, "x": x, "y": y,
                                "maximized": bool(saved.get("maximized"))})

    api = Api(window)
    window.expose(api.pick_folder)
    window.expose(api.save_file)

    # Persistent WebView profile so localStorage (grid size, search history, last tab) survives restarts.
    webview.start(private_mode=False, storage_path=str(get_app_data_dir() / "webview"))
    _shutdown_background_work()


if __name__ == "__main__":
    main()
