"""How tool-call arguments are rendered into a Choice stage while streaming."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from aidial_sdk.chat_completion import Stage

from quickapp.common.chat_completion_stream.json_object_argument_streamer import (
    ArgumentStreamEvent,
    JsonObjectArgumentStreamer,
    KeyReady,
    ObjectDone,
    StringChars,
    ValueComplete,
)
from quickapp.common.parameter_stage_format import (
    extract_parameters_config_map,
    format_parameter_value,
    parameter_name_markdown,
    parameter_value_prefix,
    parameter_value_suffix,
    streaming_fence_close,
    streaming_fence_open,
)
from quickapp.config.tools.base import BaseTool
from quickapp.config.tools.display.paramenter import FormattedParameterConfig


class ArgumentStreamMode(str, Enum):
    CONFIG_MAP = "config_map"
    JSON_OBJECT = "json_object"


@dataclass(frozen=True)
class ArgumentStreamPresentation:
    mode: ArgumentStreamMode
    parameters_config_map: dict[str, FormattedParameterConfig] = field(default_factory=dict)

    @staticmethod
    def from_tool_config(
        tool_config: BaseTool | None,
        mode: ArgumentStreamMode,
    ) -> ArgumentStreamPresentation:
        return ArgumentStreamPresentation(
            mode=mode,
            parameters_config_map=extract_parameters_config_map(tool_config),
        )


AppendContent = Callable[[str], None]


class StreamingArgumentPresenter:
    """Feed argument JSON chunks into a stage using a fixed presentation mode."""

    __slots__ = (
        "_append",
        "_presentation",
        "_streamer",
        "_header_written",
        "_active_key",
        "_skip_key",
        "_string_open",
        "_fence_open",
        "_json_first_key",
        "_json_string_open",
        "_streamed_parameter_names",
        "request_body_streamed",
        "finished",
    )

    def __init__(
        self,
        append_content: AppendContent,
        presentation: ArgumentStreamPresentation,
    ) -> None:
        self._append = append_content
        self._presentation = presentation
        self._streamer = JsonObjectArgumentStreamer()
        self._header_written = False
        self._active_key: str | None = None
        self._skip_key = False
        self._string_open = False
        self._fence_open = False
        self._json_first_key = True
        self._json_string_open = False
        self._streamed_parameter_names: set[str] = set()
        self.request_body_streamed = False
        self.finished = False

    @property
    def streamed_parameter_names(self) -> frozenset[str]:
        return frozenset(self._streamed_parameter_names)

    def feed(self, chunk: str) -> None:
        if self.finished or not chunk:
            return
        for event in self._streamer.feed(chunk):
            self._apply_event(event)

    def finish(self) -> None:
        """Close any open fences if the stream ended mid-value."""
        if self.finished:
            return
        if self._presentation.mode == ArgumentStreamMode.CONFIG_MAP:
            if self._fence_open:
                self._append(streaming_fence_close())
                self._append("\n\r")
                self._fence_open = False
                self.request_body_streamed = True
        elif self._presentation.mode == ArgumentStreamMode.JSON_OBJECT:
            if self._header_written:
                if self._json_string_open:
                    self._append('"')
                    self._json_string_open = False
                self._append("\n}\n```\n\n")
                self.request_body_streamed = True
        self.finished = True

    def _apply_event(self, event: ArgumentStreamEvent) -> None:
        if isinstance(event, KeyReady):
            self._on_key(event.key)
        elif isinstance(event, StringChars):
            self._on_string_chars(event.key, event.text)
        elif isinstance(event, ValueComplete):
            self._on_value_complete(event.key, event.value)
        elif isinstance(event, ObjectDone):
            self._on_object_done()

    def _on_key(self, key: str) -> None:
        self._active_key = key
        self._string_open = False
        self._fence_open = False
        if self._presentation.mode == ArgumentStreamMode.CONFIG_MAP:
            cfg = self._presentation.parameters_config_map.get(key)
            self._skip_key = bool(cfg and cfg.ignore)
        else:
            self._skip_key = False

    def _on_string_chars(self, key: str, text: str) -> None:
        if self._skip_key:
            return
        if self._presentation.mode == ArgumentStreamMode.CONFIG_MAP:
            self._config_map_string_chars(key, text)
        else:
            self._json_object_string_chars(key, text)

    def _on_value_complete(self, key: str, value: Any) -> None:
        if self._presentation.mode == ArgumentStreamMode.CONFIG_MAP:
            self._config_map_value_complete(key, value)
        else:
            self._json_object_value_complete(key, value)
        self._active_key = None
        self._skip_key = False
        self._string_open = False

    def _on_object_done(self) -> None:
        if self._presentation.mode == ArgumentStreamMode.JSON_OBJECT:
            if self._header_written:
                self._append("\n}\n```\n\n")
            # Empty `{}` matches MCP (no Request section); still skip static dump.
            self.request_body_streamed = True
        else:
            # Match static config_map dump which always emits the Request header.
            self._ensure_config_map_header()
            self.request_body_streamed = True
        self.finished = True

    # --- config_map ---------------------------------------------------------

    def _ensure_config_map_header(self) -> None:
        if not self._header_written:
            self._append("> #### Request:\n\r")
            self._header_written = True
            self.request_body_streamed = True

    def _config_map_string_chars(self, key: str, text: str) -> None:
        cfg = self._presentation.parameters_config_map.get(key)
        if cfg and cfg.replaced_value_info is not None:
            # Wait for ValueComplete to emit the replacement once.
            return
        if not self._string_open:
            self._ensure_config_map_header()
            if cfg:
                self._append(parameter_name_markdown(key, cfg))
                self._append(parameter_value_prefix(cfg))
                if cfg.format is not None:
                    self._append("\n")
                    self._append(streaming_fence_open(cfg.format))
                    self._fence_open = True
            else:
                self._append(f"***{key}:*** ")
            self._string_open = True
            self._streamed_parameter_names.add(key)
        self._append(text)

    def _config_map_value_complete(self, key: str, value: Any) -> None:
        cfg = self._presentation.parameters_config_map.get(key)
        if cfg and cfg.ignore:
            return

        if self._string_open:
            # Close streamed string field.
            if self._fence_open:
                self._append(streaming_fence_close())
                self._fence_open = False
                if cfg:
                    self._append(parameter_value_suffix(cfg))
                self._append("\n\r")
            else:
                if cfg:
                    self._append(parameter_value_suffix(cfg))
                self._append("\n\r")
            self._string_open = False
            return

        # Non-string, or string with replaced_value_info (not streamed).
        self._ensure_config_map_header()
        if cfg:
            self._append(parameter_name_markdown(key, cfg))
            self._append(parameter_value_prefix(cfg))
            self._append(format_parameter_value(value, cfg))
            self._append(parameter_value_suffix(cfg))
            self._append("\n\r")
        else:
            self._append(f"***{key}:*** {value}\n\r")
        self._streamed_parameter_names.add(key)

    # --- json_object --------------------------------------------------------

    def _ensure_json_header(self) -> None:
        if not self._header_written:
            self._append("> ##### Request:\n```json\n{\n")
            self._header_written = True
            self.request_body_streamed = True

    def _json_object_string_chars(self, key: str, text: str) -> None:
        if not self._json_string_open:
            self._ensure_json_header()
            if not self._json_first_key:
                self._append(",\n")
            self._json_first_key = False
            self._append(f'    {json.dumps(key)}: "')
            self._json_string_open = True
            self._streamed_parameter_names.add(key)
        self._append(_json_escape_fragment(text))

    def _json_object_value_complete(self, key: str, value: Any) -> None:
        if self._json_string_open:
            self._append('"')
            self._json_string_open = False
            return

        self._ensure_json_header()
        if not self._json_first_key:
            self._append(",\n")
        self._json_first_key = False
        dumped = json.dumps(value, indent=4, default=str)
        # Indent continuation lines to align under the object body.
        if "\n" in dumped:
            indented = dumped.replace("\n", "\n    ")
            self._append(f"    {json.dumps(key)}: {indented}")
        else:
            self._append(f"    {json.dumps(key)}: {dumped}")
        self._streamed_parameter_names.add(key)


def _json_escape_fragment(text: str) -> str:
    """Escape text for inclusion inside an already-open JSON string literal."""
    # json.dumps adds surrounding quotes; strip them.
    return json.dumps(text)[1:-1]


def build_presenter(
    stage: Stage,
    presentation: ArgumentStreamPresentation,
) -> StreamingArgumentPresenter:
    return StreamingArgumentPresenter(stage.append_content, presentation)
