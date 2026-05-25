from injector import Binder, Injector

from quickapp.attachment_processing._legacy_user_image_keep_policy import _LegacyUserImageKeepPolicy
from quickapp.attachment_processing.attachment_processing_module import AttachmentProcessingModule
from quickapp.common.abstract.tool_attachment_keep_policy import AttachmentKeepPolicy
from quickapp.config.application import ApplicationConfig
from quickapp.config.orchestrator_attachment_strategy import LazyOnDemandAttachmentStrategy
from tests.unit_tests.common.common import create_app_configuration


def _injector_with(app_config: ApplicationConfig) -> Injector:
    def configure(binder: Binder) -> None:
        binder.bind(ApplicationConfig, to=app_config)

    return Injector([AttachmentProcessingModule, configure])


def test_legacy_policy_provided_when_no_attachment_strategy():
    app_config = create_app_configuration([])
    app_config.orchestrator.attachment_strategy = None

    injector = _injector_with(app_config)
    policies = injector.get(list[AttachmentKeepPolicy])

    assert len(policies) == 1
    assert isinstance(policies[0], _LegacyUserImageKeepPolicy)


def test_legacy_policy_omitted_when_lazy_strategy_set():
    app_config = create_app_configuration([])
    app_config.orchestrator.attachment_strategy = LazyOnDemandAttachmentStrategy()

    injector = _injector_with(app_config)
    policies = injector.get(list[AttachmentKeepPolicy])

    assert policies == []
