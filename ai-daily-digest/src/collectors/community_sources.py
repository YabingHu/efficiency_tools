"""Lobsters 与 Stack Exchange 社区热议采集器。"""
import html
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta

from ..http_client import get as http_get
from ..models import NewsItem
from ..utils import report_end_utc

log = logging.getLogger(__name__)

LOBSTERS_API = "https://lobste.rs/t/ai.json"
STACKEXCHANGE_API = "https://api.stackexchange.com/2.3/questions"
HEADERS = {"User-Agent": "ai-daily-digest/1.0 (public community feed)"}


def _parse_iso_datetime(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _collect_lobsters(cfg: dict, as_of: datetime, since: datetime) -> list[NewsItem]:
    source_cfg = cfg["sources"]["community_sources"].get("lobsters", {})
    if not source_cfg.get("enabled", True):
        return []
    try:
        response = http_get(
            source_cfg.get("url", LOBSTERS_API), cfg=cfg, headers=HEADERS,
        )
        response.raise_for_status()
        stories = response.json()
    except Exception as exc:
        log.warning("Lobsters 拉取失败: %s", exc)
        return []

    min_score = source_cfg.get("min_score", 5)
    min_comments = source_cfg.get("min_comments", 2)
    items = []
    for story in stories[:source_cfg.get("max_fetch", 25)]:
        created_at = _parse_iso_datetime(story.get("created_at", ""))
        if created_at is None or not since <= created_at <= as_of:
            continue
        score = int(story.get("score") or 0)
        comments = int(story.get("comment_count") or 0)
        if score < min_score and comments < min_comments:
            continue
        story_id = str(story.get("short_id") or "").strip()
        title = str(story.get("title") or "").strip()
        discussion_url = str(story.get("comments_url") or "").strip()
        article_url = str(story.get("url") or "").strip() or discussion_url
        if not story_id or not title or not article_url:
            continue
        tags = [str(tag) for tag in story.get("tags", [])]
        items.append(NewsItem(
            id=f"lobsters:{story_id}",
            section="community",
            title=title,
            url=article_url,
            source="Lobsters",
            text=(
                f"Lobsters AI 社区：{score} 分，{comments} 条评论。"
                f"标签：{', '.join(tags)}。讨论：{discussion_url}"
            ),
            score=float(score),
            meta={
                "points": score,
                "comments": comments,
                "discussion_url": discussion_url,
                "published": created_at.isoformat(),
            },
        ))
    return items


def _collect_stackexchange_site(
    cfg: dict,
    site_cfg: dict,
    as_of: datetime,
    since: datetime,
) -> tuple[str, list[NewsItem]]:
    site = site_cfg["site"]
    name = site_cfg["name"]
    source_cfg = cfg["sources"]["community_sources"]["stackexchange"]
    try:
        response = http_get(
            STACKEXCHANGE_API,
            cfg=cfg,
            headers=HEADERS,
            params={
                "site": site,
                "sort": "hot",
                "order": "desc",
                "pagesize": source_cfg.get("max_fetch_per_site", 20),
                "filter": "default",
            },
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        log.warning("Stack Exchange [%s] 拉取失败: %s", name, exc)
        return name, []

    if payload.get("backoff"):
        log.warning("Stack Exchange 要求退避 %s 秒", payload["backoff"])

    items = []
    for question in payload.get("items", []):
        activity = datetime.fromtimestamp(
            question.get("last_activity_date") or question.get("creation_date") or 0,
            tz=UTC,
        )
        if not since <= activity <= as_of:
            continue
        question_id = question.get("question_id")
        title = html.unescape(str(question.get("title") or "")).strip()
        url = str(question.get("link") or "").strip()
        if not question_id or not title or not url:
            continue
        votes = int(question.get("score") or 0)
        answers = int(question.get("answer_count") or 0)
        views = int(question.get("view_count") or 0)
        # Stack Exchange 票数整体小于 HN；组合回答与浏览量形成可比较的热度分。
        ranking_score = votes * 10 + min(answers * 5, 30) + min(views / 20, 30)
        tags = [str(tag) for tag in question.get("tags", [])]
        items.append(NewsItem(
            id=f"stackexchange:{site}:{question_id}",
            section="community",
            title=title,
            url=url,
            source=name,
            text=(
                f"{name}：{votes} 票，{answers} 个回答，{views} 次浏览。"
                f"标签：{', '.join(tags)}"
            ),
            score=float(ranking_score),
            meta={
                "points": votes,
                "comments": answers,
                "views": views,
                "discussion_url": url,
                "published": activity.isoformat(),
            },
        ))
    return name, items


def collect(cfg: dict, today) -> list[NewsItem]:
    source_cfg = cfg["sources"]["community_sources"]
    lookback = timedelta(hours=source_cfg.get("lookback_hours", 96))
    as_of = report_end_utc(today, cfg.get("timezone", "Asia/Shanghai"))
    since = as_of - lookback

    tasks = [("Lobsters", _collect_lobsters, (cfg, as_of, since))]
    stack_cfg = source_cfg.get("stackexchange", {})
    if stack_cfg.get("enabled", True):
        tasks.extend(
            (site_cfg["name"], _collect_stackexchange_site, (cfg, site_cfg, as_of, since))
            for site_cfg in stack_cfg.get("sites", [])
        )

    results = {}
    with ThreadPoolExecutor(
        max_workers=max(1, len(tasks)), thread_name_prefix="community",
    ) as pool:
        futures = {pool.submit(function, *args): name for name, function, args in tasks}
        for future in as_completed(futures):
            name = futures[future]
            try:
                result = future.result()
                results[name] = result[1] if isinstance(result, tuple) else result
            except Exception:
                results[name] = []
                log.exception("社区源 [%s] 解析异常，跳过", name)

    items = [item for name, _, _ in tasks for item in results.get(name, [])]
    log.info("社区扩展源命中 %d 条", len(items))
    return items
