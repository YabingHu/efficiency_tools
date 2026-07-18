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
