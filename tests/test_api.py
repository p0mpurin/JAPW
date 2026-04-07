import time
from unittest.mock import patch

import pytest
import japw.pinterest as pinterest_session
from japw.api import create_app
from japw.config import get_default_config


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_search_returns_json(client):
    response = client.get("/api/search?q=anime+pfp")
    assert response.status_code == 200
    data = response.get_json()
    assert "posts" in data
    assert isinstance(data["posts"], list)
    if data["posts"]:
        assert isinstance(data["posts"][0].get("urls"), list)
    assert data.get("source") == "pinscrape"


def test_search_missing_query(client):
    response = client.get("/api/search")
    assert response.status_code == 400
    data = response.get_json()
    assert "error" in data


def test_search_uses_session_when_logged_in_by_default(client, monkeypatch):
    import japw.api as api

    cfg = dict(get_default_config())
    monkeypatch.setattr(api, "load_config", lambda _p=None: dict(cfg))
    with patch("japw.pinterest.has_session", return_value=True), patch(
        "japw.pinterest.fetch_search_image_urls",
        return_value=[{"urls": ["https://i.pinimg.com/s.jpg"]}],
    ) as m_fetch:
        r = client.get("/api/search?q=kittens")
    assert r.status_code == 200
    d = r.get_json()
    assert d["source"] == "session"
    assert d["posts"] == [{"urls": ["https://i.pinimg.com/s.jpg"]}]
    m_fetch.assert_called_once_with("kittens")


def test_search_uses_pinscrape_when_logged_in_if_setting_on(client, monkeypatch):
    import japw.api as api

    cfg = dict(get_default_config())
    cfg["search_use_pinscrape_when_logged_in"] = True
    monkeypatch.setattr(api, "load_config", lambda _p=None: dict(cfg))
    with patch("japw.pinterest.has_session", return_value=True), patch(
        "japw.pinterest.fetch_search_image_urls",
    ) as m_session, patch("japw.api.Pinterest") as MockPin:
        MockPin.return_value.search.return_value = ["https://i.pinimg.com/p.jpg"]
        r = client.get("/api/search?q=cats")
    assert r.status_code == 200
    d = r.get_json()
    assert d["source"] == "pinscrape"
    m_session.assert_not_called()
    MockPin.return_value.search.assert_called_once()


def test_home_requires_login(client):
    response = client.get("/api/home")
    assert response.status_code == 401
    data = response.get_json()
    assert "error" in data


def test_home_refresh_calls_force_refresh(client):
    with patch("japw.pinterest.has_session", return_value=True), patch(
        "japw.pinterest.fetch_home_image_urls",
        return_value=[{"urls": ["https://i.pinimg.com/a.jpg"]}],
    ) as mock_fetch:
        response = client.get("/api/home?refresh=1")
    assert response.status_code == 200
    data = response.get_json()
    assert data["posts"] == [{"urls": ["https://i.pinimg.com/a.jpg"]}]
    mock_fetch.assert_called_once_with(force_refresh=True)


def test_home_more_requires_login(client):
    response = client.post("/api/home/more", json={"seen_urls": []})
    assert response.status_code == 401


def test_search_more_requires_login(client):
    response = client.post("/api/search/more", json={"q": "cats", "seen_urls": []})
    assert response.status_code == 401


def test_boards_requires_login(client):
    response = client.get("/api/boards")
    assert response.status_code == 401


def test_boards_missing_listing_url(client, monkeypatch):
    import japw.api as api

    cfg = dict(get_default_config())
    cfg["pinterest_boards_page_url"] = ""
    monkeypatch.setattr(api, "load_config", lambda _p=None: dict(cfg))
    with patch("japw.pinterest.has_session", return_value=True):
        response = client.get("/api/boards")
    assert response.status_code == 400
    assert response.get_json().get("code") == "missing_boards_page_url"


def test_boards_invalid_listing_url_in_config(client, monkeypatch):
    import japw.api as api

    cfg = dict(get_default_config())
    cfg["pinterest_boards_page_url"] = "https://it.pinterest.com/user/wallpapers/"
    monkeypatch.setattr(api, "load_config", lambda _p=None: dict(cfg))
    with patch("japw.pinterest.has_session", return_value=True):
        response = client.get("/api/boards")
    assert response.status_code == 400
    assert response.get_json().get("code") == "invalid_boards_page_url"


def test_boards_ok_with_listing_url(client, monkeypatch):
    import japw.api as api

    cfg = dict(get_default_config())
    cfg["pinterest_boards_page_url"] = "https://it.pinterest.com/someuser/"
    monkeypatch.setattr(api, "load_config", lambda _p=None: dict(cfg))
    with patch("japw.pinterest.has_session", return_value=True), patch(
        "japw.pinterest.fetch_my_boards_list",
        return_value=[{"title": "B", "url": "https://it.pinterest.com/someuser/b/"}],
    ):
        response = client.get("/api/boards")
    assert response.status_code == 200
    data = response.get_json()
    assert data["boards"][0]["title"] == "B"


def test_settings_rejects_single_board_as_listing_url(client, monkeypatch):
    import japw.api as api

    store = {"c": dict(get_default_config())}

    def load_cfg(path=None):
        return dict(store["c"])

    def save_cfg(path, config):
        store["c"] = dict(config)

    monkeypatch.setattr(api, "load_config", load_cfg)
    monkeypatch.setattr(api, "save_config", save_cfg)
    bad = "https://it.pinterest.com/po13u3xh89/character-art/"
    r = client.post("/api/settings", json={"pinterest_boards_page_url": bad})
    assert r.status_code == 400
    assert "error" in r.get_json()


def test_settings_saves_profile_board_listing_url(client, monkeypatch):
    import japw.api as api

    store = {"c": dict(get_default_config())}

    def load_cfg(path=None):
        return dict(store["c"])

    def save_cfg(path, config):
        store["c"] = dict(config)

    monkeypatch.setattr(api, "load_config", load_cfg)
    monkeypatch.setattr(api, "save_config", save_cfg)
    good = "https://it.pinterest.com/po13u3xh89"
    r = client.post("/api/settings", json={"pinterest_boards_page_url": good})
    assert r.status_code == 200
    assert store["c"]["pinterest_boards_page_url"] == "https://it.pinterest.com/po13u3xh89/"


def test_board_listing_vs_board_url_validation():
    assert pinterest_session.is_valid_boards_listing_page_url("https://it.pinterest.com/po13u3xh89/")
    assert not pinterest_session.is_valid_boards_listing_page_url(
        "https://it.pinterest.com/po13u3xh89/character-art/"
    )
    assert pinterest_session.is_valid_user_board_url("https://it.pinterest.com/po13u3xh89/character-art/")


def test_board_pins_requires_login(client):
    response = client.get("/api/board_pins?url=https://www.pinterest.com/someuser/someboard/")
    assert response.status_code == 401


def test_board_pins_missing_url(client):
    with patch("japw.pinterest.has_session", return_value=True):
        response = client.get("/api/board_pins")
    assert response.status_code == 400


def test_board_pins_invalid_url(client):
    with patch("japw.pinterest.has_session", return_value=True):
        response = client.get("/api/board_pins?url=https://example.com/not-pinterest")
    assert response.status_code == 400


def test_board_pins_more_requires_login(client):
    response = client.post(
        "/api/board_pins/more",
        json={"board_url": "https://www.pinterest.com/u/b/", "seen_urls": []},
    )
    assert response.status_code == 401


def test_board_pins_more_ok(client):
    with patch("japw.pinterest.has_session", return_value=True), patch(
        "japw.pinterest.canonical_keys_from_urls", return_value=set()
    ), patch(
        "japw.pinterest.fetch_board_pins_more",
        return_value=[{"urls": ["https://i.pinimg.com/b.jpg"]}],
    ):
        response = client.post(
            "/api/board_pins/more",
            json={
                "board_url": "https://www.pinterest.com/user/myboard/",
                "seen_urls": ["https://i.pinimg.com/x.jpg"],
            },
        )
    assert response.status_code == 200
    data = response.get_json()
    assert data["posts"] == [{"urls": ["https://i.pinimg.com/b.jpg"]}]
    assert data["has_more"] is True


def test_home_more_ok(client):
    with patch("japw.pinterest.has_session", return_value=True), patch(
        "japw.pinterest.canonical_keys_from_urls", return_value=set()
    ), patch(
        "japw.pinterest.fetch_home_more_image_urls",
        return_value=[{"urls": ["https://i.pinimg.com/a.jpg"]}],
    ):
        response = client.post("/api/home/more", json={"seen_urls": ["https://i.pinimg.com/x.jpg"]})
    assert response.status_code == 200
    data = response.get_json()
    assert data["posts"] == [{"urls": ["https://i.pinimg.com/a.jpg"]}]
    assert data["has_more"] is True


def test_search_more_ok(client):
    with patch("japw.pinterest.has_session", return_value=True), patch(
        "japw.pinterest.canonical_keys_from_urls", return_value=set()
    ), patch("japw.pinterest.fetch_search_more_image_urls", return_value=[]):
        response = client.post("/api/search/more", json={"q": "cats", "seen_urls": []})
    assert response.status_code == 200
    data = response.get_json()
    assert data["posts"] == []
    assert data["has_more"] is False


def test_auth_status(client):
    response = client.get("/api/auth/status")
    assert response.status_code == 200
    data = response.get_json()
    assert data["connected"] is False
    assert data["login_in_progress"] is False
    assert "last_error" in data


def test_auth_login_starts(client):
    with patch("japw.pinterest.sync_session_from_installed_browsers"):
        response = client.post("/api/auth/login")
        time.sleep(0.2)
    assert response.status_code == 200
    assert response.get_json().get("started") is True


def test_auth_sync_failure_records_error(client, tmp_path, monkeypatch):
    monkeypatch.setattr(pinterest_session, "get_app_data_dir", lambda: tmp_path)

    def boom():
        raise pinterest_session.PinterestSessionError("no cookies")

    with patch("japw.pinterest.sync_session_from_installed_browsers", side_effect=boom):
        response = client.post("/api/auth/login")
        time.sleep(0.2)
    assert response.status_code == 200
    st = client.get("/api/auth/status").get_json()
    assert st.get("last_error") == "no cookies"
    assert st.get("connected") is False


@patch("japw.api.webbrowser.open")
def test_auth_open_browser(mock_open, client):
    response = client.post("/api/auth/open-browser")
    assert response.status_code == 200
    assert response.get_json().get("opened") is True
    mock_open.assert_called_once()


def test_auth_logout(client):
    response = client.post("/api/auth/logout")
    assert response.status_code == 200
    assert response.get_json().get("success") is True


def test_exclude_pins_seen_on_home():
    import japw.pinterest as ps

    try:
        ps.record_home_pins_for_search_filter(
            ["https://i.pinimg.com/736x/ab/cd/same.jpg"]
        )
        mixed = [
            "https://i.pinimg.com/236x/ab/cd/same.jpg",
            "https://i.pinimg.com/474x/xx/yy/other.jpg",
        ]
        out = ps.exclude_pins_seen_on_home(mixed)
        assert len(out) == 1
        assert "other" in out[0]
    finally:
        ps.record_home_pins_for_search_filter([])


def test_exclude_posts_seen_on_home():
    import japw.pinterest as ps

    try:
        ps.record_home_pins_for_search_filter(
            ["https://i.pinimg.com/736x/ab/cd/same.jpg"]
        )
        posts = [
            {
                "urls": [
                    "https://i.pinimg.com/236x/ab/cd/same.jpg",
                    "https://i.pinimg.com/474x/xx/yy/other.jpg",
                ]
            },
        ]
        out = ps.exclude_posts_seen_on_home(posts)
        assert len(out) == 1
        assert len(out[0]["urls"]) == 1
        assert "other" in out[0]["urls"][0]
    finally:
        ps.record_home_pins_for_search_filter([])


def test_is_promoted_pin_detects_api_and_module_markers():
    assert pinterest_session._is_promoted_pin({"is_promoted": True})
    assert pinterest_session._is_promoted_pin({"isPromoted": "true"})
    assert pinterest_session._is_promoted_pin({"promoted_is_removable": True})
    assert pinterest_session._is_promoted_pin({"ad_match_reason": "x"})
    assert pinterest_session._is_promoted_pin({"promoter": {"id": "1"}})
    assert pinterest_session._is_promoted_pin({"promotion_id": "p"})
    assert pinterest_session._is_promoted_pin({"__typename": "PromotedPin"})
    assert pinterest_session._is_promoted_pin({"module_type": "SHOPPING_AD_ROW"})
    assert pinterest_session._is_promoted_pin({"promoted_by": "Some Brand"})
    assert pinterest_session._is_promoted_pin({"promoted_by_advertiser": "Acme"})
    assert pinterest_session._is_promoted_pin({"promotedBy": "X Corp"})
    assert pinterest_session._is_promoted_pin({"ad_data": {"tracking_id": "abc"}})
    assert pinterest_session._is_promoted_pin({"native_ad_data": {"creative": "x"}})
    assert pinterest_session._is_promoted_pin({"campaign_id": "camp123"})
    assert pinterest_session._is_promoted_pin({"ad_destination_url": "https://example.com"})
    assert not pinterest_session._is_promoted_pin({"ad_data": {}})
    assert not pinterest_session._is_promoted_pin({"title": "Organic", "id": "42"})
    # Real homefeed shape: organic pins still carry ad_match_reason: 0
    assert not pinterest_session._is_promoted_pin(
        {
            "id": "41939840274795594",
            "type": "pin",
            "is_promoted": False,
            "promoted_is_removable": False,
            "ad_match_reason": 0,
        }
    )
    assert pinterest_session._is_promoted_pin(
        {
            "id": "AWdwvvpZ2dyJ35SnGsx_RRHbbykLmdvS9mP2N-a_eFa1Srwpdg3Kr0hrk1mr1NPYMXfz4QOgqcENC7Is5hRTOsA",
            "type": "pin",
            "is_promoted": True,
            "promoted_is_removable": True,
            "ad_match_reason": 0,
        }
    )


def test_api_pin_to_post_drops_promoted_when_filter_on():
    ps = pinterest_session
    img = "https://i.pinimg.com/736x/ab/cd/ef/promo.jpg"
    promoted = {
        "id": "AWtestpromo",
        "type": "pin",
        "is_promoted": True,
        "promoted_is_removable": True,
        "images": {"736x": {"url": img}},
    }
    organic = {
        "id": "41939840274795594",
        "type": "pin",
        "is_promoted": False,
        "promoted_is_removable": False,
        "ad_match_reason": 0,
        "images": {"736x": {"url": "https://i.pinimg.com/736x/ab/cd/ef/ok.jpg"}},
    }
    prev_p, prev_a = ps._filter_promoted, ps._filter_ai_content
    try:
        ps.set_content_filters(True, False)
        assert ps._api_pin_to_post(promoted) is None
        out = ps._api_pin_to_post(organic)
        assert out is not None
        assert img not in (out.get("urls") or [])
    finally:
        ps.set_content_filters(prev_p, prev_a)


def test_dedupe_pinimg_urls_keeps_best_resolution():
    from pinterest_session import dedupe_pinimg_urls

    small = "https://i.pinimg.com/236x/ab/cd/abcdef.jpg"
    large = "https://i.pinimg.com/736x/ab/cd/abcdef.jpg"
    assert dedupe_pinimg_urls([small, large]) == [large]
    assert dedupe_pinimg_urls([large, small]) == [large]


def test_expand_carousel_map_all_keys_maps_every_slide():
    import japw.pinterest as ps

    a = "https://i.pinimg.com/736x/0c/b9/31/0cb9313d292511fc67b987142a158e32.jpg"
    b = "https://i.pinimg.com/736x/a6/7b/d1/a67bd179e561f79cfd9d6cd1991182a8.jpg"
    cmap = {ps._pinimg_canonical_key(a): [a, b]}
    out = ps._expand_carousel_map_all_keys(cmap)
    assert ps._pinimg_canonical_key(a) in out
    assert ps._pinimg_canonical_key(b) in out
    assert out[ps._pinimg_canonical_key(a)] == [a, b]
    assert out[ps._pinimg_canonical_key(b)] == [a, b]


def test_merge_posts_same_pin_groups_by_pin_url():
    import japw.pinterest as ps

    pin = "https://www.pinterest.com/pin/999/"
    posts = [
        {"urls": ["https://i.pinimg.com/736x/aa/bb/one.jpg"], "pin_url": pin},
        {"urls": ["https://i.pinimg.com/736x/cc/dd/two.jpg"], "pin_url": pin},
    ]
    out = ps.merge_posts_same_pin(posts)
    assert len(out) == 1
    assert len(out[0]["urls"]) == 2
    assert out[0]["pin_url"] == "https://www.pinterest.com/pin/999/"
    other = [
        {"urls": ["https://i.pinimg.com/736x/ee/ff/three.jpg"], "pin_url": "https://it.pinterest.com/pin/1000/"},
    ]
    out2 = ps.merge_posts_same_pin(posts + other)
    assert len(out2) == 2


def test_search_uses_session_when_connected(client, monkeypatch):
    import japw.api as api

    cfg = dict(get_default_config())
    monkeypatch.setattr(api, "load_config", lambda _p=None: dict(cfg))
    fake_posts = [{"urls": ["https://i.pinimg.com/a.jpg"]}]
    with patch("japw.pinterest.has_session", return_value=True), patch(
        "japw.pinterest.fetch_search_image_urls", return_value=fake_posts
    ):
        response = client.get("/api/search?q=cats")
    assert response.status_code == 200
    data = response.get_json()
    assert data["posts"] == fake_posts
    assert data["source"] == "session"


def test_fetch_search_image_urls_filters_posts_seen_on_home():
    import japw.pinterest as ps

    raw_posts = [
        {"urls": ["https://i.pinimg.com/736x/aa/bb/one.jpg"]},
        {"urls": ["https://i.pinimg.com/736x/cc/dd/two.jpg"]},
    ]
    filtered_posts = [raw_posts[1]]

    with patch("japw.pinterest.has_session", return_value=True), patch(
        "japw.pinterest._parallel_scrape", return_value=raw_posts
    ), patch(
        "japw.pinterest.exclude_posts_seen_on_home", return_value=filtered_posts
    ) as mock_exclude, patch(
        "japw.pinterest._search_buf_start_fill"
    ):
        out = ps.fetch_search_image_urls("cats")

    assert out == filtered_posts
    mock_exclude.assert_called_once_with(raw_posts)


def test_fetch_search_more_image_urls_filters_buffered_posts_seen_on_home():
    import japw.pinterest as ps

    raw_posts = [
        {"urls": ["https://i.pinimg.com/736x/aa/bb/one.jpg"]},
        {"urls": ["https://i.pinimg.com/736x/cc/dd/two.jpg"]},
    ]
    filtered_posts = [raw_posts[1]]

    with patch("japw.pinterest.has_session", return_value=True), patch(
        "japw.pinterest._search_buf_pop", return_value=raw_posts
    ), patch(
        "japw.pinterest.exclude_posts_seen_on_home", return_value=filtered_posts
    ) as mock_exclude, patch(
        "japw.pinterest._search_buf_start_fill"
    ):
        out = ps.fetch_search_more_image_urls("cats", frozenset())

    assert out == filtered_posts
    mock_exclude.assert_called_once_with(raw_posts)


def test_pin_resolve_requires_session(client):
    response = client.post(
        "/api/pin/resolve",
        json={"cover_url": "https://i.pinimg.com/736x/a/b/c.jpg"},
    )
    assert response.status_code == 401


def test_pin_resolve_missing_cover(client):
    with patch("japw.pinterest.has_session", return_value=True):
        response = client.post("/api/pin/resolve", json={})
    assert response.status_code == 400


def test_pin_resolve_returns_pin_url(client):
    with patch("japw.pinterest.has_session", return_value=True), patch(
        "japw.pinterest.resolve_pin_url_for_cover_image",
        return_value="https://www.pinterest.com/pin/123/",
    ):
        response = client.post(
            "/api/pin/resolve",
            json={"cover_url": "https://i.pinimg.com/736x/x/y/z.jpg"},
        )
    assert response.status_code == 200
    assert response.get_json()["pin_url"] == "https://www.pinterest.com/pin/123/"


def test_pin_related_requires_session(client):
    response = client.post(
        "/api/pin/related", json={"pin_url": "https://www.pinterest.com/pin/123456789/"}
    )
    assert response.status_code == 401


def test_pin_related_rejects_invalid_url(client):
    with patch("japw.pinterest.has_session", return_value=True):
        response = client.post("/api/pin/related", json={"pin_url": "https://example.com/not-a-pin"})
    assert response.status_code == 400


def test_pin_related_missing_pin_url(client):
    with patch("japw.pinterest.has_session", return_value=True):
        response = client.post("/api/pin/related", json={})
    assert response.status_code == 400


def test_pin_related_returns_posts_when_connected(client):
    fake_posts = [
        {
            "urls": ["https://i.pinimg.com/736x/aa/bb/rel.jpg"],
            "pin_url": "https://www.pinterest.com/pin/999/",
        }
    ]
    with patch("japw.pinterest.has_session", return_value=True), patch(
        "japw.pinterest.fetch_pin_related_posts", return_value=fake_posts
    ) as mock_fetch:
        response = client.post(
            "/api/pin/related",
            json={
                "pin_url": "https://www.pinterest.com/pin/1/",
                "exclude_urls": ["https://i.pinimg.com/236x/xx/yy/here.jpg"],
            },
        )
    assert response.status_code == 200
    assert response.get_json()["posts"] == fake_posts
    mock_fetch.assert_called_once()
    args, kwargs = mock_fetch.call_args
    assert args[0] == "https://www.pinterest.com/pin/1/"
    assert args[1] == ["https://i.pinimg.com/236x/xx/yy/here.jpg"]
