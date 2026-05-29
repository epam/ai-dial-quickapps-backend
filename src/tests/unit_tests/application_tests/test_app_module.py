from unittest.mock import MagicMock

from quickapp.application.app_module import AppModule
from quickapp.config.application import StageDisplayLevel
from quickapp.config_resolvers.stage_display_resolver import StageDisplayResolver


class TestProvideStageDisplayLevel:
    def _call(self, resolver: StageDisplayResolver) -> StageDisplayLevel:
        module = AppModule()
        return module._AppModule__provide_stage_display_level(resolver)  # type: ignore[attr-defined]

    def test_delegates_to_resolver(self):
        resolver = MagicMock(spec=StageDisplayResolver)
        resolver.resolve.return_value = StageDisplayLevel.DEBUG
        assert self._call(resolver) == StageDisplayLevel.DEBUG
