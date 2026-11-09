import pytest

from quickapp.common.utils import canonical_url


@pytest.mark.parametrize(
    "url, expected",
    [
        ("projects/b/My Project/files/ä b.md", "projects/b/My%20Project/files/%C3%A4%20b.md"),
        ("projects/b/My%20Project/files/a.md", "projects/b/My%20Project/files/a.md"),
        ("files/b/100%25 #1?.txt", "files/b/100%25%20%231%3F.txt"),
        ("projects/b/p/files/folder/", "projects/b/p/files/folder/"),
        ("https://core/v1/files/b/a%20b.txt", "https://core/v1/files/b/a%20b.txt"),
    ],
)
def test_canonical_url(url: str, expected: str) -> None:
    assert canonical_url(url) == expected
