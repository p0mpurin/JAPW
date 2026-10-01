"""Colour buckets — must stay identical to frontend/js/core/colors.js."""

from __future__ import annotations

import colorsys

BUCKETS = ("red", "orange", "yellow", "green", "teal", "blue", "purple", "pink", "brown", "black", "gray", "white")

# How to ask Pinterest search for a colour.
SEARCH_WORDS = {
    "red": "red", "orange": "orange", "yellow": "yellow", "green": "green", "teal": "teal",
    "blue": "blue", "purple": "purple", "pink": "pink", "brown": "brown",
    "black": "black", "gray": "grey", "white": "white",
}


def hex_to_hsl(hex_color: str | None) -> tuple[float, float, float] | None:
    h = (hex_color or "").lstrip("#")
    if len(h) != 6:
        return None
    try:
        r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except ValueError:
        return None
    hue, light, sat = colorsys.rgb_to_hls(r, g, b)
    return hue * 360, sat, light


def bucket(hex_color: str | None) -> str | None:
    hsl = hex_to_hsl(hex_color)
    if not hsl:
        return None
    h, s, l = hsl
    if l < 0.14:
        return "black"
    if l > 0.88 and s < 0.5:
        return "white"
    if s < 0.14 or (s < 0.22 and (l < 0.25 or l > 0.75)):
        return "black" if l < 0.22 else "white" if l > 0.82 else "gray"
    if 12 <= h < 48 and l < 0.42:
        return "brown"
    if h < 12 or h >= 345:
        return "red"
    if h < 40:
        return "orange"
    if h < 68:
        return "yellow"
    if h < 160:
        return "green"
    if h < 195:
        return "teal"
    if h < 255:
        return "blue"
    if h < 295:
        return "purple"
    return "pink"
