from bs4 import BeautifulSoup

from src.collectors import official_updates


def test_parses_anthropic_newsroom_cards():
    html = """
    <a href="/news/claude-update">
      <time>Jul 14, 2026</time>
      <span class="card__title">Introducing Claude Update</span>
    </a>
    """

    rows = official_updates._parse_anthropic(
        BeautifulSoup(html, "html.parser"), "https://www.anthropic.com/news"
    )

    assert len(rows) == 1
    assert rows[0]["title"] == "Introducing Claude Update"
    assert rows[0]["url"] == "https://www.anthropic.com/news/claude-update"
    assert rows[0]["date"].date().isoformat() == "2026-07-14"


def test_parses_kimi_research_cards_with_overlay_link():
    html = """
    <div class="card">
      <a aria-label="Kimi K3" href="/en/blog/kimi-k3"></a>
      <span>2026/07/17</span>
    </div>
    """

    rows = official_updates._parse_kimi(
        BeautifulSoup(html, "html.parser"), "https://www.kimi.com/en/blog/"
    )

    assert len(rows) == 1
    assert rows[0]["title"] == "Kimi K3"
    assert rows[0]["url"] == "https://www.kimi.com/en/blog/kimi-k3"
    assert rows[0]["date"].date().isoformat() == "2026-07-17"


def test_parses_deepseek_model_release():
    html = """
    <div>
      V4.0 DeepSeek-V4 New Release Date April 24, 2026
      <a href="https://static.deepseek.com/v4-card.pdf">Model Card</a>
      <a href="https://huggingface.co/deepseek-ai/v4">Technical Report</a>
    </div>
    """

    rows = official_updates._parse_deepseek(
        BeautifulSoup(html, "html.parser"), "https://www.deepseek.com/en/transparency/"
    )

    assert len(rows) == 1
    assert rows[0]["title"] == "DeepSeek-V4 released"
    assert rows[0]["date"].date().isoformat() == "2026-04-24"


def test_parses_qwen_code_blog_cards():
    html = """
    <a href="/qwen-code-docs/en/blog/weekly-update/">
      <span>Jul 9, 2026</span>
      <h2>Qwen Code Weekly</h2>
      <p>Model fallback chains and nested sub-agents.</p>
    </a>
    """

    rows = official_updates._parse_qwen(
        BeautifulSoup(html, "html.parser"),
        "https://qwenlm.github.io/qwen-code-docs/en/blog/",
    )

    assert len(rows) == 1
    assert rows[0]["title"] == "Qwen Code Weekly"
    assert rows[0]["url"].endswith("/qwen-code-docs/en/blog/weekly-update/")
