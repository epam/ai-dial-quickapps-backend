import pytest

from quickapp.dial_files_tooling._utils import relative_to

_FOLDER = "projects/b/My%20P/files/artifacts/"


class TestRelativeTo:
    @pytest.mark.parametrize(
        "folder_url",
        [
            f"{_FOLDER}Q1%20(draft)/",
            f"{_FOLDER}Q1%20%28draft%29/",
            "projects/b/My P/files/artifacts/Q1 (draft)/",
        ],
    )
    def test_folder_matches_in_any_spelling(self, folder_url: str):
        url = f"{_FOLDER}Q1%20(draft)/sub/a%20b.md"

        assert relative_to(url, folder_url) == "sub/a%20b.md"

    def test_url_outside_the_folder_unchanged(self):
        url = f"{_FOLDER}other/a.md"

        assert relative_to(url, f"{_FOLDER}Q1/") == url

    def test_sibling_with_a_longer_name_is_outside(self):
        url = f"{_FOLDER}Q10/a.md"

        assert relative_to(url, f"{_FOLDER}Q1/") == url
