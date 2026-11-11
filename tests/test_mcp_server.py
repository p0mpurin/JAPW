import asyncio
import json
from unittest.mock import patch

import pytest

from japw import library as lib
from japw.images import pinimg_sized

IMG = "https://i.pinimg.com/originals/aa/bb/cc/one.png"
POST = {"urls": [IMG], "pin_url": "https://www.pinterest.com/pin/123/", "color": "#2244cc", "bucket": "blue",
        "width": 1200, "height": 1600, "title": "A blue thing"}


@pytest.fixture
def server(isolated_app_data, monkeypatch):
    monkeypatch.setenv("JAPW_DATA_DIR", str(isolated_app_data))
    import japw.mcp_server as m

    m._refs.clear()
    return m


def text(result) -> str:
    return result[0] if isinstance(result, list) else result


def test_sized_pinimg_urls_switch_to_jpg():
    assert pinimg_sized(IMG, "236x") == "https://i.pinimg.com/236x/aa/bb/cc/one.jpg"
    assert pinimg_sized("https://i.pinimg.com/736x/aa/b.jpg", "originals") == "https://i.pinimg.com/originals/aa/b.jpg"


def test_tools_are_registered(server):
    tools = asyncio.run(server.mcp.list_tools())
    names = {t.name for t in tools}
    for expected in ("search_pins", "search_by_image", "similar_pins", "view_pins", "download_pins",
                     "like_pins", "add_to_collection", "artist_media", "for_you_feed", "update_settings"):
        assert expected in names


def test_refs_are_stable_and_resolvable(server):
    ref = server._remember(POST)
    assert ref == server._remember(dict(POST)) and ref.startswith("p")
    assert server._resolve(ref)["pin_url"] == POST["pin_url"]
    assert server._resolve(IMG)["urls"] == [IMG]
    with pytest.raises(ValueError):
        server._resolve("nope")
    with pytest.raises(ValueError):
        server._resolve("https://evil.example/x.jpg")


def test_search_listing_has_numbered_pins(server):
    with patch("japw.pinterest.search", return_value=([POST], True)):
        out = server.search_pins("blue", count=5, preview=False)
    data = json.loads(text(out))
    assert data["has_more"] and data["next_offset"] == 1
    pin = data["pins"][0]
    assert pin["n"] == 1 and pin["color"] == "blue" and pin["size"] == "1200x1600" and pin["link"] == POST["pin_url"]


def test_contact_sheet_is_an_image(server):
    import io
    from PIL import Image as PILImage

    buf = io.BytesIO()
    PILImage.new("RGB", (40, 60), (30, 60, 200)).save(buf, "JPEG")
    with patch.object(server, "_fetch_image", return_value=buf.getvalue()):
        sheet = server._contact_sheet([POST, POST, POST])
    content = sheet.to_image_content()
    assert content.mime_type == "image/jpeg" and len(content.data) > 100


def test_library_tools_round_trip(server):
    ref = server._remember(POST)
    assert "Liked 1" in server.like_pins([ref])
    assert lib.is_liked(POST["urls"])
    assert "Added 1" in server.add_to_collection("Blues", [ref])
    assert "already" in server.add_to_collection("Blues", [ref])
    listed = json.loads(text(server.collection_pins("blues", preview=False)))
    assert listed["total"] == 1 and listed["pins"][0]["ref"] == ref
    assert "Not deleted" in server.delete_collection("Blues")
    assert "Deleted" in server.delete_collection("Blues", confirm=True)
    assert "Unliked 1" in server.unlike_pins([ref])
    assert not lib.is_liked(POST["urls"])


def test_download_tool_uses_subfolder_and_names(server, tmp_path):
    from unittest.mock import MagicMock

    server.update_settings(download_folder=str(tmp_path / "dl"))
    resp = MagicMock(content=b"\xff\xd8fake", headers={"Content-Type": "image/jpeg"})
    resp.raise_for_status = MagicMock()
    ref = server._remember(POST)
    with patch("japw.library.requests.get", return_value=resp):
        out = json.loads(server.download_pins([ref], subfolder="Blue: walls?", name="sky"))
    assert out["saved"] == 1 and not out["errors"]
    saved = out["files"][0]
    assert saved.endswith("sky.jpg") and "Blue walls" in saved


def test_update_settings_validates_folder(server):
    assert "absolute" in server.update_settings(download_folder="relative/path")
    assert "hide_ai" not in server.update_settings(hide_ai_content=True)
    assert json.loads(server.get_settings())["filter_ai_content"] is True
