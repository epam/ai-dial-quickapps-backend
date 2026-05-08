from unittest.mock import AsyncMock, MagicMock

import pytest

from quickapp.dial_core_services.dial_file_service import DialFileService


def _make_mock_dial_client() -> MagicMock:
    mock_resource_permissions = MagicMock()
    mock_resource_permissions.grant = AsyncMock(return_value=None)

    mock_dial_client = MagicMock()
    mock_dial_client.resource_permissions = mock_resource_permissions
    return mock_dial_client


def _make_service(dial_client: MagicMock | None = None) -> DialFileService:
    return DialFileService(dial_client=dial_client or _make_mock_dial_client())


class TestGrantPermissions:
    @pytest.mark.asyncio
    async def test_grant_permissions_calls_client(self):
        client = _make_mock_dial_client()
        svc = _make_service(dial_client=client)

        await svc.grant_permissions_to_files(["files/a.txt", "files/b.txt"], "my-toolset")

        client.resource_permissions.grant.assert_awaited_once_with(
            resources=["files/a.txt", "files/b.txt"],
            receiver="my-toolset",
        )

    @pytest.mark.asyncio
    async def test_grant_permissions_propagates_failure(self):
        client = _make_mock_dial_client()
        client.resource_permissions.grant.side_effect = RuntimeError("boom")
        svc = _make_service(dial_client=client)

        with pytest.raises(RuntimeError, match="boom"):
            await svc.grant_permissions_to_files(["files/x.txt"], "toolset")
