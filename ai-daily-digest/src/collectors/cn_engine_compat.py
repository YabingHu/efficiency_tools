"""固定版本中文引擎的响应兼容层；只输出固定诊断，不回显凭据或响应正文。"""
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request


def _diagnostic(platform: str, category: str) -> None:
    sys.stderr.write(f"[{platform}] 请求失败: {category}\n")


def _json_get(url: str, headers: dict, platform: str) -> dict | None:
    try:
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=15) as response:
            body = response.read(1024 * 1024 + 1)
            if len(body) > 1024 * 1024:
                _diagnostic(platform, "invalid_response")
                return None
            host = urllib.parse.urlsplit(response.geturl()).hostname or ""
            if host.startswith(("passport.", "visitor.passport.", "login.")):
                _diagnostic(platform, "login_required")
                return None
            try:
                data = json.loads(body.decode("utf-8"))
            except (ValueError, UnicodeError):
                _diagnostic(platform, "non_json_response")
                return None
            if not isinstance(data, dict):
                _diagnostic(platform, "invalid_response")
                return None
            return data
    except urllib.error.HTTPError as exc:
        _diagnostic(platform, f"http_{exc.code}")
        exc.close()
    except (TimeoutError, urllib.error.URLError):
        _diagnostic(platform, "network_error")
    return None


def install(weibo, toutiao, zhihu) -> None:
    """只替换已确认有问题的匿名响应处理，保留上游评分和数据契约。"""
    def search_weibo(topic, _from_date, _to_date, limit):
        encoded = urllib.parse.quote(topic)
        url = ("https://m.weibo.cn/api/container/getIndex?"
               f"containerid=100103type%3D1%26q%3D{encoded}&page_type=searchall")
        payload = _json_get(
            url, {"User-Agent": weibo._UA, "Referer": "https://m.weibo.cn/"}, "微博",
        )
        if payload is None:
            return []
        data = payload.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("cards"), list):
            _diagnostic("微博", "empty_data" if data is None else "invalid_response")
            return []
        items = []
        for card in data["cards"]:
            if not isinstance(card, dict):
                continue
            group = card.get("card_group") if card.get("card_type") == 11 else [card]
            for row in group if isinstance(group, list) else []:
                if isinstance(row, dict) and isinstance(row.get("mblog"), dict):
                    items.append(weibo._parse_mblog(row["mblog"]))
        return items[:limit]

    def search_toutiao(topic, limit):
        encoded = urllib.parse.quote(topic)
        url = ("https://www.toutiao.com/api/search/content/?"
               f"keyword={encoded}&count={min(limit, 20)}&offset=0")
        payload = _json_get(url, {"User-Agent": toutiao._UA,
                                "Referer": "https://www.toutiao.com/", "Cookie": "tt_webid=1"},
                            "今日头条")
        if payload is None:
            return []
        rows = payload.get("data")
        if not isinstance(rows, list):
            _diagnostic("今日头条", "empty_data" if rows is None else "invalid_response")
            return []
        return [parsed for row in rows if isinstance(row, dict)
                and (parsed := toutiao._parse_article(row)) is not None][:limit]

    def checked_search_html(fetch):
        def wrapped(url, timeout=8):
            body = fetch(url, timeout=timeout)
            if not re.search(r'class=["\'][^"\']*\bb_algo\b', body):
                raise ValueError("search_results_unavailable")
            return body
        return wrapped

    weibo._search_via_public = search_weibo
    toutiao._search_content = search_toutiao
    toutiao._fetch_html = checked_search_html(toutiao._fetch_html)
    zhihu._fetch_html = checked_search_html(zhihu._fetch_html)
