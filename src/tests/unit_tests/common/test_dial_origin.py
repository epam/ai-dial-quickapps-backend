import pytest

from quickapp.common.dial_origin import is_dial_origin

DIAL_URL = "https://dial.corp"


@pytest.mark.parametrize(
    "url",
    [
        "https://dial.corp/v1/deployments/app/mcp",
        "https://DIAL.corp/mcp",
        "https://dial.corp:443/mcp",
        "https://dial.corp",
    ],
)
def test_same_origin_is_dial(url):
    assert is_dial_origin(url, DIAL_URL)


@pytest.mark.parametrize(
    "url",
    [
        "https://dial.corp.attacker.io/mcp",
        "https://dial.corp@attacker.io/mcp",
        "http://dial.corp/mcp",
        "https://dial.corp:8443/mcp",
        "https://other.corp/mcp",
        "not a url",
        "",
    ],
)
def test_other_origin_is_not_dial(url):
    assert not is_dial_origin(url, DIAL_URL)


def test_default_port_is_equivalent_to_explicit_port():
    assert is_dial_origin("http://core:80/mcp", "http://core")


def test_dial_url_with_non_default_port_requires_the_same_port():
    assert is_dial_origin("http://core:8080/mcp", "http://core:8080")
    assert not is_dial_origin("http://core/mcp", "http://core:8080")


def test_unparsable_dial_url_matches_nothing():
    assert not is_dial_origin("https://dial.corp/mcp", "")
