import pytest

from quickapp.task_tooling._tool_config import is_inherit


@pytest.mark.parametrize(
    "tools, expected",
    [
        ("inherit", True),
        (["inherit"], True),
        ([], False),
        (["inherit", "web_search"], False),
        (["web_search"], False),
        (None, False),
    ],
)
def test_is_inherit(tools, expected):
    assert is_inherit(tools) is expected
