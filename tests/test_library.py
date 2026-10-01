import os
from unittest.mock import MagicMock, patch

IMG = "https://i.pinimg.com/736x/aa/bb/one.jpg"


def fake_response(content=b"\x89PNG\r\n\x1a\nfake", content_type="image/png"):
    resp = MagicMock()
    resp.content = content
    resp.headers = {"Content-Type": content_type}
    resp.raise_for_status = MagicMock()
    return resp


def test_download_saves_file_and_indexes_key(client):
    with patch("japw.routes.library.requests.get", return_value=fake_response()):
        r = client.post("/api/download", json={"url": IMG, "key": "aa/bb/one"})
    d = r.get_json()
    assert d["success"] and os.path.exists(d["path"]) and d["path"].endswith(".png")
    assert client.get("/api/downloads").get_json()["keys"] == ["aa/bb/one"]


def test_download_never_overwrites(client):
    with patch("japw.routes.library.requests.get", return_value=fake_response()):
        p1 = client.post("/api/download", json={"url": IMG}).get_json()["path"]
        p2 = client.post("/api/download", json={"url": IMG}).get_json()["path"]
    assert p1 != p2 and os.path.exists(p1) and os.path.exists(p2)


def test_download_validation(client):
    assert client.post("/api/download", json={}).status_code == 400
    assert client.post("/api/download", json={"url": "http://127.0.0.1/x.png"}).status_code == 400


def test_reveal_only_opens_known_files(client):
    with patch("japw.routes.library._open_folder") as m:
        r = client.post("/api/reveal", json={"path": "C:/Windows/System32/cmd.exe"})
    # Unknown path → falls back to opening the download folder itself.
    assert r.status_code == 200
    m.assert_called_once()
    assert m.call_args.kwargs.get("select", False) is False


def test_like_toggle_stores_color(client):
    r = client.post("/api/likes/toggle", json={"urls": [IMG], "color": "#ABCDEF"})
    assert r.get_json() == {"liked": True, "key": "aa/bb/one"}
    posts = client.get("/api/likes").get_json()["posts"]
    assert posts[0]["color"] == "#abcdef" and posts[0]["key"] == "aa/bb/one"
    assert client.post("/api/likes/toggle", json={"urls": [IMG]}).get_json()["liked"] is False
    assert client.get("/api/likes").get_json()["posts"] == []


def test_collections_crud(client):
    col = client.post("/api/collections", json={"name": "Walls"}).get_json()["collection"]
    cid = col["id"]
    client.post(f"/api/collections/{cid}/posts", json={"urls": [IMG], "color": "#000000"})
    client.post(f"/api/collections/{cid}/posts", json={"urls": [IMG]})  # duplicate ignored
    listing = client.get("/api/collections").get_json()["collections"]
    assert listing == [{"id": cid, "name": "Walls", "count": 1, "cover": IMG}]
    assert client.patch(f"/api/collections/{cid}", json={"name": "Wallpapers"}).status_code == 200
    posts = client.get(f"/api/collections/{cid}/posts").get_json()
    assert posts["name"] == "Wallpapers" and posts["posts"][0]["color"] == "#000000"
    client.delete(f"/api/collections/{cid}/posts", json={"key": "aa/bb/one"})
    assert client.get(f"/api/collections/{cid}/posts").get_json()["posts"] == []
    assert client.delete(f"/api/collections/{cid}").status_code == 200
    assert client.delete(f"/api/collections/{cid}").status_code == 404


def test_export_import_round_trip(client):
    client.post("/api/likes/toggle", json={"urls": [IMG]})
    bundle = client.get("/api/export").get_json()
    assert bundle["version"] == 1 and bundle["likes"]["posts"]
    client.post("/api/likes/toggle", json={"urls": [IMG]})
    assert client.post("/api/import", json=bundle).get_json() == {"success": True}
    assert client.get("/api/likes").get_json()["posts"]
    assert client.post("/api/import", json={"version": 9}).status_code == 400


def test_settings_round_trip(client, tmp_path):
    folder = str(tmp_path / "new")
    client.post("/api/settings", json={"download_folder": folder, "resolution_target_width": 99999,
                                       "resolution_match_mode": "exact", "filter_ai_content": True})
    s = client.get("/api/settings").get_json()
    assert s["download_folder"] == folder
    assert s["resolution_target_width"] == 1920  # out of range → unchanged
    assert s["resolution_match_mode"] == "exact" and s["filter_ai_content"] is True


def test_image_proxy_rejects_other_hosts(client):
    assert client.get("/api/image.png?url=http://localhost/secret").status_code == 400


def test_image_proxy_converts_to_png(client):
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (255, 0, 0)).save(buf, "JPEG")
    with patch("japw.media._http.get", return_value=fake_response(buf.getvalue(), "image/jpeg")):
        r = client.get(f"/api/image.png?url={IMG}")
    assert r.status_code == 200 and r.data.startswith(b"\x89PNG")


def test_colors_measures_and_caches(client):
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (24, 24), (200, 30, 30)).save(buf, "PNG")
    with patch("japw.media._http.get", return_value=fake_response(buf.getvalue())) as m:
        first = client.post("/api/colors", json={"urls": [IMG]}).get_json()["colors"]
        second = client.post("/api/colors", json={"urls": [IMG]}).get_json()["colors"]
    assert first == second
    r, g, b = (int(first[IMG][i:i + 2], 16) for i in (1, 3, 5))
    assert r > 150 and g < 80 and b < 80
    assert m.call_count == 1
