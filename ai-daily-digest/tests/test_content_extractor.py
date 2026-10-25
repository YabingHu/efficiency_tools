import socket

from src import content_extractor


def test_public_url_check_rejects_local_networks(monkeypatch):
    assert content_extractor._is_public_url("http://127.0.0.1/admin") is False
    assert content_extractor._is_public_url("http://localhost/admin") is False
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 443))],
    )
    assert content_extractor._is_public_url("https://internal.example/page") is False


def test_extract_readable_text_drops_navigation_and_scripts():
    html = """
    <html><body><nav>menu noise</nav><article>
      <h1>Useful title</h1><p>First useful paragraph.</p>
      <script>ignore me</script><p>Second useful paragraph.</p>
    </article></body></html>
    """
    text = content_extractor._extract_readable_text(html)
    assert text == "Useful title First useful paragraph. Second useful paragraph."


def test_explicit_article_container_excludes_unrelated_body_and_requires_match():
    html = ('<body><div class="menu">导航和推广</div><div class="article">'
            '<p>AI 模型的具体配置。</p><p>实验结果及限制。</p></div>'
            '<div>推荐内容</div></body>')
    assert content_extractor._extract_readable_text(html, selector=".article") == (
        "AI 模型的具体配置。 实验结果及限制。"
    )
    assert content_extractor._extract_readable_text(html, selector=".missing") == ""
