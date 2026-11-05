import pytest
from pydantic import ValidationError

from quickapp.common.project_context import (
    ProjectContext,
    canonical_resource_url,
    extract_project_context,
    has_unsafe_segments,
)


class TestProjectContext:
    @pytest.mark.parametrize(
        "header, expected",
        [
            ("projects/b/My Project", "projects/b/My%20Project"),
            ("projects/b/My%20Project", "projects/b/My%20Project"),
            (
                "projects/b/%D0%9F%D1%80%D0%BE%D0%B5%D0%BA%D1%82",
                "projects/b/%D0%9F%D1%80%D0%BE%D0%B5%D0%BA%D1%82",
            ),
            ("projects/b/100%25", "projects/b/100%25"),
            ("projects/b/marketing/q4", "projects/b/marketing/q4"),
            ("  projects/b/p/  ", "projects/b/p"),
        ],
    )
    def test_url_is_canonicalized(self, header: str, expected: str) -> None:
        assert ProjectContext(url=header).url == expected

    @pytest.mark.parametrize(
        "header",
        [
            "projects/b",
            "files/b/p",
            "projects//p",
            "projects/b/a//c",
            "projects/b/./p",
            "projects/b/../p",
            "projects/b/files",
            "projects/b/p/files/x",
            "projects/b/a%2Fb",
        ],
    )
    def test_invalid_url_is_rejected(self, header: str) -> None:
        with pytest.raises(ValidationError):
            ProjectContext(url=header)

    def test_layout(self) -> None:
        project = ProjectContext(url="projects/b/My Project")

        assert project.instructions_url == "projects/b/My%20Project/files/PROJECT.md"
        assert project.context_root == "projects/b/My%20Project/files/context/"
        assert project.artifacts_root == "projects/b/My%20Project/files/artifacts/"

    @pytest.mark.parametrize(
        "url, expected",
        [
            ("projects/b/My%20Project/files/artifacts/a.md", True),
            ("projects/b/My Project/files/context/", True),
            ("projects/b/My Project/files/", True),
            ("projects/b/My Project", False),
            ("projects/b/My Project 2/files/a.md", False),
            ("projects/b/My Project/sub/files/a.md", False),
            ("files/b/My Project/files/a.md", False),
            ("projects/b/My Project/files/../../Other/files/x.md", False),
            ("projects/b/My Project/files/%2e%2e/%2E%2E/Other/files/x.md", False),
            ("projects/b/My Project/files/a//b.md", False),
            ("projects/b/My Project/files/./a.md", False),
            ("projects/b/My Project/files/a%2Fb.md", False),
        ],
    )
    def test_contains(self, url: str, expected: bool) -> None:
        assert ProjectContext(url="projects/b/My Project").contains(url) is expected


@pytest.mark.parametrize(
    "url, expected",
    [
        ("projects/b/p/files/a/", False),
        ("projects/b/p/files/a.md", False),
        ("projects/b/p/files/../x", True),
        ("projects/b/p/files/%2e%2e/x", True),
        ("projects/b/p/files//x", True),
        ("projects/b/p/files/a%2fb", True),
    ],
)
def test_has_unsafe_segments(url: str, expected: bool) -> None:
    assert has_unsafe_segments(url) is expected


def test_canonical_resource_url() -> None:
    assert canonical_resource_url("projects/b/My Project/files/ä.md") == (
        "projects/b/My%20Project/files/%C3%A4.md"
    )
    assert canonical_resource_url("projects/b/My%20Project/files/") == (
        "projects/b/My%20Project/files/"
    )


class TestExtractProjectContext:
    def test_header_is_found_case_insensitively(self) -> None:
        project = extract_project_context({"X-Project-Id": "projects/b/My Project"})

        assert project is not None
        assert project.url == "projects/b/My%20Project"

    @pytest.mark.parametrize("headers", [None, {}, {"X-Other": "1"}, {"x-project-id": ""}])
    def test_no_header_means_no_project(self, headers) -> None:
        assert extract_project_context(headers) is None
