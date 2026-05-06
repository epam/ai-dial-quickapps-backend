from abc import ABC, abstractmethod
from enum import Enum
from typing import Annotated, ClassVar

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

    # Lower values run earlier. Default 0 means "no preference"; ties are
    # broken by registration order (sort is stable). Producers that other
    # initializers depend on should declare a negative order.
    order: ClassVar[int] = 0

    @abstractmethod
    async def initialize(self) -> None:  # pragma: no cover
        ...


CompletionInitializer = Annotated[BaseInitializer, InitializerType.completion]
ConfigurationInitializer = Annotated[BaseInitializer, InitializerType.configuration]
StartupInitializer = Annotated[BaseInitializer, InitializerType.startup]


async def invoke_initializers(injector: Injector, initializer_type: InitializerType) -> None:
    initializer_type_to_get = list[Annotated[BaseInitializer, initializer_type]]
    if injector.binder.has_explicit_binding_for(initializer_type_to_get):
        initializers = sorted(injector.get(initializer_type_to_get), key=lambda i: i.order)
        for initializer in initializers:
            await initializer.initialize()
