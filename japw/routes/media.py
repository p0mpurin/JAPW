"""Image proxy (PNG for the clipboard) and dominant-colour lookup."""

from flask import Blueprint, Response, jsonify, request

from japw.media import dominant_colors, fetch_png, is_allowed_image_url
from japw.pinterest import canonical_key
from japw.routes.common import body, error

bp = Blueprint("media", __name__)


@bp.get("/api/image.png")
def image_png():
    url = request.args.get("url", "").strip()
    if not is_allowed_image_url(url):
        return error("Unsupported image host")
    try:
        data = fetch_png(url)
    except Exception as e:
        return error(f"Could not load image: {e}", 502)
    return Response(data, mimetype="image/png", headers={"Cache-Control": "private, max-age=600"})


@bp.post("/api/clipboard")
def clipboard():
    """Copy an image (url) or text to the system clipboard natively."""
    from japw.clipboard import ClipboardUnavailable, copy_image, copy_text

    data = body()
    try:
        if data.get("text") is not None:
            copy_text(str(data["text"])[:10000])
            return jsonify({"copied": "text"})
        url = (data.get("url") or "").strip()
        if not is_allowed_image_url(url):
            return error("Unsupported image host")
        copy_image(fetch_png(url))
        return jsonify({"copied": "image"})
    except ClipboardUnavailable as e:
        return error(str(e), 501)
    except Exception as e:
        return error(f"Could not copy: {e}", 502)


@bp.post("/api/colors")
def colors():
    urls = [str(u) for u in (body().get("urls") or []) if u][:200]
    items = [(canonical_key(u), u) for u in urls]
    found = dominant_colors(items)
    return jsonify({"colors": {u: found[k] for k, u in items if k in found}})
