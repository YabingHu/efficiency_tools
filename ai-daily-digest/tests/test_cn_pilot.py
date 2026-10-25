from datetime import UTC, datetime

from src.cn_pilot import normalize


def test_weibo_samples_bound_deduplicate_and_do_not_export_credentials():
    posts = [
        {
            "mblog": {
                "id": str(i),
                "text": "<p>AI &amp; 编程</p>",
                "created_at": "Sun Oct 25 08:00:00 +0800 2026",
                "cookie": "secret",
                "user": {"token": "secret"},
            }
        }
        for i in range(10)
    ]
    rows = normalize("weibo", [{"card_type": 11}, posts[0], *posts])
    assert len(rows) == 5
    assert len({r["url"] for r in rows}) == 5
    assert rows[0]["text"] == "AI & 编程"
    assert rows[0]["published_at"] == "2026-10-25T08:00:00+08:00"
    assert "secret" not in str(rows)
    assert set(rows[0]) == {"platform", "author", "title", "url", "published_at", "text"}


def test_zhihu_samples_support_answers_articles_and_reject_unsafe_links():
    rows = normalize(
        "zhihu",
        [
            {
                "id": "123",
                "type": "answer",
                "question": {"id": "456", "title": "模型训练"},
                "content": "<p>一个训练方法</p>",
                "created_time": 1792886400,
            },
            {"id": "789", "type": "article", "title": "推理优化", "content": "量化实践"},
            {"id": "bad/path", "type": "article", "content": "bad"},
            {"id": "333", "type": "answer", "question": {}, "content": "bad"},
            {"id": "444", "type": "article", "content": ""},
        ],
    )
    assert len(rows) == 2
    assert rows[0]["url"] == "https://www.zhihu.com/question/456/answer/123"
    assert rows[1]["url"] == "https://zhuanlan.zhihu.com/p/789"
    assert rows[1]["published_at"] == ""


def test_old_pinned_posts_and_undated_items_do_not_displace_recent_posts():
    def post(ident, date):
        return {"mblog": {"id": str(ident), "text": "AI 实践", "created_at": date}}

    rows = normalize(
        "weibo",
        [
            post(1, "Tue Dec 23 10:00:00 +0800 2025"),
            post(2, ""),
            post(3, "Sun Oct 25 10:00:00 +0800 2026"),
        ],
        since=datetime(2026, 10, 23, tzinfo=UTC),
    )
    assert [row["url"] for row in rows] == ["https://m.weibo.cn/detail/3"]


def test_zhihu_historical_probe_is_valid_but_excluded_from_daily_candidates():
    posts = [
        {
            "id": "123",
            "type": "article",
            "title": "低频作者的模型分析",
            "content": "模型分析正文",
            "created": int(datetime(2026, 10, 19, 16, 32, 29, tzinfo=UTC).timestamp()),
        }
    ]
    assert len(normalize("zhihu", posts)) == 1
    assert normalize("zhihu", posts, since=datetime(2026, 10, 23, tzinfo=UTC)) == []
