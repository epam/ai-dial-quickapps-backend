# CLI script that dumps internal tool names/descriptors for lint drift detection.
#
# Collects every DI multiprovider named ``_provide_<feature>_tools`` (except
# ``_provide_mcp_tools``). Each entry includes ``name``, ``description``, and the
# parameter object schema
#
# Usage:
#   python dump_internal_tools.py docs/generated-internal-tools.json
#   python dump_internal_tools.py docs/generated-internal-tools.json --check

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

if __name__ == "__main__":
    from utils import add_src_to_system_path, load_env

    add_src_to_system_path()
    load_env()

from aidial_sdk.chat_completion import Message, Role
from fastapi import FastAPI
from fastapi_injector import RequestScopeFactory, RequestScopeOptions, attach_injector
from injector import Injector
from pydantic import SecretStr

from quickapp.app_factory import AppFactory
from quickapp.application._request_context import _RequestContext
from quickapp.common import StagedBaseTool
from quickapp.config.application import ApplicationConfig, Features, OrchestratorConfig
from quickapp.config.context import FileContextConfig
from quickapp.config.dial_deployment import DialDeploymentConfig, DialDeploymentParameters
from quickapp.config.dial_files import DialFilesConfig
from quickapp.config.prompt import CustomSystemPromptConfig
from quickapp.config.timestamp import ToolCallTimestampConfig


def build_dump_application_config() -> ApplicationConfig:
    """Synthetic config so gated multiproviders (e.g. timestamp) materialize tools."""
    return ApplicationConfig(
        orchestrator=OrchestratorConfig(
            deployment=DialDeploymentConfig(
                deployment_id="gpt-4o-mini-2024-07-18",
                parameters=DialDeploymentParameters(),
            ),
            system_prompt=CustomSystemPromptConfig(
                type="custom",
                content="dump-internal-tools",
                variables={},
            ),
        ),
        contexts=[
            FileContextConfig(
                url="files/dump-internal-tools/context.txt",
            ),
        ],
        tool_sets=[],
        features=Features(timestamp=ToolCallTimestampConfig(), dial_files=DialFilesConfig()),
    )


def _iter_staged_tool_providers(mod: object) -> Iterator[Callable[..., list[StagedBaseTool]]]:
    """Multiproviders named ``_provide_<feature>_tools`` except MCP (external protocol tools)."""
    for name in dir(type(mod)):
        if not name.startswith("_provide_") or not name.endswith("_tools"):
            continue
        if name == "_provide_mcp_tools":
            continue
        attr = getattr(mod, name, None)
        if callable(attr):
            yield attr


def _parameter_properties_and_required(parameters: Any) -> dict[str, Any]:
    """From OpenAI ``function.parameters``, emit only ``properties`` and ``required``."""
    raw = parameters.model_dump(mode="json", exclude_none=True)
    out: dict[str, Any] = {}
    if "properties" in raw:
        out["properties"] = raw["properties"]
    if raw.get("required"):
        out["required"] = raw["required"]
    return out


def _manifest_entry(tool: StagedBaseTool) -> dict[str, Any]:
    dumped = tool.model_dump(mode="python")
    fn = tool.tool_config.open_ai_tool.function
    name = dumped.get("name") or fn.name
    description = dumped.get("description")
    if description is None:
        description = fn.description or ""
    entry: dict[str, Any] = {
        "name": name,
        "description": description,
    }
    entry.update(_parameter_properties_and_required(fn.parameters))
    return entry


def _stable_manifest(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_name: dict[str, dict[str, Any]] = {}
    for entry in sorted(entries, key=lambda e: e["name"]):
        by_name[entry["name"]] = entry
    return list(by_name.values())


async def _gather_internal_tools_manifest() -> list[dict[str, Any]]:
    # Minimal DIAL URL so `DialSettings` and dependents validate without a real deployment.
    os.environ.setdefault("DIAL_URL", "http://dump-internal-tools.invalid")

    modules = AppFactory.build_di_modules()
    injector = Injector(modules)
    attach_injector(FastAPI(), injector, RequestScopeOptions())

    factory = injector.get(RequestScopeFactory)
    manifest_entries: list[dict[str, Any]] = []

    async with factory.create_scope():
        ctx = injector.get(_RequestContext)
        ctx.api_key = SecretStr("dump-internal-tools")
        ctx.bearer = None
        ctx.application_config = build_dump_application_config()
        # Non-empty: ``MessagesMixin.messages`` treats ``[]`` as unset (falsy guard).
        ctx.messages = [Message(role=Role.USER, content="dump-internal-tools")]

        for mod in modules:
            for provider in _iter_staged_tool_providers(mod):
                tools: list[StagedBaseTool] = injector.call_with_injection(provider)
                for tool in tools:
                    manifest_entries.append(_manifest_entry(tool))

    return _stable_manifest(manifest_entries)


def get_internal_tools_manifest_json() -> str:
    entries = asyncio.run(_gather_internal_tools_manifest())
    return json.dumps(entries, ensure_ascii=False, indent=2) + "\n"


def dump_internal_tools(output_file: str) -> None:
    generated = get_internal_tools_manifest_json()
    Path(output_file).write_text(generated, encoding="utf-8")
    print(f"Internal tools manifest dumped to {output_file}")


def check_internal_tools(output_file: str) -> None:
    generated = get_internal_tools_manifest_json()

    try:
        existing = Path(output_file).read_text(encoding="utf-8")
    except FileNotFoundError:
        print(
            f"ERROR: Internal tools file '{output_file}' not found. "
            f"Run 'make format' to generate it."
        )
        sys.exit(1)

    if generated != existing:
        print(
            f"ERROR: Internal tools file '{output_file}' is out of date. "
            f"Run 'make format' to regenerate it."
        )
        sys.exit(1)

    print(f"Internal tools file '{output_file}' is up to date.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Dump internal tools manifest to a file.")
    parser.add_argument(
        "output_file",
        type=str,
        help="The output file path for the JSON manifest.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check that the file matches the generated manifest instead of overwriting.",
    )
    args = parser.parse_args()

    if args.check:
        check_internal_tools(args.output_file)
    else:
        dump_internal_tools(args.output_file)
