"""
Debug script for X scraping. Run from the JAPW directory:
    python debug_x.py <twitter_username>

Mirrors the exact production flow:
  1. _gather_x_cookies()  →  storage_state JSON  →  Playwright context
     (same as pinterest_session, no add_cookies)
  2. Navigate to /media tab, intercept UserMedia/UserTweets responses
  3. Run _parse_media_response and print results
"""

import json
import sys
import tempfile
import os

sys.path.insert(0, ".")


def main():
    username = sys.argv[1].lstrip("@") if len(sys.argv) > 1 else "NASA"
    print(f"\n=== Debugging X scraping for @{username} ===\n")

    # ── 1. Cookie gathering (same as production) ─────────────────────────────
    print("── Cookies ──")
    from x_session import (
        _gather_x_cookies, _cookies_to_storage_state,
        _parse_media_response, _is_media_response,
    )

    try:
        raw = _gather_x_cookies()
        print(f"  _gather_x_cookies() → {len(raw)} cookies")
        interesting = {"auth_token", "ct0", "twid"}
        shown = set()
        for c in raw:
            if c.name in interesting and c.name not in shown:
                shown.add(c.name)
                preview = c.value[:10] + "…" if len(c.value) > 10 else c.value
                print(f"    [{c.domain}] {c.name} = {preview}")
        has_auth = any(c.name == "auth_token" for c in raw)
        print(f"\n  auth_token: {has_auth}")
        if not has_auth:
            print("  ⚠  Close Zen Browser completely, then re-run.")
    except Exception as e:
        print(f"  ERROR: {e}")
        return

    state = _cookies_to_storage_state(raw)
    print(f"  storage_state cookies: {len(state['cookies'])}")

    # Spot-check expires values
    bad = [c for c in state["cookies"] if c.get("expires") not in (None,) and
           not (c.get("expires") == -1 or (isinstance(c.get("expires"), int) and c.get("expires") > 0))]
    if bad:
        print(f"  ⚠  {len(bad)} cookies with bad expires: {[b['name'] for b in bad]}")
    else:
        print("  expires values all valid ✓")

    # Write to a temp storage_state file (production writes to x_state.json)
    tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w", encoding="utf-8")
    json.dump(state, tmp)
    tmp.close()
    storage_file = tmp.name
    print(f"  storage_state saved to {storage_file}")

    # ── 2. Playwright navigation (same as production) ─────────────────────────
    print(f"\n── Navigating to x.com/{username}/media ──")
    from playwright.sync_api import sync_playwright

    all_responses = []
    json_responses = []

    def on_response(response):
        url = response.url
        ct = response.headers.get("content-type", "")
        all_responses.append((url, response.status, ct))
        if "json" in ct:
            try:
                body = response.json()
                json_responses.append((url, ct, body))
            except Exception:
                pass

    with sync_playwright() as pw:
        br = pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-gpu"])
        # Use storage_state file — same as production, no add_cookies
        ctx = br.new_context(
            storage_state=storage_file,
            viewport={"width": 1280, "height": 900},
            locale="en-US",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )

        page = ctx.new_page()

        def intercept(route):
            if route.request.resource_type in ("image", "media", "font", "stylesheet"):
                route.abort()
            else:
                route.fallback()

        page.route("**/*", intercept)
        page.on("response", on_response)

        try:
            page.goto(f"https://x.com/{username}/media",
                      wait_until="domcontentloaded", timeout=30000)
            print("  Page loaded. Waiting 4s for XHR…")
            page.wait_for_timeout(4000)

            for _ in range(8):
                page.evaluate("window.scrollBy(0, 3000)")
                page.wait_for_timeout(1500)

            title = page.title()
            print(f"  Page title: {title}")

            # Detect login wall
            login_wall = page.query_selector('a[href="/login"]')
            print(f"  Login wall visible: {login_wall is not None}")

        except Exception as e:
            print(f"  Navigation error: {e}")
        finally:
            page.close()
            ctx.close()
            br.close()

    os.unlink(storage_file)

    # ── 3. Response analysis ──────────────────────────────────────────────────
    graphql = [(u, s, ct) for u, s, ct in all_responses if "/graphql/" in u]
    print(f"\n── GraphQL responses: {len(graphql)} ──")
    for url, status, ct in graphql:
        op = url.split("?")[0].split("/")[-1]
        print(f"  [{status}] {op}  ct={ct!r}")

    tweet_responses = [(u, ct) for u, s, ct in all_responses
                       if ("UserMedia" in u or "UserTweets" in u) and "/graphql/" in u]
    print(f"\n  UserMedia/UserTweets URLs matched: {len(tweet_responses)}")

    # ── 4. Parser ─────────────────────────────────────────────────────────────
    print("\n── _parse_media_response ──")
    total_posts = []
    seen_ids: set = set()

    for url, ct, body in json_responses:
        if "/graphql/" not in url:
            continue
        op = url.split("?")[0].split("/")[-1]
        matched = _is_media_response(url, ct)
        print(f"  {op}: _is_media_response={matched}")

        if matched:
            # Drill into the structure as deep as possible
            def show(d, indent=4, max_depth=8):
                prefix = " " * indent
                if not isinstance(d, dict) or max_depth == 0:
                    print(f"{prefix}{repr(d)[:120]}")
                    return
                for k, v in d.items():
                    if isinstance(v, list):
                        print(f"{prefix}{k}: list[{len(v)}]")
                        if v and isinstance(v[0], dict):
                            show(v[0], indent + 2, max_depth - 1)
                    elif isinstance(v, dict):
                        print(f"{prefix}{k}: dict")
                        show(v, indent + 2, max_depth - 1)
                    else:
                        print(f"{prefix}{k}: {repr(v)[:80]}")

            print("    Full structure:")
            show(body)

            posts, user_info = _parse_media_response(body, username, seen_ids)
            print(f"    → {len(posts)} new posts  (running total: {len(total_posts) + len(posts)})")
            total_posts.extend(posts)

    print(f"\n── Total posts: {len(total_posts)} ──")
    for i, p in enumerate(total_posts[:5]):
        print(f"  [{i}] {p['urls'][0]}")
        print(f"       tweet: {p.get('pin_url')}")

    print("\n=== Done ===\n")


if __name__ == "__main__":
    main()
