from injector import ProviderOf, inject

from quickapp.common.model_hidden_tool import ModelHiddenTool
from quickapp.common.staged_base_tool import StagedBaseTool


@inject
class HookToolRegistry:
    """The tools a hook can call: model-visible tools together with model-hidden ones."""

    def __init__(
        self,
        visible_tools_provider: ProviderOf[list[StagedBaseTool]],
        model_hidden_tools_provider: ProviderOf[list[ModelHiddenTool]],
    ) -> None:
        self._visible_tools_provider = visible_tools_provider
        self._model_hidden_tools_provider = model_hidden_tools_provider

    @property
    def tools(self) -> list[StagedBaseTool]:
        return [*self._visible_tools_provider.get(), *self._model_hidden_tools_provider.get()]
