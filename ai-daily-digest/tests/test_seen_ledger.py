from datetime import date
from pathlib import Path

from src.models import NewsItem
from src.seen_ledger import SeenLedger


def item(item_id, url="https://example.com/a", section="community"):
    return NewsItem(id=item_id, section=section, title=item_id, url=url, source="test")


def ledger(tmp_path, window_days=7):
    return SeenLedger(Path(tmp_path) / "history" / "seen-items.json", window_days)


def test_records_and_suppresses_within_window(tmp_path):
    led = ledger(tmp_path)
    shown = [item("a", "https://example.com/a")]
    led.record(shown, date(2026, 7, 20))
    led.save()

    reloaded = ledger(tmp_path)
    # 5 天后同一条仍被压制
    assert reloaded.filter_unseen([item("a", "https://example.com/a")], date(2026, 7, 25)) == []


def test_matches_by_canonical_url_even_with_different_id(tmp_path):
    led = ledger(tmp_path)
    led.record([item("hf:1", "https://example.com/paper?utm_source=x")], date(2026, 7, 20))
    # 不同 ID、追踪参数不同，但规范化 URL 相同 -> 视为重复
    fresh = led.filter_unseen(
        [item("arxiv:1", "https://example.com/paper?utm_source=y")], date(2026, 7, 22)
    )
    assert fresh == []


def test_item_reappears_after_window_expires(tmp_path):
    led = ledger(tmp_path, window_days=7)
    led.record([item("a", "https://example.com/a")], date(2026, 7, 20))
    # 第 8 天（窗口 7 天）已超出，应重新可见
    fresh = led.filter_unseen([item("a", "https://example.com/a")], date(2026, 7, 28))
    assert [value.id for value in fresh] == ["a"]


def test_same_day_is_not_suppressed(tmp_path):
    """当天重复由 main.deduplicate 负责；台账不应压制报告日当天自身。"""
    led = ledger(tmp_path)
    led.record([item("a", "https://example.com/a")], date(2026, 7, 20))
    fresh = led.filter_unseen([item("a", "https://example.com/a")], date(2026, 7, 20))
    assert [value.id for value in fresh] == ["a"]


def test_prune_drops_entries_older_than_window(tmp_path):
    led = ledger(tmp_path, window_days=7)
    led.record([item("old", "https://example.com/old")], date(2026, 7, 1))
    led.record([item("recent", "https://example.com/recent")], date(2026, 7, 20))
    led.prune(date(2026, 7, 22))
    led.save()

    document = (Path(tmp_path) / "history" / "seen-items.json").read_text(encoding="utf-8")
    assert "example.com/recent" in document
    assert "example.com/old" not in document


def test_corrupt_ledger_degrades_to_no_dedup(tmp_path):
    path = Path(tmp_path) / "history" / "seen-items.json"
    path.parent.mkdir(parents=True)
    path.write_text("{ not valid json", encoding="utf-8")
    led = SeenLedger(path, 7)
    fresh = led.filter_unseen([item("a")], date(2026, 7, 20))
    assert [value.id for value in fresh] == ["a"]


def test_unchanged_ledger_is_not_rewritten(tmp_path):
    led = ledger(tmp_path)
    led.save()  # nothing recorded -> not dirty
    assert not (Path(tmp_path) / "history" / "seen-items.json").exists()
