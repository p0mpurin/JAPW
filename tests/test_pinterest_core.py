import threading

import pytest

from japw.pinterest import parse
from japw.feeds import Feed, FeedCache
from japw.images import canonical_key, dedupe_pinimg_urls, normalize_pin_url


# ─── images ───

def test_dedupe_keeps_best_resolution():
    small = "https://i.pinimg.com/236x/ab/cd/abcdef.jpg"
    large = "https://i.pinimg.com/736x/ab/cd/abcdef.jpg"
    orig = "https://i.pinimg.com/originals/ab/cd/abcdef.png"
    assert dedupe_pinimg_urls([small, large]) == [large]
    assert dedupe_pinimg_urls([large, small, orig]) == [orig]


def test_canonical_key_matches_across_sizes_and_formats():
    assert canonical_key("https://i.pinimg.com/236x/ab/cd/x.jpg") == canonical_key("https://i.pinimg.com/originals/ab/cd/x.gif")
    # Same algorithm the frontend and stored likes use for non-pinimg URLs.
    assert canonical_key("https://pbs.twimg.com/media/abc.jpg?name=orig") == "https://pbs.twimg.com/media/abc"


def test_normalize_skips_avatars():
    assert normalize_pin_url("https://i.pinimg.com/75x75_RS/aa/bb.jpg") is None
    assert normalize_pin_url("https://example.com/a.jpg") is None
    assert normalize_pin_url("https://i.pinimg.com/736x/aa/bb.jpg?x=1") == "https://i.pinimg.com/736x/aa/bb.jpg"


# ─── parse ───

def test_is_promoted_pin_detects_markers():
    for pin in ({"is_promoted": True}, {"isPromoted": "true"}, {"promoted_is_removable": True},
                {"ad_match_reason": "x"}, {"promoter": {"id": "1"}}, {"__typename": "PromotedPin"},
                {"module_type": "SHOPPING_AD_ROW"}, {"ad_data": {"t": 1}}, {"campaign_id": "c"},
                {"ad_destination_url": "https://example.com"}):
        assert parse.is_promoted_pin(pin), pin
    assert not parse.is_promoted_pin({"ad_data": {}})
    assert not parse.is_promoted_pin({"id": "4", "type": "pin", "is_promoted": False,
                                      "promoted_is_removable": False, "ad_match_reason": 0})


def _pin(pin_id="41939840274795594", **extra):
    return {
        "id": pin_id,
        "dominant_color": "#AABBCC",
        "grid_title": "A title",
        "images": {
            "236x": {"url": "https://i.pinimg.com/236x/ab/cd/img.jpg", "width": 236, "height": 300},
            "orig": {"url": "https://i.pinimg.com/originals/ab/cd/img.jpg", "width": 1920, "height": 2440},
        },
        **extra,
    }


def test_pin_to_post_extracts_everything():
    post = parse.pin_to_post(_pin())
    assert post == {
        "urls": ["https://i.pinimg.com/originals/ab/cd/img.jpg"],
        "width": 1920,
        "height": 2440,
        "color": "#aabbcc",
        "bucket": "blue",
        "title": "A title",
        "pin_url": "https://www.pinterest.com/pin/41939840274795594/",
    }


def test_pin_to_post_carousel_and_filters():
    slide = {"images": {"736x": {"url": "https://i.pinimg.com/736x/ee/ff/slide.jpg"}}}
    post = parse.pin_to_post(_pin(carousel_data={"carousel_slots": [slide]}))
    assert post["urls"][1] == "https://i.pinimg.com/736x/ee/ff/slide.jpg"
    try:
        parse.set_content_filters(True, True)
        assert parse.pin_to_post(_pin(is_promoted=True)) is None
        assert parse.pin_to_post(_pin(is_ai_modified=True)) is None
        parse.set_content_filters(False, False)
        assert parse.pin_to_post(_pin(is_promoted=True)) is not None
    finally:
        parse.set_content_filters(True, False)
    assert parse.pin_to_post({"id": "1", "images": {}}) is None


# ─── feeds ───

def _post(i):
    return {"urls": [f"https://i.pinimg.com/736x/aa/bb/{i}.jpg"]}


class FakePages:
    """Serves numbered pages of `size` posts; bookmark = next page index."""

    def __init__(self, pages=3, size=10, dupes=False):
        self.pages, self.size, self.dupes = pages, size, dupes
        self.calls = 0
        self.lock = threading.Lock()

    def __call__(self, bookmark):
        with self.lock:
            self.calls += 1
        page = int(bookmark or 0)
        start = 0 if self.dupes else page * self.size
        posts = [_post(start + i) for i in range(self.size)]
        nxt = str(page + 1) if page + 1 < self.pages else None
        return posts, nxt


def test_feed_serves_offsets_and_reads_ahead():
    pages = FakePages(pages=3, size=10)
    feed = Feed(pages)
    first, more = feed.get(0, 10)
    assert [p["urls"][0] for p in first] == [_post(i)["urls"][0] for i in range(10)]
    assert more
    rest, more = feed.get(10, 100, min_count=100)
    assert len(rest) == 20 and not more
    again, _ = feed.get(0, 5)
    assert again == first[:5]
    assert pages.calls == 3


def test_feed_returns_after_first_page_by_default():
    feed = Feed(FakePages(pages=5, size=7))
    got, more = feed.get(0, 50)
    assert len(got) >= 7 and more


def test_feed_dedupes_and_stops_on_all_duplicate_pages():
    feed = Feed(FakePages(pages=10, size=5, dupes=True))
    got, _ = feed.get(0, 100, min_count=100)
    assert len(got) == 5
    assert feed.exhausted


def test_feed_error_propagates_then_retries():
    state = {"fail": True}

    def flaky(bookmark):
        if state["fail"]:
            raise RuntimeError("network down")
        return [_post(1)], None

    feed = Feed(flaky)
    with pytest.raises(RuntimeError):
        feed.get(0, 10)
    state["fail"] = False
    got, more = feed.get(0, 10)
    assert len(got) == 1 and not more


def test_feed_cache_lru_and_fresh():
    cache = FeedCache(size=2)
    a = cache.get(("a",), lambda: Feed(FakePages()))
    assert cache.get(("a",), lambda: Feed(FakePages())) is a
    assert cache.get(("a",), lambda: Feed(FakePages()), fresh=True) is not a
    cache.get(("b",), lambda: Feed(FakePages()))
    cache.get(("c",), lambda: Feed(FakePages()))
    assert cache.peek(("a",)) is None
