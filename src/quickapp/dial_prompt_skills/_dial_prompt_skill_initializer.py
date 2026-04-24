import logging

from injector import ProviderOf, inject

from quickapp.common.base_initializer import CompletionInitializer
from quickapp.common.exceptions import SkillCatastrophicInitializationException
from quickapp.config.application import ApplicationConfig
from quickapp.config.skill import DialPromptSkillConfig
from quickapp.dial_prompt_skills._dial_prompt_skill_resolver import DialPromptSkillResolver
from quickapp.dial_prompt_skills._dial_prompt_skills_context import _DialPromptSkillsContext

logger = logging.getLogger(__name__)


@inject
class _DialPromptSkillInitializer(CompletionInitializer):
    """Eagerly resolves DIAL prompt skills during the initialization phase so
    the merged skill set is available to ``_AddSystemPromptTransformer`` when
    it runs in the post-initializer phase.

    Reads ``ApplicationConfig.skills`` via ``ProviderOf`` (config isn't set on
    ``_RequestContext`` until ``setup_context``, which always runs before
    initializers). Delegates to ``DialPromptSkillResolver`` and pushes the
    output into ``_DialPromptSkillsContext``.

    Resolver-level exceptions (not the per-URL ones — those go through
    ``asyncio.gather(return_exceptions=True)`` inside the resolver) are
    recorded as a ``SkillCatastrophicInitializationException`` so the unified
    handler flips the stage to FAILED.
    """

    def __init__(
        self,
        config_provider: ProviderOf[ApplicationConfig],
        resolver: DialPromptSkillResolver,
        context: _DialPromptSkillsContext,
    ) -> None:
        self._config_provider = config_provider
        self._resolver = resolver
        self._context = context

    async def initialize(self) -> None:
        skill_configs = self._config_provider.get().skills or []
        dial_prompt_configs = [
            cfg for cfg in skill_configs if isinstance(cfg, DialPromptSkillConfig)
        ]
        if not dial_prompt_configs:
            return

        try:
            output = await self._resolver.resolve(dial_prompt_configs)
        except Exception as exc:
            logger.exception("DIAL prompt skill resolution failed")
            self._context.append_exception(
                SkillCatastrophicInitializationException(
                    reason=f"Failed to resolve DIAL prompt skills: {exc}"
                )
            )
            return

        self._context.extend_resolved_skills(output.resolved)
        self._context.extend_exceptions(output.exceptions)
