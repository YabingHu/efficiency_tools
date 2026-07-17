from datetime import date

from src.utils import canonical_url, report_end_utc, safe_http_url


def test_url_safety_and_canonicalization():
    assert safe_http_url("javascript:alert(1)") is None
    assert safe_http_url("https://example.com/a") == "https://example.com/a"
    assert canonical_url(
        "HTTPS://Example.COM/a/?utm_source=x&keep=1#part"
    ) == "https://example.com/a?keep=1"


def test_report_end_uses_configured_timezone():
    result = report_end_utc(date(2026, 7, 17), "Asia/Shanghai")
    assert result.isoformat().startswith("2026-07-17T15:59:59.999999+00:00")
