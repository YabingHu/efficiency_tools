"""调用 OpenAI 兼容接口生成中文摘要、点评与重要度评分。"""
import json
import logging
import re
import time

from openai import OpenAI

from .config import get_api_key
from .models import NewsItem

log = logging.getLogger(__name__)

BATCH_PROMPT = """你是一名 AI 领域资讯编辑，为《大模型每日早报》撰写内容。
下面是一批资讯条目（JSON 数组），包含 id、标题、来源和原始描述。请为每一条生成：
1. summary: 2~3 句中文摘要，说清楚"是什么、有什么亮点/意义"。原文信息不足时可结合常识，但不要编造具体数字。
2. comment: 一句话点评（观点鲜明、口语化，可以适度犀利）。
3. importance: 重要度 1~5 整数（5=重大发布/突破，3=值得一看，1=一般）。

严格返回 JSON 数组，格式：
[{"id": "...", "summary": "...", "comment": "...", "importance": 3}, ...]
不要输出任何其他文字。

资讯条目：
"""

OVERVIEW_PROMPT = """你是一名 AI 领域资讯编辑。根据以下今日资讯列表，写出 3~5 条"今日要点"，
每条一句话，概括今天大模型领域最值得关注的事情。
严格返回 JSON 数组（字符串数组），如 ["要点1", "要点2"]，不要输出其他文字。

今日资讯：
"""


def _extract_json(text: str):
    """容错解析：剥掉 markdown 代码块围栏后取最外层 JSON 数组。"""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1:
        raise ValueError(f"响应中未找到 JSON 数组: {text[:200]}")
    return json.loads(text[start:end + 1])


class Summarizer:
    def __init__(self, cfg: dict):
        llm = cfg["llm"]
        self.client = OpenAI(api_key=get_api_key(), base_url=llm["base_url"])
        self.model = llm["model"]
        self.batch_size = llm.get("batch_size", 12)
        self.max_retries = llm.get("max_retries", 2)
        self.temperature = llm.get("temperature", 0.3)

    def _chat(self, prompt: str) -> str:
        last_err = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=self.temperature,
                )
                return resp.choices[0].message.content
            except Exception as e:
                last_err = e
                log.warning("LLM 调用失败（第 %d 次）: %s", attempt + 1, e)
                time.sleep(2 * (attempt + 1))
        raise last_err

    def summarize_items(self, items: list[NewsItem]) -> None:
        """就地填充 summary_zh / comment / importance。"""
        for i in range(0, len(items), self.batch_size):
            batch = items[i:i + self.batch_size]
            payload = [{"id": it.id, "title": it.title,
                        "source": it.source, "text": it.text[:800]}
                       for it in batch]
            try:
                raw = self._chat(BATCH_PROMPT + json.dumps(payload, ensure_ascii=False))
                results = {r["id"]: r for r in _extract_json(raw) if "id" in r}
            except Exception as e:
                log.error("批次摘要失败，降级为原文展示: %s", e)
                results = {}
            for it in batch:
                r = results.get(it.id, {})
                it.summary_zh = str(r.get("summary", "")).strip() or it.text[:200]
                it.comment = str(r.get("comment", "")).strip()
                try:
                    it.importance = max(1, min(5, int(r.get("importance", 3))))
                except (TypeError, ValueError):
                    it.importance = 3
            log.info("摘要进度 %d/%d", min(i + self.batch_size, len(items)), len(items))

    def make_overview(self, items: list[NewsItem]) -> list[str]:
        top = sorted(items, key=lambda x: (x.importance, x.score), reverse=True)[:15]
        payload = [{"title": it.title, "summary": it.summary_zh, "source": it.source}
                   for it in top]
        try:
            raw = self._chat(OVERVIEW_PROMPT + json.dumps(payload, ensure_ascii=False))
            return [str(s) for s in _extract_json(raw)][:5]
        except Exception as e:
            log.error("今日要点生成失败: %s", e)
            return []
