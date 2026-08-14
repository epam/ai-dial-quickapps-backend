import pytest

from quickapp.mcp_tooling._mcp_resource_card_provider import _MCPResourceCardProvider
from quickapp.mcp_tooling._mcp_resource_meta import MCPResourceMeta
from quickapp.mcp_tooling._mcp_tooling_context import _MCPToolingContext


def _meta(
    name: str = "Schema",
    uri: str = "urn://schema",
    toolset: str = "ts",
    toolset_desc: str | None = None,
    resource_desc: str | None = None,
    mime_type: str | None = None,
) -> MCPResourceMeta:
    return MCPResourceMeta(
        resource_name=name,
        resource_uri=uri,
        toolset_name=toolset,
        toolset_description=toolset_desc,
        resource_description=resource_desc,
        mime_type=mime_type,
    )


def _context(metas: list[MCPResourceMeta]) -> _MCPToolingContext:
    ctx = _MCPToolingContext()
    ctx.extend_resource_metas(metas)
    return ctx


@pytest.mark.asyncio
async def test_empty_metas_returns_empty_string():
    provider = _MCPResourceCardProvider(_context([]))
    assert await provider.get_prompt_part() == ""


@pytest.mark.asyncio
async def test_single_resource_minimal_fields():
    provider = _MCPResourceCardProvider(_context([_meta()]))
    result = await provider.get_prompt_part()

    assert "--- Resource: Schema (ts) ---" in result
    assert "URI: urn://schema" in result


@pytest.mark.asyncio
async def test_mime_type_included_when_present():
    provider = _MCPResourceCardProvider(_context([_meta(mime_type="application/json")]))
    result = await provider.get_prompt_part()

    assert "MIME type: application/json" in result


@pytest.mark.asyncio
async def test_mime_type_omitted_when_absent():
    provider = _MCPResourceCardProvider(_context([_meta()]))
    result = await provider.get_prompt_part()

    assert "MIME type" not in result


@pytest.mark.asyncio
async def test_resource_description_used_when_present():
    provider = _MCPResourceCardProvider(
        _context([_meta(resource_desc="Resource specific desc", toolset_desc="Toolset desc")])
    )
    result = await provider.get_prompt_part()

    assert "Resource specific desc" in result
    assert "Toolset desc" not in result


@pytest.mark.asyncio
async def test_falls_back_to_toolset_description():
    provider = _MCPResourceCardProvider(
        _context([_meta(toolset_desc="Toolset fallback desc", resource_desc=None)])
    )
    result = await provider.get_prompt_part()

    assert "Toolset fallback desc" in result


@pytest.mark.asyncio
async def test_no_description_at_all():
    provider = _MCPResourceCardProvider(_context([_meta(toolset_desc=None, resource_desc=None)]))
    result = await provider.get_prompt_part()
    # Should not crash and should not contain a stray empty line from description
    lines = result.splitlines()
    assert all(line.strip() for line in lines)


@pytest.mark.asyncio
async def test_multiple_resources_joined_with_double_newline():
    metas = [
        _meta(name="A", uri="urn://a", toolset="ts1"),
        _meta(name="B", uri="urn://b", toolset="ts2"),
    ]
    provider = _MCPResourceCardProvider(_context(metas))
    result = await provider.get_prompt_part()

    assert "\n\n" in result
    assert "--- Resource: A (ts1) ---" in result
    assert "--- Resource: B (ts2) ---" in result
