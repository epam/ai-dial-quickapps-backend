import pytest

from quickapp.common.project_context import ProjectContext
from quickapp.common.url_classification import (
    UrlScheme,
    classify_url,
    is_appdir_relative,
    is_dial_storage_path,
    to_relative_project_url,
)

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
        "",
        "://broken",
        "https://",
        "//example.com/protocol-relative.pdf",
        "reports/colon:in:path.txt",
    ],
)
def test_unsupported_or_malformed_classify_as_unsupported(url: str):
    assert classify_url(url, DIAL_URL) == UrlScheme.UNSUPPORTED


@pytest.mark.parametrize(
    "url",
    [
        # files, extension optional
        "butterfly.jpg",
        "reports/img.png",
        "a/b/c.txt",
        "dir1/file.md",
        "README",
        "my report.pdf",
        "not a url",
        # dirs end with '/'
        "some_dir/",
        "dir_1/dir2/",
    ],
)
def test_schemeless_paths_classify_as_relative(url: str):
    assert classify_url(url, DIAL_URL) == UrlScheme.DIAL_APPDIR_RELATIVE


@pytest.mark.parametrize(
    "path",
    [
        # traversal / segment shape
        "../escape.png",
        "./x.md",
        "a//b.txt",
        "trailing./x.txt",
        "name..",
        "/leading/slash.txt",
        "//",
        # DIAL UI forbidden characters
        "name;v.txt",
        "data{1}.txt",
        "closing}brace.txt",
        "100%.txt",
        "q&a.txt",
        "back\\slash.txt",
        'quote".txt',
        "name=x.txt",
        "colon:name.txt",
        "comma,name.txt",
        # control characters
        "tab\tname.txt",
        "line\nbreak.txt",
        # DIAL UI length limits (255 bytes/segment, 1024 bytes total; UTF-8 bytes)
        "a" * 252 + ".txt",
        "dir/" + "b" * 256,
        "я" * 130 + ".txt",
        "/".join(["seg" * 60] * 6) + "/f.txt",
    ],
)
def test_invalid_relative_references_are_rejected(path: str):
    assert not is_appdir_relative(path)
    assert classify_url(path, DIAL_URL) == UrlScheme.UNSUPPORTED


@pytest.mark.parametrize(
    "path",
    [
        "file.md",
        "some_dir/",
        "dir_1/dir2/",
        "dir1/file.md",
        "a" * 251 + ".txt",
        "я" * 125 + ".txt",
    ],
)
def test_valid_relative_references_are_accepted(path: str):
    assert is_appdir_relative(path)


def test_dial_base_url_without_host_treats_http_url_as_external():
    assert classify_url("https://example.com/x", "not-a-real-url") == UrlScheme.EXTERNAL


class TestProjectUrls:
    @pytest.mark.parametrize(
        "url",
        [
            "projects/b/My%20Project/files/context/tickets.csv",
            "projects/b/My Project/files/PROJECT.md",
            "projects/b/",
        ],
    )
    def test_projects_url_is_dial(self, url: str):
        assert classify_url(url, DIAL_URL) == UrlScheme.DIAL

    def test_projects_folder_inside_a_relative_path_stays_relative(self):
        assert classify_url("reports/projects/a.md", DIAL_URL) == UrlScheme.DIAL_APPDIR_RELATIVE


class TestToRelativeProjectUrl:
    _PROJECT = ProjectContext(url="projects/b/My%20Project")

    @pytest.mark.parametrize(
        ("url", "base_url"),
        [
            (f"{DIAL_URL}/v1/projects/b/My%20Project/files/x.md", DIAL_URL),
            ("HTTPS://DIAL.EXAMPLE.COM/v1/projects/b/My%20Project/files/x.md", DIAL_URL),
            (f"{DIAL_URL}/core/v1/projects/b/My%20Project/files/x.md", f"{DIAL_URL}/core/"),
        ],
    )
    def test_host_matched_project_url_becomes_relative(self, url: str, base_url: str):
        assert (
            to_relative_project_url(url, base_url, self._PROJECT)
            == "projects/b/My%20Project/files/x.md"
        )

    @pytest.mark.parametrize(
        "url",
        [
            "projects/b/My%20Project/files/x.md",
            "files/b/x.md",
            f"{DIAL_URL}/v1/files/b/x.md",
            f"{DIAL_URL}/v1/projects/b/Other/files/x.md",
            f"{DIAL_URL}/v1/projects/b/My%20Project/files/../../Other/files/x.md",
            f"{DIAL_URL}/v1/projects/b/My%20Project/files/x.md?download=1",
            f"{DIAL_URL}/v2/projects/b/My%20Project/files/x.md",
            "https://other.example.com/v1/projects/b/My%20Project/files/x.md",
            "ftp://dial.example.com/v1/projects/b/My%20Project/files/x.md",
        ],
    )
    def test_anything_else_is_unchanged(self, url: str):
        assert to_relative_project_url(url, DIAL_URL, self._PROJECT) == url

    def test_unchanged_without_project(self):
        url = f"{DIAL_URL}/v1/projects/b/My%20Project/files/x.md"
        assert to_relative_project_url(url, DIAL_URL, None) == url


@pytest.mark.parametrize(
    ("url", "project", "expected"),
    [
        ("files/b/x.md", None, True),
        ("projects/b/P/files/x.md", None, False),
        ("projects/b/P/files/x.md", ProjectContext(url="projects/b/P"), True),
        ("projects/b/Q/files/x.md", ProjectContext(url="projects/b/P"), False),
        (f"{DIAL_URL}/v1/files/b/x.md", None, False),
    ],
)
def test_is_dial_storage_path(url: str, project: ProjectContext | None, expected: bool):
    assert is_dial_storage_path(url, project) is expected
