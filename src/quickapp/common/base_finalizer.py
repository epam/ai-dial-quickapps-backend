import logging
from abc import ABC, abstractmethod
from typing import ClassVar

from injector import Injector

logger = logging.getLogger(__name__)


# The BaseFinalizer class is an interface for components that release resources when the
# application stops. Implementations are contributed as a ``list[BaseFinalizer]`` multibinding
# and invoked once by invoke_finalizers, from the application lifespan.
class BaseFinalizer(ABC):

    # Lower values run earlier. Default 0 means "no preference"; ties are
    # broken by registration order (sort is stable).
    order: ClassVar[int] = 0

    @abstractmethod
    async def finalize(self) -> None:  # pragma: no cover
        ...


async def invoke_finalizers(injector: Injector) -> None:
    """Run every finalizer, isolating failures.

    A failing finalizer is logged and does not stop the others, and nothing it raises can mask
    the exception that is already unwinding the lifespan. ``CancelledError`` is a
    ``BaseException`` and so is deliberately not caught.
    """
    finalizers_type = list[BaseFinalizer]
    if not injector.binder.has_explicit_binding_for(finalizers_type):
        return
    for finalizer in sorted(injector.get(finalizers_type), key=lambda f: f.order):
        try:
            await finalizer.finalize()
        except Exception:
            logger.exception("Finalizer %s failed", type(finalizer).__name__)
