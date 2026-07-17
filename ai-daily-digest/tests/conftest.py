from copy import deepcopy

import pytest

from src.config import load_config


@pytest.fixture
def cfg(tmp_path):
    value = deepcopy(load_config())
    value["_root"] = str(tmp_path)
    return value
