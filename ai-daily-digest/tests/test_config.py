from copy import deepcopy

import pytest

from src.config import load_config, validate_config


def test_config_rejects_output_outside_project():
    cfg = deepcopy(load_config())
    cfg.pop("_root", None)
    cfg["output_dir"] = "../outside"
    with pytest.raises(ValueError, match="output_dir"):
        validate_config(cfg)


def test_config_rejects_unknown_feed_section():
    cfg = deepcopy(load_config())
    cfg.pop("_root", None)
    cfg["sources"]["rss"]["feeds"][0]["section"] = "missing"
    with pytest.raises(ValueError, match="不存在的板块"):
        validate_config(cfg)


def test_config_rejects_invalid_cache_retention():
    cfg = deepcopy(load_config())
    cfg.pop("_root", None)
    cfg["llm"]["cache_retention_days"] = 0
    with pytest.raises(ValueError, match="cache_retention_days"):
        validate_config(cfg)


def test_config_rejects_unknown_last30days_source():
    cfg = deepcopy(load_config())
    cfg.pop("_root", None)
    cfg["sources"]["last30days"]["english"]["sources"] = ["reddit", "unknown"]
    with pytest.raises(ValueError, match="不支持的来源"):
        validate_config(cfg)


def test_config_rejects_unknown_official_page_parser():
    cfg = deepcopy(load_config())
    cfg.pop("_root", None)
    cfg["sources"]["official_updates"]["sites"][0]["parser"] = "unknown"
    with pytest.raises(ValueError, match="parser"):
        validate_config(cfg)
