#!/usr/bin/env python3
"""
Dump raw JSON from Pinterest UserHomefeedResource (same call JAPW uses for /api/home).

Requires a synced Pinterest session (Settings → sync in JAPW).

  python tools/dump_homefeed_json.py
  python tools/dump_homefeed_json.py -o homefeed.json
  python tools/dump_homefeed_json.py --bookmark "<paste bookmark string>"
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import japw.pinterest as ps  # noqa: E402


def homefeed_request_url(bookmark: str | None) -> str:
    opts: dict = {
        "field_set_key": "hf_grid",
        "in_nux": False,
        "in_news_hub": False,
        "static_feed": False,
    }
    if bookmark:
        opts["bookmarks"] = [bookmark]
    params = urlencode(
        {
            "source_url": "/",
            "data": json.dumps({"options": opts, "context": {}}, separators=(",", ":")),
            "_": int(time.time() * 1000),
        }
    )
    return f"/resource/UserHomefeedResource/get/?{params}"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Print raw UserHomefeedResource JSON using your JAPW Pinterest session."
    )
    parser.add_argument(
        "--bookmark",
        default="",
        help="Pagination token from prior response: resource_response.bookmark",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Write JSON to this file instead of stdout (UTF-8).",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Single-line JSON.",
    )
    args = parser.parse_args()

    if not ps.has_session():
        print(
            "No Pinterest session. Open JAPW → Settings and sync from your browser first.",
            file=sys.stderr,
        )
        sys.exit(1)

    bm = args.bookmark.strip() or None
    url = homefeed_request_url(bm)

    def task(ctx):
        page = ps._apibr_make_home_page(ctx)
        try:
            return ps._page_fetch_json(page, url)
        finally:
            ps._apibr_close_page(page)

    raw = ps._apibr_run(task)
    if raw is None:
        print(
            "Request returned nothing (fetch failed or non-JSON). "
            "Try syncing the session again or check Playwright.",
            file=sys.stderr,
        )
        sys.exit(2)

    indent: int | None = None if args.compact else 2
    text = json.dumps(raw, indent=indent, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        print(f"Wrote {args.output}", file=sys.stderr)
    else:
        print(text)


if __name__ == "__main__":
    main()
