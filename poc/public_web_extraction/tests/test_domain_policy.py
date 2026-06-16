import sys
from pathlib import Path

POC_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(POC_DIR))

from domain_policy import extract_domain, is_blocklisted, normalize_url, validate_candidate_url


CONFIG = {
    "candidate_url_only_mode": True,
    "blocklist": ["payment-sites-placeholder.example"],
}
CANDIDATES = [{"url": "https://example.com/product", "category": "product_homepage"}]


def test_normalize_url_adds_https_and_extracts_domain():
    assert normalize_url("example.com/product") == "https://example.com/product"
    assert extract_domain("https://www.example.com/a") == "example.com"


def test_candidate_url_only_mode_enforced():
    result = validate_candidate_url("https://unknown.example/page", CANDIDATES, CONFIG)
    assert result.allowed is False
    assert result.reason == "url_not_in_candidate_pages"


def test_blocklisted_domain_is_rejected():
    assert is_blocklisted("https://pay.payment-sites-placeholder.example/checkout", CONFIG)
    result = validate_candidate_url(
        "https://payment-sites-placeholder.example/checkout",
        [{"url": "https://payment-sites-placeholder.example/checkout"}],
        CONFIG,
    )
    assert result.allowed is False
    assert result.reason == "domain_blocklisted"
