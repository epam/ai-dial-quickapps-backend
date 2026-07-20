import pytest

from quickapp.common.url_classification import UrlScheme, classify_url

DIAL_URL = "https://dial.example.com"


@pytest.mark.parametrize(
    "url",
    [
        "files/bucket/foo.pdf",
        "/files/bucket/foo.pdf",
        "files/{hash}/Foo.pdf",
        "FILES/bucket/upper.pdf",
    ],
)
def test_bare_dial_relative_paths_are_dial(url: str):
    assert classify_url(url, DIAL_URL) == UrlScheme.DIAL


@pytest.mark.parametrize(
    "url",
    [
        "https://dial.example.com/v1/files/bucket/foo.pdf",
        "https://DIAL.EXAMPLE.COM/v1/files/bucket/foo.pdf",
        "http://dial.example.com/v1/files/bucket/foo.pdf",
    ],
)
def test_dial_absolute_urls_classify_as_dial(url: str):
    assert classify_url(url, DIAL_URL) == UrlScheme.DIAL


def test_different_port_on_dial_host_still_dial():
    assert (
        classify_url("https://dial.example.com:8443/v1/files/x/y.pdf", DIAL_URL) == UrlScheme.DIAL
    )


def test_dial_url_with_trailing_slash_normalised():
    assert (
        classify_url(
            "https://dial.example.com/v1/files/x/y.pdf",
            "https://dial.example.com/",
        )
        == UrlScheme.DIAL
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/foo.pdf",
        "http://other.example/foo.pdf",
        "https://gist.github.com/u/raw/x.md",
    ],
)
def test_external_http_urls_classify_as_external(url: str):
    assert classify_url(url, DIAL_URL) == UrlScheme.EXTERNAL


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://files.example.com/x",
        "data:text/plain,hello",
        "javascript:alert(1)",
        "not a url",
        "",
        "://broken",
        "https://",
    ],
)
def test_unsupported_or_malformed_classify_as_unsupported(url: str):
    assert classify_url(url, DIAL_URL) == UrlScheme.UNSUPPORTED


def test_dial_base_url_without_host_treats_http_url_as_external():
    assert classify_url("https://example.com/x", "not-a-real-url") == UrlScheme.EXTERNAL
