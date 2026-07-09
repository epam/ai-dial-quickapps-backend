# CLI script that dumps the configuration-support OpenAPI spec for lint drift detection.
#
# Usage:
#   python dump_config_support_openapi.py docs/generated-config-support-openapi.json
#   python dump_config_support_openapi.py docs/generated-config-support-openapi.json --check

import json
import os
import sys
from pathlib import Path

if __name__ == "__main__":
    from utils import add_src_to_system_path, load_env

    add_src_to_system_path()
    load_env()

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from injector import Injector

from quickapp.app_factory import AppFactory
from quickapp.configuration_support._controller import CONFIG_SUPPORT_URI, _Controller

CONFIG_SUPPORT_OPENAPI_TITLE = "QuickApps Configuration Support API"
CONFIG_SUPPORT_OPENAPI_VERSION = "1.0.0"


def _set_env_if_empty(name: str, value: str) -> None:
    if not os.getenv(name):
        os.environ[name] = value


def get_config_support_openapi_schema() -> dict:
    _set_env_if_empty("DIAL_URL", "http://dump-config-support-openapi.invalid")
    _set_env_if_empty("OPENAI_API_KEY", "dump-config-support-openapi")
    _set_env_if_empty("OPENAI_ADMIN_KEY", "dump-config-support-openapi")

    injector = Injector(AppFactory.build_di_modules())
    app = injector.get(FastAPI)
    controller = injector.get(_Controller)
    controller.register_routes(app)

    routes = [
        route for route in app.routes if getattr(route, "path", "").startswith(CONFIG_SUPPORT_URI)
    ]

    return get_openapi(
        title=CONFIG_SUPPORT_OPENAPI_TITLE,
        version=CONFIG_SUPPORT_OPENAPI_VERSION,
        routes=routes,
    )


def get_config_support_openapi_json() -> str:
    schema = get_config_support_openapi_schema()
    return json.dumps(schema, ensure_ascii=False, indent=2) + "\n"


def dump_config_support_openapi(output_file: str) -> None:
    generated = get_config_support_openapi_json()
    Path(output_file).write_text(generated, encoding="utf-8")
    print(f"Configuration support OpenAPI spec dumped to {output_file}")


def check_config_support_openapi(output_file: str) -> None:
    generated = get_config_support_openapi_json()

    try:
        existing = Path(output_file).read_text(encoding="utf-8")
    except FileNotFoundError:
        print(
            f"ERROR: OpenAPI file '{output_file}' not found. " f"Run 'make format' to generate it."
        )
        sys.exit(1)

    if generated != existing:
        print(
            f"ERROR: OpenAPI file '{output_file}' is out of date. "
            f"Run 'make format' to regenerate it."
        )
        sys.exit(1)

    print(f"OpenAPI file '{output_file}' is up to date.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Dump configuration-support OpenAPI spec to a file."
    )
    parser.add_argument(
        "output_file",
        type=str,
        help="The output file path for the OpenAPI JSON.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check that the file matches the generated spec instead of overwriting.",
    )
    args = parser.parse_args()

    if args.check:
        check_config_support_openapi(args.output_file)
    else:
        dump_config_support_openapi(args.output_file)
