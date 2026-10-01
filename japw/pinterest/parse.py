"""Turn Pinterest API pin objects into the post dicts the UI uses, and filter ads / AI content."""

from __future__ import annotations

import base64

from japw.colors import bucket
from japw.images import dedupe_pinimg_urls, normalize_pin_url

# Updated from settings (see set_content_filters).
_filter_promoted = True
_filter_ai_content = False


def set_content_filters(filter_promoted: bool, filter_ai_content: bool) -> None:
    global _filter_promoted, _filter_ai_content
    _filter_promoted = bool(filter_promoted)
    _filter_ai_content = bool(filter_ai_content)


def _truthy(v) -> bool:
    if v is True:
        return True
    if isinstance(v, (int, float)) and not isinstance(v, bool) and v != 0:
        return True
    return isinstance(v, str) and v.strip().lower() in ("true", "1", "yes")


def is_promoted_pin(obj: dict) -> bool:
    """Detect promoted / sponsored / shopping-ad pins from Pinterest API JSON."""
    if not isinstance(obj, dict):
        return False

    for key in ("is_promoted", "isPromoted", "is_promoted_pin", "isPromotedPin"):
        if _truthy(obj.get(key)):
            return True

    # Organic tiles carry ad_match_reason: 0; only a real reason means an ad.
    if obj.get("ad_match_reason") not in (None, "", 0, False, []):
        return True

    prom = obj.get("promoter")
    if isinstance(prom, dict) and prom:
        return True
    for key in ("promoted_by_advertiser", "promoted_by", "promotedByAdvertiser", "promotedBy"):
        if obj.get(key) not in (None, "", False):
            return True
    if obj.get("promoted_is_removable") is True:
        return True
    for key in ("promotion_id", "ad_creative_id", "ad_id", "campaign_id",
                "advertiser_id", "insertion_id", "ad_group_id"):
        if obj.get(key) not in (None, "", 0, False):
            return True
    for key in ("ad_destination_url", "ad_landing_page_url", "click_through_link"):
        v = obj.get(key)
        if isinstance(v, str) and v.strip():
            return True

    tn = obj.get("__typename") or obj.get("type") or obj.get("entity_type")
    if isinstance(tn, str):
        tl = tn.lower()
        if ("promot" in tl and "unpromot" not in tl) or "advertiser" in tl or "adpin" in tl.replace("_", ""):
            return True

    disc = obj.get("disclosure_type")
    if isinstance(disc, str) and "ad" in disc.lower():
        return True
    for key in ("is_sponsored", "show_sponsored_label", "isPaidPartnership", "is_paid_partnership"):
        if _truthy(obj.get(key)):
            return True

    for key in ("module_type", "moduleType", "feed_item_type", "layout_type"):
        v = obj.get(key)
        if isinstance(v, str):
            vl = v.lower().replace("-", "_")
            if any(s in vl for s in ("shopping_ad", "shoppable_ad", "ad_module", "adslot")):
                return True
            if "sponsored" in vl and "unsponsored" not in vl:
                return True
            if vl.startswith(("promoted", "dsa")) or "_promoted_" in vl or vl.endswith("_promoted") or "dsa_" in vl:
                return True

    # Ad flags often live in a child object while the images sit on the pin itself.
    for key in ("ad_data", "adData", "ad_match_data", "adMatchData", "native_ad_data", "nativeAdData", "promoted_ad_data"):
        child = obj.get(key)
        if isinstance(child, dict) and child:
            return True

    tp = obj.get("tracking_params") or obj.get("trackingParams")
    if isinstance(tp, str) and len(tp) > 20:
        try:
            decoded = base64.b64decode(tp + "==", validate=False).decode("utf-8", errors="ignore")
            if '"is_promoted"' in decoded or '"promoted"' in decoded or '"ad_id"' in decoded:
                return True
        except Exception:
            pass

    for key, val in obj.items():
        if val in (None, "", False, 0, {}, []):
            continue
        kl = key.lower()
        if ("promot" in kl and "unpromot" not in kl) or ("sponsor" in kl and "unsponsor" not in kl):
            return True
    return False


def is_ai_content_pin(obj: dict) -> bool:
    """Detect AI-generated or AI-modified pins from Pinterest API JSON."""
    if not isinstance(obj, dict):
        return False
    for key in ("is_ai_modified", "isAiModified", "has_ai_attribution", "hasAiAttribution",
                "is_ai_generated", "isAiGenerated"):
        v = obj.get(key)
        if v is True or (isinstance(v, str) and v.strip().lower() in ("true", "1")):
            return True
    act = obj.get("ai_content_type") or obj.get("aiContentType")
    if isinstance(act, str) and act.strip():
        return True
    for key in ("ai_creator_attribution", "aiCreatorAttribution", "ai_tool_id", "aiToolId", "ai_attribution"):
        if obj.get(key) not in (None, "", {}, []):
            return True
    tn = (obj.get("__typename") or "").lower()
    return any(s in tn for s in ("aimodif", "aigenerat", "aicreated"))


def _image_urls(images: dict) -> list[str]:
    out: list[str] = []
    for entry in (images or {}).values():
        if isinstance(entry, dict):
            n = normalize_pin_url(entry.get("url") or "")
            if n and n not in out:
                out.append(n)
    return out


def _best_image(images: dict) -> str | None:
    best = dedupe_pinimg_urls(_image_urls(images))
    return best[0] if best else None


def _dimensions(images: dict) -> tuple[int, int] | None:
    for size in ("orig", "originals", "736x", "474x", "236x"):
        entry = (images or {}).get(size)
        if isinstance(entry, dict):
            try:
                w, h = int(entry.get("width") or 0), int(entry.get("height") or 0)
            except (TypeError, ValueError):
                continue
            if w > 0 and h > 0:
                return w, h
    return None


def _color(pin: dict) -> str | None:
    c = pin.get("dominant_color")
    if isinstance(c, str) and len(c) == 7 and c.startswith("#"):
        return c.lower()
    return None


def pin_to_post(pin: dict) -> dict | None:
    """
    API pin → {"urls", "pin_url", "width", "height", "color", "title"}.
    urls[0] is the cover at its best quality; carousel slides follow. None for ads/AI (if filtered)
    and pins without images.
    """
    if not isinstance(pin, dict):
        return None
    if _filter_promoted and is_promoted_pin(pin):
        return None
    if _filter_ai_content and is_ai_content_pin(pin):
        return None

    images = pin.get("images") or {}
    urls: list[str] = []
    cover = _best_image(images)
    if cover:
        urls.append(cover)

    carousel = pin.get("carousel_data")
    if isinstance(carousel, dict):
        for slot in carousel.get("carousel_slots") or []:
            u = _best_image((slot or {}).get("images") or {})
            if u:
                urls.append(u)

    if not urls:
        # Idea / story pins keep their cover elsewhere.
        story = pin.get("story_pin_data") or {}
        u = _best_image(story.get("cover_images") or story.get("thumbnail_color_images") or {})
        if u:
            urls.append(u)
    urls = dedupe_pinimg_urls(urls)
    if not urls:
        return None

    post: dict = {"urls": urls}
    dims = _dimensions(images)
    if dims:
        post["width"], post["height"] = dims
    color = _color(pin)
    if color:
        post["color"] = color
        post["bucket"] = bucket(color)
    title = (pin.get("grid_title") or pin.get("title") or "").strip()
    if title:
        post["title"] = title[:200]
    pin_id = str(pin.get("id") or "").strip()
    if pin_id.isdigit():
        post["pin_url"] = f"https://www.pinterest.com/pin/{pin_id}/"
    return post


def pins_to_posts(items) -> list[dict]:
    out = []
    for item in items or []:
        post = pin_to_post(item)
        if post:
            out.append(post)
    return out
