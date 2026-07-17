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
