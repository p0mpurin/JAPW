from unittest.mock import patch

import japw.x as xs
from japw import colors, taste
from japw.feeds import Feed, FeedCache, merged_pages


# ─── colours ───

def test_color_buckets():
    assert colors.bucket("#e5484d") == "red"
    assert colors.bucket("#3e63dd") == "blue"
    assert colors.bucket("#111111") == "black"
    assert colors.bucket("#f4f4f4") == "white"
    assert colors.bucket("#8b8d98") == "gray"
    assert colors.bucket("#5a3a20") == "brown"
    assert colors.bucket("nope") is None


# ─── shared feeds ───

def _posts(prefix, n):
    return [{"urls": [f"https://i.pinimg.com/736x/{prefix}/{i}.jpg"], "bucket": "blue" if i % 2 else "red"}
            for i in range(n)]


def test_merged_pages_interleaves_and_filters():
    a = Feed(lambda bm: (_posts("a", 4), None))
    b = Feed(lambda bm: (_posts("b", 4), None))
    merged = Feed(merged_pages([a, b], keep=lambda p: p["bucket"] == "blue", per_source=4), merged=True)
    got, more = merged.get(0, 50, min_count=50)
    assert [p["urls"][0][-7:] for p in got] == ["a/1.jpg", "b/1.jpg", "a/3.jpg", "b/3.jpg"]
    assert more is False


def test_merged_pages_survives_one_failing_source():
    def boom(bm):
        raise RuntimeError("down")
    ok = Feed(lambda bm: (_posts("ok", 2), None))
    merged = Feed(merged_pages([Feed(boom), ok], per_source=5), merged=True)
    got, _ = merged.get(0, 10, min_count=10)
    assert len(got) == 2


def test_feed_cache_factory_may_use_the_cache():
    cache = FeedCache()
    inner = cache.get(("inner",), lambda: Feed(lambda bm: ([], None)))
    outer = cache.get(("outer",), lambda: (cache.get(("inner",), lambda: None), Feed(lambda bm: ([], None)))[1])
    assert cache.peek(("inner",)) is inner and cache.peek(("outer",)) is outer


# ─── taste ───

PIN = {"urls": ["https://i.pinimg.com/736x/aa/bb/c.jpg"], "pin_url": "https://www.pinterest.com/pin/123/", "color": "#3e63dd"}
PIN2 = {"urls": ["https://i.pinimg.com/736x/dd/ee/f.jpg"], "pin_url": "https://www.pinterest.com/pin/456/"}


def test_taste_ranks_seeds_by_weight():
    taste.record("view", PIN)
    taste.record("download", PIN2)
    assert taste.seeds() == ["456", "123"]
    taste.record("like", PIN)
    assert taste.seeds()[0] == "123"
    s = taste.summary()
    assert s["counts"] == {"view": 1, "download": 1, "like": 1} and s["colors"] == ["blue"]
    assert not taste.record("bogus", PIN)


def test_taste_routes(client):
    assert client.post("/api/taste/signal", json={"kind": "like", "post": PIN}).status_code == 200
    assert client.post("/api/taste/signal", json={"kind": "nope", "post": PIN}).status_code == 400
    assert client.get("/api/taste").get_json()["seeds"] == 1
    client.post("/api/taste/reset")
    assert client.get("/api/taste").get_json()["events"] == 0


def test_foryou_route_passes_color_and_flags(client):
    with patch("japw.pinterest.has_session", return_value=True), \
            patch("japw.pinterest.for_you", return_value=([PIN], True, True)) as m:
        d = client.get("/api/foryou?offset=5&color=blue&refresh=1").get_json()
    assert d["personalised"] is True and d["next_offset"] == 6
    m.assert_called_once_with(5, 50, refresh=True, color="blue")


def test_home_and_search_ignore_unknown_colors(client):
    with patch("japw.pinterest.has_session", return_value=True), \
            patch("japw.pinterest.home", return_value=([], False)) as m:
        client.get("/api/home?color=chartreuse")
    m.assert_called_once_with(0, 50, refresh=False, color=None)


# ─── X ───

def _tweet(tid, media):
    return {"itemContent": {"tweet_results": {"result": {
        "__typename": "Tweet", "rest_id": tid,
        "core": {"user_results": {"result": {"core": {"screen_name": "artist"}}}},
        "legacy": {"full_text": "hello https://t.co/x", "extended_entities": {"media": media}},
    }}}}


PHOTO = {"type": "photo", "media_url_https": "https://pbs.twimg.com/media/AAA.jpg",
         "original_info": {"width": 1200, "height": 1600}}
GIF = {"type": "animated_gif", "media_url_https": "https://pbs.twimg.com/tweet_video_thumb/G.jpg",
       "video_info": {"variants": [{"content_type": "video/mp4", "bitrate": 0, "url": "https://video.twimg.com/g.mp4"}]}}


def test_parse_media_first_page_grid_module_and_cursor():
    body = {"data": {"user": {"result": {"timeline": {"timeline": {"instructions": [{
        "type": "TimelineAddEntries",
        "entries": [
            {"entryId": "profile-grid-0", "content": {"items": [{"item": _tweet("1", [PHOTO])}, {"item": _tweet("2", [GIF])}]}},
            {"entryId": "cursor-bottom-1", "content": {"cursorType": "Bottom", "value": "NEXT"}},
        ],
    }]}}}}}}
    posts, cursor = xs.parse_media(body, "artist")
    assert cursor == "NEXT"
    assert posts[0] == {
        "urls": ["https://pbs.twimg.com/media/AAA.jpg?name=orig"],
        "pin_url": "https://x.com/artist/status/1",
        "artist": "artist", "source": "x", "title": "hello", "width": 1200, "height": 1600,
    }
    assert posts[1]["gif_video_url"] == "https://video.twimg.com/g.mp4"


def test_parse_media_later_pages_and_end():
    body = {"data": {"user": {"result": {"timeline": {"timeline": {"instructions": [
        {"type": "TimelineAddToModule", "moduleItems": [{"item": _tweet("3", [PHOTO])}]},
        {"type": "TimelineAddEntries", "entries": [{"content": {"cursorType": "Bottom", "value": "N2"}}]},
    ]}}}}}}
    posts, cursor = xs.parse_media(body, "artist")
    assert len(posts) == 1 and cursor == "N2"
    empty = {"data": {"user": {"result": {"timeline": {"timeline": {"instructions": [
        {"type": "TimelineAddEntries", "entries": [{"content": {"cursorType": "Bottom", "value": "N3"}}]}]}}}}}}
    assert xs.parse_media(empty, "artist") == ([], None)


def test_x_routes(client):
    assert client.get("/x/media").status_code == 401
    assert client.post("/x/artists", json={"username": "not a name!"}).status_code == 400
    r = client.post("/x/artists", json={"username": "https://x.com/SomeArtist/media"})
    assert r.status_code == 201 and r.get_json()["username"] == "SomeArtist"
    assert client.post("/x/artists", json={"username": "@someartist"}).status_code == 409
    with patch("japw.x.has_x_session", return_value=True), \
            patch("japw.x.media", return_value=([{"urls": ["u"]}], True)) as m:
        d = client.get("/x/media?username=SomeArtist&offset=40").get_json()
    assert d["next_offset"] == 41 and d["has_more"]
    m.assert_called_once_with("SomeArtist", 40, 40, refresh=False)
