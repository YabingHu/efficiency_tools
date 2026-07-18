"""受限地抓取公开网页并提取可供摘要的正文。"""
import ipaddress
import logging
import socket
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from .http_client import get as http_get

log = logging.getLogger(__name__)

MAX_REDIRECTS = 3
MAX_RESPONSE_BYTES = 768 * 1024


def _is_public_url(url: str) -> bool:
    parsed = urlsplit(url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return False
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith((".localhost", ".local")):
        return False
    try:
        addresses = [ipaddress.ip_address(hostname)]
    except ValueError:
        try:
            port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
            addresses = {
                ipaddress.ip_address(result[4][0])
                for result in socket.getaddrinfo(hostname, port)
            }
        except (OSError, ValueError):
            return False
    return bool(addresses) and all(address.is_global for address in addresses)


def _extract_readable_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for node in soup.select(
        "script, style, noscript, svg, nav, footer, header, aside, form, dialog"
    ):
        node.decompose()
    container = soup.find("article") or soup.find("main") or soup.body or soup
    blocks = container.find_all(["h1", "h2", "h3", "p", "li", "blockquote"])
    text = " ".join(block.get_text(" ", strip=True) for block in blocks)
    if not text:
        text = container.get_text(" ", strip=True)
    return " ".join(text.split())


def extract_text_from_url(url: str, cfg: dict, *, min_chars: int = 160) -> str:
    """提取公开 HTML 正文；拒绝内网地址、超大响应和非文本内容。"""
    current_url = url
    try:
        for _ in range(MAX_REDIRECTS + 1):
            if not _is_public_url(current_url):
                log.warning("拒绝抓取非公网 URL: %s", current_url)
                return ""
            response = http_get(
                current_url,
                cfg=cfg,
                headers={"User-Agent": "ai-daily-digest/1.0 (article summary)"},
                allow_redirects=False,
                stream=True,
                retries=1,
            )
            if 300 <= response.status_code < 400:
                location = response.headers.get("Location")
                response.close()
                if not location:
                    return ""
                current_url = urljoin(current_url, location)
                continue
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "text/html").lower()
            if "html" not in content_type and not content_type.startswith("text/"):
                response.close()
                return ""
            chunks, total = [], 0
            for chunk in response.iter_content(chunk_size=16384):
                total += len(chunk)
                if total > MAX_RESPONSE_BYTES:
                    response.close()
                    log.warning("网页响应过大，跳过: %s", current_url)
                    return ""
                chunks.append(chunk)
            encoding = response.encoding or "utf-8"
            response.close()
            text = _extract_readable_text(b"".join(chunks).decode(encoding, errors="replace"))
            return text if len(text) >= min_chars else ""
    except Exception as exc:
        log.warning("网页正文提取失败 [%s]: %s", current_url, exc)
    return ""
