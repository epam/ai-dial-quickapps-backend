from injector import Module, inject, multiprovider

from quickapp.application import Configuration
from quickapp.config.application import ApplicationConfig
from quickapp.starters.button import _Button, _create_buttons


class StartersModule(Module):

    @inject
    @multiprovider
    def __provide_starters(self, app_config: ApplicationConfig) -> list[Configuration]:
        if not app_config.starters:
            return []
        buttons = [
            _Button(value=i + 1, caption=starter, populateText=starter)
            for i, starter in enumerate(app_config.starters)
        ]
        return [Configuration(_create_buttons(buttons=buttons))]
