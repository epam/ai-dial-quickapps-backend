import argparse
import json
import logging
import os

import requests as rq
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic.alias_generators import to_camel

if __name__ == '__main__':
    from utils import add_src_to_system_path, load_env

    add_src_to_system_path()
    load_env()

from utils import replace_env

MODEL_TYPE_TO_PATH = {
    "chat": "/chat/completions",
    "embedding": "/embeddings",
}

logger = logging.getLogger(__name__)


REMOTE_DIAL_URL = os.getenv("REMOTE_DIAL_URL")
REMOTE_DIAL_API_KEY = os.getenv("REMOTE_DIAL_API_KEY")
if not REMOTE_DIAL_URL or not REMOTE_DIAL_API_KEY:
    raise ValueError("REMOTE_DIAL_URL and REMOTE_DIAL_API_KEY must be set in .env")


class DIALBaseModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


class DIALModelCapabilities(DIALBaseModel):
    scale_types: list[str]
    completion: bool
    chat_completion: bool
    embeddings: bool
    fine_tune: bool
    inference: bool


class DIALDeploymentBase(DIALBaseModel):
    id: str = Field(description="The deployment ID")
    display_name: str | None = Field(None, description="The deployment display name")
    display_version: str | None = Field(None, description="The model display version")
    icon_url: str | None = Field(None, description="The deployment icon URL")
    description: str | None = Field(None, description="The deployment description")
    description_keywords: list[str] | None = Field(
        None, description="The deployment description keywords"
    )
    input_attachment_types: list[str] | None = Field(
        None, description="The deployment input attachment types"
    )


class DIALLimits(DIALBaseModel):
    max_total_tokens: int | None = Field(None, description="The maximum total tokens")


class DIALModelPricing(DIALBaseModel):
    unit: str | None = Field(default=None, description="The pricing unit")
    prompt: str | None = Field(default=None, description="The pricing prompt")
    completion: str | None = Field(description="The pricing completion", default=None)


class DIALModelFeatures(DIALBaseModel):
    rate: bool = False
    tokenize: bool = False
    truncate_prompt: bool = False
    configuration: bool = False
    system_prompt: bool = False
    tools: bool = False
    seed: bool = False
    url_attachments: bool = False
    folder_attachments: bool = False

    def to_config(self) -> dict:
        value = {
            "systemPromptSupported": self.system_prompt,
            "toolsSupported": self.tools,
            "urlAttachmentsSupported": self.url_attachments,
            "folderAttachmentsSupported": self.folder_attachments,
        }
        return {key: value for key, value in value.items() if value}


class DIALModel(DIALDeploymentBase):
    tokenizer_model: str | None = Field(description="The model tokenizer model", default=None)
    capabilities: DIALModelCapabilities = Field(description="The model capabilities")
    limits: DIALLimits | None = Field(None, description="The model limits")
    features: DIALModelFeatures = Field(description="The model features")
    pricing: DIALModelPricing | None = Field(None, description="The model pricing")


class DIALApplication(DIALDeploymentBase):
    application: str = Field(description="The application name")
    features: DIALModelFeatures = Field(description="The model features")


def get_dial_models() -> list[dict]:
    url = f"{REMOTE_DIAL_URL}/openai/models"
    headers = {"Api-Key": REMOTE_DIAL_API_KEY}
    response = rq.get(url, headers=headers)
    response.raise_for_status()
    return response.json()["data"]


def get_dial_applications() -> list[dict]:
    url = f"{REMOTE_DIAL_URL}/openai/applications"
    headers = {"Api-Key": REMOTE_DIAL_API_KEY}
    response = rq.get(url, headers=headers)
    response.raise_for_status()
    return response.json()["data"]


def replace_envs(config_models: dict):
    for model_id, model_config in config_models.items():
        upstreams = model_config["upstreams"]
        for upstream in upstreams:
            upstream["endpoint"] = replace_env(upstream["endpoint"])
            upstream["key"] = replace_env(upstream["key"])
    return config_models


def to_config_model(model: dict) -> tuple[str, dict] | None:
    try:
        parsed_model = DIALModel.model_validate(model)

        capabilities = parsed_model.capabilities
        if capabilities.chat_completion:
            type_ = "chat"
        elif capabilities.embeddings:
            type_ = "embedding"
        else:
            print(
                f"Skipping model={parsed_model.id}: unsupported deployment type, capabilities: {parsed_model.capabilities}"
            )
            return None
        model_config = {
            "type": type_,
            "endpoint": f"http://adapter-dial:5000/openai/deployments/{parsed_model.id}{MODEL_TYPE_TO_PATH[type_]}",
            "upstreams": [
                {
                    "endpoint": f"{REMOTE_DIAL_URL}/openai/deployments/{parsed_model.id}{MODEL_TYPE_TO_PATH[type_]}",
                    "key": REMOTE_DIAL_API_KEY,
                }
            ],
        }
        serialized = parsed_model.model_dump(
            exclude_none=True, exclude_defaults=True, by_alias=True
        )
        for field in [
            "displayName",
            "displayVersion",
            "description",
            "descriptionKeywords",
            "iconUrl",
            "inputAttachmentTypes",
            "tokenizerModel",
            "limits",
            "pricing",
        ]:
            if field in serialized:
                value = serialized[field]
                if value:
                    model_config[field] = value
        if parsed_model.features:
            model_config["features"] = parsed_model.features.to_config()  # type: ignore
        return parsed_model.id, model_config
    except ValidationError:
        logger.exception(f"Validation failed for: {str(model)}")
    return None


def to_config_application(application: dict) -> tuple[str, dict]:
    parsed_application = DIALApplication.model_validate(application)
    application_config = {
        "type": "chat",
        "endpoint": f"http://adapter-dial:5000/openai/deployments/{parsed_application.id}/chat/completions",
        "upstreams": [
            {
                "endpoint": f"{REMOTE_DIAL_URL}/openai/deployments/{parsed_application.id}/chat/completions",
                "key": REMOTE_DIAL_API_KEY,
            }
        ],
    }
    serialized = parsed_application.model_dump(
        exclude_none=True, exclude_defaults=True, by_alias=True
    )
    for field in [
        "displayName",
        "displayVersion",
        "description",
        "descriptionKeywords",
        "iconUrl",
        "inputAttachmentTypes",
    ]:
        if field in serialized:
            value = serialized[field]
            if value:
                application_config[field] = value
    return parsed_application.id, application_config


def get_config_template(path: str) -> dict:
    with open(path, "r") as fin:
        return json.load(fin)


def generate_config(models: bool, template_path: str, config_path: str, app_ids: set[str]):
    config_template = get_config_template(template_path)
    replace_envs(config_template["models"])
    if models:
        dial_models = get_dial_models()
        config_models = [to_config_model(model) for model in dial_models]
        config_models = [model for model in config_models if model]
        config_models = {model_id: config_model for model_id, config_model in config_models}  # type: ignore
        config_template["models"].update(config_models)
    if app_ids:
        dial_applications = get_dial_applications()
        config_applications = {
            application_id: config_application
            for application_id, config_application in (
                to_config_application(application) for application in dial_applications
            )
            if application_id in app_ids
        }
        config_template["models"].update(config_applications)
    limits: dict = config_template["roles"]["default"]["limits"]
    limits.clear()
    limits.update(
        {
            **{model_id: {} for model_id in config_template["models"].keys()},
            **{app_id: {} for app_id in config_template["applications"].keys()},
        }
    )
    # create subfolders for config if not exists


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog="DIALConfigGenerator",
        description="Generate DIAL config file",
    )
    parser.add_argument(
        "-m", "--models", action="store_true", help="Whether to include models in the config"
    )
    parser.add_argument("-t", "--template")
    parser.add_argument("-c", "--config")
    parser.add_argument("-a", "--applications", required=False)
    args = parser.parse_args()
    app_ids = set(args.applications.split(",")) if args.applications else set()
    generate_config(args.models, args.template, args.config, app_ids)
