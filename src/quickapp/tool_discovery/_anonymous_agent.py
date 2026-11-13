import logging
from collections.abc import Sequence

import openai
from injector import inject
from openai.types import CompletionUsage
from openai.types.chat import (
    ChatCompletion,
    ChatCompletionSystemMessageParam,
    ChatCompletionUserMessageParam,
)

from quickapp.common import DEPLOYMENT_AZURE_CLIENT
from quickapp.common.deployment_usage import ModelUsage
from quickapp.config.application import ApplicationConfig
from quickapp.tool_discovery._routing_prompt import (
    CatalogItem,
    ScoredName,
    SelectionKind,
    build_response_format,
    build_system_prompt,
    build_user_prompt,
    parse_selection,
)
from quickapp.tool_discovery._routing_result import RoutingResult

logger = logging.getLogger(__name__)


@inject
class _AnonymousAgent:
    """Fires an isolated, non-streaming LLM call to route a query against a catalog.

    No conversation history or application system prompt is included — token cost is bounded
    by the catalog size alone. The call always requests structured output (`response_format`),
    so `tool_discovery.service_model` must support it. The call is fail-open: errors and
    unparsable answers yield `[]`. A 400 answer (typically a model without structured output
    support) is also reported as a warning on the returned `RoutingResult`.
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
        catalog: Sequence[CatalogItem],
        *,
        kind: SelectionKind,
        limit: int,
        threshold: float,
    ) -> RoutingResult:
        """Return up to `limit` catalog names scoring at least `threshold`, best match first."""
        if not catalog:
            return RoutingResult()

        discovery = self.__config.orchestrator.tool_discovery
        service_model = discovery.service_model if discovery is not None else None
        if not service_model:
            logger.warning(
                "Anonymous agent routing call invoked while tool_discovery is disabled — "
                "returning no matches"
            )
            return RoutingResult()

        try:
            response = await self._request(service_model, query, catalog, kind, limit)
        except openai.BadRequestError as exc:
            return _rejected(service_model, exc)
        except openai.OpenAIError:
            logger.exception("Anonymous agent routing call failed")
            return RoutingResult()

        if not response.choices:
            logger.warning("Anonymous agent routing call returned no choices")
            return RoutingResult(usage=_to_model_usage(service_model, response.usage))

        raw = (response.choices[0].message.content or "").strip()
        known_names = {entry["name"] for entry in catalog}
        picked = parse_selection(raw, known_names, limit=limit, threshold=threshold)
        _log_selection(picked, len(catalog), kind, threshold)
        return RoutingResult(
            names=[item.name for item in picked],
            usage=_to_model_usage(service_model, response.usage),
        )

    async def _request(
        self,
        service_model: str,
        query: str,
        catalog: Sequence[CatalogItem],
        kind: SelectionKind,
        limit: int,
    ) -> ChatCompletion:
        return await self.__client.chat.completions.create(
            model=service_model,
            messages=[
                ChatCompletionSystemMessageParam(
                    role="system", content=build_system_prompt(catalog, kind, limit)
                ),
                ChatCompletionUserMessageParam(role="user", content=build_user_prompt(query)),
            ],
            response_format=build_response_format(),
            stream=False,
        )


def _rejected(service_model: str, exc: openai.BadRequestError) -> RoutingResult:
    # The exception text carries the response body, so log only the status.
    logger.warning("Anonymous agent routing call was rejected (status=%s)", exc.status_code)
    detail = exc.body.get("error", {}).get("message") if isinstance(exc.body, dict) else None
    return RoutingResult(
        warnings=[
            f"Routing model '{service_model}' rejected the request: {detail or 'bad request'}. "
            "A possible cause is that `tool_discovery.service_model` does not support "
            "structured output."
        ]
    )


def _log_selection(
    picked: list[ScoredName], catalog_size: int, kind: SelectionKind, threshold: float
) -> None:
    if not logger.isEnabledFor(logging.DEBUG):
        return
    logger.debug(
        "Routing call found %d of %d %ss (threshold=%s): %s",
        len(picked),
        catalog_size,
        kind,
        threshold,
        ", ".join(f"{item.name}={item.score:.2f}" for item in picked) or "none",
    )


def _to_model_usage(model: str, usage: CompletionUsage | None) -> ModelUsage | None:
    if usage is None:
        return None
    return ModelUsage(
        model=model,
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
    )
