import json
import os
import pytest
from unittest.mock import patch, MagicMock
from japw.api import create_app


@pytest.fixture
def client(tmp_path):
    config_path = str(tmp_path / "config.json")
    download_folder = str(tmp_path / "downloads")
    os.makedirs(download_folder, exist_ok=True)

    with open(config_path, "w") as f:
        json.dump({"download_folder": download_folder}, f)

    app = create_app(config_path=config_path)
    app.config["TESTING"] = True
    with app.test_client() as test_client:
        yield test_client, tmp_path, download_folder


def test_download_saves_file(client):
    test_client, tmp_path, download_folder = client
    fake_image = b"\x89PNG\r\n\x1a\nfakeimage"

    with patch("japw.api.requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.content = fake_image
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "image/png"}
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        response = test_client.post("/api/download", json={
            "url": "https://example.com/image.png"
        })

    assert response.status_code == 200
    data = response.get_json()
    assert data["success"] is True
    assert os.path.exists(data["path"])


def test_download_missing_url(client):
    test_client, _, _ = client
    response = test_client.post("/api/download", json={})
    assert response.status_code == 400


def test_get_settings(client):
    test_client, _, download_folder = client
    response = test_client.get("/api/settings")
    assert response.status_code == 200
    data = response.get_json()
    assert data["download_folder"] == download_folder


def test_update_settings(client):
    test_client, tmp_path, _ = client
    new_folder = str(tmp_path / "new_downloads")
    response = test_client.post("/api/settings", json={
        "download_folder": new_folder
    })
    assert response.status_code == 200

    response = test_client.get("/api/settings")
    data = response.get_json()
    assert data["download_folder"] == new_folder
