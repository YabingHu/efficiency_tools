"""Conservative event matching for versioned model and developer-tool releases."""
import re

from .models import NewsItem
from .utils import canonical_url

MODEL_FAMILIES = r"(?:gpt|claude|gemini|deepseek|qwen|kimi|llama|mistral|grok|glm)"
MODEL = re.compile(
    rf"(?<![a-z0-9]){MODEL_FAMILIES}"
    r"[ -]?(?:(?:opus|sonnet|haiku|flash|pro|turbo|air)[ -]+)?"
    r"(?:v|r|k)?\d+(?:\.\d+)*(?:[- ](?:opus|sonnet|haiku|flash(?:[- ]lite)?|"
    r"pro|max|turbo|air|mini|nano|plus|thinking|instruct|coder|preview|\d+b))?"
    r"(?![a-z0-9]|\.\d)",
    re.I,
)
TOOL = re.compile(
    r"(?<![a-z0-9])(?:claude code|codex(?: cli)?|vllm|ollama|litellm|langgraph|cursor)"
    r"[ :–-]+v?\d+(?:\.\d+)+(?:[-.](?:rc|beta|alpha|preview)\d*)?(?![a-z0-9]|\.\d)",
    re.I,
)
RELEASE = re.compile(
    r"\b(?:releas(?:e[sd]?|ing)|launch(?:es|ed)?|introduc(?:e[sd]?|ing)|"
    r"announc(?:e[sd]?|ing)|ship(?:s|ped)?)\b|发布|推出|上线", re.I,
)
MILESTONES = {
    "weights": (
        "开放模型权重",
        re.compile(
            r"\b(?:(?:model )?weights (?:are )?(?:now )?"
            r"(?:available|released)|releas(?:e[sd]?|ing) (?:the |model )?weights)\b"
            r"|(?:已|正式|现已)(?:开放|公开|开源)(?:模型)?权重|(?:模型)?权重(?:现已|已)(?:开放|公开|开源)",
            re.I,
        ),
    ),
    "api": (
        "开放 API 访问",
        re.compile(
            r"\b(?:now available (?:via|through|in|on) (?:the |our )?api|"
            r"api (?:access )?(?:is )?now (?:available|live))\b"
            r"|(?:API(?:访问)?(?:现已|已|正式)(?:开放|上线|可用)|(?:现已|已|正式)开放 API)",
            re.I,
        ),
    ),
    "stable": (
        "进入正式可用阶段",
        re.compile(r"\b(?:now generally available|(?:is )?now in general availability)\b"
                   r"|(?:现已|已)正式可用|正式商用", re.I),
    ),
}
UNCERTAIN = re.compile(
    r"\b(?:not|no|never|will|plan(?:s|ned)?|rumou?r(?:ed)?|could|might|whether)\b"
    r"|尚未|未开放|没有|预计|计划|即将|将会|传闻|是否|还未|将于", re.I,
)
OPEN_WEIGHT = re.compile(r"\bopen[- ]weights?\b", re.I)


def _entities(text: str) -> set[str]:
    entities = set()
    for match in (*TOOL.findall(text), *MODEL.findall(text)):
        match = re.sub(rf"^({MODEL_FAMILIES})(?=[vrk]?\d)", r"\1 ", match.lower())
        words = re.sub(r"[ :–-]+", " ", match.lower()).split()
        words = [word for word in words if word != "cli"]
        words = [
            word.removeprefix("v") if re.match(r"v\d", word) else word for word in words
        ]
        # Claude Sonnet 4.5 and Claude 4.5 Sonnet describe the same version.
        family, *version = words
        entities.add(" ".join((family, *sorted(version))))
    return entities


def annotate_event(item: NewsItem) -> None:
    if "event_key" in item.meta:
        return
    entities = _entities(item.title)
    if len(entities) != 1:
        return
    entity = next(iter(entities))
    source = {"source": item.source, "url": item.url}
    milestones = {}
    passages = [item.title]
    if item.meta.get("first_party"):
        passages.extend(re.split(r"(?<=[.!?。！？])\s+|[。！？\n]", item.text))
    for passage in passages:
        mentions = _entities(passage)
        if (mentions and mentions != entities) or UNCERTAIN.search(passage):
            continue
        for key, (_, pattern) in MILESTONES.items():
            if pattern.search(passage):
                milestones[key] = source
    explicit_release = RELEASE.search(item.title) and not UNCERTAIN.search(item.title)
    if explicit_release and OPEN_WEIGHT.search(item.title):
        milestones["weights"] = source
    if not (milestones or explicit_release):
        return
    item.meta["event_key"] = entity
    item.meta["event_milestones"] = milestones


def merge_event_sources(lead: NewsItem, other: NewsItem) -> None:
    """Keep provenance when two independently linked items describe one event."""
    lead.meta["event_milestones"] = {
        **other.meta.get("event_milestones", {}),
        **lead.meta.get("event_milestones", {}),
    }
    links = lead.meta.setdefault("related_sources", [])
    candidates = list(other.meta.get("related_sources", []))
    if (len(other.text.strip()) >= 60 and other.meta.get("link_status") != "rss_only"
            and other.source != lead.source):
        candidates.insert(0, {"source": other.source, "url": other.url})
    known = {canonical_url(lead.url), *(canonical_url(link["url"]) for link in links)}
    for link in candidates:
        url = canonical_url(link["url"])
        if url not in known:
            known.add(url)
            links.append(link)
