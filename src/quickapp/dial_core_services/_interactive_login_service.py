import asyncio
import json
import logging

import httpx
from httpx_sse import aconnect_sse
from injector import inject

from quickapp.common import CLIENT_CHANNEL_ID, DIAL_API_KEY
from quickapp.common.di_types import CLIENT_CHANNEL_HEADER
from quickapp.common.dial_settings import DialSettings
from quickapp.dial_core_services._interactive_login_settings import InteractiveLoginSettings
from quickapp.dial_core_services._login_result import LoginResult

logger = logging.getLogger(__name__)

_INTERACT_PATH = "/v1/ops/client-channel/interact"


@inject
class InteractiveLoginService:
    """Coordinates interactive sign-in via DIAL Core's client channel mechanism."""

    def __init__(
        self,
        api_key: DIAL_API_KEY,
        dial_settings: DialSettings,
        client_channel_id: CLIENT_CHANNEL_ID,
        settings: InteractiveLoginSettings,
    ):
        self.__api_key = api_key
        self.__dial_settings = dial_settings
        self.__client_channel_id = client_channel_id
        self.__settings = settings

    async def request_signin_batch(self, toolset_dial_ids: list[str]) -> dict[str, LoginResult]:
        """Request interactive sign-in for multiple toolsets in a single batch.

        Returns a dict mapping each dial_id to its LoginResult.
        This method never raises exceptions — all failures are mapped to LoginResult values.
        """
        if self.__client_channel_id is None:
            logger.info(
                "Interactive login skipped: no client channel ID. Toolsets: %s",
                toolset_dial_ids,
            )
            return {tid: LoginResult.NO_CHANNEL for tid in toolset_dial_ids}

        id_to_dial_id: dict[str, str] = {}
        rpc_batch: list[dict] = []
        for idx, dial_id in enumerate(toolset_dial_ids, start=1):
            rpc_id = str(idx)
            id_to_dial_id[rpc_id] = dial_id
            rpc_batch.append(
                {
                    "jsonrpc": "2.0",
                    "method": "toolset/signin",
                    "params": {"toolsetId": dial_id},
                    "id": rpc_id,
                }
            )

        logger.info(
            "Requesting interactive login for toolsets %s (channel: %s)",
            toolset_dial_ids,
            self.__client_channel_id,
        )

        try:
            return await asyncio.wait_for(
                self._do_interact(rpc_batch, id_to_dial_id, toolset_dial_ids),
                timeout=self.__settings.interactive_login_timeout_seconds,
            )
        except TimeoutError:
            logger.info(
                "Interactive login timed out after %ss for toolsets %s",
                self.__settings.interactive_login_timeout_seconds,
                toolset_dial_ids,
            )
            return {tid: LoginResult.TIMEOUT for tid in toolset_dial_ids}
        except Exception:
            logger.exception("Interactive login failed for toolsets %s", toolset_dial_ids)
            return {tid: LoginResult.ERROR for tid in toolset_dial_ids}

    async def _do_interact(
        self,
        rpc_batch: list[dict],
        id_to_dial_id: dict[str, str],
        toolset_dial_ids: list[str],
    ) -> dict[str, LoginResult]:
        """Execute the interact call and parse the SSE response."""
        assert self.__client_channel_id is not None  # guaranteed by caller
        async with httpx.AsyncClient(
            base_url=self.__dial_settings.url,
            headers={
                "Api-Key": self.__api_key.get_secret_value(),
                CLIENT_CHANNEL_HEADER: self.__client_channel_id,
            },
            timeout=httpx.Timeout(5.0, read=None),
        ) as client:
            async with aconnect_sse(client, "POST", _INTERACT_PATH, json=rpc_batch) as event_source:
                event_source.response.raise_for_status()

                async for sse_event in event_source.aiter_sse():
                    if sse_event.data:
                        return self._parse_batch_response(
                            sse_event.data, id_to_dial_id, toolset_dial_ids
                        )

        # Stream ended without a data event
        logger.warning(
            "Interactive login SSE stream ended without data for toolsets %s", toolset_dial_ids
        )
        return {tid: LoginResult.ERROR for tid in toolset_dial_ids}

    @staticmethod
    def _parse_batch_response(
        data: str,
        id_to_dial_id: dict[str, str],
        toolset_dial_ids: list[str],
    ) -> dict[str, LoginResult]:
        """Parse a JSON-RPC batch response and map to LoginResult per dial_id."""
        try:
            entries = json.loads(data)
        except (json.JSONDecodeError, TypeError):
            logger.exception("Failed to parse interactive login response: %s", data)
            return {tid: LoginResult.ERROR for tid in toolset_dial_ids}

        if not isinstance(entries, list):
            entries = [entries]

        result_map: dict[str, LoginResult] = {}
        for entry in entries:
            rpc_id = entry.get("id")
            dial_id = id_to_dial_id.get(str(rpc_id)) if rpc_id is not None else None
            if dial_id is None:
                continue

            if "error" in entry:
                result_map[dial_id] = LoginResult.ERROR
            elif entry.get("result") == "success":
                result_map[dial_id] = LoginResult.SUCCESS
            else:
                result_map[dial_id] = LoginResult.DENIED

        # Fill in any missing entries as ERROR
        for tid in toolset_dial_ids:
            if tid not in result_map:
                result_map[tid] = LoginResult.ERROR

        logger.info("Interactive login results: %s", result_map)
        return result_map

    async def request_signin(self, toolset_dial_id: str) -> LoginResult:
        """Request interactive sign-in for a single toolset. Convenience wrapper."""
        results = await self.request_signin_batch([toolset_dial_id])
        return results[toolset_dial_id]
