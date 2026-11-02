import logging
from collections.abc import Mapping, Sequence

import openai
from injector import inject
from openai.types import CompletionUsage
from pydantic import BaseModel, Field

from quickapp.common import DEPLOYMENT_AZURE_CLIENT
from quickapp.common.deployment_usage import ModelUsage
from quickapp.config.application import ApplicationConfig
from quickapp.tool_discovery._routing_prompt import (
    SelectionKind,
    build_system_prompt,
    build_user_prompt,
    parse_selection,
)

logger = logging.getLogger(__name__)


class RoutingResult(BaseModel):
    names: list[str] = Field(default_factory=list)
    usage: ModelUsage | None = None

    def with_usage(self, usage: ModelUsage | None) -> "RoutingResult":
        return RoutingResult(names=self.names, usage=usage)


@inject
class _AnonymousAgent:
    """Fires an isolated, non-streaming LLM call to route a query against a catalog.

    No conversation history or application system prompt is included — token cost is bounded
    by the catalog size alone. The call is fail-open: errors and unparsable answers yield `[]`.
    """

    def __init__(
        self,
        # The orchestrator client is pinned to the orchestrator deployment, which would make the
        # `model` kwarg below a no-op; the unpinned deployment client honours service_model.
        client: DEPLOYMENT_AZURE_CLIENT,
        config: ApplicationConfig,
    ) -> None:
        self.__client = client
        self.__config = config

    async def route(
        self,
        query: str,
        catalog: Sequence[Mapping[str, object]],
        *,
        kind: SelectionKind,
        limit: int,
        threshold: float,
    ) -> RoutingResult:
        """Return up to `limit` catalog names scoring at least `threshold`, best match first."""
        if not catalog:
            return RoutingResult()

        discovery = self.__config.orchestrator.tool_discovery
        if discovery is None:
            logger.warning(
                "Anonymous agent routing call invoked while tool_discovery is disabled — "
                "returning no matches"
            )
            return RoutingResult()
        service_model = (
            discovery.service_model or self.__config.orchestrator.deployment.deployment_id
        )

        try:
            response = await self.__client.chat.completions.create(
                model=service_model,
                messages=[
                    {"role": "system", "content": build_system_prompt(catalog, kind, limit)},
                    {"role": "user", "content": build_user_prompt(query)},
                ],
                stream=False,
            )
        except openai.OpenAIError:
            logger.exception("Anonymous agent routing call failed")
            return RoutingResult()

        usage = _to_model_usage(service_model, response.usage)
        raw = (response.choices[0].message.content or "").strip()
        known_names = {str(entry["name"]) for entry in catalog}
        picked = parse_selection(raw, known_names, limit=limit, threshold=threshold)
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Routing call found %d of %d %ss (threshold=%s): %s",
                len(picked),
                len(catalog),
                kind,
                threshold,
                ", ".join(f"{item.name}={item.score:.2f}" for item in picked) or "none",
            )
        return RoutingResult(names=[item.name for item in picked], usage=usage)


def _to_model_usage(model: str, usage: CompletionUsage | None) -> ModelUsage | None:
    if usage is None:
        return None
    return ModelUsage(
        model=model,
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
    )
