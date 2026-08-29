import logging

from injector import ProviderOf, inject

from quickapp.common.base_initializer import CompletionInitializer
from quickapp.common.exceptions import SkillCatastrophicInitializationException
from quickapp.config.application import ApplicationConfig
from quickapp.config.skill import DialSkillConfig, enumerate_skill_configs
from quickapp.dial_skills._dial_skill_resolver import DialSkillResolver
from quickapp.dial_skills._dial_skills_context import _DialSkillsContext

logger = logging.getLogger(__name__)


@inject
class _DialSkillInitializer(CompletionInitializer):
    """Eagerly resolves DIAL skill resources during the initialization phase so
    the merged skill set is available to ``_AddSystemPromptTransformer`` when
    it runs in the post-initializer phase.

    Reads ``ApplicationConfig.skills`` via ``ProviderOf`` (config isn't set on
    ``_RequestContext`` until ``setup_context``, which always runs before
    initializers). Delegates to ``DialSkillResolver`` and pushes the output
    into ``_DialSkillsContext``.

    Resolver-level exceptions (not the per-URL ones — those go through
    ``asyncio.gather(return_exceptions=True)`` inside the resolver) are
    recorded as a ``SkillCatastrophicInitializationException`` so the unified
    handler flips the stage to FAILED.
    """

    def __init__(
        self,
        config_provider: ProviderOf[ApplicationConfig],
        resolver: DialSkillResolver,
        context: _DialSkillsContext,
    ) -> None:
        self._config_provider = config_provider
        self._resolver = resolver
        self._context = context

    async def initialize(self) -> None:
        dial_skill_configs = enumerate_skill_configs(
            self._config_provider.get().skills, DialSkillConfig
        )
        if not dial_skill_configs:
            return

        try:
            output = await self._resolver.resolve(dial_skill_configs)
        except Exception as exc:
            logger.exception("DIAL skill resolution failed")
            self._context.append_exception(
                SkillCatastrophicInitializationException(
                    reason=f"Failed to resolve DIAL skills: {exc}"
                )
            )
            return

        self._context.extend_resolved_skills(output.resolved)
        self._context.extend_exceptions(output.exceptions)
