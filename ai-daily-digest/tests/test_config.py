from copy import deepcopy

import pytest

from src.config import load_config, validate_config


@pytest.mark.parametrize("path,value", [
    (("must_read", "min_quality_score"), 101),
    (("must_read", "min_source_chars"), 0),
    (("quality", "min_source_chars", "community"), False),
    (("quality", "min_source_chars", "unknown"), 80),
    (("sources", "github", "content_fetch_limit"), 0),
    (("sources", "github", "content_workers"), 100),
    (("sources", "github", "content_timeout_seconds"), -1),
])
def test_config_rejects_invalid_editorial_and_enrichment_limits(path, value):
    cfg = deepcopy(load_config())
    target = cfg
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValueError):
        validate_config(cfg)


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


def test_config_accepts_legacy_flat_quality_thresholds():
    cfg = deepcopy(load_config())
    cfg.pop("_root", None)
    cfg["quality"]["min_score"] = {
        "default": 24,
        "github": 30,
        "community": 22,
    }

    validate_config(cfg)


def test_config_rejects_invalid_cross_source_similarity():
    cfg = deepcopy(load_config())
    cfg.pop("_root", None)
    cfg["dedup"]["cross_source"]["similarity"] = 1.1

    with pytest.raises(ValueError, match="similarity"):
        validate_config(cfg)
