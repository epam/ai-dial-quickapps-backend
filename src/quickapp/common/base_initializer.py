from abc import ABC, abstractmethod
from enum import Enum
from typing import Annotated, ClassVar

from injector import Injector


class InitializerType(str, Enum):
    completion = "completion"
    configuration = "configuration"
    startup = "startup"


# The BaseInitializer class is an interface for components that handle asynchronous initialization.
# The InitializerType decides when an implementation runs:
# - completion: per request, invoked by _QuickAppCompletion before the BaseAgent implementation is
#   instantiated, so dynamic data can be injected into the dependency container for the classes
#   involved in the agent creation process;
# - configuration: per request, once the app configuration is resolved;
# - startup: once, when the application starts.
# Teardown at application stop is a separate contract: BaseFinalizer.
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
