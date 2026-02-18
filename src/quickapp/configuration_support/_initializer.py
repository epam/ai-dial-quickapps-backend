import logging

from fastapi import FastAPI
from injector import inject

from quickapp.common.base_initializer import StartupInitializer
from quickapp.configuration_support import _Controller


logger = logging.getLogger(__name__)

@inject
class _Initializer(StartupInitializer):

    def __init__(self, app: FastAPI, controller: _Controller):
        self.app = app
        self.controller = controller

    async def initialize(self) -> None:
        logger.debug(f"Initializing Configuration Support API")
        self.controller.register_routes(self.app)
