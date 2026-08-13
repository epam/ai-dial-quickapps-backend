from contextlib import AbstractAsyncContextManager
from typing import Annotated

AppLifespanParticipant = Annotated[AbstractAsyncContextManager[None], "app_lifespan"]
