from unittest.mock import AsyncMock, MagicMock

import pytest

from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.skills.exceptions import SkillFileNotFoundError
from quickapp.skills.file_reference._skill_file_source import _SkillFileSource
from quickapp.skills.registry._skills_registry import SkillsRegistry


def _source(read_result: str = "print('hi')", error: Exception | None = None):
    registry = MagicMock(spec=SkillsRegistry)
    registry.read_skill_file = AsyncMock(return_value=read_result, side_effect=error)
    return _SkillFileSource(registry), registry


class TestHandles:

    def test_handles_only_skill_references(self):
        source, _ = _source()

        assert source.handles("skill://s/a.py")
        assert not source.handles("files/b/a.py")
        assert not source.handles("https://x/skill://")


class TestLoad:

    @pytest.mark.asyncio
    async def test_returns_utf8_bytes_of_the_file_text(self):
        source, registry = _source(read_result="print('привет')")

        data = await source.load("skill://s/scripts/a.py", "code")

        assert data == "print('привет')".encode("utf-8")
        registry.read_skill_file.assert_awaited_once_with("s", "scripts/a.py")

    @pytest.mark.asyncio
    async def test_missing_file_becomes_parameter_error_listing_available_files(self):
        source, _ = _source(error=SkillFileNotFoundError("s", "x.py", ["scripts/a.py"]))

        with pytest.raises(InvalidToolCallParameterException) as excinfo:
            await source.load("skill://s/x.py", "code")

        assert excinfo.value.parameter_name == "code"
        assert "scripts/a.py" in str(excinfo.value)

    @pytest.mark.asyncio
    async def test_unreadable_file_becomes_parameter_error(self):
        source, _ = _source(error=RuntimeError("file is not UTF-8 text"))

        with pytest.raises(InvalidToolCallParameterException, match="not UTF-8 text"):
            await source.load("skill://s/a.py", "code")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("url", ["skill://s", "skill://"])
    async def test_malformed_reference(self, url: str):
        source, registry = _source()

        with pytest.raises(InvalidToolCallParameterException, match=r"skill://<skill_name>/"):
            await source.load(url, "code")
        registry.read_skill_file.assert_not_awaited()
