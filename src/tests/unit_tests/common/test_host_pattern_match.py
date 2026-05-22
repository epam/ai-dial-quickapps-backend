import pytest

from quickapp.common.external_fetch.host_pattern_match import match_host


@pytest.mark.parametrize(
    "host, patterns",
    [
        ("example.com", ["example.com"]),
        ("EXAMPLE.com", ["example.com"]),
        ("example.com", ["EXAMPLE.COM"]),
    ],
)
def test_exact_match_is_case_insensitive(host: str, patterns: list[str]):
    assert match_host(host, patterns) is True


def test_exact_pattern_does_not_match_subdomain():
    assert match_host("a.example.com", ["example.com"]) is False


@pytest.mark.parametrize(
    "host",
    [
        "a.example.com",
        "a.b.example.com",
        "deep.sub.example.com",
    ],
)
def test_wildcard_matches_any_subdomain(host: str):
    assert match_host(host, ["*.example.com"]) is True


def test_wildcard_does_not_match_apex():
    assert match_host("example.com", ["*.example.com"]) is False


def test_wildcard_does_not_match_unrelated_suffix():
    assert match_host("notexample.com", ["*.example.com"]) is False


def test_wildcard_and_apex_listed_together_match_both():
    patterns = ["example.com", "*.example.com"]
    assert match_host("example.com", patterns) is True
    assert match_host("a.example.com", patterns) is True


@pytest.mark.parametrize(
    "host",
    [
        "1.2.3.4",
        "127.0.0.1",
        "::1",
        "fe80::1",
    ],
)
def test_ip_literals_never_match(host: str):
    assert match_host(host, [host, "*.example.com"]) is False


def test_empty_patterns_returns_false():
    assert match_host("example.com", []) is False


def test_empty_host_returns_false():
    assert match_host("", ["example.com"]) is False


def test_mixed_list_picks_first_matching_pattern():
    patterns = ["other.com", "*.example.com", "third.com"]
    assert match_host("a.example.com", patterns) is True
    assert match_host("third.com", patterns) is True
    assert match_host("nope.com", patterns) is False
