from unittest.mock import MagicMock

import pytest

from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.skills.exceptions import SkillFileNotFoundError
from quickapp.skills.file_reference._skill_file_reference_transformer import (
    _SkillFileReferenceTransformer,
)
from quickapp.skills.registry._skills_registry import SkillsRegistry

_URL = "skills/b/s/files/scripts/clean.py"


def _transformer(error: Exception | None = None):
    registry = MagicMock(spec=SkillsRegistry)
    registry.resolve_file_url = MagicMock(return_value=_URL, side_effect=error)
    return _SkillFileReferenceTransformer(registry), registry


class TestTransform:

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "value", ["skill://s/scripts/clean.py", "file:url::skill://s/scripts/clean.py"]
    )
    async def test_rewrites_reference_to_file_url(self, value: str):
        transformer, registry = _transformer()

        result = await transformer.transform({"script_url": value})

        assert result == {"script_url": _URL}
        registry.resolve_file_url.assert_called_once_with("s", "scripts/clean.py")

    @pytest.mark.asyncio
    async def test_rewrites_each_element_of_a_list(self):
        transformer, registry = _transformer()

        result = await transformer.transform(
            {"scripts": ["file:url::skill://s/a.py", "plain", "skill://s/b.py"]}
        )

        assert result == {"scripts": [_URL, "plain", _URL]}
        assert registry.resolve_file_url.call_count == 2

    @pytest.mark.asyncio
    async def test_leaves_other_values_untouched(self):
        transformer, registry = _transformer()
        kwargs = {
            "a": "file:text::skill://s/a.py",
            "b": "https://example.com/x",
            "c": "hello",
            "d": 42,
            "e": "see skill://s/a.py for details",
        }

        assert await transformer.transform(dict(kwargs)) == kwargs
        registry.resolve_file_url.assert_not_called()

    @pytest.mark.asyncio
    async def test_unknown_file_is_a_parameter_error(self):
        transformer, _ = _transformer(
            error=SkillFileNotFoundError("s", "x.py", ["scripts/clean.py"])
        )

        with pytest.raises(InvalidToolCallParameterException) as excinfo:
            await transformer.transform({"script_url": "skill://s/x.py"})

        assert excinfo.value.parameter_name == "script_url"
        assert "scripts/clean.py" in str(excinfo.value)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("value", ["skill://s", "skill://", "file:url::skill://s/"])
    async def test_malformed_reference(self, value: str):
        transformer, registry = _transformer()

        with pytest.raises(InvalidToolCallParameterException, match=r"skill://<skill_name>/"):
            await transformer.transform({"script_url": value})
        registry.resolve_file_url.assert_not_called()


class TestInlinedContentIsNotAReference:

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "content",
        [
            "skill://docs/overview.md\nprint('x')",
            "skill://docs/overview.md\r\nprint('x')",
            "skill://docs/overview.md\tcomment",
        ],
    )
    async def test_multiline_text_starting_with_a_reference_is_left_alone(self, content: str):
        # The file transformer runs first and may inline a script that merely starts with
        # `skill://`; that text must never be re-read as a reference.
        transformer, registry = _transformer()

        result = await transformer.transform({"code": content})

        assert result == {"code": content}
        registry.resolve_file_url.assert_not_called()

    @pytest.mark.asyncio
    async def test_file_names_with_spaces_are_still_references(self):
        transformer, registry = _transformer()

        await transformer.transform({"script_url": "skill://s/scripts/my file's.py"})

        registry.resolve_file_url.assert_called_once_with("s", "scripts/my file's.py")
