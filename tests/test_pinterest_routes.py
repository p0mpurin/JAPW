from unittest.mock import patch

import japw.pinterest as ps

POSTS = [{"urls": ["https://i.pinimg.com/736x/aa/bb/one.jpg"], "color": "#112233"}]


def connected():
    return patch("japw.pinterest.has_session", return_value=True)


def test_home_requires_login(client):
    r = client.get("/api/home")
    assert r.status_code == 401


def test_home_returns_page_with_offsets(client):
    with connected(), patch("japw.pinterest.home", return_value=(POSTS, True)) as m:
        r = client.get("/api/home?offset=10&limit=20&refresh=1")
    assert r.status_code == 200
    d = r.get_json()
    assert d["posts"] == POSTS
    assert d["next_offset"] == 11
    assert d["has_more"] is True
    m.assert_called_once_with(10, 20, refresh=True, color=None)


def test_session_expired_maps_to_401_with_code(client):
    with connected(), patch("japw.pinterest.home", side_effect=ps.PinterestAuthExpired()):
        r = client.get("/api/home")
    assert r.status_code == 401
    assert r.get_json()["code"] == "session_expired"


def test_other_pinterest_errors_are_502(client):
    with connected(), patch("japw.pinterest.home", side_effect=ps.PinterestSessionError("boom")):
        r = client.get("/api/home")
    assert r.status_code == 502
    assert "code" not in r.get_json()


def test_search_missing_query(client):
    assert client.get("/api/search").status_code == 400


def test_search_uses_session_when_connected(client):
    with connected(), patch("japw.pinterest.search", return_value=(POSTS, True)) as m:
        r = client.get("/api/search?q=kittens&offset=50")
    d = r.get_json()
    assert d["source"] == "session"
    assert d["next_offset"] == 51
    m.assert_called_once_with("kittens", 50, 50, color=None)


def test_search_falls_back_to_pinscrape_when_logged_out(client):
    with patch("japw.routes.pinterest.Pinterest") as MockPin:
        MockPin.return_value.search.return_value = [
            "https://i.pinimg.com/236x/ab/cd/x.jpg",
            "https://i.pinimg.com/736x/ab/cd/x.jpg",
        ]
        r = client.get("/api/search?q=cats")
    d = r.get_json()
    assert d["source"] == "pinscrape"
    assert d["has_more"] is False
    assert d["posts"] == [{"urls": ["https://i.pinimg.com/736x/ab/cd/x.jpg"]}]


def test_search_uses_pinscrape_when_setting_on(client):
    client.post("/api/settings", json={"search_use_pinscrape_when_logged_in": True})
    with connected(), patch("japw.pinterest.search") as m_session, patch("japw.routes.pinterest.Pinterest") as MockPin:
        MockPin.return_value.search.return_value = ["https://i.pinimg.com/736x/p.jpg"]
        r = client.get("/api/search?q=cats")
    assert r.get_json()["source"] == "pinscrape"
    m_session.assert_not_called()


def test_search_prefetch_starts_background_fetch(client):
    with patch("japw.pinterest.prefetch_search") as m:
        r = client.post("/api/search/prefetch", json={"q": "sunset"})
        assert r.status_code == 200
        import time
        for _ in range(50):
            if m.called:
                break
            time.sleep(0.01)
    m.assert_called_once_with("sunset")


def test_suggest_never_errors(client):
    with patch("japw.pinterest.suggestions", side_effect=RuntimeError("x")):
        r = client.get("/api/search/suggest?q=ca")
    assert r.get_json() == {"suggestions": []}


def test_related_validates_and_excludes_open_pin_images(client):
    with connected():
        assert client.post("/api/pin/related", json={}).status_code == 400
        assert client.post("/api/pin/related", json={"pin_url": "https://example.com/pin/1/"}).status_code == 400
        other = {"urls": ["https://i.pinimg.com/736x/cc/dd/two.jpg"]}
        with patch("japw.pinterest.related", return_value=POSTS + [other]) as m:
            r = client.post("/api/pin/related", json={
                "pin_url": "https://www.pinterest.com/pin/123/",
                "exclude_urls": ["https://i.pinimg.com/originals/aa/bb/one.png"],
            })
    assert r.get_json()["posts"] == [other]
    m.assert_called_once_with("123")


def test_boards_and_board_pins(client):
    boards = [{"id": "9", "name": "Art", "url": "/me/art/", "count": 3, "cover": "", "secret": False}]
    with connected(), patch("japw.pinterest.my_boards", return_value=boards):
        assert client.get("/api/boards").get_json()["boards"] == boards
    with connected(), patch("japw.pinterest.board_pins", return_value=(POSTS, False)) as m:
        d = client.get("/api/boards/9/pins?url=/me/art/").get_json()
    assert d["posts"] == POSTS and d["has_more"] is False
    m.assert_called_once_with("9", "/me/art/", 0, 50)
    with connected():
        assert client.get("/api/boards/abc/pins").status_code == 400


def test_auth_endpoints(client):
    d = client.get("/api/auth/status").get_json()
    assert d == {"connected": False, "login_in_progress": False, "last_error": None}
    with patch("japw.pinterest.run_cookie_sync_thread_entry"):
        assert client.post("/api/auth/login").get_json() == {"started": True}
    ps.session.finish_sync()
    with patch("japw.routes.pinterest.webbrowser.open") as m:
        client.post("/api/auth/open-browser")
    m.assert_called_once()
    assert client.post("/api/auth/logout").get_json() == {"success": True}


def test_auth_sync_failure_records_error(monkeypatch):
    def boom():
        raise ps.PinterestSessionError("No Pinterest cookies found.")

    monkeypatch.setattr("japw.pinterest.session.sync_session_from_installed_browsers", boom)
    assert ps.try_begin_sync()
    ps.run_cookie_sync_thread_entry()
    assert "No Pinterest cookies" in ps.get_last_login_error()
    assert not ps.is_login_in_progress()
