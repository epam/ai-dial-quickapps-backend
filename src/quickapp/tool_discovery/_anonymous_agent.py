import json
import logging

import openai
from injector import inject

from quickapp.common import ORCHESTRATOR_AZURE_CLIENT
from quickapp.config.application import ApplicationConfig

logger = logging.getLogger(__name__)

_ROUTING_SYSTEM_PROMPT = (
    "You are a tool routing assistant. "
    "Given a user query, return the names of the tools from the provided catalog "
    "that are most relevant to fulfilling that query. "
    "Respond with a JSON array of tool name strings only — no explanation, no markdown. "
    "Example: [\"tool_a\", \"tool_b\"]\n\n"
    "Catalog:\n{catalog}"
)


@inject
class _AnonymousAgent:
    """Fires an isolated, non-streaming LLM call to route a query against the deferred tool catalog.

    No conversation history or application system prompt is included — token cost is bounded
    by the catalog size alone.
    """

    def __init__(
        self,
        client: ORCHESTRATOR_AZURE_CLIENT,
        config: ApplicationConfig,
    ) -> None:
        self.__client = client
        self.__config = config

    async def route(self, query: str, catalog: list[dict[str, str]]) -> list[str]:
        """Return tool names from catalog that best match query."""
        if not catalog:
            return []

        discovery = self.__config.orchestrator.tool_discovery
        if discovery is None:
            logger.warning(
                "Anonymous agent routing call invoked while tool_discovery is disabled — "
                "returning no matches"
            )
            return []
        service_model = (
            discovery.service_model or self.__config.orchestrator.deployment.deployment_id
        )

        catalog_text = "\n".join(
            f"- {entry['name']}: {entry.get('description', '')}" for entry in catalog
        )
        system_content = _ROUTING_SYSTEM_PROMPT.format(catalog=catalog_text)

        try:
            response = await self.__client.chat.completions.create(
                model=service_model,
                messages=[
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": query},
                ],
                stream=False,
            )
        except openai.OpenAIError:
            logger.exception("Anonymous agent routing call failed")
            return []

        raw = (response.choices[0].message.content or "").strip()
        try:
            names = json.loads(raw)
            if isinstance(names, list):
                return [n for n in names if isinstance(n, str)]
        except (json.JSONDecodeError, ValueError):
            logger.warning("Anonymous agent returned non-JSON response (length=%d)", len(raw))
        return []
