"""
JAPW as an MCP server: lets an AI assistant do everything the app can — find pins by text,
image, colour or taste, look at them, like / collect / download them, browse boards and X
artists, and manage settings.

Run:  python -m japw.mcp_server          (stdio transport)
Data: shares the app's data folder (%APPDATA%\\JAPW, or JAPW_DATA_DIR), so likes, collections,
      downloads and logins are the same ones you see in the app.

Every pin a tool returns gets a short, stable `ref` (e.g. "p3f9a1c2"). Pass refs to the
action tools. Listing tools also return a numbered contact sheet so the assistant can *see*
the pins before choosing.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Share the installed app's data unless told otherwise. Must happen before japw imports.
if not os.environ.get("JAPW_DATA_DIR"):
    _appdata = Path(os.environ.get("APPDATA", Path.home())) / "JAPW"
    if _appdata.is_dir() or getattr(sys, "frozen", False):
        os.environ["JAPW_DATA_DIR"] = str(_appdata)

import concurrent.futures  # noqa: E402
import hashlib  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import threading  # noqa: E402
import webbrowser  # noqa: E402
from collections import OrderedDict  # noqa: E402
from typing import Annotated, Any, Literal  # noqa: E402

from mcp.server.mcpserver import Image, MCPServer  # noqa: E402
from pydantic import Field  # noqa: E402

import japw.pinterest as ps  # noqa: E402
import japw.x as xs  # noqa: E402
from japw import feeds, library as lib, taste  # noqa: E402
from japw.colors import BUCKETS, bucket as color_bucket  # noqa: E402
from japw.config import get_app_data_dir, load_config, save_config  # noqa: E402
from japw.images import canonical_key, pinimg_sized  # noqa: E402
from japw.media import _http as media_http, dominant_colors, fetch_png, is_allowed_image_url  # noqa: E402
from japw.pinterest.parse import set_content_filters  # noqa: E402

INSTRUCTIONS = """\
JAPW is the user's Pinterest + X art browser. Use these tools to find, look at, and save images.

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
- Downloads land in the user's download folder (see japw_status); `subfolder` groups them.
- Liking, collecting and downloading also teach the user's For You feed.
Don't download or change the library unless the user asked for it.
"""

mcp = MCPServer("JAPW", instructions=INSTRUCTIONS, version="1.2.0")

Color = Literal["red", "orange", "yellow", "green", "teal", "blue", "purple", "pink", "brown", "black", "gray", "white"]
Count = Annotated[int, Field(ge=1, le=100, description="How many pins to return")]
Offset = Annotated[int, Field(ge=0, description="Skip this many (for paging: pass the previous next_offset)")]
Preview = Annotated[bool, Field(description="Include a numbered contact-sheet image of the results")]
Refs = Annotated[list[str], Field(min_length=1, description="Pin refs (from earlier results) or image URLs")]

# ─── Ref store ───────────────────────────────────────────────────────────────

_refs: OrderedDict[str, dict] = OrderedDict()
_refs_lock = threading.Lock()


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
    if s.startswith("https://") and is_allowed_image_url(s):
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
        base = url.split("?")[0]
        return f"{base}?name={'small' if px <= 680 else 'large'}"
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
        r = media_http.get(url, timeout=timeout)
        r.raise_for_status()
        return r.content
    except Exception:
        return None


_thumb_pool = concurrent.futures.ThreadPoolExecutor(max_workers=12, thread_name_prefix="JAPW-mcp-thumb")


def _contact_sheet(posts: list[dict], start: int = 1, cols: int = 6, tile_w: int = 180, tile_h: int = 225) -> Image | None:
    """One JPEG grid of numbered thumbnails — lets the assistant see many pins in one image."""
    if not posts:
        return None
    from PIL import Image as PILImage, ImageDraw, ImageFont, ImageOps

    datas = list(_thumb_pool.map(lambda p: _fetch_image(_thumb_url(p["urls"][0])), posts))
    cols = min(cols, len(posts))
    rows = (len(posts) + cols - 1) // cols
    gap = 6
    sheet = PILImage.new("RGB", (cols * tile_w + (cols + 1) * gap, rows * tile_h + (rows + 1) * gap), (16, 16, 18))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("arialbd.ttf", 18)
    except OSError:
        font = ImageFont.load_default()
    for i, data in enumerate(datas):
        x = gap + (i % cols) * (tile_w + gap)
        y = gap + (i // cols) * (tile_h + gap)
        if data:
            try:
                im = PILImage.open(io.BytesIO(data)).convert("RGB")
                sheet.paste(ImageOps.fit(im, (tile_w, tile_h), PILImage.Resampling.LANCZOS), (x, y))
            except Exception:
                draw.rectangle([x, y, x + tile_w, y + tile_h], fill=(40, 40, 46))
        else:
            draw.rectangle([x, y, x + tile_w, y + tile_h], fill=(40, 40, 46))
        label = str(start + i)
        w = draw.textlength(label, font=font) + 12
        draw.rounded_rectangle([x + 5, y + 5, x + 5 + w, y + 31], radius=8, fill=(0, 0, 0))
        draw.text((x + 11, y + 7), label, fill=(255, 255, 255), font=font)
    out = io.BytesIO()
    sheet.save(out, "JPEG", quality=82)
    return Image(data=out.getvalue(), format="jpeg")


def _listing(posts: list[dict], header: dict, preview: bool, offset: int = 0) -> list:
    """Numbered JSON list (+ contact sheet). Numbers match the sheet's labels."""
    items = [_summary(p, offset + i + 1) for i, p in enumerate(posts)]
    text = json.dumps({**header, "count": len(items), "pins": items}, ensure_ascii=False, indent=1)
    sheet = _contact_sheet(posts, start=offset + 1) if preview and posts else None
    return [text, sheet] if sheet else [text]


def _page_header(offset: int, posts: list, has_more: bool, **extra) -> dict:
    return {**extra, "offset": offset, "next_offset": offset + len(posts), "has_more": has_more}


def _err(e: Exception) -> str:
    if isinstance(e, ps.PinterestAuthExpired):
        return "Pinterest session expired — ask the user to sync again (sync_pinterest_login)."
    return f"{type(e).__name__}: {e}"


# ─── Status & accounts ───────────────────────────────────────────────────────

@mcp.tool()
def japw_status() -> str:
    """Accounts, library size, download folder and taste profile. Call this first if unsure what's set up."""
    cfg = load_config()
    return json.dumps({
        "pinterest_connected": ps.has_session(),
        "x_connected": xs.has_x_session(),
        "download_folder": cfg.get("download_folder"),
        "likes": len(lib.list_likes()),
        "collections": [{"name": c["name"], "pins": c["count"]} for c in lib.list_collections()],
        "downloads": len(lib.downloaded()),
        "x_artists": [a.get("username") for a in xs.load_artists()],
        "for_you_profile": taste.summary(),
        "filters": {"hide_promoted": cfg.get("filter_promoted", True), "hide_ai": cfg.get("filter_ai_content", False)},
        "data_folder": str(get_app_data_dir().resolve()),
    }, indent=1)


@mcp.tool()
def sync_pinterest_login() -> str:
    """Copy the Pinterest login from the user's installed browsers (Chrome, Edge, Firefox, Zen…). The user must be logged in on pinterest.com there."""
    from japw.pinterest import session

    try:
        session.sync_session_from_installed_browsers()
        session._notify()
    except Exception as e:
        return f"Sync failed: {e}"
    return "Pinterest login synced." if ps.has_session() else "No Pinterest login found in installed browsers."


@mcp.tool()
def sync_x_login() -> str:
    """Copy the X (Twitter) login from the user's installed browsers, for the artist tools."""
    try:
        xs.sync_x_session_from_browsers()
        xs.reload_x_session()
    except Exception as e:
        return f"Sync failed: {e}"
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
    """Search Pinterest. Optionally only pins of one colour. Works logged out too (logged in, results follow the user's account)."""
    try:
        posts, more = ps.search(query, offset, count, color=color)
    except Exception as e:
        return [_err(e)]
    return _listing(posts, _page_header(offset, posts, more, query=query, color=color), preview, offset)


@mcp.tool()
def home_feed(count: Count = 24, color: Color | None = None, offset: Offset = 0, refresh: bool = False, preview: Preview = True) -> list:
    """The user's personalised Pinterest home feed. refresh=True starts a fresh feed from the top."""
    try:
        posts, more = ps.home(offset, count, refresh=refresh, color=color)
    except Exception as e:
        return [_err(e)]
    return _listing(posts, _page_header(offset, posts, more, feed="home", color=color), preview, offset)


@mcp.tool()
def for_you_feed(count: Count = 24, color: Color | None = None, offset: Offset = 0, refresh: bool = False, preview: Preview = True) -> list:
    """JAPW's For You feed: more of what the user likes, built from pins they opened / liked / downloaded / collected."""
    try:
        posts, more, personal = ps.for_you(offset, count, refresh=refresh, color=color)
    except Exception as e:
        return [_err(e)]
    note = None if personal else "Not personalised yet (no taste signals) — showing the home feed."
    return _listing(posts, _page_header(offset, posts, more, feed="for_you", color=color, note=note), preview, offset)


def _pin_id(post: dict) -> str | None:
    link = post.get("pin_url") or ""
    pid = link.rstrip("/").rsplit("/", 1)[-1] if "/pin/" in link else ""
    return pid if pid.isdigit() else None


@mcp.tool()
def similar_pins(ref: Annotated[str, Field(description="A pin ref or image URL")], count: Count = 24, preview: Preview = True) -> list:
    """Pins similar to one pin. Uses Pinterest's "more like this" for Pinterest pins, visual search for anything else (X art, plain image URLs)."""
    try:
        post = _resolve(ref)
        pid = _pin_id(post)
        if pid and ps.has_session():
            posts = ps.related(pid, limit=count)
            how = "related"
        else:
            from japw import visual

            sid = visual.start(visual.fetch_image(_thumb_url(post["urls"][0], 736)))
            posts, _ = visual.page(sid, 0, count)
            how = "visual"
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
    from japw import visual

    try:
        src = image.strip()
        p = Path(src.strip('"'))
        if not src.startswith("http") and p.is_file():
            data = p.read_bytes()
        elif src.startswith("https://") and not is_allowed_image_url(src):
            data = visual.fetch_image(src)
        else:
            data = visual.fetch_image(_thumb_url(_resolve(src)["urls"][0], 736))
        sid = visual.start(data)
        posts, more = visual.page(sid, offset, count)
    except Exception as e:
        return [_err(e)]
    return _listing(posts, _page_header(offset, posts, more, searched_image=src), preview, offset)


@mcp.tool()
def search_suggestions(text: str) -> str:
    """Pinterest's autocomplete suggestions — useful for refining a search."""
    try:
        return json.dumps(ps.suggestions(text), ensure_ascii=False)
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
            post = _resolve(r)
        except ValueError as e:
            out.append(str(e))
            continue
        data = _fetch_image(_thumb_url(post["urls"][0], px))
        out.append(json.dumps(_summary(post)))
        if data:
            out.append(Image(data=data, format="png" if data[:4] == b"\x89PNG" else "jpeg"))
    return out


@mcp.tool()
def pin_details(ref: Annotated[str, Field(description="A pin ref or image URL")]) -> str:
    """Everything known about a pin: all image URLs (carousel slides), size, colour, link, and whether it's liked / downloaded / in collections."""
    try:
        post = _resolve(ref)
    except ValueError as e:
        return str(e)
    key = canonical_key(post["urls"][0])
    cols = []
    for c in lib.list_collections():
        _, cposts = lib.collection_posts(c["id"])
        if any(p.get("key") == key for p in cposts):
            cols.append(c["name"])
    info = _summary(post)
    info.update({
        "all_images": post["urls"],
        "liked": lib.is_liked(post["urls"]),
        "downloaded_to": lib.downloaded().get(key),
        "in_collections": cols,
        "hex_color": post.get("color"),
    })
    return json.dumps(info, indent=1, ensure_ascii=False)


@mcp.tool()
def pin_colors(refs: Refs) -> str:
    """Dominant colour (name + hex) of pins — measures it when Pinterest didn't provide one (X art, plain URLs)."""
    posts = _resolve_many(refs)
    missing = [(canonical_key(p["urls"][0]), p["urls"][0]) for p in posts if not p.get("color")]
    measured = dominant_colors(missing) if missing else {}
    out = []
    for r, p in zip(refs, posts):
        hexc = p.get("color") or measured.get(canonical_key(p["urls"][0]))
        out.append({"ref": _remember(p), "hex": hexc, "color": color_bucket(hexc)})
    return json.dumps(out)


# ─── Boards ──────────────────────────────────────────────────────────────────

@mcp.tool()
def list_boards() -> str:
    """The user's Pinterest boards."""
    try:
        boards = ps.my_boards()
    except Exception as e:
        return _err(e)
    return json.dumps([{k: b[k] for k in ("id", "name", "count", "secret")} for b in boards], indent=1, ensure_ascii=False)


@mcp.tool()
def board_pins(
    board: Annotated[str, Field(description="Board name or id")],
    count: Count = 30,
    offset: Offset = 0,
    preview: Preview = True,
) -> list:
    """Pins on one of the user's boards."""
    try:
        boards = ps.my_boards()
        b = next((x for x in boards if x["id"] == board), None) or \
            next((x for x in boards if x["name"].lower() == board.strip().lower()), None)
        if not b:
            return [f"No board named '{board}'. Boards: {', '.join(x['name'] for x in boards)}"]
        posts, more = ps.board_pins(b["id"], b.get("url", ""), offset, count)
    except Exception as e:
        return [_err(e)]
    return _listing(posts, _page_header(offset, posts, more, board=b["name"]), preview, offset)


# ─── X artists ───────────────────────────────────────────────────────────────

@mcp.tool()
def list_artists() -> str:
    """X artists the user follows in JAPW."""
    return json.dumps([{k: a.get(k) for k in ("username", "display_name")} for a in xs.load_artists()], ensure_ascii=False)


@mcp.tool()
def add_artist(username: Annotated[str, Field(description="X handle or profile link")]) -> str:
    """Follow an X artist in JAPW's Artists tab."""
    u = username.strip().lstrip("@")
    if ".com/" in u:
        u = u.split(".com/", 1)[1].split("/")[0].split("?")[0]
    if not u.replace("_", "").isalnum():
        return "That doesn't look like an X username."
    if xs.artist_exists(u):
        return f"@{u} is already followed."
    artist = {"username": u, "display_name": u, "avatar_url": None}
    if xs.has_x_session():
        try:
            info = xs.fetch_user_info(u)
            artist.update(username=info["username"], display_name=info["display_name"], avatar_url=info["avatar_url"])
        except Exception as e:
            return _err(e)
    import time

    artist["added_at"] = int(time.time())
    xs.add_artist(artist)
    return f"Now following @{artist['username']} ({artist['display_name']})."


@mcp.tool()
def remove_artist(username: str) -> str:
    """Stop following an X artist in JAPW."""
    return f"Removed @{username.lstrip('@')}." if xs.remove_artist(username.lstrip("@")) else "Not in the list."


@mcp.tool()
def artist_media(
    username: Annotated[str | None, Field(description="An artist's handle, or omit for all followed artists mixed")] = None,
    count: Count = 24,
    offset: Offset = 0,
    refresh: bool = False,
    preview: Preview = True,
) -> list:
    """Images posted by X artists (one artist, or everyone the user follows)."""
    if not xs.has_x_session():
        return ["Not connected to X — ask the user to log in on x.com, then call sync_x_login."]
    try:
        posts, more = xs.media(username.lstrip("@") if username else None, offset, count, refresh=refresh)
    except Exception as e:
        return [_err(e)]
    return _listing(posts, _page_header(offset, posts, more, artist=username or "all"), preview, offset)


# ─── Likes ───────────────────────────────────────────────────────────────────

def _signal(kind: str, posts: list[dict]) -> None:
    for p in posts:
        taste.record(kind, p)


@mcp.tool()
def list_liked(count: Count = 30, offset: Offset = 0, color: Color | None = None, preview: Preview = True) -> list:
    """The user's liked pins (newest first), optionally only one colour."""
    posts = [{"urls": p["urls"], "color": p.get("color"), "pin_url": p.get("pin_url")} for p in lib.list_likes() if p.get("urls")]
    if color:
        need = [(canonical_key(p["urls"][0]), p["urls"][0]) for p in posts if not p.get("color")]
        measured = dominant_colors(need) if need else {}
        for p in posts:
            p["color"] = p.get("color") or measured.get(canonical_key(p["urls"][0]))
        posts = [p for p in posts if color_bucket(p.get("color")) == color]
    page = posts[offset:offset + count]
    return _listing(page, _page_header(offset, page, offset + count < len(posts), total=len(posts), color=color), preview, offset)


@mcp.tool()
def like_pins(refs: Refs) -> str:
    """Like pins (they appear in the app's Liked tab)."""
    posts = _resolve_many(refs)
    for p in posts:
        lib.set_like(p["urls"], True, p.get("color"), p.get("pin_url"))
    _signal("like", posts)
    return f"Liked {len(posts)} pin(s)."


@mcp.tool()
def unlike_pins(refs: Refs) -> str:
    """Remove pins from the user's likes."""
    posts = _resolve_many(refs)
    for p in posts:
        lib.set_like(p["urls"], False)
    return f"Unliked {len(posts)} pin(s)."


# ─── Collections ─────────────────────────────────────────────────────────────

def _collection(name_or_id: str, create: bool = False) -> dict:
    col = lib.find_collection(name_or_id)
    if col:
        return col
    if create:
        made = lib.create_collection(name_or_id)
        return lib.find_collection(made["id"])
    names = ", ".join(c["name"] for c in lib.list_collections()) or "none yet"
    raise ValueError(f"No collection '{name_or_id}'. Collections: {names}")


@mcp.tool()
def list_collections() -> str:
    """The user's JAPW collections (local folders of pins)."""
    return json.dumps([{k: c[k] for k in ("id", "name", "count")} for c in lib.list_collections()], ensure_ascii=False, indent=1)


@mcp.tool()
def create_collection(name: str) -> str:
    """Create a new collection."""
    existing = lib.find_collection(name)
    if existing:
        return f"A collection named '{existing['name']}' already exists."
    col = lib.create_collection(name)
    return f"Created collection '{col['name']}'."


@mcp.tool()
def rename_collection(collection: Annotated[str, Field(description="Collection name or id")], new_name: str) -> str:
    """Rename a collection."""
    try:
        col = _collection(collection)
        lib.rename_collection(col["id"], new_name)
    except Exception as e:
        return str(e)
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
        lib.delete_collection(col["id"])
    except Exception as e:
        return str(e)
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
        name, cposts = lib.collection_posts(col["id"])
    except Exception as e:
        return [str(e)]
    posts = [{"urls": p["urls"], "color": p.get("color"), "pin_url": p.get("pin_url")} for p in cposts if p.get("urls")]
    page = posts[offset:offset + count]
    return _listing(page, _page_header(offset, page, offset + count < len(posts), collection=name, total=len(posts)), preview, offset)


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
    except Exception as e:
        return str(e)
    added = sum(lib.add_to_collection(col["id"], p["urls"], p.get("color"), p.get("pin_url")) for p in posts)
    _signal("collect", posts)
    return f"Added {added} pin(s) to '{col['name']}'" + (f" ({len(posts) - added} were already there)." if added < len(posts) else ".")


@mcp.tool()
def remove_from_collection(collection: Annotated[str, Field(description="Collection name or id")], refs: Refs) -> str:
    """Remove pins from a collection."""
    try:
        col = _collection(collection)
        posts = _resolve_many(refs)
    except Exception as e:
        return str(e)
    removed = sum(lib.remove_from_collection(col["id"], canonical_key(p["urls"][0])) for p in posts)
    return f"Removed {removed} pin(s) from '{col['name']}'."


# ─── Downloads & sharing ─────────────────────────────────────────────────────

@mcp.tool()
def download_pins(
    refs: Refs,
    subfolder: Annotated[str | None, Field(description="Optional folder inside the download folder, e.g. 'blue wallpapers'")] = None,
    all_images: Annotated[bool, Field(description="Also save every slide of multi-image pins")] = False,
    name: Annotated[str | None, Field(description="Optional base file name (numbered automatically)")] = None,
) -> str:
    """Save pins at full resolution to the user's download folder. Never overwrites existing files."""
    posts = _resolve_many(refs)
    jobs = []
    for i, p in enumerate(posts):
        key = canonical_key(p["urls"][0])
        urls = p["urls"] if all_images else [p.get("gif_video_url") or p["urls"][0]]
        for j, u in enumerate(urls):
            base = None
            if name:
                base = f"{name} {i + 1}" + (f"-{j + 1}" if len(urls) > 1 else "") if len(posts) > 1 or len(urls) > 1 else name
            jobs.append((u, key, base))

    def run(job):
        u, key, base = job
        try:
            return lib.download(u, key, subfolder=subfolder, name=base), None
        except Exception as e:
            return None, f"{u}: {e}"

    results = list(_thumb_pool.map(run, jobs))
    saved = [p for p, _ in results if p]
    errors = [e for _, e in results if e]
    _signal("download", posts)
    folder = os.path.dirname(saved[0]) if saved else lib.download_folder()
    return json.dumps({"saved": len(saved), "folder": folder, "files": saved, "errors": errors}, indent=1, ensure_ascii=False)


@mcp.tool()
def list_downloads(limit: Annotated[int, Field(ge=1, le=500)] = 50) -> str:
    """Recently downloaded files (newest last) and whether they still exist."""
    items = list(lib.downloaded().items())[-limit:]
    return json.dumps([{"file": path, "exists": os.path.isfile(path)} for _, path in items], indent=1, ensure_ascii=False)


@mcp.tool()
def open_download_folder() -> str:
    """Open the download folder in Explorer for the user."""
    folder = lib.download_folder()
    if not os.path.isdir(folder):
        return "The download folder doesn't exist yet."
    if sys.platform == "win32":
        os.startfile(folder)
    else:
        webbrowser.open("file://" + folder)
    return f"Opened {folder}"


@mcp.tool()
def copy_image(ref: Annotated[str, Field(description="A pin ref or image URL")]) -> str:
    """Put a pin's image on the clipboard (the user can paste it into Discord, Photoshop…). Windows only."""
    from japw.clipboard import ClipboardUnavailable, copy_image as clip

    try:
        post = _resolve(ref)
        clip(fetch_png(post["urls"][0]))
    except ClipboardUnavailable as e:
        return str(e)
    except Exception as e:
        return _err(e)
    _signal("copy", [post])
    return "Image copied to the clipboard."


@mcp.tool()
def open_pin(ref: Annotated[str, Field(description="A pin ref or image URL")]) -> str:
    """Open a pin on Pinterest / X (or the image itself) in the user's browser."""
    try:
        post = _resolve(ref)
    except ValueError as e:
        return str(e)
    url = post.get("pin_url") or post["urls"][0]
    webbrowser.open(url)
    return f"Opened {url}"


# ─── Settings & taste ────────────────────────────────────────────────────────

@mcp.tool()
def get_settings() -> str:
    """JAPW settings (download folder, filters, wallpaper filter)."""
    return json.dumps(load_config(), indent=1, ensure_ascii=False)


@mcp.tool()
def update_settings(
    download_folder: Annotated[str | None, Field(description="Absolute folder path for downloads")] = None,
    hide_promoted: bool | None = None,
    hide_ai_content: bool | None = None,
    wallpaper_filter: Annotated[bool | None, Field(description="Only show images at least the target size")] = None,
    min_width: Annotated[int | None, Field(ge=1, le=16384)] = None,
    min_height: Annotated[int | None, Field(ge=1, le=16384)] = None,
) -> str:
    """Change JAPW settings. The app picks them up next time it loads settings."""
    cfg = load_config()
    changes = {}
    if download_folder:
        p = Path(download_folder).expanduser()
        if not p.is_absolute():
            return "download_folder must be an absolute path."
        p.mkdir(parents=True, exist_ok=True)
        changes["download_folder"] = str(p)
    for key, val in (("filter_promoted", hide_promoted), ("filter_ai_content", hide_ai_content),
                     ("resolution_filter_enabled", wallpaper_filter),
                     ("resolution_target_width", min_width), ("resolution_target_height", min_height)):
        if val is not None:
            changes[key] = val
    if not changes:
        return "Nothing to change."
    cfg.update(changes)
    save_config(None, cfg)
    set_content_filters(cfg.get("filter_promoted", True), cfg.get("filter_ai_content", False))
    feeds.cache.clear()
    return "Updated: " + ", ".join(f"{k}={v}" for k, v in changes.items())


@mcp.tool()
def taste_profile() -> str:
    """What the For You feed has learned: interaction counts and favourite colours."""
    return json.dumps(taste.summary(), indent=1)


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
