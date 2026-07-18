from datetime import date

from src.collectors import community_sources


class Response:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self.data


def test_collects_lobsters_and_stackexchange_with_heat_metadata(monkeypatch, cfg):
    cfg["sources"]["community_sources"]["lookback_hours"] = 96

    def fake_get(url, **kwargs):
        if "lobste.rs" in url:
            return Response([{
                "short_id": "abc123",
                "title": "New open model",
                "url": "https://example.com/model",
                "comments_url": "https://lobste.rs/s/abc123/model",
                "score": 12,
                "comment_count": 4,
                "created_at": "2026-07-17T10:00:00+00:00",
                "tags": ["ai"],
            }])
        site = kwargs["params"]["site"]
        return Response({"items": [{
            "question_id": 42,
            "title": "RAG &amp; evaluation",
            "link": f"https://{site}.stackexchange.com/questions/42",
            "score": 2,
            "answer_count": 3,
            "view_count": 200,
            "last_activity_date": 1784304000,
            "tags": ["rag"],
        }]})

    monkeypatch.setattr(community_sources, "http_get", fake_get)
    result = community_sources.collect(cfg, date(2026, 7, 18))

    assert {item.source for item in result} == {
        "Lobsters", "GenAI Stack Exchange", "AI Stack Exchange",
    }
    stack_item = next(item for item in result if item.source == "GenAI Stack Exchange")
    assert stack_item.title == "RAG & evaluation"
    assert stack_item.meta["comments"] == 3
    assert stack_item.meta["discussion_url"] == stack_item.url
