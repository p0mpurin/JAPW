import json

import pytest

from japw.api import create_app


@pytest.fixture(autouse=True)
def isolated_app_data(tmp_path, monkeypatch):
    """Keep session files, caches and downloads out of the repo during tests."""
    base = tmp_path / "JAPW_data"
    base.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("japw.pinterest.session.get_app_data_dir", lambda: base)
    monkeypatch.setattr("japw.media.get_app_data_dir", lambda: base)
    monkeypatch.setattr("japw.config.get_app_data_dir", lambda: base)
    monkeypatch.setattr("japw.taste.get_app_data_dir", lambda: base)
    monkeypatch.setattr("japw.x.get_app_data_dir", lambda: base)
    monkeypatch.setattr("japw.taste._events", None)
    return base


@pytest.fixture
def config_path(tmp_path):
    path = tmp_path / "config.json"
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    path.write_text(json.dumps({"download_folder": str(downloads)}), encoding="utf-8")
    return str(path)


@pytest.fixture
def client(config_path):
    app = create_app(config_path=config_path, warm_up=False)
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c
