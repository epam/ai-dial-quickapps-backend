import pytest

from quickapp.dial_files_tooling._path_argument_transformer import _AppdataHomePathTransformer
from quickapp.shared.home_path.home_path_resolver import HomePathResolver
from tests.unit_tests.dial_files_tooling._helpers import make_config, make_service


def _make_transformer(
    appdata: str | None = "appbucket", agent_home_dir: str = ""
) -> _AppdataHomePathTransformer:
    resolver = HomePathResolver(
        dial_file_service=make_service(appdata=appdata),
        dial_files_config=make_config(agent_home_dir=agent_home_dir),
    )
    return _AppdataHomePathTransformer(home_resolver=resolver)


class TestAppdataHomePathTransformer:
    @pytest.mark.asyncio
    async def test_in_home_absolute_path_relativized(self):
        transformer = _make_transformer()
        result = await transformer.transform(
            {"path": "files/appbucket/reports/x.md", "content": "hi"}
        )
        assert result["path"] == "reports/x.md"
        # Non-path args are untouched.
        assert result["content"] == "hi"

    @pytest.mark.asyncio
    async def test_in_home_source_and_destination_relativized(self):
        transformer = _make_transformer()
        result = await transformer.transform(
            {
                "source": "files/appbucket/a.md",
                "destination": "files/appbucket/b.md",
            }
        )
        assert result["source"] == "a.md"
        assert result["destination"] == "b.md"

    @pytest.mark.asyncio
    async def test_out_of_home_absolute_left_unchanged(self):
        transformer = _make_transformer()
        result = await transformer.transform({"path": "files/otherbucket/uploads/x.md"})
        assert result["path"] == "files/otherbucket/uploads/x.md"

    @pytest.mark.asyncio
    async def test_relative_path_left_unchanged(self):
        transformer = _make_transformer()
        result = await transformer.transform({"path": "reports/x.md"})
        assert result["path"] == "reports/x.md"

    @pytest.mark.asyncio
    async def test_non_str_value_skipped(self):
        transformer = _make_transformer()
        result = await transformer.transform({"path": 123, "max_depth": 2})
        assert result["path"] == 123
        assert result["max_depth"] == 2

    @pytest.mark.asyncio
    async def test_missing_appdata_leaves_value_unchanged(self):
        # appdata unavailable -> home cannot be resolved -> to_display_path returns the
        # URL as-is, and the transformer must not raise.
        transformer = _make_transformer(appdata=None)
        result = await transformer.transform({"path": "files/appbucket/reports/x.md"})
        assert result["path"] == "files/appbucket/reports/x.md"

    @pytest.mark.asyncio
    async def test_honours_agent_home_subdir(self):
        transformer = _make_transformer(agent_home_dir="workspace/")
        result = await transformer.transform({"path": "files/appbucket/workspace/reports/x.md"})
        assert result["path"] == "reports/x.md"
