from abc import ABC, abstractmethod
from enum import Enum
from typing import Annotated

from injector import Injector


class InitializerType(str, Enum):
    completion = "completion"
    configuration = "configuration"
    startup = "startup"


# The BaseInitializer class is an interface for components that handle asynchronous initialization
# before the agent is created. All instances of this class are invoked by _QuickAppCompletion
# before the BaseAgent implementation is instantiated. This allows dynamic data to be injected
# into the dependency container, making it accessible to classes involved in the agent creation process.
class BaseInitializer(ABC):

    @abstractmethod
    async def initialize(self) -> None:  # pragma: no cover
        ...


CompletionInitializer = Annotated[BaseInitializer, InitializerType.completion]
ConfigurationInitializer = Annotated[BaseInitializer, InitializerType.configuration]
StartupInitializer = Annotated[BaseInitializer, InitializerType.startup]


async def invoke_initializers(injector: Injector, initializer_type: InitializerType) -> None:
    initializer_type_to_get = list[Annotated[BaseInitializer, initializer_type]]
    if injector.binder.has_explicit_binding_for(initializer_type_to_get):
        for initializer in injector.get(initializer_type_to_get):
            await initializer.initialize()
