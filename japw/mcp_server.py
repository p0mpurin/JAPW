"""
JAPW as an MCP server: lets an AI assistant do everything the app can — find pins by text,
image, colour or taste, look at them, like / collect / download them, browse boards and X
artists, and manage settings.

Run:  python japw_mcp.py   (or python -m japw.mcp_server) — stdio transport.

Everything goes through the running JAPW app's local API (http://127.0.0.1:52741), which is
opened automatically if it isn't running. The server itself never writes JAPW's files: when it
is started by a packaged (MSIX) app such as Claude Desktop, Windows redirects its AppData
writes into a private copy the app can't see. Going through the app keeps one source of truth.

Every pin a tool returns gets a short, stable `ref` (e.g. "p3f9a1c2"). Pass refs to the
action tools. Listing tools also return a numbered contact sheet so the assistant can *see*
the pins before choosing.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import io
import json
import os
import subprocess
import sys
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Annotated, Any, Literal

import requests
from mcp.server.mcpserver import Image, MCPServer
from pydantic import Field

from japw.colors import bucket as color_bucket
from japw.images import canonical_key, pinimg_sized

APP_URL = os.environ.get("JAPW_URL", "http://127.0.0.1:52741").rstrip("/")
ALLOWED_HOSTS = ("i.pinimg.com", "v.pinimg.com", "pbs.twimg.com", "video.twimg.com")

INSTRUCTIONS = """\
JAPW is the user's Pinterest + X art browser. Use these tools to find, look at, and save images.
They act through the JAPW app (opened automatically if needed), so changes show up there.

How it works:
- Every pin you get back has a short `ref` (like "p3f9a1c2"). Pass refs to action tools
  (download_pins, like_pins, add_to_collection, similar_pins, view_pins, copy_image …).
  Image URLs work wherever a ref does.
- Listing tools return a numbered contact sheet image plus a numbered list, so you can judge
  the look of results. Use view_pins to see a few pins large before deciding.
- Colours: red, orange, yellow, green, teal, blue, purple, pink, brown, black, gray, white.
  `color` on home_feed / for_you / search_pins filters server-side (fast).
- "More like these": similar_pins (Pinterest's related pins) or search_by_image (visual match;
  works for any picture, including X art and local files).
- Collection names match case-insensitively, so "handhelds" finds "Handhelds".
- Downloads land in the user's download folder (see japw_status); `subfolder` groups them.
- Liking, collecting and downloading also teach the user's For You feed.
Don't download or change the library unless the user asked for it.
"""

mcp = MCPServer("JAPW", instructions=INSTRUCTIONS, version="1.3.0")

Color = Literal["red", "orange", "yellow", "green", "teal", "blue", "purple", "pink", "brown", "black", "gray", "white"]
Count = Annotated[int, Field(ge=1, le=100, description="How many pins to return")]
Offset = Annotated[int, Field(ge=0, description="Skip this many (for paging: pass the previous next_offset)")]
Preview = Annotated[bool, Field(description="Include a numbered contact-sheet image of the results")]
Refs = Annotated[list[str], Field(min_length=1, description="Pin refs (from earlier results) or image URLs")]


# ─── Talking to the app ──────────────────────────────────────────────────────

class AppError(RuntimeError):
    pass


_http = requests.Session()
_http.mount("http://", requests.adapters.HTTPAdapter(pool_maxsize=16))
_cdn = requests.Session()
_cdn.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) JAPW"
_cdn.mount("https://", requests.adapters.HTTPAdapter(pool_maxsize=24))
_launch_lock = threading.Lock()


def _app_up() -> bool:
    try:
        return _http.get(f"{APP_URL}/api/auth/status", timeout=1.5).ok
    except requests.RequestException:
        return False


def _find_exe() -> Path | None:
    """The installed app: JAPW_EXE, a build next to this source tree, or the frozen exe itself."""
    candidates = [os.environ.get("JAPW_EXE")]
    if getattr(sys, "frozen", False):
        candidates.append(sys.executable)
    root = Path(__file__).resolve().parent.parent
    candidates.append(str(root / "dist" / "JAPW" / "JAPW.exe"))
    for c in candidates:
        if c and Path(c).is_file():
            return Path(c)
    return None


def _ensure_app() -> None:
    """Make sure the JAPW app is running; start it if not."""
    if _app_up():
        return
    with _launch_lock:
        if _app_up():
            return
        exe = _find_exe()
        if not exe:
            raise AppError("The JAPW app isn't running. Ask the user to open JAPW, then try again.")
        # Launch through Explorer: started from a packaged app (e.g. Claude Desktop) it would
        # otherwise inherit that package's redirected AppData and miss the user's real data.
        if sys.platform == "win32":
            subprocess.Popen(["explorer.exe", str(exe)])
        else:
            subprocess.Popen([str(exe)], start_new_session=True)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if _app_up():
                return
            time.sleep(0.5)
        raise AppError("Started JAPW but it didn't answer in time. Ask the user to check the app window.")


def api(method: str, path: str, *, timeout: float = 60, **kw) -> Any:
    _ensure_app()
    try:
        r = _http.request(method, f"{APP_URL}{path}", timeout=timeout, **kw)
    except requests.RequestException as e:
        raise AppError(f"Couldn't reach the JAPW app: {e}") from e
    try:
        data = r.json()
    except ValueError:
        data = {}
    if r.status_code >= 400 or (isinstance(data, dict) and data.get("error")):
        msg = data.get("error") if isinstance(data, dict) else None
        if isinstance(data, dict) and data.get("code") == "session_expired":
            msg = "Pinterest session expired — ask the user to sync again (sync_pinterest_login)."
        raise AppError(msg or f"JAPW returned HTTP {r.status_code}")
    return data


def get(path: str, **params) -> Any:
    return api("GET", path, params={k: v for k, v in params.items() if v is not None})


def post(path: str, body: dict | None = None, **kw) -> Any:
    return api("POST", path, json=body or {}, **kw)


# ─── Ref store ───────────────────────────────────────────────────────────────

_refs: OrderedDict[str, dict] = OrderedDict()
_refs_lock = threading.Lock()


def _is_cdn(url: str) -> bool:
    from urllib.parse import urlsplit

    try:
        p = urlsplit(url)
    except ValueError:
        return False
    return p.scheme == "https" and p.hostname in ALLOWED_HOSTS


def _ref_for(post: dict) -> str:
    return "p" + hashlib.sha1(canonical_key(post["urls"][0]).encode()).hexdigest()[:7]


def _remember(post: dict) -> str:
    ref = _ref_for(post)
    with _refs_lock:
        old = _refs.get(ref) or {}
        _refs[ref] = {**old, **{k: v for k, v in post.items() if v not in (None, "", [])}}
        _refs.move_to_end(ref)
        while len(_refs) > 20000:
            _refs.popitem(last=False)
    return ref


def _resolve(ref_or_url: str) -> dict:
    """A ref from earlier results, or a direct image URL."""
    s = (ref_or_url or "").strip()
    with _refs_lock:
        if s in _refs:
            return dict(_refs[s])
    if _is_cdn(s):
        post = {"urls": [s]}
        _remember(post)
        return post
    raise ValueError(f"Unknown pin '{s}'. Use a ref from an earlier result (like 'p3f9a1c2') or an image URL.")


def _resolve_many(refs: list[str]) -> list[dict]:
    return [_resolve(r) for r in refs]


# ─── Formatting ──────────────────────────────────────────────────────────────

def _thumb_url(url: str, px: int = 236) -> str:
    if "i.pinimg.com" in url:
        return pinimg_sized(url, "236x" if px <= 236 else "474x" if px <= 474 else "736x")
    if "pbs.twimg.com/media/" in url:
        return f"{url.split('?')[0]}?name={'small' if px <= 680 else 'large'}"
    return url


def _summary(post: dict, index: int | None = None) -> dict:
    out: dict[str, Any] = {}
    if index is not None:
        out["n"] = index
    out["ref"] = _remember(post)
    if post.get("title"):
        out["title"] = post["title"][:120]
    if post.get("width") and post.get("height"):
        out["size"] = f"{post['width']}x{post['height']}"
    b = post.get("bucket") or color_bucket(post.get("color"))
    if b:
        out["color"] = b
    out["source"] = "x" if post.get("source") == "x" else "pinterest"
    if post.get("artist"):
        out["artist"] = post["artist"]
    if len(post.get("urls") or []) > 1:
        out["images"] = len(post["urls"])
    if post.get("gif_video_url"):
        out["animated"] = True
    out["image"] = post["urls"][0]
    if post.get("pin_url"):
        out["link"] = post["pin_url"]
    return out


def _fetch_image(url: str, timeout: float = 15) -> bytes | None:
    try:
        r = _cdn.get(url, timeout=timeout)
        r.raise_for_status()
        return r.content
    except Exception:
        return None


_pool = concurrent.futures.ThreadPoolExecutor(max_workers=12, thread_name_prefix="JAPW-mcp")


def _contact_sheet(posts: list[dict], start: int = 1, cols: int = 6, tile_w: int = 180, tile_h: int = 225) -> Image | None:
    """One JPEG grid of numbered thumbnails — lets the assistant see many pins in one image."""
    if not posts:
        return None
    from PIL import Image as PILImage, ImageDraw, ImageFont, ImageOps

    datas = list(_pool.map(lambda p: _fetch_image(_thumb_url(p["urls"][0])), posts))
    cols = min(cols, len(posts))
    rows = (len(posts) + cols - 1) // cols
    gap = 6
    sheet = PILImage.new("RGB", (cols * tile_w + (cols + 1) * gap, rows * tile_h + (rows + 1) * gap), (16, 16, 18))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("arialbd.ttf", 20)
    except OSError:
        font = ImageFont.load_default()
    for i, data in enumerate(datas):
        x = gap + (i % cols) * (tile_w + gap)
        y = gap + (i // cols) * (tile_h + gap)
        placed = False
        if data:
            try:
                im = PILImage.open(io.BytesIO(data)).convert("RGB")
                sheet.paste(ImageOps.fit(im, (tile_w, tile_h), PILImage.Resampling.LANCZOS), (x, y))
                placed = True
            except Exception:
                pass
        if not placed:
            draw.rectangle([x, y, x + tile_w, y + tile_h], fill=(40, 40, 46))
        label = str(start + i)
        w = draw.textlength(label, font=font) + 14
        draw.rounded_rectangle([x + 5, y + 5, x + 5 + w, y + 33], radius=8, fill=(0, 0, 0))
        draw.text((x + 12, y + 7), label, fill=(255, 255, 255), font=font)
    out = io.BytesIO()
    sheet.save(out, "JPEG", quality=82)
    return Image(data=out.getvalue(), format="jpeg")


def _listing(posts: list[dict], header: dict, preview: bool, offset: int = 0) -> list:
    """Numbered JSON list (+ contact sheet). Numbers match the sheet's labels."""
    items = [_summary(p, offset + i + 1) for i, p in enumerate(posts)]
    text = json.dumps({**header, "count": len(items), "pins": items}, ensure_ascii=False, indent=1)
    sheet = _contact_sheet(posts, start=offset + 1) if preview and posts else None
    return [text, sheet] if sheet else [text]


def _paged(data: dict, offset: int, **extra) -> tuple[list[dict], dict]:
    posts = [p for p in data.get("posts", []) if p.get("urls")]
    return posts, {**extra, "offset": offset, "next_offset": data.get("next_offset", offset + len(posts)),
                   "has_more": bool(data.get("has_more"))}


def _err(e: Exception) -> str:
    return str(e) if isinstance(e, (AppError, ValueError)) else f"{type(e).__name__}: {e}"


def _signal(kind: str, posts: list[dict]) -> None:
    for p in posts:
        try:
            post("/api/taste/signal", {"kind": kind, "post": {k: p.get(k) for k in ("urls", "pin_url", "color", "source", "artist")}})
        except AppError:
            pass


# ─── Status & accounts ───────────────────────────────────────────────────────

@mcp.tool()
def japw_status() -> str:
    """Accounts, library size, download folder and taste profile. Call this first if unsure what's set up."""
    try:
        cfg = get("/api/settings")
        return json.dumps({
            "pinterest_connected": get("/api/auth/status").get("connected"),
            "x_connected": get("/x/auth/status").get("connected"),
            "download_folder": cfg.get("download_folder"),
            "likes": len(get("/api/likes").get("posts", [])),
            "collections": [{"name": c["name"], "pins": c["count"]} for c in get("/api/collections").get("collections", [])],
            "downloads": len(get("/api/downloads").get("keys", [])),
            "x_artists": [a.get("username") for a in get("/x/artists")],
            "for_you_profile": get("/api/taste"),
            "filters": {"hide_promoted": cfg.get("filter_promoted", True), "hide_ai": cfg.get("filter_ai_content", False)},
        }, indent=1, ensure_ascii=False)
    except Exception as e:
        return _err(e)


@mcp.tool()
def sync_pinterest_login() -> str:
    """Copy the Pinterest login from the user's installed browsers (Chrome, Edge, Firefox, Zen…). The user must be logged in on pinterest.com there."""
    try:
        try:
            post("/api/auth/login")
        except AppError as e:
            if "already" not in str(e).lower():
                raise
        for _ in range(120):
            st = get("/api/auth/status")
            if not st.get("login_in_progress"):
                if st.get("last_error"):
                    return f"Sync failed: {st['last_error']}"
                return "Pinterest login synced." if st.get("connected") else "No Pinterest login found."
            time.sleep(0.5)
        return "Still syncing — check again in a moment."
    except Exception as e:
        return _err(e)


@mcp.tool()
def sync_x_login() -> str:
    """Copy the X (Twitter) login from the user's installed browsers, for the artist tools."""
    try:
        post("/x/auth/sync")
    except Exception as e:
        return f"Sync failed: {_err(e)}"
    return "X login synced."


# ─── Finding pins ────────────────────────────────────────────────────────────

@mcp.tool()
def search_pins(
    query: Annotated[str, Field(description="What to look for, e.g. 'misty forest cabin'")],
    count: Count = 24,
    color: Color | None = None,
    offset: Offset = 0,
    preview: Preview = True,
) -> list:
    """Search Pinterest. Optionally only pins of one colour."""
    try:
        posts, hdr = _paged(get("/api/search", q=query, offset=offset, limit=count, color=color), offset, query=query, color=color)
    except Exception as e:
        return [_err(e)]
    return _listing(posts[:count], hdr, preview, offset)


@mcp.tool()
def home_feed(count: Count = 24, color: Color | None = None, offset: Offset = 0, refresh: bool = False, preview: Preview = True) -> list:
    """The user's personalised Pinterest home feed. refresh=True starts a fresh feed from the top."""
    try:
        posts, hdr = _paged(get("/api/home", offset=offset, limit=count, color=color, refresh=1 if refresh else None),
                            offset, feed="home", color=color)
    except Exception as e:
        return [_err(e)]
    return _listing(posts[:count], hdr, preview, offset)


@mcp.tool()
def for_you_feed(count: Count = 24, color: Color | None = None, offset: Offset = 0, refresh: bool = False, preview: Preview = True) -> list:
    """JAPW's For You feed: more of what the user likes, built from pins they opened / liked / downloaded / collected."""
    try:
        data = get("/api/foryou", offset=offset, limit=count, color=color, refresh=1 if refresh else None)
        note = None if data.get("personalised", True) else "Not personalised yet — showing the home feed."
        posts, hdr = _paged(data, offset, feed="for_you", color=color, note=note)
    except Exception as e:
        return [_err(e)]
    return _listing(posts[:count], hdr, preview, offset)


def _visual(data: bytes | None = None, url: str | None = None) -> str:
    if data is not None:
        return api("POST", "/api/visual", files={"image": ("image.jpg", data, "application/octet-stream")})["id"]
    return post("/api/visual", {"url": url})["id"]


@mcp.tool()
def similar_pins(ref: Annotated[str, Field(description="A pin ref or image URL")], count: Count = 24, preview: Preview = True) -> list:
    """Pins similar to one pin. Uses Pinterest's "more like this" for Pinterest pins, visual search for anything else (X art, plain image URLs)."""
    try:
        p = _resolve(ref)
        link = p.get("pin_url") or ""
        posts: list[dict] = []
        how = "related"
        if "pinterest.com/pin/" in link:
            try:
                posts = post("/api/pin/related", {"pin_url": link, "exclude_urls": p["urls"]}).get("posts", [])
            except AppError:
                posts = []
        if not posts:
            how = "visual"
            sid = _visual(url=_thumb_url(p["urls"][0], 736))
            posts = get(f"/api/visual/{sid}", offset=0, limit=count).get("posts", [])
    except Exception as e:
        return [_err(e)]
    return _listing(posts[:count], {"similar_to": ref, "method": how}, preview)


@mcp.tool()
def search_by_image(
    image: Annotated[str, Field(description="A pin ref, an https image URL, or a local file path")],
    count: Count = 24,
    offset: Offset = 0,
    preview: Preview = True,
) -> list:
    """Find pins that look like a picture (Pinterest visual search). Accepts refs, image URLs or files on this computer."""
    try:
        src = image.strip()
        path = Path(src.strip('"'))
        if not src.startswith("http") and path.is_file():
            sid = _visual(data=path.read_bytes())
        elif src.startswith("https://") and not _is_cdn(src):
            sid = _visual(url=src)
        else:
            sid = _visual(url=_thumb_url(_resolve(src)["urls"][0], 736))
        posts, hdr = _paged(get(f"/api/visual/{sid}", offset=offset, limit=count), offset, searched_image=src)
    except Exception as e:
        return [_err(e)]
    return _listing(posts[:count], hdr, preview, offset)


@mcp.tool()
def search_suggestions(text: str) -> str:
    """Pinterest's autocomplete suggestions — useful for refining a search."""
    try:
        return json.dumps(get("/api/search/suggest", q=text).get("suggestions", []), ensure_ascii=False)
    except Exception:
        return "[]"


# ─── Looking at pins ─────────────────────────────────────────────────────────

@mcp.tool()
def view_pins(refs: Refs, size: Literal["medium", "large"] = "medium") -> list:
    """See pins up close (one image each, up to 6). Use after a contact sheet to inspect candidates."""
    out: list = []
    px = 474 if size == "medium" else 736
    for r in refs[:6]:
        try:
            p = _resolve(r)
        except ValueError as e:
            out.append(str(e))
            continue
        data = _fetch_image(_thumb_url(p["urls"][0], px))
        out.append(json.dumps(_summary(p), ensure_ascii=False))
        if data:
            out.append(Image(data=data, format="png" if data[:4] == b"\x89PNG" else "jpeg"))
    return out


def _collections_containing(key: str) -> list[str]:
    names = []
    for c in get("/api/collections").get("collections", []):
        cposts = get(f"/api/collections/{c['id']}/posts").get("posts", [])
        if any(p.get("key") == key for p in cposts):
            names.append(c["name"])
    return names


@mcp.tool()
def pin_details(ref: Annotated[str, Field(description="A pin ref or image URL")]) -> str:
    """Everything known about a pin: all image URLs (carousel slides), size, colour, link, and whether it's liked / downloaded / in collections."""
    try:
        p = _resolve(ref)
        key = canonical_key(p["urls"][0])
        info = _summary(p)
        info.update({
            "all_images": p["urls"],
            "liked": any(x.get("key") == key for x in get("/api/likes").get("posts", [])),
            "downloaded": key in set(get("/api/downloads").get("keys", [])),
            "in_collections": _collections_containing(key),
            "hex_color": p.get("color"),
        })
        return json.dumps(info, indent=1, ensure_ascii=False)
    except Exception as e:
        return _err(e)


@mcp.tool()
def pin_colors(refs: Refs) -> str:
    """Dominant colour (name + hex) of pins — measures it when Pinterest didn't provide one (X art, plain URLs)."""
    try:
        posts = _resolve_many(refs)
        missing = [p["urls"][0] for p in posts if not p.get("color")]
        measured = post("/api/colors", {"urls": missing}).get("colors", {}) if missing else {}
    except Exception as e:
        return _err(e)
    out = []
    for p in posts:
        hexc = p.get("color") or measured.get(p["urls"][0])
        out.append({"ref": _remember(p), "hex": hexc, "color": color_bucket(hexc)})
    return json.dumps(out)


# ─── Boards ──────────────────────────────────────────────────────────────────

@mcp.tool()
def list_boards() -> str:
    """The user's Pinterest boards."""
    try:
        boards = get("/api/boards").get("boards", [])
    except Exception as e:
        return _err(e)
    return json.dumps([{k: b.get(k) for k in ("id", "name", "count", "secret")} for b in boards], indent=1, ensure_ascii=False)


@mcp.tool()
def board_pins(
    board: Annotated[str, Field(description="Board name or id")],
    count: Count = 30,
    offset: Offset = 0,
    preview: Preview = True,
) -> list:
    """Pins on one of the user's boards."""
    try:
        boards = get("/api/boards").get("boards", [])
        b = next((x for x in boards if x["id"] == board), None) or \
            next((x for x in boards if x["name"].lower() == board.strip().lower()), None)
        if not b:
            return [f"No board named '{board}'. Boards: {', '.join(x['name'] for x in boards)}"]
        posts, hdr = _paged(get(f"/api/boards/{b['id']}/pins", offset=offset, limit=count, url=b.get("url", "")), offset, board=b["name"])
    except Exception as e:
        return [_err(e)]
    return _listing(posts[:count], hdr, preview, offset)


# ─── X artists ───────────────────────────────────────────────────────────────

@mcp.tool()
def list_artists() -> str:
    """X artists the user follows in JAPW."""
    try:
        return json.dumps([{k: a.get(k) for k in ("username", "display_name")} for a in get("/x/artists")], ensure_ascii=False)
    except Exception as e:
        return _err(e)


@mcp.tool()
def add_artist(username: Annotated[str, Field(description="X handle or profile link")]) -> str:
    """Follow an X artist in JAPW's Artists tab."""
    try:
        a = post("/x/artists", {"username": username})
    except Exception as e:
        return _err(e)
    return f"Now following @{a.get('username')} ({a.get('display_name')})."


@mcp.tool()
def remove_artist(username: str) -> str:
    """Stop following an X artist in JAPW."""
    try:
        ok = api("DELETE", f"/x/artists/{username.lstrip('@')}").get("ok")
    except Exception as e:
        return _err(e)
    return f"Removed @{username.lstrip('@')}." if ok else "Not in the list."


@mcp.tool()
def artist_media(
    username: Annotated[str | None, Field(description="An artist's handle, or omit for all followed artists mixed")] = None,
    count: Count = 24,
    offset: Offset = 0,
    refresh: bool = False,
    preview: Preview = True,
) -> list:
    """Images posted by X artists (one artist, or everyone the user follows)."""
    try:
        data = get("/x/media", username=username.lstrip("@") if username else None, offset=offset, limit=count,
                   refresh=1 if refresh else None)
        posts, hdr = _paged(data, offset, artist=username or "all")
    except Exception as e:
        return [_err(e)]
    return _listing(posts[:count], hdr, preview, offset)


# ─── Likes ───────────────────────────────────────────────────────────────────

def _liked_keys() -> set[str]:
    return {p.get("key") for p in get("/api/likes").get("posts", [])}


def _set_liked(posts: list[dict], liked: bool) -> int:
    keys = _liked_keys()
    changed = 0
    for p in posts:
        if (canonical_key(p["urls"][0]) in keys) != liked:
            post("/api/likes/toggle", {"urls": p["urls"], "color": p.get("color"), "pin_url": p.get("pin_url")})
            changed += 1
    return changed


@mcp.tool()
def list_liked(count: Count = 30, offset: Offset = 0, color: Color | None = None, preview: Preview = True) -> list:
    """The user's liked pins (newest first), optionally only one colour."""
    try:
        posts = [{"urls": p["urls"], "color": p.get("color"), "pin_url": p.get("pin_url")}
                 for p in get("/api/likes").get("posts", []) if p.get("urls")]
        if color:
            missing = [p["urls"][0] for p in posts if not p.get("color")]
            measured = post("/api/colors", {"urls": missing}).get("colors", {}) if missing else {}
            for p in posts:
                p["color"] = p.get("color") or measured.get(p["urls"][0])
            posts = [p for p in posts if color_bucket(p.get("color")) == color]
    except Exception as e:
        return [_err(e)]
    page = posts[offset:offset + count]
    hdr = {"color": color, "total": len(posts), "offset": offset, "next_offset": offset + len(page),
           "has_more": offset + count < len(posts)}
    return _listing(page, hdr, preview, offset)


@mcp.tool()
def like_pins(refs: Refs) -> str:
    """Like pins (they appear in the app's Liked tab)."""
    try:
        posts = _resolve_many(refs)
        n = _set_liked(posts, True)
    except Exception as e:
        return _err(e)
    return f"Liked {n} pin(s)" + (f" ({len(posts) - n} already liked)." if n < len(posts) else ".")


@mcp.tool()
def unlike_pins(refs: Refs) -> str:
    """Remove pins from the user's likes."""
    try:
        n = _set_liked(_resolve_many(refs), False)
    except Exception as e:
        return _err(e)
    return f"Unliked {n} pin(s)."


# ─── Collections ─────────────────────────────────────────────────────────────

def _collections() -> list[dict]:
    return get("/api/collections").get("collections", [])


def _collection(name_or_id: str, create: bool = False) -> dict:
    cols = _collections()
    needle = name_or_id.strip().lower()
    col = next((c for c in cols if c["id"] == name_or_id), None) or \
        next((c for c in cols if c["name"].strip().lower() == needle), None)
    if col:
        return col
    if create:
        return post("/api/collections", {"name": name_or_id.strip()})["collection"]
    names = ", ".join(c["name"] for c in cols) or "none yet"
    raise ValueError(f"No collection '{name_or_id}'. Collections: {names}")


@mcp.tool()
def list_collections() -> str:
    """The user's JAPW collections (local folders of pins)."""
    try:
        return json.dumps([{k: c[k] for k in ("id", "name", "count")} for c in _collections()], ensure_ascii=False, indent=1)
    except Exception as e:
        return _err(e)


@mcp.tool()
def create_collection(name: str) -> str:
    """Create a new collection."""
    try:
        existing = next((c for c in _collections() if c["name"].strip().lower() == name.strip().lower()), None)
        if existing:
            return f"A collection named '{existing['name']}' already exists."
        col = post("/api/collections", {"name": name})["collection"]
    except Exception as e:
        return _err(e)
    return f"Created collection '{col['name']}'."


@mcp.tool()
def rename_collection(collection: Annotated[str, Field(description="Collection name or id")], new_name: str) -> str:
    """Rename a collection."""
    try:
        col = _collection(collection)
        api("PATCH", f"/api/collections/{col['id']}", json={"name": new_name})
    except Exception as e:
        return _err(e)
    return f"Renamed '{col['name']}' to '{new_name}'."


@mcp.tool()
def delete_collection(
    collection: Annotated[str, Field(description="Collection name or id")],
    confirm: Annotated[bool, Field(description="Must be true — only after the user explicitly asked to delete it")] = False,
) -> str:
    """Delete a collection (the pins themselves stay on Pinterest; only this list is removed). Needs confirm=true."""
    if not confirm:
        return "Not deleted: pass confirm=true once the user has confirmed."
    try:
        col = _collection(collection)
        api("DELETE", f"/api/collections/{col['id']}")
    except Exception as e:
        return _err(e)
    return f"Deleted collection '{col['name']}'."


@mcp.tool()
def collection_pins(
    collection: Annotated[str, Field(description="Collection name or id")],
    count: Count = 30,
    offset: Offset = 0,
    preview: Preview = True,
) -> list:
    """Pins in one collection."""
    try:
        col = _collection(collection)
        data = get(f"/api/collections/{col['id']}/posts")
    except Exception as e:
        return [_err(e)]
    posts = [{"urls": p["urls"], "color": p.get("color"), "pin_url": p.get("pin_url")} for p in data.get("posts", []) if p.get("urls")]
    page = posts[offset:offset + count]
    hdr = {"collection": data.get("name", col["name"]), "total": len(posts), "offset": offset,
           "next_offset": offset + len(page), "has_more": offset + count < len(posts)}
    return _listing(page, hdr, preview, offset)


@mcp.tool()
def add_to_collection(
    collection: Annotated[str, Field(description="Collection name or id")],
    refs: Refs,
    create_if_missing: bool = True,
) -> str:
    """Add pins to a collection (creates it if needed)."""
    try:
        col = _collection(collection, create=create_if_missing)
        posts = _resolve_many(refs)
        have = {p.get("key") for p in get(f"/api/collections/{col['id']}/posts").get("posts", [])}
        added = 0
        for p in posts:
            if canonical_key(p["urls"][0]) in have:
                continue
            post(f"/api/collections/{col['id']}/posts", {"urls": p["urls"], "color": p.get("color"), "pin_url": p.get("pin_url")})
            added += 1
    except Exception as e:
        return _err(e)
    _signal("collect", posts)
    return f"Added {added} pin(s) to '{col['name']}'" + (f" ({len(posts) - added} were already there)." if added < len(posts) else ".")


@mcp.tool()
def remove_from_collection(collection: Annotated[str, Field(description="Collection name or id")], refs: Refs) -> str:
    """Remove pins from a collection."""
    try:
        col = _collection(collection)
        posts = _resolve_many(refs)
        for p in posts:
            api("DELETE", f"/api/collections/{col['id']}/posts", json={"key": canonical_key(p["urls"][0])})
    except Exception as e:
        return _err(e)
    return f"Removed {len(posts)} pin(s) from '{col['name']}'."


# ─── Downloads & sharing ─────────────────────────────────────────────────────

@mcp.tool()
def download_pins(
    refs: Refs,
    subfolder: Annotated[str | None, Field(description="Optional folder inside the download folder, e.g. 'blue wallpapers'")] = None,
    all_images: Annotated[bool, Field(description="Also save every slide of multi-image pins")] = False,
    name: Annotated[str | None, Field(description="Optional base file name (numbered automatically)")] = None,
) -> str:
    """Save pins at full resolution to the user's download folder. Never overwrites existing files."""
    try:
        posts = _resolve_many(refs)
        _ensure_app()
    except Exception as e:
        return _err(e)
    jobs = []
    for i, p in enumerate(posts):
        key = canonical_key(p["urls"][0])
        urls = p["urls"] if all_images else [p.get("gif_video_url") or p["urls"][0]]
        for j, u in enumerate(urls):
            base = None
            if name:
                base = name if len(posts) == 1 and len(urls) == 1 else f"{name} {i + 1}" + (f"-{j + 1}" if len(urls) > 1 else "")
            jobs.append({"url": u, "key": key, "subfolder": subfolder, "name": base})

    def run(job):
        try:
            return post("/api/download", job).get("path"), None
        except Exception as e:
            return None, f"{job['url']}: {_err(e)}"

    results = list(_pool.map(run, jobs))
    saved = [p for p, _ in results if p]
    errors = [e for _, e in results if e]
    _signal("download", posts)
    return json.dumps({"saved": len(saved), "folder": os.path.dirname(saved[0]) if saved else None,
                       "files": saved, "errors": errors}, indent=1, ensure_ascii=False)


@mcp.tool()
def list_downloads() -> str:
    """How many images have been downloaded with JAPW, and where the download folder is."""
    try:
        return json.dumps({"downloaded": len(get("/api/downloads").get("keys", [])),
                           "folder": get("/api/settings").get("download_folder")}, ensure_ascii=False)
    except Exception as e:
        return _err(e)


@mcp.tool()
def open_download_folder() -> str:
    """Open the download folder in Explorer for the user."""
    try:
        post("/api/reveal", {})
    except Exception as e:
        return _err(e)
    return "Opened the download folder."


@mcp.tool()
def copy_image(ref: Annotated[str, Field(description="A pin ref or image URL")]) -> str:
    """Put a pin's image on the clipboard (the user can paste it into Discord, Photoshop…)."""
    try:
        p = _resolve(ref)
        post("/api/clipboard", {"url": p["urls"][0]})
    except Exception as e:
        return _err(e)
    _signal("copy", [p])
    return "Image copied to the clipboard."


@mcp.tool()
def open_pin(ref: Annotated[str, Field(description="A pin ref or image URL")]) -> str:
    """Open a pin on Pinterest / X (or the image itself) in the user's browser."""
    try:
        p = _resolve(ref)
        url = p.get("pin_url") or p["urls"][0]
        post("/api/open-url", {"url": url})
    except Exception as e:
        return _err(e)
    return f"Opened {url}"


# ─── Settings & taste ────────────────────────────────────────────────────────

@mcp.tool()
def get_settings() -> str:
    """JAPW settings (download folder, filters, wallpaper filter)."""
    try:
        return json.dumps(get("/api/settings"), indent=1, ensure_ascii=False)
    except Exception as e:
        return _err(e)


@mcp.tool()
def update_settings(
    download_folder: Annotated[str | None, Field(description="Absolute folder path for downloads")] = None,
    hide_promoted: bool | None = None,
    hide_ai_content: bool | None = None,
    wallpaper_filter: Annotated[bool | None, Field(description="Only show images at least the target size")] = None,
    min_width: Annotated[int | None, Field(ge=1, le=16384)] = None,
    min_height: Annotated[int | None, Field(ge=1, le=16384)] = None,
) -> str:
    """Change JAPW settings."""
    if download_folder and not Path(download_folder).expanduser().is_absolute():
        return "download_folder must be an absolute path."
    changes = {k: v for k, v in {
        "download_folder": download_folder, "filter_promoted": hide_promoted, "filter_ai_content": hide_ai_content,
        "resolution_filter_enabled": wallpaper_filter, "resolution_target_width": min_width,
        "resolution_target_height": min_height,
    }.items() if v is not None}
    if not changes:
        return "Nothing to change."
    try:
        post("/api/settings", changes)
    except Exception as e:
        return _err(e)
    return "Updated: " + ", ".join(f"{k}={v}" for k, v in changes.items())


@mcp.tool()
def taste_profile() -> str:
    """What the For You feed has learned: interaction counts and favourite colours."""
    try:
        return json.dumps(get("/api/taste"), indent=1)
    except Exception as e:
        return _err(e)


# ─── Prompts ─────────────────────────────────────────────────────────────────

@mcp.prompt()
def find_and_save(theme: str, how_many: int = 10) -> str:
    """Find pins matching a theme, check them visually, and save the best ones."""
    return (
        f"Find {how_many} great images for: {theme}.\n"
        "1. search_pins (try a couple of phrasings or search_suggestions; use `color` if a colour matters).\n"
        "2. Look at the contact sheets; view_pins the promising ones to check quality.\n"
        "3. Prefer large, clean images (check `size`). Use similar_pins on the best to find more in the same style.\n"
        f"4. download_pins the best {how_many} into a subfolder named after the theme, and add them to a collection "
        "with the same name. Then summarise what you saved."
    )


@mcp.prompt()
def more_like_my_taste(count: int = 20) -> str:
    """Use the user's likes and For You profile to find new pins in the same aesthetic."""
    return (
        "Look at taste_profile and list_liked to understand the user's aesthetic (colours, subjects, mood). "
        f"Then use for_you_feed, similar_pins on a few liked pins, and search_pins to gather {count} new pins that fit. "
        "Show me the best ones with view_pins and describe why they match before saving anything."
    )


def main() -> None:
    mcp.run("stdio")


if __name__ == "__main__":
    main()
