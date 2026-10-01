"""
Local taste profile for the For You feed.

Every meaningful interaction (opening, liking, collecting, downloading, copying a pin) is
recorded on this machine only. Pins you engaged with recently and strongly become "seeds";
For You is built from Pinterest's "more like this" for those seeds. Nothing is sent to
Pinterest except the related-pins lookups themselves.
"""

from __future__ import annotations

import json
import threading
import time

from japw.config import get_app_data_dir

WEIGHTS = {"view": 1.0, "open": 1.0, "copy": 3.0, "download": 3.5, "like": 4.0, "collect": 4.0}
HALF_LIFE_DAYS = 10.0
MAX_EVENTS = 600

_lock = threading.Lock()
_events: list[dict] | None = None
_version = 0  # bumps whenever the profile changes (For You uses it to know when to rebuild)


def _path():
    return get_app_data_dir() / "taste.json"


def _load() -> list[dict]:
    global _events
    if _events is None:
        try:
            with open(_path(), encoding="utf-8") as f:
                data = json.load(f)
            _events = [e for e in data.get("events", []) if isinstance(e, dict)]
        except (OSError, ValueError):
            _events = []
    return _events


def _save() -> None:
    try:
        with open(_path(), "w", encoding="utf-8") as f:
            json.dump({"events": _events}, f)
    except OSError:
        pass


def pin_id_from_url(pin_url: str | None) -> str | None:
    if not pin_url or "/pin/" not in pin_url:
        return None
    pid = pin_url.rstrip("/").rsplit("/", 1)[-1]
    return pid if pid.isdigit() else None


def record(kind: str, post: dict) -> bool:
    """Store one interaction. Returns False for unknown kinds / posts without an image."""
    global _version
    if kind not in WEIGHTS or not isinstance(post, dict) or not post.get("urls"):
        return False
    event = {
        "kind": kind,
        "ts": time.time(),
        "url": str(post["urls"][0]),
        "pin_id": pin_id_from_url(post.get("pin_url")),
        "color": post.get("color") if isinstance(post.get("color"), str) else None,
        "source": post.get("source") or "pinterest",
        "artist": post.get("artist"),
    }
    with _lock:
        events = _load()
        # Collapse repeated views of the same pin within a minute.
        if kind == "view" and events and events[-1]["kind"] == "view" and events[-1]["url"] == event["url"] \
                and event["ts"] - events[-1]["ts"] < 60:
            return True
        events.append(event)
        del events[:-MAX_EVENTS]
        _version += 1
        _save()
    return True


def version() -> int:
    return _version


def _decay(ts: float, now: float) -> float:
    return 0.5 ** ((now - ts) / 86400 / HALF_LIFE_DAYS)


def seeds(limit: int = 10) -> list[str]:
    """Pinterest pin ids ranked by decayed interaction weight."""
    now = time.time()
    scores: dict[str, float] = {}
    with _lock:
        for e in _load():
            if e.get("pin_id"):
                scores[e["pin_id"]] = scores.get(e["pin_id"], 0.0) + WEIGHTS.get(e["kind"], 1.0) * _decay(e["ts"], now)
    return [pid for pid, _ in sorted(scores.items(), key=lambda kv: -kv[1])[:limit]]


def favourite_colors(limit: int = 3) -> list[str]:
    """Colour buckets you engage with most (for the profile summary)."""
    from japw.colors import bucket

    now = time.time()
    scores: dict[str, float] = {}
    with _lock:
        for e in _load():
            b = bucket(e.get("color"))
            if b:
                scores[b] = scores.get(b, 0.0) + WEIGHTS.get(e["kind"], 1.0) * _decay(e["ts"], now)
    return [b for b, _ in sorted(scores.items(), key=lambda kv: -kv[1])[:limit]]


def summary() -> dict:
    with _lock:
        events = list(_load())
    counts: dict[str, int] = {}
    for e in events:
        counts[e["kind"]] = counts.get(e["kind"], 0) + 1
    return {"events": len(events), "counts": counts, "seeds": len(seeds(50)), "colors": favourite_colors()}


def reset() -> None:
    global _events, _version
    with _lock:
        _events = []
        _version += 1
        _save()
