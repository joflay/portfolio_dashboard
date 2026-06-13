from portfolio_dashboard.config import _normalize_endpoint


def test_normalize_endpoint_adds_https_scheme() -> None:
    assert _normalize_endpoint("api.webull.com") == "https://api.webull.com"


def test_normalize_endpoint_keeps_existing_scheme() -> None:
    assert _normalize_endpoint("https://example.test/") == "https://example.test"
