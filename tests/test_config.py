import json
import pytest
from japw.config import load_config, save_config, get_default_config


def test_get_default_config():
    config = get_default_config()
    assert "download_folder" in config
    assert config["download_folder"].endswith("JAPW")
    assert config.get("resolution_filter_enabled") is False
    assert config.get("resolution_target_width") == 1920
    assert config.get("resolution_target_height") == 1080
    assert config.get("resolution_match_mode") == "min"
    assert config.get("pinterest_boards_page_url") == ""
    assert config.get("search_use_pinscrape_when_logged_in") is False


def test_load_config_creates_default_when_missing(tmp_path):
    config_path = tmp_path / "config.json"
    config = load_config(str(config_path))
    assert config["download_folder"].endswith("JAPW")
    assert config_path.exists()


def test_save_and_load_config(tmp_path):
    config_path = tmp_path / "config.json"
    save_config(str(config_path), {"download_folder": "/custom/path"})
    config = load_config(str(config_path))
    assert config["download_folder"] == "/custom/path"
    assert "resolution_filter_enabled" in config


def test_load_config_handles_corrupt_json(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text("not json")
    config = load_config(str(config_path))
    assert "download_folder" in config
