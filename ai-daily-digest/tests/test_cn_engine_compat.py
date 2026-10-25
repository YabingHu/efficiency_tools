import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.collectors import cn_engine_compat as compat
from src.collectors.last30days_sources import _platform_errors, _run_engine


def modules():
    return (
        SimpleNamespace(_UA="test", _parse_mblog=lambda row: row),
        SimpleNamespace(_UA="test", _parse_article=lambda row: row,
                        _fetch_html=lambda *_args, **_kwargs: "<html>搜索首页</html>"),
        SimpleNamespace(_fetch_html=lambda *_args, **_kwargs: "<html>搜索首页</html>"),
    )


def test_toutiao_null_is_diagnosed_without_iteration_error(monkeypatch, capsys):
    weibo, toutiao, zhihu = modules()
    monkeypatch.setattr(compat, "_json_get", lambda *_: {"message": "success", "data": None})
    compat.install(weibo, toutiao, zhihu)
    assert toutiao._search_content("AI", 10) == []
    errors = _platform_errors(capsys.readouterr().err)
    assert errors == {"toutiao": ["empty_data"]}


def test_valid_empty_and_populated_toutiao_data_remain_distinct(monkeypatch, capsys):
    weibo, toutiao, zhihu = modules()
    compat.install(weibo, toutiao, zhihu)
    monkeypatch.setattr(compat, "_json_get", lambda *_: {"data": []})
    assert toutiao._search_content("AI", 10) == []
    assert capsys.readouterr().err == ""
    monkeypatch.setattr(compat, "_json_get", lambda *_: {"data": [None, {"title": "AI"}]})
    assert toutiao._search_content("AI", 10) == [{"title": "AI"}]


@pytest.mark.parametrize("url,body,category", [
    ("https://visitor.passport.weibo.cn/visitor", b"private response", "login_required"),
    ("https://m.weibo.cn/api", b"<html>private response</html>", "non_json_response"),
    ("https://m.weibo.cn/api", b"[]", "invalid_response"),
])
def test_response_failures_are_safe_and_specific(monkeypatch, capsys, url, body, category):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def geturl(self):
            return url

        def read(self, *_):
            return body

    monkeypatch.setattr(compat.urllib.request, "urlopen", lambda *_args, **_kwargs: Response())
    assert compat._json_get("https://m.weibo.cn/api", {}, "微博") is None
    stderr = capsys.readouterr().err
    assert "private response" not in stderr
    assert _platform_errors(stderr) == {"weibo": [category]}


def test_weibo_nested_cards_are_preserved(monkeypatch):
    weibo, toutiao, zhihu = modules()
    payload = {"data": {"cards": [
        {"card_type": 9, "mblog": {"id": 1}},
        {"card_type": 11, "card_group": [{"mblog": {"id": 2}}, None]},
    ]}}
    monkeypatch.setattr(compat, "_json_get", lambda *_: payload)
    compat.install(weibo, toutiao, zhihu)
    assert weibo._search_via_public("AI", "2026-10-24", "2026-10-25", 10) == [
        {"id": 1}, {"id": 2},
    ]


def test_search_landing_page_is_not_treated_as_successful_empty_result():
    weibo, toutiao, zhihu = modules()
    compat.install(weibo, toutiao, zhihu)
    with pytest.raises(ValueError, match="search_results_unavailable"):
        zhihu._fetch_html("https://cn.bing.com/search?q=AI")


def test_valid_json_payload_is_preserved(monkeypatch):
    payload = {"data": [{"title": "AI"}]}
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def geturl(self):
            return "https://www.toutiao.com/api"

        def read(self, *_):
            return json.dumps(payload).encode()

    monkeypatch.setattr(compat.urllib.request, "urlopen", lambda *_args, **_kwargs: Response())
    assert compat._json_get("https://www.toutiao.com/api", {}, "今日头条") == payload


def test_project_runner_loads_compatibility_layer_in_child_process(tmp_path):
    scripts = tmp_path / "scripts"
    lib = scripts / "lib"
    lib.mkdir(parents=True)
    (lib / "__init__.py").write_text("", encoding="utf-8")
    for name in ("weibo", "toutiao", "zhihu"):
        (lib / f"{name}.py").write_text(
            '_UA = "test"\n'
            'def _fetch_html(*args, **kwargs): return "<html></html>"\n'
            'def _parse_article(row): return row\n'
            'def _parse_mblog(row): return row\n', encoding="utf-8",
        )
    engine = scripts / "last30days.py"
    engine.write_text(
        'import json, urllib.request\nfrom lib import toutiao\n'
        'class Response:\n'
        '    def __enter__(self): return self\n'
        '    def __exit__(self, *args): pass\n'
        '    def geturl(self): return "https://www.toutiao.com/api"\n'
        '    def read(self, *args): return b\'{"data":null}\'\n'
        'urllib.request.urlopen = lambda *args, **kwargs: Response()\n'
        'print(json.dumps({"toutiao": toutiao._search_content("AI", 10)}))\n',
        encoding="utf-8",
    )
    runner = Path(__file__).resolve().parents[1] / "src" / "cn_engine_runner.py"
    result = _run_engine(runner, [str(engine)], 10)
    assert result["toutiao"] == []
    assert result["_engine_platform_errors"] == {"toutiao": ["empty_data"]}
